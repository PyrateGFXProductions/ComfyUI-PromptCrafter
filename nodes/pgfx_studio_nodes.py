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
    from ..utils import pgfx_utils as utils
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
except ImportError:
    print("[PromptCrafter Studio] Some dependencies are missing. Some features may be disabled.")
except Exception as e:
    print(f"[PromptCrafter Studio] Unexpected error during node initialization: {e}")

    


# --- NEW HELPER FOR MODEL SELECTION ---
def _get_sorted_models_by_preference(all_llm_models):
    """Optimized model sorting with better fallback logic"""
    if not all_llm_models:
        return []

    # Common GPU-friendly quants - higher preference
    quant_preference = ['q4_k_m', 'q5_k_m', 'q6_k', 'q4_0', 'q5_0', 'q4_1', 'q5_1', 'q3_k_m', 'q2_k']

    def get_model_rank(model_name_list):
        model_name = model_name_list[0].lower()

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
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"

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
                "segment_duration": ("FLOAT", {"default": 4.0, "min": 0.1}),
                "enable_vad": ("BOOLEAN", {"default": True}),
                "vad_threshold": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
                "enable_emotion_detection": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("AUDIO", "DICT", "INT")
    RETURN_NAMES = ("AUDIO", "TIMING_MAP", "SCENE_COUNT")
    FUNCTION = "process_audio"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"

    def process_audio(self, audio, PROJECT_CONFIG, profile, segment_duration=4.0, enable_vad=True, vad_threshold=0.5, enable_emotion_detection=True):
        # Extract fps from PROJECT_CONFIG
        fps = PROJECT_CONFIG.get("fps", 24)

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
    @classmethod
    def INPUT_TYPES(cls):
        try:
            whisper_models = PromptCrafter_SRTCreator.PromptCrafter_SRTCreator.get_whisper_models()
            profile_options = screenwriter_profiles.get_profile_options()
            all_llm_models = creator_nodes.get_combined_models()
            if not all_llm_models:
                all_llm_models = [["disabled"]]
            
            sorted_llm_models = _get_sorted_models_by_preference(all_llm_models)
            
            thinking_default = next((m[0] for m in sorted_llm_models if "Qwen3-VL-8b-Thinking" in m[0]), sorted_llm_models[0][0] if sorted_llm_models else "disabled")
            instruct_default = next((m[0] for m in sorted_llm_models if "Qwen3-VL-8b-Instruct" in m[0]), sorted_llm_models[0][0] if sorted_llm_models else "disabled")

        except Exception:
            whisper_models = [["disabled"]]
            profile_options = ["None (Manual Input)"]
            all_llm_models = [["disabled"]]
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
                "whisper_model": (whisper_models,),
                "raw_lyrics_override": ("STRING", {"multiline": True, "tooltip": "Optional: Provide a perfect script to force-align, overriding the internal transcription."}),
                "debug_mode": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("DICT", "DICT")
    RETURN_NAMES = ("SCREENPLAY", "AUDIO_META")
    FUNCTION = "write_script"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"

    def write_script(self, TIMING_MAP, audio, profile, thinking_model, instruct_model, whisper_model="large-v3", raw_lyrics_override="", debug_mode=False):
        # --- Profile Integration ---
        if profile != "None (Manual Input)":
            profile_settings = screenwriter_profiles.NAMED_SCREENWRITER_PROFILES.get(profile, {})
            whisper_model = profile_settings.get("whisper_model", whisper_model)

        if whisper_model == "disabled":
            # If both whisper is disabled and no override is provided, we can't proceed.
            if not (raw_lyrics_override and raw_lyrics_override.strip()):
                print("[Screenwriter] Error: Whisper is disabled and no raw_lyrics_override was provided. Cannot generate screenplay.")
                return ({"data": []}, {})
            print("[Screenwriter] Whisper model is disabled by profile. Relying solely on 'raw_lyrics_override'.")

        # 1. Run transcription and alignment once on the full audio clip.
        # This is far more accurate and efficient than transcribing each small chunk.
        srt_node = PromptCrafter_SRTCreator.PromptCrafter_SRTCreator()
        
        # Use AI correction if a ground truth script is provided.
        enable_ai_correction = bool(raw_lyrics_override and raw_lyrics_override.strip())

        if whisper_model != "disabled":
            srt_result = srt_node.execute(
                audio, 
                whisper_model, 
                "en",
                enable_ai_correction,
                instruct_model, # Use the 'instruct' model for correction, as intended by the SRT Creator
                raw_lyrics_override,
                debug_mode,
                False  # enable_translation
            )
            timed_segments_json = srt_result[3]
        else: # If whisper is disabled, we can't transcribe, so we can't get timed segments.
            timed_segments_json = "[]"
        
        try:
            word_segments = json.loads(timed_segments_json)
        except (getattr(json, 'JSONDecodeError', Exception), TypeError) as e:
            print("[Screenwriter] Error: Failed to parse Whisper JSON or result was None. Proceeding without lyrics.")
            word_segments = []
        
        screenplay_data = []
        timing_data = TIMING_MAP.get("data", [])

        # Add a check for None or empty timing_data
        if not timing_data:
            print("[Screenwriter] Warning: TIMING_MAP data is empty or invalid.")
            return ({"data": []}, {})

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
                    "type": "instrumental"
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
            
            entry = {
                "index": scene_idx,
                "text": text if text else "[INSTRUMENTAL]",
                "type": "lyric" if text else "instrumental"
            }
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
            
        return ({"data": screenplay_data}, audio_meta)

# --- NEW: THE CREATIVE DIRECTOR ---
class PGFX_Studio_CreativeDirector:
    """
    The project's lead visionary. This agent analyzes the screenplay to develop a
    global creative concept and a detailed visual brief for the Director.
    """
    @classmethod
    def INPUT_TYPES(cls):
        try:
            all_llm_models = creator_nodes.get_combined_models()
            if not all_llm_models: all_llm_models = [["disabled"]]

            sorted_llm_models = _get_sorted_models_by_preference(all_llm_models)

            thinking_default = next((m[0] for m in sorted_llm_models if "qwen" in m[0].lower() and ("thinking" in m[0].lower() or "32b" in m[0].lower() or "72b" in m[0].lower())), sorted_llm_models[0][0] if sorted_llm_models else "disabled")
            instruct_default = next((m[0] for m in sorted_llm_models if "qwen" in m[0].lower() and "instruct" in m[0].lower()), sorted_llm_models[0][0] if sorted_llm_models else "disabled")
        except Exception:
            all_llm_models = [["disabled"]]
            thinking_default = "disabled"
            instruct_default = "disabled"

        return {
            "required": {
                "SCREENPLAY": ("DICT",),
                "TIMING_MAP": ("DICT",),
                "thinking_model": (all_llm_models, {"default": thinking_default}),
                "instruct_model": (all_llm_models, {"default": instruct_default}),
                "character_override": ("STRING", {"multiline": True, "default": "", "tooltip": "Manually define the character. If empty, AI will describe from reference images."}),
                "gguf_gpu_layers": ("INT", {"default": -1, "min": -1, "max": 128, "step": 1, "tooltip": "Number of layers to offload to GPU for GGUF models. -1 for all, 0 for none."}),
                "debug_mode": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "reference_image": ("IMAGE",),
            }
        }

    RETURN_TYPES = ("DICT", "STRING")
    RETURN_NAMES = ("VISUAL_BRIEF", "creative_concept_log")
    FUNCTION = "develop_concept"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"

    # In nodes_studio.py, in the PGFX_Studio_CreativeDirector class, modify the develop_concept method:

    def _get_fallback_vrg_vars(self):
        """Provide comprehensive fallback values"""
        return {
            "character_description": "A mysterious figure",
            "song_theme_style": "dystopian industrial, dark fantasy, steampunk, gritty realism, corporate oppression, holiday subversion, worker rebellion, absurdist humor",
            "environment": "industrial workshop, santa's office, reindeer pen, break room, toy assembly line, north pole command center, elf dormitory, empty workshop",
            "lighting": "harsh fluorescent, dim candlelight, spotlight interrogation, cold blue tint, warm fire glow, dramatic shadows, overcast daylight, soft dawn",
            "camera_motion": "pan left, tilt down, zoom in, track forward, orbit left, pan right, tilt up, zoom out",
            "physical_interaction": "hammering toy, writing list, slumping exhausted, pointing angrily, dodging kick, singing off-key, whispering rebel, walking away",
            "facial_expression": "exhausted resignation, defiant smirk, angry shouting, fearful cowering, surprised pain, drunk confusion, quiet determination, relieved smile",
            "shots": "close up, medium shot, wide shot, extreme close up, over the shoulder, profile shot, two shot, extreme wide shot",
            "outfit_rules": "red hat, white beard, blue trousers, brown boots, red tunic, white shirt, black belt, green gloves",
            "character_visibility": "full body, face only, hands focus, profile view, back view, silhouette, close crop, wide angle"
        }

    def develop_concept(self, SCREENPLAY, TIMING_MAP, thinking_model, instruct_model,
                   character_override, debug_mode, gguf_gpu_layers=-1, reference_image=None):
        # Add input validation
        if not SCREENPLAY or not SCREENPLAY.get("data"):
            return ({}, "[ERROR] SCREENPLAY is empty or invalid.")

        screenplay_data = SCREENPLAY.get("data", [])

        # Part 1: Describe reference image
        image_context = "No reference images."
        images_to_pass = []
        if reference_image is not None:
            image_context = "A reference image is provided. Analyze it directly to inform your creative choices."
            images_to_pass = [reference_image]
            
        final_character_desc = character_override.strip() or ("A character based on the reference image." if reference_image is not None else "A mysterious figure.")
        lyrics_text = "`\n`".join([s['text'] for s in screenplay_data if s['type'] == 'lyric'])
        lyrics_summary = "`\n`".join(lyrics_text.splitlines()[:20])

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
            n_gpu_layers=gguf_gpu_layers
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
            - `camera_motion` must only use: zoom in, zoom out, pan left, pan right, tilt up, tilt down, track forward, track backward, orbit left, orbit right, rotate.
            - `shots` must only use: close up, extreme close up, medium shot, wide shot, extreme wide shot, over the shoulder, profile shot, two shot.
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
                    timeout=180  # Increased timeout
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
            "visual_styles_auto": [s.strip() for s in auto_vrg_vars.get("song_theme_style", "").split(',')],
            "environment_auto": [s.strip() for s in auto_vrg_vars.get("environment", "").split(',')],
            "lighting_auto": [s.strip() for s in auto_vrg_vars.get("lighting", "").split(',')],
        }

        log = f"`--- THEME REASONING ---\n`{theme_reasoning}`\n\n--- AUTO-STYLES REASONING ---\n`{vrg_reasoning}"

        return (visual_brief, log)


# --- THE DIRECTOR ---
class PGFX_Studio_Director:
    """
    The Director. Creates an edit plan and generates a shot list based on the
    Creative Director's visual brief and the Screenwriter's script.
    """

    @classmethod
    def INPUT_TYPES(cls):
        try:
            # Director profiles are now a fallback, not the primary input
            director_profiles._load_director_profiles()
            profile_options = director_profiles.get_director_profile_options()            

            all_llm_models = creator_nodes.get_combined_models()
            if not all_llm_models:
                all_llm_models = [["disabled"]]

            sorted_llm_models = _get_sorted_models_by_preference(all_llm_models)

            # Set default models, falling back to the first available if not found
            thinking_default = next((m[0] for m in sorted_llm_models if "Qwen3-VL-8b-Thinking" in m[0]), sorted_llm_models[0][0] if sorted_llm_models else "disabled")
            instruct_default = next((m[0] for m in sorted_llm_models if "Qwen3-VL-8b-Instruct" in m[0]), sorted_llm_models[0][0] if sorted_llm_models else "disabled")
        except Exception as e:
            print(f"[Director] Error loading models or profiles: {e}")
            profile_options = ["None (Manual Input)"]
            all_llm_models = [["disabled"]]
            thinking_default = "disabled"
            instruct_default = "disabled"
            
        return {
            "required": {
                "SCREENPLAY": ("DICT",),
                "thinking_model": (all_llm_models, {"default": thinking_default}),
                "instruct_model": (all_llm_models, {"default": instruct_default}),
                "use_prompt_template": ("BOOLEAN", {"default": False, "tooltip": "If True, uses a simple template for prompts instead of an LLM call per scene."}),
                "debug_mode": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "VISUAL_BRIEF": ("DICT",), # Now takes the brief from the Creative Director
                "director_profile_override": (profile_options, {"default": "None (Manual Input)"}),
                "manual_character_override": ("STRING", {"multiline": True, "default": ""}),
                "manual_styles_override": ("STRING", {"multiline": True, "default": ""}),            }
        }
    RETURN_TYPES = ("DICT", "STRING")
    RETURN_NAMES = ("SHOT_LIST", "reasoning_log")
    FUNCTION = "direct_scenes"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"

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

    def _get_edit_plan(self, screenplay_data, styles, thinking_model, instruct_model, debug_mode):
        """
        First LLM call (The Planner): Creates a high-level plan for which style to use for which scene.
        """
        climax_indices = self._detect_climax_scenes(screenplay_data)
        climax_info = ""
        if climax_indices:
            climax_info = f"\nPre-analysis suggests the emotional climax occurs around scenes: {', '.join(map(str, climax_indices))}. Pay special attention to these scenes when assigning styles and camera work."
        
        MAX_LLM_SCREENPLAY_LINES = 25
        if len(screenplay_data) > MAX_LLM_SCREENPLAY_LINES:
            first_scene_text = screenplay_data[0].get('text', '').strip()
            if all(s.get('type') == 'instrumental' and s.get('text', '').strip() == first_scene_text for s in screenplay_data):
                screenplay_for_prompt = f"  - Scene 0 to {len(screenplay_data) - 1} (instrumental): All scenes are identical instrumentals with the text \"{first_scene_text}\"."
                print(f"\033[93m[Director] Summarized {len(screenplay_data)} identical instrumental scenes to prevent LLM context overflow.\033[0m")
            else:
                print(f"\033[93m[Director] Screenplay has {len(screenplay_data)} scenes. Truncating to prevent LLM context overflow.\033[0m")
                screenplay_for_prompt = "\n".join([f"  - Scene {s['index']} ({s['type']}): \"{s['text']}\"" for s in screenplay_data[:20]])
                screenplay_for_prompt += f"\n  - ... and {len(screenplay_data) - 20} more scenes."
        else:
            screenplay_for_prompt = "\n".join([f"  - Scene {s['index']} ({s['type']}): \"{s['text']}\"" for s in screenplay_data])
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
            debug_mode=debug_mode
        )

        if not ok:
            reasoning = f"[ERROR] Edit plan chain failed. Details: {result_data}\n\n--- Last successful reasoning ---\n{reasoning}"
            result_data = {}

        # Add robust JSON parsing
        try:
            assignments = []
            if isinstance(result_data, dict) and "scene_assignments" in result_data:
                assignments = result_data["scene_assignments"]
            elif isinstance(result_data, list):
                assignments = result_data
            else:
                # Try to extract JSON from string if possible
                if isinstance(result_data, str):
                    import json
                    try:
                        parsed = json.loads(result_data)
                        if isinstance(parsed, dict) and "scene_assignments" in parsed:
                            assignments = parsed["scene_assignments"]
                        elif isinstance(parsed, list):
                            assignments = parsed
                        else:
                            raise ValueError("Unexpected JSON structure")
                    except json.JSONDecodeError:
                        # Try to extract JSON from markdown if present
                        if "```json" in result_data:
                            json_str = result_data.split("```json")[1].split("```")[0]
                            parsed = json.loads(json_str)
                            if isinstance(parsed, dict) and "scene_assignments" in parsed:
                                assignments = parsed["scene_assignments"]
                            elif isinstance(parsed, list):
                                assignments = parsed
                            else:
                                raise ValueError("Unexpected JSON structure")
                        else:
                            raise ValueError("No valid JSON found")
                else:
                    raise ValueError("Unexpected result type")

            # Validate assignments
            if not isinstance(assignments, list):
                raise ValueError("Assignments is not a list")

        except Exception as e:
            error_log = f"Failed to parse edit plan: {str(e)}. Reasoning: {reasoning}. Result: {result_data}"
            print(f"[Director] {error_log}")
            fallback_plan = [{"index": s["index"], "style": styles[0], "reasoning": "Fallback due to parsing error."}
                            for s in screenplay_data]
            return fallback_plan, error_log

        return assignments, reasoning


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
        # Limit length
        if len(prompt) > 300:
            prompt = prompt[:300] + "..."
        return prompt

    def _generate_shot_prompt(self, scene_data, assigned_style, character_description, thinking_model, instruct_model, debug_mode):
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
        if len(sanitized_lyric_text) > 200:
            sanitized_lyric_text = sanitized_lyric_text[:200] + "..."

        scene_type = scene_data["type"]
        is_climax = scene_data.get("is_climax", False)

        climax_instruction = "This is the song's climax; use dynamic, high-energy camera work like dolly zooms or fast tracking shots." if is_climax else ""

        if scene_type == "instrumental":
            # Generate mood-based visuals instead of literal interpretations
            task = f"Create a cinematic B-roll or transition shot that conveys the mood of '{assigned_style}'. Use abstract visuals, lighting effects, or symbolic imagery that matches the song's atmosphere. Avoid literal interpretations of lyrics."
            analysis_instruction = "Think about the emotional tone of the music. What colors, textures, and camera movements would best represent this mood?"
        else:
            visual_metaphor = self._enhance_visual_metaphors(sanitized_lyric_text, assigned_style, thinking_model, instruct_model, debug_mode)
            metaphor_guidance = ""
            if visual_metaphor:
                metaphor_guidance = f"Consider this visual metaphor: {visual_metaphor}."

            task = f"Brainstorm a cinematic scene visualizing this lyric: '{sanitized_lyric_text}'. The main character is '{character_description}'. The scene must be in the style of '{assigned_style}'. {climax_instruction} {metaphor_guidance}"
            analysis_instruction = "First, analyze the provided lyric for its emotional tone, key narrative elements, and any visual opportunities (like colors, textures, or actions). If a visual metaphor is provided, use it as your primary creative direction. Based on your analysis, think step-by-step about the lighting, camera angle, composition, and mood that would best represent the lyric."

        thinking_prompt = textwrap.dedent(f"""
            You are a detailed-oriented cinematographer.
            {analysis_instruction}
            **Task:** {task}
        """).strip()
        
        instruct_schema = {
            "positive_prompt": "string (The detailed visual description for an AI image generator)",
            "negative_prompt": "string (What to avoid, e.g., text, watermarks, ugly, blurry)"
        }
        instruct_prompt = textwrap.dedent(f"""
            Based on the cinematographer's reasoning, generate a JSON object following the schema.

            **Schema:** {json.dumps(instruct_schema, indent=2)}

            **CRITICAL INSTRUCTIONS:**
            - The final output MUST be a single, raw JSON object.
            - Do not wrap the JSON in markdown code fences.
            - Use standard double-quotes for all keys and string values.

            Return ONLY the JSON object.
        """).strip()

        ok, result_data, reasoning = utils.chain_of_thought_process(
            thinking_prompt=thinking_prompt,
            thinking_model=thinking_model,
            instruct_prompt=instruct_prompt,
            instruct_model=instruct_model,
            debug_mode=debug_mode
        )

        if not ok:
            reasoning = f"[ERROR] Shot prompt chain failed. Details: {result_data}\n\n--- Last successful reasoning ---\n{reasoning}"
            result_data = {}

        if debug_mode:
            print(f"[Director] Shot Gen Reasoning for Scene {scene_data['index']}:\n{reasoning}")

        # SANITIZE THE FINAL PROMPT OUTPUT FOR VIDEO MODEL COMPATIBILITY
        if isinstance(result_data, dict):
            pos_prompt = result_data.get("positive_prompt", f"{assigned_style}, {character_description}, {sanitized_lyric_text}")
            neg_prompt = result_data.get("negative_prompt", "text, watermark, ugly, blurry")
        else:
            print(f"\033[93m[Director] LLM shot generation failed for scene {scene_data['index']}. Using fallback.\033[0m")
            pos_prompt = f"{assigned_style}, {character_description}, cinematic shot visualizing '{sanitized_lyric_text}'"
            neg_prompt = "text, watermark, ugly, blurry"
        
        # Additional sanitization for video model compatibility
        pos_prompt = self._sanitize_prompt_for_video_model(pos_prompt)
        neg_prompt = self._sanitize_prompt_for_video_model(neg_prompt)
        
        return pos_prompt, neg_prompt

    def _enhance_visual_metaphors(self, lyric_text, assigned_style, thinking_model, instruct_model, debug_mode):
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
            debug_mode=debug_mode
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

    def direct_scenes(self, SCREENPLAY, thinking_model, instruct_model, use_prompt_template, debug_mode, VISUAL_BRIEF=None, director_profile_override="None (Manual Input)", manual_character_override="", manual_styles_override=""):
        # --- FIX: ROBUST CACHING ---
        # Create a unique hash of the inputs that matter
        input_str = f"{str(SCREENPLAY)}{str(VISUAL_BRIEF)}{director_profile_override}{manual_styles_override}{manual_character_override}{use_prompt_template}"
        input_hash = hashlib.md5(input_str.encode('utf-8')).hexdigest()
        
        # Check if we already have a plan for this exact input
        if hasattr(self, '_cached_plan') and self._cached_plan.get('hash') == input_hash:
            print("[Director] Using cached Shot List (Skipping LLM/Template generation).")
            return ({"data": self._cached_plan['data']}, self._cached_plan['log'])

        shot_list = []
        full_reasoning_log = ""
        VISUAL_BRIEF = VISUAL_BRIEF or {}
        
        screenplay_data = SCREENPLAY.get("data", [])
        if not screenplay_data:
            return ({"data": []}, "[ERROR] SCREENPLAY is empty or invalid.")
        
        # --- NEW: Evolved Logic for Sourcing Creative Direction ---
        # Priority: 1. Manual Overrides -> 2. VISUAL_BRIEF -> 3. Profile Override
        final_char_desc = manual_character_override.strip() or VISUAL_BRIEF.get("character_description", "A mysterious figure.")
        
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

        final_visual_styles = "\n".join(final_visual_styles_list)

        # Use the final determined styles
        styles = [s.split(':')[0].strip() for s in final_visual_styles.splitlines() if s.strip()]
        if not styles:
            return ({"data": []}, "[ERROR] No visual styles provided.")

        # Stage 1: Get the high-level edit plan. This is still needed to assign styles.
        edit_plan, plan_reasoning = self._get_edit_plan(screenplay_data, styles, thinking_model, instruct_model, debug_mode)
        full_reasoning_log += "--- EDIT PLAN REASONING ---\n" + plan_reasoning + "\n\n"

        # Validate the style assignments
        edit_plan = self._validate_style_assignments(edit_plan, styles)

        # Create a dictionary for quick lookup
        screenplay_dict = {s["index"]: s for s in screenplay_data}

        # --- ENHANCEMENT: Mark climax scenes based on plan ---
        climax_indices = {item['index'] for item in edit_plan if 'climax' in item.get('reasoning', '').lower()}
        if climax_indices:
            print(f"[Director] Identified climax scenes at indices: {climax_indices}")
            for index in climax_indices:
                if index in screenplay_dict:
                    screenplay_dict[index]['is_climax'] = True

        # Stage 2: Generate a detailed shot for each item in the plan
        for assignment in edit_plan:
            index = assignment.get("index")
            assigned_style = assignment.get("style")
            
            if index is None or assigned_style is None or index not in screenplay_dict:
                print(f"[Director] Warning: Skipping invalid assignment in edit plan: {assignment}")
                continue

            scene_data = screenplay_dict[index]

            if use_prompt_template:
                if index == 0: # Print only on the first iteration
                    print("[Director] Using prompt template instead of LLM for shot generation.")
                lyric_text = scene_data["text"]
                scene_type = scene_data["type"]
                if scene_type == "instrumental":
                    pos_prompt = f"{assigned_style}, {final_char_desc}, cinematic b-roll, transition shot"
                else:
                    # Escape single quotes in lyric_text to avoid breaking the prompt string
                    safe_lyric = lyric_text.replace("'", "\\'")
                    pos_prompt = f"{assigned_style}, {final_char_desc}, cinematic shot visualizing '{safe_lyric}'"
                neg_prompt = "text, watermark, ugly, blurry"
            else:
                # Generate the core prompt for this shot using an LLM.
                pos_prompt, neg_prompt = self._generate_shot_prompt(scene_data, assigned_style, final_char_desc, thinking_model, instruct_model, debug_mode)

            shot_list.append({
                "index": index,
                "positive": pos_prompt,
                "negative": neg_prompt,
                "seed": index * 9999 + 101,
                "style": assigned_style
            })
            
        # At the very end of the function, save to cache before returning:
        self._cached_plan = {'hash': input_hash, 'data': shot_list, 'log': full_reasoning_log}
        return ({"data": shot_list}, full_reasoning_log)

# --- THE CINEMATOGRAPHER ---
class PGFX_Studio_Cinematographer:
    """
    Acts as the bridge between the data (SHOT_LIST, TIMING_MAP) and the generation loop.
    It fetches the correct prompt, audio, and data for the current scene index.
    Includes an auto-incrementing counter that resets per project, mimicking a trigger counter.
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

        # Limit length to prevent token overflow
        if len(prompt) > 250:
            prompt = prompt[:250] + "..."

        return prompt

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
            }
        }
    RETURN_TYPES = ("STRING", "STRING", "INT", "AUDIO", "INT", "INT", "INT")
    RETURN_NAMES = ("positive", "negative", "seed", "audio_chunk", "num_frames", "scene_index", "remaining_scenes")
    FUNCTION = "get_shot"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"

    def _interrupt_execution(self):
        """Stops the execution of the ComfyUI queue."""
        try:
            server.PromptServer.instance.send_json("execution_interrupted", {"prompt_id": "PGFX_STUDIO_LOOP_TERMINATED"})
            print("\033[92m[Cinematographer] All scenes rendered. Workflow execution stopped.\033[0m")
        except Exception as e:
            print(f"[Cinematographer] Warning: Could not send execution interruption signal. {e}")

    def get_shot(self, SHOT_LIST, TIMING_MAP, PROJECT_CONFIG, mode, scene_index, reset_counter=False):
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
        num_scenes = len(shot_list_data)
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
            print("[Cinematographer] Warning: SHOT_LIST is empty. Returning empty data.")
            return ("", "", 0, empty_audio, 0, current_index, remaining_scenes)
        
        # In Fixed mode, the user might provide an out-of-bounds index.
        if current_index >= num_scenes:
            print(f"[Cinematographer] Error: scene_index {current_index} is out of bounds (total scenes: {num_scenes}).")
            return ("", "", 0, empty_audio, 0, current_index, remaining_scenes)

        effective_index = current_index
        
        shot = next((s for s in shot_list_data if s.get("index") == effective_index), None)
        timing_map_data = TIMING_MAP.get("data", [])
        timing = next((t for t in timing_map_data if t.get("index") == effective_index), None)

        if shot is None or timing is None:
            print(f"[Cinematographer] Error: No shot or timing data found for index {effective_index}. Check SHOT_LIST/TIMING_MAP alignment.")
            return ("", "", 0, empty_audio, 0, effective_index, remaining_scenes)

        num_frames = timing.get("num_frames", 0)
        audio_chunk = timing.get("audio_dict", empty_audio)

        # Sanitize prompts before returning them
        positive_prompt = shot.get("positive", "")
        negative_prompt = shot.get("negative", "")
        
        # Apply sanitization to prevent CUDA errors
        positive_prompt = self._sanitize_prompt_for_video_model(positive_prompt)
        negative_prompt = self._sanitize_prompt_for_video_model(negative_prompt)

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
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"
    OUTPUT_NODE = True

    def save_scene_clip(self, PROJECT_CONFIG, video_frames, scene_index, audio_chunk=None):
        import imageio
        import numpy as np
        
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

        # 3. Save Video (Simple ImageIO)
        # We save silent video here because the PostMaster adds the Master Audio later
        images_np = (video_frames.cpu().numpy() * 255).astype(np.uint8)
        try:
            imageio.mimwrite(full_path, images_np, fps=fps, codec='libx264', quality=8, macro_block_size=1)
        except Exception as e:
            print(f"[Editor] Error saving clip: {e}")
            return ("",)

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
            from . import style_profiles
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
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"

    def apply_style(self, base_style, character_consistency_tags, global_lighting_mood, additional_lora_triggers="", style_strength=1.0):
        from . import style_profiles
        
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
                all_llm_models = [["disabled"]]

            sorted_llm_models = _get_sorted_models_by_preference(all_llm_models)

            # Generalize default model selection to avoid specific unsupported models
            thinking_default = next((m[0] for m in sorted_llm_models if "qwen" in m[0].lower() and "thinking" in m[0].lower()), sorted_llm_models[0][0] if sorted_llm_models else "disabled")
            instruct_default = next((m[0] for m in sorted_llm_models if "qwen" in m[0].lower() and "instruct" in m[0].lower()), sorted_llm_models[0][0] if sorted_llm_models else "disabled")
        except Exception as e:
            print(f"[Script Supervisor] Error loading models: {e}")
            all_llm_models = [["disabled"]]
            thinking_default = "disabled"
            instruct_default = "disabled"

        return {
            "required": {
                "SHOT_LIST": ("DICT",),
                "SCREENPLAY": ("DICT",),
                "thinking_model": (all_llm_models, {"default": thinking_default}),
                "instruct_model": (all_llm_models, {"default": instruct_default}),
                "debug_mode": ("BOOLEAN", {"default": False}),
            }
        }
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("continuity_report",)
    FUNCTION = "review"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"

    def review(self, SHOT_LIST, SCREENPLAY, thinking_model, instruct_model, debug_mode=False):
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
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"

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
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"

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
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"
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
    "PGFX_Studio_Stylist": PGFX_Studio_Stylist,
    "PGFX_Studio_Animator": PGFX_Studio_Animator,
    "PGFX_Studio_ScriptSupervisor": PGFX_Studio_ScriptSupervisor,
    "PGFX_Studio_Stylist": PGFX_Studio_Stylist,
    "PGFX_Studio_Animator": PGFX_Studio_Animator,
    "PGFX_Studio_ScriptSupervisor": PGFX_Studio_ScriptSupervisor,
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
    "PGFX_Studio_Stylist": "🎨 Studio Stylist (Looks)",
    "PGFX_Studio_Animator": "👄 Studio Animator (Visemes)",
    "PGFX_Studio_ScriptSupervisor": "📋 Studio Script Supervisor (Review)",
    "PGFX_Studio_Sampler": "🎤 Studio Sampler (Universal)",
    "PGFX_Studio_ControlNet": "👄 Studio ControlNet (Viseme Bridge)",
}