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
import textwrap

# Third-party imports
import torch
from PIL import Image

# ComfyUI imports
import comfy.utils

# Local module imports
from . import api_clients
from . import config
from . import style_profiles
from . import utils
from . import organization_profiles
from . import captioner_profiles

# ------------------------------------------------------------------------------------
# PromptCrafter_QnA Node
# ------------------------------------------------------------------------------------
class PromptCrafter_QnA:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "user_text": ("STRING", {"multiline": True, "default": config.DEFAULT_PROMPT_TEXT, "tooltip": "Your question or instruction for the model."}),
                "model": (api_clients.get_all_models(), {"tooltip": "The language model (text or vision) to use for the answer."}),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Controls creativity. Lower is more deterministic."}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "step": 1, "tooltip": "Seed for reproducible results. -1 for random. Set Temperature to 0 for full determinism."}),
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10, "tooltip": "Timeout in seconds for each API call. Increase if you get timeout errors."} ),
                "safe_mode": ("BOOLEAN", {"default": True, "tooltip": "Enforce SFW rules to prevent NSFW, violent, or controversial content."} ),
                "debug_mode": ("BOOLEAN", {"default": False, "tooltip": "Print all intermediate prompts to the console for debugging."} ),
                "save_to_txt": ("BOOLEAN", {"default": False, "tooltip": "Save the full Q&A context and response to a text file in the ComfyUI/output directory."} ),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
            "optional": {
                "image": ("IMAGE", {"tooltip": "Optional reference image for the query. Requires a vision model (VLM)."}),
                "auto_select_model": ("BOOLEAN", {"default": True, "tooltip": "Automatically select a vision model if an image is connected, or a text model if not."} ),
                "enable_web_search": ("BOOLEAN", {"default": True, "tooltip": "Allow the node to perform a web search for questions about recent events or topics requiring current information."} ),
                "fast_web_search": ("BOOLEAN", {"default": True, "tooltip": "In web search mode, only use search result snippets instead of fetching full page content. Much faster."} ),
                "folder_path": ("STRING", {"multiline": False, "default": "input", "tooltip": "Folder containing an optional context file (e.g., 'input' or 'input/texts')."}),
                "filename_prefix": ("STRING", {"multiline": False, "default": "PromptCrafter/QnA", "tooltip": "Subdirectory and prefix for the saved text file."} ),
                "file_name": ("STRING", {"multiline": False, "default": "<none>", "tooltip": "The name of the text file within the specified folder."} ),
                "chunk_large_context": ("BOOLEAN", {"default": True, "tooltip": "Automatically chunk and summarize context files that are too large."} ),
                "chunk_size_words": ("INT", {"default": 2000, "min": 500, "max": 8000, "step": 100, "tooltip": "The approximate size of each chunk in words for summarization."} ),
                "summarization_strategy": (["Default (Abstractive)", "Extractive"], {"default": "Default (Abstractive)", "tooltip": "How to summarize large context. Abstractive creates new text, Extractive pulls key sentences."} ),
                "history_in": ("STRING", {"multiline": False, "default": "", "input": "hidden"}),
                "clear_history": ("BOOLEAN", {"default": False, "tooltip": "Set to True for one run to clear the conversation history."} ),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("response", "history_out")
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter"
    
    def execute(self, user_text, model, **kwargs):
        try:
            # Extract parameters from kwargs with defaults
            image = kwargs.get("image")
            auto_select_model = kwargs.get("auto_select_model", True)
            history_in = kwargs.get("history_in", "")
            clear_history = kwargs.get("clear_history", False)
            folder_path = kwargs.get("folder_path")
            file_name = kwargs.get("file_name", "<none>")
            enable_web_search = kwargs.get("enable_web_search", True)
            seed = kwargs.get("seed", -1)
            debug_mode = kwargs.get("debug_mode", False)
            timeout = kwargs.get("timeout", 120)
            fast_web_search = kwargs.get("fast_web_search", True)
            summarization_strategy = kwargs.get("summarization_strategy", "Default (Abstractive)")
            chunk_large_context = kwargs.get("chunk_large_context", True)
            chunk_size_words = kwargs.get("chunk_size_words", 2000)
            temperature = kwargs.get("temperature", 0.2)
            safe_mode = kwargs.get("safe_mode", True)
            save_to_txt = kwargs.get("save_to_txt", False)
            filename_prefix = kwargs.get("filename_prefix", "PromptCrafter/QnA")
            
            llm_model = model
            has_image = image is not None

            if auto_select_model:
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

            if not llm_model:
                llm_model = config.FALLBACK_TEXT_MODEL

            context, raw_context, context_source = "", "", "None"
            history_text = history_in.strip() if history_in and not clear_history else ""
            has_file_context = folder_path and file_name and file_name != "<none>"

            if has_file_context:
                fpath = utils._get_verified_path(folder_path, file_name)
                if fpath:
                    raw_context = utils.safe_read(fpath)
                    context = raw_context
                    context_source = f"File ({file_name})"
                else:
                    context = f"[Error: File not found at '{os.path.join(folder_path, file_name)}'.]"
                    raw_context = context
                    context_source = f"File ({file_name}) - Not Found"
            elif enable_web_search:
                search_needed, search_query = utils._should_perform_web_search(user_text, llm_model, seed, debug_mode, timeout=timeout)
                if search_needed and isinstance(search_query, str) and search_query.strip():
                    web_context = utils._perform_web_search(search_query, num_results=3, debug_mode=debug_mode, fast_search=fast_web_search)
                    context = web_context
                    raw_context = web_context
                    context_source = f"Web Search (query: '{search_query}')"
                elif search_needed:
                    context = "[Error: No valid search query provided for web search.]"
                    raw_context = context
                    context_source = "Web Search - Invalid Query"

            strategy_key = "extractive" if "Extractive" in summarization_strategy else "default"
            if chunk_large_context and context and not context.startswith("[Error"):
                if len(context.split()) > chunk_size_words:
                    print(f"\033[94m[PromptCrafter] Context from {context_source} is large. Summarizing...\033[0m")
                    context = utils._summarize_large_text(raw_context, chunk_size_words, llm_model, temperature, seed, debug_mode, timeout, strategy=strategy_key, user_query=user_text)
                    utils._debug_print(debug_mode, "Summarized Context", context)

            final_user_text, raw_user_text = user_text, user_text
            if chunk_large_context and len(user_text.split()) > chunk_size_words and user_text.strip() != config.DEFAULT_PROMPT_TEXT:
                print(f"\033[94m[PromptCrafter] User text is large. Summarizing...\033[0m")
                final_user_text = utils._summarize_large_text(user_text, chunk_size_words, llm_model, temperature, seed, debug_mode, timeout, strategy=strategy_key)
                utils._debug_print(debug_mode, "Summarized User Text", final_user_text)

            if (context or image is not None) and user_text.strip() == config.DEFAULT_PROMPT_TEXT:
                final_user_text = "Describe this image in detail." if image is not None else "Summarize the key points of the provided context."

            safety_rule = f"\n\n{config.SAFE_MODE_RULE}" if safe_mode else ""
            history_section = f"CONVERSATION HISTORY (for context):\n{history_text}\n\n" if history_text else ""
            context_section = f"ADDITIONAL CONTEXT (for this query only):\n{context}\n\n" if context else ""
            prompt = f"You are a helpful Q&A assistant. Answer the user's query based on the conversation history and any additional context provided.\n\n{history_section}{context_section}CURRENT USER QUERY:\n{final_user_text}{safety_rule}".strip()

            images_to_pass = [image] if image is not None else None
            ok, resp = api_clients.query_model_auto(llm_model, prompt, images=images_to_pass, prefer_chat=True, temperature=temperature, seed=seed, debug_mode=debug_mode, debug_title="QnA Prompt", timeout=timeout)

            response_text = utils.TextCleaner.single_paragraph(resp if ok else f"Ollama error: {resp}")
            new_history_entry = f"User: {final_user_text}\nAssistant: {response_text}"
            updated_history = f"{history_text}\n{new_history_entry}".strip() if history_text else new_history_entry

            if save_to_txt and response_text.strip():
                sections = []
                if history_text: sections.append(("CONVERSATION HISTORY", history_text))
                sections.append(("CONTEXT SOURCE", context_source))
                if raw_context:
                    sections.append(("CONTEXT (RAW)", raw_context))
                    if raw_context != context: sections.append(("CONTEXT (SUMMARIZED)", context))
                sections.append(("USER QUERY (RAW)" if raw_user_text != final_user_text else "USER QUERY", user_text))
                if raw_user_text != final_user_text: sections.append(("USER QUERY (SUMMARIZED)", final_user_text))
                sections.append(("RESPONSE", response_text))
                utils._save_output_to_file(filename_prefix, sections, base_filename="qna")

            return (response_text, updated_history)
        except Exception as e:
            print(f"\033[91m[PromptCrafter] Error in QnA node: {e}\033[0m")
            import traceback
            traceback.print_exc()
            return (f"An error occurred: {e}", "")

# ------------------------------------------------------------------------------------
# PromptCrafter_Captioner Node
# ------------------------------------------------------------------------------------
class PromptCrafter_Captioner:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "vision_model": (api_clients.get_all_models(), {"tooltip": "The vision language model (VLM) to use for captioning."}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
            "optional": {
                "image": ("IMAGE", {"tooltip": "The image to be captioned (for single mode)."}),
                "filename": ("STRING", {"default": "", "tooltip": "Filename for single mode (ignored in batch mode). If empty, a timestamp is used."} ),
                "batch_mode": ("BOOLEAN", {"default": False, "tooltip": "Enable batch processing of an entire folder."} ),
                "input_folder": ("STRING", {"default": "input/captions_todo", "tooltip": "Directory of images to process in batch mode (relative to ComfyUI root)."}),
                "skip_existing": ("BOOLEAN", {"default": True, "tooltip": "In batch mode, skip images that already have a corresponding .txt caption file."} ),
                "captioner_profile": (captioner_profiles.get_captioner_profile_options(), {"default": "Default (Training Style)", "tooltip": "Select a pre-configured captioning prompt. Overrides the manual prompt text box."}),
                "max_workers": ("INT", {"default": 4, "min": 1, "max": 16, "step": 1, "tooltip": "Number of parallel threads for batch processing."} ),
                "caption_prompt": ("STRING", {"multiline": True, "default": config.DEFAULT_CAPTION_PROMPT, "tooltip": "The prompt template used to guide the captioning model."} ),
                "caption_prefix": ("STRING", {"multiline": False, "default": "", "tooltip": "A single trigger word to add to every caption. Overridden by the trigger words file."} ),
                "trigger_words_folder_path": ("STRING", {"multiline": False, "default": "input", "tooltip": "Folder containing an optional file of trigger words (one per line)."}),
                "trigger_words_file": ("STRING", {"multiline": False, "default": "<none>", "tooltip": "File with a list of trigger words to be randomly chosen from for each caption."} ),
                "save_caption": ("BOOLEAN", {"default": True, "tooltip": "Save the caption to a text file."} ),
                "save_in_input_folder": ("BOOLEAN", {"default": True, "tooltip": "If True, saves the .txt caption file in the batch mode input folder alongside the image. If False, saves to the output_path."}),
                "add_caption_to_metadata": ("BOOLEAN", {"default": True, "tooltip": "Write the caption to the image's metadata (e.g., EXIF). Requires `piexif` library."} ),
                "rename_file_with_caption": ("BOOLEAN", {"default": False, "tooltip": "In batch mode, rename the image file based on the generated caption. Makes files searchable."}),
                "output_path": ("STRING", {"default": "captions", "tooltip": "Subdirectory within ComfyUI/output to save caption files."} ),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Controls creativity. Lower is more deterministic."} ),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "step": 1, "tooltip": "Seed for reproducible results. -1 for random."} ),
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10, "tooltip": "Timeout in seconds for each API call. Increase if you get timeout errors with slow models."} ),
                "safe_mode": ("BOOLEAN", {"default": True, "tooltip": "Enforce SFW rules to prevent NSFW, violent, or controversial content."} ),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("caption",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Utils"

    def _sanitize_filename(self, text, max_length=150):
        """Sanitizes a string to be a valid filename."""
        # Replace spaces and common delimiters with underscores
        text = re.sub(r'[\s,]+', '_', text)
        # Remove any characters that are not valid in filenames
        text = re.sub(r'[\\/*?:"<>|]', '', text)
        # Remove leading/trailing underscores and truncate
        return text.strip('_')[:max_length]

    def _caption_one_image(self, image_tensor, vision_model, final_caption_prompt, temperature, seed, debug_mode, timeout):
        """Helper function to run the captioning query for a single image tensor."""
        first_image = image_tensor[0] if torch.is_tensor(image_tensor) and image_tensor.ndim == 4 else image_tensor
        ok, caption = api_clients.query_model_auto(vision_model, prompt=final_caption_prompt, images=[first_image], prefer_chat=True, temperature=temperature, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title="Image Caption Prompt")
        return (True, utils.TextCleaner.single_paragraph(caption)) if ok else (False, f"Model error: {caption}")
    
    def execute(self, vision_model, image=None, batch_mode=False, input_folder=None, skip_existing=True, captioner_profile="Default (Training Style)", max_workers=4, caption_prompt=config.DEFAULT_CAPTION_PROMPT, caption_prefix="", trigger_words_folder_path="input", trigger_words_file="<none>", save_caption=True, save_in_input_folder=True, add_caption_to_metadata=True, rename_file_with_caption=False, output_path="captions", filename="", temperature=0.2, debug_mode=False, safe_mode=True, seed=-1, timeout=120, **kwargs):
        model = vision_model or config.FALLBACK_VISION_MODEL
        
        final_caption_prompt = caption_prompt # Default to manual input
        if captioner_profile != "None (Manual Prompt)":
            profile = captioner_profiles.NAMED_CAPTIONER_PROFILES.get(captioner_profile)
            if profile and "prompt" in profile:
                final_caption_prompt = profile["prompt"]
                print(f"\033[92m[PromptCrafter] Using captioner profile: '{captioner_profile}'\033[0m")

        if safe_mode and config.SAFE_MODE_RULE not in final_caption_prompt:
            final_caption_prompt = f"{final_caption_prompt}\n{config.SAFE_MODE_RULE}"

        trigger_words = []
        fpath = utils._get_verified_path(trigger_words_folder_path, trigger_words_file)
        if fpath:
            content = utils.safe_read(fpath)
            if not content.startswith("[Error"):
                trigger_words = [line.strip() for line in content.splitlines() if line.strip()]
                if trigger_words: print(f"\033[92m[PromptCrafter] Loaded {len(trigger_words)} trigger words from {trigger_words_file}.\033[0m")

        if batch_mode:
            if not input_folder: return ("Batch mode is enabled, but no input folder was provided.",)
            full_folder_path = utils._get_verified_path(input_folder, is_dir=True)
            if not full_folder_path: return (f"Input folder not found: {input_folder}",)

            image_files = [f for f in os.listdir(full_folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp'))]
            if not image_files: return (f"No images found in {full_folder_path}",)

            # Determine the output directory for caption files
            if save_in_input_folder:
                out_dir = full_folder_path
            else:
                out_dir = utils._get_and_create_output_dir(output_path)
                if not out_dir: return (f"Could not create or access output path: {output_path}",)

            processed_count, renamed_count, skipped_count, failed_count = 0, 0, 0, 0
            failed_files = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_img = {executor.submit(self._caption_one_image, comfy.utils.pil2tensor(Image.open(os.path.join(full_folder_path, img)).convert("RGB")), model, final_caption_prompt, temperature, seed, debug_mode, timeout): img for img in image_files}

                for future in concurrent.futures.as_completed(future_to_img):
                    img_filename = future_to_img[future]
                    try:
                        base_fname, img_ext = os.path.splitext(img_filename)
                        
                        # The path for the caption file depends on where we are saving it
                        if save_in_input_folder:
                            caption_filepath = os.path.join(full_folder_path, f"{base_fname}.txt")
                        else:
                            caption_filepath = os.path.join(out_dir, f"{base_fname}.txt")

                        if skip_existing and os.path.exists(caption_filepath):
                            skipped_count += 1
                            continue

                        ok, caption_text = future.result()
                        if not ok:
                            failed_count += 1
                            failed_files.append(img_filename)
                            print(f"\033[93m[PromptCrafter] Warning: Failed to caption {img_filename}: {caption_text}\033[0m")
                            continue

                        current_prefix = random.choice(trigger_words) if trigger_words else caption_prefix
                        final_caption = f"{current_prefix.strip()}, {caption_text}" if current_prefix else caption_text

                        if rename_file_with_caption:
                            sanitized_base_name = self._sanitize_filename(caption_text)
                            if not sanitized_base_name:
                                sanitized_base_name = f"caption_{int(time.time()*1000)}"

                            # When renaming, the new image and caption always live in the input folder
                            # Use the new utility to get a unique path
                            new_img_path, final_sanitized_name = utils._get_unique_filepath(full_folder_path, sanitized_base_name, img_ext)
                            sanitized_base_name = final_sanitized_name # Update base name to the unique version
                            new_caption_path = os.path.join(full_folder_path, f"{sanitized_base_name}.txt")
                            
                            if save_caption:
                                with open(new_caption_path, "w", encoding="utf-8") as f: f.write(final_caption)
                            
                            os.rename(os.path.join(full_folder_path, img_filename), new_img_path)
                            if add_caption_to_metadata:
                                utils._add_metadata_to_image(new_img_path, final_caption)
                            renamed_count += 1
                            print(f"\033[92m[PromptCrafter] Renamed & Captioned: {img_filename} -> {os.path.basename(new_img_path)}\033[0m")
                        else:
                            if save_caption:
                                with open(caption_filepath, "w", encoding="utf-8") as f: f.write(final_caption)
                            processed_count += 1
                            if add_caption_to_metadata:
                                utils._add_metadata_to_image(os.path.join(full_folder_path, img_filename), final_caption)
                            print(f"\033[92m[PromptCrafter] Captioned: {img_filename}\033[0m")

                    except Exception as e:
                        failed_count += 1
                        failed_files.append(img_filename)
                        print(f"\033[91m[PromptCrafter] An unexpected error occurred for {img_filename}: {e}\033[0m")

            status_message = f"Batch complete. Total: {len(image_files)}."
            if processed_count > 0: status_message += f" Captioned: {processed_count}."
            if renamed_count > 0: status_message += f" Renamed: {renamed_count}."
            if failed_count > 0:
                failed_files_str = ", ".join(failed_files[:5])
                if failed_count > 5: failed_files_str += f", and {failed_count - 5} more"
                status_message += f" Failed: {failed_count} ({failed_files_str})."
            else:
                status_message += " Failed: 0."
            if skipped_count > 0: status_message += f" Skipped: {skipped_count}."
            return (status_message,)

        else: # Single Mode
            if image is None: return ("No image provided for single captioning mode.",)
            if rename_file_with_caption:
                print("\033[93m[PromptCrafter] Warning: 'rename_file_with_caption' is only available in batch mode and will be ignored.\033[0m")

            ok, caption = self._caption_one_image(image, model, final_caption_prompt, temperature, seed, debug_mode, timeout)
            if not ok: return (caption,)

            current_prefix = random.choice(trigger_words) if trigger_words else caption_prefix
            final_caption = f"{current_prefix.strip()}, {caption}" if current_prefix else caption

            if save_caption:
                out_dir = utils._get_and_create_output_dir(output_path)
                fname = filename.strip() or f"caption_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time()*1000)%1000}"
                fname = self._sanitize_filename(fname, max_length=200)
                with open(os.path.join(out_dir, f"{fname}.txt"), "w", encoding="utf-8") as f:
                    f.write(final_caption)
            
            # This part is tricky for single mode as we don't have the original file path.
            # This implementation assumes the user will save the image manually, and the metadata
            # won't be added. A more advanced implementation would require a file path input.
            if add_caption_to_metadata:
                print("\033[93m[PromptCrafter] Warning: 'add_caption_to_metadata' is only fully supported in batch mode where file paths are known. Metadata was not written in single mode.\033[0m")

            return (final_caption,)


# ------------------------------------------------------------------------------------
# PromptCrafter Creator Nodes (Base, Image, Video, Lyrics)
# ------------------------------------------------------------------------------------
class PromptCrafter_BaseCreator: # noqa
    def _handle_creator_exception(self, e, **kwargs):
        """A centralized exception handler for creator nodes."""
        print(f"\033[91m[PromptCrafter] An unexpected error occurred in {type(self).__name__}: {e}\033[0m")
        import traceback
        traceback.print_exc()
        
        # Get the specific return types for the calling class instance.
        # This makes the handler generic and future-proof for new creator nodes
        # with different return signatures.
        return_types = getattr(self, 'RETURN_TYPES', [])

        error_string = f"Error in {type(self).__name__}: {e}"
        return_values = [error_string]
        
        # For the rest of the outputs, provide safe defaults based on their type.
        # Start from the second output, as the first is always the error message.
        for i in range(1, len(return_types)):
            return_type = return_types[i]
            if return_type == "STRING":
                return_values.append("")  # Empty string is safer than None for text inputs.
            else:
                return_values.append(None) # None is fine for IMAGE, etc.
        return tuple(return_values)


    def _collect_images_with_weights(self, image_count=1, image_weights_json="{}", **kwargs):
        """Collects all connected image tensors and their weights from the dynamic inputs."""
        images_with_weights = []
        weights = {}
        try:
            weights = json.loads(image_weights_json)
        except (json.JSONDecodeError, TypeError):
            print(f"\033[93m[PromptCrafter] Warning: Could not parse image_weights_json. Using default weights. Value: {image_weights_json}\033[0m")

        for i in range(1, image_count + 1):
            image = kwargs.get(f"image_{i}")
            if image is not None:
                weight = float(weights.get(f"image_weight_{i}", 1.0))
                images_with_weights.append((image, weight))
        return images_with_weights

    def _prepare_run_parameters(self, prompt_type, temperature, max_length_words, original_temp, original_max_len): # noqa
        if temperature == original_temp:
            if prompt_type == "Video": temperature = 0.4

        if max_length_words == original_max_len:
            if prompt_type == "Image": max_length_words = 200
            elif prompt_type == "Video": max_length_words = 80
            elif prompt_type == "Lyrics": max_length_words = 40
        return temperature, max_length_words

    def _setup_config(self, mode, user_text, model, images_with_weights=None, **kwargs): # noqa
        if not model or "NO_MODELS_FOUND" in model or "OLLAMA_UNREACHABLE" in model:
            raise ValueError("No vision models found or Ollama is unreachable. Please install a vision model (e.g., 'ollama run llava') or configure a remote API key.")

        input_types = getattr(type(self), "INPUT_TYPES", lambda: {})()
        original_temp = input_types.get("required", {}).get("temperature", ({}, {}))[1].get("default", 0.2)
        original_max_len = input_types.get("required", {}).get("max_length_words", ({}, {}))[1].get("default", 0)
        temperature, max_length_words = self._prepare_run_parameters(
            mode, kwargs.get('temperature'), kwargs.get('max_length_words'), original_temp, original_max_len
        )
        language = utils._detect_language(user_text)
        
        config_params = kwargs.copy()

        config_params.update({
            'model': model, 'language': language, 'temperature': temperature, 
            'max_length_words': max_length_words,
            'use_chat_api': True,
            'use_deep_think': True,
        })

        from dataclasses import fields
        config_fields = {f.name for f in fields(config.PromptCrafterRunConfig)}
        filtered_params = {k: v for k, v in config_params.items() if k in config_fields}

        run_config = config.PromptCrafterRunConfig(**filtered_params)
        
        # --- Centralized Style Profile Selection ---
        # Determine the style profile ONCE and store it in the config.
        style_tags = kwargs.get("style_tags", "").strip()
        if style_tags:
            # New "Style Tags" input takes priority for multi-style blending. # noqa
            print(f"\033[94m[PromptCrafter] Using style tags for multi-style blending: {style_tags}\033[0m")
            tag_names = [tag.strip() for tag in style_tags.split(',')]
            inspirations = []
            # Use the persona from the first valid tag.
            first_persona = "You are an expert art historian." 
            
            for i, name in enumerate(tag_names):
                profile = style_profiles.NAMED_STYLE_PROFILES.get(name)
                if profile:
                    if i == 0: # Grab persona from the first tag
                        first_persona = profile.get("persona", first_persona)
                    inspirations.append(profile.get("inspiration", ""))
            
            run_config.style_profile = {"persona": first_persona, "inspiration": "\n- ".join(filter(None, inspirations))}
        elif run_config.style_override and run_config.style_override != "None":
            # User has overridden the style.
            original_name = re.sub(r'^\(.*\)\s', '', run_config.style_override)
            if original_name in style_profiles.NAMED_STYLE_PROFILES:
                run_config.style_profile = style_profiles.NAMED_STYLE_PROFILES[original_name]
        else:
            # If override is "None" and no tags are provided, use an empty profile
            # to prevent unwanted dynamic style analysis.
            run_config.style_profile = {}

        return run_config

    def _handle_creative_intent(self, mode, user_text, images_with_weights, run_config): # noqa
        has_text = user_text and user_text.strip() and user_text.strip() != config.DEFAULT_PROMPT_TEXT
        has_images = bool(images_with_weights)

        if has_text and not has_images:
            image_keywords = ["image", "images", "picture", "pictures", "photo", "reference", "input"]
            if any(kw in user_text.lower() for kw in image_keywords):
                print("\033[94m[PromptCrafter] User text mentions images, but none are connected. Using AI to confirm intent...\033[0m")
                prompt = f"""Analyze the user's request. Does it explicitly mention using input images, reference images, or the provided images?
- If it says \"using the images\", \"based on the pictures\", etc., answer YES.
- If it just describes a scene (e.g., \"create an image of a woman\"), answer NO.
---
USER REQUEST ---
{user_text}
---
Respond with ONLY a JSON object: {{'requires_images': true/false}}"""
                ok, result = api_clients._reason_with_model(run_config.model, prompt, use_chat_api=run_config.use_chat_api, temperature=0.0, seed=run_config.seed, debug_mode=run_config.debug_mode, debug_title="Image Intent Check")
                if ok and isinstance(result, dict) and result.get("requires_images"):
                    return "Your instructions appear to refer to input images, but none were connected. Please connect reference images or rephrase your instructions.", None

        elif has_images and not has_text:
            print("\033[94m[PromptCrafter] Images provided but no text. Engaging creative autopilot to generate instructions...\033[0m")
            image_context, _ = self._describe_images(images_with_weights, run_config)
            prompt = f"""You are a creative director. Analyze the following image descriptions and invent a high-level, single-paragraph instruction for a new, creative scene that uses the subjects from the images.
- Be imaginative. Suggest a new scenario, interaction, or story.
- Do NOT just describe the images. Create a new concept.
- Example: If given images of a knight and a dragon, you might suggest: \"A cinematic scene where the knight and the dragon are not fighting, but instead stand together on a clifftop, looking out over a vast, misty valley as allies.\"

--- IMAGE DESCRIPTIONS ---
{image_context}
---
Return ONLY the single-paragraph creative instruction. No commentary.""" # noqa
            ok, new_instruction = api_clients.query_model_auto(run_config.model, prompt, prefer_chat=True, temperature=0.7, seed=run_config.seed, debug_mode=run_config.debug_mode, debug_title="Creative Autopilot")
            if ok and new_instruction:
                print(f"\033[92m[PromptCrafter] Creative Autopilot generated instruction: {new_instruction}\033[0m")
                return None, new_instruction
            else:
                return "Creative Autopilot failed to generate instructions from the images. Please provide text instructions or check your model.", None

        return None, None

    def _describe_images(self, images_with_weights, run_config):
        if not images_with_weights:
            return "No reference images provided.", []

        images = [img for img, _ in images_with_weights]
        weights = [w for _, w in images_with_weights]
        cache_key = utils._get_cache_key(images, weights, run_config.model, run_config.use_chat_api, run_config.temperature, run_config.language, run_config.safe_mode, run_config.seed, "describe_images_v4_parallel", run_config.style_profile)
        if config.CACHE.has(cache_key):
            print("\033[94m[PromptCrafter] Using cached image descriptions and primary subjects.\033[0m")
            return config.CACHE.get(cache_key)

        description_objects = []
        for idx, (img, weight) in enumerate(images_with_weights, start=1):
            if weight <= 0: continue
            description_objects.append(self._describe_one_image_with_persona(img, weight, idx, run_config))
        
        full_text_descriptions = [d.get("full_text", "") for d in description_objects]
        primary_subjects = [d.get("primary_subject", "") for d in description_objects if d.get("primary_subject")]
        
        result_text = "\n\n".join(full_text_descriptions)
        result_tuple = (result_text, primary_subjects)
        config.CACHE.set(cache_key, result_tuple)
        return result_tuple
    
    def _describe_one_image_with_persona(self, img, weight, idx, run_config):
        # Use the pre-selected profile from the config instead of re-analyzing.
        persona = run_config.style_profile.get("persona", "You are an expert art historian.")

        desc_prompt = self._build_image_description_prompt(persona, idx, run_config.language, run_config.safe_mode)
        ok, result_json = api_clients._reason_with_model(run_config.model, desc_prompt, images=[img], use_chat_api=run_config.use_chat_api, temperature=run_config.temperature, seed=run_config.seed, timeout=run_config.timeout, debug_mode=run_config.debug_mode, debug_title=f"Image Description {idx}")

        if ok and isinstance(result_json, dict):
            desc_text = utils.TextCleaner.single_paragraph(result_json.get("description", ""))
            primary_subject = result_json.get("primary_subject", "")
            return {"full_text": f"Image {idx} (Weight: {weight:.2f}): {desc_text}", "primary_subject": primary_subject}
        else:
            return {"full_text": f"Image {idx} (Weight: {weight:.2f}): [Error describing image: {result_json}]", "primary_subject": ""}

    def _build_image_description_prompt(self, persona, idx, language, safe_mode): # noqa
        safety_rule = f"\n{config.SAFE_MODE_RULE}" if safe_mode else ""
        return f"""
{persona}
Analyze Image {idx} and provide a detailed, one-paragraph description and identify the single primary subject.

Your task is to:
1.  Identify the single most important subject (the focal point).
2.  Describe the visual elements of the scene factually. Describe the subject's clothing and actions. Avoid interpreting or labeling the artistic style (e.g., instead of "punk rock", say "wearing a studded leather vest and ripped jeans").
3.  If there is any readable text, transcribe it exactly.

Return ONLY a JSON object with two keys:
- \"primary_subject\": (string) The single most important subject in the image (e.g., \"a majestic stag\", \"a woman in an elegant dress\").
- \"description\": (string) The full, one-paragraph description of the entire scene.

The final output must be in {language} only.{safety_rule}"""

    def _generate_visual_prompt_pipeline(self, mode, user_text, images_with_weights, save_to_txt, filename_prefix, run_config, negative_prompt="", **kwargs): # noqa
        images = [img for img, _ in images_with_weights]
        if not images_with_weights and not (user_text and user_text.strip() and user_text.strip() != config.DEFAULT_PROMPT_TEXT):
            return ("No inputs provided.", None, None)
            
        ok_context, context_data = self._prepare_visual_prompt_context(user_text, images_with_weights, run_config)
        if not ok_context: return (context_data[0], None, None)
        image_context, user_instructions, user_context, mandatory_tokens, primary_subjects_from_images = context_data

        ok_draft, draft_or_err = self._generate_initial_draft(mode, user_instructions, user_context, image_context, mandatory_tokens, images, run_config, primary_subjects_from_images) # noqa
        if not ok_draft: return (draft_or_err, image_context, None)
        scene_prompt = draft_or_err
        
        style_rules = self._build_style_and_composition_rules(mode, images, run_config, user_instructions, user_context, image_context) # noqa
        scene_prompt = self._refine_image_video_prompt(scene_prompt, mode, mandatory_tokens, style_rules, run_config) # noqa
        
        new_positive, counter_negatives = utils._simplify_for_diffusion(scene_prompt, user_text, run_config)
        scene_prompt = new_positive

        combined_negative_input = f"{negative_prompt}, {counter_negatives}".strip().strip(',')
        final_negative_prompt = self._finalize_visual_prompt_output(scene_prompt, image_context, user_text, mandatory_tokens, run_config, save_to_txt, filename_prefix, user_negative_prompt=combined_negative_input) # noqa

        return (scene_prompt, image_context, final_negative_prompt)

    def _prepare_visual_prompt_context(self, user_text, images_with_weights, run_config):
        describe_result = self._describe_images(images_with_weights, run_config)
        if describe_result is None:
            image_context, primary_subjects_from_images = "No reference images provided.", []
        else:
            image_context, primary_subjects_from_images = describe_result

        # This logic is now consolidated and correctly handles all cases.
        tok_ok, tokens_or_msg = utils._extract_mandatory_tokens_with_model(image_context, user_text, run_config, primary_subjects_from_images)
        if not tok_ok:
            return False, (tokens_or_msg, None, None, None, None)
        
        mandatory_tokens = tokens_or_msg
        all_primary_subjects = [re.sub(r'^\s*\bPRIMARY\b\s*', '', t) for t in mandatory_tokens.get("primary", [])]

        user_instructions, user_context = user_text, ""
        return True, (image_context, user_instructions, user_context, mandatory_tokens, all_primary_subjects)

    def _generate_initial_draft(self, mode, user_instructions, user_context, image_context, mandatory_tokens, images, run_config, primary_subjects_from_images=None): # noqa
        merge_prompt = self._build_initial_merge_prompt(mode, user_instructions, user_context, image_context, mandatory_tokens, images, run_config, primary_subjects_from_images)
        generation_kwargs = {"prefer_chat": run_config.use_chat_api, "temperature": run_config.temperature, "seed": run_config.seed, "timeout": 120, "debug_mode": run_config.debug_mode}

        refinements = getattr(run_config, 'deep_think_refinements', 3)

        if run_config.use_deep_think and refinements > 0:
            print("\033[94m[PromptCrafter] Deep Think enabled. Starting iterative refinement...\033[0m")
            generation_kwargs["debug_title"] = f"Initial {mode} Prompt (Deep Think)"
            generation_kwargs["images"] = images
            ok, scene_prompt = utils._deep_think_and_refine(run_config.model, merge_prompt, max_iterations=refinements, confidence_threshold=run_config.deep_think_confidence, **generation_kwargs)
        else:
            if run_config.use_deep_think and refinements == 0:
                print("\033[94m[PromptCrafter] Deep Think disabled by setting refinements to 0.\033[0m")
            generation_kwargs["debug_title"] = f"Initial {mode} Prompt"
            ok, scene_prompt = api_clients.query_model_auto(run_config.model, merge_prompt, **generation_kwargs)

        return (True, utils.TextCleaner.single_paragraph(scene_prompt)) if ok else (False, f"Ollama error: {scene_prompt}")

    def _build_initial_merge_prompt(self, mode, user_instructions, user_context, image_context, mandatory_tokens, images, run_config, primary_subjects_from_images=None): # noqa
        style_composition_rules = self._build_style_and_composition_rules(mode, images, run_config, user_instructions, user_context, image_context)
        if run_config.negative_concepts:
            style_composition_rules.insert(0, f"- CRITICAL: Do NOT include any of the following concepts: {run_config.negative_concepts}")
        style_composition_rules_str = "\n".join(style_composition_rules)

        core_scene_text = user_instructions
        if user_context: core_scene_text += f"\n\n{user_context}"

        has_instructions = core_scene_text and core_scene_text.strip() and core_scene_text.strip() != config.DEFAULT_PROMPT_TEXT

        blend_keywords = ["blend", "merge", "combine", "hybrid", "chimera", "fused", "wearing"]
        user_wants_to_blend = any(keyword in core_scene_text.lower() for keyword in blend_keywords)
        replace_keywords = ["replace", "instead of", "substitute"]
        user_wants_to_replace = any(keyword in core_scene_text.lower() for keyword in replace_keywords)

        if not user_wants_to_blend and has_instructions and len(primary_subjects_from_images or []) > 1:
            user_wants_to_blend = self._user_requests_blending_with_ai(core_scene_text, primary_subjects_from_images, run_config) # noqa
        if not user_wants_to_replace and has_instructions and len(primary_subjects_from_images or []) > 0:
            user_wants_to_replace = self._user_requests_replacement_with_ai(core_scene_text, primary_subjects_from_images, run_config) # noqa

        task_rules = []
        if has_instructions:
            task_rules.append("1.  The USER INSTRUCTIONS are your primary guide. The final prompt MUST fulfill the user's core request.")
            task_rules.append("2.  Use the PRIMARY SUBJECTS and INSPIRATIONAL CONTEXT to flesh out the scene, but only in ways that support and do not contradict the USER INSTRUCTIONS.")
        else:
            task_rules.append("1.  Create a **new, single, coherent scene** that features ALL of the mandatory PRIMARY SUBJECTS interacting or co-existing in a plausible way.")
            task_rules.append("2.  Use the INSPIRATIONAL CONTEXT to flesh out the environment, lighting, and mood.")

        if user_wants_to_replace:
            task_rules.append("3.  **GUIDANCE:** The user has requested to REPLACE a subject. Identify the subject to be replaced from the image context and substitute it with the new subject from the user's instructions.")
        elif user_wants_to_blend:
            task_rules.append("3.  **GUIDANCE:** The user has requested to BLEND or MERGE subjects. Fulfill this request creatively using the primary subjects as your building blocks.")
        else:
            task_rules.append("3.  **CRITICAL RULE:** Do NOT merge or blend the features of the subjects. Each subject must remain distinct and separate (e.g., the stag is a stag, the eagle is an eagle. Do NOT create an eagle with antlers).")

        task_rules.append("4.  Create a single, flowing paragraph for the new cinematic prompt.")
        task_rules.append("5.  Integrate the `STYLE & COMPOSITION RULES` into your final prompt.")
        task_rules_str = "\n".join(task_rules)

        user_instructions_section = ""
        if has_instructions:
            user_instructions_section = f"**USER INSTRUCTIONS (Primary Goal)**\n---\n{core_scene_text}\n---"

        # This is now a standard template string, not an f-string.
        # Placeholders will be filled by the .format() method below.
        merge_template = textwrap.dedent("""
            You are an expert prompt engineer. Your task is to create a single, coherent, and detailed prompt for a {mode} generation model.

            **YOUR PRIMARY GOAL:**
            {user_instructions_section}

            **MANDATORY SUBJECTS (Must be in the final scene):**
            {primary_subjects_json}

            **YOUR TASK:**
            {task_rules_str}

            --- STYLE & COMPOSITION RULES ---
            {style_rules_str}
            ---

            Return ONLY the final, polished prompt.
        """).strip()

        # Correctly format the template with the prepared variables.
        return merge_template.format(
            mode=mode,
            user_instructions_section=user_instructions_section,
            primary_subjects_json=json.dumps(primary_subjects_from_images or []),
            task_rules_str=task_rules_str,
            style_rules_str=style_composition_rules_str
        )

    def _user_requests_blending_with_ai(self, user_text, primary_subjects, run_config): # noqa
        prompt = textwrap.dedent(f"""
            You are a request analysis expert. Read the user's instructions and determine if they are asking to merge, combine, or transfer features between the primary subjects.

            --- PRIMARY SUBJECTS ---
            {json.dumps(primary_subjects)}

            --- USER INSTRUCTIONS ---
            {user_text}

            --- ANALYSIS ---
            Does the user want to combine features from one subject onto another (e.g., "an eagle with antlers", "a woman wearing a dress made of flowers")?

            Respond with ONLY a JSON object containing a single boolean key "blending_requested".
            Example: {{"blending_requested": true}}
        """).strip()
        ok, result_json = api_clients._reason_with_model(run_config.model, prompt, use_chat_api=run_config.use_chat_api, temperature=0.0, seed=run_config.seed, debug_mode=run_config.debug_mode, debug_title="Blending Intent Check")
        return ok and isinstance(result_json, dict) and result_json.get("blending_requested", False)

    def _user_requests_replacement_with_ai(self, user_text, primary_subjects, run_config): # noqa
        prompt = textwrap.dedent(f"""
            You are a request analysis expert. Read the user's instructions and determine if they are asking to REPLACE one subject with another.

            --- PRIMARY SUBJECTS (from images) ---
            {json.dumps(primary_subjects)}

            --- USER INSTRUCTIONS ---
            {user_text}

            --- ANALYSIS ---
            Does the user want to replace a subject from the images with a new one from their instructions (e.g., "replace the man with a robot", "instead of a car, make it a spaceship")?

            Respond with ONLY a JSON object containing a single boolean key "replacement_requested".
            Example: {{"replacement_requested": true}}
        """).strip()
        ok, result_json = api_clients._reason_with_model(run_config.model, prompt, use_chat_api=run_config.use_chat_api, temperature=0.0, seed=run_config.seed, debug_mode=run_config.debug_mode, debug_title="Replacement Intent Check")
        return ok and isinstance(result_json, dict) and result_json.get("replacement_requested", False)

    def _build_style_and_composition_rules(self, mode, images, run_config, user_instructions="", user_context="", image_context=""): # noqa
        all_rules: list[str] = []
        if run_config.safe_mode: all_rules.append(config.SAFE_MODE_RULE)
        if mode == "Video": all_rules.extend(self._get_video_specific_rules(run_config, user_instructions, user_context, image_context))
        all_rules.extend(self._get_base_composition_rules(run_config.language))

        # This now correctly uses the profile determined in _setup_config
        inspiration = run_config.style_profile.get("inspiration", "")
        if inspiration: all_rules.append(f"- {inspiration}")
            
        return all_rules

    def _get_base_composition_rules(self, language): # noqa
        return [
            "- The primary subject(s) from the USER INSTRUCTIONS must be the clear focal point of the composition, correctly scaled and prominently featured.",
            "- Include ONLY characters/objects explicitly requested in USER INSTRUCTIONS.",
            "- Do NOT include secondary figures unless explicitly mentioned or essential.",
            "- Enforce cinematic depth: foreground, midground, background with natural scale and occlusion.",
            "- Dynamic composition that guides the viewer’s eye (rule of thirds, triangular balance, or S-curve).",
            "- Figures must interact or contrast for narrative depth (conflict, harmony, guardianship).",
            "- Dramatic, photorealistic lighting with clear key light, rim light, and atmospheric mood.",
            "- Do NOT reference source images (e.g., 'the man from image 1'); describe a single, unified scene.",
            f"- CRITICAL: The final prompt must be in {language} only. No other languages.",
            "- One flowing paragraph only.",
        ]

    def _get_video_specific_rules(self, run_config, user_instructions="", user_context="", image_context=""): # noqa
        motion_analysis_prompt = f"""You are an expert film director. Analyze the provided scene context and choose the most appropriate motion style and a specific camera movement for a video prompt.

--- SCENE CONTEXT ---
User Instructions: {user_instructions}
Image Descriptions: {image_context}
--- END SCENE CONTEXT ---

Part 1: Choose ONE motion style from the following list that best fits the overall mood and action:
- \"subtle, natural\": For calm, still scenes (e.g., gentle breeze).
- \"smooth, flowing\": For graceful, continuous movements (e.g., dancing, walking).
- \"dynamic, cinematic\": For energetic, purposeful actions (e.g., running, dramatic gestures).
- \"intense, action-packed\": For high-energy, chaotic scenes (e.g., battles, chases).

Part 2: Based on your choice, suggest ONE specific camera movement from this list:
- \"static shot\", \"slow pan left\", \"slow pan right\", \"tilt up\", \"tilt down\", \"dolly zoom\", \"tracking shot\", \"handheld shaky cam\", \"crane shot\".

Return ONLY a JSON object with your choices.
Example: {{"motion_style": \"dynamic, cinematic\", "camera_movement": \"tracking shot\"}}"""
        ok, result_json = api_clients._reason_with_model(run_config.model, motion_analysis_prompt, use_chat_api=run_config.use_chat_api, temperature=0.1, seed=run_config.seed, debug_mode=run_config.debug_mode, debug_title="Video Motion Style Analysis")

        motion_type_adjective = "subtle, natural"
        camera_movement_suggestion = "static shot"
        if ok and isinstance(result_json, dict):
            motion_type_adjective = result_json.get("motion_style", motion_type_adjective)
            camera_movement_suggestion = result_json.get("camera_movement", camera_movement_suggestion)

        motion_example = "e.g., 'a warrior lunging forward, sword gleaming as it cuts through the air, sparks flying on impact'" if "intense" in motion_type_adjective else "e.g., 'a person standing still, their coat gently billowing in the wind, cherry blossom petals drifting past'"
        motion_instruction = f"- CRITICAL PRIORITY: Emphasize the subject's ACTIONS and the PHYSICS of their movement. The motion should be {motion_type_adjective}. Describe the motion with active verbs and adverbs ({motion_example}). This detail is essential for generating faithful video movement."
        camera_instruction = f"- Suggestion for Camera: Incorporate a '{camera_movement_suggestion}' to enhance the '{motion_type_adjective}' feel of the scene."

        return [
            "- Role: Expert Wan2.2 video prompt generator.",
            "- Use Wan2.2 formula: [Cinematic Shot] + [Primary Subject & Detailed Description] + [Scene & Environment] + [Detailed Action & Physics-Based Motion] + [Camera Movement & Angle] + [Visual Style & Aesthetic Controls] + [Atmosphere & Mood].",
            motion_instruction,
            camera_instruction
        ]

    def _refine_image_video_prompt(self, draft_prompt, mode, mandatory_tokens, style_rules, run_config): # noqa
        current_prompt = draft_prompt
        
        # Extract the subject names from the tagged list
        primary_items_list = [re.sub(r'^\[PRIMARY\]\s*', '', t) for t in (mandatory_tokens or {}).get("primary", [])]

        if not primary_items_list:
            critique_prompt = self._build_refinement_prompt(current_prompt, mode, [], [], style_rules, run_config, ask_for_json=False)
            ok, revised_prompt = api_clients.query_model_auto(run_config.model, critique_prompt, prefer_chat=run_config.use_chat_api, temperature=run_config.temperature, seed=run_config.seed, timeout=90, debug_mode=run_config.debug_mode, debug_title="Image/Video Refine (Single Pass)")
            return utils.TextCleaner.single_paragraph(revised_prompt if ok else current_prompt)

        all_allowed = (mandatory_tokens or {}).get("allowed_list", [])

        for i in range(run_config.max_retries + 1):
            critique_prompt = self._build_refinement_prompt(current_prompt, mode, primary_items_list, all_allowed, style_rules, run_config, ask_for_json=True)
            ok, result_json = api_clients._reason_with_model(run_config.model, critique_prompt, use_chat_api=run_config.use_chat_api, temperature=run_config.temperature, seed=run_config.seed, timeout=90, debug_mode=run_config.debug_mode, debug_title=f"Image/Video Refine & Check (Try {i+1})")

            if not ok or not isinstance(result_json, dict):
                print(f"\033[93m[PromptCrafter] Warning: Refinement step failed to return valid JSON. Using previous version. Error: {result_json}\033[0m")
                return current_prompt

            current_prompt = utils.TextCleaner.single_paragraph(result_json.get("refined_prompt", current_prompt))
            missing_items = result_json.get("missing_items", ["*validation failed*"])
            hallucinated_items = result_json.get("hallucinated_items", ["*validation failed*"])

            if not missing_items and not hallucinated_items:
                return current_prompt

        return current_prompt

    def _build_refinement_prompt(self, prompt_to_review, mode, primary_items, all_allowed_items, style_rules, run_config, ask_for_json=True): # noqa
        mode_specific_rule = "- The prompt must describe a single, static frame. Remove any video-like transition phrases (e.g., 'then', 'the scene shifts') or motion verbs." if mode == "Image" else ""

        strength = run_config.critique_strength
        if strength == "Subtle":
            critique_instruction = "- Subtly refine the DRAFT PROMPT. Focus on improving wording, flow, and clarity. Do NOT make major structural changes or add new concepts. The core description should remain the same."
        elif strength == "Heavy":
            critique_instruction = "- Radically revise the DRAFT PROMPT for maximum cinematic impact. You have creative freedom to restructure the scene, change the composition, and add descriptive flair, as long as you adhere to all MANDATORY SUBJECTS and rules. Be bold in your edit."
        else:  # Normal
            critique_instruction = "- Revise the DRAFT PROMPT to meet ALL of the requirements listed above.\n- Integrate mandatory subjects naturally.\n- Remove any hallucinated subjects not in the allowed list.\n- Apply all style and mode-specific rules.\n- Enhance the prompt for cinematic quality, clarity, and impact."

        json_return_format = textwrap.dedent("""--- JSON RESPONSE INSTRUCTIONS ---
Return ONLY a single JSON object with three keys:
- `refined_prompt`: (string) The improved version of the prompt.
- `missing_items`: (array of strings) A list of any **MANDATORY SUBJECTS** that are still missing. Should be `[]` on success.
- `hallucinated_items`: (array of strings) A list of any subjects you included that were NOT in the original **ALLOWED SUBJECTS** list. Should be `[]` on success.
--- END JSON RESPONSE INSTRUCTIONS ---""") # noqa
        text_return_format = f"INSTRUCTIONS:\n{critique_instruction}\n\nReturn ONLY the final, improved prompt. No commentary."
        final_instructions = json_return_format if ask_for_json else text_return_format

        # Base template
        refine_template = textwrap.dedent("""You are a master prompt critic and editor. Your task is to review and enhance the following DRAFT PROMPT.

--- DRAFT PROMPT ---
{prompt_to_review}
--- END DRAFT PROMPT ---

--- REQUIREMENTS & RULES ---
{mandatory_section}
{allowed_section}
3.  **MODE-SPECIFIC RULES:**
    - The final prompt is for an '{mode}' generation.
    {mode_specific_rule}
4.  **GENERAL STYLE & COMPOSITION RULES:**
{rules}
--- END REQUIREMENTS & RULES ---

{instructions}""")

        mandatory_section = f"1.  **MANDATORY SUBJECTS (CRITICAL):** The final prompt MUST include all of the following subjects: {json.dumps(primary_items)}\n" if primary_items else ""
        allowed_section = f"2.  **ALLOWED SUBJECTS (Anti-Hallucination):** The prompt should ONLY contain subjects from this list. If the draft contains subjects not on this list, REMOVE them or replace them with a generic equivalent from the list. Allowed list: {json.dumps(all_allowed_items)}\n" if all_allowed_items else ""

        return refine_template.format(
            prompt_to_review=prompt_to_review,
            mandatory_section=mandatory_section,
            allowed_section=allowed_section,
            mode=mode,
            mode_specific_rule=mode_specific_rule,
            rules="\n".join(style_rules),
            instructions=final_instructions
        )

    def _finalize_visual_prompt_output(self, scene_prompt, image_context, user_text, mandatory_tokens, run_config, save_to_txt, filename_prefix, user_negative_prompt=""): # noqa
        ai_negative_prompt = utils._generate_negative_prompt(scene_prompt, run_config, user_negative_prompt="")
        parts = [p for p in [user_negative_prompt, ai_negative_prompt] if p and p.strip()]
        final_negative_prompt = ", ".join(parts)

        if save_to_txt and scene_prompt and scene_prompt.strip():
            sections = [("IMAGE CONTEXT", image_context)]
            if user_text and user_text.strip() and user_text.strip() != config.DEFAULT_PROMPT_TEXT:
                sections.append(("USER TEXT", user_text))
            if mandatory_tokens:
                all_tokens = mandatory_tokens.get("primary", []) + mandatory_tokens.get("secondary", [])
                if all_tokens: sections.append(("EXTRACTED TOKENS", "\n".join(all_tokens)))
            sections.append(("NEGATIVE PROMPT", final_negative_prompt))
            sections.append(("SCENE PROMPT", scene_prompt))
            utils._save_output_to_file(filename_prefix, sections, base_filename="scene_prompt")
        return final_negative_prompt

    def _handle_scheduled_mode(self, mode, user_text, images_with_weights, run_config, **kwargs): # noqa
        images = [img for img, _ in images_with_weights]
        describe_result = self._describe_images(images_with_weights, run_config)
        if describe_result is None:
            image_context_for_all, primary_subjects_from_images = "No reference images provided.", []
        else:
            image_context_for_all, primary_subjects_from_images = describe_result
        style_rules = self._build_style_and_composition_rules(mode, images, run_config, user_text, "", image_context_for_all)
        user_negative_prompt = kwargs.get("negative_prompt", "")
        ai_negative_prompt = utils._generate_negative_prompt(user_text, run_config, user_negative_prompt="")
        parts = [p for p in [user_negative_prompt, ai_negative_prompt] if p and p.strip()]
        base_negative_prompt = ", ".join(parts)

        if '\n\n' in user_text:
            print("\033[94m[PromptCrafter] Multi-paragraph input detected. Using manual scene breaks.\033[0m")
            scenes = [p.strip() for p in user_text.split('\n\n') if p.strip()]
        else:
            if not user_text or len(user_text.split()) < 20:
                scenes = utils._generate_storyboard_from_instruction_with_ai(user_text, image_context_for_all, primary_subjects_from_images, run_config)
            else:
                print("\033[94m[PromptCrafter] Attempting to split single-paragraph story into scenes with AI...\033[0m")
                scenes = utils._split_text_into_scenes_with_ai(user_text, run_config)

        if not scenes:
            return ("", "AI failed to generate a storyboard. Please try rephrasing your request or check the model.", "", "")

        print(f"\033[94m[PromptCrafter] Schedule mode enabled. Generating prompts for {len(scenes)} scenes...\033[0m")

        generated_prompts: list[str] = [""] * len(scenes)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(scenes))) as executor:
            future_to_index = {executor.submit(self._generate_prompt_for_scene, scene_text, mode, images_with_weights, image_context_for_all, style_rules, run_config, **kwargs): i for i, scene_text in enumerate(scenes)}
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    result = future.result()
                    if result is None:
                        result = ""
                    generated_prompts[index] = str(result)
                    print(f"\033[92m[PromptCrafter] Finished processing scene {index + 1}/{len(scenes)}.\033[0m")
                except Exception as exc:
                    error_msg = f"[Error processing scene {index + 1}: {exc}]"
                    generated_prompts[index] = error_msg
                    print(f"\033[91m[PromptCrafter] {error_msg}\033[0m")

        if not any(generated_prompts):
            return ("", "Failed to generate prompts for any of the scenes. Please check the model and logs.", image_context_for_all, base_negative_prompt)

        schedule_json = utils._create_schedule_from_items(generated_prompts, kwargs.get("max_frames", 240), 0, kwargs.get("interpolate_keyframes", True), kwargs.get("interpolation_frame_interval", 10))
        
        if kwargs.get("save_to_txt", False) and schedule_json:
            sections = [("USER TEXT", user_text), ("IMAGE CONTEXT", image_context_for_all), ("NEGATIVE PROMPT", base_negative_prompt), ("SCHEDULE", schedule_json)]
            utils._save_output_to_file(kwargs.get("filename_prefix"), sections, base_filename="schedule")

        return ("", schedule_json, image_context_for_all, base_negative_prompt)

    def _generate_prompt_for_scene(self, scene_text, mode, images_with_weights, image_context_for_all, style_rules, run_config, **kwargs): # noqa
        config_key_parts = (run_config.model, run_config.language, run_config.temperature, run_config.use_chat_api, run_config.max_length_words, run_config.seed, run_config.max_retries, run_config.critique_strength, run_config.simplify_for_diffusion, run_config.use_deep_think, str(run_config.style_profile))
        cache_key = utils._get_cache_key("gen_prompt_for_scene_v1", scene_text, mode, images_with_weights, image_context_for_all, style_rules, config_key_parts)
        if config.CACHE.has(cache_key):
            print(f"\033[94m[PromptCrafter] Using cached prompt for scene: '{scene_text[:50]}...'") # noqa
            return config.CACHE.get(cache_key)

        images = [img for img, _ in images_with_weights]
        tok_ok, mandatory_tokens = utils._extract_mandatory_tokens_with_model(image_context_for_all, scene_text, run_config)
        if not tok_ok: return f"[Error extracting tokens for scene: {mandatory_tokens}]"

        ok_draft, draft_or_err = self._generate_initial_draft(mode, scene_text, "", image_context_for_all, mandatory_tokens, images, run_config)
        if not ok_draft: return f"[Error generating draft for scene: {draft_or_err}]"
        
        scene_prompt = self._refine_image_video_prompt(draft_or_err, mode, mandatory_tokens, style_rules, run_config)
        new_positive, _ = utils._simplify_for_diffusion(scene_prompt, scene_text, run_config)
        
        config.CACHE.set(cache_key, new_positive)
        return new_positive

class PromptCrafter_ImageCreator(PromptCrafter_BaseCreator):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "user_text": ("STRING", {"multiline": True, "default": config.DEFAULT_PROMPT_TEXT}),
                "model": (api_clients.get_all_models(), {"tooltip": "The language model to use for all analysis and generation. Vision-capable models are required if using images."} ),
                "image_count": ("INT", {"default": 1, "min": 1, "max": 5, "step": 1}),
                # --- Generation Control ---
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff}),
                "max_length_words": ("INT", {"default": 0, "min": 0, "max": 400, "step": 10}),
                "style_override": (style_profiles.get_style_override_options("Image"), {"default": "None"}),
                "critique_strength": (["Subtle", "Normal", "Heavy"], {"default": "Normal"}),
                "deep_think_refinements": ("INT", {"default": 3, "min": 0, "max": 10, "step": 1, "tooltip": "Number of iterative refinement steps for the Deep Think process. 0 disables it."}),
                "simplify_for_diffusion": ("BOOLEAN", {"default": True}),
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10}),
                "max_retries": ("INT", {"default": 2, "min": 0, "max": 10}),
                "safe_mode": ("BOOLEAN", {"default": True}),
                "debug_mode": ("BOOLEAN", {"default": False}),
                "save_to_txt": ("BOOLEAN", {"default": False}),
                "filename_prefix": ("STRING", {"default": "scene_prompts"}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "negative_prompt": "STRING"},
            "optional": {
                "style_tags": ("STRING", {"multiline": False, "default": "", "tooltip": "Combine styles by typing their names, separated by commas (e.g., Cyberpunk, Film Noir). Overrides the dropdown."}),
                "generate_schedule": ("BOOLEAN", {"default": False}),
                "max_frames": ("INT", {"default": 240, "min": 1, "max": 99999}),
                "interpolate_keyframes": ("BOOLEAN", {"default": True}),
                "interpolation_frame_interval": ("INT", {"default": 10, "min": 0, "max": 100}),
            },
        }

    MAX_IMAGES = 5
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING") + ("IMAGE",) * MAX_IMAGES
    RETURN_NAMES = ("prompt", "schedule", "image_context", "negative_prompt") + tuple(f"reference_image_{i}" for i in range(1, MAX_IMAGES + 1))
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter"

    def execute(self, user_text, model, negative_prompt="", **kwargs):
        try:
            images_with_weights = self._collect_images_with_weights(**kwargs) # noqa
            initial_run_config = self._setup_config("Image", user_text, model, images_with_weights=images_with_weights, **kwargs)
            
            error, new_user_text = self._handle_creative_intent("Image", user_text, images_with_weights, initial_run_config)
            if error: return (error,) + (None,) * (len(self.RETURN_TYPES) - 1)
            final_user_text = new_user_text or user_text

            run_config = self._setup_config("Image", final_user_text, model, images_with_weights=images_with_weights, **kwargs)

            passthrough_images = [img for img, _ in images_with_weights]
            passthrough_images.extend([None] * (self.MAX_IMAGES - len(passthrough_images)))

            if kwargs.get("generate_schedule"):
                prompt, schedule, image_context, neg_prompt = self._handle_scheduled_mode("Image", final_user_text, images_with_weights, run_config, **kwargs)
                return (prompt, schedule, image_context, neg_prompt) + tuple(passthrough_images)
            else:
                pipeline_kwargs = {k: v for k, v in kwargs.items() if k not in ['prompt', 'extra_pnginfo']}
                pipeline_kwargs.pop('save_to_txt', None)
                pipeline_kwargs.pop('filename_prefix', None)

                prompt, image_context, negative_prompt_out = self._generate_visual_prompt_pipeline(
                    mode="Image", user_text=final_user_text, images_with_weights=images_with_weights, save_to_txt=kwargs.get("save_to_txt", False), filename_prefix=kwargs.get("filename_prefix", "scene_prompts"), run_config=run_config, negative_prompt=negative_prompt, **pipeline_kwargs
                )
                return (prompt, "", image_context, negative_prompt_out) + tuple(passthrough_images)
        except Exception as e:
            return self._handle_creator_exception(e)


# ------------------------------------------------------------------------------------
# PromptCrafter_FileOrganizer Node
# ------------------------------------------------------------------------------------
class PromptCrafter_FileOrganizer:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (api_clients.get_all_models(), {"tooltip": "The language model to use for all analysis and generation. Vision-capable models are required if using images."} ),
                "input_folder": ("STRING", {"default": "output/unorganized", "tooltip": "The folder containing the files you want to organize (relative to ComfyUI root)."}),
                "output_folder": ("STRING", {"default": "output/organized", "tooltip": "The root folder where organized subdirectories will be created (relative to ComfyUI root)."}),
                "organization_profile": (organization_profiles.get_organization_profile_options(), {"default": "None (Manual Scheme)", "tooltip": "Select a pre-configured organization scheme. Overrides the manual scheme text box."}),
                "organization_scheme": ("STRING", {
                    "multiline": True,
                    "default": "# Define rules, one per line. The first match will be used.\n# Format: CRITERION: VALUE -> FOLDER_NAME\n# Criteria: image_resolution, image_description_contains, captionfile_contains, filename_contains, metadata_contains, content_keyword\n\nimage_resolution: >1920x1080 -> High_Resolution/4K_ish\nimage_resolution: ==512x512 -> Square_Images/512x512\nimage_description_contains: cat -> By_Embedded_Caption/Cats\ncaptionfile_contains: dog -> By_Text_File/Dogs\nfilename_contains: car -> By_Filename/Cars\nmetadata_contains: AnimateDiff -> By_Workflow/Animations\ncontent_keyword: landscape -> By_VLM_Content/Landscapes",
                    "tooltip": "Rules for organizing files. 'image_resolution' checks dimensions (e.g., >1024x768). 'image_description_contains' reads embedded EXIF/PNG descriptions. 'captionfile_contains' reads .txt files. 'filename_contains' checks the filename. 'metadata_contains' checks the ComfyUI workflow."
                }),
                "action": (["Copy", "Move"], {"default": "Copy", "tooltip": "Copy files (safer) or move them to the new location."}),
                "dry_run": ("BOOLEAN", {"default": False, "tooltip": "Simulate the organization process and report actions without moving or copying files."}),
                "analysis_priority": (["Metadata First", "Content First", "Metadata Only"], {"default": "Metadata First", "tooltip": "The order of analysis. 'Metadata First' is fastest."}),
                "fallback_folder": ("STRING", {"default": "_unorganized", "tooltip": "Subfolder for files that do not match any rule."}),
                "auto_generate_scheme": ("BOOLEAN", {"default": False, "tooltip": "Automatically generate an organization scheme by analyzing a sample of files. Overrides the manual scheme."}),
            },
            "optional": {
                "run_organization": ("BOOLEAN", {"default": False, "tooltip": "Toggle to True to start the organization process. It will run once per execution."}),
                "max_workers": ("INT", {"default": 4, "min": 1, "max": 16, "step": 1, "tooltip": "Number of parallel threads for processing files." }),
                "recursive": ("BOOLEAN", {"default": False, "tooltip": "Process files in all subdirectories of the input folder as well."}),
                "create_log_file": ("BOOLEAN", {"default": False, "tooltip": "Create a text log file summarizing all operations in the output folder."}),
                "log_filename": ("STRING", {"default": "organization_log.txt", "tooltip": "The name of the log file to be created in the output folder."}),
                "delete_source_folder_on_move": ("BOOLEAN", {"default": False, "tooltip": "After a successful 'Move' operation, delete the original input folder if it's empty. Use with caution."}),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("summary", "dry_run_plan", "generated_scheme_out")
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter/Utils"
    OUTPUT_NODE = True

    def _read_metadata(self, image_path):
        """Safely reads PNG info metadata from an image file."""
        try:
            with Image.open(image_path) as img:
                if "prompt" in img.info and img.info["prompt"]:
                    return json.loads(img.info["prompt"])
                if "workflow" in img.info and img.info["workflow"]:
                    workflow_data = img.info["workflow"]
                    return json.loads(workflow_data)
        except (json.JSONDecodeError, IOError, TypeError, KeyError, AttributeError):
            return None
        return None

    def _check_resolution_rule(self, image_size, rule_value):
        """Parses a resolution rule and checks if the image size matches."""
        # image_size is a tuple (width, height)
        # rule_value is a string like ">1024x768" or "==512x512"
        match = re.match(r"([<>=!]{1,2})\s*(\d+)[xX](\d+)", rule_value.strip())
        if not match:
            return False

        op, target_w_str, target_h_str = match.groups()
        img_w, img_h = image_size
        target_w, target_h = int(target_w_str), int(target_h_str)

        # Define a mapping from operator string to a lambda function
        ops = {
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
        }

        op_func = ops.get(op)
        if not op_func:
            return False

        # The rule matches if BOTH width and height satisfy the condition
        return op_func(img_w, target_w) and op_func(img_h, target_h)

    def _recursively_find_value(self, data, search_value, case_sensitive=False):
        """Iteratively search for a value within a nested dict/list structure."""
        stack = collections.deque([data])
        if not isinstance(search_value, str):
            return False
        search_key = search_value if case_sensitive else search_value.lower()

        while stack:
            current_item = stack.pop()
            if isinstance(current_item, dict):
                stack.extend(current_item.values())
            elif isinstance(current_item, list):
                stack.extend(current_item)
            elif isinstance(current_item, str):
                current_val = current_item if case_sensitive else current_item.lower()
                if search_key in current_val:
                    return True
        return False

    def _get_target_for_file(self, file_path, rules, vision_model, analysis_priority, file_info_cache):
        """Analyzes a single file and returns the target subfolder name."""
        base_name, _ = os.path.splitext(os.path.basename(file_path))
        file_info = file_info_cache.get(file_path, {})
        # --- Resolution Analysis (perform once if needed) ---
        image_size = None
        has_resolution_rules = any(r[0] == 'image_resolution' for r in rules)

        if has_resolution_rules and file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            try:
                with Image.open(file_path) as img:
                    image_size = img.size
                for criterion, value, folder in rules:
                    if criterion == "image_resolution" and self._check_resolution_rule(image_size, value):
                        return folder
            except Exception: pass # Fail silently if image is not readable

        # --- File-based Analysis (Filename and Caption File) ---
        if analysis_priority != "Content First":
            # 1. Check filename
            for criterion, value, folder in rules:
                if criterion == "filename_contains":
                    if value.lower() in base_name.lower():
                        return folder
            
            # 2. Check for embedded image description (PNG Description or EXIF UserComment)
            image_description = file_info.get("image_description")
            if image_description:
                for criterion, value, folder in rules:
                    if criterion == "image_description_contains" and value.lower() in image_description.lower():
                        return folder

            # 3. Check for and read companion caption file (.txt)
            caption_content = file_info.get("caption_content")
            if caption_content:
                for criterion, value, folder in rules:
                    if criterion == "captionfile_contains" and value.lower() in caption_content.lower():
                        return folder

        # --- Embedded ComfyUI Workflow Metadata Analysis ---
        if analysis_priority != "Content First":
            metadata = file_info.get("metadata")
            if metadata:
                for criterion, value, folder in rules:
                    if criterion == "metadata_contains":
                        if self._recursively_find_value(metadata, value, case_sensitive=False):
                            return folder
                    elif criterion == "prompt_keyword":
                        for node in metadata.get("nodes", []):
                            if node.get("type") in ["CLIPTextEncode", "KSampler"]:
                                if self._recursively_find_value(node.get("properties", {}), value):
                                    return folder
            if analysis_priority == "Metadata Only":
                return None # Stop here if only metadata analysis is requested

        # --- Content Analysis (VLM) ---
        if vision_model and any(r[0] == 'content_keyword' for r in rules):
            try:
                pil_image = Image.open(file_path).convert("RGB")
                image_tensor = comfy.utils.pil2tensor(pil_image)
                
                prompt = "Describe this image in a few keywords. Focus on the main subject, style, and setting. Example: 'photo, car, city street, nighttime'"
                ok, caption = api_clients.query_model_auto(vision_model, prompt=prompt, images=[image_tensor[0]], prefer_chat=True, temperature=0.1, seed=1, timeout=60)
                
                if ok:
                    for criterion, value, folder in rules:
                        if criterion == "content_keyword" and value.lower() in caption.lower():
                            return folder
            except Exception as e:
                print(f"\033[93m[FileOrganizer] Warning: Content analysis failed for {os.path.basename(file_path)}: {e}\033[0m")

        return None

    def _generate_scheme_with_ai(self, file_groups, model, max_workers, debug_mode=False):
        """Analyzes a sample of files and uses an LLM to generate an organization scheme."""
        print(f"\033[94m[FileOrganizer] Auto-generating organization scheme by analyzing a sample of files...\033[0m")
        
        # Take a sample of up to 15 file groups to analyze
        sample_groups = file_groups[:15]
        file_profiles = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_profile = {
                executor.submit(self._summarize_file_for_scheme, self._get_representative_file(group)): group
                for group in sample_groups
            }
            for future in concurrent.futures.as_completed(future_to_profile):
                profile = future.result()
                if profile:
                    file_profiles.append(profile)

        if not file_profiles:
            return None, "Could not generate summaries for any sample files. Unable to create a scheme."

        # Convert the list of profile dicts into a nicely formatted JSON string for the prompt
        profiles_json_text = json.dumps(file_profiles, indent=2)
        
        prompt = textwrap.dedent(f"""
            You are an expert data analyst and file organization assistant. Your task is to create a logical organization scheme based on a sample of file profiles.

            **Available Rule Criteria & Syntax:**
            - `image_resolution`: Checks image dimensions. Use operators `==`, `>`, `<`. Example: `image_resolution: >1024x1024 -> High_Resolution`
            - `image_description_contains`: Checks embedded metadata (EXIF/PNG). Most reliable for content. Example: `image_description_contains: cat -> By_Subject/Cats`
            - `captionfile_contains`: Checks an associated `.txt` file. Example: `captionfile_contains: dog -> By_Text_File/Dogs`
            - `filename_contains`: Checks the file's name. Good for types like 'screenshot'. Example: `filename_contains: screenshot -> By_Type/Screenshots`

            --- FILE PROFILES (Sample Data) ---
            {profiles_json_text}
            ---

            INSTRUCTIONS:
            1.  **Analyze & Correlate:** Read all file profiles. Identify common themes, subjects, styles, AND image resolutions.
            2.  **Select Best Criterion:** For each theme you identify, determine the BEST rule criterion to use.
                - If you see common resolutions (e.g., many `512x512` images), create an `image_resolution` rule.
                - For content themes, prefer `image_description_contains` if available, otherwise use `captionfile_contains`.
            3.  **Create Rules:** Generate 5-10 powerful rules based on your analysis. The format is `criterion: keyword -> Folder/Subfolder`.
            4.  **Be Smart:** Create logical, hierarchical folder structures (e.g., `By_Style/Anime`, `By_Subject/Cats`). Use lowercase keywords.
            5.  **Prioritize:** Focus on rules that will categorize the most files.

            Return ONLY the rules, one per line. Do not include commentary or code blocks.

            Example Output:
            image_resolution: ==512x512 -> By_Resolution/Square_512
            image_description_contains: cat -> By_Subject/Cats
            image_description_contains: dog -> By_Subject/Dogs
            captionfile_contains: cyberpunk -> By_Theme/Cyberpunk
            filename_contains: screenshot -> By_Type/Screenshots
        """).strip()

        ok, scheme = api_clients.query_model_auto(model, prompt, prefer_chat=True, temperature=0.1, seed=1, timeout=120, debug_mode=debug_mode, debug_title="Auto-Generate Scheme")
        return (scheme, None) if ok else (None, f"AI scheme generation failed: {scheme}")

    def _group_files_by_basename(self, directory, extensions, recursive=False):
        """
        Groups files in a directory by their base name, ensuring associated files (like image.png and image.txt) are processed together.
        Can optionally process subdirectories recursively.
        """
        initial_groups = collections.defaultdict(list)
        
        if recursive:
            for root, _, files in os.walk(directory):
                for f in files:
                    if f.lower().endswith(extensions):
                        full_path = os.path.join(root, f)
                        base_name_path, _ = os.path.splitext(full_path)
                        initial_groups[base_name_path].append(full_path)
        else:
            for f in os.listdir(directory):
                if f.lower().endswith(extensions) and os.path.isfile(os.path.join(directory, f)):
                    base_name_path, _ = os.path.splitext(os.path.join(directory, f))
                    initial_groups[base_name_path].append(os.path.join(directory, f))

        return list(initial_groups.values())

    def _get_representative_file(self, file_group):
        """
        Selects the best file from a group for analysis (prefers PNGs for metadata, then other images).
        """
        image_files = [f for f in file_group if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
        png_files = [f for f in image_files if f.lower().endswith('.png')]
        
        if png_files: return png_files[0]
        if image_files: return image_files[0]
        return file_group[0] if file_group else None

    def _process_file_group(self, file_group, rules, vision_model, analysis_priority, fallback_folder, full_input_path, full_output_path, action, file_info_cache, dry_run=False, create_log_file=False):
        """
        Determines the target folder for a group of files and performs the move/copy action.
        This function is designed to be run in a thread pool.
        Returns a tuple: (status, processed_count, log_messages)
        """
        if not file_group:
            return "skipped_empty", 0, []

        representative_file = self._get_representative_file(file_group) # noqa
        target_subfolder = self._get_target_for_file(representative_file, rules, vision_model, analysis_priority, file_info_cache)
        
        if target_subfolder is None:
            target_subfolder = fallback_folder
        
        dest_dir = os.path.join(full_output_path, target_subfolder)

        if not dry_run:
            # This check is important for thread safety.
            if not os.path.isdir(dest_dir):
                try:
                    os.makedirs(dest_dir, exist_ok=True)
                except OSError as e:
                    # Handles race condition where another thread creates the directory between the check and the call.
                    if not os.path.isdir(dest_dir):
                        raise e

        processed_count = 0
        log_messages = []
        for file_path in file_group:
            if not os.path.exists(file_path): continue
            
            dest_path = os.path.join(dest_dir, os.path.basename(file_path))
            
            if os.path.abspath(file_path) == os.path.abspath(dest_path):
                continue

            if dry_run:
                action_verb = "MOVE" if action == "Move" else "COPY"
                relative_file_path = os.path.relpath(file_path, full_input_path)
                log_msg = f"[Dry Run] Would {action_verb} '{relative_file_path}' to '{os.path.relpath(dest_dir, full_output_path)}'"
                print(f"\033[96m{log_msg}\033[0m")
                if create_log_file: log_messages.append(log_msg)
                processed_count += 1
            else:
                try:
                    if action == "Move":
                        shutil.move(file_path, dest_path)
                    else: # Copy
                        shutil.copy2(file_path, dest_path)
                    if create_log_file:
                        action_verb_past = "Moved" if action == "Move" else "Copied"
                        log_messages.append(f"OK: {action_verb_past} '{os.path.relpath(file_path, full_input_path)}' to '{os.path.relpath(dest_dir, full_output_path)}'")
                    processed_count += 1
                except FileExistsError:
                    # This is an expected outcome if the file is already there.
                    continue
                except Exception as e:
                    # Catch other potential errors during file operation.
                    print(f"\033[91m[FileOrganizer] Error processing file {file_path}: {e}\033[0m")
                    if create_log_file: log_messages.append(f"FAIL: Error processing '{os.path.relpath(file_path, full_input_path)}': {e}")
                    return "failed", 0, log_messages

        status = "moved" if action == "Move" else "copied"
        return status, processed_count, log_messages

    def _summarize_file_for_scheme(self, file_path):
        """Generates a structured summary of a file's text-based metadata for scheme generation."""
        if not file_path:
            return None

        profile = {
            "filename": os.path.basename(file_path),
            "image_resolution": None,
            "image_description": None,
            "caption_content": None,
        }

        # Read image resolution if it's an image file
        if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            try:
                with Image.open(file_path) as img:
                    profile["image_resolution"] = f"{img.width}x{img.height}"
            except Exception:
                pass # Fail silently if image is unreadable

        # Read embedded image description (from EXIF/PNG)
        image_description = utils._read_image_description(file_path)
        if image_description:
            profile["image_description"] = image_description.strip()

        # Read companion .txt file
        caption_path = os.path.splitext(file_path)[0] + ".txt"
        if os.path.exists(caption_path):
            try:
                with open(caption_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        profile["caption_content"] = content
            except Exception:
                pass
        return profile

    def execute(self, model, input_folder, output_folder, organization_profile, organization_scheme, action, dry_run, analysis_priority, fallback_folder, auto_generate_scheme=False, run_organization=False, max_workers=4, recursive=False, create_log_file=False, log_filename="organization_log.txt", delete_source_folder_on_move=False, **kwargs):
        if not run_organization:
            return ("Organization not started. Set 'run_organization' to True.", "", "")

        full_input_path = utils._get_verified_path(input_folder, is_dir=True)
        if not full_input_path:
            return (f"Error: Input folder not found at '{input_folder}'.", "", "")
        
        full_output_path = utils._get_and_create_output_dir(output_folder)
        
        log_messages = []
        if create_log_file:
            log_messages.append(f"--- PromptCrafter File Organizer Log ---")
            log_messages.append(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            log_messages.append(f"Input Folder: {full_input_path}")
            log_messages.append(f"Output Folder: {full_output_path}")
            log_messages.append(f"Action: {action} | Recursive: {recursive}")
            log_messages.append("-" * 40)

        if dry_run:
            print("\033[96m[FileOrganizer] DRY RUN MODE ENABLED. No files will be moved or copied.\033[0m")
        
        supported_ext = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp4', '.mov', '.txt')
        file_groups = self._group_files_by_basename(full_input_path, supported_ext, recursive=recursive)

        if not file_groups: return ("No supported files found in the input folder.", "", "")

        final_scheme = organization_scheme
        generated_scheme_out = ""
        if auto_generate_scheme:
            generated_scheme, error = self._generate_scheme_with_ai(file_groups, model, max_workers, debug_mode=kwargs.get("debug_mode", False))
            if error:
                return (f"Error during auto-scheme generation: {error}", "", "")
            final_scheme = generated_scheme
            print(f"\033[92m[FileOrganizer] Using auto-generated scheme:\n{final_scheme}\033[0m")
        elif organization_profile != "None (Manual Scheme)":
            profile = organization_profiles.NAMED_ORGANIZATION_PROFILES.get(organization_profile)
            if profile and "scheme" in profile:
                final_scheme = profile["scheme"]
                print(f"\033[92m[FileOrganizer] Using scheme from profile: '{organization_profile}'\033[0m")

        generated_scheme_out = final_scheme if auto_generate_scheme else ""
        rules = []
        for line in final_scheme.splitlines():
            line = line.strip()
            if line.startswith("#") or "->" not in line: continue
            try:
                condition, folder = line.split("->")
                criterion, value = condition.split(":", 1)
                rules.append((criterion.strip(), value.strip(), folder.strip()))
            except ValueError:
                print(f"\033[93m[FileOrganizer] Warning: Skipping invalid rule: {line}\033[0m")
        
        if not rules: return ("Error: No valid organization rules were defined.", "", generated_scheme_out)

        counts = collections.Counter()
        total_files_processed = 0
        all_op_logs = []

        # Pre-cache file info to avoid redundant reads in parallel
        file_info_cache = {}
        print(f"\033[94m[FileOrganizer] Pre-analyzing {len(file_groups)} file groups...\033[0m")
        for group in file_groups:
            rep_file = self._get_representative_file(group)
            if rep_file:
                file_info_cache[rep_file] = self._summarize_file_for_scheme(rep_file)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Create a future for each file group
            future_to_group = {
                executor.submit(self._process_file_group, group, rules, model, analysis_priority, fallback_folder, full_input_path, full_output_path, action, file_info_cache, dry_run, create_log_file): group
                for group in file_groups
            }

            completed_count = 0
            for future in concurrent.futures.as_completed(future_to_group):
                completed_count += 1
                print(f"\033[92m[FileOrganizer] Processing... ({completed_count}/{len(file_groups)})\033[0m", end='\r')
                group = future_to_group[future]
                try:
                    status, num_processed, op_logs = future.result()
                    if op_logs: all_op_logs.extend(op_logs)
                    counts[status] += num_processed
                    total_files_processed += num_processed
                except Exception as e:
                    counts["failed"] += len(group)
                    print(f"\033[91m[FileOrganizer] Error processing group for {os.path.basename(group[0])}: {e}\033[0m")
        print("\n\033[92m[FileOrganizer] Processing complete.\033[0m")

        total_groups = len(file_groups)
        summary_prefix = "Dry Run Complete!" if dry_run else "Organization Complete!"
        summary = f"{summary_prefix} Processed {total_files_processed} files across {total_groups} groups.\n"
        if dry_run:
            summary += f"Actions that would be taken:\n"

        if counts['copied'] > 0: summary += f"- Copied: {counts['copied']} files\n"
        if counts['moved'] > 0: summary += f"- Moved: {counts['moved']} files\n"
        if counts['failed'] > 0: summary += f"- Failed: {counts['failed']} files\n"
        summary = summary.strip()

        # --- Delete source folder if requested and conditions are met ---
        if delete_source_folder_on_move and not recursive and action == "Move" and not dry_run and counts['failed'] == 0 and counts['moved'] > 0:
            try:
                # Safety check: only delete if the folder is now empty.
                if not os.listdir(full_input_path):
                    shutil.rmtree(full_input_path)
                    delete_msg = f"\nSuccessfully deleted empty source folder: {input_folder}"
                    print(f"\033[92m[FileOrganizer]{delete_msg}\033[0m")
                    summary += delete_msg.strip()
                else:
                    delete_msg = f"\nSource folder '{input_folder}' was not deleted because it is not empty after the move operation."
                    print(f"\033[93m[FileOrganizer] Warning:{delete_msg}\033[0m")
                    summary += delete_msg.strip()
            except Exception as e:
                delete_msg = f"\nError deleting source folder '{input_folder}': {e}"
                print(f"\033[91m[FileOrganizer]{delete_msg}\033[0m")
                summary += delete_msg.strip()
        elif delete_source_folder_on_move and recursive:
            delete_msg = "\n'delete_source_folder_on_move' is disabled when 'recursive' is enabled to prevent accidental deletion of parent folders."
            print(f"\033[93m[FileOrganizer] Info:{delete_msg}\033[0m")
            summary += delete_msg.strip()

        if create_log_file:
            log_messages.extend(sorted(all_op_logs))
            log_messages.append("-" * 40)
            log_messages.append(summary.replace('\n', '\n' + ' ' * 4)) # Indent summary for readability
            
            log_file_path = os.path.join(full_output_path, log_filename)
            try:
                with open(log_file_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(log_messages))
                print(f"\033[92m[FileOrganizer] Operation log saved to: {log_file_path}\033[0m")
            except Exception as e:
                print(f"\033[91m[FileOrganizer] Error writing log file: {e}\033[0m")

        dry_run_plan_str = "\n".join(sorted(all_op_logs)) if dry_run else ""

        return (summary, dry_run_plan_str, generated_scheme_out)


class PromptCrafter_VideoCreator(PromptCrafter_BaseCreator):
    @classmethod
    def INPUT_TYPES(cls):
        types = copy.deepcopy(PromptCrafter_ImageCreator.INPUT_TYPES())
        types["required"]["temperature"] = ("FLOAT", {"default": 0.4, "min": 0.0, "max": 1.0, "step": 0.01})
        types["required"]["max_length_words"] = ("INT", {"default": 0, "min": 0, "max": 400, "step": 10})
        types["required"]["style_override"] = (style_profiles.get_style_override_options("Video"), {"default": "None"})
        if "image_weights_json" in types["optional"]:
            del types["optional"]["image_weights_json"]
        # Add style_tags if it's not there from the parent
        if "style_tags" not in types["optional"]:
             types["optional"]["style_tags"] = ("STRING", {"multiline": False, "default": "", "tooltip": "Combine styles by typing their names, separated by commas (e.g., Cyberpunk, Film Noir). Overrides the dropdown."})
        return types

    MAX_IMAGES = 5
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING") + ("IMAGE",) * MAX_IMAGES
    RETURN_NAMES = ("prompt", "schedule", "image_context", "negative_prompt") + tuple(f"reference_image_{i}" for i in range(1, MAX_IMAGES + 1))
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter"

    def execute(self, user_text, model, negative_prompt="", **kwargs):
        try:
            images_with_weights = self._collect_images_with_weights(**kwargs) # noqa
            initial_run_config = self._setup_config("Video", user_text, model, images_with_weights=images_with_weights, **kwargs)
            
            error, new_user_text = self._handle_creative_intent("Video", user_text, images_with_weights, initial_run_config)
            if error: return (error,) + (None,) * (len(self.RETURN_TYPES) - 1)
            final_user_text = new_user_text or user_text

            run_config = self._setup_config("Video", final_user_text, model, images_with_weights=images_with_weights, **kwargs)

            passthrough_images = [img for img, _ in images_with_weights]
            passthrough_images.extend([None] * (self.MAX_IMAGES - len(passthrough_images)))

            if kwargs.get("generate_schedule"):
                prompt, schedule, image_context, neg_prompt = self._handle_scheduled_mode("Video", final_user_text, images_with_weights, run_config, **kwargs)
                return (prompt, schedule, image_context, neg_prompt) + tuple(passthrough_images)
            else:
                pipeline_kwargs = {k: v for k, v in kwargs.items() if k not in ['prompt', 'extra_pnginfo']}
                pipeline_kwargs.pop('save_to_txt', None)
                pipeline_kwargs.pop('filename_prefix', None)

                prompt, image_context, final_negative_prompt = self._generate_visual_prompt_pipeline(
                    mode="Video", user_text=final_user_text, images_with_weights=images_with_weights, save_to_txt=kwargs.get("save_to_txt", False), filename_prefix=kwargs.get("filename_prefix", "scene_prompts"), run_config=run_config, negative_prompt=negative_prompt, **pipeline_kwargs
                )
                return (prompt, "", image_context, final_negative_prompt) + tuple(passthrough_images)
        except Exception as e:
            return self._handle_creator_exception(e)

class PromptCrafter_LyricsCreator(PromptCrafter_BaseCreator):
    @classmethod
    def INPUT_TYPES(cls):
        types = copy.deepcopy(PromptCrafter_ImageCreator.INPUT_TYPES())
        types["required"]["temperature"] = ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01})
        # // AI ENHANCEMENT: Changed default max_length_words to 40, aligning with the goal of shorter prompts.
        types["required"]["max_length_words"] = ("INT", {"default": 40, "min": 0, "max": 400, "step": 10})
        types["required"]["style_override"] = (style_profiles.get_style_override_options("Lyrics"), {"default": "None"})
        types["required"]["simplify_for_diffusion"] = ("BOOLEAN", {"default": False})
        types["required"]["filename_prefix"] = ("STRING", {"default": "lyrics_prompts"})
        types["optional"].update({
            "style_tags": ("STRING", {"multiline": False, "default": "", "tooltip": "Combine styles by typing their names, separated by commas (e.g., Cyberpunk, Film Noir). Overrides the dropdown."}),
            "audio_folder_path": ("STRING", {"multiline": False, "default": "input/audio"}),
            "audio_file": ("STRING", {"multiline": False, "default": "<none>"}),
            "lyrics_folder_path": ("STRING", {"multiline": False, "default": "input/lyrics"}),
            "lyrics_file": ("STRING", {"multiline": False, "default": "<none>"}),
            "use_audio_alignment": ("BOOLEAN", {"default": True}),
            "song_length_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 3600.0, "step": 0.1}),
            "fps": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.5}),
        })
        types["optional"]["generate_schedule"] = ("BOOLEAN", {"default": True})
        types["optional"]["interpolate_keyframes"] = ("BOOLEAN", {"default": False})
        types["optional"]["interpolation_frame_interval"] = ("INT", {"default": 0, "min": 0, "max": 100})
        return types

    MAX_IMAGES = 5
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING") + ("IMAGE",) * MAX_IMAGES
    RETURN_NAMES = ("prompt", "schedule", "image_context", "negative_prompt") + tuple(f"reference_image_{i}" for i in range(1, MAX_IMAGES + 1))
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter"

    def execute(self, user_text, model, **kwargs):
        try:
            images_with_weights = self._collect_images_with_weights(**kwargs)
            lyrics_text, timed_segments, lyrics_meta = utils._get_lyrics_from_input(user_text, kwargs.get("lyrics_folder_path"), kwargs.get("lyrics_file"), kwargs.get("debug_mode", False))
            audio_path = utils._get_audio_path(kwargs.get("audio_folder_path"), kwargs.get("audio_file"))

            run_config = self._setup_config("Lyrics", lyrics_text or user_text, model, images_with_weights=images_with_weights, **kwargs)

            passthrough_images = [img for img, _ in images_with_weights]
            passthrough_images.extend([None] * (self.MAX_IMAGES - len(passthrough_images)))

            prompt, schedule, image_context, negative_prompt = self._handle_lyrics_mode(
                lyrics=lyrics_text,
                timed_segments=timed_segments,
                images_with_weights=images_with_weights,
                user_instructions=user_text,
                lyrics_meta=lyrics_meta,
                config=run_config,
                audio_path=audio_path,
                generate_schedule=kwargs.get("generate_schedule", False),
                negative_prompt=kwargs.get("negative_prompt", ""),
                save_to_txt=kwargs.get("save_to_txt", False),
                filename_prefix=kwargs.get("filename_prefix", "lyrics_prompts")
            )
            return (prompt, schedule, image_context, negative_prompt) + tuple(passthrough_images)
        except Exception as e:
            return self._handle_creator_exception(e)

    def _handle_lyrics_mode(self, lyrics, timed_segments, images_with_weights, user_instructions, lyrics_meta, config, audio_path=None, generate_schedule=False, negative_prompt="", save_to_txt=False, filename_prefix=""): # noqa
        if config.use_audio_alignment and audio_path and lyrics and not lyrics.startswith("[Error"):
            print("\033[94m[PromptCrafter] Audio file provided. Performing audio-lyric alignment (this is experimental)...\033[0m")
            spectrogram_img = utils.audio_to_spectrogram(audio_path)
            if isinstance(spectrogram_img, Image.Image):
                corrected_lyrics = self._validate_lyrics_against_audio(lyrics, spectrogram_img, config)
                if corrected_lyrics.strip() and corrected_lyrics.strip() != lyrics.strip():
                    print("\033[92m[PromptCrafter] Lyrics corrected based on audio analysis.\033[0m")
                    lyrics = corrected_lyrics
                    lyrics, timed_segments = utils._process_lyrics_content(lyrics)
            else:
                print(f"\033[93m[PromptCrafter] Warning: Could not generate spectrogram. Error: {spectrogram_img}\033[0m")

        if not lyrics or not lyrics.strip(): return ("No lyrics provided.", "", "No reference images provided.", "")
        if lyrics.startswith("[Error"):
            return (f"Failed to process lyrics input: {lyrics}", "", "No reference images provided.", "")

        image_context, mandatory_tokens, style_inspiration_section, instructions_section, context_section = self._prepare_lyrics_generation_context(user_instructions, images_with_weights, lyrics, config)
        
        theme_ok, global_theme_or_err = self._generate_storyboard_global_theme(lyrics, instructions_section, context_section, image_context, config)
        if not theme_ok: return (global_theme_or_err, "", image_context, "")

        storyboard_prompts = self._process_lyrics_storyboard(lyrics, timed_segments, global_theme_or_err, mandatory_tokens, style_inspiration_section, config)
        if not storyboard_prompts or (isinstance(storyboard_prompts, str) and storyboard_prompts.startswith("Could not generate")):
            return (storyboard_prompts or "Failed to generate storyboard prompts.", "", image_context, "")

        storyboard_text_for_neg_prompt = "\n\n---\n\n".join(storyboard_prompts)
        ai_negative_prompt = utils._generate_negative_prompt(storyboard_text_for_neg_prompt, config, user_negative_prompt="")
        parts = [p for p in [negative_prompt, ai_negative_prompt] if p and p.strip()]
        final_negative_prompt = ", ".join(parts)

        final_output = self._create_final_lyrics_output(storyboard_prompts=storyboard_prompts, timed_segments=timed_segments, generate_schedule=generate_schedule, fps=config.fps, song_length_seconds=config.song_length_seconds, config=config)
        
        prompt_out, schedule_out = ("", final_output) if generate_schedule else (final_output, "")

        if save_to_txt: self._save_lyrics_output_to_file(filename_prefix, lyrics_meta, image_context, lyrics, final_negative_prompt, final_output)
        return (prompt_out, schedule_out, image_context, final_negative_prompt)

    # // AI ENHANCEMENT: New method to group lyrics into logical scenes using an LLM.
    # // This creates more meaningful chunks (verse, chorus, etc.) than simple line-by-line processing.
    def _group_lyrics_into_scenes(self, lyrics, run_config):
        """Groups raw lyrics into narratively coherent scenes using an AI model."""
        print("\033[94m[PromptCrafter] Grouping lyrics into logical scenes using AI...\033[0m")
        prompt = textwrap.dedent(f"""
            You are a literary analyst. Your task is to read the following song lyrics and group them into logical scenes or sections (like Verse 1, Chorus, Bridge, etc.).
            Each scene should represent a distinct part of the narrative or a shift in mood.

            --- LYRICS ---
            {lyrics}
            --- END LYRICS ---

            RULES:
            1. Analyze the structure and meaning to identify logical breaks.
            2. Group consecutive lines into scenes. Do not split a single thought.
            3. Return ONLY a JSON object with a single key "scenes", which is an array of strings. Each string in the array should be a multi-line block of lyrics representing one scene.

            Example Output:
            {{
                "scenes": [
                    "First line of verse 1\\nSecond line of verse 1",
                    "First line of the chorus\\nSecond line of the chorus",
                    "First line of verse 2\\nSecond line of verse 2"
                ]
            }}
        """).strip()

        ok, result_json = api_clients._reason_with_model(run_config.model, prompt, use_chat_api=run_config.use_chat_api, temperature=0.0, seed=run_config.seed, debug_mode=run_config.debug_mode, debug_title="Lyric Scene Grouping")
        
        if ok and isinstance(result_json, dict) and "scenes" in result_json and isinstance(result_json["scenes"], list):
            print(f"\033[92m[PromptCrafter] Successfully grouped lyrics into {len(result_json['scenes'])} scenes.\033[0m")
            return result_json["scenes"]
        else:
            print(f"\033[93m[PromptCrafter] Warning: AI-based lyric grouping failed. Falling back to line-by-line processing. Error: {result_json}\033[0m")
            return None # Fallback signal

    def _validate_lyrics_against_audio(self, lyrics_text, audio_img, run_config): # noqa
        prompt = f"""You are a lyrics alignment assistant.
Compare the provided text (lyrics) with the singing audio represented by this spectrogram.
Correct any misheard or missing words. Maintain line breaks and rhythm.

RAW LYRICS:
{lyrics_text}

Return ONLY the corrected lyrics."""
        ok, corrected = api_clients.query_model_auto(run_config.model, prompt, images=[audio_img], prefer_chat=True, temperature=run_config.temperature, seed=run_config.seed, debug_mode=run_config.debug_mode, timeout=run_config.timeout, debug_title="Audio-Lyric Cross-Check")
        return corrected if ok else lyrics_text

    def _prepare_lyrics_generation_context(self, user_instructions, images_with_weights, lyrics, run_config): # noqa
        images = [img for img, _ in images_with_weights]
        describe_result = self._describe_images(images_with_weights, run_config)
        if describe_result is None:
            image_context, _ = "No reference images provided.", []
        else:
            image_context, _ = describe_result
        parsed_instructions, parsed_context = user_instructions, ""
        style_inspiration_section, instructions_section, context_section = self._prepare_lyrics_context_sections(run_config, images, lyrics, parsed_instructions, parsed_context)
        tok_ok, mandatory_tokens = utils._extract_mandatory_tokens_with_model(image_context, (parsed_instructions or ""), run_config)
        return image_context, (mandatory_tokens if tok_ok else {}), style_inspiration_section, instructions_section, context_section

    def _prepare_lyrics_context_sections(self, run_config, images, lyrics, instructions, context): # noqa
        style_inspiration_section = ""
        if run_config.style_profile:
            inspiration = run_config.style_profile.get("inspiration", "")
            if inspiration: style_inspiration_section = f"- {inspiration}\n"
        elif run_config.style_override != "None" and run_config.style_override in style_profiles.STYLE_KEYWORDS:
            style_inspiration_section = f"- Style: {style_profiles.STYLE_KEYWORDS[run_config.style_override]}\n"
        else:
            inspiration = run_config.style_profile.get("inspiration", "")
            if inspiration: style_inspiration_section = f"- {inspiration.lstrip('- ').strip()}\n"
        
        instructions_section = f"SONG INSTRUCTIONS (use as a guide, but prioritize the ACTION/MOTION rules):\n{instructions}\n\n" if instructions and instructions.strip() else ""
        context_section = f"SONG CONTEXT & NARRATIVE (for mood and story):\n{context}\n\n" if context and context.strip() else ""
        return style_inspiration_section, instructions_section, context_section

    def _generate_storyboard_global_theme(self, lyrics, instructions_section, context_section, image_context, run_config): # noqa
        theme_prompt = f"""You are a music video director. Your task is to analyze the provided source material and synthesize a \"Global Theme\" for a music video. This theme is a high-level summary that will ensure visual consistency across all scenes.

**CRITICAL INSTRUCTIONS:**
1.  **Analyze Source Material:** Your theme MUST be based on the explicit information and implicit mood of the LYRICS, INSTRUCTIONS, and IMAGE REFERENCES.
2.  **Handle Abstract Lyrics:** If the lyrics are abstract or non-narrative, focus on interpreting the core emotions, mood, and symbolism. Translate these abstract concepts into a cohesive visual theme. For example, for lyrics about loneliness, you might suggest a theme of 'a single figure in vast, empty landscapes with a cool, desaturated color palette'.
3.  **Avoid Contradiction:** Do NOT invent narratives or characters that contradict the source material. Your theme should be a creative interpretation, not a replacement.
4.  **Define Core Elements:** The theme should define the core visual style, setting, character design, and mood.

--- LYRICS ---
{lyrics}
--- INSTRUCTIONS ---
{instructions_section}
--- CONTEXT ---
{context_section}
--- IMAGE REFERENCES ---
{image_context}
---
Return ONLY the Global Theme description in a single, concise paragraph."""
        ok, theme = api_clients.query_model_auto(run_config.model, theme_prompt, prefer_chat=run_config.use_chat_api, temperature=run_config.temperature, seed=run_config.seed, timeout=120, debug_mode=run_config.debug_mode, debug_title="Storyboard Global Theme")
        return (True, utils.TextCleaner.single_paragraph(theme)) if ok else (False, f"Could not generate storyboard theme: {theme}")

    # // AI ENHANCEMENT: Reworked the entire storyboard generation process.
    # // It now segments lyrics more intelligently and uses a two-step "concept -> prompt" process.
    def _process_lyrics_storyboard(self, lyrics, timed_segments, global_theme, mandatory_tokens, style_inspiration_section, run_config):
        storyboard_rules_text = self._build_storyboard_rules(run_config, style_inspiration_section)
        
        segments = []
        if timed_segments:
            # Use SRT data if available
            segments = [(str(i + 1), seg[2]) for i, seg in enumerate(timed_segments)]
        else:
            # Otherwise, use AI to group lyrics into scenes
            scene_lyrics = self._group_lyrics_into_scenes(lyrics, run_config)
            if scene_lyrics:
                segments = [(f"Scene {i + 1}", scene_text) for i, scene_text in enumerate(scene_lyrics)]
            else:
                # Fallback to line-by-line if AI grouping fails
                segments = [(f"Line {i + 1}", line) for i, line in enumerate(lyrics.splitlines()) if line.strip()]

        if not segments: return "Could not segment lyrics into processable lines or sections."

        print(f"\033[94m[PromptCrafter] Generating storyboard for {len(segments)} scenes iteratively...\033[0m")
        processed_prompts: list[str] = [""] * len(segments)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(segments))) as executor:
            # Submit all jobs to the executor
            future_to_index = {
                executor.submit(self._create_prompt_for_scene, name, text, global_theme, storyboard_rules_text, mandatory_tokens, run_config): i
                for i, (name, text) in enumerate(segments)
            }
            # Process results as they complete
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                segment_name, _ = segments[index]
                try:
                    processed_prompts[index] = future.result()
                    print(f"\033[92m[PromptCrafter] Finished processing '{segment_name}'.\033[0m")
                except Exception as exc:
                    error_message = f"Scene '{segment_name}' generated an exception: {exc}"
                    print(f'\033[91m[PromptCrafter] {error_message}\033[0m')
                    processed_prompts[index] = f"[Error: {error_message}]"
        
        return processed_prompts

    # // AI ENHANCEMENT: This is the new core method for generating prompts.
    # // It uses a two-step process to first create a simple "shot concept" and then
    # // expand it into a polished, concise final prompt. This improves conceptual quality and brevity.
    def _create_prompt_for_scene(self, scene_name, scene_text, global_theme, storyboard_rules_text, mandatory_tokens, run_config):
        """Generates a final prompt for a lyric scene in two steps: Concept and Refinement."""
        
        # --- STEP 1: Conceptualize the Shot ---
        concept_prompt = textwrap.dedent(f"""
            You are a creative music video director. Your goal is to invent a single, clear visual concept for a short 5-second video clip that represents the lyrics provided.

            --- GLOBAL THEME (for visual consistency) ---
            {global_theme}

            --- LYRIC SCENE: "{scene_name}" ---
            {scene_text}
            ---
            
            TASK: Describe a single, compelling camera shot. Focus on ONE core action or visual moment.
            - What is the subject doing?
            - What is the key visual element?
            - Keep the concept description to a single, simple sentence (under 20 words).

            Return ONLY the shot concept sentence.
        """).strip()

        concept_ok, shot_concept = api_clients.query_model_auto(
            run_config.model, concept_prompt, prefer_chat=run_config.use_chat_api, temperature=run_config.temperature,
            seed=run_config.seed, timeout=90, debug_mode=run_config.debug_mode, debug_title=f"Concept for '{scene_name}'"
        )

        if not concept_ok:
            error_msg = f"Failed to generate concept for '{scene_name}': {shot_concept}"
            print(f"\033[93m[PromptCrafter] Warning: {error_msg}\033[0m")
            return f"[Error: {error_msg}]"

        # --- STEP 2: Refine the Concept into a Final Prompt ---
        refine_prompt = textwrap.dedent(f"""
            You are an expert prompt engineer for video generation models. Your task is to refine the SHOT CONCEPT into a concise, high-quality final prompt.

            --- SHOT CONCEPT ---
            {shot_concept}
            ---
            
            --- STYLE & COMPOSITION RULES ---
            {storyboard_rules_text}
            ---
            
            TASK:
            1.  Translate the SHOT CONCEPT into a powerful, descriptive prompt.
            2.  Integrate the style and composition rules naturally.
            3.  Ensure the final prompt is clear, focused, and remains concise.

            Return ONLY the final, polished prompt.
        """).strip()

        final_ok, final_prompt = api_clients.query_model_auto(
            run_config.model, refine_prompt, prefer_chat=run_config.use_chat_api, temperature=run_config.temperature,
            seed=run_config.seed, timeout=90, debug_mode=run_config.debug_mode, debug_title=f"Refine Prompt for '{scene_name}'"
        )
        
        if not final_ok:
            error_msg = f"Failed to refine prompt for '{scene_name}': {final_prompt}"
            print(f"\033[93m[PromptCrafter] Warning: {error_msg}\033[0m")
            return f"[Error: {error_msg}]"

        return utils.TextCleaner.slim_prompt_text(utils.TextCleaner.single_paragraph(final_prompt))

    # // AI ENHANCEMENT: Updated storyboard rules to be more direct and enforce brevity.
    # // Specifically targets a ~5 second / 77-81 frame output per prompt.
    def _build_storyboard_rules(self, run_config, style_inspiration_section):
        safety_rule = f"\n{config.SAFE_MODE_RULE}" if run_config.safe_mode else ""
        length_rule = f"- The final prompt must be concise (ideally under {run_config.max_length_words} words) to create a clear, focused 5-second video clip (approx. 77-81 frames)."
        negative_concepts_rule = f"- CRITICAL: Do NOT include any of the following concepts: {run_config.negative_concepts}" if run_config.negative_concepts else ""
        
        return textwrap.dedent(f"""
            - All generated prompt text MUST be in {run_config.language}.
            {style_inspiration_section.strip()}
            {safety_rule.strip()}
            {negative_concepts_rule.strip()}
            - The visual elements (characters, setting) must be consistent with the Global Theme.
            - The ACTION and MOOD must be a direct visual interpretation of the specific lyric scene.
            - CRITICAL PRIORITY: Focus on a single, clear subject ACTION and physics-based MOTION.
            - Keep the environment concise and supporting, not distracting.
            - Maintain visual continuity with the overall theme.
            {length_rule}
        """).strip()

    def _create_final_lyrics_output(self, storyboard_prompts, timed_segments, generate_schedule, fps, song_length_seconds, config): # noqa
        if not generate_schedule: return "\n\n---\n\n".join(storyboard_prompts)
        if timed_segments: return self._create_schedule_from_srt(storyboard_prompts, timed_segments, fps, config)
        max_frames = int(song_length_seconds * fps) if song_length_seconds > 0 else config.max_frames
        return utils._create_schedule_from_items(storyboard_prompts, max_frames, 0, config.interpolate_keyframes, config.interpolation_frame_interval)

    def _create_schedule_from_srt(self, storyboard_prompts, timed_segments, fps, run_config): # noqa
        print("\033[94m[PromptCrafter] SRT file detected. Generating timed schedule...\033[0m")
        if len(storyboard_prompts) != len(timed_segments):
            return f"[Error: Mismatch between SRT segments ({len(timed_segments)}) and generated prompts ({len(storyboard_prompts)}).]"
        schedule = collections.OrderedDict()
        for i, seg in enumerate(timed_segments):
            frame = int(seg[0] * fps)
            prompt = storyboard_prompts[i].strip()
            schedule[frame] = prompt
        if run_config.interpolate_keyframes:
            schedule = utils._interpolate_schedule_prompts(schedule, run_config.interpolation_frame_interval)
        schedule_items = ",".join([f'\"{str(key)}\": {json.dumps(str(value))}' for key, value in schedule.items()])
        return f"{{{schedule_items}}}"

    def _save_lyrics_output_to_file(self, filename_prefix, lyrics_meta, image_context, lyrics, final_negative_prompt, final_output): # noqa
        if not final_output or not final_output.strip(): return
        sections = []
        if lyrics_meta and lyrics_meta[0] and lyrics_meta[1] and lyrics_meta[1] != "<none>":
            sections.append(("LYRICS SOURCE FILE", f"folder: {lyrics_meta[0]}\nfile: {lyrics_meta[1]}"))
        sections.extend([("IMAGE CONTEXT", image_context or "No reference images provided."), ("LYRICS", (lyrics or "").strip()), ("NEGATIVE PROMPT", final_negative_prompt or ""), ("OUTPUT", final_output)])
        utils._save_output_to_file(filename_prefix, sections, base_filename="lyrics_prompts")
class PromptCrafter_ClearCache:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"action": (["Clear Cache", "Check Size"], {"default": "Clear Cache"})}}
    INPUT_IS_CHANGED = "ALWAYS"

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status",)
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter/Utils"

    def execute(self, action):
        if action == "Clear Cache":
            removed_count = config.CACHE.clear()
            status_message = f"Cache cleared. Removed {removed_count} items."
            print(f"\033[92m[PromptCrafter] {status_message}\033[0m")
        else:
            status_message = f"Cache contains {config.CACHE.size} of {config.CACHE.max_size} items."
        return (status_message,)

NODE_CLASS_MAPPINGS = {
    "PromptCrafter_QnA": PromptCrafter_QnA,
    "PromptCrafter_Captioner": PromptCrafter_Captioner,
    "PromptCrafter_ImageCreator": PromptCrafter_ImageCreator,
    "PromptCrafter_VideoCreator": PromptCrafter_VideoCreator,
    "PromptCrafter_LyricsCreator": PromptCrafter_LyricsCreator,
    "PromptCrafter_ClearCache": PromptCrafter_ClearCache,
    "PromptCrafter_FileOrganizer": PromptCrafter_FileOrganizer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_QnA": f"PromptCrafter QnA",
    "PromptCrafter_Captioner": f"PromptCrafter Image Captioner",
    "PromptCrafter_ImageCreator": f"PromptCrafter Image Prompt Creator",
    "PromptCrafter_VideoCreator": f"PromptCrafter Video Prompt Creator",
    "PromptCrafter_LyricsCreator": f"PromptCrafter Lyrics-to-Prompt Creator",
    "PromptCrafter_ClearCache": f"PromptCrafter Cache Utility",
    "PromptCrafter_FileOrganizer": f"PromptCrafter File Organizer",
}