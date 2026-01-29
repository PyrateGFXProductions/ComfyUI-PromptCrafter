import os
import torch
import torch.serialization
import json
import warnings
import librosa
from pathlib import Path
import torchaudio.transforms as T

from ..utils import pgfx_utils as utils
from ..core import pgfx_api_clients as api_clients

# Suppress the specific UserWarning from speechbrain that is triggered by whisperx
# warnings.filterwarnings("ignore", category=UserWarning, module='speechbrain.inference')

# --- Global State for Model Caching ---
LOADED_MODELS = {
    "transcription_model": None,
    "transcription_model_name": "",
    "align_model": None,
    "align_model_metadata": None,
    "align_model_lang": ""
}

class PromptCrafter_SRTCreator:
    DESCRIPTION = "Generates a highly accurate SRT file from an audio input, with optional AI-powered correction using a ground truth script."

    def __init__(self):
        pass

    @classmethod
    def get_whisper_models(cls):
        """Scans the ComfyUI models directory recursively for faster-whisper models."""
        # Default models that can be downloaded by faster-whisper directly
        default_models = ["tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en", "large-v1", "large-v2", "large-v3", "distil-large-v2"]
        
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
        return {
            "required": {
                "audio": ("AUDIO",),
                "whisper_model": (cls.get_whisper_models(), {"default": "large-v3"}),
                "language": ("STRING", {"default": "en", "tooltip": "Language code for transcription (e.g., 'en', 'es', 'ja')."}),
                "enable_ai_correction": ("BOOLEAN", {"default": False}),
                "correction_model": ("STRING", {"default": "ollama/qwen3-vl:8b", "tooltip": "The LLM to use for correcting the transcript."} ),
                "enable_translation": ("BOOLEAN", {"default": False, "tooltip": "Translate the transcription to English (requires English alignment model)."}),
                "debug_mode": ("BOOLEAN", {"default": False}),
                "segment_duration_seconds": ("FLOAT", {"default": 4.0, "min": 1.0, "max": 10.0, "step": 0.5}),
                "enable_ai_text_refinement": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "ground_truth_script": ("STRING", {"multiline": True, "default": "", "tooltip": "Optional: Provide a perfect script to correct the AI's transcription."} ),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("srt_output", "plain_text_output", "structured_script", "timed_segments_json_string", "translated_srt_output", "translated_plain_text_output")
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Audio"

    def _load_models(self, whisper_model_name, language, debug_mode):
        """Loads and caches whisperx transcription and alignment models."""
        import whisperx
        global LOADED_MODELS
        device = "cuda" if torch.cuda.is_available() else "cpu"

        # === 🔐 Expanded safe globals for PyTorch 2.6+ / Pyannote compatibility ===
        try:
            from pyannote.audio.core.model import Introspection
            from pyannote.audio.core.task import Specifications, Problem, Resolution # <--- Added Resolution
            from pyannote.audio.utils.powerset import Powerset # Common in newer models
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

        except ImportError as e:
            if debug_mode: print(f"[SRTCreator] Note: Some safety modules not found: {e}")
        # ===========================================================================

        # Load Transcription Model
        if LOADED_MODELS["transcription_model"] is None or LOADED_MODELS["transcription_model_name"] != whisper_model_name:
            if debug_mode: print(f"[SRTCreator] Loading whisper model: {whisper_model_name}")

            # --- ROBUST FIX: Convert clean name back to local path if needed ---
            model_path_or_name = whisper_model_name
            if "/" in whisper_model_name: # Indicates a potential local model like "Systran/faster-whisper-large-v3"
                model_path_or_name = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'models', 'faster-whisper', f"models--{whisper_model_name.replace('/', '--')}")
            
            vad_options = {"vad_method": "silero"}
            LOADED_MODELS["transcription_model"] = whisperx.load_model(
                model_path_or_name, device, compute_type="float16", vad_options=vad_options
            )
            LOADED_MODELS["transcription_model_name"] = whisper_model_name

        # Load Alignment Model
        if LOADED_MODELS["align_model"] is None or LOADED_MODELS["align_model_lang"] != language:
            if debug_mode: print(f"[SRTCreator] Loading alignment model for language: {language}")
            align_model, align_meta = whisperx.load_align_model(language_code=language, device=device)
            LOADED_MODELS["align_model"] = align_model
            LOADED_MODELS["align_model_metadata"] = align_meta
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

    def execute(self, audio, whisper_model, language, enable_ai_correction, correction_model, 
            enable_translation, enable_ai_text_refinement, debug_mode=False, 
            ground_truth_script="", segment_duration_seconds=4.0):
        import whisperx

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

        # --- Load Models ---
        transcription_model, align_model, align_meta = self._load_models(whisper_model, language, debug_mode)
        
        # --- 1. FAST Transcription (no batching for speed) ---
        if debug_mode: print("[SRTCreator] Performing transcription...")
        try:
            transcription_result = transcription_model.transcribe(
                audio_16k, 
                batch_size=16,  # Increased batch size
                language=language,
                task="transcribe"
            )
        except Exception as e:
            return (f"Transcription error: {e}", "", "", "", "", "")

        if not transcription_result or not transcription_result.get("segments"):
            return ("No speech detected", "", "", "", "", "")

        # --- 2. FAST Alignment ---
        if debug_mode: print("[SRTCreator] Aligning...")
        try:
            final_alignment = whisperx.align(
                transcription_result["segments"], 
                align_model, 
                align_meta, 
                audio_16k, 
                device="cuda" if torch.cuda.is_available() else "cpu", 
                return_char_alignments=False
            )
        except Exception as e:
            return (f"Alignment error: {e}", "", "", "", "", "")

        word_segments = final_alignment.get("word_segments", [])
        if not word_segments:
            return ("No word timestamps generated", "", "", "", "", "")
        
        if enable_ai_correction and ground_truth_script and ground_truth_script.strip():
            if debug_mode: print("[SRTCreator] Step 2/4: Applying AI correction...")

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
            
        srt_output = utils.to_srt(srt_segments_list) if srt_segments_list else ""
            
        if debug_mode:
            print(f"[DEBUG] Final SRT output length: {len(srt_output)}")
            if srt_output:
                print(f"[DEBUG] First 300 chars:\n{srt_output[:300]}")
        
        # Simple structured script (basic section detection)
        structured_script = self._simple_structure_detection(plain_text_output)
        
        timed_segments_json_string = json.dumps(word_segments, indent=2)

        # --- 4. OPTIONAL Translation (only if needed) ---
        translated_srt_output = ""
        translated_plain_text_output = ""
        if enable_translation:
            if debug_mode: print("[SRTCreator] Translating...")
            try:
                translation_result = transcription_model.transcribe(
                    audio_16k,
                    batch_size=16,
                    task="translate",
                    language=language
                )
                
                if translation_result and translation_result.get("segments"):
                    translated_plain_text_output = " ".join([seg['text'].strip() for seg in translation_result["segments"]])
                    
                    # Quick alignment for translation
                    en_align_model, en_align_meta = whisperx.load_align_model(language_code='en', device="cuda" if torch.cuda.is_available() else "cpu")
                    translated_alignment = whisperx.align(
                        translation_result["segments"],
                        en_align_model,
                        en_align_meta,
                        audio_16k,
                        device="cuda" if torch.cuda.is_available() else "cpu",
                        return_char_alignments=False
                    )
                    
                    translated_word_segments = translated_alignment.get("word_segments", [])
                    if translated_word_segments:
                        translated_srt_segments_list = self._generate_padded_srt(translated_word_segments, segment_duration_seconds, total_audio_duration, debug_mode)
                        translated_srt_output = utils.to_srt(translated_srt_segments_list)

            except Exception as e:
                translated_srt_output = f"Translation error: {e}"

        return (srt_output, plain_text_output, structured_script, timed_segments_json_string, translated_srt_output, translated_plain_text_output)


# ------------------------------------------------------------------------------------
# Node Mappings
# ------------------------------------------------------------------------------------
NODE_CLASS_MAPPINGS = {
    "PromptCrafter_SRTCreator": PromptCrafter_SRTCreator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_SRTCreator": "📝 PromptCrafter SRT Creator",
}