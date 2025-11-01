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
import librosa

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
# Helper function to read node descriptions from HELP.md
# ------------------------------------------------------------------------------------
def get_node_description(node_name):
    """Parses HELP.md and extracts the description for a given node class name."""
    try:
        help_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "HELP.md")
        if not os.path.exists(help_path):
            return f"Help file not found for {node_name}."

        with open(help_path, "r", encoding="utf-8") as f:
            content = f.read()

        pattern = re.compile(rf"## `{node_name}`\n(.*?)(?=\n## `|\Z)", re.DOTALL)
        match = pattern.search(content)

        if match:
            return match.group(1).strip()
        else:
            # Fallback for the custom profiles section
            if node_name == "Customizing Profiles":
                pattern = re.compile(r"## Customizing Profiles\n(.*)", re.DOTALL)
                match = pattern.search(content)
                if match:
                    return match.group(1).strip()
            return f"No description found in HELP.md for {node_name}."

    except Exception as e:
        return f"Error reading help file: {e}"

# ------------------------------------------------------------------------------------
# PromptCrafter_QnA Node
# ------------------------------------------------------------------------------------
class PromptCrafter_QnA:
    DESCRIPTION = get_node_description("PromptCrafter_QnA")
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "instruction": ("STRING", {"multiline": True, "default": config.DEFAULT_PROMPT_TEXT, "tooltip": "Your primary question or instruction for the model."}),
                "subject": ("STRING", {"multiline": True, "default": "", "tooltip": "Optional: The subject, topic, or any additional text to provide context for your instruction."}),
                "model": (api_clients.get_all_models(), {"tooltip": "The language model (text or vision) to use for the answer."}),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Controls creativity. Lower is more deterministic."}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "step": 1, "tooltip": "Seed for reproducible results. -1 for random. Set Temperature to 0 for full determinism."}),
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10, "tooltip": "Timeout in seconds for each API call. Increase if you get timeout errors."} ),
                "safe_mode": ("BOOLEAN", {"default": True, "tooltip": "Enforce SFW rules to prevent NSFW, violent, or controversial content."} ),
                "debug_mode": ("BOOLEAN", {"default": False, "tooltip": "Print all intermediate prompts to the console for debugging."} ),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
            "optional": {
                "image": ("IMAGE", {"tooltip": "Optional reference image for the query. Requires a vision model (VLM)."}),
                "auto_select_model": ("BOOLEAN", {"default": True, "tooltip": "Automatically select a vision model if an image is connected, or a text model if not."} ),
                "enable_web_search": ("BOOLEAN", {"default": True, "tooltip": "Allow the node to perform a web search for questions about recent events or topics requiring current information."} ),
                "fast_web_search": ("BOOLEAN", {"default": True, "tooltip": "In web search mode, only use search result snippets instead of fetching full page content. Much faster."} ),
                "folder_path": ("STRING", {"multiline": False, "default": "input", "tooltip": "Folder containing an optional context file (e.g., 'input' or 'input/texts')."}),
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
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter/Utils"
    
    def execute(self, instruction, subject, model, **kwargs):
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
                    safe_folder = folder_path if folder_path is not None else ""
                    safe_file = file_name if file_name is not None else ""
                    context = f"[Error: File not found at '{os.path.join(safe_folder, safe_file)}'.]"
                    raw_context = context
                    context_source = f"File ({file_name}) - Not Found"
            elif enable_web_search:
                search_needed, search_query = utils._should_perform_web_search(instruction, llm_model, seed, debug_mode, timeout=timeout)
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
                    context = utils._summarize_large_text(raw_context, chunk_size_words, llm_model, temperature, seed, debug_mode, timeout, strategy=strategy_key, user_query=instruction)
                    utils._debug_print(debug_mode, "Summarized Context", context)

            final_user_text, raw_user_text = instruction, instruction
            if chunk_large_context and len(instruction.split()) > chunk_size_words and instruction.strip() != config.DEFAULT_PROMPT_TEXT:
                print(f"\033[94m[PromptCrafter] User text is large. Summarizing...\033[0m")
                final_user_text = utils._summarize_large_text(instruction, chunk_size_words, llm_model, temperature, seed, debug_mode, timeout, strategy=strategy_key)
                utils._debug_print(debug_mode, "Summarized User Text", final_user_text)

            if (context or image is not None) and instruction.strip() == config.DEFAULT_PROMPT_TEXT:
                final_user_text = "Describe this image in detail." if image is not None else "Summarize the key points of the provided context."

            user_query = final_user_text
            if subject and subject.strip():
                user_query = f"SUBJECT:\n{subject}\n\nINSTRUCTION:\n{final_user_text}"

            safety_rule = f"\n\n{config.SAFE_MODE_RULE}" if safe_mode else ""
            history_section = f"CONVERSATION HISTORY (for context):\n{history_text}\n\n" if history_text else ""
            context_section = f"ADDITIONAL CONTEXT (for this query only):\n{context}\n\n" if context else ""
            prompt = f"You are a helpful Q&A assistant. Answer the user's query based on the conversation history and any additional context provided.\n\n{history_section}{context_section}CURRENT USER QUERY:\n{user_query}{safety_rule}".strip()

            images_to_pass = [image] if image is not None else None
            ok, resp = api_clients.query_model_auto(llm_model, prompt, images=images_to_pass, prefer_chat=True, temperature=temperature, seed=seed, debug_mode=debug_mode, debug_title="QnA Prompt", timeout=timeout)

            response_text = resp if ok else f"Ollama error: {resp}"
            # If the response looks like a JSON object or array, don't clean it to preserve its structure.
            stripped_response = response_text.strip()
            if not (stripped_response.startswith('{') and stripped_response.endswith('}')) and not (stripped_response.startswith('[') and stripped_response.endswith(']')):
                response_text = utils.TextCleaner.single_paragraph(response_text)
            new_history_entry = f"User: {user_query}\nAssistant: {response_text}"
            updated_history = f"{history_text}\n{new_history_entry}".strip() if history_text else new_history_entry

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
    DESCRIPTION = get_node_description("PromptCrafter_Captioner")
    @classmethod
    def INPUT_TYPES(cls):
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
                "captioner_profile": (captioner_profiles.get_captioner_profile_options(), {"default": "Default (Training Style)", "tooltip": "Select a pre-configured captioning prompt. Overrides the manual prompt text box."} ),
                "max_workers": ("INT", {"default": 4, "min": 1, "max": 16, "step": 1, "tooltip": "Number of parallel threads for batch processing."} ),
                "caption_prompt": ("STRING", {"multiline": True, "default": config.DEFAULT_CAPTION_PROMPT, "tooltip": "The prompt template used to guide the captioning model."} ),
                "caption_prefix": ("STRING", {"multiline": False, "default": "", "tooltip": "A single trigger word to add to every caption. Overridden by the trigger words file."} ),
                "trigger_words_folder_path": ("STRING", {"multiline": False, "default": "input", "tooltip": "Folder containing an optional file of trigger words (one per line)."}),
                "trigger_words_file": ("STRING", {"multiline": False, "default": "<none>", "tooltip": "File with a list of trigger words to be randomly chosen from for each caption."} ),
                "save_caption": ("BOOLEAN", {"default": True, "tooltip": "Save the caption to a text file."} ),
                "save_in_input_folder": ("BOOLEAN", {"default": True, "tooltip": "If True, saves the .txt caption file in the batch mode input folder alongside the image. If False, saves to the output_path."} ),
                "add_caption_to_metadata": ("BOOLEAN", {"default": True, "tooltip": "Write the caption to the image's metadata (e.g., EXIF). Requires `piexif` library."} ),
                "rename_file_with_caption": ("BOOLEAN", {"default": False, "tooltip": "In batch mode, rename the image file based on the generated caption. Makes files searchable."} ),
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
        text = re.sub(r'[\\/*?:"<<>>|]', '', text)
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

            image_files = [f for f in os.listdir(full_folder_path) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp"))]
            if not image_files: return (f"No images found in {full_folder_path}",)

            # Determine the output directory for caption files
            if save_in_input_folder:
                out_dir = full_folder_path
            else:
                out_dir = utils._get_and_create_output_dir(output_path)
                if not out_dir: return (f"Could not create or access output path: {output_path}",)

            processed_count, renamed_count, skipped_count, failed_count = 0, 0, 0, 0
            failed_files = []

            # --- FIX 1: Corrected ThreadPoolExecutor Dictionary Syntax ---
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_img = {
                    executor.submit(
                        self._caption_one_image,
                        utils.pil2tensor(Image.open(os.path.join(full_folder_path, img)).convert("RGB")),
                        model,
                        final_caption_prompt,
                        temperature,
                        seed,
                        debug_mode,
                        timeout
                    ): img
                    for img in image_files
                }
                # -----------------------------------------------------------

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
                            
                            # --- FIX 3: Corrected f-string for batch mode fallback ---
                            if not sanitized_base_name:
                                sanitized_base_name = f"caption_{int(time.time()*1000)}" 
                            # -------------------------------------------------------

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
                # Ensure out_dir is valid; fall back to creating the requested output_path or use CWD
                if not out_dir:
                    try:
                        os.makedirs(output_path, exist_ok=True)
                        out_dir = os.path.abspath(output_path)
                    except Exception:
                        out_dir = os.getcwd()
                        print(f"\033[93m[PromptCrafter] Warning: Could not create output path '{output_path}', falling back to current working directory: {out_dir}\033[0m")

                # --- FIX 2: Corrected f-string for single mode filename ---
                fname = filename.strip() or f"caption_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time()*1000)%1000}"
                # -------------------------------------------------------
                fname = self._sanitize_filename(fname, max_length=200)
                file_path = os.path.join(out_dir, f"{fname}.txt")
                with open(file_path, "w", encoding="utf-8") as f:
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
    def _is_speech_prompt_request(self, user_text, run_config):
        """Analyzes user text to determine if it's a request for a speech/dialogue prompt."""
        # Keywords and patterns that strongly suggest a speech prompt format
        speech_keywords = ["speech prompt", "saying:", "exclaiming", "dialogue"]
        # Regex to find <S>...<E> or similar tags
        speech_tag_pattern = re.compile(r'<S>.*<E>', re.IGNORECASE | re.DOTALL)

        if any(keyword in user_text.lower() for keyword in speech_keywords) or speech_tag_pattern.search(user_text):
            utils._debug_print(run_config.debug_mode, "Speech Prompt Check", "Pattern match found, confirming with AI.")
            prompt = textwrap.dedent(f'''
                Analyze the user's request. Is the user asking to create a text prompt that includes dialogue, speech, or specific text to be spoken by a subject, often using tags like <S> and <E>?

                --- USER REQUEST ---
                {user_text}
                ---

                Respond with ONLY a JSON object: {{"is_speech_request": true/false}}
            ''').strip()
            
            ok, result = api_clients._reason_with_model(
                run_config.model, 
                prompt, 
                use_chat_api=run_config.use_chat_api, 
                temperature=0.0, 
                seed=run_config.seed, 
                debug_mode=run_config.debug_mode, 
                debug_title="Speech Intent Check",
                timeout=run_config.timeout
            )
            
            if ok and isinstance(result, dict) and result.get("is_speech_request"):
                return True
        
        return False

    def _handle_speech_prompt_request(self, user_text, images_with_weights, run_config):
            """Handles the specific case of generating a formatted speech prompt."""
            print("\033[94m[PromptCrafter] Speech prompt format detected. Using specialized handler...\033[0m")
            
            # Use a fallback value if the subclass hasn't defined MAX_IMAGES
            num_images = getattr(self, "MAX_IMAGES", 5)
            
            if not images_with_weights:
                return ("Speech prompt generation requires an image to identify the subject.", None, None, None, None, None) + (None,) * num_images

            # 1. Get the primary subject from the first image.
            image_context, primary_subjects = self._describe_images(images_with_weights, run_config)
            
            subject_description = "A subject" # Default fallback
            if primary_subjects:
                # Clean up the subject description, removing any [PRIMARY] tags etc.
                subject_description = re.sub(r'^\s*\[PRIMARY\]\s*', '', primary_subjects[0]).strip()
            
            # 2. Use an LLM to fill in the user's template.
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

            ok, final_prompt = api_clients.query_model_auto(
                run_config.model,
                prompt,
                prefer_chat=True,
                temperature=run_config.temperature,
                seed=run_config.seed,
                debug_mode=run_config.debug_mode,
                debug_title="Speech Prompt Generation",
                timeout=run_config.timeout
            )

            if not ok:
                return (f"Failed to generate speech prompt: {final_prompt}", None, None, None, None, None) + (None,) * num_images

            # --- NEW: Generate the <AUDCAP> audio description for OVI format ---
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

            ok_aud, aud_desc = api_clients.query_model_auto(
                run_config.model,
                audcap_prompt,
                prefer_chat=True,
                temperature=0.1, # Low temp for factual description
                seed=run_config.seed,
                debug_mode=run_config.debug_mode,
                debug_title="OVI <AUDCAP> Generation",
                timeout=run_config.timeout
            )

            ovi_formatted_prompt = final_prompt # Start with the base prompt
            if ok_aud and aud_desc.strip():
                # Add the audio caption in the OVI format
                ovi_formatted_prompt = f"{final_prompt.strip().rstrip('.')} <AUDCAP> {aud_desc.strip()} <ENDAUDCAP>"
            else:
                # Fallback if AUDCAP generation fails, just use the visual prompt
                print(f"\033[93m[PromptCrafter] Warning: Could not generate <AUDCAP> description. Returning speech prompt without it. Error: {aud_desc}\033[0m")
                # ovi_formatted_prompt is already set to final_prompt, so no action needed

            # Pass through the results in the expected format for the node
            passthrough_images = [img for img, _ in images_with_weights]
            passthrough_images.extend([None] * (num_images - len(passthrough_images)))
            
            return (ovi_formatted_prompt, "", image_context, "", run_config.model, str(run_config.seed)) + tuple(passthrough_images)

    def _is_lyrics_to_prompt_request(self, user_text, run_config):
            """Analyzes user text to determine if it's a request for the multi-prompt lyric generator."""
            # Keywords that strongly suggest this specific format
            lyrics_keywords = ["lyrics:", "lyric-driven prompts", "lyric fragment", "[shot type]"]
            
            # Check for keywords and the pipe separator
            text_lower = user_text.lower()
            if any(keyword in text_lower for keyword in lyrics_keywords) and "|" in user_text:
                utils._debug_print(run_config.debug_mode, "Lyrics-to-Prompt Check", "Pattern match found, confirming with AI.")
                prompt = textwrap.dedent(f'''
                    Analyze the user's request. Is the user asking to generate a list of video prompts, where each prompt corresponds to a pipe-separated (|) lyric fragment?
                    The instructions often mention "Lyric-Driven Prompts", "Core Rules", "[Shot Type] -> [Character]", and a "Lyrics:" section.

                    --- USER REQUEST ---
                    {user_text}
                    ---

                    Respond with ONLY a JSON object: {{"is_lyrics_request": true/false}}
                ''').strip()
                
                ok, result = api_clients._reason_with_model(
                    run_config.model, 
                    prompt, 
                    use_chat_api=run_config.use_chat_api, 
                    temperature=0.0, 
                    seed=run_config.seed, 
                    debug_mode=run_config.debug_mode, 
                    debug_title="Lyrics-to-Prompt Intent Check",
                    timeout=run_config.timeout
                )
                
                if ok and isinstance(result, dict) and result.get("is_lyrics_request"):
                    return True
            
            return False

    def _handle_lyrics_to_prompt_request(self, user_text, images_with_weights, run_config):
        """Handles the specific case of generating pipe-separated prompts from lyrics."""
        print("\033[94m[PromptCrafter] Lyrics-to-Prompt format detected. Using specialized handler...\033[0m")
        
        # This task is text-only and doesn't use the 'mandatory_subjects' pipeline.
        # It's a direct call to the LLM with the user's full instructions.
        
        # We need to get the image context, if any, to add to the prompt.
        describe_result = self._describe_images(images_with_weights, run_config)
        if describe_result is None:
            image_context, primary_subjects_from_images = "No reference images provided.", []
        else:
            image_context, primary_subjects_from_images = describe_result

        # Build a prompt that *just* asks the LLM to follow the user's instructions.
        # We do NOT inject our own "MANDATORY SUBJECTS".
        prompt = textwrap.dedent(f'''
            You are an expert AI Music Video Prompt Creator. Your task is to follow the user's instructions EXACTLY to generate a series of pipe-separated video prompts.

            --- USER INSTRUCTIONS ---
            {user_text}
            ---
            
            --- REFERENCE IMAGE CONTEXT (if needed) ---
            {image_context}
            ---

            TASK:
            1.  Read the user's "Core Rules" and "Lyrics" section.
            2.  Generate EXACTLY one prompt for EACH lyric fragment.
            3.  The number of prompts MUST match the number of lyric fragments.
            4.  Each prompt MUST follow the user's specified structure (e.g., [Shot Type] -> [Character...]).
            5.  The final output MUST be a single string of all prompts, separated by the "|" character.

            Return ONLY the final, pipe-separated prompt string. Do not include any commentary.
        ''').strip()

        ok, final_prompts = api_clients.query_model_auto(
            run_config.model,
            prompt,
            prefer_chat=True,
            temperature=run_config.temperature,
            seed=run_config.seed,
            debug_mode=run_config.debug_mode,
            debug_title="Lyrics-to-Prompt Generation",
            timeout=run_config.timeout
        )

        if not ok:
            return (f"Failed to generate lyrics-to-prompt output: {final_prompts}", None, None, None, None, None) + (None,) * getattr(self, "MAX_IMAGES", 5)

        # Generate a negative prompt based on the *generated* prompts
        ai_negative_prompt = utils._generate_negative_prompt(final_prompts, run_config, user_negative_prompt="")

        # Pass through the results in the expected format for the node
        num_images = getattr(self, "MAX_IMAGES", 5)
        passthrough_images = [img for img, _ in images_with_weights]
        passthrough_images.extend([None] * (num_images - len(passthrough_images)))
        
        return (final_prompts, "", image_context, ai_negative_prompt, run_config.model, str(run_config.seed)) + tuple(passthrough_images)

    def _handle_creator_exception(self, e):
            """Logs the exception and returns a tuple matching the node's return signature."""
            import traceback
            error_message = f"[PromptCrafter] Error: {e}"
            print(f"\033[91m{error_message}\n{traceback.format_exc()}\033[0m")
            
            # This is the key: we return a tuple with the error message as the first
            # item, and then pad the rest with 'None' to match the node's
            # RETURN_TYPES. This prevents the workflow from crashing.
            # Use getattr safely to handle subclasses that define RETURN_TYPES at class level.
            try:
                # Prefer instance attribute first, then class attribute, fallback to None
                rt = getattr(self, "RETURN_TYPES", None)
                if rt is None:
                    rt = getattr(type(self), "RETURN_TYPES", None)
                num_returns = len(rt) if rt else 2
            except Exception:
                # Any unexpected issue falls back to a safe default
                num_returns = 2
                
            return (error_message,) + (None,) * (num_returns - 1)

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
- If it just describes a scene (e.g., \"create an image of a woman\", answer NO.
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
            cached = config.CACHE.get(cache_key)
            # Ensure we never return None from the cache to prevent unpacking errors.
            if cached is None:
                return ("No reference images provided.", [])
            return cached

        description_objects = [None] * len(images_with_weights)
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_index = {
                executor.submit(self._describe_one_image_with_persona, img, weight, idx, run_config): idx - 1
                for idx, (img, weight) in enumerate(images_with_weights, start=1)
                if weight > 0
            }

            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    description_objects[index] = future.result()
                except Exception as e:
                    print(f"\033[91m[PromptCrafter] Error describing image at index {index}: {e}\033[0m")
                    description_objects[index] = {"full_text": f"Image {index + 1}: [Error describing image]", "primary_subject": ""}
        
        # Filter out None values from images that were skipped (weight <= 0) or failed
        description_objects = [d for d in description_objects if d is not None]
        
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
        ok, result_json = api_clients._reason_with_model(
            run_config.model,
            desc_prompt,
            images=[img],
            use_chat_api=run_config.use_chat_api,
            temperature=run_config.temperature,
            seed=run_config.seed,
            timeout=run_config.timeout,
            debug_mode=run_config.debug_mode,
            debug_title=f"Image Description {idx}")

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
2.  Describe the visual elements of the scene factually. Describe the subject's clothing and actions. Avoid interpreting or labeling the artistic style (e.g., instead of \"punk rock\", say \"wearing a studded leather vest and ripped jeans\").
3.  If there is any readable text, transcribe it exactly.

Return ONLY a JSON object with two keys:
- \"primary_subject\": (string) The single most important subject in the image (e.g., \"a majestic stag\", \"a woman in an elegant dress\").
- \"description\": (string) The full, one-paragraph description of the entire scene.

The final output must be in {language} only.{safety_rule}"""

    def _generate_visual_prompt_pipeline(self, mode, user_text, images_with_weights, run_config, negative_prompt="", **kwargs): # noqa
        images = [img for img, _ in images_with_weights]
        if not images_with_weights and not (user_text and user_text.strip() and user_text.strip() != config.DEFAULT_PROMPT_TEXT):
            return ("No inputs provided.", None, "")
            
        ok_context, context_data = self._prepare_visual_prompt_context(user_text, images_with_weights, run_config)
        if not ok_context: return (context_data[0], None, "")
        image_context, user_instructions, user_context, mandatory_tokens, primary_subjects_from_images = context_data

        ok_draft, draft_or_err = self._generate_initial_draft(mode, user_instructions, user_context, image_context, mandatory_tokens, images, run_config, primary_subjects_from_images) # noqa
        if not ok_draft: return (draft_or_err, image_context, "")
        scene_prompt = draft_or_err
        
        # Ensure we always pass strings to _build_style_and_composition_rules to avoid type issues
        safe_user_instructions = user_instructions or ""
        safe_user_context = user_context or ""
        safe_image_context = image_context or ""
        # Ensure image_context is a string before passing
        image_context_str = str(safe_image_context) if not isinstance(safe_image_context, str) else safe_image_context
        style_rules = self._build_style_and_composition_rules(mode, images, run_config, safe_user_instructions, safe_user_context, image_context_str) # noqa
        scene_prompt = self._refine_image_video_prompt(scene_prompt, mode, mandatory_tokens, style_rules, run_config) # noqa
        
        new_positive, counter_negatives = utils._simplify_for_diffusion(scene_prompt, user_text, run_config)
        scene_prompt = new_positive

        combined_negative_input = f"{negative_prompt}, {counter_negatives}".strip().strip(',')
        final_negative_prompt = self._finalize_visual_prompt_output(scene_prompt, image_context, user_text, mandatory_tokens, run_config, user_negative_prompt=combined_negative_input) # noqa

        return (scene_prompt, image_context, final_negative_prompt)

    def _prepare_visual_prompt_context(self, user_text, images_with_weights, run_config):
        describe_result = self._describe_images(images_with_weights, run_config)
        if describe_result is None:
            image_context, primary_subjects_from_images = "No reference images provided.", []
        else:
            image_context, primary_subjects_from_images = describe_result

        # This logic is now consolidated and correctly handles all cases.
        tok_ok, tokens_or_msg = utils._extract_mandatory_tokens_with_model(image_context, user_text, run_config, primary_subjects_from_images)

        # If token extraction from text fails, but we have subjects from images,
        # treat the image subjects as mandatory and continue. This handles cases
        # where the user provides an image with a generic prompt like "create a prompt for this."
        if not tok_ok and primary_subjects_from_images:
            print("\033[94m[PromptCrafter] No subjects found in text prompt. Using subjects from image analysis instead.\033[0m")
            tok_ok = True
            tokens_or_msg = {"primary": primary_subjects_from_images, "allowed_list": primary_subjects_from_images}

        if not tok_ok:
            return False, (tokens_or_msg, None, None, None, None)
        
        mandatory_tokens = tokens_or_msg
        # Robust handling: ensure we have an iterable list of primary items regardless of the returned type.
        primary_list = []
        if isinstance(mandatory_tokens, dict):
            primary_list = mandatory_tokens.get("primary", []) or []
        elif isinstance(mandatory_tokens, str):
            primary_list = [mandatory_tokens]
        elif isinstance(mandatory_tokens, (list, tuple)):
            primary_list = list(mandatory_tokens)
        else:
            primary_list = []

        # Normalize to a flat list of strings
        normalized_primary = []
        for item in primary_list:
            if item is None:
                continue
            if isinstance(item, (list, tuple)):
                for sub in item:
                    if isinstance(sub, str):
                        normalized_primary.append(sub)
                    else:
                        try:
                            normalized_primary.append(str(sub))
                        except Exception:
                            continue
            elif isinstance(item, str):
                normalized_primary.append(item)
            else:
                try:
                    normalized_primary.append(str(item))
                except Exception:
                    continue

        all_primary_subjects = [re.sub(r'^\s*\bPRIMARY\b\s*', '', t).strip() for t in normalized_primary]
        # --- FIX 2: Inject the Image 1 Subject as Mandatory ---
        if image_context:
            try:
                # The image_context contains the JSON output from the initial image analysis
                image_json = json.loads(image_context)
                primary_subject_from_image = image_json.get("primary_subject", "").strip()

                if primary_subject_from_image:
                    # Append the image's subject to the mandatory list
                    # Prepending a tag ensures it's clearly identified as the primary visual focus
                    tagged_subject = f"[PRIMARY] {primary_subject_from_image}"
                    if tagged_subject not in all_primary_subjects:
                         all_primary_subjects.append(tagged_subject)
            except json.JSONDecodeError:
                # Log error if image context isn't valid JSON, but continue
                print(f"[PromptCrafter] Warning: Failed to parse Image 1 JSON for subject injection.")
        # -----------------------------------------------------------
        # --- FIX: Strip Example Section to Prevent Subject Misinterpretation ---
        # The 'example:' block often contains subjects that are incorrectly parsed as mandatory.
        # This regex removes the 'example:' keyword and everything that follows it.
        cleaned_user_text = re.sub(r'(\n|\r\n|\r)?example:.*', '', user_text, flags=re.DOTALL)
        # ------------------------------------------------------------------
        
        user_instructions, user_context = cleaned_user_text, ""
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
            Does the user want to combine features from one subject onto another (e.g., \"an eagle with antlers\", \"a woman wearing a dress made of flowers\")?

            Respond with ONLY a JSON object containing a single boolean key \"blending_requested\".
            Example: {{'blending_requested': true}}
        """ ).strip()
        ok, result_json = api_clients._reason_with_model(
            run_config.model,
            prompt,
            use_chat_api=run_config.use_chat_api,
            temperature=0.0, seed=run_config.seed,
            debug_mode=run_config.debug_mode,
            debug_title="Blending Intent Check",
            timeout=run_config.timeout) # <-- ADD THIS LINE
        
        return ok and isinstance(result_json, dict) and result_json.get("blending_requested", False)

    def _user_requests_replacement_with_ai(self, user_text, primary_subjects, run_config): # noqa
        prompt = textwrap.dedent(f"""
            You are a request analysis expert. Read the user's instructions and determine if they are asking to REPLACE one subject with another.

            --- PRIMARY SUBJECTS (from images) ---
            {json.dumps(primary_subjects)}

            --- USER INSTRUCTIONS ---
            {user_text}

            --- ANALYSIS ---
            Does the user want to replace a subject from the images with a new one from their instructions (e.g., \"replace the man with a robot\", \"instead of a car, make it a spaceship\")?

            Respond with ONLY a JSON object containing a single boolean key \"replacement_requested\".
            Example: {{'replacement_requested': true}}
        """ ).strip()
        ok, result_json = api_clients._reason_with_model(
            run_config.model,
            prompt,
            use_chat_api=run_config.use_chat_api,
            temperature=0.0, seed=run_config.seed,
            debug_mode=run_config.debug_mode,
            debug_title="Replacement Intent Check",
            timeout=run_config.timeout) # <-- ADD THIS LINE
        
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

---
SCENE CONTEXT ---
User Instructions: {user_instructions}
Image Descriptions: {image_context}
---
END SCENE CONTEXT ---

Part 1: Choose ONE motion style from the following list that best fits the overall mood and action:
- \"subtle, natural\": For calm, still scenes (e.g., gentle breeze).
- \"smooth, flowing\": For graceful, continuous movements (e.g., dancing, walking).
- \"dynamic, cinematic\": For energetic, purposeful actions (e.g., running, dramatic gestures).
- \"intense, action-packed\": For high-energy, chaotic scenes (e.g., battles, chases).

Part 2: Based on your choice, suggest ONE specific camera movement from this list:
- \"static shot\", \"slow pan left\", \"slow pan right\", \"tilt up\", \"tilt down\", \"dolly zoom\", \"tracking shot\", \"handheld shaky cam\", \"crane shot\".

Return ONLY a JSON object with your choices.
Example: {{'motion_style': \"dynamic, cinematic\", 'camera_movement': \"tracking shot\"}}"""
        ok, result_json = api_clients._reason_with_model(
            run_config.model,
            motion_analysis_prompt,
            use_chat_api=run_config.use_chat_api,
            temperature=0.1,
            seed=run_config.seed,
            debug_mode=run_config.debug_mode,
            debug_title="Video Motion Style Analysis",
            timeout=run_config.timeout) # <-- ADD THIS LINE

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
        primary_items_list = [re.sub(r'^\[\w+\]\\s*', '', t) for t in (mandatory_tokens or {}).get("primary", [])]

        if not primary_items_list:
            critique_prompt = self._build_refinement_prompt(current_prompt, mode, [], [], style_rules, run_config, ask_for_json=False)
            ok, revised_prompt = api_clients.query_model_auto(run_config.model, critique_prompt, prefer_chat=run_config.use_chat_api, temperature=run_config.temperature, seed=run_config.seed, timeout=run_config.timeout, debug_mode=run_config.debug_mode, debug_title="Image/Video Refine (Single Pass)")
            return utils.TextCleaner.single_paragraph(revised_prompt if ok else current_prompt)

        all_allowed = (mandatory_tokens or {}).get("allowed_list", [])

        for i in range(run_config.max_retries + 1):
            critique_prompt = self._build_refinement_prompt(current_prompt, mode, primary_items_list, all_allowed, style_rules, run_config, ask_for_json=True)
            ok, result_json = api_clients._reason_with_model(
                run_config.model,
                critique_prompt,
                use_chat_api=run_config.use_chat_api,
                temperature=run_config.temperature,
                seed=run_config.seed,
                timeout=run_config.timeout, # <-- ADD THIS LINE
                debug_mode=run_config.debug_mode,
                debug_title=f"Image/Video Refine & Check (Try {i+1})")

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
--- END JSON RESPONSE INSTRUCTIONS ---""" ) # noqa
        text_return_format = f"INSTRUCTIONS:\n{critique_instruction}\n\nReturn ONLY the final, improved prompt. No commentary."
        final_instructions = json_return_format if ask_for_json else text_return_format

        # Base template
        refine_template = textwrap.dedent("""
            You are a master prompt critic and editor. Your task is to review and enhance the following DRAFT PROMPT.

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

            {instructions}""" ).strip()

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

    def _finalize_visual_prompt_output(self, scene_prompt, image_context, user_text, mandatory_tokens, run_config, user_negative_prompt=""): # noqa
        ai_negative_prompt = utils._generate_negative_prompt(scene_prompt, run_config, user_negative_prompt=user_negative_prompt)
        parts = [p for p in [user_negative_prompt, ai_negative_prompt] if p and p.strip()]
        final_negative_prompt = ", ".join(parts)
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
                    print(f'\033[91m[PromptCrafter] {error_msg}\033[0m')

        if not any(generated_prompts):
            return ("", "Failed to generate prompts for any of the scenes. Please check the model and logs.", image_context_for_all, base_negative_prompt)

        # --- NEW: Apply target model formatting to each prompt in the schedule ---
        target_model_format = kwargs.get("target_model_format", "Generic")
        if target_model_format != "Generic (SD1.5, SD2.1)":
            print(f"\033[94m[PromptCrafter] Applying '{target_model_format}' formatting to {len(generated_prompts)} scheduled scenes...\033[0m")
            formatted_prompts = []
            for p in generated_prompts:
                if p.startswith("[Error:"):
                    formatted_prompts.append(p)
                else:
                    formatted_prompts.append(self._format_prompt_for_target(p, target_model_format))
            generated_prompts = formatted_prompts
        # --- END NEW BLOCK ---

        schedule_json = utils._create_schedule_from_items(generated_prompts, kwargs.get("max_frames", 240), 0, kwargs.get("interpolate_keyframes", True), kwargs.get("interpolation_frame_interval", 10))
        
        return ("", schedule_json, image_context_for_all, base_negative_prompt)

    def _format_prompt_for_target(self, prompt, target_format):
            prompt_text = str(prompt).strip().rstrip(',')
            
            if target_format == "Generic (SD1.5, SD2.1)":
                # Standard prompt, no changes needed.
                return prompt_text

            elif target_format == "Fooocus":
                # Fooocus uses --style flags
                return f"{prompt_text} --style cinematic-default"
            
            elif target_format == "Stable Diffusion 3":
                # SD3 can use weighting, but a standard prompt is fine.
                # This is more of a placeholder for future, complex SD3 syntax.
                return prompt_text
            
            elif target_format == "Stable Cascade":
                # Stable Cascade uses a standard prompt, no special formatting required.
                return prompt_text

            elif target_format == "FLUX / Qwen / Hunyuan":
                # These models (like FLUX, PixArt, Hunyuan, and Qwen-Image) 
                # often benefit from simple, descriptive prompts + quality tags.
                return f"{prompt_text}, masterpiece, high quality, 8k"

            elif target_format == "Generic Video (Wan, etc.)":
                # Most Wan 2.2 variants (T2V, I2V, S2V, OVI, VACE, Animate) 
                # and others (hidream, chroma) use a standard descriptive prompt.
                # The OVI speech format is handled separately by our speech detector.
                return prompt_text
            
            else: # "Generic" fallback
                return prompt_text

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

# ------------------------------------------------------------------------------------
# PromptCrafter_VisualCreator Node
# ------------------------------------------------------------------------------------
class PromptCrafter_VisualCreator(PromptCrafter_BaseCreator):
    DESCRIPTION = "A unified node to create advanced prompts for images or short videos by analyzing user text and optional reference images."
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pipeline_mode": (["Image", "Video"], {"default": "Image"}),
                "instruction": ("STRING", {"multiline": True, "default": config.DEFAULT_PROMPT_TEXT, "tooltip": "Your primary instruction for the model (e.g., 'Create a cinematic shot of...')."}),
                "subject": ("STRING", {"multiline": True, "default": "", "tooltip": "Optional: The subject, topic, or any additional text to provide context for your instruction."}),
                "model": (api_clients.get_all_models(), {"tooltip": "The language model to use for all analysis and generation. Vision-capable models are required if using images."} ),
                "image_count": ("INT", {"default": 1, "min": 1, "max": 5, "step": 1}),
                # --- Generation Control ---
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff}),
                "max_length_words": ("INT", {"default": 0, "min": 0, "max": 400, "step": 10}),
                "style_override": (style_profiles.get_style_override_options("Image"), {"default": "None"}),
                "critique_strength": (["Subtle", "Normal", "Heavy"], {"default": "Normal"}),
                "deep_think_refinements": ("INT", {"default": 3, "min": 0, "max": 10, "step": 1, "tooltip": "Number of iterative refinement steps for the Deep Think process. 0 disables it."} ),
                "simplify_for_diffusion": ("BOOLEAN", {"default": True}),
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10}),
                "max_retries": ("INT", {"default": 2, "min": 0, "max": 10}),
                "safe_mode": ("BOOLEAN", {"default": True}),
                "debug_mode": ("BOOLEAN", {"default": False}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO", "negative_prompt": "STRING"},
            "optional": {
                "style_tags": ("STRING", {"multiline": False, "default": "", "tooltip": "Combine styles by typing their names, separated by commas (e.g., Cyberpunk, Film Noir). Overrides the dropdown."} ),
                "target_model_format": (["Generic (SD1.5, SD2.1)", "Fooocus", "Stable Diffusion 3", "Stable Cascade", "FLUX / Qwen / Hunyuan", "Generic Video (Wan, etc.)"], {"default": "Generic (SD1.5, SD2.1)", "tooltip": "Format the prompt for a specific model's syntax. OVI speech format is handled automatically."}),
                "generate_schedule": ("BOOLEAN", {"default": False}),
                "max_frames": ("INT", {"default": 240, "min": 1, "max": 99999}),
                "interpolate_keyframes": ("BOOLEAN", {"default": False}),
                "interpolation_frame_interval": ("INT", {"default": 10, "min": 0, "max": 100}),
            },
        }

    MAX_IMAGES = 5
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING") + ("IMAGE",) * MAX_IMAGES
    RETURN_NAMES = ("prompt", "schedule", "image_context", "negative_prompt", "model_out", "seed_out") + tuple(f"reference_image_{i}" for i in range(1, MAX_IMAGES + 1))
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter/Creator"

    def execute(self, instruction, subject, model, negative_prompt="", **kwargs):
        try:
            # Combine instruction and subject to form the user_text
            user_text = instruction
            if subject and subject.strip():
                user_text = f"SUBJECT:\n{subject}\n\nINSTRUCTION:\n{instruction}"

            pipeline_mode = kwargs.get("pipeline_mode", "Image")
            target_model_format = kwargs.get("target_model_format", "Generic")
            
            images_with_weights = self._collect_images_with_weights(**kwargs) # noqa
            initial_run_config = self._setup_config(pipeline_mode, user_text, model, images_with_weights=images_with_weights, **kwargs)
            
            if self._is_speech_prompt_request(user_text, initial_run_config):
                return self._handle_speech_prompt_request(user_text, images_with_weights, initial_run_config)
            
            # <<< --- ADD THIS NEW BLOCK --- >>>
            # Check for the special lyrics-to-prompt format
            if self._is_lyrics_to_prompt_request(user_text, initial_run_config):
                return self._handle_lyrics_to_prompt_request(user_text, images_with_weights, initial_run_config)
            # <<< --- END OF NEW BLOCK --- >>>
            
            error, new_user_text = self._handle_creative_intent(pipeline_mode, user_text, images_with_weights, initial_run_config)
            if error: return (error,) + (None,) * (len(self.RETURN_TYPES) - 1)
            final_user_text = new_user_text or user_text

            run_config = self._setup_config(pipeline_mode, final_user_text, model, images_with_weights=images_with_weights, **kwargs)

            passthrough_images = [img for img, _ in images_with_weights]
            passthrough_images.extend([None] * (self.MAX_IMAGES - len(passthrough_images)))

            if kwargs.get("generate_schedule"):
                prompt, schedule, image_context, neg_prompt = self._handle_scheduled_mode(pipeline_mode, final_user_text, images_with_weights, run_config, **kwargs)
                prompt = self._format_prompt_for_target(prompt, target_model_format)
                return (prompt, schedule, image_context, neg_prompt, model, str(run_config.seed)) + tuple(passthrough_images)
            else:
                pipeline_kwargs = {k: v for k, v in kwargs.items() if k not in ['prompt', 'extra_pnginfo']}

                prompt, image_context, negative_prompt_out = self._generate_visual_prompt_pipeline(
                    mode=pipeline_mode, user_text=final_user_text, images_with_weights=images_with_weights, run_config=run_config, negative_prompt=negative_prompt, **pipeline_kwargs
                )
                prompt = self._format_prompt_for_target(prompt, target_model_format)
                return (prompt, "", image_context, negative_prompt_out, model, str(run_config.seed)) + tuple(passthrough_images)
        except Exception as e:
            return self._handle_creator_exception(e)

# ------------------------------------------------------------------------------------
# PromptCrafter_LyricsCreator Node
# ------------------------------------------------------------------------------------
class PromptCrafter_LyricsCreator(PromptCrafter_BaseCreator):
    DESCRIPTION = get_node_description("PromptCrafter_LyricsCreator")
    @classmethod
    def INPUT_TYPES(cls):
        types = copy.deepcopy(PromptCrafter_VisualCreator.INPUT_TYPES()) # Base off the new visual creator
        types["required"]["temperature"] = ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01})
        # // AI ENHANCEMENT: Changed default max_length_words to 40, aligning with the goal of shorter prompts.
        types["required"]["max_length_words"] = ("INT", {"default": 40, "min": 0, "max": 400, "step": 10})
        types["required"]["style_override"] = (style_profiles.get_style_override_options("Lyrics"), {"default": "None"})
        types["required"]["simplify_for_diffusion"] = ("BOOLEAN", {"default": False})
        
        # Remove inputs not relevant to LyricsCreator
        if "pipeline_mode" in types["required"]: del types["required"]["pipeline_mode"]
        if "target_model_format" in types["optional"]: del types["optional"]["target_model_format"]

        types["optional"]['signal'] = ('*', {})

        types["optional"].update({
            "style_tags": ("STRING", {"multiline": False, "default": "", "tooltip": "Combine styles by typing their names, separated by commas (e.g., Cyberpunk, Film Noir). Overrides the dropdown."} ),
            "audio_folder_path": ("STRING", {"multiline": False, "default": "input/audio"}),
            "audio_file": ("STRING", {"multiline": False, "default": "<none>"}),
            "lyrics_folder_path": ("STRING", {"multiline": False, "default": "input/lyrics"}),
            "lyrics_file": ("STRING", {"multiline": False, "default": "<none>"}),
            "use_audio_alignment": ("BOOLEAN", {"default": True}),
            "song_length_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 3600.0, "step": 0.1}),
            "fps": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.5}),
            "scene_splitting_mode": (["Structural Tag", "Fixed Duration", "Frame Length"], {"default": "Structural Tag", "tooltip": "How to split lyrics into scenes. 'Structural Tag' uses AI to find sections. 'Fixed Duration' and 'Frame Length' use fixed time chunks."}),
            "max_scene_duration_seconds": ("FLOAT", {"default": 5.0, "min": 0.0, "max": 60.0, "step": 0.1, "tooltip": "Max scene length in seconds for 'Fixed Duration' mode."}),
            "max_scene_frames": ("INT", {"default": 120, "min": 0, "max": 4096, "step": 1, "tooltip": "Max scene length in frames for 'Frame Length' mode."}),
            "whisper_model_size": (["tiny", "base", "small", "medium", "large-v3"], {"default": "large-v3", "tooltip": "The size of the Whisper model to use for transcription. Larger models are more accurate but slower and use more VRAM."} ),
            "whisper_language": (["auto-detect", "en", "es", "fr", "de", "it", "pt", "is", "ru", "ja", "ko", "zh"], {"default": "auto-detect", "tooltip": "Language of the audio. 'is' for Icelandic. Providing this greatly improves accuracy."}),
            "whisper_engine": (["faster-whisper", "insanely-fast-whisper"], {"default": "faster-whisper", "tooltip": "Default: faster-whisper. Alternative: insanely-fast-whisper (optimized for batch processing)."} ),
            "target_model_format": (["Generic (SD1.5, SD2.1)", "Fooocus", "Stable Diffusion 3", "Stable Cascade", "FLUX / Qwen / Hunyuan", "Generic Video (Wan, etc.)"], {"default": "Generic Video (Wan, etc.)", "tooltip": "Format the prompt for a specific model's syntax. OVI speech format is handled automatically."}),
            # VRGDG Music Video Prompt Creator inputs
            "use_vrg_prompt_builder": ("BOOLEAN", {"default": False, "tooltip": "If True, use the detailed music video prompt builder inputs below, overriding the main user_text input."}),
            "automate_vrg_variables": ("BOOLEAN", {"default": False, "tooltip": "If True, use an LLM to automatically fill the VRGDG variables based on the lyrics."}),
            "character_description": ("STRING", {"multiline": True, "default": "The Women."}),
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
        return types
    
    STATIC_RETURN_TYPES = (
        "STRING",    # prompt
        "STRING",    # schedule
        "STRING",    # image_context
        "STRING",    # negative_prompt
        "STRING",    # clean_lyrics_txt
        "STRING",    # lyrics_srt
        "STRING",    # model_out
        "STRING",    # seed_out
        "DICT",      # audio_meta
        "IMAGE",     # spectrogram_preview
        "*",         # signal
        "STRING",    # auto_character
        "STRING",    # auto_theme
        "STRING",    # auto_environment
        "STRING",    # auto_lighting
        "STRING",    # auto_interaction
        "STRING",    # auto_expression
        "STRING",    # auto_shots
        "STRING",    # auto_outfit
        "STRING",    # auto_visibility
    )
    
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
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter/Creator"

    def _build_vrg_prompt_instructions(self, pipe_separated_lyrics, num_fragments, character_description, song_theme_style, word_count_min, word_count_max, list_handling_mode, environment, lighting, camera_motion, physical_interaction, facial_expression, shots, outfit_rules, character_visibility):
        # Generate list handling instructions based on mode
        if "Strict Cycle" in list_handling_mode:
            list_instructions = """8. List Handling:
- If multiple options are provided for any of the below categories, treat them as a list.
- Cycle through list items across prompts in order.
- Do not repeat an item until all others have been used.
- Once all have been used, restart the cycle.
- Each prompt must use exactly one item from each category."""
        
        elif "Reference Guide" in list_handling_mode:
            list_instructions = """8. List Handling:
- The categories below are INSPIRATION and REFERENCE GUIDES.
- Use them as starting points to create variations and similar ideas.
- Feel free to combine elements or create new options in the same style.
- Prioritize what works best for each lyric fragment and the overall narrative flow.
- Maintain variety across prompts - avoid repeating the exact same choices.
- Stay true to the overall aesthetic and mood of the provided examples."""
        
        elif "Random Selection" in list_handling_mode:
            list_instructions = """8. List Handling:
- If multiple options are provided for any category, select randomly from the list.
- Items can repeat across prompts - there is no cycling requirement.
- Prioritize what works best for each lyric fragment and the overall narrative flow.
- Ensure overall variety across the full sequence of prompts.
- Each prompt should feel fresh even if some elements repeat."""
        
        else:  # Free Interpretation
            list_instructions = """8. List Handling:
- The categories below are LOOSE GUIDELINES ONLY.
- You may use them as-is, combine them, modify them, or create entirely new options.
- Prioritize what works best for each lyric fragment and the overall narrative flow.
- Feel free to ignore any category if it doesn't serve the visual storytelling.
- Creativity and coherence are more important than strict adherence to the lists."""
        
        full_string = f"""
AI Music Video Prompt Creator

User Input:
Character: {character_description.strip()}
Style/Theme: {song_theme_style.strip()}
Lyrics: {pipe_separated_lyrics.strip()}

*** CRITICAL INSTRUCTION - PRIORITY OVERRIDE ***
The following general style/character/environment keywords (e.g., 'Alien in alien skin', 'dark alien science laboratory') must be treated ONLY as a background style guide. 

The most important element of the final prompt MUST be the UNIQUE action, emotion, or narrative point described in the specific lyric segment. Do not allow the general keywords to overwhelm the unique lyric-driven action. Your final prompt should focus the camera and attention on the unique event described by the lyric.

Core Rules:

1. Lyric-Driven Prompts (MOST IMPORTANT):
   - The lyrics provided above are pipe-separated (|).
   - There are exaclty {num_fragments} lyric fragments and each one corresponds to ONE video prompt.
   - FIRST, read through ALL the lyrics to understand the full narrative arc and emotional journey of the song.
   - Understand the overall story, themes, and progression before creating any individual prompts.
   - Then, create one prompt per lyric fragment that reflects both:
     a) The specific meaning/mood of THAT lyric fragment
     b) How it fits into the larger narrative and aesthetic of the FULL song
   - The NUMBER of prompts MUST MATCH the NUMBER of lyric fragments exactly this will always be {num_fragments}.
   - Each prompt's visual content should be INSPIRED BY and REFLECT the meaning, mood, and imagery of its corresponding lyric fragment.
   - The visuals should enhance and complement what the lyric is expressing.

2. Structure (this order must always be followed):
   [Shot Type] -> [Character + Outfit] -> [Physical Interaction] -> [Environment] -> [Lighting] -> [Camera Motion] -> [Cinematic Detail] -> [Facial Expression]

3. Continuity Between Prompts:
   - Each prompt should flow naturally from the previous one.
   - Connect the ending visual detail of one prompt to the beginning of the next.
   - Create a cohesive visual narrative that follows the lyrical journey.

4. Visual Requirements:
   Every prompt must include:
   - Character + Outfit
   - Physical Interaction
   - Environment
   - Lighting
   - Camera Motion
   - Facial Expression

5. Language Rules:
   - Clear, direct, natural wording only.
   - No abstract or poetic terms, no sound descriptions, no static shots.
   - Do not use quotation marks, colons, semicolons, or special characters.
   - The ONLY allowed special character is the "|" PIPE separator BETWEEN prompts.
   - Never use "|" inside a prompt itself.

6. Word Count:
   - Every prompt must be between {word_count_min} and {word_count_max} words.

7. Endings:
   - End each prompt on a strong visual detail.
   - Never end with mood labels or trailing phrases like "captivated gaze," "vulnerable," or "conveying emotion."
   - Mood must be shown through visuals, not named.

{list_instructions}

Environment: {environment.strip()}
Lighting: {lighting.strip()}
Camera Motion/Angles: {camera_motion.strip()}
Physical Interaction: {physical_interaction.strip()}
Facial Expression: {facial_expression.strip()}
Shots: {shots.strip()}
Outfit Rules: {outfit_rules.strip()}
Character Visibility: {character_visibility.strip()}

Prompt Structure (for every lyric fragment, {word_count_min}–{word_count_max} words):

-Start with the Shot Type
-Then add in the Character and Outfit if any
-Then add their Physical Interaction
-Then add the Environment
-Then add the Lighting
-Then add the Camera Motion
-Then provide the Cinematic Detail
-Then mention the Facial Expression / Emotion

Formatting Rules:
- Input lyrics are split by "|"
- Output prompts MUST be joined with "|" (one prompt per lyric)
- Do NOT insert "|" anywhere inside a prompt
- Use simple everyday words.
- There should be exaclly {num_fragments} prompts that are PIPE separated. 
- Remember that the prompts should be lyric driven while taking into account user input.

Example prompt using this Structure:
Close up of a woman in a white dress as she touches a broad jungle leaf, in a vibrant jungle under a sun-dappled canopy, slow tracking reveals textured leaves. Intense raw emotion

"""
        return full_string.strip()

    def execute(self, instruction, subject, model, **kwargs):
        try:
            # Combine instruction and subject to form the user_text
            user_text = instruction
            if subject and subject.strip():
                user_text = f"SUBJECT:\n{subject}\n\nINSTRUCTION:\n{instruction}"
            
            images_with_weights = self._collect_images_with_weights(**kwargs)

            audio_file = kwargs.get("audio_file", "<none>")
            lyrics_file = kwargs.get("lyrics_file", "<none>")
            audio_path = utils._get_audio_path(kwargs.get("audio_folder_path"), audio_file)

            song_length_seconds = kwargs.get("song_length_seconds", 0.0)
            if song_length_seconds <= 0 and audio_path:
                try:
                    import librosa
                    print("[PromptCrafter] Song length not provided, calculating from audio file...")
                    audio_y, audio_sr = librosa.load(audio_path)
                    duration = librosa.get_duration(y=audio_y, sr=audio_sr)
                    kwargs["song_length_seconds"] = duration
                    print(f"[PromptCrafter] Calculated song length: {duration:.2f} seconds.")
                except Exception as e:
                    print(f"[PromptCrafter] Warning: Could not calculate song length from audio: {e}")

            user_lyrics, _, _ = utils._get_lyrics_from_input(user_text, kwargs.get("lyrics_folder_path"), kwargs.get("lyrics_file", "<none>"), kwargs.get("debug_mode", False))
            whisper_transcript, initial_timed_segments, _ = self._transcribe_audio(audio_path, kwargs.get("whisper_model_size", "large-v3"), kwargs.get("whisper_engine", "faster-whisper"), kwargs.get("whisper_language", "auto-detect"))

            lyrics_for_analysis = user_lyrics if user_lyrics else (whisper_transcript or "")
            run_config = self._setup_config("Lyrics", lyrics_for_analysis, model, images_with_weights=images_with_weights, **kwargs)

            final_lyrics_text, final_timed_segments, spectrogram_preview_pil = self._align_and_correct_lyrics(
                whisper_transcript, initial_timed_segments, user_lyrics, audio_path, run_config
            )

            spectrogram_preview = None
            if spectrogram_preview_pil:
                spectrogram_preview = utils.pil2tensor(spectrogram_preview_pil)

            use_vrg_prompt_builder = kwargs.get("use_vrg_prompt_builder", False)

            # --- NEW: Automated VRGDG Variable Filling ---
            auto_vrg_vars = {
                "auto_character": "", "auto_theme": "", "auto_environment": "",
                "auto_lighting": "", "auto_interaction": "", "auto_expression": "",
                "auto_shots": "", "auto_outfit": "", "auto_visibility": ""
            }
            automate_vrg_variables = kwargs.get("automate_vrg_variables", False)

            # Keep a local copy of vrg_kwargs to modify
            vrg_kwargs = {k: v for k, v in kwargs.items() if k in ['character_description', 'song_theme_style', 'word_count_min', 'word_count_max', 'list_handling_mode', 'environment', 'lighting', 'camera_motion', 'physical_interaction', 'facial_expression', 'shots', 'outfit_rules', 'character_visibility']}

            if use_vrg_prompt_builder and automate_vrg_variables and final_lyrics_text:
                print("\033[94m[PromptCrafter] Automating VRGDG variables from lyrics and/or images...\033[0m")

                # Get image descriptions if available
                image_context, _ = self._describe_images(images_with_weights, run_config)
                if "No reference images" in image_context:
                    image_context = "" # Clear if no images are actually present

                image_context_section = ""
                if image_context:
                    image_context_section = f'''
                    REFERENCE IMAGE DESCRIPTIONS:
                    ---
                    {image_context}
                    ---
                    '''

                analysis_prompt = textwrap.dedent(f'''
                    You are a world-class music video creative director. Analyze the following song lyrics and optional reference image descriptions to generate a creative concept for a music video.

                    {image_context_section}

                    LYRICS:
                    ---
                    {final_lyrics_text}
                    ---

                    Based on the lyrics AND any reference images provided, provide a detailed concept by filling out the following fields in a JSON object.
                    If reference images are provided, the "character_description" and "outfit_rules" MUST be based on them.

                    - "character_description": (string) A brief, evocative description of the main character.
                    - "song_theme_style": (string) A comma-separated list of 8-10 keywords describing the overall theme, style, and mood.
                    - "environment": (string) A comma-separated list of 8 distinct, evocative environments or settings that fit the song's narrative.
                    - "lighting": (string) A comma-separated list of 8 specific lighting styles that match the environments and mood.
                    - "physical_interaction": (string) A comma-separated list of 8 physical actions the character might perform.
                    - "facial_expression": (string) A general description of the character's emotional state or facial expressions.
                    - "shots": (string) A comma-separated list of 8 standard camera shots (e.g., "Close up, medium, wide angle, over the shoulder").
                    - "outfit_rules": (string) A description of the character's primary outfit.
                    - "character_visibility": (string) A comma-separated list of 8 ways the character might be framed or obscured.

                    Return ONLY the raw JSON object and nothing else.
                ''')

                ok, result_json = api_clients._reason_with_model(
                    run_config.model,
                    analysis_prompt,
                    use_chat_api=run_config.use_chat_api,
                    temperature=0.4, # Slightly more creative for this task
                    seed=run_config.seed,
                    debug_mode=run_config.debug_mode,
                    debug_title="VRGDG Variable Automation",
                    timeout=run_config.timeout
                )

                if ok and isinstance(result_json, dict):
                    print("\u001b[92m[PromptCrafter] Successfully generated automated VRGDG variables.\u001b[0m")
                    
                    # Update the kwargs with the new values, then populate the output variables
                    auto_vrg_vars["auto_character"] = result_json.get("character_description", "").strip()
                    if auto_vrg_vars["auto_character"]: vrg_kwargs["character_description"] = auto_vrg_vars["auto_character"]

                    auto_vrg_vars["auto_theme"] = result_json.get("song_theme_style", "").strip()
                    if auto_vrg_vars["auto_theme"]: vrg_kwargs["song_theme_style"] = auto_vrg_vars["auto_theme"]

                    auto_vrg_vars["auto_environment"] = result_json.get("environment", "").strip()
                    if auto_vrg_vars["auto_environment"]: vrg_kwargs["environment"] = auto_vrg_vars["auto_environment"]
                    
                    auto_vrg_vars["auto_lighting"] = result_json.get("lighting", "").strip()
                    if auto_vrg_vars["auto_lighting"]: vrg_kwargs["lighting"] = auto_vrg_vars["auto_lighting"]

                    auto_vrg_vars["auto_interaction"] = result_json.get("physical_interaction", "").strip()
                    if auto_vrg_vars["auto_interaction"]: vrg_kwargs["physical_interaction"] = auto_vrg_vars["auto_interaction"]

                    auto_vrg_vars["auto_expression"] = result_json.get("facial_expression", "").strip()
                    if auto_vrg_vars["auto_expression"]: vrg_kwargs["facial_expression"] = auto_vrg_vars["auto_expression"]

                    auto_vrg_vars["auto_shots"] = result_json.get("shots", "").strip()
                    if auto_vrg_vars["auto_shots"]: vrg_kwargs["shots"] = auto_vrg_vars["auto_shots"]

                    auto_vrg_vars["auto_outfit"] = result_json.get("outfit_rules", "").strip()
                    if auto_vrg_vars["auto_outfit"]: vrg_kwargs["outfit_rules"] = auto_vrg_vars["auto_outfit"]
                    
                    auto_vrg_vars["auto_visibility"] = result_json.get("character_visibility", "").strip()
                    if auto_vrg_vars["auto_visibility"]: vrg_kwargs["character_visibility"] = auto_vrg_vars["auto_visibility"]

                else:
                    print(f"\u001b[93m[PromptCrafter] Warning: Failed to generate automated VRGDG variables. Using manual inputs. Error: {result_json}\u001b[0m")
            # --- END: Automated VRGDG Variable Filling ---

            if use_vrg_prompt_builder:
                print("\033[94m[PromptCrafter] VRGDG Music Video Prompt Builder enabled. Constructing detailed instructions...\033[0m")
                
                lyric_fragments = []
                if final_timed_segments:
                    lyric_fragments = [seg[2] for seg in final_timed_segments]
                elif final_lyrics_text:
                    scenes = self._group_lyrics_into_scenes(final_lyrics_text, run_config)
                    if scenes:
                        lyric_fragments = scenes
                    else:
                        lyric_fragments = [line for line in final_lyrics_text.splitlines() if line.strip()]

                if not lyric_fragments:
                    return self._handle_creator_exception(Exception("Could not extract any lyric fragments to use with the VRGDG Prompt Builder."))

                pipe_separated_lyrics = " | ".join(lyric_fragments)
                num_fragments = len(lyric_fragments)

                vrg_kwargs = {k: v for k, v in kwargs.items() if k in ['character_description', 'song_theme_style', 'word_count_min', 'word_count_max', 'list_handling_mode', 'environment', 'lighting', 'camera_motion', 'physical_interaction', 'facial_expression', 'shots', 'outfit_rules', 'character_visibility']}
                
                instructions_for_generation = self._build_vrg_prompt_instructions(pipe_separated_lyrics, num_fragments, **vrg_kwargs)
                
                # Use the specialized handler for this type of prompt
                (prompt, _, image_context, negative_prompt, model_out, seed_out, *_) = self._handle_lyrics_to_prompt_request(instructions_for_generation, images_with_weights, run_config)
                schedule = ""

            else:
                prompt, schedule, image_context, negative_prompt = self._generate_prompts_from_lyrics(
                    lyrics=final_lyrics_text,
                    timed_segments=final_timed_segments,
                    images_with_weights=images_with_weights,
                    user_instructions=user_text,
                    config=run_config,
                    negative_prompt=kwargs.get("negative_prompt", ""),
                    **kwargs
                )

            passthrough_images = [img for img, _ in images_with_weights]
            passthrough_images.extend([None] * (self.MAX_IMAGES - len(passthrough_images)))
            
            final_srt_string = ""
            if final_timed_segments:
                def to_srt_time(seconds):
                    millis = round((seconds - int(seconds)) * 1000)
                    seconds_int = int(seconds)
                    minutes = seconds_int // 60
                    seconds_int %= 60
                    hours = minutes // 60
                    minutes %= 60
                    return f"{hours:02d}:{minutes:02d}:{seconds_int:02d},{millis:03d}"
                
                srt_lines = []
                for i, (start, end, text) in enumerate(final_timed_segments):
                    srt_lines.append(str(i + 1))
                    srt_lines.append(f"{to_srt_time(start)} --> {to_srt_time(end)}")
                    srt_lines.append(text)
                    srt_lines.append("")
                final_srt_string = "\n".join(srt_lines)

            audio_meta = {
                "timed_segments": final_timed_segments,
                "fps": kwargs.get("fps", 16.0),
                "scene_splitting_mode": kwargs.get("scene_splitting_mode", "Structural Tag"),
                "max_scene_frames": kwargs.get("max_scene_frames", 120),
                "max_scene_duration_seconds": kwargs.get("max_scene_duration_seconds", 5.0)
            }

            return (prompt, schedule, image_context, negative_prompt, final_lyrics_text, final_srt_string, model, str(run_config.seed), audio_meta, spectrogram_preview) + tuple(passthrough_images) + (kwargs.get('signal'),) + (auto_vrg_vars["auto_character"], auto_vrg_vars["auto_theme"], auto_vrg_vars["auto_environment"], auto_vrg_vars["auto_lighting"], auto_vrg_vars["auto_interaction"], auto_vrg_vars["auto_expression"], auto_vrg_vars["auto_shots"], auto_vrg_vars["auto_outfit"], auto_vrg_vars["auto_visibility"])

        except Exception as e:
            return self._handle_creator_exception(e)

    def _transcribe_audio(self, audio_path, model_size="large-v3", engine="faster-whisper", language="auto-detect"):
        if not audio_path: return None, None, None
        
        print(f"\033[94m[PromptCrafter] Transcribing audio at {audio_path} using {engine}...")
        # If language is 'auto-detect', pass None to the library, which triggers its auto-detection.
        lang_arg = language if language != "auto-detect" else None

        try:
            if engine == "insanely-fast-whisper":
                try:
                    from transformers import pipeline
                    import torch

                    print(f"[PromptCrafter] Loading whisper model 'openai/whisper-{model_size}' with insanely-fast-whisper pipeline...")
                    device = "cuda:0" if torch.cuda.is_available() else "cpu"
                    torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32

                    pipe = pipeline(
                        "automatic-speech-recognition",
                        model=f"openai/whisper-{model_size}",
                        torch_dtype=torch_dtype,
                        device=device,
                    )

                    generate_kwargs = {"language": lang_arg} if lang_arg else {}
                    outputs = pipe(audio_path, chunk_length_s=30, batch_size=24, return_timestamps=True, generate_kwargs=generate_kwargs)
                    lyrics_text = outputs["text"]

                    timed_segments = []
                    if "chunks" in outputs:
                        for chunk in outputs["chunks"]:
                            start, end = chunk["timestamp"]
                            timed_segments.append((start, end, chunk["text"].strip()))
                    
                    print(f"\033[92m[PromptCrafter] Transcription complete with insanely-fast-whisper.\033[0m")
                    lyrics_meta = f"Transcribed from {os.path.basename(audio_path)} (insanely-fast-whisper)"
                    return lyrics_text, timed_segments, lyrics_meta

                except Exception as e:
                    # --- FIX: Graceful Fallback to faster-whisper on any error ---
                    print(f"\033[93m[PromptCrafter] Warning: 'insanely-fast-whisper' failed with error: {e}\033[0m")
                    print(f"\033[94m[PromptCrafter] Automatically falling back to 'faster-whisper' engine.\033[0m")
                    # Explicitly call the faster-whisper logic from here.
                    return self._transcribe_with_faster_whisper(audio_path, model_size, language)

            # Default to faster-whisper if it was selected or if the above failed
            return self._transcribe_with_faster_whisper(audio_path, model_size, language)

        except Exception as e:
            print(f"\033[91m[PromptCrafter] Error during audio transcription: {e}\033[0m")
            return f"[Error during transcription: {e}]", [], None

    def _transcribe_with_faster_whisper(self, audio_path, model_size, language):
        """Handles transcription using the faster-whisper engine."""
        from faster_whisper import WhisperModel
        import torch

        lang_arg = language if language != "auto-detect" else None
        device = "cuda" if torch.cuda.is_available() else "cpu"
        compute_type = "float16" if torch.cuda.is_available() else "int8"

        print(f"[PromptCrafter] Loading whisper model '{model_size}' on device '{device}' with compute type '{compute_type}'...")
        model_whisper = WhisperModel(model_size, device=device, compute_type=compute_type)

        print(f"[PromptCrafter] Transcribing with language: {language}")
        segments_generator, info = model_whisper.transcribe(audio_path, word_timestamps=True, language=lang_arg, condition_on_previous_text=False)

        segments = list(segments_generator)
        lyrics_text = " ".join([s.text.strip() for s in segments]).strip()
        timed_segments = [(s.start, s.end, s.text.strip()) for s in segments]

        print(f"\033[92m[PromptCrafter] Transcription complete. Language: {info.language}, Duration: {info.duration}s\033[0m")
        lyrics_meta = f"Transcribed from {os.path.basename(audio_path)} ({info.language})\n"
        return lyrics_text, timed_segments, lyrics_meta

    def _align_and_correct_lyrics(self, whisper_transcript, initial_timed_segments, user_lyrics, audio_path, config):
        """
        The core logic to align user-provided lyrics with Whisper's timing.
        Returns a tuple of (lyrics_text, timed_segments, spectrogram_image).
        """
        spectrogram_img = None  # Initialize to None

        # Case 1: No timing data available. Use user lyrics and AI scene splitting.
        if not initial_timed_segments:
            print("\033[94m[PromptCrafter] No timing data available. Using AI to segment lyrics.\033[0m")
            # No audio, so no spectrogram can be generated.
            return user_lyrics, None, None

        # If we have audio, we can generate a spectrogram regardless of other conditions.
        if audio_path:
            spectrogram_img = utils.audio_to_spectrogram(audio_path)
            if isinstance(spectrogram_img, str):
                print(f"\033[91m[PromptCrafter] Error: Spectrogram generation failed. Reason: {spectrogram_img}\033[0m")
                spectrogram_img = None # Ensure it's None on failure
            else:
                print(f"\033[94m[PromptCrafter] Spectrogram generated successfully. Type: {type(spectrogram_img)}\033[0m")

        # Case 2: Timing data is available, but no separate user lyrics are provided. Trust Whisper.
        if not user_lyrics or user_lyrics.strip() == whisper_transcript.strip():
            print("\033[94m[PromptCrafter] Using Whisper transcript and timing directly.\033[0m")
            return whisper_transcript, initial_timed_segments, spectrogram_img

        # Case 3: Both timing and user lyrics are available. Attempt VLM alignment.
        # This requires a valid spectrogram image.
        if not spectrogram_img:
            print(f"\033[93m[PromptCrafter] Warning: Cannot attempt VLM alignment without a valid spectrogram. Falling back to Whisper transcript.\033[0m")
            return whisper_transcript, initial_timed_segments, spectrogram_img

        print("\033[94m[PromptCrafter] Aligning ground truth lyrics with Whisper timing using VLM...\033[0m")
        
        alignment_prompt = textwrap.dedent(f"""
            You are an expert audio-lyric alignment specialist. Your task is to correct an inaccurate ASR transcript by using a provided "Ground Truth" lyric sheet as a reference, guided by an audio spectrogram.
            - **ASR Transcript (Potentially Inaccurate):** This is the raw output from the speech recognition. It has good timing but may have wrong words.
            - **Ground Truth Lyrics (Accurate Content):** This is the correct text of the song.
            - **Spectrogram:** This is the visual representation of the audio.
            **Your Goal:** Produce a corrected, full-text transcript that has the structure and flow of the ASR transcript but with the accurate words from the Ground Truth Lyrics. Preserve structural tags like `[Chorus]` or `[Verse]` from the ASR transcript.
            ---
            **ASR Transcript (for structure and timing):**
            ```
            {whisper_transcript}
            ```
            ---
            **Ground Truth Lyrics (for correct words):**
            ```
            {user_lyrics}
            ```
            ---
            Return ONLY the final, 100% corrected full-text transcript.
        """).strip()

        # No need for a separate debug print, the main query_model_auto will handle it
        # print(f"\033[94m[PromptCrafter] VLM Alignment Prompt:\n{alignment_prompt}\033[0m")
        ok, corrected_lyrics = api_clients.query_model_auto(config.model, alignment_prompt, images=[spectrogram_img], prefer_chat=True, temperature=0.0, seed=config.seed, debug_mode=config.debug_mode, timeout=config.timeout, debug_title="Audio-Lyric Alignment")
        # print(f"\033[94m[PromptCrafter] VLM Alignment Result: ok={ok}, corrected_lyrics='{corrected_lyrics[:200]}...'\033[0m")

        # --- FALLBACK LOGIC ---
        if not ok or not corrected_lyrics.strip():
            print(f"\033[93m[PromptCrafter] Warning: VLM alignment failed (Error: {corrected_lyrics}). Falling back to the raw Whisper transcript and its {len(initial_timed_segments)} timed segments.\033[0m")
            return whisper_transcript, initial_timed_segments, spectrogram_img

        print("\033[92m[PromptCrafter] VLM alignment complete. Re-segmenting corrected lyrics...\033[0m")
        final_segments = self._resegment_lyrics_with_vlm(corrected_lyrics, initial_timed_segments, config)
        
        # --- FINAL SANITY CHECK ---
        if not final_segments:
            print(f"\033[93m[PromptCrafter] Warning: VLM re-segmentation failed. Falling back to raw Whisper transcript and its {len(initial_timed_segments)} timed segments.\033[0m")
            return whisper_transcript, initial_timed_segments, spectrogram_img

        return corrected_lyrics, final_segments, spectrogram_img

    def _analyze_audio_mood(self, audio_path, lyrics_text, config):
        if not audio_path:
            return ""
        try:
            import librosa
            import numpy as np
            print("\033[94m[PromptCrafter] Analyzing audio and lyrics for mood...")
            y, sr = librosa.load(audio_path)
            tempo_values, _ = librosa.beat.beat_track(y=y, sr=sr)
            
            # Handle cases where tempo is an array or a single value
            tempo = np.mean(tempo_values) if isinstance(tempo_values, np.ndarray) and tempo_values.size > 0 else tempo_values
            
            # Ensure tempo is a scalar float before formatting
            audio_summary = f"The song has a tempo of approximately {float(tempo):.0f} BPM." # noqa
            
            mood_prompt = f"""Analyze the provided musical features and lyrics to describe the song's overall mood and genre in a few keywords.
---
AUDIO FEATURES: {audio_summary}
---
LYRICS (for emotional context):
{lyrics_text[:1000]}... 
---
            
            Return only the keywords. Example: 'energetic, rock, upbeat' or 'somber, orchestral, melancholic'.
            """
            ok, mood_keywords = api_clients.query_model_auto(config.model, mood_prompt, prefer_chat=True, temperature=0.1, seed=config.seed, debug_mode=config.debug_mode, debug_title="Audio Mood Analysis")
            
            if ok and mood_keywords:
                print(f"\033[92m[PromptCrafter] Detected Audio Mood: {mood_keywords}\033[0m")
                return mood_keywords.strip()
            return ""
            
        except ImportError:
            print("\033[91m[PromptCrafter] Error: 'librosa' is not installed, which is required for audio mood analysis. Please run 'pip install librosa'.\033[0m")
            return ""
        except Exception as e:
            print(f"\033[91m[PromptCrafter] Could not analyze audio mood: {e}\033[0m")
            return ""

    def _generate_prompts_from_lyrics(self, lyrics, timed_segments, images_with_weights, user_instructions, config, negative_prompt, **kwargs):
            if not lyrics or not lyrics.strip(): return "No lyrics provided.", "", "No reference images provided.", ""
            
            audio_path = utils._get_audio_path(kwargs.get("audio_folder_path"), kwargs.get("audio_file", "<none>"))
            
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future_mood = executor.submit(self._analyze_audio_mood, audio_path, lyrics, config)
                future_context = executor.submit(self._prepare_lyrics_generation_context, user_instructions, images_with_weights, lyrics, config)

                mood_keywords = future_mood.result()
                image_context, mandatory_tokens, style_inspiration_section, instructions_section, context_section = future_context.result()

            if lyrics.startswith("[Error"):
                return f"Failed to process lyrics input: {lyrics}", "", "No reference images provided.", ""

            theme_ok, global_theme_or_err = self._generate_storyboard_global_theme(lyrics, instructions_section, context_section, image_context, config, mood_keywords=mood_keywords)
            if not theme_ok: return global_theme_or_err, "", image_context, ""

            has_real_timed_segments = timed_segments is not None
            
            # --- START FIX ---
            # Read ALL scheduling parameters directly from kwargs
            scene_splitting_mode = kwargs.get('scene_splitting_mode', 'Structural Tag')
            max_scene_frames = kwargs.get('max_scene_frames', 120)
            max_scene_duration_seconds = kwargs.get('max_scene_duration_seconds', 5.0)
            interpolate_keyframes = kwargs.get('interpolate_keyframes', False)
            interpolation_frame_interval = kwargs.get('interpolation_frame_interval', 0)
            fps = kwargs.get('fps', 16.0) 
            # --- END FIX ---

            if timed_segments:
                # fps = kwargs.get('fps', 16.0) # Moved up

                if scene_splitting_mode == 'Fixed Duration':
                    # max_duration_secs = kwargs.get('max_scene_duration_seconds', 5.0) # Moved up
                    max_duration_secs = max_scene_duration_seconds
                    min_duration_secs = max_duration_secs * 0.8
                elif scene_splitting_mode == 'Frame Length':
                    # max_scene_frames = kwargs.get('max_scene_frames', 120) # Moved up
                    max_duration_secs = max_scene_frames / fps
                    min_duration_secs = max_duration_secs * 0.8
                else: # Structural Tag
                    # max_duration_secs = kwargs.get('max_scene_duration_seconds', 5.0) # Moved up
                    max_duration_secs = max_scene_duration_seconds
                    min_duration_secs = max_duration_secs * 0.8

                print(f"\033[94m[PromptCrafter] Using '{scene_splitting_mode}' mode. Processing timed segments into scenes with min duration: {min_duration_secs:.2f}s, max duration: {max_duration_secs:.2f}s...\033[0m")

                timed_segments = utils._process_timed_segments(timed_segments, 0, min_duration_secs, max_duration_secs)

            # --- START FIX ---
            # Pass **kwargs all the way through
            storyboard_prompts, processed_segments = self._process_lyrics_storyboard(lyrics, timed_segments, global_theme_or_err, mandatory_tokens, style_inspiration_section, config, **kwargs)
            # --- END FIX ---
            
            if not storyboard_prompts or (isinstance(storyboard_prompts, str) and storyboard_prompts.startswith("Could not generate")): # noqa
                return (storyboard_prompts or "Failed to generate storyboard prompts."), "", image_context, "" # noqa

            timed_segments = processed_segments
            target_model_format = kwargs.get("target_model_format", "Generic")
            if target_model_format != "Generic":
                print(f"\033[94m[PromptCrafter] Applying '{target_model_format}' formatting to {len(storyboard_prompts)} lyric scenes...\033[0m")
                formatted_prompts = []
                for p in storyboard_prompts:
                    if p.startswith("[Error:"):
                        formatted_prompts.append(p)
                    else:
                        formatted_prompts.append(self._format_prompt_for_target(p, target_model_format))
                storyboard_prompts = formatted_prompts

            storyboard_text_for_neg_prompt = "\n\n---\n\n".join(storyboard_prompts)
            ai_negative_prompt = utils._generate_negative_prompt(storyboard_text_for_neg_prompt, config, user_negative_prompt="")
            parts = [p for p in [negative_prompt, ai_negative_prompt] if p and p.strip()]
            final_negative_prompt = ", ".join(parts)

            final_output = self._create_final_lyrics_output(
                storyboard_prompts=storyboard_prompts,
                timed_segments=timed_segments,
                generate_schedule=kwargs.get("generate_schedule", False),
                fps=fps, # Pass the read value
                song_length_seconds=config.song_length_seconds,
                max_frames=kwargs.get("max_frames", 240),
                has_real_timed_segments=has_real_timed_segments,
                
                # --- START FIX ---
                # Pass all scheduling parameters explicitly
                scene_splitting_mode=scene_splitting_mode,
                max_scene_frames=max_scene_frames,
                max_scene_duration_seconds=max_scene_duration_seconds,
                interpolate_keyframes=interpolate_keyframes,
                interpolation_frame_interval=interpolation_frame_interval
                # --- END FIX ---
            )
            
            prompt_out, schedule_out = ("", final_output) if kwargs.get("generate_schedule", False) else (final_output, "")
            
            return prompt_out, schedule_out, image_context, final_negative_prompt

    # // AI ENHANCEMENT: New method to group lyrics into logical scenes using an LLM.
    # // This creates more meaningful chunks (verse, chorus, etc.) than simple line-by-line processing.
    def _group_lyrics_into_scenes(self, lyrics, run_config):
        """Groups raw lyrics into narratively coherent scenes using an AI model."""
        # --- NEW: Pre-filter the lyrics to remove structural tags ---
        filtered_lyrics_lines = []
        for line in lyrics.splitlines():
            # This regex removes lines that are just tags like [Intro], [Chorus], (screaming), etc.
            if not re.fullmatch(r'^\s*\[[^\]]+\]\s*$', line) and not re.fullmatch(r'^\s*\([^)]+\)\s*$', line):
                filtered_lyrics_lines.append(line)
        filtered_lyrics = "\n".join(filtered_lyrics_lines).strip()
        if not filtered_lyrics:
            print(f"\033[93m[PromptCrafter] Warning: Lyrics contain only structural tags. Cannot group into scenes.\033[0m")
            return None
        # --- END NEW BLOCK ---
        print("\033[94m[PromptCrafter] Grouping lyrics into logical scenes using AI...\033[0m")
        prompt = textwrap.dedent(f"""
            You are a literary analyst. Your task is to read the following song lyrics and group them into logical scenes or sections (like Verse 1, Chorus, Bridge, etc.).
            Each scene should represent a distinct part of the narrative or a shift in mood.

            --- LYRICS ---
            {filtered_lyrics}
            --- END LYRICS ---

            RULES:
            1. Analyze the structure and meaning to identify logical breaks.
            2. Group consecutive lines into scenes. Do not split a single thought.
            3. Return ONLY a JSON object with a single key "scenes", which is an array of strings. Each string in the array should be a multi-line block of lyrics representing one scene.

            Example Output:
            {{
                "scenes": [
                    "First line of verse 1\nSecond line of verse 1",
                    "First line of the chorus\nSecond line of the chorus",
                    "First line of verse 2\nSecond line of verse 2"
                ]
            }}
        """ ).strip()

        ok, result_json = api_clients._reason_with_model(
            run_config.model,
            prompt,
            use_chat_api=run_config.use_chat_api,
            temperature=0.0,
            seed=run_config.seed,
            debug_mode=run_config.debug_mode,
            debug_title="Lyric Scene Grouping",
            timeout=run_config.timeout) # <-- ADD THIS LINE
        
        if ok and isinstance(result_json, dict) and "scenes" in result_json and isinstance(result_json["scenes"], list):
            print(f"\033[92m[PromptCrafter] Successfully grouped lyrics into {len(result_json['scenes'])} scenes.\033[0m")
            return result_json["scenes"]
        else:
            print(f"\033[93m[PromptCrafter] Warning: AI-based lyric grouping failed. Falling back to line-by-line processing. Error: {result_json}\033[0m")
            return None # Fallback signal
    
    def _resegment_lyrics_with_vlm(self, corrected_lyrics_text, original_segments, run_config):
        """
        After lyrics are corrected, this function uses an LLM to intelligently map the new
        text back onto the original timing segments.
        """
        original_segments_json = json.dumps([{"start": s[0], "end": s[1], "text": s[2]} for s in original_segments], indent=2)

        prompt = textwrap.dedent(f"""
            You are a text alignment expert. You are given a corrected full-text transcript and a JSON array of the original, time-coded segments from an ASR system. The text in the original segments is wrong, but the timings are correct.

            Your task is to create a new JSON array of segments that uses the **original timings** but contains the **corrected text**.

            1.  Read the `CORRECTED_FULL_TEXT`. This is the ground truth for the song's content.
            2.  Go through the `ORIGINAL_SEGMENTS` one by one. These provide the timing structure.
            3.  For each original segment, find the corresponding portion of text in the `CORRECTED_FULL_TEXT` to assign to it.
            4.  Create a new segment object that keeps the original `start` and `end` times but uses the new, correct text.
            5.  **CRITICAL RULE**: The goal is to map the *entire* `CORRECTED_FULL_TEXT` onto the sequence of `ORIGINAL_SEGMENTS`. Do not leave out any lyrics. If an original segment contains only a structural tag (e.g., `[Verse]`), you MUST include the lyrical lines that follow that tag in the corrected text, distributing them across the timed segments until the next tag is reached. Avoid creating long segments that contain only a tag.
            6.  **IMPORTANT FOR LARGE INPUTS**: The provided text and segments may be very long. Process them carefully from beginning to end. Ensure the output is a single, valid, complete JSON array. Do not truncate the output.

            ---
            **CORRECTED_FULL_TEXT:**
            ```
            {corrected_lyrics_text}
            ```
            ---
            **ORIGINAL_SEGMENTS (for timing reference):**
            ```json
            {original_segments_json}
            ```
            ---

            Return ONLY the new, corrected JSON array of segment objects. The text from all segments, when joined, should perfectly match the `CORRECTED_FULL_TEXT`.
        """).strip()

        # Increased timeout for potentially long-running re-segmentation task.
        timeout = max(300, run_config.timeout)

        ok, result_json = api_clients._reason_with_model(
            run_config.model,
            prompt,
            use_chat_api=True,
            temperature=0.0,
            seed=run_config.seed,
            debug_mode=run_config.debug_mode,
            debug_title="Lyric Re-segmentation",
            timeout=timeout)

        if ok and isinstance(result_json, list):
            # Convert the JSON list of dicts back to a list of tuples
            return [(seg.get('start', 0), seg.get('end', 0), seg.get('text', '')) for seg in result_json]
        else:
            print(f"\033[93m[PromptCrafter] Warning: AI re-segmentation failed. Returning original segments. Error: {result_json}\033[0m")
            return original_segments

    def _create_schedule_from_timed_segments(self, prompts, segments, fps, interpolate_keyframes, interpolation_frame_interval):
        schedule = collections.OrderedDict()
        if not prompts or not segments:
            return "{}"

        print(f"\033[94m[PromptCrafter DEBUG] Scheduling with FPS: {fps}\033[0m")
        if segments:
            print(f"\033[94m[PromptCrafter DEBUG] First segment start time: {segments[0][0]}\033[0m")

        if len(prompts) != len(segments):
            print(f"\033[93m[PromptCrafter] Warning: Mismatch between number of prompts ({len(prompts)}) and lyric segments ({len(segments)}). Falling back to even distribution.\033[0m")
            # --- START FIX ---
            # This fallback was broken. It now needs parameters.
            # However, this path is unlikely to be hit if the primary logic is correct.
            # We'll just create a simple schedule for robustness.
            total_frames = int(segments[-1][1] * fps) if segments else 240
            return utils._create_schedule_from_items(prompts, total_frames, 0, interpolate_keyframes, interpolation_frame_interval)
            # --- END FIX ---

        for i, prompt in enumerate(prompts):
            if i < len(segments):
                start_time = segments[i][0]
                frame = int(start_time * fps)
                schedule[frame] = prompt
        
        # --- START FIX ---
        # Use the passed-in parameters, not 'config'
        if interpolate_keyframes and interpolation_frame_interval > 0:
            schedule = utils._interpolate_schedule_prompts(schedule, interpolation_frame_interval)
        # --- END FIX ---

        schedule_items = [f'"{str(key)}": {json.dumps(str(value))}' for key, value in schedule.items()]
        return "{\n" + ",\n".join(schedule_items) + "\n}"

    def _prepare_lyrics_generation_context(self, user_instructions, images_with_weights, lyrics, run_config): # noqa
        images = [img for img, _ in images_with_weights]
        describe_result = self._describe_images(images_with_weights, run_config)
        # Be defensive: ensure describe_result is not None and is an iterable tuple before unpacking.
        if describe_result is None:
            image_context, _ = "No reference images provided.", []
        elif isinstance(describe_result, tuple) and len(describe_result) >= 2:
            image_context, _ = describe_result
        else:
            # Fallback for unexpected return types
            image_context, _ = "No reference images provided.", []
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

    def _generate_storyboard_global_theme(self, lyrics, instructions_section, context_section, image_context, run_config, mood_keywords=""): # noqa
        mood_section = f"\n--- AUDIO MOOD ---\n{mood_keywords}\n" if mood_keywords else ""
        theme_prompt = f"""You are a music video director. Your task is to analyze the provided source material and synthesize a "Global Theme" for a music video. This theme is a high-level summary that will ensure visual consistency across all scenes.

**CRITICAL INSTRUCTIONS:**
1.  **Analyze Source Material:** Your theme MUST be based on the explicit information and implicit mood of the LYRICS, INSTRUCTIONS, IMAGE REFERENCES, and especially the AUDIO MOOD.
2.  **Handle Abstract Lyrics:** If the lyrics are abstract or non-narrative, focus on interpreting the core emotions, mood, and symbolism. Translate these abstract concepts into a cohesive visual theme. For example, for lyrics about loneliness, you might suggest a theme of 'a single figure in vast, empty landscapes with a cool, desaturated color palette'.
3.  **Prioritize Audio Mood:** The AUDIO MOOD is a strong indicator of the intended feeling. If the lyrics are ambiguous, let the audio mood guide your visual theme.
4.  **Define Core Elements:** The theme should define the core visual style, setting, character design, and mood.

--- LYRICS ---
{lyrics}
--- INSTRUCTIONS ---
{instructions_section}
--- CONTEXT ---
{context_section}
--- IMAGE REFERENCES ---
{image_context}{mood_section}
---
Return ONLY the Global Theme description in a single, concise paragraph."""
        ok, theme = api_clients.query_model_auto(run_config.model, theme_prompt, prefer_chat=run_config.use_chat_api, temperature=run_config.temperature, seed=run_config.seed, timeout=120, debug_mode=run_config.debug_mode, debug_title="Storyboard Global Theme")
        return (True, utils.TextCleaner.single_paragraph(theme)) if ok else (False, f"Could not generate storyboard theme: {theme}")

    def _process_lyrics_storyboard(self, lyrics, timed_segments, global_theme, mandatory_tokens, style_inspiration_section, run_config, **kwargs):
        """
        Processes lyrics into a storyboard. It segments the lyrics, generates a prompt for each segment,
        and returns both the prompts and the original segments to preserve timing information.
        """
        storyboard_rules_text = self._build_storyboard_rules(run_config, style_inspiration_section)
        
        segments = []
        # --- START FIX ---
        # Read scene_splitting_mode from kwargs, not config
        scene_splitting_mode = kwargs.get('scene_splitting_mode', 'Structural Tag')
        # --- END FIX ---

        if timed_segments:
            # Use SRT data if available. Each segment is a tuple (start, end, text).
            segments = timed_segments
        
        # --- START FIX ---
        # This block now correctly reads the scene_splitting_mode from kwargs
        else:
            if scene_splitting_mode != 'Structural Tag':
                # Log if user selected a time-based mode without timed data
                print(f"\033[93m[PromptCrafter] Warning: '{scene_splitting_mode}' selected, but no timed segments available. Falling back to AI-based scene grouping.\033[0m")
            
            # AI-group the lyrics into logical scenes.
            scene_lyrics = self._group_lyrics_into_scenes(lyrics, run_config)
            
            if scene_lyrics:
                # Create "fake" timed segments for non-timed lyrics
                segments = [(i, i + 1, scene_text) for i, scene_text in enumerate(scene_lyrics)]
            else:
                # If AI grouping also fails, then fall back to line-by-line.
                print(f"\033[93m[PromptCrafter] AI grouping failed. Falling back to line-by-line processing.\033[0m")
                segments = [(i, i + 1, line) for i, line in enumerate(lyrics.splitlines()) if line.strip()]
        # --- END FIX ---

        if not segments:
            return "Could not segment lyrics into processable lines or sections.", None

        print(f"\033[94m[PromptCrafter] Generating storyboard for {len(segments)} scenes iteratively...\033[0m")
        processed_prompts: list[str] = [""] * len(segments)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(segments))) as executor:
            # Submit all jobs to the executor
            future_to_index = {
                executor.submit(self._create_prompt_for_scene, f"Scene {i+1}", seg[2], global_theme, storyboard_rules_text, mandatory_tokens, run_config): i
                for i, seg in enumerate(segments)
            }
            # Process results as they complete
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                segment_name = f"Scene {index + 1}"
                try:
                    processed_prompts[index] = future.result()
                    print(f"\033[92m[PromptCrafter] Finished processing '{segment_name}'.\033[0m")
                except Exception as exc:
                    error_message = f"Scene '{segment_name}' generated an exception: {exc}"
                    print(f'\033[91m[PromptCrafter] {error_message}\033[0m')
                    processed_prompts[index] = f"[Error: {error_message}]"
        
        # Return both the prompts and the original segments to maintain the link to timing data
        return processed_prompts, segments

    def _create_prompt_for_scene(self, scene_name, scene_text, global_theme, storyboard_rules_text, mandatory_tokens, run_config):
        """Generates a final prompt for a lyric scene in a single, optimized step."""
        
        merged_prompt = textwrap.dedent(f"""
            You are an expert prompt engineer for advanced video generation models (e.g., Sora, VEO, Wan2.2). Your task is to create a rich, detailed, and cinematic final prompt for a short 5-second video clip that represents the lyrics provided.

            --- GLOBAL THEME (for visual consistency) ---
            {global_theme}

            --- LYRIC SCENE: "{scene_name}" ---
            {scene_text}
            ---
            
            --- STYLE & COMPOSITION RULES ---
            {storyboard_rules_text}
            ---
            
            TASK:
            1.  **Invent a Concept**: First, invent a single, clear visual concept for the clip based on the LYRIC SCENE. Focus on ONE core action or visual moment.
            2.  **Elevate the Concept**: Transform your concept into a powerful, descriptive, and cinematic prompt.
            3.  **Add Cinematic Detail**: Incorporate dynamic camera work (e.g., 'cinematic dolly zoom', 'dramatic slow-motion tracking shot', 'low-angle shot', 'epic aerial shot').
            4.  **Specify Lighting & Atmosphere**: Describe the lighting and atmosphere with evocative terms (e.g., 'volumetric god rays piercing through dark clouds', 'eerie twilight casting long shadows', 'flickering firelight illuminating the warrior\'s face').
            5.  **Integrate Rules**: Naturally weave in the style and composition rules.
            6.  **Emphasize Motion**: Ensure the prompt has a clear subject performing a core ACTION with realistic, physics-based MOTION.

            Return ONLY the final, polished, and cinematic prompt. Do not include any titles, labels, or markdown like "**Final Prompt:**".
        """).strip()

        final_ok, final_prompt = api_clients.query_model_auto(
            run_config.model, merged_prompt, prefer_chat=run_config.use_chat_api, temperature=run_config.temperature,
            seed=run_config.seed, timeout=120, debug_mode=run_config.debug_mode, debug_title=f"Create Prompt for '{scene_name}'"
        )
        
        if not final_ok:
            error_msg = f"Failed to generate prompt for '{scene_name}': {final_prompt}"
            print(f"\033[93m[PromptCrafter] Warning: {error_msg}\033[0m")
            return f"[Error: {error_msg}]"

        return utils.TextCleaner.slim_prompt_text(utils.TextCleaner.single_paragraph(final_prompt))

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
        """ ).strip()

    def _create_final_lyrics_output(self, storyboard_prompts, timed_segments, generate_schedule, fps, song_length_seconds, max_frames, has_real_timed_segments, scene_splitting_mode, max_scene_frames, max_scene_duration_seconds, interpolate_keyframes, interpolation_frame_interval): # noqa
        
        if not generate_schedule:
            return "\n\n---\n\n".join(storyboard_prompts)
        
        # Path 1: We have real audio timing data. This logic is sound.
        if timed_segments and has_real_timed_segments:
            return self._create_schedule_from_timed_segments(
                storyboard_prompts, 
                timed_segments, 
                fps, 
                interpolate_keyframes, 
                interpolation_frame_interval
            )
        
        # --- START FIX ---
        # Path 2: No audio timing data. This is where the logic was flawed.
        
        # Determine the length of each scene based on the splitting mode.
        scene_length = 0
        if scene_splitting_mode == 'Frame Length':
            scene_length = max_scene_frames
        elif scene_splitting_mode == 'Fixed Duration':
            scene_length = int(max_scene_duration_seconds * fps)
        
        # If we have a fixed scene length, use specific logic to build the schedule.
        if scene_length > 0:
            print(f"\033[94m[PromptCrafter] Creating schedule with fixed scene length of {scene_length} frames.\033[0m")
            
            schedule = collections.OrderedDict()
            current_frame = 0
            for prompt in storyboard_prompts:
                schedule[current_frame] = prompt
                current_frame += scene_length
            
            # Apply interpolation between the main keyframes if requested.
            if interpolate_keyframes and interpolation_frame_interval > 0:
                print(f"\033[94m[PromptCrafter] Applying interpolation with an interval of {interpolation_frame_interval} frames.\033[0m")
                schedule = utils._interpolate_schedule_prompts(schedule, interpolation_frame_interval)
            
            schedule_items = [f'\"{str(key)}\": {json.dumps(str(value))}' for key, value in schedule.items()]
            return "{\n" + ",\n".join(schedule_items) + "\n}"

        # Fallback for 'Structural Tag' mode without timing data, which distributes prompts evenly.
        else:
            print(f"\033[94m[PromptCrafter] Using 'Structural Tag' mode without timed data. Distributing scenes evenly.\033[0m")
            total_frames = int(song_length_seconds * fps) if song_length_seconds > 0 else max_frames
            return utils._create_schedule_from_items(
                storyboard_prompts,
                total_frames,
                0, # start_frame
                interpolate_keyframes,
                interpolation_frame_interval
            )
        # --- END FIX ---

    def _create_schedule_from_srt(self, storyboard_prompts, timed_segments, fps, run_config): # noqa
        print("\033[94m[PromptCrafter] SRT file detected. Generating timed schedule...\033[0m")
        if len(storyboard_prompts) != len(timed_segments):
            return f"[Error: Mismatch between SRT segments ({len(timed_segments)}) and generated prompts ({len(storyboard_prompts)}).]"
        
        schedule = collections.OrderedDict()
        for i, seg in enumerate(timed_segments):
            start_time, end_time, _ = seg
            prompt = storyboard_prompts[i].strip()
            start_frame = int(start_time * fps)
            end_frame = int(end_time * fps)
            schedule[start_frame] = prompt # Prompt starts at the beginning of the segment
            if end_frame > start_frame: schedule[end_frame] = prompt # Hold prompt until the end

        if run_config.interpolate_keyframes:
            schedule = utils._interpolate_schedule_prompts(schedule, run_config.interpolation_frame_interval)
        schedule_items = ",".join([f'\"{str(key)}\": {json.dumps(str(value))}' for key, value in schedule.items()])
        return "{\n" + ",\n".join([f'"{str(key)}": {json.dumps(str(value))}' for key, value in schedule.items()]) + "\n}"

# ------------------------------------------------------------------------------------
# PromptCrafter_AudioSplitter Node
# ------------------------------------------------------------------------------------
class PromptCrafter_AudioSplitter(PromptCrafter_BaseCreator):
    DESCRIPTION = "Splits an audio input into 16 chunks based on timing data from a LyricsCreator 'audio_meta' output."
    
    RETURN_TYPES = tuple(["AUDIO"] * 16)
    RETURN_NAMES = tuple([f"audio_{i}" for i in range(1, 17)])
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter/Creator"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "audio_meta": ("DICT", {"tooltip": "The 'audio_meta' output from a PromptCrafter_LyricsCreator node."}),
                "set_index": ("INT", {"default": 0, "min": 0, "max": 999, "tooltip": "The current batch/set number (e.g., 0 for first 16 scenes, 1 for next 16)."}),
            }
        }

    def execute(self, audio, audio_meta, set_index=0):
        try:
            # --- DEBUG: Inspect incoming audio_meta ---
            if isinstance(audio_meta, dict):
                print(f"\033[95m[PromptCrafter_AudioSplitter DEBUG] Received audio_meta keys: {list(audio_meta.keys())}\033[0m")
            else:
                print(f"\033[95m[PromptCrafter_AudioSplitter DEBUG] Received audio_meta is not a dictionary. Type: {type(audio_meta)}\033[0m")
            # -----------------------------------------

            # --- 1. Unpack Audio and Meta ---
            if not isinstance(audio, dict) or "waveform" not in audio:
                raise ValueError("Invalid AUDIO input. Expected a dictionary with 'waveform' and 'sample_rate'.")
            
            waveform = audio["waveform"]
            sample_rate = int(audio["sample_rate"])

            if waveform.ndim == 2:
                waveform = waveform.unsqueeze(0) # (C, T) -> (B, C, T)

            total_samples = waveform.shape[-1]
            total_duration_sec = total_samples / sample_rate

            if not isinstance(audio_meta, dict):
                raise ValueError("Invalid 'audio_meta' input. Expected a dictionary from PromptCrafter_LyricsCreator.")

            timed_segments = audio_meta.get("timed_segments")
            fps = float(audio_meta.get("fps", 16.0))
            scene_splitting_mode = audio_meta.get("scene_splitting_mode", "Structural Tag")
            
            scene_samples = 0
            
            # --- 2. Determine Scene Length in Samples ---
            if scene_splitting_mode == 'Frame Length':
                frames_per_scene = int(audio_meta.get("max_scene_frames", 120))
                scene_samples = int(frames_per_scene * (sample_rate / fps))
            elif scene_splitting_mode == 'Fixed Duration':
                duration_per_scene = float(audio_meta.get("max_scene_duration_seconds", 5.0))
                scene_samples = int(duration_per_scene * sample_rate)
            
            segments = []
            scene_count = 16 # This node always outputs 16 scenes
            
            # --- 3. Split Audio ---
            if timed_segments:
                # Path A: We have real timing data from Whisper/alignment
                print(f"[PromptCrafter_AudioSplitter] Splitting audio using {len(timed_segments)} timed segments.")
                
                # Get the 16 segments for the current set_index
                start_idx = set_index * scene_count
                end_idx = start_idx + scene_count
                segments_for_this_set = timed_segments[start_idx:end_idx]
                
                for i in range(scene_count):
                    if i < len(segments_for_this_set):
                        start_sec, end_sec, _ = segments_for_this_set[i]
                        start_samp = int(start_sec * sample_rate)
                        end_samp = int(end_sec * sample_rate)
                        
                        # Clamp to audio boundaries
                        start_samp = max(0, start_samp)
                        end_samp = min(total_samples, end_samp)
                        
                        seg = waveform[..., start_samp:end_samp]
                    else:
                        # Pad with silence if no more segments
                        seg = torch.zeros((waveform.shape[0], waveform.shape[1], 1000), dtype=waveform.dtype, device=waveform.device) # 1000 samples of silence
                    
                    segments.append({"waveform": seg, "sample_rate": sample_rate})

            elif scene_samples > 0:
                # Path B: No timing data, but we have a fixed scene length
                print(f"[PromptCrafter_AudioSplitter] Splitting audio into fixed chunks of {scene_samples} samples.")
                
                offset_samples = set_index * scene_count * scene_samples
                
                for i in range(scene_count):
                    start_samp = offset_samples + (i * scene_samples)
                    end_samp = start_samp + scene_samples
                    
                    # Clamp to audio boundaries
                    start_samp = max(0, start_samp)
                    end_samp = min(total_samples, end_samp)
                    
                    seg = waveform[..., start_samp:end_samp]
                    
                    # Pad segment with silence if it's short (e.g., end of audio)
                    current_len = seg.shape[-1]
                    if current_len < scene_samples and current_len > 0:
                        pad_len = scene_samples - current_len
                        pad = torch.zeros((seg.shape[0], seg.shape[1], pad_len), dtype=seg.dtype, device=seg.device)
                        seg = torch.cat([seg, pad], dim=-1)
                    elif current_len <= 0:
                        # Full silence if we're past the audio
                        seg = torch.zeros((waveform.shape[0], waveform.shape[1], scene_samples), dtype=waveform.dtype, device=waveform.device)

                    segments.append({"waveform": seg, "sample_rate": sample_rate})
            
            else:
                # Path C: Fallback (e.g., "Structural Tag" with no timing)
                # This is less ideal, but provides a fallback.
                print(f"[PromptCrafter_AudioSplitter] Warning: No timing data. Splitting audio evenly across {total_duration_sec}s.")
                total_scenes_approx = max(1, len(audio_meta.get("timed_segments", []))) # A guess
                if total_scenes_approx <= 1: total_scenes_approx = int(total_duration_sec / 5.0) # 5s guess
                
                scene_samples = int(total_samples / max(1, total_scenes_approx))
                # Now run the logic from Path B with this guess
                offset_samples = set_index * scene_count * scene_samples
                for i in range(scene_count):
                    start_samp = offset_samples + (i * scene_samples)
                    end_samp = start_samp + scene_samples
                    start_samp = max(0, min(total_samples -1, start_samp))
                    end_samp = max(0, min(total_samples, end_samp))
                    seg = waveform[..., start_samp:end_samp]
                    segments.append({"waveform": seg, "sample_rate": sample_rate})
            
            # Ensure we always return 16 outputs
            if len(segments) < scene_count:
                silence_samples = scene_samples if scene_samples > 0 else int(sample_rate * 4.0) # 4s silence
                silence = torch.zeros((waveform.shape[0], waveform.shape[1], silence_samples), dtype=waveform.dtype, device=waveform.device)
                for _ in range(scene_count - len(segments)):
                    segments.append({"waveform": silence, "sample_rate": sample_rate})
            
            return tuple(segments)

        except Exception as e:
            # On failure, return 16 Nones
            print(f"\033[91m[PromptCrafter_AudioSplitter] Error: {e}\033[0m")
            import traceback
            traceback.print_exc()
            return (None,) * 16

# ------------------------------------------------------------------------------------
# PromptCrafter_Formatter Node (Enhanced)
# ------------------------------------------------------------------------------------
class PromptCrafter_Formatter:
    DESCRIPTION = "Formats prompts or schedules. Can apply templates or add prefixes/suffixes to individual prompts or all keyframes in a schedule."
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["Build from Template", "Edit Single Prompt", "Bulk Edit Schedule"], {"default": "Build from Template", "tooltip": "Choose the formatting operation."}),
            },
            "optional": {
                "prompt_in": ("STRING", {"multiline": True, "default": "", "tooltip": "The main prompt string to format."}),
                "schedule_in": ("STRING", {"multiline": True, "default": "", "tooltip": "The schedule JSON string to format."}),
                
                # For "Simple Template" mode
                "template_text": ("STRING", {"multiline": True, "default": "A high-quality photo of {a}, in the style of {b}.", "tooltip": "Template for 'Simple Template' mode. Use {a}, {b}, {prompt}, {schedule}, etc."}),
                "var_a": ("STRING", {"multiline": False, "default": "", "tooltip": "Replaces {a} in the template."}),
                "var_b": ("STRING", {"multiline": False, "default": "", "tooltip": "Replaces {b} in the template."}),
                "var_c": ("STRING", {"multiline": False, "default": "", "tooltip": "Replaces {c} in the template."}),
                "var_d": ("STRING", {"multiline": False, "default": "", "tooltip": "Replaces {d} in the template."}),

                # For "Apply to Prompt/Schedule" modes
                "prefix": ("STRING", {"multiline": False, "default": "", "tooltip": "Text to add to the beginning of the prompt(s)."}),
                "suffix": ("STRING", {"multiline": False, "default": "", "tooltip": "Text to add to the end of the prompt(s)."}),
                "find_text": ("STRING", {"multiline": False, "default": "", "tooltip": "Text to find (case-sensitive)."}),
                "replace_with": ("STRING", {"multiline": False, "default": "", "tooltip": "Text to replace with."}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("formatted_prompt", "formatted_schedule")
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Utils"

    def _format_text(self, text, prefix, suffix, find_text, replace_with):
        """Helper function to apply formatting rules to a single text string."""
        
        # 1. Start with the core text
        processed_text = text if text else ""
        
        # 2. Find/Replace
        if find_text:
            processed_text = processed_text.replace(find_text, replace_with)
        
        # 3. Add Prefix/Suffix
        # Use a list to join non-empty parts, avoiding comma/space issues
        parts = []
        if prefix:
            parts.append(prefix.strip())
        if processed_text:
            parts.append(processed_text)
        if suffix:
            parts.append(suffix.strip())
            
        # Join with ", " only if multiple parts exist
        return ", ".join(parts)

    def execute(self, mode, prompt_in="", schedule_in="", template_text="", var_a="", var_b="", var_c="", var_d="", prefix="", suffix="", find_text="", replace_with=""):
        
        out_prompt = prompt_in
        out_schedule = schedule_in

        if mode == "Build from Template":
            placeholders = {
                "{a}": str(var_a),
                "{b}": str(var_b),
                "{c}": str(var_c),
                "{d}": str(var_d),
                "{prompt}": str(prompt_in),
                "{schedule}": str(schedule_in),
            }
            formatted_text = template_text
            for placeholder, value in placeholders.items():
                formatted_text = formatted_text.replace(placeholder, value)
            
            # In this mode, the main output is the formatted template text.
            out_prompt = formatted_text
            # Pass the original schedule through unchanged
            out_schedule = schedule_in 
        
        elif mode == "Edit Single Prompt":
            out_prompt = self._format_text(prompt_in, prefix, suffix, find_text, replace_with)
            # Pass schedule through unchanged
            out_schedule = schedule_in

        elif mode == "Bulk Edit Schedule":
            if not schedule_in:
                return (prompt_in, "") # Pass prompt, return empty schedule
            
            try:
                # We need the json module
                import json
                schedule_data = json.loads(schedule_in)
                
                new_schedule = {}
                # Iterate through the schedule (which is a dict of "frame": "prompt")
                for frame, prompt_text in schedule_data.items():
                    # Apply the same formatting rules to each prompt
                    new_schedule[frame] = self._format_text(prompt_text, prefix, suffix, find_text, replace_with)
                
                # Re-serialize the schedule to a string
                out_schedule = json.dumps(new_schedule, indent=4)
                # Pass prompt through unchanged
                out_prompt = prompt_in
            
            except json.JSONDecodeError:
                error_msg = "[PromptCrafter Formatter] Error: schedule_in is not valid JSON. Cannot apply to schedule."
                print(f"\033[91m{error_msg}\033[0m")
                out_prompt = error_msg # Output error to prompt string
                out_schedule = schedule_in # Pass through the broken schedule
            except Exception as e:
                error_msg = f"[PromptCrafter Formatter] Error processing schedule: {e}"
                print(f"\033[91m{error_msg}\033[0m")
                out_prompt = error_msg
                out_schedule = schedule_in

        return (out_prompt, out_schedule)

# ------------------------------------------------------------------------------------
# PromptCrafter_SaveTextFile Node
# ------------------------------------------------------------------------------------
class PromptCrafter_SaveTextFile:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text_to_save": ("STRING", {"multiline": True}),
                "folder_path": ("STRING", {"default": "ComfyUI/output/PromptCrafter"}),
                "filename_template": ("STRING", {"default": "{seed}_{model_name}.txt"}),
            },
            "optional": {
                "model_name": ("STRING", {"multiline": False, "default": ""}),
                "seed": ("STRING", {"multiline": False, "default": ""}),
                "user_text": ("STRING", {"multiline": False, "default": ""}),
                "custom_var": ("STRING", {"multiline": False, "default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("save_status",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Utils"

    def execute(self, text_to_save, folder_path, filename_template, model_name="", seed="", user_text="", custom_var=""):
        # 1. ADD: Ensure all replacement values are strings
        filename = filename_template.replace("{model_name}", str(model_name))
        filename = filename.replace("{seed}", str(seed))
        filename = filename.replace("{user_text}", str(user_text))
        filename = filename.replace("{custom_var}", str(custom_var))

        # Sanitize the filename
        filename = utils.TextCleaner.sanitize_filename(filename)

        # Ensure the directory exists (This is fine, but robust error handling is better)
        os.makedirs(folder_path, exist_ok=True)
        
        # 2. ADD: Logic to get a unique filename and prevent overwrites
        base_name, ext = os.path.splitext(filename)
        # The 'utils' function from the original good code is the best way to handle this
        # Assuming the existence of utils._get_unique_filepath(directory, base_name, extension)
        out_dir = os.path.abspath(folder_path) # Need absolute path for the utility
        full_path, _ = utils._get_unique_filepath(out_dir, base_name, ext)

        # Write the content to the file
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(text_to_save)

        return (f"Saved to {full_path}",)

# ------------------------------------------------------------------------------------
# PromptCrafter_FileOrganizer Node
# ------------------------------------------------------------------------------------
class PromptCrafter_FileOrganizer:
    DESCRIPTION = get_node_description("PromptCrafter_FileOrganizer")
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
                "auto_generate_scheme": ("BOOLEAN", {"default": False, "tooltip": "Automatically generate an organization scheme by analyzing a sample of files. Overrides the manual scheme."} ),
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
                image_tensor = utils.pil2tensor(pil_image)
                
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
            - `image_resolution`: Checks image dimensions. Use operators `=`, `>`, `<`. Example: `image_resolution: >1024x1024 -> High_Resolution`
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

        final_scheme = organization_scheme or ""  # Set empty string as default
        generated_scheme_out = ""
        if auto_generate_scheme:
            generated_scheme, error = self._generate_scheme_with_ai(file_groups, model, max_workers, debug_mode=kwargs.get("debug_mode", False))
            if error:
                return (f"Error during auto-scheme generation: {error}", "", "")
            # Ensure we never assign None to final_scheme
            final_scheme = generated_scheme or ""
            print(f"\033[92m[FileOrganizer] Using auto-generated scheme:\n{final_scheme}\033[0m")
        elif organization_profile != "None (Manual Scheme)":
            profile = organization_profiles.NAMED_ORGANIZATION_PROFILES.get(organization_profile)
            if profile and "scheme" in profile:
                # Use .get and default to empty string to avoid None
                final_scheme = profile.get("scheme", "") or ""
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
            
            # Ensure full_output_path is a valid string (utils._get_and_create_output_dir may return None on failure)
            if not full_output_path:
                try:
                    os.makedirs(output_folder, exist_ok=True)
                    full_output_path = os.path.abspath(output_folder)
                except Exception:
                    # Fallback to current working directory if we cannot create the requested folder
                    full_output_path = os.getcwd()

            log_file_path = os.path.join(full_output_path, log_filename)
            try:
                with open(log_file_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(log_messages))
                print(f"\033[92m[FileOrganizer] Operation log saved to: {log_file_path}\033[0m")
            except Exception as e:
                print(f"\033[91m[FileOrganizer] Error writing log file: {e}\033[0m")

        dry_run_plan_str = "\n".join(sorted(all_op_logs)) if dry_run else ""

        return (summary, dry_run_plan_str, generated_scheme_out)

# ------------------------------------------------------------------------------------
# PromptCrafter_CacheUtility Node
# ------------------------------------------------------------------------------------
class PromptCrafter_CacheUtility:
    DESCRIPTION = get_node_description("PromptCrafter_CacheUtility")
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

# ------------------------------------------------------------------------------------
# PromptCrafter_ImageSwitcher Node
# ------------------------------------------------------------------------------------
# In nodes.py, locate and replace the PromptCrafter_ImageSwitcher class:

class PromptCrafter_ImageSwitcher:
    DESCRIPTION = "Switches between multiple image inputs based on an index or randomly, triggered by a signal."
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                # NEW: Switching mode selector
                "image_count": ("INT", {"default": 2, "min": 2, "max": 16, "step": 1, "tooltip": "The number of image input pins to generate. Use the 'Manual Refresh' button to apply changes."}),
                "switching_mode": (["Chronological (Index)", "Random Select"], {"default": "Chronological (Index)", "tooltip": "Method to choose the image: incremental using the index or pure random selection."}),
                "signal": ("*", {"optional": True, "tooltip": "A signal from another node to force execution/switching."}),
            },
            "optional": {
                # Input for the chronological mode
                "current_index": ("INT", {"default": 0, "min": 0, "max": 1000, "step": 1, "tooltip": "The 0-based index of the image to select (only used in Chronological mode)."}),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("selected_image", "selected_index")
    FUNCTION = "switch_image"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Utils"

    def switch_image(self, switching_mode, image_count, current_index=0, signal=None, **kwargs):
        images = []
        
        # 1. Collect all connected dynamic image inputs based on image_count
        for i in range(1, image_count + 1):
            key = f"image_{i}"
            # Only append the image tensor if the pin exists and is connected
            if key in kwargs and kwargs[key] is not None:
                images.append(kwargs[key])
        
        if not images:
            raise ValueError("PromptCrafter_ImageSwitcher: No images were provided or connected to the dynamic pins.")

        num_images = len(images)
        selected_index = 0

        # 2. Implement switching logic based on mode
        if switching_mode == "Chronological (Index)":
            # Use the user's index (clamped to prevent out-of-bounds error)
            selected_index = max(0, min(num_images - 1, current_index))
        
        elif switching_mode == "Random Select":
            # Select a random index from the connected images (0 to num_images - 1)
            selected_index = random.randint(0, num_images - 1)
        
        # 3. Return the selected image and the index used
        selected_image = images[selected_index]
        return (selected_image, selected_index)

NODE_CLASS_MAPPINGS = {
    "PromptCrafter_QnA": PromptCrafter_QnA,
    "PromptCrafter_Captioner": PromptCrafter_Captioner,
    "PromptCrafter_VisualCreator": PromptCrafter_VisualCreator,
    "PromptCrafter_LyricsCreator": PromptCrafter_LyricsCreator,
    "PromptCrafter_AudioSplitter": PromptCrafter_AudioSplitter,
    "PromptCrafter_CacheUtility": PromptCrafter_CacheUtility,
    "PromptCrafter_FileOrganizer": PromptCrafter_FileOrganizer,
    "PromptCrafter_Formatter": PromptCrafter_Formatter,
    "PromptCrafter_SaveTextFile": PromptCrafter_SaveTextFile,
    "PromptCrafter_ImageSwitcher": PromptCrafter_ImageSwitcher,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_QnA": "PromptCrafter QnA",
    "PromptCrafter_Captioner": "PromptCrafter Image Captioner",
    "PromptCrafter_VisualCreator": "PromptCrafter Visual Creator",
    "PromptCrafter_LyricsCreator": "PromptCrafter Lyrics-to-Prompt Creator",
    "PromptCrafter_AudioSplitter": "PromptCrafter Audio Splitter",
    "PromptCrafter_CacheUtility": "PromptCrafter Cache Utility",
    "PromptCrafter_FileOrganizer": "PromptCrafter File Organizer",
    "PromptCrafter_Formatter": "PromptCrafter Text Formatter",
    "PromptCrafter_SaveTextFile": "PromptCrafter Save Text File",
    "PromptCrafter_ImageSwitcher": "PromptCrafter Image Switcher",
}