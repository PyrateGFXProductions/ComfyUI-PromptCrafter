import textwrap
import concurrent.futures
import os
import re
import collections
import json
from typing import Tuple, Any, List, Optional, Dict

import torch
from PIL import Image

from . import pgfx_api_clients as api_clients
from . import pgfx_config as config
from ..utils import pgfx_utils as utils
from ..utils import pgfx_json_utils as json_utils

# --- NEW: CONCURRENCY CONTROL ---
# Setting this to 1 or 2 is vital for stability and efficiency when calling local LLMs (like Ollama)
# with a lot of complex requests. This prevents server overload and timeouts.
MAX_CONCURRENT_LLM_CALLS = 1

def _get_file_hash(filepath, block_size=65536):
    """Generates an SHA256 hash for the content of a given file."""
    import hashlib
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as f:
        buf = f.read(block_size)
        while len(buf) > 0:
            hasher.update(buf)
            buf = f.read(block_size)
    return hasher.hexdigest()

class ThoughtProcess:
    """
    Simulates a multi-lobe thinking process for generating creative prompts.
    This class orchestrates different "lobes" (specialized functions) 
    to handle analysis, creative drafting, and refinement.
    """
    def __init__(self, run_config, user_text, negative_prompt, mode, image_context, primary_subjects_from_images, **kwargs):
        self.run_config = run_config
        self.user_text = user_text
        self.negative_prompt = negative_prompt
        self.mode = mode
        self.artistry_level = kwargs.get('artistry_level', 5)
        self.creativity_level = kwargs.get('creativity_level', 5)
        self.logicality_level = kwargs.get('logicality_level', 5)

        # Pop image_weights_json to handle them explicitly and prevent conflicts
        image_weights_json = kwargs.pop('image_weights_json', '{}')
        image_count = kwargs.get('image_count', 1)

        self.kwargs = kwargs

        # Pop all mode-specific kwargs to avoid polluting the main kwargs
        self.qna_instruction = kwargs.pop('qna_instruction', None)
        self.qna_subject = kwargs.pop('qna_subject', None)
        self.qna_image = kwargs.pop('qna_image', None)
        self.qna_history_in = kwargs.pop('qna_history_in', "")
        self.qna_clear_history = kwargs.pop('qna_clear_history', False)
        self.qna_folder_path = kwargs.pop('qna_folder_path', None)
        self.qna_file_name = kwargs.pop('qna_file_name', "<none>")
        self.qna_enable_web_search = kwargs.pop('qna_enable_web_search', True)
        self.qna_fast_web_search = kwargs.pop('qna_fast_web_search', True)
        self.qna_summarization_strategy = kwargs.pop('qna_summarization_strategy', "Default (Abstractive)")
        self.qna_chunk_large_context = kwargs.pop('qna_chunk_large_context', True)
        self.qna_chunk_size_words = kwargs.pop('qna_chunk_size_words', 2000)
        self.qna_safe_mode = kwargs.pop('qna_safe_mode', True)
        self.qna_auto_select_model = kwargs.pop('qna_auto_select_model', True)

        self.lyrics_audio_file = kwargs.pop('lyrics_audio_file', "<none>")
        self.lyrics_lyrics_file = kwargs.pop('lyrics_lyrics_file', "<none>")
        self.lyrics_audio_folder_path = kwargs.pop('lyrics_audio_folder_path', "input/audio")
        self.lyrics_lyrics_folder_path = kwargs.pop('lyrics_lyrics_folder_path', "input/lyrics")
        self.lyrics_use_audio_alignment = kwargs.pop('lyrics_use_audio_alignment', True)
        self.lyrics_song_length_seconds = kwargs.pop('lyrics_song_length_seconds', 0.0)
        self.lyrics_fps = kwargs.pop('lyrics_fps', 16.0)
        self.lyrics_scene_splitting_mode = kwargs.pop('lyrics_scene_splitting_mode', "Structural Tag")
        self.lyrics_max_scene_duration_seconds = kwargs.pop('lyrics_max_scene_duration_seconds', 5.0)
        self.lyrics_max_scene_frames = kwargs.pop('lyrics_max_scene_frames', 120)
        self.lyrics_whisper_model_size = kwargs.pop('lyrics_whisper_model_size', "large-v3")
        self.lyrics_whisper_language = kwargs.pop('lyrics_whisper_language', "auto-detect")
        self.lyrics_whisper_engine = kwargs.pop('lyrics_whisper_engine', "faster-whisper")
        self.lyrics_use_vrg_prompt_builder = kwargs.pop('lyrics_use_vrg_prompt_builder', False)
        self.lyrics_automate_vrg_variables = kwargs.pop('lyrics_automate_vrg_variables', False)
        self.lyrics_character_description = kwargs.pop('lyrics_character_description', "The Women.")
        self.lyrics_song_theme_style = kwargs.pop('lyrics_song_theme_style', "cinematic realism, emotional storytelling, soft surrealism, naturalistic tone, dreamlike nostalgia, modern drama, poetic symbolism, intimate atmosphere")
        self.lyrics_word_count_min = kwargs.pop('lyrics_word_count_min', 30)
        self.lyrics_word_count_max = kwargs.pop('lyrics_word_count_max', 50)
        self.lyrics_list_handling_mode = kwargs.pop('lyrics_list_handling_mode', "Reference Guide (LLM creates variations inspired by list)")
        self.lyrics_environment = kwargs.pop('lyrics_environment', "open field at dusk, dimly lit bedroom, empty city street at night, forest clearing with morning fog, seaside cliff at golden hour, rainy urban alley, sunlit living room, desert road at sunrise")
        self.lyrics_lighting = kwargs.pop('lyrics_lighting', "warm amber glow, cool window light, neon reflections, diffused morning light, soft backlight haze, flickering streetlights, gentle afternoon sun, pink-orange dawn light")
        self.lyrics_camera_motion = kwargs.pop('lyrics_camera_motion', "push in, pull back, pan left, pan right, tilt up, tilt down, track forward, orbit")
        self.lyrics_physical_interaction = kwargs.pop('lyrics_physical_interaction', "walking through tall grass, lying on bed staring upward, leaning against a wall in stillness, reaching toward sunlight, hair moving in wind, footsteps in puddles, brushing hand across furniture, standing motionless in breeze")
        self.lyrics_facial_expression = kwargs.pop('lyrics_facial_expression', "Intense raw emotion")
        self.lyrics_shots = kwargs.pop('lyrics_shots', "close up, medium shot, wide shot, over the shoulder, establishing shot, low angle, high angle, overhead shot")
        self.lyrics_outfit_rules = kwargs.pop('lyrics_outfit_rules', "a white dress")
        self.lyrics_character_visibility = kwargs.pop('lyrics_character_visibility', "mostly visible, half-shadowed, silhouetted, reflected or obscured, seen from behind, partially out of frame, emerging from light, fading into darkness")
        self.lyrics_generate_schedule = kwargs.pop('lyrics_generate_schedule', True)
        self.lyrics_interpolate_keyframes = kwargs.pop('lyrics_interpolate_keyframes', False)
        self.lyrics_interpolation_frame_interval = kwargs.pop('lyrics_interpolation_frame_interval', 0)
        self.lyrics_target_model_format = kwargs.pop('lyrics_target_model_format', "LTX-2 (Audio/Lip Sync/Retake)")

        # The nodes now handle image collection and description, so we just store the results.
        self.images_with_weights = self._collect_images_with_weights(image_count, image_weights_json)

        self.state = {
            "user_text": user_text,
            "user_instructions": user_text,
            "user_context": "",
            "image_context": image_context,
            "primary_subjects_from_images": primary_subjects_from_images,
            "all_primary_subjects": [],
            "mandatory_tokens": {},
            "draft_prompt": "",
            "style_rules": "",
            "final_prompt": "",
            "negative_prompt": negative_prompt,
            "qna_response": "",
            "qna_history_out": "",
            "lyrics_prompt": "",
            "lyrics_schedule": "",
            "lyrics_image_context": "",
            "lyrics_negative_prompt": "",
            "lyrics_clean_lyrics_txt": "",
            "lyrics_lyrics_srt": "",
            "lyrics_model_out": "",
            "lyrics_seed_out": "",
            "lyrics_audio_meta": {},
            "lyrics_spectrogram_preview": None,
            "lyrics_signal": None,
            "lyrics_auto_character": "",
            "lyrics_auto_theme": "",
            "lyrics_auto_environment": "",
            "lyrics_auto_lighting": "",
            "lyrics_auto_interaction": "",
            "lyrics_auto_expression": "",
            "lyrics_auto_shots": "",
            "lyrics_auto_outfit": "",
            "lyrics_auto_visibility": "",
        }

    def _llm_runtime_kwargs(self):
        return {
            "llm_device": getattr(self.run_config, "llm_device", getattr(config, "DEFAULT_LLM_DEVICE", "Default (GPU)")),
            "reset_context": bool(getattr(self.run_config, "reset_context", getattr(config, "DEFAULT_LLM_STATELESS", True))),
        }

    def _is_reasoning_model(self, model_name):
        """Detects if the model is a specialized reasoning model (like DeepSeek-R1)."""
        reasoning_keywords = ["deepseek-r1", "reasoning", "thought", "thinking", "o1-", "o3-"]
        return any(kw in str(model_name).lower() for kw in reasoning_keywords)

    def _wrap_reasoning_prompt(self, prompt, model_name):
        """Wraps the prompt in a thought trigger for reasoning models."""
        if self._is_reasoning_model(model_name):
            return textwrap.dedent(f"""
                <thought>
                Identify the specific PGFX node context. Analyze the visual and narrative constraints. 
                Ensure the output matches the requested schema exactly.
                </thought>
                {prompt}
            """).strip()
        return prompt

    def _query_model(self, model, prompt, images=None, **kwargs):
        llm_kwargs = self._llm_runtime_kwargs()
        llm_kwargs.update(kwargs)
        wrapped_prompt = self._wrap_reasoning_prompt(prompt, model)
        return api_clients.query_model_auto(model, wrapped_prompt, images=images, **llm_kwargs)

    def _reason_with_model(self, model, prompt, images=None, **kwargs):
        llm_kwargs = self._llm_runtime_kwargs()
        llm_kwargs.update(kwargs)
        wrapped_prompt = self._wrap_reasoning_prompt(prompt, model)
        return api_clients._reason_with_model(model, wrapped_prompt, images=images, **llm_kwargs)

    def _collect_images_with_weights(self, image_count=1, image_weights_json="{}"):
        """Collects all connected image tensors and their weights from the dynamic inputs."""
        images_with_weights = []
        weights = {}
        try:
            parsed_weights = json_utils.extract_and_parse_json(image_weights_json)
            if isinstance(parsed_weights, dict):
                weights = parsed_weights
        except Exception:
            print(f"\033[93m[PromptCrafter] Warning: Could not parse image_weights_json. Using default weights. Value: {image_weights_json}\033[0m")

        for i in range(1, image_count + 1):
            image = self.kwargs.get(f"image_{i}")
            if image is not None:
                weight = float(weights.get(f"image_weight_{i}", 1.0))
                images_with_weights.append((image, weight))
        return images_with_weights

    def run(self) -> "Tuple[Any, ...]":
        """
        The Project Manager.
        Receives the client brief and delegates to the correct department.
        """
        print(f"\033[95m[PromptCrafter-Orchestrator] Brief received. Assembling team for '{self.mode}' mode.\033[0m")
        
        if self.mode == "QnA":
            return self._run_qna_chain_of_command()
        
        elif self.mode == "Lyrics":
            return self._run_lyrics_chain_of_command()
        
        else: 
            return self._run_visual_chain_of_command()

    def _run_visual_chain_of_command(self):
        """
        [Team Lead: Studio Director]
        Manages the workflow for creating a cinematic image or video prompt.
        """
        print("\033[95m[PromptCrafter-Studio] Workflow initiated...\033[0m")

        brief, error_msg = self._visual_agent_analyze_brief()
        if error_msg:
            return (error_msg, None, "")
        
        if brief:
            self.state.update(brief)

        # --- OPTIMIZATION: Run draft writing and style rule generation in parallel ---
        print("\033[94m[PromptCrafter-Studio] Beginning parallel processing for draft and style rules...\033[0m")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            # Submit draft writing agent
            draft_future = executor.submit(self._visual_agent_write_draft)
            
            # Submit style rule generation
            images = [img for img, _ in self.images_with_weights]
            style_rules_future = executor.submit(
                self._build_style_and_composition_rules,
                self.mode, images, self.run_config, self.state["user_text"] or "",
                "", str(self.state["image_context"]), self.artistry_level
            )

            # Wait for draft to complete
            print("\033[94m[PromptCrafter-Studio] Waiting for creative draft...\033[0m")
            draft, error_msg = draft_future.result()
            if error_msg:
                # Ensure the other future is cancelled if one fails
                style_rules_future.cancel()
                return (error_msg, self.state["image_context"], "")
            self.state["draft_prompt"] = draft
            print("\033[92m[PromptCrafter-Studio] Creative draft completed.\033[0m")

            # Wait for style rules to complete
            print("\033[94m[PromptCrafter-Studio] Waiting for style rules...\033[0m")
            style_rules = style_rules_future.result()
            print("\033[92m[PromptCrafter-Studio] Style rules completed.\033[0m")

        styled_prompt = self._visual_agent_apply_style(style_rules)
        self.state["final_prompt"] = styled_prompt

        final_prompt, negative_prompt = self._visual_agent_finalize_and_clean()
        
        self.state["final_prompt"] = final_prompt
        self.state["negative_prompt"] = negative_prompt

        print("\033[95m[PromptCrafter-Studio] Visual prompt complete.\033[0m")
        return self.state["final_prompt"], self.state["image_context"], self.state["negative_prompt"]

    def _run_qna_chain_of_command(self):
        """
        [Team Lead: Lead Researcher]
        Manages the workflow for answering a user's question.
        """
        print("\033[95m[PromptCrafter-Research] Workflow initiated...\033[0m")
        try:
            llm_model = self._qna_agent_triage_request()

            context, raw_context, context_source = self._qna_agent_gather_context()

            # Elite Optimization: Summarize history if it exceeds 75% of a safe window (approx 1500 words)
            current_history = self.qna_history_in.strip() if self.qna_history_in and not self.qna_clear_history else ""
            if len(current_history.split()) > 1500:
                print(f"\033[94m[QnA-Agent] History is long ({len(current_history.split())} words). Summarizing for context efficiency...\033[0m")
                summary_prompt = textwrap.dedent(f"""
                    Summarize the following conversation history into a concise "State Summary". 
                    Capture key subjects, previous decisions, and the current narrative state.
                    Keep it under 400 words.

                    CONVERSATION HISTORY:
                    {current_history}
                """).strip()
                ok, summary = self._query_model(llm_model, summary_prompt, temperature=0.3)
                if ok:
                    current_history = f"[PREVIOUS CONVERSATION SUMMARY]:\n{summary}\n"
                    print("\033[92m[QnA-Agent] History successfully condensed.\033[0m")

            briefing_context = self._qna_agent_summarize_context(
                context, raw_context, context_source, llm_model
            )
            summarized_query = self._qna_agent_summarize_query(llm_model)

            response_text, updated_history = self._qna_agent_formulate_answer(
                llm_model, briefing_context, summarized_query, history_override=current_history
            )

            self.state["qna_response"] = response_text
            self.state["qna_history_out"] = updated_history
            print("\033[95m[PromptCrafter-Research] QnA response complete.\033[0m")
            return response_text, updated_history

        except Exception as e:
            print(f"\033[91m[PromptCrafter-Research] Error in QnA chain: {e}\033[0m")
            import traceback
            traceback.print_exc()
            return f"An error occurred: {e}", self.state.get("qna_history_out", "")
    def _run_lyrics_chain_of_command(self):
        """
        [Team Lead: Executive Producer]
        Manages the audio and creative departments to produce a music video schedule.
        """
        print("\033[95m[PromptCrafter-MusicVideo] Workflow initiated...\033[0m")
        try:
            print("\033[95m[MusicVideo-AudioDept] Starting audio processing...\033[0m")
            audio_path, song_length_seconds = self._lyrics_agent_load_audio()
            self.lyrics_song_length_seconds = song_length_seconds
            
            whisper_transcript, initial_timed_segments, audio_info = self._transcribe_audio(audio_path)

            user_lyrics, _, _ = utils._get_lyrics_from_input(self.user_text, self.lyrics_lyrics_folder_path, self.lyrics_lyrics_file, self.run_config.debug_mode)
            final_lyrics_text, final_timed_segments, spectrogram_preview = self._align_and_correct_lyrics(
                whisper_transcript, initial_timed_segments, user_lyrics, audio_path
            )

            segment_entries = self._extract_segment_entries_from_text(self.user_text)
            if self._lyrics_request_expects_segment_json(segment_entries):
                schedule_out = self._lyrics_agent_write_segment_json(segment_entries, final_lyrics_text)
                prompt_out = ""
                image_context_out = self.state.get("image_context") or ""

                print(
                    f"\033[94m[PromptCrafter-MusicVideo] Segment-locked output selected: "
                    f"prompt_len={len(str(prompt_out or ''))}, "
                    f"schedule_len={len(str(schedule_out or ''))}, "
                    f"segment_count={len(segment_entries)}\033[0m"
                )

                print("\033[95m[MusicVideo-PostProd] Finalizing assets...\033[0m")
                final_srt_string, audio_meta = self._lyrics_agent_finalize_assets(
                    final_timed_segments, spectrogram_preview, audio_info
                )

                negative_prompt_out = utils._generate_negative_prompt(
                    schedule_out,
                    self.run_config,
                    user_negative_prompt=self.negative_prompt,
                )
                print("\033[95m[PromptCrafter-MusicVideo] Production complete.\033[0m")

                return {
                    "prompt": prompt_out,
                    "schedule": schedule_out,
                    "image_context": image_context_out,
                    "negative_prompt": negative_prompt_out,
                    "clean_lyrics_txt": final_lyrics_text,
                    "lyrics_srt": final_srt_string,
                    "model_out": self.run_config.model,
                    "seed_out": str(self.run_config.seed),
                    "audio_meta": audio_meta,
                    "spectrogram_preview": spectrogram_preview,
                    "signal": self.kwargs.get('signal'),
                    "auto_character": "",
                    "auto_theme": "",
                    "auto_environment": "",
                    "auto_lighting": "",
                    "auto_interaction": "",
                    "auto_expression": "",
                    "auto_shots": "",
                    "auto_outfit": "",
                    "auto_visibility": "",
                }
            
            print("\033[95m[MusicVideo-CreativeDept] Starting creative development...\033[0m")
            global_theme, image_context_out = self._lyrics_agent_develop_concept(final_lyrics_text)
            
            # --- REFACTOR: Process lyrics in structural chunks in parallel ---
            lyric_chunks = self._split_lyrics_into_chunks(final_lyrics_text, final_timed_segments)
            
            all_prompts = []
            all_auto_vrg_vars = []

            print(f"\033[94m[MusicVideo-Production] Processing {len(lyric_chunks)} structural song sections in parallel...\033[0m")

            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_CONCURRENT_LLM_CALLS) as executor:
                # Create a mapping of future to chunk index to preserve order
                    future_to_index = {
                        executor.submit(self._process_lyric_chunk, chunk, image_context_out, global_theme): i
                        for i, chunk in enumerate(lyric_chunks)
                    }
                    
                    # Initialize results list with placeholders (annotated so static checkers accept tuple assignments)
                    results: List[Optional[Tuple[str, Dict[str, Any]]]] = [None] * len(lyric_chunks)
                    for future in concurrent.futures.as_completed(future_to_index):
                        index = future_to_index[future]
                        chunk = lyric_chunks[index]
                        try:
                            # Place the result in the correct position
                            results[index] = future.result()
                            print(f"\033[92m[MusicVideo-Production] Finished processing section: {chunk.get('tag', 'Untitled')}\033[0m")
                        except Exception as exc:
                            print(f'\033[91m[MusicVideo-Production] Section {chunk.get("tag", "Untitled")} generated an exception: {exc}\033[0m')
                            results[index] = (f"[Error processing section: {exc}]", {})

            # Reassemble results, which are now in order
            for result in results:
                if result:
                    prompt_or_schedule, auto_vrg_vars = result
                    all_prompts.append(prompt_or_schedule)
                    all_auto_vrg_vars.append(auto_vrg_vars)

            # --- Consolidate results ---
            if self.lyrics_generate_schedule:
                schedule_out = self._merge_schedules(all_prompts)
                prompt_out = ""
            else:
                prompt_out = " | ".join(filter(None, all_prompts))
                schedule_out = ""
            print(
                f"\033[94m[PromptCrafter-MusicVideo] Consolidated section outputs: "
                f"count={len(all_prompts)}, "
                f"prompt_len={len(str(prompt_out or ''))}, "
                f"schedule_len={len(str(schedule_out or ''))}\033[0m"
            )
            
            # Consolidate auto_vrg_vars for output
            final_auto_vrg_vars = all_auto_vrg_vars[-1] if all_auto_vrg_vars else {}
            # --- END REFACTOR ---
            
            print("\033[95m[MusicVideo-PostProd] Finalizing assets...\033[0m")
            final_srt_string, audio_meta = self._lyrics_agent_finalize_assets(
                final_timed_segments, spectrogram_preview, audio_info
            )
            
            negative_prompt_out = utils._generate_negative_prompt(prompt_out or schedule_out, self.run_config, user_negative_prompt=self.negative_prompt)
            print("\033[95m[PromptCrafter-MusicVideo] Production complete.\033[0m")
            
            # --- FIX: Ensure final_auto_vrg_vars is a dictionary before accessing keys ---
            auto_character = final_auto_vrg_vars.get("auto_character", "") if isinstance(final_auto_vrg_vars, dict) else ""
            auto_theme = final_auto_vrg_vars.get("auto_theme", "") if isinstance(final_auto_vrg_vars, dict) else ""
            auto_environment = final_auto_vrg_vars.get("auto_environment", "") if isinstance(final_auto_vrg_vars, dict) else ""
            auto_lighting = final_auto_vrg_vars.get("auto_lighting", "") if isinstance(final_auto_vrg_vars, dict) else ""
            auto_interaction = final_auto_vrg_vars.get("auto_interaction", "") if isinstance(final_auto_vrg_vars, dict) else ""
            auto_expression = final_auto_vrg_vars.get("auto_expression", "") if isinstance(final_auto_vrg_vars, dict) else ""
            auto_shots = final_auto_vrg_vars.get("auto_shots", "") if isinstance(final_auto_vrg_vars, dict) else ""
            auto_outfit = final_auto_vrg_vars.get("auto_outfit", "") if isinstance(final_auto_vrg_vars, dict) else ""
            auto_visibility = final_auto_vrg_vars.get("auto_visibility", "") if isinstance(final_auto_vrg_vars, dict) else ""

            # Return a consolidated dictionary
            return {
                "prompt": prompt_out,
                "schedule": schedule_out,
                "image_context": image_context_out,
                "negative_prompt": negative_prompt_out,
                "clean_lyrics_txt": final_lyrics_text,
                "lyrics_srt": final_srt_string,
                "model_out": self.run_config.model,
                "seed_out": str(self.run_config.seed),
                "audio_meta": audio_meta,
                "spectrogram_preview": spectrogram_preview,
                "signal": self.kwargs.get('signal'),
                "auto_character": auto_character,
                "auto_theme": auto_theme,
                "auto_environment": auto_environment,
                "auto_lighting": auto_lighting,
                "auto_interaction": auto_interaction,
                "auto_expression": auto_expression,
                "auto_shots": auto_shots,
                "auto_outfit": auto_outfit,
                "auto_visibility": auto_visibility,
            }

        except Exception as e:
            print(f"\033[91m[MusicVideo-Production] Error: {e}\033[0m")
            import traceback
            traceback.print_exc()
            return (f"An error occurred: {e}",) + (None,) * 19

    def _split_lyrics_into_chunks(self, lyrics_text, timed_segments):
        """Splits lyrics into structural chunks (Intro, Verse, Chorus, etc.)."""
        chunks = []
        # Regex to find structural tags like [Intro], [Verse 1], [Chorus - Yelled]
        pattern = re.compile(r"(\[.*?\])")
        parts = pattern.split(lyrics_text)
        
        # If the text starts with a tag, parts[0] will be empty.
        # If it starts with text, parts[0] is that text. We want to ignore it.
        start_index = 1 if parts and parts[0].strip() == "" else 1

        # Process the rest of the parts, which will be [tag], text, [tag], text...
        # Start at 1 to skip any text before the first tag.
        for i in range(start_index, len(parts), 2):
            tag = parts[i].strip()
            text = parts[i+1].strip() if i + 1 < len(parts) else ""
            if text:
                chunks.append({"tag": tag, "text": text})

        if not chunks:
            return [{"tag": "Full Song", "text": lyrics_text}]

        # If we have timed segments, associate them with the correct chunk
        if timed_segments:
            for chunk in chunks:
                chunk["segments"] = []
                chunk_text_lower = chunk["text"].lower()
                for seg_start, seg_end, seg_text in timed_segments:
                    # A simple containment check to associate segments with chunks
                    if seg_text.lower() in chunk_text_lower:
                        chunk["segments"].append((seg_start, seg_end, seg_text))
        
        return chunks

    def _merge_schedules(self, schedules):
        """Merges multiple JSON schedule strings into a single one."""
        merged_schedule = collections.OrderedDict()
        for schedule_str in schedules:
            try:
                schedule_data = json_utils.extract_and_parse_json(schedule_str)
                if schedule_data:
                    merged_schedule.update({int(k): v for k, v in schedule_data.items()})
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return json.dumps(collections.OrderedDict(sorted(merged_schedule.items())), indent=4)

    @staticmethod
    def _normalize_segment_key(key):
        """Normalizes segment identifiers to the canonical segmentN format."""
        if key is None:
            return None
        match = re.search(r"(?:lyric)?segment\s*(\d+)", str(key), re.IGNORECASE)
        if not match:
            return None
        return f"segment{int(match.group(1))}"

    def _extract_segment_entries_from_text(self, text):
        """
        Extracts the largest contiguous block of segment lines from an instruction.
        This lets us ignore short example blocks and preserve the real numbered input.
        """
        if not text:
            return collections.OrderedDict()

        segment_line = re.compile(r'^\s*["\']?((?:lyric)?segment\s*\d+)["\']?\s*:\s*(.+?)\s*$', re.IGNORECASE)
        blocks = []
        current_block = []

        for raw_line in text.splitlines():
            match = segment_line.match(raw_line.strip())
            if match:
                key = self._normalize_segment_key(match.group(1))
                value = match.group(2).rstrip(",").strip()
                if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                current_block.append((key, value))
                continue

            if current_block:
                blocks.append(current_block)
                current_block = []

        if current_block:
            blocks.append(current_block)

        if not blocks:
            return collections.OrderedDict()

        best_block = max(blocks, key=len)
        normalized = collections.OrderedDict()
        for key, value in best_block:
            if key:
                normalized[key] = str(value).strip()
        return normalized

    def _lyrics_request_expects_segment_json(self, segment_entries=None):
        """Detects segment-locked JSON correction tasks from the instruction text."""
        if segment_entries is None:
            segment_entries = self._extract_segment_entries_from_text(self.user_text)
        if len(segment_entries) < 2:
            return False

        cues = (
            r"return exactly \[?n\]? corrected segments",
            r"do not put lyricsegment",
            r"output clean,\s*valid json only",
            r"segment\d+",
        )
        return any(re.search(pattern, self.user_text or "", re.IGNORECASE) for pattern in cues)

    def _normalize_segment_json_response(self, raw_response, expected_segments):
        """
        Normalizes a model response into exactly the expected segment keys.
        Missing keys fall back to the original segment text so downstream nodes
        always receive a complete segment set instead of a reduced scene list.
        """
        parsed = None
        candidate_items = []

        if isinstance(raw_response, dict):
            parsed = raw_response
        elif isinstance(raw_response, str):
            try:
                parsed = json_utils.extract_and_parse_json(raw_response)
            except Exception:
                parsed = None

        if isinstance(parsed, dict):
            candidate_items = list(parsed.items())
        elif isinstance(raw_response, str):
            segment_line = re.compile(r'^\s*["\']?((?:lyric)?segment\s*\d+)["\']?\s*:\s*(.+?)\s*,?\s*$', re.IGNORECASE)
            for raw_line in raw_response.splitlines():
                match = segment_line.match(raw_line.strip())
                if not match:
                    continue
                candidate_items.append((match.group(1), match.group(2)))

        normalized_candidates = {}
        for raw_key, raw_value in candidate_items:
            key = self._normalize_segment_key(raw_key)
            if not key:
                continue

            value = raw_value
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            value = str(value).rstrip(",").strip()
            if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]
            normalized_candidates[key] = value

        normalized = collections.OrderedDict()
        for key, fallback_value in expected_segments.items():
            normalized[key] = str(normalized_candidates.get(key, fallback_value)).strip()
        return normalized

    def _lyrics_agent_write_segment_json(self, expected_segments, final_lyrics_text):
        """
        Generates one JSON entry per locked lyric segment without regrouping the
        input into larger storyboard scenes.
        """
        print(
            f"\033[94m[MusicVideo-CreativeDept] Segment-locked JSON mode detected. "
            f"Preserving {len(expected_segments)} lyric segments.\033[0m"
        )

        expected_keys = list(expected_segments.keys())
        segment_block = "\n".join(
            f'"{key}": {json.dumps(value, ensure_ascii=False)}'
            for key, value in expected_segments.items()
        )
        reference_lyrics = final_lyrics_text.strip() if isinstance(final_lyrics_text, str) else ""
        reference_section = f"\nREFERENCE LYRICS:\n{reference_lyrics}\n" if reference_lyrics else ""

        prompt = textwrap.dedent(
            f"""
            You are completing a segment-locked lyrics JSON task.

            STRICT OUTPUT RULES:
            - Return ONLY a JSON object.
            - Output exactly {len(expected_keys)} keys in this exact order:
              {", ".join(expected_keys)}
            - Never merge, split, skip, reorder, or rename segments.
            - Normalize any lyricsegment keys to segment keys.
            - Each value must be a JSON string.
            - If a segment is short, expand it naturally, but only within that same segment.

            LOCKED INPUT SEGMENTS:
            {segment_block}
            {reference_section}
            ORIGINAL INSTRUCTION TO FOLLOW:
            {self.user_text}
            """
        ).strip()

        ok, raw_response = self._query_model(
            self.run_config.model,
            prompt,
            prefer_chat=True,
            temperature=0.0,
            seed=self.run_config.seed,
            debug_mode=self.run_config.debug_mode,
            debug_title="Generate Segment-Locked Lyrics JSON",
            timeout=self.run_config.timeout,
        )
        if not ok:
            raise Exception(f"Failed to generate segment-locked lyrics JSON: {raw_response}")

        normalized = self._normalize_segment_json_response(raw_response, expected_segments)
        print(
            f"\033[94m[PromptCrafter-MusicVideo] Segment JSON output: "
            f"expected={len(expected_segments)}, actual={len(normalized)}\033[0m"
        )
        return json.dumps(normalized, indent=4, ensure_ascii=False)

    def _process_lyric_chunk(self, chunk, image_context_out, global_theme):
        """
        Processes a single lyric chunk to generate prompts and VRG variables.
        This method is designed to be run in a parallel execution context.
        """
        chunk_text = chunk["text"]
        chunk_timed_segments = chunk.get("segments")
        
        print(f"\033[96m--- Processing Section: {chunk.get('tag', 'Untitled')} ---\033[0m")

        # --- Run chain of command for each chunk ---
        vrg_kwargs, auto_vrg_vars = self._lyrics_agent_automate_vrg_vars(chunk_text, image_context_out)

        if self.lyrics_use_vrg_prompt_builder:
            # VRG builder operates on the text of the chunk
            prompt_out, schedule_out = self._lyrics_agent_write_vrg_prompts(
                chunk_timed_segments, chunk_text, vrg_kwargs
            )
        else:
            # Storyboard operates on the text of the chunk
            prompt_out, schedule_out = self._lyrics_agent_write_storyboard_prompts(
                chunk_text, chunk_timed_segments, global_theme, image_context_out
            )

        prompt_or_schedule = schedule_out if self.lyrics_generate_schedule else prompt_out
        return prompt_or_schedule, auto_vrg_vars

    def _generate_vrg_variables(self, lyrics, image_context):
        """
        Generates the nine creative visual categories using an LLM based on the provided instructions.
        """
        # --- OPTIMIZATION: Summarize long lyrics to avoid huge prompts ---
        lyric_lines = lyrics.splitlines()
        if len(lyric_lines) > 20:
            lyrics_summary = "\n".join(lyric_lines[:10] + ["..."] + lyric_lines[-10:])
        else:
            lyrics_summary = lyrics

        # --- ENHANCEMENT: The prompt is rewritten to enforce the primacy of image context. ---
        prompt = textwrap.dedent(f"""
            You are an expert AI Music Video Director. Your task is to analyze reference images and song lyrics to produce ten creative visual categories.

            **CRITICAL HIERARCHY:**
            1.  **IMAGE CONTEXT IS PRIMARY:** The `Image Context` is the absolute source of truth for all visual elements. The generated `character_description`, `outfit_rules`, and `environment` MUST directly and accurately reflect the content of the images.
            2.  **LYRICS PROVIDE MOOD:** The `Lyrics` provide the mood, narrative, and emotional atmosphere that should be applied to the visual elements derived from the images.

            **TASK:**
            Produce ten creative visual categories. Each category must contain exactly eight comma-separated cinematic entries. Each category must appear in its own labeled code block.

            **VISUAL CATEGORIES TO GENERATE:**
            `character_description`, `song_theme_style`, `environment`, `lighting`, `camera_motion`, `physical_interaction`, `facial_expression`, `shots`, `outfit_rules`, `character_visibility`.

            **FEW-SHOT EXAMPLES FOR STYLE PATTERN:**
            Example Input (Lyrics: "The cold rain falls on the neon streets"):
            - environment: rainy urban alley, slick asphalt, neon-lit corner, steam from vents...
            - lighting: flickering neon blue, harsh streetlamp, wet reflections, deep shadows...
            - camera_motion: slow dolly in, low angle tilt, handheld jitter, static tracking...
            - outfit_rules: black trenchcoat, leather gloves, soaked denim, heavy boots...

            **STRICT RULES:**
            -   `character_description` MUST be a direct, factual description of the person in the `Image Context`.
            -   `camera_motion` must use standard cinematic camera language suitable for LTX-2 (for example: push in, pull back, pan, tilt, track, orbit, handheld, static).
            -   `shots` must use standard cinematic shot language suitable for LTX-2 (for example: close up, medium shot, wide shot, establishing shot, over the shoulder, low angle, high angle, overhead shot).
            -   `outfit_rules` must be two-word entries derived directly from the `Image Context` (e.g., white dress, blue shirt, black jacket).
            -   **Positional Pairing is CRITICAL**: The first entry in `environment` corresponds to the first in `lighting`, `camera_motion`, etc. The second entries correspond, and so on for all eight positions.
            -   Do NOT include lyric text or unrelated commentary in the output.

            --- ANALYSIS INPUT ---
            Image Context (Primary Visual Source): "{image_context}"
            Lyrics (Mood and Narrative Source): "{lyrics_summary}"
            ---

            Return ONLY the ten categories in their labeled code blocks.
        """)

        ok, ai_output = self._query_model(
            self.run_config.model,
            prompt,
            prefer_chat=True,
            temperature=self.run_config.temperature,
            seed=self.run_config.seed,
            debug_mode=self.run_config.debug_mode,
            debug_title="Generate VRG Variables",
            timeout=self.run_config.timeout
        )

        if not ok:
            print(f"\033[91m[MusicVideo-CreativeDept] Error generating VRG variables: {ai_output}\033[0m")
            return {
                "auto_character": "", "auto_theme": "", "auto_environment": "",
                "auto_lighting": "", "auto_camera_motion": "", "auto_interaction": "", 
                "auto_expression": "", "auto_shots": "", "auto_outfit": "", "auto_visibility": ""
            }

        # Parse the AI output into the individual categories
        parsed_vars = self._parse_vrg_output(ai_output)
        return parsed_vars

    def _parse_vrg_output(self, ai_output):
        """Parses the LLM output and extracts the VRG variables, enforcing constraints."""
        categories = {
            "auto_theme": "", 
            "auto_environment": "",
            "auto_lighting": "", 
            "auto_camera_motion": "",
            "auto_interaction": "", 
            "auto_expression": "", 
            "auto_shots": "", 
            "auto_outfit": "", 
            "auto_visibility": "",
            "auto_character": "",
        }

        def extract_category(text, category_name):
            # Regex to find a category block and extract its content
            match = re.search(rf"```{category_name}\s*\n(.*?)\n```", text, re.DOTALL)
            return match.group(1).strip() if match else ""

        # Map the output names to the names from the instructions
        categories["auto_character"] = extract_category(ai_output, "character_description")
        categories["auto_theme"] = extract_category(ai_output, "song_theme_style")
        categories["auto_environment"] = extract_category(ai_output, "environment")
        categories["auto_lighting"] = extract_category(ai_output, "lighting")
        categories["auto_camera_motion"] = extract_category(ai_output, "camera_motion")
        categories["auto_interaction"] = extract_category(ai_output, "physical_interaction")
        categories["auto_expression"] = extract_category(ai_output, "facial_expression")
        categories["auto_shots"] = extract_category(ai_output, "shots")
        categories["auto_outfit"] = extract_category(ai_output, "outfit_rules")
        categories["auto_visibility"] = extract_category(ai_output, "character_visibility")

        # --- Enforce Constraints ---
        # Enforce two-word entries for outfit_rules
        if categories["auto_outfit"]:
            entries = [e.strip() for e in categories["auto_outfit"].split(",")]
            valid_entries = [e for e in entries if len(e.split()) == 2]
            categories["auto_outfit"] = ", ".join(valid_entries)

        # Enforce allowed actions for camera_motion
        if categories["auto_camera_motion"]:
            allowed_motions = {
                "static", "handheld", "zoom in", "zoom out", "push in", "pull back",
                "dolly in", "dolly out", "pan", "pan left", "pan right", "tilt", "tilt up", "tilt down",
                "track", "tracking shot", "track forward", "track backward",
                "orbit", "orbit left", "orbit right", "rotate", "rotate around",
                "truck left", "truck right", "arc left", "arc right", "crane up", "crane down",
                "follow", "follow shot", "whip pan", "locked-off"
            }
            entries = [e.strip().lower() for e in categories["auto_camera_motion"].split(",")]
            valid_entries = [e for e in entries if e in allowed_motions]
            categories["auto_camera_motion"] = ", ".join(valid_entries)

        # Enforce standard framing types for shots
        if categories["auto_shots"]:
            allowed_shots = {
                "close up", "extreme close up", "medium close up", "medium shot",
                "full shot", "wide shot", "extreme wide shot", "long shot", "establishing shot",
                "over the shoulder", "profile shot", "two shot", "point of view", "insert shot",
                "macro shot", "overhead shot", "high angle", "low angle"
            }
            entries = [e.strip().lower() for e in categories["auto_shots"].split(",")]
            valid_entries = [e for e in entries if e in allowed_shots]
            categories["auto_shots"] = ", ".join(valid_entries)

        return categories

    def _build_vrg_prompt_instructions(self, pipe_separated_lyrics, num_fragments):
        """
        Constructs the prompt for the LLM to generate pipe-separated prompts
        based on the VRG categories and the provided lyrics.
        """
        # Retrieve the VRG variables, either automated or user-provided
        auto_vrg_vars = self.state.get("auto_vrg_vars", {})
        
        character_desc = self.lyrics_character_description
        song_theme_style = auto_vrg_vars.get("auto_theme") or self.lyrics_song_theme_style
        environment_list = auto_vrg_vars.get("auto_environment") or self.lyrics_environment
        lighting_list = auto_vrg_vars.get("auto_lighting") or self.lyrics_lighting
        camera_motion_list = auto_vrg_vars.get("auto_camera_motion") or self.lyrics_camera_motion
        physical_interaction_list = auto_vrg_vars.get("auto_interaction") or self.lyrics_physical_interaction
        facial_expression_list = auto_vrg_vars.get("auto_expression") or self.lyrics_facial_expression
        shots_list = auto_vrg_vars.get("auto_shots") or self.lyrics_shots
        outfit_rules_list = auto_vrg_vars.get("auto_outfit") or self.lyrics_outfit_rules
        character_visibility_list = auto_vrg_vars.get("auto_visibility") or self.lyrics_character_visibility
        
        # The prompt needs to instruct the LLM to use these lists and generate
        # one prompt per lyric fragment, separated by '|'.
        # It also needs to respect the positional pairing.
        
        model_guidelines = self._model_specific_guidelines("Video", self.run_config)
        guidelines_section = f"--- MODEL-SPECIFIC GUIDELINES ---\n{model_guidelines}\n---\n\n" if model_guidelines else ""
        
        prompt_template = textwrap.dedent(f"""
            You are an expert music video director and prompt engineer. Your task is to create {num_fragments} distinct, cinematic video prompts, one for each pipe-separated lyric fragment provided below. Each prompt must be designed for a text-to-video generation model.

            --- SONG CONTEXT ---
            Character Description: {character_desc}
            Song Theme/Style: {song_theme_style}
            ---

            --- VISUAL CATEGORIES (Use these to inspire your prompts. Entries are positionally paired where applicable.) ---
            Environment: {environment_list}
            Lighting: {lighting_list}
            Camera Motion: {camera_motion_list}
            Physical Interaction: {physical_interaction_list}
            Facial Expression: {facial_expression_list}
            Shots: {shots_list}
            Outfit Rules: {outfit_rules_list}
            Character Visibility: {character_visibility_list}
            ---

            --- LYRIC FRAGMENTS (Generate one prompt for each fragment) ---
            {pipe_separated_lyrics}
            ---

            {guidelines_section}
            INSTRUCTIONS:
            1.  Generate exactly {num_fragments} prompts, one for each lyric fragment.
            2.  Each prompt should be a detailed, single-sentence description of a visual scene.
            3.  Incorporate elements from the VISUAL CATEGORIES, ensuring variety across the 8 entries for each category (Environment, Lighting, etc.) while maintaining coherence.
            4.  For categories like Environment, Lighting, Camera Motion, Physical Interaction, Facial Expression, Shots, Outfit Rules, and Character Visibility, the first entry of each list should correspond to the first lyric fragment's prompt, the second entry to the second lyric fragment's prompt, and so on. Cycle through the 8 entries for each category if there are more than 8 lyric fragments.
            5.  Do NOT include the lyric text itself in the generated prompts.
            6.  The prompts should be imaginative yet grounded in cinematic realism.
            7.  Separate each generated prompt with a single pipe character `|`.
            8.  Ensure the output is ONLY the pipe-separated prompts. No commentary, no code blocks, no extra text.
            9.  Keep each prompt concise, aiming for {self.lyrics_word_count_min}-{self.lyrics_word_count_max} words.
            
            Example Output (if 2 fragments):
            A lone figure stands silhouetted against a vibrant sunset in a vast desert, a slow zoom out revealing the endless horizon | Close up on a woman's face, a single tear rolling down her cheek, illuminated by the soft glow of a street lamp
        """)
        return prompt_template

    # --- AGENT IMPLEMENTATIONS ---

    def _visual_agent_analyze_brief(self):
        """Agent 1: Analyzes user text and reference images."""
        print("\033[94m[Studio-Agent 1] Analyzing brief, images, and text...\033[0m")
        
        # --- FIX: Use the pre-analyzed image context from the state ---
        image_context = self.state.get("image_context")
        if not image_context:
            image_context = ""
        primary_subjects_from_images = self.state.get("primary_subjects_from_images", [])
        tok_ok, tokens_or_msg = utils._extract_mandatory_tokens_with_model(image_context, self.user_text, self.run_config, primary_subjects_from_images)

        if not tok_ok and primary_subjects_from_images:
            tok_ok = True
            tokens_or_msg = {"primary": primary_subjects_from_images, "allowed_list": primary_subjects_from_images}

        if not tok_ok:
            return None, tokens_or_msg
        
        brief = {
            "image_context": image_context,
            "primary_subjects_from_images": primary_subjects_from_images,
            "mandatory_tokens": tokens_or_msg
        }
        # self._consolidate_subjects() # This logic is now inlined
        mandatory_tokens = brief["mandatory_tokens"]
        primary_list = []
        if isinstance(mandatory_tokens, dict):
            primary_list = mandatory_tokens.get("primary", []) or []
        elif isinstance(mandatory_tokens, str):
            primary_list = [mandatory_tokens]
        elif isinstance(mandatory_tokens, (list, tuple)):
            primary_list = list(mandatory_tokens)
        else:
            primary_list = []

        normalized_primary = []
        for item in primary_list:
            if item is None: continue
            if isinstance(item, (list, tuple)):
                for sub in item:
                    if isinstance(sub, str): normalized_primary.append(sub)
                    else: 
                        try: normalized_primary.append(str(sub))
                        except Exception: continue
            elif isinstance(item, str):
                normalized_primary.append(item)
            else:
                try: normalized_primary.append(str(item))
                except Exception: continue

        all_primary_subjects = [re.sub(r'^\s*\bPRIMARY\b\s*', '', t).strip() for t in normalized_primary]
        
        if brief["primary_subjects_from_images"]:
            primary_subject_from_image = brief["primary_subjects_from_images"][0].strip()
            if primary_subject_from_image:
                tagged_subject = f"[PRIMARY] {primary_subject_from_image}"
                if tagged_subject not in all_primary_subjects:
                    all_primary_subjects.append(tagged_subject)
        
        brief["all_primary_subjects"] = all_primary_subjects
        
        if isinstance(brief["mandatory_tokens"], dict):
            brief["mandatory_tokens"]['primary'] = all_primary_subjects
            # --- FIX: Add type check before using .get() to satisfy Pylance ---
            if 'allowed_list' in brief["mandatory_tokens"]:
                allowed_list = brief["mandatory_tokens"].get('allowed_list', []) or []
                brief["mandatory_tokens"]['allowed_list'] = list(set(allowed_list + all_primary_subjects))
            # --- END FIX ---

        return brief, None

    def _get_adjusted_temperature(self, base_temp, creativity_level):
        """
        Adjusts the base temperature based on the creativity level (1-10).
        Level 5 is neutral. Higher levels increase temp, lower levels decrease it.
        """
        # Map creativity_level (1-10) to a multiplier (e.g., 0.5 to 1.5)
        # A creativity level of 5 corresponds to a multiplier of 1.0
        multiplier = 1.0 + (creativity_level - 5) * 0.1  # Each step changes multiplier by 0.1

        adjusted_temp = base_temp * multiplier
        # Clamp the final temperature to a safe range (e.g., 0.0 to 1.5)
        return max(0.0, min(1.5, adjusted_temp))

    @staticmethod
    def _is_ltx2_target(run_config):
        fmt = getattr(run_config, "target_model_format", "Generic (SD1.5, SD2.1)")
        return fmt.startswith("LTX-2") or fmt == "Generic Video (Wan, etc.)"

    @staticmethod
    def _model_specific_guidelines(mode, run_config):
        guidelines = ""
        if ThoughtProcess._is_ltx2_target(run_config):
            guidelines = f"""
MODEL-SPECIFIC PROMPTING GUIDELINES (LTX-2 / LTX-2.3 Video Generation):
{config.LTX2_PROMPT_GUIDELINES}

{config.LTX2_VIDEO_PROMPT_CATEGORIES}
"""
        return guidelines

    def _build_initial_merge_prompt(self, mode, user_text, user_negative_prompt, image_context, mandatory_tokens, images, run_config, all_primary_subjects):
        """
        Constructs the initial, comprehensive prompt for the LLM to generate the first draft.
        """
        # --- 1. Set up Persona and Core Task ---
        persona = run_config.style_profile.get("persona", "You are an expert cinematic prompt engineer.")
        task_description = f"Your task is to generate a single, detailed, and creative prompt for a text-to-{mode.lower()} model."

        # --- 2. Format Mandatory Subjects ---
        # --- FIX: Add type check before using .get() to satisfy Pylance ---
        primary_subjects_str = ""
        if isinstance(mandatory_tokens, dict):
            primary_subjects_str = ", ".join([s.replace("[PRIMARY]", "").strip() for s in mandatory_tokens.get("primary", [])])
            secondary_subjects_str = ", ".join([s.replace("[SECONDARY][OPTIONAL]", "").strip() for s in mandatory_tokens.get("secondary", [])])
        else:
            secondary_subjects_str = ""
        
        mandatory_section = "MANDATORY SUBJECTS (Must be included):\n"
        if primary_subjects_str:
            mandatory_section += f"- Primary: {primary_subjects_str}\n"
        if secondary_subjects_str:
            mandatory_section += f"- Secondary (Optional): {secondary_subjects_str}\n"
        if not primary_subjects_str and not secondary_subjects_str:
            mandatory_section = "MANDATORY SUBJECTS: None specified. You have creative freedom.\n"

        # --- 3. Format Style Inspiration ---
        style_inspiration = run_config.style_profile.get("inspiration", "")
        style_section = f"STYLE INSPIRATION (Use this as a guide):\n- {style_inspiration}\n" if style_inspiration else ""

        # --- 4. Format Image Context ---
        image_context_section = f"REFERENCE IMAGE CONTEXT:\n{image_context}\n" if image_context and not image_context.startswith("No reference") else ""

        # --- 5. Model-Specific Guidelines ---
        model_guidelines = self._model_specific_guidelines(mode, run_config)

        # --- 6. Assemble the Final Prompt ---
        prompt_template = textwrap.dedent(f"""
            {persona}
            {task_description}

            ---
            USER INSTRUCTIONS (Primary Goal)
            ---
            {user_text}
            ---

            {mandatory_section.strip()}
            ---

            {style_section.strip()}
            ---

            {image_context_section.strip()}
            ---
            {model_guidelines}
            ---

            **FINAL INSTRUCTIONS:**
            1.  Synthesize all the information above into a single, coherent, and descriptive paragraph.
            2.  Ensure all 'Primary' mandatory subjects are central to the scene.
            3.  The final prompt should be between {run_config.max_length_words // 2} and {run_config.max_length_words} words.
            4.  Return ONLY the final prompt string. No commentary, no titles, no extra text.
        """).strip()

        return prompt_template

    def _build_style_and_composition_rules(self, mode, images, run_config, user_text, negative_prompt, image_context, artistry_level=5):
        """
        Generates a dictionary of style and composition rules based on the selected style profile and artistry level.
        """
        # 1. Get the base inspiration from the style profile stored in run_config
        style_profile = run_config.style_profile
        base_inspiration = style_profile.get("inspiration", "A balanced and visually appealing composition.")
        
        style_rules = {
            "base_inspiration": base_inspiration,
            "additional_rules": []
        }

        # 2. If artistry is high, use an LLM to generate more specific rules.
        if artistry_level > 6:
            print(f"\033[94m[PromptCrafter] High artistry level ({artistry_level}) detected. Generating additional style rules...\033[0m")
            
            # The persona is also taken from the style profile
            persona = style_profile.get("persona", "You are an expert art director.")

            prompt = textwrap.dedent(f"""
                {persona}
                Your task is to generate 3-5 additional, specific, and creative style and composition rules to enhance a scene.

                **BASE INSPIRATION:** {base_inspiration}
                **USER REQUEST:** {user_text}
                **IMAGE CONTEXT:** {image_context}

                **INSTRUCTIONS:**
                - Create rules that complement the base inspiration and user request.
                - Focus on cinematic elements like lighting, camera angles, color grading, and mood.
                - Do not contradict the user's request.
                - Return ONLY a JSON object with a single key, "additional_rules", containing an array of strings.

                **Example Output:**
                {{
                    "additional_rules": [
                        "Utilize a shallow depth of field to isolate the subject.",
                        "Incorporate volumetric lighting to create a sense of atmosphere.",
                        "Apply a subtle film grain for a more organic texture."
                    ]
                }}
            """).strip()

            ok, result = self._reason_with_model(
                run_config.model,
                prompt,
                use_chat_api=run_config.use_chat_api,
                temperature=0.4,
                seed=run_config.seed,
                debug_mode=run_config.debug_mode,
                debug_title="Generate Additional Style Rules",
            )
            if ok and isinstance(result, dict) and "additional_rules" in result:
                style_rules["additional_rules"] = result["additional_rules"]

        return style_rules

    def _visual_agent_write_draft(self):
        """Agent 2: Writes the initial creative draft."""
        print("\033[94m[Studio-Agent 2] Writing creative draft...\033[0m")
        images = [img for img, _ in self.images_with_weights]
        adjusted_temperature = self._get_adjusted_temperature(self.run_config.temperature, self.creativity_level)

        # Inlined from _generate_initial_draft
        merge_prompt = self._build_initial_merge_prompt(self.mode, self.state["user_text"], "", self.state["image_context"], self.state["mandatory_tokens"], images, self.run_config, self.state["all_primary_subjects"])
        generation_kwargs = {"prefer_chat": self.run_config.use_chat_api, "temperature": adjusted_temperature, "seed": self.run_config.seed, "timeout": self.run_config.timeout, "debug_mode": self.run_config.debug_mode}

        refinements = getattr(self.run_config, 'deep_think_refinements', 3)

        if self.run_config.use_deep_think and refinements > 0:
            print("\033[94m[PromptCrafter] Deep Think enabled. Starting iterative refinement...\033[0m")
            generation_kwargs["debug_title"] = f"Initial {self.mode} Prompt (Deep Think)"
            generation_kwargs["images"] = images
            ok, scene_prompt = utils._deep_think_and_refine(self.run_config.model, merge_prompt, max_iterations=refinements, confidence_threshold=self.run_config.deep_think_confidence, **generation_kwargs)
        else:
            if self.run_config.use_deep_think and refinements == 0:
                print("\033[94m[PromptCrafter] Deep Think disabled by setting refinements to 0.\033[0m")
            generation_kwargs["debug_title"] = f"Initial {self.mode} Prompt"
            ok, scene_prompt = self._query_model(self.run_config.model, merge_prompt, **generation_kwargs)

        return (utils.TextCleaner.single_paragraph(scene_prompt), None) if ok else (None, f"Ollama error: {scene_prompt}")

    def _visual_agent_apply_style(self, style_rules):
        """Agent 3: Applies cinematic style, composition, and art direction."""
        print("\033[94m[Studio-Agent 3] Applying art direction and style...\033[0m")
        self.state["style_rules"] = style_rules
        
        model_guidelines = self._model_specific_guidelines(self.mode, self.run_config)
        guidelines_section = f"\n**MODEL-SPECIFIC GUIDELINES:**\n{model_guidelines}\n" if model_guidelines else ""
        
        # Inlined from _refine_image_video_prompt
        refinement_prompt = f"""
You are an expert cinematic prompt engineer. Your task is to refine a DRAFT prompt by integrating STYLE & COMPOSITION RULES, transforming it into a final, polished, and highly effective prompt for a {self.mode} generation model.

**DRAFT PROMPT:**
---
{self.state["draft_prompt"]}
---

**STYLE & COMPOSITION RULES:**
---
{json.dumps(style_rules)}
---
{guidelines_section}
**YOUR TASK:**
1.  **Integrate Rules:** Rewrite the DRAFT to seamlessly and naturally incorporate the STYLE & COMPOSITION RULES.
2.  **Enhance, Don't Replace:** Build upon the core ideas of the DRAFT. Do not discard its main subjects or intent.
3.  **Cinematic Language:** Use vivid, descriptive, and cinematic language suitable for a top-tier text-to-image model.
4.  **Single Paragraph:** The final output must be a single, coherent paragraph.

Return ONLY the final, refined prompt.
"""
        ok, refined_prompt = self._query_model(
            self.run_config.model, refinement_prompt, prefer_chat=self.run_config.use_chat_api, 
            temperature=self.run_config.temperature, seed=self.run_config.seed, 
            timeout=self.run_config.timeout, debug_mode=self.run_config.debug_mode, debug_title="Refine Visual Prompt"
        )
        return utils.TextCleaner.single_paragraph(refined_prompt) if ok else self.state["draft_prompt"]

    def _visual_agent_finalize_and_clean(self):
        """Agent 4: Cleans prompt for diffusion and generates negatives."""
        print("\033[94m[Studio-Agent 4] Finalizing prompt and generating negatives...\033[0m")
        new_positive, counter_negatives = utils._simplify_for_diffusion(self.state["final_prompt"], self.state["user_text"], self.run_config)
        
        combined_negative_input = f"{self.negative_prompt}, {counter_negatives}".strip().strip(',')
        
        final_negative = utils._generate_negative_prompt(new_positive, self.run_config, user_negative_prompt=combined_negative_input)
        return new_positive, final_negative

    def _qna_agent_triage_request(self):
        """Agent 1: Analyzes request and assigns the correct model."""
        print("\033[94m[QnA-Agent 1] Triaging request and selecting model...\033[0m")
        llm_model = self.run_config.model
        has_image = self.qna_image is not None
        if self.qna_auto_select_model:
            vision_models_list = api_clients.get_vision_models()
            text_models_list = api_clients.get_text_models()
            is_vision_model = llm_model in vision_models_list
            is_text_model = llm_model in text_models_list

            if has_image and not is_vision_model:
                fallback = next((m for m in vision_models_list if "llava" in m), vision_models_list[0] if vision_models_list else config.FALLBACK_VISION_MODEL)
                print(f"\033[93m[PromptCrafter] Warning: Image provided to QnA node, but '{llm_model}' is not a vision model. Auto-switching to '{fallback}'.\033[0m")
                llm_model = fallback
            elif not has_image and is_vision_model and not is_text_model:
                fallback = next((m for m in text_models_list if "llama3" in m), text_models_list[0] if text_models_list else config.FALLBACK_TEXT_MODEL)
                print(f"\033[93m[PromptCrafter] Warning: No image provided to QnA node, but '{llm_model}' is a vision-only model. Auto-switching to '{fallback}'.\033[0m")
                llm_model = fallback

        return llm_model if llm_model else config.FALLBACK_TEXT_MODEL

    def _qna_agent_gather_context(self):
        """Agent 2: Retrieves context from files or the web."""
        print("\033[94m[QnA-Agent 2] Gathering context...\033[0m")
        context, raw_context, context_source = "", "", "None"
        has_file_context = self.qna_folder_path and self.qna_file_name and self.qna_file_name != "<none>"

        if has_file_context:
            fpath = utils._get_verified_path(self.qna_folder_path, self.qna_file_name)
            if fpath:
                raw_context = utils.safe_read(fpath)
                context = raw_context
                context_source = f"File ({self.qna_file_name})"
            else:
                safe_folder = self.qna_folder_path if self.qna_folder_path is not None else ""
                safe_file = self.qna_file_name if self.qna_file_name is not None else ""
                context = f"[Error: File not found at '{os.path.join(safe_folder, safe_file)}'.]"
                raw_context = context
                context_source = f"File ({self.qna_file_name}) - Not Found"
        elif self.qna_enable_web_search:
            search_needed, search_query = utils._should_perform_web_search(self.qna_instruction, self.run_config.model, self.run_config.seed, self.run_config.debug_mode, timeout=self.run_config.timeout)
            if search_needed and isinstance(search_query, str) and search_query.strip():
                web_context = utils._perform_web_search(search_query, num_results=3, debug_mode=self.run_config.debug_mode, fast_search=self.qna_fast_web_search)
                context = web_context
                raw_context = web_context
                context_source = f"Web Search (query: '{search_query}')"
            elif search_needed:
                context = "[Error: No valid search query provided for web search.]"
                raw_context = context
                context_source = "Web Search - Invalid Query"
        return context, raw_context, context_source

    def _qna_agent_summarize_context(self, context, raw_context, context_source, llm_model):
        """Agent 3a: Summarizes the retrieved context if it's too large."""
        strategy_key = "extractive" if "Extractive" in self.qna_summarization_strategy else "default"
        if self.qna_chunk_large_context and context and not context.startswith("[Error") :
            if len(context.split()) > self.qna_chunk_size_words:
                print(f"\033[94m[QnA-Agent 3] Context from {context_source} is large. Summarizing...\033[0m")
                return utils._summarize_large_text(raw_context, self.qna_chunk_size_words, llm_model, self.run_config.temperature, self.run_config.seed, self.run_config.debug_mode, self.run_config.timeout, strategy=strategy_key, user_query=self.qna_instruction)
        return context

    def _qna_agent_summarize_query(self, llm_model):
        """Agent 3b: Summarizes the user's query if it's too large."""
        final_user_text = self.qna_instruction
        if self.qna_chunk_large_context and len(self.qna_instruction.split()) > self.qna_chunk_size_words and self.qna_instruction.strip() != config.DEFAULT_PROMPT_TEXT:
            print(f"\033[94m[PromptCrafter] User text is large. Summarizing...\033[0m")
            final_user_text = utils._summarize_large_text(self.qna_instruction, self.qna_chunk_size_words, llm_model, self.run_config.temperature, self.run_config.seed, self.run_config.debug_mode, self.run_config.timeout, strategy="default")
            utils._debug_print(self.run_config.debug_mode, "Summarized User Text", final_user_text)

        if (self.qna_image is not None) and self.qna_instruction.strip() == config.DEFAULT_PROMPT_TEXT:
            final_user_text = "Describe this image in detail."
        
        if self.qna_subject and self.qna_subject.strip():
            return f"SUBJECT:\n{self.qna_subject}\n\nINSTRUCTION:\n{final_user_text}"
        return final_user_text

    def _qna_agent_formulate_answer(self, llm_model, briefing_context, summarized_query, history_override=None):
        """Agent 4: Constructs the final prompt and queries the LLM for the answer."""
        print("\033[94m[QnA-Agent 4] Formulating final answer...\033[0m")
        
        # Use history_override if provided (e.g. summarized history)
        if history_override is not None:
            history_text = history_override
        else:
            history_text = self.qna_history_in.strip() if self.qna_history_in and not self.qna_clear_history else ""
            
        safety_rule = f"\n\n{config.SAFE_MODE_RULE}" if self.qna_safe_mode else ""
        history_section = f"CONVERSATION HISTORY (for context):\n{history_text}\n\n" if history_text else ""
        context_section = f"ADDITIONAL CONTEXT (for this query only):\n{briefing_context}\n\n" if briefing_context else ""
        prompt = f"You are a helpful Q&A assistant. Answer the user's query based on the conversation history and any additional context provided.\n\n{history_section}{context_section}CURRENT USER QUERY:\n{summarized_query}{safety_rule}".strip()

        images_to_pass = [self.qna_image] if self.qna_image is not None else None
        model_name = "" if llm_model is None else str(llm_model)
        is_gguf_model = model_name.lower().startswith("gguf/")
        is_vision_request = self.qna_image is not None
        safe_max_tokens = 768 if is_vision_request else 1536
        gguf_runtime_kwargs = {}
        llm_device_choice = str(getattr(self.run_config, "llm_device", "Default (GPU)") or "").strip().lower()
        cpu_mode = llm_device_choice in {"cpu", "host", "cpu-only", "cpu only"}
        if is_gguf_model:
            gguf_runtime_kwargs["unload_after_query"] = True
            gguf_runtime_kwargs["unload_vision_after_query"] = is_vision_request
            gguf_runtime_kwargs["vision_projector_use_gpu"] = False
            if is_vision_request and cpu_mode:
                gguf_runtime_kwargs["n_gpu_layers"] = 0
                gguf_runtime_kwargs["n_batch"] = 64
                gguf_runtime_kwargs["n_ubatch"] = 32
        ok, resp = self._query_model(
            llm_model,
            prompt,
            images=images_to_pass,
            prefer_chat=True,
            temperature=self.run_config.temperature,
            seed=self.run_config.seed,
            debug_mode=self.run_config.debug_mode,
            debug_title="QnA Prompt",
            timeout=self.run_config.timeout,
            max_tokens=safe_max_tokens,
            **gguf_runtime_kwargs,
        )
        
        response_text = resp if ok else f"Ollama error: {resp}"
        stripped_response = response_text.strip()
        if not (stripped_response.startswith('{') and stripped_response.endswith('}')) and not (stripped_response.startswith('[') and stripped_response.endswith(']')):
            response_text = utils.TextCleaner.single_paragraph(response_text)
        new_history_entry = f"User: {summarized_query}\nAssistant: {response_text}"
        
        # We always append to the REAL history for the output, even if we used a summary for the prompt
        actual_history = self.qna_history_in.strip() if self.qna_history_in and not self.qna_clear_history else ""
        updated_history = f"{actual_history}\n{new_history_entry}".strip() if actual_history else new_history_entry
        
        return response_text, updated_history

    def _lyrics_agent_load_audio(self):
        """Agent A1: Loads audio and determines its length."""
        print("\033[94m[MusicVideo-AudioDept] Agent A1: Loading audio...\033[0m")
        audio_path = utils._get_audio_path(self.lyrics_audio_folder_path, self.lyrics_audio_file)
        song_length_seconds = self.lyrics_song_length_seconds
        if song_length_seconds <= 0 and audio_path:
            try:
                import librosa
                print("[PromptCrafter] Song length not provided, calculating from audio file...")
                duration = librosa.get_duration(path=audio_path)
                song_length_seconds = duration
                print(f"[PromptCrafter] Calculated song length: {duration:.2f} seconds.")
            except Exception as e:
                print(f"[PromptCrafter] Warning: Could not calculate song length from audio: {e}")
        return audio_path, song_length_seconds

    def _lyrics_agent_develop_concept(self, lyrics):
        """Agent C1: Develops the global theme and image context."""
        print("\033[94m[MusicVideo-CreativeDept] Agent C1: Developing concept...\033[0m")
        
        # --- ENHANCEMENT: Explicitly describe images first to inform VRG automation ---
        # This ensures that when automate_vrg_variables is on, the image context is available.
        # Use the pre-analyzed image context from the state
        image_context_out = self.state.get("image_context")
        if not image_context_out:
            image_context_out = ""
        primary_subjects_from_images = self.state.get("primary_subjects_from_images", [])

        # --- NEW: Override character description if automating from images ---
        if self.lyrics_automate_vrg_variables and primary_subjects_from_images:
            # Use the primary subject from the image as the character description
            self.lyrics_character_description = primary_subjects_from_images[0]
            print(f"\033[92m[MusicVideo-CreativeDept] Automated character from image: '{self.lyrics_character_description}'\033[0m")
        # --- END NEW ---
        
        # Now prepare the rest of the context using the lyrics and user text.
        _, _, style_inspiration_section, instructions_section, context_section = self._prepare_lyrics_generation_context(self.user_text, lyrics)
        
        audio_path = utils._get_audio_path(self.lyrics_audio_folder_path, self.lyrics_audio_file)
        mood_keywords = self._analyze_audio_mood(audio_path, lyrics)

        theme_ok, global_theme_or_err = self._generate_storyboard_global_theme(lyrics, instructions_section, context_section, image_context_out, mood_keywords=mood_keywords)
        if not theme_ok:
            raise Exception(f"Failed to generate storyboard theme: {global_theme_or_err}")
            
        return global_theme_or_err, image_context_out

    def _lyrics_agent_automate_vrg_vars(self, final_lyrics_text, image_context_out):
        """Agent C2: Automates VRG variables if requested."""
        auto_vrg_vars = {
            "auto_character": "", "auto_theme": "", "auto_environment": "",
            "auto_lighting": "", "auto_interaction": "", "auto_expression": "",
            "auto_shots": "", "auto_outfit": "", "auto_visibility": ""
        }
        vrg_kwargs = self.kwargs.copy()

        if self.lyrics_automate_vrg_variables:
            print("\033[94m[MusicVideo-CreativeDept] Agent C2: Automating VRG variables...\033[0m")
            auto_vrg_vars = self._generate_vrg_variables(final_lyrics_text, image_context_out)
            self.state["auto_vrg_vars"] = auto_vrg_vars # Store for later use in _build_vrg_prompt_instructions

        return vrg_kwargs, auto_vrg_vars

    def _prepare_lyrics_generation_context(self, user_text, lyrics):
        """
        A helper method to gather and structure all context needed for lyrics-based prompt generation.
        """
        # 1. Get image context from the state
        image_context = self.state.get("image_context", "")

        # --- OPTIMIZATION: Summarize long lyrics for token extraction ---
        lyric_lines = lyrics.splitlines()
        if len(lyric_lines) > 20:
            lyrics_summary = "\n".join(lyric_lines[:10] + ["..."] + lyric_lines[-10:])
        else:
            lyrics_summary = lyrics

        # 2. Extract mandatory tokens from the combined user text and lyrics
        combined_text = f"{user_text}\n\nLYRICS:\n{lyrics_summary}"
        tok_ok, mandatory_tokens = utils._extract_mandatory_tokens_with_model(
            image_context, combined_text, self.run_config, self.state.get("primary_subjects_from_images", [])
        )
        if not tok_ok:
            print(f"\033[93m[PromptCrafter] Warning: Could not extract mandatory tokens for lyrics generation: {mandatory_tokens}\033[0m")
            mandatory_tokens = {}

        # 3. Get style inspiration from the run configuration's style profile
        style_inspiration = self.run_config.style_profile.get("inspiration", "")
        style_inspiration_section = f"STYLE INSPIRATION:\n- {style_inspiration}\n" if style_inspiration else ""

        # 4. Build the instructions section
        instructions_section = "INSTRUCTIONS:\n"
        if user_text and user_text.strip() and user_text.strip() != config.DEFAULT_PROMPT_TEXT:
            instructions_section += f"- User's primary instruction: {user_text}\n"
        # --- FIX: Add type check before using .get() to satisfy Pylance ---
        if isinstance(mandatory_tokens, dict) and mandatory_tokens.get("primary"):
        # --- END FIX ---
            instructions_section += f"- Mandatory subjects to include: {', '.join(mandatory_tokens['primary'])}\n"

        # 5. Build the context section
        context_section = "CONTEXT:\n"
        if image_context:
            context_section += f"- Reference Image Context: {image_context}\n"
        if lyrics:
            context_section += f"- Song Lyrics: {lyrics}\n"

        # Ensure sections are not empty before adding them
        if instructions_section == "INSTRUCTIONS:\n": instructions_section = ""
        if context_section == "CONTEXT:\n": context_section = ""

        return image_context, mandatory_tokens, style_inspiration_section, instructions_section, context_section

    def _analyze_audio_mood(self, audio_path, lyrics):
        """Analyzes audio features and lyrics to determine the mood."""
        if not audio_path or not config.LIBROSA_AVAILABLE:
            return []

        cache_key = utils._get_cache_key("analyze_mood_v2", audio_path, lyrics)
        if config.CACHE.has(cache_key):
            print("\033[94m[MusicVideo-AudioDept] Using cached audio mood analysis.\033[0m")
            cached_data = config.CACHE.get(cache_key)
            return cached_data if isinstance(cached_data, list) else []

        print("\033[94m[MusicVideo-AudioDept] Analyzing audio mood...\033[0m")
        try:
            import librosa
            y, sr = librosa.load(audio_path)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            rms = librosa.feature.rms(y=y)
            energy = float(rms.mean())
            
            mood_prompt = textwrap.dedent(f"""
                You are an expert music analyst. Analyze the provided audio features and lyrics to determine the overall mood of the song.

                **Audio Features:**
                - Tempo: {float(tempo):.2f} BPM
                - Energy (RMS): {float(energy):.4f} (higher is more energetic)

                **Lyrics:**
                ---
                {lyrics[:1500]}
                ---

                **Task:**
                Based on all the information, generate a list of 3-5 keywords that best describe the mood of the song (e.g., "upbeat, energetic, happy" or "somber, melancholic, reflective").

                Return ONLY a JSON array of strings. Example: ["upbeat", "energetic", "happy"]
            """).strip()

            ok, mood_keywords = self._reason_with_model(
                self.run_config.model,
                mood_prompt,
                use_chat_api=True,
                temperature=0.2,
                seed=self.run_config.seed,
                debug_mode=self.run_config.debug_mode,
                debug_title="Analyze Audio Mood",
            )
            if ok and isinstance(mood_keywords, list):
                config.CACHE.set(cache_key, mood_keywords)
                return mood_keywords
        except Exception as e:
            print(f"\033[93m[MusicVideo-AudioDept] Warning: Could not analyze audio mood. Error: {e}\033[0m")
        
        return []
        
    def _generate_storyboard_global_theme(self, lyrics, instructions_section, context_section, image_context, mood_keywords=None):
        """
        Uses an LLM to generate a high-level creative concept for the music video.
        """
        print("\033[94m[MusicVideo-CreativeDept] Generating global theme...\033[0m")

        mood_section = f"SONG MOOD (from audio analysis):\n- {', '.join(mood_keywords)}\n" if mood_keywords else ""

        prompt = textwrap.dedent(f"""
            You are an expert music video creative director. Your task is to devise a single, concise, high-level creative concept or global theme for a music video. This theme will guide the creation of the entire storyboard.

            ---
            {instructions_section}
            ---
            {context_section}
            ---
            {mood_section}
            ---

            **INSTRUCTIONS:**
            1.  Synthesize all the provided information (lyrics, mood, instructions, image context).
            2.  Create a single, compelling, and imaginative theme.
            3.  The theme should be a short paragraph that sets the tone, setting, and narrative arc.
            4.  Return ONLY the theme description. No commentary.

            **Example Output:**
            A lonely astronaut drifts through the silent, vibrant nebulae of a forgotten galaxy, haunted by fragmented memories of a lost love on Earth that appear as ghostly projections on the cockpit's viewport. The journey is a melancholic dance between the vast, beautiful emptiness of space and the intimate, painful beauty of memory.
        """).strip()

        ok, theme_or_err = self._query_model(
            self.run_config.model, prompt, prefer_chat=True,
            temperature=self.run_config.temperature, seed=self.run_config.seed,
            debug_mode=self.run_config.debug_mode, timeout=self.run_config.timeout,
            debug_title="Generate Global Storyboard Theme"
        )
        return ok, theme_or_err

    def _group_lyrics_into_scenes(self, lyrics_text):
        """
        Fallback method to split raw lyrics text into scenes using AI
        when no timed segments are available.
        """
        print("\033[93m[MusicVideo-CreativeDept] Warning: No timed segments available. Using AI to split lyrics into scenes...\033[0m")
        # We can reuse the utility function that's already designed for this task.
        scenes = utils._split_text_into_scenes_with_ai(lyrics_text, self.run_config)
        return scenes

    def _lyrics_agent_write_vrg_prompts(self, final_timed_segments, final_lyrics_text, vrg_kwargs):
        """Agent C3 (VRG): Writes prompts using the VRG prompt builder."""
        print("\033[94m[MusicVideo-CreativeDept] Agent C3 (VRG): Writing prompts with VRG builder...\033[0m")
        
        if not final_timed_segments:
            scenes = self._group_lyrics_into_scenes(final_lyrics_text)
            if not scenes:
                raise Exception("Could not segment lyrics for VRG prompt generation.")
            pipe_separated_lyrics = "|".join(scenes)
            num_fragments = len(scenes)
        else:
            pipe_separated_lyrics = "|".join([seg[2] for seg in final_timed_segments])
            num_fragments = len(final_timed_segments)

        vrg_instructions = self._build_vrg_prompt_instructions(pipe_separated_lyrics, num_fragments)

        ok, final_prompts = self._query_model(
            self.run_config.model,
            vrg_instructions,
            prefer_chat=True,
            temperature=self.run_config.temperature,
            seed=self.run_config.seed,
            debug_mode=self.run_config.debug_mode,
            debug_title="VRG Lyrics-to-Prompt Generation",
            timeout=self.run_config.timeout
        )

        if not ok:
            raise Exception(f"Failed to generate VRG lyrics-to-prompt output: {final_prompts}")

        prompt_out = final_prompts
        schedule_out = ""
        if self.lyrics_generate_schedule:
            prompts_list = [p.strip() for p in final_prompts.split('|')]
            schedule_out = self._create_final_lyrics_output(
                prompts_list,
                final_timed_segments,
                True,
                self.lyrics_fps,
                self.lyrics_song_length_seconds,
                self.lyrics_max_scene_frames,
                bool(final_timed_segments),
                self.lyrics_scene_splitting_mode,
                self.lyrics_max_scene_frames,
                self.lyrics_max_scene_duration_seconds,
                self.lyrics_interpolate_keyframes,
                self.lyrics_interpolation_frame_interval
            )
            prompt_out = ""

        return prompt_out, schedule_out

    def _create_final_lyrics_output(self, storyboard_prompts, timed_segments, generate_schedule, fps, song_length_seconds, max_frames, has_real_timed_segments, scene_splitting_mode, max_scene_frames, max_scene_duration_seconds, interpolate_keyframes, interpolation_frame_interval):
        """
        Formats the final output for the LyricsCreator node, either as a pipe-separated
        string or a JSON schedule.
        """
        if not generate_schedule:
            return " | ".join(storyboard_prompts)

        # --- Schedule Generation Logic ---
        schedule = collections.OrderedDict()
        num_prompts = len(storyboard_prompts)

        if has_real_timed_segments and timed_segments:
            # Use precise timings from audio analysis
            for i, prompt in enumerate(storyboard_prompts):
                if i < len(timed_segments):
                    start_time, _, _ = timed_segments[i]
                    frame_index = int(start_time * fps)
                    schedule[frame_index] = prompt
        else:
            # No precise timings, so calculate frames based on splitting mode
            frames_per_scene = 0
            if scene_splitting_mode == 'Frame Length':
                frames_per_scene = max_scene_frames
            elif scene_splitting_mode == 'Fixed Duration':
                frames_per_scene = int(max_scene_duration_seconds * fps)
            else: # Structural Tag (fallback)
                # Distribute prompts evenly across the song's duration or max_frames
                total_frames = int(song_length_seconds * fps) if song_length_seconds > 0 else max_frames
                if num_prompts > 0:
                    frames_per_scene = total_frames // num_prompts

            if frames_per_scene > 0:
                for i, prompt in enumerate(storyboard_prompts):
                    frame_index = i * frames_per_scene
                    schedule[frame_index] = prompt

        if not schedule: # Final fallback if all else fails
            return utils._create_schedule_from_items(storyboard_prompts, max_frames, 0, interpolate_keyframes, interpolation_frame_interval)

        schedule_items = [f'"{str(key)}": {json.dumps(str(value))}' for key, value in schedule.items()]
        return "{\n" + ",\n".join(schedule_items) + "\n}"

    def _process_lyrics_storyboard(self, final_lyrics_text, final_timed_segments, global_theme, mandatory_tokens, style_inspiration_section, **kwargs):
        """
        Processes lyrics into scenes and generates a storyboard prompt for each scene in parallel.
        """
        if final_timed_segments:
            processed_segments = utils._process_timed_segments(
                final_timed_segments, self.lyrics_fps,
                min_duration_secs=self.lyrics_max_scene_duration_seconds / 2,
                max_duration_secs=self.lyrics_max_scene_duration_seconds
            )
            scenes = [seg[2] for seg in processed_segments]
        else:
            scenes = utils._split_text_into_scenes_with_ai(final_lyrics_text, self.run_config)
            processed_segments = None # No timing info available

        if not scenes:
            return "Could not generate scenes from lyrics.", None

        print(f"\033[94m[MusicVideo-CreativeDept] Generating storyboard for {len(scenes)} scenes in parallel...\033[0m")
        
        storyboard_prompts = [""] * len(scenes)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(scenes))) as executor:
            future_to_index = {
                executor.submit(
                    self._generate_prompt_for_lyric_scene,
                    scene_text, i + 1, len(scenes), global_theme, mandatory_tokens, style_inspiration_section
                ): i for i, scene_text in enumerate(scenes)
            }
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result = future.result()
                    storyboard_prompts[index] = result
                    print(f"\033[92m[MusicVideo-CreativeDept] Finished processing scene {index + 1}/{len(scenes)}.\033[0m")
                except Exception as exc:
                    error_msg = f"[Error processing scene {index + 1}: {exc}]"
                    storyboard_prompts[index] = error_msg
                    print(f'\033[91m[MusicVideo-CreativeDept] {error_msg}\033[0m')

        return storyboard_prompts, processed_segments

    def _generate_prompt_for_lyric_scene(self, scene_lyrics, scene_number, total_scenes, global_theme, mandatory_tokens, style_inspiration_section):
        """
        Generates a single cinematic prompt for a specific lyric scene.
        """
        model_guidelines = self._model_specific_guidelines("Video", self.run_config)
        guidelines_section = f"\n**MODEL-SPECIFIC GUIDELINES:**\n{model_guidelines}\n" if model_guidelines else ""

        prompt = textwrap.dedent(f"""
            You are an expert music video director. Your task is to create a single, cinematic prompt for one scene of a music video.

            **GLOBAL THEME / CONCEPT:**
            {global_theme}

            **STYLE INSPIRATION:**
            {style_inspiration_section}

            **CURRENT SCENE ({scene_number} of {total_scenes}):**
            - Lyrics for this scene: "{scene_lyrics}"
            {guidelines_section}
            **INSTRUCTIONS:**
            1.  Create a single, descriptive prompt for this specific scene.
            2.  The prompt must be inspired by the scene's lyrics and the global theme.
            3.  Incorporate the style inspiration.
            4.  If any mandatory subjects are specified, ensure they are included: {mandatory_tokens.get('primary', 'None')}
            5.  Keep the prompt concise, between {self.lyrics_word_count_min} and {self.lyrics_word_count_max} words.
            6.  Return ONLY the final prompt string. No commentary.
        """).strip()

        ok, scene_prompt = self._query_model(
            self.run_config.model,
            prompt,
            prefer_chat=True,
            temperature=self.run_config.temperature,
            seed=self.run_config.seed,
            debug_mode=self.run_config.debug_mode,
            timeout=self.run_config.timeout,
            debug_title=f"Generate Lyric Scene {scene_number}",
        )
        return scene_prompt if ok else f"[Error generating prompt for scene {scene_number}: {scene_prompt}]"

    def _lyrics_agent_write_storyboard_prompts(self, final_lyrics_text, final_timed_segments, global_theme, image_context_out):
        """Agent C3 (Storyboard): Writes prompts using the standard storyboard workflow. (FAST MODE)"""
        print("\033[94m[MusicVideo-CreativeDept] Agent C3 (Storyboard): Writing storyboard prompts... (FAST MODE)\033[0m")
        
        if not final_lyrics_text or not final_lyrics_text.strip():
            return "No lyrics provided.", ""

        # 1. Prepare context (same as before)
        _, mandatory_tokens, style_inspiration_section, _, _ = self._prepare_lyrics_generation_context(self.user_text, final_lyrics_text)

        # 2. Split this chunk's lyrics into scenes (same logic as _process_lyrics_storyboard)
        processed_segments = None
        if final_timed_segments:
            processed_segments = utils._process_timed_segments(
                final_timed_segments, self.lyrics_fps,
                min_duration_secs=self.lyrics_max_scene_duration_seconds / 2,
                max_duration_secs=self.lyrics_max_scene_duration_seconds
            )
            scenes = [seg[2] for seg in processed_segments]
        else:
            scenes = utils._split_text_into_scenes_with_ai(final_lyrics_text, self.run_config)
            processed_segments = None # No timing info available

        if not scenes:
            raise Exception("Could not generate scenes from lyrics.")

        # 3. Build the new "Mega-Prompt"
        # We'll join the scenes with '|' to pass to the LLM
        pipe_separated_lyrics = " | ".join(scenes)
        num_fragments = len(scenes)
        
        # --- FIX: Ensure mandatory_tokens is a dict before .get() ---
        primary_subjects = "None"
        if isinstance(mandatory_tokens, dict):
            primary_subjects = mandatory_tokens.get('primary', 'None')
        # --- END FIX ---
        
        model_guidelines = self._model_specific_guidelines("Video", self.run_config)
        guidelines_section = f"\n**MODEL-SPECIFIC GUIDELINES:**\n{model_guidelines}\n" if model_guidelines else ""

        # This prompt is inspired by _generate_prompt_for_lyric_scene and _build_vrg_prompt_instructions
        mega_prompt = textwrap.dedent(f"""
            You are an expert music video director. Your task is to create {num_fragments} distinct, cinematic video prompts, one for each pipe-separated lyric fragment provided below.

            **GLOBAL THEME / CONCEPT:**
            {global_theme}

            **STYLE INSPIRATION:**
            {style_inspiration_section}

            **MANDATORY SUBJECTS (must be included):**
            {primary_subjects}
            {guidelines_section}
            **LYRIC FRAGMENTS (Generate one prompt for each fragment):**
            ---
            {pipe_separated_lyrics}
            ---

            INSTRUCTIONS:
            1.  Generate exactly {num_fragments} prompts, one for each lyric fragment.
            2.  Each prompt must be a detailed, single-sentence description inspired by its corresponding lyric and the GLOBAL THEME.
            3.  Seamlessly integrate the STYLE INSPIRATION and MANDATORY SUBJECTS into each prompt.
            4.  Do NOT include the lyric text itself in the generated prompts.
            5.  Keep each prompt concise, aiming for {self.lyrics_word_count_min}-{self.lyrics_word_count_max} words.
            6.  Separate each generated prompt with a single pipe character `|`.
            7.  Return ONLY the pipe-separated prompts. No commentary, no code blocks, no extra text.
        """).strip()

        # 4. Make the single LLM call
        ok, final_prompts = self._query_model(
            self.run_config.model,
            mega_prompt,
            prefer_chat=True,
            temperature=self.run_config.temperature,
            seed=self.run_config.seed,
            debug_mode=self.run_config.debug_mode,
            debug_title=f"Generate Storyboard Batch (x{num_fragments} scenes)",
            timeout=self.run_config.timeout
        )

        if not ok:
            raise Exception(f"Failed to generate storyboard batch prompts: {final_prompts}")
        
        # 5. Process the result
        storyboard_prompts = [p.strip() for p in final_prompts.split('|')]
        
        # Handle mismatch in counts, a common LLM failure
        if len(storyboard_prompts) != num_fragments:
            print(f"\033[93m[PromptCrafter] Warning: LLM returned {len(storyboard_prompts)} prompts, but expected {num_fragments}. Trimming/padding list.\033[0m")
            # Trim extra prompts
            storyboard_prompts = storyboard_prompts[:num_fragments]
            # Pad missing prompts
            if len(storyboard_prompts) < num_fragments:
                storyboard_prompts.extend([storyboard_prompts[-1] if storyboard_prompts else "cinematic shot"] * (num_fragments - len(storyboard_prompts)))

        # 6. Create the final schedule/prompt string (same as before)
        final_output = self._create_final_lyrics_output(
            storyboard_prompts=storyboard_prompts,
            timed_segments=processed_segments,
            generate_schedule=self.lyrics_generate_schedule,
            fps=self.lyrics_fps,
            song_length_seconds=self.lyrics_song_length_seconds,
            max_frames=self.lyrics_max_scene_frames,
            has_real_timed_segments=bool(final_timed_segments),
            scene_splitting_mode=self.lyrics_scene_splitting_mode,
            max_scene_frames=self.lyrics_max_scene_frames,
            max_scene_duration_seconds=self.lyrics_max_scene_duration_seconds,
            interpolate_keyframes=self.lyrics_interpolate_keyframes,
            interpolation_frame_interval=self.lyrics_interpolation_frame_interval
        )
        
        prompt_out, schedule_out = ("", final_output) if self.lyrics_generate_schedule else (final_output, "")
        
        return prompt_out, schedule_out

    def _transcribe_audio(self, audio_path):
        """Agent A2: Transcribes audio to text using the selected Whisper engine."""
        if not audio_path:
            print("\033[93m[MusicVideo-AudioDept] No audio file provided for transcription. Skipping.\033[0m")
            return "", None, None

        print(f"\033[94m[MusicVideo-AudioDept] Agent A2: Transcribing '{os.path.basename(audio_path)}' with {self.lyrics_whisper_engine} (model: {self.lyrics_whisper_model_size})...\033[0m")

        # Generate a robust cache key including file content hash
        try:
            audio_content_hash = _get_file_hash(audio_path)
        except Exception as e:
            print(f"\033[93m[PromptCrafter] Warning: Could not hash audio file content: {e}. Using path only for cache key.\033[0m")
            audio_content_hash = "" # Fallback if hashing fails

        cache_key = utils._get_cache_key(
            "transcribe_v3", audio_content_hash, audio_path, self.lyrics_whisper_engine, 
            self.lyrics_whisper_model_size, self.lyrics_whisper_language
        )
        if config.CACHE.has(cache_key):
            print("\033[94m[MusicVideo-AudioDept] Using cached transcription.\033[0m")
            # --- FIX: Ensure we don't return None from a failed cache read ---
            cached_result = config.CACHE.get(cache_key)
            if cached_result is not None:
                return cached_result
            # If cache read fails, proceed to re-transcribe instead of returning None.

        try:
            # Dynamically import the correct transcription library based on the engine setting
            if self.lyrics_whisper_engine == "faster-whisper":
                from faster_whisper import WhisperModel
                device = "cuda" if torch.cuda.is_available() else "cpu"
                compute_type = "float16" if torch.cuda.is_available() else "int8"
                language = None if self.lyrics_whisper_language in (None, "auto-detect") else self.lyrics_whisper_language

                model = WhisperModel(self.lyrics_whisper_model_size, device=device, compute_type=compute_type)
                segments, info = model.transcribe(audio_path, language=language)
                timed_segments = []
                text_parts = []
                for seg in segments:
                    text = (seg.text or "").strip()
                    timed_segments.append((float(seg.start), float(seg.end), text))
                    if text:
                        text_parts.append(text)
                full_text = " ".join(text_parts).strip()
                config.CACHE.set(cache_key, (full_text, timed_segments, info))
                return full_text, timed_segments, info
            elif self.lyrics_whisper_engine == "insanely-fast-whisper":
                from . import pgfx_fast_transcriber as transcriber
            else:
                raise ImportError(f"Unknown whisper_engine: {self.lyrics_whisper_engine}")

            result = transcriber.transcribe_audio(
                audio_path, self.lyrics_whisper_model_size, self.lyrics_whisper_language
            )
            # Unpack the result to get full_text, timed_segments, and info
            full_text, timed_segments, info = result 
            config.CACHE.set(cache_key, (full_text, timed_segments, info))
            return full_text, timed_segments, info

        except Exception as e:
            print(f"\033[91m[MusicVideo-AudioDept] Error during transcription: {e}\033[0m")
            return f"[Error during transcription: {e}]", None, None # Return None for info as well

    def _align_and_correct_lyrics(self, whisper_transcript, initial_timed_segments, user_lyrics, audio_path):
        """Agent A3: Aligns, corrects, and finalizes the lyrics and their timings."""
        print("\033[94m[MusicVideo-AudioDept] Agent A3: Aligning and Finalizing Lyrics...\033[0m")
    
        # Generate spectrogram regardless of other steps
        spectrogram_preview = None
        if audio_path:
            try:
                import torchaudio

                try:
                    torchaudio.set_audio_backend("soundfile")
                except Exception:
                    pass
                waveform, sample_rate = torchaudio.load(audio_path)
                audio_np = waveform.mean(dim=0).cpu().numpy() if waveform.ndim > 1 else waveform.cpu().numpy()
                spectrogram_preview = utils.audio_to_spectrogram(audio_np, sample_rate)
            except Exception as e:
                print(f"\033[93m[MusicVideo-AudioDept] Warning: Could not generate spectrogram preview: {e}\033[0m")
                spectrogram_preview = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
    
        # Determine the definitive text to be used for alignment.
        # Priority: User-provided lyrics > Whisper transcript.
        text_to_align = user_lyrics if user_lyrics and user_lyrics.strip() else whisper_transcript
    
        if not text_to_align or text_to_align.startswith("[Error") or not audio_path:
            print("\033[91m[MusicVideo-AudioDept] No valid lyrics or transcript available for alignment. Cannot generate timed segments.\033[0m")
            return text_to_align, None, spectrogram_preview
    
        # If alignment is disabled, we just return the text without timings.
        if not self.lyrics_use_audio_alignment:
            print("\033[93m[MusicVideo-AudioDept] Audio alignment is disabled. Returning raw text without timings.\033[0m")
            return text_to_align, None, spectrogram_preview
    
        # --- NEW: Direct, more reliable alignment using whisperx ---
        print(f"\033[94m[MusicVideo-AudioDept] Aligning text with audio using whisperx (model: {self.lyrics_whisper_model_size})...\033[0m")
        try:
            import whisperx
            device = "cuda" if torch.cuda.is_available() else "cpu"
            
            # Load the base model for transcription hints.
            # We use the initial ASR segments to guide the alignment of the (potentially different) final text.
            model = whisperx.load_model(self.lyrics_whisper_model_size, device, compute_type="float16")
            audio = whisperx.load_audio(audio_path)
            
            # This is the key step: align the ground truth `text_to_align` with the audio.
            # We provide the original segments as a guide.
            result = whisperx.align(
                initial_timed_segments, model, {"language": self.lyrics_whisper_language}, audio, device,
                return_char_alignments=False
            )
            
            final_timed_segments = result.get("segments")
            print("\033[92m[MusicVideo-AudioDept] Direct alignment successful.\033[0m")
            return text_to_align, final_timed_segments, spectrogram_preview

        except Exception as e:
            print(f"\033[91m[MusicVideo-AudioDept] CRITICAL: Direct audio alignment with whisperx failed: {e}\033[0m")
            if initial_timed_segments:
                print("\033[93m[MusicVideo-AudioDept] Falling back to transcription segment timings instead of text-only mode.\033[0m")
                return text_to_align, initial_timed_segments, spectrogram_preview
            print("\033[93m[MusicVideo-AudioDept] This can be due to VRAM issues or a mismatch between lyrics and audio. Falling back to text-only mode.\033[0m")
            return text_to_align, None, spectrogram_preview
    
    def _lyrics_agent_finalize_assets(self, final_timed_segments, spectrogram_preview, audio_info):
        """Agent P1: Finalizes SRT string and audio metadata."""
        print("\033[94m[MusicVideo-PostProd] Agent P1: Finalizing assets...\033[0m")
        final_srt_string = utils.to_srt(final_timed_segments) if final_timed_segments else ""
        
        audio_meta = {
            "timed_segments": final_timed_segments,
            "spectrogram_preview": spectrogram_preview,
            "fps": self.lyrics_fps,
            "scene_splitting_mode": self.lyrics_scene_splitting_mode,
            "max_scene_frames": self.lyrics_max_scene_frames,
            "max_scene_duration_seconds": self.lyrics_max_scene_duration_seconds,
            "duration": audio_info.duration if audio_info and hasattr(audio_info, 'duration') else 0,
            "language": audio_info.language if audio_info and hasattr(audio_info, 'language') else "unknown",
        }
        return final_srt_string, audio_meta
