# Standard library imports
import os
import io
import json
import time
import inspect
import re
import contextlib
import contextvars
import threading
import errno
import uuid
import queue
import subprocess
from typing import Callable, Dict, Any

# Third-party imports
import requests

# Local module imports
import base64
from . import pgfx_config as config
from ..utils import pgfx_json_utils as json_utils
try:
    import folder_paths
except Exception:
    folder_paths = None

# >>> API_OLLAMA_THROTTLE >>>

# ----------------------------------------------------------------------
# 3️⃣  Global throttling for all Ollama calls – prevents overload.
# ----------------------------------------------------------------------
import threading
import functools

_MAX_OLLAMA_CONCURRENT_CALLS = 1   # set >1 only if you have a multi‑GPU server
_ollama_semaphore = threading.Semaphore(_MAX_OLLAMA_CONCURRENT_CALLS)
_LLM_RUNTIME_OVERRIDES = contextvars.ContextVar("pgfx_llm_runtime_overrides", default={})

def _with_ollama_throttle(func):
    """Decorator that serialises access to Ollama."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _ollama_semaphore:
            return func(*args, **kwargs)
    return wrapper

# Apply the decorator to the public entry points.
# <<< API_OLLAMA_THROTTLE <<<

def _normalize_llm_device_choice(choice):
    value = str(choice or "").strip().lower()
    if value in {"cpu", "host", "cpu-only", "cpu only"}:
        return "cpu"
    return "default"

def push_llm_runtime_context(llm_device=None, reset_context=None):
    current = _LLM_RUNTIME_OVERRIDES.get({})
    updated = dict(current)
    if llm_device is not None:
        updated["llm_device"] = llm_device
    if reset_context is not None:
        updated["reset_context"] = bool(reset_context)
    return _LLM_RUNTIME_OVERRIDES.set(updated)

def pop_llm_runtime_context(token):
    if token is None:
        return
    try:
        _LLM_RUNTIME_OVERRIDES.reset(token)
    except Exception:
        pass

@contextlib.contextmanager
def llm_runtime_context(llm_device=None, reset_context=None):
    token = push_llm_runtime_context(llm_device=llm_device, reset_context=reset_context)
    try:
        yield
    finally:
        pop_llm_runtime_context(token)

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
    from transformers import AutoProcessor, AutoModelForCausalLM, AutoConfig, BitsAndBytesConfig
    try:
        # Present in some transformers versions.
        from transformers import AutoModelForConditionalGeneration
    except ImportError:
        try:
            # Newer transformers expose Seq2Seq instead of ConditionalGeneration.
            from transformers import AutoModelForSeq2SeqLM as AutoModelForConditionalGeneration
        except ImportError:
            # Final fallback keeps HF loading available for CausalLM-only environments.
            AutoModelForConditionalGeneration = AutoModelForCausalLM
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
    class AutoModelForConditionalGeneration(DummyModel): pass
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
    _model_runtime = {}  # Runtime tuning metadata per loaded model
    _vram_probe_lock = threading.Lock()
    _last_vram_probe_ts = 0.0
    _last_vram_free_mib = None

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
                self._model_runtime.pop(model_to_evict, None)
                import gc
                try:
                    if 'torch' in globals() and torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except NameError:
                    pass
                gc.collect()

    def is_configured(self):
        return config.LLAMA_CPP_AVAILABLE

    @classmethod
    def _get_free_vram_mib(cls):
        now = time.time()
        with cls._vram_probe_lock:
            if cls._last_vram_free_mib is not None and (now - cls._last_vram_probe_ts) < 3.0:
                return cls._last_vram_free_mib

        free_mib = None

        # Prefer torch runtime signal when available.
        try:
            if 'torch' in globals() and torch.cuda.is_available():
                free_bytes, _ = torch.cuda.mem_get_info()
                free_mib = int(free_bytes // (1024 * 1024))
        except Exception:
            free_mib = None

        # Fallback to nvidia-smi for environments where torch is unavailable at this stage.
        if free_mib is None:
            try:
                res = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                    capture_output=True,
                    text=True,
                    timeout=1.5,
                    check=False,
                )
                if res.returncode == 0:
                    first_line = (res.stdout or "").strip().splitlines()
                    if first_line:
                        token = first_line[0].strip().split()[0]
                        free_mib = int(token)
            except Exception:
                free_mib = None

        with cls._vram_probe_lock:
            cls._last_vram_probe_ts = now
            cls._last_vram_free_mib = free_mib

        return free_mib

    def _resolve_vision_runtime_defaults(self):
        auto_tune = bool(getattr(config, "GGUF_AUTO_TUNE", True))
        profile = str(getattr(config, "GGUF_PROFILE", "balanced")).strip().lower()
        if profile not in {"safe", "balanced", "speed"}:
            profile = "balanced"

        free_mib = self._get_free_vram_mib()
        has_cuda = False
        try:
            has_cuda = bool('torch' in globals() and torch.cuda.is_available())
        except Exception:
            has_cuda = False
        if free_mib is not None and free_mib > 0:
            has_cuda = True

        n_gpu_layers = int(getattr(config, "VISION_GGUF_N_GPU_LAYERS", 0))
        n_batch = int(getattr(config, "VISION_GGUF_N_BATCH", 128))
        n_ubatch = int(getattr(config, "VISION_GGUF_N_UBATCH", 64))
        unload_after_query = bool(getattr(config, "GGUF_UNLOAD_VISION_AFTER_QUERY", True))

        if auto_tune and not getattr(config, "VISION_GGUF_N_GPU_LAYERS_WAS_SET", False):
            if not has_cuda:
                n_gpu_layers = 0
            elif free_mib is None:
                if profile == "safe":
                    n_gpu_layers = 2
                elif profile == "speed":
                    n_gpu_layers = 10
                else:
                    n_gpu_layers = 6
            else:
                if profile == "safe":
                    if free_mib >= 10000:
                        n_gpu_layers = 10
                    elif free_mib >= 8500:
                        n_gpu_layers = 6
                    elif free_mib >= 7000:
                        n_gpu_layers = 2
                    else:
                        n_gpu_layers = 0
                elif profile == "speed":
                    if free_mib >= 10500:
                        n_gpu_layers = -1
                    elif free_mib >= 9000:
                        n_gpu_layers = 16
                    elif free_mib >= 7500:
                        n_gpu_layers = 10
                    elif free_mib >= 6200:
                        n_gpu_layers = 6
                    elif free_mib >= 5000:
                        n_gpu_layers = 2
                    else:
                        n_gpu_layers = 0
                else:
                    if free_mib >= 10000:
                        n_gpu_layers = 16
                    elif free_mib >= 8500:
                        n_gpu_layers = 10
                    elif free_mib >= 7000:
                        n_gpu_layers = 6
                    elif free_mib >= 6000:
                        n_gpu_layers = 4
                    elif free_mib >= 5000:
                        n_gpu_layers = 2
                    else:
                        n_gpu_layers = 0

        if auto_tune and not getattr(config, "VISION_GGUF_N_BATCH_WAS_SET", False):
            if n_gpu_layers == -1 or n_gpu_layers >= 12:
                n_batch = 128
            elif n_gpu_layers >= 6:
                n_batch = 96
            else:
                n_batch = 64
        if auto_tune and not getattr(config, "VISION_GGUF_N_UBATCH_WAS_SET", False):
            n_ubatch = 64 if n_batch >= 128 else 32
        if auto_tune and not getattr(config, "GGUF_UNLOAD_VISION_AFTER_QUERY_WAS_SET", False):
            if n_gpu_layers == 0:
                unload_after_query = True
            elif profile == "speed":
                unload_after_query = False
            else:
                # Balanced/Safe defaults prioritize avoiding downstream OOM when
                # large diffusion/ACE models load after PromptCrafter stages.
                unload_after_query = True

        n_batch = max(32, int(n_batch))
        n_ubatch = max(32, min(int(n_ubatch), n_batch))

        return {
            "auto_tune": auto_tune,
            "profile": profile,
            "free_vram_mib": free_mib,
            "n_gpu_layers": int(n_gpu_layers),
            "n_batch": int(n_batch),
            "n_ubatch": int(n_ubatch),
            "unload_after_query": bool(unload_after_query),
        }

    def _load_model(self, model_id: str, **kwargs):
        # Loads a GGUF model, handling vision capabilities and potential errors.
        # This function is separated to cleanly manage model loading and caching.
        
        # 1. Normalize path and check for existence
        model_id_without_prefix = _normalize_gguf_model_relpath(model_id)
        normalized_model_path, attempted_paths = _resolve_gguf_model_path(model_id_without_prefix)

        if normalized_model_path is None:
            preferred_path = os.path.join(config.LLM_MODEL_DIR, model_id_without_prefix.replace('/', os.path.sep))
            attempted_lines = "\n - ".join(attempted_paths[:12]) if attempted_paths else "(no candidate paths generated)"
            raise FileNotFoundError(
                errno.ENOENT,
                f"GGUF model not found. Tried:\n - {attempted_lines}",
                preferred_path,
            )


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
        is_vision_model = any(
            kw in model_id.lower()
            for kw in {"llava", "moondream", "bakllava", "fuyu", "idefics", "qwen", "vision", "clip", "mmproj"}
        )
        vision_runtime = self._resolve_vision_runtime_defaults() if is_vision_model else None
        default_n_gpu_layers = (
            vision_runtime["n_gpu_layers"]
            if is_vision_model and vision_runtime is not None
            else getattr(config, "VISION_GGUF_N_GPU_LAYERS", 0)
            if is_vision_model
            else getattr(config, "DEFAULT_GGUF_N_GPU_LAYERS", -1)
        )
        if "n_gpu_layers" in kwargs:
            n_gpu_layers = int(kwargs.get("n_gpu_layers", default_n_gpu_layers))
            if is_vision_model and n_gpu_layers == -1 and default_n_gpu_layers != -1:
                # Keep legacy workflows stable: for VLMs, explicit -1 can hard-crash on 8-12GB cards.
                print(
                    f"\033[93m[PromptCrafter] Vision model requested n_gpu_layers=-1. "
                    f"Using safe default n_gpu_layers={default_n_gpu_layers} instead. "
                    f"Set PGFX_VISION_GGUF_N_GPU_LAYERS=-1 to force full GPU offload.\033[0m"
                )
                n_gpu_layers = default_n_gpu_layers
        else:
            n_gpu_layers = default_n_gpu_layers
        n_ctx = int(kwargs.get("n_ctx", getattr(config, "DEFAULT_GGUF_N_CTX", 4096)))
        min_n_ctx = int(kwargs.get("min_n_ctx", getattr(config, "MIN_GGUF_N_CTX", 1024)))
        n_ctx = max(256, n_ctx)
        min_n_ctx = max(256, min(min_n_ctx, n_ctx))
        default_n_batch = (
            vision_runtime["n_batch"]
            if is_vision_model and vision_runtime is not None
            else getattr(config, "VISION_GGUF_N_BATCH", 128)
            if is_vision_model
            else getattr(config, "DEFAULT_GGUF_N_BATCH", 512)
        )
        default_n_ubatch = (
            vision_runtime["n_ubatch"]
            if is_vision_model and vision_runtime is not None
            else getattr(config, "VISION_GGUF_N_UBATCH", 64)
            if is_vision_model
            else getattr(config, "DEFAULT_GGUF_N_UBATCH", 256)
        )
        n_batch = int(kwargs.get("n_batch", default_n_batch))
        n_ubatch = int(kwargs.get("n_ubatch", default_n_ubatch))
        n_batch = max(32, min(n_batch, n_ctx))
        n_ubatch = max(32, min(n_ubatch, n_batch))
        offload_kqv = bool(kwargs.get("offload_kqv", n_gpu_layers != 0))
        allow_cpu_retry = bool(kwargs.get("enable_cpu_retry", getattr(config, "GGUF_ENABLE_CPU_RETRY", False)))
        llama_kwargs = {
            "model_path": normalized_model_path,
            "n_ctx": n_ctx,
            "n_gpu_layers": n_gpu_layers,
            "n_batch": n_batch,
            "n_ubatch": n_ubatch,
            "offload_kqv": offload_kqv,
            "verbose": True,
        }
        def _supports_llama_arg(arg_name: str) -> bool:
            try:
                return arg_name in inspect.signature(Llama.__init__).parameters
            except Exception:
                return False

        if is_vision_model and "qwen" in model_id.lower():
            image_min_tokens = int(getattr(config, "QWEN_VL_IMAGE_MIN_TOKENS", 0) or 0)
            if image_min_tokens > 0 and _supports_llama_arg("image_min_tokens"):
                llama_kwargs["image_min_tokens"] = image_min_tokens
            elif image_min_tokens > 0:
                print(
                    "\033[93m[PromptCrafter] Llama() does not accept image_min_tokens in this "
                    "llama-cpp-python build. Consider upgrading for better Qwen-VL grounding.\033[0m"
                )
        print(
            f"\033[94m[PromptCrafter] GGUF runtime settings for '{model_id}': "
            f"n_ctx={n_ctx}, n_gpu_layers={n_gpu_layers}, n_batch={n_batch}, n_ubatch={n_ubatch}, offload_kqv={offload_kqv}\033[0m"
        )
        if is_vision_model and vision_runtime is not None:
            free_vram_display = vision_runtime["free_vram_mib"] if vision_runtime["free_vram_mib"] is not None else "unknown"
            print(
                f"\033[94m[PromptCrafter] Vision runtime policy for '{model_id}': "
                f"profile={vision_runtime['profile']}, auto_tune={vision_runtime['auto_tune']}, "
                f"free_vram={free_vram_display} MiB, unload_after_query={vision_runtime['unload_after_query']}\033[0m"
            )
        if is_vision_model and n_gpu_layers == 0:
            print(
                "\033[93m[PromptCrafter] Vision GGUF is configured with n_gpu_layers=0. "
                "Inference will be CPU-dominant and significantly slower.\033[0m"
            )

        def _remember_runtime(effective_llama_kwargs):
            with self._cache_lock:
                self._model_runtime[model_id] = {
                    "is_vision_model": is_vision_model,
                    "n_ctx": int(effective_llama_kwargs.get("n_ctx", n_ctx)),
                    "n_gpu_layers": int(effective_llama_kwargs.get("n_gpu_layers", n_gpu_layers)),
                    "n_batch": int(effective_llama_kwargs.get("n_batch", n_batch)),
                    "n_ubatch": int(effective_llama_kwargs.get("n_ubatch", n_ubatch)),
                    "unload_after_query": (
                        vision_runtime["unload_after_query"]
                        if is_vision_model and vision_runtime is not None
                        else bool(getattr(config, "GGUF_UNLOAD_VISION_AFTER_QUERY", True))
                    ),
                    "profile": vision_runtime["profile"] if is_vision_model and vision_runtime is not None else "n/a",
                    "free_vram_mib": vision_runtime["free_vram_mib"] if is_vision_model and vision_runtime is not None else None,
                }

        def _looks_like_context_oom(err):
            msg = str(err).lower()
            markers = (
                "out of memory",
                "cudamalloc failed",
                "failed to allocate buffer for kv cache",
                "failed to create context",
                "alloc_tensor_range",
                "cuda_host",
            )
            return any(m in msg for m in markers)
        # 3. Handle Vision Models
        
        if is_vision_model:
            print(f"\033[94m[PromptCrafter] Vision model detected. Auto-configuring chat handler...\033[0m")
            explicit_projector_kw = "vision_projector_use_gpu" in kwargs
            if explicit_projector_kw:
                vision_projector_use_gpu = bool(kwargs.get("vision_projector_use_gpu", False))
            elif getattr(config, "GGUF_VISION_PROJECTOR_USE_GPU_WAS_SET", False):
                vision_projector_use_gpu = bool(getattr(config, "GGUF_VISION_PROJECTOR_USE_GPU", False))
            else:
                # Auto-enable projector GPU when vision offload is already active and VRAM looks healthy.
                auto_gpu = False
                free_mib = None
                if vision_runtime is not None:
                    free_mib = vision_runtime.get("free_vram_mib")
                    if int(vision_runtime.get("n_gpu_layers", 0)) != 0:
                        auto_gpu = True
                if free_mib is not None and free_mib < 5000:
                    auto_gpu = False
                vision_projector_use_gpu = auto_gpu
                if vision_projector_use_gpu:
                    print(
                        "\033[94m[PromptCrafter] Auto-enabled vision projector GPU backend. "
                        "Set PGFX_GGUF_VISION_PROJECTOR_USE_GPU=0 to force CPU.\033[0m"
                    )
            
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
                        
                    def _supports_handler_arg(arg_name: str) -> bool:
                        try:
                            return arg_name in inspect.signature(Qwen3VLChatHandler.__init__).parameters
                        except Exception:
                            return False

                    force_reasoning = "thinking" in model_id.lower()
                    handler_kwargs = {
                        "clip_model_path": os.path.join(model_dir, projector_file),
                        "force_reasoning": force_reasoning,
                        "use_gpu": vision_projector_use_gpu,
                    }
                    image_min_tokens = int(getattr(config, "QWEN_VL_IMAGE_MIN_TOKENS", 0) or 0)
                    if image_min_tokens > 0 and _supports_handler_arg("image_min_tokens"):
                        handler_kwargs["image_min_tokens"] = image_min_tokens
                    elif image_min_tokens > 0:
                        print(
                            "\033[93m[PromptCrafter] Qwen3VLChatHandler does not accept image_min_tokens in this "
                            "llama-cpp-python build. Consider upgrading for better grounding.\033[0m"
                        )

                    chat_handler = Qwen3VLChatHandler(**handler_kwargs)
                    projector_backend = "GPU" if vision_projector_use_gpu else "CPU"
                    print(
                        f"\033[92m[PromptCrafter] Configured Qwen3VLChatHandler with projector '{projector_file}' "
                        f"(backend={projector_backend}).\033[0m"
                    )

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

            # For context/VRAM allocation failures, first try a smaller n_ctx before any CPU fallback.
            if _looks_like_context_oom(e) and llama_kwargs.get("n_ctx", n_ctx) > min_n_ctx:
                reduced_ctx = max(min_n_ctx, llama_kwargs["n_ctx"] // 2)
                retry_kwargs = dict(llama_kwargs)
                retry_kwargs["n_ctx"] = reduced_ctx
                print(
                    f"\033[93m[PromptCrafter] GGUF context allocation failed. "
                    f"Retrying with reduced n_ctx={reduced_ctx} (was {llama_kwargs['n_ctx']}). Error: {e}\033[0m"
                )
                try:
                    llm = Llama(**retry_kwargs)
                    llama_kwargs = retry_kwargs
                    _remember_runtime(llama_kwargs)
                    return llm, is_vision_model
                except Exception as reduced_e:
                    e = reduced_e

            # GPU allocation/context failures can crash some llama.cpp builds if CPU fallback is immediate.
            if n_gpu_layers != 0 and _looks_like_context_oom(e) and not allow_cpu_retry:
                raise RuntimeError(
                    f"GGUF load failed due GPU memory/KV cache limits "
                    f"(n_ctx={llama_kwargs.get('n_ctx')}, n_gpu_layers={n_gpu_layers}). "
                    f"Try a smaller model, lower context via PGFX_GGUF_N_CTX "
                    f"(e.g. 2048), or enable explicit CPU retry with PGFX_GGUF_ENABLE_CPU_RETRY=1. "
                    f"Original error: {e}"
                ) from e

            # Legacy fallback for non-oom failures, or explicit opt-in CPU retry.
            if n_gpu_layers != 0:
                cpu_retry_ctx = max(min_n_ctx, min(llama_kwargs.get("n_ctx", n_ctx), getattr(config, "DEFAULT_GGUF_N_CTX", 4096)))
                print(
                    f"\033[93m[PromptCrafter] Initial GGUF load failed. "
                    f"Retrying with CPU only (n_gpu_layers=0, n_ctx={cpu_retry_ctx}). "
                    f"This fallback is much slower than GPU offload. Error: {e}\033[0m"
                )
                cpu_kwargs = dict(llama_kwargs)
                cpu_kwargs["n_gpu_layers"] = 0
                cpu_kwargs["n_ctx"] = cpu_retry_ctx
                cpu_kwargs["offload_kqv"] = False
                llm = Llama(**cpu_kwargs)  # CPU retry
                llama_kwargs = cpu_kwargs
            else:
                raise e  # Re-raise if it already failed on CPU

        _remember_runtime(llama_kwargs)
        return llm, is_vision_model

    def query(self, model_id, prompt, images_b64=None, timeout=None, temperature=None, seed=None, max_tokens=None, **kwargs):
        if not self.is_configured():
            return False, "GGUFClient is not configured because `llama-cpp-python` is not installed."

        if max_tokens is None:
            max_tokens = config.DEFAULT_MAX_TOKENS
        if timeout is None:
            timeout = getattr(config, "GGUF_DEFAULT_TIMEOUT_SECONDS", 180)
        try:
            timeout_seconds = float(timeout) if timeout is not None else None
        except Exception:
            timeout_seconds = float(getattr(config, "GGUF_DEFAULT_TIMEOUT_SECONDS", 180))
        if timeout_seconds is not None and timeout_seconds <= 0:
            timeout_seconds = None
        allow_partial_on_timeout = bool(kwargs.get("allow_partial_on_timeout", False))
        reset_context = bool(kwargs.get("reset_context", getattr(config, "DEFAULT_LLM_STATELESS", True)))

        llm = None
        is_vision_model = False
        unload_after_query = bool(kwargs.get("unload_after_query", False))
        unload_vision_after_query_from_kwargs = "unload_vision_after_query" in kwargs
        unload_vision_after_query = bool(
            kwargs.get(
                "unload_vision_after_query",
                getattr(config, "GGUF_UNLOAD_VISION_AFTER_QUERY", True),
            )
        )

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

            runtime_info = self._model_runtime.get(model_id, {})
            active_n_ctx = max(256, int(runtime_info.get("n_ctx", getattr(config, "DEFAULT_GGUF_N_CTX", 4096))))

            if is_vision_model and not unload_vision_after_query_from_kwargs:
                if not getattr(config, "GGUF_UNLOAD_VISION_AFTER_QUERY_WAS_SET", False):
                    runtime_unload = runtime_info.get("unload_after_query", None)
                    if runtime_unload is not None:
                        unload_vision_after_query = bool(runtime_unload)

            if reset_context:
                try:
                    llm.reset()
                except Exception:
                    pass

            # --- Inference ---
            prefer_chat = bool(kwargs.get("prefer_chat", False))

            def _timeout_error(partial_content=""):
                if timeout_seconds is None:
                    return f"GGUF model '{model_id}' timed out."
                timeout_display = int(timeout_seconds) if float(timeout_seconds).is_integer() else timeout_seconds
                msg = f"GGUF model '{model_id}' timed out after {timeout_display} seconds."
                if partial_content:
                    msg += f" Partial output length: {len(partial_content)} chars."
                return msg

            def _looks_like_prompt_overflow(err):
                msg = str(err).lower()
                markers = (
                    "prompt exceeds n_ctx",
                    "prompt is too long",
                    "too many tokens",
                    "context window",
                )
                return any(marker in msg for marker in markers)

            def _looks_like_kv_slot_error(err):
                msg = str(err).lower()
                markers = (
                    "no kv slot available",
                    "decode failed at pos",
                    "failed to find a memory slot",
                    "memory_seq_rm",
                    "llama_decode failed",
                )
                return any(marker in msg for marker in markers)

            def _extract_prompt_overflow_counts(err):
                err_text = str(err)
                match = re.search(r"prompt exceeds n_ctx:\s*(\d+)\s*>\s*(\d+)", err_text, flags=re.IGNORECASE)
                if not match:
                    return None, None
                try:
                    return int(match.group(1)), int(match.group(2))
                except Exception:
                    return None, None

            def _trim_prompt_for_context(
                prompt_text,
                n_ctx_limit,
                observed_prompt_tokens=None,
                extra_reduction_tokens=0,
            ):
                safe_prompt = "" if prompt_text is None else str(prompt_text)
                reserve_tokens = int(kwargs.get("prompt_trim_reserve_tokens", 192))
                if is_vision_model and images_b64:
                    reserve_tokens = max(
                        reserve_tokens,
                        int(kwargs.get("vision_prompt_trim_reserve_tokens", 1536)),
                    )
                elif is_vision_model or bool(kwargs.get("prefer_chat", False)):
                    reserve_tokens = max(
                        reserve_tokens,
                        int(kwargs.get("chat_prompt_trim_reserve_tokens", 384)),
                    )
                reserve_tokens = max(32, reserve_tokens + max(0, int(extra_reduction_tokens)))
                max_prompt_tokens = max(64, int(n_ctx_limit) - reserve_tokens)
                marker = "\n\n[... prompt trimmed to fit GGUF context window ...]\n\n"

                token_ids = None
                original_token_count = observed_prompt_tokens

                try:
                    token_ids = llm.tokenize(safe_prompt.encode("utf-8"), add_bos=False)
                    original_token_count = len(token_ids)
                except Exception:
                    token_ids = None

                if token_ids is not None:
                    if len(token_ids) <= max_prompt_tokens:
                        return safe_prompt, len(token_ids), len(token_ids), False

                    marker_tokens = []
                    try:
                        marker_tokens = llm.tokenize(marker.encode("utf-8"), add_bos=False)
                    except Exception:
                        marker_tokens = []

                    available = max(32, max_prompt_tokens - len(marker_tokens))
                    head = max(16, int(available * 0.65))
                    tail = max(16, available - head)
                    if head + tail > len(token_ids):
                        head = min(head, len(token_ids))
                        tail = max(0, len(token_ids) - head)

                    combined_tokens = token_ids[:head]
                    if marker_tokens:
                        combined_tokens += marker_tokens
                    if tail > 0:
                        combined_tokens += token_ids[-tail:]

                    combined_tokens = combined_tokens[:max_prompt_tokens]
                    try:
                        decoded = llm.detokenize(combined_tokens)
                        trimmed_text = (
                            decoded.decode("utf-8", errors="ignore")
                            if isinstance(decoded, (bytes, bytearray))
                            else str(decoded)
                        )
                    except Exception:
                        trimmed_text = safe_prompt

                    if trimmed_text and trimmed_text != safe_prompt:
                        return trimmed_text, len(token_ids), len(combined_tokens), True

                if original_token_count is None:
                    original_token_count = max(1, len(safe_prompt) // 4)

                ratio = min(0.95, float(max_prompt_tokens) / float(max(1, original_token_count)))
                keep_chars = max(256, int(len(safe_prompt) * ratio))
                if keep_chars >= len(safe_prompt):
                    keep_chars = max(1, int(len(safe_prompt) * 0.9))
                if keep_chars <= 0:
                    return safe_prompt, int(original_token_count), int(original_token_count), False

                head_chars = max(64, int(keep_chars * 0.7))
                tail_chars = max(64, keep_chars - head_chars)
                if head_chars + tail_chars >= len(safe_prompt):
                    trimmed_text = safe_prompt[:keep_chars]
                else:
                    trimmed_text = f"{safe_prompt[:head_chars]}{marker}{safe_prompt[-tail_chars:]}"

                if trimmed_text == safe_prompt:
                    return safe_prompt, int(original_token_count), int(original_token_count), False

                approx_after = max(1, int(original_token_count * (len(trimmed_text) / max(1, len(safe_prompt)))))
                return trimmed_text, int(original_token_count), int(approx_after), True

            def _extract_chat_content(output):
                try:
                    choices = output.get("choices") if isinstance(output, dict) else None
                    choice = choices[0] if choices else {}
                    message = choice.get("message", {}) if isinstance(choice, dict) else {}
                    content_val = message.get("content", "")

                    # Some chat handlers return segmented content.
                    if isinstance(content_val, list):
                        parts = []
                        for item in content_val:
                            if isinstance(item, dict):
                                text_val = item.get("text") or item.get("content")
                                if isinstance(text_val, str):
                                    parts.append(text_val)
                            elif isinstance(item, str):
                                parts.append(item)
                        content_val = "\n".join(parts)

                    if isinstance(content_val, str) and content_val.strip():
                        return content_val.strip()

                    # Qwen/Reasoning models may put text into reasoning_content.
                    reasoning_val = message.get("reasoning_content", "")
                    if isinstance(reasoning_val, str) and reasoning_val.strip():
                        return reasoning_val.strip()

                    text_val = choice.get("text", "") if isinstance(choice, dict) else ""
                    if isinstance(text_val, str) and text_val.strip():
                        return text_val.strip()
                except Exception:
                    pass
                return ""

            def _extract_completion_content(output):
                try:
                    choices = output.get("choices") if isinstance(output, dict) else None
                    choice = choices[0] if choices else {}
                    text_val = choice.get("text", "") if isinstance(choice, dict) else ""
                    return text_val.strip() if isinstance(text_val, str) else ""
                except Exception:
                    return ""

            def _extract_chat_delta_text(chunk):
                try:
                    choices = chunk.get("choices") if isinstance(chunk, dict) else None
                    choice = choices[0] if choices else {}
                    delta = choice.get("delta", {}) if isinstance(choice, dict) else {}

                    if isinstance(delta, dict):
                        content_val = delta.get("content")
                        if isinstance(content_val, str):
                            return content_val
                        if isinstance(content_val, list):
                            parts = []
                            for item in content_val:
                                if isinstance(item, dict):
                                    text_val = item.get("text") or item.get("content")
                                    if isinstance(text_val, str):
                                        parts.append(text_val)
                                elif isinstance(item, str):
                                    parts.append(item)
                            if parts:
                                return "".join(parts)
                        reasoning_val = delta.get("reasoning_content")
                        if isinstance(reasoning_val, str):
                            return reasoning_val
                    elif isinstance(delta, str):
                        return delta

                    # Some handlers may stream plain text field directly.
                    text_val = choice.get("text", "") if isinstance(choice, dict) else ""
                    if isinstance(text_val, str):
                        return text_val
                except Exception:
                    pass
                return ""

            def _extract_completion_delta_text(chunk):
                try:
                    choices = chunk.get("choices") if isinstance(chunk, dict) else None
                    choice = choices[0] if choices else {}
                    text_val = choice.get("text", "") if isinstance(choice, dict) else ""
                    return text_val if isinstance(text_val, str) else ""
                except Exception:
                    return ""

            def _run_stream_with_idle_timeout(stream_factory, extract_fn):
                """
                Consume a blocking llama-cpp stream with idle-timeout protection.
                Timeout applies to "no chunk received for N seconds", not total runtime.
                """
                if timeout_seconds is None:
                    chunks = []
                    for chunk in stream_factory():
                        chunks.append(extract_fn(chunk))
                    return "".join(chunks).strip(), False

                out_queue: "queue.Queue[Any]" = queue.Queue()
                done_sentinel = object()

                def _producer():
                    try:
                        for chunk in stream_factory():
                            out_queue.put(chunk)
                    except Exception as stream_err:
                        out_queue.put(stream_err)
                    finally:
                        out_queue.put(done_sentinel)

                producer = threading.Thread(target=_producer, daemon=True)
                producer.start()

                chunks = []
                while True:
                    try:
                        item = out_queue.get(timeout=timeout_seconds)
                    except queue.Empty:
                        return "".join(chunks).strip(), True

                    if item is done_sentinel:
                        return "".join(chunks).strip(), False
                    if isinstance(item, Exception):
                        raise item
                    chunks.append(extract_fn(item))

            def _run_chat_completion(chat_kwargs):
                if timeout_seconds is None:
                    output = llm.create_chat_completion(**chat_kwargs)
                    return _extract_chat_content(output), False

                stream_kwargs = dict(chat_kwargs)
                stream_kwargs["stream"] = True
                return _run_stream_with_idle_timeout(
                    lambda: llm.create_chat_completion(**stream_kwargs),
                    _extract_chat_delta_text,
                )

            def _run_completion(inference_kwargs):
                if timeout_seconds is None:
                    output = llm(**inference_kwargs)
                    return _extract_completion_content(output), False

                stream_kwargs = dict(inference_kwargs)
                stream_kwargs["stream"] = True
                return _run_stream_with_idle_timeout(
                    lambda: llm(**stream_kwargs),
                    _extract_completion_delta_text,
                )

            use_chat_api = bool(is_vision_model or prefer_chat)
            content = ""
            prompt_for_inference = "" if prompt is None else str(prompt)
            max_trim_retries = int(kwargs.get("max_prompt_trim_retries", 2))
            max_trim_retries = max(0, min(max_trim_retries, 4))
            max_kv_retry_attempts = int(kwargs.get("max_kv_retry_attempts", 1))
            max_kv_retry_attempts = max(0, min(max_kv_retry_attempts, 2))
            requested_max_tokens = max(16, int(max_tokens))

            def _compute_safe_max_tokens(prompt_tokens_estimate):
                prompt_tokens_estimate = max(0, int(prompt_tokens_estimate))
                if is_vision_model and images_b64:
                    headroom = int(kwargs.get("vision_generation_headroom_tokens", 1408))
                    hard_cap = int(kwargs.get("vision_max_output_tokens_cap", 768))
                elif is_vision_model or use_chat_api:
                    headroom = int(kwargs.get("chat_generation_headroom_tokens", 512))
                    hard_cap = int(kwargs.get("chat_max_output_tokens_cap", 1024))
                else:
                    headroom = int(kwargs.get("text_generation_headroom_tokens", 256))
                    hard_cap = int(kwargs.get("text_max_output_tokens_cap", 2048))
                available = max(64, active_n_ctx - prompt_tokens_estimate - headroom)
                return max(64, min(requested_max_tokens, hard_cap, available))

            if images_b64 and not is_vision_model:
                print("\033[93m[PromptCrafter] Warning: Images provided, but the loaded GGUF model is not a vision model. Ignoring images.\033[0m")
            prompt_for_inference, pre_tokens_before, pre_tokens_after, pre_trimmed = _trim_prompt_for_context(
                prompt_for_inference,
                n_ctx_limit=active_n_ctx,
            )
            if pre_trimmed:
                print(
                    f"\033[93m[PromptCrafter] Prompt was trimmed before GGUF inference for '{model_id}' "
                    f"to fit n_ctx={active_n_ctx} ({pre_tokens_before} -> {pre_tokens_after} tokens).\033[0m"
                )

            if is_vision_model and images_b64 and bool(kwargs.get("reset_kv_before_inference", reset_context)):
                try:
                    llm.reset()
                except Exception:
                    pass

            max_tokens_for_inference = _compute_safe_max_tokens(pre_tokens_after)
            if max_tokens_for_inference < requested_max_tokens:
                print(
                    f"\033[93m[PromptCrafter] Capping GGUF max_tokens for '{model_id}' "
                    f"from {requested_max_tokens} to {max_tokens_for_inference} to preserve KV headroom.\033[0m"
                )

            trim_retry_count = 0
            kv_retry_count = 0
            while True:
                try:
                    content = ""
                    if use_chat_api:
                        if images_b64 and is_vision_model:
                            user_content = [{"type": "text", "text": prompt_for_inference}]
                            for img_b64 in images_b64:
                                user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}})
                            messages = [{"role": "user", "content": user_content}]
                        else:
                            messages = [{"role": "user", "content": prompt_for_inference}]

                        chat_kwargs = {"messages": messages, "max_tokens": int(max_tokens_for_inference)}
                        if temperature is not None:
                            chat_kwargs["temperature"] = temperature
                        if seed is not None and int(seed) >= 0:
                            chat_kwargs["seed"] = int(seed)
                        chat_kwargs["stop"] = ["<|end_of_text|>", "<|endoftext|>", "User:", "###"]

                        content, timed_out = _run_chat_completion(chat_kwargs)
                        if timed_out:
                            if content and allow_partial_on_timeout:
                                print(f"\033[93m[PromptCrafter] {_timeout_error(content)} Returning partial output as requested.\033[0m")
                                return True, content
                            return False, _timeout_error(content)
                        if not content:
                            # Retry once without explicit stop tokens to avoid premature truncation.
                            retry_kwargs = dict(chat_kwargs)
                            retry_kwargs.pop("stop", None)
                            content, timed_out = _run_chat_completion(retry_kwargs)
                            if timed_out:
                                if content and allow_partial_on_timeout:
                                    print(f"\033[93m[PromptCrafter] {_timeout_error(content)} Returning partial output as requested.\033[0m")
                                    return True, content
                                return False, _timeout_error(content)

                        # Some VLMs still behave better with plain completion in text-only mode.
                        if not content and is_vision_model and not images_b64:
                            completion_kwargs = {
                                "prompt": f"User:\n{prompt_for_inference}\n\nAssistant:\n",
                                "max_tokens": int(max_tokens_for_inference),
                                "stop": ["<|end_of_text|>", "<|endoftext|>", "User:", "###"],
                            }
                            if temperature is not None:
                                completion_kwargs["temperature"] = temperature
                            if seed is not None and int(seed) >= 0:
                                completion_kwargs["seed"] = int(seed)
                            content, timed_out = _run_completion(completion_kwargs)
                            if timed_out:
                                if content and allow_partial_on_timeout:
                                    print(f"\033[93m[PromptCrafter] {_timeout_error(content)} Returning partial output as requested.\033[0m")
                                    return True, content
                                return False, _timeout_error(content)
                    else:
                        inference_kwargs = {
                            "prompt": prompt_for_inference,
                            "max_tokens": int(max_tokens_for_inference),
                            "stop": ["<|end_of_text|>", "User:", "###"],
                        }
                        if temperature is not None:
                            inference_kwargs["temperature"] = temperature
                        if seed is not None and int(seed) >= 0:
                            inference_kwargs["seed"] = int(seed)

                        content, timed_out = _run_completion(inference_kwargs)
                        if timed_out:
                            if content and allow_partial_on_timeout:
                                print(f"\033[93m[PromptCrafter] {_timeout_error(content)} Returning partial output as requested.\033[0m")
                                return True, content
                            return False, _timeout_error(content)
                    break
                except Exception as inference_error:
                    if _looks_like_prompt_overflow(inference_error) and trim_retry_count < max_trim_retries:
                        observed_prompt_tokens, observed_n_ctx = _extract_prompt_overflow_counts(inference_error)
                        context_limit = max(256, int(observed_n_ctx or active_n_ctx))
                        overflow_tokens = (
                            max(0, int(observed_prompt_tokens) - context_limit)
                            if observed_prompt_tokens is not None
                            else 0
                        )
                        extra_reduction = overflow_tokens + (128 * (trim_retry_count + 1))
                        trimmed_prompt, before_tokens, after_tokens, trimmed = _trim_prompt_for_context(
                            prompt_for_inference,
                            n_ctx_limit=context_limit,
                            observed_prompt_tokens=observed_prompt_tokens,
                            extra_reduction_tokens=extra_reduction,
                        )
                        if not trimmed or trimmed_prompt == prompt_for_inference:
                            raise

                        trim_retry_count += 1
                        prompt_for_inference = trimmed_prompt
                        max_tokens_for_inference = _compute_safe_max_tokens(after_tokens)
                        print(
                            f"\033[93m[PromptCrafter] Prompt exceeded GGUF context and was trimmed for retry "
                            f"({before_tokens} -> {after_tokens} tokens, retry {trim_retry_count}/{max_trim_retries}).\033[0m"
                        )
                        continue

                    if _looks_like_kv_slot_error(inference_error) and kv_retry_count < max_kv_retry_attempts:
                        kv_retry_count += 1
                        extra_reduction = 256 * kv_retry_count
                        trimmed_prompt, before_tokens, after_tokens, trimmed = _trim_prompt_for_context(
                            prompt_for_inference,
                            n_ctx_limit=active_n_ctx,
                            extra_reduction_tokens=extra_reduction,
                        )
                        if trimmed and trimmed_prompt != prompt_for_inference:
                            prompt_for_inference = trimmed_prompt
                        max_tokens_for_inference = min(
                            max_tokens_for_inference,
                            _compute_safe_max_tokens(after_tokens),
                            max(64, max_tokens_for_inference // 2),
                            int(kwargs.get("kv_retry_max_tokens", 256)),
                        )
                        try:
                            llm.reset()
                        except Exception:
                            pass
                        print(
                            f"\033[93m[PromptCrafter] GGUF decode hit KV-slot limits; retrying with tighter budget "
                            f"(retry {kv_retry_count}/{max_kv_retry_attempts}, max_tokens={max_tokens_for_inference}).\033[0m"
                        )
                        continue

                    raise

            if not content:
                return False, f"GGUF model '{model_id}' returned an empty response."
            
            return True, content

        except Exception as e:
            # Consolidate error handling
            # If the error is during loading, clear the failed model from cache
            with self._cache_lock:
                self._model_cache.pop(model_id, None)
                self._last_used.pop(model_id, None) # Also remove from last_used
                self._model_runtime.pop(model_id, None)
            
            error_message = f"Error with GGUF model '{model_id}': {e}"
            # Provide more specific advice based on the error type
            if isinstance(e, FileNotFoundError):
                searched_path = getattr(e, "filename", None) or "unknown"
                details = getattr(e, "strerror", None) or str(e)
                hint = ""
                try:
                    available = get_local_llm_gguf_files()
                    if available:
                        sample = ", ".join(available[:5])
                        suffix = " ..." if len(available) > 5 else ""
                        hint = f" Available local GGUF models include: {sample}{suffix}"
                except Exception:
                    pass
                error_message = (
                    f"GGUF model file not found for '{model_id}'. "
                    f"Searched at: {searched_path}. {details} "
                    f"Please check the file exists and the name is correct in `ComfyUI/models/LLM`.{hint}"
                )
            elif "llama_chat_format" in str(e) or "clip_model_path" in str(e):
                error_message = f"GGUF vision model error for '{model_id}': {e}. This often means your version of `llama-cpp-python` is outdated or incompatible with this model's architecture. Please try upgrading it: `pip install --upgrade --force-reinstall llama-cpp-python`"
            elif "cublas" in str(e).lower() or "cuda" in str(e).lower():
                 error_message = f"GGUF CUDA error for '{model_id}': {e}. This indicates an issue with your GPU setup. Ensure your NVIDIA drivers are up to date and that your `llama-cpp-python` was compiled with the correct CUDA support."
            
            print(f"\033[91m[PromptCrafter] {error_message}\033[0m")
            # Traceback for advanced debugging by user
            import traceback
            traceback.print_exc()
            return False, error_message
        finally:
            should_unload = bool(unload_after_query or (unload_vision_after_query and is_vision_model))
            if should_unload:
                with self._cache_lock:
                    self._model_cache.pop(model_id, None)
                    self._last_used.pop(model_id, None)
                    self._model_runtime.pop(model_id, None)
                try:
                    del llm
                except Exception:
                    pass
                try:
                    import gc
                    gc.collect()
                    if 'torch' in globals() and torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass








def _find_hf_model_path_local(base_model_name):
    """
    Searches for a HuggingFace model's directory in configured model directories.
    Returns the full path if found, otherwise None.
    """
    for model_dir in _get_hf_scan_dirs():
        # Direct match (historical behavior)
        hf_path = os.path.join(model_dir, base_model_name)
        if os.path.isdir(hf_path) and os.path.exists(os.path.join(hf_path, 'config.json')):
            return hf_path

        # Nested/relative match support for extra model roots.
        rel_path = base_model_name.replace("/", os.path.sep)
        hf_rel = os.path.join(model_dir, rel_path)
        if os.path.isdir(hf_rel) and os.path.exists(os.path.join(hf_rel, 'config.json')):
            return hf_rel
    return None


def _dedupe_existing_dirs(paths):
    out = []
    seen = set()
    for p in paths:
        try:
            rp = os.path.realpath(p)
        except Exception:
            rp = p
        if rp in seen:
            continue
        seen.add(rp)
        if os.path.isdir(rp):
            out.append(rp)
    return out


def _get_registered_model_dirs(*preferred_names):
    """
    Resolve ComfyUI-registered model directories from folder_paths, including
    paths injected via extra_model_paths.yaml.
    """
    if folder_paths is None:
        return []

    paths = []
    keys = []
    try:
        keys = list(folder_paths.folder_names_and_paths.keys())
    except Exception:
        keys = []

    preferred_lower = {n.lower() for n in preferred_names if n}

    # First pass: exact names
    for name in preferred_names:
        try:
            paths.extend(folder_paths.get_folder_paths(name))
        except Exception:
            pass

    # Second pass: case-insensitive name matches
    for key in keys:
        if key.lower() in preferred_lower:
            try:
                paths.extend(folder_paths.get_folder_paths(key))
            except Exception:
                pass

    return _dedupe_existing_dirs(paths)


def _normalize_gguf_model_relpath(model_id: str) -> str:
    model_rel = (model_id or "").strip()
    if model_rel.startswith("gguf/"):
        model_rel = model_rel[len("gguf/"):]
    model_rel = model_rel.replace("\\", "/").lstrip("/")
    return model_rel


def _resolve_gguf_model_path(model_id: str):
    """
    Resolve a GGUF model id to an existing filesystem path.
    Returns (resolved_path_or_none, attempted_paths_list).
    """
    model_rel = _normalize_gguf_model_relpath(model_id)
    attempted_paths = []
    if not model_rel:
        return None, attempted_paths

    scan_dirs = _get_llm_scan_dirs() or [config.LLM_MODEL_DIR]

    # Absolute path passthrough.
    if os.path.isabs(model_rel):
        attempted_paths.append(model_rel)
        if os.path.exists(model_rel):
            return model_rel, attempted_paths

    # Primary resolution: exact relative path under each scan dir.
    rel_native = model_rel.replace("/", os.path.sep)
    for scan_dir in scan_dirs:
        candidate = os.path.join(scan_dir, rel_native)
        attempted_paths.append(candidate)
        if os.path.exists(candidate):
            return candidate, attempted_paths

    # Fallback resolution: case-insensitive and basename match from discovered GGUF files.
    discovered_rel = []
    try:
        discovered_rel = get_local_llm_gguf_files()
    except Exception:
        discovered_rel = []

    if discovered_rel:
        discovered_map = {m.lower(): m for m in discovered_rel}
        matched_rel = discovered_map.get(model_rel.lower())

        if matched_rel is None:
            requested_basename = os.path.basename(model_rel).lower()
            basename_matches = [m for m in discovered_rel if os.path.basename(m).lower() == requested_basename]
            if len(basename_matches) == 1:
                matched_rel = basename_matches[0]
            elif len(basename_matches) > 1:
                requested_parts = [p for p in model_rel.lower().split("/") if p]

                def _suffix_score(path):
                    parts = [p for p in path.lower().split("/") if p]
                    score = 0
                    while score < min(len(parts), len(requested_parts)):
                        if parts[-1 - score] != requested_parts[-1 - score]:
                            break
                        score += 1
                    return score

                basename_matches.sort(key=_suffix_score, reverse=True)
                best = basename_matches[0]
                if _suffix_score(best) > 0:
                    matched_rel = best

        if matched_rel is not None:
            matched_native = matched_rel.replace("/", os.path.sep)
            for scan_dir in scan_dirs:
                candidate = os.path.join(scan_dir, matched_native)
                attempted_paths.append(candidate)
                if os.path.exists(candidate):
                    return candidate, attempted_paths

    return None, attempted_paths


def _get_llm_scan_dirs():
    base = [config.LLM_MODEL_DIR]
    # Capture both canonical and extra-path naming variants.
    registered = _get_registered_model_dirs("LLM", "llm")
    return _dedupe_existing_dirs(base + registered)


def _get_hf_scan_dirs():
    base = list(config.HF_MODEL_DIRS)
    # HF models are commonly kept under Qwen or LLM roots in Comfy installs.
    registered = _get_registered_model_dirs("Qwen", "qwen", "LLM", "llm")
    return _dedupe_existing_dirs(base + registered)

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
        hf_device = str(kwargs.get("hf_device", "auto")).strip().lower()
        if hf_device not in {"auto", "cpu"}:
            hf_device = "auto"
        
        cache_key = (base_model_name, quantization_str, hf_device)

        try:
            with self._cache_lock:
                if cache_key not in self._model_cache:
                    self._load_model(base_model_name, quantization_str, hf_device=hf_device, **kwargs)
                
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

    def _load_model(self, base_model_name, quantization_str, hf_device="auto", **kwargs):
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
        
        hf_device = str(hf_device or "auto").strip().lower()
        # Determine quantization config
        quant_config = None
        if quantization_str in ("4bit", "fp4"):
            quant_config = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16)
        elif quantization_str == "8bit":
            quant_config = BitsAndBytesConfig(load_in_8bit=True)

        if hf_device == "cpu" and quant_config is not None:
            print("\033[93m[PromptCrafter] CPU mode selected for HF model. Ignoring 4/8-bit bitsandbytes quantization settings.\033[0m")
            quant_config = None

        if hf_device == "cpu":
            dtype = torch.float32
            device_map = "cpu"
            attn_impl = "eager"
        else:
            device = comfy.model_management.get_torch_device()
            dtype = torch.bfloat16 if comfy.model_management.supports_bf16(device) else torch.float16
            device_map = "auto"
            attn_impl = "flash_attention_2" if hasattr(torch.nn.functional, 'scaled_dot_product_attention') else "eager"

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
            device_map=device_map,
            quantization_config=quant_config,
            trust_remote_code=True,
            attn_implementation=attn_impl
        )

        cache_key = (base_model_name, quantization_str, hf_device)
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
            last_err = data_or_err

            # If chat fails and fallback is allowed, try /api/generate before failing.
            if endpoint == "chat" and allow_chat_fallback and len(endpoints_to_try) > 1:
                if status_code == 404:
                    with self._lock:
                        self._chat_api_unsupported.add(model_id)
                        print(f"\033[94m[PromptCrafter] Ollama model '{model_id}' does not support /api/chat. Switching to /api/generate.\033[0m")
                else:
                    print(f"\033[93m[PromptCrafter] Ollama /api/chat failed for '{model_id}' (status {status_code}). Retrying via /api/generate.\033[0m")
                continue

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
    runtime_overrides = _LLM_RUNTIME_OVERRIDES.get({})
    if "llm_device" not in kwargs:
        kwargs["llm_device"] = runtime_overrides.get("llm_device", getattr(config, "DEFAULT_LLM_DEVICE", "Default (GPU)"))
    if "reset_context" not in kwargs:
        kwargs["reset_context"] = runtime_overrides.get("reset_context", getattr(config, "DEFAULT_LLM_STATELESS", True))
    
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

    llm_device_choice = _normalize_llm_device_choice(kwargs.get("llm_device"))
    provider_key = provider.lower()
    if provider_key == "gguf":
        if llm_device_choice == "cpu":
            kwargs.setdefault("n_gpu_layers", 0)
            kwargs.setdefault("offload_kqv", False)
            kwargs.setdefault("vision_projector_use_gpu", False)
            kwargs.setdefault("unload_after_query", True)
    elif provider_key == "hf":
        kwargs.setdefault("hf_device", "cpu" if llm_device_choice == "cpu" else "auto")

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
EMPTY_CACHE_EXPIRATION_SECONDS = 10

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
    local_models = []
    try:
        llm_dirs = _get_llm_scan_dirs()
        for llm_dir in llm_dirs:
            for root, _, files in os.walk(llm_dir):
                for file in files:
                    if file.lower().endswith('.gguf') and "mmproj" not in file.lower():
                        local_models.append(os.path.relpath(os.path.join(root, file), llm_dir).replace('\\', '/'))
    except Exception as e:
        print(f"\033[93m[PromptCrafter] Warning: Could not scan LLM directories for GGUF files. Error: {e}\033[0m")
    return sorted(list(set(local_models)))

def get_local_hf_models():
    """Scans configured directories for local HuggingFace models."""
    local_models = set()
    for model_dir in _get_hf_scan_dirs():
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
    if not all_hf_models:
        return ["no_local_qwen_files_found"]
    
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
            cached_data, timestamp, ttl = _model_cache[cache_key]
            if now - timestamp < ttl:
                return cached_data

    all_api_models_details = _get_all_model_data()
    filtered_api_models = []

    # Get local GGUF and HF models
    local_gguf_models = get_local_llm_gguf_files()
    local_hf_models = get_local_hf_models()

    # Add local GGUF models
    for model in local_gguf_models:
        model_id = f"gguf/{model}"
        is_vision = ModelInspector.is_vision_model({"id": model_id})
        if model_type == "all" or (model_type == "vision" and is_vision) or (model_type == "text" and not is_vision):
            filtered_api_models.append(model_id)

    # Add local HuggingFace models
    for model in local_hf_models:
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
    
    ttl = EMPTY_CACHE_EXPIRATION_SECONDS if available_models == ["NO_MODELS_FOUND"] else CACHE_EXPIRATION_SECONDS
    with _cache_lock:
        _model_cache[cache_key] = (available_models, time.time(), ttl)
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
