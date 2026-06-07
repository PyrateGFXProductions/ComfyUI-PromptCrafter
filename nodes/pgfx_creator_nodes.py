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
try:
    import librosa
except ImportError:
    librosa = None
try:
    import torchaudio
except ImportError:
    torchaudio = None

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

def get_combined_models():
    """Helper to get a combined list of local-first models and configured providers."""
    gguf_files = api_clients.get_local_llm_gguf_files()
    gguf_models = [f"gguf/{m}" for m in gguf_files if "not installed" not in m and "not_found" not in m and "error_scanning" not in m]
    
    hf_models = api_clients.get_local_hf_models()
    hf_models_formatted = [f"hf/{m}" for m in hf_models if "not installed" not in m]

    api_models = api_clients.get_all_models()
    # Combine lists, ensuring local models are listed first.
    combined = hf_models_formatted + gguf_models + [m for m in api_models if m not in hf_models_formatted + gguf_models]
    return combined

_LOCAL_PROVIDER_PREFIXES = ("gguf/", "hf/", "ollama/", "lmstudio/", "text-generation-webui/")

def _is_local_model_id(model_id):
    """Returns True when a model identifier resolves to a local runtime/provider."""
    if not model_id:
        return True
    model = str(model_id).strip()
    lower = model.lower()
    if lower.startswith(_LOCAL_PROVIDER_PREFIXES):
        return True

    # Backward compatibility: allow raw local model names.
    try:
        if model in api_clients.get_local_hf_models():
            return True
        if model in api_clients.get_local_llm_gguf_files():
            return True
    except Exception:
        pass
    return False

def _enforce_local_only_models(local_only_models, selected_models):
    """
    Blocks non-local model identifiers when local-only mode is enabled.
    selected_models: iterable of tuples [(label, model_id), ...]
    """
    if not local_only_models:
        return
    invalid = []
    for label, model_id in selected_models:
        if model_id and str(model_id).strip() and str(model_id).strip().lower() not in ("none", "<none>"):
            if not _is_local_model_id(model_id):
                invalid.append(f"{label}='{model_id}'")
    if invalid:
        details = ", ".join(invalid)
        raise ValueError(
            "Local-only mode is enabled. Non-local model selection blocked: "
            f"{details}. Use local providers only (gguf/, hf/, ollama/, lmstudio/, text-generation-webui/)."
        )

# ------------------------------------------------------------------------------------
# Helper function to read node descriptions from HELP.md
# ------------------------------------------------------------------------------------
def get_node_description(node_name):
    """Parses HELP.md and extracts the description for a given node class name."""
    try:
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
# PromptCrafter Creator Nodes (Base, Image, Video, Lyrics)
# ------------------------------------------------------------------------------------
from ..core.pgfx_base_creator import PromptCrafter_BaseCreator

# ------------------------------------------------------------------------------------
# PromptCrafter_VisualCreator Node
# ------------------------------------------------------------------------------------
class PromptCrafter_VisualCreator(PromptCrafter_BaseCreator):
    DESCRIPTION = get_node_description("PromptCrafter_VisualCreator")
    @classmethod
    def INPUT_TYPES(cls):
        combined_models = get_combined_models()
        return {
            "required": {
                "response_mode": (["Predictable", "Creative"], {"default": "Predictable", "tooltip": "Predictable = deterministic, instruction-only. Creative = current behavior."}),
                "pipeline_mode": (["Image", "Video"], {"default": "Image"}),
                "instruction": ("STRING", {"multiline": True, "default": config.DEFAULT_PROMPT_TEXT}),
                "subject": ("STRING", {"multiline": True, "default": "" } ),
                "model": (combined_models, {"tooltip": "The language model to use. Prefer local backends (gguf/, hf/, or local provider runtimes)."} ),
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
                "llm_device": (config.LLM_DEVICE_OPTIONS, {"default": config.DEFAULT_LLM_DEVICE}),
                "reset_context": ("BOOLEAN", {"default": config.DEFAULT_LLM_STATELESS}),
                "local_only_models": ("BOOLEAN", {"default": True}),
                "style_tags": ("STRING", {"multiline": False, "default": ""}),
                "target_model_format": (["Generic (SD1.5, SD2.1)", "Fooocus", "Stable Diffusion 3", "Stable Cascade", "FLUX / Qwen / Hunyuan", "LTX-2 (Audio/Lip Sync/Retake)"], {"default": "Generic (SD1.5, SD2.1)"}),
                "generate_schedule": ("BOOLEAN", {"default": False}),
                "max_frames": ("INT", {"default": 240, "min": 1, "max": 99999}),
                "interpolate_keyframes": ("BOOLEAN", {"default": False}),
                "interpolation_frame_interval": ("INT", {"default": 10, "min": 0, "max": 16}),
                "format_profile": (text_io.CREATOR_FORMAT_PROFILE_OPTIONS, {"default": "Custom"}),
                "output_target": (text_io.VISUAL_OUTPUT_TARGET_OPTIONS, {"default": "Prompt"}),
                "output_format": (text_io.FORMAT_OPTIONS, {"default": "Plain Text"}),
                "auto_save": ("BOOLEAN", {"default": False}),
                "auto_save_target": (text_io.VISUAL_OUTPUT_TARGET_OPTIONS, {"default": "Prompt"}),
                "auto_save_folder_path": ("STRING", {"multiline": False, "default": "ComfyUI/output/PromptCrafter"}),
                "auto_save_filename_template": ("STRING", {"multiline": False, "default": "{seed}_{model_name}_{target}.txt"}),
                "auto_save_file_type": (text_io.AUTO_FILE_TYPE_OPTIONS, {"default": "Match Output Format"}),
                "auto_save_custom_var": ("STRING", {"multiline": False, "default": ""}),
            },
        }

    MAX_IMAGES = 5
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING") + ("IMAGE",) * MAX_IMAGES
    RETURN_NAMES = ("prompt", "schedule", "image_context", "negative_prompt", "model_out", "seed_out") + tuple(f"reference_image_{i}" for i in range(1, MAX_IMAGES + 1))
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Creator"

    def execute(self, instruction, subject, model, negative_prompt="", **kwargs):
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
            _enforce_local_only_models(
                bool(kwargs.get("local_only_models", True)),
                (
                    ("model", model),
                    ("thinking_model", thinking_model),
                    ("instruct_model", instruct_model),
                ),
            )

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
            initial_run_config = self._setup_config(PromptCrafter_VisualCreator, pipeline_mode, user_text, model, images_with_weights=images_with_weights, **kwargs)
            
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

                ok_think, reasoning_log = api_clients.query_model_auto(
                    thinking_model,
                    thinking_prompt,
                    images=[img for img, _ in images_with_weights],
                    prefer_chat=True,
                    temperature=initial_run_config.temperature,
                    seed=initial_run_config.seed,
                    timeout=initial_run_config.timeout,
                    llm_device=initial_run_config.llm_device,
                    reset_context=initial_run_config.reset_context,
                    debug_mode=kwargs.get('debug_mode', False),
                    debug_title="Dual-Model Stage 1: Thinker"
                )

                if not ok_think or not reasoning_log or not reasoning_log.strip():
                    return self._handle_creator_exception(Exception(f"Dual-Model Stage 1 (Thinker) failed or returned empty: {reasoning_log}"))

                reasoning_for_instruct = reasoning_log.split("### REASONING", 1)[1].strip() if "### REASONING" in reasoning_log else reasoning_log.strip()
                
                instruct_schema = {
                    "positive_prompt": "string (The final prompt)",
                    "negative_prompt": "string (The negative prompt)"
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
                """).strip()

                instruct_timeout = 0 if str(instruct_model).lower().startswith("gguf/") else initial_run_config.timeout
                ok, result_data = api_clients._reason_with_model(
                    instruct_model,
                    instruct_prompt,
                    images=[],
                    use_chat_api=True,
                    temperature=0.0,
                    seed=initial_run_config.seed,
                    timeout=instruct_timeout,
                    llm_device=initial_run_config.llm_device,
                    reset_context=initial_run_config.reset_context,
                    debug_mode=kwargs.get('debug_mode', False),
                    debug_title="Dual-Model Stage 2: Instructor (JSON)"
                )
                
                if not ok or not result_data:
                    return self._handle_creator_exception(Exception(f"Dual-Model Stage 2 (Instruct) failed: {result_data}"))

                if isinstance(result_data, str):
                    cleaned_result = json_utils.strip_markdown_code_fences(result_data)
                    try:
                        result_data = json.loads(cleaned_result)
                    except:
                        try:
                            repaired = json_utils.repair_truncated_json(cleaned_result)
                            result_data = json.loads(repaired)
                        except Exception as e:
                            return self._handle_creator_exception(Exception(f"Dual-Model Stage 2 (Instruct) failed to return valid JSON: {e}"))

                if not isinstance(result_data, dict):
                    return self._handle_creator_exception(Exception("Dual-Model Stage 2 (Instruct) failed to return a JSON object."))

                final_prompt = result_data.get("positive_prompt", "")
                final_negative_prompt = result_data.get("negative_prompt", "")
                final_prompt = self._format_prompt_for_target(final_prompt, target_model_format)

                passthrough_images = [img for img, _ in images_with_weights]
                passthrough_images.extend([None] * (self.MAX_IMAGES - len(passthrough_images)))

                final_image_context = f"--- REASONING LOG ---\n{reasoning_log}\n\n--- IMAGE CONTEXT ---\n{image_context}"
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
                if response_mode == "Predictable":
                    error, new_user_text = None, None
                else:
                    error, new_user_text = self._handle_creative_intent(pipeline_mode, user_text, images_with_weights, initial_run_config)
                if error: 
                    return (error,) + (None,) * (len(self.RETURN_TYPES) - 1)
                final_user_text = new_user_text or user_text
                
                run_config = self._setup_config(PromptCrafter_VisualCreator, pipeline_mode, final_user_text, model, images_with_weights=images_with_weights, **kwargs)
                
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
                    if image_context_for_all:
                        image_context_out, _, primary_subjects_from_images = image_context_for_all
                    else:
                        image_context_out, primary_subjects_from_images = "", []
                    
                    style_rules = self._build_style_and_composition_rules("Image", [img for img, _ in images_with_weights], run_config, final_user_text, "", image_context_out)
                    
                    final_prompt = self._generate_prompt_for_scene(
                        final_user_text,
                        "Image",
                        images_with_weights,
                        image_context_out,
                        style_rules,
                        run_config,
                        primary_subjects_from_images=primary_subjects_from_images,
                        **kwargs,
                    )
                    
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
    DESCRIPTION = get_node_description("PromptCrafter_LyricsCreator")
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
        types["required"]["model"] = (combined_models, {"tooltip": "The language model to use. Prefer local backends (gguf/, hf/, or local provider runtimes)."} )
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
            "audio_file": ("STRING", {"multiline": False, "default": "<none>"}),
            "lyrics_file": ("STRING", {"multiline": False, "default": "<none>"}),
            "use_audio_alignment": ("BOOLEAN", {"default": True}),
            "song_length_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 3600.0, "step": 0.1}),
            "fps": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.5}),
            "scene_splitting_mode": (["Structural Tag", "Fixed Duration", "Frame Length"], {"default": "Structural Tag"}),
            "max_scene_duration_seconds": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 60.0, "step": 0.1}),
            "max_scene_frames": ("INT", {"default": 120, "min": 0, "max": 4096, "step": 1}),
            "whisper_model": (cls.get_whisper_models(), {"default": "large-v3"}),
            "whisper_language": (["auto-detect", "en", "es", "fr", "de", "it", "pt", "is", "ru", "ja", "ko", "zh"], {"default": "auto-detect"}),
            "whisper_engine": (["faster-whisper", "insanely-fast-whisper"], {"default": "faster-whisper"}),
            "target_model_format": (["Generic (SD1.5, SD2.1)", "Fooocus", "Stable Diffusion 3", "Stable Cascade", "FLUX / Qwen / Hunyuan", "LTX-2 (Audio/Lip Sync/Retake)"], {"default": "LTX-2 (Audio/Lip Sync/Retake)"}),
            "automate_vrg_variables": ("BOOLEAN", {"default": False}),
            "character_description": ("STRING", {"multiline": True, "default": "The Women."} ),
            "song_theme_style": ("STRING", {"multiline": True, "default": "cinematic realism, emotional storytelling, soft surrealism, naturalistic tone, dreamlike nostalgia, modern drama, poetic symbolism, intimate atmosphere"}),
            "word_count_min": ("INT", {"default": 30, "min": 10, "max": 200}),
            "word_count_max": ("INT", {"default": 50, "min": 10, "max": 200}),
            "list_handling_mode": (["Strict Cycle", "Reference Guide", "Random Selection", "Free Interpretation"], {"default": "Reference Guide"}),
            "environment": ("STRING", {"multiline": True, "default": "open field at dusk, dimly lit bedroom, empty city street at night, forest clearing with morning fog, seaside cliff at golden hour, rainy urban alley, sunlit living room, desert road at sunrise"}),
            "lighting": ("STRING", {"multiline": True, "default": "warm amber glow, cool window light, neon reflections, diffused morning light, soft backlight haze, flickering streetlights, gentle afternoon sun, pink-orange dawn light"}),
            "camera_motion": ("STRING", {"multiline": True, "default": "push in, pull back, pan left, pan right, tilt up, tilt down, track forward, orbit"}),
            "physical_interaction": ("STRING", {"multiline": True, "default": "walking through tall grass, lying on bed staring upward, leaning against a wall in stillness, reaching toward sunlight, hair moving in wind, footsteps in puddles, brushing hand across furniture, standing motionless in breeze"}),
            "facial_expression": ("STRING", {"multiline": True, "default": "Intense raw emotion"}),
            "shots": ("STRING", {"multiline": True, "default": "close up, medium shot, wide shot, over the shoulder, establishing shot, low angle, high angle, overhead shot"}),
            "outfit_rules": ("STRING", {"multiline": True, "default": "a white dress"}),
            "character_visibility": ("STRING", {"multiline": True, "default": "mostly visible, half-shadowed, silhouetted, reflected or obscured, seen from behind, partially out of frame, emerging from light, fading into darkness"}),
        })
        types["optional"]["generate_schedule"] = ("BOOLEAN", {"default": True})
        types["optional"]["interpolate_keyframes"] = ("BOOLEAN", {"default": False})
        types["optional"]["interpolation_frame_interval"] = ("INT", {"default": 0, "min": 0, "max": 16})

        for k in ["output_target", "auto_save_target"]:
            if k in types["optional"]:
                types["optional"][k] = (text_io.LYRICS_OUTPUT_TARGET_OPTIONS, {"default": "Schedule"})
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
    RETURN_TYPES = STATIC_RETURN_TYPES + ("IMAGE",) * MAX_DYNAMIC_IMAGES + ("STRING",)
    RETURN_NAMES = STATIC_RETURN_NAMES + tuple(f"reference_image_{i}" for i in range(1, MAX_DYNAMIC_IMAGES + 1)) + ("schedule_json",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Creator"

    @staticmethod
    def _resolve_schedule_json_output(schedule_value):
        if schedule_value is None:
            return ""
        if isinstance(schedule_value, dict):
            return json.dumps(schedule_value, indent=2, ensure_ascii=False)
        if isinstance(schedule_value, str):
            if not schedule_value.strip():
                return ""
            try:
                parsed = json_utils.extract_and_parse_json(schedule_value)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                return json.dumps(parsed, indent=2, ensure_ascii=False)
            return schedule_value
        return str(schedule_value)

    @classmethod
    def _make_json_safe_output(cls, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value

        if isinstance(value, dict):
            safe = {}
            for key, item in value.items():
                safe[str(key)] = cls._make_json_safe_output(item)
            return safe

        if isinstance(value, (list, tuple, set)):
            return [cls._make_json_safe_output(item) for item in value]

        if isinstance(value, Image.Image):
            return {
                "_type": "PIL.Image",
                "mode": value.mode,
                "size": list(value.size),
            }

        if torch.is_tensor(value):
            return {
                "_type": "torch.Tensor",
                "shape": list(value.shape),
                "dtype": str(value.dtype),
            }

        if hasattr(value, "item"):
            try:
                return value.item()
            except Exception:
                pass

        if hasattr(value, "tolist"):
            try:
                return value.tolist()
            except Exception:
                pass

        return str(value)

    def execute(self, instruction, subject, model, negative_prompt="", **kwargs):
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
            _enforce_local_only_models(
                bool(kwargs.get("local_only_models", True)),
                (
                    ("model", model),
                    ("thinking_model", thinking_model),
                    ("instruct_model", instruct_model),
                ),
            )
            user_text = instruction
            if subject and subject.strip():
                user_text = f"SUBJECT:\n{subject}\n\nINSTRUCTION:\n{instruction}"

            images_with_weights = self._collect_images_with_weights(**kwargs)
            run_config = self._setup_config(PromptCrafter_LyricsCreator, "Lyrics", user_text, model, images_with_weights=images_with_weights, **kwargs)
            format_profile = kwargs.get("format_profile", "Custom")
            output_target = kwargs.get("output_target", "Schedule")
            output_format = kwargs.get("output_format", "Plain Text")
            auto_save = kwargs.get("auto_save", False)
            auto_save_target = kwargs.get("auto_save_target", "Schedule")

            if format_profile and format_profile != "Custom":
                profile = text_io.CREATOR_FORMAT_PROFILES.get(format_profile)
                if profile:
                    output_target = profile.get("output_target", output_target)
                    output_format = profile.get("output_format", output_format)
                    auto_save = profile.get("auto_save", auto_save)
                    auto_save_target = profile.get("auto_save_target", auto_save_target)
            
            # --- DUAL-MODEL CHAIN PATH ---
            if thinking_model and instruct_model and "None" not in thinking_model and "None" not in instruct_model:
                print(f"\033[94m[PromptCrafter] Dual-Model mode activated for Lyrics Creator.\033[0m")
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
                                try:
                                    torchaudio.set_audio_backend("soundfile")
                                except Exception:
                                    pass
                                waveform, sample_rate = torchaudio.load(audio_path)
                            except Exception as e:
                                if librosa:
                                    audio_np, sample_rate = librosa.load(audio_path, sr=None, mono=False)
                                    waveform = torch.from_numpy(audio_np)
                                    if waveform.ndim == 1:
                                        waveform = waveform.unsqueeze(0)
                                else:
                                    raise ImportError("Neither torchaudio nor librosa could load audio.")
                            
                            audio_data = {"waveform": waveform.unsqueeze(0) if waveform.ndim == 2 else waveform, "sample_rate": sample_rate}
                            srt_node = pgfx_srt_creator.PromptCrafter_SRTCreator()
                            srt_res = srt_node.execute(
                                audio_data,
                                kwargs.get("whisper_model", "large-v3"),
                                kwargs.get("whisper_language", "en"),
                                "silero",
                                bool(instruct_model),
                                instruct_model or "large-v3",
                                False,
                                kwargs.get("debug_mode", False),
                                5.0,
                                False,
                                False,
                                ground_truth_script="",
                            )
                            
                            lyrics_srt = srt_res[0]
                            clean_lyrics_txt = srt_res[1]
                            if srt_res[3]:
                                parsed = json_utils.extract_and_parse_json(srt_res[3])
                                timed_segments = parsed if isinstance(parsed, list) else []
                                
                            audio_meta = {
                                "audio_total_duration": float(waveform.shape[-1]) / sample_rate,
                                "sample_rate": sample_rate,
                                "timed_segments": timed_segments,
                                "vocal_audio": audio_data
                            }
                        except Exception as e:
                            print(f"\033[91m[PromptCrafter] Audio processing failed: {e}\033[0m")

                thinking_prompt = textwrap.dedent(f"""
                    You are a music video director. Your task is to brainstorm a sequence of cinematic scenes for the provided lyrics.

                    **SONG LYRICS:**
                    {clean_lyrics_txt}
                    **SONG THEME / STYLE:**
                    {kwargs.get('song_theme_style', 'cinematic')}
                    **CHARACTER:**
                    {kwargs.get('character_description', 'main singer')}
                    
                    **TASK:**
                    Think step-by-step. Break the song into logical scenes. For each scene, describe the visual action, the camera shot, and the mood.
                    Write down your creative reasoning and a scene-by-scene plan for the final prompt schedule.
                """).strip()

                thinking_timeout = 0 if str(thinking_model).lower().startswith("gguf/") else run_config.timeout
                ok_think, reasoning_txt = api_clients.query_model_auto(
                    thinking_model, thinking_prompt, images=[], prefer_chat=True,
                    temperature=run_config.temperature, seed=run_config.seed, timeout=thinking_timeout,
                    llm_device=run_config.llm_device, reset_context=run_config.reset_context,
                    debug_mode=kwargs.get('debug_mode', False), debug_title="Dual-Model Stage 1: Thinker (Lyrics)"
                )
                if not ok_think or not reasoning_txt:
                    return self._handle_creator_exception(Exception("Dual-Model Stage 1 (Thinker) failed."))

                instruct_schema = {
                    "prompt_schedule": {
                        "0": "prompt at frame 0",
                        "120": "prompt at frame 120"
                    }
                }
                instruct_prompt = textwrap.dedent(f"""
                    Based on the following creative reasoning, generate a JSON object containing the prompt schedule.
                    The keys of the 'prompt_schedule' object must be frame numbers (as strings).
                    **REASONING:**
                    {reasoning_txt}

                    **JSON SCHEMA:**
                    ```json
                    {json.dumps(instruct_schema, indent=2)}
                    ```
                    Return ONLY the JSON object.
                """).strip()

                instruct_timeout = 0 if str(instruct_model).lower().startswith("gguf/") else run_config.timeout
                ok_instruct, result_data = api_clients._reason_with_model(
                    instruct_model, instruct_prompt, images=[], use_chat_api=True,
                    temperature=0.0, seed=run_config.seed, timeout=instruct_timeout,
                    llm_device=run_config.llm_device, reset_context=run_config.reset_context,
                    debug_mode=kwargs.get('debug_mode', False), debug_title="Dual-Model Stage 2: Instructor (Lyrics)"
                )
                if not ok_instruct or not result_data:
                    return self._handle_creator_exception(Exception("Dual-Model Stage 2 (Instruct) failed."))

                if isinstance(result_data, str):
                    cleaned = json_utils.strip_markdown_code_fences(result_data)
                    try:
                        result_data = json.loads(cleaned)
                    except:
                        try:
                            result_data = json.loads(json_utils.repair_truncated_json(cleaned))
                        except Exception as e:
                            return self._handle_creator_exception(Exception(f"Dual-Model Stage 2 returned invalid JSON: {e}"))

                if not isinstance(result_data, dict) or "prompt_schedule" not in result_data:
                    return self._handle_creator_exception(Exception("Dual-Model Stage 2 failed to return a valid prompt_schedule."))
                
                schedule_json = json.dumps(result_data["prompt_schedule"], indent=4)
                passthrough_images = [img for img, _ in images_with_weights]
                passthrough_images.extend([None] * (self.MAX_DYNAMIC_IMAGES - len(passthrough_images)))
                
                spec_preview = spectrogram_preview if spectrogram_preview is not None else torch.zeros((1, 64, 64, 3))
                if isinstance(spec_preview, Image.Image):
                    spec_preview = utils.pil2tensor(spec_preview)

                outputs_map = {
                    "Prompt": "",
                    "Schedule": schedule_json,
                    "Image Context": "",
                    "Negative Prompt": "",
                    "Clean Lyrics": clean_lyrics_txt,
                    "Lyrics SRT": lyrics_srt
                }
                formatted_map = self._apply_output_formatting_map(outputs_map, output_target, output_format, text_io.LYRICS_OUTPUT_TARGET_OPTIONS)
                p_out = formatted_map.get("Prompt", "") or formatted_map.get("Schedule", schedule_json)
                
                return (
                    p_out, formatted_map.get("Schedule", schedule_json), "", "", 
                    formatted_map.get("Clean Lyrics", clean_lyrics_txt), formatted_map.get("Lyrics SRT", lyrics_srt), 
                    model, str(run_config.seed), self._make_json_safe_output(audio_meta), spec_preview, 
                    kwargs.get("signal"), kwargs.get("character_description"), kwargs.get("song_theme_style"), 
                    kwargs.get("environment"), kwargs.get("lighting"), kwargs.get("physical_interaction"), 
                    kwargs.get("facial_expression"), kwargs.get("shots"), kwargs.get("outfit_rules"), 
                    kwargs.get("character_visibility")
                ) + tuple(passthrough_images) + (self._resolve_schedule_json_output(schedule_json),)

            # --- LEGACY SINGLE-MODEL PATH ---
            else:
                res_desc = self._describe_images(images_with_weights, run_config)
                img_ctx, subjects = (res_desc[0], res_desc[2]) if res_desc else ("", [])
                l_kwargs = kwargs.copy()
                _l_map = {
                    "audio_file": "lyrics_audio_file", "lyrics_file": "lyrics_lyrics_file", 
                    "audio_folder_path": "lyrics_audio_folder_path", "lyrics_folder_path": "lyrics_lyrics_folder_path", 
                    "use_audio_alignment": "lyrics_use_audio_alignment", "song_length_seconds": "lyrics_song_length_seconds", 
                    "fps": "lyrics_fps", "scene_splitting_mode": "lyrics_scene_splitting_mode", 
                    "max_scene_duration_seconds": "lyrics_max_scene_duration_seconds", "max_scene_frames": "lyrics_max_scene_frames", 
                    "whisper_model": "lyrics_whisper_model_size", "whisper_language": "lyrics_whisper_language", 
                    "whisper_engine": "lyrics_whisper_engine", "character_description": "lyrics_character_description", 
                    "song_theme_style": "lyrics_song_theme_style", "word_count_min": "lyrics_word_count_min", 
                    "word_count_max": "lyrics_word_count_max", "list_handling_mode": "lyrics_list_handling_mode", 
                    "environment": "lyrics_environment", "lighting": "lyrics_lighting", 
                    "camera_motion": "lyrics_camera_motion", "physical_interaction": "lyrics_physical_interaction", 
                    "facial_expression": "lyrics_facial_expression", "shots": "lyrics_shots", 
                    "outfit_rules": "lyrics_outfit_rules", "character_visibility": "lyrics_character_visibility", 
                    "generate_schedule": "lyrics_generate_schedule", "interpolate_keyframes": "lyrics_interpolate_keyframes", 
                    "interpolation_frame_interval": "lyrics_interpolation_frame_interval", "target_model_format": "lyrics_target_model_format"
                }
                for sk, dk in _l_map.items(): 
                    if sk in kwargs: l_kwargs[dk] = kwargs[sk]
                
                thought = thinking_process.ThoughtProcess(
                    run_config=run_config, user_text=user_text, negative_prompt=negative_prompt, 
                    image_context=img_ctx, primary_subjects_from_images=subjects, mode="Lyrics", **l_kwargs
                )
                result = thought.run()
                if isinstance(result, dict):
                    prompt, schedule, img_ctx_res, neg_out, cl_txt, l_srt, a_meta, spec_pre = \
                        result.get("prompt", ""), result.get("schedule", ""), result.get("image_context", img_ctx), \
                        result.get("negative_prompt", ""), result.get("clean_lyrics_txt", ""), result.get("lyrics_srt", ""), \
                        result.get("audio_meta", {}), result.get("spectrogram_preview")
                    ac, at, ae, al, ai, ax, asht, ao, av = [result.get(f"auto_{x}", kwargs.get(x)) for x in ["character", "theme", "environment", "lighting", "interaction", "expression", "shots", "outfit", "visibility"]]
                else: 
                    return self._handle_creator_exception(Exception("Invalid engine output."))

                if schedule and isinstance(schedule, str) and schedule.strip() != "{}":
                    schedule = self._enhance_schedule_with_talent_direction(schedule, cl_txt, model, a_meta.get("timed_segments", []))
                if prompt: 
                    prompt = self._enhance_prompt_with_talent_direction(prompt, cl_txt, model)
                
                if spec_pre is not None and isinstance(spec_pre, Image.Image):
                    spec_pre = utils.pil2tensor(spec_pre)
                elif spec_pre is None:
                    spec_pre = torch.zeros((1, 64, 64, 3))
                
                passthrough_images = [img for img, _ in images_with_weights]
                passthrough_images.extend([None] * (self.MAX_DYNAMIC_IMAGES - len(passthrough_images)))
                
                outputs_map = {
                    "Prompt": prompt, "Schedule": schedule, "Image Context": img_ctx_res, 
                    "Negative Prompt": neg_out, "Clean Lyrics": cl_txt, "Lyrics SRT": l_srt
                }
                formatted_map = self._apply_output_formatting_map(outputs_map, output_target, output_format, text_io.LYRICS_OUTPUT_TARGET_OPTIONS)
                p_out = formatted_map.get("Prompt", prompt) or formatted_map.get("Schedule", schedule)
                return (
                    p_out, formatted_map.get("Schedule", schedule), formatted_map.get("Image Context", img_ctx_res), 
                    formatted_map.get("Negative Prompt", neg_out), formatted_map.get("Clean Lyrics", cl_txt), 
                    formatted_map.get("Lyrics SRT", l_srt), model, str(run_config.seed), 
                    self._make_json_safe_output(a_meta), spec_pre, kwargs.get("signal"), 
                    ac, at, ae, al, ai, ax, asht, ao, av
                ) + tuple(passthrough_images) + (self._resolve_schedule_json_output(schedule),)
        except Exception as e: 
            return self._handle_creator_exception(e)

# ------------------------------------------------------------------------------------
# Easy / Simplified Variants
# ------------------------------------------------------------------------------------
class PromptCrafter_VisualCreatorEasy(PromptCrafter_VisualCreator):
    DESCRIPTION = get_node_description("PromptCrafter_VisualCreatorEasy")
    @classmethod
    def INPUT_TYPES(cls):
        combined_models = get_combined_models()
        return {
            "required": {
                "instruction": ("STRING", {"multiline": True, "default": config.DEFAULT_PROMPT_TEXT}), 
                "subject": ("STRING", {"multiline": True, "default": ""}), 
                "model": (combined_models, {}), 
                "pipeline_mode": (["Image", "Video"], {"default": "Image"}), 
                "target_model_format": (["Generic (SD1.5, SD2.1)", "Fooocus", "Stable Diffusion 3", "Stable Cascade", "FLUX / Qwen / Hunyuan", "LTX-2 (Audio/Lip Sync/Retake)"], {"default": "Generic (SD1.5, SD2.1)"}), 
                "style_override": (style_profiles.get_style_override_options("Image"), {"default": "None"}), 
                "image_count": ("INT", {"default": 1}), 
                "seed": ("INT", {"default": -1})
            }, 
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "negative_prompt": "STRING"}
        }
    def execute(self, instruction, subject, model, negative_prompt="", **kwargs):
        kwargs.update({"response_mode": "Creative", "temperature": 0.3, "artistry_level": 7, "creativity_level": 7, "logicality_level": 7, "deep_think_refinements": 3, "simplify_for_diffusion": True, "timeout": 120, "max_retries": 2, "safe_mode": True, "local_only_models": True})
        return super().execute(instruction, subject, model, negative_prompt=negative_prompt, **kwargs)

class PromptCrafter_LyricsCreatorEasy(PromptCrafter_LyricsCreator):
    DESCRIPTION = get_node_description("PromptCrafter_LyricsCreatorEasy")
    @classmethod
    def INPUT_TYPES(cls):
        combined_models = get_combined_models()
        return {
            "required": {
                "instruction": ("STRING", {"multiline": True, "default": config.DEFAULT_PROMPT_TEXT}), 
                "subject": ("STRING", {"multiline": True, "default": ""}), 
                "model": (combined_models, {}), 
                "target_model_format": (["Generic (SD1.5, SD2.1)", "Fooocus", "Stable Diffusion 3", "Stable Cascade", "FLUX / Qwen / Hunyuan", "LTX-2 (Audio/Lip Sync/Retake)"], {"default": "LTX-2 (Audio/Lip Sync/Retake)"}), 
                "style_override": (style_profiles.get_style_override_options("Lyrics"), {"default": "None"}), 
                "image_count": ("INT", {"default": 1}), 
                "audio_file": ("STRING", {"default": "<none>"}), 
                "lyrics_file": ("STRING", {"default": "<none>"}), 
                "whisper_model": (cls.get_whisper_models(), {"default": "large-v3"}), 
                "whisper_language": (["auto-detect", "en", "es", "fr", "de", "it", "pt", "is", "ru", "ja", "ko", "zh"], {"default": "auto-detect"}), 
                "seed": ("INT", {"default": -1})
            }, 
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "negative_prompt": "STRING"}
        }
    def execute(self, instruction, subject, model, negative_prompt="", **kwargs):
        kwargs.update({"response_mode": "Creative", "temperature": 0.3, "artistry_level": 7, "creativity_level": 7, "logicality_level": 7, "deep_think_refinements": 3, "simplify_for_diffusion": True, "timeout": 120, "max_retries": 2, "safe_mode": True, "local_only_models": True, "use_audio_alignment": True, "fps": 16.0, "scene_splitting_mode": "Structural Tag", "max_scene_duration_seconds": 5.0, "max_scene_frames": 120, "whisper_engine": "faster-whisper", "character_description": "The Women.", "song_theme_style": "cinematic realism", "word_count_min": 30, "word_count_max": 50})
        return super().execute(instruction, subject, model, negative_prompt=negative_prompt, **kwargs)

# ------------------------------------------------------------------------------------
# Node Mappings
# ------------------------------------------------------------------------------------
NODE_CLASS_MAPPINGS = {
    "PromptCrafter_VisualCreator": PromptCrafter_VisualCreator,
    "PromptCrafter_LyricsCreator": PromptCrafter_LyricsCreator,
    "PromptCrafter_VisualCreatorEasy": PromptCrafter_VisualCreatorEasy,
    "PromptCrafter_LyricsCreatorEasy": PromptCrafter_LyricsCreatorEasy,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_VisualCreator": "✨ Image → Prompt",
    "PromptCrafter_LyricsCreator": "🎤 Lyrics → Prompt",
    "PromptCrafter_VisualCreatorEasy": "✨ Easy Image → Prompt",
    "PromptCrafter_LyricsCreatorEasy": "🎤 Easy Lyrics → Prompt",
}
