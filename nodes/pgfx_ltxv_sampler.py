import copy
import sys

import torch


PGFX_LTXV_CATEGORY = "☠️PGFX🏴‍☠️ /LTXV"


def _nested_cls():
    from comfy.nested_tensor import NestedTensor

    return NestedTensor


def _is_nested_latent(latent):
    NestedTensor = _nested_cls()
    return isinstance(latent.get("samples", None), NestedTensor)


def _index_dim_2(tensor, indices):
    NestedTensor = _nested_cls()
    if isinstance(tensor, NestedTensor):
        return NestedTensor(_index_dim_2(t, indices) for t in tensor.tensors)
    return tensor.index_select(2, indices.to(device=tensor.device))


def _slice_dim_2(tensor, start, end):
    NestedTensor = _nested_cls()
    if isinstance(tensor, NestedTensor):
        return NestedTensor(_slice_dim_2(t, start, end) for t in tensor.tensors)
    sl = [slice(None)] * tensor.ndim
    sl[2] = slice(start, end)
    return tensor[tuple(sl)]


def _select_latent_frames(latent, start_index, end_index):
    selected = latent.copy()
    samples = selected["samples"]
    frames = samples.shape[2]
    start_idx = frames + start_index if start_index < 0 else start_index
    end_idx = frames + end_index if end_index < 0 else end_index
    start_idx = max(0, min(start_idx, frames - 1))
    end_idx = max(0, min(end_idx, frames - 1))
    if start_idx > end_idx:
        start_idx = end_idx

    selected["samples"] = _slice_dim_2(samples, start_idx, end_idx + 1)
    noise_mask = selected.get("noise_mask", None)
    if noise_mask is not None:
        selected["noise_mask"] = _slice_dim_2(noise_mask, start_idx, end_idx + 1)
    return selected


def _limit_latent_frames(latent, max_frames):
    if max_frames is None or max_frames <= 0:
        return latent

    frame_count = latent["samples"].shape[2]
    if frame_count <= max_frames:
        return latent

    indices = torch.linspace(0, frame_count - 1, max_frames).round().long().unique()
    limited = latent.copy()
    limited["samples"] = _index_dim_2(limited["samples"], indices)
    noise_mask = limited.get("noise_mask", None)
    if noise_mask is not None:
        limited["noise_mask"] = _index_dim_2(noise_mask, indices)
    print(
        f"### [PGFX_LTXVInContextSampler] Limited guiding latent frames from {frame_count} to {limited['samples'].shape[2]}",
        file=sys.stderr,
    )
    return limited


def _split_video_latent(latent):
    NestedTensor = _nested_cls()
    video_latent = latent.copy()
    video_latent["samples"] = latent["samples"].tensors[0]
    noise_mask = latent.get("noise_mask", None)
    if isinstance(noise_mask, NestedTensor):
        video_latent["noise_mask"] = noise_mask.tensors[0]
    elif noise_mask is not None:
        video_latent["noise_mask"] = noise_mask
    return video_latent


def _merge_video_latent(video_latent, original_latent):
    if not _is_nested_latent(original_latent):
        return video_latent

    NestedTensor = _nested_cls()
    tensors = original_latent["samples"].tensors
    merged = video_latent.copy()
    merged["samples"] = NestedTensor((video_latent["samples"], *tensors[1:]))

    original_mask = original_latent.get("noise_mask", None)
    video_mask = video_latent.get("noise_mask", None)
    if isinstance(original_mask, NestedTensor):
        merged["noise_mask"] = NestedTensor((video_mask, *original_mask.tensors[1:]))
    elif video_mask is not None:
        merged["noise_mask"] = video_mask
    else:
        merged.pop("noise_mask", None)
    return merged


def _add_image_guide(positive, negative, vae, latent, image, frame_idx, strength):
    from comfy_extras.nodes_lt import LTXVAddGuide

    if not _is_nested_latent(latent):
        return LTXVAddGuide.execute(
            positive=positive,
            negative=negative,
            vae=vae,
            latent=latent,
            image=image,
            frame_idx=frame_idx,
            strength=strength,
        )

    video_latent = _split_video_latent(latent)
    positive, negative, video_latent = LTXVAddGuide.execute(
        positive=positive,
        negative=negative,
        vae=vae,
        latent=video_latent,
        image=image,
        frame_idx=frame_idx,
        strength=strength,
    )
    return positive, negative, _merge_video_latent(video_latent, latent)


def _crop_guides(positive, negative, latent):
    from comfy_extras.nodes_lt import LTXVCropGuides, get_keyframe_idxs

    if not _is_nested_latent(latent):
        return LTXVCropGuides.execute(
            positive=positive,
            negative=negative,
            latent=latent,
        )

    _, num_keyframes = get_keyframe_idxs(positive)
    if num_keyframes == 0:
        return positive, negative, latent

    video_latent = _split_video_latent(latent)
    positive, negative, video_latent = LTXVCropGuides.execute(
        positive=positive,
        negative=negative,
        latent=video_latent,
    )
    return positive, negative, _merge_video_latent(video_latent, latent)


def _get_raw_conds_from_guider(guider):
    if not hasattr(guider, "raw_conds"):
        if "negative" not in guider.original_conds:
            raise ValueError(
                "Guider does not have negative conds, cannot use it as a guider."
            )
        raw_pos = guider.original_conds["positive"]
        positive = [[raw_pos[0]["cross_attn"], copy.deepcopy(raw_pos[0])]]
        raw_neg = guider.original_conds["negative"]
        negative = [[raw_neg[0]["cross_attn"], copy.deepcopy(raw_neg[0])]]
        guider.raw_conds = (positive, negative)
    return guider.raw_conds


def _get_video_noise_mask(latent, video_samples):
    NestedTensor = _nested_cls()
    noise_mask = latent.get("noise_mask", None)
    if isinstance(noise_mask, NestedTensor):
        return noise_mask.tensors[0]
    if noise_mask is not None:
        return noise_mask.clone()
    return torch.ones(
        (video_samples.shape[0], 1, video_samples.shape[2], 1, 1),
        dtype=torch.float32,
        device=video_samples.device,
    )


def _dilate_video_latent(latent, horizontal_scale, vertical_scale):
    if horizontal_scale == 1 and vertical_scale == 1:
        return latent

    samples = latent["samples"]
    mask = latent.get("noise_mask", None)
    dilated_shape = samples.shape[:3] + (
        samples.shape[3] * vertical_scale,
        samples.shape[4] * horizontal_scale,
    )
    dilated_samples = torch.zeros(
        dilated_shape,
        device=samples.device,
        dtype=samples.dtype,
        requires_grad=False,
    )
    dilated_samples[..., ::vertical_scale, ::horizontal_scale] = samples

    dilated_mask_shape = (
        dilated_samples.shape[0],
        1,
        dilated_samples.shape[2],
        dilated_samples.shape[3],
        dilated_samples.shape[4],
    )
    dilated_mask = torch.full(
        dilated_mask_shape,
        -1.0,
        device=samples.device,
        dtype=samples.dtype,
        requires_grad=False,
    )
    dilated_mask[..., ::vertical_scale, ::horizontal_scale] = (
        mask if mask is not None else 1.0
    )
    return {"samples": dilated_samples, "noise_mask": dilated_mask}


def _append_guide_attention_entry(conditioning, pre_filter_count, latent_shape):
    import node_helpers

    entries = []
    for item in conditioning:
        found = item[1].get("guide_attention_entries", None)
        if found is not None:
            entries = list(found)
            break
    entries.append(
        {
            "pre_filter_count": pre_filter_count,
            "strength": 1.0,
            "pixel_mask": None,
            "latent_shape": latent_shape,
        }
    )
    return node_helpers.conditioning_set_values(
        conditioning, {"guide_attention_entries": entries}
    )


def _add_latent_guide(positive, negative, vae, latent, guiding_latent, latent_idx, strength):
    from comfy_extras import nodes_lt

    NestedTensor = _nested_cls()
    latent_samples = latent["samples"]
    audio_samples = None
    if isinstance(latent_samples, NestedTensor):
        latent_tensors = latent_samples.tensors
        latent_samples = latent_tensors[0]
        if len(latent_tensors) > 1:
            audio_samples = latent_tensors[1]

    noise_mask = _get_video_noise_mask(latent, latent_samples)

    if isinstance(guiding_latent["samples"], NestedTensor):
        guide_latent = guiding_latent.copy()
        guide_latent["samples"] = guiding_latent["samples"].tensors[0]
        guide_mask = guiding_latent.get("noise_mask", None)
        if isinstance(guide_mask, NestedTensor):
            guide_latent["noise_mask"] = guide_mask.tensors[0]
    else:
        guide_latent = guiding_latent

    guide = guide_latent["samples"]
    guide_orig_shape = list(guide.shape[2:])
    if latent_samples.shape[4] % guide.shape[4] != 0 or latent_samples.shape[3] % guide.shape[3] != 0:
        raise ValueError(
            "The ratio of the height and width of the latents and guiding_latents must be an integer"
        )

    guide_latent = _dilate_video_latent(
        guide_latent,
        horizontal_scale=latent_samples.shape[4] // guide.shape[4],
        vertical_scale=latent_samples.shape[3] // guide.shape[3],
    )
    guide = guide_latent["samples"]
    guide_mask = guide_latent.get("noise_mask", None)
    iclora_tokens_added = guide.shape[2] * guide.shape[3] * guide.shape[4]

    scale_factors = vae.downscale_index_formula
    frame_idx = (
        latent_idx * scale_factors[0]
        if latent_idx <= 0
        else 1 + (latent_idx - 1) * scale_factors[0]
    )

    positive, negative, latent_samples, noise_mask = nodes_lt.LTXVAddGuide.append_keyframe(
        positive=positive,
        negative=negative,
        frame_idx=frame_idx,
        latent_image=latent_samples,
        noise_mask=noise_mask,
        guiding_latent=guide,
        strength=strength,
        scale_factors=scale_factors,
        guide_mask=guide_mask,
    )

    positive = _append_guide_attention_entry(
        positive, iclora_tokens_added, guide_orig_shape
    )
    negative = _append_guide_attention_entry(
        negative, iclora_tokens_added, guide_orig_shape
    )

    output = {"samples": latent_samples, "noise_mask": noise_mask}
    if audio_samples is not None:
        output["samples"] = NestedTensor((latent_samples, audio_samples))
    return positive, negative, output


class PGFX_LTXVInContextSampler:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vae": ("VAE", {"tooltip": "The VAE to use."}),
                "guider": (
                    "GUIDER",
                    {"tooltip": "The guider to use, must be a STGGuiderAdvanced."},
                ),
                "sampler": ("SAMPLER", {"tooltip": "The sampler to use."}),
                "sigmas": ("SIGMAS", {"tooltip": "The sigmas to use."}),
                "noise": ("NOISE", {"tooltip": "The noise to use for sampling."}),
                "guiding_latents": (
                    "LATENT",
                    {"tooltip": "Guiding latents, typically with an IC-LoRA."},
                ),
            },
            "optional": {
                "optional_cond_images": (
                    "IMAGE",
                    {"tooltip": "Optional keyframe images for additional conditioning."},
                ),
                "num_frames": (
                    "INT",
                    {
                        "default": -1,
                        "min": -1,
                        "max": 1000,
                        "step": 1,
                        "tooltip": "If -1, derive frame count from guiding_latents.",
                    },
                ),
                "optional_cond_indices": (
                    "STRING",
                    {
                        "default": "0",
                        "tooltip": "Comma-separated frame indices for optional conditioning images.",
                    },
                ),
                "guiding_strength": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.0, "max": 1.0, "advanced": True},
                ),
                "guiding_start_step": (
                    "INT",
                    {"default": 0, "min": 0, "max": 1000, "advanced": True},
                ),
                "guiding_end_step": (
                    "INT",
                    {
                        "default": 1,
                        "min": 0,
                        "max": 1000,
                        "advanced": True,
                        "tooltip": "End step for expensive full guide conditioning. Lower values are faster.",
                    },
                ),
                "max_guiding_latent_frames": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 1000,
                        "advanced": True,
                        "tooltip": "0 keeps every guide frame. Lower caps reduce attention cost.",
                    },
                ),
                "cond_image_strength": (
                    "FLOAT",
                    {"default": 1.0, "min": 0.0, "max": 1.0, "advanced": True},
                ),
            },
        }

    RETURN_TYPES = ("LATENT", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("denoised_video", "positive", "negative")
    FUNCTION = "sample"
    CATEGORY = PGFX_LTXV_CATEGORY

    def sample(
        self,
        vae,
        guider,
        sampler,
        sigmas,
        noise,
        guiding_latents,
        optional_cond_images=None,
        optional_cond_indices=None,
        num_frames=-1,
        cond_image_strength=1.0,
        guiding_strength=1.0,
        guiding_start_step=0,
        guiding_end_step=1,
        max_guiding_latent_frames=0,
    ):
        from comfy_extras.nodes_custom_sampler import SamplerCustomAdvanced, SplitSigmas
        from comfy_extras.nodes_lt import EmptyLTXVLatentVideo

        NestedTensor = _nested_cls()
        guider = copy.copy(guider)
        guider.original_conds = copy.deepcopy(guider.original_conds)
        if optional_cond_images is None:
            optional_cond_indices = None

        if optional_cond_indices is not None and optional_cond_images is not None:
            optional_cond_indices = optional_cond_indices.split(",")
            optional_cond_indices = [int(i) for i in optional_cond_indices]
            if len(optional_cond_indices) != len(optional_cond_images):
                raise ValueError(
                    "Number of optional cond images must match number of optional cond indices"
                )

        positive, negative = _get_raw_conds_from_guider(guider)
        time_scale_factor, width_scale_factor, height_scale_factor = (
            vae.downscale_index_formula
        )

        _, _, frames, height, width = guiding_latents["samples"].shape
        if num_frames != -1:
            frames = (num_frames - 1) // time_scale_factor + 1

        new_latents = EmptyLTXVLatentVideo.execute(
            width=width * width_scale_factor,
            height=height * height_scale_factor,
            length=(frames - 1) * time_scale_factor + 1,
            batch_size=1,
        )[0]

        if (
            guider.model_patcher.model.diffusion_model.__class__.__name__
            == "LTXAVModel"
        ):
            if not _is_nested_latent(guiding_latents):
                raise ValueError(
                    "PGFX LTXV In Context Sampler is using an LTXAV model, but guiding_latents "
                    "does not contain an audio/video NestedTensor. Connect an AV latent from "
                    "LTXVConcatAVLatent, or use an LTXV video model."
                )
            audio_latent = torch.zeros_like(guiding_latents["samples"].tensors[1])
            new_latents["samples"] = NestedTensor((new_latents["samples"], audio_latent))

        high_sigmas, rest_sigmas = SplitSigmas().get_sigmas(sigmas, guiding_start_step)
        middle_sigmas, low_sigmas = SplitSigmas().get_sigmas(
            rest_sigmas, guiding_end_step - guiding_start_step
        )

        if len(high_sigmas) > 1:
            print(
                "### [PGFX_LTXVInContextSampler] Denoising with keyframes only on sigmas: ",
                high_sigmas,
                file=sys.stderr,
            )
            _, new_latents = SamplerCustomAdvanced().sample(
                noise=noise,
                guider=guider,
                sampler=sampler,
                sigmas=high_sigmas,
                latent_image=new_latents,
            )

        if optional_cond_indices is not None and 0 in optional_cond_indices:
            guiding_latents = _select_latent_frames(guiding_latents, 1, -1)
            skip_one_guiding_latent = True
        else:
            skip_one_guiding_latent = False

        guiding_latents = _limit_latent_frames(
            guiding_latents, max_guiding_latent_frames
        )

        print("### [PGFX_LTXVInContextSampler] Adding conditioning on guiding latents", file=sys.stderr)
        positive, negative, new_latents = _add_latent_guide(
            positive=positive,
            negative=negative,
            vae=vae,
            latent=new_latents,
            guiding_latent=guiding_latents,
            latent_idx=1 if skip_one_guiding_latent else 0,
            strength=guiding_strength,
        )

        if optional_cond_images is not None:
            print(
                f"### [PGFX_LTXVInContextSampler] Adding conditioning on keyframes {optional_cond_indices}",
                file=sys.stderr,
            )
            for cond_image, cond_idx in zip(optional_cond_images, optional_cond_indices):
                if cond_idx % 8 == 1:
                    raise ValueError(
                        f"Conditioning image index {cond_idx} is a multiple of 8 + 1 and guiding latents are used. Please provide other cond image indices"
                    )
                positive, negative, new_latents = _add_image_guide(
                    positive=positive,
                    negative=negative,
                    vae=vae,
                    latent=new_latents,
                    image=cond_image.unsqueeze(0),
                    frame_idx=cond_idx,
                    strength=cond_image_strength,
                )

        guider.set_conds(positive, negative)
        print(
            "### [PGFX_LTXVInContextSampler] Denoising with full conditioning on sigmas: ",
            middle_sigmas,
            file=sys.stderr,
        )
        _, denoised_output_latents = SamplerCustomAdvanced().sample(
            noise=noise,
            guider=guider,
            sampler=sampler,
            sigmas=middle_sigmas,
            latent_image=new_latents,
        )

        positive, negative, denoised_output_latents = _crop_guides(
            positive=positive,
            negative=negative,
            latent=denoised_output_latents,
        )

        if len(low_sigmas) > 1:
            guider.set_conds(positive, negative)
            print(
                "### [PGFX_LTXVInContextSampler] Denoising with keyframes only on sigmas: ",
                low_sigmas,
                file=sys.stderr,
            )
            _, denoised_output_latents = SamplerCustomAdvanced().sample(
                noise=noise,
                guider=guider,
                sampler=sampler,
                sigmas=low_sigmas,
                latent_image=denoised_output_latents,
            )
            positive, negative, denoised_output_latents = _crop_guides(
                positive=positive,
                negative=negative,
                latent=denoised_output_latents,
            )

        return (denoised_output_latents, positive, negative)


NODE_CLASS_MAPPINGS = {
    "PGFX_LTXVInContextSampler": PGFX_LTXVInContextSampler,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_LTXVInContextSampler": "PGFX LTXV In Context Sampler",
}
