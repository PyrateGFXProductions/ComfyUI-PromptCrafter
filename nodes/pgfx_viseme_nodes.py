import os
import sys
import gc
import traceback
import torch
import numpy as np
import re
from PIL import Image, ImageDraw
import folder_paths

from ..utils import pgfx_viseme_utils as viseme_utils

class PGFX_ScriptGuidedVisemes:
    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "audio_meta": ("DICT", {}),
                "fps": ("INT", {"default": 25, "min": 1, "max": 60}),
                "coarticulation_profile": (list(viseme_utils.COARTICULATION_PROFILES.keys()), {"default": "Singing"}),
                "debug": ("BOOLEAN", {"default": False}),
                "image_width": ("INT", {"default": 512, "min": 64, "max": 2048, "step": 64}),
                "image_height": ("INT", {"default": 512, "min": 64, "max": 2048, "step": 64}),
                "max_frames": ("INT", {"default": 0, "min": 0, "max": 99999, "step": 1}),
                "scene_index": ("INT", {"default": 0, "min": 0, "max": 100}),
                "draw_style": (["Dots", "Outline", "Filled Outline"], {"default": "Filled Outline"}),
                "dot_color": ("STRING", {"default": "white"}),
                "line_color": ("STRING", {"default": "white"}),
                "fill_color": ("STRING", {"default": "black"}),
                "dot_size": ("INT", {"default": 3, "min": 1, "max": 20}),
                "line_thickness": ("INT", {"default": 2, "min": 1, "max": 20}),
                "emotion_intensity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 3.0, "step": 0.1}),
            },
            "optional": {
                "face_template": ("IMAGE", {}),
                "speechbrain_model_base_path": ("STRING", {"default": "", "multiline": False}),
            }
        }

    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Utils"
    RETURN_TYPES = ("IMAGE", "STRING", "BOOLEAN", "STRING",)
    RETURN_NAMES = ("control_images", "phoneme_debug_text", "is_silent", "instrumental_cue",)
    FUNCTION = "execute"

    def execute(self, audio_meta, fps, coarticulation_profile, debug, image_width, image_height, 
                max_frames, scene_index, draw_style, dot_color, line_color, fill_color, 
                dot_size, line_thickness, emotion_intensity, face_template=None, 
                speechbrain_model_base_path="", **kwargs):
        
        default_image_output = torch.zeros(1, image_height, image_width, 3, dtype=torch.float32, device="cpu")
        batch_size = kwargs.get('batch_size', 16)
        full_phoneme_debug_string = "Silent audio detected. Viseme generation skipped."
        
        if debug: 
            print(f"--- [PGFX Visemes] EXECUTION START (Scene Index: {scene_index}) ---")

        try:
            g2p = viseme_utils.get_g2p()
            if not g2p:
                return (default_image_output, "ERROR: g2p_en library failed to initialize.", True, None)

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
            
            # --- EMOTION DETECTION (Audio-based) ---
            # NOTE: For now, we keep the audio emotion detection internal to the node 
            # as it requires SpeechBrain which is heavy and optional.
            current_emotion = "NEUTRAL"
            try:
                vocal_audio = audio_meta.get("vocal_audio", {})
                waveform = vocal_audio.get("waveform")
                sample_rate = vocal_audio.get("sample_rate")

                if waveform is not None and waveform.numel() > 0:
                    max_amp = waveform.abs().max()
                    if 0 < max_amp < 0.25:
                        waveform = waveform / (max_amp + 1e-7)
                
                if waveform is not None and "speechbrain" in sys.modules:
                    # Logic for audio-based emotion detection would go here if needed
                    # For now, we default to NEUTRAL or Keyword-based
                    pass
            except Exception as e:
                if debug: print(f"[PGFX Visemes] Emotion detection warning: {e}")

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
                    
                    # Keyword-based emotion fallback
                    emotion_for_word = "NEUTRAL"
                    for emo, profile in viseme_utils.EMOTION_PROFILES.items():
                        if any(keyword in original_word.lower() for keyword in profile.get("keywords", [])):
                            emotion_for_word = emo
                            break
                    
                    final_emotion = current_emotion if current_emotion != "NEUTRAL" else emotion_for_word

                    try:
                        phonemes = g2p(original_word.upper())
                        valid_phonemes = [p.replace('0', '').replace('1', '').replace('2', '') for p in phonemes 
                                         if p.replace('0', '').replace('1', '').replace('2', '') in viseme_utils.PHONEME_TO_VISEME_MAP]

                        if not valid_phonemes:
                            phoneme_script.append(("SIL", local_start, local_end, final_emotion, local_start, local_end))
                            continue

                        duration_per_phoneme = (local_end - local_start) / len(valid_phonemes)
                        current_phoneme_time = local_start
                        for p_clean in valid_phonemes:
                            phoneme_script.append((p_clean, current_phoneme_time, current_phoneme_time + duration_per_phoneme, final_emotion, local_start, local_end))
                            current_phoneme_time += duration_per_phoneme
                    except Exception as e:
                        if debug: print(f"[PGFX Visemes] ERROR during phoneme generation for word '{original_word}': {e}")
                        phoneme_script.append(("SIL", local_start, local_end, final_emotion, local_start, local_end))

            # --- Frame Generation ---
            total_frames = max_frames if max_frames > 0 else int(scene_duration * fps)
            if total_frames <= 0: total_frames = 1

            frame_visemes = [] 
            phoneme_script.sort(key=lambda x: x[1])

            for i in range(total_frames):
                frame_time = (i + 0.5) / fps
                found_viseme, found_emotion, found_intensity = "SIL", "NEUTRAL", 0.0

                for p_str, p_start, p_end, emo, w_start, w_end in phoneme_script:
                    if p_start <= frame_time < p_end:
                        found_viseme = viseme_utils.PHONEME_TO_VISEME_MAP.get(p_str, "SIL")
                        found_emotion = emo
                        multiplier = viseme_utils.calculate_dynamic_intensity(frame_time, w_start, w_end)
                        found_intensity = emotion_intensity * multiplier
                        break
                
                frame_visemes.append((found_viseme, found_emotion, found_intensity))

            # --- Draw Images ---
            template_frames_pil = viseme_utils.tensor_to_pil(face_template) if face_template is not None and face_template.numel() > 0 else []
            num_template_frames = len(template_frames_pil)

            output_chunks = []
            current_chunk_images = []

            for i in range(total_frames):
                viseme_name, emotion, current_intensity = frame_visemes[i]
                curr_landmarks = viseme_utils.VISEME_TO_LANDMARK_MAP.get(viseme_name, viseme_utils.VISEME_TO_LANDMARK_MAP["SIL"])

                prev_viseme = frame_visemes[max(0, i - 1)][0]
                next_viseme = frame_visemes[min(len(frame_visemes) - 1, i + 1)][0]

                prev_landmarks = viseme_utils.VISEME_TO_LANDMARK_MAP.get(prev_viseme, viseme_utils.VISEME_TO_LANDMARK_MAP["SIL"])
                next_landmarks = viseme_utils.VISEME_TO_LANDMARK_MAP.get(next_viseme, viseme_utils.VISEME_TO_LANDMARK_MAP["SIL"])

                landmarks_norm = viseme_utils.blend_landmarks(prev_landmarks, curr_landmarks, next_landmarks, coarticulation_profile)

                # Special "SURPRISED" handling from old script
                if emotion == "SURPRISED" and current_intensity > 0:
                    surprise_shape = viseme_utils.VISEME_TO_LANDMARK_MAP["OO"]
                    landmarks_norm = [(ox * (1 - current_intensity) + sx * current_intensity, 
                                       oy * (1 - current_intensity) + sy * current_intensity) 
                                      for (ox, oy), (sx, sy) in zip(landmarks_norm, surprise_shape)]

                img = template_frames_pil[i % num_template_frames].copy() if num_template_frames > 0 else Image.new('RGB', (image_width, image_height), 'black')
                draw = ImageDraw.Draw(img)
                viseme_utils.draw_landmarks_helper(draw, landmarks_norm, img.width, img.height, draw_style, dot_color, line_color, fill_color, dot_size, line_thickness, emotion, current_intensity)
                current_chunk_images.append(img)

                if len(current_chunk_images) == batch_size or i == total_frames - 1:
                    image_tensor_chunk = viseme_utils.pil_to_tensor(current_chunk_images)
                    output_chunks.append(image_tensor_chunk)
                    current_chunk_images = []

            if not output_chunks:
                return (default_image_output, full_phoneme_debug_string, True, instrumental_cue_for_scene)

            final_image_tensor = torch.cat(output_chunks, dim=0)
            return (final_image_tensor, "Animation Generated", False, instrumental_cue_for_scene)

        except Exception as e:
            if debug: traceback.print_exc()
            return (default_image_output, f"CRITICAL ERROR: {e}", True, None)

NODE_CLASS_MAPPINGS = {"PGFX_ScriptGuidedVisemes": PGFX_ScriptGuidedVisemes}
NODE_DISPLAY_NAME_MAPPINGS = {"PGFX_ScriptGuidedVisemes": "☠️PGFX Script-Guided Visemes"}
