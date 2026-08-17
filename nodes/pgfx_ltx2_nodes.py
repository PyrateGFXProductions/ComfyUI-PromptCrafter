import logging
import sys
import os
import json
import math
import hashlib
import shutil
from datetime import datetime
logger = logging.getLogger("PGFX")
print("### [PGFX] ComfyUI-PromptCrafter LTX2 Nodes Initializing...", file=sys.stderr)
from typing import Dict, Any, Tuple
from server import PromptServer
import folder_paths
import torch
import comfy.ldm.modules.attention
import comfy.model_base
import comfy.utils

# ------------------------------------------------------------------------------------
# Helper function to read node descriptions from HELP.md
# ------------------------------------------------------------------------------------
def get_node_description(node_name):
    """Parses HELP.md and extracts the description for a given node class name."""
    try:
        import os
        import re
        help_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "HELP.md")
        if not os.path.exists(help_path):
            return f"Help file not found for {node_name}."

        with open(help_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Match either ## `NodeName` or ## `NodeName` (Alternate Name)
        pattern = re.compile(rf"##\s*`({node_name})(?:`|\s*\(.*?\)`)\n(.*?)(?=\n##\s*`|\Z)", re.DOTALL)
        match = pattern.search(content)

        if match:
            return match.group(2).strip()
        return f"No description found in HELP.md for {node_name}."
    except Exception as e:
        return f"Error reading help file: {e}"

# --- RUNTIME PATCH FOR CPU ATTENTION ---
# Some MultiGPU patches force the LTX2/LTXV text encoder to CPU.
# ComfyUI's default optimized_attention may try to use xformers on these CPU tensors,
# which causes a NotImplementedError. We patch it here to fallback to pytorch for CPU.
_original_optimized_attention = comfy.ldm.modules.attention.optimized_attention

def _manual_attention_fallback(q, k, v, heads, mask=None):
    """
    A manual PyTorch attention implementation that is extremely robust to 
    dimension mismatches (3D/4D) and mask broadcasting.
    """
    # 1. Normalize shapes to 4D (B, L, H, D) or (B, H, L, D)
    # ComfyUI usually passes (B, L, C) or (B, L, H, D). 
    # attention_pytorch expects (B, H, L, D) for the internal loop or SDPA.
    
    # Ensure q, k, v are 4D (B, L, H, D)
    if q.ndim == 3:
        b, l, c = q.shape
        q = q.view(b, l, heads, c // heads)
        k = k.view(k.shape[0], k.shape[1], heads, k.shape[2] // heads)
        v = v.view(v.shape[0], v.shape[1], heads, v.shape[2] // heads)
    
    # Transpose to (Batch, Heads, Seq_Len, Dim_Head)
    q = q.transpose(1, 2)
    k = k.transpose(1, 2)
    v = v.transpose(1, 2)
    
    # 2. Handle Mask Broadcasting
    # If mask is 3D (B, 1, S) or (B, L, S), and we have Heads > 1,
    # we need to make it (B, 1, 1, S) or (B, 1, L, S) for broadcasting.
    if mask is not None:
        if mask.ndim == 3:
            # Add the head dimension (B, 1, L, S)
            mask = mask.unsqueeze(1)
        elif mask.ndim == 2:
            # Add heads and query-len dimensions (B, 1, 1, S)
            mask = mask.unsqueeze(1).unsqueeze(1)

    # 3. Execution
    try:
        # Try SDPA first
        return torch.nn.functional.scaled_dot_product_attention(
            q, k, v, attn_mask=mask, dropout_p=0.0, is_causal=False
        ).transpose(1, 2).reshape(q.shape[0], q.shape[2], -1)
    except Exception as e:
        # Final slow fallback: Manual Matmul
        # print(f"### [PGFX] SDPA failed ({e}), using manual matmul.", file=sys.stderr)
        scale = 1.0 / math.sqrt(q.shape[-1])
        attn = torch.matmul(q, k.transpose(-2, -1)) * scale
        if mask is not None:
            attn = attn + mask
        attn = torch.softmax(attn, dim=-1)
        return torch.matmul(attn, v).transpose(1, 2).reshape(q.shape[0], q.shape[2], -1)

def _patched_optimized_attention(q, k, v, heads, mask=None, attn_precision=None, transformer_options=None, **kwargs):
    # Diagnostic logging (can be noisy, but needed for this specific crash)
    # print(f"### [PGFX] Attention: q={q.shape}, k={k.shape}, v={v.shape}, heads={heads}, device={q.device}", file=sys.stderr)
    
    # Fallback conditions:
    # 1. Any tensor is on CPU (xformers/flash-attn are CUDA-only)
    # 2. Tensors are sparse (as suggested by the 'sparse_coo' error message)
    #
    # ComfyUI's optimized attention routinely receives 3D (B, T, C) tensors and
    # handles reshaping itself. Treating all 3D GPU attention as a fallback case
    # hijacks attention for unrelated models and caused compatibility failures as
    # ComfyUI added new keyword arguments.
    is_cpu = q.device.type == "cpu" or k.device.type == "cpu" or v.device.type == "cpu"
    is_sparse = q.is_sparse or k.is_sparse or v.is_sparse
    
    if is_cpu or is_sparse:
        if is_sparse:
             print(f"### [PGFX] Detected Sparse Tensor! q={q.shape}, sparse={is_sparse}", file=sys.stderr)
        
        try:
             # Try the standard comfy fallback first
             return comfy.ldm.modules.attention.attention_pytorch(
                 q, k, v, heads, mask=mask, attn_precision=attn_precision,
                 transformer_options=transformer_options, **kwargs
             )
        except Exception:
             # If it fails (dimensions, unpacking, etc), use our robust manual fallback
             return _manual_attention_fallback(q, k, v, heads, mask)
        
    return _original_optimized_attention(
        q, k, v, heads, mask=mask, attn_precision=attn_precision,
        transformer_options=transformer_options, **kwargs
    )

if not hasattr(comfy.ldm.modules.attention, "_pgfx_patched"):
    print("### [PGFX] Applying CPU-safe Attention Patch...", file=sys.stderr)
    comfy.ldm.modules.attention.optimized_attention = _patched_optimized_attention
    comfy.ldm.modules.attention._pgfx_patched = True

# --- RUNTIME PATCH FOR GGUF LINEAR SHAPE INVERSIONS ---
# PGFX Studio local patch to handle ComfyUI-GGUF dimension inversions on LTXV/LTX2 
# audio/video padding embeddings connectors (e.g. 15360x3840 vs 1024x3840).
import comfy.ops
_original_linear_forward = comfy.ops.manual_cast.Linear.forward_comfy_cast_weights

def _pgfx_gguf_linear_forward(self, input, *args, **kwargs):
    try:
        return _original_linear_forward(self, input, *args, **kwargs)
    except RuntimeError as e:
        if "shapes cannot be multiplied" in str(e):
            # Check if transposing the weight matrix resolves it
            # The error is usually mat1 (input: ..., in_features) x mat2 (weight^T: in_features, out_features)
            # In comfy.ops, it calls F.linear(input, weight, bias)
            # If weight is loaded as (in_features, out_features) instead of (out_features, in_features),
            # this crashes. Let's try to transpose the weight locally.
            try:
                weight, bias = self.cast_bias_weight(input)
                # If input target is weight.shape[0] instead of weight.shape[1]
                if input.shape[-1] == weight.shape[0] and input.shape[-1] != weight.shape[1]:
                    # print(f"### [PGFX] Intercepted transposed GGUF Linear weight: {weight.shape}. Transposing...", file=sys.stderr)
                    # Transpose weight to (out_features, in_features)
                    transposed_weight = weight.t()
                    return torch.nn.functional.linear(input, transposed_weight, bias)
            except Exception as inner_e:
                pass # Fall through to original error
        raise e

if not hasattr(comfy.ops.manual_cast.Linear, "_pgfx_linear_patched"):
    print("### [PGFX] Applying GGUF Linear Shape Patch...", file=sys.stderr)
    comfy.ops.manual_cast.Linear.forward_comfy_cast_weights = _pgfx_gguf_linear_forward
    comfy.ops.manual_cast.Linear._pgfx_linear_patched = True

# --- RUNTIME PATCH FOR LTXAV GGUF CONNECTOR TENSORS ---
# Recent ComfyUI versions detect LTX-2 AV checkpoints as `ltxav`, which expects
# audio/video embedding connector weights inside the UNet state dict. Some GGUF
# exports omit these tensors, while shipping them separately as
# `ltx-2-19b-embeddings_connector_*`. When missing, UNet loads with randomly
# initialized connectors and generation quality can collapse (often black output).
_PGFX_LTXAV_CONNECTOR_CACHE = {
    "path": None,
    "weights": None,
}

def _discover_ltxav_connector_path():
    preferred = "ltx-2-19b-embeddings_connector_dev_bf16.safetensors"
    
    # Search in 'clip' folder paths
    try:
        clip_files = folder_paths.get_filename_list("clip")
        for name in clip_files:
            if preferred in name or ("ltx" in name.lower() and "embeddings_connector" in name.lower()):
                path = folder_paths.get_full_path("clip", name)
                if path and os.path.isfile(path):
                    return path
    except Exception:
        pass

    # Fallback: search 'checkpoints' and 'diffusion_models'
    for folder in ["checkpoints", "diffusion_models"]:
        try:
            files = folder_paths.get_filename_list(folder)
            for name in files:
                if preferred in name or ("ltx" in name.lower() and "embeddings_connector" in name.lower()):
                    path = folder_paths.get_full_path(folder, name)
                    if path and os.path.isfile(path):
                        return path
        except Exception:
            continue
            
    return None

def _load_ltxav_connector_weights(target_dtype=None, target_device=None):
    cached_path = _PGFX_LTXAV_CONNECTOR_CACHE.get("path")
    cached_weights = _PGFX_LTXAV_CONNECTOR_CACHE.get("weights")
    
    if cached_path and isinstance(cached_weights, dict):
        # Check if we need to re-cast
        first_val = next(iter(cached_weights.values()))
        if (target_dtype is None or first_val.dtype == target_dtype):
             return cached_path, cached_weights

    connector_path = _discover_ltxav_connector_path()
    if not connector_path:
        return None, {}

    print(f"### [PGFX] Loading LTXAV connectors from {os.path.basename(connector_path)}", file=sys.stderr)
    raw = comfy.utils.load_torch_file(connector_path, safe_load=True)
    connector_weights = {}
    
    for key, value in raw.items():
        norm_key = key
        if norm_key.startswith("model.diffusion_model."):
            norm_key = norm_key[len("model.diffusion_model."):]
        elif norm_key.startswith("diffusion_model."):
            norm_key = norm_key[len("diffusion_model."):]

        if norm_key.startswith("audio_embeddings_connector.") or norm_key.startswith("video_embeddings_connector."):
            if target_dtype is not None:
                value = value.to(dtype=target_dtype)
            if target_device is not None:
                value = value.to(device=target_device)
            connector_weights[norm_key] = value

    _PGFX_LTXAV_CONNECTOR_CACHE["path"] = connector_path
    _PGFX_LTXAV_CONNECTOR_CACHE["weights"] = connector_weights
    return connector_path, connector_weights

_original_base_load_model_weights = comfy.model_base.BaseModel.load_model_weights

def _pgfx_load_model_weights_with_ltxav_connectors(self, sd, unet_prefix="", assign=False):
    try:
        # Check for LTXAV model (or anything that has the connector keys but they are missing in sd)
        is_ltxav = isinstance(self, comfy.model_base.LTXAV)
        
        # Also check for Gemma/LTX-2 style models by architecture name if possible
        model_name = self.__class__.__name__.lower()
        if not is_ltxav and ("ltx" in model_name or "gemma" in model_name):
             is_ltxav = True

        if is_ltxav:
            pref = unet_prefix or ""
            has_audio_connector = any(k.startswith(f"{pref}audio_embeddings_connector.") for k in sd.keys())
            has_video_connector = any(k.startswith(f"{pref}video_embeddings_connector.") for k in sd.keys())

            if not (has_audio_connector and has_video_connector):
                # Determine target dtype from an existing weight to prevent FP8/BF16 mismatches
                target_dtype = None
                if sd:
                    # Get dtype of first available tensor
                    first_tensor = next(iter(sd.values()))
                    if hasattr(first_tensor, "dtype"):
                        target_dtype = first_tensor.dtype
                
                connector_path, connector_weights = _load_ltxav_connector_weights(target_dtype=target_dtype)
                if connector_weights:
                    injected = 0
                    for key, value in connector_weights.items():
                        target_key = f"{pref}{key}"
                        if target_key not in sd:
                            sd[target_key] = value
                            injected += 1
                    if injected > 0:
                        print(
                            f"### [PGFX] LTXAV connector merge: injected {injected} tensors ({target_dtype}) from {os.path.basename(connector_path)}",
                            file=sys.stderr,
                        )
                else:
                    print(
                        "### [PGFX] CRITICAL: LTXAV model missing connector tensors (audio_embeddings_connector / video_embeddings_connector). "
                        "Generation will likely be NOISE. Please place 'ltx-2-19b-embeddings_connector_dev_bf16.safetensors' in your models/clip folder.",
                        file=sys.stderr,
                    )
    except Exception as e:
        print(f"### [PGFX] WARNING: LTXAV connector auto-merge failed: {e}", file=sys.stderr)

    return _original_base_load_model_weights(self, sd, unet_prefix=unet_prefix, assign=assign)

if not hasattr(comfy.model_base.BaseModel, "_pgfx_ltxav_connector_patch"):
    print("### [PGFX] Applying LTXAV connector auto-merge patch...", file=sys.stderr)
    comfy.model_base.BaseModel.load_model_weights = _pgfx_load_model_weights_with_ltxav_connectors
    comfy.model_base.BaseModel._pgfx_ltxav_connector_patch = True


from ..core import pgfx_config as config
from ..utils import pgfx_utils as utils

class PGFX_Studio_LTX2Queue:
    """
    LTX-2 Queue Manager.
    Automatically calculates the number of required generation sets based on audio
    duration and frames per scene, and dispatches the required jobs to the ComfyUI API queue.
    """
    DESCRIPTION = get_node_description("PGFX_Studio_LTX2Queue")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PROJECT_CONFIG": ("DICT",),
                "TIMING_MAP": ("DICT",),
                "enable_auto_queue": ("BOOLEAN", {"default": True, "tooltip": "If true, jobs will be automatically dispatched to the queue."}),
                "force_reset": ("BOOLEAN", {"default": False, "tooltip": "If true, forces the set tracking to reset to 0."}),
            },
            "optional": {
                "audio_meta": ("DICT", {"tooltip": "Fallback audio metadata if TIMING_MAP lacks timing info."}),
            }
        }

    RETURN_TYPES = ("DICT", "DICT", "INT", "INT", "BOOLEAN")
    RETURN_NAMES = ("PROJECT_CONFIG", "TIMING_MAP", "current_set_index", "total_sets", "is_final_set")
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Studio"

    _SESSION_STATE = {}

    def execute(self, PROJECT_CONFIG: Dict[str, Any], TIMING_MAP: Dict[str, Any], enable_auto_queue: bool, force_reset: bool, audio_meta: Dict[str, Any] = None) -> Tuple[Dict[str, Any], Dict[str, Any], int, int, bool]:
        
        # Extract required metadata
        render_plan = PROJECT_CONFIG.get("render_plan", {})
        target_dir = PROJECT_CONFIG.get("root_path", folder_paths.get_output_directory())
        
        # Calculate unique session key based on project path and timing parameters
        # We use a custom encoder/stringifier for the hash to handle Tensors safely.
        def safe_stringify(obj):
            if isinstance(obj, torch.Tensor):
                # We care about the size/shape and a small slice of data for the hash
                return f"Tensor_{obj.shape}_{obj.device}"
            if isinstance(obj, dict):
                return {k: safe_stringify(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [safe_stringify(i) for i in obj]
            return str(obj)

        timing_str = str(safe_stringify(TIMING_MAP))
        timing_hash = hashlib.sha256(timing_str.encode()).hexdigest()
        session_key = f"{target_dir}_{timing_hash}"
        
        # Calculate total required sets
        total_clips = len(TIMING_MAP.get("durations_frames", []))
        if total_clips == 0 and audio_meta and "durations_frames" in audio_meta:
            total_clips = len(audio_meta.get("durations_frames", []))
            
        total_sets = total_clips if total_clips > 0 else 1
        
        # Load state from memory-only session state
        session_id = str(PROJECT_CONFIG.get("session_id", "default_session"))
        session_key = f"ltx2_queue_{session_id}"
        
        # Determine if we should mark failure (e.g. if we were called but are in an error state)
        # We check the session state for a failure flag that might have been set by other nodes
        # or the Cinematographer if it detects an empty output path.
        has_failed = self._SESSION_STATE.get(f"{session_key}_failed", False)
        
        if force_reset:
            self._SESSION_STATE[session_key] = 0
            self._SESSION_STATE[f"{session_key}_has_queued"] = False
            self._SESSION_STATE[f"{session_key}_failed"] = False
            print(f"### [LTX2Queue] Force Reset triggered for session {session_id}")
            
        current_set_index = self._SESSION_STATE.get(session_key, 0)
        has_queued = self._SESSION_STATE.get(f"{session_key}_has_queued", False)

        if has_failed:
             print(f"### [LTX2Queue] Session {session_id} has FAILED. Auto-queuing disabled.")
             return (PROJECT_CONFIG, TIMING_MAP, current_set_index, total_sets, True)

        # Update total sets if provided in config
        if "total_sets" in PROJECT_CONFIG:
             total_sets = int(PROJECT_CONFIG["total_sets"])

        # AUTO-QUEUE LOGIC: Only trigger on the FIRST run (index 0) and if not already done
        if enable_auto_queue and current_set_index == 0 and not has_queued:
            if total_sets > 1:
                queues_to_add = total_sets - 1
                print(f"### [LTX2Queue] Auto-queuing {queues_to_add} additional runs to complete {total_sets} total clips for session {session_id}.")
                for _ in range(queues_to_add):
                    PromptServer.instance.send_sync("impact-add-queue", {})
                self._SESSION_STATE[f"{session_key}_has_queued"] = True
            else:
                # If total_sets is 1, it means only one job is needed, so it's effectively "queued"
                self._SESSION_STATE[f"{session_key}_has_queued"] = True

        # Determine if this is the final job
        is_final_set = (current_set_index >= total_sets - 1)


        # Advance state for the next run (instantly in memory)
        next_index = current_set_index + 1 if not is_final_set else 0
        self._SESSION_STATE[session_key] = next_index

        # Mutate project config with the active generation targets
        render_plan["active_job_index"] = current_set_index
        render_plan["total_jobs"] = total_sets
        PROJECT_CONFIG["render_plan"] = render_plan
        
        # Inform the UI
        try:
            status_msg = f"⏳ Processing clip {current_set_index + 1} of {total_sets}."
            if is_final_set:
                status_msg = f"🏁 Final clip ({current_set_index + 1}/{total_sets}) generation triggered."
            PromptServer.instance.send_sync("vrgdg_instructions_popup", {"message": status_msg, "type": "info" if not is_final_set else "success", "title": "LTX-2 Queue Manager"})
        except Exception:
            pass

        return (PROJECT_CONFIG, TIMING_MAP, current_set_index, total_sets, is_final_set)

import subprocess
import glob

class PGFX_Studio_Stitcher:
    """
    LTX-2 Video Stitcher.
    Collects the generated clips from the output directory and concatenates them
    with the original audio stem using ffmpeg.
    """
    DESCRIPTION = get_node_description("PGFX_Studio_Stitcher")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PROJECT_CONFIG": ("DICT",),
                "is_final_set": ("BOOLEAN",),
            },
            "optional": {
                "original_audio": ("AUDIO",),
                "file_prefix": ("STRING", {"default": "LTX2_Part_", "tooltip": "Prefix of the files to stitch saved by the video saver."}),
                "clear_parts_after_stitch": ("BOOLEAN", {"default": False})
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("final_video_path",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Studio"
    OUTPUT_NODE = True

    def execute(self, PROJECT_CONFIG: Dict[str, Any], is_final_set: bool, original_audio: Any = None, file_prefix: str = "LTX2_Part_", clear_parts_after_stitch: bool = False) -> Tuple[str]:
        if not is_final_set:
            return ("Generation in progress. No stitch yet.",)
            
        target_dir = PROJECT_CONFIG.get("root_path", folder_paths.get_output_directory())
        
        # Look for the parts
        search_pattern = os.path.join(target_dir, f"{file_prefix}*.mp4")
        video_files = glob.glob(search_pattern)
        
        if not video_files:
            video_files = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.endswith('.mp4') and 'FINAL' not in f]
            
        if not video_files:
            print(f"[LTX2Stitcher] No video files found to stitch in {target_dir}")
            return ("Error: No video files found",)
            
        # Sort files by modification time or alphabetically
        video_files.sort(key=os.path.getmtime)
        
        concat_txt_path = os.path.join(target_dir, "stitch_concat.txt")
        try:
            with open(concat_txt_path, 'w') as f:
                for vf in video_files:
                    # ffmpeg requires forward slashes or escaped backslashes, and proper quoting
                    safe_path = vf.replace('\\', '/')
                    f.write(f"file '{safe_path}'\n")
        except Exception as e:
            print(f"[LTX2Stitcher] Error writing concat file: {e}")
            return ("Error writing concat file",)
            
        final_video_path = os.path.join(target_dir, f"FINAL_LTX2_MusicVideo_{int(os.path.getmtime(video_files[0]))}.mp4")
        merged_video_no_audio = os.path.join(target_dir, "temp_merged_no_audio.mp4")
        
        # Run ffmpeg concat
        try:
            print(f"[LTX2Stitcher] Stitching {len(video_files)} files...")
            concat_cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", 
                "-i", concat_txt_path, 
                "-c", "copy", 
                merged_video_no_audio
            ]
            subprocess.run(concat_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # If audio is provided, extract from tensor and add to video. 
            # If not, the file is already merged.
            if original_audio is not None and "waveform" in original_audio:
                import torchaudio
                waveform = original_audio["waveform"]
                sample_rate = original_audio["sample_rate"]
                
                if waveform.ndim == 3:
                    waveform = waveform.squeeze(0)
                    
                temp_audio_path = os.path.join(target_dir, "temp_original_audio.wav")
                torchaudio.save(temp_audio_path, waveform.cpu(), sample_rate)
                
                mux_cmd = [
                    "ffmpeg", "-y", 
                    "-i", merged_video_no_audio, 
                    "-i", temp_audio_path, 
                    "-c:v", "copy", 
                    "-c:a", "aac", 
                    "-map", "0:v:0", "-map", "1:a:0",
                    final_video_path
                ]
                subprocess.run(mux_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                if os.path.exists(temp_audio_path):
                    os.remove(temp_audio_path)
            else:
                # Just rename the merged video if no audio
                os.rename(merged_video_no_audio, final_video_path)
                
            if os.path.exists(merged_video_no_audio):
                os.remove(merged_video_no_audio)
                
            if clear_parts_after_stitch:
                for vf in video_files:
                    try:
                        os.remove(vf)
                    except:
                        pass
                        
            print(f"[LTX2Stitcher] Success! Final video saved to {final_video_path}")
            
            PromptServer.instance.send_sync("vrgdg_instructions_popup", {
                "message": f"🎉 Final Video Stitched Successfully!\nSaved to: {final_video_path}", 
                "type": "success", 
                "title": "LTX-2 Stitcher"
            })
                
            return (final_video_path,)
            
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
            print(f"[LTX2Stitcher] FFmpeg Error: {err_msg}")
            return (f"FFmpeg Error: {err_msg}",)
        except Exception as e:
            print(f"[LTX2Stitcher] Unexpected Error: {e}")
            return (f"Error: {e}",)


import torch
import comfy.utils
import comfy.model_management
from comfy_extras.nodes_lt_upsampler import LTXVLatentUpsampler

class PGFX_LTXVLatentUpsampler:
    """
    Enhanced LTXV Latent Upsampler that preserves and spatially upscales the noise mask.
    Prevents NoneType errors in subsequent sampling stages.
    """
    DESCRIPTION = get_node_description("PGFX_LTXVLatentUpsampler")
    @classmethod
    def INPUT_TYPES(s):
        return LTXVLatentUpsampler.INPUT_TYPES()

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "upsample"
    CATEGORY = "☠️PGFX /Studio"

    def _ensure_5d_latent(self, tensor):
        """Normalize legacy 4D video latents to 5D [B,C,F,H,W]."""
        if hasattr(tensor, "ndim") and tensor.ndim == 4:
            return tensor.unsqueeze(0)
        return tensor

    def _flatten_nested_leaves(self, value):
        """Recursively flatten NestedTensor structures into plain tensor leaves."""
        if getattr(value, "is_nested", False):
            leaves = []
            for child in value.unbind():
                leaves.extend(self._flatten_nested_leaves(child))
            return leaves
        return [value]

    def _select_video_leaf(self, value):
        leaves = [t for t in self._flatten_nested_leaves(value) if hasattr(t, "ndim")]
        if not leaves:
            return None

        # Prefer true video latent rank, fallback to legacy rank.
        video = next((t for t in leaves if t.ndim == 5), None)
        if video is None:
            video = next((t for t in leaves if t.ndim == 4), None)
        if video is None:
            return None
        return self._ensure_5d_latent(video)

    def _select_video_mask_leaf(self, value):
        leaves = [t for t in self._flatten_nested_leaves(value) if hasattr(t, "ndim")]
        if not leaves:
            return None
        mask = next((t for t in leaves if t.ndim == 5), None)
        if mask is None:
            mask = next((t for t in leaves if t.ndim == 4), None)
        return mask

    def _upscale_mask_to_latent(self, mask, target_latent):
        if mask is None or not hasattr(mask, "shape") or not hasattr(target_latent, "shape"):
            return mask
        if len(target_latent.shape) != 5:
            return mask

        # Accept legacy 4D masks by inserting batch dimension.
        if len(mask.shape) == 4:
            mask = mask.unsqueeze(0)
        if len(mask.shape) != 5:
            return mask

        b, _, f, h, w = target_latent.shape
        mb, mc, mf, mh, mw = mask.shape

        # Align temporal length first (nearest frame mapping).
        if mf != f:
            if mf == 1 and f > 1:
                mask = mask.expand(mask.shape[0], mask.shape[1], f, mask.shape[3], mask.shape[4])
            elif mf > 1 and f > 0:
                frame_idx = torch.linspace(0, mf - 1, f, device=mask.device).round().long()
                mask = mask.index_select(2, frame_idx)

        # Align spatial resolution with nearest upscaling for binary-ish masks.
        if (mh, mw) != (h, w):
            flat = mask.permute(0, 2, 1, 3, 4).reshape(-1, mc, mh, mw)
            flat = comfy.utils.common_upscale(flat, w, h, "nearest-exact", "disabled")
            mask = flat.reshape(mask.shape[0], f, mc, h, w).permute(0, 2, 1, 3, 4)

        mask = comfy.utils.repeat_to_batch_size(mask, b)
        if mask.shape[1] != 1:
            mask = mask[:, :1, ...]
        return mask

    def upsample(self, samples, upscale_model, vae):
        # Store original mask if it exists
        original_mask = samples.get("noise_mask", None)
        upsampler = LTXVLatentUpsampler()
        latents = samples.get("samples")

        # Handle AV NestedTensor by upscaling only the video branch and returning
        # a regular video latent (not nested). This node is used on video-only path.
        if getattr(latents, "is_nested", False):
            video_latent = self._select_video_leaf(latents)
            if video_latent is None:
                print("### [PGFX] PGFX_LTXVLatentUpsampler: no video leaf found in nested latent; skipping.", file=sys.stderr)
                return (samples,)

            video_only_samples = samples.copy()
            video_only_samples["samples"] = video_latent

            if getattr(original_mask, "is_nested", False):
                video_mask = self._select_video_mask_leaf(original_mask)
                if video_mask is not None:
                    video_only_samples["noise_mask"] = video_mask
                else:
                    video_only_samples.pop("noise_mask", None)
            elif original_mask is not None:
                video_only_samples["noise_mask"] = original_mask
            else:
                video_only_samples.pop("noise_mask", None)

            (video_result,) = upsampler.upsample_latent(video_only_samples, upscale_model, vae)
            upsampled_video_latent = video_result["samples"]

            result = samples.copy()
            result["samples"] = upsampled_video_latent

            # Restore mask (native upsampler drops it).
            if original_mask is not None:
                if getattr(original_mask, "is_nested", False):
                    video_mask = self._select_video_mask_leaf(original_mask)
                    if video_mask is not None:
                        result["noise_mask"] = self._upscale_mask_to_latent(video_mask, upsampled_video_latent)
                    else:
                        result.pop("noise_mask", None)
                else:
                    result["noise_mask"] = self._upscale_mask_to_latent(original_mask, upsampled_video_latent)

            return (result,)

        # Regular video latent path.
        regular_samples = samples.copy()
        regular_samples["samples"] = self._ensure_5d_latent(latents)
        (result,) = upsampler.upsample_latent(regular_samples, upscale_model, vae)
        if original_mask is not None and not getattr(original_mask, "is_nested", False):
            result["noise_mask"] = self._upscale_mask_to_latent(original_mask, result["samples"])
        return (result,)

class PGFX_LTXVCorrectiveMask:
    """
    Ensures a noise_mask is present and correctly shaped for LTXV nodes.
    Used before SamplerCustomAdvanced to prevent 'NoneType' shape errors.
    """
    DESCRIPTION = get_node_description("PGFX_LTXVCorrectiveMask")
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "samples": ("LATENT",),
            },
            "optional": {
                "mask_override": ("MASK",),
                "force_mask": (["disabled", "enabled"], {"default": "enabled"}),
            }
        }

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "fix_mask"
    CATEGORY = "☠️PGFX /Studio"

    def _flatten_nested_leaves(self, value):
        if getattr(value, "is_nested", False):
            leaves = []
            for child in value.unbind():
                leaves.extend(self._flatten_nested_leaves(child))
            return leaves
        return [value]

    def _normalize_nested_samples(self, latents):
        """
        Collapse accidentally nested-in-nested AV latents into a sampler-safe shape.
        Result is either:
        - plain Tensor (single branch), or
        - NestedTensor of plain tensor leaves (no nested branches).
        """
        if not getattr(latents, "is_nested", False):
            return latents

        leaves = [t for t in self._flatten_nested_leaves(latents) if hasattr(t, "shape") and hasattr(t, "ndim")]
        if not leaves:
            return latents

        # Keep deterministic order while removing duplicate references.
        deduped = []
        seen = set()
        for t in leaves:
            tid = id(t)
            if tid in seen:
                continue
            seen.add(tid)
            deduped.append(t)

        # For AV graphs, strongly prefer one video branch + one audio branch.
        video = next((t for t in deduped if t.ndim == 5), None)
        audio = next((t for t in deduped if t.ndim == 4 and t is not video), None)
        if video is not None and audio is not None:
            import comfy.nested_tensor
            return comfy.nested_tensor.NestedTensor((video, audio))

        if len(deduped) == 1:
            return deduped[0]

        import comfy.nested_tensor
        return comfy.nested_tensor.NestedTensor(tuple(deduped))

    def fix_mask(self, samples, mask_override=None, force_mask="enabled"):
        print(f"!!! [PGFX_CorrectiveMask] Entering fix_mask. Force: {force_mask}", file=sys.stderr)
        print(f"!!! [PGFX_CorrectiveMask] Input keys: {list(samples.keys())}", file=sys.stderr)
        result = samples.copy()
        latents = self._normalize_nested_samples(samples["samples"])
        if latents is not samples["samples"]:
            result["samples"] = latents
            print("!!! [PGFX_CorrectiveMask] Normalized nested latent structure for sampler safety", file=sys.stderr)
            if getattr(latents, "is_nested", False):
                branch_shapes = [tuple(t.shape) if hasattr(t, "shape") else str(type(t)) for t in latents.unbind()]
                print(f"!!! [PGFX_CorrectiveMask] Normalized sample branches: {branch_shapes}", file=sys.stderr)
        
        # Determine shape and dtype even for NestedTensors
        if getattr(latents, "is_nested", False):
            if hasattr(latents, "tensors") and len(latents.tensors) > 0:
                # Prefer the video branch shape (5D) when AV branches are mixed.
                base_latent = next(
                    (t for t in latents.tensors if hasattr(t, "ndim") and t.ndim == 5),
                    latents.tensors[0],
                )
                l_shape = base_latent.shape
                l_dtype = base_latent.dtype
                l_device = base_latent.device
                print(f"!!! [PGFX_CorrectiveMask] Nested latent detected. Base shape: {l_shape}", file=sys.stderr)
            else:
                l_shape = latents.shape
                l_dtype = latents.dtype
                l_device = latents.device
        else:
            if hasattr(latents, "shape"):
                l_shape = latents.shape
                l_dtype = latents.dtype
                l_device = latents.device
                print(f"!!! [PGFX_CorrectiveMask] Regular latent detected. Shape: {l_shape}", file=sys.stderr)
            else:
                # Last resort fallback if it's something totally unexpected
                print(f"!!! [PGFX_CorrectiveMask] WARNING: Latent missing shape attribute!", file=sys.stderr)
                return (samples,)

        needs_forced_mask = force_mask == "enabled" and ("noise_mask" not in result or result["noise_mask"] is None)
        if needs_forced_mask:
            if getattr(latents, "is_nested", False) and hasattr(latents, "tensors"):
                import comfy.nested_tensor
                new_masks = []
                for t in latents.tensors:
                    # AV NestedTensor branches can differ in rank (video=5D, audio=4D).
                    # Keep branch rank and force channel dim to 1.
                    if not hasattr(t, "shape") or len(t.shape) < 2:
                        continue
                    mask_shape = list(t.shape)
                    mask_shape[1] = 1
                    new_masks.append(torch.ones(tuple(mask_shape), dtype=t.dtype, device=t.device))
                result["noise_mask"] = comfy.nested_tensor.NestedTensor(tuple(new_masks))
                print(f"!!! [PGFX_CorrectiveMask] Forced default NestedTensor ones mask", file=sys.stderr)
            else:
                # Force a default ones mask for standard tensors
                if len(l_shape) == 4:
                    l_shape = (1,) + tuple(l_shape)
                if len(l_shape) != 5:
                    print(f"!!! [PGFX_CorrectiveMask] WARNING: Unsupported latent shape for force mask: {l_shape}", file=sys.stderr)
                    return (samples,)
                b, c, f, h, w = l_shape
                result["noise_mask"] = torch.ones((b, 1, f, h, w), dtype=l_dtype, device=l_device)
                print(f"!!! [PGFX_CorrectiveMask] Forced default ones mask: {result['noise_mask'].shape}", file=sys.stderr)
        elif force_mask == "enabled":
            print("!!! [PGFX_CorrectiveMask] Existing mask detected; preserving instead of forcing default mask", file=sys.stderr)
        
        if mask_override is not None:
            # Convert MASK to noise_mask shape (b, 1, f, h, w)
            m = mask_override
            if m.ndim == 3: # (f, h, w)
                m = m.unsqueeze(0).unsqueeze(1) # (1, 1, f, h, w)
            elif m.ndim == 4: # (b, f, h, w)
                m = m.unsqueeze(1) # (b, 1, f, h, w)
            
            # Ensure spatial-temporal match
            if m.shape[-3:] != l_shape[-3:]:
                if len(l_shape) == 4:
                    l_shape = (1,) + tuple(l_shape)
                if len(l_shape) != 5:
                    print(f"!!! [PGFX_CorrectiveMask] WARNING: Unsupported latent shape for mask override: {l_shape}", file=sys.stderr)
                    return (samples,)
                b, c, f, h, w = l_shape
                m_shape = m.shape
                # Use common_upscale for robust resizing
                m = comfy.utils.common_upscale(m.flatten(0, 1), w, h, "nearest-exact", "disabled")
                m = m.reshape(b, 1, f, h, w)
            
            result["noise_mask"] = m.to(l_device)
            print(f"!!! [PGFX_CorrectiveMask] Applied mask override: {result['noise_mask'].shape}", file=sys.stderr)
        elif "noise_mask" not in result or result["noise_mask"] is None:
            if force_mask == "enabled":
                # Already handled above
                pass
            else:
                print(f"!!! [PGFX_CorrectiveMask] Mask missing and force_mask disabled! This may CRASH if keyframes are used.", file=sys.stderr)
        else:
            # Check existing mask shape for NestedTensor or Regular
            mask = result["noise_mask"]
            if getattr(mask, "is_nested", False):
                # Keep nested masks nested when samples are AV nested latents.
                # LTXVSeparateAVLatent expects two mask branches and will crash
                # on a flattened tensor mask (masks[1] out of range).
                if getattr(latents, "is_nested", False):
                    import comfy.nested_tensor
                    latent_parts = list(latents.unbind())
                    raw_masks = mask.unbind()
                    mask_parts = list(raw_masks) if isinstance(raw_masks, (list, tuple)) else []
                    fixed_masks = []
                    for idx, lt in enumerate(latent_parts):
                        m = mask_parts[idx] if idx < len(mask_parts) else None
                        if m is None or not hasattr(m, "shape"):
                            if hasattr(lt, "shape") and len(lt.shape) >= 2:
                                m_shape = list(lt.shape)
                                m_shape[1] = 1
                                m = torch.ones(tuple(m_shape), dtype=lt.dtype, device=lt.device)
                        elif hasattr(m, "shape") and hasattr(lt, "shape"):
                            if len(m.shape) == 4 and len(lt.shape) == 5:
                                m = m.unsqueeze(0)
                            if len(m.shape) >= 2 and m.shape[1] != 1:
                                m = m[:, :1, ...]
                        fixed_masks.append(m)
                    result["noise_mask"] = comfy.nested_tensor.NestedTensor(tuple(fixed_masks))
                    print("!!! [PGFX_CorrectiveMask] Preserving NestedTensor mask for AV split compatibility", file=sys.stderr)
                else:
                    # For non-nested latents, flatten to a regular tensor.
                    print(f"!!! [PGFX_CorrectiveMask] Unbinding NestedTensor mask for non-nested latent compatibility", file=sys.stderr)
                    masks = mask.unbind()
                    if isinstance(masks, (list, tuple)) and len(masks) > 0:
                        video_mask = next((m for m in masks if hasattr(m, "ndim") and m.ndim == 5), masks[0])
                        result["noise_mask"] = video_mask
                    else:
                        print(f"!!! [PGFX_CorrectiveMask] WARNING: Nested mask unbind returned no tensors.", file=sys.stderr)
                        result.pop("noise_mask", None)
            elif mask.shape[1] != 1 and mask.shape[1] == l_shape[1]:
                # Native nodes sometimes create masks with channel count matching latents (128)
                result["noise_mask"] = mask[:, :1, ...]
                print(f"!!! [PGFX_CorrectiveMask] Reshaped 128-ch mask to 1-ch: {result['noise_mask'].shape}", file=sys.stderr)
            else:
                print(f"!!! [PGFX_CorrectiveMask] Mask already valid: {mask.shape if hasattr(mask, 'shape') else 'no shape'}", file=sys.stderr)

        print(f"!!! [PGFX_CorrectiveMask] Output keys: {list(result.keys())}", file=sys.stderr)
        return (result,)

class PGFX_LatentProbe:
    DESCRIPTION = get_node_description("PGFX_LatentProbe")
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "samples": ("LATENT",),
                "label": ("STRING", {"default": "Probe"}),
            }
        }

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "probe"
    CATEGORY = "☠️PGFX /Studio"

    def probe(self, samples, label):
        print(f"--- [PGFX_Probe: {label}] ---", file=sys.stderr)
        for k, v in samples.items():
            if getattr(v, "is_nested", False):
                print(f"  {k}: NestedTensor {v.shape} ({v.dtype if hasattr(v, 'dtype') else 'no-dtype'}) on {v.device if hasattr(v, 'device') else 'no-device'}", file=sys.stderr)
            elif hasattr(v, "shape"):
                print(f"  {k}: Tensor {v.shape} ({v.dtype if hasattr(v, 'dtype') else 'no-dtype'}) on {v.device if hasattr(v, 'device') else 'no-device'}", file=sys.stderr)
            else:
                print(f"  {k}: {type(v)}", file=sys.stderr)
        print(f"---------------------------", file=sys.stderr)
        return (samples,)

NODE_CLASS_MAPPINGS = {
    "PGFX_Studio_LTX2Queue": PGFX_Studio_LTX2Queue,
    "PGFX_Studio_Stitcher": PGFX_Studio_Stitcher,
    "PGFX_LTXVLatentUpsampler": PGFX_LTXVLatentUpsampler,
    "PGFX_LTXVCorrectiveMask": PGFX_LTXVCorrectiveMask,
    "PGFX_LatentProbe": PGFX_LatentProbe,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_Studio_LTX2Queue": "???? Legacy ?? LTX-2 Queue Manager",
    "PGFX_Studio_Stitcher": "???? Legacy ??? LTX-2 Video Stitcher",
    "PGFX_LTXVLatentUpsampler": "???? Legacy ?? PGFX LTXV Latent Upsampler",
    "PGFX_LTXVCorrectiveMask": "???? Legacy ??? PGFX LTXV Corrective Mask",
    "PGFX_LatentProbe": "???? Legacy ?? PGFX Latent Probe"
}
