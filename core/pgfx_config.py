# Standard library imports
import os
from dataclasses import dataclass, field
import textwrap

# Local module imports
# Import 'cache' here to resolve the circular dependency and allow direct initialization.
from . import pgfx_cache as cache


def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}

# --- Constants ---
DEFAULT_PROMPT_TEXT = "Describe your idea here. You can use multiple paragraphs to define scenes for a schedule."
FALLBACK_TEXT_MODEL = "llama3:latest" # A sensible default for text-only tasks
FALLBACK_VISION_MODEL = "qwen2.5vl:7b" # The recommended model for this node pack
DEFAULT_CAPTION_PROMPT = textwrap.dedent("""
    Create a concise, descriptive caption for this image, suitable for training an AI model.
    - Be factual and literal. Describe only what is visible.
    - Start with the main subject.
    - Use comma-separated phrases or tags.
    - Do not mention artist names, brand names, or copyrighted characters.
    - Example: a photo of a black cat, sitting on a red couch, in a dimly lit room, high quality.
""").strip()

MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 1.5
DEFAULT_MAX_TOKENS = 4096

# --- LLM Runtime Controls ---
LLM_DEVICE_OPTIONS = ["Default (GPU)", "CPU"]
_raw_llm_device = os.getenv("PGFX_LLM_DEVICE", "default").strip().lower()
DEFAULT_LLM_DEVICE = "CPU" if _raw_llm_device in {"cpu", "host"} else "Default (GPU)"
# Stateless by default to prevent cross-request conversational carryover.
DEFAULT_LLM_STATELESS = _env_flag("PGFX_LLM_STATELESS", "1")


# --- Path and Global State Configuration ---
# --- Path and Global State Configuration ---
try:
    import folder_paths
    COMFYUI_ROOT_DIR = folder_paths.base_path
    MODELS_DIR = folder_paths.models_dir
    TEMP_DIR = folder_paths.get_temp_directory()
except ImportError:
    # Fallback for standalone/testing usage (non-ComfyUI environment)
    COMFYUI_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    MODELS_DIR = os.path.join(COMFYUI_ROOT_DIR, "models")
    TEMP_DIR = os.path.join(COMFYUI_ROOT_DIR, "temp")

LLM_MODEL_DIR = os.path.join(MODELS_DIR, "LLM")
QWEN_MODEL_DIR = os.path.join(MODELS_DIR, "Qwen")

# List of directories to scan for HuggingFace models
HF_MODEL_DIRS = [LLM_MODEL_DIR, QWEN_MODEL_DIR]

# Initialize the disk cache directly here to prevent race conditions.
cache_dir = os.path.join(TEMP_DIR, "comfyui-promptcrafter_cache")
CACHE = cache.DiskCache(cache_dir=cache_dir, max_size_gb=2.0)
SHARED_SESSION = None

# --- Model Caching ---
PRELOAD_MODELS = [] # List of model_ids (e.g., "gguf/llama-3-8b-instruct.Q4_K_M.gguf") to load at startup
MAX_CACHED_MODELS = 2 # Maximum number of GGUF models to keep in VRAM/RAM cache

# --- GGUF Runtime Defaults ---
# Large values (e.g. 16384) can allocate multi-GB KV caches and easily OOM on consumer GPUs.
DEFAULT_GGUF_N_CTX = int(os.getenv("PGFX_GGUF_N_CTX", "4096"))
MIN_GGUF_N_CTX = int(os.getenv("PGFX_GGUF_MIN_N_CTX", "1024"))
GGUF_DEFAULT_TIMEOUT_SECONDS = int(os.getenv("PGFX_GGUF_TIMEOUT_SECONDS", "180"))
GGUF_AUTO_TUNE = _env_flag("PGFX_GGUF_AUTO_TUNE", "1")
GGUF_PROFILE = os.getenv("PGFX_GGUF_PROFILE", "balanced").strip().lower()
if GGUF_PROFILE not in {"safe", "balanced", "speed"}:
    GGUF_PROFILE = "balanced"
# GPU offload defaults: keep text models fast by default, keep vision models stable by default.
DEFAULT_GGUF_N_GPU_LAYERS_WAS_SET = os.getenv("PGFX_GGUF_N_GPU_LAYERS") is not None
VISION_GGUF_N_GPU_LAYERS_WAS_SET = os.getenv("PGFX_VISION_GGUF_N_GPU_LAYERS") is not None
DEFAULT_GGUF_N_GPU_LAYERS = int(os.getenv("PGFX_GGUF_N_GPU_LAYERS", "-1"))
VISION_GGUF_N_GPU_LAYERS = int(os.getenv("PGFX_VISION_GGUF_N_GPU_LAYERS", "0"))
# Conservative batch defaults to avoid CUDA VMM spikes during decode on 8-12GB cards.
DEFAULT_GGUF_N_BATCH_WAS_SET = os.getenv("PGFX_GGUF_N_BATCH") is not None
DEFAULT_GGUF_N_UBATCH_WAS_SET = os.getenv("PGFX_GGUF_N_UBATCH") is not None
VISION_GGUF_N_BATCH_WAS_SET = os.getenv("PGFX_VISION_GGUF_N_BATCH") is not None
VISION_GGUF_N_UBATCH_WAS_SET = os.getenv("PGFX_VISION_GGUF_N_UBATCH") is not None
DEFAULT_GGUF_N_BATCH = int(os.getenv("PGFX_GGUF_N_BATCH", "512"))
DEFAULT_GGUF_N_UBATCH = int(os.getenv("PGFX_GGUF_N_UBATCH", "256"))
VISION_GGUF_N_BATCH = int(os.getenv("PGFX_VISION_GGUF_N_BATCH", "128"))
VISION_GGUF_N_UBATCH = int(os.getenv("PGFX_VISION_GGUF_N_UBATCH", "64"))
# Retrying GPU OOM loads in CPU mode can crash some llama.cpp builds; keep off by default.
GGUF_ENABLE_CPU_RETRY = _env_flag("PGFX_GGUF_ENABLE_CPU_RETRY", "0")
# Large vision GGUFs frequently collide with downstream diffusion/ACE loads on 8-12GB GPUs.
# Unload after query by default; set PGFX_GGUF_UNLOAD_VISION_AFTER_QUERY=0 to keep cached.
GGUF_UNLOAD_VISION_AFTER_QUERY_WAS_SET = os.getenv("PGFX_GGUF_UNLOAD_VISION_AFTER_QUERY") is not None
GGUF_UNLOAD_VISION_AFTER_QUERY = _env_flag("PGFX_GGUF_UNLOAD_VISION_AFTER_QUERY", "1")
# Vision projector (mmproj/mtmd) is large and can hard-abort llama.cpp on CUDA OOM.
# Keep projector on CPU by default; enable with PGFX_GGUF_VISION_PROJECTOR_USE_GPU=1 if you have ample VRAM.
GGUF_VISION_PROJECTOR_USE_GPU_WAS_SET = os.getenv("PGFX_GGUF_VISION_PROJECTOR_USE_GPU") is not None
GGUF_VISION_PROJECTOR_USE_GPU = _env_flag("PGFX_GGUF_VISION_PROJECTOR_USE_GPU", "0")
# Qwen3-VL grounding can degrade when image tokens are too low.
# Set PGFX_QWEN_VL_IMAGE_MIN_TOKENS=1024+ for better grounding/lip-sync prompt reliability.
QWEN_VL_IMAGE_MIN_TOKENS_WAS_SET = os.getenv("PGFX_QWEN_VL_IMAGE_MIN_TOKENS") is not None
QWEN_VL_IMAGE_MIN_TOKENS = max(0, int(os.getenv("PGFX_QWEN_VL_IMAGE_MIN_TOKENS", "1024")))

# --- Dependency Flags (set at runtime in __init__.py) ---
LLAMA_CPP_AVAILABLE = False
QWEN_VL_AVAILABLE = False
LANGDETECT_AVAILABLE = False
PYPDF_AVAILABLE = False
DUCKDUCKGO_SEARCH_AVAILABLE = False
LIBROSA_AVAILABLE = False
MATPLOTLIB_AVAILABLE = False
PIEXIF_AVAILABLE = False

# --- API Configuration ---
LOCAL_SERVER_CONFIG = {
    "ollama": {
                "base_url": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        "timeout": int(os.getenv("OLLAMA_TIMEOUT", "120")),
        "enabled": True,
    },
    "lmstudio": {
                "base_url": os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234"),
        "timeout": int(os.getenv("LMSTUDIO_TIMEOUT", "120")),
        "enabled": False, # Users can enable this if they use LM Studio
    },
    "text-generation-webui": {
                "base_url": os.getenv("OOBABOOGA_BASE_URL", "http://127.0.0.1:5000"),
        "timeout": int(os.getenv("OOBABOOGA_TIMEOUT", "120")),
        "enabled": False, # Users can enable this if they use text-generation-webui
    }
}
# --- Style and Prompting Configuration ---

SAFE_MODE_RULE = "CRITICAL SAFETY RULE: Do not generate content that is NSFW, sexually explicit, violent, gory, or depicts hate speech. All output must be safe for work."
DEFAULT_CHINESE_NEGATIVE_PROMPT = "模糊，畸形，失真，低质量，丑陋，额外肢体，残缺，水印，签名，文本，错误，解剖不当"

NEGATIVE_KEYWORDS = {
    "quality": ["blurry", "distorted", "low quality", "ugly", "jpeg artifacts", "pixelated"],
    "composition": ["bad composition", "cropped", "cut off", "out of frame", "tiling"],
    "anatomy": ["deformed", "disfigured", "malformed", "mutated", "extra limbs", "missing limbs", "bad anatomy"],
    "text": ["watermark", "signature", "text", "username", "logo"],
    "contextual": {
        "person": ["cartoon", "3d", "disney", "cgi", "rendering", "anime"],
        "photograph": ["drawing", "painting", "illustration", "sketch"],
        "landscape": ["people", "animals", "vehicles"],
    }
}

@dataclass
class PromptCrafterRunConfig:
    """A dataclass to hold all runtime configuration for a node execution."""
    # Core execution params
    model: str
    language: str
    temperature: float
    seed: int
    timeout: int
    debug_mode: bool
    safe_mode: bool
    
    # Prompt generation params
    image_count: int
    max_length_words: int
    style_override: str
    critique_strength: str
    max_retries: int
    simplify_for_diffusion: bool

    # --- Fields with default values ---
    use_chat_api: bool = True
    use_deep_think: bool = True
    deep_think_confidence: float = 0.8
    negative_concepts: str = ""
    style_profile: dict = field(default_factory=dict)
    thinking_model: str = ""
    instruct_model: str = ""

    # Lyrics-specific params
    interpolate_keyframes: bool = False
    interpolation_frame_interval: int = 0
    fps: float = 16.0
    song_length_seconds: float = 0.0
    use_audio_alignment: bool = True

    # Brain/Lobe controls
    artistry: float = 0.5
    creativity: float = 0.5
    llm_device: str = "Default (GPU)"
    reset_context: bool = True

    def __post_init__(self):
        # Ensure numeric types are correct
        self.temperature = float(self.temperature)
        self.seed = int(self.seed)
        self.timeout = int(self.timeout)
        self.max_length_words = int(self.max_length_words)
        self.max_retries = int(self.max_retries)
        self.image_count = int(self.image_count)
        # Ensure lyrics-specific numeric types are correct
        self.fps = float(self.fps)
        self.song_length_seconds = float(self.song_length_seconds)
        self.artistry = float(self.artistry)
        self.creativity = float(self.creativity)
        device_choice = str(self.llm_device).strip().lower()
        self.llm_device = "CPU" if device_choice in {"cpu", "host"} else "Default (GPU)"
        self.reset_context = bool(self.reset_context)
