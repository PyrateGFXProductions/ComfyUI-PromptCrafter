import json
import re
import traceback

import torch
from PIL import Image, ImageDraw

from ..utils import pgfx_viseme_utils as viseme_utils

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

# ------------------------------------------------------------------------------------
# PGFX_CinemaVisemeRig Node
# ------------------------------------------------------------------------------------
class PGFX_CinemaVisemeRig:
    DESCRIPTION = get_node_description("PGFX_CinemaVisemeRig")
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lyrics": ("STRING", {"multiline": True, "placeholder": "Enter the text to animate...", "tooltip": "The phonetic driver. The node will calculate precise mouth movements based on these words."}),
                "fps": ("INT", {"default": 25, "min": 1, "max": 120}),
                "target_mode": (["LivePortrait (Cyan/Magenta)", "ControlNet (Canny)", "Mask Only (Lip Focus)"], {"default": "LivePortrait (Cyan/Magenta)", "tooltip": "Select the backend you are driving. 'LivePortrait' is the Gold Standard for realism."}),
                "smoothing_sigma": ("FLOAT", {"default": 1.2, "min": 0.0, "max": 5.0, "step": 0.1, "tooltip": "Gaussian temporal smoothing. Higher values (1.5+) eliminate all jitter but may look 'mumbly'. Lower values (0.5) are sharper but twitchier."}),
                "image_width": ("INT", {"default": 512, "min": 64, "max": 4096, "step": 64}),
                "image_height": ("INT", {"default": 512, "min": 64, "max": 4096, "step": 64}),
            },
            "optional": {
                "audio_meta": ("DICT", {"tooltip": "Optional: Connect a WhisperX output here for perfect millisecond-level word timing."}),
                "face_template": ("IMAGE", {"tooltip": "Optional: A reference face to draw the rig on top of. If empty, a black background is used."}),
                "emotion_intensity": ("STRING", {"default": "1.0", "multiline": False}),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("rig_guides", "canny_guides", "lip_mask", "phoneme_debug")
    FUNCTION = "animate"
    CATEGORY = "☠️PGFX /Video"

    def animate(self, lyrics, fps, target_mode, smoothing_sigma, image_width, image_height, audio_meta=None, face_template=None, emotion_intensity="1.0", **kwargs):
        try:
            emotion_intensity = float(emotion_intensity)
        except (ValueError, TypeError):
            emotion_intensity = 1.0
        try:
            g2p = viseme_utils.get_g2p()
            if not g2p:
                raise RuntimeError("G2P_EN library failed to initialize.")

            # 1. Resolve Timing
            word_segments = []
            if audio_meta and "word_segments" in audio_meta:
                word_segments = audio_meta["word_segments"]
            else:
                # Basic phonetic spacing if no audio_meta
                lyrics = str(lyrics or "")
                words = [w for w in re.sub(r"[^\w'\- ]+", "", lyrics).split() if w]
                cursor = 0.0
                words_per_sec = 2.5 # Average speaking rate
                for w in words:
                    duration = max(0.2, len(w) / (words_per_sec * 5))
                    word_segments.append({"word": w, "start": cursor, "end": cursor + duration})
                    cursor += duration + 0.05

            if not word_segments:
                return (torch.zeros(1, image_height, image_width, 3), torch.zeros(1, image_height, image_width, 3), torch.zeros(1, image_height, image_width), "No words found")

            total_duration = word_segments[-1]["end"]
            # Use actual audio total duration if available so silent trailing
            # frames are not truncated — every audio frame gets viseme conditioning.
            if audio_meta:
                audio_total = audio_meta.get("audio_total_duration", 0) or 0
                if audio_total > total_duration:
                    total_duration = audio_total
            total_frames = int(round(total_duration * fps))
            total_frames = max(1, total_frames)

            # 2. Build Weighted Phoneme Script
            phoneme_script = []
            for word_info in word_segments:
                word_text = word_info["word"]
                start, end = word_info["start"], word_info["end"]
                
                phonemes = g2p(word_text.upper())
                valid = []
                total_weight = 0.0
                for p in phonemes:
                    token = re.sub(r"\d+", "", str(p)).strip()
                    if token in viseme_utils.PHONEME_TO_VISEME_MAP:
                        weight = viseme_utils.PHONEME_TO_VISEME_MAP[token]['weight']
                        valid.append({'token': token, 'weight': weight})
                        total_weight += weight
                
                if not valid:
                    phoneme_script.append(("SIL", start, end, 1.0))
                    continue

                # Distribute duration by weight
                word_dur = end - start
                curr_t = start
                for v in valid:
                    p_dur = (v['weight'] / total_weight) * word_dur
                    phoneme_script.append((v['token'], curr_t, curr_t + p_dur, v['weight']))
                    curr_t += p_dur

            # 3. Sample Landmarks per Frame
            raw_landmarks_series = []
            frame_visemes = []
            for f in range(total_frames):
                t = (f + 0.5) / fps
                active_viseme = "SIL"
                for p, p_start, p_end, _ in phoneme_script:
                    if p_start <= t < p_end:
                        active_viseme = viseme_utils.PHONEME_TO_VISEME_MAP.get(p, {'viseme': 'SIL'})['viseme']
                        break
                
                frame_visemes.append(active_viseme)
                raw_landmarks_series.append(viseme_utils.VISEME_TO_LANDMARK_MAP.get(active_viseme, viseme_utils.VISEME_TO_LANDMARK_MAP["SIL"]))

            # 4. Gaussian Smoothing (The Secret Sauce)
            smoothed_landmarks = viseme_utils.gaussian_smooth_landmarks(raw_landmarks_series, sigma=smoothing_sigma)

            # 5. Render Outputs
            rig_images = []
            canny_images = []
            lip_masks = []
            
            template_frames = viseme_utils.tensor_to_pil(face_template) if face_template is not None else []
            
            for f in range(total_frames):
                lms = smoothed_landmarks[f]
                
                # Base Rig / Guides
                if template_frames:
                    base_img = template_frames[f % len(template_frames)].copy().resize((image_width, image_height))
                else:
                    base_img = Image.new("RGB", (image_width, image_height), "black")
                
                draw = ImageDraw.Draw(base_img)
                
                # Configure style based on target_mode
                if "LivePortrait" in target_mode:
                    viseme_utils.draw_landmarks_helper(draw, lms, image_width, image_height, "Filled Outline", "#06b6d4", "#ff00ff", "#000000", 4, 3, "NEUTRAL", 1.0)
                else:
                    viseme_utils.draw_landmarks_helper(draw, lms, image_width, image_height, "Dots", "white", "white", "black", 4, 2, "NEUTRAL", 1.0)
                
                rig_images.append(base_img)
                
                # Canny Logic
                canny_img = Image.new("RGB", (image_width, image_height), "black")
                viseme_utils.draw_landmarks_helper(ImageDraw.Draw(canny_img), lms, image_width, image_height, "Outline", "white", "white", "black", 1, 2, "NEUTRAL", 1.0)
                canny_images.append(canny_img)
                
                # Mask Logic
                lip_masks.append(viseme_utils.get_mouth_mask(lms, image_width, image_height))

            return (
                viseme_utils.pil_to_tensor(rig_images),
                viseme_utils.pil_to_tensor(canny_images),
                viseme_utils.pil_to_tensor(lip_masks).squeeze(-1),
                f"Generated {total_frames} frames of phonetic animation."
            )

        except Exception as e:
            print(f"\n*** [PGFX_CinemaVisemeRig] ERROR: {e} ***\n")
            traceback.print_exc()
            return (torch.zeros(1, image_height, image_width, 3), torch.zeros(1, image_height, image_width, 3), torch.zeros(1, image_height, image_width), f"ERROR: {e}")

class PGFX_ScriptGuidedVisemes:
    DESCRIPTION = get_node_description("PGFX_ScriptGuidedVisemes")
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio_meta": ("DICT", {}),
                "fps": ("INT", {"default": 25, "min": 1, "max": 120}),
                "coarticulation_profile": (
                    list(viseme_utils.COARTICULATION_PROFILES.keys()),
                    {"default": "Singing"},
                ),
                "debug": ("BOOLEAN", {"default": False}),
                "image_width": ("INT", {"default": 512, "min": 64, "max": 4096, "step": 64}),
                "image_height": ("INT", {"default": 512, "min": 64, "max": 4096, "step": 64}),
                "max_frames": ("INT", {"default": 0, "min": 0, "max": 99999, "step": 1}),
                "scene_index": ("INT", {"default": 0, "min": 0, "max": 99999}),
                "draw_style": (["Dots", "Outline", "Filled Outline"], {"default": "Filled Outline"}),
                "dot_color": ("STRING", {"default": "white"}),
                "line_color": ("STRING", {"default": "white"}),
                "fill_color": ("STRING", {"default": "black"}),
                "dot_size": ("INT", {"default": 3, "min": 1, "max": 20}),
                "line_thickness": ("INT", {"default": 2, "min": 1, "max": 20}),
                "emotion_intensity": ("STRING", {"default": "1.0", "multiline": False}),
            },
            "optional": {
                "face_template": ("IMAGE", {}),
                "batch_size": ("INT", {"default": 16, "min": 1, "max": 4096}),
                "speechbrain_model_base_path": ("STRING", {"default": "", "multiline": False}),
            },
        }

    CATEGORY = "☠️PGFX /Video"
    RETURN_TYPES = ("IMAGE", "STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = ("control_images", "phoneme_debug_text", "is_silent", "instrumental_cue")
    FUNCTION = "execute"

    @staticmethod
    def _clean_word(word):
        text = str(word or "").strip()
        text = re.sub(r"[^\w'\- ]+", "", text)
        return text.strip()

    @staticmethod
    def _coerce_float_list(values, fps):
        durations = []
        for value in values or []:
            try:
                durations.append(float(value))
            except Exception:
                continue
        return durations

    @staticmethod
    def _extract_durations_seconds(audio_meta, fps):
        # If the audio_meta carrier recorded its own fps, prefer that to avoid
        # frame-count ↔ seconds conversion mismatch across pipeline stages.
        meta_fps = audio_meta.get("fps", None)
        if meta_fps is not None:
            try:
                meta_fps = float(meta_fps)
            except Exception:
                meta_fps = None
        effective_fps = meta_fps if meta_fps is not None else float(fps)

        if audio_meta.get("durations"):
            return PGFX_ScriptGuidedVisemes._coerce_float_list(audio_meta.get("durations"), effective_fps)

        if audio_meta.get("durations_seconds"):
            return PGFX_ScriptGuidedVisemes._coerce_float_list(audio_meta.get("durations_seconds"), effective_fps)

        if audio_meta.get("scene_durations"):
            return PGFX_ScriptGuidedVisemes._coerce_float_list(audio_meta.get("scene_durations"), effective_fps)

        frames = audio_meta.get("durations_frames") or []
        durations = []
        for value in frames:
            try:
                durations.append(float(value) / effective_fps)
            except Exception:
                continue
        return durations

    @staticmethod
    def _extract_word_segments(audio_meta):
        segments = []

        direct_words = audio_meta.get("word_segments") or audio_meta.get("words") or []
        for word in direct_words:
            start = word.get("start")
            end = word.get("end")
            text = PGFX_ScriptGuidedVisemes._clean_word(word.get("word") or word.get("text"))
            if text and start is not None and end is not None:
                try:
                    segments.append({"word": text, "start": float(start), "end": float(end)})
                except Exception:
                    continue

        if segments:
            return sorted(segments, key=lambda item: item["start"])

        alignment = audio_meta.get("alignment_result") or {}
        for seg in alignment.get("segments", []):
            for word in seg.get("words", []):
                start = word.get("start")
                end = word.get("end")
                text = PGFX_ScriptGuidedVisemes._clean_word(word.get("word") or word.get("text"))
                if text and start is not None and end is not None:
                    try:
                        segments.append({"word": text, "start": float(start), "end": float(end)})
                    except Exception:
                        continue

        return sorted(segments, key=lambda item: item["start"])

    @staticmethod
    def _extract_word_segments_from_json(word_timing_json):
        if not str(word_timing_json or "").strip():
            return []
        try:
            payload = json.loads(word_timing_json)
        except Exception:
            return []

        if isinstance(payload, dict):
            if isinstance(payload.get("word_segments"), list):
                payload = payload["word_segments"]
            elif isinstance(payload.get("words"), list):
                payload = payload["words"]
            else:
                payload = []

        segments = []
        for word in payload if isinstance(payload, list) else []:
            start = word.get("start")
            end = word.get("end")
            text = PGFX_ScriptGuidedVisemes._clean_word(word.get("word") or word.get("text"))
            if text and start is not None and end is not None:
                try:
                    segments.append({"word": text, "start": float(start), "end": float(end)})
                except Exception:
                    continue
        return sorted(segments, key=lambda item: item["start"])

    @staticmethod
    def _instrumental_cue_for_scene(audio_meta, scene_index):
        cues = audio_meta.get("instrumental_cues") or []
        if isinstance(cues, list) and scene_index < len(cues):
            return str(cues[scene_index] or "")
        return ""

    @staticmethod
    def _resolve_scene_window(audio_meta, word_segments, durations, scene_index, fps, max_frames):
        offset_seconds = float(audio_meta.get("offset_seconds", 0.0) or 0.0)

        if durations:
            safe_index = min(scene_index, max(len(durations) - 1, 0))
            start = offset_seconds + sum(durations[:safe_index])
            duration = max(0.0, float(durations[safe_index]))
            return start, duration, safe_index

        if scene_index > 0:
            return offset_seconds, 0.0, scene_index

        if max_frames > 0:
            return offset_seconds, float(max_frames) / float(fps), scene_index

        if word_segments:
            start = min(word["start"] for word in word_segments)
            end = max(word["end"] for word in word_segments)
            return start, max(0.0, end - start), scene_index

        return offset_seconds, 0.0, scene_index

    @staticmethod
    def _fallback_frames(total_frames, image_width, image_height, face_template):
        total_frames = max(1, int(total_frames))
        if face_template is not None and hasattr(face_template, "numel") and face_template.numel() > 0:
            frame_count = int(face_template.shape[0])
            if frame_count >= total_frames:
                return face_template[:total_frames].detach().cpu().clone()
            repeats = []
            for idx in range(total_frames):
                repeats.append(face_template[idx % frame_count : (idx % frame_count) + 1].detach().cpu())
            return torch.cat(repeats, dim=0)

        return torch.zeros(total_frames, image_height, image_width, 3, dtype=torch.float32, device="cpu")

    @staticmethod
    def _emotion_for_word(word):
        lowered = str(word or "").lower()
        for emotion, profile in viseme_utils.EMOTION_PROFILES.items():
            if any(keyword in lowered for keyword in profile.get("keywords", [])):
                return emotion
        return "NEUTRAL"

    @staticmethod
    def _phonemes_for_word(g2p, word):
        phonemes = g2p(word)
        cleaned = []
        for phoneme in phonemes:
            token = re.sub(r"\d+", "", str(phoneme or "").strip())
            if token in viseme_utils.PHONEME_TO_VISEME_MAP:
                cleaned.append(token)
        return cleaned

    def execute(
        self,
        audio_meta,
        fps,
        coarticulation_profile,
        debug,
        image_width,
        image_height,
        max_frames,
        scene_index,
        draw_style,
        dot_color,
        line_color,
        fill_color,
        dot_size,
        line_thickness,
        emotion_intensity,
        face_template=None,
        batch_size=16,
        speechbrain_model_base_path="",
        **kwargs,
    ):
        try:
            emotion_intensity = float(emotion_intensity)
        except (ValueError, TypeError):
            emotion_intensity = 1.0
        if debug:
            print(f"--- [PGFX Visemes] EXECUTION START (Scene Index: {scene_index}) ---")

        try:
            g2p = viseme_utils.get_g2p()
            if not g2p:
                fallback = self._fallback_frames(max_frames or 1, image_width, image_height, face_template)
                return (fallback, "ERROR: g2p_en library failed to initialize.", True, "")

            durations = self._extract_durations_seconds(audio_meta, fps)
            word_segments = self._extract_word_segments(audio_meta)
            scene_start_abs, scene_duration, resolved_scene_index = self._resolve_scene_window(
                audio_meta, word_segments, durations, scene_index, fps, max_frames
            )
            scene_end_abs = scene_start_abs + scene_duration
            instrumental_cue = self._instrumental_cue_for_scene(audio_meta, resolved_scene_index)

            total_frames = int(max_frames) if max_frames and max_frames > 0 else int(round(scene_duration * fps))
            total_frames = max(1, total_frames)

            if scene_duration <= 0.0:
                fallback = self._fallback_frames(total_frames, image_width, image_height, face_template)
                return (fallback, "SILENCE (No scene duration resolved)", True, instrumental_cue)

            scene_words = [
                word for word in word_segments
                if word["end"] > scene_start_abs and word["start"] < scene_end_abs
            ]

            if not scene_words:
                fallback = self._fallback_frames(total_frames, image_width, image_height, face_template)
                return (fallback, "SILENCE (No words overlap this scene)", True, instrumental_cue)

            phoneme_script = []
            debug_parts = []

            for word in scene_words:
                word_text = word["word"]
                local_start = max(0.0, word["start"] - scene_start_abs)
                local_end = min(scene_duration, word["end"] - scene_start_abs)
                if local_end <= local_start:
                    continue

                phonemes = self._phonemes_for_word(g2p, word_text)
                emotion = self._emotion_for_word(word_text)

                if not phonemes:
                    phoneme_script.append(("SIL", local_start, local_end, emotion, local_start, local_end))
                    debug_parts.append(f"{word_text}:SIL")
                    continue

                debug_parts.append(f"{word_text}:{'-'.join(phonemes)}")
                duration_per_phoneme = (local_end - local_start) / float(len(phonemes))
                phoneme_time = local_start
                for idx, phoneme in enumerate(phonemes):
                    next_time = local_end if idx == len(phonemes) - 1 else phoneme_time + duration_per_phoneme
                    phoneme_script.append((phoneme, phoneme_time, next_time, emotion, local_start, local_end))
                    phoneme_time = next_time

            phoneme_script.sort(key=lambda item: item[1])

            if not phoneme_script:
                fallback = self._fallback_frames(total_frames, image_width, image_height, face_template)
                return (fallback, "SILENCE (No phonemes generated)", True, instrumental_cue)

            frame_visemes = []
            for frame_idx in range(total_frames):
                frame_time = (frame_idx + 0.5) / float(fps)
                active_viseme = ("SIL", "NEUTRAL", 0.0)
                for phoneme, start, end, emotion, word_start, word_end in phoneme_script:
                    if start <= frame_time < end:
                        viseme_name = viseme_utils.PHONEME_TO_VISEME_MAP.get(phoneme, "SIL")
                        multiplier = viseme_utils.calculate_dynamic_intensity(frame_time, word_start, word_end)
                        active_viseme = (viseme_name, emotion, max(0.0, emotion_intensity * multiplier))
                        break
                frame_visemes.append(active_viseme)

            template_frames = viseme_utils.tensor_to_pil(face_template) if face_template is not None and face_template.numel() > 0 else []
            template_count = len(template_frames)

            output_chunks = []
            current_chunk = []
            batch_size = max(1, int(batch_size))

            for frame_idx, (viseme_name, emotion, intensity) in enumerate(frame_visemes):
                curr_landmarks = viseme_utils.VISEME_TO_LANDMARK_MAP.get(
                    viseme_name, viseme_utils.VISEME_TO_LANDMARK_MAP["SIL"]
                )
                prev_viseme = frame_visemes[max(0, frame_idx - 1)][0]
                next_viseme = frame_visemes[min(len(frame_visemes) - 1, frame_idx + 1)][0]
                prev_landmarks = viseme_utils.VISEME_TO_LANDMARK_MAP.get(
                    prev_viseme, viseme_utils.VISEME_TO_LANDMARK_MAP["SIL"]
                )
                next_landmarks = viseme_utils.VISEME_TO_LANDMARK_MAP.get(
                    next_viseme, viseme_utils.VISEME_TO_LANDMARK_MAP["SIL"]
                )

                landmarks_norm = viseme_utils.blend_landmarks(
                    prev_landmarks, curr_landmarks, next_landmarks, coarticulation_profile
                )

                if emotion == "SURPRISED" and intensity > 0.0:
                    surprise = viseme_utils.VISEME_TO_LANDMARK_MAP["OO"]
                    landmarks_norm = [
                        (
                            base_x * (1.0 - intensity) + surprise_x * intensity,
                            base_y * (1.0 - intensity) + surprise_y * intensity,
                        )
                        for (base_x, base_y), (surprise_x, surprise_y) in zip(landmarks_norm, surprise)
                    ]

                if template_count > 0:
                    image = template_frames[frame_idx % template_count].copy()
                else:
                    image = Image.new("RGB", (image_width, image_height), "black")

                draw = ImageDraw.Draw(image)
                viseme_utils.draw_landmarks_helper(
                    draw,
                    landmarks_norm,
                    image.width,
                    image.height,
                    draw_style,
                    dot_color,
                    line_color,
                    fill_color,
                    dot_size,
                    line_thickness,
                    emotion,
                    intensity,
                )
                current_chunk.append(image)

                if len(current_chunk) == batch_size or frame_idx == total_frames - 1:
                    output_chunks.append(viseme_utils.pil_to_tensor(current_chunk))
                    current_chunk = []

            final_tensor = torch.cat(output_chunks, dim=0) if output_chunks else self._fallback_frames(
                total_frames, image_width, image_height, face_template
            )
            debug_text = " | ".join(debug_parts[:24])
            if len(debug_parts) > 24:
                debug_text += f" | ... ({len(debug_parts)} words)"

            return (final_tensor, debug_text or "Animation Generated", False, instrumental_cue)

        except Exception as exc:
            if debug:
                traceback.print_exc()
            fallback = self._fallback_frames(max_frames or 1, image_width, image_height, face_template)
            return (fallback, f"CRITICAL ERROR: {exc}", True, "")


class PGFX_UniversalVisemeGuides(PGFX_ScriptGuidedVisemes):
    DESCRIPTION = get_node_description("PGFX_UniversalVisemeGuides")
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "fps": ("INT", {"default": 25, "min": 1, "max": 120}),
                "image_width": ("INT", {"default": 512, "min": 64, "max": 4096, "step": 64}),
                "image_height": ("INT", {"default": 512, "min": 64, "max": 4096, "step": 64}),
                "max_frames": ("INT", {"default": 0, "min": 0, "max": 99999, "step": 1}),
                "scene_index": ("INT", {"default": 0, "min": 0, "max": 99999}),
                "scene_start_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "step": 0.001}),
                "scene_duration_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "step": 0.001}),
                "coarticulation_profile": (
                    list(viseme_utils.COARTICULATION_PROFILES.keys()),
                    {"default": "Singing"},
                ),
                "draw_style": (["Dots", "Outline", "Filled Outline"], {"default": "Filled Outline"}),
                "dot_color": ("STRING", {"default": "white"}),
                "line_color": ("STRING", {"default": "white"}),
                "fill_color": ("STRING", {"default": "black"}),
                "dot_size": ("INT", {"default": 3, "min": 1, "max": 20}),
                "line_thickness": ("INT", {"default": 2, "min": 1, "max": 20}),
                "emotion_intensity": ("STRING", {"default": "1.0", "multiline": False}),
                "debug": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "audio_meta": ("DICT", {}),
                "word_timing_json": ("STRING", {"default": "", "multiline": True}),
                "face_template": ("IMAGE", {}),
                "batch_size": ("INT", {"default": 16, "min": 1, "max": 4096}),
            },
        }

    CATEGORY = "☠️PGFX /Video"
    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = (
        "control_images",
        "depth_guides",
        "canny_guides",
        "phoneme_debug_text",
        "is_silent",
        "instrumental_cue",
    )
    FUNCTION = "execute_universal"

    def _draw_guide_frames(
        self,
        frame_visemes,
        total_frames,
        image_width,
        image_height,
        coarticulation_profile,
        draw_style,
        dot_color,
        line_color,
        fill_color,
        dot_size,
        line_thickness,
        face_template,
        batch_size,
    ):
        template_frames = viseme_utils.tensor_to_pil(face_template) if face_template is not None and face_template.numel() > 0 else []
        template_count = len(template_frames)
        main_chunks = []
        depth_chunks = []
        canny_chunks = []
        current_main = []
        current_depth = []
        current_canny = []
        batch_size = max(1, int(batch_size))

        for frame_idx, (viseme_name, emotion, intensity) in enumerate(frame_visemes):
            curr_landmarks = viseme_utils.VISEME_TO_LANDMARK_MAP.get(
                viseme_name, viseme_utils.VISEME_TO_LANDMARK_MAP["SIL"]
            )
            prev_viseme = frame_visemes[max(0, frame_idx - 1)][0]
            next_viseme = frame_visemes[min(len(frame_visemes) - 1, frame_idx + 1)][0]
            prev_landmarks = viseme_utils.VISEME_TO_LANDMARK_MAP.get(
                prev_viseme, viseme_utils.VISEME_TO_LANDMARK_MAP["SIL"]
            )
            next_landmarks = viseme_utils.VISEME_TO_LANDMARK_MAP.get(
                next_viseme, viseme_utils.VISEME_TO_LANDMARK_MAP["SIL"]
            )
            landmarks_norm = viseme_utils.blend_landmarks(
                prev_landmarks, curr_landmarks, next_landmarks, coarticulation_profile
            )

            if emotion == "SURPRISED" and intensity > 0.0:
                surprise = viseme_utils.VISEME_TO_LANDMARK_MAP["OO"]
                landmarks_norm = [
                    (
                        base_x * (1.0 - intensity) + surprise_x * intensity,
                        base_y * (1.0 - intensity) + surprise_y * intensity,
                    )
                    for (base_x, base_y), (surprise_x, surprise_y) in zip(landmarks_norm, surprise)
                ]

            if template_count > 0:
                main_image = template_frames[frame_idx % template_count].copy()
            else:
                main_image = Image.new("RGB", (image_width, image_height), "black")
            depth_image = Image.new("RGB", (image_width, image_height), "black")
            canny_image = Image.new("RGB", (image_width, image_height), "black")

            viseme_utils.draw_landmarks_helper(
                ImageDraw.Draw(main_image),
                landmarks_norm,
                main_image.width,
                main_image.height,
                draw_style,
                dot_color,
                line_color,
                fill_color,
                dot_size,
                line_thickness,
                emotion,
                intensity,
            )
            viseme_utils.draw_landmarks_helper(
                ImageDraw.Draw(depth_image),
                landmarks_norm,
                depth_image.width,
                depth_image.height,
                "Filled Outline",
                "white",
                "white",
                "gray",
                dot_size,
                line_thickness,
                emotion,
                intensity,
            )
            viseme_utils.draw_landmarks_helper(
                ImageDraw.Draw(canny_image),
                landmarks_norm,
                canny_image.width,
                canny_image.height,
                "Outline",
                "white",
                "white",
                "black",
                dot_size,
                line_thickness,
                emotion,
                intensity,
            )

            current_main.append(main_image)
            current_depth.append(depth_image)
            current_canny.append(canny_image)

            if len(current_main) == batch_size or frame_idx == total_frames - 1:
                main_chunks.append(viseme_utils.pil_to_tensor(current_main))
                depth_chunks.append(viseme_utils.pil_to_tensor(current_depth))
                canny_chunks.append(viseme_utils.pil_to_tensor(current_canny))
                current_main = []
                current_depth = []
                current_canny = []

        return (
            torch.cat(main_chunks, dim=0),
            torch.cat(depth_chunks, dim=0),
            torch.cat(canny_chunks, dim=0),
        )

    def execute_universal(
        self,
        fps,
        image_width,
        image_height,
        max_frames,
        scene_index,
        scene_start_seconds,
        scene_duration_seconds,
        coarticulation_profile,
        draw_style,
        dot_color,
        line_color,
        fill_color,
        dot_size,
        line_thickness,
        emotion_intensity,
        debug,
        audio_meta=None,
        word_timing_json="",
        face_template=None,
        batch_size=16,
        **kwargs,
    ):
        audio_meta = audio_meta or {}
        try:
            emotion_intensity = float(emotion_intensity)
        except (ValueError, TypeError):
            emotion_intensity = 1.0
        if debug:
            print(f"--- [PGFX Universal Visemes] START (Scene Index: {scene_index}) ---")

        try:
            g2p = viseme_utils.get_g2p()
            if not g2p:
                fallback = self._fallback_frames(max_frames or 1, image_width, image_height, face_template)
                return (fallback, fallback.clone(), fallback.clone(), "ERROR: g2p_en library failed to initialize.", True, "")

            word_segments = self._extract_word_segments_from_json(word_timing_json)
            if not word_segments:
                word_segments = self._extract_word_segments(audio_meta)

            durations = self._extract_durations_seconds(audio_meta, fps)
            instrumental_cue = self._instrumental_cue_for_scene(audio_meta, scene_index)

            if scene_duration_seconds > 0.0:
                scene_start_abs = max(0.0, float(scene_start_seconds))
                scene_duration = float(scene_duration_seconds)
            else:
                scene_start_abs, scene_duration, _ = self._resolve_scene_window(
                    audio_meta, word_segments, durations, scene_index, fps, max_frames
                )

            total_frames = int(max_frames) if max_frames and max_frames > 0 else int(round(scene_duration * fps))
            total_frames = max(1, total_frames)
            scene_end_abs = scene_start_abs + scene_duration

            if scene_duration <= 0.0 or not word_segments:
                fallback = self._fallback_frames(total_frames, image_width, image_height, face_template)
                return (fallback, fallback.clone(), fallback.clone(), "SILENCE (No usable timing data)", True, instrumental_cue)

            scene_words = [
                word for word in word_segments
                if word["end"] > scene_start_abs and word["start"] < scene_end_abs
            ]
            if not scene_words:
                fallback = self._fallback_frames(total_frames, image_width, image_height, face_template)
                return (fallback, fallback.clone(), fallback.clone(), "SILENCE (No words overlap this scene)", True, instrumental_cue)

            phoneme_script = []
            debug_parts = []
            for word in scene_words:
                word_text = word["word"]
                local_start = max(0.0, word["start"] - scene_start_abs)
                local_end = min(scene_duration, word["end"] - scene_start_abs)
                if local_end <= local_start:
                    continue
                phonemes = self._phonemes_for_word(g2p, word_text)
                emotion = self._emotion_for_word(word_text)

                if not phonemes:
                    phoneme_script.append(("SIL", local_start, local_end, emotion, local_start, local_end))
                    debug_parts.append(f"{word_text}:SIL")
                    continue

                debug_parts.append(f"{word_text}:{'-'.join(phonemes)}")
                duration_per_phoneme = (local_end - local_start) / float(len(phonemes))
                phoneme_time = local_start
                for idx, phoneme in enumerate(phonemes):
                    next_time = local_end if idx == len(phonemes) - 1 else phoneme_time + duration_per_phoneme
                    phoneme_script.append((phoneme, phoneme_time, next_time, emotion, local_start, local_end))
                    phoneme_time = next_time

            phoneme_script.sort(key=lambda item: item[1])
            if not phoneme_script:
                fallback = self._fallback_frames(total_frames, image_width, image_height, face_template)
                return (fallback, fallback.clone(), fallback.clone(), "SILENCE (No phonemes generated)", True, instrumental_cue)

            frame_visemes = []
            for frame_idx in range(total_frames):
                frame_time = (frame_idx + 0.5) / float(fps)
                active_viseme = ("SIL", "NEUTRAL", 0.0)
                for phoneme, start, end, emotion, word_start, word_end in phoneme_script:
                    if start <= frame_time < end:
                        viseme_name = viseme_utils.PHONEME_TO_VISEME_MAP.get(phoneme, "SIL")
                        multiplier = viseme_utils.calculate_dynamic_intensity(frame_time, word_start, word_end)
                        active_viseme = (viseme_name, emotion, max(0.0, emotion_intensity * multiplier))
                        break
                frame_visemes.append(active_viseme)

            main_tensor, depth_tensor, canny_tensor = self._draw_guide_frames(
                frame_visemes,
                total_frames,
                image_width,
                image_height,
                coarticulation_profile,
                draw_style,
                dot_color,
                line_color,
                fill_color,
                dot_size,
                line_thickness,
                face_template,
                batch_size,
            )

            debug_text = " | ".join(debug_parts[:24])
            if len(debug_parts) > 24:
                debug_text += f" | ... ({len(debug_parts)} words)"

            return (
                main_tensor,
                depth_tensor,
                canny_tensor,
                debug_text or "Animation Generated",
                False,
                instrumental_cue,
            )

        except Exception as exc:
            if debug:
                traceback.print_exc()
            fallback = self._fallback_frames(max_frames or 1, image_width, image_height, face_template)
            return (fallback, fallback.clone(), fallback.clone(), f"CRITICAL ERROR: {exc}", True, "")


class PGFX_WordTimingJsonBuilder(PGFX_ScriptGuidedVisemes):
    DESCRIPTION = get_node_description("PGFX_WordTimingJsonBuilder")
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "debug": ("BOOLEAN", {"default": False}),
            },
            "optional": {
                "audio_meta": ("DICT", {}),
                "segments_json_text": ("STRING", {"default": "", "multiline": True}),
                "srt_text": ("STRING", {"default": "", "multiline": True}),
                "srt_path": ("STRING", {"default": "", "multiline": False}),
            },
        }

    CATEGORY = "☠️PGFX /Video"
    RETURN_TYPES = ("STRING", "DICT", "INT", "STRING")
    RETURN_NAMES = ("word_timing_json", "word_segments", "total_words", "status_text")
    FUNCTION = "build"

    @staticmethod
    def _parse_srt_timestamp(value):
        text = str(value or "").strip().replace(",", ".")
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError(f"Invalid SRT timestamp: {value}")
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        return hours * 3600.0 + minutes * 60.0 + seconds

    @classmethod
    def _word_segments_from_timed_segments(cls, timed_segments):
        segments = []
        for seg in timed_segments or []:
            text = str(seg.get("text") or seg.get("lyric") or seg.get("word") or "").strip()
            if not text:
                continue
            start = seg.get("start")
            end = seg.get("end")
            if start is None or end is None:
                continue
            try:
                start = float(start)
                end = float(end)
            except Exception:
                continue
            if end <= start:
                continue
            words = [cls._clean_word(word) for word in text.split()]
            words = [word for word in words if word]
            if not words:
                continue
            weights = [max(len(word), 1) for word in words]
            total_weight = float(sum(weights))
            cursor = start
            for idx, word in enumerate(words):
                if idx == len(words) - 1:
                    next_cursor = end
                else:
                    next_cursor = cursor + ((end - start) * (weights[idx] / total_weight))
                segments.append({"word": word, "start": round(cursor, 6), "end": round(next_cursor, 6)})
                cursor = next_cursor
        return segments

    @classmethod
    def _word_segments_from_srt_text(cls, srt_text):
        raw_text = str(srt_text or "").strip()
        if not raw_text:
            return []

        segments = []
        blocks = re.split(r"\n\s*\n", raw_text.replace("\r\n", "\n"))
        for block in blocks:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            if "-->" not in block:
                continue

            time_line_index = 0
            if "-->" not in lines[0] and len(lines) > 1:
                time_line_index = 1
            if "-->" not in lines[time_line_index]:
                continue

            try:
                start_text, end_text = [part.strip() for part in lines[time_line_index].split("-->", 1)]
                start = cls._parse_srt_timestamp(start_text)
                end = cls._parse_srt_timestamp(end_text)
            except Exception:
                continue

            caption_text = " ".join(lines[time_line_index + 1 :]).strip()
            if end <= start or not caption_text:
                continue

            words = [cls._clean_word(word) for word in caption_text.split()]
            words = [word for word in words if word]
            if not words:
                continue

            weights = [max(len(word), 1) for word in words]
            total_weight = float(sum(weights))
            cursor = start
            for idx, word in enumerate(words):
                if idx == len(words) - 1:
                    next_cursor = end
                else:
                    next_cursor = cursor + ((end - start) * (weights[idx] / total_weight))
                segments.append({"word": word, "start": round(cursor, 6), "end": round(next_cursor, 6)})
                cursor = next_cursor

        return segments

    @staticmethod
    def _load_srt_text_from_path(srt_path):
        path = str(srt_path or "").strip()
        if not path:
            return ""
        with open(path, "r", encoding="utf-8-sig") as handle:
            return handle.read()

    @staticmethod
    def _normalize_segments(segments):
        normalized = []
        for seg in segments or []:
            word = str(seg.get("word") or seg.get("text") or "").strip()
            if not word:
                continue
            try:
                start = float(seg.get("start"))
                end = float(seg.get("end"))
            except Exception:
                continue
            if end <= start:
                continue
            normalized.append({"word": word, "start": round(start, 6), "end": round(end, 6)})
        return sorted(normalized, key=lambda item: (item["start"], item["end"], item["word"]))

    @classmethod
    def _segments_from_json_text(cls, segments_json_text):
        raw = str(segments_json_text or "").strip()
        if not raw:
            return []

        def _segments_from_duration_map(payload):
            duration_keys = [
                key for key in payload.keys() if re.match(r"segment\d+_Duration_[0-9.]+$", str(key), re.I)
            ]
            if not duration_keys:
                return []

            def _segment_sort_key(key):
                match = re.match(r"segment(\d+)_Duration_([0-9.]+)$", str(key), re.I)
                if not match:
                    return (10**9, 0.0)
                return (int(match.group(1)), float(match.group(2)))

            segments = []
            cursor = 0.0
            for key in sorted(duration_keys, key=_segment_sort_key):
                match = re.match(r"segment(\d+)_Duration_([0-9.]+)$", str(key), re.I)
                if not match:
                    continue
                duration = float(match.group(2))
                text = str(payload.get(key) or "").strip()
                if not text or duration <= 0.0:
                    cursor += max(duration, 0.0)
                    continue
                cleaned_words = [cls._clean_word(word) for word in text.split()]
                cleaned_words = [word for word in cleaned_words if word]
                if not cleaned_words:
                    cursor += duration
                    continue
                weights = [max(len(word), 1) for word in cleaned_words]
                total_weight = float(sum(weights))
                local_cursor = cursor
                for idx, word in enumerate(cleaned_words):
                    if idx == len(cleaned_words) - 1:
                        next_cursor = cursor + duration
                    else:
                        next_cursor = local_cursor + (duration * (weights[idx] / total_weight))
                    segments.append(
                        {
                            "word": word,
                            "start": round(local_cursor, 6),
                            "end": round(next_cursor, 6),
                        }
                    )
                    local_cursor = next_cursor
                cursor += duration
            return cls._normalize_segments(segments)

        try:
            payload = json.loads(raw)
        except Exception:
            payload = {}
            for line in raw.splitlines():
                match = re.match(
                    r'\s*"?(segment\d+_Duration_[0-9.]+)"?\s*:\s*"(.*)"\s*,?\s*$',
                    line.strip(),
                    re.I,
                )
                if match:
                    payload[match.group(1)] = match.group(2)
            if payload:
                return _segments_from_duration_map(payload)
            return []

        if isinstance(payload, dict):
            if isinstance(payload.get("word_segments"), list):
                return cls._normalize_segments(payload.get("word_segments"))
            if isinstance(payload.get("timed_segments"), list):
                return cls._normalize_segments(cls._word_segments_from_timed_segments(payload.get("timed_segments")))
            if isinstance(payload.get("segments"), list):
                return cls._normalize_segments(cls._word_segments_from_timed_segments(payload.get("segments")))
            duration_segments = _segments_from_duration_map(payload)
            if duration_segments:
                return duration_segments

        if isinstance(payload, list):
            if payload and isinstance(payload[0], dict) and "word" in payload[0]:
                return cls._normalize_segments(payload)
            return cls._normalize_segments(cls._word_segments_from_timed_segments(payload))

        return []

    def build(self, debug=False, audio_meta=None, segments_json_text="", srt_text="", srt_path=""):
        audio_meta = audio_meta or {}
        try:
            source = "none"
            segments = []

            if isinstance(audio_meta, dict):
                segments = self._extract_word_segments(audio_meta)
                if segments:
                    source = "audio_meta.word_segments"
                else:
                    timed_segments = audio_meta.get("timed_segments") or []
                    segments = self._word_segments_from_timed_segments(timed_segments)
                    if segments:
                        source = "audio_meta.timed_segments"

            if not segments and str(segments_json_text or "").strip():
                segments = self._segments_from_json_text(segments_json_text)
                if segments:
                    source = "segments_json_text"

            if not segments and str(srt_text or "").strip():
                segments = self._word_segments_from_srt_text(srt_text)
                if segments:
                    source = "srt_text"

            if not segments and str(srt_path or "").strip():
                loaded_srt_text = self._load_srt_text_from_path(srt_path)
                segments = self._word_segments_from_srt_text(loaded_srt_text)
                if segments:
                    source = "srt_path"

            segments = self._normalize_segments(segments)
            payload = {"word_segments": segments, "source": source, "total_words": len(segments)}
            output_json = json.dumps(payload, indent=2, ensure_ascii=True)

            if debug:
                print(f"[PGFX Word Timing Json Builder] source={source} total_words={len(segments)}")

            if not segments:
                return (output_json, payload, 0, "No word timing data could be derived from audio_meta or SRT input.")

            return (output_json, payload, len(segments), f"Built {len(segments)} word timings from {source}.")
        except Exception as exc:
            if debug:
                traceback.print_exc()
            payload = {"word_segments": [], "source": "error", "total_words": 0}
            return (json.dumps(payload, indent=2, ensure_ascii=True), payload, 0, f"CRITICAL ERROR: {exc}")


# ------------------------------------------------------------------------------------
# PGFX_VisemeCondImagePrep Node — Bridge Viseme Rig → Sampler Conditioning
# ------------------------------------------------------------------------------------
class PGFX_VisemeCondImagePrep:
    DESCRIPTION = (
        "Bridges CinemaVisemeRig outputs into PGFX_LTXVInContextSampler.optional_cond_images. "
        "Takes the canny mouth-shape guides + lip mask and blends them onto a face template "
        "at subliminal strength. The sampler receives per-frame visual hints of the target "
        "mouth shape — no visible overlay, just latent-space guidance that corrects phoneme "
        "pronunciation in the generated video."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "canny_guides": ("IMAGE", {"tooltip": "Canny edge mouth shapes from CinemaVisemeRig.canny_guides. Shape [F, H, W, 3]."}),
                "lip_mask": ("MASK", {"tooltip": "Lip region mask from CinemaVisemeRig.lip_mask. Shape [F, H, W]."}),
                "mouth_influence": ("FLOAT", {"default": 0.15, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Blend strength of canny edges onto face. 0.1-0.2 is typically invisible but effective."}),
                "cond_strength": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Pass-through to sampler cond_image_strength. Controls how strongly conditioning influences generation."}),
                "frame_step": ("INT", {"default": 8, "min": 1, "max": 64, "step": 1, "tooltip": "Every Nth frame gets a conditioning image. Higher = less VRAM but coarser guidance. Use 4-16."}),
                "blend_mode": (["Lip Region Only", "Full Frame Soft", "Edges Only (Debug)"], {"default": "Lip Region Only"}),
            },
            "optional": {
                "face_template": ("IMAGE", {"tooltip": "Optional: A single reference face frame to blend mouth shapes onto. If omitted, a gray background is used."}),
                "cond_indices_override": ("STRING", {"multiline": False, "default": "", "tooltip": "Optional: Comma-separated frame indices. Overrides auto-computed step indices."}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING", "FLOAT")
    RETURN_NAMES = ("cond_images", "cond_indices", "cond_strength")
    FUNCTION = "prepare"
    CATEGORY = "☠️PGFX /Video"

    def prepare(self, canny_guides, lip_mask, mouth_influence, cond_strength, frame_step, blend_mode, face_template=None, cond_indices_override=""):
        try:
            B = canny_guides.shape[0]
            H = canny_guides.shape[1]
            W = canny_guides.shape[2]

            # Resolve face template: use corresponding frame per cond index
            if face_template is not None:
                tf = face_template
                tf_h, tf_w = tf.shape[1], tf.shape[2]
                if tf_h != H or tf_w != W:
                    tf = torch.nn.functional.interpolate(tf.permute(0, 3, 1, 2), size=(H, W), mode="bilinear").permute(0, 2, 3, 1)
                tf = tf.clamp(0, 1)
            else:
                tf = None

            # Determine frame indices
            if cond_indices_override.strip():
                parts = [p.strip() for p in cond_indices_override.split(",") if p.strip()]
                indices = sorted(set(int(p) for p in parts if p.isdigit()))
                indices = [i for i in indices if i < B]
            else:
                indices = list(range(0, B, frame_step))

            if not indices:
                indices = [0]

            # Prepare output images
            out_imgs = []
            for idx in indices:
                canny = canny_guides[idx:idx+1]  # [1, H, W, 3]
                mask = lip_mask[idx:idx+1]       # [1, H, W]
                if mask.dim() == 2:
                    mask = mask.unsqueeze(0)
                elif mask.dim() == 3 and mask.shape[0] != 1:
                    mask = mask[idx:idx+1]

                # Normalize mask to [0,1] float
                mask = mask.float()
                if mask.max() > 1.0:
                    mask = mask / 255.0
                mask = mask.clamp(0, 1)
                # Add channel dim for broadcasting: [1, H, W] -> [1, H, W, 1]
                mask = mask.unsqueeze(-1)

                # Pick face frame that best matches this cond index
                if tf is not None:
                    tf_idx = min(idx, tf.shape[0] - 1)
                    ref_frame = tf[tf_idx:tf_idx+1]
                else:
                    ref_frame = torch.ones(1, H, W, 3) * 0.5

                if blend_mode == "Edges Only (Debug)":
                    blended = canny
                elif blend_mode == "Full Frame Soft":
                    blended = ref_frame * (1 - mouth_influence) + canny * mouth_influence
                else:  # Lip Region Only
                    blended = ref_frame * (1 - mask * mouth_influence) + canny * (mask * mouth_influence)

                blended = blended.clamp(0, 1)
                out_imgs.append(blended)

            out_tensor = torch.cat(out_imgs, dim=0) if len(out_imgs) > 1 else out_imgs[0]
            out_indices = ",".join(str(i) for i in indices)

            return (out_tensor, out_indices, cond_strength)

        except Exception as e:
            print(f"\n*** [PGFX_VisemeCondImagePrep] ERROR: {e} ***\n")
            traceback.print_exc()
            dummy = torch.zeros(1, 64, 64, 3)
            return (dummy, "0", cond_strength)


NODE_CLASS_MAPPINGS = {
    "PGFX_CinemaVisemeRig": PGFX_CinemaVisemeRig,
    "PGFX_ScriptGuidedVisemes": PGFX_ScriptGuidedVisemes,
    "PGFX_UniversalVisemeGuides": PGFX_UniversalVisemeGuides,
    "PGFX_WordTimingJsonBuilder": PGFX_WordTimingJsonBuilder,
    "PGFX_VisemeCondImagePrep": PGFX_VisemeCondImagePrep,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_CinemaVisemeRig": "👄 Cinema Viseme Rig",
    "PGFX_ScriptGuidedVisemes": "👄 Script-Guided Visemes",
    "PGFX_UniversalVisemeGuides": "👄 Universal Viseme Guides",
    "PGFX_WordTimingJsonBuilder": "📝 Word Timing JSON Builder",
    "PGFX_VisemeCondImagePrep": "🎭 Viseme → Conditioning Bridge",
}
