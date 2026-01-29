import torch
import torchaudio
import math
import copy
import numpy as np
import inspect
from tqdm import tqdm
import gc
import re
import os # Added for script_directory and path ops
import sys # Added for sys.path if dynamic import is needed later (though aiming for self-contained)

# ComfyUI internal imports
from comfy.utils import common_upscale, ProgressBar
import comfy.model_management as mm
import torch.nn.functional as F
from comfy.model_management import get_torch_device, offload_device
from comfy.samplers import KSAMPLER_SCHEDULERS, KSampler, KSamplerAdvanced
from comfy.ldm.modules.diffusionmodules.openaimodel import Timestep # From nodes_sampler.py internal usage
from comfy.models.motion_module import MotionWrapper # From nodes_sampler.py internal usage
from comfy.sample import get_additional_models # From nodes_sampler.py internal usage
from comfy.samplers import get_sampler # From nodes_sampler.py internal usage
from nodes import MAX_RESOLUTION # Assuming this is needed, if not, can remove later
from contextlib import nullcontext # For torch.autocast context manager

# Local helper function moved from nodes_studio.py
def linear_interpolation_fps(features, input_fps, output_fps, output_len=None):
    if features is None:
        return None
    features = features.transpose(1, 2)
    seq_len = features.shape[2] / float(input_fps)
    if output_len is None:
        output_len = int(seq_len * output_fps)
    output_features = F.interpolate(features, size=output_len, align_corners=True, mode='linear')
    return output_features.transpose(1, 2)

# Global variables
device = get_torch_device()
offload_device = offload_device()
scheduler_list = KSAMPLER_SCHEDULERS # This will be used in INPUT_TYPES for WanVideoMusicVideoSampler

# Placeholder for classes/functions that will be copied and adapted from ComfyUI-WanVideoWrapper
# The goal is to make WanVideoMusicVideoSampler fully self-contained.

# --- REPLICATED UTILITY FUNCTIONS from ComfyUI-WanVideoWrapper/utils.py (Partial, add as needed) ---
# NOTE: This section will be expanded as more dependencies are identified.

# Replicated log function (simplified for direct use)
def log(message, level="INFO"):
    """A simple logging function. Can be expanded if needed."""
    print(f"[{level}] WanVideoMusicVideoSampler: {message}")

# Placeholder for dict_to_device (used in nodes_sampler.py)
def dict_to_device(data, device):
    """Recursively moves tensors in a dictionary to the specified device."""
    if isinstance(data, torch.Tensor):
        return data.to(device)
    if isinstance(data, dict):
        return {k: dict_to_device(v, device) for k, v in data.items()}
    if isinstance(data, list):
        return [dict_to_device(elem, device) for elem in data]
    return data

# Placeholder for apply_lora, fourier_filter, optimized_scale, setup_radial_attention,
# compile_model, tangential_projection, get_raag_guidance, temporal_score_rescaling,
# offload_transformer, init_blockswap. These are complex and will be added only if strictly necessary
# and if their logic can be reasonably contained. Many of these might be related to specific
# model patching or optimization steps that might not be directly inlinable without significant effort.

# --- Placeholder for ComfyUI-WanVideoWrapper/wanvideo/modules/model.py content ---
# (rope_params is a crucial dependency for `rope_functions`)
# Need to fetch the definition of rope_params
# I will define a dummy rope_params for now and fill it later.
def rope_params(dim, heads, ntk_scale=1.0, alpha=1.0, L_test=1.0, k=0):
    # This needs to be the actual implementation from wanvideo/modules/model.py
    # For now, a placeholder that returns a dummy tensor.
    # This will likely cause issues if the model actually uses RoPE and this is not implemented correctly.
    log(f"WARNING: Using placeholder rope_params. Actual implementation from WanVideoWrapper is required for full functionality.", "WARN")
    # A simple dummy to prevent immediate crash, likely incorrect for actual use
    return torch.empty(dim, heads) # Incorrect, needs actual implementation


# --- Placeholder for ComfyUI-WanVideoWrapper/wanvideo/schedulers.py content ---
# (get_scheduler is crucial for `WanVideoSampler`)
# Need to fetch the definition of get_scheduler
# I will define a dummy get_scheduler for now and fill it later.
def get_scheduler(name, steps, start_step, end_step, shift, device, model_dim, denoise_strength, sigmas=None, log_timesteps=True):
    # This needs to be the actual implementation from wanvideo/schedulers.py
    # For now, a placeholder that returns a dummy scheduler and timesteps.
    log(f"WARNING: Using placeholder get_scheduler. Actual implementation from WanVideoWrapper is required for full functionality.", "WARN")
    # A simple dummy for now
    class DummyScheduler:
        def __init__(self, sigmas):
            self.sigmas = sigmas
        def step(self, model_output, timestep, sample, **kwargs):
            return sample # Passthrough for dummy
    dummy_timesteps = torch.linspace(1000, 1, steps)
    if sigmas is None:
        dummy_sigmas = torch.linspace(1.0, 0.0, steps + 1)
    else:
        dummy_sigmas = sigmas
    return DummyScheduler(dummy_sigmas), dummy_timesteps, None, None

# --- Placeholder for custom_linear.py content ---
# (remove_lora_from_module, set_lora_params, _replace_linear)
# Need to fetch these. For now, dummy functions.
def remove_lora_from_module(model):
    log("WARNING: Using dummy remove_lora_from_module. Actual implementation from WanVideoWrapper is required.", "WARN")
    pass

def set_lora_params(model, patches):
    log("WARNING: Using dummy set_lora_params. Actual implementation from WanVideoWrapper is required.", "WARN")
    pass

def _replace_linear(transformer, dtype, sd, compile_args):
    log("WARNING: Using dummy _replace_linear. Actual implementation from WanVideoWrapper is required.", "WARN")
    return transformer

# --- Placeholder for gguf.py content ---
# (set_lora_params_gguf)
def set_lora_params_gguf(transformer, patches):
    log("WARNING: Using dummy set_lora_params_gguf. Actual implementation from WanVideoWrapper is required.", "WARN")
    pass

# --- Placeholder for multitalk.py content ---
# (add_noise)
def add_noise(original_samples, noise, timesteps):
    log("WARNING: Using dummy add_noise. Actual implementation from WanVideoWrapper is required.", "WARN")
    return original_samples # Simple passthrough

# --- Placeholder for enhance_a_video/globals.py content ---
# (set_enhance_weight, set_num_frames)
def set_enhance_weight(weight):
    log("WARNING: Using dummy set_enhance_weight. Actual implementation from WanVideoWrapper is required.", "WARN")
    pass

def set_num_frames(num_frames):
    log("WARNING: Using dummy set_num_frames. Actual implementation from WanVideoWrapper is required.", "WARN")
    pass

# --- Placeholder for nodes_model_loading.py content ---
# (load_weights)
def load_weights(model, sd, weight_dtype=torch.float16, base_dtype=torch.float32, transformer_load_device=None, patcher=None, gguf=False, reader=None, block_swap_args=None, compile_args=None):
    log("WARNING: Using dummy load_weights. Actual implementation from WanVideoWrapper is required.", "WARN")
    # This is a critical function, a dummy here will likely break many things.
    # It attempts to load model weights. For now, pass through.
    if sd is not None and not gguf:
        log("Dummy load_weights is attempting to apply patches from sd to model.", "WARN")
        # Simulate loading by just setting a flag if available
        if hasattr(model, 'patched_linear'):
            model.patched_linear = True
    return model

# --- Placeholder for WanMove/trajectory.py content ---
# (replace_feature)
def replace_feature(image_cond_input, track_pos, strength):
    log("WARNING: Using dummy replace_feature. Actual implementation from WanVideoWrapper is required.", "WARN")
    return image_cond_input

# --- Placeholder for various other utilities from .utils if needed ---
# log, print_memory, apply_lora, fourier_filter, optimized_scale, setup_radial_attention,
# compile_model, dict_to_device, tangential_projection, get_raag_guidance, temporal_score_rescaling,
# offload_transformer, init_blockswap

# --- The WanVideoMusicVideoSampler class (replica) ---
# The core logic of WanVideoSampler will be copied here.
# It will be renamed WanVideoMusicVideoSampler, and its internal logic
# modified to use the replicated functions defined above.

rope_functions = ["default", "comfy", "comfy_chunked"]

class WanVideoMusicVideoSampler:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("WANVIDEOMODEL",),
                "image_embeds": ("WANVIDIMAGE_EMBEDS", ),
                "steps": ("INT", {"default": 30, "min": 1}),
                "cfg": ("FLOAT", {"default": 6.0, "min": 0.0, "max": 30.0, "step": 0.01}),
                "shift": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 1000.0, "step": 0.01}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "force_offload": ("BOOLEAN", {"default": True, "tooltip": "Moves the model to the offload device after sampling"}),
                "scheduler": (scheduler_list, {"default": "unipc",}),
                "riflex_freq_index": ("INT", {"default": 0, "min": 0, "max": 1000, "step": 1, "tooltip": "Frequency index for RIFLEX, disabled when 0, default 6. Allows for new frames to be generated after without looping"}),
                "audio_scale": ("FLOAT", {"default": 2.5, "min": 0.0, "max": 10.0}), # Music Video Sampler Specific
                "input_audio_fps": ("INT", {"default": 50, "min": 1, "max": 200}), # Music Video Sampler Specific
                "output_video_fps": ("INT", {"default": 25, "min": 1, "max": 60}), # Music Video Sampler Specific
            },
            "optional": {
                "text_embeds": ("WANVIDEOTEXTEMBEDS", ),
                "samples": ("LATENT", {"tooltip": "init Latents to use for video2video process"} ),
                "denoise_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "feta_args": ("FETAARGS", ),
                "context_options": ("WANVIDCONTEXT", ),
                "cache_args": ("CACHEARGS", ),
                "flowedit_args": ("FLOWEDITARGS", {"tooltip": "FlowEdit support has been deprecated"}),
                "batched_cfg": ("BOOLEAN", {"default": False, "tooltip": "Batch cond and uncond for faster sampling, possibly faster on some hardware, uses more memory"}),
                "slg_args": ("SLGARGS", ),
                "rope_function": (rope_functions, {"default": "comfy", "tooltip": "Comfy's RoPE implementation doesn't use complex numbers and can thus be compiled, that should be a lot faster when using torch.compile. Chunked version has reduced peak VRAM usage when not using torch.compile"}),
                "loop_args": ("LOOPARGS", ),
                "experimental_args": ("EXPERIMENTALARGS", ),
                "sigmas": ("SIGMAS", ),
                "unianimate_poses": ("UNIANIMATE_POSE", ),
                "fantasytalking_embeds": ("FANTASYTALKING_EMBEDS", ),
                "uni3c_embeds": ("UNI3C_EMBEDS", ),
                "multitalk_embeds": ("MULTITALK_EMBEDS", ),
                "freeinit_args": ("FREEINITARGS", ),
                "start_step": ("INT", {"default": 0, "min": 0, "max": 10000, "step": 1, "tooltip": "Start step for the sampling, 0 means full sampling, otherwise samples only from this step"}),
                "end_step": ("INT", {"default": -1, "min": -1, "max": 10000, "step": 1, "tooltip": "End step for the sampling, -1 means full sampling, otherwise samples only until this step"}),
                "add_noise_to_samples": ("BOOLEAN", {"default": False, "tooltip": "Add noise to the samples before sampling, needed for video2video sampling when starting from clean video"}),
                "whisper_model": ("WHISPERMODEL",), # Music Video Sampler Specific
                "reference_image": ("IMAGE",), # Music Video Sampler Specific
                "audio": ("AUDIO",), # Music Video Sampler Specific
            }
        }

    RETURN_TYPES = ("LATENT", "LATENT",)
    RETURN_NAMES = ("samples", "denoised_samples",)
    FUNCTION = "process"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"

    def __init__(self):
        # Initialize internal state variables, copied from WanVideoSampler if any
        # For now, just placeholder
        self.window_tracker = None
        self.cache_state = [None, None]
        self.cache_state_source = [None, None]
        self.cache_states_context = []
        self.controlnet = None # Assuming controlnet is handled similarly
        self.noise_front_pad_num = 0

    def process(self, model, image_embeds, shift, steps, cfg, seed, scheduler, riflex_freq_index, text_embeds=None,
        force_offload=True, samples=None, feta_args=None, denoise_strength=1.0, context_options=None,
        cache_args=None, teacache_args=None, flowedit_args=None, batched_cfg=False, slg_args=None, rope_function="comfy", loop_args=None,
        experimental_args=None, sigmas=None, unianimate_poses=None, fantasytalking_embeds=None, uni3c_embeds=None, multitalk_embeds=None, freeinit_args=None, start_step=0, end_step=-1, add_noise_to_samples=False):
        # This entire method needs to be copied from WanVideoSampler.process and adapted
        # I will replace 'self' references where appropriate and resolve imports.

        # For now, a placeholder to prevent immediate crash and indicate incomplete state
        log("ERROR: WanVideoMusicVideoSampler.process is not fully implemented yet. Using placeholder.", "ERROR")
        dummy_latent = {"samples": torch.zeros(1, 4, 16, 64, 64), "x": 0.0, "y": 0.0}
        return (dummy_latent, dummy_latent)

    # Helper methods for audio, reference image, and latent decoding (copied from nodes_studio.py initially)
    def _prepare_audio_embeddings(self, whisper_model, audio, num_frames, input_fps, output_fps, audio_scale):
        """Prepare audio embeddings using Whisper model"""
        model_w = whisper_model["model"] # Renamed to avoid conflict with 'model' argument in process
        feature_extractor = whisper_model["feature_extractor"]
        dtype = whisper_model["dtype"]
        sampling_rate = 16000

        audio_input = audio["waveform"]
        if audio_input.ndim > 2:
            audio_input = audio_input[0]

        sample_rate = audio["sample_rate"]

        if sample_rate != sampling_rate:
            resampler = torchaudio.transforms.Resample(
                orig_freq=sample_rate,
                new_freq=sampling_rate
            ).to(device)
            audio_input = resampler(audio_input.to(device))

        if audio_input.shape[0] == 2:  # Stereo to Mono
            audio_input = audio_input.mean(dim=0, keepdim=False)
        else:
            audio_input = audio_input[0]

        model_w.to(device) # Use model_w here
        audio_features = feature_extractor(
            audio_input.cpu(),
            sampling_rate=sampling_rate,
            return_tensors="pt"
        ).input_features
        audio_features = audio_features.to(device, dtype)

        audio_prompts = model_w.encoder( # Use model_w here
            audio_features,
            output_hidden_states=True
        ).hidden_states
        audio_prompts = torch.stack(audio_prompts, dim=2)
        model_w.to(offload_device) # Use model_w here

        # Interpolate features to match video FPS
        feat0 = linear_interpolation_fps(
            audio_prompts[:, :, 0:8].mean(dim=2),
            input_fps, output_fps
        )
        feat1 = linear_interpolation_fps(
            audio_prompts[:, :, 8:16].mean(dim=2),
            input_fps, output_fps
        )
        feat2 = linear_interpolation_fps(
            audio_prompts[:, :, 16:24].mean(dim=2),
            input_fps, output_fps
        )
        feat3 = linear_interpolation_fps(
            audio_prompts[:, :, 24:32].mean(dim=2),
            input_fps, output_fps
        )
        feat4 = linear_interpolation_fps(
            audio_prompts[:, :, 32],
            input_fps, output_fps
        )

        audio_emb = torch.stack([feat0, feat1, feat2, feat3, feat4], dim=2)[0]

        # Pad or trim to match num_frames
        if audio_emb.shape[0] < num_frames:
            pad = torch.zeros(
                num_frames - audio_emb.shape[0],
                *audio_emb.shape[1:],
                device=device,
                dtype=dtype
            )
            audio_emb = torch.cat([audio_emb, pad], dim=0)
        else:
            audio_emb = audio_emb[:num_frames]

        return {
            "humo_audio_emb": audio_emb,
            "humo_audio_scale": audio_scale,
            "humo_reference_count": 0
        }

    def _prepare_reference_image(self, reference_image, num_frames, lat_w, lat_h):
        """Prepare reference image embeddings"""
        if reference_image.shape[1] != lat_h * 8 or reference_image.shape[2] != lat_w * 8:
            reference_image = common_upscale(
                reference_image.movedim(-1, 1),
                lat_w * 8,
                lat_h * 8,
                "lanczos",
                "center"
            ).movedim(1, -1)

        # Create mask and reference latent
        mask = torch.zeros(4, num_frames, lat_h, lat_w, device=device)
        mask[:, 0] = 1.0  # First frame is reference

        return {
            "image_embeds": reference_image,
            "mask": mask,
            "has_ref": True
        }

    def _decode_latents(self, vae, latents):
        """Decode latents to video frames"""
        if vae is None or latents is None:
            return torch.zeros((1, 64, 64, 3))

        vae.to(device)
        video = vae.decode(latents.to(device))
        vae.to(offload_device)

        return video.cpu()

    # The following were also in the removed block but seem to be internal
    # to the WanVideoSampler's logic, they will be moved into the process
    # method or appropriate helper methods as part of the full replication.
    # def _sample_video(...)
    # def _decode_samples(...)

# You would also add NODE_CLASS_MAPPINGS and NODE_DISPLAY_NAME_MAPPINGS at the end
# but for the replica, it will be imported and mapped in nodes_studio.py
# Example:
# NODE_CLASS_MAPPINGS = {
#    "WanVideoMusicVideoSampler": WanVideoMusicVideoSampler,
# }
# NODE_DISPLAY_NAME_MAPPINGS = {
#    "WanVideoMusicVideoSampler": "🎤 WanVideo Music Video Sampler",
# }
