# Standard library imports
import os
import re
import time
import json
import random
import threading
import concurrent.futures
import textwrap
import collections
from PIL import Image
import torch
import comfy.utils

# Local module imports
from . import config
from . import utils
from . import api_clients
from .style_engine import StyleEngine

# --- Node-specific constants ---
DEFAULT_CAPTION_PROMPT = textwrap.dedent("""
    Your task is to create a highly detailed and accurate caption for this image, suitable for training an AI model.
    Follow this formula strictly:
    1.  **Subject**: Start with the main subject, including descriptive details (e.g., `1girl, red hair, blue eyes`).
    2.  **Action/Pose**: Describe what the subject is doing (e.g., `sitting on a couch`, `looking at viewer`).
    3.  **Clothing/Details**: Describe all clothing and key accessories (e.g., `wearing a blue dress, necklace`).
    4.  **Setting**: Describe the environment (e.g., `in a dimly lit room, red couch, window in background`).
    5.  **Style**: Describe the artistic style (e.g., `photorealistic, cinematic lighting, high quality`).
    
    Combine these into a single, comma-separated list of tags. Be factual and literal. Do not mention artist names, brand names, or copyrighted characters.
""").strip()

# ------------------------------------------------------------------------------------
# PromptCrafter_QnA Node
# ------------------------------------------------------------------------------------
class PromptCrafter_QnA:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "user_text": ("STRING", {"multiline": True, "default": config.DEFAULT_PROMPT_TEXT, "tooltip": "Your question or instruction for the model."}),
                "model": (api_clients.get_all_models(), {"dynamic": True, "tooltip": "The language model (text or vision) to use for the answer."}),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Controls creativity. Lower is more deterministic."}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "step": 1, "tooltip": "Seed for reproducible results. -1 for random. Set Temperature to 0 for full determinism."}),
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10, "tooltip": "Timeout in seconds for each API call. Increase if you get timeout errors."}),
                "safe_mode": ("BOOLEAN", {"default": True, "tooltip": "Enforce SFW rules to prevent NSFW, violent, or controversial content."}),
                "debug_mode": ("BOOLEAN", {"default": False, "tooltip": "Print all intermediate prompts to the console for debugging."}),
                "save_to_txt": ("BOOLEAN", {"default": False, "tooltip": "Save the full Q&A context and response to a text file in the ComfyUI/output directory."}),
                "filename_prefix": ("STRING", {"multiline": False, "default": "PromptCrafter/QnA", "tooltip": "Subdirectory and prefix for the saved text file."}),
            },
            "optional": {
                "image": ("IMAGE", {"tooltip": "Optional reference image for the query. Requires a vision model (VLM)."}),
                "auto_select_model": ("BOOLEAN", {"default": True, "tooltip": "Automatically select a vision model if an image is connected, or a text model if not."}),
                "enable_web_search": ("BOOLEAN", {"default": True, "tooltip": "Allow the node to perform a web search for questions about recent events or topics requiring current information."}),
                "fast_web_search": ("BOOLEAN", {"default": True, "tooltip": "In web search mode, only use search result snippets instead of fetching full page content. Much faster."}),
                "folder_path": ("STRING", {"multiline": False, "default": "input", "tooltip": "Folder containing an optional context file (e.g., 'input' or 'input/texts')."}),
                "file_name": ("STRING", {"multiline": False, "default": "<none>", "tooltip": "The name of the text file within the specified folder."}),
                "chunk_large_context": ("BOOLEAN", {"default": True, "tooltip": "Automatically chunk and summarize context files that are too large."}),
                "chunk_size_words": ("INT", {"default": 2000, "min": 500, "max": 8000, "step": 100, "tooltip": "The approximate size of each chunk in words for summarization."}),
                "summarization_strategy": (["Default (Abstractive)", "Extractive"], {"default": "Default (Abstractive)", "tooltip": "How to summarize large context. Abstractive creates new text, Extractive pulls key sentences."}),
                "max_history_words": ("INT", {"default": 1500, "min": 100, "max": 8000, "step": 100, "tooltip": "Maximum number of words to keep in history before summarizing the oldest parts."}),
                "history_in": ("STRING", {"multiline": False, "default": "", "input": "hidden"}),
                "clear_history": ("BOOLEAN", {"default": False, "tooltip": "Set to True for one run to clear the conversation history."}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("response", "history_out")
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️/PromptCrafter"

    def execute(self, user_text, model, temperature, seed, debug_mode, safe_mode, save_to_txt, filename_prefix, image=None, auto_select_model=True, folder_path=None, file_name="<none>", chunk_large_context=True, chunk_size_words=2000, timeout=120, enable_web_search=True, fast_web_search=True, history_in="", clear_history=False, summarization_strategy="Default (Abstractive)", max_history_words=1500):
        llm_model = model
        has_image = image is not None

        if auto_select_model:
            vision_models_list = api_clients._get_models_by_type("vision")
            text_models_list = api_clients._get_models_by_type("text")
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

        if not llm_model: llm_model = config.FALLBACK_TEXT_MODEL

        history_text = history_in.strip() if history_in and not clear_history else ""
        history_words = history_text.split()
        if len(history_words) > max_history_words:
            print(f"\033[94m[PromptCrafter] History is long ({len(history_words)} words). Summarizing oldest parts to fit under {max_history_words} words...\033[0m")
            words_to_keep_recent = max_history_words // 3
            recent_history = " ".join(history_words[-words_to_keep_recent:])
            history_to_summarize = " ".join(history_words[:-words_to_keep_recent])
            
            summarization_prompt = textwrap.dedent(f"""
                You are a conversation summarizer. The following is the beginning of a long conversation. Summarize it into a concise paragraph that captures the key topics, entities, and conclusions discussed.
                --- CONVERSATION TO SUMMARIZE ---\n{history_to_summarize}\n--- END ---
                Return ONLY the summary.
            """)
            
            ok_sum, summary = api_clients.query_model_auto(llm_model, summarization_prompt, prefer_chat=True, temperature=0.0, seed=seed, debug_mode=debug_mode, timeout=timeout, debug_title="QnA History Summarization")
            
            if ok_sum:
                history_text = f"Summary of earlier conversation:\n{summary}\n\n---\n\n{recent_history}"
                utils._debug_print(debug_mode, "Summarized History", history_text)
            else:
                print(f"\033[93m[PromptCrafter] Warning: History summarization failed. Truncating history instead. Error: {summary}\033[0m")
                history_text = " ".join(history_words[-max_history_words:])


        all_contexts, context_sources = [], []

        # 1. Gather File Context
        has_file_context = folder_path and file_name and file_name != "<none>"
        if has_file_context:
            full_folder_path = folder_path if os.path.isabs(folder_path) else os.path.join(config.COMFYUI_ROOT_DIR, folder_path)
            fpath = os.path.join(full_folder_path, file_name)
            if os.path.exists(fpath):
                file_content = utils.safe_read(fpath)
                all_contexts.append(f"--- CONTEXT FROM FILE: {file_name} ---\n{file_content}")
                context_sources.append(f"File ({file_name})")
            else:
                all_contexts.append(f"[Error: File not found at '{fpath}'.]")
                context_sources.append(f"File ({file_name}) - Not Found")

        # 2. Gather Web Search Context
        if enable_web_search:
            search_needed, search_query = utils._should_perform_web_search(user_text, llm_model, seed, debug_mode, timeout=timeout)
            if search_needed:
                web_context = utils._perform_web_search(search_query, num_results=3, debug_mode=debug_mode, fast_search=fast_web_search)
                if web_context and not web_context.startswith("["):
                    all_contexts.append(f"--- CONTEXT FROM WEB SEARCH (Query: '{search_query}') ---\n{web_context}")
                    context_sources.append(f"Web Search ('{search_query}')")

        # 3. Combine and Summarize
        raw_context = "\n\n".join(all_contexts)
        context = raw_context
        context_source = " + ".join(context_sources) if context_sources else "None"
        strategy_key = "extractive" if "Extractive" in summarization_strategy else "default"
        if chunk_large_context and context and not context.startswith("[Error"):
            words = context.split()
            if len(words) > chunk_size_words:
                print(f"\033[94m[PromptCrafter] Combined context from {context_source} is large ({len(words)} words). Summarizing...\033[0m")
                context = utils._summarize_large_text(raw_context, chunk_size_words, llm_model, temperature, seed, debug_mode, timeout, strategy=strategy_key, user_query=user_text)
                utils._debug_print(debug_mode, "Summarized Context", context)

        final_user_text, raw_user_text = user_text, user_text
        if chunk_large_context and len(user_text.split()) > chunk_size_words and user_text.strip() != config.DEFAULT_PROMPT_TEXT:
            print(f"\033[94m[PromptCrafter] User text is large ({len(user_text.split())} words). Summarizing...\033[0m")
            final_user_text = utils._summarize_large_text(user_text, chunk_size_words, llm_model, temperature, seed, debug_mode, timeout, strategy=strategy_key)
            utils._debug_print(debug_mode, "Summarized User Text", final_user_text)

        if (context or image is not None) and user_text.strip() == config.DEFAULT_PROMPT_TEXT:
            final_user_text = "Describe this image in detail." if image is not None else "Summarize the key points of the provided context."

        safety_rule = f"\n\n{config.SAFE_MODE_RULE}" if safe_mode else ""
        history_section = f"CONVERSATION HISTORY (for context):\n{history_text}\n\n" if history_text else ""
        context_section = f"ADDITIONAL CONTEXT (for this query only):\n{context}\n\n" if context else ""
        
        prompt = textwrap.dedent(f"""
            You are a helpful Q&A assistant. Answer the user's query based on the conversation history and any additional context provided.
            {history_section}{context_section}CURRENT USER QUERY:
            {final_user_text}{safety_rule}
        """).strip()

        images_to_pass = [image] if image is not None else None
        ok, resp = api_clients.query_model_auto(llm_model, prompt, images=images_to_pass, prefer_chat=True, temperature=temperature, seed=seed, debug_mode=debug_mode, debug_title="QnA Prompt", timeout=timeout)

        response_text = utils.TextCleaner.single_paragraph(resp if ok else f"Model error: {resp}")
        new_history_entry = f"User: {final_user_text}\nAssistant: {response_text}"
        updated_history = f"{history_text}\n{new_history_entry}".strip() if history_text else new_history_entry
        
        if save_to_txt and response_text.strip():
            base_dir = os.path.join(config.COMFYUI_ROOT_DIR, "output")
            safe_subdir = os.path.normpath(filename_prefix.strip()).lstrip('.').lstrip('/')
            out_dir = os.path.join(base_dir, safe_subdir)
            os.makedirs(out_dir, exist_ok=True)
            fname = f"qna_{time.strftime('%Y%m%d_%H%M%S')}.txt"
            fpath = os.path.join(out_dir, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(f"=== MODEL: {llm_model} ===\n\n")
                if history_text: f.write(f"=== CONVERSATION HISTORY ===\n{history_text}\n\n")
                f.write(f"=== CONTEXT SOURCE: {context_source} ===\n\n")
                if raw_context: f.write(f"=== CONTEXT (RAW) ===\n{raw_context}\n\n")
                if raw_context != context: f.write(f"=== CONTEXT (SUMMARIZED) ===\n{context}\n\n")
                f.write("=== USER QUERY (RAW) ===\n" if raw_user_text != final_user_text else "=== USER QUERY ===\n")
                f.write(f"{user_text}\n\n")
                if raw_user_text != final_user_text: f.write(f"=== USER QUERY (SUMMARIZED) ===\n{final_user_text}\n\n")
                f.write(f"=== RESPONSE ===\n{response_text}\n")

        return (response_text, updated_history)

# ------------------------------------------------------------------------------------
# PromptCrafter_Captioner Node
# ------------------------------------------------------------------------------------
class PromptCrafter_Captioner:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vision_model": (api_clients.get_vision_models(), {"dynamic": True, "tooltip": "The vision language model (VLM) to use for captioning."}),
            },
            "optional": {
                "image": ("IMAGE", {"tooltip": "The image to be captioned (for single mode)."}),
                "filename": ("STRING", {"default": "", "tooltip": "Filename for single mode (ignored in batch mode). If empty, a timestamp is used."}),
                "batch_mode": ("BOOLEAN", {"default": False, "tooltip": "Enable batch processing of an entire folder."}),
                "input_folder": ("STRING", {"default": "input/captions_todo", "tooltip": "Directory of images to process in batch mode (relative to ComfyUI root)."}),
                "skip_existing": ("BOOLEAN", {"default": True, "tooltip": "In batch mode, skip images that already have a corresponding .txt caption file."}),
                "max_workers": ("INT", {"default": 4, "min": 1, "max": 16, "step": 1, "tooltip": "Number of parallel threads for batch processing."}),
                "api_concurrency": ("INT", {"default": 5, "min": 1, "max": 16, "step": 1, "tooltip": "Max concurrent API requests for remote models (OpenAI, Anthropic, etc.) to avoid rate limiting."}),
                "caption_prompt": ("STRING", {"multiline": True, "default": DEFAULT_CAPTION_PROMPT, "tooltip": "The prompt template used to guide the captioning model."}),                
                "caption_prefix": ("STRING", {"multiline": False, "default": "", "tooltip": "A single trigger word to add to every caption. Overridden by the trigger words file."}),
                "trigger_words_folder_path": ("STRING", {"multiline": False, "default": "input", "tooltip": "Folder containing an optional file of trigger words (one per line)."}),
                "trigger_words_file": ("STRING", {"multiline": False, "default": "<none>", "tooltip": "File with a list of trigger words to be randomly chosen from for each caption."}),
                "save_caption": ("BOOLEAN", {"default": True, "tooltip": "Save the caption to a text file."}),                
                "output_path": ("STRING", {"default": "captions", "tooltip": "Subdirectory within ComfyUI/output to save caption files."}),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Controls creativity. Lower is more deterministic."}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "step": 1, "tooltip": "Seed for reproducible results. -1 for random."}),
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10, "tooltip": "Timeout in seconds for each API call. Increase if you get timeout errors with slow models."}),
                "safe_mode": ("BOOLEAN", {"default": True, "tooltip": "Enforce SFW rules to prevent NSFW, violent, or controversial content."}),
                "use_chat_api": ("BOOLEAN", {"default": False, "tooltip": "Use the /api/chat endpoint. Better for models fine-tuned for chat."}),
                "debug_mode": ("BOOLEAN", {"default": False, "tooltip": "Print all intermediate prompts to the console for debugging."}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("caption",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️/PromptCrafter"

    def _caption_one_image(self, image_tensor, model, final_caption_prompt, use_chat_api, temperature, seed, debug_mode, timeout):
        is_api_model = "/" in model
        first_image = image_tensor[0] if torch.is_tensor(image_tensor) and image_tensor.ndim == 4 else image_tensor
        ok, caption = api_clients.query_model_auto(model, prompt=final_caption_prompt, images=[first_image], prefer_chat=(use_chat_api or is_api_model), temperature=temperature, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title="Image Caption Prompt")
        if not ok: return False, f"Model error: {caption}"
        return True, utils.TextCleaner.single_paragraph(caption)

    def _process_single_batch_item(self, img_filename, full_folder_path, out_dir, model, final_caption_prompt, use_chat_api, temperature, seed, debug_mode, caption_prefix, trigger_words, save_caption, timeout, semaphore):
        try:
            base_fname, _ = os.path.splitext(img_filename)
            caption_filepath = os.path.join(out_dir, f"{base_fname}.txt")
            img_path = os.path.join(full_folder_path, img_filename)
            pil_image = Image.open(img_path).convert("RGB") # This can raise exceptions
            image_tensor = comfy.utils.pil2tensor(pil_image)
            
            if semaphore: semaphore.acquire()
            try:
                ok, caption_text = self._caption_one_image(image_tensor, model, final_caption_prompt, use_chat_api, temperature, seed, debug_mode, timeout)
            finally:
                if semaphore: semaphore.release()
            
            if not ok: return "failed", f"Failed to caption {img_filename}: {caption_text}"

            final_caption = caption_text
            current_prefix = caption_prefix
            if trigger_words: current_prefix = random.choice(trigger_words)
            if current_prefix: final_caption = f"{current_prefix.strip()}, {final_caption}"

            if save_caption:
                with open(caption_filepath, "w", encoding="utf-8") as f: f.write(final_caption)
            
            return "success", img_filename
        except Exception as e:
            return "failed", f"Error processing {img_filename}: {e}"

    def execute(self, vision_model, image=None, batch_mode=False, input_folder=None, skip_existing=True, max_workers=4, api_concurrency=5, caption_prompt=DEFAULT_CAPTION_PROMPT, caption_prefix="", trigger_words_folder_path="input", trigger_words_file="<none>", save_caption=True, output_path="captions", filename="", temperature=0.2, debug_mode=False, safe_mode=True, seed=-1, use_chat_api=False, timeout=120):
        model = vision_model or config.FALLBACK_VISION_MODEL
        final_caption_prompt = caption_prompt
        if safe_mode and config.SAFE_MODE_RULE not in final_caption_prompt:
            final_caption_prompt = f"{final_caption_prompt}\n{config.SAFE_MODE_RULE}"

        trigger_words = []
        if trigger_words_folder_path and trigger_words_file and trigger_words_file != "<none>":
            full_folder_path = trigger_words_folder_path if os.path.isabs(trigger_words_folder_path) else os.path.join(config.COMFYUI_ROOT_DIR, trigger_words_folder_path)
            fpath = os.path.join(full_folder_path, trigger_words_file)
            if os.path.exists(fpath):
                content = utils.safe_read(fpath)
                if not content.startswith("[Error"):
                    trigger_words = [line.strip() for line in content.splitlines() if line.strip()]
                    if trigger_words: print(f"\033[92m[PromptCrafter] Loaded {len(trigger_words)} trigger words from {trigger_words_file}.\033[0m")
            else:
                print(f"\033[93m[PromptCrafter] Warning: Trigger words file not found at '{fpath}'.\033[0m")

        if batch_mode:
            if not input_folder: return ("Batch mode is enabled, but no input folder was provided.",)
            full_folder_path = input_folder if os.path.isabs(input_folder) else os.path.join(config.COMFYUI_ROOT_DIR, input_folder)
            if not os.path.isdir(full_folder_path): return (f"Input folder not found: {full_folder_path}",)

            base_dir = os.path.join(config.COMFYUI_ROOT_DIR, "output")
            safe_subdir = os.path.normpath(output_path.strip()).lstrip('.').lstrip('/')
            out_dir = os.path.join(base_dir, safe_subdir)
            os.makedirs(out_dir, exist_ok=True)

            all_image_files = [f for f in os.listdir(full_folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp'))]
            if not all_image_files: return (f"No images found in {full_folder_path}",)

            files_to_process = all_image_files
            skipped_count = 0
            if skip_existing:
                files_to_process = []
                for img_filename in all_image_files:
                    base_fname, _ = os.path.splitext(img_filename)
                    if os.path.exists(os.path.join(out_dir, f"{base_fname}.txt")):
                        skipped_count += 1
                    else:
                        files_to_process.append(img_filename)
            
            if not files_to_process:
                return (f"Batch complete. All {len(all_image_files)} image(s) were already captioned.",)

            semaphore = threading.Semaphore(api_concurrency) if "/" in model else None
            if semaphore: print(f"\033[94m[PromptCrafter] Remote API detected. Limiting concurrent requests to {api_concurrency}.\033[0m")

            pbar = comfy.utils.ProgressBar(len(files_to_process))
            processed_count, failed_count, failed_files = 0, 0, []
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(self._process_single_batch_item, img, full_folder_path, out_dir, model, final_caption_prompt, use_chat_api, temperature, seed, debug_mode, caption_prefix, trigger_words, save_caption, timeout, semaphore): img for img in files_to_process}
                for future in concurrent.futures.as_completed(futures):
                    img_filename = futures[future]
                    try:
                        status, result = future.result()
                        if status == "success": processed_count += 1; print(f"\033[92m[PromptCrafter] Captioned: {result}\033[0m")
                        elif status == "failed": failed_count += 1; failed_files.append(img_filename); print(f"\033[93m[PromptCrafter] Warning: {result}\033[0m")
                    except Exception as e:
                        failed_count += 1; failed_files.append(img_filename); print(f"\033[91m[PromptCrafter] An unexpected error occurred for {img_filename}: {e}\033[0m")
                    pbar.update(1)

            status_message = f"Batch complete. Total found: {len(all_image_files)}. Processed: {processed_count}."
            if failed_count > 0:
                failed_files_str = ", ".join(failed_files[:5])
                if failed_count > 5: failed_files_str += f", and {failed_count - 5} more"
                status_message += f" Failed: {failed_count} ({failed_files_str}). Check console for details."
            else:
                status_message += " Failed: 0."
            if skipped_count > 0: status_message += f" Skipped: {skipped_count}."
            return (status_message,)
        else:
            if image is None: return ("No image provided for single captioning mode.",)
            ok, caption = self._caption_one_image(image, model, final_caption_prompt, use_chat_api, temperature, seed, debug_mode, timeout)
            if not ok: return (caption,)

            final_caption = caption
            current_prefix = caption_prefix
            if trigger_words: current_prefix = random.choice(trigger_words)
            if current_prefix: final_caption = f"{current_prefix.strip()}, {final_caption}"

            if save_caption:
                base_dir = os.path.join(config.COMFYUI_ROOT_DIR, "output")
                safe_subdir = os.path.normpath(output_path.strip()).lstrip('.').lstrip('/')
                out_dir = os.path.join(base_dir, safe_subdir)
                os.makedirs(out_dir, exist_ok=True)
                fname = filename.strip() or f"caption_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time()*1000)%1000}"
                fname = re.sub(r'[\\/*?:"<>|]', "", fname)
                with open(os.path.join(out_dir, f"{fname}.txt"), "w", encoding="utf-8") as f: f.write(final_caption)
            
            return (final_caption,)

# ------------------------------------------------------------------------------------
# Creator Nodes
# ------------------------------------------------------------------------------------
class PromptCrafter_BaseCreator:
    """A base class containing shared logic for visual prompt creation nodes."""

    def _collect_images_with_weights(self, image_count=1, image_weights_json="{}", **kwargs):
        images_with_weights = []
        try:
            weights = json.loads(image_weights_json)
        except (json.JSONDecodeError, TypeError):
            weights = {}
            print(f"\033[93m[PromptCrafter] Warning: Could not parse image_weights_json. Using default weights. Value: {image_weights_json}\033[0m")

        for i in range(1, image_count + 1):
            image = kwargs.get(f"image_{i}")
            if image is not None:
                weight = float(weights.get(f"image_weight_{i}", 1.0))
                images_with_weights.append((image, weight))
        return images_with_weights

    def _prepare_run_parameters(self, prompt_type, temperature, use_chat_api, max_length_words, original_temp, original_max_len):
        if temperature == original_temp:
            if prompt_type == "Video": temperature, use_chat_api = 0.4, True
        if max_length_words == original_max_len:
            if prompt_type == "Image": max_length_words = 200
            elif prompt_type == "Video": max_length_words = 80
            elif prompt_type == "Lyrics": max_length_words = 100
        return temperature, use_chat_api, max_length_words

    def _setup_config(self, mode, user_text, vision_model, images_with_weights, **kwargs):
        has_images = any(img is not None for img, _ in images_with_weights)

        # If images are provided, we MUST have a working vision model.
        if has_images:
            if not vision_model or "NO_MODELS_FOUND" in vision_model or "OLLAMA_OFFLINE" in vision_model:
                raise ValueError("Image(s) provided, but no vision models found or Ollama is unreachable. Please install a vision model (e.g., 'ollama run llava') or configure a remote API key.")

            available_vision_models = api_clients._get_models_by_type("vision")
            if vision_model not in available_vision_models:
                fallback = next((m for m in available_vision_models if "llava" in m), available_vision_models[0] if available_vision_models else config.FALLBACK_VISION_MODEL)
                raise ValueError(f"Image(s) provided, but model '{vision_model}' is not a vision model. Please select a vision-capable model (e.g., '{fallback}').")

        original_temp = self.INPUT_TYPES()["required"]["temperature"][1]["default"]
        original_max_len = self.INPUT_TYPES()["required"]["max_length_words"][1]["default"]
        temperature, use_chat_api, max_length_words = self._prepare_run_parameters(mode, kwargs.get('temperature'), kwargs.get('use_chat_api'), kwargs.get('max_length_words'), original_temp, original_max_len)
        
        config_params = kwargs.copy()
        # The model used for generation is the one selected in the UI.
        # The vision_model check above is only for image analysis.
        model_to_use = vision_model
        config_params.update({'model': model_to_use, 'language': utils._detect_language(user_text), 'temperature': temperature, 'use_chat_api': use_chat_api, 'max_length_words': max_length_words})
        run_config = config.PromptCrafterRunConfig(**config_params)

        if run_config.style_override and run_config.style_override != "None":
            original_name = re.sub(r'^\(.*\)\s', '', run_config.style_override)
            if original_name in config.NAMED_STYLE_PROFILES:
                run_config.style_profile = config.NAMED_STYLE_PROFILES[original_name]
        
        return run_config

    def _describe_one_image_with_persona(self, img, weight, idx, run_config):
        style_engine = StyleEngine(run_config.model, run_config.use_chat_api, run_config.temperature, run_config.seed, image=img, debug_mode=run_config.debug_mode, timeout=run_config.timeout)
        persona = f"You are a Director of Photography analyzing a frame. {style_engine.get_persona()}"

        safety_rule = f"\n{config.SAFE_MODE_RULE}" if run_config.safe_mode else ""
        desc_template = textwrap.dedent(f"""
            {persona}
            Your task is to perform a highly detailed and accurate analysis of Image {idx}.
            Break down your analysis into the following components:
            1.  **Primary Subject**: Identify the single most important subject or focal point. Be specific (e.g., "a woman with red hair" not just "a woman").
            2.  **Secondary Subjects**: List any other relevant subjects, characters, or objects.
            3.  **Setting**: Describe the environment and background.
            4.  **Composition**: Explain how the subjects are arranged in the frame (e.g., rule of thirds, centered, off-center).
            5.  **Lighting**: Describe the lighting style (e.g., soft, harsh, dramatic, natural) and light sources.
            6.  **Artistic Style**: Identify the overall style (e.g., photorealistic, anime, watercolor, cinematic).
            7.  **Full Description**: Synthesize all the above points into a single, cohesive, and detailed paragraph.
            8.  **Transcription**: If there is any readable text, transcribe it exactly.

            Return ONLY a JSON object with the following keys: "primary_subject", "secondary_subjects", "setting", "composition", "lighting", "style", "full_description", "transcription".
            The final output must be in {run_config.language} only.{safety_rule}
        """).strip()
        
        reason_kwargs = {"use_chat_api": run_config.use_chat_api, "temperature": run_config.temperature, "seed": run_config.seed, "timeout": run_config.timeout, "debug_mode": run_config.debug_mode, "debug_title": f"Image Description {idx}"}
        ok, result_json = api_clients._reason_with_model(run_config.model, desc_template, images=[img], **reason_kwargs)

        if ok and isinstance(result_json, dict):
            full_desc = result_json.get('full_description')
            if not full_desc:
                parts = [result_json.get('primary_subject'), result_json.get('setting'), f"Composition: {result_json.get('composition')}", f"Lighting: {result_json.get('lighting')}", f"Style: {result_json.get('style')}"]
                full_desc = ". ".join(p for p in parts if p)
            transcription = result_json.get('transcription')
            if transcription: full_desc += f" Text in image: '{transcription}'"
            return {"full_text": f"Image {idx} (Weight: {weight:.2f}): {utils.TextCleaner.single_paragraph(full_desc)}", "primary_subject": result_json.get("primary_subject", "")}
        else:
            return {"full_text": f"Image {idx} (Weight: {weight:.2f}): [Error describing image: {result_json}]", "primary_subject": ""}

    def _describe_images(self, images_with_weights, run_config):
        if not images_with_weights: return "No reference images provided.", []

        images = [img for img, _ in images_with_weights]
        weights = [w for _, w in images_with_weights]
        cache_key = utils._get_cache_key(images, weights, run_config.model, run_config.use_chat_api, run_config.temperature, run_config.language, run_config.safe_mode, run_config.seed, "describe_images_v4_parallel")
        if config.CACHE.has(cache_key):
            print("\033[94m[PromptCrafter] Using cached image descriptions and primary subjects.\033[0m")
            return config.CACHE.get(cache_key)

        images_to_process = [(img, weight, idx) for idx, (img, weight) in enumerate(images_with_weights, start=1) if weight > 0]
        if not images_to_process: return "No reference images provided.", []

        print(f"\033[94m[PromptCrafter] Describing {len(images_to_process)} image(s) in parallel...\033[0m")
        description_objects = [None] * len(images_to_process)
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(images_to_process)) as executor:
            future_to_index = {executor.submit(self._describe_one_image_with_persona, img, weight, idx, run_config): i for i, (img, weight, idx) in enumerate(images_to_process)}
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    description_objects[index] = future.result()
                except Exception as exc:
                    print(f"\033[91m[PromptCrafter] An unexpected error occurred while describing image {index + 1}: {exc}\033[0m")
                    description_objects[index] = {"full_text": f"Image {index + 1}: [Error describing image: {exc}]", "primary_subject": ""}
        
        full_text_descriptions = [d.get("full_text", "") for d in description_objects if d]
        primary_subjects = [d.get("primary_subject", "") for d in description_objects if d and d.get("primary_subject")]
        
        result_text = "\n\n".join(full_text_descriptions)
        result_tuple = (result_text, primary_subjects)
        config.CACHE.set(cache_key, result_tuple)
        return result_tuple

    def _handle_scheduled_mode(self, mode, user_text, images_with_weights, run_config, **kwargs):
        images = [img for img, _ in images_with_weights]
        image_context_for_all, primary_subjects_from_images = self._describe_images(images_with_weights, run_config)
        style_rules = self._build_style_and_composition_rules(mode, images, run_config, user_text, "", image_context_for_all)
        base_negative_prompt = utils._generate_negative_prompt(user_text, run_config, user_negative_prompt=kwargs.get("negative_prompt", ""))

        if '\n\n' in user_text:
            print("\033[94m[PromptCrafter] Multi-paragraph input detected. Using manual scene breaks.\033[0m")
            scenes = [p.strip() for p in user_text.split('\n\n') if p.strip()]
        else:
            if not user_text or len(user_text.split()) < 20:
                scenes = utils._generate_storyboard_from_instruction_with_ai(user_text, image_context_for_all, primary_subjects_from_images, run_config)
            else:
                print("\033[94m[PromptCrafter] Attempting to split single-paragraph story into scenes with AI...\033[0m")
                scenes = utils._split_text_into_scenes_with_ai(user_text, run_config)

        if not scenes: return ("", "AI failed to generate a storyboard. Please try rephrasing your request or check the model.", "", "")

        print(f"\033[94m[PromptCrafter] Schedule mode enabled. Generating prompts for {len(scenes)} scenes...\033[0m")

        generated_prompts = [None] * len(scenes)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(scenes))) as executor:
            future_to_index = {executor.submit(self._generate_prompt_for_scene, scene, mode, images_with_weights, image_context_for_all, style_rules, run_config, **kwargs): i for i, scene in enumerate(scenes)}
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    generated_prompts[index] = future.result()
                    print(f"\033[92m[PromptCrafter] Finished processing scene {index + 1}/{len(scenes)}.\033[0m")
                except Exception as exc:
                    error_msg = f"[Error processing scene {index + 1}: {exc}]"
                    generated_prompts[index] = error_msg
                    print(f"\033[91m[PromptCrafter] {error_msg}\033[0m")

        if not any(p for p in generated_prompts if p and not p.startswith("[Error")):
            return ("", "Failed to generate prompts for any of the scenes. Please check the model and logs.", image_context_for_all, base_negative_prompt)

        schedule_json = utils._create_schedule_from_items(generated_prompts, kwargs.get("max_frames", 240), 0, kwargs.get("interpolate_keyframes", True), kwargs.get("interpolation_frame_interval", 10))
        
        if kwargs.get("save_to_txt", False) and schedule_json:
            utils._save_output_to_file(kwargs.get("filename_prefix"), [("USER TEXT", user_text), ("IMAGE CONTEXT", image_context_for_all), ("NEGATIVE PROMPT", base_negative_prompt), ("SCHEDULE", schedule_json)], base_filename="schedule")

        return ("", schedule_json, image_context_for_all, base_negative_prompt)

    def _generate_visual_prompt_pipeline(self, mode, user_text, images_with_weights, save_to_txt, filename_prefix, run_config, negative_prompt="", **kwargs):
        images = [img for img, _ in images_with_weights]
        has_text = user_text and user_text.strip() and user_text.strip() != config.DEFAULT_PROMPT_TEXT
        if not images and not kwargs.get("style_reference_image") and not has_text:
            return ("No inputs provided. Please connect at least one main image, a style reference image, or provide user text.", "", "")
            
        image_context, user_instructions, user_context, mandatory_tokens, primary_subjects_from_images = self._prepare_visual_prompt_context(user_text, images_with_weights, run_config)

        ok_draft, draft_or_err = self._generate_initial_draft(mode, user_instructions, user_context, image_context, mandatory_tokens, images, run_config, primary_subjects_from_images)
        if not ok_draft: return (draft_or_err, image_context, "")
        scene_prompt = draft_or_err

        style_rules = self._build_style_and_composition_rules(mode, images, run_config, user_instructions, user_context, image_context)
        scene_prompt = self._refine_image_video_prompt(scene_prompt, mode, mandatory_tokens, style_rules, run_config)
        
        new_positive, counter_negatives = utils._simplify_for_diffusion(scene_prompt, user_text, run_config)
        scene_prompt = new_positive

        combined_negative_input = f"{negative_prompt}, {counter_negatives}".strip().strip(',')
        final_negative_prompt = self._finalize_visual_prompt_output(scene_prompt, image_context, user_text, mandatory_tokens, run_config, save_to_txt, filename_prefix, user_negative_prompt=combined_negative_input)

        return (scene_prompt, image_context, final_negative_prompt)

    # --- Methods below are helpers for the main pipeline ---

    def _prepare_visual_prompt_context(self, user_text, images_with_weights, run_config):
        image_context, primary_subjects_from_images = self._describe_images(images_with_weights, run_config)
        user_instructions, user_context = user_text, ""
        tok_ok, tokens_or_msg = utils._extract_mandatory_tokens_with_model(image_context, user_text, run_config)
        mandatory_tokens = tokens_or_msg if tok_ok else {"primary": [], "secondary": [], "allowed_list": []}
        return image_context, user_instructions, user_context, mandatory_tokens, primary_subjects_from_images

    def _generate_initial_draft(self, mode, user_instructions, user_context, image_context, mandatory_tokens, images, run_config, primary_subjects_from_images=None):
        merge_prompt = self._build_initial_merge_prompt(mode, user_instructions, user_context, image_context, mandatory_tokens, images, run_config, primary_subjects_from_images)
        gen_kwargs = {"prefer_chat": run_config.use_chat_api, "temperature": run_config.temperature, "seed": run_config.seed, "timeout": 120, "debug_mode": run_config.debug_mode}
        if run_config.use_deep_think:
            print("\033[94m[PromptCrafter] Deep Think enabled. Starting iterative refinement...\033[0m")
            gen_kwargs.update({"debug_title": f"Initial {mode} Prompt (Deep Think)", "images": images})
            ok, scene_prompt = utils._deep_think_and_refine(run_config.model, merge_prompt, max_iterations=3, confidence_threshold=run_config.deep_think_confidence, **gen_kwargs)
        else:
            gen_kwargs["debug_title"] = f"Initial {mode} Prompt"
            ok, scene_prompt = api_clients.query_model_auto(run_config.model, merge_prompt, **gen_kwargs)
        if not ok: return False, f"Model error: {scene_prompt}"
        return True, utils.TextCleaner.single_paragraph(scene_prompt)

    def _finalize_visual_prompt_output(self, scene_prompt, image_context, user_text, mandatory_tokens, run_config, save_to_txt, filename_prefix, user_negative_prompt=""):
        final_negative_prompt = utils._generate_negative_prompt(scene_prompt, run_config, user_negative_prompt=user_negative_prompt)
        if save_to_txt and scene_prompt and scene_prompt.strip():
            sections = [("IMAGE CONTEXT", image_context)]
            if user_text and user_text.strip() and user_text.strip() != config.DEFAULT_PROMPT_TEXT: sections.append(("USER TEXT", user_text))
            if mandatory_tokens:
                all_tokens = mandatory_tokens.get("primary", []) + mandatory_tokens.get("secondary", [])
                if all_tokens: sections.append(("EXTRACTED TOKENS", "\n".join(all_tokens)))
            sections.append(("NEGATIVE PROMPT", final_negative_prompt))
            sections.append(("SCENE PROMPT", scene_prompt))
            utils._save_output_to_file(filename_prefix, sections, base_filename="scene_prompt")
        return final_negative_prompt

    def _get_base_composition_rules(self, language):
        return [
            "- The primary subject(s) from the USER INSTRUCTIONS must be the clear focal point of the composition, correctly scaled and prominently featured.",
            "- Include ONLY characters/objects explicitly requested in USER INSTRUCTIONS.",
            "- Do NOT include secondary figures unless explicitly mentioned or essential.",
            "- Enforce cinematic depth: foreground, midground, background with natural scale and occlusion.",
            "- Dynamic composition that guides the viewer’s eye (rule of thirds, triangular balance, or S-curve).",
            "- Figures must interact or contrast for narrative depth (conflict, harmony, guardianship).",
            "- Dramatic, photorealistic lighting with clear key light, rim light, and atmospheric mood.",
            "- Maintain stylistic and subject consistency (temporal stability in video).",
            "- Do NOT reference source images (e.g., 'the man from image 1'); describe a single, unified scene.",
            f"- CRITICAL: The final prompt must be in {language} only. No other languages.",
            "- One flowing paragraph only.",
        ]

    def _get_video_specific_rules(self, run_config, user_instructions="", user_context="", image_context=""):
        cinematography_analysis_prompt = textwrap.dedent(f"""
            You are an expert Director of Photography. Analyze the provided scene context to design a single, compelling cinematic shot.
            --- SCENE CONTEXT ---\nUser Instructions: {user_instructions}\nImage Descriptions: {image_context}\n--- END SCENE CONTEXT ---
            Based on the context, make a professional choice for each of the following cinematography elements:
            1.  **Shot Type**: Choose ONE that best fits the mood (e.g., "Extreme Close-Up", "Close-Up", "Medium Shot", "Full Shot", "Wide Shot", "Establishing Shot").
            2.  **Lens Style**: Choose ONE lens style to suggest (e.g., "Wide-Angle Lens (e.g., 24mm)", "Standard Lens (e.g., 50mm)", "Telephoto Lens (e.g., 85mm)", "Anamorphic Lens").
            3.  **Camera Movement**: Choose ONE specific movement (e.g., "Static Shot", "Slow Pan", "Whip Pan", "Tracking Shot", "Dolly Zoom", "Crane Shot", "Handheld").
            4.  **Lighting Style**: Choose ONE descriptive style (e.g., "High-Key Lighting", "Low-Key Lighting (Chiaroscuro)", "Soft, Diffused Light", "Hard, Direct Light", "Golden Hour Lighting", "Blue Hour Lighting").

            Return ONLY a JSON object with your four choices. Example: {{"shot_type": "Medium Shot", "lens_style": "Standard Lens (e.g., 50mm)", "camera_movement": "Slow Pan", "lighting_style": "Low-Key Lighting (Chiaroscuro)"}}
        """).strip()
        ok, result_json = api_clients._reason_with_model(run_config.model, cinematography_analysis_prompt, run_config.use_chat_api, 0.1, run_config.seed, debug_mode=run_config.debug_mode, debug_title="Video Cinematography Analysis")
        
        cinematography_rules = []
        if ok and isinstance(result_json, dict):
            shot_type = result_json.get("shot_type", "Medium Shot")
            lens_style = result_json.get("lens_style", "Standard Lens (e.g., 50mm)")
            camera_movement = result_json.get("camera_movement", "Static Shot")
            lighting_style = result_json.get("lighting_style", "Soft, Diffused Light")
            cinematography_rules.append(f"- **Shot Design**: The scene should be framed as a '{shot_type}' using a '{lens_style}'.")
            cinematography_rules.append(f"- **Camera Work**: Incorporate a '{camera_movement}' to establish the scene's energy.")
            cinematography_rules.append(f"- **Lighting**: The scene must be lit with '{lighting_style}'.")
        
        return ["- Role: Expert Director of Photography designing a shot.", "- Use Wan2.2 formula: [Cinematic Shot] + [Primary Subject & Detailed Description] + [Scene & Environment] + [Detailed Action & Physics-Based Motion] + [Camera Movement & Angle] + [Visual Style & Aesthetic Controls] + [Atmosphere & Mood].", "- CRITICAL PRIORITY: Emphasize the subject's ACTIONS and the PHYSICS of their movement. Describe motion with active verbs and adverbs (e.g., 'a warrior lunging forward, sword gleaming')."] + cinematography_rules

    def _build_style_and_composition_rules(self, mode, images, run_config, user_instructions="", user_context="", image_context=""):
        all_rules = []
        if run_config.safe_mode: all_rules.append(config.SAFE_MODE_RULE)
        if mode == "Video": all_rules.extend(self._get_video_specific_rules(run_config, user_instructions, user_context, image_context))
        all_rules.extend(self._get_base_composition_rules(run_config.language))
        if run_config.style_profile:
            inspiration = run_config.style_profile.get("inspiration", "")
            if inspiration: all_rules.append(f"- {inspiration}")
        elif run_config.style_override != "None" and run_config.style_override in config.STYLE_KEYWORDS:
            all_rules.append(f"- Style: {config.STYLE_KEYWORDS[run_config.style_override]}")
        else:
            style_engine = StyleEngine(run_config.model, run_config.use_chat_api, run_config.temperature, run_config.seed, image=images[0] if images else None, debug_mode=run_config.debug_mode, timeout=run_config.timeout)
            all_rules.extend(style_engine.get_composition_rules())
        return all_rules

    def _build_initial_merge_prompt(self, mode, user_instructions, user_context, image_context, mandatory_tokens, images, run_config, primary_subjects_from_images=None):
        style_composition_rules = self._build_style_and_composition_rules(mode, images, run_config, user_instructions, user_context, image_context)
        if run_config.negative_concepts: style_composition_rules.insert(0, f"- CRITICAL: Do NOT include any of the following concepts: {run_config.negative_concepts}")
        style_composition_rules_str = "\n".join(style_composition_rules)
        core_scene_text = f"{user_instructions}\n\n{user_context}" if user_context else user_instructions
        has_instructions = core_scene_text and core_scene_text.strip() and core_scene_text.strip() != config.DEFAULT_PROMPT_TEXT
        
        task_rules = []
        if has_instructions and len(images) > 0:
            task_rules.append("1.  The USER INSTRUCTIONS are your primary guide. The final prompt MUST fulfill the user's core request.")
            task_rules.append("2.  Use the PRIMARY SUBJECTS and INSPIRATIONAL CONTEXT to flesh out the scene, but only in ways that support and do not contradict the USER INSTRUCTIONS.")
        elif len(images) == 1:
            task_rules.append("1.  **Creative Inspiration Task:** You have been given a single reference image. Do NOT simply describe it. Instead, create a **new, imaginative scene** that is *inspired by* the subject, style, and mood of the reference image. For example, if the image is a portrait of a knight, you could create a scene of that knight on a new quest in a different location.")
            task_rules.append("2.  Use the INSPIRATIONAL CONTEXT to understand the details of the original image, then build your new scene from there.")
        else:
            task_rules.append("1.  Create a **new, single, coherent scene** that features ALL of the mandatory PRIMARY SUBJECTS interacting or co-existing in a plausible way.")
            task_rules.append("2.  Use the INSPIRATIONAL CONTEXT to flesh out the environment, lighting, and mood.")

        task_rules.extend(["3.  Design a single, cinematic shot as a flowing paragraph.", "4.  Integrate the `STYLE & COMPOSITION RULES` into your final shot design."])
        task_rules_str = "\n".join(task_rules)

        user_instructions_section = f"**USER INSTRUCTIONS (Primary Goal)**\n---\n{core_scene_text}\n---\n" if has_instructions else ""

        merge_template = textwrap.dedent(f"""
            You are an expert Director of Photography. Your task is to design a single, coherent, and detailed cinematic shot by synthesizing the provided creative elements.
            **PRIMARY SUBJECTS (Mandatory Building Blocks)**\nYour final scene MUST include all of the following primary subjects:\n{json.dumps(primary_subjects_from_images or [])}
            {user_instructions_section}
            **INSPIRATIONAL CONTEXT (For Atmosphere and Style ONLY)**\nUse the following full descriptions of the reference images to build the world around the primary subjects.\n---\n{image_context}\n---
            **YOUR TASK:**\n{task_rules_str}
            --- STYLE & COMPOSITION RULES ---\n{style_composition_rules_str}\n---
            Return ONLY the final, polished prompt.
        """).strip()
        return merge_template

    def _refine_image_video_prompt(self, draft_prompt, mode, mandatory_tokens, style_rules, run_config):
        current_prompt = draft_prompt
        primary_items_list = [re.sub(r'^\[PRIMARY\]\s*', '', t) for t in (mandatory_tokens or {}).get("primary", [])]
        if not primary_items_list:
            critique_prompt = self._build_refinement_prompt(current_prompt, mode, [], [], style_rules, run_config, ask_for_json=False)
            ok, revised_prompt = api_clients.query_model_auto(run_config.model, critique_prompt, prefer_chat=run_config.use_chat_api, temperature=run_config.temperature, seed=run_config.seed, timeout=90, debug_mode=run_config.debug_mode, debug_title="Image/Video Refine (Single Pass)")
            return utils.TextCleaner.single_paragraph(revised_prompt) if ok else current_prompt

        all_allowed = (mandatory_tokens or {}).get("allowed_list", [])
        for i in range(run_config.max_retries + 1):
            critique_prompt = self._build_refinement_prompt(current_prompt, mode, primary_items_list, all_allowed, style_rules, run_config, ask_for_json=True)
            reason_kwargs = {"use_chat_api": run_config.use_chat_api, "temperature": run_config.temperature, "seed": run_config.seed, "timeout": 90, "debug_mode": run_config.debug_mode, "debug_title": f"Image/Video Refine & Check (Try {i+1})"}
            ok, result_json = api_clients._reason_with_model(run_config.model, critique_prompt, **reason_kwargs)
            if not ok or not isinstance(result_json, dict):
                print(f"\033[93m[PromptCrafter] Warning: Refinement step failed to return valid JSON. Using previous version. Error: {result_json}\033[0m")
                return current_prompt
            current_prompt = utils.TextCleaner.single_paragraph(result_json.get("refined_prompt", current_prompt))
            if not result_json.get("missing_items") and not result_json.get("hallucinated_items"):
                return current_prompt
        return current_prompt

    def _build_refinement_prompt(self, prompt_to_review, mode, primary_items, all_allowed_items, style_rules, run_config, ask_for_json=True):
        mode_specific_rule = "- The prompt must describe a single, static frame. Remove any video-like transition phrases (e.g., 'then', 'the scene shifts')." if mode == "Image" else "- The prompt must describe a continuous shot with clear subject motion."
        strength = run_config.critique_strength
        if strength == "Subtle": critique_instruction = "- Subtly refine the DRAFT PROMPT. Focus on improving wording, flow, and clarity. Do NOT make major structural changes or add new concepts."
        elif strength == "Heavy": critique_instruction = "- Radically revise the DRAFT PROMPT for maximum cinematic impact. You have creative freedom to restructure the scene, change the composition, and add descriptive flair, as long as you adhere to all MANDATORY SUBJECTS and rules."
        else: critique_instruction = "- Revise the DRAFT PROMPT to meet ALL of the requirements listed above.\n- Integrate mandatory subjects naturally.\n- Remove any hallucinated subjects not in the allowed list.\n- Apply all style and mode-specific rules.\n- Enhance the prompt for cinematic quality, clarity, and impact."
        
        json_return_format = textwrap.dedent("""
            INSTRUCTIONS:
            1. **Revise**: Revise the DRAFT PROMPT to meet ALL requirements.
            2. **Validate**: Check if the new prompt contains all **MANDATORY SUBJECTS** and no subjects NOT in the **ALLOWED SUBJECTS** list.
            3. **Return JSON**: Return ONLY a single JSON object with three keys: `refined_prompt` (string), `missing_items` (array of strings, should be `[]` on success), and `hallucinated_items` (array of strings, should be `[]` on success).
        """)
        text_return_format = f"INSTRUCTIONS:\n{critique_instruction}\n\nReturn ONLY the final, improved prompt. No commentary."
        final_instructions = json_return_format if ask_for_json else text_return_format

        style_rules_str = "\n".join(style_rules) # Fix for f-string backslash issue
        refine_template = textwrap.dedent(f"""
            You are a master prompt critic and editor, acting as a Director of Photography. Your task is to review and enhance the following DRAFT SHOT DESCRIPTION.
            --- DRAFT PROMPT ---\n{prompt_to_review}\n--- END DRAFT PROMPT ---
            --- REQUIREMENTS & RULES ---
            __MANDATORY_SUBJECTS_SECTION__
            __ALLOWED_SUBJECTS_SECTION__
            3. **MODE-SPECIFIC RULES:**\n- The final prompt is for an '{mode}' generation.\n{mode_specific_rule}
            4. **GENERAL STYLE & COMPOSITION RULES:**\n{style_rules_str}
            --- END REQUIREMENTS & RULES ---\n{final_instructions}
        """)

        mandatory_section = f'1. **MANDATORY SUBJECTS (CRITICAL):** The final prompt MUST include all of the following subjects: {json.dumps(primary_items)}\n' if primary_items else ""
        allowed_section = f'2. **ALLOWED SUBJECTS (Anti-Hallucination):** The prompt should ONLY contain subjects from this list. If the draft contains subjects not on this list, REMOVE them. Allowed list: {json.dumps(all_allowed_items)}\n' if all_allowed_items else ""
        
        refine_template = refine_template.replace("__MANDATORY_SUBJECTS_SECTION__\n", mandatory_section)
        refine_template = refine_template.replace("__ALLOWED_SUBJECTS_SECTION__\n", allowed_section)
        return refine_template

    def _generate_prompt_for_scene(self, scene_text, mode, images_with_weights, image_context_for_all, style_rules, run_config, **kwargs):
        config_key_parts = (run_config.model, run_config.language, run_config.temperature, run_config.use_chat_api, run_config.max_length_words, run_config.seed, run_config.max_retries, run_config.critique_strength, run_config.simplify_for_diffusion, run_config.use_deep_think, str(run_config.style_profile))
        cache_key = utils._get_cache_key("gen_prompt_for_scene_v1", scene_text, mode, images_with_weights, image_context_for_all, style_rules, config_key_parts)
        if config.CACHE.has(cache_key):
            print(f"\033[94m[PromptCrafter] Using cached prompt for scene: '{scene_text[:50]}...'\033[0m")
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
# Image & Video Creator Node Classes
# ------------------------------------------------------------------------------------
class PromptCrafter_ImageCreator(PromptCrafter_BaseCreator):
    @classmethod
    def INPUT_TYPES(cls):
        inputs = {
            "required": {
                "user_text": ("STRING", {"multiline": True, "default": config.DEFAULT_PROMPT_TEXT}),
                "vision_model": (api_clients.get_vision_models(), {"dynamic": True}),
                "image_count": ("INT", {"default": 1, "min": 0, "max": 8, "step": 1, "tooltip": "Number of image inputs to show. Use the 'Update Image Inputs' button to apply changes."}),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff}),
                "max_length_words": ("INT", {"default": 0, "min": 0, "max": 400, "step": 10}),
                "style_override": (config.get_style_override_options("Image"), {"default": "None"}),
                "critique_strength": (["Subtle", "Normal", "Heavy"], {"default": "Normal"}),
                "simplify_for_diffusion": ("BOOLEAN", {"default": True}),
                "use_deep_think": ("BOOLEAN", {"default": False}),
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10}),
                "max_retries": ("INT", {"default": 2, "min": 0, "max": 10}),
                "safe_mode": ("BOOLEAN", {"default": True}),
                "debug_mode": ("BOOLEAN", {"default": False}),
                "save_to_txt": ("BOOLEAN", {"default": False}),
                "filename_prefix": ("STRING", {"default": "scene_prompts"}),
            },
            "optional": {
                "image_weights_json": ("STRING", {"default": "{}", "multiline": True, "input": "hidden"}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
                "generate_schedule": ("BOOLEAN", {"default": False}),
                "max_frames": ("INT", {"default": 240, "min": 1, "max": 99999}),
                "interpolate_keyframes": ("BOOLEAN", {"default": True}),
                "interpolation_frame_interval": ("INT", {"default": 10, "min": 0, "max": 100}),
            },
        }
        return inputs

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "schedule", "image_context", "negative_prompt")
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️/PromptCrafter"

    def execute(self, user_text, vision_model, **kwargs):
        try:
            images_with_weights = self._collect_images_with_weights(**kwargs)
            run_config = self._setup_config("Image", user_text, vision_model, images_with_weights, **kwargs)
            if kwargs.get("generate_schedule"):
                return self._handle_scheduled_mode("Image", user_text, images_with_weights, run_config, **kwargs)
            else:
                prompt, image_context, negative_prompt = self._generate_visual_prompt_pipeline(mode="Image", user_text=user_text, images_with_weights=images_with_weights, run_config=run_config, **kwargs)
                return (prompt, "", image_context, negative_prompt)
        except ValueError as e:
            return (str(e), "", "", "")

class PromptCrafter_VideoCreator(PromptCrafter_BaseCreator):
    @classmethod
    def INPUT_TYPES(cls):
        # Identical to ImageCreator, just with different defaults for some fields
        types = PromptCrafter_ImageCreator.INPUT_TYPES()
        types["required"]["temperature"][1]["default"] = 0.4
        types["required"]["max_length_words"][1]["default"] = 0 # Auto will be 120
        types["required"]["style_override"] = (config.get_style_override_options("Video"), {"default": "None"})
        return types

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "schedule", "image_context", "negative_prompt")
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️/PromptCrafter"

    def execute(self, user_text, vision_model, **kwargs):
        try:
            images_with_weights = self._collect_images_with_weights(**kwargs)
            run_config = self._setup_config("Video", user_text, vision_model, images_with_weights, **kwargs)
            if kwargs.get("generate_schedule"):
                return self._handle_scheduled_mode("Video", user_text, images_with_weights, run_config, **kwargs)
            else:
                prompt, image_context, negative_prompt = self._generate_visual_prompt_pipeline(mode="Video", user_text=user_text, images_with_weights=images_with_weights, run_config=run_config, **kwargs)
                return (prompt, "", image_context, negative_prompt)
        except ValueError as e:
            return (str(e), "", "", "")

# ------------------------------------------------------------------------------------
# Lyrics Creator Node
# ------------------------------------------------------------------------------------
class PromptCrafter_LyricsCreator(PromptCrafter_BaseCreator):
    @classmethod
    def INPUT_TYPES(cls):
        # Similar to other creators but with lyrics-specific inputs
        types = PromptCrafter_ImageCreator.INPUT_TYPES()
        types["required"]["temperature"][1]["default"] = 0.5
        types["required"]["max_length_words"][1]["default"] = 100
        types["required"]["style_override"] = (config.get_style_override_options("Lyrics"), {"default": "None"})
        types["optional"].update({
            "audio_folder_path": ("STRING", {"default": "input/audio"}),
            "audio_file": ("STRING", {"default": "<none>"}),
            "lyrics_folder_path": ("STRING", {"default": "input/lyrics"}),
            "lyrics_file": ("STRING", {"default": "<none>"}),
            "song_length_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 3600.0, "step": 0.1}),
            "fps": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.5}),
        })
        # Set different defaults for scheduling
        types["optional"]["generate_schedule"][1]["default"] = True
        types["optional"]["interpolate_keyframes"][1]["default"] = False
        types["optional"]["interpolation_frame_interval"][1]["default"] = 0
        return types

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "schedule", "image_context", "negative_prompt")
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️/PromptCrafter"

    def execute(self, user_text, vision_model, **kwargs):
        try:
            images_with_weights = self._collect_images_with_weights(**kwargs)
            run_config = self._setup_config("Lyrics", user_text, vision_model, images_with_weights, **kwargs)
            lyrics_text, timed_segments, lyrics_meta = utils._get_lyrics_from_input(user_text, kwargs.get("lyrics_folder_path"), kwargs.get("lyrics_file"), run_config.debug_mode)
            audio_path = utils._get_audio_path(kwargs.get("audio_folder_path"), kwargs.get("audio_file"))

            prompt, schedule, image_context, negative_prompt = self._handle_lyrics_mode(lyrics=lyrics_text, timed_segments=timed_segments, images_with_weights=images_with_weights, user_instructions=user_text, lyrics_meta=lyrics_meta, run_config=run_config, audio_path=audio_path, **kwargs)
            return (prompt, schedule, image_context, negative_prompt)
        except ValueError as e:
            return (str(e), "", "", "")

    def _handle_lyrics_mode(self, lyrics, timed_segments, images_with_weights, user_instructions, lyrics_meta, run_config, audio_path=None, **kwargs):
        if not lyrics or not lyrics.strip() or lyrics.startswith("[Error"):
            return (f"Failed to process lyrics input: {lyrics}", "", "No reference images provided.", "")

        image_context, mandatory_tokens, style_inspiration_section, instructions_section, context_section = self._prepare_lyrics_generation_context(user_instructions, images_with_weights, lyrics, run_config)
        
        theme_ok, global_theme_or_err = self._generate_storyboard_global_theme(lyrics, instructions_section, context_section, image_context, run_config)
        if not theme_ok: return (global_theme_or_err, "", image_context, "")

        storyboard_prompts = self._process_lyrics_storyboard(lyrics, timed_segments, global_theme_or_err, mandatory_tokens, style_inspiration_section, run_config)
        if not storyboard_prompts or (isinstance(storyboard_prompts, str) and storyboard_prompts.startswith("Could not generate")):
            return (storyboard_prompts or "Failed to generate storyboard prompts.", "", image_context, "")

        storyboard_text_for_neg_prompt = "\n\n---\n\n".join(storyboard_prompts)
        final_negative_prompt = utils._generate_negative_prompt(storyboard_text_for_neg_prompt, run_config, user_negative_prompt=kwargs.get("negative_prompt", ""))

        final_output = self._create_final_lyrics_output(storyboard_prompts=storyboard_prompts, timed_segments=timed_segments, run_config=run_config, **kwargs)
        
        prompt_out, schedule_out = ("", final_output) if kwargs.get("generate_schedule") else (final_output, "")

        if run_config.save_to_txt: self._save_lyrics_output_to_file(run_config.filename_prefix, lyrics_meta, image_context, lyrics, final_negative_prompt, final_output)
        return (prompt_out, schedule_out, image_context, final_negative_prompt)

    def _prepare_lyrics_generation_context(self, user_instructions, images_with_weights, lyrics, run_config):
        images = [img for img, _ in images_with_weights]
        image_context, _ = self._describe_images(images_with_weights, run_config)
        parsed_instructions, parsed_context = user_instructions, ""
        
        style_inspiration_section = ""
        if run_config.style_profile:
            inspiration = run_config.style_profile.get("inspiration", "")
            if inspiration: style_inspiration_section = f"- {inspiration}\n"
        elif run_config.style_override != "None" and run_config.style_override in config.STYLE_KEYWORDS:
            style_inspiration_section = f"- Style: {config.STYLE_KEYWORDS[run_config.style_override]}\n"
        else:
            style_engine = StyleEngine(run_config.model, run_config.use_chat_api, run_config.temperature, run_config.seed, image=images[0] if images else None, text=lyrics, debug_mode=run_config.debug_mode, timeout=run_config.timeout)
            dynamic_rules = style_engine.get_composition_rules()
            if dynamic_rules: style_inspiration_section = f"- {dynamic_rules[0].lstrip('- ').strip()}\n"
        
        instructions_section = f"SONG INSTRUCTIONS:\n{parsed_instructions}\n\n" if parsed_instructions and parsed_instructions.strip() else ""
        context_section = f"SONG CONTEXT & NARRATIVE:\n{parsed_context}\n\n" if parsed_context and parsed_context.strip() else ""
        
        tok_ok, mandatory_tokens = utils._extract_mandatory_tokens_with_model(image_context, (parsed_instructions or ""), run_config)
        return image_context, (mandatory_tokens if tok_ok else {}), style_inspiration_section, instructions_section, context_section

    def _generate_storyboard_global_theme(self, lyrics, instructions_section, context_section, image_context, run_config):
        theme_prompt = textwrap.dedent(f"""
            You are a music video director. Your task is to analyze the provided source material and synthesize a "Global Theme" for a music video. This theme is a high-level summary that will ensure visual consistency across all scenes.
            **CRITICAL INSTRUCTIONS:**
            1. **Analyze Source Material:** Your theme MUST be based on the explicit information and implicit mood of the LYRICS, INSTRUCTIONS, and IMAGE REFERENCES.
            2. **Handle Abstract Lyrics:** If the lyrics are abstract or non-narrative, focus on interpreting the core emotions, mood, and symbolism. Translate these abstract concepts into a cohesive visual theme. For example, for lyrics about loneliness, you might suggest a theme of 'a single figure in vast, empty landscapes with a cool, desaturated color palette'.
            3. **Avoid Contradiction:** Do NOT invent narratives or characters that contradict the source material. Your theme should be a creative interpretation, not a replacement.
            4. **Define Core Elements:** The theme should define the core visual style, setting, character design, and mood.
            --- LYRICS ---\n{lyrics}\n--- INSTRUCTIONS ---\n{instructions_section}\n--- CONTEXT ---\n{context_section}\n--- IMAGE REFERENCES ---\n{image_context}\n---
            Return ONLY the Global Theme description in a single, concise paragraph.
        """).strip()
        ok, theme = api_clients.query_model_auto(run_config.model, theme_prompt, prefer_chat=run_config.use_chat_api, temperature=run_config.temperature, seed=run_config.seed, timeout=120, debug_mode=run_config.debug_mode, debug_title="Storyboard Global Theme")
        return (True, utils.TextCleaner.single_paragraph(theme)) if ok else (False, f"Could not generate storyboard theme: {theme}")

    def _process_lyrics_storyboard(self, lyrics, timed_segments, global_theme, mandatory_tokens, style_inspiration_section, run_config):
        storyboard_rules_text = self._build_storyboard_rules(run_config, style_inspiration_section)
        segments = [(str(i + 1), seg[2]) for i, seg in enumerate(timed_segments)] if timed_segments else [(f"Line {i + 1}", line) for i, line in enumerate(lyrics.splitlines()) if line.strip()]
        if not segments: return "Could not segment lyrics into processable lines or sections."

        print(f"\033[94m[PromptCrafter] Generating storyboard for {len(segments)} lyric segments sequentially for improved coherence...\033[0m")
        processed_prompts = []
        previous_prompt_context = None
        pbar = comfy.utils.ProgressBar(len(segments))

        for i, (segment_name, segment_text) in enumerate(segments):
            try:
                generated_prompt = self._generate_and_refine_segment_prompt(segment_name, segment_text, global_theme, storyboard_rules_text, mandatory_tokens, run_config, previous_prompt_context=previous_prompt_context)
                processed_prompts.append(generated_prompt)
                # The context for the next prompt is the *visual description* part of the current prompt.
                previous_prompt_context = re.sub(r'# Segment: .*?\n# Global Theme: .*?\n\n', '', generated_prompt, flags=re.DOTALL).strip()
            except Exception as exc:
                error_message = f"Segment '{segment_name}' generated an exception: {exc}"
                print(f'\033[91m[PromptCrafter] {error_message}\033[0m')
                error_prompt = f"# Segment: {segment_name}\n# Global Theme: {global_theme}\n\n[Error: {error_message}]"
                processed_prompts.append(error_prompt)
                previous_prompt_context = None # Reset context on error
            pbar.update(1)

        return processed_prompts

    def _generate_and_refine_segment_prompt(self, segment_name, segment_text, global_theme, storyboard_rules_text, mandatory_tokens, run_config, previous_prompt_context=None):
        previous_scene_section = f"--- PREVIOUS SCENE (for narrative continuity) ---\n{previous_prompt_context}\n" if previous_prompt_context else ""
        draft_prompt_template = textwrap.dedent(f"""
            You are an expert Wan2.2 video prompt generator. Write a single, detailed cinematic prompt for the lyric segment below, following the Wan2.2 formula and adhering to the Global Theme.
            **Visual Interpretation:** Your primary task is to visually interpret the `CURRENT LYRIC SEGMENT`. Use the `GLOBAL THEME` as your creative guide to translate the mood, emotion, and symbolism of the lyric into a concrete visual scene. Do not just repeat the lyric.
            **Wan2.2 Formula:** [Subject Description] + [Scene Description] + [Detailed Action & Physics-Based Motion] + [Aesthetics & Stylization].
            {previous_scene_section}--- GLOBAL THEME (Your guide for consistency) ---\n{global_theme}\n--- CURRENT LYRIC SEGMENT: "{segment_name}" ---\n{segment_text}\n--- RULES ---\n{storyboard_rules_text}
            Return ONLY the generated prompt for this single segment.
        """).strip()
        draft_ok, draft_prompt = api_clients.query_model_auto(run_config.model, draft_prompt_template, prefer_chat=run_config.use_chat_api, temperature=run_config.temperature, seed=run_config.seed, timeout=90, debug_mode=run_config.debug_mode, debug_title=f"Draft for Segment '{segment_name}'")
        if not draft_ok: return f"# Segment: {segment_name}\n# Global Theme: {global_theme}\n\n[Error generating prompt for this segment: {draft_prompt}]"

        scene_prompt = utils.TextCleaner.slim_prompt_text(utils.TextCleaner.dedupe_sentences(utils.TextCleaner.single_paragraph(draft_prompt)))
        primary_items_list = [re.sub(r'^\[PRIMARY\]\s*', '', t) for t in (mandatory_tokens or {}).get("primary", [])]
        refined_prompt = self._refine_lyric_segment_prompt(scene_prompt, primary_items_list, storyboard_rules_text, run_config, f"Storyboard Segment '{segment_name}'", global_theme, previous_prompt_context)
        return f"# Segment: {segment_name}\n# Global Theme: {global_theme}\n\n{utils.TextCleaner.slim_prompt_text(refined_prompt)}"

    def _refine_lyric_segment_prompt(self, draft_prompt, mandatory_items, rules_text, run_config, debug_title_prefix, global_theme=None, previous_prompt_context=None):
        current_prompt = draft_prompt
        for i in range(run_config.max_retries + 1):
            critique_prompt = self._build_lyric_refinement_prompt(current_prompt, mandatory_items, global_theme, rules_text, previous_prompt_context)
            ok, revised_prompt = api_clients.query_model_auto(run_config.model, critique_prompt, prefer_chat=run_config.use_chat_api, temperature=run_config.temperature, seed=run_config.seed, timeout=90, debug_mode=run_config.debug_mode, debug_title=f"{debug_title_prefix} Refine (Try {i+1})")
            if not ok: return current_prompt
            current_prompt = utils.TextCleaner.single_paragraph(revised_prompt)
            if self._check_lyric_segment_coverage(current_prompt, mandatory_items, run_config, f"{debug_title_prefix} (Try {i+1})"):
                return current_prompt
        return current_prompt

    def _build_lyric_refinement_prompt(self, current_prompt, mandatory_items, global_theme, rules_text, previous_prompt_context=None):
        previous_scene_section = f"2. **NARRATIVE CONTINUITY:** The refined prompt should logically follow the PREVIOUS SCENE.\n--- PREVIOUS SCENE ---\n{previous_prompt_context}\n" if previous_prompt_context else ""
        refine_template = textwrap.dedent(f"""
            You are a master prompt critic and editor for Wan2.2 video prompts. Your task is to review and enhance the following DRAFT PROMPT for a music video segment.
            --- DRAFT PROMPT ---\n{current_prompt}\n--- END DRAFT PROMPT ---
            --- REQUIREMENTS & RULES ---
            1. **MANDATORY SUBJECTS (CRITICAL):** The final prompt MUST include all of the following subjects: {json.dumps(mandatory_items) if mandatory_items else "None"}
            - **Visual Interpretation:** The prompt must be a visual interpretation of the song's mood and lyrics, guided by the GLOBAL THEME. It should not be a literal description of the words.
            {previous_scene_section}2. **GLOBAL THEME (for consistency):** {global_theme or "Not specified."}
            3. **Wan2.2 Formula:** The prompt should follow the structure: [Subject Description] + [Scene Description] + [Detailed Action & Physics-Based Motion] + [Aesthetics & Stylization].
            4. **STYLE & COMPOSITION RULES:**\n{rules_text}
            --- END REQUIREMENTS & RULES ---
            INSTRUCTIONS: Revise the DRAFT PROMPT to meet ALL requirements. Ensure mandatory subjects are integrated naturally. Enhance for cinematic quality. Return ONLY the final, improved prompt.
        """)
        if not mandatory_items: refine_template = refine_template.replace(re.search(r"1\. \*\*MANDATORY SUBJECTS.*?{subjects}\n", refine_template).group(0), "")
        return refine_template

    def _check_lyric_segment_coverage(self, prompt, mandatory_items, run_config, debug_title_prefix):
        if not mandatory_items: return True
        coverage_prompt = f'Analyze the SCENE PROMPT below. Does it semantically contain all of the REQUIRED ITEMS? REQUIRED ITEMS: {json.dumps(mandatory_items)} SCENE PROMPT: {prompt} Respond with ONLY a JSON object: {{"missing_items": []}}.'
        ok, result_json = api_clients._reason_with_model(run_config.model, coverage_prompt, run_config.use_chat_api, 0.0, run_config.seed, debug_mode=run_config.debug_mode, debug_title=f"{debug_title_prefix} Check")
        if not ok:
            print(f"\033[93m[PromptCrafter] Warning: Coverage check failed for '{debug_title_prefix}'. Retrying. Error: {result_json}\033[0m")
            return False
        return not result_json.get("missing_items")

    def _build_storyboard_rules(self, run_config, style_inspiration_section):
        safety_rule = f"\n{config.SAFE_MODE_RULE}" if run_config.safe_mode else ""
        length_rule = f"- Keep each segment's prompt under {run_config.max_length_words} words." if run_config.max_length_words > 0 else "- Each segment's prompt length target: 80-120 words."
        negative_concepts_rule = f"CRITICAL: Do NOT include any of the following concepts: {run_config.negative_concepts}" if run_config.negative_concepts else ""
        return textwrap.dedent(f"""- CRITICAL: All generated prompt text MUST be in {run_config.language}. Do NOT use any other languages.\n{style_inspiration_section}{safety_rule}\n{negative_concepts_rule}\n- The visual elements should be based on the USER INSTRUCTIONS and IMAGE REFERENCES. Do not invent new core subjects.\n- The ACTION and MOOD of the prompt must be a direct visual interpretation of the specific lyric segment.\n- CRITICAL PRIORITY: Focus on subject ACTIONS and physics-based MOTION. Keep the environment concise.\n- Maintain continuity: characters, setting, palette, lens/lighting consistent across segments.\n{length_rule}""")

    def _create_final_lyrics_output(self, storyboard_prompts, timed_segments, run_config, **kwargs):
        if not kwargs.get("generate_schedule"): return "\n\n---\n\n".join(storyboard_prompts)
        if timed_segments:
            print("\033[94m[PromptCrafter] Timed segments detected. Generating timed schedule...\033[0m")
            schedule = collections.OrderedDict()
            for i, seg in enumerate(timed_segments):
                frame = int(seg[0] * kwargs.get("fps", 16.0))
                prompt = re.sub(r'# Segment: .*?\n# Global Theme: .*?\n\n', '', storyboard_prompts[i], flags=re.DOTALL).strip()
                schedule[frame] = prompt
            if run_config.interpolate_keyframes: schedule = utils._interpolate_schedule_prompts(schedule, run_config.interpolation_frame_interval)
            return ",\n".join([f'"{str(key)}": {json.dumps(str(value))}' for key, value in schedule.items()])
        
        max_frames = int(kwargs.get("song_length_seconds", 0) * kwargs.get("fps", 16.0)) if kwargs.get("song_length_seconds", 0) > 0 else kwargs.get("max_frames", 240)
        return utils._create_schedule_from_items(storyboard_prompts, max_frames, 0, run_config.interpolate_keyframes, run_config.interpolation_frame_interval)

    def _save_lyrics_output_to_file(self, filename_prefix, lyrics_meta, image_context, lyrics, final_negative_prompt, final_output):
        if not final_output or not final_output.strip(): return
        sections = []
        if lyrics_meta and lyrics_meta[0] and lyrics_meta[1] and lyrics_meta[1] != "<none>": sections.append(("LYRICS SOURCE FILE", f"folder: {lyrics_meta[0]}\nfile: {lyrics_meta[1]}"))
        sections.extend([("IMAGE CONTEXT", image_context or "No reference images provided."), ("LYRICS", (lyrics or "").strip()), ("NEGATIVE PROMPT", final_negative_prompt or ""), ("OUTPUT", final_output)])
        utils._save_output_to_file(filename_prefix, sections, base_filename="lyrics_prompts")

# ------------------------------------------------------------------------------------
# Utility Nodes
# ------------------------------------------------------------------------------------
class PromptCrafter_ClearCache:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"action": (["Clear Cache", "Check Size"], {"default": "Clear Cache"})}}
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️/PromptCrafter/Utils"

    def execute(self, action):
        if action == "Clear Cache":
            removed_count = config.CACHE.clear()
            status_message = f"Cache cleared. Removed {removed_count} items."
            print(f"\033[92m[PromptCrafter] {status_message}\033[0m")
        else:
            status_message = f"Cache contains {config.CACHE.size()} of {config.CACHE.max_size} items."
        return (status_message,)