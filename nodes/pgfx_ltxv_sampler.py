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

def _get_video_noise_mask(latent, video_samples):
    NestedTensor = _nested_cls()
    noise_mask = latent.get("noise_mask", None)
    if isinstance(noise_mask, NestedTensor):
        return noise_mask.tensors[0]
    if noise_mask is not None:
        if noise_mask.ndim == 5 and noise_mask.shape[1] == 1:
            return noise_mask.clone()
    return torch.ones(
        (video_samples.shape[0], 1, video_samples.shape[2], video_samples.shape[3], video_samples.shape[4]),
        dtype=torch.float32,
        device=video_samples.device,
    )

def _limit_latent_frames(latent, max_frames):
    if max_frames is None or max_frames <= 0:
        return latent
    samples = latent["samples"]
    frame_count = samples.shape[2] if not isinstance(samples, (_nested_cls())) else samples.tensors[0].shape[2]
    if frame_count <= max_frames:
        return latent
    indices = torch.linspace(0, frame_count - 1, max_frames).round().long().unique()
    selected = latent.copy()
    if _is_nested_latent(selected):
        NestedTensor = _nested_cls()
        selected["samples"] = NestedTensor(tuple(t.index_select(2, indices.to(t.device)) for t in samples.tensors))
    else:
        selected["samples"] = samples.index_select(2, indices.to(samples.device))
    mask = selected.get("noise_mask", None)
    if mask is not None:
        if isinstance(mask, (_nested_cls())):
             NestedTensor = _nested_cls()
             selected["noise_mask"] = NestedTensor(tuple(t.index_select(2, indices.to(t.device)) for t in mask.tensors))
        else:
             selected["noise_mask"] = mask.index_select(2, indices.to(mask.device))
    return selected

def _select_latent_frames(latent, start_index, end_index):
    selected = latent.copy()
    samples = selected["samples"]
    def slice_tensor(t, s, e):
        sl = [slice(None)] * t.ndim
        sl[2] = slice(s, e)
        return t[tuple(sl)]
    frames = samples.shape[2] if not isinstance(samples, (_nested_cls())) else samples.tensors[0].shape[2]
    start_idx = frames + start_index if start_index < 0 else start_index
    end_idx = frames + end_index if end_index < 0 else end_index
    start_idx = max(0, min(start_idx, frames - 1))
    end_idx = max(0, min(end_idx, frames - 1))
    if start_idx > end_idx: start_idx = end_idx
    if _is_nested_latent(selected):
        NestedTensor = _nested_cls()
        selected["samples"] = NestedTensor(tuple(slice_tensor(t, start_idx, end_idx + 1) for t in samples.tensors))
    else:
        selected["samples"] = slice_tensor(samples, start_idx, end_idx + 1)
    noise_mask = selected.get("noise_mask", None)
    if noise_mask is not None:
        if isinstance(noise_mask, (_nested_cls())):
             NestedTensor = _nested_cls()
             selected["noise_mask"] = NestedTensor(tuple(slice_tensor(t, start_idx, end_idx + 1) for t in noise_mask.tensors))
        else:
             selected["noise_mask"] = slice_tensor(noise_mask, start_idx, end_idx + 1)
    return selected

def _sync_to_device(obj, device):
    if isinstance(obj, torch.Tensor):
        return obj.to(device=device)
    if isinstance(obj, dict):
        return {k: _sync_to_device(v, device) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sync_to_device(x, device) for x in obj]
    return obj

def _sanitize_conditioning(cond, guider, target_device=None):
    import torch
    import comfy.model_management
    device = target_device if target_device is not None else comfy.model_management.get_torch_device()
    m = guider.model_patcher.model
    dtype = m.get_dtype_inference()
    if cond is None: return []
    if not isinstance(cond, list):
        cond = list(cond) if isinstance(cond, tuple) else [cond]
    sanitized = []
    for item in cond:
        if isinstance(item, (list, tuple)) and len(item) >= 2 and not isinstance(item, dict):
            t = item[0]
            d = item[1]
            if hasattr(t, "to"): t = t.to(device=device, dtype=dtype)
            d = _sync_to_device(d, device)
            sanitized.append([t, d])
        elif isinstance(item, dict):
            item = _sync_to_device(item, device)
            ctx = item.get("context", item.get("cross_attn", None))
            if ctx is None:
                tensors = [(v.numel(), v) for v in item.values() if hasattr(v, "shape") and v.ndim >= 2]
                if tensors: ctx = sorted(tensors, key=lambda x: x[0], reverse=True)[0][1]
            if ctx is None:
                ctx = torch.zeros((1, 1, 5120), device=device, dtype=dtype)
            else:
                ctx = ctx.to(device=device, dtype=dtype)
            if ctx.ndim == 2: ctx = ctx.unsqueeze(0)
            elif ctx.ndim == 1: ctx = ctx.unsqueeze(0).unsqueeze(0)
            sanitized.append([ctx, item])
    return sanitized

def _get_raw_conds_from_guider(guider):
    if not hasattr(guider, "raw_conds"):
        pos_raw = guider.original_conds.get("positive", [])
        neg_raw = guider.original_conds.get("negative", [])
        def safe_copy_cond(c_list):
            res = []
            for c in c_list:
                if isinstance(c, (list, tuple)) and not isinstance(c, dict):
                     res.append([c[0], c[1].copy()])
                elif isinstance(c, dict):
                     res.append(c.copy())
                else:
                     res.append(c)
            return res
        guider.raw_conds = (safe_copy_cond(pos_raw), safe_copy_cond(neg_raw))
    return guider.raw_conds

def _append_guide_attention_entry(positive, negative, pre_filter_count, latent_shape, strength=1.0, attention_mask=None):
    import node_helpers
    new_entry = {
        "pre_filter_count": int(pre_filter_count),
        "strength": strength,
        "pixel_mask": attention_mask.unsqueeze(0).unsqueeze(0) if attention_mask is not None else None,
        "latent_shape": latent_shape,
    }
    results = []
    for cond in (positive, negative):
        existing = []
        for t in cond:
            found = t[1].get("guide_attention_entries", None)
            if found is not None:
                existing = found; break
        entries = [*existing, new_entry]
        results.append(node_helpers.conditioning_set_values(cond, {"guide_attention_entries": entries}))
    return results[0], results[1]

def _split_video_latent(latent):
    NestedTensor = _nested_cls()
    video_latent = latent.copy()
    video_latent["samples"] = latent["samples"].tensors[0]
    mask = latent.get("noise_mask", None)
    if isinstance(mask, NestedTensor):
        video_latent["noise_mask"] = mask.tensors[0]
    elif mask is not None:
        video_latent["noise_mask"] = mask
    return video_latent

def _merge_video_latent(video_latent, original_latent):
    if not _is_nested_latent(original_latent):
        return video_latent
    NestedTensor = _nested_cls()
    orig_tensors = original_latent["samples"].tensors
    video_samples = video_latent["samples"]
    audio_samples = orig_tensors[1]
    if video_samples.shape[2] > orig_tensors[0].shape[2]:
        diff = video_samples.shape[2] - orig_tensors[0].shape[2]
        ratio = audio_samples.shape[2] / orig_tensors[0].shape[2]
        pad_len = int(diff * ratio)
        if pad_len > 0:
            padding = torch.zeros((audio_samples.shape[0], audio_samples.shape[1], pad_len, audio_samples.shape[3]), device=audio_samples.device, dtype=audio_samples.dtype)
            audio_samples = torch.cat([audio_samples, padding], dim=2)
    merged = video_latent.copy()
    merged["samples"] = NestedTensor((video_samples, audio_samples))
    original_mask = original_latent.get("noise_mask", None)
    video_mask = video_latent.get("noise_mask", None)
    if isinstance(original_mask, NestedTensor):
        orig_masks = original_mask.tensors
        audio_mask = orig_masks[1]
        if audio_samples.shape[2] > orig_masks[1].shape[2]:
             diff = audio_samples.shape[2] - orig_masks[1].shape[2]
             padding = torch.zeros((audio_mask.shape[0], 1, diff, 1), device=audio_mask.device, dtype=audio_mask.dtype)
             audio_mask = torch.cat([audio_mask, padding], dim=2)
        merged["noise_mask"] = NestedTensor((video_mask, audio_mask))
    elif video_mask is not None:
        merged["noise_mask"] = video_mask
    return merged

def _crop_guides(positive, negative, latent):
    from comfy_extras.nodes_lt import LTXVCropGuides, get_keyframe_idxs
    if not _is_nested_latent(latent):
        return LTXVCropGuides.execute(positive=positive, negative=negative, latent=latent)
    _, num_keyframes = get_keyframe_idxs(positive)
    if num_keyframes == 0:
        return positive, negative, latent
    video_latent = _split_video_latent(latent)
    res = LTXVCropGuides.execute(positive=positive, negative=negative, latent=video_latent)
    return res[0], res[1], _merge_video_latent(res[2], latent)

def _add_image_guide(positive, negative, vae, latent, image, frame_idx, strength, guider):
    from comfy_extras.nodes_lt import LTXVAddGuide
    v_latent = _split_video_latent(latent) if _is_nested_latent(latent) else latent
    device = v_latent["samples"].device
    san_pos = _sanitize_conditioning(positive, guider, device)
    san_neg = _sanitize_conditioning(negative, guider, device)
    image = image.to(device)
    res = LTXVAddGuide.execute(positive=san_pos, negative=san_neg, vae=vae, latent=v_latent, image=image, frame_idx=frame_idx, strength=strength)
    if _is_nested_latent(latent):
        return res[0], res[1], _merge_video_latent(res[2], latent)
    return res[0], res[1], res[2]

def _add_latent_guide(positive, negative, vae, latent, guiding_latent, latent_idx, strength, guider):
    from comfy_extras import nodes_lt
    NestedTensor = _nested_cls()
    v_latent = _split_video_latent(latent) if _is_nested_latent(latent) else latent
    g_latent = _split_video_latent(guiding_latent) if _is_nested_latent(guiding_latent) else guiding_latent
    device = v_latent["samples"].device
    
    san_pos = _sanitize_conditioning(positive, guider, device)
    san_neg = _sanitize_conditioning(negative, guider, device)
    
    g_samples = g_latent["samples"].to(device)
    v_samples = v_latent["samples"]
    
    # RESOLUTION MATCHING FIX
    if g_samples.shape[3] != v_samples.shape[3] or g_samples.shape[4] != v_samples.shape[4]:
        import comfy.utils
        g_samples = comfy.utils.common_upscale(g_samples, v_samples.shape[4], v_samples.shape[3], "nearest-exact", "disabled")
        g_latent["samples"] = g_samples
        if "noise_mask" in g_latent and g_latent["noise_mask"] is not None:
             m = g_latent["noise_mask"].to(device)
             m = comfy.utils.common_upscale(m.flatten(0, 1), v_samples.shape[4], v_samples.shape[3], "nearest-exact", "disabled")
             g_latent["noise_mask"] = m.reshape(g_samples.shape[0], 1, g_samples.shape[2], v_samples.shape[3], v_samples.shape[4])

    noise_mask = _get_video_noise_mask(v_latent, v_samples)
    scale_factors = vae.downscale_index_formula
    frame_idx = latent_idx * scale_factors[0] if latent_idx <= 0 else 1 + (latent_idx - 1) * scale_factors[0]
    
    pre_filter_count = g_samples.shape[2] * g_samples.shape[3] * g_samples.shape[4]
    guide_latent_shape = list(g_samples.shape[2:])

    res = nodes_lt.LTXVAddGuide.append_keyframe(
        positive=san_pos, negative=san_neg, frame_idx=frame_idx,
        latent_image=v_samples, noise_mask=noise_mask,
        guiding_latent=g_samples, strength=strength, scale_factors=scale_factors
    )
    out_pos, out_neg, out_v_samples, out_v_mask = res
    out_pos, out_neg = _append_guide_attention_entry(out_pos, out_neg, pre_filter_count, guide_latent_shape, strength=strength)
    output = {"samples": out_v_samples, "noise_mask": out_v_mask}
    if _is_nested_latent(latent):
        output = _merge_video_latent(output, latent)
    return out_pos, out_neg, output

class PGFX_LTXVInContextSampler:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vae": ("VAE", {"tooltip": "The VAE to use."}),
                "guider": ("GUIDER", {"tooltip": "The guider to use."}),
                "sampler": ("SAMPLER", {"tooltip": "The sampler to use."}),
                "sigmas": ("SIGMAS", {"tooltip": "The sigmas to use."}),
                "noise": ("NOISE", {"tooltip": "The noise to use."}),
                "guiding_latents": ("LATENT", {"tooltip": "Guiding latents."}),
            },
            "optional": {
                "optional_cond_images": ("IMAGE", {"tooltip": "Optional keyframe images."}),
                "num_frames": ("INT", {"default": -1, "min": -1, "max": 1000, "step": 1}),
                "optional_cond_indices": ("STRING", {"default": "0"}),
                "guiding_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "advanced": True}),
                "guiding_start_step": ("INT", {"default": 0, "min": 0, "max": 1000, "advanced": True}),
                "guiding_end_step": ("INT", {"default": 1000, "min": 0, "max": 1000, "advanced": True}),
                "max_guiding_latent_frames": ("INT", {"default": 0, "min": 0, "max": 1000, "advanced": True}),
                "cond_image_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "advanced": True}),
            },
        }

    RETURN_TYPES = ("LATENT", "CONDITIONING", "CONDITIONING")
    RETURN_NAMES = ("denoised_video", "positive", "negative")
    FUNCTION = "sample"
    CATEGORY = PGFX_LTXV_CATEGORY

    def sample(self, vae, guider, sampler, sigmas, noise, guiding_latents, optional_cond_images=None, optional_cond_indices=None, num_frames=-1, cond_image_strength=1.0, guiding_strength=1.0, guiding_start_step=0, guiding_end_step=1000, max_guiding_latent_frames=0):
        from comfy_extras.nodes_custom_sampler import SamplerCustomAdvanced, SplitSigmas
        from comfy_extras.nodes_lt import EmptyLTXVLatentVideo
        import comfy.model_management
        
        NestedTensor = _nested_cls()
        guider = copy.copy(guider)
        if optional_cond_images is None: optional_cond_indices = None
        if optional_cond_indices is not None and optional_cond_images is not None:
            optional_cond_indices = [int(i) for i in optional_cond_indices.split(",")]
            assert len(optional_cond_indices) == len(optional_cond_images)

        pos_raw, neg_raw = _get_raw_conds_from_guider(guider)
        device = comfy.model_management.get_torch_device()
        positive = _sanitize_conditioning(pos_raw, guider, device)
        negative = _sanitize_conditioning(neg_raw, guider, device)
        
        time_scale_factor, width_scale_factor, height_scale_factor = vae.downscale_index_formula
        samples = guiding_latents["samples"]
        if not isinstance(samples, NestedTensor):
             l_f, l_h, l_w = samples.shape[2], samples.shape[3], samples.shape[4]
        else:
             l_f, l_h, l_w = samples.tensors[0].shape[2], samples.tensors[0].shape[3], samples.tensors[0].shape[4]
        if num_frames != -1: l_f = (num_frames - 1) // time_scale_factor + 1
        
        new_latents = EmptyLTXVLatentVideo.execute(
            width=l_w * width_scale_factor, height=l_h * height_scale_factor,
            length=(l_f - 1) * time_scale_factor + 1, batch_size=1,
        )[0]
        new_latents["samples"] = new_latents["samples"].to(device)
        
        if guider.model_patcher.model.diffusion_model.__class__.__name__ == "LTXAVModel":
            audio_latent = torch.zeros_like(samples.tensors[1]) if isinstance(samples, NestedTensor) else torch.zeros((1, 128, l_f, 1), device=device)
            new_latents["samples"] = NestedTensor((new_latents["samples"], audio_latent.to(device)))

        high_sigmas, rest_sigmas = SplitSigmas().get_sigmas(sigmas, guiding_start_step)
        middle_sigmas, low_sigmas = SplitSigmas().get_sigmas(rest_sigmas, guiding_end_step - guiding_start_step)

        if len(high_sigmas) > 1:
            print("### [PGFX] Denoising [Pass 1]", file=sys.stderr)
            guider.set_conds(positive, negative)
            (_, new_latents) = SamplerCustomAdvanced().sample(noise=noise, guider=guider, sampler=sampler, sigmas=high_sigmas, latent_image=new_latents)

        if optional_cond_indices is not None and 0 in optional_cond_indices:
            guiding_latents = _select_latent_frames(guiding_latents, 1, -1)
            skip_one_guiding_latent = True
        else: skip_one_guiding_latent = False
        guiding_latents = _limit_latent_frames(guiding_latents, max_guiding_latent_frames)

        print("### [PGFX] Adding latent guides", file=sys.stderr)
        positive, negative, new_latents = _add_latent_guide(positive, negative, vae, new_latents, guiding_latents, 1 if skip_one_guiding_latent else 0, guiding_strength, guider)

        if optional_cond_images is not None:
            print("### [PGFX] Adding keyframes", file=sys.stderr)
            for cond_image, cond_idx in zip(optional_cond_images, optional_cond_indices):
                if cond_idx % 8 == 1: continue
                positive, negative, new_latents = _add_image_guide(positive, negative, vae, new_latents, cond_image.unsqueeze(0), cond_idx, cond_image_strength, guider)

        guider.set_conds(positive, negative)
        print("### [PGFX] Denoising [Pass 2]", file=sys.stderr)
        (_, denoised_output_latents) = SamplerCustomAdvanced().sample(noise=noise, guider=guider, sampler=sampler, sigmas=middle_sigmas, latent_image=new_latents)

        positive, negative, denoised_output_latents = _crop_guides(positive, negative, denoised_output_latents)

        if len(low_sigmas) > 1:
            guider.set_conds(positive, negative)
            print("### [PGFX] Denoising [Pass 3]", file=sys.stderr)
            (_, denoised_output_latents) = SamplerCustomAdvanced().sample(noise=noise, guider=guider, sampler=sampler, sigmas=low_sigmas, latent_image=denoised_output_latents)
            positive, negative, denoised_output_latents = _crop_guides(positive, negative, denoised_output_latents)

        return (denoised_output_latents, positive, negative)

NODE_CLASS_MAPPINGS = {"PGFX_LTXVInContextSampler": PGFX_LTXVInContextSampler}
NODE_DISPLAY_NAME_MAPPINGS = {"PGFX_LTXVInContextSampler": "PGFX LTXV In Context Sampler"}
