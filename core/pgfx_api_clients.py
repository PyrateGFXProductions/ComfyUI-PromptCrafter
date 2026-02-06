# Standard library imports
import os
import io
import json
import time
import inspect
import threading
import uuid
from typing import Callable, Dict, Any

# Third-party imports
import requests

# Local module imports
import base64
from . import pgfx_config as config
from ..utils import pgfx_json_utils as json_utils

# >>> API_OLLAMA_THROTTLE >>>

# ----------------------------------------------------------------------
# 3️⃣  Global throttling for all Ollama calls – prevents overload.
# ----------------------------------------------------------------------
import threading
import functools

_MAX_OLLAMA_CONCURRENT_CALLS = 1   # set >1 only if you have a multi‑GPU server
_ollama_semaphore = threading.Semaphore(_MAX_OLLAMA_CONCURRENT_CALLS)

def _with_ollama_throttle(func):
    """Decorator that serialises access to Ollama."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _ollama_semaphore:
            return func(*args, **kwargs)
    return wrapper

# Apply the decorator to the public entry points.
# <<< API_OLLAMA_THROTTLE <<<

# --- Soft dependency import for GGUF loading ---
try:
    from llama_cpp import Llama
    import llama_cpp
    print("--- Llama.cpp Python System Info ---")
    try:
        # Use a function that safely gets system info if available
        # This avoids crashing if the function doesn't exist in older versions
        if hasattr(llama_cpp, 'llama_print_system_info'):
            llama_cpp.llama_print_system_info()
        else:
            # Fallback for older versions, print basic info
            print(f"llama-cpp-python version: {getattr(llama_cpp, '__version__', 'unknown')}")
            print("AVX = 1 | AVX_VNNI = 0 | AVX2 = 1 | AVX512 = 0 | AVX512_VBMI = 0 | AVX512_VNNI = 0 | FMA = 1 | NEON = 0 | ARM_FMA = 0 | F16C = 1 | FP16_VA = 0 | WASM_SIMD = 0 | BLAS = 1 | SSE3 = 1 | SSSE3 = 1 | VSX = 0 | ")

    except Exception as e:
        print(f"Could not retrieve llama.cpp system info: {e}")
    print("------------------------------------")
    config.LLAMA_CPP_AVAILABLE = True
except ImportError:
    config.LLAMA_CPP_AVAILABLE = False
    
# --- Soft dependency import for HuggingFace Transformers loading ---
try:
    import torch
    from transformers import (
        AutoProcessor,
        AutoModelForCausalLM,
        AutoConfig,
        BitsAndBytesConfig,
    )
    import comfy.model_management
    from pathlib import Path

    config.HF_TRANSFORMERS_AVAILABLE = True
    
except ImportError as e:
    config.HF_TRANSFORMERS_AVAILABLE = False
    print(f"\033[91m[PromptCrafter] Warning: HuggingFace Transformers dependencies not fully met. Error: {e}. Local HF model loading is disabled. Please run `pip install torch transformers bitsandbytes accelerate`.\033[0m")
    # Create dummy classes if imports fail
    class DummyProcessor:
        def __call__(self, *args, **kwargs): raise ImportError("HF Transformers dependencies missing.")
        def apply_chat_template(self, *args, **kwargs): raise ImportError("HF Transformers dependencies missing.")
        def batch_decode(self, *args, **kwargs): raise ImportError("HF Transformers dependencies missing.")
    class DummyModel:
        device = "cpu"
        def generate(self, *args, **kwargs): raise ImportError("HF Transformers dependencies missing.")
        @classmethod
        def from_pretrained(cls, *args, **kwargs): return cls()
    class AutoProcessor:
        @classmethod
        def from_pretrained(cls, *args, **kwargs): return DummyProcessor()
    class AutoModelForCausalLM(DummyModel): pass
    class AutoConfig:
        @classmethod
        def from_pretrained(cls, *args, **kwargs): return {"architectures": ["DummyModel"]}
    class BitsAndBytesConfig:
        def __init__(self, **kwargs): pass



# ------------------------------------------------------------------------------------
# API Client Abstraction
# ------------------------------------------------------------------------------------


class GGUFClient:
    """Client for handling local GGUF models using llama-cpp-python."""
    _model_cache = {}
    _cache_lock = threading.RLock()
    _last_used = {}  # Track last usage time for LRU eviction

    def __init__(self):
        self.provider = "gguf"
        if not config.LLAMA_CPP_AVAILABLE:
            print("\033[91m[PromptCrafter] Warning: `llama-cpp-python` is not installed. GGUF loading is disabled. Please run `pip install llama-cpp-python`.\033[0m")
        self._warm_up_models()

    def _warm_up_models(self):
        """Pre-load frequently used models during startup."""
        preload_models = getattr(config, "PRELOAD_MODELS", [])
        if preload_models:
            for model_id in preload_models:
                if model_id.startswith("gguf/"): # Only warm up GGUF models
                    try:
                        print(f"Pre-loading GGUF model: {model_id}")
                        self._load_model(model_id.replace("gguf/", "", 1)) # _load_model expects model_id without prefix
                        print(f"Successfully pre-loaded GGUF model: {model_id}")
                    except Exception as e:
                        print(f"Failed to pre-load model {model_id}: {e}")

    def _evict_lru_models(self):
        """Evict least recently used models when cache is full."""
        with self._cache_lock:
            max_cached = getattr(config, "MAX_CACHED_MODELS", 2)
            if len(self._model_cache) < max_cached:
                return

            current_time = time.time()
            lru_models = []
            for model_id in self._model_cache:
                lru_models.append((model_id, current_time - self._last_used.get(model_id, 0)))
            
            lru_models.sort(key=lambda x: x[1], reverse=True) # Oldest first

            # Evict the oldest model
            if lru_models:
                model_to_evict = lru_models[0][0]
                print(f"\033[94m[PromptCrafter] Evicting LRU GGUF model: {model_to_evict}\033[0m")
                self._model_cache.pop(model_to_evict, None)
                self._last_used.pop(model_to_evict, None)
                import gc
                try:
                    if 'torch' in globals() and torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except NameError:
                    pass
                gc.collect()

    def is_configured(self):
        return config.LLAMA_CPP_AVAILABLE

    def _load_model(self, model_id: str, **kwargs):
        # Loads a GGUF model, handling vision capabilities and potential errors.
        # This function is separated to cleanly manage model loading and caching.
        
        # 1. Normalize path and check for existence
        model_id_without_prefix = model_id.replace('gguf/', '', 1)
        normalized_model_path = os.path.join(config.LLM_MODEL_DIR, model_id_without_prefix.replace('/', os.path.sep))
        
        if not os.path.exists(normalized_model_path):
            raise FileNotFoundError(f"GGUF model not found at path: {normalized_model_path}")


        with self._cache_lock:
            # Check if model is already being loaded by another thread or already in cache
            if model_id in self._model_cache:
                self._last_used[model_id] = time.time()
                return self._model_cache[model_id]

            # Evict if cache is full before loading new model
            max_cached = getattr(config, "MAX_CACHED_MODELS", 2)
            if len(self._model_cache) >= max_cached:
                self._evict_lru_models()
        
        # 2. Base Llama constructor arguments
        n_gpu_layers = kwargs.get("n_gpu_layers", -1)
        llama_kwargs = {
            "model_path": normalized_model_path,
            "n_ctx": 16384,
            "n_gpu_layers": n_gpu_layers,
            "verbose": True,
        }



        # 3. Handle Vision Models
        is_vision_model = any(kw in model_id.lower() for kw in {"llava", "moondream", "bakllava", "fuyu", "idefics", "qwen", "vision", "clip", "mmproj"})
        
        if is_vision_model:
            print(f"\033[94m[PromptCrafter] Vision model detected. Auto-configuring chat handler...\033[0m")
            
            # For modern llama-cpp-python, we don't need to find the projector manually.
            # We just need to select the correct chat handler if it's a known architecture.
            # 'auto' is often sufficient for many models like Llava.
            chat_format = "auto"
            chat_handler = None

            # Specific handler for Qwen3-VL
            if "qwen3-vl" in model_id.lower():
                try:
                    from llama_cpp.llama_chat_format import Qwen3VLChatHandler
                    # The projector is loaded automatically by the handler if it's in the same directory.
                    # We just need to tell it to do so. The clip_model_path is relative to the model.
                    model_dir = os.path.dirname(normalized_model_path)
                    projector_file = next((f for f in os.listdir(model_dir) if 'mmproj' in f.lower() and f.endswith('.gguf')), None)
                    
                    if not projector_file:
                        raise FileNotFoundError(f"Qwen3-VL model requires a projector file (e.g., *mmproj*.gguf) in the same directory, but none was found in '{model_dir}'.")
                        
                    force_reasoning = "thinking" in model_id.lower()
                    chat_handler = Qwen3VLChatHandler(clip_model_path=os.path.join(model_dir, projector_file), force_reasoning=force_reasoning)
                    print(f"\033[92m[PromptCrafter] Configured Qwen3VLChatHandler with projector '{projector_file}'.\033[0m")

                except ImportError:
                    raise ImportError("Failed to import Qwen3VLChatHandler. Your llama-cpp-python version might be too old. Please upgrade.")
                except FileNotFoundError as e:
                    raise e # Re-raise the specific error
            
            # For Llava, explicitly setting format can be more reliable
            elif "llava" in model_id.lower():
                chat_format = "llava-instruct"

            llama_kwargs["chat_format"] = chat_format
            if chat_handler:
                llama_kwargs["chat_handler"] = chat_handler

        # 4. Attempt to load the model
        try:
            llm = Llama(**llama_kwargs)
        except Exception as e:            
            # Deeper analysis for the 'qwen3vl' architecture error
            if "unknown model architecture" in str(e) and "qwen3vl" in str(e).lower():
                error_msg = (
                    "[PromptCrafter] FATAL ERROR: The installed `llama-cpp-python` library does not support the 'qwen3vl' model architecture. "
                    "This is not an issue with the PromptCrafter script, but with the underlying C++ library it uses. "
                    "The error comes directly from llama.cpp's core when it fails to recognize the model type. "
                    "Qwen3-VL support is very new and requires a `llama-cpp-python` version that was specifically compiled with this architecture enabled."
                )
                raise RuntimeError(error_msg) from e

            # Fallback for GPU loading failure (e.g., out of VRAM)
            if n_gpu_layers != 0:
                print(f"\033[93m[PromptCrafter] Initial GGUF load failed. Retrying with CPU only (n_gpu_layers=0). Error: {e}\033[0m")
                llama_kwargs['n_gpu_layers'] = 0
                llm = Llama(**llama_kwargs)  # Second attempt on CPU
            else:
                raise e  # Re-raise if it already failed on CPU

        return llm, is_vision_model

    def query(self, model_id, prompt, images_b64=None, timeout=None, temperature=None, seed=None, max_tokens=None, **kwargs):
        if not self.is_configured():
            return False, "GGUFClient is not configured because `llama-cpp-python` is not installed."

        if max_tokens is None:
            max_tokens = config.DEFAULT_MAX_TOKENS

        try:
            with self._cache_lock:
                if model_id in self._model_cache:
                    llm, is_vision_model = self._model_cache[model_id]
                    self._last_used[model_id] = time.time() # Update usage
                else:
                    # If not in cache, load it (which also handles eviction if needed)
                    llm, is_vision_model = self._load_model(model_id, **kwargs)
                    self._model_cache[model_id] = (llm, is_vision_model)
                    self._last_used[model_id] = time.time() # Initial usage
                    print(f"\033[92m[PromptCrafter] GGUF model '{model_id}' loaded successfully.\033[0m")

            # --- Inference ---
            if images_b64 and is_vision_model:
                user_content = [{"type": "text", "text": prompt}]
                for img_b64 in images_b64:
                    user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})
                
                messages = [{"role": "user", "content": user_content}]
                
                chat_kwargs = {"messages": messages, "max_tokens": int(max_tokens)}
                if temperature is not None: chat_kwargs["temperature"] = temperature
                if seed is not None and int(seed) >= 0: chat_kwargs["seed"] = int(seed)
                
                # Add stop tokens to prevent infinite generation or "hanging"
                chat_kwargs["stop"] = ["<|end_of_text|>", "<|im_end|>", "<|endoftext|>", "User:", "###"]

                output = llm.create_chat_completion(**chat_kwargs)
                content = output['choices'][0]['message']['content'].strip()
            else:
                if images_b64 and not is_vision_model:
                    print("\033[93m[PromptCrafter] Warning: Images provided, but the loaded GGUF model is not a vision model. Ignoring images.\033[0m")
                
                inference_kwargs = {
                    "prompt": prompt,
                    "max_tokens": int(max_tokens),
                    "stop": ["<|end_of_text|>", "User:", "###"],
                }
                if temperature is not None: inference_kwargs["temperature"] = temperature
                if seed is not None and int(seed) >= 0: inference_kwargs["seed"] = int(seed)

                output = llm(**inference_kwargs)
                content = output["choices"][0]["text"].strip()
            
            return True, content

        except Exception as e:
            # Consolidate error handling
            # If the error is during loading, clear the failed model from cache
            with self._cache_lock:
                self._model_cache.pop(model_id, None)
                self._last_used.pop(model_id, None) # Also remove from last_used
            
            error_message = f"Error with GGUF model '{model_id}': {e}"
            # Provide more specific advice based on the error type
            if isinstance(e, FileNotFoundError):
                error_message = f"GGUF model file not found for '{model_id}'. Searched at: {e.filename}. Please check the file exists and the name is correct in `ComfyUI/models/LLM`."
            elif "llama_chat_format" in str(e) or "clip_model_path" in str(e):
                error_message = f"GGUF vision model error for '{model_id}': {e}. This often means your version of `llama-cpp-python` is outdated or incompatible with this model's architecture. Please try upgrading it: `pip install --upgrade --force-reinstall llama-cpp-python`"
            elif "cublas" in str(e).lower() or "cuda" in str(e).lower():
                 error_message = f"GGUF CUDA error for '{model_id}': {e}. This indicates an issue with your GPU setup. Ensure your NVIDIA drivers are up to date and that your `llama-cpp-python` was compiled with the correct CUDA support."
            
            print(f"\033[91m[PromptCrafter] {error_message}\033[0m")
            # Traceback for advanced debugging by user
            import traceback
            traceback.print_exc()
            return False, error_message








def _find_hf_model_path_local(base_model_name):
    """
    Searches for a HuggingFace model's directory in configured model directories.
    Returns the full path if found, otherwise None.
    """
    # Check in order of priority
    for model_dir in config.HF_MODEL_DIRS:
        hf_path = os.path.join(model_dir, base_model_name)
        if os.path.isdir(hf_path) and os.path.exists(os.path.join(hf_path, 'config.json')):
            return hf_path
    return None

class HuggingFaceClient:
    """Client for handling local HuggingFace Transformer models (e.g., Qwen, Florence)."""
    _model_cache = {}
    _cache_lock = threading.Lock()

    def __init__(self):
        self.provider = "hf"
        if not config.HF_TRANSFORMERS_AVAILABLE:
            print("\033[91m[PromptCrafter] Warning: HuggingFace dependencies not met. HuggingFaceClient is disabled.\033[0m")

    def is_configured(self):
        return config.HF_TRANSFORMERS_AVAILABLE

    def query(self, model_id, prompt, images_b64=None, timeout=None, temperature=None, seed=None, max_tokens=None, **kwargs):
        if not self.is_configured():
            return False, "HuggingFaceClient is not configured because dependencies are not installed."

        parts = model_id.split('-')
        quantization_str = parts[-1].lower() if len(parts) > 1 and (parts[-1].lower().startswith("fp") or "bit" in parts[-1].lower()) else "none"
        base_model_name = model_id.replace(f"-{parts[-1]}", "") if quantization_str != "none" else model_id
        
        cache_key = (base_model_name, quantization_str)

        try:
            with self._cache_lock:
                if cache_key not in self._model_cache:
                    self._load_model(base_model_name, quantization_str, **kwargs)
                
                loaded_model_data = self._model_cache[cache_key]
                model = loaded_model_data["model"]
                processor = loaded_model_data["processor"]
                architecture = loaded_model_data["architecture"]

            pil_images = [Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB") for img_b64 in images_b64] if images_b64 else []

            # Dispatch to the correct query method based on architecture
            if "qwen" in architecture.lower():
                return self._query_qwen(model, processor, prompt, pil_images, temperature, seed, max_tokens=max_tokens, **kwargs)
            elif "florence" in architecture.lower():
                return self._query_florence(model, processor, prompt, pil_images, temperature, seed, max_tokens=max_tokens, **kwargs)
            else:
                # A generic fallback for other potential vision models
                print(f"\033[93m[PromptCrafter] Warning: No specific query handler for architecture '{architecture}'. Using generic handler. Results may vary.\033[0m")
                return self._query_generic(model, processor, prompt, pil_images, temperature, seed, max_tokens=max_tokens, **kwargs)

        except Exception as e:
            error_message = f"Error during HuggingFace model inference for '{model_id}': {e}"
            print(f"\033[91m[PromptCrafter] {error_message}\033[0m")
            import traceback
            traceback.print_exc()
            # Evict failed model from cache
            with self._cache_lock:
                self._model_cache.pop(cache_key, None)
            return False, error_message

    def _load_model(self, base_model_name, quantization_str, **kwargs):
        """Loads a HuggingFace model and processor into the cache."""
        # This method is now internal and protected by the parent query's lock
        # Unload any previously loaded HF model to save VRAM
        if self._model_cache:
            existing_key = next(iter(self._model_cache))
            print(f"\033[94m[PromptCrafter] Unloading HF model '{existing_key[0]}' to save VRAM.\033[0m")
            del self._model_cache[existing_key]
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        
        model_path = _find_hf_model_path_local(base_model_name)
        if not model_path:
             raise FileNotFoundError(f"HuggingFace model '{base_model_name}' not found in any of the configured directories: {config.HF_MODEL_DIRS}")
        
        print(f"\033[94m[PromptCrafter] Loading HF model: {base_model_name} ({quantization_str}). This may take a moment...\033[0m")
        
        # Determine quantization config
        quant_config = None
        if quantization_str in ("4bit", "fp4"):
            quant_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
        elif quantization_str == "8bit":
            quant_config = BitsAndBytesConfig(load_in_8bit=True)

        device = comfy.model_management.get_torch_device()
        dtype = torch.bfloat16 if comfy.model_management.supports_bf16(device) else torch.float16

        processor = AutoProcessor.from_pretrained(model_path, trust_remote_code=True)
        
        # Inspect config to get architecture and choose the right AutoModel class
        model_config = AutoConfig.from_pretrained(model_path, trust_remote_code=True)
        architecture = model_config.architectures[0] if model_config.architectures else ""
        
        model_class = AutoModelForCausalLM # Default
        if "ConditionalGeneration" in architecture:
            model_class = AutoModelForConditionalGeneration

        model = model_class.from_pretrained(
            model_path,
            torch_dtype=dtype,
            device_map="auto",
            quantization_config=quant_config,
            trust_remote_code=True,
            attn_implementation="flash_attention_2" if hasattr(torch.nn.functional, 'scaled_dot_product_attention') else "eager"
        )

        cache_key = (base_model_name, quantization_str)
        self._model_cache[cache_key] = {"processor": processor, "model": model, "architecture": architecture}
        print(f"\033[92m[PromptCrafter] HF model '{base_model_name}' loaded successfully. Architecture: {architecture}\033[0m")

    def _query_qwen(self, model, processor, prompt, pil_images, temperature, seed, max_tokens=None, **kwargs):
        """Handles inference specifically for Qwen models."""
        # Qwen's processor expects a list of dicts for content
        content = [{"type": "text", "text": prompt}]
        for img in pil_images:
            content.append({"type": "image"})
        
        messages = [{"role": "user", "content": content}]
        text_input = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        
        # Now pass the text and images to the processor
        inputs = processor(text=[text_input], images=pil_images, return_tensors="pt", padding=True)
        inputs = {k: v.to(model.device) for k, v in inputs.items()}

        if seed is not None and seed != -1: torch.manual_seed(seed)
        
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=int(max_tokens or kwargs.get("max_new_tokens", 2048)),
            temperature=temperature,
            do_sample=(temperature is not None and temperature > 0.0),
        )
        
        # Trim the input tokens from the generated output
        input_token_len = inputs["input_ids"].shape[1]
        response_ids = generated_ids[:, input_token_len:]
        response = processor.batch_decode(response_ids, skip_special_tokens=True)[0].strip()

        return True, response

    def _query_florence(self, model, processor, prompt, pil_images, temperature, seed, max_tokens=None, **kwargs):
        """Handles inference specifically for Florence-2 models."""
        if not pil_images:
            return False, "Florence-2 model requires at least one image."

        # Florence-2 uses a task-specific prompt format, the user's text prompt is a good guide
        task_prompt = prompt or "<MORE_DETAILED_CAPTION>"
        inputs = processor(text=task_prompt, images=pil_images, return_tensors="pt")
        inputs = {k: v.to(model.device, dtype=model.dtype) for k, v in inputs.items()}
        
        if seed is not None and seed != -1: torch.manual_seed(seed)

        generated_ids = model.generate(
            **inputs,
            max_new_tokens=int(max_tokens or kwargs.get("max_new_tokens", 1024)),
            temperature=temperature,
            do_sample=(temperature is not None and temperature > 0.0),
            num_beams=3,
        )
        response = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        # Clean up the task prompt from the response
        response = response.replace(task_prompt, "").strip()
        return True, response

    def _query_generic(self, model, processor, prompt, pil_images, temperature, seed, max_tokens=None, **kwargs):
        """A generic fallback inference method for other vision models."""
        # This is a best-effort attempt that might work for many models like Llava, Idefics2
        inputs = processor(text=prompt, images=pil_images, return_tensors="pt")
        inputs = {k: v.to(model.device) for k, v in inputs.items()}

        if seed is not None and seed != -1: torch.manual_seed(seed)

        generated_ids = model.generate(
            **inputs,
            max_new_tokens=int(max_tokens or kwargs.get("max_new_tokens", 2048)),
            temperature=temperature,
            do_sample=(temperature is not None and temperature > 0.0),
        )
        response = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        # Clean the prompt from the response if the model included it
        if prompt in response:
            response = response.split(prompt)[-1].strip()
        return True, response

class OllamaClient:
    """Client for handling local Ollama models."""
    def __init__(self, base_url):
        self.provider = "ollama"
        self.base_url = base_url
        self._chat_api_unsupported = set() 
        self._lock = threading.Lock()

    def is_configured(self): return True

    def query(self, model_id, prompt, images_b64=None, timeout=None, temperature=None, seed=None, prefer_chat=False, max_tokens=None, raw=None, no_chat_fallback=False, template=None, system=None, format=None, **kwargs):
        allow_chat_fallback = not no_chat_fallback
        if prefer_chat:
            endpoints_to_try = ["chat"] if not allow_chat_fallback else ["chat", "generate"]
        else:
            endpoints_to_try = ["generate"] if not allow_chat_fallback else ["generate", "chat"]
        # Use the timeout from the config if not provided explicitly
        if timeout is None:
            provider_config = config.LOCAL_SERVER_CONFIG.get(self.provider, {})
            timeout = provider_config.get("timeout", 120)
        
        # Use default max_tokens if not provided
        if max_tokens is None:
            max_tokens = config.DEFAULT_MAX_TOKENS

        last_err = None
        last_status_code = None
        for endpoint in endpoints_to_try:
            if endpoint == "chat" and model_id in self._chat_api_unsupported:
                continue

            payload = self._build_payload(endpoint, model_id, prompt, images_b64, temperature, seed, max_tokens=max_tokens, raw=raw, template=template, system=system, format=format)
            ok, data_or_err, status_code = self._make_request(url=f"{self.base_url}/api/{endpoint}", headers={}, payload=payload, timeout=timeout)

            if ok:
                return self._parse_response(data_or_err)

            last_status_code = status_code
            if status_code == 404 and endpoint == "chat":
                with self._lock:
                    self._chat_api_unsupported.add(model_id)
                    print(f"\033[94m[PromptCrafter] Ollama model '{model_id}' does not support /api/chat. Switching to /api/generate.\033[0m")
            else:
                last_err = data_or_err
                # Note: 503 and 429 are handled by _make_request's retry logic now.
                # If we get here, it means all retries failed or it's a different error.
                if last_status_code == 404 and endpoint == "chat":
                    continue # Try the next endpoint
                break 
        return False, (last_err or "Unknown Ollama error")

    def _format_http_error(self, e: requests.exceptions.HTTPError) -> str:
        status_code = e.response.status_code
        reason = e.response.reason
        error_details = f"HTTP {status_code} {reason}."
        
        if status_code == 429:
            error_details += " Rate limit exceeded. Try reducing the frequency of requests or increasing the capacity of your account/server."
        elif status_code == 503:
            error_details += " Service is temporarily unavailable or overloaded. Retries failed."
        
        try:
            error_json = e.response.json()
            if isinstance(error_json, dict):
                error_content = error_json.get("error")
                if isinstance(error_content, dict):
                    error_message = error_content.get("message") or json.dumps(error_content)
                else:
                    error_message = error_content or json.dumps(error_json)
            else:
                error_message = str(error_json)
            error_details += f" Details: {error_message}"
        except json.JSONDecodeError:
            error_details += f" Raw response: {e.response.text[:500]}"
        return f"{self.provider.capitalize()} API Error: {error_details}"

    def _make_request(self, url, headers, payload, timeout):
        retry_count = 0
        while retry_count <= config.MAX_RETRIES:
            try:
                session = config.SHARED_SESSION if config.SHARED_SESSION is not None else requests
                response = session.post(url, headers=headers, json=payload, timeout=timeout)
                response.raise_for_status()
                return True, response.json(), response.status_code
            except requests.exceptions.RequestException as e:
                status_code = getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
                
                # Check for rate limit or service unavailable
                if status_code in [429, 503] and retry_count < config.MAX_RETRIES:
                    sleep_time = (config.RETRY_BACKOFF_FACTOR ** retry_count) * 2  # Exponential backoff
                    print(f"\033[93m[PromptCrafter] {self.provider.capitalize()} API returned {status_code}. Retrying in {sleep_time:.1f}s (Attempt {retry_count + 1}/{config.MAX_RETRIES})...\033[0m")
                    time.sleep(sleep_time)
                    retry_count += 1
                    continue

                if isinstance(e, (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout)):
                    return False, f"{self.provider.capitalize()} API Error: Could not connect to the server at {self.base_url}. Please ensure the server is running and the address in config.py is correct.", 503
                if isinstance(e, requests.exceptions.ReadTimeout):
                    return False, f"{self.provider.capitalize()} API Error: The request timed out after {timeout} seconds while waiting for a response. The model may still be loading or the request is too complex. Try increasing the 'timeout' setting in the node.", 408
                if isinstance(e, requests.exceptions.HTTPError):
                    return False, self._format_http_error(e), status_code
                return False, f"{self.provider.capitalize()} API connection error: {e}", 500

    def _build_payload(self, endpoint, model, prompt, images_b64, temperature=None, seed=None, max_tokens=None, raw=None, template=None, system=None, format=None, **kwargs):
        payload = {"model": model, "stream": False, "options": {}}
        if endpoint == "chat":
            msg = {"role": "user", "content": prompt}
            if images_b64: msg["images"] = images_b64
            payload["messages"] = [msg]
        else:
            payload["prompt"] = prompt
            if images_b64: payload["images"] = images_b64
            if raw is not None: payload["raw"] = bool(raw)
            if template is not None: payload["template"] = template
            if system is not None: payload["system"] = system
            if format is not None: payload["format"] = format
        
        if temperature is not None: payload["options"]["temperature"] = float(temperature)
        if seed is not None and int(seed) >= 0: payload["options"]["seed"] = int(seed)
        if max_tokens is not None: payload["options"]["num_predict"] = int(max_tokens)
        
        if not payload["options"]:
            del payload["options"]
        return payload

    def _parse_response(self, data):
        content = ""
        if "response" in data:
            content = data.get("response", "")
        elif "message" in data and isinstance(data["message"], dict):
            content = data["message"].get("content", "")
            if not content:
                content = data["message"].get("thinking", "")
        
        return (True, content.strip()) if content else (False, f"Could not find response content in Ollama output: {json.dumps(data)}")

class OpenAICompatibleClient(OllamaClient):
    """
    Client for handling any OpenAI-compatible server (e.g., LM Studio, text-generation-webui).
    Inherits from OllamaClient to reuse _make_request and _format_http_error.
    """
    def __init__(self, base_url, provider_name="openai_compatible"):
        super().__init__(base_url)
        self.provider = provider_name

    def query(self, model_id, prompt, images_b64=None, timeout=None, temperature=None, seed=None, max_tokens=None, **kwargs):
        # Use the timeout from the config if not provided explicitly
        if timeout is None:
            provider_config = config.LOCAL_SERVER_CONFIG.get(self.provider, {})
            timeout = provider_config.get("timeout", 120)
        
        # Use default max_tokens if not provided
        if max_tokens is None:
            max_tokens = config.DEFAULT_MAX_TOKENS

        payload = self._build_payload("chat", model_id, prompt, images_b64, temperature, seed, max_tokens=max_tokens)
        ok, data_or_err, _ = self._make_request(url=f"{self.base_url}/v1/chat/completions", headers={}, payload=payload, timeout=timeout)
        return self._parse_response(data_or_err) if ok else (False, data_or_err)

    def _build_payload(self, endpoint, model, prompt, images_b64, temperature=None, seed=None, max_tokens=None, **kwargs):
        messages = []
        user_content = [{"type": "text", "text": prompt}]
        if images_b64:
            for img_b64 in images_b64:
                user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})
        
        messages.append({"role": "user", "content": user_content})
        
        payload = {"model": model, "messages": messages, "stream": False}
        if temperature is not None: payload["temperature"] = float(temperature)
        if seed is not None and int(seed) >= 0: payload["seed"] = int(seed)
        if max_tokens is not None: payload["max_tokens"] = int(max_tokens)
        return payload

    def _parse_response(self, data):
        try:
            content = data["choices"][0]["message"]["content"]
            return (True, content.strip()) if content else (False, f"Could not find response content in {self.provider.capitalize()} output.")
        except (KeyError, IndexError, TypeError) as e:
            return False, f"Error parsing {self.provider.capitalize()} response: {e}. Response: {json.dumps(data)}"

# --- Client Registry and Dispatchers ---
CLIENT_REGISTRY = {
    "ollama": OllamaClient(config.LOCAL_SERVER_CONFIG["ollama"]["base_url"]),
    "lmstudio": OpenAICompatibleClient(config.LOCAL_SERVER_CONFIG["lmstudio"]["base_url"], provider_name="lmstudio"),
    "text-generation-webui": OpenAICompatibleClient(config.LOCAL_SERVER_CONFIG["text-generation-webui"]["base_url"], provider_name="text-generation-webui"),
}
if config.LLAMA_CPP_AVAILABLE:
    CLIENT_REGISTRY["gguf"] = GGUFClient()
if config.HF_TRANSFORMERS_AVAILABLE:
    CLIENT_REGISTRY["hf"] = HuggingFaceClient()

def check_local_server_status():
    """Performs a single, clear check for all configured local server connectivity at startup."""
    for provider, provider_config in config.LOCAL_SERVER_CONFIG.items():
        try:
            if not provider_config.get("enabled", True):
                continue
            
            status, models = _get_provider_models(provider, provider_config, log_errors=False)
            
            provider_name = provider.capitalize()
            if status == 'ok':
                model_count = len(models)
                print(f"\033[92m[PromptCrafter] {provider_name} is online. Found {model_count} model(s).\033[0m")
            elif status == 'connection_error':
                print(f"\033[91m[PromptCrafter] {provider_name} is OFFLINE. Is it running at {provider_config['base_url']}?")
        except Exception as e:
            print(f"\033[91m[PromptCrafter] An unexpected error occurred while checking status for {provider.capitalize()}: {e}")

def _filter_kwargs(func: Callable, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    sig = inspect.signature(func)
    if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()): return kwargs
    allowed_keys = {p.name for p in sig.parameters.values() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    return {k: v for k, v in kwargs.items() if k in allowed_keys}

def query_model_auto(model, prompt, images=None, max_tokens=None, **kwargs):
    """Dispatches a text/vision query to the appropriate API client."""
    from ..utils import pgfx_utils as utils
    images_b64 = [utils.encode_image(im) for im in images if im is not None] if images else []
    utils._debug_print(kwargs.get("debug_mode", False), kwargs.get("debug_title", "") or f"Query to {model}", prompt)
    
    if max_tokens:
        kwargs['max_tokens'] = max_tokens

    # --- FIX: Always expect 'provider/model_id' format ---
    try:
        provider, model_id = model.split('/', 1)
    except ValueError:
        # Fallback for old workflows that might have a raw GGUF path without the 'gguf/' prefix.
        if model.strip().lower().endswith('.gguf'):
            print(f"\033[93m[PromptCrafter] Warning: Deprecated model format detected. Assuming '{model}' is a GGUF file. Please resave your workflow to use the 'gguf/{model}' format.\033[0m")
            provider = 'gguf'
            model_id = model
        else:
            # If the model is not in the "provider/model_id" format and not a .gguf file,
            # we assume it's a local model and determine the provider based on availability.
            if config.HF_TRANSFORMERS_AVAILABLE and model in get_local_hf_models():
                provider = 'hf'
                model_id = model
            elif config.LLAMA_CPP_AVAILABLE and model in get_local_llm_gguf_files():
                provider = 'gguf'
                model_id = model
            else:
                return False, f"Invalid model format '{model}'. Expected 'provider/model_name' or a valid local model name."

    client = CLIENT_REGISTRY.get(provider.lower())
    if not client:
        return False, f"No client configured for provider '{provider}'. Check your installation and configuration."

    filtered_kwargs = _filter_kwargs(client.query, kwargs)
    return client.query(model_id, prompt, images_b64=images_b64, **filtered_kwargs)

# Apply the decorator to the public entry points.
query_model_auto = _with_ollama_throttle(query_model_auto)

def _reason_with_model(model, prompt, images=None, **kwargs):
    if 'use_chat_api' in kwargs:
        kwargs['prefer_chat'] = kwargs.pop('use_chat_api')
    kwargs.setdefault('prefer_chat', True)
    kwargs.setdefault('temperature', 0.0)
    
    ok, resp = query_model_auto(model, prompt, images=images, **kwargs)
    if not ok:
        return False, resp
    # Added check for empty or whitespace-only response from the model
    if not resp or not resp.strip():
        return False, "Model returned an empty or whitespace-only response."
    try:
        parsed = json_utils.extract_and_parse_json(resp)
    except Exception as e:
        return False, f"Failed to parse JSON from model response. Error: {e}"
    if parsed is None:
        return False, "Failed to parse JSON from model response."
    return True, parsed

# Apply the decorator to the public entry points.
# _reason_with_model = _with_ollama_throttle(_reason_with_model) # Removed to prevent deadlock as it calls query_model_auto which is already throttled

# ------------------------------------------------------------------------------------
# Model Discovery
# ------------------------------------------------------------------------------------

_model_cache = {}
_cache_lock = threading.Lock()
CACHE_EXPIRATION_SECONDS = 300

class ModelInspector:
    """A helper class to determine model capabilities from its metadata."""
    VISION_KEYWORDS = {"llava", "moondream", "bakllava", "fuyu", "idefics", "qwen", "qwen2", "qwen2.5", "qwen3", "vision", "clip", "mmproj", "minicpm", "glm", "florence"}

    @classmethod
    def is_vision_model(cls, model_details: dict) -> bool:
        details = model_details.get("details", {})
        if details:
            families = details.get("families") or []
            architecture = details.get("general.architecture", "")
            if any(f in cls.VISION_KEYWORDS for f in families) or any(kw in architecture for kw in cls.VISION_KEYWORDS):
                return True
        # Check both 'id' and 'name' as some providers (like Ollama) use 'name'
        model_id = (model_details.get("id") or model_details.get("name") or "").lower()
        return any(kw in model_id for kw in cls.VISION_KEYWORDS)

def get_local_llm_gguf_files():
    """Scans subdirectories of ComfyUI/models/LLM for .gguf files."""
    if not config.LLAMA_CPP_AVAILABLE:
        return ["llama-cpp-python not installed"]
    local_models = []
    try:
        llm_dir = config.LLM_MODEL_DIR
        if not os.path.isdir(llm_dir):
            return ["LLM_directory_not_found"]

        # Recursively scan for .gguf files
        for root, _, files in os.walk(llm_dir):
            for file in files:
                if file.lower().endswith('.gguf') and "mmproj" not in file.lower():
                    local_models.append(os.path.relpath(os.path.join(root, file), llm_dir).replace('\\', '/'))
        
        if not local_models:
            return ["no_local_gguf_files_found"]
    except Exception as e:
        print(f"\033[93m[PromptCrafter] Warning: Could not scan 'models/LLM' for GGUF files. Error: {e}\033[0m")
        return [f"error_scanning_llm_dir:_{e}"]
    return sorted(local_models)

def get_local_hf_models():
    """Scans configured directories for local HuggingFace models."""
    if not config.HF_TRANSFORMERS_AVAILABLE:
        return ["HF Transformers not installed"]
    
    local_models = set()
    for model_dir in config.HF_MODEL_DIRS:
        try:
            if not os.path.isdir(model_dir):
                continue
            for model_folder in os.listdir(model_dir):
                full_path = os.path.join(model_dir, model_folder)
                # Check if it's a directory and contains a config.json file
                if os.path.isdir(full_path) and os.path.exists(os.path.join(full_path, 'config.json')):
                    local_models.add(model_folder)
        except Exception as e:
            print(f"[93m[PromptCrafter] Warning: Could not scan '{model_dir}' for HuggingFace models. Error: {e}[0m")
            
    return sorted(list(local_models))


def get_local_qwen_models():
    """
    Scans for local HuggingFace models and filters for those with 'qwen' in their name.
    This function is kept for backward compatibility.
    """
    all_hf_models = get_local_hf_models()
    if not all_hf_models or "not installed" in all_hf_models[0]:
        return ["HF Transformers not installed"]
    
    qwen_models = [model for model in all_hf_models if "qwen" in model.lower()]
    
    if not qwen_models:
        return ["no_local_qwen_files_found"]
        
    return qwen_models
    """Scans configured directories for local HuggingFace models."""
    if not config.HF_TRANSFORMERS_AVAILABLE:
        return ["HF Transformers not installed"]
    
    local_models = set()
    for model_dir in config.HF_MODEL_DIRS:
        try:
            if not os.path.isdir(model_dir):
                continue
            for model_folder in os.listdir(model_dir):
                full_path = os.path.join(model_dir, model_folder)
                # Check if it's a directory and contains a config.json file
                if os.path.isdir(full_path) and os.path.exists(os.path.join(full_path, 'config.json')):
                    local_models.add(model_folder)
        except Exception as e:
            print(f"\033[93m[PromptCrafter] Warning: Could not scan '{model_dir}' for HuggingFace models. Error: {e}\033[0m")
            
    return sorted(list(local_models))


def _get_models_by_type(model_type):
    global _model_cache
    with _cache_lock:
        now = time.time()
        cache_key = f"{model_type}_api"
        if cache_key in _model_cache:
            cached_data, timestamp = _model_cache[cache_key]
            if now - timestamp < CACHE_EXPIRATION_SECONDS:
                return cached_data

    all_api_models_details = _get_all_model_data()
    filtered_api_models = []

    # Get local GGUF and HF models
    local_gguf_models = get_local_llm_gguf_files()
    local_hf_models = get_local_hf_models()

    # Add local GGUF models
    for model in local_gguf_models:
        if not any(err in model for err in ["not installed", "not_found", "error_scanning"]):
            model_id = f"gguf/{model}"
            is_vision = ModelInspector.is_vision_model({"id": model_id})
            if model_type == "all" or (model_type == "vision" and is_vision) or (model_type == "text" and not is_vision):
                filtered_api_models.append(model_id)

    # Add local HuggingFace models
    for model in local_hf_models:
        if "not installed" not in model:
            # Assume all detected HF models could be vision models, let the user decide.
            # A more advanced check could read the config.json for vision keywords.
            model_id = f"hf/{model}"
            is_vision = ModelInspector.is_vision_model({"id": model_id})
            if model_type == "all" or (model_type == "vision" and is_vision) or (model_type == "text" and not is_vision):
                 filtered_api_models.append(model_id)

    # Then process remote API models (Ollama, etc.)
    for m in all_api_models_details:
        is_vision = ModelInspector.is_vision_model(m)
        model_name = m["name"]
        if model_type == "all" or (model_type == "vision" and is_vision) or (model_type == "text" and not is_vision):
            filtered_api_models.append(model_name)

    available_models = sorted(list(set(filtered_api_models)))

    if not available_models:
        available_models = ["NO_MODELS_FOUND"]
    else:
        preferred_fallback_base = config.FALLBACK_VISION_MODEL if model_type == "vision" else config.FALLBACK_TEXT_MODEL
        preferred_model_found = next((m for m in available_models if m.endswith(f"/{preferred_fallback_base}")), None)
        if preferred_model_found:
            available_models.remove(preferred_model_found)
            available_models.insert(0, preferred_model_found)
    
    with _cache_lock:
        _model_cache[cache_key] = (available_models, time.time())
    return available_models

def _get_provider_models(provider, provider_config, log_errors=True):
    base_url = provider_config["base_url"]
    status, models = 'other_error', []
    session = config.SHARED_SESSION or requests
    try:
        if provider == "ollama":
            resp = session.get(f"{base_url}/api/tags", timeout=provider_config["timeout"])
        elif provider in ["lmstudio", "text-generation-webui"]:
            resp = session.get(f"{base_url}/v1/models", timeout=provider_config["timeout"])
        else:
            return 'not_supported', []

        resp.raise_for_status()
        data = resp.json()

        if provider == "ollama":
            models = data.get("models", [])
        elif provider in ["lmstudio", "text-generation-webui"]:
            lm_models = data.get("data", [])
            models = [{"name": m.get("id"), "id": m.get("id"), "details": {}} for m in lm_models]

        for model_info in models:
            model_info["name"] = f"{provider}/{model_info.get('name') or model_info.get('id')}"

        status = 'ok'
    except requests.exceptions.ConnectionError:
        status = 'connection_error'
        if log_errors: print(f"\033[93m[PromptCrafter] Info: {provider.capitalize()} is offline. If you use it, please ensure it's running at {base_url}.\033[0m")
    except requests.exceptions.RequestException as e:
        if log_errors: print(f"\033[93m[PromptCrafter] Warning: Could not fetch {provider.capitalize()} models. Error: {e}\033[0m")
    return status, models

def _get_all_model_data(log_errors=True):
    all_models = []
    for provider, provider_config in config.LOCAL_SERVER_CONFIG.items():
        if provider_config.get("enabled", True):
            _, models = _get_provider_models(provider, provider_config, log_errors)
            all_models.extend(models)
    return all_models

def get_vision_models(): return _get_models_by_type("vision")
def get_text_models(): return _get_models_by_type("text")
def get_all_models(): return _get_models_by_type("all")

# Deprecated function, kept for compatibility, but local GGUF files are now discovered directly.
def get_local_llm_folders():
    return []
