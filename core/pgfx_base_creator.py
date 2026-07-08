# Standard library imports
import os
import shutil
import re
import json
import time
import random
import copy
import concurrent.futures
import threading
import collections
import warnings
import textwrap
from pathlib import Path
from typing import Union

# Third-party imports
import torch
from PIL import Image
import librosa

# ComfyUI imports
import comfy.utils

# Local module imports
# Local module imports
from . import pgfx_api_clients as api_clients
from . import pgfx_config as config
from . import pgfx_thinking_engine as thinking_process
from .profiles import pgfx_style_profiles as style_profiles

from ..utils import pgfx_utils as utils
from ..utils import pgfx_json_utils as json_utils
from ..utils import pgfx_text_io as text_io


class PromptCrafter_BaseCreator:
    # noqa
    _vrg_fallback_words = ["standing", "sitting", "laying", "resting", "waiting", "walking", "dancing", "looking", "thinking"]
    _content_analysis_cache = {}

    @classmethod
    def _llm_runtime_kwargs(cls, run_config):
        if run_config is None:
            return {}
        return {
            "llm_device": getattr(run_config, "llm_device", getattr(config, "DEFAULT_LLM_DEVICE", "Default (GPU)")),
            "reset_context": bool(getattr(run_config, "reset_context", getattr(config, "DEFAULT_LLM_STATELESS", True))),
        }

    @classmethod
    def _query_llm(cls, model, prompt, run_config=None, images=None, **kwargs):
        llm_kwargs = cls._llm_runtime_kwargs(run_config)
        llm_kwargs.update(kwargs)
        return api_clients.query_model_auto(model, prompt, images=images, **llm_kwargs)

    @classmethod
    def _reason_with_llm(cls, model, prompt, run_config=None, images=None, **kwargs):
        llm_kwargs = cls._llm_runtime_kwargs(run_config)
        llm_kwargs.update(kwargs)
        return api_clients._reason_with_model(model, prompt, images=images, **llm_kwargs)

    @staticmethod
    def _format_output_text(text, output_format, label="text"):
        return text_io.format_text_payload(text, output_format, label=label)

    @staticmethod
    def _format_schedule_output(schedule_text, output_format):
        formatted, err = text_io.format_schedule_text(schedule_text, output_format)
        if err:
            print(f"\033[91m[PromptCrafter] {err}\033[0m")
            return schedule_text
        return formatted

    @classmethod
    def _apply_output_formatting(cls, prompt_text, schedule_text, output_target, output_format):
        outputs = {
            "Prompt": prompt_text,
            "Schedule": schedule_text,
        }
        formatted = cls._apply_output_formatting_map(outputs, output_target, output_format, text_io.OUTPUT_TARGET_OPTIONS)
        return formatted.get("Prompt", prompt_text), formatted.get("Schedule", schedule_text)

    @classmethod
    def _apply_output_formatting_map(cls, outputs, output_target, output_format, available_targets):
        if not outputs:
            return {}
        formatted = dict(outputs)
        selected = text_io.resolve_selected_targets(output_target, available_targets)
        for target in selected:
            if target not in formatted:
                continue
            if target == "Schedule":
                formatted[target] = cls._format_schedule_output(formatted[target], output_format)
            else:
                label = target.lower().replace(" ", "_")
                formatted[target] = cls._format_output_text(formatted[target], output_format, label=label)
        return formatted

    @staticmethod
    def _auto_save_outputs(outputs, auto_save_target, output_format, folder_path, filename_template, file_type, replacements):
        if not outputs or not auto_save_target:
            return

        resolved_type = text_io.resolve_file_type(file_type, output_format)
        base_replacements = dict(replacements or {})
        base_replacements["format"] = output_format.replace(" ", "_").lower()
        base_replacements["file_type"] = resolved_type

        selected = text_io.resolve_selected_targets(auto_save_target, list(outputs.keys()))

        for target_name, text_val in outputs.items():
            if target_name not in selected:
                continue
            if text_val is None or not str(text_val).strip():
                continue
            replacements_for_target = dict(base_replacements)
            replacements_for_target["target"] = target_name.lower().replace(" ", "_")
            try:
                text_io.save_text_to_file(
                    text_val,
                    folder_path,
                    filename_template,
                    resolved_type,
                    replacements=replacements_for_target,
                )
            except Exception as e:
                print(f"\033[91m[PromptCrafter] Auto-save failed for {target_name}: {e}\033[0m")

    @classmethod
    def _analyze_content_for_direction(cls, content, content_type="text"):
        """Analyzes content. Returns empty dict."""
        return {"recommended_approach": {}}

    @classmethod
    def _enhance_prompt_with_talent_direction(cls, prompt, original_content="", target_model="Generic Video"):
        """Applies model-specific prompt formatting rules for better generation quality."""
        if not prompt or not prompt.strip():
            return prompt

        target_model_lower = target_model.lower() if target_model else ""
        is_ltx2 = any(kw in target_model_lower for kw in ["ltx-2", "ltx2", "ltx 2"])

        if is_ltx2:
            # Ensure LTX-2 best practices: single paragraph, present tense, no markdown
            cleaned = prompt.strip().strip("'\"").strip()
            cleaned = re.sub(r'\n+', ' ', cleaned)
            cleaned = re.sub(r'\s+', ' ', cleaned)
            return cleaned

        return prompt

    @classmethod
    def _generate_directed_prompts(cls, content_list, target_model="Generic Video", content_type="text"):
        """Generate prompts without talent direction."""
        enhanced_prompts = []
        for i, content in enumerate(content_list):
            if not content:
                enhanced_prompts.append("")
            else:
                enhanced_prompts.append(content)
        return enhanced_prompts

    @classmethod
    def _create_directed_schedule(cls, prompts, timing_data=None, target_model="Generic Video"):
        """Create schedule with talent-directed prompts."""
        if not prompts:
            return "{}"
            
        # Enhance all prompts with talent direction
        enhanced_prompts = cls._generate_directed_prompts(prompts, target_model, "video")

        schedule = collections.OrderedDict()
        
        if timing_data and len(timing_data) == len(enhanced_prompts):
            for i, (prompt, timing) in enumerate(zip(enhanced_prompts, timing_data)):
                start_time = timing[0] if isinstance(timing, (list, tuple)) else i * 5.0
                frame_number = int(start_time * 16)
                schedule[frame_number] = prompt
        else:
            for i, prompt in enumerate(enhanced_prompts):
                frame_number = i * 80
                schedule[frame_number] = prompt
                
        schedule_items = [f'\"{str(key)}\": {json.dumps(str(value))}' for key, value in schedule.items()]
        return "{\n" + ",\n".join(schedule_items) + "\n}"

    @staticmethod
    def _vrg_count_words(line):
        return len(re.findall(r'\w+', line))

    @staticmethod
    def _vrg_collapse_repeats(line):
        tokens = line.split()
        result = []
        last_word = None
        repeat_count = 0
        for word in tokens:
            if word.lower() == last_word:
                repeat_count += 1
            else:
                last_word = word.lower()
                repeat_count = 1
            if repeat_count <= 3:
                result.append(word)
        cleaned = []
        prev = None
        for word in result:
            if word.lower() == prev:
                continue
            cleaned.append(word)
            prev = word.lower()
        return " ".join(cleaned)

    @classmethod
    def _vrg_enrich_lyrics(cls, timed_segments):
        if not timed_segments:
            return ""

        transcriptions = [seg[2] for seg in timed_segments]
        safe_transcriptions = [t if t else random.choice(cls._vrg_fallback_words) for t in transcriptions]
        enriched_transcriptions = []

        for i in range(len(safe_transcriptions)):
            pieces = []

            if i > 0:
                pieces.append(safe_transcriptions[i - 1].strip())

            pieces.append(safe_transcriptions[i].strip())

            combined = " ".join(pieces).strip()
            word_count = cls._vrg_count_words(combined)

            j = i + 1
            while word_count < 4 and j < len(safe_transcriptions):
                combined += " " + safe_transcriptions[j].strip()
                word_count = cls._vrg_count_words(combined)
                j += 1

            if word_count < 4:
                combined = random.choice(cls._vrg_fallback_words) + " " + combined

            enriched_transcriptions.append(cls._vrg_collapse_repeats(combined.strip()))

        return " | ".join(enriched_transcriptions)
        
    @classmethod
    def _describe_images(cls, images_with_weights, run_config):
        """Generates descriptions for a list of images using a vision model with retry logic."""
        if not images_with_weights:
            return None, None, None

        all_descriptions = []
        all_subjects = []
        full_context = ""
        
        describe_model = run_config.thinking_model if run_config.thinking_model and "None" not in run_config.thinking_model else run_config.model
        max_retries = run_config.max_retries
        persona = run_config.style_profile.get("persona", "You are a mythologist and expert in fantasy creature and character design.")

        for i, (image, weight) in enumerate(images_with_weights):
            if image is None:
                continue

            ok = False
            result_data = None
            
            desc_prompt = cls._build_image_description_prompt(persona, i + 1, run_config.language, run_config.safe_mode)

            # --- Retry logic ---
            for attempt in range(max_retries + 1):
                ok, result_data = cls._reason_with_llm(
                    describe_model, 
                    desc_prompt, 
                    run_config=run_config,
                    images=[image], 
                    use_chat_api=run_config.use_chat_api,
                    temperature=run_config.temperature, 
                    seed=run_config.seed, 
                    timeout=run_config.timeout,
                    debug_mode=run_config.debug_mode, 
                    debug_title=f"Image Description {i + 1}"
                )

                if ok and isinstance(result_data, dict) and result_data.get("description"):
                    break # Success
                elif attempt < max_retries:
                    print(f"\033[93m[PromptCrafter] Attempt {attempt + 1} to describe image {i + 1} failed or returned empty. Retrying...\033[0m")
            
            if ok and isinstance(result_data, dict):
                description = result_data.get("description", "").strip()
                subject = result_data.get("primary_subject", "").strip()
                if description:
                    all_descriptions.append(description)
                    all_subjects.append(subject)
                    full_context += f"Image {i+1} (Weight: {weight:.2f}): {description}\n\n"
                else:
                    error_message = "Model returned empty description."
                    print(f"\033[91m[PromptCrafter] Error describing image {i+1}: {error_message}\033[0m")
                    fallback_desc = "a photo of a [subject]"
                    all_descriptions.append(fallback_desc)
                    all_subjects.append("[subject]")
                    full_context += f"Image {i+1} (Weight: {weight:.2f}): {fallback_desc}\n\n"
            else:
                error_message = result_data if isinstance(result_data, str) else "Unknown error after all retries."
                print(f"\033[91m[PromptCrafter] Failed to describe image {i+1} after {max_retries + 1} attempts: {error_message}\033[0m")                
                fallback_desc = "a photo of a [subject]"
                all_descriptions.append(fallback_desc)
                all_subjects.append("[subject]")
                full_context += f"Image {i+1} (Weight: {weight:.2f}): {fallback_desc}\n\n"

        return full_context.strip(), all_descriptions, all_subjects
    
    @classmethod
    def _describe_one_image_with_persona(cls, img, weight, idx, run_config):
        persona = run_config.style_profile.get("persona", "You are an expert art historian.")
        desc_prompt = cls._build_image_description_prompt(persona, idx, run_config.language, run_config.safe_mode)
        ok, result_json = cls._reason_with_llm(
            run_config.model, desc_prompt, images=[img], use_chat_api=run_config.use_chat_api,
            run_config=run_config,
            temperature=run_config.temperature, seed=run_config.seed, timeout=run_config.timeout,
            debug_mode=run_config.debug_mode, debug_title=f"Image Description {idx}")

        if ok and isinstance(result_json, dict):
            desc_text = utils.TextCleaner.single_paragraph(result_json.get("description", ""))
            primary_subject = result_json.get("primary_subject", "")
            return {"full_text": f"Image {idx} (Weight: {weight:.2f}): {desc_text}", "primary_subject": primary_subject}
        else:
            return {"full_text": f"Image {idx} (Weight: {weight:.2f}): [Error describing image: {result_json}]", "primary_subject": ""}

    @staticmethod
    def _build_image_description_prompt(persona, idx, language, safe_mode):
        safety_rule = f"\n{config.SAFE_MODE_RULE}" if safe_mode else ""
        return f"""{persona}
Analyze Image {idx} and provide a detailed, one-paragraph description and identify the single primary subject.

Your task is to describe the visual elements of the scene factually, identify the single most important subject, and transcribe any readable text.

Example:
{{ "primary_subject": "a woman with long brown hair", "description": "A photo of a woman with long brown hair wearing a red dress, standing in a sunlit forest. The background is filled with green trees and dappled light." }}

Return ONLY a JSON object with two keys:
- \"primary_subject\": (string) The single most important subject in the image (e.g., \"a majestic stag\", \"a woman in an elegant dress\").
- \"description\": (string) The full, one-paragraph description of the entire scene.

The final output must be in {language} only.{safety_rule}"""

    @classmethod
    def _is_speech_prompt_request(cls, user_text, run_config):
        """Analyzes user text to determine if it's a request for a speech/dialogue prompt."""
        speech_keywords = ["speech prompt", "saying:", "exclaiming", "dialogue"]
        speech_tag_pattern = re.compile(r'<S>.*<E>', re.IGNORECASE | re.DOTALL)

        if any(keyword in user_text.lower() for keyword in speech_keywords) or speech_tag_pattern.search(user_text):
            utils._debug_print(run_config.debug_mode, "Speech Prompt Check", "Pattern match found, confirming with AI.")
            prompt = textwrap.dedent(f'''
                Analyze the user's request. Is the user asking to create a text prompt that includes dialogue, speech, or specific text to be spoken by a subject, often using tags like <S> and <E>?

                --- USER REQUEST ---
                A cinematic shot of a [character] singing the lyrics | A dramatic close-up of the [character] as they deliver the final line
                Core Rules:
                - [Shot Type] -> [Character] [Action] [Setting]
                - All prompts must be cinematic.
                Lyrics:
                I'm walking on sunshine | and don't it feel good
                ---

                Based on the user request above, which contains pipe separators and mentions lyrics, the correct response is:
                {{"is_lyrics_request": true}}
            ''').strip()
            
            ok, result = cls._query_llm(
                run_config.model, prompt, use_chat_api=run_config.use_chat_api, temperature=0.0, 
                run_config=run_config,
                seed=run_config.seed, debug_mode=run_config.debug_mode, 
                debug_title="Speech Intent Check", timeout=run_config.timeout
            )
            
            if ok and isinstance(result, dict) and result.get("is_speech_request"):
                return True
        
        return False

    @classmethod
    def _handle_speech_prompt_request(cls, user_text, images_with_weights, run_config, max_images=5):
            """Handles the specific case of generating a formatted speech prompt."""
            try:
                print("\033[94m[PromptCrafter] Speech prompt format detected. Using specialized handler...\033[0m")
                
                if not images_with_weights:
                    return ("Speech prompt generation requires an image to identify the subject.", None, None, None, None, None) + (None,) * max_images

                describe_result = cls._describe_images(images_with_weights, run_config)
                if describe_result is not None:
                    image_context, _, primary_subjects = describe_result
                else:
                    image_context, primary_subjects = "No reference images provided.", []
                
                subject_description = "A subject"
                if primary_subjects:
                    subject_description = re.sub(r'^\s*\[PRIMARY\]\s*', '', primary_subjects[0]).strip()
                
                prompt = textwrap.dedent(f'''
                    You are a creative writer. Your task is to generate a single, formatted speech prompt based on the user's instructions.

                    --- USER INSTRUCTIONS ---
                    {user_text}
                    ---
                    
                    --- SUBJECT DESCRIPTION ---
                    The primary subject of the scene is: {subject_description}
                    ---

                    TASK:
                    1.  Follow the user's specified format EXACTLY.
                    2.  Replace the placeholder for the subject description (e.g., `<describe subject>`) with the provided SUBJECT DESCRIPTION.
                    3.  Invent a unique, creative, and contextually appropriate line of dialogue for the subject to say, and place it inside the speech tags (e.g., `<S>...</E>`).
                    4.  If the user's instructions mention a specific tone (e.g., "ironically funny"), adhere to it.

                    Return ONLY the final, formatted prompt string. Do not include any commentary.
                ''').strip()

                ok, final_prompt = cls._query_llm(
                    run_config.model, prompt, prefer_chat=True, temperature=run_config.temperature,
                    run_config=run_config,
                    seed=run_config.seed, debug_mode=run_config.debug_mode,
                    debug_title="Speech Prompt Generation", timeout=run_config.timeout
                )

                if not ok:
                    return (f"Failed to generate speech prompt: {final_prompt}", None, None, None, None, None) + (None,) * max_images

                audcap_prompt = textwrap.dedent(f'''
                    You are an expert audio engineer. Analyze the following scene description and dialogue.
                    Generate a concise audio description for the <AUDCAP> tag.
                    - Describe the voice (e.g., "Clear older male voice", "Young female voice, whispering").
                    - Describe the speech itself (e.g., "speaking dialogue sarcastically").
                    - Add 1-2 relevant, subtle background sounds (e.g., "subtle outdoor ambience", "faint city noise").
                    - Be concise. Keep the description to one sentence.

                    --- SCENE & DIALOGUE ---
                    {final_prompt}
                    ---

                    Return ONLY the audio description text (e.g., "Clear older male voice speaking dialogue sarcastically, subtle outdoor ambience.")
                    Do not include the <AUDCAP> tags yourself.
                ''').strip()

                ok_aud, aud_desc = cls._query_llm(
                    run_config.model, audcap_prompt, prefer_chat=True, temperature=0.1, # Low temp for factual description
                    run_config=run_config,
                    seed=run_config.seed, debug_mode=run_config.debug_mode,
                    debug_title="OVI <AUDCAP> Generation", timeout=run_config.timeout
                )

                ovi_formatted_prompt = final_prompt
                if ok_aud and aud_desc.strip():
                    ovi_formatted_prompt = f"{final_prompt.strip().rstrip('.')}\n<AUDCAP> {aud_desc.strip()} <ENDAUDCAP>"
                else:
                    print(f"\033[93m[PromptCrafter] Warning: Could not generate <AUDCAP> description. Returning speech prompt without it. Error: {aud_desc}\033[0m")

                passthrough_images = [img for img, _ in images_with_weights]
                passthrough_images.extend([None] * (max_images - len(passthrough_images)))
                
                return (ovi_formatted_prompt, "", image_context, "", run_config.model, str(run_config.seed)) + tuple(passthrough_images)
            except Exception as e:
                return cls._handle_creator_exception(e, max_images + 6)

    @classmethod
    def _is_lyrics_to_prompt_request(cls, user_text, run_config):
            """Analyzes user text to determine if it's a request for the multi-prompt lyric generator."""
            lyrics_keywords = ["lyrics:", "lyric-driven prompts", "lyric fragment", "[shot type]"]
            
            text_lower = user_text.lower()
            if any(keyword in text_lower for keyword in lyrics_keywords) and "|" in user_text:
                utils._debug_print(run_config.debug_mode, "Lyrics-to-Prompt Check", "Pattern match found, confirming with AI.")
                prompt = textwrap.dedent(f'''
                    Analyze the user's request. Is the user asking to generate a list of video prompts, where each prompt corresponds to a pipe-separated (|) lyric fragment?
                    The instructions often mention "Lyric-Driven Prompts", "Core Rules", "[Shot Type] -> [Character]", and a "Lyrics:" section.

                    --- USER REQUEST ---
                    {user_text}
                    ---

                    Respond with ONLY a JSON object: {{'is_lyrics_request': true/false}}
                ''').strip()
                
                ok, result = cls._reason_with_llm(
                    run_config.model, prompt, use_chat_api=run_config.use_chat_api, temperature=0.0, 
                    run_config=run_config,
                    seed=run_config.seed, debug_mode=run_config.debug_mode, 
                    debug_title="Lyrics-to-Prompt Intent Check", timeout=run_config.timeout
                )
                
                if ok and isinstance(result, dict) and result.get("is_lyrics_request"):
                    return True
            
            return False

    @classmethod
    def _build_style_and_composition_rules(cls, mode, images, run_config, user_text, user_negative_prompt, image_context):
        """
        Analyzes style and composition to create a reusable set of rules for prompt generation.
        This is a helper for the scheduled mode's prompt generation.
        """
        style_profile = run_config.style_profile
        
        if style_profile and style_profile.get("inspiration"):
            return {"inspiration": style_profile.get("inspiration")}

        analysis_prompt = textwrap.dedent(f"""
            You are an expert art director and film theorist. Analyze the user's request and reference image context to define the core artistic style and composition.

            **User Request:**
            ---
            {user_text}
            ---

            **Reference Image Context:**
            ---
            {image_context}
            ---

            **Your Task:**
            Return a JSON object with one key: "inspiration".
            The "inspiration" value should be a concise, one-sentence string describing the overall visual style, citing 2-3 artistic or cinematic influences.
            Example: {{'inspiration': "Composition inspired by the dramatic lighting of Caravaggio and the epic scale of a Ridley Scott film."}}

            Return ONLY the JSON object.
        """ ).strip()

        ok, result = cls._reason_with_llm(
            run_config.model,
            analysis_prompt,
            run_config=run_config,
            images=images,
            use_chat_api=run_config.use_chat_api,
            temperature=0.1,
            seed=run_config.seed,
            timeout=run_config.timeout,
            debug_mode=run_config.debug_mode,
            debug_title="Dynamic Style Analysis (Scheduled)",
        )
        return result if ok and isinstance(result, dict) else {}

    @classmethod
    def _handle_creator_exception(cls, e):
        import traceback
        import torch
        error_message = f"[PromptCrafter] Error: {e}"
        print(f"\033[91m{error_message}\n{traceback.format_exc()}\033[0m")
        
        # Dynamically determine the correct number of returns and their types
        return_types = getattr(cls, "RETURN_TYPES", ("STRING", "STRING"))
        results = []
        for i, t in enumerate(return_types):
            if i == 0:
                results.append(error_message)
            elif t == "IMAGE":
                # Return a dummy black 64x64 tensor to prevent downstream nodes from crashing on .shape access
                results.append(torch.zeros((1, 64, 64, 3)))
            elif t == "MASK":
                results.append(torch.zeros((64, 64)))
            elif t == "LATENT":
                results.append({"samples": torch.zeros((1, 4, 8, 8))})
            elif t == "CONDITIONING":
                results.append([[torch.zeros((1, 1, 1024)), {}]])
            elif t == "AUDIO":
                results.append({"waveform": torch.zeros((1, 1, 1024)), "sample_rate": 44100})
            elif t == "DICT":
                results.append({})
            elif t == "INT":
                results.append(0)
            elif t == "FLOAT":
                results.append(0.0)
            elif t == "BOOLEAN":
                results.append(False)
            else:
                results.append("")
        return tuple(results)

    @staticmethod
    def _collect_images_with_weights(**kwargs):
        """Collects all connected image tensors and their weights from the dynamic inputs."""
        images_with_weights = []
        image_count = kwargs.get("image_count", 1)
        image_weights_json = kwargs.get("image_weights_json", "{}")
        
        weights = {}
        try:
            parsed_weights = json_utils.extract_and_parse_json(image_weights_json)
            if isinstance(parsed_weights, dict):
                weights = parsed_weights
        except Exception:
            print(f"\033[93m[PromptCrafter] Warning: Could not parse image_weights_json. Using default weights. Value: {image_weights_json}\033[0m")

        for i in range(1, image_count + 1):
            image = kwargs.get(f"image_{i}")
            if image is not None:
                weight = float(weights.get(f"image_weight_{i}", 1.0))
                images_with_weights.append((image, weight))
        return images_with_weights

    @staticmethod
    def _prepare_run_parameters(prompt_type, temperature, max_length_words, original_temp, original_max_len): # noqa
        if temperature == original_temp:
            if prompt_type == "Video": temperature = 0.4

        if max_length_words == original_max_len:
            if prompt_type == "Image": max_length_words = 200
            elif prompt_type == "Video": max_length_words = 80
        return temperature, max_length_words

    @classmethod
    def _setup_config(cls, node_cls, mode, user_text, model, images_with_weights=None, **kwargs): # noqa
        if not model or "NO_MODELS_FOUND" in model or "OLLAMA_UNREACHABLE" in model:
            raise ValueError("No vision models found or Ollama is unreachable. Please install a vision model (e.g., 'ollama run llava') or configure a remote API key.")

        input_types = getattr(node_cls, "INPUT_TYPES", lambda: {"required": {}, "optional": {}})()
        original_temp = 0.2
        original_max_len = 0
        if "temperature" in input_types.get("required", {}):
            temp_config = input_types["required"]["temperature"]
            if isinstance(temp_config, (tuple, list)) and len(temp_config) > 1:
                original_temp = temp_config[1].get("default", 0.2)
        if "max_length_words" in input_types.get("required", {}):
            max_len_config = input_types["required"]["max_length_words"]
            if isinstance(max_len_config, (tuple, list)) and len(max_len_config) > 1:
                original_max_len = max_len_config[1].get("default", 0)
        temperature, max_length_words = cls._prepare_run_parameters(
            mode, kwargs.get('temperature'), kwargs.get('max_length_words'), original_temp, original_max_len
        )
        language = utils._detect_language(user_text)
        
        config_params = kwargs.copy()

        config_params.update({
            'model': model, 'language': language, 'temperature': temperature, 
            'max_length_words': max_length_words,
            'use_chat_api': kwargs.get('use_chat_api', True),
            'use_deep_think': kwargs.get('use_deep_think', True),
        })

        from dataclasses import fields
        config_fields = {f.name for f in fields(config.PromptCrafterRunConfig)}
        filtered_params = {k: v for k, v in config_params.items() if k in config_fields}

        run_config = config.PromptCrafterRunConfig(**filtered_params)
        
        style_tags = kwargs.get("style_tags", "").strip()
        if style_tags:
            print(f"\033[94m[PromptCrafter] Using style tags for multi-style blending: {style_tags}\033[0m")
            tag_names = [tag.strip() for tag in style_tags.split(',')]
            inspirations = []
            first_persona = "You are an expert art historian."
            
            for i, name in enumerate(tag_names):
                profile = style_profiles.NAMED_STYLE_PROFILES.get(name)
                if profile:
                    if i == 0: # Grab persona from the first tag
                        first_persona = profile.get("persona", first_persona)
                    inspirations.append(profile.get("inspiration", ""))
            
            run_config.style_profile = {"persona": first_persona, "inspiration": "\n- ".join(filter(None, inspirations))}
        elif run_config.style_override and run_config.style_override != "None":
            original_name = re.sub(r'^\(.*\]\s*', '', run_config.style_override)
            if original_name in style_profiles.NAMED_STYLE_PROFILES:
                run_config.style_profile = style_profiles.NAMED_STYLE_PROFILES[original_name]
        else:
            run_config.style_profile = {}

        return run_config

    @classmethod
    def _handle_creative_intent(cls, mode, user_text, images_with_weights, run_config): # noqa
        has_text = user_text and user_text.strip() and user_text.strip() != config.DEFAULT_PROMPT_TEXT
        has_images = bool(images_with_weights)

        if has_text and not has_images:
            image_keywords = ["image", "images", "picture", "pictures", "photo", "reference", "input"]
            if any(kw in user_text.lower() for kw in image_keywords):
                print("\033[94m[PromptCrafter] User text mentions images, but none are connected. Using AI to confirm intent...\033[0m")
                prompt = f"""Analyze the user's request. Does it explicitly mention using input images, reference images, or the provided images?
- If it says \"using the images\", \"based on the pictures\", etc., answer YES.
- If it just describes a scene (e.g., \"create an image of a woman\", answer NO.
---
USER REQUEST ---
{user_text}
---
Respond with ONLY a JSON object: {{'requires_images': true/false}}""" .strip()
                ok, result = cls._reason_with_llm(
                    run_config.model,
                    prompt,
                    run_config=run_config,
                    use_chat_api=run_config.use_chat_api,
                    temperature=0.0,
                    seed=run_config.seed,
                    debug_mode=run_config.debug_mode,
                    debug_title="Image Intent Check",
                )
                if ok and isinstance(result, dict) and result.get("requires_images"):
                    return "Your instructions appear to refer to input images, but none were connected. Please connect reference images or rephrase your instructions.", None

        elif has_images and not has_text:
            print("\033[94m[PromptCrafter] Images provided but no text. Engaging creative autopilot to generate instructions...\033[0m")
            describe_result = cls._describe_images(images_with_weights, run_config)
            if describe_result:
                image_context, _, _ = describe_result
            else:
                image_context = ""
            prompt = f"""You are a creative director. Analyze the following image descriptions and invent a high-level, single-paragraph instruction for a new, creative scene that uses the subjects from the images.
- Be imaginative. Suggest a new scenario, interaction, or story.
- Do NOT just describe the images. Create a new concept.
- Example: If given images of a knight and a dragon, you might suggest: \"A cinematic scene where the knight and the dragon are not fighting, but instead stand together on a clifftop, looking out over a vast, misty valley as allies.\"

--- IMAGE DESCRIPTIONS ---
{image_context}
---
Return ONLY the single-paragraph creative instruction. No commentary.""" .strip()
            ok, new_instruction = cls._query_llm(
                run_config.model,
                prompt,
                run_config=run_config,
                prefer_chat=True,
                temperature=0.7,
                seed=run_config.seed,
                debug_mode=run_config.debug_mode,
                debug_title="Creative Autopilot",
            )
            if ok and new_instruction:
                print(f"\033[92m[PromptCrafter] Creative Autopilot generated instruction: {new_instruction}\033[0m")
                return None, new_instruction
            else:
                return "Creative Autopilot failed to generate instructions from the images. Please provide text instructions or check your model.", None

        return None, None

    @classmethod
    def _handle_scheduled_mode(cls, mode, user_text, images_with_weights, run_config, **kwargs): # noqa
        images = [img for img, _ in images_with_weights]
        describe_result = cls._describe_images(images_with_weights, run_config)
        if describe_result:
            image_context_for_all, _, primary_subjects_from_images = describe_result
        else:
            image_context_for_all, primary_subjects_from_images = "", []
        style_rules = cls._build_style_and_composition_rules(mode, images, run_config, user_text, "", image_context_for_all)
        user_negative_prompt = kwargs.get("negative_prompt", "")
        ai_negative_prompt = utils._generate_negative_prompt(user_text, run_config, user_negative_prompt="")
        parts = [p for p in [user_negative_prompt, ai_negative_prompt] if p and p.strip()]
        base_negative_prompt = ", ".join(parts)

        if '\n\n' in user_text:
            print("\033[94m[PromptCrafter] Multi-paragraph input detected. Using manual scene breaks.\033[0m")
            scenes = [p.strip() for p in user_text.split('\n\n') if p.strip()]
        else:
            scenes = utils._generate_storyboard_from_instruction_with_ai(user_text, image_context_for_all, primary_subjects_from_images, run_config)

        if not scenes:
            return ("", "AI failed to generate or split the text into a storyboard. Please try rephrasing your request or check the model.", "", "")

        print(f"\033[94m[PromptCrafter] Schedule mode enabled. Generating prompts for {len(scenes)} scenes...\033[0m")

        generated_prompts: list[str] = [""] * len(scenes)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(scenes))) as executor:
            future_to_index = {executor.submit(cls._generate_prompt_for_scene, scene_text, mode, images_with_weights, image_context_for_all, style_rules, run_config, primary_subjects_from_images=primary_subjects_from_images, **kwargs): i for i, scene_text in enumerate(scenes)}
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result = future.result()
                    if result is None: result = ""
                    generated_prompts[index] = str(result)
                    print(f"\033[92m[PromptCrafter] Finished processing scene {index + 1}/{len(scenes)}.\033[0m")
                except Exception as exc:
                    error_msg = f"[Error processing scene {index + 1}: {exc}]"
                    generated_prompts[index] = error_msg
                    print(f'\033[91m[PromptCrafter] {error_msg}\033[0m')

        if not any(generated_prompts):
            return ("", "Failed to generate prompts for any of the scenes. Please check the model and logs.", image_context_for_all, base_negative_prompt)

        target_model_format = kwargs.get("target_model_format", "Generic")
        if target_model_format != "Generic (SD1.5, SD2.1)":
            print(f"\033[94m[PromptCrafter] Applying '{target_model_format}' formatting to {len(generated_prompts)} scheduled scenes...\033[0m")
            formatted_prompts = [cls._format_prompt_for_target(p, target_model_format) if not p.startswith("[Error:") else p for p in generated_prompts]
            generated_prompts = formatted_prompts

        schedule_json = utils._create_schedule_from_items(generated_prompts, kwargs.get("max_frames", 240), 0, kwargs.get("interpolate_keyframes", True), kwargs.get("interpolation_frame_interval", 10))
                
        return ("", schedule_json, image_context_for_all, base_negative_prompt)

    @classmethod
    def _generate_initial_draft(cls, mode, user_instructions, user_context, image_context, 
                          mandatory_tokens, images, run_config, primary_subjects_from_images=None):
        """Generate initial draft with talent direction enhancement."""
        merge_prompt = cls._build_initial_merge_prompt(mode, user_instructions, user_context, 
                                                      image_context, mandatory_tokens, images, 
                                                      run_config, primary_subjects_from_images)
        
        generation_kwargs = {
            "prefer_chat": run_config.use_chat_api, "temperature": run_config.temperature, 
            "seed": run_config.seed, "timeout": 120, "debug_mode": run_config.debug_mode
        }
        
        refinements = getattr(run_config, 'deep_think_refinements', 3)
        
        if run_config.use_deep_think and refinements > 0:
            print("\033[94m[PromptCrafter] Deep Think enabled. Starting iterative refinement...\033[0m")
            generation_kwargs["debug_title"] = f"Initial {mode} Prompt (Deep Think)"
            generation_kwargs["images"] = images
            ok, scene_prompt = utils._deep_think_and_refine(
                run_config.model, merge_prompt, max_iterations=refinements, 
                confidence_threshold=run_config.deep_think_confidence, **generation_kwargs
            )
        else:
            if run_config.use_deep_think and refinements == 0:
                print("\033[94m[PromptCrafter] Deep Think disabled by setting refinements to 0.\033[0m")
            generation_kwargs["debug_title"] = f"Initial {mode} Prompt"
            ok, scene_prompt = cls._query_llm(run_config.model, merge_prompt, run_config=run_config, **generation_kwargs)
        
        if ok and scene_prompt:
            original_content = f"{user_instructions} {user_context}".strip()
            enhanced_prompt = cls._enhance_prompt_with_talent_direction(
                utils.TextCleaner.single_paragraph(scene_prompt), 
                original_content, 
                run_config.target_model_format
            )
            return (True, enhanced_prompt)
        else:
            return (False, f"Ollama error: {scene_prompt}")

    @staticmethod
    def _format_prompt_for_target(prompt, target_format):
            prompt_text = str(prompt).strip().rstrip(',')
            
            if target_format == "Generic (SD1.5, SD2.1)": return prompt_text
            elif target_format == "Fooocus": return f"{prompt_text} --style cinematic-default"
            elif target_format == "Stable Diffusion 3": return prompt_text
            elif target_format == "Stable Cascade": return prompt_text
            elif target_format == "FLUX / Qwen / Hunyuan": return f"{prompt_text}, masterpiece, high quality, 8k"
            elif target_format in ("LTX-2 (Audio/Lip Sync/Retake)", "Generic Video (Wan, etc.)"): return prompt_text
            else: return prompt_text

    @classmethod
    def _generate_prompt_for_scene(cls, scene_text, mode, images_with_weights, image_context_for_all, style_rules, run_config, primary_subjects_from_images=None, **kwargs): # noqa
        if primary_subjects_from_images is None:
            primary_subjects_from_images = []
        elif isinstance(primary_subjects_from_images, str):
            primary_subjects_from_images = [primary_subjects_from_images]
        elif not isinstance(primary_subjects_from_images, list):
            primary_subjects_from_images = list(primary_subjects_from_images)

        primary_subjects_from_images = [str(s).strip() for s in primary_subjects_from_images if s and str(s).strip()]

        config_key_parts = (run_config.model, run_config.language, run_config.temperature, run_config.use_chat_api, run_config.max_length_words, run_config.seed, run_config.max_retries, run_config.critique_strength, run_config.simplify_for_diffusion, run_config.use_deep_think, str(run_config.style_profile))
        cache_key = utils._get_cache_key("gen_prompt_for_scene_v1", scene_text, mode, images_with_weights, image_context_for_all, style_rules, primary_subjects_from_images, config_key_parts)
        if config.CACHE.has(cache_key):
            print(f"\033[94m[PromptCrafter] Using cached prompt for scene.\033[0m")
            cached_prompt = config.CACHE.get(cache_key)
            return cls._enhance_prompt_with_talent_direction(cached_prompt, scene_text, run_config.target_model_format)

        images = [img for img, _ in images_with_weights]
        tok_ok, mandatory_tokens = utils._extract_mandatory_tokens_with_model(
            image_context_for_all, scene_text, run_config, primary_subjects_from_images
        )
        if not tok_ok and primary_subjects_from_images:
            tok_ok = True
            mandatory_tokens = {"primary": primary_subjects_from_images, "allowed_list": primary_subjects_from_images}
        if not tok_ok: 
            error_prompt = f"[Error extracting tokens for scene: {mandatory_tokens}]"
            return cls._enhance_prompt_with_talent_direction(error_prompt, scene_text, run_config.target_model_format)

        ok_draft, draft_or_err = cls._generate_initial_draft(
            mode, scene_text, "", image_context_for_all, mandatory_tokens, images, run_config, primary_subjects_from_images
        )
        
        if not ok_draft: 
            error_prompt = f"[Error generating draft for scene: {draft_or_err}]"
            return cls._enhance_prompt_with_talent_direction(error_prompt, scene_text, run_config.target_model_format)
            
        scene_prompt = cls._refine_image_video_prompt(
            draft_or_err, mode, mandatory_tokens, style_rules, run_config
        )
        
        new_positive, _ = utils._simplify_for_diffusion(scene_prompt, scene_text, run_config)
        
        enhanced_positive = cls._enhance_prompt_with_talent_direction(
            new_positive, scene_text, run_config.target_model_format
        )
        
        config.CACHE.set(cache_key, enhanced_positive)
        return enhanced_positive

    @staticmethod
    def _get_adjusted_temperature(base_temp, creativity_level):
        multiplier = 1.0 + (creativity_level - 5) * 0.1
        adjusted_temp = base_temp * multiplier
        return max(0.0, min(1.5, adjusted_temp))

    @staticmethod
    def _build_initial_merge_prompt(mode, user_text, user_negative_prompt, image_context, mandatory_tokens, images, run_config, all_primary_subjects):
        thought_process = thinking_process.ThoughtProcess(run_config=run_config, user_text=user_text, negative_prompt=user_negative_prompt, image_context=image_context, primary_subjects_from_images=all_primary_subjects, mode=mode)
        return thought_process._build_initial_merge_prompt(mode, user_text, user_negative_prompt, image_context, mandatory_tokens, images, run_config, all_primary_subjects)

    @staticmethod
    def _build_refinement_prompt(current_prompt, mode, primary_items, secondary_items, style_rules, run_config, ask_for_json=False):
        """Build a refinement prompt for iterative prompt improvement."""
        style_inspiration = style_rules.get("inspiration", "") if style_rules else ""
        refinement_prompt = textwrap.dedent(f"""
        You are an expert prompt engineer for AI image/video generation. Your task is to refine and improve the following prompt.

            **Current Prompt:**
            {current_prompt}

            **Mode:** {mode}
            **Style Inspiration:** {style_inspiration}

            **Your Task:**
            Refine the prompt to be more vivid, detailed, and optimized for {mode} generation. Enhance descriptive language while maintaining the core concept.
            
            Return the refined prompt only, without any commentary.
        """ ).strip()
        
        return refinement_prompt

    @classmethod
    def _refine_image_video_prompt(cls, draft_prompt, mode, mandatory_tokens, style_rules, run_config):
        current_prompt = draft_prompt
        primary_items_list = [(t or "") for t in (mandatory_tokens or {}).get("primary", [])]
        
        if not primary_items_list:
            critique_prompt = cls._build_refinement_prompt(current_prompt, mode, [], [], style_rules, run_config, ask_for_json=False)
            ok, revised_prompt = cls._query_llm(
                run_config.model, critique_prompt, prefer_chat=run_config.use_chat_api, 
                run_config=run_config,
                temperature=run_config.temperature, seed=run_config.seed, timeout=90, 
                debug_mode=run_config.debug_mode, debug_title="Image/Video Refine (Single Pass)"
            )
            refined_prompt = utils.TextCleaner.single_paragraph(revised_prompt if ok else current_prompt)
        else:
            refined_prompt = current_prompt
        
        if refined_prompt:
            enhanced_prompt = cls._enhance_prompt_with_talent_direction(
                refined_prompt, 
                refined_prompt,
                run_config.target_model_format
            )
            return enhanced_prompt
        else:
            return refined_prompt

    @classmethod
    def _analyze_lyrics_emotional_progression(cls, lyrics_text, timed_segments):
        """Analyze emotional progression throughout the lyrics."""
        if not lyrics_text: 
            return {}
        emotional_progression = {}
        lines = lyrics_text.split('\n')
        
        for i, line in enumerate(lines):
            if line.strip():
                analysis = cls._analyze_content_for_direction(line, "lyrics_line")
                emotional_tone = analysis.get("emotional_tone", "neutral")
                
                if timed_segments and i < len(timed_segments):
                    start_frame = int(timed_segments[i][0] * 16)
                    emotional_progression[start_frame] = emotional_tone
                else:
                    frame_number = i * 80
                    emotional_progression[frame_number] = emotional_tone
                    
        return emotional_progression

    @staticmethod
    def _get_timing_context_for_frame(frame_number, timed_segments):
        """Get timing context for a specific frame."""
        if not timed_segments: 
            return {"scene_type": "middle", "position": "middle"}
        time_seconds = frame_number / 16.0
        
        for i, (start, end, text) in enumerate(timed_segments):
            if start <= time_seconds <= end:
                position_ratio = i / len(timed_segments)
                if position_ratio < 0.2: 
                    scene_type = "intro"
                elif position_ratio > 0.8: 
                    scene_type = "outro"
                elif 0.4 <= position_ratio <= 0.6: 
                    scene_type = "climax"
                else: 
                    scene_type = "verse"
                    
                return {"scene_type": scene_type, "position": "early" if position_ratio < 0.5 else "late", "segment_index": i}
                
        return {"scene_type": "middle", "position": "middle"}

    @classmethod
    def _enhance_schedule_with_talent_direction(cls, schedule_json, original_content, target_model, timed_segments=None):
        """Enhance schedule with talent direction."""
        try:
            schedule_data = json_utils.extract_and_parse_json(schedule_json)
            if not isinstance(schedule_data, dict):
                return schedule_json
            if any(not str(frame).strip().isdigit() for frame in schedule_data.keys()):
                return schedule_json
            enhanced_schedule = {}
            
            if timed_segments is None:
                timed_segments = []
            
            emotional_arc = cls._analyze_lyrics_emotional_progression(original_content, timed_segments)
            
            for frame, prompt in schedule_data.items():
                if isinstance(prompt, str) and prompt.strip():
                    timing_context = cls._get_timing_context_for_frame(int(frame), timed_segments)
                    
                    enhanced_prompt = cls._enhance_prompt_with_talent_direction(
                        prompt, original_content, target_model
                    )
                    
                    if timing_context:
                        emotional_context = emotional_arc.get(int(frame), "neutral")
                        context_tags = f"[{timing_context['scene_type']}, {emotional_context} mood]"
                        enhanced_prompt = f"{context_tags} {enhanced_prompt}"
                    
                    enhanced_schedule[frame] = enhanced_prompt
                else:
                    enhanced_schedule[frame] = prompt
                    
            return json.dumps(enhanced_schedule, indent=4)
        except json.JSONDecodeError:
            return schedule_json
