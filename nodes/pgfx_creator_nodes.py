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
import torchaudio

# ComfyUI imports
import comfy.utils

# Local module imports
from ..core import pgfx_api_clients as api_clients
from ..core import pgfx_config as config
from ..core.profiles import pgfx_style_profiles as style_profiles
from ..utils import pgfx_utils as utils
from ..utils import pgfx_json_utils as json_utils
from ..utils import pgfx_text_io as text_io
from ..core.profiles import pgfx_organization_profiles as organization_profiles
from . import pgfx_audio_srt as pgfx_srt_creator
from ..core.profiles import pgfx_captioner_profiles as captioner_profiles
from ..core import pgfx_thinking_engine as thinking_process

# Suppress the specific UserWarning from speechbrain that is triggered by whisperx
# warnings.filterwarnings("ignore", category=UserWarning, module='speechbrain.inference')

# Suppress the specific UserWarning from speechbrain that is triggered by whisperx
# warnings.filterwarnings("ignore", category=UserWarning, module='speechbrain.inference')

def get_combined_models():
    """Helper to get a combined list of GGUF, HuggingFace and API models."""
    gguf_files = api_clients.get_local_llm_gguf_files()
    gguf_models = [f"gguf/{m}" for m in gguf_files if "not installed" not in m and "not_found" not in m and "error_scanning" not in m]
    
    hf_models = api_clients.get_local_hf_models()
    hf_models_formatted = [f"hf/{m}" for m in hf_models if "not installed" not in m]

    api_models = api_clients.get_all_models()
    # Combine lists, ensuring local models are listed first.
    combined = hf_models_formatted + gguf_models + [m for m in api_models if m not in hf_models_formatted + gguf_models]
    return combined


# ------------------------------------------------------------------------------------
# PromptCrafter Creator Nodes (Base, Image, Video, Lyrics)
# ------------------------------------------------------------------------------------
from ..core.pgfx_base_creator import PromptCrafter_BaseCreator
# ------------------------------------------------------------------------------------
# PromptCrafter_VisualCreator Node
# ------------------------------------------------------------------------------------
class PromptCrafter_VisualCreator(PromptCrafter_BaseCreator):
    DESCRIPTION = "Enhanced visual creator with professional talent direction for superior prompt generation."
    @classmethod
    def INPUT_TYPES(cls):
        combined_models = get_combined_models()
        return {
            "required": {
                "response_mode": (["Predictable", "Creative"], {"default": "Predictable", "tooltip": "Predictable = deterministic, instruction-only. Creative = current behavior."}),
                "pipeline_mode": (["Image", "Video"], {"default": "Image"}),
                "instruction": ("STRING", {"multiline": True, "default": config.DEFAULT_PROMPT_TEXT}),
                "subject": ("STRING", {"multiline": True, "default": "" } ),
                "model": (combined_models, {"tooltip": "The language model to use. Can be a local GGUF file or an API-based model."} ),
                "image_count": ("INT", {"default": 1, "min": 1, "max": 5, "step": 1}),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01}),
                "artistry_level": ("INT", {"default": 5, "min": 1, "max": 10, "step": 1}),
                "creativity_level": ("INT", {"default": 5, "min": 1, "max": 10, "step": 1}),
                "logicality_level": ("INT", {"default": 5, "min": 1, "max": 10, "step": 1}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff}),
                "max_length_words": ("INT", {"default": 0, "min": 0, "max": 10000, "step": 10}),
                "style_override": (style_profiles.get_style_override_options("Image"), {"default": "None"}),
                "critique_strength": (["Subtle", "Normal", "Heavy"], {"default": "Normal"}),
                "deep_think_refinements": ("INT", {"default": 3, "min": 0, "max": 10, "step": 1}),
                "simplify_for_diffusion": ("BOOLEAN", {"default": True}),
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10}),
                "max_retries": ("INT", {"default": 2, "min": 0, "max": 10}),
                "safe_mode": ("BOOLEAN", {"default": True}),
                "debug_mode": ("BOOLEAN", {"default": False}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "negative_prompt": "STRING"},
            "optional": {
                "thinking_model": (combined_models, {"tooltip": "Optional: The 'thinker' model for the dual-model chain."} ),
                "instruct_model": (combined_models, {"tooltip": "Optional: The 'instruct' model for the dual-model chain."} ),
                "style_tags": ("STRING", {"multiline": False, "default": ""}),
                "target_model_format": (["Generic (SD1.5, SD2.1)", "Fooocus", "Stable Diffusion 3", "Stable Cascade", "FLUX / Qwen / Hunyuan", "Generic Video (Wan, etc.)"], {"default": "Generic (SD1.5, SD2.1)"}),
                "generate_schedule": ("BOOLEAN", {"default": False}),
                "max_frames": ("INT", {"default": 240, "min": 1, "max": 99999}),
                "interpolate_keyframes": ("BOOLEAN", {"default": False}),
                "interpolation_frame_interval": ("INT", {"default": 10, "min": 0, "max": 16}),
                "format_profile": (text_io.CREATOR_FORMAT_PROFILE_OPTIONS, {"default": "Custom", "tooltip": "Quick presets for output formatting and auto-save."}),
                "output_target": (text_io.VISUAL_OUTPUT_TARGET_OPTIONS, {"default": "Prompt", "tooltip": "Which outputs to format."}),
                "output_format": (text_io.FORMAT_OPTIONS, {"default": "Plain Text", "tooltip": "Format to apply to selected outputs."}),
                "auto_save": ("BOOLEAN", {"default": False, "tooltip": "Auto-save the selected output(s) to a file."}),
                "auto_save_target": (text_io.VISUAL_OUTPUT_TARGET_OPTIONS, {"default": "Prompt", "tooltip": "Which output(s) to auto-save."}),
                "auto_save_folder_path": ("STRING", {"multiline": False, "default": "ComfyUI/output/PromptCrafter", "tooltip": "Folder to save files into."}),
                "auto_save_filename_template": ("STRING", {"multiline": False, "default": "{seed}_{model_name}_{target}.txt", "tooltip": "Filename template. Supports {model_name}, {seed}, {user_text}, {custom_var}, {target}, {format}, {file_type}."}),
                "auto_save_file_type": (text_io.AUTO_FILE_TYPE_OPTIONS, {"default": "Match Output Format", "tooltip": "File extension for auto-saved files."}),
                "auto_save_custom_var": ("STRING", {"multiline": False, "default": "", "tooltip": "Custom placeholder value for {custom_var} in the filename template."}),
            },
        }

    MAX_IMAGES = 5
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING") + ("IMAGE",) * MAX_IMAGES
    RETURN_NAMES = ("prompt", "schedule", "image_context", "negative_prompt", "model_out", "seed_out") + tuple(f"reference_image_{i}" for i in range(1, MAX_IMAGES + 1))
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /Creator"

    def execute(self, instruction, subject, model, negative_prompt="", **kwargs):
        """Execute with talent direction integration."""
        try:
            response_mode = kwargs.get("response_mode", "Predictable")
            mode_kwargs = dict(kwargs)
            if response_mode == "Predictable":
                mode_kwargs.update({
                    "temperature": 0.0,
                    "seed": 0,
                    "use_chat_api": False,
                    "use_deep_think": False,
                    "deep_think_refinements": 0,
                    "max_retries": 0,
                })
                thinking_model = None
                instruct_model = None
            else:
                thinking_model = mode_kwargs.get("thinking_model")
                instruct_model = mode_kwargs.get("instruct_model")
            kwargs = mode_kwargs

            user_text = instruction
            if subject and subject.strip():
                user_text = f"SUBJECT:\n{subject}\n\nINSTRUCTION:\n{instruction}"

            pipeline_mode = kwargs.get("pipeline_mode", "Image")
            target_model_format = kwargs.get("target_model_format", "Generic (SD1.5, SD2.1)")
            format_profile = kwargs.get("format_profile", "Custom")
            output_target = kwargs.get("output_target", "Prompt")
            output_format = kwargs.get("output_format", "Plain Text")
            auto_save = kwargs.get("auto_save", False)
            auto_save_target = kwargs.get("auto_save_target", "Prompt")
            auto_save_folder_path = kwargs.get("auto_save_folder_path", "ComfyUI/output/PromptCrafter")
            auto_save_filename_template = kwargs.get("auto_save_filename_template", "{seed}_{model_name}_{target}.txt")
            auto_save_file_type = kwargs.get("auto_save_file_type", "Match Output Format")
            auto_save_custom_var = kwargs.get("auto_save_custom_var", "")

            if format_profile and format_profile != "Custom":
                profile = text_io.CREATOR_FORMAT_PROFILES.get(format_profile)
                if profile:
                    output_target = profile.get("output_target", output_target)
                    output_format = profile.get("output_format", output_format)
                    auto_save = profile.get("auto_save", auto_save)
                    auto_save_target = profile.get("auto_save_target", auto_save_target)
                    auto_save_file_type = profile.get("auto_save_file_type", auto_save_file_type)
            
            images_with_weights = self._collect_images_with_weights(**kwargs)
            initial_run_config = self._setup_config(pipeline_mode, user_text, model, images_with_weights=images_with_weights, **kwargs)
            
            # --- DUAL-MODEL CHAIN PATH ---
            if thinking_model and instruct_model and "None" not in thinking_model and "None" not in instruct_model:
                print(f"\033[94m[PromptCrafter] Dual-Model mode activated for Visual Creator.\033[0m")
                
                describe_result = self._describe_images(images_with_weights, initial_run_config)
                image_context = describe_result[0] if describe_result else "No reference images provided."
                
                thinking_prompt = textwrap.dedent(f"""
                    You are an expert prompt engineer and art director. Your task is to brainstorm a creative and detailed prompt for an AI image generator based on the user's request and any reference images.

                    **USER REQUEST:**
                    {user_text}

                    **REFERENCE IMAGE CONTEXT:**
                    {image_context}
                    
                    **YOUR TASK:**
                    Think step-by-step. What is the core subject? What is the mood? What composition would be best? What artistic style is requested? What are the key lighting and environmental details?
                    Write down your creative reasoning and a detailed plan for the final prompt under the markdown heading "### REASONING". Also, consider what should be AVOIDED to create a better image.

                    Example of expected output format:
                    ### REASONING
                    The user wants a picture of a majestic dragon in a dark, misty forest. The style should be photorealistic and cinematic.
                    - Core Subject: A large, ancient dragon.
                    - Setting: A dark, misty forest at night, maybe with some moonlight filtering through the trees.
                    - Mood: Mysterious, powerful, slightly intimidating but awe-inspiring.
                    - Composition: A medium shot of the dragon, perhaps its head and glowing eyes are the main focus.
                    - Style: Photorealistic, 8k, cinematic lighting, volumetric fog.
                    - To Avoid: Cartoonish features, overly bright colors, daytime setting.
                """).strip()

                # --- Manual Chain-of-Thought Implementation ---
                # This replaces the call to utils.chain_of_thought_process to gain more control over the process.

                # Step 1: Run the 'thinking' model to get the reasoning.
                ok_think, raw_reasoning_output = api_clients.query_model_auto(
                    thinking_model,
                    thinking_prompt,
                    images=[img for img, _ in images_with_weights],
                    prefer_chat=True,
                    temperature=initial_run_config.temperature,
                    seed=initial_run_config.seed,
                    timeout=initial_run_config.timeout,
                    debug_mode=kwargs.get('debug_mode', False),
                    debug_title="Dual-Model Stage 1: Thinker"
                )

                if not ok_think:
                    return self._handle_creator_exception(Exception(f"Dual-Model Stage 1 (Thinker) failed: {raw_reasoning_output}"))

                # FIX: Check for empty or whitespace-only response from the thinking model.
                if not raw_reasoning_output or not raw_reasoning_output.strip():
                    error_message = "Dual-Model Stage 1 (Thinker) returned an empty response. Aborting."
                    utils._debug_print(kwargs.get('debug_mode', False), "Dual-Model Failure", error_message)
                    return self._handle_creator_exception(Exception(error_message))

                # The full output is saved for debugging/context.
                reasoning_log = raw_reasoning_output

                # Step 2: Extract the reasoning using a markdown header.
                # This is more robust as it includes a fallback to use the entire output if the header is missing.
                reasoning_for_instruct = ""
                if "### REASONING" in reasoning_log:
                    # Ideal case: The model followed instructions and used the header.
                    reasoning_for_instruct = reasoning_log.split("### REASONING", 1)[1].strip()
                else:
                    # Fallback: The model did not use the header. Use the entire non-empty output as reasoning.
                    # This is less clean but prevents a hard crash and might still work.
                    print(f"[93m[PromptCrafter] Warning: '### REASONING' header not found in Thinker model output. Using entire output as reasoning.[0m")
                    reasoning_for_instruct = reasoning_log.strip()

                # If reasoning is empty after attempting extraction, it's a failure.
                if not reasoning_for_instruct:
                    error_message = "Dual-Model Stage 1 (Thinker) failed to produce valid reasoning within <think> tags."
                    utils._debug_print(kwargs.get('debug_mode', False), "Dual-Model Failure", f"{error_message}\nRaw Output:\n{reasoning_log}")
                    return self._handle_creator_exception(Exception(error_message))
                
                # Step 3: Run the 'instruct' model to get the final JSON output.
                instruct_schema = {
                    "positive_prompt": "string (The final, detailed, comma-separated prompt for the image generator.)",
                    "negative_prompt": "string (A list of comma-separated keywords to avoid, like 'blurry, ugly, text, watermark'.)"
                }

                instruct_prompt = textwrap.dedent(f"""
                    Based on the following creative reasoning, generate a final JSON object containing the positive and negative prompts.

                    **REASONING:**
                    {reasoning_for_instruct}

                    **JSON SCHEMA:**
                    ```json
                    {json.dumps(instruct_schema, indent=2)}
                    ```

                    Return ONLY the JSON object.
                """ ).strip()

                ok, result_data = api_clients._reason_with_model(
                    instruct_model,
                    instruct_prompt,
                    images=[], # Instruct model does not need images, only reasoning.
                    use_chat_api=True,
                    temperature=0.1, # Low temperature for precise JSON output
                    seed=initial_run_config.seed,
                    timeout=initial_run_config.timeout,
                    debug_mode=kwargs.get('debug_mode', False),
                    debug_title="Dual-Model Stage 2: Instructor (JSON)"
                )
                
                if not ok or not isinstance(result_data, dict):
                    return self._handle_creator_exception(Exception(f"Dual-Model Stage 2 (Instruct) failed: {result_data}"))

                final_prompt = result_data.get("positive_prompt", "")
                final_negative_prompt = result_data.get("negative_prompt", "")
                final_prompt = self._format_prompt_for_target(final_prompt, target_model_format)

                passthrough_images = [img for img, _ in images_with_weights]
                passthrough_images.extend([None] * (self.MAX_IMAGES - len(passthrough_images)))

                final_image_context = f"""--- REASONING LOG ---
{reasoning_log}

--- IMAGE CONTEXT ---
{image_context} """ 
                outputs_map = {
                    "Prompt": final_prompt,
                    "Schedule": "",
                    "Image Context": final_image_context,
                    "Negative Prompt": final_negative_prompt,
                }
                formatted_map = self._apply_output_formatting_map(
                    outputs_map,
                    output_target,
                    output_format,
                    text_io.VISUAL_OUTPUT_TARGET_OPTIONS,
                )
                if auto_save:
                    self._auto_save_outputs(
                        formatted_map,
                        auto_save_target,
                        output_format,
                        auto_save_folder_path,
                        auto_save_filename_template,
                        auto_save_file_type,
                        {
                            "model_name": model,
                            "seed": initial_run_config.seed,
                            "user_text": user_text,
                            "custom_var": auto_save_custom_var,
                        },
                    )

                return (
                    formatted_map.get("Prompt", final_prompt),
                    formatted_map.get("Schedule", ""),
                    formatted_map.get("Image Context", final_image_context),
                    formatted_map.get("Negative Prompt", final_negative_prompt),
                    model,
                    str(initial_run_config.seed),
                ) + tuple(passthrough_images)

            # --- LEGACY SINGLE-MODEL PATH ---
            else:
                # --- DEPRECATION of specialized handlers ---
                # All visual prompts now go through the main generation pipeline.
                # The _is_speech_prompt_request and _is_lyrics_to_prompt_request checks are removed.
                
                if response_mode == "Predictable":
                    error, new_user_text = None, None
                else:
                    error, new_user_text = self._handle_creative_intent(pipeline_mode, user_text, images_with_weights, initial_run_config)
                if error: 
                    return (error,) + (None,) * (len(self.RETURN_TYPES) - 1)
                final_user_text = new_user_text or user_text
                
                run_config = self._setup_config(pipeline_mode, final_user_text, model, images_with_weights=images_with_weights, **kwargs)
                
                passthrough_images = [img for img, _ in images_with_weights]
                passthrough_images.extend([None] * (self.MAX_IMAGES - len(passthrough_images)))
                
                if kwargs.get("generate_schedule"):
                    prompt, schedule, image_context, neg_prompt = self._handle_scheduled_mode(
                        pipeline_mode, final_user_text, images_with_weights, run_config, **kwargs
                    )
                    
                    if schedule and schedule.strip() != "{}":
                        enhanced_schedule = self._enhance_schedule_with_talent_direction(schedule, final_user_text, model, timed_segments=None)
                        schedule = enhanced_schedule

                    outputs_map = {
                        "Prompt": prompt,
                        "Schedule": schedule,
                        "Image Context": image_context,
                        "Negative Prompt": neg_prompt,
                    }
                    formatted_map = self._apply_output_formatting_map(
                        outputs_map,
                        output_target,
                        output_format,
                        text_io.VISUAL_OUTPUT_TARGET_OPTIONS,
                    )
                    if auto_save:
                        self._auto_save_outputs(
                            formatted_map,
                            auto_save_target,
                            output_format,
                            auto_save_folder_path,
                            auto_save_filename_template,
                            auto_save_file_type,
                            {
                                "model_name": model,
                                "seed": run_config.seed,
                                "user_text": final_user_text,
                            "custom_var": auto_save_custom_var,
                        },
                    )

                    return (
                        formatted_map.get("Prompt", prompt),
                        formatted_map.get("Schedule", schedule),
                        formatted_map.get("Image Context", image_context),
                        formatted_map.get("Negative Prompt", neg_prompt),
                        model,
                        str(run_config.seed),
                    ) + tuple(passthrough_images)
                else:
                    image_context_for_all = self._describe_images(images_with_weights, run_config)
                    image_context_out = image_context_for_all[0] if image_context_for_all else ""
                    
                    style_rules = self._build_style_and_composition_rules("Image", [img for img, _ in images_with_weights], run_config, final_user_text, "", image_context_out)
                    
                    final_prompt = self._generate_prompt_for_scene(final_user_text, "Image", images_with_weights, image_context_out, style_rules, run_config, **kwargs)
                    
                    ai_negative_prompt = utils._generate_negative_prompt(final_prompt, run_config, user_negative_prompt=negative_prompt)
                    
                    final_prompt_formatted = self._format_prompt_for_target(final_prompt, target_model_format)

                    outputs_map = {
                        "Prompt": final_prompt_formatted,
                        "Schedule": "",
                        "Image Context": image_context_out,
                        "Negative Prompt": ai_negative_prompt,
                    }
                    formatted_map = self._apply_output_formatting_map(
                        outputs_map,
                        output_target,
                        output_format,
                        text_io.VISUAL_OUTPUT_TARGET_OPTIONS,
                    )
                    if auto_save:
                        self._auto_save_outputs(
                            formatted_map,
                            auto_save_target,
                            output_format,
                            auto_save_folder_path,
                            auto_save_filename_template,
                            auto_save_file_type,
                            {
                                "model_name": model,
                                "seed": run_config.seed,
                                "user_text": final_user_text,
                            "custom_var": auto_save_custom_var,
                        },
                    )

                    return (
                        formatted_map.get("Prompt", final_prompt_formatted),
                        formatted_map.get("Schedule", ""),
                        formatted_map.get("Image Context", image_context_out),
                        formatted_map.get("Negative Prompt", ai_negative_prompt),
                        model,
                        str(run_config.seed),
                    ) + tuple(passthrough_images)
        except Exception as e:
            return self._handle_creator_exception(e)


# ------------------------------------------------------------------------------------
# PromptCrafter_LyricsCreator Node
# ------------------------------------------------------------------------------------
class PromptCrafter_LyricsCreator(PromptCrafter_BaseCreator):
    DESCRIPTION = "Enhanced lyrics-to-prompt creator with professional film crew direction."

    @classmethod
    def get_whisper_models(cls):
        """Scans for local Whisper models and returns a list including defaults."""
        default_models = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
        
        module_dir = os.path.dirname(os.path.abspath(__file__))
        comfy_root = os.path.abspath(os.path.join(module_dir, '..', '..', '..'))
        
        search_dirs = [
            os.path.join(comfy_root, "models", "faster-whisper"),
            os.path.join(comfy_root, "models", "audio_encoders"),
            os.path.join(comfy_root, "models", "sonic"),
        ]
        
        found_models = set()
        for s_dir in search_dirs:
            if os.path.isdir(s_dir):
                for item in os.listdir(s_dir):
                    if os.path.isdir(os.path.join(s_dir, item)):
                        found_models.add(item)
        return utils._unique_keep_order(default_models + sorted(list(found_models)))

    @classmethod
    def INPUT_TYPES(cls):
        combined_models = get_combined_models()
        types = copy.deepcopy(PromptCrafter_VisualCreator.INPUT_TYPES())
        if "response_mode" not in types["required"]:
            types["required"]["response_mode"] = (["Predictable", "Creative"], {"default": "Predictable", "tooltip": "Predictable = deterministic, instruction-only. Creative = current behavior."})
        types["required"]["model"] = (combined_models, {"tooltip": "The language model to use. Can be a local GGUF file or an API-based model."} )
        types["required"]["temperature"] = ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01})
        types["required"]["max_length_words"] = ("INT", {"default": 2000, "min": 0, "max": 10000, "step": 100})
        types["required"]["style_override"] = (style_profiles.get_style_override_options("Lyrics"), {"default": "None"})
        types["required"]["simplify_for_diffusion"] = ("BOOLEAN", {"default": False})
        
        if "pipeline_mode" in types["required"]:
            del types["required"]["pipeline_mode"]
        if "target_model_format" in types["optional"]:
            del types["optional"]["target_model_format"]

        types["optional"]['signal'] = ('*', {})
        types["optional"]["thinking_model"] = (combined_models, {"tooltip": "Optional: The 'thinker' model for the dual-model chain."} )
        types["optional"]["instruct_model"] = (combined_models, {"tooltip": "Optional: The 'instruct' model for the dual-model chain."} )
        types["optional"].update({
            "style_tags": ("STRING", {"multiline": False, "default": ""}),
            "vrg_compatibility_mode": ("BOOLEAN", {"default": False, "tooltip": "If True, use the detailed music video prompt builder inputs below, overriding the main user_text input."} ),
            "audio_folder_path": ("STRING", {"multiline": False, "default": "input/audio"}),
            "audio_file": ("STRING", {"multiline": False, "default": "<none>"}),
            "lyrics_folder_path": ("STRING", {"multiline": False, "default": "input/lyrics"}),
            "lyrics_file": ("STRING", {"multiline": False, "default": "<none>"}),
            "use_audio_alignment": ("BOOLEAN", {"default": True}),
            "song_length_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 3600.0, "step": 0.1}),
            "fps": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.5}),
            "scene_splitting_mode": (["Structural Tag", "Fixed Duration", "Frame Length"], {"default": "Structural Tag"}),
            "max_scene_duration_seconds": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 60.0, "step": 0.1, "tooltip": "Max scene length in seconds for 'Fixed Duration' mode."} ),
            "max_scene_frames": ("INT", {"default": 120, "min": 0, "max": 4096, "step": 1, "tooltip": "Max scene length in frames for 'Frame Length' mode."} ),
            "whisper_model": (cls.get_whisper_models(), {"default": "large-v3", "tooltip": "The Whisper model to use for transcription. Larger models are more accurate but slower and use more VRAM."} ),
            "whisper_language": (["auto-detect", "en", "es", "fr", "de", "it", "pt", "is", "ru", "ja", "ko", "zh"], {"default": "auto-detect", "tooltip": "Language of the audio. 'is' for Icelandic. Providing this greatly improves accuracy."} ),
            "whisper_engine": (["faster-whisper", "insanely-fast-whisper"], {"default": "faster-whisper", "tooltip": "Default: faster-whisper. Alternative: insanely-fast-whisper (optimized for batch processing)."} ),
            "target_model_format": (["Generic (SD1.5, SD2.1)", "Fooocus", "Stable Diffusion 3", "Stable Cascade", "FLUX / Qwen / Hunyuan", "Generic Video (Wan, etc.)"], {"default": "Generic Video (Wan, etc.)", "tooltip": "Format the prompt for a specific model's syntax. OVI speech format is handled automatically."} ),
            "use_vrg_prompt_builder": ("BOOLEAN", {"default": False, "tooltip": "If True, use the detailed music video prompt builder inputs below, overriding the main user_text input."} ),
            "automate_vrg_variables": ("BOOLEAN", {"default": False, "tooltip": "If True, use an LLM to automatically fill the VRGDG variables based on the lyrics."} ),
            "character_description": ("STRING", {"multiline": True, "default": "The Women."} ),
            "song_theme_style": ("STRING", {"multiline": True, "default": "cinematic realism, emotional storytelling, soft surrealism, naturalistic tone, dreamlike nostalgia, modern drama, poetic symbolism, intimate atmosphere"}),
            "word_count_min": ("INT", {"default": 30, "min": 10, "max": 200}),
            "word_count_max": ("INT", {"default": 50, "min": 10, "max": 200}),
            "list_handling_mode": (["Strict Cycle (use each once, then repeat)", "Reference Guide (LLM creates variations inspired by list)", "Random Selection (pick randomly from list)", "Free Interpretation (LLM can ignore or combine items)"], {"default": "Reference Guide (LLM creates variations inspired by list)"}),
            "environment": ("STRING", {"multiline": True, "default": "open field at dusk, dimly lit bedroom, empty city street at night, forest clearing with morning fog, seaside cliff at golden hour, rainy urban alley, sunlit living room, desert road at sunrise"}),
            "lighting": ("STRING", {"multiline": True, "default": "warm amber glow, cool window light, neon reflections, diffused morning light, soft backlight haze, flickering streetlights, gentle afternoon sun, pink-orange dawn light"}),
            "camera_motion": ("STRING", {"multiline": True, "default": "zoom in, zoom out, tilt down, rotate around, tilt up, pan, track"}),
            "physical_interaction": ("STRING", {"multiline": True, "default": "walking through tall grass, lying on bed staring upward, leaning against a wall in stillness, reaching toward sunlight, hair moving in wind, footsteps in puddles, brushing hand across furniture, standing motionless in breeze"}),
            "facial_expression": ("STRING", {"multiline": True, "default": "Intense raw emotion"}),
            "shots": ("STRING", {"multiline": True, "default": "Close up, medium, wide angle, over the shoulder, point of view, overhead, ground level"}),
            "outfit_rules": ("STRING", {"multiline": True, "default": "a white dress"}),
            "character_visibility": ("STRING", {"multiline": True, "default": "mostly visible, half-shadowed, silhouetted, reflected or obscured, seen from behind, partially out of frame, emerging from light, fading into darkness"}),
        })
        types["optional"]["generate_schedule"] = ("BOOLEAN", {"default": True})
        types["optional"]["interpolate_keyframes"] = ("BOOLEAN", {"default": False})
        types["optional"]["interpolation_frame_interval"] = ("INT", {"default": 0, "min": 0, "max": 16})

        if "whisper_model_size" in types["optional"]:
            del types["optional"]["whisper_model_size"]

        if "output_target" in types["optional"]:
            options, meta = types["optional"]["output_target"]
            new_meta = dict(meta)
            new_meta["default"] = "Schedule"
            types["optional"]["output_target"] = (text_io.LYRICS_OUTPUT_TARGET_OPTIONS, new_meta)
        if "auto_save_target" in types["optional"]:
            options, meta = types["optional"]["auto_save_target"]
            new_meta = dict(meta)
            new_meta["default"] = "Schedule"
            types["optional"]["auto_save_target"] = (text_io.LYRICS_OUTPUT_TARGET_OPTIONS, new_meta)
        return types
    
    STATIC_RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "DICT", "IMAGE", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "STRING")
    STATIC_RETURN_NAMES = (
        "prompt",
        "schedule", 
        "image_context",
        "negative_prompt",
        "clean_lyrics_txt",
        "lyrics_srt",
        "model_out",
        "seed_out",
        "audio_meta",
        "spectrogram_preview",
        "signal",
        "auto_character",
        "auto_theme",
        "auto_environment",
        "auto_lighting",
        "auto_interaction",
        "auto_expression",
        "auto_shots",
        "auto_outfit",
        "auto_visibility",
    )
    
    MAX_DYNAMIC_IMAGES = 5
    RETURN_TYPES = STATIC_RETURN_TYPES + ("IMAGE",) * MAX_DYNAMIC_IMAGES
    RETURN_NAMES = STATIC_RETURN_NAMES + tuple(f"reference_image_{i}" for i in range(1, MAX_DYNAMIC_IMAGES + 1))
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Creator"

    def execute(self, instruction, subject, model, **kwargs):
        """Execute with talent direction integration."""
        try:
            response_mode = kwargs.get("response_mode", "Predictable")
            mode_kwargs = dict(kwargs)
            if response_mode == "Predictable":
                mode_kwargs.update({
                    "temperature": 0.0,
                    "seed": 0,
                    "use_chat_api": False,
                    "use_deep_think": False,
                    "deep_think_refinements": 0,
                    "max_retries": 0,
                })
                thinking_model = None
                instruct_model = None
            else:
                thinking_model = mode_kwargs.get("thinking_model")
                instruct_model = mode_kwargs.get("instruct_model")
            kwargs = mode_kwargs
            user_text = instruction
            if subject and subject.strip():
                user_text = f"SUBJECT:\n{subject}\n\nINSTRUCTION:\n{instruction}"

            images_with_weights = self._collect_images_with_weights(**kwargs)
            run_config = self._setup_config("Lyrics", user_text, model, images_with_weights=images_with_weights, **kwargs)
            format_profile = kwargs.get("format_profile", "Custom")
            output_target = kwargs.get("output_target", "Schedule")
            output_format = kwargs.get("output_format", "Plain Text")
            auto_save = kwargs.get("auto_save", False)
            auto_save_target = kwargs.get("auto_save_target", "Schedule")
            auto_save_folder_path = kwargs.get("auto_save_folder_path", "ComfyUI/output/PromptCrafter")
            auto_save_filename_template = kwargs.get("auto_save_filename_template", "{seed}_{model_name}_{target}.txt")
            auto_save_file_type = kwargs.get("auto_save_file_type", "Match Output Format")
            auto_save_custom_var = kwargs.get("auto_save_custom_var", "")

            if format_profile and format_profile != "Custom":
                profile = text_io.CREATOR_FORMAT_PROFILES.get(format_profile)
                if profile:
                    output_target = profile.get("output_target", output_target)
                    output_format = profile.get("output_format", output_format)
                    auto_save = profile.get("auto_save", auto_save)
                    auto_save_target = profile.get("auto_save_target", auto_save_target)
                    auto_save_file_type = profile.get("auto_save_file_type", auto_save_file_type)

            # --- DUAL-MODEL CHAIN PATH ---
            if thinking_model and instruct_model and "None" not in thinking_model and "None" not in instruct_model:
                print(f"\033[94m[PromptCrafter] Dual-Model mode activated for Lyrics Creator.\033[0m")
                
                # Inline implementation of audio processing (replacing missing Lobe_Music)
                clean_lyrics_txt = user_text
                lyrics_srt = ""
                timed_segments = []
                audio_meta = {}
                spectrogram_preview = None
                
                audio_folder = kwargs.get("audio_folder_path", "input/audio")
                audio_filename = kwargs.get("audio_file", "<none>")
                
                if audio_filename != "<none>":
                    audio_path = utils._get_verified_path(audio_folder, audio_filename)
                    if audio_path:
                        try:
                            try:
                                waveform, sample_rate = torchaudio.load(audio_path)
                            except Exception as e:
                                print(f"[PromptCrafter] torchaudio load failed, trying librosa: {e}")
                                audio_np, sample_rate = librosa.load(audio_path, sr=None, mono=False)
                                waveform = torch.from_numpy(audio_np)
                                if waveform.ndim == 1:
                                    waveform = waveform.unsqueeze(0)
                            audio_data = {"waveform": waveform.unsqueeze(0) if waveform.ndim == 2 else waveform, "sample_rate": sample_rate}
                            
                            srt_node = pgfx_srt_creator.PromptCrafter_SRTCreator()
                            
                            lyrics_folder = kwargs.get("lyrics_folder_path", "input/lyrics")
                            lyrics_filename = kwargs.get("lyrics_file", "<none>")
                            ground_truth_text = ""
                            if lyrics_filename != "<none>":
                                lpath = utils._get_verified_path(lyrics_folder, lyrics_filename)
                                if lpath: ground_truth_text = utils.safe_read(lpath)
                            
                            whisper_model = kwargs.get("whisper_model", "large-v3")
                            language = kwargs.get("whisper_language", "auto-detect")
                            if language == "auto-detect": language = None
                            
                            srt_res = srt_node.execute(
                                audio_data, whisper_model, language if language else "en",
                                bool(ground_truth_text), instruct_model, False, False,
                                kwargs.get("debug_mode", False), ground_truth_text
                            )
                            
                            lyrics_srt = srt_res[0]
                            clean_lyrics_txt = srt_res[1]
                            if srt_res[3]:
                                parsed_segments = json_utils.extract_and_parse_json(srt_res[3])
                                timed_segments = parsed_segments if isinstance(parsed_segments, list) else []
                                
                            audio_meta = {
                                "audio_total_duration": float(waveform.shape[-1]) / sample_rate,
                                "sample_rate": sample_rate,
                                "timed_segments": timed_segments,
                                "word_segments": timed_segments,
                                "vocal_audio": audio_data
                            }
                        except Exception as e:
                            print(f"\033[91m[PromptCrafter] Audio processing failed: {e}\033[0m")

                audio_meta_result = {
                    "clean_lyrics_txt": clean_lyrics_txt,
                    "lyrics_srt": lyrics_srt,
                    "timed_segments": timed_segments,
                    "audio_meta": audio_meta,
                    "spectrogram_preview": spectrogram_preview
                }
                
                clean_lyrics = audio_meta_result.get("clean_lyrics_txt", "")
                timed_segments = audio_meta_result.get("timed_segments", [])
                
                if not clean_lyrics and not timed_segments:
                     return self._handle_creator_exception(Exception("No lyrics found from transcription or direct input."))

                thinking_prompt = textwrap.dedent(f"""
                    You are a music video director. Your task is to brainstorm a sequence of cinematic scenes for the provided lyrics.

                    **SONG LYRICS:**
                    {clean_lyrics}
                    **SONG THEME / STYLE:**
                    {kwargs.get('song_theme_style', 'A cinematic and emotional music video.')}
                    **CHARACTER:**
                    {kwargs.get('character_description', 'The main singer.')}
                    **TASK:**
                    Think step-by-step. Break the song into logical scenes. For each scene, describe the visual action, the camera shot, and the mood.
                    Write down your creative reasoning and a scene-by-scene plan for the final prompt schedule.
                """ ).strip()

                # --- Manual Chain-of-Thought Implementation for LyricsCreator ---

                # Step 1: Run the 'thinking' model to get the reasoning.
                thinking_timeout = 0 if str(thinking_model).lower().startswith("gguf/") else run_config.timeout
                ok_think, reasoning_text = api_clients.query_model_auto(
                    thinking_model,
                    thinking_prompt,
                    images=[],
                    prefer_chat=True,
                    temperature=run_config.temperature,
                    seed=run_config.seed,
                    timeout=thinking_timeout,
                    debug_mode=kwargs.get('debug_mode', False),
                    debug_title="Dual-Model Stage 1: Thinker (Lyrics)"
                )

                if not ok_think:
                    return self._handle_creator_exception(Exception(f"Dual-Model Stage 1 (Thinker) failed: {reasoning_text}"))
                
                if not reasoning_text or not reasoning_text.strip():
                    return self._handle_creator_exception(Exception("Dual-Model Stage 1 (Thinker) returned an empty response."))

                utils._debug_print(kwargs.get('debug_mode', False), "Dual-Model Stage 1: Reasoning Output (Lyrics)", reasoning_text)

                # Step 2: Run the 'instruct' model to get the final JSON output.
                instruct_schema = {
                    "prompt_schedule": {
                        "0": "string (A detailed cinematic prompt for the first scene at frame 0.)",
                        "120": "string (A detailed cinematic prompt for the second scene at frame 120.)",
                    }
                }

                instruct_prompt = textwrap.dedent(f"""
                    Based on the following creative reasoning, generate a JSON object containing the prompt schedule.
                    The keys of the 'prompt_schedule' object must be frame numbers (as strings).
                    **REASONING:**
                    {reasoning_text}

                    **JSON SCHEMA (example):**
                    ```json
                    {json.dumps(instruct_schema, indent=2)}
                    ```

                    Return ONLY the JSON object.
                """ ).strip()

                instruct_timeout = 0 if str(instruct_model).lower().startswith("gguf/") else run_config.timeout
                ok_instruct, result_data = api_clients._reason_with_model(
                    instruct_model,
                    instruct_prompt,
                    images=[],
                    use_chat_api=True,
                    temperature=0.0, # Zero temp for strict formatting
                    seed=run_config.seed,
                    timeout=instruct_timeout,
                    debug_mode=kwargs.get('debug_mode', False),
                    debug_title="Dual-Model Stage 2: Instructor (Lyrics)"
                )

                if not ok_instruct or not isinstance(result_data, dict) or "prompt_schedule" not in result_data:
                    return self._handle_creator_exception(Exception(f"Dual-Model Stage 2 (Instruct) for Lyrics failed: {result_data}"))
                
                schedule_json = json.dumps(result_data["prompt_schedule"], indent=4)
                
                passthrough_images = [img for img, _ in images_with_weights]
                passthrough_images.extend([None] * (self.MAX_DYNAMIC_IMAGES - len(passthrough_images)))
                
                audio_meta_dict = audio_meta_result.get("audio_meta") if isinstance(audio_meta_result.get("audio_meta"), dict) else {}
                
                # Ensure spectrogram_preview is a valid tensor to prevent downstream errors
                spec_preview = audio_meta_result.get("spectrogram_preview")
                if spec_preview is None:
                    spec_preview = torch.zeros((1, 64, 64, 3), dtype=torch.float32)
                elif isinstance(spec_preview, Image.Image):
                    spec_preview = utils.pil2tensor(spec_preview)

                outputs_map = {
                    "Prompt": "",
                    "Schedule": schedule_json,
                    "Image Context": "",
                    "Negative Prompt": "",
                    "Clean Lyrics": clean_lyrics,
                    "Lyrics SRT": audio_meta_result.get("lyrics_srt", ""),
                }
                formatted_map = self._apply_output_formatting_map(
                    outputs_map,
                    output_target,
                    output_format,
                    text_io.LYRICS_OUTPUT_TARGET_OPTIONS,
                )
                if auto_save:
                    self._auto_save_outputs(
                        formatted_map,
                        auto_save_target,
                        output_format,
                        auto_save_folder_path,
                        auto_save_filename_template,
                        auto_save_file_type,
                        {
                            "model_name": model,
                            "seed": run_config.seed,
                            "user_text": user_text,
                            "custom_var": auto_save_custom_var,
                        },
                    )

                return (
                    formatted_map.get("Prompt", ""),
                    formatted_map.get("Schedule", schedule_json),
                    formatted_map.get("Image Context", ""),
                    formatted_map.get("Negative Prompt", ""),
                    formatted_map.get("Clean Lyrics", clean_lyrics),
                    formatted_map.get("Lyrics SRT", audio_meta_result.get("lyrics_srt", "")),
                    model, str(run_config.seed), audio_meta_dict,
                    spec_preview, kwargs.get("signal"),
                    kwargs.get("character_description"), kwargs.get("song_theme_style"), kwargs.get("environment"),
                    kwargs.get("lighting"), kwargs.get("physical_interaction"), kwargs.get("facial_expression"),
                    kwargs.get("shots"), kwargs.get("outfit_rules"),
                    kwargs.get("character_visibility")
                ) + tuple(passthrough_images)

            # --- LEGACY SINGLE-MODEL PATH ---
            else:
                # --- DEPRECATION of specialized handlers ---
                # All lyrics-based generation now goes through the main storyboard thought process.
                describe_result = self._describe_images(images_with_weights, run_config)
                image_context_out, _, primary_subjects_from_images = describe_result if describe_result else ("", [], [])

                # Map UI kwargs to ThoughtProcess expected lyrics_* keys
                lyrics_kwargs = kwargs.copy()
                _lyrics_key_map = {
                    "audio_file": "lyrics_audio_file",
                    "lyrics_file": "lyrics_lyrics_file",
                    "audio_folder_path": "lyrics_audio_folder_path",
                    "lyrics_folder_path": "lyrics_lyrics_folder_path",
                    "use_audio_alignment": "lyrics_use_audio_alignment",
                    "song_length_seconds": "lyrics_song_length_seconds",
                    "fps": "lyrics_fps",
                    "scene_splitting_mode": "lyrics_scene_splitting_mode",
                    "max_scene_duration_seconds": "lyrics_max_scene_duration_seconds",
                    "max_scene_frames": "lyrics_max_scene_frames",
                    "whisper_model": "lyrics_whisper_model_size",
                    "whisper_language": "lyrics_whisper_language",
                    "whisper_engine": "lyrics_whisper_engine",
                    "use_vrg_prompt_builder": "lyrics_use_vrg_prompt_builder",
                    "automate_vrg_variables": "lyrics_automate_vrg_variables",
                    "character_description": "lyrics_character_description",
                    "song_theme_style": "lyrics_song_theme_style",
                    "word_count_min": "lyrics_word_count_min",
                    "word_count_max": "lyrics_word_count_max",
                    "list_handling_mode": "lyrics_list_handling_mode",
                    "environment": "lyrics_environment",
                    "lighting": "lyrics_lighting",
                    "camera_motion": "lyrics_camera_motion",
                    "physical_interaction": "lyrics_physical_interaction",
                    "facial_expression": "lyrics_facial_expression",
                    "shots": "lyrics_shots",
                    "outfit_rules": "lyrics_outfit_rules",
                    "character_visibility": "lyrics_character_visibility",
                    "generate_schedule": "lyrics_generate_schedule",
                    "interpolate_keyframes": "lyrics_interpolate_keyframes",
                    "interpolation_frame_interval": "lyrics_interpolation_frame_interval",
                    "target_model_format": "lyrics_target_model_format",
                }
                for src_key, dst_key in _lyrics_key_map.items():
                    if src_key in kwargs and dst_key not in lyrics_kwargs:
                        lyrics_kwargs[dst_key] = kwargs.get(src_key)

                thought_process_instance = thinking_process.ThoughtProcess(
                    run_config=run_config, user_text=user_text,
                    negative_prompt=kwargs.get("negative_prompt", ""), image_context=image_context_out,
                    primary_subjects_from_images=primary_subjects_from_images,
                    mode="Lyrics", **lyrics_kwargs
                )

                result = thought_process_instance.run()
                if isinstance(result, dict):
                    prompt = result.get("prompt", "")
                    schedule = result.get("schedule", "")
                    image_context_out = result.get("image_context", image_context_out)
                    negative_prompt_out = result.get("negative_prompt", "")
                    clean_lyrics_txt = result.get("clean_lyrics_txt", "")
                    lyrics_srt = result.get("lyrics_srt", "")
                    audio_meta = result.get("audio_meta", {}) if isinstance(result.get("audio_meta", {}), dict) else {}
                    spectrogram_preview = result.get("spectrogram_preview", None)
                    auto_character = result.get("auto_character", "") or kwargs.get("character_description")
                    auto_theme = result.get("auto_theme", "") or kwargs.get("song_theme_style")
                    auto_environment = result.get("auto_environment", "") or kwargs.get("environment")
                    auto_lighting = result.get("auto_lighting", "") or kwargs.get("lighting")
                    auto_interaction = result.get("auto_interaction", "") or kwargs.get("physical_interaction")
                    auto_expression = result.get("auto_expression", "") or kwargs.get("facial_expression")
                    auto_shots = result.get("auto_shots", "") or kwargs.get("shots")
                    auto_outfit = result.get("auto_outfit", "") or kwargs.get("outfit_rules")
                    auto_visibility = result.get("auto_visibility", "") or kwargs.get("character_visibility")
                elif isinstance(result, tuple) and len(result) >= 8:
                    # Backward compatibility if a tuple is returned
                    prompt, image_context_out, negative_prompt_out, clean_lyrics_txt, lyrics_srt, audio_meta, spectrogram_preview, schedule = result[:8]
                    auto_character = kwargs.get("character_description")
                    auto_theme = kwargs.get("song_theme_style")
                    auto_environment = kwargs.get("environment")
                    auto_lighting = kwargs.get("lighting")
                    auto_interaction = kwargs.get("physical_interaction")
                    auto_expression = kwargs.get("facial_expression")
                    auto_shots = kwargs.get("shots")
                    auto_outfit = kwargs.get("outfit_rules")
                    auto_visibility = kwargs.get("character_visibility")
                else:
                    return self._handle_creator_exception(Exception(f"Lyrics engine returned invalid output: {result}"))

                if schedule and isinstance(schedule, str) and schedule.strip() and schedule.strip() != "{}":
                    timed_segments = audio_meta.get("timed_segments") if isinstance(audio_meta, dict) else []
                    schedule = self._enhance_schedule_with_talent_direction(schedule, clean_lyrics_txt, model, timed_segments)
                
                if prompt:
                    prompt = self._enhance_prompt_with_talent_direction(prompt, clean_lyrics_txt, model)
                
                #if kwargs.get("vrg_compatibility_mode"):
                #    print("\033[94m[PromptCrafter] VRGDG Compatibility Mode Enabled. Enriching prompts...\033[0m")
                #    timed_segments = audio_meta.get("timed_segments") if isinstance(audio_meta, dict) else []
                #    prompt = self._vrg_enrich_lyrics(timed_segments)
                #    schedule = ""
                
                if spectrogram_preview is not None and isinstance(spectrogram_preview, Image.Image):
                    spectrogram_preview = utils.pil2tensor(spectrogram_preview)
                
                if prompt is None or (isinstance(prompt, str) and prompt.startswith("An error occurred:")):
                    return self._handle_creator_exception(Exception(prompt or "A critical error occurred in the thought process."))

                target_model_format = kwargs.get("target_model_format", "Generic Video (Wan, etc.)")
                
                passthrough_images = [img for img, _ in images_with_weights]
                passthrough_images.extend([None] * (self.MAX_DYNAMIC_IMAGES - len(passthrough_images)))
                
                auto_vars = kwargs.get("automate_vrg_variables", False)
                
                outputs_map = {
                    "Prompt": prompt,
                    "Schedule": schedule,
                    "Image Context": image_context_out,
                    "Negative Prompt": negative_prompt_out,
                    "Clean Lyrics": clean_lyrics_txt,
                    "Lyrics SRT": lyrics_srt,
                }
                formatted_map = self._apply_output_formatting_map(
                    outputs_map,
                    output_target,
                    output_format,
                    text_io.LYRICS_OUTPUT_TARGET_OPTIONS,
                )
                if auto_save:
                    self._auto_save_outputs(
                        formatted_map,
                        auto_save_target,
                        output_format,
                        auto_save_folder_path,
                        auto_save_filename_template,
                        auto_save_file_type,
                        {
                            "model_name": model,
                            "seed": run_config.seed,
                            "user_text": user_text,
                            "custom_var": auto_save_custom_var,
                        },
                    )

                return (
                    formatted_map.get("Prompt", prompt),
                    formatted_map.get("Schedule", schedule),
                    formatted_map.get("Image Context", image_context_out),
                    formatted_map.get("Negative Prompt", negative_prompt_out),
                    formatted_map.get("Clean Lyrics", clean_lyrics_txt),
                    formatted_map.get("Lyrics SRT", lyrics_srt),
                    model, str(run_config.seed), audio_meta if isinstance(audio_meta, dict) else {}, spectrogram_preview,
                    kwargs.get("signal"), auto_character, auto_theme,
                    auto_environment, auto_lighting, auto_interaction,
                    auto_expression, auto_shots, auto_outfit,
                    auto_visibility
                ) + tuple(passthrough_images)
        except Exception as e:
            return self._handle_creator_exception(e)


# ------------------------------------------------------------------------------------
# Node Mappings
# ------------------------------------------------------------------------------------
NODE_CLASS_MAPPINGS = {
    "PromptCrafter_VisualCreator": PromptCrafter_VisualCreator,
    "PromptCrafter_LyricsCreator": PromptCrafter_LyricsCreator,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_VisualCreator": "✨ Visual Creator",
    "PromptCrafter_LyricsCreator": "🎤 Lyrics Creator",
}
