import os
import sys, gc
import warnings
import traceback
import whisperx
from whisperx.asr import FasterWhisperPipeline, WhisperModel 
import librosa
import textwrap
from g2p_en import G2p
from PIL import Image, ImageDraw
import numpy as np
from pathlib import Path
import torch
import json
import torchaudio
import folder_paths 
# from speechbrain.inference.interfaces import foreign_class

try:
    from speechbrain.inference import EncoderClassifier
    from speechbrain.inference.interfaces import foreign_class
except Exception as e:
    print("="*80)
    print("--- [PGFX Visemes] IMPORT WARNING (EXTENDED_DEBUG) ---")
    print("Could not import 'speechbrain'. This is required for audio-based emotion detection.")
    print(f"THE DETAILED ERROR WAS: {type(e).__name__}: {e}")
    print("\n--- FULL TRACEBACK ---")
    traceback.print_exc()
    print("--- END TRACEBACK ---\n")
    print("The node will fall back to keyword-based emotion detection.")
    print("The error above might indicate a conflict with another library.")
    print("="*80)
    EncoderClassifier = None
    foreign_class = None

from . import pgfx_utils as utils
import re

class AnyType(str):
    def __ne__(self, __value: object) -> bool:
        return False

any_typ = AnyType("*")

def _strip_srt_from_text(text: str) -> str:
    pattern = re.compile(
        r'(\d+)\s*[\r\n]+'
        r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*[\r\n]+'
        r'([\s\S]*?)(?=\n\n|\Z)',
        re.MULTILINE
    )
    text_parts = [match[3].strip().replace('\n', ' ') for match in pattern.finditer(text)]
    if text_parts:
        return " ".join(text_parts)
    return " ".join(text.splitlines())

# warnings.filterwarnings("ignore", category=UserWarning, module='speechbrain.inference')

# --- Global State ---
LOADED_MODELS = {
    "emotion_profiles": {},
    "emotion_file_timestamp": 0,
    "emotion_classifier": None,
    "g2p_instance": None # Moved from global to instance
}

# --- Emotion Detection ---

def load_emotion_classifier(custom_base_path=None):
    """Loads the emotion classifier model into the global state."""
    global LOADED_MODELS
    if LOADED_MODELS["emotion_classifier"] is None and EncoderClassifier is not None:
        try:
            print("[PGFX Visemes] Loading audio emotion classifier model...")
            
            # Define the model source and a user-friendly local directory name, consistent with other nodes.
            source_hf_id = "speechbrain/emotion-recognition-wav2vec2-IEMOCAP"
            local_model_name = "emotion-recognition-wav2vec2-IEMOCAP"

            # This logic is now unified with the PGFX_Studio_SoundEngineer node to ensure a single, correct model location.
            if custom_base_path and os.path.isdir(custom_base_path):
                 # A custom path is respected but is now directed to a consistent subfolder.
                 wav2vec2_base_path = os.path.join(custom_base_path, "models", "wav2vec2")
                 print(f"[PGFX Visemes] Using custom base path for wav2vec2 models: {wav2vec2_base_path}")
            else:
                # Use the canonical ComfyUI models path to ensure consistency.
                wav2vec2_base_path = os.path.join(folder_paths.base_path, "models", "wav2vec2")

            local_model_dir = os.path.join(wav2vec2_base_path, local_model_name)
            os.makedirs(local_model_dir, exist_ok=True)

            print(f"[PGFX Visemes] Attempting to load/download model: {source_hf_id} to {local_model_dir}")
            
            LOADED_MODELS["emotion_classifier"] = foreign_class(
                source=source_hf_id,
                pymodule_file="custom_interface.py",
                classname="CustomEncoderClassifier",
                savedir=local_model_dir, # SpeechBrain will cache here
            )
            print("[PGFX Visemes] Audio emotion classifier loaded successfully.")
        except Exception as e:
            print(f"[PGFX Visemes] ERROR: Could not load the audio emotion classifier. Keyword-based emotion will be used as a fallback. Error details: {e}")
            LOADED_MODELS["emotion_classifier"] = None # Ensure it's reset on failure

def cleanup_emotion_model():
    """Removes the emotion classifier model from memory."""
    global LOADED_MODELS
    if LOADED_MODELS.get("emotion_classifier") is not None:
        print("[PGFX Visemes] Unloading audio emotion classifier model.")
        del LOADED_MODELS["emotion_classifier"]
        LOADED_MODELS["emotion_classifier"] = None
        gc.collect()
        torch.cuda.empty_cache()

def detect_emotion_from_audio(audio_chunk, sample_rate, classifier):
    """Detects emotion from an audio chunk using the provided classifier."""
    if classifier is None or audio_chunk is None or audio_chunk.nelement() == 0:
        return "NEUTRAL"
    try:
        # The model expects a 1D tensor and a sample rate
        out_prob, score, index, text_lab = classifier.classify_batch(audio_chunk)
        return text_lab[0].upper()
    except Exception as e:
        print(f"[PGFX Visemes] Warning: Audio emotion detection failed. Details: {e}")
        return "NEUTRAL"

def detect_emotion_from_word(word):
    emotion_profiles = LOADED_MODELS.get("emotion_profiles", {})
    word_lower = word.lower()
    for emotion, profile in emotion_profiles.items():
        if any(keyword in word_lower for keyword in profile.get("keywords", [])):
            return emotion
    return "NEUTRAL"

# --- Helper Functions ---
def pil_to_tensor(images_pil):
    if not isinstance(images_pil, list):
        images_pil = [images_pil]
    images_np = [np.array(img).astype(np.float32) / 255.0 for img in images_pil]
    images_tensor = [torch.from_numpy(img) for img in images_np]
    if images_tensor:
        return torch.stack(images_tensor)
    else:
        return torch.empty(0, 512, 512, 3, dtype=torch.float32)

def tensor_to_pil(tensor):
    if tensor is None or tensor.nelement() == 0:
        return []
    images_np = (tensor.cpu().numpy() * 255).astype(np.uint8)
    return [Image.fromarray(img) for img in images_np]

def draw_landmarks_helper(draw, landmarks_norm, width, height, draw_style, dot_color, line_color, fill_color, dot_size, line_thickness, emotion, emotion_intensity):
    outer_lip_indices = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0]
    inner_lip_indices = [12, 13, 14, 15, 16, 17, 18, 19, 12]
    points = [(nx * width, ny * height) for nx, ny in landmarks_norm]

    if emotion != "NEUTRAL" and emotion_intensity > 0:
        modifier = LOADED_MODELS.get("emotion_profiles", {}).get(emotion, {}).get("modifier", (0, 0))
        points = apply_emotion_modifier(points, modifier, emotion_intensity, width, height)

    outer_lip_points = [points[i] for i in outer_lip_indices]
    inner_lip_points = [points[i] for i in inner_lip_indices]

    if draw_style in ["Outline", "Filled Outline"]:
        draw.line(outer_lip_points, fill=line_color, width=line_thickness, joint="curve")
        draw.line(inner_lip_points, fill=line_color, width=line_thickness, joint="curve")
    if draw_style == "Filled Outline":
        draw.polygon(inner_lip_points, fill=fill_color)
    if draw_style == "Dots":
        for x, y in points:
            draw.ellipse((x - dot_size // 2, y - dot_size // 2, x + dot_size // 2, y + dot_size // 2), fill=dot_color)

def apply_emotion_modifier(points, modifier, intensity, width, height):
    ndx, ndy = modifier
    dx = ndx * intensity * width
    dy = ndy * intensity * height
    left_corner_idx, right_corner_idx = 0, 6
    new_points = list(points)
    for i in range(len(points)):
        if i == left_corner_idx or i == right_corner_idx:
            new_points[i] = (points[i][0] + dx, points[i][1] + dy)
        elif i in [1, 5, 7, 11]:
            new_points[i] = (points[i][0] + dx * 0.5, points[i][1] + dy * 0.5)
    return new_points

def calculate_dynamic_intensity(frame_time, word_start, word_end):
    if word_start is None or word_end is None or word_end <= word_start:
        return 1.0
    word_duration = word_end - word_start
    progress = max(0.0, min(1.0, (frame_time - word_start) / word_duration))
    dynamic_multiplier = (1.0 - 0.2) * np.sin(progress * np.pi) + 0.2
    return min(dynamic_multiplier, 1.0)

COARTICULATION_PROFILES = { "Speech": (0.15, 0.70, 0.15), "Singing": (0.10, 0.80, 0.10) }
def blend_landmarks(prev_lm, curr_lm, next_lm, weights):
    if weights is None: weights = COARTICULATION_PROFILES["Speech"]
    w_prev, w_curr, w_next = weights
    blended = []
    for i in range(len(curr_lm)):
        prev_pt = prev_lm[i] if i < len(prev_lm) else curr_lm[i]
        next_pt = next_lm[i] if i < len(next_lm) else curr_lm[i]
        x = (prev_pt[0] * w_prev) + (curr_lm[i][0] * w_curr) + (next_pt[0] * w_next)
        y = (prev_pt[1] * w_prev) + (curr_lm[i][1] * w_curr) + (next_pt[1] * w_next)
        blended.append((x, y))
    return blended

def get_default_emotion_profiles():
    return {
        "HAPPY": {"keywords": ["happy", "joy", "smile", "laugh", "bright", "love", "vibrant", "glee"], "modifier": [0.0, -0.015]},
        "SAD": {"keywords": ["sad", "cry", "tear", "grief", "sorrow", "lonely", "down", "blue"], "modifier": [0.0, 0.015]},
        "ANGRY": {"keywords": ["angry", "rage", "fury", "shout", "hate", "fight", "protest"], "modifier": [0.0, 0.005]},
        "SURPRISED": {"keywords": ["wow", "oh", "omg", "surprise", "shocked", "gasp"], "modifier": [0.0, 0.0]}
    }

def load_emotion_profiles():
    global LOADED_MODELS
    module_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(module_dir, "emotions.json")
    try:
        if os.path.exists(json_path):
            current_timestamp = os.path.getmtime(json_path)
            if current_timestamp == LOADED_MODELS.get("emotion_file_timestamp"): return
            print("[PGFX Visemes] Detected change in emotions.json. Reloading profiles.")
            with open(json_path, 'r') as f: data = json.load(f)
            profiles = {p['name'].upper(): {"keywords": p.get('keywords', []), "modifier": p.get('modifier', [0.0, 0.0])} for p in data.get('emotions', [])}
            LOADED_MODELS["emotion_profiles"] = profiles
            LOADED_MODELS["emotion_file_timestamp"] = current_timestamp
        else:
             LOADED_MODELS["emotion_profiles"] = get_default_emotion_profiles()
    except Exception:
        LOADED_MODELS["emotion_profiles"] = get_default_emotion_profiles()

CX, CY = 0.5, 0.7
VISEME_TO_LANDMARK_MAP = {
    "SIL": [(CX-0.15, CY-0.02), (CX-0.12, CY-0.01), (CX-0.06, CY+0.00), (CX+0.00, CY+0.00), (CX+0.06, CY+0.00), (CX+0.12, CY-0.01), (CX+0.15, CY-0.02), (CX+0.12, CY-0.01), (CX+0.06, CY+0.00), (CX+0.00, CY+0.00), (CX-0.06, CY+0.00), (CX-0.12, CY-0.01), (CX-0.12, CY-0.01), (CX-0.06, CY+0.00), (CX+0.00, CY+0.00), (CX+0.06, CY+0.00), (CX+0.12, CY-0.01), (CX+0.06, CY+0.00), (CX+0.00, CY+0.00), (CX-0.06, CY+0.00)],
    "AA": [(CX-0.16, CY-0.02), (CX-0.12, CY-0.04), (CX-0.06, CY-0.05), (CX+0.00, CY-0.05), (CX+0.06, CY-0.05), (CX+0.12, CY-0.04), (CX+0.16, CY-0.02), (CX+0.12, CY+0.08), (CX+0.06, CY+0.10), (CX+0.00, CY+0.10), (CX-0.06, CY+0.10), (CX-0.12, CY+0.08), (CX-0.12, CY-0.02), (CX-0.06, CY-0.03), (CX+0.00, CY-0.03), (CX+0.06, CY-0.03), (CX+0.12, CY-0.02), (CX+0.06, CY+0.07), (CX+0.00, CY+0.07), (CX-0.06, CY+0.07)],
    "EE": [(CX-0.20, CY-0.01), (CX-0.15, CY-0.02), (CX-0.07, CY-0.02), (CX+0.00, CY-0.02), (CX+0.07, CY-0.02), (CX+0.15, CY-0.02), (CX+0.20, CY-0.01), (CX+0.15, CY+0.02), (CX+0.07, CY+0.02), (CX+0.00, CY+0.02), (CX-0.07, CY+0.02), (CX-0.15, CY+0.02), (CX-0.15, CY-0.01), (CX-0.07, CY-0.01), (CX+0.00, CY-0.01), (CX+0.07, CY-0.01), (CX+0.15, CY-0.01), (CX+0.07, CY+0.01), (CX+0.00, CY+0.01), (CX-0.07, CY+0.01)],
    "OO": [(CX-0.08, CY-0.02), (CX-0.06, CY-0.04), (CX-0.03, CY-0.05), (CX+0.00, CY-0.05), (CX+0.03, CY-0.05), (CX+0.06, CY-0.04), (CX+0.08, CY-0.02), (CX+0.06, CY-0.04), (CX+0.03, CY+0.05), (CX+0.00, CY+0.05), (CX-0.03, CY+0.05), (CX-0.06, CY+0.04), (CX-0.05, CY-0.02), (CX-0.03, CY-0.03), (CX+0.00, CY-0.03), (CX+0.03, CY-0.03), (CX+0.05, CY-0.02), (CX+0.03, CY+0.03), (CX+0.00, CY+0.03), (CX-0.03, CY+0.03)],
    "S_L": [(CX-0.18, CY-0.01), (CX-0.14, CY-0.02), (CX-0.07, CY-0.02), (CX+0.00, CY-0.02), (CX+0.07, CY-0.02), (CX+0.14, CY-0.02), (CX+0.18, CY-0.01), (CX+0.14, CY+0.02), (CX+0.07, CY+0.02), (CX+0.00, CY+0.02), (CX-0.07, CY+0.02), (CX-0.14, CY+0.02), (CX-0.14, CY-0.01), (CX-0.07, CY-0.01), (CX+0.00, CY-0.01), (CX+0.07, CY-0.01), (CX+0.14, CY-0.01), (CX+0.07, CY+0.01), (CX+0.00, CY+0.01), (CX-0.07, CY+0.01)],
    "DENTAL": [(CX-0.17, CY-0.02), (CX-0.13, CY-0.03), (CX-0.07, CY-0.03), (CX+0.00, CY-0.03), (CX+0.07, CY-0.03), (CX+0.13, CY-0.03), (CX+0.17, CY-0.02), (CX+0.13, CY+0.03), (CX+0.07, CY+0.03), (CX+0.00, CY+0.03), (CX-0.07, CY+0.03), (CX-0.13, CY+0.03), (CX-0.13, CY-0.01), (CX-0.07, CY-0.01), (CX+0.00, CY-0.01), (CX+0.07, CY-0.01), (CX+0.13, CY-0.01), (CX+0.07, CY+0.01), (CX+0.00, CY+0.01), (CX-0.07, CY+0.01)],
    "LABIODENTAL": [(CX-0.17, CY-0.02), (CX-0.13, CY-0.03), (CX-0.07, CY-0.03), (CX+0.00, CY-0.03), (CX+0.07, CY-0.03), (CX+0.13, CY-0.03), (CX+0.17, CY-0.02), (CX+0.13, CY+0.02), (CX+0.07, CY+0.01), (CX+0.00, CY+0.01), (CX-0.07, CY+0.01), (CX-0.13, CY+0.02), (CX-0.13, CY-0.01), (CX-0.07, CY-0.01), (CX+0.00, CY-0.01), (CX+0.07, CY-0.01), (CX+0.13, CY-0.01), (CX+0.07, CY-0.00), (CX+0.00, CY-0.00), (CX-0.07, CY-0.00)],
}
PHONEME_TO_VISEME_MAP = {'SIL': 'SIL', 'F': 'LABIODENTAL', 'V': 'LABIODENTAL', 'TH': 'DENTAL', 'DH': 'DENTAL', 'P': 'SIL', 'B': 'SIL', 'M': 'SIL', 'AA': 'AA', 'AE': 'AA', 'AH': 'AA', 'AO': 'AA', 'AW': 'AA', 'AY': 'AA', 'IY': 'EE', 'IH': 'EE', 'EH': 'EE', 'EY': 'EE', 'OW': 'OO', 'OY': 'OO', 'UW': 'OO', 'UH': 'OO', 'L': 'S_L', 'S': 'S_L', 'Z': 'S_L', 'R': 'OO', 'W': 'OO', 'Y': 'EE', 'CH': 'S_L', 'JH': 'S_L', 'SH': 'S_L', 'ZH': 'S_L', 'G': 'AA', 'K': 'AA', 'NG': 'AA', 'N': 'S_L', 'HH': 'AA'}

class PGFX_ScriptGuidedVisemes:
    def __init__(self):
        self.g2p_instance = None

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {"audio_meta": ("DICT", {}), "fps": ("INT", {"default": 25, "min": 1, "max": 60}), "coarticulation_profile": (list(COARTICULATION_PROFILES.keys()), {"default": "Singing"}), "debug": ("BOOLEAN", {"default": False}), "image_width": ("INT", {"default": 512, "min": 64, "max": 2048, "step": 64}), "image_height": ("INT", {"default": 512, "min": 64, "max": 2048, "step": 64}), "max_frames": ("INT", {"default": 0, "min": 0, "max": 99999, "step": 1}), "scene_index": ("INT", {"default": 0, "min": 0, "max": 100}), "draw_style": (["Dots", "Outline", "Filled Outline"], {"default": "Filled Outline"}), "dot_color": ("STRING", {"default": "white"}), "line_color": ("STRING", {"default": "white"}), "fill_color": ("STRING", {"default": "black"}), "dot_size": ("INT", {"default": 3, "min": 1, "max": 20}), "line_thickness": ("INT", {"default": 2, "min": 1, "max": 20}), "emotion_intensity": ("STRING", {"default": "1.0", "multiline": False}),}, "optional": {"face_template": ("IMAGE", {}), "speechbrain_model_base_path": ("STRING", {"default": "", "multiline": False}),}}

    CATEGORY = "☠️PGFX /PromptCrafter/Utils"
    RETURN_TYPES = ("IMAGE", "STRING", "BOOLEAN", "STRING",)
    RETURN_NAMES = ("control_images", "phoneme_debug_text", "is_silent", "instrumental_cue",)
    FUNCTION = "execute"

    def execute(self, audio_meta, fps, coarticulation_profile, debug, image_width, image_height, max_frames, scene_index, draw_style, dot_color, line_color, fill_color, dot_size, line_thickness, emotion_intensity, face_template=None, speechbrain_model_base_path="", **kwargs):
        try:
            emotion_intensity = float(emotion_intensity)
        except (ValueError, TypeError):
            emotion_intensity = 1.0
        default_image_output = torch.zeros(1, image_height, image_width, 3, dtype=torch.float32, device="cpu")
        batch_size = kwargs.get('batch_size', 16)
        full_phoneme_debug_string = ""
        
        if debug: 
            print(f"--- [PGFX Visemes] EXECUTION START (Scene Index: {scene_index}) ---")

        try:
            # --- Defer g2p initialization ---
            if self.g2p_instance is None:
                try:
                    print("PGFX_ScriptGuidedVisemes: Initializing g2p_en library...")
                    
                    # Step 1: Check for NLTK data. This is a common failure point.
                    try:
                        import nltk
                        # This checks if the specific data is available, without it G2P can't work.
                        nltk.data.find('taggers/averaged_perceptron_tagger.zip')
                        nltk.data.find('corpora/cmudict.zip')
                        print("PGFX_ScriptGuidedVisemes: Required NLTK data found.")
                    except LookupError as e:
                        print(f"PGFX_ScriptGuidedVisemes: NLTK data missing: {e}. Attempting to download...")
                        # g2p_en requires 'cmudict' for phonemes and the tagger for processing.
                        nltk.download('cmudict', quiet=True)
                        nltk.download('averaged_perceptron_tagger', quiet=True)
                        print("PGFX_ScriptGuidedVisemes: NLTK data downloaded.")

                    # Step 2: Now, initialize G2p
                    self.g2p_instance = G2p()
                    
                    # Step 3: Test the instance to be sure.
                    # This will raise an exception if the model failed to load silently.
                    _ = self.g2p_instance("test")
                    
                    print("PGFX_ScriptGuidedVisemes: g2p_en initialized and tested successfully.")
                    
                except Exception as e:
                    print(f"PGFX_ScriptGuidedVisemes: FATAL: Could not initialize g2p_en.")
                    print(f"   Error Type: {type(e).__name__}")
                    print(f"   Error Details: {e}")
                    print(f"   Please ensure the 'g2p_en' and 'nltk' packages are correctly installed in your environment.")
                    traceback.print_exc()
                    return (default_image_output, "ERROR: g2p_en library failed to initialize. Check console for details.", True, None)

            # --- Load models ---
            load_emotion_profiles()
            load_emotion_classifier(speechbrain_model_base_path)

            # --- Extract data from meta ---
            alignment_data = audio_meta.get("alignment_result", {})
            durations = audio_meta.get("durations", [])
            offset_seconds = audio_meta.get("offset_seconds", 0.0)
            instrumental_cues = audio_meta.get("instrumental_cues", [])
            instrumental_cue_for_scene = instrumental_cues[scene_index] if scene_index < len(instrumental_cues) else None

            if not alignment_data or "segments" not in alignment_data:
                return (default_image_output, "SILENCE (No alignment data)", True, instrumental_cue_for_scene)

            # --- Calculate Time Window for this Scene ---
            if scene_index >= len(durations):
                scene_index = len(durations) - 1
            
            previous_duration_sum = sum(durations[:scene_index]) if scene_index > 0 else 0.0
            
            scene_start_abs = offset_seconds + previous_duration_sum
            scene_duration = durations[scene_index] if scene_index < len(durations) else 0.0
            scene_end_abs = scene_start_abs + scene_duration
            
            if debug:
                print(f"[PGFX Visemes] Sync Info for Scene {scene_index}:")
                print(f"  - Set Offset: {offset_seconds:.3f}s")
                print(f"  - Local Offset: {previous_duration_sum:.3f}s")
                print(f"  - Absolute Window: {scene_start_abs:.3f}s to {scene_end_abs:.3f}s")

            # --- EMOTION DETECTION ---
            current_emotion = "NEUTRAL"
            try:
                vocal_audio = audio_meta.get("vocal_audio", {})
                waveform = vocal_audio.get("waveform")
                sample_rate = vocal_audio.get("sample_rate")

                if waveform is not None and waveform.numel() > 0:
                    max_amp = waveform.abs().max()
                    # If max amplitude is > 0 but low, it may not be normalized. Let's normalize it.
                    if 0 < max_amp < 0.25:
                        if debug:
                            print(f"[PGFX Visemes] DEBUG: Waveform seems un-normalized (max amp: {max_amp:.4f}). Normalizing for processing.")
                        waveform = waveform / (max_amp + 1e-7)
                
                if waveform is not None:
                    context_padding = 0.5 
                    start_samp = int(max(0, scene_start_abs - context_padding) * sample_rate)
                    end_samp = int(min((scene_end_abs + context_padding) * sample_rate, waveform.shape[-1]))
                    
                    if start_samp < waveform.shape[-1]:
                        audio_slice = waveform[..., start_samp:end_samp]
                        if audio_slice.abs().max() < 0.01:
                             if debug: print("[PGFX Visemes] Audio slice is silent/muted. Emotion set to NEUTRAL.")
                             current_emotion = "NEUTRAL"
                        else:
                             current_emotion = detect_emotion_from_audio(audio_slice.squeeze(0), sample_rate, LOADED_MODELS["emotion_classifier"])
                             if debug: print(f"[PGFX Visemes] Detected Emotion: {current_emotion}")
            except Exception as e:
                print(f"[PGFX Visemes] Emotion detection warning: {e}")

            # --- Generate Phoneme Script ---
            phoneme_script = []
            all_word_segments = [word for seg in alignment_data.get("segments", []) for word in seg.get("words", [])]
            
            for word_info in all_word_segments:
                original_word = word_info.get('word', '').strip()
                if not original_word: continue
                
                word_start, word_end = word_info.get('start'), word_info.get('end')
                if word_start is None or word_end is None: continue

                if word_end > scene_start_abs and word_start < scene_end_abs:
                    local_start = word_start - scene_start_abs
                    local_end = word_end - scene_start_abs
                    
                    emotion_for_word = detect_emotion_from_word(original_word)
                    final_emotion = current_emotion if current_emotion != "NEUTRAL" else emotion_for_word

                    if self.g2p_instance is None:
                        # This should not happen if the initialization logic is correct.
                        # If we see this message, it means initialization was skipped or failed silently.
                        print("[PGFX Visemes] FATAL: g2p_instance is None before use! This indicates an initialization failure.")
                        continue # Skip this word

                    try:
                        phonemes = self.g2p_instance(original_word.upper())
                        valid_phonemes = [p.replace('0', '').replace('1', '').replace('2', '') for p in phonemes if p.replace('0', '').replace('1', '').replace('2', '') in PHONEME_TO_VISEME_MAP]

                        if not valid_phonemes:
                            phoneme_script.append(("SIL", local_start, local_end, final_emotion, local_start, local_end))
                            continue

                        duration_per_phoneme = (local_end - local_start) / len(valid_phonemes)
                        current_phoneme_time = local_start
                        for p_clean in valid_phonemes:
                            phoneme_script.append((p_clean, current_phoneme_time, current_phoneme_time + duration_per_phoneme, final_emotion, local_start, local_end))
                            current_phoneme_time += duration_per_phoneme
                    except Exception as e:
                        print(f"[PGFX Visemes] ERROR during phoneme generation for word '{original_word}': {e}")
                        # We can decide to continue to the next word or append a silent segment
                        phoneme_script.append(("SIL", local_start, local_end, final_emotion, local_start, local_end))
                        continue

            # --- Frame Generation ---
            if max_frames > 0:
                total_frames = max_frames
            else:
                total_frames = int(scene_duration * fps)

            is_silent_scene = False
            if waveform is not None:
                 exact_start = int(scene_start_abs * sample_rate)
                 exact_end = int(scene_end_abs * sample_rate)
                 if exact_start < waveform.shape[-1]:
                     exact_chunk = waveform[..., exact_start:exact_end]
                     chunk_max = exact_chunk.abs().max()
                     if isinstance(chunk_max, torch.Tensor) and chunk_max.numel() > 1:
                         chunk_max = chunk_max.max()
                     if exact_chunk.numel() > 0 and chunk_max < 0.001:
                         is_silent_scene = True
            
            # --- CRITICAL FIX: SCRIPT PRIORITY OVER SILENCE ---
            # Even if audio is silent, if we have a script (phonemes found), we animate!
            if is_silent_scene:
                if not phoneme_script:
                    if debug: print("[PGFX Visemes] Scene is silent AND has no script words. Generating blank output.")
                else:
                    if debug: print("[PGFX Visemes] Scene is audio-silent, but SCRIPT detected (Synthetic or Manual). Forcing animation.")
                    is_silent_scene = False # Force it to run generation
            
            if is_silent_scene and not phoneme_script:
                 # Generate a static sequence of frames for silence, don't return early with just 1 frame
                 full_phoneme_debug_string = "Silent (Static Face)"
                 pass # We let the loop below generate the frames (all SIL) so dimensions match WanVideo

            frame_visemes = [] 
            
            phoneme_script.sort(key=lambda x: x[1])

            for i in range(total_frames):
                frame_time = (i + 0.5) / fps
                
                found_viseme = "SIL"
                found_emotion = "NEUTRAL"
                found_intensity = 0.0

                for p_str, p_start, p_end, emo, w_start, w_end in phoneme_script:
                    if p_start <= frame_time < p_end:
                        found_viseme = PHONEME_TO_VISEME_MAP.get(p_str, "SIL")
                        found_emotion = emo
                        multiplier = calculate_dynamic_intensity(frame_time, w_start, w_end)
                        found_intensity = emotion_intensity * multiplier
                        break
                
                frame_visemes.append((found_viseme, found_emotion, found_intensity))

            # --- Draw Images ---
            # MODIFIED: Process and yield images in chunks to save memory
            template_frames_pil = [img.convert("RGB").resize((image_width, image_height)) for img in tensor_to_pil(face_template)] if face_template is not None and face_template.nelement() > 0 else []
            num_template_frames = len(template_frames_pil)
            coarticulation_weights = COARTICULATION_PROFILES.get(coarticulation_profile, COARTICULATION_PROFILES["Speech"])

            output_chunks = []
            current_chunk_images = []

            for i in range(total_frames):
                viseme_name, emotion, current_intensity = frame_visemes[i]
                curr_landmarks = VISEME_TO_LANDMARK_MAP.get(viseme_name, VISEME_TO_LANDMARK_MAP["SIL"])

                prev_viseme = frame_visemes[max(0, i - 1)][0]
                next_viseme = frame_visemes[min(len(frame_visemes) - 1, i + 1)][0]

                prev_landmarks = VISEME_TO_LANDMARK_MAP.get(prev_viseme, VISEME_TO_LANDMARK_MAP["SIL"])
                next_landmarks = VISEME_TO_LANDMARK_MAP.get(next_viseme, VISEME_TO_LANDMARK_MAP["SIL"])

                landmarks_norm = blend_landmarks(prev_landmarks, curr_landmarks, next_landmarks, coarticulation_weights)

                if emotion == "SURPRISED" and current_intensity > 0:
                    surprise_shape = VISEME_TO_LANDMARK_MAP["OO"]
                    landmarks_norm = [(ox * (1 - current_intensity) + sx * current_intensity, oy * (1 - current_intensity) + sy * current_intensity) for (ox, oy), (sx, sy) in zip(landmarks_norm, surprise_shape)]

                img = template_frames_pil[i % num_template_frames].copy() if num_template_frames > 0 else Image.new('RGB', (image_width, image_height), 'black')
                draw = ImageDraw.Draw(img)
                draw_landmarks_helper(draw, landmarks_norm, img.width, img.height, draw_style, dot_color, line_color, fill_color, dot_size, line_thickness, emotion, current_intensity)
                current_chunk_images.append(img)

                if len(current_chunk_images) == batch_size or i == total_frames - 1:
                    image_tensor_chunk = pil_to_tensor(current_chunk_images)
                    output_chunks.append(image_tensor_chunk)
                    current_chunk_images = []

            if not output_chunks:
                return (default_image_output, full_phoneme_debug_string, True, instrumental_cue_for_scene)

            # Concatenate all the small tensor chunks into the final output tensor
            final_image_tensor = torch.cat(output_chunks, dim=0)
            return (final_image_tensor, full_phoneme_debug_string, False, instrumental_cue_for_scene)

        except Exception as e:
            print(f"--- [PGFX Visemes] FATAL UNEXPECTED ERROR ---")
            traceback.print_exc(file=sys.stdout)
            return (default_image_output, f"CRITICAL ERROR: {e}", True, None)
        finally:
            cleanup_emotion_model()
            gc.collect()

# NOTE: NODE_CLASS_MAPPINGS / NODE_DISPLAY_NAME_MAPPINGS for PGFX_ScriptGuidedVisemes
# are in pgfx_viseme_nodes.py to avoid duplicate registration.
