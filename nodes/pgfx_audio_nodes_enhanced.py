
import json
import re
import torch
import node_helpers

class PGFXTextEncodeAceStepAudio15Advanced:
    ACE15_LATENT_FRAMES_PER_SECOND = 25.0
    ACE15_AUDIO_CODE_TOKENS_PER_SECOND = 5.0
    TIMELINE_OFFSET_MODES = ["trim_pad", "wrap"]

    KEY_SCALE_OPTIONS = [
        "C major", "C# major", "Db major", "D major", "D# major", "Eb major", "E major",
        "F major", "F# major", "Gb major", "G major", "G# major", "Ab major", "A major",
        "A# major", "Bb major", "B major", "C minor", "C# minor", "Db minor", "D minor",
        "D# minor", "Eb minor", "E minor", "F minor", "F# minor", "Gb minor", "G minor",
        "G# minor", "Ab minor", "A minor", "A# minor", "Bb minor", "B minor",
    ]

    @staticmethod
    def _normalize_audio_codes(audio_codes):
        """
        ACE-Step 1.5 expects numeric audio codes (typically [[int, int, ...]]).
        Return None for empty/invalid text so downstream code does not try
        torch.tensor("..."), which raises `invalid data type 'str'`.
        """
        if audio_codes is None:
            return None

        if isinstance(audio_codes, torch.Tensor):
            return audio_codes.detach().cpu().tolist()

        if isinstance(audio_codes, (list, tuple)):
            if not audio_codes:
                return None
            if all(not isinstance(x, (list, tuple)) for x in audio_codes):
                try:
                    return [[int(float(x)) for x in audio_codes]]
                except (TypeError, ValueError):
                    return None
            try:
                return [
                    [int(float(v)) for v in row]
                    for row in audio_codes
                    if isinstance(row, (list, tuple)) and len(row) > 0
                ] or None
            except (TypeError, ValueError):
                return None

        if isinstance(audio_codes, str):
            text = audio_codes.strip()
            if not text:
                return None

            parsed = None
            try:
                parsed = json.loads(text)
            except Exception:
                # Fallback: parse comma/space/newline-separated numbers.
                number_tokens = re.findall(r"-?\d+(?:\.\d+)?", text)
                if number_tokens:
                    parsed = [int(float(x)) for x in number_tokens]

            if parsed is None:
                return None

            return PGFXTextEncodeAceStepAudio15Advanced._normalize_audio_codes(parsed)

        return None

    @staticmethod
    def _build_prompt_text(tags, instruction, caption, has_lyrics=False, instrumental=False):
        """
        Build the main caption text while keeping lyrics separate for ACE15.
        """
        parts = []
        tags_text = str(tags or "").strip()
        instruction_text = str(instruction or "").strip()
        caption_text = str(caption or "").strip()

        if tags_text:
            parts.append(tags_text)
        if instruction_text:
            parts.append(f"Style direction: {instruction_text}")
        if caption_text:
            parts.append(caption_text)
        if has_lyrics and not instrumental:
            # Bias the LM toward earlier vocal onset without requiring explicit lyric markers.
            parts.append("Start vocals early and keep lyrics active through most of the track.")

        if not parts:
            return tags_text
        return "\n\n".join(parts)

    @staticmethod
    def _latent_samples(latent):
        if latent is None:
            return None
        if isinstance(latent, dict):
            return latent.get("samples", None)
        if isinstance(latent, torch.Tensor):
            return latent
        return None

    @classmethod
    def _offset_latent_timeline(cls, latent_samples, offset_seconds, offset_mode="trim_pad"):
        """
        Shift ACE 1.5 latent timeline left while keeping duration unchanged.
        - trim_pad: drop leading frames, pad tail with last frame
        - wrap: circular shift
        """
        if latent_samples is None or not isinstance(latent_samples, torch.Tensor):
            return latent_samples
        if latent_samples.ndim < 3 or latent_samples.shape[-1] <= 1:
            return latent_samples
        try:
            offset_seconds = float(offset_seconds)
        except Exception:
            return latent_samples
        if offset_seconds <= 0.0:
            return latent_samples

        shift_frames = int(round(offset_seconds * cls.ACE15_LATENT_FRAMES_PER_SECOND))
        if shift_frames <= 0:
            return latent_samples
        shift_frames = shift_frames % latent_samples.shape[-1]
        if shift_frames == 0:
            return latent_samples

        if str(offset_mode).strip().lower() == "wrap":
            return torch.cat(
                (latent_samples[..., shift_frames:], latent_samples[..., :shift_frames]),
                dim=-1,
            )

        # trim_pad (default): remove early intro influence instead of rotating it to the end.
        kept = latent_samples[..., shift_frames:]
        pad_source = latent_samples[..., -1:]
        if pad_source.shape[-1] == 0:
            return latent_samples
        pad = pad_source.repeat_interleave(shift_frames, dim=-1)
        return torch.cat((kept, pad), dim=-1)

    @classmethod
    def _offset_audio_codes_timeline(cls, audio_codes, offset_seconds, offset_mode="trim_pad"):
        """
        Shift ACE 1.5 audio-code timeline left while preserving sequence length.
        - trim_pad: drop leading tokens, pad tail with last token
        - wrap: circular shift
        """
        normalized = cls._normalize_audio_codes(audio_codes)
        if normalized is None:
            return None
        try:
            offset_seconds = float(offset_seconds)
        except Exception:
            return normalized
        if offset_seconds <= 0.0:
            return normalized

        shift_tokens = int(round(offset_seconds * cls.ACE15_AUDIO_CODE_TOKENS_PER_SECOND))
        if shift_tokens <= 0:
            return normalized

        shifted = []
        for row in normalized:
            if not isinstance(row, list) or len(row) <= 1:
                shifted.append(row)
                continue
            s = shift_tokens % len(row)
            if s == 0:
                shifted.append(row)
            elif str(offset_mode).strip().lower() == "wrap":
                shifted.append(row[s:] + row[:s])
            else:
                shifted.append(row[s:] + [row[-1]] * s)
        return shifted

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "clip": ("CLIP", {
                    "tooltip": "Connect the CLIP encoder from your loaded audio model. This is what reads your text."
                }),
                "task_type": ([
                    "text2music", "cover", "repaint", "extract", "lego", "complete"
                ], {
                    "tooltip": "ACE task mode. Cover-style tasks follow source latent structure when source/reference audio is connected."
                }),
                "instruction": ("STRING", {
                    "multiline": True,
                    "tooltip": "Main plain-English instruction for what you want to generate."
                }),
                "tags": ("STRING", {
                    "multiline": True,
                    "tooltip": "Short style keywords (genre, mood, instruments, vibe). Think of this like prompt tags."
                }),
                "lyrics": ("STRING", {
                    "multiline": True,
                    "tooltip": "Words to sing/speak. Leave empty if you want music only."
                }),
                "instrumental": ([False, True], {
                    "default": False,
                    "tooltip": "If True, target an instrumental track with no vocals."
                }),
                "vocal_language": (["en", "ja", "zh", "es", "de", "fr", "pt", "ru", "it", "nl", "pl", "tr", "vi", "cs", "fa", "id", "ko", "uk", "hu", "ar", "sv", "ro", "el"], {
                    "tooltip": "Language for vocal pronunciation and lyric generation."
                }),
                "bpm": ("INT", {
                    "default": 120,
                    "min": 10,
                    "max": 300,
                    "tooltip": "Song speed in beats per minute. Higher BPM sounds faster."
                }),
                "keyscale": ("COMBO", {
                    "default": "C major",
                    "options": s.KEY_SCALE_OPTIONS,
                    "tooltip": "Musical key and mode (major/minor) to steer harmony."
                }),
                "timesignature": (['2', '3', '4', '6'], {
                    "tooltip": "Beats per bar. 4 is most common for pop/electronic."
                }),
                "duration": ("FLOAT", {
                    "default": 10.0,
                    "min": 1.0,
                    "max": 300.0,
                    "step": 0.1,
                    "tooltip": "Target output length in seconds."
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 0xffffffffffffffff,
                    "tooltip": "Random starting value. Reuse the same seed + settings to reproduce similar results."
                }),
                "thinking": ([False, True], {
                    "default": True,
                    "tooltip": "Lets the language side plan more before decoding. Usually slower, sometimes smarter."
                }),
                "lm_temperature": ("FLOAT", {
                    "default": 0.70,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.01,
                    "tooltip": "Language creativity. Mainly affects LM-generated audio codes (typically text2music without source latent cover guidance)."
                }),
                "lm_cfg_scale": ("FLOAT", {
                    "default": 2.0,
                    "min": 0.0,
                    "max": 10.0,
                    "step": 0.1,
                    "tooltip": "How strongly LM-generated codes follow instructions. Limited effect in source-guided cover workflows."
                }),
                "lm_top_k": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 100,
                    "tooltip": "Top-K sampling for LM-generated codes. Limited effect in source-guided cover workflows."
                }),
                "lm_top_p": ("FLOAT", {
                    "default": 0.9,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "Top-P sampling for LM-generated codes. Limited effect in source-guided cover workflows."
                }),
                "use_cot_metas": ([False, True], {
                    "default": True,
                    "tooltip": "Allow internal reasoning over metadata fields before output."
                }),
                "use_cot_caption": ([False, True], {
                    "default": True,
                    "tooltip": "Allow internal reasoning over caption/context text."
                }),
                "use_cot_lyrics": ([False, True], {
                    "default": True,
                    "tooltip": "Allow internal reasoning over lyrics for better consistency."
                }),
                "use_cot_language": ([False, True], {
                    "default": True,
                    "tooltip": "Allow internal reasoning about language choice and phrasing."
                }),
                "use_constrained_decoding": ([False, True], {
                    "default": True,
                    "tooltip": "Force stricter decoding rules. Helpful for structure, but can reduce creativity."
                }),
            },
            "optional": {
                "reference_audio": ("LATENT", {
                    "tooltip": "Optional ACE audio LATENT reference (use VAEEncodeAudio first). Used for cover/repaint-style tasks."
                }),
                "src_audio": ("LATENT", {
                    "tooltip": "Optional ACE audio LATENT source (use VAEEncodeAudio first). Used by cover/repaint-style tasks."
                }),
                "audio_codes": ("STRING", {
                    "multiline": True,
                    "tooltip": "Optional advanced code list. Use JSON like [1,2,3] or [[1,2,3]]. Leave blank to auto-generate."
                }),
                "caption": ("STRING", {
                    "multiline": True,
                    "tooltip": "Optional plain-language description to reinforce your instruction."
                }),
                "lm_negative_prompt": ("STRING", {
                    "multiline": True,
                    "tooltip": "Tell the language model what to avoid (style, words, topics, tone)."
                }),
                "cover_source_offset_seconds": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 300.0,
                    "step": 0.1,
                    "tooltip": "Timeline shift in seconds. In cover-style tasks it shifts source latents; in text2music it shifts audio-code timeline."
                }),
                "cover_source_offset_mode": ("COMBO", {
                    "default": "trim_pad",
                    "options": s.TIMELINE_OFFSET_MODES,
                    "tooltip": "trim_pad removes intro content (stronger). wrap rotates timeline (gentler)."
                }),
            }
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "encode"

    CATEGORY = "☠️PGFX🏴‍☠️ /Audio"

    def encode(self, clip, task_type, instruction, tags, lyrics, instrumental, vocal_language, bpm, keyscale, timesignature, duration, seed, thinking, lm_temperature, lm_cfg_scale, lm_top_k, lm_top_p, use_cot_metas, use_cot_caption, use_cot_lyrics, use_cot_language, use_constrained_decoding, reference_audio=None, src_audio=None, audio_codes=None, caption=None, lm_negative_prompt=None, cover_source_offset_seconds=0.0, cover_source_offset_mode="trim_pad"):
        normalized_audio_codes = self._normalize_audio_codes(audio_codes)
        negative_caption = "" if lm_negative_prompt is None else str(lm_negative_prompt).strip()
        lyrics_text = "" if lyrics is None else str(lyrics)
        lyric_lines = [ln.strip() for ln in lyrics_text.splitlines() if ln.strip()]
        task_mode_raw = str(task_type or "text2music").strip().lower()
        allowed_task_modes = {"text2music", "cover", "repaint", "extract", "lego", "complete"}
        task_mode = task_mode_raw if task_mode_raw in allowed_task_modes else "text2music"
        ref_samples = self._latent_samples(reference_audio)
        src_samples = self._latent_samples(src_audio)

        try:
            cover_source_offset_seconds = float(cover_source_offset_seconds)
        except Exception:
            cover_source_offset_seconds = 0.0
        offset_mode = str(cover_source_offset_mode or "trim_pad").strip().lower()
        if offset_mode not in set(self.TIMELINE_OFFSET_MODES):
            offset_mode = "trim_pad"

        if cover_source_offset_seconds > 0.0 and normalized_audio_codes is not None:
            normalized_audio_codes = self._offset_audio_codes_timeline(
                normalized_audio_codes, cover_source_offset_seconds, offset_mode
            )
            print(
                f"[PGFX ACE15] applied audio-code offset: {cover_source_offset_seconds:.2f}s "
                f"({int(round(cover_source_offset_seconds * self.ACE15_AUDIO_CODE_TOKENS_PER_SECOND))} tokens), "
                f"mode={offset_mode}, task={task_mode}"
            )

        if task_mode != "text2music" and cover_source_offset_seconds > 0.0:
            if src_samples is not None:
                src_samples = self._offset_latent_timeline(src_samples, cover_source_offset_seconds, offset_mode)
                print(
                    f"[PGFX ACE15] applied source-latent offset: {cover_source_offset_seconds:.2f}s "
                    f"({int(round(cover_source_offset_seconds * self.ACE15_LATENT_FRAMES_PER_SECOND))} frames), "
                    f"mode={offset_mode}, task={task_mode}, source=src_audio"
                )
            elif ref_samples is not None:
                ref_samples = self._offset_latent_timeline(ref_samples, cover_source_offset_seconds, offset_mode)
                print(
                    f"[PGFX ACE15] applied source-latent offset: {cover_source_offset_seconds:.2f}s "
                    f"({int(round(cover_source_offset_seconds * self.ACE15_LATENT_FRAMES_PER_SECOND))} frames), "
                    f"mode={offset_mode}, task={task_mode}, source=reference_audio"
                )

        # Route task-specific source/reference behavior to the key Comfy ACE consumes.
        if task_mode == "text2music":
            # In Comfy's ACE backend, providing reference_audio_timbre_latents flips to cover mode.
            # Keep text2music LM-driven to avoid silent/near-silent cover behavior.
            routed_reference = None
        else:
            routed_reference = src_samples if src_samples is not None else ref_samples

        try:
            normalized_timesignature = int(str(timesignature).strip().split("/", 1)[0])
        except Exception:
            normalized_timesignature = 4

        # Build caption text from tags/instruction/caption while passing lyrics separately.
        prompt_text = self._build_prompt_text(
            tags=tags,
            instruction=instruction,
            caption=caption,
            has_lyrics=bool(lyric_lines),
            instrumental=bool(instrumental),
        )

        tokenize_kwargs = {
            # Keep this aligned with ComfyUI's native TextEncodeAceStepAudio1.5 call.
            "lyrics": lyrics_text,
            "bpm": bpm,
            "duration": duration,
            "timesignature": normalized_timesignature,
            "language": vocal_language,
            "keyscale": keyscale,
            "seed": seed,
            "task_type": task_mode,
            "generate_audio_codes": (normalized_audio_codes is None and routed_reference is None),
            "cfg_scale": lm_cfg_scale,
            "temperature": lm_temperature,
            "top_p": lm_top_p,
            "top_k": lm_top_k,
            "min_p": 0.0,
        }
        if negative_caption:
            tokenize_kwargs["caption_negative"] = negative_caption
        tokens = clip.tokenize(prompt_text, **tokenize_kwargs)

        conditioning = clip.encode_from_tokens_scheduled(tokens)

        conditioning_values = {
            "thinking": thinking,
            "lm_temperature": lm_temperature,
            "lm_cfg_scale": lm_cfg_scale,
            "lm_top_k": lm_top_k,
            "lm_top_p": lm_top_p,
            "use_cot_metas": use_cot_metas,
            "use_cot_caption": use_cot_caption,
            "use_cot_lyrics": use_cot_lyrics,
            "use_cot_language": use_cot_language,
            "use_constrained_decoding": use_constrained_decoding,
            "task_type": task_type,
            "instrumental": instrumental,
        }
        if routed_reference is not None:
            conditioning_values["reference_audio_timbre_latents"] = [routed_reference]
        if normalized_audio_codes is not None and routed_reference is None:
            conditioning_values["audio_codes"] = normalized_audio_codes
        conditioning = node_helpers.conditioning_set_values(conditioning, conditioning_values)
        
        return (conditioning,)


class PGFXAceStep15LatentTimelineOffset:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "latent": ("LATENT", {
                    "tooltip": "ACE-Step latent audio to offset before feeding a cover guider."
                }),
                "offset_seconds": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 300.0,
                    "step": 0.1,
                    "tooltip": "How much to shift the latent timeline to the left."
                }),
                "offset_mode": ("COMBO", {
                    "default": "trim_pad",
                    "options": PGFXTextEncodeAceStepAudio15Advanced.TIMELINE_OFFSET_MODES,
                    "tooltip": "trim_pad removes intro content; wrap rotates timeline."
                }),
                "latent_fps": ("FLOAT", {
                    "default": 25.0,
                    "min": 1.0,
                    "max": 200.0,
                    "step": 0.1,
                    "tooltip": "ACE-Step 1.5 latent rate is 25 fps."
                }),
            }
        }

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "offset"
    CATEGORY = "☠️PGFX🏴‍☠️ /Audio"

    @staticmethod
    def _shift_samples(samples, offset_seconds, offset_mode, latent_fps):
        if not isinstance(samples, torch.Tensor):
            return samples
        if samples.ndim < 3 or samples.shape[-1] <= 1:
            return samples

        try:
            seconds = float(offset_seconds)
            fps = float(latent_fps)
        except Exception:
            return samples

        if seconds <= 0.0 or fps <= 0.0:
            return samples

        shift_frames = int(round(seconds * fps))
        if shift_frames <= 0:
            return samples

        total = samples.shape[-1]
        shift_frames = shift_frames % total
        if shift_frames == 0:
            return samples

        mode = str(offset_mode or "trim_pad").strip().lower()
        if mode == "wrap":
            return torch.cat((samples[..., shift_frames:], samples[..., :shift_frames]), dim=-1)

        kept = samples[..., shift_frames:]
        pad_source = samples[..., -1:]
        if pad_source.shape[-1] == 0:
            return samples
        pad = pad_source.repeat_interleave(shift_frames, dim=-1)
        return torch.cat((kept, pad), dim=-1)

    def offset(self, latent, offset_seconds, offset_mode, latent_fps):
        if not isinstance(latent, dict):
            return (latent,)

        samples = latent.get("samples", None)
        shifted = self._shift_samples(samples, offset_seconds, offset_mode, latent_fps)
        if shifted is samples:
            return (latent,)

        shift_frames = int(round(float(offset_seconds) * float(latent_fps)))
        print(
            f"[PGFX ACE15] latent guider offset applied: {float(offset_seconds):.2f}s "
            f"({shift_frames} frames @ {float(latent_fps):.2f}fps), mode={str(offset_mode)}"
        )

        out = dict(latent)
        out["samples"] = shifted
        return (out,)

NODE_CLASS_MAPPINGS = {
    "PGFXTextEncodeAceStepAudio15Advanced": PGFXTextEncodeAceStepAudio15Advanced,
    "PGFXAceStep15LatentTimelineOffset": PGFXAceStep15LatentTimelineOffset,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFXTextEncodeAceStepAudio15Advanced": "Text Encode Ace Step Audio 1.5 (PGFX Advanced)",
    "PGFXAceStep15LatentTimelineOffset": "ACE-Step 1.5 Latent Timeline Offset (PGFX)",
}
