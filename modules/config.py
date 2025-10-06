# Standard library imports
import os
from dataclasses import dataclass, field
import textwrap

# Local module imports
# Import 'cache' here to resolve the circular dependency and allow direct initialization.
from . import cache

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


# --- Path and Global State Configuration ---
# This assumes the custom_nodes folder is directly under ComfyUI
COMFYUI_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
# Initialize the disk cache directly here to prevent race conditions.
cache_dir = os.path.join(COMFYUI_ROOT_DIR, "temp", "comfyui-promptcrafter_cache")
CACHE = cache.DiskCache(cache_dir=cache_dir, max_size_gb=2.0)
SHARED_SESSION = None

# --- Dependency Flags (set at runtime in __init__.py) ---
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
        "enabled": True,
    },
    "lmstudio": {
        "base_url": os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234"),
        "enabled": False, # Users can enable this if they use LM Studio
    },
    "text-generation-webui": {
        "base_url": os.getenv("OOBABOOGA_BASE_URL", "http://127.0.0.1:5000"),
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

    # Lyrics-specific params
    interpolate_keyframes: bool = False
    interpolation_frame_interval: int = 0
    fps: float = 16.0
    song_length_seconds: float = 0.0
    use_audio_alignment: bool = True

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