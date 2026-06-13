import os
import sys
import types
import importlib
import asyncio
import torch
import torch.serialization
import json
import warnings
import re
import librosa
from pathlib import Path
import torchaudio.transforms as T

from ..utils import pgfx_utils as utils
from ..core import pgfx_api_clients as api_clients
from ..core import pgfx_config as config

# Suppress the specific UserWarning from speechbrain that is triggered by whisperx
# warnings.filterwarnings("ignore", category=UserWarning, module='speechbrain.inference')

# ---[PromptCrafter] SpeechBrain/Torch compatibility patch (prevents recursion) ---
def _ensure_speechbrain_lazy_patch(debug_mode=False):
    _ensure_torchaudio_list_audio_backends()
    try:
        import speechbrain.utils.importutils as sb_importutils

        try:
            parts = torch.__version__.split('.')
            major = int(parts[0])
            minor = int(parts[1])
            should_patch = major > 2 or (major == 2 and minor >= 1)
        except Exception:
            should_patch = True

        LazyModule = sb_importutils.LazyModule
        if should_patch and not hasattr(LazyModule, '_sb_torch_patched'):
            _orig_getattr = LazyModule.__getattr__
            _guard = set()

            def patched_getattr(self, attr):
                key = (id(self), attr)
                if key in _guard:
                    raise AttributeError(attr)
                _guard.add(key)
                try:
                    return _orig_getattr(self, attr)
                except (RecursionError, ImportError):
                    # Break recursion loop or handle missing optional dependencies gracefully.
                    # Raising AttributeError here tells callers (like inspect) that the attribute/module is unavailable.
                    raise AttributeError(attr)
                finally:
                    _guard.discard(key)

            LazyModule.__getattr__ = patched_getattr
            LazyModule._sb_torch_patched = True
            if debug_mode:
                print("[PromptCrafter] Applied SpeechBrain LazyModule recursion guard.")
    except Exception as e:
        if debug_mode:
            print(f"[PromptCrafter] INFO: Could not apply SpeechBrain patch. Reason: {e}")
        if 'speechbrain' in sys.modules:
            del sys.modules['speechbrain']
# ---[End Patch]---

def _load_clean_dataloader_symbols(debug_mode=False):
    global TORCH_DATALOADER_CLEAN_INIT, TORCH_DATALOADER_CLEAN_RESET
    if TORCH_DATALOADER_CLEAN_INIT is not None:
        return
    try:
        import importlib.util
        import torch.utils.data.dataloader as dl
        spec = importlib.util.spec_from_file_location("_pc_torch_dataloader_clean", dl.__file__)
        if spec is None or spec.loader is None:
            return
        clean_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(clean_mod)
        TORCH_DATALOADER_CLEAN_INIT = clean_mod._BaseDataLoaderIter.__init__
        TORCH_DATALOADER_CLEAN_RESET = getattr(clean_mod._BaseDataLoaderIter, "_reset", None)
    except Exception as e:
        if debug_mode:
            print(f"[SRTCreator] Failed to load clean DataLoader symbols: {e}")

def _fix_speechbrain_dataloader_recursion(debug_mode=False):
    global TORCH_DATALOADER_RESET
    if TORCH_DATALOADER_RESET:
        return
    try:
        import torch.utils.data.dataloader as dl
        _load_clean_dataloader_symbols(debug_mode)
        if TORCH_DATALOADER_CLEAN_INIT is None:
            return

        init = dl._BaseDataLoaderIter.__init__
        old = getattr(dl._BaseDataLoaderIter, "__old_init__", None)

        def _is_speechbrain_func(fn):
            try:
                return "speechbrain" in (fn.__code__.co_filename or "")
            except Exception:
                return False

        # If SpeechBrain has patched the iterator, force restore clean init unconditionally.
        needs_reset = _is_speechbrain_func(init) or _is_speechbrain_func(old) or (old is init)

        if needs_reset:
            dl._BaseDataLoaderIter.__init__ = TORCH_DATALOADER_CLEAN_INIT
            if hasattr(dl._BaseDataLoaderIter, "__old_init__"):
                dl._BaseDataLoaderIter.__old_init__ = TORCH_DATALOADER_CLEAN_INIT
            if TORCH_DATALOADER_CLEAN_RESET is not None and hasattr(dl._BaseDataLoaderIter, "_reset"):
                dl._BaseDataLoaderIter._reset = TORCH_DATALOADER_CLEAN_RESET
            TORCH_DATALOADER_RESET = True
            if debug_mode:
                print("[SRTCreator] Reset torch DataLoader to remove SpeechBrain patch.")
    except Exception as e:
        if debug_mode:
            print(f"[SRTCreator] DataLoader recursion fix skipped: {e}")

# --- Global State for Model Caching ---
LOADED_MODELS = {
    "transcription_model": None,
    "transcription_model_name": "",
    "transcription_vad_method": "",
    "align_model": None,
    "align_model_metadata": None,
    "align_model_lang": ""
}

WHISPERX_MODULE = None
WHISPERX_PYANNOTE_AVAILABLE = None
WHISPERX_PYANNOTE_ERROR = None
TORCH_DATALOADER_RESET = False
TORCH_DATALOADER_CLEAN_INIT = None
TORCH_DATALOADER_CLEAN_RESET = None

class _PassthroughVAD:
    """VAD that treats all audio as speech. Used when real VAD model fails to load."""
    def __call__(self, audio_dict):
        import numpy as np
        from pyannote.core import SlidingWindowFeature, SlidingWindow

        waveform = audio_dict["waveform"]
        sample_rate = audio_dict["sample_rate"]
        duration = waveform.shape[-1] / float(sample_rate)
        n_frames = max(1, int(np.ceil(duration / 0.1)))
        data = np.ones((n_frames, 1), dtype=np.float32)
        window = SlidingWindow(duration=0.1, step=0.1, start=0.0)
        return SlidingWindowFeature(data, window)

def _clear_modules(prefixes):
    for name in list(sys.modules):
        for prefix in prefixes:
            if name == prefix or name.startswith(prefix + "."):
                del sys.modules[name]
                break

def _install_whisperx_pyannote_stub():
    module_name = "whisperx.vads.pyannote"
    if module_name in sys.modules:
        return
    stub = types.ModuleType(module_name)
    stub.__promptcrafter_stub__ = True

    class Pyannote:
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "Pyannote VAD is unavailable in this environment. "
                "Use vad_model='silero' or fix the pyannote/speechbrain installation."
            )

    stub.Pyannote = Pyannote
    sys.modules[module_name] = stub

def _ensure_torchaudio_list_audio_backends():
    try:
        import torchaudio
    except Exception:
        return

    if hasattr(torchaudio, "list_audio_backends"):
        return

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

def _add_pyannote_safe_globals(debug_mode=False):
    try:
        from pyannote.audio.core.model import Introspection
        from pyannote.audio.core.task import Specifications, Problem, Resolution
        from pyannote.audio.utils.powerset import Powerset
        from omegaconf import ListConfig, DictConfig
        from omegaconf.base import ContainerMetadata, Metadata
        from omegaconf.nodes import AnyNode, IntegerNode, FloatNode, StringNode, BooleanNode
        import typing
        import collections

        safe_globals = [
            Introspection,
            Specifications,
            Problem,
            Resolution,
            Powerset,
            ListConfig,
            DictConfig,
            ContainerMetadata,
            Metadata,
            AnyNode,
            IntegerNode,
            FloatNode,
            StringNode,
            BooleanNode,
            int, float, str, bool, list, dict, tuple, set,
            collections.defaultdict,
            typing.Any,
        ]

        if hasattr(torch, 'torch_version') and hasattr(torch.torch_version, 'TorchVersion'):
            safe_globals.append(torch.torch_version.TorchVersion)

        torch.serialization.add_safe_globals(safe_globals)
    except Exception as e:
        if debug_mode:
            print(f"[SRTCreator] Note: Pyannote safe globals not added: {e}")

def _prepare_whisperx_import(debug_mode=False, force=False):
    global WHISPERX_PYANNOTE_AVAILABLE, WHISPERX_PYANNOTE_ERROR
    if WHISPERX_PYANNOTE_AVAILABLE is not None and not force:
        return

    _ensure_torchaudio_list_audio_backends()
    _ensure_speechbrain_lazy_patch(debug_mode)

    try:
        # Deep import to validate full Pyannote + SpeechBrain dependency chain
        from pyannote.audio.pipelines import VoiceActivityDetection  # noqa: F401
        WHISPERX_PYANNOTE_AVAILABLE = True
        WHISPERX_PYANNOTE_ERROR = None
        stub = sys.modules.get("whisperx.vads.pyannote")
        if getattr(stub, "__promptcrafter_stub__", False):
            del sys.modules["whisperx.vads.pyannote"]
            _clear_modules(["whisperx.asr", "whisperx.vads"])
        return
    except Exception as e:
        WHISPERX_PYANNOTE_AVAILABLE = False
        WHISPERX_PYANNOTE_ERROR = e
        if debug_mode:
            print(f"[SRTCreator] Pyannote import failed; disabling Pyannote VAD. Reason: {e}")
        _clear_modules(["speechbrain", "pyannote", "whisperx.asr", "whisperx.vads", "whisperx.vads.pyannote"])
        _install_whisperx_pyannote_stub()

def _get_whisperx(debug_mode=False):
    global WHISPERX_MODULE
    _prepare_whisperx_import(debug_mode, force=True)
    if WHISPERX_MODULE is not None:
        return WHISPERX_MODULE
    WHISPERX_MODULE = importlib.import_module("whisperx")
    return WHISPERX_MODULE

class PromptCrafter_SRTCreator:
    DESCRIPTION = "Generates a highly accurate SRT file from an audio input, with optional AI-powered correction using a ground truth script."

    @classmethod
    def get_whisper_models(cls):
        """Scans the ComfyUI models directory recursively for faster-whisper models."""
        # Default models that can be downloaded by faster-whisper directly
        default_models = ["disabled", "tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large-v1", "large-v2", "large-v3", "distil-large-v2"]
        
        module_dir = os.path.dirname(os.path.abspath(__file__))
        comfy_root = os.path.abspath(os.path.join(module_dir, '..', '..', '..'))
        models_dir = os.path.join(comfy_root, "models")
        
        all_model_names = set()
        if os.path.isdir(models_dir):
            for root, _, files in os.walk(models_dir):
                if "model.bin" in files:
                    # --- DEFINITIVE FIX: Add all possible name formats for backward compatibility ---
                    # 1. The full, absolute path (most stable for loading, but ugly)
                    all_model_names.add(os.path.abspath(root))

                    # 2. The clean, Hugging Face-style ID (best for UI)
                    path_parts = Path(root).parts
                    for part in reversed(path_parts):
                        if part.startswith("models--"):
                            model_id = part.replace("models--", "", 1).replace("--", "/")
                            all_model_names.add(model_id)
                            # 3. The old, messy format for validation
                            all_model_names.add(part)
                            break

        # Combine defaults with found models, ensuring no duplicates and keeping a sensible order.
        return utils._unique_keep_order(default_models + sorted(list(all_model_names)))

    @classmethod
    def INPUT_TYPES(cls):
        whisper_models = cls.get_whisper_models()
        whisper_default = "large-v3" if "large-v3" in whisper_models else whisper_models[0]
        try:
            import importlib.util
            if importlib.util.find_spec("whisperx") is None and "disabled" in whisper_models:
                whisper_default = "disabled"
        except Exception:
            if "disabled" in whisper_models:
                whisper_default = "disabled"

        return {
            "required": {
                "audio": ("AUDIO",),
                "whisper_model": (whisper_models, {"default": whisper_default}),
                "language": ("STRING", {"default": "en", "tooltip": "Language code for transcription (e.g., 'en', 'es', 'ja')."}),
                "vad_method": (["silero", "pyannote"], {"default": "silero", "tooltip": "Voice activity detection backend. Pyannote requires compatible pyannote/speechbrain/torchaudio."}),
                "enable_ai_correction": ("BOOLEAN", {"default": False}),
                "correction_model": ("STRING", {"default": "ollama/mistral-large-3:675b-cloud", "tooltip": "The LLM to use for correcting the transcript."} ),
                "enable_translation": ("BOOLEAN", {"default": False, "tooltip": "Translate the transcription to English (requires English alignment model)."}),
                "debug_mode": ("BOOLEAN", {"default": False}),
                "segment_duration_seconds": ("FLOAT", {"default": 4.0, "min": 1.0, "max": 10.0, "step": 0.5}),
                "enable_ai_text_refinement": ("BOOLEAN", {"default": False}),
                "strict_speaker_detection": ("BOOLEAN", {"default": False, "tooltip": "If True, fail when a speaker is ambiguous or missing."}),
            },
            "optional": {
                "ground_truth_script": ("STRING", {"multiline": True, "default": "", "tooltip": "Optional: Provide a perfect script to correct the AI's transcription."} ),
                "llm_device": (
                    config.LLM_DEVICE_OPTIONS,
                    {
                        "default": config.DEFAULT_LLM_DEVICE,
                        "tooltip": "Where local LLM inference should run. 'Default (GPU)' uses configured acceleration; 'CPU' forces CPU for local GGUF/HF models.",
                    },
                ),
                "reset_context": (
                    "BOOLEAN",
                    {
                        "default": config.DEFAULT_LLM_STATELESS,
                        "tooltip": "If enabled, resets local model context before each call to avoid carrying prior conversation state.",
                    },
                ),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "DICT", "DICT", "STRING")
    RETURN_NAMES = ("srt_output", "plain_text_output", "structured_script", "timed_segments_json_string", "translated_srt_output", "translated_plain_text_output", "SCREENPLAY", "CHARACTER_TRACK", "validation_report")
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Text"

    def _load_vad_model_safe(self, whisperx_module, debug_mode):
        """Load VAD model on CPU to avoid cuDNN/weights_only GPU issues. Falls back to passthrough VAD."""
        _add_pyannote_safe_globals(debug_mode)
        try:
            from whisperx.vad import load_vad_model as _load_vad
            vad_model = _load_vad(torch.device("cpu"))
            if debug_mode:
                print("[SRTCreator] VAD model loaded on CPU successfully.")
            return vad_model
        except Exception as e:
            if debug_mode:
                print(f"[SRTCreator] VAD model loading failed; using passthrough VAD. Reason: {e}")
            return _PassthroughVAD()

    def _is_cudnn_available(self):
        """Check if cuDNN ops infer DLL (CTranslate2 8.x) is loadable."""
        if not torch.cuda.is_available():
            return False
        needed = "cudnn_ops_infer64_8.dll"
        search_dirs = [os.path.join(os.path.dirname(torch.__file__), "lib")]
        try:
            import importlib.util
            spec = importlib.util.find_spec("ctranslate2")
            if spec is not None and spec.origin:
                search_dirs.append(os.path.dirname(spec.origin))
        except Exception:
            pass
        for d in search_dirs:
            d = os.path.abspath(d)
            dll_path = os.path.join(d, needed)
            if os.path.exists(dll_path):
                try:
                    import ctypes
                    os.add_dll_directory(d)
                    ctypes.CDLL(dll_path)
                    return True
                except Exception:
                    pass
        return False

    def _load_whisperx_model(self, whisperx, model_path_or_name, device, load_kwargs, debug_mode):
        """Try loading whisperx model on GPU first; fall back to CPU on cuDNN errors."""
        devices_to_try = [device]
        if device.startswith("cuda"):
            devices_to_try.append("cpu")
        last_error = None
        for dev in devices_to_try:
            kw = dict(load_kwargs)
            if dev == "cpu":
                kw["compute_type"] = "float32"
            try:
                return whisperx.load_model(model_path_or_name, dev, **kw)
            except Exception as e:
                last_error = e
                if debug_mode:
                    print(f"[SRTCreator] whisperx load_model failed on {dev}; Reason: {e}")
                if dev == devices_to_try[-1]:
                    raise last_error
                continue

    def _load_transcription_model(self, whisper_model_name, vad_method, debug_mode, language="auto-detect"):
        """Loads and caches only the whisperx transcription model (no alignment)."""
        whisperx = _get_whisperx(debug_mode)
        global LOADED_MODELS
        gpu_ok = torch.cuda.is_available() and self._is_cudnn_available()
        if torch.cuda.is_available() and not gpu_ok and debug_mode:
            print("[SRTCreator] cuDNN ops DLL not found; forcing whisper to CPU.")
        device = "cuda" if gpu_ok else "cpu"
        _ensure_speechbrain_lazy_patch(debug_mode)

        if (
            LOADED_MODELS["transcription_model"] is None
            or LOADED_MODELS["transcription_model_name"] != whisper_model_name
            or LOADED_MODELS["transcription_vad_method"] != vad_method
        ):
            if debug_mode: print(f"[SRTCreator] Loading whisper model: {whisper_model_name}")

            model_path_or_name = whisper_model_name
            if "/" in whisper_model_name:
                model_path_or_name = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'models', 'faster-whisper', f"models--{whisper_model_name.replace('/', '--')}")

            selected_vad_method = (vad_method or "silero").lower().strip()
            effective_vad_method = selected_vad_method
            if selected_vad_method == "pyannote" and not WHISPERX_PYANNOTE_AVAILABLE:
                effective_vad_method = "silero"
            if debug_mode and effective_vad_method != selected_vad_method:
                reason = f": {WHISPERX_PYANNOTE_ERROR}" if WHISPERX_PYANNOTE_ERROR else ""
                print(f"[SRTCreator] Falling back to Silero VAD{reason}")

            vad_model = self._load_vad_model_safe(whisperx, debug_mode)
            load_kwargs = dict(
                compute_type="float16",
                vad_model=vad_model,
                language=None if language == "auto-detect" else language,
            )

            LOADED_MODELS["transcription_model"] = self._load_whisperx_model(
                whisperx, model_path_or_name, device, load_kwargs, debug_mode
            )
            LOADED_MODELS["transcription_model_name"] = whisper_model_name
            LOADED_MODELS["transcription_vad_method"] = effective_vad_method

        return LOADED_MODELS["transcription_model"]

    def _load_models(self, whisper_model_name, language, vad_method, debug_mode):
        """Loads and caches whisperx transcription and alignment models."""
        whisperx = _get_whisperx(debug_mode)
        global LOADED_MODELS
        gpu_ok = torch.cuda.is_available() and self._is_cudnn_available()
        if torch.cuda.is_available() and not gpu_ok and debug_mode:
            print("[SRTCreator] cuDNN ops DLL not found; forcing whisper to CPU.")
        device = "cuda" if gpu_ok else "cpu"
        _ensure_speechbrain_lazy_patch(debug_mode)

        # Load Transcription Model
        if (
            LOADED_MODELS["transcription_model"] is None
            or LOADED_MODELS["transcription_model_name"] != whisper_model_name
            or LOADED_MODELS["transcription_vad_method"] != vad_method
        ):
            if debug_mode: print(f"[SRTCreator] Loading whisper model: {whisper_model_name}")

            model_path_or_name = whisper_model_name
            if "/" in whisper_model_name:
                model_path_or_name = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'models', 'faster-whisper', f"models--{whisper_model_name.replace('/', '--')}")

            selected_vad_method = (vad_method or "silero").lower().strip()
            effective_vad_method = selected_vad_method
            if selected_vad_method == "pyannote" and not WHISPERX_PYANNOTE_AVAILABLE:
                effective_vad_method = "silero"
            if debug_mode and effective_vad_method != selected_vad_method:
                reason = f": {WHISPERX_PYANNOTE_ERROR}" if WHISPERX_PYANNOTE_ERROR else ""
                print(f"[SRTCreator] Falling back to Silero VAD{reason}")

            vad_model = self._load_vad_model_safe(whisperx, debug_mode)
            load_kwargs = dict(
                compute_type="float16",
                vad_model=vad_model,
                language=None if language == "auto-detect" else language,
            )

            LOADED_MODELS["transcription_model"] = self._load_whisperx_model(
                whisperx, model_path_or_name, device, load_kwargs, debug_mode
            )
            LOADED_MODELS["transcription_model_name"] = whisper_model_name
            LOADED_MODELS["transcription_vad_method"] = effective_vad_method

        # Load Alignment Model
        if LOADED_MODELS["align_model"] is None or LOADED_MODELS["align_model_lang"] != language:
            if debug_mode: print(f"[SRTCreator] Loading alignment model for language: {language}")
            try:
                align_model, align_meta = whisperx.load_align_model(language_code=language, device=device)
                LOADED_MODELS["align_model"] = align_model
                LOADED_MODELS["align_model_metadata"] = align_meta
                LOADED_MODELS["align_model_lang"] = language
            except Exception as e:
                if debug_mode:
                    print(f"[SRTCreator] Alignment model loading failed; continuing without alignment. Reason: {e}")
                LOADED_MODELS["align_model"] = None
                LOADED_MODELS["align_model_metadata"] = None
                LOADED_MODELS["align_model_lang"] = language

        return LOADED_MODELS["transcription_model"], LOADED_MODELS["align_model"], LOADED_MODELS["align_model_metadata"]

    def _generate_padded_srt(self, word_segments, segment_duration_seconds, total_audio_duration, debug_mode=False):
        """
        Generate SRT with words distributed into fixed-duration time segments.
        """
        if not word_segments:
            return []

        # Sort words by start time
        sorted_words = sorted(word_segments, key=lambda x: x['start'])
        
        srt_entries = []
        
        # Generate fixed-duration segments covering entire audio
        segment_start_time = 0.0
        
        while segment_start_time < total_audio_duration:
            segment_end_time = min(segment_start_time + segment_duration_seconds, total_audio_duration)
            
            # Find words that start within this time segment
            words_in_segment = []
            for word in sorted_words:
                if segment_start_time <= word['start'] < segment_end_time:
                    words_in_segment.append(word)
            
            # Create segment
            if words_in_segment:
                text = " ".join([word['word'].strip() for word in words_in_segment]).strip()
                # Use actual word timings for display
                actual_start = words_in_segment[0]['start']
                actual_end = words_in_segment[-1]['end']
                srt_entries.append((actual_start, actual_end, text))
            else:
                # Empty segment
                srt_entries.append((segment_start_time, segment_end_time, ""))
            
            segment_start_time += segment_duration_seconds
        
        return srt_entries

    def _simple_structure_detection(self, text):
        """
        Simple, fast structure detection without LLM calls.
        """
        if not text:
            return text
            
        lines = text.split('\n')
        structured_lines = []
        
        chorus_indicators = ['chorus', 'refrain', 'hook']
        verse_indicators = ['verse', 'stanza']
        bridge_indicators = ['bridge', 'interlude']
        
        for line in lines:
            line_lower = line.lower().strip()
            if not line_lower:
                continue
                
            # Simple pattern matching for structure tags
            if any(indicator in line_lower for indicator in chorus_indicators):
                structured_lines.append(f"[Chorus]\n{line}")
            elif any(indicator in line_lower for indicator in verse_indicators):
                structured_lines.append(f"[Verse]\n{line}")
            elif any(indicator in line_lower for indicator in bridge_indicators):
                structured_lines.append(f"[Bridge]\n{line}")
            elif 'intro' in line_lower and len(line_lower) < 20:
                structured_lines.append(f"[Intro]\n{line}")
            elif 'outro' in line_lower and len(line_lower) < 20:
                structured_lines.append(f"[Outro]\n{line}")
            else:
                structured_lines.append(line)
        
        return '\n'.join(structured_lines)

    def _normalize_speaker_id(self, name):
        if not name:
            return "unknown"
        slug = re.sub(r'[^a-zA-Z0-9]+', '_', name.strip().lower()).strip('_')
        return slug or "unknown"

    def _extract_speaker_from_text(self, text):
        """
        Returns (speaker_name, cleaned_text, confidence) if a speaker tag is found.
        Recognizes:
        - [Speaker] text
        - (Speaker) text
        - Speaker: text (heuristic, short labels)
        """
        t = (text or "").strip()
        if not t:
            return (None, "", None)

        m = re.match(r'^[\[\(]\s*(.+?)\s*[\]\)]\s*(.*)$', t)
        if m:
            return (m.group(1).strip(), m.group(2).strip(), 1.0)

        m = re.match(r'^([A-Za-z][A-Za-z0-9 _\-]{0,32})\s*:\s*(.*)$', t)
        if m:
            label = m.group(1).strip()
            if len(label.split()) <= 4:
                return (label, m.group(2).strip(), 0.9)

        return (None, t, None)

    def _build_screenplay_and_character_track(self, srt_segments_list, strict):
        report = []
        screenplay_data = []
        characters = {}
        timeline = []
        errors = 0

        if not srt_segments_list:
            report.append("ERROR: No SRT segments available to build SCREENPLAY.")
            return ({"data": []}, {"characters": {}, "timeline": []}, "\n".join(report), True)

        for idx, (_, __, text) in enumerate(srt_segments_list):
            speaker_name, clean_text, confidence = self._extract_speaker_from_text(text)

            scene_type = "instrumental" if not clean_text else "lyric"

            if scene_type != "instrumental" and not speaker_name:
                msg = f"ERROR: Missing speaker tag for index {idx}."
                if strict:
                    errors += 1
                report.append(msg if strict else msg.replace("ERROR", "WARNING"))

            speaker_id = self._normalize_speaker_id(speaker_name) if speaker_name else "unknown"

            if speaker_id not in characters:
                characters[speaker_id] = {"display_name": speaker_name or speaker_id}

            timeline.append({"index": idx, "speaker_id": speaker_id})

            entry = {
                "index": idx,
                "type": scene_type,
                "text": clean_text,
                "speaker_id": speaker_id,
            }
            if speaker_name:
                entry["speaker_name"] = speaker_name
            if confidence is not None:
                entry["confidence"] = confidence

            screenplay_data.append(entry)

        if errors:
            report.append(f"ERROR: Strict speaker detection failed ({errors} missing).")
            return ({"data": []}, {"characters": {}, "timeline": []}, "\n".join(report), True)

        if not report:
            report.append("SCREENPLAY + CHARACTER_TRACK validated.")

        return ({"data": screenplay_data}, {"characters": characters, "timeline": timeline}, "\n".join(report), False)

    async def execute(self, audio, whisper_model, language, vad_method, enable_ai_correction, correction_model, 
            enable_translation, debug_mode, segment_duration_seconds, enable_ai_text_refinement, strict_speaker_detection,
            ground_truth_script="", llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS):
        def _empty_outputs(msg):
            return ("", "", "", "", "", "", {"data": []}, {"characters": {}, "timeline": []}, msg)

        if whisper_model == "disabled":
            return _empty_outputs("Whisper model disabled by user.")

        try:
            whisperx = _get_whisperx(debug_mode)
        except ModuleNotFoundError as e:
            msg = (
                "WhisperX dependency missing. Install whisperx (plus its compatible deps) "
                "or run Screenwriter with whisper disabled and provide raw_lyrics_override. "
                f"Details: {e}"
            )
            if debug_mode:
                print(f"[SRTCreator] {msg}")
            return _empty_outputs(msg)
        except Exception as e:
            msg = f"WhisperX initialization error: {e}"
            if debug_mode:
                print(f"[SRTCreator] {msg}")
            return _empty_outputs(msg)

        if not isinstance(audio, dict) or "waveform" not in audio:
            raise ValueError("Invalid AUDIO input. Expected a dictionary with 'waveform' and 'sample_rate'.")

        # --- Prepare Audio ---
        waveform_tensor = audio["waveform"].float()
        original_sr = audio["sample_rate"]
        if waveform_tensor.ndim == 3:
            waveform_tensor = waveform_tensor.squeeze(0)
        audio_np = waveform_tensor.cpu().numpy()
        if audio_np.ndim == 2:
            audio_np = audio_np.mean(axis=0)
        
        audio_16k = librosa.resample(audio_np, orig_sr=original_sr, target_sr=16000)
        total_audio_duration = len(audio_16k) / 16000
        if debug_mode: print(f"[SRTCreator] Audio prepared and resampled to 16kHz.")

        loop = asyncio.get_running_loop()

        # --- 1. Load transcription model only (no alignment yet) ---
        if debug_mode: print(f"[SRTCreator] Loading transcription model ({whisper_model})...")
        transcription_model = await loop.run_in_executor(
            None, self._load_transcription_model, whisper_model, vad_method, debug_mode, language
        )
        await asyncio.sleep(0)  # yield to event loop

        # --- 2. FAST Transcription (no batching for speed) ---
        if debug_mode: print("[SRTCreator] Performing transcription...")
        try:
            _fix_speechbrain_dataloader_recursion(debug_mode)
            transcribe_language = None if language == "auto-detect" else language
            transcription_result = await loop.run_in_executor(
                None, lambda: transcription_model.transcribe(
                    audio_16k, batch_size=16, language=transcribe_language, task="transcribe"
                )
            )
        except Exception as e:
            if debug_mode:
                import traceback
                print("[SRTCreator] Transcription exception traceback:")
                print(traceback.format_exc())
            return _empty_outputs(f"Transcription error: {e}")

        await asyncio.sleep(0)  # yield to event loop

        if not transcription_result or not transcription_result.get("segments"):
            return _empty_outputs("No speech detected")

        # --- 3. Load alignment model using detected language (from transcription) ---
        detected_lang = transcription_result.get("language", language)
        if detected_lang == "auto-detect" or not detected_lang:
            detected_lang = "en"
        if debug_mode:
            print(f"[SRTCreator] Loading alignment model for language: {detected_lang}")
        _, align_model, align_meta = await loop.run_in_executor(
            None, self._load_models, whisper_model, detected_lang, vad_method, debug_mode
        )
        await asyncio.sleep(0)  # yield to event loop

        # --- 4. FAST Alignment ---
        if debug_mode: print("[SRTCreator] Aligning...")
        try:
            final_alignment = await loop.run_in_executor(
                None, lambda: whisperx.align(
                    transcription_result["segments"], 
                    align_model, 
                    align_meta, 
                    audio_16k, 
                    device="cuda" if torch.cuda.is_available() else "cpu", 
                    return_char_alignments=False
                )
            )
        except Exception as e:
            return _empty_outputs(f"Alignment error: {e}")

        word_segments = final_alignment.get("word_segments", [])
        if not word_segments:
            return _empty_outputs("No word timestamps generated")
        
        if enable_ai_correction and ground_truth_script and ground_truth_script.strip():
            if debug_mode: print("[SRTCreator] Step 2/4: Applying AI correction...")
            try:
                corrected = self._correct_with_ai(ground_truth_script, word_segments, debug_mode)
                if corrected:
                    word_segments = corrected
            except Exception as e:
                if debug_mode: print(f"[SRTCreator] AI correction failed: {e}")

        # --- 3. INTELLIGENT SRT Generation ---
        if debug_mode: print("[SRTCreator] Generating SRT...")
        
        # Get plain text first
        plain_text_output = " ".join([seg.get('text', '').strip() for seg in transcription_result["segments"] if seg.get('text')]).strip()
        
        # Generate SRT with intelligent segmentation
        # In the execute method, this line should be:
        srt_segments_list = self._generate_padded_srt(word_segments, segment_duration_seconds, total_audio_duration, debug_mode)
        
        if debug_mode:
            print(f"[DEBUG] Generated {len(srt_segments_list)} SRT segments")
            for i, (start, end, text) in enumerate(srt_segments_list[:10]):  # Show first 10 segments
                print(f"[DEBUG] Segment {i+1}: {start:.3f}-{end:.3f} '{text}'")
            
        if enable_ai_text_refinement and srt_segments_list:
            if debug_mode: print("[SRTCreator] Refining text formatting...")
            srt_segments_list = [
                (start, end, text[0].upper() + text[1:] if text and len(text) > 1 else text)
                for start, end, text in srt_segments_list
            ]
        srt_output = utils.to_srt(srt_segments_list) if srt_segments_list else ""
            
        if debug_mode:
            print(f"[DEBUG] Final SRT output length: {len(srt_output)}")
            if srt_output:
                print(f"[DEBUG] First 300 chars:\n{srt_output[:300]}")
        
        # Simple structured script (basic section detection)
        structured_script = self._simple_structure_detection(plain_text_output)
        
        timed_segments_json_string = json.dumps(srt_segments_list)

        # --- 4. OPTIONAL Translation (only if needed) ---
        translated_srt_output = ""
        translated_plain_text_output = ""
        if enable_translation:
            if debug_mode: print("[SRTCreator] Translating...")
            try:
                translation_result = await loop.run_in_executor(
                    None, lambda: transcription_model.transcribe(
                        audio_16k, batch_size=16, task="translate", language=language
                    )
                )
                
                if translation_result and translation_result.get("segments"):
                    translated_plain_text_output = " ".join([seg['text'].strip() for seg in translation_result["segments"]])
                    
                    # Quick alignment for translation
                    en_align_model, en_align_meta = await loop.run_in_executor(
                        None, lambda: whisperx.load_align_model(
                            language_code='en', device="cuda" if torch.cuda.is_available() else "cpu"
                        )
                    )
                    translated_alignment = await loop.run_in_executor(
                        None, lambda: whisperx.align(
                            translation_result["segments"],
                            en_align_model,
                            en_align_meta,
                            audio_16k,
                            device="cuda" if torch.cuda.is_available() else "cpu",
                            return_char_alignments=False
                        )
                    )
                    
                    translated_word_segments = translated_alignment.get("word_segments", [])
                    if translated_word_segments:
                        translated_srt_segments_list = self._generate_padded_srt(translated_word_segments, segment_duration_seconds, total_audio_duration, debug_mode)
                        translated_srt_output = utils.to_srt(translated_srt_segments_list)

            except Exception as e:
                translated_srt_output = f"Translation error: {e}"

        screenplay, character_track, validation_report, failed = self._build_screenplay_and_character_track(
            srt_segments_list, strict_speaker_detection
        )

        if failed:
            return (srt_output, plain_text_output, structured_script, timed_segments_json_string, translated_srt_output, translated_plain_text_output, screenplay, character_track, validation_report)

        return (srt_output, plain_text_output, structured_script, timed_segments_json_string, translated_srt_output, translated_plain_text_output, screenplay, character_track, validation_report)

    def _correct_with_ai(self, ground_truth_script, word_segments, debug_mode=False):
        """Apply AI correction to align word segments with the ground truth script."""
        from difflib import SequenceMatcher
        gt_words = ground_truth_script.split()
        if not gt_words or not word_segments:
            return None
        corrected = []
        gt_idx = 0
        for seg in word_segments:
            seg_text = seg.get("word", "").strip().lower()
            if not seg_text:
                corrected.append(seg)
                continue
            # Skip punctuation-only segments
            if not any(c.isalpha() for c in seg_text):
                corrected.append(seg)
                continue
            # If the segment matches the ground truth, keep it
            if gt_idx < len(gt_words) and seg_text == gt_words[gt_idx].strip(".,!?;:\"'()[]{}").lower():
                seg["word"] = gt_words[gt_idx]
                corrected.append(seg)
                gt_idx += 1
            else:
                # Try to find the closest match in remaining ground truth
                best_match = None
                for j in range(gt_idx, min(gt_idx + 5, len(gt_words))):
                    if seg_text == gt_words[j].strip(".,!?;:\"'()[]{}").lower():
                        best_match = j
                        break
                if best_match is not None:
                    seg["word"] = gt_words[best_match]
                    corrected.append(seg)
                    gt_idx = best_match + 1
                else:
                    # Could not match; skip or keep original
                    if debug_mode:
                        print(f"[SRTCreator] AI correction: Could not match '{seg_text}' in ground truth")
                    corrected.append(seg)
        if debug_mode:
            print(f"[SRTCreator] AI correction: Processed {len(word_segments)} segments, matched to ground truth")
        return corrected


# ------------------------------------------------------------------------------------
# Node Mappings
# ------------------------------------------------------------------------------------
NODE_CLASS_MAPPINGS = {
    "PromptCrafter_SRTCreator": PromptCrafter_SRTCreator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_SRTCreator": "???? Legacy ?? SRT Creator",
}
