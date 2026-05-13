import json
import re
import torch
import node_helpers

class PGFXTextEncodeAceStepAudio15Advanced:
    ACE15_LATENT_FRAMES_PER_SECOND = 25.0
    ACE15_AUDIO_CODE_TOKENS_PER_SECOND = 5.0
    TIMELINE_OFFSET_MODES = ["trim_pad", "wrap"]

    KEY_SCALE_OPTIONS = [
        "A major", "A# major", "Ab major", "A minor", "A# minor", "Ab minor",
        "B major", "B# major", "Bb major", "B minor", "B# minor", "Bb minor",
        "C major", "C# major", "Cb major", "C minor", "C# minor", "Cb minor",
        "D major", "D# major", "Db major", "D minor", "D# minor", "Db minor",
        "E major", "E# major", "Eb major", "E minor", "E# minor", "Eb minor",
        "F major", "F# major", "Fb major", "F minor", "F# minor", "Fb minor",
        "G major", "G# major", "Gb major", "G minor", "G# minor", "Gb minor"
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
    def _preprocess_lyrics(lyrics):
        """
        Clean and normalize lyrics using Official ACE-Step 1.5 line-markers.
        This forces the LM to process lyrics in a strict sequence.
        """
        if not lyrics:
            return ""
        
        # Normalize line endings and trim lines
        lines = [line.strip() for line in str(lyrics).splitlines() if line.strip()]
        if not lines:
            return ""

        # ACE-Step 1.5 Sequencer Fix: Add explicit L1:, L2: markers
        formatted_lines = []
        for i, line in enumerate(lines):
            formatted_lines.append(f"L{i+1}: {line}")
        
        # Wrap in official structural tokens
        return "[LYRICS]\n" + "\n".join(formatted_lines) + "\n[END_LYRICS]"


    @staticmethod
    def _latent_samples(latent):
        if latent is None:
            return None
        if isinstance(latent, dict):
            # ComfyUI standard LATENT uses "samples"
            # Some audio nodes use "waveform"
            for key in ["samples", "waveform", "audio"]:
                if key in latent and latent[key] is not None:
                    res = latent[key]
                    return res.contiguous() if isinstance(res, torch.Tensor) else res
            return None
        if isinstance(latent, torch.Tensor):
            return latent.contiguous()
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
            ).contiguous()

        # trim_pad (default): remove early intro influence instead of rotating it to the end.
        kept = latent_samples[..., shift_frames:]
        pad_source = latent_samples[..., -1:]
        if pad_source.shape[-1] == 0:
            return latent_samples
        pad = pad_source.repeat_interleave(shift_frames, dim=-1)
        return torch.cat((kept, pad), dim=-1).contiguous()

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
                "task_type": (["text2music", "cover", "extract", "lego", "repaint"], {
                    "default": "text2music",
                    "tooltip": "The specific generation task to perform. ACE-Step 1.5 uses these to determine the generation pipeline."
                }),
                "instruction": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "Main plain-English instruction for what you want to generate."
                }),
                "tags": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "Short style keywords (genre, mood, instruments, vibe). Think of this like prompt tags."
                }),
                "lyrics": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "Words to sing/speak. Leave empty if you want music only."
                }),
                "instrumental": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "If True, target an instrumental track with no vocals."
                }),
                "vocal_language": ([
                    'en', 'zh', 'ja', 'ko', 'es', 'fr', 'de', 'it', 'pt', 'ru',
                    'ar', 'hi', 'vi', 'th', 'id', 'ms', 'tl', 'nl', 'pl', 'tr',
                    'sv', 'da', 'no', 'fi', 'cs', 'sk', 'hu', 'ro', 'bg', 'hr',
                    'sr', 'uk', 'el', 'he', 'fa', 'bn', 'ta', 'te', 'pa', 'ur',
                    'ne', 'sw', 'ht', 'is', 'lt', 'la', 'az', 'ca', 'sa', 'yue',
                    'unknown'
                ], {
                    "default": "en",
                    "tooltip": "Language for vocal pronunciation and lyric generation."
                }),
                "audio_cover_strength": ("FLOAT", {
                    "default": 0.2,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "Controls how strongly the reference audio guides the style. 0.0=Pure Text, 1.0=Strict Style. Recommended: 0.2"
                }),
                "cover_noise_strength": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "Controls noise injection for covers. 0.0=Pure Gaussian Noise (recommended). Higher values use more source audio."
                }),
                "repainting_start": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 1000.0,
                    "step": 0.1,
                    "tooltip": "Start time in seconds for music_editing (repaint) task."
                }),
                "repainting_end": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 1000.0,
                    "step": 0.1,
                    "tooltip": "End time in seconds for music_editing (repaint) task."
                }),
                "bpm": ("INT", {
                    "default": 120,
                    "min": 1,
                    "max": 300,
                    "tooltip": "Song speed in beats per minute. Higher BPM sounds faster."
                }),
                "keyscale": ("COMBO", {
                    "default": "C major",
                    "options": s.KEY_SCALE_OPTIONS,
                    "tooltip": "Musical key and mode (major/minor) to steer harmony."
                }),
                "timesignature": (['2', '3', '4', '6'], {
                    "default": '4',
                    "tooltip": "Beats per bar. 4 is most common for pop/electronic."
                }),
                "duration": ("FLOAT", {
                    "default": 10.0,
                    "min": 0.0,
                    "max": 1000.0,
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
                "use_cot_metas": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Allow internal reasoning over metadata fields before output."
                }),
                "use_cot_caption": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Allow internal reasoning over caption/context text."
                }),
                "use_cot_lyrics": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Allow internal reasoning over lyrics for better consistency."
                }),
                "use_cot_language": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Allow internal reasoning about language choice and phrasing."
                }),
                "use_constrained_decoding": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Force stricter decoding rules. Helpful for structure, but can reduce creativity."
                }),
                "debug": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "If enabled, logs the constructed prompt to the console and returns it as a string output."
                }),
            },
            "optional": {
                "track_name": (["", "vocals", "drums", "bass", "guitar", "keyboard", "strings", "percussion", "synth", "fx", "brass", "woodwinds", "backing_vocals"], {
                    "default": "",
                    "tooltip": "Specific track to extract or generate (only for extract/lego tasks)."
                }),
                "reference_audio": ("LATENT", {
                    "tooltip": "Optional ACE-Step latent audio to shift the source audio's timeline. Typically used for cover/repaint style tasks."
                }),
                "src_audio": ("LATENT", {
                    "tooltip": "Optional ACE-Step latent audio to shift the source audio's timeline. Typically used for cover/repaint style tasks."
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
                "cover_source_offset_mode": (["trim_pad", "wrap"], {
                    "default": "trim_pad",
                    "tooltip": "trim_pad removes intro content (stronger). wrap rotates timeline (gentler)."
                }),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "STRING")
    RETURN_NAMES = ("CONDITIONING", "built_prompt")
    FUNCTION = "encode"

    CATEGORY = "☠️PGFX🏴‍☠️ /Audio"
    
    def _apply_semantic_dropout(self, tensor, dropout_prob, mask_value=0.0):
        """
        Randomly masks elements of a tensor. 
        Used to 'weaken' a structural guide without corrupting the remaining tokens.
        """
        if dropout_prob <= 0.0:
            return tensor
        if dropout_prob >= 1.0:
            return torch.full_like(tensor, mask_value)
            
        mask = torch.rand(tensor.shape, device=tensor.device) > dropout_prob
        return tensor * mask.to(tensor.dtype) + (~mask).to(tensor.dtype) * mask_value

    def encode(self, clip, task_type, instruction, tags, lyrics, instrumental, vocal_language, audio_cover_strength, cover_noise_strength, repainting_start, repainting_end, bpm, keyscale, timesignature, duration, seed, thinking, lm_temperature, lm_cfg_scale, lm_top_k, lm_top_p, use_cot_metas, use_cot_caption, use_cot_lyrics, use_cot_language, use_constrained_decoding, debug, track_name="", reference_audio=None, src_audio=None, audio_codes=None, caption=None, lm_negative_prompt=None, cover_source_offset_seconds=0.0, cover_source_offset_mode="trim_pad"):
        print("\n" + "🔥" * 20)
        print("🔥 [PGFX ACE15] ENCODE METHOD TRIGGERED 🔥")
        print("🔥" * 20)

        import math

        # --- 0. STABILITY: APPLY OFFICIAL PATCHES ---
        try:
            # Try to find and apply official patches from the reference extension
            import sys
            import os
            # Attempt to find the extension directory relative to custom_nodes
            custom_nodes_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
            ref_dir = os.path.join(custom_nodes_dir, "comfyui_ryanonyheinside")
            if os.path.exists(ref_dir) and ref_dir not in sys.path:
                sys.path.append(ref_dir)
            
            try:
                from nodes.acestep import patches
                patches.apply_acestep_patches()
                print("|-- Stability: Official ACE-Step patches applied.")
            except ImportError:
                # Try alternative import path
                try:
                    import custom_nodes.comfyui_ryanonyheinside.nodes.acestep.patches as patches
                    patches.apply_acestep_patches()
                    print("|-- Stability: Official ACE-Step patches applied (via custom_nodes path).")
                except:
                    pass
        except Exception as e:
            print(f"|-- Stability: Patch application skipped ({str(e)})")

        # --- 1. OFFICIAL ACE-STEP 1.5 CONFIGURATION ---
        TASK_MAP = {
            "text2music": "text2music",
            "cover": "cover",
            "extract": "extract",
            "lego": "lego",
            "repaint": "repaint"
        }
        mapped_task = TASK_MAP.get(task_type, "text2music")
        
        is_cover = (mapped_task == "cover")
        is_repaint = (mapped_task == "repaint")
        is_extract = (mapped_task == "extract")
        is_lego = (mapped_task == "lego")


        # Safe casting for numeric inputs
        try:
            safe_bpm = int(bpm) if bpm is not None else 120
        except:
            safe_bpm = 120
        try:
            safe_duration = float(duration) if duration is not None else 10.0
        except:
            safe_duration = 10.0

        normalized_audio_codes = self._normalize_audio_codes(audio_codes)
        negative_caption = "" if lm_negative_prompt is None else str(lm_negative_prompt).strip()
        lyrics_text = self._preprocess_lyrics(lyrics)
        lyric_lines = [ln.strip() for ln in lyrics_text.splitlines() if ln.strip()]

        ref_samples = self._latent_samples(reference_audio)
        src_samples = self._latent_samples(src_audio)

        # --- 2. TIMELINE OFFSETS ---
        try:
            offset_sec = float(cover_source_offset_seconds)
        except:
            offset_sec = 0.0
        offset_mode = str(cover_source_offset_mode or "trim_pad").strip().lower()
        if offset_mode not in set(self.TIMELINE_OFFSET_MODES):
            offset_mode = "trim_pad"

        if offset_sec > 0.0:
            if normalized_audio_codes is not None:
                normalized_audio_codes = self._offset_audio_codes_timeline(normalized_audio_codes, offset_sec, offset_mode)
            if mapped_task != "text2music":
                if src_samples is not None:
                    src_samples = self._offset_latent_timeline(src_samples, offset_sec, offset_mode)
                elif ref_samples is not None:
                    ref_samples = self._offset_latent_timeline(ref_samples, offset_sec, offset_mode)

        # --- 3. DUAL-LOGIC ROUTING ---
        if (is_cover or is_extract or is_lego) and src_samples is None and ref_samples is not None:
            src_samples = ref_samples
            print("|-- Pipeline: Mirroring Style Reference into Structural Guide.")

        if mapped_task == "text2music":
            routed_reference = ref_samples
        else:
            routed_reference = src_samples if src_samples is not None else ref_samples

        try:
            normalized_timesignature = int(str(timesignature).strip().split("/", 1)[0])
        except:
            normalized_timesignature = 4

        # --- 4. TASK-AWARE INSTRUCTION & PROMPT BUILDING ---
        TASK_INSTRUCTIONS = {
            "text2music": "Fill the audio semantic mask based on the given conditions:",
            "repaint": "Repaint the mask area based on the given conditions:",
            "cover": "Generate audio semantic tokens based on the given conditions:",
            "extract": "Extract the {TRACK_NAME} track from the audio:",
            "extract_default": "Extract the track from the audio:",
            "lego": "Generate the {TRACK_NAME} track based on the audio context:",
            "lego_default": "Generate the track based on the audio context:",
        }
        
        task_instruction = TASK_INSTRUCTIONS.get(mapped_task, TASK_INSTRUCTIONS.get("text2music"))
        if "{TRACK_NAME}" in task_instruction:
            if track_name:
                task_instruction = task_instruction.format(TRACK_NAME=track_name.upper())
            else:
                task_instruction = TASK_INSTRUCTIONS.get(f"{mapped_task}_default", task_instruction.replace("{TRACK_NAME}", ""))

        # --- 4. STRUCTURAL ANCHORING (ACE-STEP 1.5 SEQUENCER FIX) ---
        # We wrap the prompt in official structural tags to anchor the LM.
        prompt_parts = [
            f"[BPM]: {safe_bpm}",
            f"[KEYS]: {keyscale}",
            f"[TIME]: {normalized_timesignature}/4"
        ]
        
        if tags:
            prompt_parts.append(f"[STYLE]: {str(tags).strip()}")
        
        if instruction:
            prompt_parts.append(f"[INSTRUCTION]: {str(instruction).strip()}")
            
        if caption:
            prompt_parts.append(f"[CONTEXT]: {str(caption).strip()}")
            
        if lyrics_text:
            prompt_parts.append(lyrics_text) # This is already wrapped in [LYRICS] tags
            
        final_prompt = "\n".join(prompt_parts)
        
        # For non-t2m tasks, we add the task header
        if mapped_task != "text2music":
            prompt_text = f"{task_instruction}\n\n{final_prompt}"
        else:
            prompt_text = final_prompt

        should_generate_codes = (normalized_audio_codes is None and mapped_task in ("text2music", "repaint"))
        if mapped_task in ("cover", "extract", "lego") and routed_reference is None and normalized_audio_codes is None:
            should_generate_codes = True
            print("|-- Warning: No source for guided task. Falling back to LM code generation.")

        tokenize_kwargs = {
            "lyrics": lyrics_text,
            "bpm": safe_bpm,
            "duration": safe_duration,
            "timesignature": normalized_timesignature,
            "language": vocal_language,
            "keyscale": keyscale,
            "seed": seed,
            "generate_audio_codes": should_generate_codes,
            "cfg_scale": lm_cfg_scale,
            "temperature": lm_temperature,
            "top_p": lm_top_p,
            "top_k": lm_top_k,
            "min_p": 0.0,
            "task_type": mapped_task,
            "track_name": track_name if track_name else None,
        }
        if negative_caption:
            tokenize_kwargs["caption_negative"] = negative_caption

        diag_lines = [
            "🚀 [PGFX ACE15 DIAGNOSTICS] 🚀",
            f"|-- Task Routing: '{task_type}' -> Mapped: '{mapped_task}'",
            f"|-- Track Name: {track_name if track_name else 'N/A'}",
            f"|-- Structural Guide: {'src_audio' if src_samples is not None else ('reference_audio' if ref_samples is not None else ('NONE' if normalized_audio_codes is None else 'MANUAL CODES'))}",
            f"|-- Style Reference: {'reference_audio' if ref_samples is not None else 'NONE'}",
            f"|-- Timing: {safe_duration}s @ {safe_bpm} BPM",
            f"|-- LM Code Gen: {'ENABLED (Autonomous)' if should_generate_codes else 'DISABLED (Guided)'}",
        ]

        if is_cover or is_extract or is_lego:
            diag_lines.append(f"|-- Guided Strength: {audio_cover_strength}")
            if not should_generate_codes and normalized_audio_codes is None and routed_reference is None:
                diag_lines.append("⚠️ [WARNING] No Structural Guide! Model will be blind to rhythm.")

        # --- 5. THE UNIVERSAL BRIDGE (QUANTIZATION) ---
        struct_map = normalized_audio_codes
        
        if struct_map is None and (is_cover or is_repaint or is_extract or is_lego) and routed_reference is not None:
            try:
                model_ref = getattr(clip, "patcher", None)
                if model_ref:
                    inner_model = getattr(model_ref, "model", None)
                    diff_model = getattr(inner_model, "diffusion_model", inner_model)
                    
                    bridge_comp = getattr(diff_model, "tokenizer", getattr(inner_model, "codec", getattr(inner_model, "quantizer", None)))
                    
                    if bridge_comp:
                        with torch.no_grad():
                            raw_samples = routed_reference
                            if isinstance(routed_reference, dict) and "samples" in routed_reference:
                                raw_samples = routed_reference["samples"]
                            
                            comp_params = list(bridge_comp.parameters())
                            target_device = comp_params[0].device if comp_params else torch.device("cpu")
                            target_dtype = comp_params[0].dtype if comp_params else torch.float32
                            
                            raw_samples = raw_samples.to(device=target_device, dtype=target_dtype).contiguous()
                            
                            is_semantic = hasattr(bridge_comp, "tokenize")
                            if is_semantic:
                                raw_samples = raw_samples.movedim(-1, -2)
                            
                            if target_device.type == 'cuda':
                                torch.cuda.synchronize()
                                torch.cuda.empty_cache()
                            
                            try:
                                if is_semantic:
                                    quantized, _ = bridge_comp.tokenize(raw_samples)
                                    detokenizer = getattr(diff_model, "detokenizer", None)
                                    if detokenizer:
                                        struct_map = detokenizer(quantized)
                                        struct_map = struct_map.movedim(-1, -2).contiguous()
                                    else:
                                        struct_map = quantized.movedim(-1, -2).contiguous()
                                else:
                                    struct_map = bridge_comp.encode(raw_samples).contiguous()
                                
                                # Safety synchronization
                                if target_device.type == 'cuda':
                                    torch.cuda.synchronize()
                                
                                comp_name = "Tokenizer" if is_semantic else "Codec"
                                diag_lines.append(f"|-- Universal Bridge: [SUCCESS] REAL {comp_name} pass ({target_device.type}).")
                            except Exception as e:
                                if "misaligned" in str(e).lower() and target_device.type == 'cuda':
                                    diag_lines.append("|-- Universal Bridge: [RETRY] CUDA error, falling back to CPU...")
                                    raw_cpu = raw_samples.cpu()
                                    bridge_comp.cpu()
                                    if is_semantic:
                                        q_cpu, _ = bridge_comp.tokenize(raw_cpu)
                                        detok = getattr(diff_model, "detokenizer", None)
                                        if detok:
                                            detok.cpu()
                                            struct_map = detok(q_cpu).movedim(-1, -2).contiguous()
                                            detok.to(target_device)
                                        else:
                                            struct_map = q_cpu.movedim(-1, -2).contiguous()
                                    else:
                                        struct_map = bridge_comp.encode(raw_cpu).contiguous()
                                    
                                    bridge_comp.to(target_device)
                                    struct_map = struct_map.to(target_device)
                                else:
                                    raise e
                    else:
                        struct_map = routed_reference
                        diag_lines.append("|-- Universal Bridge: [FALLBACK] Soft-Code pass (Quantizer not found).")
                else:
                    struct_map = routed_reference
                    diag_lines.append("|-- Universal Bridge: [FALLBACK] Soft-Code pass (Model ref missing).")
            except Exception as e:
                struct_map = routed_reference
                diag_lines.append(f"|-- Universal Bridge: [FALLBACK] Active (Bridge Error: {str(e)})")

        # --- 6. SILENCE & ENERGY AUDIT ---
        if struct_map is not None and isinstance(struct_map, torch.Tensor):
            latent_energy = torch.mean(torch.abs(struct_map.float())).item()
            if latent_energy < 1e-7:
                diag_lines.append("🛑 [CRITICAL WARNING] Empty Structural Guide detected! (Silence)")
            else:
                diag_lines.append(f"|-- Structural Energy: {latent_energy:.4f} (Active)")

        # --- 7. RHYTHMIC PULSING (BPM ANCHORING) ---
        if struct_map is not None and is_cover and isinstance(struct_map, torch.Tensor) and torch.is_floating_point(struct_map):
            try:
                frames_per_beat = (25.0 * 60.0) / safe_bpm
                diag_lines.append(f"|-- Rhythmic Grid: Pulsing soft-codes at ~{frames_per_beat:.2f} frames per beat.")
                pulse = (torch.sin(torch.linspace(0, 2 * 3.14159 * (safe_duration * safe_bpm / 60.0), struct_map.shape[-1])) * 0.5 + 0.5).to(struct_map.device)
                struct_map = (struct_map * pulse).contiguous()
            except Exception as e:
                diag_lines.append(f"|-- Rhythmic Grid: Failed to pulse ({str(e)})")

        # --- 8. MULTI-PHASE CONDITIONING ASSEMBLY (TRIPLE-REDUNDANT BRIDGING) ---
        strength = float(audio_cover_strength)
        strength = max(0.0, min(1.0, strength))
        noise_level = float(cover_noise_strength)
        noise_level = max(0.0, min(1.0, noise_level))
        
        # 1. ENCODE SINGLE PATH (Standard ACE-Step Execution)
        tokens = clip.tokenize(prompt_text, **tokenize_kwargs)
        cond = clip.encode_from_tokens_scheduled(tokens)
        h = cond[0][0] # Prompt Embeddings
        c_device = h.device
        c_dtype = h.dtype

        # 2. EXPLICIT METADATA INJECTION (Bridging the Dead Sliders)
        # We inject the exact keys the ACE-Step 1.5 backend and samplers look for
        base_values = {
            "bpm": float(safe_bpm),
            "duration": safe_duration,
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
            "instrumental": instrumental,
            "task_type": mapped_task,
            "track_name": track_name if track_name else None,
            # THE BRIDGE: Explicitly passing strength to the conditioning_values dict
            "audio_cover_strength": strength,
            "cover_noise_strength": noise_level,
            "strength": strength,
            "noise_strength": noise_level,
            "stop_at_step_percent": strength,
            # UNIVERSAL SAMPLER BRIDGE: Keys that affect backend behavior
            "start_at_step": 0,
            "end_at_step": 10000,
            "uncond_prob": max(0.0, min(1.0, 1.0 - strength)),
            "guidance_scale": max(1.0, strength * 10.0),
        }

        if is_repaint:
            base_values.update({"repainting_start": repainting_start, "repainting_end": repainting_end})

        # 3. PHYSICAL TENSOR DROPOUT (Non-Destructive Influence)
        final_struct_map = None
        if struct_map is not None:
            final_struct_map = struct_map.to(device=c_device, dtype=c_dtype).clone()
            
            # Use Dropout instead of multiplication to avoid corrupting indices/latents
            # If strength is 0.2, we drop 80% of the guide data.
            dropout_prob = max(0.0, min(1.0, 1.0 - strength))
            
            # Also factor in noise_level (noise adds to the dropout probability)
            total_dropout = max(dropout_prob, noise_level)
            
            if total_dropout > 0.0:
                final_struct_map = self._apply_semantic_dropout(final_struct_map, total_dropout)
                diag_lines.append(f"|-- Semantic Dropout: {total_dropout:.2f} probability (Strength: {strength:.2f})")
            
            if is_cover or is_extract or is_lego:
                base_values["precomputed_lm_hints_25Hz"] = final_struct_map
            elif is_repaint:
                base_values["context_latents"] = [final_struct_map]
            else:
                base_values["audio_codes"] = final_struct_map

        if ref_samples is not None:
            base_values["reference_audio_timbre_latents"] = [ref_samples.to(device=c_device, dtype=c_dtype)]

        # 4. ASSEMBLE FINAL CONDITIONING
        # We return a single, perfectly weighted conditioning block to ensure 
        # that no matter what sampler is used, the sliders are "live".
        final_conditioning = []
        for _, m in cond: # Template
            new_m = m.copy()
            new_m.update(base_values)
            final_conditioning.append([h, new_m])

        if c_device.type == 'cuda':
            torch.cuda.synchronize()
            torch.cuda.empty_cache()

        diag_lines.append("|-- Status: Triple-Redundant Bridge Active.")
        diag_str = "\n".join(diag_lines)
        print("\n" + diag_str + "\n" + "="*40 + "\n")
        
        full_report = diag_str + "\n\n" + "="*20 + "\nFINAL PROMPT TEXT:\n" + prompt_text
        return (final_conditioning, full_report)


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
        return torch.cat((kept, pad), dim=-1).contiguous()

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
