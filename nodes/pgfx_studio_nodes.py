import textwrap
import re
import os
import time
import hashlib
import traceback
import torch
import torchaudio
import folder_paths



# Attempt to import dependent nodes
nodes_sampler = None
nodes_controlnet = None
viseme_utils = None

try:
    from g2p_en import G2p
    from PIL import Image, ImageDraw
    from . import pgfx_creator_nodes as creator_nodes
    from . import pgfx_audio_srt as PromptCrafter_SRTCreator
    from ..core import pgfx_api_clients as api_clients
    from ..core import pgfx_config as config
    from ..utils import pgfx_utils as utils
    from ..utils import pgfx_json_utils as json_utils
    from ..core.profiles import pgfx_sound_engineer_profiles as sound_engineer_profiles
    from ..core.profiles import pgfx_screenwriter_profiles as screenwriter_profiles
    from ..core.profiles import pgfx_editor_profiles as editor_profiles
    from ..core.profiles import pgfx_director_profiles as director_profiles
    from . import pgfx_studio_sampler as nodes_sampler
    from . import pgfx_studio_controlnet as nodes_controlnet
    from ..utils import pgfx_viseme_utils as viseme_utils
    import server

    import numpy as np
    import imageio
    import json
except ImportError as e:
    print(f"[PromptCrafter Studio] ImportError during initialization: {e}")
    # Define minimal fallbacks for ALL imported modules to prevent NameError
    if 'sound_engineer_profiles' not in locals() and 'sound_engineer_profiles' not in globals():
        class _SoundFallback:
            @staticmethod
            def get_profile_options(): return ["Error: Missing Dependencies"]
            NAMED_SOUND_ENGINEER_PROFILES = {}
        sound_engineer_profiles = _SoundFallback()
    if 'director_profiles' not in locals() and 'director_profiles' not in globals():
        class _DirectorFallback:
            @staticmethod
            def get_director_profile_options(): return ["Error: Missing Dependencies"]
            @staticmethod
            def _load_director_profiles(): pass
            NAMED_DIRECTOR_PROFILES = {}
        director_profiles = _DirectorFallback()
    if 'screenwriter_profiles' not in locals() and 'screenwriter_profiles' not in globals():
        class _ScreenwriterFallback:
            @staticmethod
            def get_screenwriter_profile_options(): return ["Error: Missing Dependencies"]
            NAMED_SCREENWRITER_PROFILES = {}
        screenwriter_profiles = _ScreenwriterFallback()
    if 'editor_profiles' not in locals() and 'editor_profiles' not in globals():
        class _EditorFallback:
            @staticmethod
            def get_editor_profile_options(): return ["Error: Missing Dependencies"]
            NAMED_EDITOR_PROFILES = {}
        editor_profiles = _EditorFallback()
    if 'creator_nodes' not in locals() and 'creator_nodes' not in globals():
        class _CreatorFallback:
            @staticmethod
            def get_combined_models(): return ["Error: Missing Dependencies"]
        creator_nodes = _CreatorFallback()
    if 'utils' not in locals() and 'utils' not in globals():
        class _UtilsFallback:
            @staticmethod
            def _unique_keep_order(l): return l
        utils = _UtilsFallback()
    if 'api_clients' not in locals() and 'api_clients' not in globals():
        api_clients = None
    if 'json_utils' not in locals() and 'json_utils' not in globals():
        json_utils = None
    if 'PromptCrafter_SRTCreator' not in locals() and 'PromptCrafter_SRTCreator' not in globals():
        PromptCrafter_SRTCreator = None
    
    print("[PromptCrafter Studio] Some dependencies are missing. Some features may be disabled.")
except Exception as e:
    print(f"[PromptCrafter Studio] Unexpected error during node initialization: {e}")
    traceback.print_exc()

if "config" not in globals():
    class _StudioConfigFallback:
        LLM_DEVICE_OPTIONS = ["Default (GPU)", "CPU"]
        DEFAULT_LLM_DEVICE = "Default (GPU)"
        DEFAULT_LLM_STATELESS = True
    config = _StudioConfigFallback()

# Optional runtime capabilities. Keep these defined even when optional deps fail.
VAD_AVAILABLE = hasattr(torch, "hub")
EMOTION_REC_AVAILABLE = False
EncoderClassifier = None

try:
    # Preferred modern SpeechBrain path.
    from speechbrain.inference.classifiers import EncoderClassifier as _SBEncoderClassifier
    EncoderClassifier = _SBEncoderClassifier
    EMOTION_REC_AVAILABLE = True
except Exception:
    try:
        # Legacy fallback path used by older SpeechBrain releases.
        from speechbrain.pretrained import EncoderClassifier as _SBEncoderClassifier
        EncoderClassifier = _SBEncoderClassifier
        EMOTION_REC_AVAILABLE = True
    except Exception:
        EMOTION_REC_AVAILABLE = False



# --- NEW HELPER FOR MODEL SELECTION ---
def _normalize_model_name(model_entry):
    if isinstance(model_entry, (list, tuple)) and model_entry:
        return model_entry[0]
    return model_entry

def _select_model_default(sorted_llm_models, predicate, fallback="disabled"):
    for model_entry in sorted_llm_models:
        model_name = _normalize_model_name(model_entry)
        if isinstance(model_name, str) and predicate(model_name):
            return model_name
    if sorted_llm_models:
        first = _normalize_model_name(sorted_llm_models[0])
        return first if isinstance(first, str) else fallback
    return fallback

def _get_sorted_models_by_preference(all_llm_models):
    """Optimized model sorting with better fallback logic"""
    if not all_llm_models:
        return []

    # Common GPU-friendly quants - higher preference
    quant_preference = ['q4_k_m', 'q5_k_m', 'q6_k', 'q4_0', 'q5_0', 'q4_1', 'q5_1', 'q3_k_m', 'q2_k']

    def get_model_rank(model_entry):
        model_name = _normalize_model_name(model_entry)
        if not isinstance(model_name, str):
            return 2
        model_name = model_name.lower()

        # Check for specific problematic models
        if "qwen3-vl-8b-thinking" in model_name and "q8_0" in model_name:
            return 3  # Lower priority for Q8_0 of this specific model

        # Prefer non-Q8_0 models that have a known good quant type
        for quant in quant_preference:
            if quant in model_name:
                return 0  # Highest preference

        # Q8_0 is next, as it works but might be slow on GPU
        if 'q8_0' in model_name:
            return 1  # Medium preference

        # Everything else (like F16, F32, or unknown) is last
        return 2  # Lowest preference

    return sorted(all_llm_models, key=get_model_rank)

def _studio_llm_runtime_optional_inputs():
    device_options = getattr(config, "LLM_DEVICE_OPTIONS", ["Default (GPU)", "CPU"])
    # Studio defaults are GPU-first to avoid accidental CPU fallback on long video planning jobs.
    default_device = "Default (GPU)"
    default_reset = getattr(config, "DEFAULT_LLM_STATELESS", True)
    return {
        "llm_device": (
            device_options,
            {
                "default": default_device,
                "tooltip": "Where local LLM inference should run. 'Default (GPU)' uses configured acceleration; 'CPU' forces CPU for local GGUF/HF models.",
            },
        ),
        "reset_context": (
            "BOOLEAN",
            {
                "default": default_reset,
                "tooltip": "If enabled, resets local model context before each call to avoid carrying prior conversation state.",
            },
        ),
    }


# --- THE PRODUCER ---
class PGFX_Studio_Producer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project_name": ("STRING", {"default": "MyMovie"}),
                "resolution": ([
                    # Standard Def
                    "640x480",   # 4:3
                    "720x480",   # 3:2
                    "832x480",   # ~1.73:1
                    "854x480",   # 16:9 SD
                    # Standard Def Vertical
                    "480x640",
                    "480x720",
                    # HD & FHD
                    "1024x576",  # 16:9
                    "1280x720",  # 16:9 HD
                    "1920x1080", # 16:9 FHD
                    "576x1024", "720x1280"], {"default": "854x480"}),
                "fps": ("INT", {"default": 24, "min": 1, "max": 60}),
                "root_output_path": ("STRING", {"default": "PromptCrafter_Studio"}),
            }
        }
    RETURN_TYPES = ("DICT",)
    RETURN_NAMES = ("PROJECT_CONFIG",)
    FUNCTION = "configure"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"

    def configure(self, project_name, resolution, fps, root_output_path):
        width, height = map(int, resolution.split("x"))
        return ({
            "project_name": project_name,
            "width": width,
            "height": height,
            "fps": fps,
            "root_path": root_output_path
        },)

# --- THE SOUND ENGINEER ---
class PGFX_Studio_SoundEngineer:
    """
    Stateful: caches VAD/emotion models at class-level for reuse.
    Reset occurs on process restart or node reload.
    """
    _vad_model = None
    _get_speech_timestamps = None
    _emotion_classifier = None
    _emotion_model_failed = False

    def _load_vad_model(self):
        if not VAD_AVAILABLE:
            return False
        if self._vad_model is None:
            try:
                # Silero VAD model with weights_only=False
                self._vad_model, utils = torch.hub.load(
                    repo_or_dir='snakers4/silero-vad',
                    model='silero_vad',
                    force_reload=False,
                    onnx=False,
                    trust_repo=True  # Add this parameter
                )
                self._get_speech_timestamps = utils[0]
                print("[Sound Engineer] VAD model loaded successfully.")
                return True
            except Exception as e:
                print(f"\033[91m[Sound Engineer] Error loading VAD model: {e}\033[0m")
                return False
        return True


    def _is_speech_present(self, waveform, sample_rate, threshold=0.5):
        if self._vad_model is None or self._get_speech_timestamps is None:
            return True # Default to assuming speech if VAD is not available

        # Silero VAD requires a 16000Hz sample rate. Resample if necessary.
        if sample_rate != 16000:
            try:
                import torchaudio.transforms as T
                # Handle resizing if on GPU/CPU differently or ensure device compatibility
                resampler = T.Resample(orig_freq=sample_rate, new_freq=16000).to(waveform.device)
                resampled_waveform = resampler(waveform)
                sample_rate = 16000
            except Exception as e:
                print(f"\033[91m[Sound Engineer] Warning: Failed to resample audio for VAD. Assuming speech is present. Error: {e}\033[0m")
                return True
        else:
            resampled_waveform = waveform

        # VAD model expects a 1-dimensional tensor
        if resampled_waveform.ndim > 1:
            mono_waveform = resampled_waveform.mean(dim=0)
        else:
            mono_waveform = resampled_waveform
        
        try:
            speech_timestamps = self._get_speech_timestamps(
                mono_waveform, self._vad_model,
                sampling_rate=sample_rate,
                threshold=threshold
            )
            return len(speech_timestamps) > 0
        except Exception as e:
            print(f"[Sound Engineer] VAD Processing failed, defaulting to True. Error: {e}")
            return True

    def _load_emotion_model(self):
        if not EMOTION_REC_AVAILABLE:
            return False
        if self._emotion_classifier is None:
            try:
                # Define the model source and a user-friendly local directory name
                source_repo = "speechbrain/emotion-recognition-wav2vec2-IEMOCAP"
                local_model_name = "emotion-recognition-wav2vec2-IEMOCAP"
                
                # Construct a path inside ComfyUI's models/wav2vec2 directory
                wav2vec2_base_path = os.path.join(folder_paths.get_folder_paths("checkpoints")[0], "..", "wav2vec2")
                model_path = os.path.join(wav2vec2_base_path, local_model_name)

                # The 'savedir' should point to the specific directory where the model
                # should be stored. This makes it predictable for users.
                self._emotion_classifier = EncoderClassifier.from_hparams(
                    source=source_repo,
                    savedir=model_path
                )
                print("[Sound Engineer] Audio emotion recognition model loaded successfully.")
                
                # --- Diagnostic Prints ---
                print(f"[Sound Engineer] DIAGNOSTIC: Classifier loaded. Type: {type(self._emotion_classifier)}")
                if hasattr(self._emotion_classifier, 'mods'):
                    print(f"[Sound Engineer] DIAGNOSTIC: Classifier has 'mods' attribute. Type: {type(self._emotion_classifier.mods)}")
                    print(f"[Sound Engineer] DIAGNOSTIC: Keys in self._emotion_classifier.mods: {list(self._emotion_classifier.mods.keys())}")
                    if 'wav2vec2' in self._emotion_classifier.mods and hasattr(self._emotion_classifier.mods.wav2vec2, 'compute_features'):
                        print("[Sound Engineer] DIAGNOSTIC: Found 'compute_features' in mods.wav2vec2 (expected).")
                    elif hasattr(self._emotion_classifier.mods, 'compute_features'):
                        print("[Sound Engineer] DIAGNOSTIC: Found 'compute_features' directly in mods.")
                    else:
                        print("[Sound Engineer] DIAGNOSTIC: 'compute_features' NOT found in expected locations within mods.")
                else:
                    print("[Sound Engineer] DIAGNOSTIC: Classifier does NOT have 'mods' attribute.")
                # --- End Diagnostic Prints ---

                return True
            except Exception as e:
                print(f"\033[91m[Sound Engineer] Error loading audio emotion model: {e}\033[0m")
                return False
        return True

    def _get_emotion(self, waveform, sample_rate):
        if self._emotion_classifier is None or self._emotion_model_failed:
            return "neutral"
        try:
            # Resample if needed
            if sample_rate != 16000:
                try:
                    import torchaudio.transforms as T
                    resampler = T.Resample(orig_freq=sample_rate, new_freq=16000).to(waveform.device)
                    waveform = resampler(waveform)
                    sample_rate = 16000
                except Exception as e:
                    print(f"\033[91m[Sound Engineer] Warning: Failed to resample audio for emotion detection. Error: {e}\033[0m")
                    return "neutral"
            
            # Convert to mono if needed
            if waveform.dim() == 3 and waveform.shape[1] > 1:
                waveform_mono = torch.mean(waveform, dim=1)
            elif waveform.dim() == 3:
                waveform_mono = waveform.squeeze(1)
            else:
                waveform_mono = waveform

            # Manually call the modules to bypass breaking change in classify_batch
            wav_lens = torch.tensor([1.0]).to(waveform_mono.device)
            feats = self._emotion_classifier.mods.wav2vec2(waveform_mono, wav_lens)
            embeddings = self._emotion_classifier.mods.avg_pool(feats, wav_lens)
            output_probs = self._emotion_classifier.mods.output_mlp(embeddings)
            
            # Get the predicted label from the output probabilities
            prediction = self._emotion_classifier.hparams.label_encoder.decode_torch(
                torch.nn.functional.softmax(output_probs, dim=-1)
            )

            # Handle variable nesting in prediction from speechbrain due to breaking changes
            result = prediction
            while isinstance(result, list) and result:
                result = result[0]

            if isinstance(result, str):
                return result.lower()
            else:
                # If after unpacking we still don't have a string, something is wrong.
                print(f"[Sound Engineer] Warning: Could not extract a string from emotion prediction. Result was: {result}")
                return "neutral"
        except Exception as e:
            print(f"\033[91m[Sound Engineer] Audio emotion detection failed: {e}\033[0m")
            print("\033[91m[Sound Engineer] This is likely due to a breaking change in the 'speechbrain' library. Emotion detection will be disabled for this session.\033[0m")
            self._emotion_model_failed = True
            return "neutral"


    @classmethod
    def INPUT_TYPES(cls):
        profile_options = sound_engineer_profiles.get_profile_options()
        return {
            "required": {
                "audio": ("AUDIO",),
                "PROJECT_CONFIG": ("DICT",),
                "profile": (profile_options, {"default": profile_options[0]}),
            },
            "optional": {
                "MEL_BAND_VOCALS": ("AUDIO", {"tooltip": "Optional: Use vocals separated by Mel-Band RoFormer for better VAD/Emotion detection."}),
                "segment_duration": ("FLOAT", {"default": 4.0, "min": 0.1}),
                "enable_vad": ("BOOLEAN", {"default": True}),
                "vad_threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
                "enable_emotion_detection": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("AUDIO", "DICT", "INT")
    RETURN_NAMES = ("AUDIO", "TIMING_MAP", "SCENE_COUNT")
    FUNCTION = "process_audio"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"

    def process_audio(self, audio, PROJECT_CONFIG, profile, MEL_BAND_VOCALS=None, segment_duration=4.0, enable_vad=True, vad_threshold=0.5, enable_emotion_detection=True):
        # Extract fps from PROJECT_CONFIG
        fps = PROJECT_CONFIG.get("fps", 24)

        # Use clean vocals if provided for analysis, but keep original for output
        analysis_audio = MEL_BAND_VOCALS if MEL_BAND_VOCALS is not None else audio

        # --- Profile Integration ---
        if profile != "None (Manual Input)":
            profile_settings = sound_engineer_profiles.NAMED_SOUND_ENGINEER_PROFILES.get(profile, {})
            segment_duration = profile_settings.get("segment_duration", segment_duration)
            enable_vad = profile_settings.get("enable_vad", enable_vad)
            vad_threshold = profile_settings.get("vad_threshold", vad_threshold)
            enable_emotion_detection = profile_settings.get("enable_emotion_detection", enable_emotion_detection)

        if audio is None:
            print("[Sound Engineer] Warning: Input audio is None.")
            return ({"waveform": torch.zeros((1, 1, 1)), "sample_rate": 44100}, {"data": []}, 0)
            
        waveform = audio.get("waveform")
        sample_rate = audio.get("sample_rate")
        
        if waveform is None or sample_rate is None or waveform.numel() == 0:
            print("[Sound Engineer] Warning: Input audio is empty or invalid.")
            return (audio, {"data": []}, 0)

        # --- SHAPE SANITIZATION ---
        # ComfyUI audio nodes expect [Batch, Channels, Samples].
        # Often batch is 1. If it's missing, we must add it to prevent downstream failures in PreviewAudio.
        if waveform.ndim == 2: # [Channels, Samples]
            print(f"[Sound Engineer] Input waveform is 2D {waveform.shape}. Unsqueezing batch dim.")
            waveform = waveform.unsqueeze(0) # -> [1, Channels, Samples]
        elif waveform.ndim == 1: # [Samples]
            print(f"[Sound Engineer] Input waveform is 1D {waveform.shape}. Unsqueezing batch and channel dims.")
            waveform = waveform.unsqueeze(0).unsqueeze(0) # -> [1, 1, Samples]
            
        if enable_vad:
            self._load_vad_model()

        if enable_emotion_detection:
            self._load_emotion_model()
            
        total_samples = waveform.shape[-1]
        chunk_samples = int(segment_duration * sample_rate)
        
        timing_map_data = []
        all_chunk_frames = []
        num_chunks = (total_samples + chunk_samples - 1) // chunk_samples
        try:
            audio_duration = float(total_samples) / float(sample_rate)
            print(f"[Sound Engineer] Audio duration: {audio_duration:.2f}s -> {num_chunks} scene(s) at {segment_duration:.2f}s each.")
        except Exception:
            pass
        
        last_known_emotion = "neutral" # Initialize last known emotion

        for i in range(num_chunks):
            start_sample = i * chunk_samples
            end_sample = min((i + 1) * chunk_samples, total_samples)
            # Slicing preserves dimensions [Batch, Channels, Time]
            chunk_wave = waveform[...,start_sample:end_sample]
            
            # If a chunk is invalid or empty, create a silent chunk of the correct duration.
            # This prevents downstream nodes from failing on zero-length audio.
            if chunk_wave.ndim < 3 or chunk_wave.shape[0] == 0 or chunk_wave.shape[1] == 0 or chunk_wave.shape[-1] == 0:
                if chunk_wave.shape[-1] == 0:
                    print(f"[Sound Engineer] Warning: chunk at index {i} is empty. Creating a silent chunk.")
                else:
                    print(f"[Sound Engineer] Warning: chunk_wave at index {i} has unexpected shape {chunk_wave.shape}. Creating a silent chunk.")

                # Create a silent chunk for the full segment duration
                pad_shape = list(waveform.shape[:-1]) + [chunk_samples]
                chunk_wave = torch.zeros(pad_shape, dtype=waveform.dtype, device=waveform.device)

                contains_speech = False
                emotion = "neutral"
                num_frames = int(round(segment_duration * fps))
            else:
                # Calculate actual number of frames for this chunk
                actual_chunk_duration = (end_sample - start_sample) / sample_rate
                num_frames = int(round(actual_chunk_duration * fps))

                # Pad if the last chunk is shorter than segment_duration
                if chunk_wave.shape[-1] < chunk_samples:
                    pad_size = chunk_samples - chunk_wave.shape[-1]
                    # Create padding matching the shape of chunk_wave except for the last dimension
                    pad_shape = list(chunk_wave.shape)
                    pad_shape[-1] = pad_size
                    pad = torch.zeros(pad_shape, dtype=chunk_wave.dtype, device=chunk_wave.device)
                    chunk_wave = torch.cat((chunk_wave, pad), dim=-1)

                # VAD usually runs on the first item in the batch
                contains_speech = self._is_speech_present(chunk_wave[0], sample_rate, vad_threshold) if enable_vad and self._vad_model else True
                
                # Perform emotion detection and update last_known_emotion
                if enable_emotion_detection and self._emotion_classifier:
                    emotion = self._get_emotion(chunk_wave, sample_rate)
                    last_known_emotion = emotion # Update last known emotion
                else:
                    emotion = last_known_emotion # Use last known emotion if detection is disabled


            timing_map_data.append({
                "index": i,
                "start": i * segment_duration,
                "end": (i + 1) * segment_duration,
                "audio_dict": {"waveform": chunk_wave, "sample_rate": sample_rate},
                "contains_speech": contains_speech,
                "emotion": emotion,
                "num_frames": num_frames, # Add num_frames to each chunk entry
            })
            all_chunk_frames.append(num_frames) # Collect all num_frames

        return (audio, {"data": timing_map_data, "durations_frames": all_chunk_frames}, num_chunks)

# --- THE SCREENWRITER ---
class PGFX_Studio_Screenwriter:
    _cached_result = None

    @classmethod
    def INPUT_TYPES(cls):
        try:
            whisper_models = PromptCrafter_SRTCreator.PromptCrafter_SRTCreator.get_whisper_models()
            whisper_default = "large-v3" if "large-v3" in whisper_models else whisper_models[0]
            try:
                import importlib.util
                if importlib.util.find_spec("whisperx") is None and "disabled" in whisper_models:
                    whisper_default = "disabled"
            except Exception:
                if "disabled" in whisper_models:
                    whisper_default = "disabled"

            profile_options = screenwriter_profiles.get_profile_options()
            all_llm_models = creator_nodes.get_combined_models()
            if not all_llm_models:
                all_llm_models = ["disabled"]
            
            sorted_llm_models = _get_sorted_models_by_preference(all_llm_models)
            
            thinking_default = _select_model_default(
                sorted_llm_models,
                lambda name: "Qwen3-VL-8b-Thinking" in name
            )
            instruct_default = _select_model_default(
                sorted_llm_models,
                lambda name: "Qwen3-VL-8b-Instruct" in name
            )

        except Exception:
            whisper_models = ["disabled"]
            whisper_default = "disabled"
            profile_options = ["None (Manual Input)"]
            all_llm_models = ["disabled"]
            thinking_default = "disabled"
            instruct_default = "disabled"

        return {
            "required": {
                "TIMING_MAP": ("DICT",),
                "audio": ("AUDIO",),
                "profile": (profile_options, {"default": profile_options[0]}),
                "thinking_model": (all_llm_models, {"default": thinking_default}),
                "instruct_model": (all_llm_models, {"default": instruct_default}),
            },
            "optional": {
                "MEL_BAND_VOCALS": ("AUDIO", {"tooltip": "Optional: Use vocals separated by Mel-Band RoFormer for superior transcription accuracy."}),
                "whisper_model": (whisper_models, {"default": whisper_default}),
                "raw_lyrics_override": ("STRING", {"multiline": True, "tooltip": "Optional: Provide a perfect script to force-align, overriding the internal transcription."}),
                "debug_mode": ("BOOLEAN", {"default": False}),
                **_studio_llm_runtime_optional_inputs(),
            }
        }

    RETURN_TYPES = ("DICT", "DICT")
    RETURN_NAMES = ("SCREENPLAY", "AUDIO_META")
    FUNCTION = "write_script"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"

    def _build_fallback_word_segments_from_override(self, raw_lyrics_override, timing_data):
        raw = "" if raw_lyrics_override is None else str(raw_lyrics_override).strip()
        if not raw or not timing_data:
            return []

        lyric_lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lyric_lines:
            compact = re.sub(r"\s+", " ", raw).strip()
            if compact:
                lyric_lines = [compact]
        if not lyric_lines:
            return []

        scene_count = max(1, len(timing_data))
        word_segments = []

        for scene_pos, scene in enumerate(timing_data):
            start_t = float(scene.get("start", 0.0))
            end_t = float(scene.get("end", start_t))
            if end_t <= start_t:
                continue

            line_idx = min(int((scene_pos / scene_count) * len(lyric_lines)), len(lyric_lines) - 1)
            line_text = lyric_lines[line_idx]
            words = [w for w in re.findall(r"\S+", line_text) if w]
            if not words:
                continue

            step = (end_t - start_t) / len(words)
            for i, word in enumerate(words):
                w_start = start_t + (i * step)
                w_end = min(end_t, w_start + (step * 0.92))
                word_segments.append({
                    "word": word,
                    "start": w_start,
                    "end": w_end,
                })

        return word_segments

    def _audio_signature(self, audio):
        if not isinstance(audio, dict):
            return "no-audio"
        sample_rate = int(audio.get("sample_rate", 0) or 0)
        waveform = audio.get("waveform")
        if not torch.is_tensor(waveform):
            return f"{sample_rate}:no-waveform"

        shape = tuple(int(x) for x in waveform.shape)
        total = int(waveform.numel())
        if total <= 0:
            return f"{sample_rate}:{shape}:empty"

        try:
            flat = waveform.detach().reshape(-1)
            step = max(1, total // 32)
            sampled = flat[::step][:32].float().cpu().tolist()
            digest_src = ",".join(f"{v:.6f}" for v in sampled)
            checksum = hashlib.md5(digest_src.encode("utf-8")).hexdigest()
        except Exception:
            checksum = hashlib.md5(str(shape).encode("utf-8")).hexdigest()
        return f"{sample_rate}:{shape}:{checksum}"

    def _timing_signature(self, timing_data):
        signature = []
        if not isinstance(timing_data, list):
            return signature
        for entry in timing_data:
            if not isinstance(entry, dict):
                continue
            try:
                idx = int(entry.get("index", -1))
            except Exception:
                idx = -1
            try:
                start_t = round(float(entry.get("start", 0.0)), 3)
            except Exception:
                start_t = 0.0
            try:
                end_t = round(float(entry.get("end", 0.0)), 3)
            except Exception:
                end_t = 0.0
            try:
                frames = int(entry.get("num_frames", 0))
            except Exception:
                frames = 0
            signature.append({
                "index": idx,
                "start": start_t,
                "end": end_t,
                "contains_speech": bool(entry.get("contains_speech", True)),
                "num_frames": frames,
            })
        return signature

    def _clone_screenplay(self, screenplay_data):
        if not isinstance(screenplay_data, list):
            return []
        return [dict(s) for s in screenplay_data if isinstance(s, dict)]

    def _clone_audio_meta(self, audio_meta):
        if not isinstance(audio_meta, dict):
            return {}
        out = dict(audio_meta)
        align = out.get("alignment_result", {})
        if isinstance(align, dict):
            segments = align.get("segments", [])
            if isinstance(segments, list):
                out["alignment_result"] = {"segments": [dict(s) for s in segments if isinstance(s, dict)]}
        if isinstance(out.get("word_segments"), list):
            out["word_segments"] = [dict(w) for w in out["word_segments"] if isinstance(w, dict)]
        if isinstance(out.get("durations"), list):
            out["durations"] = list(out["durations"])
        if isinstance(out.get("instrumental_cues"), list):
            out["instrumental_cues"] = list(out["instrumental_cues"])
        return out

    def write_script(
        self,
        TIMING_MAP,
        audio,
        profile,
        thinking_model,
        instruct_model,
        MEL_BAND_VOCALS=None,
        whisper_model="large-v3",
        raw_lyrics_override="",
        debug_mode=False,
        llm_device=getattr(config, "DEFAULT_LLM_DEVICE", "Default (GPU)"),
        reset_context=getattr(config, "DEFAULT_LLM_STATELESS", True),
    ):
        # --- Profile Integration ---
        if profile != "None (Manual Input)":
            profile_settings = screenwriter_profiles.NAMED_SCREENWRITER_PROFILES.get(profile, {})
            whisper_model = profile_settings.get("whisper_model", whisper_model)

        if whisper_model == "disabled":
            if not (raw_lyrics_override and raw_lyrics_override.strip()):
                print("[Screenwriter] Whisper is disabled and no raw_lyrics_override was provided. Generating a purely instrumental screenplay.")
            else:
                print("[Screenwriter] Whisper model is disabled. Relying solely on 'raw_lyrics_override'.")

        # 1. Run transcription and alignment once on the full audio clip.
        # Use MEL_BAND_VOCALS if provided for cleaner transcription.
        transcription_audio = MEL_BAND_VOCALS if MEL_BAND_VOCALS is not None else audio
        srt_node = PromptCrafter_SRTCreator.PromptCrafter_SRTCreator()

        # Use AI correction if a ground truth script is provided.
        enable_ai_correction = bool(raw_lyrics_override and raw_lyrics_override.strip())

        timing_data = TIMING_MAP.get("data", [])
        if not timing_data:
            print("[Screenwriter] Warning: TIMING_MAP data is empty or invalid.")
            return ({"data": []}, {})

        cache_payload = {
            "timing": self._timing_signature(timing_data),
            "audio": self._audio_signature(transcription_audio),
            "profile": str(profile),
            "thinking_model": str(thinking_model),
            "instruct_model": str(instruct_model),
            "whisper_model": str(whisper_model),
            "raw_lyrics_override": str(raw_lyrics_override or "").strip(),
        }
        cache_hash = hashlib.md5(
            json.dumps(cache_payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        if isinstance(self._cached_result, dict) and self._cached_result.get("hash") == cache_hash:
            if debug_mode:
                print("[Screenwriter] Using cached screenplay (skipping re-transcription/re-segmentation).")
            cached_screenplay = self._clone_screenplay(self._cached_result.get("screenplay", []))
            cached_audio_meta = self._clone_audio_meta(self._cached_result.get("audio_meta", {}))
            return ({"data": cached_screenplay}, cached_audio_meta)

        if whisper_model != "disabled":
            try:
                srt_result = srt_node.execute(
                    audio=transcription_audio,
                    whisper_model=whisper_model,
                    language="en",
                    vad_method="silero",
                    enable_ai_correction=enable_ai_correction,
                    correction_model=instruct_model,
                    enable_translation=False,
                    debug_mode=debug_mode,
                    segment_duration_seconds=4.0,
                    enable_ai_text_refinement=False,
                    strict_speaker_detection=False,
                    ground_truth_script=raw_lyrics_override,
                    llm_device=llm_device,
                    reset_context=reset_context,
                )
                timed_segments_json = srt_result[3] if len(srt_result) > 3 else "[]"
                validation_report = srt_result[8] if len(srt_result) > 8 else ""
                if debug_mode and validation_report:
                    print(f"[Screenwriter] SRT validation report: {validation_report}")
            except ModuleNotFoundError as e:
                print(f"[Screenwriter] WhisperX unavailable ({e}). Falling back to raw_lyrics_override/timing map.")
                timed_segments_json = "[]"
            except Exception as e:
                print(f"[Screenwriter] SRT transcription failed ({e}). Falling back to raw_lyrics_override/timing map.")
                timed_segments_json = "[]"
        else: # If whisper is disabled, we can't transcribe, so we can't get timed segments.
            timed_segments_json = "[]"

        try:
            parsed_segments = json_utils.extract_and_parse_json(timed_segments_json)
            word_segments = parsed_segments if isinstance(parsed_segments, list) else []
        except Exception:
            print("[Screenwriter] Error: Failed to parse Whisper JSON or result was None. Proceeding without lyrics.")
            word_segments = []

        if not word_segments and raw_lyrics_override and raw_lyrics_override.strip():
            print("[Screenwriter] Using fallback timed word segmentation from raw_lyrics_override.")
            word_segments = self._build_fallback_word_segments_from_override(raw_lyrics_override, timing_data)

        screenplay_data = []

        # 2. Distribute the timed words into the scenes defined by the Sound Engineer.
        for scene in timing_data:
            scene_idx = scene["index"]
            start_t = scene["start"]
            end_t = scene["end"]
            
            # Respect the VAD analysis from the Sound Engineer.
            if not scene.get("contains_speech", True):
                screenplay_data.append({
                    "index": scene_idx,
                    "text": "[INSTRUMENTAL]",
                    "type": "instrumental",
                    "raw_text": "[INSTRUMENTAL]"
                })
                continue

            # If VAD detected speech, find the corresponding words.
            # --- ENHANCEMENT: Use overlap logic instead of just start time ---
            # A word belongs to a scene if its time range overlaps with the scene's time range.
            words_in_scene = [
                w["word"] for w in word_segments 
                if w.get("start") is not None and w.get("end") is not None and
                   max(start_t, w["start"]) < min(end_t, w["end"])
            ]
            
            text = " ".join(words_in_scene).strip()
            
            def _looks_like_stage_direction(val: str) -> bool:
                if not val:
                    return False
                raw = val.strip()
                if raw.startswith("[") and raw.endswith("]"):
                    return True
                lowered = raw.lower()
                markers = ("intro", "outro", "instrumental", "solo", "guitar", "riff", "interlude")
                return any(m in lowered for m in markers) and len(raw.split()) <= 6

            raw_text = text if text else "[INSTRUMENTAL]"
            entry = {
                "index": scene_idx,
                "text": raw_text,
                "type": "lyric" if text else "instrumental",
                "raw_text": raw_text,
            }

            # Treat bracketed or stage-direction lines as instrumental to avoid literal prompts.
            if entry["text"] and _looks_like_stage_direction(entry["text"]):
                entry["text"] = "[INSTRUMENTAL]"
                entry["type"] = "instrumental"
            screenplay_data.append(entry)

        # 3. Construct the audio_meta dictionary for downstream nodes
        audio_meta = {
            "alignment_result": {"segments": screenplay_data},
            "word_segments": word_segments,
            "durations": [scene['end'] - scene['start'] for scene in timing_data],
            "offset_seconds": 0.0,
            "instrumental_cues": [s.get("type") == "instrumental" for s in screenplay_data],
            "vocal_audio": audio,
        }

        if debug_mode:
            lyric_count = sum(1 for s in screenplay_data if s.get("type") == "lyric" and s.get("text") and s.get("text") != "[INSTRUMENTAL]")
            print(f"[Screenwriter] Built screenplay with {len(screenplay_data)} scene(s), {lyric_count} lyric scene(s).")

        self._cached_result = {
            "hash": cache_hash,
            "screenplay": self._clone_screenplay(screenplay_data),
            "audio_meta": self._clone_audio_meta(audio_meta),
        }
        return ({"data": screenplay_data}, audio_meta)

# --- NEW: THE CREATIVE DIRECTOR ---
class PGFX_Studio_CreativeDirector:
    """
    The project's lead visionary. This agent analyzes the screenplay to develop a
    global creative concept and a detailed visual brief for the Director.
    """
    _cached_concept = None
    _cached_reference_by_sig = {}

    @classmethod
    def INPUT_TYPES(cls):
        try:
            all_llm_models = creator_nodes.get_combined_models()
            if not all_llm_models: all_llm_models = ["disabled"]

            sorted_llm_models = _get_sorted_models_by_preference(all_llm_models)

            thinking_default = _select_model_default(
                sorted_llm_models,
                lambda name: "qwen" in name.lower() and ("thinking" in name.lower() or "32b" in name.lower() or "72b" in name.lower())
            )
            instruct_default = _select_model_default(
                sorted_llm_models,
                lambda name: "qwen" in name.lower() and "instruct" in name.lower()
            )
        except Exception:
            all_llm_models = ["disabled"]
            thinking_default = "disabled"
            instruct_default = "disabled"

        return {
            "required": {
                "SCREENPLAY": ("DICT",),
                "TIMING_MAP": ("DICT",),
                "thinking_model": (all_llm_models, {"default": thinking_default}),
                "instruct_model": (all_llm_models, {"default": instruct_default}),
                "character_override": ("STRING", {"multiline": True, "default": "", "tooltip": "Manually define the character. If empty, AI will describe from reference images."}),
                "fast_mode": ("BOOLEAN", {"default": True, "tooltip": "Single-pass concept generation to reduce repeated LLM work and CPU fallback risk."}),
                "gguf_gpu_layers": ("INT", {"default": -1, "min": -1, "max": 128, "step": 1, "tooltip": "Number of layers to offload to GPU for GGUF models. -1 for all, 0 for none."}),
                "debug_mode": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "reference_image": ("IMAGE",),
                **_studio_llm_runtime_optional_inputs(),
            }
        }

    RETURN_TYPES = ("DICT", "STRING")
    RETURN_NAMES = ("VISUAL_BRIEF", "creative_concept_log")
    FUNCTION = "develop_concept"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"

    # In nodes_studio.py, in the PGFX_Studio_CreativeDirector class, modify the develop_concept method:

    def _get_fallback_vrg_vars(self):
        """Provide comprehensive fallback values"""
        return {
            "character_description": "The same main character from the reference image.",
            "song_theme_style": "dystopian industrial, dark fantasy, steampunk, gritty realism, corporate oppression, holiday subversion, worker rebellion, absurdist humor",
            "environment": "industrial workshop, santa's office, reindeer pen, break room, toy assembly line, north pole command center, elf dormitory, empty workshop",
            "lighting": "harsh fluorescent, dim candlelight, spotlight interrogation, cold blue tint, warm fire glow, dramatic shadows, overcast daylight, soft dawn",
            "camera_motion": "push in, pull back, pan left, pan right, tilt up, tilt down, track forward, orbit",
            "physical_interaction": "hammering toy, writing list, slumping exhausted, pointing angrily, dodging kick, singing off-key, whispering rebel, walking away",
            "facial_expression": "exhausted resignation, defiant smirk, angry shouting, fearful cowering, surprised pain, drunk confusion, quiet determination, relieved smile",
            "shots": "close up, medium shot, wide shot, extreme close up, over the shoulder, profile shot, two shot, extreme wide shot",
            "outfit_rules": "red hat, white beard, blue trousers, brown boots, red tunic, white shirt, black belt, green gloves",
            "character_visibility": "full body, face only, hands focus, profile view, back view, silhouette, close crop, wide angle"
        }

    def _split_list(self, value):
        return [s.strip() for s in str(value or "").split(",") if s.strip()]

    def _clone_visual_brief(self, visual_brief):
        if not isinstance(visual_brief, dict):
            return {}
        out = {}
        for key, value in visual_brief.items():
            if isinstance(value, list):
                out[key] = list(value)
            elif isinstance(value, dict):
                out[key] = dict(value)
            else:
                out[key] = value
        return out

    def _screenplay_signature(self, screenplay_data):
        signature = []
        if not isinstance(screenplay_data, list):
            return signature
        for entry in screenplay_data:
            if not isinstance(entry, dict):
                continue
            signature.append({
                "index": int(entry.get("index", -1)) if isinstance(entry.get("index", None), int) else -1,
                "type": str(entry.get("type", "") or ""),
                "text": str(entry.get("text", "") or ""),
                "raw_text": str(entry.get("raw_text", "") or ""),
            })
        return signature

    def _timing_signature(self, TIMING_MAP):
        timing_data = TIMING_MAP.get("data", []) if isinstance(TIMING_MAP, dict) else []
        signature = []
        if not isinstance(timing_data, list):
            return signature
        for entry in timing_data:
            if not isinstance(entry, dict):
                continue
            try:
                idx = int(entry.get("index", -1))
            except Exception:
                idx = -1
            try:
                start_t = round(float(entry.get("start", 0.0)), 3)
            except Exception:
                start_t = 0.0
            try:
                end_t = round(float(entry.get("end", 0.0)), 3)
            except Exception:
                end_t = 0.0
            signature.append({
                "index": idx,
                "start": start_t,
                "end": end_t,
            })
        return signature

    def _reference_image_signature(self, reference_image):
        if reference_image is None:
            return "none"
        if not torch.is_tensor(reference_image):
            return f"non-tensor:{type(reference_image).__name__}"
        shape = tuple(int(x) for x in reference_image.shape)
        total = int(reference_image.numel())
        if total <= 0:
            return f"{shape}:empty"
        try:
            flat = reference_image.detach().reshape(-1)
            step = max(1, total // 32)
            sampled = flat[::step][:32].float().cpu().tolist()
            digest_src = ",".join(f"{v:.6f}" for v in sampled)
            checksum = hashlib.md5(digest_src.encode("utf-8")).hexdigest()
        except Exception:
            checksum = hashlib.md5(str(shape).encode("utf-8")).hexdigest()
        return f"{shape}:{checksum}"

    def _describe_reference_image(
        self,
        reference_image,
        thinking_model,
        instruct_model,
        debug_mode,
        llm_device,
        reset_context,
        gguf_gpu_layers=-1,
    ):
        """
        Use a vision-capable LLM to extract a concrete character/environment description
        from the reference image so downstream prompts are grounded.
        """
        if reference_image is None:
            return {}

        thinking_prompt = textwrap.dedent("""
            You are a visual analyst. Examine the reference image carefully.
            Identify the main character, what they are doing, their outfit, props, and the environment.
            Keep the description literal and grounded in what is visible.
        """).strip()

        instruct_prompt = textwrap.dedent("""
            Return a JSON object with these keys:
            - character_description: 1-2 sentences describing the main character (species/subject, clothing, pose, action, key props).
            - environment_description: 1 sentence describing the setting and background.
            - mood: a short phrase capturing lighting/atmosphere.
            - key_props: a comma-separated list of 3-6 visible props.

            Rules:
            - Be literal. Do not invent story elements.
            - Use standard double quotes for JSON keys/values.
            - Return ONLY the JSON object.
        """).strip()

        ok, result, reasoning = utils.chain_of_thought_process(
            thinking_prompt=thinking_prompt,
            thinking_model=thinking_model,
            instruct_prompt=instruct_prompt,
            instruct_model=instruct_model,
            images=[reference_image],
            debug_mode=debug_mode,
            n_gpu_layers=gguf_gpu_layers,
            llm_device=llm_device,
            reset_context=reset_context,
            single_pass_if_same_model=True,
            timeout=240,
        )
        if not ok or not isinstance(result, dict):
            if debug_mode:
                print(f"[Creative Director] Reference image analysis failed: {result} | {reasoning}")
            return {}
        return result

    def develop_concept(self, SCREENPLAY, TIMING_MAP, thinking_model, instruct_model,
                   character_override, fast_mode=True, debug_mode=False, gguf_gpu_layers=-1, reference_image=None,
                   llm_device=getattr(config, "DEFAULT_LLM_DEVICE", "Default (GPU)"),
                   reset_context=getattr(config, "DEFAULT_LLM_STATELESS", True)):
        # Add input validation
        if not SCREENPLAY or not SCREENPLAY.get("data"):
            return ({}, "[ERROR] SCREENPLAY is empty or invalid.")

        screenplay_data = SCREENPLAY.get("data", [])
        reference_sig = self._reference_image_signature(reference_image)
        cache_payload = {
            "screenplay": self._screenplay_signature(screenplay_data),
            "timing": self._timing_signature(TIMING_MAP),
            "thinking_model": str(thinking_model),
            "instruct_model": str(instruct_model),
            "character_override": str(character_override or "").strip(),
            "fast_mode": bool(fast_mode),
            "gguf_gpu_layers": int(gguf_gpu_layers),
            "reference_sig": reference_sig,
        }
        cache_hash = hashlib.md5(
            json.dumps(cache_payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        ).hexdigest()

        if isinstance(self._cached_concept, dict) and self._cached_concept.get("hash") == cache_hash:
            if debug_mode:
                print("[Creative Director] Using cached VISUAL_BRIEF (skipping repeated concept generation).")
            cached_brief = self._clone_visual_brief(self._cached_concept.get("brief", {}))
            cached_log = self._cached_concept.get("log", "")
            return (cached_brief, cached_log)

        # Part 1: Describe reference image
        image_context = "No reference images."
        images_to_pass = []
        reference_analysis = {}
        if reference_image is not None:
            image_context = "A reference image is provided. Analyze it directly to inform your creative choices."
            images_to_pass = [reference_image]
            cached_reference = self._cached_reference_by_sig.get(reference_sig, {})
            if isinstance(cached_reference, dict) and cached_reference:
                reference_analysis = dict(cached_reference)
                if debug_mode:
                    print("[Creative Director] Using cached reference-image analysis.")
            else:
                reference_analysis = self._describe_reference_image(
                    reference_image=reference_image,
                    thinking_model=thinking_model,
                    instruct_model=instruct_model,
                    debug_mode=debug_mode,
                    llm_device=llm_device,
                    reset_context=reset_context,
                    gguf_gpu_layers=gguf_gpu_layers,
                )
                if reference_analysis:
                    self._cached_reference_by_sig[reference_sig] = dict(reference_analysis)
            if reference_analysis:
                image_context = (
                    f"{reference_analysis.get('environment_description','').strip()} "
                    f"Props: {reference_analysis.get('key_props','').strip()} "
                    f"Mood: {reference_analysis.get('mood','').strip()}"
                ).strip()

        final_character_desc = character_override.strip() or reference_analysis.get("character_description") or (
            "The same main character from the reference image, preserving identity, costume, and key props."
            if reference_image is not None else "A mysterious figure."
        )
        lyrics_text = "`\n`".join([s['text'] for s in screenplay_data if s['type'] == 'lyric'])
        lyrics_summary = "`\n`".join(lyrics_text.splitlines()[:20])

        # Fast path: one LLM pass returning both theme and style variable buckets.
        if fast_mode:
            fast_thinking_prompt = textwrap.dedent(f"""
                You are an expert AI Music Video Creative Director.
                Analyze the lyrics and context, then design a coherent visual concept for LTX-2 scene generation.
                Keep reasoning concise and production-oriented.

                CONTEXT:
                - Lyrics: {lyrics_summary}
                - Character: {final_character_desc}
                - Reference Image Context: {image_context}
            """).strip()

            fast_instruct_prompt = textwrap.dedent("""
                Return a single JSON object with keys:
                `global_theme`, `song_theme_style`, `environment`, `lighting`,
                `camera_motion`, `physical_interaction`, `facial_expression`,
                `shots`, `outfit_rules`, `character_visibility`.

                Rules:
                - Each field except `global_theme` must be a string containing exactly eight comma-separated entries.
                - Use cinematic language compatible with LTX-2.
                - Return ONLY raw JSON with standard double quotes.
            """).strip()

            ok_fast, fast_result, fast_reasoning = utils.chain_of_thought_process(
                thinking_prompt=fast_thinking_prompt,
                thinking_model=thinking_model,
                instruct_prompt=fast_instruct_prompt,
                instruct_model=instruct_model,
                images=images_to_pass,
                debug_mode=debug_mode,
                n_gpu_layers=gguf_gpu_layers,
                llm_device=llm_device,
                reset_context=reset_context,
                timeout=240,
            )

            if not ok_fast or not isinstance(fast_result, dict):
                if debug_mode:
                    print(f"[Creative Director] Fast mode failed; using fallback vars. Result: {fast_result}")
                auto_vrg_vars = self._get_fallback_vrg_vars()
                global_theme = "A cinematic interpretation of the song's emotional arc."
                log = f"[FAST MODE FALLBACK]\n{fast_reasoning}"
            else:
                auto_vrg_vars = fast_result
                global_theme = str(fast_result.get("global_theme", "A cinematic interpretation of the song's emotional arc.")).strip()
                if not global_theme:
                    global_theme = "A cinematic interpretation of the song's emotional arc."
                log = f"`--- FAST MODE REASONING ---\n`{fast_reasoning}"

            visual_brief = {
                "character_description": final_character_desc,
                "global_theme": global_theme,
                "visual_styles_auto": self._split_list(auto_vrg_vars.get("song_theme_style", "")),
                "environment_auto": self._split_list(auto_vrg_vars.get("environment", "")),
                "lighting_auto": self._split_list(auto_vrg_vars.get("lighting", "")),
                "camera_motion_auto": self._split_list(auto_vrg_vars.get("camera_motion", "")),
                "physical_interaction_auto": self._split_list(auto_vrg_vars.get("physical_interaction", "")),
                "facial_expression_auto": self._split_list(auto_vrg_vars.get("facial_expression", "")),
                "shots_auto": self._split_list(auto_vrg_vars.get("shots", "")),
                "outfit_rules_auto": self._split_list(auto_vrg_vars.get("outfit_rules", "")),
                "character_visibility_auto": self._split_list(auto_vrg_vars.get("character_visibility", "")),
                "reference_environment": reference_analysis.get("environment_description", ""),
                "reference_mood": reference_analysis.get("mood", ""),
                "reference_props": reference_analysis.get("key_props", ""),
            }
            self._cached_concept = {
                "hash": cache_hash,
                "brief": self._clone_visual_brief(visual_brief),
                "log": log,
            }
            return (self._clone_visual_brief(visual_brief), log)

        # Part 2: Generate Global Theme using Chain of Thought
        theme_thinking_prompt = textwrap.dedent(f"""
            You are an expert music video creative director. Your task is to devise a single, concise, high-level creative concept or global theme for a music video.
            Think step-by-step about the tone, setting, and narrative arc based on the provided context.
            IMPORTANT: The song is likely a custom track. Do not assume it is a famous song or try to guess an artist. If lyrics are not provided, treat it as an original instrumental. Base your concept ONLY on the information below.
            Write down your creative reasoning in 3-4 concise bullet points. Then, outline a plan for the theme in another 3-4 bullet points. Keep your entire response brief.

            CONTEXT:
            - Lyrics: {lyrics_summary}
            - Character: {final_character_desc}
            - Reference Image Context: {image_context}
        """)
        theme_instruct_prompt = "Based on the creative reasoning provided, write the final theme description as a single, compelling, and imaginative paragraph. Return ONLY the paragraph."

        ok_theme, theme_result, theme_reasoning = utils.chain_of_thought_process(
            thinking_prompt=theme_thinking_prompt, thinking_model=thinking_model,
            instruct_prompt=theme_instruct_prompt, instruct_model=instruct_model,
            images=images_to_pass, debug_mode=debug_mode,
            expect_json=False,
            n_gpu_layers=gguf_gpu_layers,
            llm_device=llm_device,
            reset_context=reset_context,
        )
        if not ok_theme: return ({}, f"[ERROR] Failed to generate global theme: {theme_result}")
        global_theme = theme_result

        # Part 3: Generate Automated VRG variables using Chain of Thought
        vrg_thinking_prompt = textwrap.dedent(f"""
            You are an expert AI Music Video Director. Your task is to analyze the reference images and song lyrics to produce ten creative visual categories.
            Think step-by-step. How can the lyrics' mood be applied to the visual elements from the image context?
            The `character_description` MUST be a direct description of the person in the image context.
            Positional Pairing is critical: the first entry in `environment` should correspond to the first in `lighting`, etc., for all eight positions.
            Brainstorm eight comma-separated options for each of the following 10 categories.

            ANALYSIS INPUT:
            - Image Context (Primary Visual Source): "{image_context}"
            - Lyrics (Mood and Narrative Source): "{lyrics_summary}"
        """)
        
        vrg_instruct_prompt = textwrap.dedent(f"""
            Based on the creative reasoning, generate a JSON object with 10 keys: `character_description`, `song_theme_style`, `environment`, `lighting`, `camera_motion`, `physical_interaction`, `facial_expression`, `shots`, `outfit_rules`, `character_visibility`.
            Each key's value must be a string containing exactly eight comma-separated cinematic entries.

            STRICT CONSTRAINTS: 
            - `camera_motion` must use cinematic camera language compatible with LTX-2 (examples: push in, pull back, pan, tilt, track, orbit, handheld, static).
            - `shots` must use cinematic shot language compatible with LTX-2 (examples: close up, medium shot, wide shot, establishing shot, over the shoulder, low angle, high angle, overhead shot).
            - `outfit_rules` must be two-word entries derived directly from the `Image Context` (e.g., white dress, blue shirt, black jacket).
            - The output MUST be a single, raw JSON object. Do not wrap it in markdown ```json ... ```.
            - Use standard double quotes " for all JSON keys and string values.

            Return ONLY the JSON object. Do not include any other text, commentary, or explanations.
        """)

        # Add timeout and retry logic
        max_retries = 3
        vrg_result = None
        vrg_reasoning = ""
        auto_vrg_vars = {}

        for attempt in range(max_retries):
            try:
                ok_vrg, vrg_result, vrg_reasoning = utils.chain_of_thought_process(
                    thinking_prompt=vrg_thinking_prompt,
                    thinking_model=thinking_model,
                    instruct_prompt=vrg_instruct_prompt,
                    instruct_model=instruct_model,
                    images=images_to_pass,
                    debug_mode=debug_mode,
                    n_gpu_layers=gguf_gpu_layers,
                    timeout=180,  # Increased timeout
                    llm_device=llm_device,
                    reset_context=reset_context,
                )

                if ok_vrg and isinstance(vrg_result, dict):
                    auto_vrg_vars = vrg_result
                    break  # Success, exit loop
                
                print(f"[Creative Director] VRG generation attempt {attempt + 1} failed or returned invalid data. Retrying...")

            except Exception as e:
                print(f"[Creative Director] Exception on attempt {attempt + 1}: {str(e)}")
                if attempt == max_retries - 1:
                    print(f"[Creative Director] Failed after {max_retries} attempts: {str(e)}")
                    auto_vrg_vars = self._get_fallback_vrg_vars()
                    vrg_reasoning += f"\n[ERROR] All attempts to generate VRG failed. Last error: {str(e)}"
                    break # exit loop and use fallback

        # If after all retries we still don't have a dict, use fallback
        if not auto_vrg_vars:
            print("[Creative Director] All attempts failed. Using fallback VRG variables.")
            auto_vrg_vars = self._get_fallback_vrg_vars()
            vrg_reasoning += "\n[ERROR] All VRG generation attempts failed, using fallback data."


        # Part 4: Assemble the final brief
        visual_brief = {
            "character_description": final_character_desc,
            "global_theme": global_theme,
            "visual_styles_auto": self._split_list(auto_vrg_vars.get("song_theme_style", "")),
            "environment_auto": self._split_list(auto_vrg_vars.get("environment", "")),
            "lighting_auto": self._split_list(auto_vrg_vars.get("lighting", "")),
            "camera_motion_auto": self._split_list(auto_vrg_vars.get("camera_motion", "")),
            "physical_interaction_auto": self._split_list(auto_vrg_vars.get("physical_interaction", "")),
            "facial_expression_auto": self._split_list(auto_vrg_vars.get("facial_expression", "")),
            "shots_auto": self._split_list(auto_vrg_vars.get("shots", "")),
            "outfit_rules_auto": self._split_list(auto_vrg_vars.get("outfit_rules", "")),
            "character_visibility_auto": self._split_list(auto_vrg_vars.get("character_visibility", "")),
            "reference_environment": reference_analysis.get("environment_description", ""),
            "reference_mood": reference_analysis.get("mood", ""),
            "reference_props": reference_analysis.get("key_props", ""),
        }

        log = f"`--- THEME REASONING ---\n`{theme_reasoning}`\n\n--- AUTO-STYLES REASONING ---\n`{vrg_reasoning}"
        self._cached_concept = {
            "hash": cache_hash,
            "brief": self._clone_visual_brief(visual_brief),
            "log": log,
        }
        return (self._clone_visual_brief(visual_brief), log)


# --- THE DIRECTOR ---
class PGFX_Studio_Director:
    """
    The Director. Creates an edit plan and generates a shot list based on the
    Creative Director's visual brief and the Screenwriter's script.
    Stateful: caches the last shot list per input hash; resets on input change
    or process restart.
    """

    @classmethod
    def INPUT_TYPES(cls):
        try:
            # Director profiles are now a fallback, not the primary input
            director_profiles._load_director_profiles()
            profile_options = director_profiles.get_director_profile_options()            

            all_llm_models = creator_nodes.get_combined_models()
            if not all_llm_models:
                all_llm_models = ["disabled"]

            sorted_llm_models = _get_sorted_models_by_preference(all_llm_models)

            # Set default models, falling back to the first available if not found
            thinking_default = _select_model_default(
                sorted_llm_models,
                lambda name: "Qwen3-VL-8b-Thinking" in name
            )
            instruct_default = _select_model_default(
                sorted_llm_models,
                lambda name: "Qwen3-VL-8b-Instruct" in name
            )
        except Exception as e:
            print(f"[Director] Error loading models or profiles: {e}")
            profile_options = ["None (Manual Input)"]
            all_llm_models = ["disabled"]
            thinking_default = "disabled"
            instruct_default = "disabled"
            
        return {
            "required": {
                "SCREENPLAY": ("DICT",),
                "thinking_model": (all_llm_models, {"default": thinking_default}),
                "instruct_model": (all_llm_models, {"default": instruct_default}),
                "use_prompt_template": ("BOOLEAN", {"default": True, "tooltip": "If True, uses deterministic prompt construction and skips per-scene LLM prompting (recommended for long scene counts)."}),
                "debug_mode": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "VISUAL_BRIEF": ("DICT",), # Now takes the brief from the Creative Director
                "director_profile_override": (profile_options, {"default": "None (Manual Input)"}),
                "manual_character_override": ("STRING", {"multiline": True, "default": ""}),
                "manual_styles_override": ("STRING", {"multiline": True, "default": ""}),
                "enable_visual_metaphors": ("BOOLEAN", {"default": False, "tooltip": "If True, runs an extra LLM metaphor pass per lyric scene (slow)."}),
                "lock_character_seed": ("BOOLEAN", {"default": True, "tooltip": "If True, uses one stable seed across all scenes to improve character consistency."}),
                **_studio_llm_runtime_optional_inputs(),
            }
        }
    RETURN_TYPES = ("DICT", "STRING")
    RETURN_NAMES = ("SHOT_LIST", "reasoning_log")
    FUNCTION = "direct_scenes"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"

    def _detect_climax_scenes(self, screenplay_data):
        """Identify scenes that likely represent emotional climaxes"""
        # Analyze scene text for emotional intensity markers
        climax_markers = ['shout', 'scream', 'cry', 'explode', 'rage', 'passion']
        climax_scenes = []

        for scene in screenplay_data:
            if scene['type'] == 'lyric':
                text = scene['text'].lower()
                if any(marker in text for marker in climax_markers):
                    scene['is_climax'] = True
                    climax_scenes.append(scene['index'])

        return climax_scenes

    def _validate_style_assignments(self, edit_plan, styles):
        """Ensure style assignments follow logical progression"""
        # Check for abrupt style changes
        for i in range(1, len(edit_plan)):
            prev_style = edit_plan[i-1]['style']
            curr_style = edit_plan[i]['style']
            if prev_style != curr_style:
                # Add transition logic if needed
                edit_plan[i]['transition'] = True
        return edit_plan

    def _pick_from_list(self, values, index, fallback=""):
        if isinstance(values, list) and values:
            try:
                return values[int(index) % len(values)]
            except Exception:
                return values[0]
        if isinstance(values, str) and values.strip():
            return values.strip()
        return fallback

    def _infer_scene_music_role(self, scene_data):
        scene_type = str(scene_data.get("type", "") or "").strip().lower()
        text = str(scene_data.get("text", "") or "").strip()
        raw_text = str(scene_data.get("raw_text", "") or "").strip()
        merged = f"{raw_text} {text}".lower()

        instruments = []
        keyword_map = {
            "guitar": ["guitar"],
            "piano": ["piano", "keys", "keyboard"],
            "upright bass": ["upright bass", "bass solo", "double bass", "bass"],
            "fiddle": ["fiddle", "violin"],
            "drums": ["drum", "percussion"],
            "saxophone": ["sax", "saxophone"],
        }
        for label, keys in keyword_map.items():
            if any(k in merged for k in keys):
                instruments.append(label)

        structure_cues = [
            "instrumental",
            "interlude",
            "solo",
            "breakdown",
            "intro",
            "outro",
        ]
        is_structural_instrumental = any(cue in merged for cue in structure_cues)
        is_instrumental = scene_type == "instrumental" or is_structural_instrumental

        if is_instrumental:
            role = "instrumental_broll"
        elif instruments:
            role = "band_performance"
        else:
            role = "lead_vocal"

        return {
            "role": role,
            "is_instrumental": is_instrumental,
            "instruments": instruments,
            "text": text,
            "raw_text": raw_text,
        }

    def _infer_hard_cut(self, scene_data, prev_scene_data, assignment, assigned_style="", prev_style=""):
        # Explicit overrides always win.
        explicit = assignment.get("hard_cut", None) if isinstance(assignment, dict) else None
        if isinstance(explicit, bool):
            return explicit
        if isinstance(explicit, (int, float)):
            return bool(explicit)
        if isinstance(explicit, str) and explicit.strip().lower() in {"1", "true", "yes", "hard_cut", "hard-cut", "cut"}:
            return True

        try:
            idx = int(scene_data.get("index", 0))
        except Exception:
            idx = 0
        if idx <= 0:
            return False

        curr_type = str(scene_data.get("type", "") or "").strip().lower()
        prev_type = str((prev_scene_data or {}).get("type", "") or "").strip().lower()

        curr_text = f"{scene_data.get('raw_text', '')} {scene_data.get('text', '')}".lower()
        structural_markers = ["interlude", "solo", "breakdown", "intro", "outro", "scene change"]
        if any(marker in curr_text for marker in structural_markers):
            return True

        # A lyric<->instrumental switch is generally a true scene break.
        if curr_type != prev_type and ("instrumental" in {curr_type, prev_type}):
            return True

        # Style change alone is not enough to force a hard cut.
        if assigned_style and prev_style and assigned_style.strip().lower() != prev_style.strip().lower():
            semantic_shift_markers = ["new location", "different location", "flashback", "cut to"]
            if any(marker in curr_text for marker in semantic_shift_markers):
                return True

        return False

    def _format_scene_manifest_for_planner(self, screenplay_data, max_text_len=96):
        lines = []
        for i, scene in enumerate(screenplay_data):
            scene_index = scene.get("index", i)
            scene_type = scene.get("type", "instrumental")
            text = str(scene.get("text", "") or "")
            text = re.sub(r"\s+", " ", text.replace("\n", " ").strip())
            if len(text) > max_text_len:
                text = text[: max_text_len - 3].rstrip() + "..."
            lines.append(f'  - Scene {scene_index} ({scene_type}): "{text}"')
        return "\n".join(lines)

    def _resolve_style_name(self, style_name, styles):
        candidate = str(style_name or "").strip()
        if not candidate:
            return ""
        for style in styles:
            if candidate.lower() == str(style).strip().lower():
                return style
        for style in styles:
            style_l = str(style).strip().lower()
            cand_l = candidate.lower()
            if cand_l in style_l or style_l in cand_l:
                return style
        return ""

    def _normalize_scene_assignments(self, assignments, screenplay_data, styles):
        expected_indices = []
        for i, scene in enumerate(screenplay_data):
            try:
                expected_indices.append(int(scene.get("index", i)))
            except Exception:
                expected_indices.append(i)

        expected_set = set(expected_indices)
        normalized_by_index = {}
        invalid_rows = []
        extra_indices = []

        if not isinstance(assignments, list):
            return [], {
                "expected_indices": expected_indices,
                "missing_indices": expected_indices,
                "invalid_rows": ["Assignments payload is not a list."],
                "extra_indices": [],
            }

        for row in assignments:
            if not isinstance(row, dict):
                invalid_rows.append(f"Non-dict assignment: {row}")
                continue

            raw_index = row.get("index")
            try:
                index = int(raw_index)
            except Exception:
                invalid_rows.append(f"Invalid index: {raw_index}")
                continue

            if index not in expected_set:
                extra_indices.append(index)
                continue
            if index in normalized_by_index:
                continue

            resolved_style = self._resolve_style_name(row.get("style", ""), styles)
            if not resolved_style:
                invalid_rows.append(f"Invalid style for scene {index}: {row.get('style')}")
                continue

            reasoning = str(row.get("reasoning", "") or "").strip() or "Model assignment."
            normalized_by_index[index] = {
                "index": index,
                "style": resolved_style,
                "reasoning": reasoning,
            }

        normalized = [normalized_by_index[i] for i in expected_indices if i in normalized_by_index]
        missing = [i for i in expected_indices if i not in normalized_by_index]

        return normalized, {
            "expected_indices": expected_indices,
            "missing_indices": missing,
            "invalid_rows": invalid_rows,
            "extra_indices": sorted(set(extra_indices)),
        }

    def _repair_edit_plan_with_llm(self, screenplay_data, styles, instruct_model, debug_mode, llm_device, reset_context, previous_result, previous_reasoning):
        scene_manifest = self._format_scene_manifest_for_planner(screenplay_data, max_text_len=80)
        expected_indices = []
        for i, scene in enumerate(screenplay_data):
            try:
                expected_indices.append(int(scene.get("index", i)))
            except Exception:
                expected_indices.append(i)
        style_list_for_prompt = "\n".join([f"  - {s}" for s in styles])
        previous_result_text = str(previous_result)
        if len(previous_result_text) > 2500:
            previous_result_text = previous_result_text[:2500] + "..."
        previous_reasoning_text = str(previous_reasoning or "")
        if len(previous_reasoning_text) > 2500:
            previous_reasoning_text = previous_reasoning_text[:2500] + "..."

        repair_prompt = textwrap.dedent(f"""
            You are repairing an invalid music-video scene plan JSON.
            Return a single JSON object with key "scene_assignments".

            Allowed styles (must match exactly):
            {style_list_for_prompt}

            Required scene indices (must appear exactly once each):
            {expected_indices}

            Screenplay:
            {scene_manifest}

            Previous invalid output:
            {previous_result_text}

            Previous reasoning context:
            {previous_reasoning_text}

            Required schema:
            {{
              "scene_assignments": [
                {{
                  "index": 0,
                  "style": "one allowed style",
                  "reasoning": "brief reason"
                }}
              ]
            }}

            Rules:
            - Include every required scene index exactly once.
            - Do not return an empty array.
            - "style" must be one of the allowed styles exactly.
            - Return ONLY raw JSON with standard double quotes.
        """).strip()

        ok, repaired = api_clients._reason_with_model(
            instruct_model,
            prompt=repair_prompt,
            llm_device=llm_device,
            reset_context=reset_context,
            debug_mode=debug_mode,
            debug_title="Director Plan Repair",
            timeout=180,
            max_tokens=4096,
            temperature=0.1,
        )
        if not ok:
            return None, f"Repair pass failed: {repaired}"

        repair_assignments = []
        if isinstance(repaired, dict) and "scene_assignments" in repaired:
            repair_assignments = repaired.get("scene_assignments", [])
        elif isinstance(repaired, list):
            repair_assignments = repaired
        else:
            return None, f"Repair pass returned unexpected structure: {type(repaired).__name__}"

        normalized, stats = self._normalize_scene_assignments(repair_assignments, screenplay_data, styles)
        if stats["missing_indices"]:
            return None, f"Repair pass still incomplete. Missing scene indices: {stats['missing_indices'][:12]}"

        return normalized, "Repair pass succeeded."

    def _plan_chunk_assignments_with_llm(self, screenplay_chunk, styles, instruct_model, debug_mode, llm_device, reset_context):
        if not screenplay_chunk:
            return [], "Chunk planner received empty screenplay chunk."

        required_indices = []
        for i, scene in enumerate(screenplay_chunk):
            try:
                required_indices.append(int(scene.get("index", i)))
            except Exception:
                required_indices.append(i)

        style_list_for_prompt = "\n".join([f"  - {s}" for s in styles])
        chunk_manifest = self._format_scene_manifest_for_planner(screenplay_chunk, max_text_len=88)

        chunk_prompt = textwrap.dedent(f"""
            You are an AI music video director planner.
            Build style assignments for this scene chunk only.

            Allowed styles (must match exactly):
            {style_list_for_prompt}

            Required scene indices (must be fully covered):
            {required_indices}

            Scene chunk:
            {chunk_manifest}

            Return ONLY one JSON object:
            {{
              "scene_assignments": [
                {{
                  "index": 0,
                  "style": "one allowed style",
                  "reasoning": "brief reason"
                }}
              ]
            }}

            Rules:
            - Include every required index exactly once.
            - Do not return an empty array.
            - Do not include indices outside the required list.
            - Return raw JSON only.
        """).strip()

        last_error = ""
        for attempt in range(1, 4):
            ok, parsed = api_clients._reason_with_model(
                instruct_model,
                prompt=chunk_prompt,
                llm_device=llm_device,
                reset_context=True if attempt > 1 else reset_context,
                debug_mode=debug_mode,
                debug_title=f"Director Chunk Planner (attempt {attempt})",
                timeout=220,
                max_tokens=4096,
                temperature=0.1,
            )
            if not ok:
                last_error = f"model call failed: {parsed}"
                continue

            assignments = []
            if isinstance(parsed, dict) and "scene_assignments" in parsed:
                assignments = parsed.get("scene_assignments", [])
            elif isinstance(parsed, list):
                assignments = parsed
            else:
                last_error = f"unexpected structure: {type(parsed).__name__}"
                continue

            normalized, stats = self._normalize_scene_assignments(assignments, screenplay_chunk, styles)
            if stats.get("missing_indices"):
                last_error = f"missing indices: {stats.get('missing_indices')}"
                continue

            return normalized, f"Chunk planner succeeded on attempt {attempt}."

        # SELF-HEALING RECOVERY: If we reached here, the model failed to provide all indices.
        # Instead of failing the entire chunk, we "self-heal" by filling gaps with a default style.
        import sys
        print(f"### [Director] Chunk planner failed with '{last_error}'. Initiating self-healing...", file=sys.stderr)
        
        # Fallback assignments: use the first available style if any, otherwise skip
        fallback_style = styles[0] if styles else "Default"
        
        # We start with empty assignments or whatever we got last
        assignments = assignments if assignments else []
        normalized, stats = self._normalize_scene_assignments(assignments, screenplay_chunk, styles)
        
        missing = stats.get("missing_indices", [])
        if missing:
            print(f"### [Director] Self-healing filling {len(missing)} missing indices: {missing}", file=sys.stderr)
            for idx in missing:
                normalized.append({
                    "index": idx,
                    "style": fallback_style,
                    "reasoning": "Self-healed fallback assignment due to planner failure."
                })
        
        # Re-sort to maintain order
        normalized = sorted(normalized, key=lambda x: x["index"])
        
        return normalized, f"Chunk planner recovered using self-healing (last error: {last_error})."

    def _plan_in_chunks_with_llm(self, screenplay_data, styles, instruct_model, debug_mode, llm_device, reset_context, chunk_size=12):
        if not screenplay_data:
            return [], "Chunk planner received empty screenplay."

        chunk_size = max(6, int(chunk_size))
        combined = []
        logs = []

        for start in range(0, len(screenplay_data), chunk_size):
            end = min(len(screenplay_data), start + chunk_size)
            chunk = screenplay_data[start:end]
            chunk_plan, chunk_log = self._plan_chunk_assignments_with_llm(
                screenplay_chunk=chunk,
                styles=styles,
                instruct_model=instruct_model,
                debug_mode=debug_mode,
                llm_device=llm_device,
                reset_context=reset_context,
            )
            scene_bounds = f"{chunk[0].get('index', start)}..{chunk[-1].get('index', end - 1)}"
            logs.append(f"Chunk {scene_bounds}: {chunk_log}")
            if chunk_plan is None:
                return None, "\n".join(logs)
            combined.extend(chunk_plan)

        normalized, stats = self._normalize_scene_assignments(combined, screenplay_data, styles)
        if stats.get("missing_indices"):
            return None, "\n".join(logs + [f"Combined chunk plan missing indices: {stats.get('missing_indices')}"])

        return normalized, "\n".join(logs)

    def _build_ltx2_prompt(self, scene_data, assigned_style, character_description, visual_brief, scene_index):
        # Pull structured hints from the visual brief
        env_hint = self._pick_from_list(visual_brief.get("environment_auto"), scene_index, "")
        lighting_hint = self._pick_from_list(visual_brief.get("lighting_auto"), scene_index, "")
        camera_motion = self._pick_from_list(visual_brief.get("camera_motion_auto"), scene_index, "slow push in")
        interaction = self._pick_from_list(visual_brief.get("physical_interaction_auto"), scene_index, "performing to the music")
        expression = self._pick_from_list(visual_brief.get("facial_expression_auto"), scene_index, "focused expression")
        shot_type = self._pick_from_list(visual_brief.get("shots_auto"), scene_index, "medium shot")
        outfit = self._pick_from_list(visual_brief.get("outfit_rules_auto"), scene_index, "")
        visibility = self._pick_from_list(visual_brief.get("character_visibility_auto"), scene_index, "full body")

        ref_env = str(visual_brief.get("reference_environment", "") or "").strip()
        ref_mood = str(visual_brief.get("reference_mood", "") or "").strip()
        ref_props = str(visual_brief.get("reference_props", "") or "").strip()
        global_theme = str(visual_brief.get("global_theme", "") or "").strip()
        outfit_rules_all = [str(x).strip() for x in visual_brief.get("outfit_rules_auto", []) if str(x).strip()]
        # Keep identity constraints stable across scenes to reduce character drift.
        stable_outfit = ", ".join(outfit_rules_all[:3]) if outfit_rules_all else ""

        env_parts = []
        if env_hint:
            env_parts.append(env_hint)
        if ref_env and (ref_env.lower() not in " ".join(env_parts).lower()):
            env_parts.append(ref_env)
        env_text = ", ".join(p for p in env_parts if p) or "a cinematic setting"

        props_sentence = f" Props include {ref_props}." if ref_props else ""
        outfit_sentence = f" wearing {outfit}" if outfit else ""
        continuity_sentence = ""
        if stable_outfit or ref_props:
            continuity_bits = [b for b in [stable_outfit, ref_props] if b]
            continuity_sentence = f" Keep character identity and wardrobe continuity fixed: {', '.join(continuity_bits)}."
        visibility_sentence = f", {visibility}" if visibility else ""

        lyric_text = (scene_data.get("text") or "").strip()
        raw_text = (scene_data.get("raw_text") or "").strip()
        scene_type = scene_data.get("type", "instrumental")
        role_info = self._infer_scene_music_role(scene_data)
        instruments = role_info.get("instruments", [])
        instrument_phrase = ", ".join(instruments) if instruments else ""

        if role_info.get("is_instrumental"):
            subject_desc = (
                f"the same main character and supporting band members{outfit_sentence}"
                if instrument_phrase
                else f"the same main character{outfit_sentence}"
            )
            action_desc = (
                f"performing an instrumental passage focused on {instrument_phrase}"
                if instrument_phrase
                else "performing an instrumental passage with dynamic musical body language"
            )
        else:
            subject_desc = f"{character_description}{outfit_sentence}"
            action_desc = interaction

        # Sentence 1: shot + subject + action + environment
        s1 = (
            f"A {shot_type}{visibility_sentence} frames {subject_desc}, "
            f"{action_desc}, in {env_text}.{props_sentence}"
        ).strip()

        # Sentence 2: style + lighting + mood
        mood = ref_mood or (global_theme if len(global_theme.split()) < 12 else "")
        mood_clause = f", mood {mood}" if mood else ""
        lighting_clause = f"{lighting_hint} lighting" if lighting_hint else "cinematic lighting"
        s2 = f"The visual style is {assigned_style} with {lighting_clause}{mood_clause}."

        # Sentence 3: camera movement + expression
        s3 = f"The camera {camera_motion} to emphasize {expression}."

        # Sentence 4: audio + dialogue
        if scene_type == "lyric" and lyric_text and lyric_text != "[INSTRUMENTAL]" and not role_info.get("is_instrumental"):
            s4 = (
                f'The character sings, "{lyric_text}", with clear mouth articulation, '
                "natural jaw/tongue motion, and frame-accurate lip sync."
            )
        else:
            if raw_text and raw_text != "[INSTRUMENTAL]":
                cue = raw_text if raw_text.startswith("[") else f"[{raw_text}]"
                if instrument_phrase:
                    s4 = f"Audio is instrumental, {cue}; feature {instrument_phrase} performance and B-roll inserts."
                else:
                    s4 = f"Audio is instrumental, {cue}; use expressive B-roll and supporting-performer coverage."
            else:
                if instrument_phrase:
                    s4 = f"Audio is instrumental; feature {instrument_phrase} performance with natural ensemble coverage."
                else:
                    s4 = "Audio is instrumental; no sung dialogue, focus on performance movement and B-roll."

        # Single paragraph as required by LTX-2 guidance.
        return " ".join([s1, s2, s3, s4, continuity_sentence]).replace("  ", " ").strip()

    def _get_edit_plan(self, screenplay_data, styles, thinking_model, instruct_model, debug_mode, llm_device, reset_context):
        """
        First LLM call (The Planner): Creates a high-level plan for which style to use for which scene.
        """
        planner_model = str(instruct_model or "").strip()
        planner_disabled = planner_model.lower() in {"", "disabled", "none", "no_api_models_found", "no_models_found"}
        thinking_model_name = str(thinking_model or "").strip()
        if planner_disabled and thinking_model_name and thinking_model_name.lower() not in {"disabled", "none"}:
            planner_model = thinking_model_name

        if len(screenplay_data) >= 24:
            chunk_plan, chunk_log = self._plan_in_chunks_with_llm(
                screenplay_data=screenplay_data,
                styles=styles,
                instruct_model=planner_model,
                debug_mode=debug_mode,
                llm_device=llm_device,
                reset_context=reset_context,
                chunk_size=10,
            )
            if chunk_plan is not None:
                return chunk_plan, "[Director] Chunk planner primary mode (large screenplay).\n" + chunk_log
            print(f"[Director] Chunk planner primary mode failed, falling back to global planner. Details: {chunk_log}")

        climax_indices = self._detect_climax_scenes(screenplay_data)
        climax_info = ""
        if climax_indices:
            climax_info = f"\nPre-analysis suggests the emotional climax occurs around scenes: {', '.join(map(str, climax_indices))}. Pay special attention to these scenes when assigning styles and camera work."
        
        screenplay_for_prompt = self._format_scene_manifest_for_planner(screenplay_data, max_text_len=96)
        if len(screenplay_data) > 40:
            print(f"[Director] Planning {len(screenplay_data)} scenes with compact manifest formatting.")

        required_indices = []
        for i, scene in enumerate(screenplay_data):
            try:
                required_indices.append(int(scene.get("index", i)))
            except Exception:
                required_indices.append(i)

        style_list_for_prompt = "\n".join([f"  - {s}" for s in styles])

        thinking_prompt = textwrap.dedent(f"""
            You are an expert music video director. Your task is to analyze the emotional rhythm of a song and create a high-level visual plan.
            You will assign a visual style to each scene based on the screenplay.

            **NARRATIVE ARC ANALYSIS:**
            1.  Read the entire screenplay to understand the song's structure, energy, and lyrical content.
            2.  A pre-analysis has been performed to locate potential climax scenes based on lyrical content. Use this as a guide.
            3.  For the climax scenes, you should assign more dynamic styles, and you will later instruct the cinematographer to use more dynamic shots.{climax_info}

            **CONTEXT:**
            - **Available Visual Styles:**
            {style_list_for_prompt}
            - **Screenplay (Lyrics & Scene Types):**
            {screenplay_for_prompt}

            **YOUR TASK:**
            Think step-by-step.
            - Which style fits the verse vs. the chorus? When should the energy shift?
            - Assign a style from the **Available Visual Styles** to EACH scene index.
            - Write down your reasoning for these choices.
        """).strip()

        plan_schema = {
            "scene_assignments": [
                {
                    "index": "int (The scene index)",
                    "style": "string (The EXACT name of the style chosen from the available list, e.g., 'Style_A')",
                    "reasoning": "string (A brief justification for this choice)"
                }
            ]
        }

        instruct_prompt_template = textwrap.dedent(f"""
            Based on the director's reasoning below, generate the final JSON plan.

            --- DIRECTOR'S REASONING ---
            {{reasoning}}
            ---

            The `scene_assignments` array MUST cover every scene index from the screenplay.
            Required indices: {required_indices}

            **Schema:** {json.dumps(plan_schema, indent=2)}
            
            **CRITICAL INSTRUCTIONS:**
            - The final output MUST be a single, raw JSON object.
            - Do not wrap the JSON in markdown code fences (```json ... ```).
            - Use standard double-quotes for all keys and string values.
            - Ensure all strings are properly terminated.
            - Do not add any text, explanations, or commentary before or after the JSON object.

            Return ONLY the JSON object.
        """).strip()

        ok, result_data, reasoning = utils.chain_of_thought_process(
            thinking_prompt=thinking_prompt,
            thinking_model=thinking_model,
            instruct_prompt=instruct_prompt_template,
            instruct_model=instruct_model,
            debug_mode=debug_mode,
            llm_device=llm_device,
            reset_context=reset_context,
            timeout=240,
        )

        if not ok:
            reasoning = f"[ERROR] Edit plan chain failed. Details: {result_data}\n\n--- Last successful reasoning ---\n{reasoning}"
            result_data = {}

        # Add robust JSON parsing
        parse_error = None
        assignments = []
        try:
            parsed = result_data
            if isinstance(result_data, str):
                parsed = json_utils.extract_and_parse_json(result_data)

            if isinstance(parsed, dict) and "scene_assignments" in parsed:
                assignments = parsed["scene_assignments"]
            elif isinstance(parsed, list):
                assignments = parsed
            else:
                raise ValueError("Unexpected JSON structure")

            # Validate assignments
            if not isinstance(assignments, list):
                raise ValueError("Assignments is not a list")

        except Exception as e:
            parse_error = f"Failed to parse edit plan: {str(e)}. Result: {result_data}"
            print(f"[Director] {parse_error}")
            assignments = []

        normalized, stats = self._normalize_scene_assignments(assignments, screenplay_data, styles)
        missing = stats.get("missing_indices", [])

        if missing:
            missing_preview = ", ".join(map(str, missing[:12]))
            if len(missing) > 12:
                missing_preview += ", ..."
            repair_reason = f"Planner output incomplete. Missing scene indices: {missing_preview}"
            print(f"[Director] {repair_reason}")
            repaired_plan, repair_log = self._repair_edit_plan_with_llm(
                screenplay_data=screenplay_data,
                styles=styles,
                instruct_model=planner_model,
                debug_mode=debug_mode,
                llm_device=llm_device,
                reset_context=reset_context,
                previous_result=result_data,
                previous_reasoning=reasoning,
            )
            if repaired_plan is not None:
                merged_log = reasoning + f"\n\n[Director] {repair_reason}\n[Director] {repair_log}"
                return repaired_plan, merged_log
            chunk_plan, chunk_log = self._plan_in_chunks_with_llm(
                screenplay_data=screenplay_data,
                styles=styles,
                instruct_model=planner_model,
                debug_mode=debug_mode,
                llm_device=llm_device,
                reset_context=reset_context,
            )
            if chunk_plan is not None:
                merged_log = (
                    reasoning
                    + f"\n\n[Director] {repair_reason}\n[Director] {repair_log}"
                    + "\n[Director] Global planner failed, chunk planner recovered full coverage."
                    + f"\n{chunk_log}"
                )
                return chunk_plan, merged_log
            error_log = (
                f"{parse_error + ' | ' if parse_error else ''}{repair_reason}. {repair_log}. "
                f"Chunk planner failed: {chunk_log}"
            )
            return [], error_log

        if parse_error:
            reasoning = reasoning + f"\n\n[Director] {parse_error}"

        invalid_rows = stats.get("invalid_rows", [])
        if invalid_rows:
            reasoning = reasoning + f"\n\n[Director] Ignored invalid assignment rows: {len(invalid_rows)}"

        return normalized, reasoning


    # In nodes_studio.py, in the PGFX_Studio_Director class, modify the _generate_shot_prompt method:

    def _sanitize_prompt_for_video_model(self, prompt):
        """Sanitize prompts to prevent CUDA errors in T5 encoder"""
        if not prompt:
            return ""
        import re
        # Remove problematic Unicode characters
        prompt = re.sub(r'[^\x20-\x7E\xA0-\xFF\u0100-\u017F\u0180-\u024F\u1E00-\u1EFF]', '', prompt)
        # Remove excessive special characters
        prompt = re.sub(r'[^\w\s\-\'\",.:;!?\(\)\[\]/&]', ' ', prompt)
        # Normalize whitespace
        prompt = re.sub(r'\s+', ' ', prompt).strip()
        # Keep prompts long enough for identity + scene detail while still bounded for LTX-2 contiguous paragraphs.
        if len(prompt) > 4000:
            prompt = prompt[:3800].rstrip() + " ... " + prompt[-150:].lstrip()
        return prompt

    def _apply_shot_continuity_directive(self, prompt, scene_index, hard_cut):
        """Append explicit transition intent so downstream shot-to-shot continuity is deterministic."""
        base = self._sanitize_prompt_for_video_model(prompt or "")
        if scene_index <= 0:
            directive = (
                "Opening shot. Establish character identity, wardrobe, and scene geography clearly."
            )
        elif hard_cut:
            directive = (
                "Hard cut to a new scene while preserving the same character identity, wardrobe, and tone."
            )
        else:
            directive = (
                "Continue directly from the previous shot's final frame, preserving character position, "
                "camera momentum, lighting direction, and spatial continuity."
            )

        if directive.lower() not in base.lower():
            base = f"{base} {directive}".strip()
        return self._sanitize_prompt_for_video_model(base)

    def _generate_shot_prompt(self, scene_data, assigned_style, character_description, visual_brief, scene_index, thinking_model, instruct_model, debug_mode, llm_device, reset_context, enable_visual_metaphors=False):
        """
        Second LLM call (The Shot Director): Generates a detailed prompt for a single scene.
        The LLM is now responsible for analyzing the lyric internally.
        """
        lyric_text = scene_data["text"]

        # Sanitize lyric_text to prevent errors in fallback prompts or with LLMs
        import re, string
        sanitized_lyric_text = ''.join(char for char in lyric_text if char in string.printable)
        sanitized_lyric_text = re.sub(r'\s+', ' ', sanitized_lyric_text).strip()
        
        # ADDITIONAL SANITIZATION FOR VIDEO MODEL COMPATIBILITY
        # Remove problematic characters that can cause CUDA errors in T5 encoder
        sanitized_lyric_text = re.sub(r'[^\x20-\x7E\xA0-\xFF\u0100-\u017F\u0180-\u024F\u1E00-\u1EFF]', '', sanitized_lyric_text)
        # Limit length to prevent token overflow
        if len(sanitized_lyric_text) > 320:
            sanitized_lyric_text = sanitized_lyric_text[:320] + "..."

        scene_type = scene_data["type"]
        role_info = self._infer_scene_music_role(scene_data)
        instruments = role_info.get("instruments", [])
        instrument_phrase = ", ".join(instruments) if instruments else "the active instruments"
        is_climax = scene_data.get("is_climax", False)

        climax_instruction = "This is the song's climax; use dynamic, high-energy camera work like dolly zooms or fast tracking shots." if is_climax else ""

        if role_info.get("is_instrumental") or scene_type == "instrumental":
            # Keep instrumental scenes character-led to preserve likeness continuity.
            task = (
                f"Create a cinematic instrumental scene in style '{assigned_style}' featuring "
                f"the same lead character '{character_description}' and, when appropriate, additional band members. "
                f"Match action to the music with visible {instrument_phrase} performance and purposeful B-roll. "
                f"Keep lead identity and wardrobe continuity anchored to the reference image."
            )
            analysis_instruction = (
                "Think about the musical phrasing and instrumentation. Build a shot that preserves lead-character identity, "
                "adds supporting performers when musically justified, and uses camera/lens choices that feel intentionally edited."
            )
        else:
            visual_metaphor = None
            if enable_visual_metaphors:
                visual_metaphor = self._enhance_visual_metaphors(
                    sanitized_lyric_text,
                    assigned_style,
                    thinking_model,
                    instruct_model,
                    debug_mode,
                    llm_device,
                    reset_context,
                )
            metaphor_guidance = ""
            if visual_metaphor:
                metaphor_guidance = f"Consider this visual metaphor: {visual_metaphor}."

            task = (
                f"Brainstorm a cinematic scene visualizing this lyric: '{sanitized_lyric_text}'. "
                f"The main character is '{character_description}'. The scene must be in style '{assigned_style}'. "
                f"Prioritize clear mouth visibility and syllable-accurate lip movement for the sung words. "
                f"{climax_instruction} {metaphor_guidance}"
            )
            analysis_instruction = "First, analyze the provided lyric for its emotional tone, key narrative elements, and any visual opportunities (like colors, textures, or actions). If a visual metaphor is provided, use it as your primary creative direction. Based on your analysis, think step-by-step about the lighting, camera angle, composition, and mood that would best represent the lyric."

        ref_env = str(visual_brief.get("reference_environment", "") or "").strip()
        ref_mood = str(visual_brief.get("reference_mood", "") or "").strip()
        ref_props = str(visual_brief.get("reference_props", "") or "").strip()
        env_hint = self._pick_from_list(visual_brief.get("environment_auto"), scene_index, "")
        lighting_hint = self._pick_from_list(visual_brief.get("lighting_auto"), scene_index, "")
        camera_hint = self._pick_from_list(visual_brief.get("camera_motion_auto"), scene_index, "")
        shot_hint = self._pick_from_list(visual_brief.get("shots_auto"), scene_index, "")
        interaction_hint = self._pick_from_list(visual_brief.get("physical_interaction_auto"), scene_index, "")
        expression_hint = self._pick_from_list(visual_brief.get("facial_expression_auto"), scene_index, "")

        thinking_prompt = textwrap.dedent(f"""
            You are a detail-oriented cinematographer creating LTX-2 prompts.
            Follow the LTX-2 prompt guidelines:
            - Single paragraph, present tense, 4–8 sentences.
            - Include shot type, subject description, action, environment, lighting, camera movement, and audio.
            - Dialogue/singing must be in double quotes. Performance cues may be in [brackets].
            - Preserve reference-character identity across scenes; do not switch subjects or wardrobe.

            REFERENCE IMAGE NOTES:
            - Environment: {ref_env}
            - Props: {ref_props}
            - Mood: {ref_mood}

            STYLE HINTS:
            - Environment hint: {env_hint}
            - Lighting hint: {lighting_hint}
            - Shot hint: {shot_hint}
            - Camera motion hint: {camera_hint}
            - Interaction hint: {interaction_hint}
            - Expression hint: {expression_hint}

            {analysis_instruction}
            **Task:** {task}
        """).strip()
        
        instruct_schema = {
            "positive_prompt": "string (Single-paragraph LTX-2 prompt, present tense, 4–8 sentences, includes audio/dialogue)",
            "negative_prompt": "string (What to avoid, e.g., text, watermarks, ugly, blurry)"
        }
        instruct_prompt = textwrap.dedent(f"""
            Based on the cinematographer's reasoning, generate a JSON object following the schema.

            **Schema:** {json.dumps(instruct_schema, indent=2)}

            **CRITICAL INSTRUCTIONS:**
            - The final output MUST be a single, raw JSON object.
            - Do not wrap the JSON in markdown code fences.
            - Use standard double-quotes for all keys and string values.
            - The positive_prompt must follow LTX-2 prompt rules (single paragraph, present tense, 4–8 sentences).

            Return ONLY the JSON object.
        """).strip()

        ok, result_data, reasoning = utils.chain_of_thought_process(
            thinking_prompt=thinking_prompt,
            thinking_model=thinking_model,
            instruct_prompt=instruct_prompt,
            instruct_model=instruct_model,
            debug_mode=debug_mode,
            llm_device=llm_device,
            reset_context=reset_context,
        )

        if not ok:
            reasoning = f"[ERROR] Shot prompt chain failed. Details: {result_data}\n\n--- Last successful reasoning ---\n{reasoning}"
            result_data = {}

        if debug_mode:
            print(f"[Director] Shot Gen Reasoning for Scene {scene_data['index']}:\n{reasoning}")

        # SANITIZE THE FINAL PROMPT OUTPUT FOR VIDEO MODEL COMPATIBILITY
        if isinstance(result_data, dict):
            pos_prompt = result_data.get("positive_prompt")
            if not pos_prompt:
                pos_prompt = self._build_ltx2_prompt(scene_data, assigned_style, character_description, visual_brief, scene_index)
            neg_prompt = result_data.get("negative_prompt", "text, watermark, ugly, blurry")
        else:
            print(f"\033[93m[Director] LLM shot generation failed for scene {scene_data['index']}. Using fallback.\033[0m")
            pos_prompt = self._build_ltx2_prompt(scene_data, assigned_style, character_description, visual_brief, scene_index)
            neg_prompt = "text, watermark, ugly, blurry"
        
        # Additional sanitization for video model compatibility
        pos_prompt = self._sanitize_prompt_for_video_model(pos_prompt)
        neg_prompt = self._sanitize_prompt_for_video_model(neg_prompt)

        # Ensure the final shot prompt always carries the current character identity text.
        char_desc = self._sanitize_prompt_for_video_model(character_description)
        if char_desc and char_desc.lower() not in pos_prompt.lower():
            pos_prompt = f"{char_desc}. {pos_prompt}".strip()
            pos_prompt = self._sanitize_prompt_for_video_model(pos_prompt)
        
        return pos_prompt, neg_prompt

    def _enhance_visual_metaphors(self, lyric_text, assigned_style, thinking_model, instruct_model, debug_mode, llm_device, reset_context):
        """Generate stronger visual metaphors for abstract lyrics"""
        thinking_prompt = f"""
        Analyze this lyric: "{lyric_text}"
        The desired style is: "{assigned_style}"
        Create 3 strong, distinct visual metaphors that could represent this concept cinematically.
        For each metaphor, describe a complete scene including:
        - A symbolic object or action.
        - A specific color palette.
        - A description of the lighting.
        - A suggested camera angle or movement.
        - How it connects to the lyric's meaning.
        Think step-by-step to develop creative and visually interesting ideas.
        """

        instruct_prompt = """
        Based on the creative reasoning, generate a JSON array of 3 objects. Each object should have 'metaphor_description' and 'reasoning' keys.

        **Schema:**
        [
            {
                "metaphor_description": "string (A rich, detailed visual description of the scene, combining all elements into a prompt-ready sentence.)",
                "reasoning": "string (A brief explanation of why this metaphor fits the lyric.)"
            }
        ]

        **CRITICAL INSTRUCTIONS:**
        - The final output MUST be a single, raw JSON object.
        - Do not wrap the JSON in markdown code fences.
        - Use standard double-quotes for all keys and string values.

        Return ONLY the JSON object.
        """

        ok, result_data, reasoning = utils.chain_of_thought_process(
            thinking_prompt=thinking_prompt,
            thinking_model=thinking_model,
            instruct_prompt=instruct_prompt,
            instruct_model=instruct_model,
            debug_mode=debug_mode,
            llm_device=llm_device,
            reset_context=reset_context,
        )

        if not ok:
            if debug_mode:
                print(f"[Director] Metaphor generation failed. Reasoning: {reasoning}. Result: {result_data}")
            return None

        if isinstance(result_data, list) and result_data:
            # For now, let's just pick the first one. A more advanced implementation could pick one randomly or based on reasoning.
            best_metaphor = result_data[0].get("metaphor_description", None)
            if debug_mode:
                print(f"[Director] Generated metaphors: {result_data}")
                print(f"[Director] Selected metaphor: {best_metaphor}")
            return best_metaphor
        
        return None

    def direct_scenes(self, SCREENPLAY, thinking_model, instruct_model, use_prompt_template, debug_mode, VISUAL_BRIEF=None, director_profile_override="None (Manual Input)", manual_character_override="", manual_styles_override="", enable_visual_metaphors=False, lock_character_seed=True, llm_device=getattr(config, "DEFAULT_LLM_DEVICE", "Default (GPU)"), reset_context=getattr(config, "DEFAULT_LLM_STATELESS", True)):
        # --- FIX: ROBUST CACHING ---
        # Create a stable unique hash using SORTED JSON serialization so that
        # dict ordering differences across runs don't invalidate the cache.
        def _make_stable_hash(screenplay, brief, profile, manual_char, manual_styles, use_template, lock_seed, enable_metaphors, t_model, i_model, device, ctx):
            screenplay_scenes = sorted(
                [{"index": s.get("index"), "type": s.get("type"), "text": s.get("text", "")} for s in screenplay],
                key=lambda x: x["index"]
            )
            brief_stable = {
                "character_description": str(brief.get("character_description", "") or ""),
                "visual_styles_auto": sorted([str(s) for s in (brief.get("visual_styles_auto") or [])]),
                "global_theme": str(brief.get("global_theme", "") or ""),
            } if brief else {}
            payload = {
                "scenes": screenplay_scenes,
                "brief": brief_stable,
                "profile": str(profile), "manual_char": str(manual_char).strip(),
                "manual_styles": str(manual_styles).strip(), "use_template": bool(use_template),
                "lock_seed": bool(lock_seed), "enable_metaphors": bool(enable_metaphors),
                "t_model": str(t_model), "i_model": str(i_model),
            }
            return hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")).hexdigest()

        screenplay_data = SCREENPLAY.get("data", [])
        if not screenplay_data:
            return ({}, "[ERROR] SCREENPLAY is empty or invalid.")

        input_hash = _make_stable_hash(
            screenplay_data, VISUAL_BRIEF or {}, director_profile_override, manual_character_override,
            manual_styles_override, use_prompt_template, lock_character_seed, enable_visual_metaphors,
            thinking_model, instruct_model, llm_device, reset_context
        )

        # Check if we already have a plan for this exact input
        if hasattr(self, '_cached_plan') and self._cached_plan.get('hash') == input_hash:
            print("[Director] Using cached Shot List (Skipping LLM/Template generation).")
            return ({"data": self._cached_plan['data']}, self._cached_plan['log'])

        shot_list = []
        full_reasoning_log = ""
        VISUAL_BRIEF = VISUAL_BRIEF or {}
        if debug_mode:
            print(f"[Director] use_prompt_template={use_prompt_template}")
        
        # --- NEW: Evolved Logic for Sourcing Creative Direction ---
        # Priority: 1. Manual Overrides -> 2. VISUAL_BRIEF -> 3. Profile Override
        final_char_desc = manual_character_override.strip() or str(VISUAL_BRIEF.get("character_description", "") or "").strip()
        if not final_char_desc:
            final_char_desc = "a consistent main subject performing to the music"
            msg = (
                "[Director] Missing character_description in VISUAL_BRIEF. "
                "Using fallback character description to keep the run valid."
            )
            print(msg)
            full_reasoning_log += msg + "\n\n"
        
        # Get styles from the brief or manual override
        styles_from_brief = VISUAL_BRIEF.get("visual_styles_auto", [])
        manual_styles_list = [s.strip() for s in manual_styles_override.splitlines() if s.strip()]
        
        final_visual_styles_list = manual_styles_list or styles_from_brief
        
        # Fallback to a static profile only if no dynamic or manual styles are provided
        if not final_visual_styles_list and director_profile_override != "None (Manual Input)":
            print(f"[Director] No dynamic brief or manual styles. Falling back to profile: '{director_profile_override}'")
            profile = director_profiles.NAMED_DIRECTOR_PROFILES.get(director_profile_override, {})
            if profile:
                final_char_desc = profile.get("character_description", final_char_desc)
                final_visual_styles_list = profile.get("visual_styles", [])

        if not final_visual_styles_list:
            final_visual_styles_list = [
                "Cinematic realism: grounded environments, coherent motion, detailed subject continuity"
            ]
            msg = (
                "[Director] Missing visual styles in VISUAL_BRIEF/profile. "
                "Using fallback style assignment to keep the run valid."
            )
            print(msg)
            full_reasoning_log += msg + "\n\n"

        final_visual_styles = "\n".join(final_visual_styles_list)

        # Use the final determined styles
        styles = [s.split(':')[0].strip() for s in final_visual_styles.splitlines() if s.strip()]
        if not styles:
            styles = ["Cinematic realism"]

        # Stage 1: Assign styles to scenes.
        if use_prompt_template:
            # Fast deterministic mode: avoid planner LLM call entirely.
            edit_plan = []
            for idx, scene in enumerate(screenplay_data):
                assigned_style = styles[idx % len(styles)]
                edit_plan.append({
                    "index": scene.get("index", idx),
                    "style": assigned_style,
                    "reasoning": "Template mode deterministic style assignment."
                })
            plan_reasoning = "[Director] Template mode: skipped LLM edit planner."
        else:
            edit_plan, plan_reasoning = self._get_edit_plan(
                screenplay_data,
                styles,
                thinking_model,
                instruct_model,
                debug_mode,
                llm_device,
                reset_context,
            )

        full_reasoning_log += "--- EDIT PLAN REASONING ---\n" + plan_reasoning + "\n\n"

        # Validate assignments (also smooths abrupt style transitions)
        edit_plan = self._validate_style_assignments(edit_plan, styles)

        expected_scene_count = len(screenplay_data)
        if not isinstance(edit_plan, list):
            err = f"[ERROR] Director edit plan is not a list (got {type(edit_plan).__name__})."
            print(err)
            return ({"data": []}, full_reasoning_log + err)
        if len(edit_plan) != expected_scene_count:
            err = (
                f"[ERROR] Director edit plan is incomplete: got {len(edit_plan)} assignments "
                f"for {expected_scene_count} scenes."
            )
            print(err)
            return ({"data": []}, full_reasoning_log + err)

        # Create a dictionary for quick lookup
        screenplay_dict = {s["index"]: s for s in screenplay_data}

        # --- ENHANCEMENT: Mark climax scenes based on plan ---
        climax_indices = {item['index'] for item in edit_plan if 'climax' in item.get('reasoning', '').lower()}
        if climax_indices:
            print(f"[Director] Identified climax scenes at indices: {climax_indices}")
            for index in climax_indices:
                if index in screenplay_dict:
                    screenplay_dict[index]['is_climax'] = True

        invalid_assignments = []

        plan_by_index = {}
        for row in edit_plan:
            if isinstance(row, dict) and "index" in row:
                plan_by_index[row["index"]] = row

        # Stage 2: Generate a detailed shot for each item in the plan
        for assignment in edit_plan:
            index = assignment.get("index")
            assigned_style = assignment.get("style")
            
            if index is None or assigned_style is None or index not in screenplay_dict:
                invalid_assignments.append(f"Invalid assignment: {assignment}")
                continue

            scene_data = screenplay_dict[index]
            prev_scene = screenplay_dict.get(index - 1)
            prev_style = ""
            prev_plan = plan_by_index.get(index - 1, {})
            if isinstance(prev_plan, dict):
                prev_style = str(prev_plan.get("style", "") or "")
            is_hard_cut = self._infer_hard_cut(
                scene_data=scene_data,
                prev_scene_data=prev_scene,
                assignment=assignment,
                assigned_style=assigned_style,
                prev_style=prev_style,
            )

            if use_prompt_template:
                if index == 0: # Print only on the first iteration
                    print("[Director] Using prompt template instead of LLM for shot generation.")
                pos_prompt = self._build_ltx2_prompt(scene_data, assigned_style, final_char_desc, VISUAL_BRIEF, index)
                neg_prompt = "text, watermark, ugly, blurry"
            else:
                # Generate the core prompt for this shot using an LLM.
                pos_prompt, neg_prompt = self._generate_shot_prompt(
                    scene_data,
                    assigned_style,
                    final_char_desc,
                    VISUAL_BRIEF,
                    index,
                    thinking_model,
                    instruct_model,
                    debug_mode,
                    llm_device,
                    reset_context,
                    enable_visual_metaphors,
                )

            pos_prompt = self._apply_shot_continuity_directive(pos_prompt, index, is_hard_cut)

            shot_list.append({
                "index": index,
                "positive": pos_prompt,
                "negative": neg_prompt,
                "seed": 101 if lock_character_seed else (index * 9999 + 101),
                "style": assigned_style,
                "hard_cut": is_hard_cut,
                "continuity_mode": "start" if int(index) <= 0 else ("hard_cut" if is_hard_cut else "continue"),
                "prompt_regenerated": True,
            })

        if invalid_assignments:
            err = (
                f"[ERROR] Director produced {len(invalid_assignments)} invalid assignment(s). "
                f"Example: {invalid_assignments[0]}"
            )
            print(err)
            return ({"data": []}, full_reasoning_log + "\n" + err)

        if len(shot_list) != expected_scene_count:
            err = (
                f"[ERROR] Director generated {len(shot_list)} shots for {expected_scene_count} scenes. "
                "Aborting to avoid incomplete/generic output."
            )
            print(err)
            return ({"data": []}, full_reasoning_log + "\n" + err)
            
        # At the very end of the function, save to cache before returning:
        self._cached_plan = {'hash': input_hash, 'data': shot_list, 'log': full_reasoning_log}
        return ({"data": shot_list}, full_reasoning_log)

# --- THE CINEMATOGRAPHER ---
class PGFX_Studio_Cinematographer:
    """
    Acts as the bridge between the data (SHOT_LIST, TIMING_MAP) and the generation loop.
    It fetches the correct prompt, audio, and data for the current scene index.
    Includes an auto-incrementing counter that resets per project, mimicking a trigger counter.
    Stateful: auto-index resets when project_name changes or when reset_counter is True.
    """
    _auto_index = 0
    _last_project_name = "" # Initialize as empty string

    # ADD THE METHOD HERE, BEFORE get_shot
    def _sanitize_prompt_for_video_model(self, prompt):
        """Enhanced sanitization for video model compatibility"""
        if not prompt:
            return ""

        import re
        import string

        # Remove problematic Unicode characters
        prompt = re.sub(r'[^\x20-\x7E\xA0-\xFF\u0100-\u017F\u0180-\u024F\u1E00-\u1EFF]', ' ', prompt)

        # Remove excessive special characters
        prompt = re.sub(r'[^\w\s\-\'\",.:;!?\(\)\[\]/&]', ' ', prompt)

        # Normalize whitespace
        prompt = re.sub(r'\s+', ' ', prompt).strip()

        # Remove markdown formatting
        prompt = re.sub(r'```.*?```', '', prompt, flags=re.DOTALL)
        prompt = re.sub(r'`[^`]+`', '', prompt)

        # Keep prompts long enough for identity + scene detail while still bounded.
        if len(prompt) > 1500:
            prompt = prompt[:1200].rstrip() + " ... " + prompt[-250:].lstrip()

        return prompt

    def _audio_duration_seconds(self, audio_dict):
        if not isinstance(audio_dict, dict):
            return 0.0
        waveform = audio_dict.get("waveform")
        sample_rate = audio_dict.get("sample_rate", 0)
        if not torch.is_tensor(waveform):
            return 0.0
        try:
            sr = float(sample_rate)
            if sr <= 0:
                return 0.0
            total_samples = int(waveform.shape[-1]) if waveform.ndim >= 1 else 0
            if total_samples <= 0:
                return 0.0
            return float(total_samples) / sr
        except Exception:
            return 0.0

    def _coerce_scene_index(self, value):
        try:
            return int(value)
        except Exception:
            return None

    def _find_scene_entry(self, entries, target_index):
        """
        Resolve by explicit `index` first, then positional fallback.
        Returns: (entry_or_none, source) where source is index|position|none.
        """
        if not isinstance(entries, list):
            return (None, "none")

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            idx = self._coerce_scene_index(entry.get("index", None))
            if idx == target_index:
                return (entry, "index")

        if 0 <= target_index < len(entries):
            fallback = entries[target_index]
            if isinstance(fallback, dict):
                return (fallback, "position")

        return (None, "none")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "SHOT_LIST": ("DICT",),
                "TIMING_MAP": ("DICT",),
                "PROJECT_CONFIG": ("DICT",),
                "mode": (["Auto-Increment", "Fixed"], {"default": "Auto-Increment"}),
                "scene_index": ("INT", {"default": 0, "min": 0, "step": 1, "tooltip": "The specific scene index to fetch in 'Fixed' mode."}),
            },
            "optional": {
                "reset_counter": ("BOOLEAN", {"default": False, "tooltip": "If True, forces the 'Auto-Increment' counter back to 0."}),
                "CHARACTER_TRACK": ("DICT",),
            }
        }
    RETURN_TYPES = ("STRING", "STRING", "INT", "AUDIO", "INT", "INT", "INT")
    RETURN_NAMES = ("positive", "negative", "seed", "audio_chunk", "num_frames", "scene_index", "remaining_scenes")
    FUNCTION = "get_shot"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"

    def _interrupt_execution(self):
        """Stops the execution of the ComfyUI queue."""
        try:
            server.PromptServer.instance.send_json("execution_interrupted", {"prompt_id": "PGFX_STUDIO_LOOP_TERMINATED"})
            print("\033[92m[Cinematographer] All scenes rendered. Workflow execution stopped.\033[0m")
        except Exception as e:
            print(f"[Cinematographer] Warning: Could not send execution interruption signal. {e}")

    def get_shot(self, SHOT_LIST, TIMING_MAP, PROJECT_CONFIG, mode, scene_index, reset_counter=False, CHARACTER_TRACK=None):
        project_name = PROJECT_CONFIG.get("project_name", "")
        
        # --- Counter Management ---
        if PGFX_Studio_Cinematographer._last_project_name != project_name:
            PGFX_Studio_Cinematographer._auto_index = 0
            PGFX_Studio_Cinematographer._last_project_name = project_name
            print(f"[Cinematographer] New project '{project_name}' detected, resetting auto-index to 0.")

        if reset_counter:
            PGFX_Studio_Cinematographer._auto_index = 0
            print("[Cinematographer] Counter explicitly reset to 0.")

        shot_list_data = SHOT_LIST.get("data", [])
        timing_map_data = TIMING_MAP.get("data", [])
        durations_frames = TIMING_MAP.get("durations_frames", [])
        timing_scene_count = 0
        if isinstance(durations_frames, list) and durations_frames:
            timing_scene_count = len(durations_frames)
        elif isinstance(timing_map_data, list):
            timing_scene_count = len(timing_map_data)

        shot_scene_count = len(shot_list_data) if isinstance(shot_list_data, list) else 0
        num_scenes = max(shot_scene_count, timing_scene_count)
        empty_audio = {"waveform": torch.zeros((1, 1, 1)), "sample_rate": 44100}

        # --- Index and State Management ---
        if mode == "Auto-Increment":
            current_index = PGFX_Studio_Cinematographer._auto_index

            if num_scenes > 0 and current_index >= num_scenes:
                print("\033[92m[Cinematographer] All scenes rendered. Resetting counter for next run.\033[0m")
                PGFX_Studio_Cinematographer._auto_index = 0  # Reset for next workflow run
                return ("", "", 0, empty_audio, 0, current_index, 0) # Stop execution for this path

            PGFX_Studio_Cinematographer._auto_index += 1
            remaining_scenes = max(0, num_scenes - PGFX_Studio_Cinematographer._auto_index)
        else: # Fixed mode
            current_index = scene_index
            remaining_scenes = max(0, num_scenes - current_index - 1)
            print(f"[Cinematographer] Fixed mode: Using provided index {current_index}.")

        # --- Data Retrieval ---
        if num_scenes == 0:
            raise ValueError(
                "[Cinematographer] SHOT_LIST/TIMING_MAP has zero scenes. "
                "Director planning failed or upstream contracts are disconnected."
            )
        
        # In Fixed mode, the user might provide an out-of-bounds index.
        if current_index >= num_scenes:
            print(f"[Cinematographer] Error: scene_index {current_index} is out of bounds (total scenes: {num_scenes}).")
            return ("", "", 0, empty_audio, 0, current_index, remaining_scenes)

        effective_index = current_index
        
        shot, shot_source = self._find_scene_entry(shot_list_data, effective_index)
        timing, timing_source = self._find_scene_entry(timing_map_data, effective_index)

        if shot_source == "position" or timing_source == "position":
            print(
                f"[Cinematographer] Warning: scene {effective_index} resolved via positional fallback "
                f"(shot={shot_source}, timing={timing_source})."
            )

        if shot is None or timing is None:
            if mode == "Auto-Increment":
                # Revert auto-index back so repeated runs don't skip unrendered scenes
                PGFX_Studio_Cinematographer._auto_index = current_index
            raise ValueError(
                f"[Cinematographer] No shot/timing data for scene index {effective_index}. "
                "Stopping run to avoid invalid audio/video generation."
            )

        # Optional character context (log-only, no prompt mutation yet)
        if CHARACTER_TRACK and isinstance(CHARACTER_TRACK, dict):
            timeline = CHARACTER_TRACK.get("timeline", [])
            if isinstance(timeline, list):
                match = next((t for t in timeline if t.get("scene_index") == effective_index), None)
                if match:
                    print(f"[Cinematographer] Character context: {match.get('character_id', 'unknown')} (scene {effective_index}).")

        num_frames = timing.get("num_frames", 0)
        audio_chunk = timing.get("audio_dict", empty_audio)
        fps = PROJECT_CONFIG.get("fps", 24)
        try:
            fps = max(1, int(fps))
        except Exception:
            fps = 24

        # Enforce audio/video duration parity at scene level.
        audio_dur = self._audio_duration_seconds(audio_chunk)
        if audio_dur > 0:
            expected_frames = max(1, int(round(audio_dur * fps)))
            try:
                current_frames = int(num_frames)
            except Exception:
                current_frames = 0
            if current_frames != expected_frames:
                print(
                    f"[Cinematographer] Adjusted num_frames from {current_frames} to {expected_frames} "
                    f"to match audio chunk duration {audio_dur:.2f}s at {fps} FPS."
                )
            num_frames = expected_frames

        # Sanitize prompts before returning them
        positive_prompt = shot.get("positive", "")
        negative_prompt = shot.get("negative", "")
        
        # Apply sanitization to prevent CUDA errors
        positive_prompt = self._sanitize_prompt_for_video_model(positive_prompt)
        negative_prompt = self._sanitize_prompt_for_video_model(negative_prompt)

        if not positive_prompt.strip():
            raise ValueError(
                f"[Cinematographer] Empty positive prompt at scene {effective_index}. "
                "Stopping run to avoid undefined generation."
            )

        print(f"[Cinematographer] Outputting data for scene {effective_index} ({remaining_scenes} remaining).")
        return (positive_prompt, negative_prompt, shot.get("seed", 0), audio_chunk, num_frames, effective_index, remaining_scenes)


# --- THE EDITOR ---
class PGFX_Studio_Editor:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PROJECT_CONFIG": ("DICT",),
                "video_frames": ("IMAGE",), 
                "scene_index": ("INT", {"default": 0, "min": 0}), # Added to track loop
            },
            "optional": {
                "audio_chunk": ("AUDIO",), # Optional: Save chunk audio if needed for preview
            }
        }
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("clip_path",)
    FUNCTION = "save_scene_clip"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"
    OUTPUT_NODE = True

    def save_scene_clip(self, PROJECT_CONFIG, video_frames, scene_index, audio_chunk=None):
        import imageio
        import numpy as np
        import shutil
        import subprocess
        import wave

        def _extract_audio_payload(chunk):
            waveform_val = None
            sample_rate_val = 0
            try:
                if chunk is None:
                    return waveform_val, sample_rate_val
                if isinstance(chunk, dict) or hasattr(chunk, "get"):
                    waveform_val = chunk.get("waveform")
                    sample_rate_val = chunk.get("sample_rate", 0)
                elif isinstance(chunk, (tuple, list)) and len(chunk) >= 2:
                    waveform_val = chunk[0]
                    sample_rate_val = chunk[1]
                else:
                    waveform_val = getattr(chunk, "waveform", None)
                    sample_rate_val = getattr(chunk, "sample_rate", 0)
            except Exception:
                return None, 0
            return waveform_val, sample_rate_val

        def _normalize_waveform(waveform_val):
            if waveform_val is None:
                return None
            try:
                if torch.is_tensor(waveform_val):
                    wf = waveform_val.detach().cpu()
                elif isinstance(waveform_val, np.ndarray):
                    wf = torch.from_numpy(waveform_val)
                else:
                    return None

                if wf.ndim == 3:
                    wf = wf.squeeze(0)
                if wf.ndim == 1:
                    wf = wf.unsqueeze(0)
                elif wf.ndim == 2 and wf.shape[0] > wf.shape[1] and wf.shape[1] <= 8:
                    # Some nodes emit [samples, channels]; convert to [channels, samples].
                    wf = wf.transpose(0, 1)

                if wf.ndim != 2:
                    return None
                return wf.float().contiguous()
            except Exception:
                return None

        def _write_pcm16_wav(path, waveform_val, sample_rate_val):
            arr = waveform_val.detach().cpu().numpy()
            arr = np.clip(arr, -1.0, 1.0)
            interleaved = (arr.T * 32767.0).astype(np.int16)
            with wave.open(path, "wb") as wf:
                wf.setnchannels(int(arr.shape[0]))
                wf.setsampwidth(2)
                wf.setframerate(int(sample_rate_val))
                wf.writeframes(interleaved.tobytes())
        
        root = PROJECT_CONFIG.get("root_path", "PromptCrafter_Studio")
        proj = PROJECT_CONFIG.get("project_name", "MyProject")
        fps = PROJECT_CONFIG.get("fps", 24)

        # 1. Setup Directory
        output_dir = os.path.join(folder_paths.get_output_directory(), root, proj)
        os.makedirs(output_dir, exist_ok=True)

        # 2. Filename Strategy (Scene_001.mp4)
        filename = f"Scene_{scene_index:03d}.mp4"
        full_path = os.path.join(output_dir, filename)

        print(f"[Editor] Saving Scene {scene_index} to {filename}...")

        # 3. Save Video Frames (ImageIO)
        images_np = (video_frames.cpu().numpy() * 255).astype(np.uint8)
        audio_waveform = None
        audio_sample_rate = 0
        has_valid_audio = False
        waveform, sample_rate = _extract_audio_payload(audio_chunk)
        if waveform is not None:
            try:
                sr = float(sample_rate)
                if sr > 0:
                    sample_count = int(waveform.shape[-1]) if hasattr(waveform, "shape") else 0
                    if sample_count > 0:
                        target_frames = max(1, int(round((float(sample_count) / sr) * float(fps))))
                        current_frames = int(images_np.shape[0]) if images_np.ndim >= 1 else 0
                        if current_frames > target_frames:
                            images_np = images_np[:target_frames]
                            print(f"[Editor] Trimmed frames {current_frames} -> {target_frames} to match audio duration.")
                        elif 0 < current_frames < target_frames:
                            pad_count = target_frames - current_frames
                            tail = np.repeat(images_np[-1:], pad_count, axis=0)
                            images_np = np.concatenate([images_np, tail], axis=0)
                            print(f"[Editor] Padded frames {current_frames} -> {target_frames} to match audio duration.")

                    audio_waveform = _normalize_waveform(waveform)
                    if torch.is_tensor(audio_waveform) and audio_waveform.numel() > 0:
                        has_valid_audio = True
                        audio_sample_rate = int(round(sr))
            except Exception as e:
                print(f"[Editor] Warning: could not align frame count to audio duration ({e}).")
        elif audio_chunk is not None:
            print(f"[Editor] Warning: audio_chunk payload not understood ({type(audio_chunk)}); saving silent clip.")

        silent_path = full_path
        if has_valid_audio:
            silent_path = os.path.join(output_dir, f"Scene_{scene_index:03d}_silent.mp4")
        try:
            imageio.mimwrite(silent_path, images_np, fps=fps, codec='libx264', quality=8, macro_block_size=1)
        except Exception as e:
            print(f"[Editor] Error saving clip: {e}")
            return ("",)

        if has_valid_audio:
            ffmpeg_path = shutil.which("ffmpeg")
            if ffmpeg_path:
                temp_audio_path = os.path.join(output_dir, f"Scene_{scene_index:03d}_audio.wav")
                try:
                    _write_pcm16_wav(temp_audio_path, audio_waveform, audio_sample_rate)
                    mux_cmd = [
                        ffmpeg_path,
                        "-y",
                        "-i",
                        silent_path,
                        "-i",
                        temp_audio_path,
                        "-c:v",
                        "copy",
                        "-c:a",
                        "aac",
                        "-b:a",
                        "192k",
                        "-shortest",
                        full_path,
                    ]
                    subprocess.run(mux_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if os.path.exists(silent_path):
                        os.remove(silent_path)
                except Exception as e:
                    print(f"[Editor] Warning: failed to mux scene audio ({e}); keeping silent scene clip.")
                    try:
                        if os.path.exists(silent_path) and silent_path != full_path:
                            shutil.move(silent_path, full_path)
                    except Exception:
                        pass
                finally:
                    try:
                        if os.path.exists(temp_audio_path):
                            os.remove(temp_audio_path)
                    except Exception:
                        pass
            else:
                print("[Editor] Warning: ffmpeg not found; saving silent scene clip only.")
                try:
                    if os.path.exists(silent_path) and silent_path != full_path:
                        shutil.move(silent_path, full_path)
                except Exception:
                    pass

        # 4. Update Stitch List (The "Manifest")
        stitch_list_path = os.path.join(output_dir, "stitch_list.txt")
        
        # If this is Scene 0, we can optionally clear the old list to start fresh
        if scene_index == 0 and os.path.exists(stitch_list_path):
            try:
                os.remove(stitch_list_path)
            except: pass

        # Append this file to the list
        entry = f"file '{filename}'\n"
        
        # Read existing to prevent duplicates if re-running specific chunks
        existing_lines = []
        if os.path.exists(stitch_list_path):
            with open(stitch_list_path, 'r') as f:
                existing_lines = f.readlines()
        
        if entry not in existing_lines:
            # We must ensure the list stays sorted by scene index
            # Re-read, add new, sort, write back is safer
            all_files = [line.strip() for line in existing_lines if line.strip()]
            all_files.append(entry.strip())
            
            # Simple sort logic assuming "Scene_XXX" format
            all_files.sort()
            
            with open(stitch_list_path, 'w') as f:
                f.write('\n'.join(all_files) + '\n')

        return (full_path,)

# --- NEW NODES ---

class PGFX_Studio_Stylist:
    """
    The project's Visual Stylist. Manages Lora triggers, artistic influences, 
    and character consistency tags based on style_profiles.json.
    """
    @classmethod
    def INPUT_TYPES(cls):
        try:
            from ..core.profiles import pgfx_style_profiles as style_profiles
            style_profiles._load_style_profiles()
            style_options = style_profiles.get_style_override_options("Video")
        except Exception:
            style_options = ["None"]

        return {
            "required": {
                "base_style": (style_options, {"default": "None"}),
                "character_consistency_tags": ("STRING", {"multiline": True, "default": "wearing a tattered leather jacket, messy hair"}),
                "global_lighting_mood": (["Natural", "Cinematic High-Key", "Gritty Low-Key", "Neon/Cyber", "Vintage/Faded"], {"default": "Cinematic High-Key"}),
            },
            "optional": {
                "additional_lora_triggers": ("STRING", {"multiline": False, "default": ""}),
                "style_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.1}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("visual_identity_brief", "lora_conditioning_text")
    FUNCTION = "apply_style"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"

    def apply_style(self, base_style, character_consistency_tags, global_lighting_mood, additional_lora_triggers="", style_strength=1.0):
        from ..core.profiles import pgfx_style_profiles as style_profiles
        
        clean_name = re.sub(r'^\(.*\)\s*', '', base_style)
        profile = style_profiles.NAMED_STYLE_PROFILES.get(clean_name, {})
        
        inspiration = profile.get("inspiration", "A standard cinematic look.")
        keywords = style_profiles.STYLE_KEYWORDS.get(clean_name, "")
        
        visual_brief = textwrap.dedent(f"""
            **VISUAL IDENTITY:**
            - **Core Style:** {clean_name}
            - **Artistic Inspiration:** {inspiration}
            - **Lighting Palette:** {global_lighting_mood}
            - **Character Requirements:** {character_consistency_tags}
            - **Key Aesthetic Markers:** {keywords}
        """).strip()

        lora_tags = []
        if keywords: lora_tags.append(keywords)
        if additional_lora_triggers: lora_tags.append(additional_lora_triggers)
        
        tech_string = ", ".join(lora_tags)
        if style_strength != 1.0:
            tech_string = f"({tech_string}:{style_strength:.1f})"

        return (visual_brief, tech_string)

class PGFX_Studio_ScriptSupervisor:
    """
    The project's continuity checker. This node is a placeholder for a future
    implementation that will review the SHOT_LIST against the SCREENPLAY for
    narrative and emotional consistency.
    """
    @classmethod
    def INPUT_TYPES(cls):
        try:
            all_llm_models = creator_nodes.get_combined_models()
            if not all_llm_models:
                all_llm_models = ["disabled"]

            sorted_llm_models = _get_sorted_models_by_preference(all_llm_models)

            # Generalize default model selection to avoid specific unsupported models
            thinking_default = _select_model_default(
                sorted_llm_models,
                lambda name: "qwen" in name.lower() and "thinking" in name.lower()
            )
            instruct_default = _select_model_default(
                sorted_llm_models,
                lambda name: "qwen" in name.lower() and "instruct" in name.lower()
            )
        except Exception as e:
            print(f"[Script Supervisor] Error loading models: {e}")
            all_llm_models = ["disabled"]
            thinking_default = "disabled"
            instruct_default = "disabled"

        return {
            "required": {
                "SHOT_LIST": ("DICT",),
                "SCREENPLAY": ("DICT",),
                "thinking_model": (all_llm_models, {"default": thinking_default}),
                "instruct_model": (all_llm_models, {"default": instruct_default}),
                "debug_mode": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                **_studio_llm_runtime_optional_inputs(),
            },
        }
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("continuity_report",)
    FUNCTION = "review"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"

    def review(self, SHOT_LIST, SCREENPLAY, thinking_model, instruct_model, debug_mode=False, llm_device=getattr(config, "DEFAULT_LLM_DEVICE", "Default (GPU)"), reset_context=getattr(config, "DEFAULT_LLM_STATELESS", True)):
        shot_list_data = SHOT_LIST.get("data", [])
        screenplay_data = SCREENPLAY.get("data", [])

        if not shot_list_data or not screenplay_data:
            return ("Not enough data to perform a review.",)

        # Prepare the data for the LLM, truncating if too long to prevent context overflow.
        MAX_LINES_FOR_REVIEW = 20
        if len(screenplay_data) > MAX_LINES_FOR_REVIEW:
            print(f"\033[93m[Script Supervisor] Screenplay has {len(screenplay_data)} scenes. Truncating for review prompt.\033[0m")
            screenplay_text = "\n".join([f"Scene {s['index']} ({s['type']}): {s['text']}" for s in screenplay_data[:MAX_LINES_FOR_REVIEW]])
            screenplay_text += f"\n... and {len(screenplay_data) - MAX_LINES_FOR_REVIEW} more scenes."
        else:
            screenplay_text = "\n".join([f"Scene {s['index']} ({s['type']}): {s['text']}" for s in screenplay_data])

        if len(shot_list_data) > MAX_LINES_FOR_REVIEW:
            print(f"\033[93m[Script Supervisor] Shot list has {len(shot_list_data)} shots. Truncating for review prompt.\033[0m")
            shot_list_text = "\n".join([f"Scene {s['index']} (Style: {s['style']}): {s['positive']}" for s in shot_list_data[:MAX_LINES_FOR_REVIEW]])
            shot_list_text += f"\n... and {len(shot_list_data) - MAX_LINES_FOR_REVIEW} more shots."
        else:
            shot_list_text = "\n".join([f"Scene {s['index']} (Style: {s['style']}): {s['positive']}" for s in shot_list_data])

        thinking_prompt = textwrap.dedent(f"""
            You are a meticulous script supervisor. Your task is to review a screenplay and the corresponding shot list to identify any continuity errors or inconsistencies in theme, emotion, and style.

            **SCREENPLAY (Source of Truth):**
            ---
            {screenplay_text}
            ---

            **GENERATED SHOT LIST (To Be Reviewed):**
            ---
            {shot_list_text}
            ---

            **YOUR TASK:**
            Think step-by-step. Compare each scene in the screenplay to its generated shot.
            - Does the visual description in the shot list match the lyrical content and type (lyric/instrumental)?
            - Is the emotional tone consistent?
            - Are there any jarring visual shifts that don't align with the song's narrative arc?
            - Note any potential issues and provide a summary of your findings.
        """).strip()

        instruct_prompt = textwrap.dedent("""
            Based on the script supervisor's reasoning, generate a JSON object with a single key: "report".
            The value of "report" should be a string containing a concise, bulleted continuity report.
            If no major issues are found, the report should state that continuity is good.

            **CRITICAL INSTRUCTIONS:**
            - The final output MUST be a single, raw JSON object.
            - Do not wrap the JSON in markdown.
            - Do not add any text before or after the JSON.
            - Use standard double-quotes.

            Return ONLY the JSON object.
        """).strip()

        # The call to chain_of_thought_process will now use the default expect_json=True
        ok, result, _ = utils.chain_of_thought_process(
            thinking_prompt=thinking_prompt, thinking_model=thinking_model,
            instruct_prompt=instruct_prompt, instruct_model=instruct_model,
            debug_mode=debug_mode,
            llm_device=llm_device,
            reset_context=reset_context,
        )

        if not ok:
            return (f"Continuity review failed: {result}",)
        
        # Extract the report from the JSON
        if isinstance(result, dict) and "report" in result:
            report_text = result["report"]
            # Clean up the text if it's a string representation of a list
            if isinstance(report_text, list):
                report_text = "\n".join(map(str, report_text))
            return (report_text,)
        else:
            # Fallback if the model still fails to produce valid JSON, but gives a string
            if isinstance(result, str):
                return (f"Continuity review returned unexpected format. Raw output: {result}",)
            return ("Continuity review failed: Model returned invalid data format.",)

class PGFX_Studio_Animator:
    @classmethod
    def INPUT_TYPES(cls):
        # Helper to get coarticulation keys safely

        # Helper to get coarticulation keys safely
        coarticulation_keys = ["Singing"]
        if viseme_utils and hasattr(viseme_utils, 'COARTICULATION_PROFILES'):
            coarticulation_keys = list(viseme_utils.COARTICULATION_PROFILES.keys())

        return {
            "required": {
                "AUDIO_META": ("DICT",),
                "PROJECT_CONFIG": ("DICT",),
                "current_index": ("INT", {"default": 0, "min": 0}),
                "face_template": ("IMAGE",),
                "debug": ("BOOLEAN", {"default": False}),
                "max_frames": ("INT", {"default": 0, "min": 0, "max": 99999, "step": 1}),
                "dot_size": ("INT", {"default": 3, "min": 1, "max": 20}),
                "line_thickness": ("INT", {"default": 2, "min": 1, "max": 20}),
            },
            "optional": {
                "coarticulation_profile": (coarticulation_keys, {"default": "Singing"}),
                "emotion_intensity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 3.0, "step": 0.1}),
                "draw_style": (["Dots", "Outline", "Filled Outline"], {"default": "Filled Outline"}),
                "dot_color": ("STRING", {"default": "white"}),
                "line_color": ("STRING", {"default": "white"}),
                "fill_color": ("STRING", {"default": "black"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE")
    RETURN_NAMES = ("animation_frames", "depth_maps", "canny_maps")
    FUNCTION = "animate"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"

    def animate(self, AUDIO_META, PROJECT_CONFIG, current_index, face_template,
                debug, max_frames, dot_size, line_thickness, **kwargs):
        import time, nltk
        import torch
        import numpy as np
        from g2p_en import G2p
        from PIL import Image, ImageDraw

        fps = PROJECT_CONFIG.get("fps", 24)
        width, height = PROJECT_CONFIG.get("width", 512), PROJECT_CONFIG.get("height", 512)
        
        # Word segments and overall durations
        word_segments = AUDIO_META.get("word_segments", [])
        durations = AUDIO_META.get("durations", [])
        instrumental_cues = AUDIO_META.get("instrumental_cues", [])
        
        if current_index >= len(durations): 
            return (face_template.repeat(max_frames, 1, 1, 1), face_template.repeat(max_frames, 1, 1, 1), face_template.repeat(max_frames, 1, 1, 1))
        
        scene_duration = durations[current_index]
        scene_start_time = sum(durations[:current_index])
        scene_end_time = scene_start_time + scene_duration

        # Filter words for this scene
        scene_words = [w for w in word_segments if w.get("start") is not None and w.get("end") is not None and
                       max(scene_start_time, w["start"]) < min(scene_end_time, w["end"])]

        g2p = viseme_utils.get_g2p()
        if not g2p:
            return (face_template.repeat(max_frames, 1, 1, 1), face_template.repeat(max_frames, 1, 1, 1), face_template.repeat(max_frames, 1, 1, 1))

        phoneme_script = []
        for w in scene_words:
            phonemes = g2p(w["word"])
            for p in phonemes:
                clean_p = re.sub(r'\d+', '', p)
                viseme = viseme_utils.PHONEME_TO_VISEME_MAP.get(clean_p, "SIL")
                phoneme_script.append({"viseme": viseme, "start": w["start"], "end": w["end"], "word": w["word"]})

        frames, depths, cannys = [], [], []
        profile_name = kwargs.get("coarticulation_profile", "Singing")
        
        for f in range(max_frames):
            t = scene_start_time + (f / fps)
            
            # Find active, prev, next visemes for coarticulation
            active_list = [p for p in phoneme_script if p["start"] <= t <= p["end"]]
            active = active_list[0] if active_list else {"viseme": "SIL", "start": t, "end": t+0.1, "word": ""}
            
            idx = phoneme_script.index(active) if active in phoneme_script else -1
            prev_v = phoneme_script[idx-1]["viseme"] if idx > 0 else "SIL"
            curr_v = active["viseme"]
            next_v = phoneme_script[idx+1]["viseme"] if idx != -1 and idx < len(phoneme_script)-1 else "SIL"
            
            # Blend landmarks
            lms = viseme_utils.blend_landmarks(
                viseme_utils.VISEME_TO_LANDMARK_MAP[prev_v], 
                viseme_utils.VISEME_TO_LANDMARK_MAP[curr_v], 
                viseme_utils.VISEME_TO_LANDMARK_MAP[next_v], 
                profile_name
            )
            
            # Intensity and Emotion
            intensity = viseme_utils.calculate_dynamic_intensity(t, active.get("start"), active.get("end"))
            emotion = "NEUTRAL"
            if active.get("word"):
                for emo, data in viseme_utils.EMOTION_PROFILES.items():
                    if any(k in active.get("word", "").lower() for k in data["keywords"]): 
                        emotion = emo
            
            # Draw
            main_img = Image.new("RGB", (width, height), "black")
            depth_img = Image.new("RGB", (width, height), "black")
            canny_img = Image.new("RGB", (width, height), "black")
            
            viseme_utils.draw_landmarks_helper(
                ImageDraw.Draw(main_img), lms, width, height, 
                kwargs.get("draw_style", "Filled Outline"), 
                kwargs.get("dot_color", "white"), kwargs.get("line_color", "white"), 
                kwargs.get("fill_color", "black"), dot_size, line_thickness, 
                emotion, intensity * kwargs.get("emotion_intensity", 1.0)
            )
            viseme_utils.draw_landmarks_helper(
                ImageDraw.Draw(depth_img), lms, width, height, 
                "Filled Outline", "white", "white", "gray", dot_size, line_thickness, 
                emotion, intensity
            )
            viseme_utils.draw_landmarks_helper(
                ImageDraw.Draw(canny_img), lms, width, height, 
                "Outline", "white", "white", "black", dot_size, line_thickness, 
                emotion, intensity
            )

            frames.append(torch.from_numpy(np.array(main_img).astype(np.float32) / 255.0))
            depths.append(torch.from_numpy(np.array(depth_img).astype(np.float32) / 255.0))
            cannys.append(torch.from_numpy(np.array(canny_img).astype(np.float32) / 255.0))

        return (torch.stack(frames), torch.stack(depths), torch.stack(cannys))


# --- NEW: VIDEO COMBINER ---
class PGFX_Studio_VideoCombiner:
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("blended_video_frames",)
    FUNCTION = "blend_videos"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "video_frames": ("IMAGE",),
                "current_index": ("INT", {"default": 0, "min": 0}),
                "SCENE_COUNT": ("INT", {"default": 1, "min": 1}),
                "PROJECT_CONFIG": ("DICT",),
                "TIMING_MAP": ("DICT",),
            },
            "optional": {
                "reset_combiner": ("BOOLEAN", {"default": False, "tooltip": "Set to True on the first iteration of a new project to clear previous data."}),
            },
        }

    def _trim_or_pad(self, video, target_frames):
        if video is None:
            return None
        if video.ndim != 4:
            raise ValueError(f"Expected video tensor with 4 dims (frames,H,W,C), got {tuple(video.shape)}")
        
        cur = int(video.shape[0])
        
        if cur > target_frames:
            # Trim if too long
            return video[:target_frames]
        
        if cur < target_frames:
            # Pad with the last frame if too short
            need = target_frames - cur
            last_frame = video[-1:].clone()
            pad = last_frame.repeat(need, 1, 1, 1)
            return torch.cat([video, pad], dim=0)
        
        return video

    def blend_videos(self, video_frames, current_index, SCENE_COUNT, PROJECT_CONFIG, TIMING_MAP, reset_combiner=False):
        # This node conforms an incoming video clip to the exact number of frames 
        # specified in the TIMING_MAP for the current scene_index.
        
        durations_frames = TIMING_MAP.get("durations_frames", [])

        if not durations_frames:
            print("[Video Combiner] Warning: TIMING_MAP does not contain 'durations_frames'. Returning input video as-is.")
            return (video_frames,)
            
        if current_index >= len(durations_frames):
            print(f"[Video Combiner] Warning: current_index {current_index} is out of bounds for durations_frames (len {len(durations_frames)}). Returning input video as-is.")
            return (video_frames,)

        target_frames = durations_frames[current_index]
        
        if target_frames <= 0:
            print(f"[Video Combiner] Warning: Target frames for index {current_index} is {target_frames}. This is invalid. Defaulting to 1 frame.")
            target_frames = 1

        conformed_video = self._trim_or_pad(video_frames, target_frames)
        
        print(f"[Video Combiner] Scene {current_index}: Conformed video from {video_frames.shape[0]} to {conformed_video.shape[0]} frames.")
        
        return (conformed_video,)

# --- PGFX STUDIO POSTMASTER NODE ---
class PGFX_Studio_PostMaster:
    """
    The Mastering Suite. Reads the 'stitch_list.txt' built by the Editor 
    and combines it with the Master Audio to produce the final result.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PROJECT_CONFIG": ("DICT",),
                "master_audio": ("AUDIO",),
                "auto_stitch_at_end": ("BOOLEAN", {"default": True, "tooltip": "Automatically render when the last scene is detected."}),
                "force_render_now": ("BOOLEAN", {"default": False, "tooltip": "Ignore scene count and render immediately with clips generated so far."}),
            },
            "optional": {
                 "remaining_scenes": ("INT", {"default": 999, "forceInput": True}),
                 "output_filename": ("STRING", {"default": "FINAL_MUSIC_VIDEO"}),
            }
        }
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("final_file_path",)
    FUNCTION = "render_master"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"
    OUTPUT_NODE = True

    def render_master(self, PROJECT_CONFIG, master_audio, auto_stitch_at_end, force_render_now, remaining_scenes=999, output_filename="FINAL_MUSIC_VIDEO"):
        # Determine if rendering should proceed
        should_render = force_render_now or (auto_stitch_at_end and remaining_scenes == 0)
        
        if not should_render:
            return (f"Waiting... ({remaining_scenes} scenes remaining)",)
        
        # --- The rest of the function proceeds only if should_render is True ---
        import subprocess
        import torchaudio

        root = PROJECT_CONFIG.get("root_path", "PromptCrafter_Studio")
        proj = PROJECT_CONFIG.get("project_name", "MyProject")
        
        work_dir = os.path.join(folder_paths.get_output_directory(), root, proj)
        stitch_list = os.path.join(work_dir, "stitch_list.txt")
        audio_path = os.path.join(work_dir, "temp_master_audio.wav")
        output_video = os.path.join(work_dir, f"{output_filename}.mp4")

        if not os.path.exists(stitch_list):
            return (f"Error: No stitch_list.txt found in {work_dir}",)

        print(f"[PostMaster] Rendering Master Video for {proj}...")

        # 1. Save Master Audio to disk
        waveform = master_audio["waveform"]
        sample_rate = master_audio["sample_rate"]
        # Ensure correct shape for torchaudio (Channels, Time)
        if waveform.ndim == 3: waveform = waveform.squeeze(0)
        torchaudio.save(audio_path, waveform, sample_rate)

        # 2. Run FFmpeg Concatenation
        cmd = [
            'ffmpeg', '-y',
            '-f', 'concat', '-safe', '0', '-i', stitch_list,
            '-i', audio_path,
            '-c:v', 'copy',
            '-c:a', 'aac', '-b:a', '192k',
            '-map', '0:v', '-map', '1:a',
            '-shortest', 
            output_video
        ]

        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print(f"[PostMaster] Success! Saved to: {output_video}")
            
            # Cleanup Audio
            if os.path.exists(audio_path): os.remove(audio_path)
            
            return (output_video,)
        except subprocess.CalledProcessError as e:
            error_message = e.stderr.decode()
            print(f"[PostMaster] FFmpeg failed: {error_message}")
            # Try to provide a more helpful error
            if "Unsafe file name" in error_message:
                print("[PostMaster] HINT: FFmpeg reported an unsafe file name. This can happen if your project_name or file paths contain special characters. Try using simpler names without spaces or symbols.")
            return ("FFmpeg Error (Check Console)",)




# --- STUDIO DIRECTOR UTILITIES ---
class PGFX_Studio_ProjectContext:
    """
    Builds a canonical project context string for THINK nodes.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "song_metadata": ("STRING", {"multiline": True, "default": ""}),
                "artist": ("STRING", {"multiline": False, "default": ""}),
                "genre": ("STRING", {"multiline": False, "default": ""}),
                "era": ("STRING", {"multiline": False, "default": ""}),
                "desired_aesthetic": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("PROJECT_CONTEXT",)
    FUNCTION = "build"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio"

    def build(self, song_metadata, artist, genre, era, desired_aesthetic):
        parts = [
            f"SONG_METADATA: {'' if song_metadata is None else str(song_metadata).strip()}",
            f"ARTIST: {'' if artist is None else str(artist).strip()}",
            f"GENRE: {'' if genre is None else str(genre).strip()}",
            f"ERA: {'' if era is None else str(era).strip()}",
            f"DESIRED_AESTHETIC: {'' if desired_aesthetic is None else str(desired_aesthetic).strip()}",
        ]
        if not any(p.split(":", 1)[1].strip() for p in parts):
            raise ValueError("PGFX_Studio_ProjectContext requires at least one non-empty field.")
        return ("\n".join(parts),)


class PGFX_Studio_StoreText:
    """
    Stores text artifacts (lyrics.json, visual_style.json, shot_plan.json) under the project output folder.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PROJECT_CONFIG": ("DICT",),
                "text_to_store": ("STRING", {"multiline": True}),
                "filename": ("STRING", {"multiline": False, "default": "artifact.json"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("stored_path",)
    FUNCTION = "store"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio/IO"
    OUTPUT_NODE = True

    def store(self, PROJECT_CONFIG, text_to_store, filename):
        if text_to_store is None or not str(text_to_store).strip():
            raise ValueError("PGFX_Studio_StoreText requires non-empty text_to_store.")
        if filename is None or not str(filename).strip():
            raise ValueError("PGFX_Studio_StoreText requires a valid filename.")

        root = PROJECT_CONFIG.get("root_path", "PromptCrafter_Studio")
        proj = PROJECT_CONFIG.get("project_name", "MyProject")
        out_dir = os.path.join(folder_paths.get_output_directory(), root, proj)
        os.makedirs(out_dir, exist_ok=True)

        clean_name = utils.TextCleaner.sanitize_filename(os.path.basename(str(filename)))
        if not clean_name:
            raise ValueError("PGFX_Studio_StoreText filename is invalid after sanitization.")
        full_path = os.path.join(out_dir, clean_name)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(str(text_to_store))

        return (full_path,)


class PGFX_Studio_LoadText:
    """
    Loads text artifacts from the project output folder.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PROJECT_CONFIG": ("DICT",),
                "filename": ("STRING", {"multiline": False, "default": "artifact.json"}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("loaded_text",)
    FUNCTION = "load"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio/IO"

    def load(self, PROJECT_CONFIG, filename):
        if filename is None or not str(filename).strip():
            raise ValueError("PGFX_Studio_LoadText requires a valid filename.")

        root = PROJECT_CONFIG.get("root_path", "PromptCrafter_Studio")
        proj = PROJECT_CONFIG.get("project_name", "MyProject")
        in_dir = os.path.join(folder_paths.get_output_directory(), root, proj)

        clean_name = utils.TextCleaner.sanitize_filename(os.path.basename(str(filename)))
        if not clean_name:
            raise ValueError("PGFX_Studio_LoadText filename is invalid after sanitization.")
        full_path = os.path.join(in_dir, clean_name)

        if not os.path.exists(full_path):
            raise FileNotFoundError(f"PGFX_Studio_LoadText could not find file: {full_path}")

        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()

        if not content.strip():
            raise ValueError(f"PGFX_Studio_LoadText loaded empty content from: {full_path}")
        return (content,)


class PGFX_Studio_ShotPlannerPromptBuilder:
    """
    Builds a deterministic prompt for QnAThink (shot planner) without any LLM calls.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PROJECT_CONTEXT": ("STRING", {"multiline": True}),
                "lyrics_json": ("STRING", {"multiline": True}),
                "visual_style_json": ("STRING", {"multiline": True}),
                "timing_json": ("STRING", {"multiline": True}),
                "shot_index": ("INT", {"default": 1, "min": 1}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "build"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio/Director"

    def build(self, PROJECT_CONTEXT, lyrics_json, visual_style_json, timing_json, shot_index):
        if PROJECT_CONTEXT is None or not str(PROJECT_CONTEXT).strip():
            raise ValueError("PGFX_Studio_ShotPlannerPromptBuilder requires PROJECT_CONTEXT.")
        if lyrics_json is None or not str(lyrics_json).strip():
            raise ValueError("PGFX_Studio_ShotPlannerPromptBuilder requires lyrics_json.")
        if visual_style_json is None or not str(visual_style_json).strip():
            raise ValueError("PGFX_Studio_ShotPlannerPromptBuilder requires visual_style_json.")
        if timing_json is None or not str(timing_json).strip():
            raise ValueError("PGFX_Studio_ShotPlannerPromptBuilder requires timing_json.")
        if shot_index < 1:
            raise ValueError("PGFX_Studio_ShotPlannerPromptBuilder shot_index must be >= 1.")

        import json as _json

        try:
            lyrics_data = _json.loads(lyrics_json)
        except Exception as e:
            raise ValueError(f"lyrics_json is not valid JSON: {e}")

        if not isinstance(lyrics_data, dict):
            raise ValueError("lyrics_json must be a JSON object.")

        lyric_key = f"lyricSegment{shot_index}"
        if lyric_key not in lyrics_data:
            raise ValueError(f"lyrics_json missing expected key: {lyric_key}")

        # Validate visual_style_json is JSON (content remains unchanged in prompt)
        try:
            _json.loads(visual_style_json)
        except Exception as e:
            raise ValueError(f"visual_style_json is not valid JSON: {e}")

        lyric_text = lyrics_data.get(lyric_key)
        if lyric_text is None or str(lyric_text).strip() == "":
            raise ValueError(f"lyrics_json value for {lyric_key} is empty.")

        prompt = textwrap.dedent(f"""
            You are a shot planner. Produce reasoning only. Do NOT output JSON.

            You are planning a single shot for:
            - Shot index (1-based): {shot_index}
            - Lyric key: {lyric_key}

            Provide reasoning for these fields:
            purpose, shot_type, motion, camera, continuity, pacing, notes.

            PROJECT CONTEXT:
            {PROJECT_CONTEXT}

            LYRIC (verbatim):
            {lyric_text}

            GLOBAL VISUAL STYLE (JSON):
            {visual_style_json}

            TIMING (JSON):
            {timing_json}
        """).strip()

        return (prompt,)


class PGFX_Studio_ShotPlanToShotList:
    """
    Converts shot_plan.json + lyrics.json + visual_style.json into a canonical SHOT_LIST.
    """
    NEGATIVE_PROMPT = (
        "text, subtitles, captions, watermark, logo, typography, extra people, crowd, "
        "duplicate faces, distorted anatomy, deformed hands, oversharpening, cartoon, "
        "illustration, CGI, low quality"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "shot_plan_json": ("STRING", {"multiline": True}),
                "lyrics_json": ("STRING", {"multiline": True}),
                "visual_style_json": ("STRING", {"multiline": True}),
            }
        }

    RETURN_TYPES = ("DICT",)
    RETURN_NAMES = ("SHOT_LIST",)
    FUNCTION = "assemble"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio/Director"

    def assemble(self, shot_plan_json, lyrics_json, visual_style_json):
        import json as _json

        if shot_plan_json is None or not str(shot_plan_json).strip():
            raise ValueError("shot_plan_json is empty.")
        if lyrics_json is None or not str(lyrics_json).strip():
            raise ValueError("lyrics_json is empty.")
        if visual_style_json is None or not str(visual_style_json).strip():
            raise ValueError("visual_style_json is empty.")

        try:
            shot_plan = _json.loads(shot_plan_json)
        except Exception as e:
            raise ValueError(f"shot_plan_json is not valid JSON: {e}")
        if not isinstance(shot_plan, dict) or "shots" not in shot_plan:
            raise ValueError("shot_plan_json must be an object with a 'shots' array.")
        shots = shot_plan.get("shots", [])
        if not isinstance(shots, list) or not shots:
            raise ValueError("shot_plan_json 'shots' must be a non-empty list.")

        try:
            lyrics_data = _json.loads(lyrics_json)
        except Exception as e:
            raise ValueError(f"lyrics_json is not valid JSON: {e}")
        if not isinstance(lyrics_data, dict):
            raise ValueError("lyrics_json must be a JSON object.")

        try:
            visual_style = _json.loads(visual_style_json)
        except Exception as e:
            raise ValueError(f"visual_style_json is not valid JSON: {e}")
        if not isinstance(visual_style, dict):
            raise ValueError("visual_style_json must be a JSON object.")

        required_visual_keys = ["style", "camera_language", "lighting", "mood", "palette", "era"]
        for key in required_visual_keys:
            if key not in visual_style:
                raise ValueError(f"visual_style_json missing required key: {key}")

        style_val = str(visual_style.get("style", ""))
        camera_language = str(visual_style.get("camera_language", ""))
        lighting = str(visual_style.get("lighting", ""))
        mood = str(visual_style.get("mood", ""))
        palette = str(visual_style.get("palette", ""))
        era = str(visual_style.get("era", ""))

        required_shot_keys = [
            "index", "lyric_segment", "purpose", "shot_type", "motion",
            "camera", "continuity", "pacing", "notes"
        ]

        shot_list = []
        for shot in shots:
            if not isinstance(shot, dict):
                raise ValueError("Each entry in shots must be an object.")
            for key in required_shot_keys:
                if key not in shot:
                    raise ValueError(f"Shot entry missing required key: {key}")

            try:
                index_1b = int(shot.get("index"))
            except Exception:
                raise ValueError(f"Shot index is not an integer: {shot.get('index')}")
            if index_1b < 1:
                raise ValueError(f"Shot index must be >= 1, got {index_1b}")

            lyric_segment = str(shot.get("lyric_segment"))
            expected_lyric_key = f"lyricSegment{index_1b}"
            if lyric_segment != expected_lyric_key:
                raise ValueError(f"Shot lyric_segment '{lyric_segment}' does not match index {index_1b}.")
            if lyric_segment not in lyrics_data:
                raise ValueError(f"lyrics_json missing key: {lyric_segment}")

            lyric_text = str(lyrics_data.get(lyric_segment))

            shot_type = str(shot.get("shot_type", "")).strip()
            motion = str(shot.get("motion", "")).strip()
            camera = str(shot.get("camera", "")).strip()
            pacing = str(shot.get("pacing", "")).strip()
            purpose = str(shot.get("purpose", "")).strip()
            continuity = str(shot.get("continuity", "")).strip()

            shot_block = f"{shot_type} shot, {motion}, {camera}, pacing {pacing}.\nNarrative intent: {purpose}."
            if continuity:
                shot_block += f"\nVisual continuity note: {continuity}."

            lyric_block = f"Inspired by lyric: {lyric_text}"
            style_block = (
                f"Visual style: {style_val}.\n"
                f"Camera language: {camera_language}.\n"
                f"Lighting: {lighting}.\n"
                f"Mood: {mood}.\n"
                f"Color palette: {palette}.\n"
                f"Era: {era}."
            )
            constraint_block = (
                "Cinematic still frame, realistic photography, no text, no watermark, no logos, no extra people."
            )

            positive_prompt = "\n".join([shot_block, lyric_block, style_block, constraint_block])

            index_0b = index_1b - 1
            shot_list.append({
                "index": index_0b,
                "positive": positive_prompt,
                "negative": self.NEGATIVE_PROMPT,
                "seed": index_0b * 9999 + 101,
                "style": style_val,
            })

        return ({"data": shot_list},)


# --- ADAPTERS ---
class PGFX_Studio_AudioPinAdapter:
    """
    Adapter to bridge SoundEngineer output pin 'AUDIO' to nodes expecting 'audio'.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "AUDIO": ("AUDIO",),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "adapt"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio/Adapters"

    def adapt(self, AUDIO):
        if not isinstance(AUDIO, dict) or "waveform" not in AUDIO or "sample_rate" not in AUDIO:
            raise ValueError("PGFX_Studio_AudioPinAdapter expected AUDIO dict with 'waveform' and 'sample_rate'.")
        return (AUDIO,)


# --- PROJECT CONFIG ADAPTER ---
class PGFX_Studio_ProjectConfigValidator:
    """
    Adapter to validate PROJECT_CONFIG core keys and allowed extended keys.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PROJECT_CONFIG": ("DICT",),
            },
            "optional": {
                "strict": ("BOOLEAN", {"default": False, "tooltip": "If True, raises on missing/invalid core keys."}),
            }
        }

    RETURN_TYPES = ("DICT", "DICT", "STRING")
    RETURN_NAMES = ("PROJECT_CONFIG", "PROJECT_CONFIG_CORE", "validation_report")
    FUNCTION = "validate"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio/Adapters"

    def _to_int(self, value, name, report, strict):
        try:
            return int(value)
        except Exception:
            msg = f"ERROR: {name} is not an int: {value}"
            if strict:
                raise ValueError(msg)
            report.append(msg)
            return None

    def _to_str(self, value, name, report, strict):
        if value is None:
            msg = f"ERROR: {name} missing."
            if strict:
                raise ValueError(msg)
            report.append(msg)
            return ""
        if isinstance(value, str):
            return value
        try:
            report.append(f"WARNING: {name} coerced to string.")
            return str(value)
        except Exception:
            msg = f"ERROR: {name} is not a string: {value}"
            if strict:
                raise ValueError(msg)
            report.append(msg)
            return ""

    def validate(self, PROJECT_CONFIG, strict=False):
        if not isinstance(PROJECT_CONFIG, dict):
            raise ValueError("PGFX_Studio_ProjectConfigValidator expected PROJECT_CONFIG as dict.")

        report = []
        cfg_out = dict(PROJECT_CONFIG)

        project_name = self._to_str(cfg_out.get("project_name"), "project_name", report, strict)
        root_path = self._to_str(cfg_out.get("root_path"), "root_path", report, strict)
        fps = self._to_int(cfg_out.get("fps"), "fps", report, strict)

        if fps is None:
            fps = 24
            report.append("WARNING: fps defaulted to 24.")
        elif fps <= 0:
            msg = f"WARNING: fps <= 0 ({fps}); clamped to 1."
            if strict:
                raise ValueError(msg)
            report.append(msg)
            fps = 1

        # Optional extended keys
        if "width" in cfg_out:
            width = self._to_int(cfg_out.get("width"), "width", report, strict)
            if width is None:
                width = 0
            if width <= 0:
                report.append(f"WARNING: width <= 0 ({width}).")
            cfg_out["width"] = width

        if "height" in cfg_out:
            height = self._to_int(cfg_out.get("height"), "height", report, strict)
            if height is None:
                height = 0
            if height <= 0:
                report.append(f"WARNING: height <= 0 ({height}).")
            cfg_out["height"] = height

        cfg_out["project_name"] = project_name
        cfg_out["root_path"] = root_path
        cfg_out["fps"] = fps

        cfg_core = {
            "project_name": project_name,
            "root_path": root_path,
            "fps": fps,
        }

        if not report:
            report.append("PROJECT_CONFIG valid.")

        return (cfg_out, cfg_core, "\n".join(report))


# --- PROJECT CONFIG TO SIZE ---
class PGFX_Studio_ProjectConfigToSize:
    """
    Adapter to extract width/height/fps from PROJECT_CONFIG and optionally align to a block size.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "PROJECT_CONFIG": ("DICT",),
            },
            "optional": {
                "align_to": ("INT", {"default": 8, "min": 1, "max": 128, "step": 1}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "INT")
    RETURN_NAMES = ("width", "height", "fps")
    FUNCTION = "extract"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio/Adapters"

    def _to_int(self, value, fallback):
        try:
            return int(value)
        except Exception:
            return int(fallback)

    def _align(self, value, align_to):
        align = max(1, int(align_to))
        return max(1, (int(value) // align) * align)

    def extract(self, PROJECT_CONFIG, align_to=8):
        if not isinstance(PROJECT_CONFIG, dict):
            raise ValueError("PGFX_Studio_ProjectConfigToSize expected PROJECT_CONFIG as dict.")
        width = self._to_int(PROJECT_CONFIG.get("width", 512), 512)
        height = self._to_int(PROJECT_CONFIG.get("height", 512), 512)
        fps = self._to_int(PROJECT_CONFIG.get("fps", 24), 24)
        width = self._align(width, align_to)
        height = self._align(height, align_to)
        if fps <= 0:
            fps = 24
        return (width, height, fps)


# --- TIMING MAP ADAPTER ---
class PGFX_Studio_TimingMapAdapter:
    """
    Adapter to validate and normalize TIMING_MAP:
    - Ensures core key 'durations_frames' exists and is list[int].
    - Preserves extended keys.
    - Normalizes data[] entries to align with durations_frames.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "TIMING_MAP": ("DICT",),
            },
            "optional": {
                "PROJECT_CONFIG": ("DICT",),
                "strict": ("BOOLEAN", {"default": False, "tooltip": "If True, raises on invalid/missing core keys instead of best-effort normalization."}),
            }
        }

    RETURN_TYPES = ("DICT", "DICT", "STRING")
    RETURN_NAMES = ("TIMING_MAP", "TIMING_MAP_CORE", "validation_report")
    FUNCTION = "adapt"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio/Adapters"

    def _int_list(self, values, report, strict):
        out = []
        for i, v in enumerate(values):
            try:
                out.append(int(v))
            except Exception:
                msg = f"WARNING: durations_frames[{i}]='{v}' invalid; set to 0."
                if strict:
                    raise ValueError(msg)
                report.append(msg)
                out.append(0)
        return out

    def adapt(self, TIMING_MAP, PROJECT_CONFIG=None, strict=False):
        if not isinstance(TIMING_MAP, dict):
            raise ValueError("PGFX_Studio_TimingMapAdapter expected TIMING_MAP as dict.")

        report = []
        timing_out = dict(TIMING_MAP)

        data_in = TIMING_MAP.get("data")
        durations = TIMING_MAP.get("durations_frames")

        # Derive durations from data if missing
        if durations is None and isinstance(data_in, list) and data_in:
            derived = []
            ok = True
            for entry in data_in:
                if not isinstance(entry, dict) or "num_frames" not in entry:
                    ok = False
                    break
                try:
                    derived.append(int(entry.get("num_frames", 0)))
                except Exception:
                    ok = False
                    break
            if ok:
                durations = derived
                report.append("INFO: durations_frames derived from data[num_frames].")

        if durations is None:
            msg = "ERROR: TIMING_MAP missing 'durations_frames' and could not derive from 'data'."
            if strict:
                raise ValueError(msg)
            report.append(msg)
            durations = []
        else:
            durations = self._int_list(list(durations), report, strict)

        # Normalize data list
        data_out = []
        if isinstance(data_in, list):
            for entry in data_in:
                if isinstance(entry, dict):
                    data_out.append(dict(entry))
                else:
                    report.append("WARNING: Non-dict entry removed from TIMING_MAP['data'].")

        # Build index map for fast lookup
        by_index = {}
        for entry in data_out:
            idx = entry.get("index")
            if isinstance(idx, int):
                by_index[idx] = entry

        # Optionally derive start/end from fps
        fps = None
        if isinstance(PROJECT_CONFIG, dict):
            try:
                fps_val = PROJECT_CONFIG.get("fps", None)
                fps = float(fps_val) if fps_val is not None else None
                if fps is not None and fps <= 0:
                    fps = None
            except Exception:
                fps = None

        if durations:
            normalized_data = []
            cumulative_sec = 0.0
            for idx, frames in enumerate(durations):
                entry = dict(by_index.get(idx, {}))
                if entry.get("index") != idx:
                    entry["index"] = idx
                if entry.get("num_frames") != frames:
                    if "num_frames" in entry:
                        report.append(f"INFO: data[{idx}].num_frames normalized to durations_frames ({frames}).")
                    entry["num_frames"] = frames

                if fps:
                    duration_sec = frames / fps
                    if "start" not in entry:
                        entry["start"] = cumulative_sec
                    if "end" not in entry:
                        entry["end"] = cumulative_sec + duration_sec
                    cumulative_sec += duration_sec

                normalized_data.append(entry)

            data_out = normalized_data

        timing_out["durations_frames"] = durations
        timing_out["data"] = data_out

        timing_core = {"durations_frames": durations}

        if not report:
            report.append("TIMING_MAP valid. Core key 'durations_frames' present and data normalized.")

        return (timing_out, timing_core, "\n".join(report))


# --- SCENE COUNT ADAPTER ---
class PGFX_Studio_SceneCountAdapter:
    """
    Adapter to normalize scene count signals:
    - SCENE_COUNT is the total number of scenes.
    - remaining_scenes is scenes left AFTER current scene index.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "SCENE_COUNT": ("INT",),
            },
            "optional": {
                "scene_index": ("INT",),
                "remaining_scenes": ("INT",),
                "strict": ("BOOLEAN", {"default": False, "tooltip": "If True, raise on invalid inputs instead of clamping."}),
            }
        }

    RETURN_TYPES = ("INT", "INT", "STRING")
    RETURN_NAMES = ("SCENE_COUNT", "remaining_scenes", "validation_report")
    FUNCTION = "adapt"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio/Adapters"

    def _to_int(self, value, name, report, strict):
        try:
            return int(value)
        except Exception:
            msg = f"ERROR: {name} is not an int: {value}"
            if strict:
                raise ValueError(msg)
            report.append(msg)
            return 0

    def adapt(self, SCENE_COUNT, scene_index=None, remaining_scenes=None, strict=False):
        report = []

        total = self._to_int(SCENE_COUNT, "SCENE_COUNT", report, strict)
        if total < 0:
            msg = f"WARNING: SCENE_COUNT < 0 ({total}); clamped to 0."
            if strict:
                raise ValueError(msg)
            report.append(msg)
            total = 0

        idx = 0
        if scene_index is not None:
            idx = self._to_int(scene_index, "scene_index", report, strict)
            if idx < 0:
                msg = f"WARNING: scene_index < 0 ({idx}); clamped to 0."
                if strict:
                    raise ValueError(msg)
                report.append(msg)
                idx = 0

        if remaining_scenes is None:
            # Compute remaining scenes after current index
            remaining = max(0, total - (idx + 1))
            report.append("INFO: remaining_scenes computed from SCENE_COUNT and scene_index.")
        else:
            remaining = self._to_int(remaining_scenes, "remaining_scenes", report, strict)
            if remaining < 0:
                msg = f"WARNING: remaining_scenes < 0 ({remaining}); clamped to 0."
                if strict:
                    raise ValueError(msg)
                report.append(msg)
                remaining = 0
            if total > 0 and remaining > total:
                msg = f"WARNING: remaining_scenes ({remaining}) > SCENE_COUNT ({total}); clamped."
                if strict:
                    raise ValueError(msg)
                report.append(msg)
                remaining = total

            expected = max(0, total - (idx + 1))
            if total > 0 and scene_index is not None and remaining != expected:
                report.append(
                    f"WARNING: remaining_scenes ({remaining}) does not match SCENE_COUNT/scene_index ({expected})."
                )

        if not report:
            report.append("Scene count valid.")

        return (total, remaining, "\n".join(report))


# --- AUTO-QUEUE ADAPTER ---
class PGFX_Studio_AutoQueue:
    """
    Adapter to auto-queue additional ComfyUI runs so each run renders one scene.
    Uses Impact Pack's `impact-add-queue` event if available.
    """
    _all_at_start_signature_by_project = {}
    _one_per_scene_seen = set()

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "remaining_scenes": ("INT", {"forceInput": True}),
                "scene_index": ("INT", {"forceInput": True}),
                "enable_auto_queue": ("BOOLEAN", {"default": True}),
                "queue_strategy": (["All At Start", "One Per Run"], {"default": "All At Start"}),
                "max_queue": ("INT", {"default": 64, "min": 1, "max": 1024}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("queue_status",)
    FUNCTION = "auto_queue"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio/Adapters"
    OUTPUT_NODE = True

    def _to_int(self, value, fallback=0):
        try:
            return int(value)
        except Exception:
            return fallback

    def _project_key(self, PROJECT_CONFIG):
        if isinstance(PROJECT_CONFIG, dict):
            name = str(PROJECT_CONFIG.get("project_name", "") or "").strip()
            if name:
                return name
        return "default"

    def _clear_project_state(self, project_key):
        self._all_at_start_signature_by_project.pop(project_key, None)
        prefix = f"{project_key}|"
        self._one_per_scene_seen = {sig for sig in self._one_per_scene_seen if not sig.startswith(prefix)}

    def auto_queue(self, remaining_scenes, scene_index, enable_auto_queue=True, queue_strategy="All At Start", max_queue=64, PROJECT_CONFIG=None, SCENE_COUNT=None, **_kwargs):
        if not enable_auto_queue:
            return ("Auto-queue disabled.",)

        remaining = self._to_int(remaining_scenes, 0)
        idx = self._to_int(scene_index, 0)
        max_q = max(1, self._to_int(max_queue, 1))
        project_key = self._project_key(PROJECT_CONFIG)
        scene_total = self._to_int(SCENE_COUNT, idx + remaining + 1)

        if scene_total > 0:
            expected_remaining = max(0, scene_total - (idx + 1))
            if remaining > expected_remaining:
                remaining = expected_remaining

        if remaining <= 0:
            self._clear_project_state(project_key)
            return ("No remaining scenes to queue.",)

        if queue_strategy == "All At Start":
            if idx != 0:
                return (f"Auto-queue skipped (scene_index={idx}).",)
            signature = f"{project_key}|{scene_total}|{remaining}|{max_q}"
            if self._all_at_start_signature_by_project.get(project_key) == signature:
                return ("Auto-queue skipped (already queued for this run signature).",)
            self._all_at_start_signature_by_project[project_key] = signature
            prefix = f"{project_key}|"
            self._one_per_scene_seen = {sig for sig in self._one_per_scene_seen if not sig.startswith(prefix)}
            runs = min(remaining, max_q)
            scene_signature = None
        else:
            scene_signature = f"{project_key}|{idx}"
            if scene_signature in self._one_per_scene_seen:
                return ("Auto-queue skipped (scene already queued for this run).",)
            self._one_per_scene_seen.add(scene_signature)
            runs = 1

        queued = 0
        try:
            if "server" not in globals():
                return ("Auto-queue unavailable: server not initialized.",)
            for _ in range(runs):
                server.PromptServer.instance.send_sync("impact-add-queue", {})
                queued += 1
        except Exception as e:
            if queue_strategy == "All At Start":
                self._all_at_start_signature_by_project.pop(project_key, None)
            elif scene_signature:
                self._one_per_scene_seen.discard(scene_signature)
            return (f"Auto-queue failed after {queued} job(s): {e}",)

        if queue_strategy == "All At Start" and remaining > runs:
            return (f"Auto-queued {queued} job(s). {remaining - runs} scene(s) left; raise max_queue or queue manually.",)

        return (f"Auto-queued {queued} job(s).",)


# --- SHOT LIST ADAPTER ---
class PGFX_Studio_ShotListAdapter:
    """
    Adapter to validate and normalize SHOT_LIST against TIMING_MAP.
    Ensures one entry per scene index and preserves creative metadata.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "SHOT_LIST": ("DICT",),
                "TIMING_MAP": ("DICT",),
            },
            "optional": {
                "strict": ("BOOLEAN", {"default": False, "tooltip": "If True, raises on missing/invalid entries."}),
            }
        }

    RETURN_TYPES = ("DICT", "DICT", "STRING")
    RETURN_NAMES = ("SHOT_LIST", "SHOT_LIST_CORE", "validation_report")
    FUNCTION = "adapt"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio/Adapters"

    def _to_int(self, value, name, report, strict):
        try:
            return int(value)
        except Exception:
            msg = f"ERROR: {name} is not an int: {value}"
            if strict:
                raise ValueError(msg)
            report.append(msg)
            return None

    def _to_str(self, value, name, report, strict):
        if value is None:
            msg = f"ERROR: {name} missing."
            if strict:
                raise ValueError(msg)
            report.append(msg)
            return ""
        if isinstance(value, str):
            return value
        try:
            report.append(f"WARNING: {name} coerced to string.")
            return str(value)
        except Exception:
            msg = f"ERROR: {name} is not a string: {value}"
            if strict:
                raise ValueError(msg)
            report.append(msg)
            return ""

    def adapt(self, SHOT_LIST, TIMING_MAP, strict=False):
        if not isinstance(SHOT_LIST, dict):
            raise ValueError("PGFX_Studio_ShotListAdapter expected SHOT_LIST as dict.")
        if not isinstance(TIMING_MAP, dict):
            raise ValueError("PGFX_Studio_ShotListAdapter expected TIMING_MAP as dict.")

        report = []
        shots_in = SHOT_LIST.get("data", [])
        if not isinstance(shots_in, list):
            report.append("WARNING: SHOT_LIST['data'] is not a list. Treating as empty.")
            shots_in = []

        durations = TIMING_MAP.get("durations_frames")
        if isinstance(durations, list):
            expected_count = len(durations)
        else:
            timing_data = TIMING_MAP.get("data", [])
            if isinstance(timing_data, list):
                expected_count = len(timing_data)
                report.append("INFO: expected scene count derived from TIMING_MAP['data'].")
            else:
                expected_count = len(shots_in)
                report.append("WARNING: TIMING_MAP missing durations_frames/data. Using SHOT_LIST length.")

        if expected_count > 0 and not shots_in:
            msg = "ERROR: SHOT_LIST is empty; refusing to synthesize placeholder scenes."
            if strict:
                raise ValueError(msg)
            report.append(msg)
            shot_out = dict(SHOT_LIST)
            shot_out["data"] = []
            return (shot_out, {"data": []}, "\n".join(report))

        # Build index -> shot mapping
        by_index = {}
        for entry in shots_in:
            if not isinstance(entry, dict):
                report.append("WARNING: Non-dict entry removed from SHOT_LIST['data'].")
                continue
            idx = self._to_int(entry.get("index"), "shot.index", report, strict)
            if idx is None:
                continue
            if idx in by_index:
                report.append(f"WARNING: Duplicate shot index {idx}; keeping first.")
                continue
            by_index[idx] = dict(entry)

        normalized = []
        core_list = []

        for idx in range(max(0, expected_count)):
            entry = dict(by_index.get(idx, {}))
            if not entry:
                msg = f"ERROR: Missing shot for index {idx}."
                if strict:
                    raise ValueError(msg)
                report.append(msg)
                continue

            # Ensure required keys
            entry["index"] = idx
            entry["positive"] = self._to_str(entry.get("positive"), "positive", report, strict)
            entry["negative"] = self._to_str(entry.get("negative"), "negative", report, strict)
            seed = self._to_int(entry.get("seed"), "seed", report, strict)
            entry["seed"] = 0 if seed is None else seed
            entry["style"] = self._to_str(entry.get("style"), "style", report, strict)

            normalized.append(entry)
            core_list.append({
                "index": entry["index"],
                "positive": entry["positive"],
                "negative": entry["negative"],
                "seed": entry["seed"],
                "style": entry["style"],
            })

        extra_indices = [i for i in by_index.keys() if i < 0 or i >= expected_count]
        if extra_indices:
            report.append(f"WARNING: Dropped shots outside timing range: {sorted(extra_indices)}.")

        if expected_count > 0 and len(normalized) != expected_count:
            report.append(f"ERROR: SHOT_LIST incomplete ({len(normalized)}/{expected_count}).")

        shot_out = dict(SHOT_LIST)
        shot_out["data"] = normalized
        shot_core = {"data": core_list}

        if not report:
            report.append("SHOT_LIST valid.")

        return (shot_out, shot_core, "\n".join(report))


# --- CHARACTER TRACK ADAPTER ---
class PGFX_Studio_CharacterTrackAdapter:
    """
    Adapter to validate and normalize CHARACTER_TRACK against TIMING_MAP.
    Ensures scene indices align, normalizes character IDs, and derives frame ranges.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "CHARACTER_TRACK": ("DICT",),
                "TIMING_MAP": ("DICT",),
            },
            "optional": {
                "strict": ("BOOLEAN", {"default": False, "tooltip": "If True, raises on missing/invalid entries."}),
            }
        }

    RETURN_TYPES = ("DICT", "DICT", "STRING")
    RETURN_NAMES = ("CHARACTER_TRACK", "CHARACTER_TRACK_CORE", "validation_report")
    FUNCTION = "adapt"
    CATEGORY = "☠️PGFX🏴‍☠️ /Studio/Adapters"

    def _to_int(self, value, name, report, strict):
        try:
            return int(value)
        except Exception:
            msg = f"ERROR: {name} is not an int: {value}"
            if strict:
                raise ValueError(msg)
            report.append(msg)
            return None

    def _to_str(self, value, name, report, strict):
        if value is None:
            msg = f"ERROR: {name} missing."
            if strict:
                raise ValueError(msg)
            report.append(msg)
            return ""
        if isinstance(value, str):
            return value
        try:
            report.append(f"WARNING: {name} coerced to string.")
            return str(value)
        except Exception:
            msg = f"ERROR: {name} is not a string: {value}"
            if strict:
                raise ValueError(msg)
            report.append(msg)
            return ""

    def adapt(self, CHARACTER_TRACK, TIMING_MAP, strict=False):
        if not isinstance(CHARACTER_TRACK, dict):
            raise ValueError("PGFX_Studio_CharacterTrackAdapter expected CHARACTER_TRACK as dict.")
        if not isinstance(TIMING_MAP, dict):
            raise ValueError("PGFX_Studio_CharacterTrackAdapter expected TIMING_MAP as dict.")

        report = []
        track_out = dict(CHARACTER_TRACK)

        characters_in = CHARACTER_TRACK.get("characters", {})
        if not isinstance(characters_in, dict):
            report.append("WARNING: CHARACTER_TRACK['characters'] is not a dict. Treating as empty.")
            characters_in = {}

        timeline_in = CHARACTER_TRACK.get("timeline", [])
        if not isinstance(timeline_in, list):
            report.append("WARNING: CHARACTER_TRACK['timeline'] is not a list. Treating as empty.")
            timeline_in = []

        durations = TIMING_MAP.get("durations_frames", [])
        if not isinstance(durations, list):
            report.append("WARNING: TIMING_MAP missing durations_frames. Frame alignment will be skipped.")
            durations = []

        # Build frame ranges from durations
        start_frames = []
        acc = 0
        for d in durations:
            try:
                frames = int(d)
            except Exception:
                frames = 0
            start_frames.append(acc)
            acc += max(0, frames)

        def _frame_range(scene_index):
            if scene_index < 0 or scene_index >= len(durations):
                return (None, None)
            start = start_frames[scene_index]
            end = start + max(0, int(durations[scene_index]))
            return (start, end)

        # Normalize characters
        characters_out = {}
        for cid, meta in characters_in.items():
            cid_norm = self._to_str(cid, "character_id", report, strict)
            if not cid_norm:
                continue
            meta_dict = meta if isinstance(meta, dict) else {}
            name = meta_dict.get("name") or meta_dict.get("display_name") or cid_norm
            aliases = meta_dict.get("aliases") or []
            if not isinstance(aliases, list):
                aliases = [str(aliases)]
            default_style = meta_dict.get("default_style")
            characters_out[cid_norm] = {
                "name": str(name),
                "aliases": [str(a) for a in aliases],
                "default_style": default_style if default_style is None else str(default_style),
            }

        # Normalize timeline
        timeline_out = []
        for entry in timeline_in:
            if not isinstance(entry, dict):
                report.append("WARNING: Non-dict timeline entry dropped.")
                continue
            scene_index = entry.get("scene_index")
            if scene_index is None and "index" in entry:
                scene_index = entry.get("index")
            scene_index = self._to_int(scene_index, "scene_index", report, strict)
            if scene_index is None:
                continue

            character_id = entry.get("character_id") or entry.get("speaker_id")
            character_id = self._to_str(character_id, "character_id", report, strict) or "unknown"

            if character_id not in characters_out:
                characters_out[character_id] = {
                    "name": entry.get("speaker_name") or character_id,
                    "aliases": [],
                    "default_style": None,
                }

            start_frame = entry.get("start_frame")
            end_frame = entry.get("end_frame")
            if start_frame is None or end_frame is None:
                sf, ef = _frame_range(scene_index)
                if sf is not None and ef is not None:
                    start_frame = sf
                    end_frame = ef
                else:
                    start_frame = start_frame if start_frame is not None else 0
                    end_frame = end_frame if end_frame is not None else 0

            text = entry.get("text", "")
            is_dialogue = entry.get("is_dialogue")
            if is_dialogue is None:
                is_dialogue = bool(text)
            emotion = entry.get("emotion")

            timeline_out.append({
                "scene_index": scene_index,
                "start_frame": int(start_frame),
                "end_frame": int(end_frame),
                "character_id": character_id,
                "text": str(text),
                "emotion": None if emotion is None else str(emotion),
                "is_dialogue": bool(is_dialogue),
            })

        track_out["characters"] = characters_out
        track_out["timeline"] = timeline_out

        core = {"characters": characters_out, "timeline": timeline_out}

        if not report:
            report.append("CHARACTER_TRACK valid.")

        return (track_out, core, "\n".join(report))


# --- NODE MAPPINGS ---
NODE_CLASS_MAPPINGS = {
    "PGFX_Studio_Producer": PGFX_Studio_Producer,
    "PGFX_Studio_SoundEngineer": PGFX_Studio_SoundEngineer,
    "PGFX_Studio_CreativeDirector": PGFX_Studio_CreativeDirector,
    "PGFX_Studio_Screenwriter": PGFX_Studio_Screenwriter,
    "PGFX_Studio_Director": PGFX_Studio_Director,
    "PGFX_Studio_Cinematographer": PGFX_Studio_Cinematographer,
    "PGFX_Studio_Editor": PGFX_Studio_Editor,
    "PGFX_Studio_PostMaster": PGFX_Studio_PostMaster, # Added
    "PGFX_Studio_ProjectContext": PGFX_Studio_ProjectContext,
    "PGFX_Studio_StoreText": PGFX_Studio_StoreText,
    "PGFX_Studio_LoadText": PGFX_Studio_LoadText,
    "PGFX_Studio_ShotPlannerPromptBuilder": PGFX_Studio_ShotPlannerPromptBuilder,
    "PGFX_Studio_ShotPlanToShotList": PGFX_Studio_ShotPlanToShotList,
    "PGFX_Studio_Stylist": PGFX_Studio_Stylist,
    "PGFX_Studio_Animator": PGFX_Studio_Animator,
    "PGFX_Studio_ScriptSupervisor": PGFX_Studio_ScriptSupervisor,
    "PGFX_Studio_AudioPinAdapter": PGFX_Studio_AudioPinAdapter,
    "PGFX_Studio_ProjectConfigValidator": PGFX_Studio_ProjectConfigValidator,
    "PGFX_Studio_ProjectConfigToSize": PGFX_Studio_ProjectConfigToSize,
    "PGFX_Studio_TimingMapAdapter": PGFX_Studio_TimingMapAdapter,
    "PGFX_Studio_SceneCountAdapter": PGFX_Studio_SceneCountAdapter,
    "PGFX_Studio_AutoQueue": PGFX_Studio_AutoQueue,
    "PGFX_Studio_ShotListAdapter": PGFX_Studio_ShotListAdapter,
    "PGFX_Studio_CharacterTrackAdapter": PGFX_Studio_CharacterTrackAdapter,
}

if nodes_sampler:
    NODE_CLASS_MAPPINGS["PGFX_Studio_Sampler"] = nodes_sampler.PGFX_Studio_Sampler

if nodes_controlnet:
    NODE_CLASS_MAPPINGS["PGFX_Studio_ControlNet"] = nodes_controlnet.PGFX_Studio_ControlNet

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_Studio_Producer": "🎬 Studio Producer (Config)",
    "PGFX_Studio_SoundEngineer": "🔊 Studio Sound Engineer (Audio)",
    "PGFX_Studio_CreativeDirector": "🧠 Studio Creative Director (Concept)",
    "PGFX_Studio_Screenwriter": "✍️ Studio Screenwriter (Lyrics)",
    "PGFX_Studio_Director": "🎥 Studio Director (Prompts)",
    "PGFX_Studio_Cinematographer": "📹 Studio Cinematographer (Shot)",
    "PGFX_Studio_Editor": "🎞️ Studio Editor (Scene Saver)",
    "PGFX_Studio_PostMaster": "🏗️ Studio PostMaster (Final Render)", # Added
    "PGFX_Studio_ProjectContext": "🧭 Studio Project Context",
    "PGFX_Studio_StoreText": "💾 Studio Store Text",
    "PGFX_Studio_LoadText": "📂 Studio Load Text",
    "PGFX_Studio_ShotPlannerPromptBuilder": "🧠 Studio Shot Planner Prompt Builder",
    "PGFX_Studio_ShotPlanToShotList": "🧱 Studio Shot Plan To Shot List",
    "PGFX_Studio_Stylist": "🎨 Studio Stylist (Looks)",
    "PGFX_Studio_Animator": "👄 Studio Animator (Visemes)",
    "PGFX_Studio_ScriptSupervisor": "📋 Studio Script Supervisor (Review)",
    "PGFX_Studio_Sampler": "🎤 Studio Sampler (Universal)",
    "PGFX_Studio_ControlNet": "👄 Studio ControlNet (Viseme Bridge)",
    "PGFX_Studio_AudioPinAdapter": "🔌 Studio Adapter (AUDIO→audio)",
    "PGFX_Studio_ProjectConfigValidator": "🔌 Studio Adapter (PROJECT_CONFIG core)",
    "PGFX_Studio_ProjectConfigToSize": "📐 Studio Adapter (PROJECT_CONFIG → Size)",
    "PGFX_Studio_TimingMapAdapter": "🔌 Studio Adapter (TIMING_MAP core)",
    "PGFX_Studio_SceneCountAdapter": "🔌 Studio Adapter (Scene Count)",
    "PGFX_Studio_AutoQueue": "🔁 Studio Auto-Queue (Scenes)",
    "PGFX_Studio_ShotListAdapter": "🔌 Studio Adapter (SHOT_LIST core)",
    "PGFX_Studio_CharacterTrackAdapter": "🔌 Studio Adapter (CHARACTER_TRACK core)",
}
