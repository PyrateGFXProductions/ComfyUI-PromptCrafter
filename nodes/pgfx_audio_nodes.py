# ---[PromptCrafter] Early torchaudio compatibility (needed before SpeechBrain import) ---
try:
    import torchaudio
    if not hasattr(torchaudio, 'list_audio_backends'):
        try:
            from torchaudio.backend import list_audio_backends as _list_audio_backends

            def patched_list_audio_backends():
                try:
                    backends = _list_audio_backends()
                    return backends or ["soundfile"]
                except Exception:
                    return ["soundfile"]

            torchaudio.list_audio_backends = patched_list_audio_backends
        except Exception:
            def list_audio_backends():
                return ["soundfile"]
            torchaudio.list_audio_backends = list_audio_backends
except Exception:
    pass
# ---[End Early Patch]---

# ---[PromptCrafter] SpeechBrain/Torch 2.8+ Compatibility Patch---
try:
    import torch
    import speechbrain.utils.importutils
    
    # This patch prevents a RecursionError when using torch >= 2.8 with SpeechBrain's lazy importing.
    # The issue arises from a conflict between Torch's custom op registration and SpeechBrain's `LazyModule`.
    
    # Robust version check (string comparison like "2.10" < "2.8" is flawed)
    try:
        parts = torch.__version__.split('.')
        major = int(parts[0])
        minor = int(parts[1])
        should_patch = major > 2 or (major == 2 and minor >= 1) # Apply to PyTorch 2.1+
    except:
        should_patch = True # Fallback to safe side

    if should_patch:
        # We only patch if the fix isn't already applied.
        if not hasattr(speechbrain.utils.importutils.LazyModule, '_sb_torch_patched'):
            _orig_ensure_module = speechbrain.utils.importutils.LazyModule.ensure_module

            def patched_ensure_module(self, stacklevel):
                try:
                    return _orig_ensure_module(self, stacklevel)
                except (RecursionError, ImportError):
                    # Break recursion loop or handle missing optional dependencies gracefully.
                    # Raising AttributeError here tells callers (like inspect) that the module/attr is not available.
                    raise AttributeError()

            def patched_getattr(self, attr):
                try:
                    # This is the original logic from SpeechBrain's LazyModule.__getattr__
                    return getattr(self.ensure_module(1), attr)
                except (RecursionError, ImportError):
                    # Break recursion loop or handle missing optional dependencies gracefully.
                    raise AttributeError(attr)

            # Apply the patch and mark it as applied.
            speechbrain.utils.importutils.LazyModule.ensure_module = patched_ensure_module
            speechbrain.utils.importutils.LazyModule.__getattr__ = patched_getattr
            speechbrain.utils.importutils.LazyModule._sb_torch_patched = True
            print("[PromptCrafter] SUCCESS: Applied runtime patch to SpeechBrain for Torch 2.8+ compatibility.")

except Exception as e:
    # If speechbrain is not present or another error occurs, we log it but don't crash.
    print(f"[PromptCrafter] INFO: Could not apply SpeechBrain patch. Reason: {e}")
    # Cleanup partially loaded speechbrain to allow downstream imports to try again cleanly
    import sys
    if 'speechbrain' in sys.modules:
        del sys.modules['speechbrain']
    pass
# ---[End of Patch]---
import torch
try:
    from omegaconf import ListConfig
    from omegaconf.base import ContainerMetadata
except ImportError:
    ListConfig = None
    ContainerMetadata = None
import typing # Import typing module to access typing.Any
import collections # Import collections module to access defaultdict
import functools # Import functools for wraps

# Store the original torch.load function
_original_torch_load = torch.load

# Define a patched torch.load that forces weights_only=False
@functools.wraps(_original_torch_load)
def _patched_torch_load(*args, **kwargs):
    kwargs['weights_only'] = False # Force weights_only to False
    return _original_torch_load(*args, **kwargs)

import os
import gc
import torchaudio
import random
import re
import hashlib
import json
import math
import textwrap
import time
import warnings
from pathlib import Path
import sys
from typing import Dict, List, Optional, Tuple, Any

# Monkey-patch for torchaudio API changes in newer versions
if not hasattr(torchaudio, 'AudioMetaData'):
    try:
        # For torchaudio > 2.1, FileInfo is the replacement
        from torchaudio import FileInfo
        torchaudio.AudioMetaData = FileInfo
    except ImportError:
        try:
            # For some older versions, it was moved to backend.common
            from torchaudio.backend.common import AudioMetaData
            torchaudio.AudioMetaData = AudioMetaData
        except ImportError:
            class AudioMetaData: pass
            torchaudio.AudioMetaData = AudioMetaData

if not hasattr(torchaudio, 'list_audio_backends'):
    try:
        # Try to import the new function location
        from torchaudio.backend import list_audio_backends as _list_audio_backends
        def patched_list_audio_backends():
            backends = _list_audio_backends()
            # If the real function returns an empty list, provide a default
            # that pyannote.audio expects, preventing an IndexError.
            if not backends:
                return ["soundfile"]
            return backends
        torchaudio.list_audio_backends = patched_list_audio_backends
    except ImportError:
        # If the import fails entirely, create a dummy that provides the default.
        def list_audio_backends():
            return ["soundfile"]
        torchaudio.list_audio_backends = list_audio_backends

import librosa
import numpy as np

# --- ENHANCED: More robust import and debugging for whisper-ctranslate2 ---
import traceback
try:
    from faster_whisper import WhisperModel as CTranslate2WhisperModel
    CTRANSLATE2_AVAILABLE = True
except Exception as e:
    CTRANSLATE2_AVAILABLE = False
    print("\n" + "="*80)
    print("--- 🎤 [PromptCrafter] AudioSplitterV2 Dependency Warning ---")
    print("Could not import 'faster_whisper'. This package is essential for the node's primary alignment method.")
    print(f"\n[Reason] {type(e).__name__}: {e}")
    print("\n[Action Required]")
    print("To fix this, you need to install the package in your ComfyUI Python environment.")
    print("1. Open a terminal or command prompt.")
    print("2. Navigate to your ComfyUI installation directory.")
    print("3. Run the following command:")
    
    pip_executable = os.path.join(os.path.dirname(sys.executable), "pip")
    if not os.path.exists(pip_executable):
        pip_executable = "pip"

    print(f'\n   `"{pip_executable}" install faster-whisper`\n')
    print("4. Restart ComfyUI after the installation is complete.")
    print("\nThe node will now fall back to a less accurate alignment method, which may produce suboptimal results.")
    print("="*80 + "\n")

import folder_paths
from server import PromptServer

# Suppress warnings
warnings.filterwarnings("ignore", category=UserWarning, module='speechbrain.inference')

class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False

any_typ = AnyType("*")

# ------------------------------------------------------------------------------------
# Helper function to read node descriptions from HELP.md
# ------------------------------------------------------------------------------------
def get_node_description(node_name):
    """Parses HELP.md and extracts the description for a given node class name."""
    try:
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

class PromptCrafter_AudioSplitter_v2:
    DESCRIPTION = get_node_description("PromptCrafter_AudioSplitter_v2")
    RETURN_TYPES = (
        "DICT", "FLOAT", "STRING", "INT", "STRING", "STRING", "STRING",
        "INT", "INT", "INT", "DICT", "STRING"
    ) + tuple(["AUDIO"] * 16) + (any_typ,)

    RETURN_NAMES = (
        "meta", "total_duration", "lyrics_string", "index",
        "start_time", "end_time", "instructions",
        "total_sets", "groups_in_last_set", "frames_per_scene", "audio_meta",
        "output_folder"
    ) + tuple([f"audio_{i}" for i in range(1, 17)]) + ("signal_out",)

    FUNCTION = "run"
    CATEGORY = "☠️PGFX /Audio"

    def __init__(self):
        self.transcription_model = None
        self.model_name = ""
        self.debug_mode = True  # Added debug flag

    @classmethod
    def get_whisper_models(cls):
        """Scans for local Whisper models and returns a list including defaults."""
        default_models = ["tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large-v1", "large-v2", "large-v3", "distil-large-v2"]
        return default_models

    @classmethod
    def INPUT_TYPES(cls, **kwargs):
        optional_inputs = {f"context_{i}": ("STRING", {"default": "", "multiline": True}) for i in range(1, 17)}
        
        return {
            "required": {
                "vocal_audio": ("AUDIO", {"tooltip": "The primary audio track containing vocals."}),
                "srt_or_script_path": ("STRING", {"default": "path/to/your.srt or path/to/your_script.txt"}),
                "trigger": (any_typ,),
                "scene_duration_seconds": ("FLOAT", {"default": 4.0, "min": 1.0, "max": 10.0}),
                "folder_path": ("STRING", {"multiline": False, "default": "video_output"}),
                "enable_auto_queue": ("BOOLEAN", {"default": True}),
                "whisper_model": (cls.get_whisper_models(), {"default": "large-v3"}),
                "language": ("STRING", {"default": "en"}),
                "correction_model": ("STRING", {"default": "ollama/qwen3-vl:8b"}),
                "enable_silence_detection": ("BOOLEAN", {"default": True}),
                "silence_threshold": ("STRING", {"default": "0.1", "multiline": False}),
             },
            "optional": {
                "instrumental_audio": ("AUDIO", {"optional": True}),
                "llm_device": (["Default (GPU)", "CPU"], {"default": "Default (GPU)", "tooltip": "Where local LLM inference should run. 'Default (GPU)' uses configured acceleration; 'CPU' forces CPU for local GGUF/HF models."}),
                "reset_context": ("BOOLEAN", {"default": True, "tooltip": "If enabled, resets local model context before each call to avoid carrying prior conversation state."}),
                **optional_inputs
            }
        }

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return random.random()

    def _debug_print(self, message: str):
        """Helper method for debug printing"""
        if self.debug_mode:
            print(f"[DEBUG] {message}")

    def _load_transcription_model(self, model_name, language):
        if self.transcription_model is None or self.model_name != model_name:
            import whisperx
            self._debug_print(f"Loading whisper model: {model_name}")
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model_path_or_name = model_name
            
            # Check for local model path
            if "/" in model_name:
                possible_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)), 
                    '..', '..', '..', 'models', 'faster-whisper', 
                    f"models--{model_name.replace('/', '--')}"
                )
                if os.path.exists(possible_path):
                    model_path_or_name = possible_path
                    self._debug_print(f"Using local model path: {model_path_or_name}")
            
            try:
                # Apply the monkey patch before loading the model
                torch.load = _patched_torch_load
                self.transcription_model = whisperx.load_model(
                    model_path_or_name, device, language=language, compute_type="float16"
                )
                self.model_name = model_name
                self._debug_print("Model loaded successfully")
            except Exception as e:
                self._debug_print(f"Error loading model: {str(e)}")
                raise
            finally:
                # Always restore the original torch.load after the operation
                torch.load = _original_torch_load
        return self.transcription_model

    def _transcribe_with_ctranslate2(self, audio_path, model_name, language, initial_prompt=""):
        """
        A more accurate transcription method using whisper-ctranslate2 with Silero VAD.
        """
        if not CTRANSLATE2_AVAILABLE:
            raise ImportError("The 'faster-whisper' library is not installed. Please run 'pip install faster-whisper'.")
        
        self._debug_print("Transcribing with high-accuracy ctranslate2 engine (with VAD)...")
        
        try:
            # Initialize the whisper model
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = CTranslate2WhisperModel(model_name, device=device, compute_type="float16")

            # Transcribe with word timestamps and VAD enabled
            segments, _ = model.transcribe(
                audio_path,
                language=language,
                initial_prompt=initial_prompt,
                word_timestamps=True,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500}
            )

            # Reformat the output to match whisperx's structure for compatibility
            whisperx_segments = []
            all_words = []
            for segment in segments:
                words = [{'word': w.word, 'start': w.start, 'end': w.end, 'score': w.probability} for w in segment.words]
                all_words.extend(words)
                whisperx_segments.append({'text': segment.text, 'start': segment.start, 'end': segment.end, 'words': words})
            
            self._debug_print(f"Transcription completed with {len(whisperx_segments)} segments")
            return {'segments': whisperx_segments, 'word_segments': all_words}
        except Exception as e:
            self._debug_print(f"Error in _transcribe_with_ctranslate2: {str(e)}")
            raise

    def _get_ai_corrected_script(self, raw_transcript, ground_truth_script, correction_model, llm_device="Default (GPU)", reset_context=True):
        if not ground_truth_script or not raw_transcript:
            return ground_truth_script
        
        if len(raw_transcript) < 10:
             return ground_truth_script
             
        correction_prompt = textwrap.dedent(f"""
            You are an expert audio transcription editor. Your task is to create a definitive transcript by correcting an AI-generated transcript using the user-provided script as the ground truth.
            **GROUND TRUTH (User-Provided Script):**\n---\n{ground_truth_script}\n---
            **AI-GENERATED TRANSCRIPT (for reference):**\n---\n{raw_transcript}\n---
            **INSTRUCTIONS:**
            1. Use the "GROUND TRUTH" as the authoritative source for the words.
            2. Correct any spelling, punctuation, or word errors in the AI-generated transcript to match the ground truth.
            3. Preserve the line breaks and structure of the "GROUND TRUTH" script.
            4. Return ONLY the final, corrected script text. No commentary.
        """).strip()
        
        try:
            from ..core import pgfx_api_clients as api_clients
            ok, corrected_script = api_clients.query_model_auto(
                correction_model, correction_prompt, prefer_chat=True, temperature=0.0,
                seed=-1, debug_mode=self.debug_mode, timeout=120, debug_title="AudioSplitter Script Correction",
                llm_device=llm_device,
                reset_context=reset_context,
            )
            if ok and corrected_script:
                self._debug_print("Successfully corrected transcript with LLM.")
                return corrected_script
        except ImportError:
            pass
        except Exception as e:
            self._debug_print(f"Warning: LLM script correction failed: {e}")
        return ground_truth_script
 
    def _create_synthetic_alignment(self, texts, starts_samples, samples_per_scene, sample_rate):
        self._debug_print("Creating SYNTHETIC alignment data (fallback mode).")
        word_segments = []
        segments = []
        
        for i, text in enumerate(texts):
            if not text.strip() or "[INSTRUMENTAL]" in text: 
                continue
            
            start_time = starts_samples[i] / sample_rate
            end_time = (starts_samples[i] + samples_per_scene) / sample_rate
            duration = end_time - start_time
            
            words = text.split()
            if not words: continue
            
            word_dur = duration / len(words)
            chunk_words = []
            for w_idx, word in enumerate(words):
                w_start = start_time + (w_idx * word_dur)
                w_end = w_start + word_dur
                w_entry = {'word': word, 'start': w_start, 'end': w_end, 'score': 0.99}
                word_segments.append(w_entry)
                chunk_words.append(w_entry)
                
            segments.append({
                'start': start_time, 'end': end_time, 'text': text, 'words': chunk_words
            })
            
        return {"segments": segments, "word_segments": word_segments}

    def _get_or_create_project_metadata(self, folder_path: str, audio_duration: float, scene_duration: float, audio_waveform, whisper_model, language, correction_model, enable_silence_detection, silence_threshold) -> tuple:
        metadata_file = os.path.join(folder_path, ".project_metadata.json")
        try:
            sample_data = audio_waveform[..., :48000].cpu().numpy().tobytes()
            settings_string = f"{whisper_model}{language}{correction_model}{enable_silence_detection}{silence_threshold}"
            combined_hash_data = sample_data + settings_string.encode('utf-8')
            project_hash = hashlib.md5(combined_hash_data).hexdigest()[:16]
        except Exception as e:
            self._debug_print(f"Error creating project hash: {str(e)}")
            project_hash = "unknown"

        total_groups = math.ceil(audio_duration / scene_duration)
        expected_sets = math.ceil(total_groups / 16)
        
        current_project = {
            "audio_duration": audio_duration, 
            "scene_duration": scene_duration, 
            "project_hash": project_hash, 
            "expected_sets": expected_sets, 
            "total_groups": total_groups,
            "whisper_model": whisper_model,
            "language": language,
            "correction_model": correction_model,
            "enable_silence_detection": enable_silence_detection,
            "silence_threshold": silence_threshold
        }

        if os.path.exists(metadata_file):
            try:
                with open(metadata_file, 'r') as f: 
                    existing_metadata = json.load(f)
                is_same_project = (
                    abs(existing_metadata.get("audio_duration", 0) - audio_duration) < 1.0 and
                    existing_metadata.get("project_hash") == project_hash and
                    abs(existing_metadata.get("scene_duration", 0) - scene_duration) < 0.1
                )
                if is_same_project:
                    return existing_metadata, False
                else:
                    return current_project, True
            except Exception as e:
                self._debug_print(f"Error reading metadata: {str(e)}")
                return current_project, True
        else:
            return current_project, True

    def _save_project_metadata(self, folder_path: str, metadata: dict):
        metadata_file = os.path.join(folder_path, ".project_metadata.json")
        try:
            with open(metadata_file, 'w') as f: 
                json.dump(metadata, f, indent=2)
        except Exception as e:
            self._debug_print(f"Error saving metadata: {str(e)}")

    def _get_smart_output_folder(self, folder_name: str, audio_duration: float, scene_duration: float, audio_waveform, whisper_model, language, correction_model, enable_silence_detection, silence_threshold) -> tuple:
        folder_name = re.sub(r'[<>:"|?*]', '_', folder_name.strip() or "video_output").replace('..', '').replace('/', '_').replace('\\', '_')
        base_output = folder_paths.get_output_directory()
        target_folder = os.path.join(base_output, folder_name)
        os.makedirs(target_folder, exist_ok=True)
        
        metadata, is_new_project = self._get_or_create_project_metadata(
            target_folder, audio_duration, scene_duration, audio_waveform, 
            whisper_model, language, correction_model, enable_silence_detection, silence_threshold
        )

        if is_new_project and (any(f for f in os.listdir(target_folder) if f != ".project_metadata.json") or os.path.exists(os.path.join(target_folder, "FINAL_VIDEO.mp4"))):
            version = 2
            while os.path.exists(os.path.join(base_output, f"{folder_name}_v{version}")):
                version += 1
            new_folder_name = f"{folder_name}_v{version}"
            target_folder = os.path.join(base_output, new_folder_name)
            os.makedirs(target_folder, exist_ok=True)
            self._debug_print(f"Auto-Version: New project/settings detected → creating '{new_folder_name}'")
        
        self._save_project_metadata(target_folder, metadata)
        return target_folder, metadata

    def _calculate_sets_and_instructions(self, audio, index, scene_duration_seconds, enable_auto_queue=True):
        instructions = ""
        end_time_str = "0:00"
        total_sets = 0
        groups_in_last_set = 0
        durations_frames_full = []

        try:
            waveform = audio["waveform"]
            sample_rate = audio["sample_rate"]
        except Exception as e:
            self._debug_print(f"Error accessing audio data: {str(e)}")
            return ("❌ Expected audio to be a dict.", "0:00", 0, 0, 0, {"durations_frames": []})

        fps = 25
        frames_per_scene = int(round(fps * scene_duration_seconds))
        # NOTE: _adjust_frames_for_humo intentionally removed — it introduced a
        # ~1% timing warp (frames_per_scene → H.264-aligned) that accumulated
        # across scenes, causing WhisperX word timestamps to drift from scene
        # boundaries. Scene-frame counts should match the user's intended duration.
        
        groups_per_set = 16
        samples_per_frame = sample_rate / fps

        try:
            num_samples = waveform.shape[-1]
            audio_duration = num_samples / sample_rate
        except Exception as e:
            self._debug_print(f"Error calculating audio duration: {str(e)}")
            return ("❌ Failed to compute audio duration.", "0:00", 0, 0, frames_per_scene, {"durations_frames": []})

        total_audio_frames = int(num_samples / samples_per_frame) if num_samples > 0 else 0

        if total_audio_frames > 0:
            full_groups = math.floor(total_audio_frames / frames_per_scene)
            leftover_frames = total_audio_frames - full_groups * frames_per_scene
            if full_groups > 0:
                durations_frames_full.extend([frames_per_scene] * full_groups)
            if leftover_frames > 0:
                durations_frames_full.append(leftover_frames)
            if durations_frames_full and durations_frames_full[0] != frames_per_scene:
                durations_frames_full[0] = frames_per_scene

            total_groups = len(durations_frames_full)
            total_sets = math.ceil(total_groups / groups_per_set) if total_groups > 0 else 0
            groups_in_last_set = (total_groups % groups_per_set if (total_groups % groups_per_set) != 0 else (groups_per_set if total_groups > 0 else 0))

        minutes = int(audio_duration // 60)
        seconds = int(audio_duration % 60)
        end_time_str = f"{minutes}:{seconds:02d}"

        if total_sets == 0:
            instructions = "❌ Audio too short. No runs required."
        elif total_sets == 1:
            disable_text = "group 16" if groups_in_last_set == 15 else f"groups {groups_in_last_set+1}–16"
            if groups_in_last_set == 16:
                instructions = f"⚠️  1 run needed\n✅ Using all 16 groups"
            else:
                instructions = f"⚠️  Audio is less than 16 groups ({groups_in_last_set} groups detected)\n❗ Mute {disable_text} on 'Fast Groups Muter'\n🔴 Cancel this run and re-run after muting"
        elif groups_in_last_set != 16:
            disable_text = "group 16" if groups_in_last_set == 15 else f"groups {groups_in_last_set+1}–16"
            if enable_auto_queue:
                queued_now = 1 + max(0, total_sets - 2)
                instructions = (
                    f"⚠️  {total_sets} runs needed\n"
                    f"✅ {queued_now} run(s) currently in queue\n"
                    f"❗ Mute {disable_text} on 'Fast Groups Muter', then hit RUN one more time"
                )
            else:
                instructions = f"⚠️  {total_sets} runs needed\n🔴 Auto-queue is DISABLED\n❗ Manually run each set and mute {disable_text} on final run"
        else:
            if enable_auto_queue:
                instructions = f"⚠️  {total_sets} runs needed\n✅ All {total_sets} runs are auto-queued"
            else:
                instructions = f"⚠️  {total_sets} runs needed\n🔴 Auto-queue is DISABLED\n❗ Manually run all {total_sets} sets"

        if total_sets > 1 and index > 0:
            if index + 1 == total_sets:
                if groups_in_last_set != 16:
                    disable_text = "group 16" if groups_in_last_set == 15 else f"groups {groups_in_last_set+1}–16"
                    instructions = f"🏁 Final run ({index + 1} of {total_sets})\n✅ Make sure {disable_text} are muted!"
                else:
                    instructions = f"🏁 Final run ({index + 1} of {total_sets}) in progress..."
            else:
                if groups_in_last_set != 16:
                    disable_text = "group 16" if groups_in_last_set == 15 else f"groups {groups_in_last_set+1}–16"
                    instructions = (
                        f"⏳ Run {index + 1} of {total_sets} in progress\n"
                        f"📝 Reminder: {disable_text} need to be muted on last run"
                    )
                else:
                    instructions = f"⏳ Run {index + 1} of {total_sets} in progress..."

        start_group = index * 16
        end_group = min(start_group + 16, len(durations_frames_full))
        durations_frames_this_set = durations_frames_full[start_group:end_group] if durations_frames_full else []

        return (instructions, end_time_str, total_sets, groups_in_last_set, frames_per_scene, {"durations_frames": durations_frames_this_set})

    def _maybe_auto_queue(self, total_sets: int, groups_in_last_set: int, index: int, enable: bool):
        if not enable:
            self._debug_print("Auto-queue disabled by user toggle.")
            return

        if index == 0:
            runs = 0
            if total_sets > 1:
                if groups_in_last_set == 16:
                    runs = max(0, total_sets - 1)
                else:
                    runs = max(0, total_sets - 2)

            if runs > 0:
                self._debug_print(f"Auto-queuing {runs} extra job(s).")
                for _ in range(runs):
                    try:
                        PromptServer.instance.send_sync("impact-add-queue", {})
                    except Exception:
                        self._debug_print("Auto-queue skipped (Impact Pack not installed).")
            else:
                self._debug_print("No extra jobs needed for auto-queuing.")
        else:
            self._debug_print(f"Skipping auto-queue check (current index: {index}).")

    def _send_popup_notification(self, message: str, message_type: str = "info", title: str = "Audio Splitter"):
        try:
            PromptServer.instance.send_sync("vrgdg_instructions_popup", {"message": message, "type": message_type, "title": title})
        except AttributeError:
            self._debug_print("Popup notification skipped (VRGDG not installed).")
        except Exception as e:
            self._debug_print(f"Error sending popup notification: {str(e)}")

    def _adjust_frames_for_humo(self, frames: int) -> int:
        return 4 * ((frames + 2) // 4) + 1

    def _load_vad_model(self):
        try:
            model, utils = torch.hub.load(repo_or_dir='snakers4/silero-vad', model='silero_vad', force_reload=False, onnx=False)
            (get_speech_timestamps, _, read_audio, *_) = utils
            return model, get_speech_timestamps
        except Exception as e:
            self._debug_print(f"Error loading VAD model: {e}")
            return None, None

    def _is_speech_present(self, vad_model, get_speech_timestamps, waveform, sample_rate, threshold):
        if vad_model is None: 
            return True
        try:
            mono_waveform = waveform.mean(dim=0)
            speech_timestamps = get_speech_timestamps(mono_waveform, vad_model, sampling_rate=sample_rate, threshold=threshold)
            return len(speech_timestamps) > 0
        except Exception as e:
            self._debug_print(f"Error in _is_speech_present: {str(e)}")
            return True  # Default to True if VAD fails

    def _is_instrumental_present(self, waveform, threshold=1e-4):
        if waveform is None or waveform.numel() == 0: 
            return False
        return torch.max(torch.abs(waveform)) > threshold

    def _get_aligned_text(self, text_to_align, audio_path, model, language, output_folder):
        alignment_result = {"segments": [], "word_segments": []}
        run_hash = ""
        
        try:
            hasher = hashlib.md5()
            with open(audio_path, 'rb') as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            hasher.update(str(self.model_name).encode('utf-8'))
            run_hash = hasher.hexdigest()[:16]
            cache_path = os.path.join(output_folder, f"alignment_cache_ct2_{run_hash}.json")
            
            if os.path.exists(cache_path):
                self._debug_print("Loading cached alignment.")
                with open(cache_path, 'r') as f:
                    return json.load(f)

            if not CTRANSLATE2_AVAILABLE:
                self._debug_print("Warning: whisper-ctranslate2 is not available. Alignment will be inaccurate.")
                return {"segments": [], "word_segments": []} 

            # If we proceed, it means CTRANSLATE2_AVAILABLE is True
            alignment_result = self._transcribe_with_ctranslate2(audio_path, self.model_name, language, initial_prompt=text_to_align)
            
            if 'word_segments' in alignment_result:
                validated_word_segments = []
                for word in alignment_result.get('word_segments', []):
                    if 'start' in word:
                        validated_word_segments.append(word)
                alignment_result['word_segments'] = validated_word_segments

            self._debug_print("Saving alignment cache.")
            with open(cache_path, 'w') as f:
                json.dump(alignment_result, f)
                
            return alignment_result

        except Exception as e:
            self._debug_print(f"Error during word alignment: {e}")
            return {"segments": [], "word_segments": []} 

    def _count_index_from_folder(self, folder_path: str) -> int:
        """Matches VRGDG_GetIndexNumber: count *-audio.mp4 as sets already done."""
        try:
            if not os.path.isdir(folder_path):
                return 0
            return len([
                f for f in os.listdir(folder_path)
                if f.lower().endswith(".mp4") and "-audio" in f.lower()
            ])
        except Exception as e:
            self._debug_print(f"Failed to scan folder '{folder_path}': {e}")
            return 0

    def run(self, vocal_audio, srt_or_script_path, trigger, scene_duration_seconds, folder_path, enable_auto_queue, whisper_model, language, correction_model, enable_silence_detection=True, silence_threshold=0.1, instrumental_audio=None, llm_device="Default (GPU)", reset_context=True, **kwargs):
        self._debug_print("Starting AudioSplitter V2 run")
        
        try:
            if isinstance(silence_threshold, str) and silence_threshold.strip() == '':
                valid_silence_threshold = 0.1
            else:
                valid_silence_threshold = float(silence_threshold)
        except (ValueError, TypeError):
            valid_silence_threshold = 0.1

        if not isinstance(vocal_audio, dict) or "waveform" not in vocal_audio:
            error_msg = "ERROR: Vocal audio is missing or invalid. Check connections."
            self._debug_print(error_msg)
            dummy_meta = {"error": error_msg}
            # Return a dummy tuple with correct types to prevent workflow crash
            return (dummy_meta, 0.0, "", 0, "0:00", "0:00", error_msg, 0, 0, 0, dummy_meta, "", *([None] * 16), any_typ)
        
        waveform, sample_rate = vocal_audio["waveform"], int(vocal_audio["sample_rate"])
        instrumental_waveform = instrumental_audio.get("waveform") if isinstance(instrumental_audio, dict) else None

        if waveform.ndim == 2: 
            waveform = waveform.unsqueeze(0)
        if instrumental_waveform is not None and instrumental_waveform.ndim == 2:
            instrumental_waveform = instrumental_waveform.unsqueeze(0)

        total_duration = float(waveform.shape[-1]) / float(sample_rate)

        # ---- Check if metadata exists BEFORE creating folder/metadata ----
        base_output = folder_paths.get_output_directory()
        temp_folder = os.path.join(base_output, folder_path.strip() if folder_path.strip() else "video_output")
        metadata_existed_before = os.path.exists(os.path.join(temp_folder, ".project_metadata.json"))

        output_folder, project_metadata = self._get_smart_output_folder(
            folder_path, total_duration, scene_duration_seconds, waveform,
            whisper_model, language, correction_model, enable_silence_detection, valid_silence_threshold
        )
        
        # ---- index from folder (replaces TriggerCounter + GetIndexNumber) ----
        set_index = self._count_index_from_folder(output_folder)
        self._debug_print(f"Detected set_index={set_index} from folder: {output_folder}")
        
        # Use a temp folder inside output directory to avoid cross-drive issues on Windows
        temp_dir = os.path.join(folder_paths.get_output_directory(), "PromptCrafter_Temp")
        os.makedirs(temp_dir, exist_ok=True)
        temp_audio_path = os.path.join(temp_dir, f"audiosplitter_temp_{random.randint(1000, 9999)}.wav")
        torchaudio.save(temp_audio_path, waveform.squeeze(0).cpu(), sample_rate)
        
        scene_count = 16 
        transcription_model = self._load_transcription_model(whisper_model, language)

        instructions, end_time_str_hr, total_sets, groups_in_last_set, frames_per_scene, audio_meta = self._calculate_sets_and_instructions(vocal_audio, set_index, scene_duration_seconds, enable_auto_queue)
        
        self._maybe_auto_queue(total_sets, groups_in_last_set, set_index, enable_auto_queue)

        # --- NOTIFICATION LOGIC ---
        if set_index == 0:
            is_rerun = metadata_existed_before
            
            if is_rerun:
                metadata_file = os.path.join(output_folder, ".project_metadata.json")
                try:
                    with open(metadata_file, 'r') as f: 
                        existing_meta = json.load(f)
                    is_same_audio = (
                        abs(existing_meta.get("audio_duration", 0) - total_duration) < 1.0 and
                        abs(existing_meta.get("scene_duration", 0) - scene_duration_seconds) < 0.1
                    )
                    is_rerun = is_same_audio
                except Exception as e:
                    self._debug_print(f"Error reading existing metadata: {str(e)}")
                    is_rerun = False
            
            if total_sets == 1 and groups_in_last_set != 16:
                if is_rerun:
                    disable_text = "group 16" if groups_in_last_set == 15 else f"groups {groups_in_last_set+1}–16"
                    rerun_instructions = (
                        f"⏳ Run 1 of 1 in progress\n"
                        f"📝 Reminder: {disable_text} should be muted"
                    )
                    instructions = rerun_instructions
                    self._send_popup_notification(rerun_instructions, "warning", "⏳ RUN IN PROGRESS")
                else:
                    self._send_popup_notification(instructions, "red", "🚨 CANCEL & RECONFIGURE REQUIRED")
            elif total_sets > 1 and groups_in_last_set != 16:
                self._send_popup_notification(instructions, "red", "🎬 STARTING WORKFLOW")
            else:
                self._send_popup_notification(instructions, "info", "🎬 STARTING WORKFLOW")
                
        elif set_index > 0 and set_index + 1 < total_sets:
            if groups_in_last_set != 16:
                self._send_popup_notification(instructions, "yellow", "⏳ PROGRESS UPDATE")
            
        elif set_index + 1 == total_sets:
            if groups_in_last_set != 16:
                self._send_popup_notification(instructions, "red", "🏁 FINAL RUN - ACTION REQUIRED!")
            else:
                self._send_popup_notification(instructions, "green", "🏁 FINAL RUN")

        fps = 25
        actual_seconds_per_scene = frames_per_scene / fps
        samples_per_scene = int(frames_per_scene * sample_rate / fps + 0.5)
        offset_samples = int(round(set_index * scene_count * samples_per_scene))
        start_sec = set_index * 16 * actual_seconds_per_scene 

        vad_model, get_speech_timestamps = (self._load_vad_model() if enable_silence_detection else (None, None))

        ground_truth_script = ""
        if os.path.isfile(srt_or_script_path):
             if srt_or_script_path.lower().endswith('.srt'):
                try:
                    with open(srt_or_script_path, 'r', encoding='utf-8') as f:
                        srt_content = f.read()
                    text_lines = [line for line in srt_content.splitlines() if not line.isdigit() and '-->' not in line and line.strip()]
                    ground_truth_script = " ".join(text_lines)
                except Exception as e:
                    self._debug_print(f"Error reading SRT file: {str(e)}")
             else:
                try:
                    with open(srt_or_script_path, 'r', encoding='utf-8') as f: 
                        ground_truth_script = f.read()
                except Exception as e:
                    self._debug_print(f"Error reading script file: {str(e)}")
        elif srt_or_script_path:
             ground_truth_script = srt_or_script_path
        
        segments = []
        starts_samples = []
        starts = [int(round(offset_samples + i * samples_per_scene)) for i in range(scene_count)]
        starts_samples.extend(starts)

        for i in range(scene_count):
            start_samp = starts[i]
            end_samp = start_samp + samples_per_scene
            vocal_chunk = torch.zeros((1, waveform.shape[1], samples_per_scene), dtype=waveform.dtype)
            
            if start_samp < waveform.shape[-1]:
                vocal_chunk_unpadded = waveform[..., start_samp:min(end_samp, waveform.shape[-1])].contiguous().clone()
                pad_size = samples_per_scene - vocal_chunk_unpadded.shape[-1]
                if pad_size > 0:
                    vocal_chunk_unpadded = torch.nn.functional.pad(vocal_chunk_unpadded, (0, pad_size))
                vocal_chunk = vocal_chunk_unpadded

            instrumental_chunk = None
            if instrumental_waveform is not None:
                instrumental_chunk = torch.zeros((1, instrumental_waveform.shape[1], samples_per_scene), dtype=instrumental_waveform.dtype)
                if start_samp < instrumental_waveform.shape[-1]:
                    instrumental_chunk_unpadded = instrumental_waveform[..., start_samp:min(end_samp, instrumental_waveform.shape[-1])].contiguous().clone()
                    pad_size = samples_per_scene - instrumental_chunk_unpadded.shape[-1]
                    if pad_size > 0:
                        instrumental_chunk_unpadded = torch.nn.functional.pad(instrumental_chunk_unpadded, (0, pad_size))
                    instrumental_chunk = instrumental_chunk_unpadded

            final_chunk = vocal_chunk
            is_speech = self._is_speech_present(vad_model, get_speech_timestamps, vocal_chunk[0], sample_rate, valid_silence_threshold) if enable_silence_detection else True
            
            if not is_speech:
                # FIXED: Return ZEROS instead of instrumental chunk if instrumental is missing.
                # This ensures VHS always gets a valid audio tensor, preventing the crash.
                final_chunk = instrumental_chunk if instrumental_chunk is not None else torch.zeros_like(vocal_chunk)
            
            segments.append({"waveform": final_chunk, "sample_rate": sample_rate})

        # --- TRANSCRIPTION & ALIGNMENT ---
        try:
            full_raw_transcription = transcription_model.transcribe(waveform.squeeze(0).mean(dim=0).cpu().numpy())
            full_raw_text = "".join([seg['text'] for seg in full_raw_transcription.get("segments", [])])
            corrected_script = self._get_ai_corrected_script(
                full_raw_text,
                ground_truth_script,
                correction_model,
                llm_device=llm_device,
                reset_context=reset_context,
            )
            
            alignment_result = self._get_aligned_text(
                corrected_script, temp_audio_path, transcription_model, language, output_folder
            )
        except Exception as e:
            self._debug_print(f"Error in transcription/alignment: {str(e)}")
            alignment_result = {"segments": [], "word_segments": []}
            corrected_script = ground_truth_script
        
        current_set_lyrics = []
        alignment_words = alignment_result.get("word_segments", [])
        fallback_transcriptions = [] 

        for i in range(scene_count):
            scene_start_time = start_sec + (i * actual_seconds_per_scene)
            scene_end_time = scene_start_time + actual_seconds_per_scene
            
            scene_text = ""
            
            # --- Check Audio VAD for this specific chunk ---
            chunk_vad_check = self._is_speech_present(vad_model, get_speech_timestamps, segments[i]["waveform"][0], sample_rate, valid_silence_threshold) if enable_silence_detection else True
            
            if not chunk_vad_check:
                # --- SILENCE DETECTED: SMART B-ROLL LOGIC ---
                # This ensures we don't send an empty string for "B-roll" segments
                scene_text = "" 
            else:
                if alignment_words:
                    words_in_scene = [
                        w['word'] for w in alignment_words 
                        if w.get('start', -1) >= scene_start_time and w.get('end', -1) <= scene_end_time
                    ]
                    scene_text = " ".join(words_in_scene).strip()
                
                if not scene_text:
                    try:
                        chunk_audio = segments[i]["waveform"].squeeze(0).mean(dim=0).cpu().numpy()
                        chunk_res = transcription_model.transcribe(chunk_audio, language=language)
                        scene_text = " ".join([s['text'] for s in chunk_res.get("segments", [])]).strip()
                    except Exception as e:
                        self._debug_print(f"Error transcribing chunk {i}: {str(e)}")
                        scene_text = ""
            
            fallback_transcriptions.append(scene_text) 
            
            # --- PROMPT CONSTRUCTION ---
            ctx = kwargs.get(f"context_{i+1}", "").strip()
            
            if not scene_text:
                # If SILENCE: Insert B-Roll prompt!
                if ctx:
                    final_text = f"{ctx} [INSTRUMENTAL]"
                else:
                    final_text = "(Instrumental) Cinematic B-roll footage, atmosphere, establishing shot [INSTRUMENTAL]"
            else:
                if ctx:
                    final_text = f"{ctx}, {scene_text}"
                else:
                    final_text = scene_text

            current_set_lyrics.append(final_text.replace("|", ""))

        if not alignment_words:
             alignment_result = self._create_synthetic_alignment(
                 fallback_transcriptions, starts_samples, samples_per_scene, sample_rate
             )
             self._debug_print(f"Generated synthetic alignment for {len(alignment_result['word_segments'])} words.")

        lyrics_text = " | ".join(current_set_lyrics)

        if self.transcription_model is not None:
            self._debug_print("Unloading whisperx model...")
            del self.transcription_model
            self.transcription_model = None
            gc.collect()
        
        end_sec = min(start_sec + 16 * actual_seconds_per_scene, total_duration)
        start_time_str, end_time_str = fmt_time(start_sec), fmt_time(end_sec)
        
        
        instrumental_cues = []
        if lyrics_text:
            parts = lyrics_text.split('|')
            for i in range(16):
                part = parts[i].strip() if i < len(parts) else ""
                match = re.search(r'\[INSTRUMENTAL(?:\s*([^\\]+))?\]', part, re.IGNORECASE)
                if match:
                    cue = match.group(1).strip() if match.group(1) else "Instrumental"
                    instrumental_cues.append(cue)
                else:
                    instrumental_cues.append(None)
        else:
            instrumental_cues = [None] * 16

        meta = {
            "durations": [actual_seconds_per_scene] * 16,
            "durations_frames": [frames_per_scene] * 16,
            "offset_seconds": start_sec,
            "starts": starts_samples,
            "sample_rate": sample_rate,
            "fps": fps,
            "audio_total_duration": total_duration,
            "outputs_count": len(segments),
            "output_folder": output_folder,
            "project_metadata": project_metadata,
            "alignment_result": alignment_result,
            "instrumental_cues": instrumental_cues,
            "language": language,
            "vocal_audio": vocal_audio
        }

        self._debug_print("AudioSplitter V2 run completed successfully")
        return (meta, total_duration, lyrics_text, set_index, start_time_str, end_time_str, instructions, total_sets, groups_in_last_set, frames_per_scene, meta, output_folder, *tuple(segments[:16]), any_typ)

def fmt_time(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{int(s):02d}"

NODE_CLASS_MAPPINGS = {
    "PromptCrafter_AudioSplitter_v2": PromptCrafter_AudioSplitter_v2,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_AudioSplitter_v2": "???? Legacy ?? Audio Splitter v2",
}
