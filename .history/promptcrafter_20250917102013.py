# Standard library imports for file operations, time, data encoding, etc.
import time
import os
import io
import re
import json
import base64
import collections
import random
import concurrent.futures
import threading
import requests
import numpy as np
import torch
import textwrap
import inspect
import ast
from typing import Callable, Dict, Any
from PIL import Image
import hashlib
import comfy.utils

__version__ = "2.0.1"

# --- Global Session for connection pooling ---
# Using a single requests.Session object allows for connection reuse, which improves performance.
SHARED_SESSION = requests.Session()
SHARED_SESSION.headers.update({
    'User-Agent': f'ComfyUI-PromptCrafter/{__version__} (https://github.com/pythongosssss/ComfyUI-PromptCrafter)'
})

# --- Global Paths ---
# This finds the root directory of ComfyUI, which is useful for locating input/output folders.
COMFYUI_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- Dependency Check for langdetect ---
# This tries to import the 'langdetect' library. If it's not installed, it sets a flag
# and prints a warning, allowing the script to run without language detection features.
try:
    from langdetect import detect, LangDetectException
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False
    print("\033[93m[PromptCrafter] Warning: `langdetect` not found. Language detection will be disabled. Run `pip install langdetect` for automatic language support. Falling back to English.\033[0m")

# --- Dependency Check for pypdf ---
# This tries to import the 'pypdf' library. If it's not installed, it sets a flag
# and prints a warning, allowing the script to run without PDF extraction features.
try:
    from pypdf import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False
    print("\033[93m[PromptCrafter] Warning: `pypdf` not found. PDF text extraction from URLs will be disabled. Run `pip install pypdf` to enable this feature.\033[0m")

# --- Dependency Check for duckduckgo-search ---
# This tries to import the 'duckduckgo-search' library. If it's not installed, it sets a flag
# and prints a warning, allowing the script to run without web search features in QnA mode.
try:
    from duckduckgo_search import DDGS
    import itertools
    DUCKDUCKGO_SEARCH_AVAILABLE = True
except ImportError:
    DUCKDUCKGO_SEARCH_AVAILABLE = False
    print("\033[93m[PromptCrafter] Warning: `duckduckgo-search` not found. Web search in QnA mode will be disabled. Run `pip install duckduckgo-search` to enable this feature.\033[0m")

# --- Dependency Check for librosa ---
try:
    import librosa
    import librosa.display
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False
    print("\033[93m[PromptCrafter] Warning: `librosa` not found. Audio alignment features will be disabled. Run `pip install librosa` to enable this feature.\033[0m")

# --- Dependency Check for matplotlib ---
try:
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("\033[93m[PromptCrafter] Warning: `matplotlib` not found. Audio alignment features will be disabled. Run `pip install matplotlib` to enable this feature.\033[0m")

# --- API Key Loading ---
# This section handles loading API keys for services like OpenAI, Anthropic, and Google.
# The recommended way is to set them as environment variables in your ComfyUI startup script.
# As a fallback, if `python-dotenv` is installed, it will try to load them from a `.env` file in the ComfyUI root folder.
try:
    from dotenv import load_dotenv
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False
    print("\033[93m[PromptCrafter] Warning: `python-dotenv` not found. Automatic loading of API keys from a `.env` file will be disabled. Run `pip install python-dotenv` to enable this feature.\033[0m")

if DOTENV_AVAILABLE:
    if load_dotenv(dotenv_path=os.path.join(COMFYUI_ROOT_DIR, ".env")):
        print("\033[92m[PromptCrafter] Loaded API keys from .env file.\033[0m")

# ------------------------------------------------------------------------------------
# Config / Defaults
# ------------------------------------------------------------------------------------

# --- API Configuration (for external models) ---
# This dictionary holds the configuration for various external APIs.
# It automatically populates the 'api_key' fields by reading environment variables.
API_CONFIG = {
    "openai": {
        "api_key": os.getenv("OPENAI_API_KEY"),
        "base_url": os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1"),
        "vision_models": ["gpt-4o", "gpt-4-turbo"],
        "text_models": ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo"],
    },
    "anthropic": {
        "api_key": os.getenv("ANTHROPIC_API_KEY"),
        "base_url": "https://api.anthropic.com/v1",
        # Anthropic models are multimodal by default
        "vision_models": ["claude-3-5-sonnet-20240620", "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"],
        "text_models": ["claude-3-5-sonnet-20240620", "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"],
    },
    "google": {
        "api_key": os.getenv("GOOGLE_API_KEY"),
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        # Gemini models are multimodal.
        "vision_models": ["gemini-1.5-pro-latest"],
        "text_models": ["gemini-1.5-pro-latest"],
    },
}

# --- Startup Info ---
# This is now handled after the client registry is defined.

class SimpleLRUCache:
    """
    A simple Least Recently Used (LRU) cache implementation with a fixed size.
    When the cache is full, it discards the least recently used item.
    """
    def __init__(self, max_size=50):
        self.max_size = max_size
        self.cache = collections.OrderedDict()
        self.lock = threading.Lock()

    def get(self, key):
        """Retrieves an item from the cache and marks it as recently used."""
        with self.lock:
            if key not in self.cache:
                return None
            self.cache.move_to_end(key)
            return self.cache[key]

    def set(self, key, value):
        """Adds an item to the cache, evicting the oldest if necessary."""
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            if len(self.cache) > self.max_size:
                self.cache.popitem(last=False)

    def has(self, key):
        """Checks if a key exists in the cache."""
        with self.lock:
            return key in self.cache

    def size(self):
        """Returns the current number of items in the cache."""
        with self.lock:
            return len(self.cache)

    def clear(self):
        """Clears the entire cache and returns the number of items removed."""
        with self.lock:
            size = len(self.cache)
            self.cache.clear()
            return size

CACHE = SimpleLRUCache(max_size=50)

# --- Default Values and Constants ---
DEFAULT_PROMPT_TEXT = "Enter your instructions here..."
FALLBACK_VISION_MODEL = "qwen2.5vl:7b"
FALLBACK_TEXT_MODEL = "llama3:8b"  # A sensible default text model
OLLAMA_BASE = "http://localhost:11434"
SAFE_MODE_RULE = "- CRITICAL RULE: The output must be strictly safe-for-work (SFW). It must NOT contain, describe, or allude to nudity, sexual content, violence, gore, hateful content, or controversial subjects. All subjects must be fully clothed."
STYLE_KEYWORDS = {
    "None": "",
    # General Visual Styles
    "Photorealistic": "photorealistic, 8k, uhd, high quality, film grain, detailed, sharp focus, professional photography, masterpiece",
    "Fantasy Painting": "epic fantasy painting, digital art, detailed, intricate, concept art, matte painting, trending on artstation",
    "Anime / Manga": "anime style, manga art, vibrant colors, cel shading, key visual, studio trigger style, makoto shinkai style",
    "Cyberpunk": "cyberpunk, neon-drenched, futuristic city, chrome details, dystopian, blade runner aesthetic",
    "Watercolor": "watercolor painting, loose brush strokes, vibrant, wet-on-wet technique, paper texture",
    "Vintage Photo": "vintage photograph, 1970s, sepia tone, kodachrome, faded colors, old photo",
    "Minimalist": "minimalist, clean lines, simple, uncluttered, negative space, geometric shapes, flat colors",
    # Film & Music Video Styles
    "Cinematic Film": "cinematic film still, dramatic lighting, shallow depth of field, anamorphic lens flare, 35mm film grain",
    "Pop Music Video": "bright, vibrant colors, high energy, clean visuals, pop aesthetic, sunny, dance choreography",
    "Rock Music Video": "gritty, high contrast, lens flare, dynamic camera work, concert lighting, raw energy, band performance",
    "90s Hip-Hop Video": "90s hip-hop aesthetic, fisheye lens, vibrant streetwear, urban setting, film grain, Hype Williams style",
    "Synthwave / Retro Video": "synthwave aesthetic, neon grid, retro-futuristic, 80s style, VHS effect, pink and blue lighting, chrome reflections",
    "Gothic / Metal Video": "gothic aesthetic, dark, moody, high contrast, slow motion, dramatic shadows, baroque elements, atmospheric smoke",
}

STYLE_PROFILES = [] # Raw list of profiles, populated at startup
NAMED_STYLE_PROFILES = {} # Dictionary mapping profile names to profiles, for the UI

def get_style_override_options(mode="Image"):
    """Returns a combined list of style options for the UI dropdown."""
    # Start with "None" and the simple keyword styles.
    style_options = ["None"] + list(STYLE_KEYWORDS.keys())[1:]
    # Add the names of the complex profiles from the JSON file.
    if NAMED_STYLE_PROFILES:
        # Filter profiles based on the node's mode ('Image', 'Video', 'Lyrics')
        mode_lower = mode.lower()
        
        # Create a list of formatted profile names that are relevant to the current node.
        formatted_profiles = []
        for name, profile in NAMED_STYLE_PROFILES.items():
            profile_type = profile.get("type", "all")
            # Check if the profile is relevant for the current node mode.
            if profile_type == mode_lower or profile_type == "all":
                # Format the name with its type, e.g., "(Image) Fantasy Battle"
                formatted_name = f"({profile_type.capitalize()}) {name}"
                formatted_profiles.append(formatted_name)
        
        style_options += sorted(formatted_profiles)
    # Use dict.fromkeys to remove any potential duplicates while preserving order.
    return list(dict.fromkeys(style_options))

def _load_style_profiles():
    """Loads style profiles from an external JSON file or uses internal defaults."""
    global STYLE_PROFILES, NAMED_STYLE_PROFILES
    
    # Default profiles, in case the file is missing or invalid
    DEFAULT_STYLE_PROFILES = [
        {"name": "Fantasy Battle", "type": "image", "keywords": [["fantasy", "battle"], ["fantasy", "epic"]], "persona": "You are a mythologist and expert in fantasy creature and character design.", "inspiration": "Composition inspired by the masterful action of Akira Kurosawa and the raw energy of Frank Frazetta, with the dramatic lighting of Caravaggio."},
        {"name": "Mythic Fantasy", "type": "image", "keywords": [["fantasy"], ["mythology"]], "persona": "You are a mythologist and expert in fantasy creature and character design.", "inspiration": "Composition inspired by the elegant, flowing lines of Yoshitaka Amano and the romanticism of John William Waterhouse."},
        {"name": "Cyberpunk", "type": "all", "keywords": [["sci-fi"], ["cyberpunk"], ["futuristic"]], "persona": "You are a sci-fi world-builder and concept artist for futuristic films.", "inspiration": "Composition inspired by the atmospheric lighting of Roger Deakins (Blade Runner 2049) and the gritty, dense world-building of Syd Mead."},
        {"name": "Emotional Portrait", "type": "image", "keywords": [["portrait"], ["love"], ["ballad"], ["romantic"], ["introspective"]], "persona": "You are a master of emotional storytelling, skilled in interpreting expression and mood.", "inspiration": "Composition inspired by the intimate, dramatic lighting of Rembrandt and the candid, personal framing of Annie Leibovitz."},
        {"name": "Epic Landscape", "type": "image", "keywords": [["landscape"], ["nature"]], "persona": "You are a landscape art specialist with an eye for composition, atmosphere, and natural detail.", "inspiration": "Composition inspired by the epic scale of Ansel Adams and the sublime, atmospheric light of J.M.W. Turner."},
        {"name": "Anime / Manga", "type": "all", "keywords": [["anime"], ["manga"]], "persona": "You are an expert anime and manga style analyst.", "inspiration": "Composition inspired by the dynamic angles of Hiroyuki Imaishi and the detailed environmental design of Makoto Shinkai."},
        {"name": "Gritty Rock Video", "type": "video", "keywords": [["rock"], ["protest"], ["angry"]], "persona": "You are a director known for gritty, high-energy, and impactful visuals.", "inspiration": "Composition inspired by the kinetic, handheld camera work of a Paul Greengrass film and the high-contrast visuals of a music video by Hype Williams."}
    ]

    # Path to the custom JSON file
    node_dir = os.path.dirname(os.path.abspath(__file__))
    json_path = os.path.join(node_dir, "style_profiles.json")

    loaded_profiles = []
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                loaded_profiles = json.load(f)
                print(f"\033[92m[PromptCrafter] Loaded {len(loaded_profiles)} custom style profiles from style_profiles.json.\033[0m")
        except json.JSONDecodeError as e:
            print(f"\033[91m[PromptCrafter] Error: Could not parse style_profiles.json. Using default profiles. Error: {e}\033[0m")
            loaded_profiles = DEFAULT_STYLE_PROFILES
        except Exception as e:
            print(f"\033[91m[PromptCrafter] Error: Could not read style_profiles.json. Using default profiles. Error: {e}\033[0m")
            loaded_profiles = DEFAULT_STYLE_PROFILES
    else:
        # File doesn't exist, so let's create it for the user as a template.
        print("\033[94m[PromptCrafter] Info: style_profiles.json not found. Creating it with default profiles for customization.\033[0m")
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_STYLE_PROFILES, f, indent=4)
            loaded_profiles = DEFAULT_STYLE_PROFILES
        except Exception as e:
            print(f"\033[91m[PromptCrafter] Error: Could not write default style_profiles.json file. Please check permissions. Error: {e}\033[0m")
            loaded_profiles = DEFAULT_STYLE_PROFILES
    
    STYLE_PROFILES = loaded_profiles
    # Populate the named dictionary for the dropdown
    NAMED_STYLE_PROFILES.clear()
    for profile in STYLE_PROFILES:
        # Use the 'name' key, but fall back to the first keyword if 'name' is missing for backward compatibility.
        name = profile.get("name")
        if not name:
            # Generate a fallback name if one isn't provided.
            try:
                name = profile.get("keywords", [["Unnamed"]])[0][0].replace("_", " ").title()
            except (IndexError, AttributeError):
                name = "Unnamed Profile"
        NAMED_STYLE_PROFILES[name] = profile

# Call the function once at startup
_load_style_profiles()

# --- Negative Prompt Keyword Sets ---
# These keyword sets are used by the local negative prompt generator to anticipate
# common AI image generation failures without needing an extra API call.
DEFAULT_CHINESE_NEGATIVE_PROMPT = "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走，裸露，NSFW"

# This dictionary is now structured for more granular, context-aware negative keyword generation.
# Instead of broad categories, it maps specific trigger words found in a positive prompt
# to a list of relevant negative keywords.
NEGATIVE_KEYWORDS = {
    # General quality and composition keywords are almost always useful.
    "quality": [
        "ugly", "blurry", "worst quality", "low quality", "jpeg artifacts", "noisy", "grainy",
        "pixelated", "out of focus", "oversaturated", "undersaturated", "low-resolution", "text",
        "watermark", "signature", "logo", "bad art", "tiling", "morbid", "error", "username",
        "artist name", "cropped", "cut off", "draft"
    ],
    "composition": [
        "poorly drawn", "poorly framed", "out of frame", "cluttered", "messy",
        "poor composition"
    ],
    # Contextual triggers: if a key is in the prompt, add the corresponding values.
    "contextual": {
        # General anatomy for humanoids
        "person": ["bad anatomy", "deformed", "disfigured", "malformed", "mutated", "long neck", "uncanny valley", "body horror", "gross proportions", "missing arms", "missing legs", "extra arms", "extra legs", "malformed limbs"],
        # Specific anatomy parts
        "hands": ["bad hands", "extra fingers", "mutated hands", "fused fingers", "too many fingers"],
        "face": ["asymmetrical eyes", "poorly drawn face", "cloned face"],
        "portrait": ["asymmetrical eyes", "poorly drawn face", "cloned face"],
        # Style triggers for photorealism
        "photo": ["drawing", "painting", "illustration", "sketch", "3d", "render", "cartoon", "anime"],
        "photograph": ["drawing", "painting", "illustration", "sketch", "3d", "render", "cartoon", "anime"],
        "photorealistic": ["drawing", "painting", "illustration", "sketch", "3d", "render", "cartoon", "anime"],
        "realistic": ["drawing", "painting", "illustration", "sketch", "3d", "render", "cartoon", "anime"],
    }
}

# ------------------------------------------------------------------------------------
# Utils
# ------------------------------------------------------------------------------------

def _debug_print(debug_mode, title, content):
    """Prints debug information to the console if debug_mode is True."""
    if debug_mode:
        print("\n\033[95m{eq} DEBUG: {title} {eq}\033[0m".format(eq='='*20, title=title))
        print(content)
        print("\033[95m{eq}\033[0m\n".format(eq='='* (42 + len(title))))

def _get_cache_key(*args):
    """Creates a unique and deterministic key for caching based on the node's inputs."""
    hasher = hashlib.sha256() # Use a fast and reliable hashing algorithm.
    for arg in args:
        if isinstance(arg, list) and arg and isinstance(arg[0], torch.Tensor):
            # Handle a list of image tensors
            for tensor in arg:
                hasher.update(tensor.cpu().numpy().tobytes())
        elif isinstance(arg, torch.Tensor):
            # Handle a single image tensor
            hasher.update(arg.cpu().numpy().tobytes())
        elif isinstance(arg, Image.Image):
            # Handle a PIL image
            hasher.update(arg.tobytes())
        else:
            # For strings, numbers, bools, etc.
            hasher.update(str(arg).encode('utf-8'))
    return hasher.hexdigest()

def _filter_kwargs(func: Callable, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Filters a dictionary of keyword arguments to only include those accepted by a function.
    This makes the dispatchers more robust, as they can safely pass a wide range of
    arguments without causing a TypeError on a client that doesn't accept them.
    """
    sig = inspect.signature(func)
    # If the function accepts arbitrary keyword arguments (e.g., **kwargs), we can pass everything.
    if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
        return kwargs
    
    # Otherwise, filter to only include named parameters that the function explicitly accepts.
    allowed_keys = {p.name for p in sig.parameters.values() if p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)}
    return {k: v for k, v in kwargs.items() if k in allowed_keys}

def _handle_creative_intent(self, user_text, images_with_weights, config):
    """
    A smart function to handle user intent. It returns a tuple: (error_message, new_user_text).
    - If text implies images but none are provided, returns an error.
    - If images are provided but no text, it generates a creative instruction.
    """
    has_text = user_text and user_text.strip() and user_text.strip() != DEFAULT_PROMPT_TEXT
    has_images = bool(images_with_weights)

    # --- Scenario 1: Missing Image Intent ---
    if has_text and not has_images:
        image_keywords = ["image", "images", "picture", "pictures", "photo", "reference", "input"]
        if any(kw in user_text.lower() for kw in image_keywords):
            print("\033[94m[PromptCrafter] User text mentions images, but none are connected. Using AI to confirm intent...\033[0m")
            prompt = textwrap.dedent(f"""
                Analyze the user's request. Does it explicitly mention using input images, reference images, or the provided images?
                - If it says "using the images", "based on the pictures", etc., answer YES.
                - If it just describes a scene (e.g., "create an image of a woman"), answer NO.
                --- USER REQUEST ---\n{user_text}\n---
                Respond with ONLY a JSON object: {{"requires_images": true/false}}
            """).strip()
            ok, result = _reason_with_model(config.model, prompt, config.use_chat_api, 0.0, config.seed, debug_mode=config.debug_mode, debug_title="Image Intent Check")
            if ok and isinstance(result, dict) and result.get("requires_images"):
                return "Your instructions appear to refer to input images, but none were connected. Please connect reference images or rephrase your instructions.", None

    # --- Scenario 2: Missing Text Intent (Creative Autopilot) ---
    elif has_images and not has_text:
        print("\033[94m[PromptCrafter] Images provided but no text. Engaging creative autopilot to generate instructions...\033[0m")
        image_context, _ = self._describe_images(images_with_weights, config)
        
        prompt = textwrap.dedent(f"""
            You are a creative director. Analyze the following image descriptions and invent a high-level, single-paragraph instruction for a new, creative scene that uses the subjects from the images.
            - Be imaginative. Suggest a new scenario, interaction, or story.
            - Do NOT just describe the images. Create a new concept.
            - Example: If given images of a knight and a dragon, you might suggest: "A cinematic scene where the knight and the dragon are not fighting, but instead stand together on a clifftop, looking out over a vast, misty valley as allies."

            --- IMAGE DESCRIPTIONS ---\n{image_context}\n---
            Return ONLY the single-paragraph creative instruction. No commentary.
        """).strip()

        ok, new_instruction = query_model_auto(config.model, prompt, prefer_chat=True, temperature=0.7, seed=config.seed, debug_mode=config.debug_mode, debug_title="Creative Autopilot")
        
        if ok and new_instruction:
            print(f"\033[92m[PromptCrafter] Creative Autopilot generated instruction: {new_instruction}\033[0m")
            return None, new_instruction
        else:
            return "Creative Autopilot failed to generate instructions from the images. Please provide text instructions or check your model.", None

    # --- Default Case: No action needed ---
    return None, None

# A mapping of language codes from 'langdetect' to human-readable names.
LANG_MAP = {
    'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German',
    'it': 'Italian', 'pt': 'Portuguese', 'nl': 'Dutch', 'ru': 'Russian',
    'ja': 'Japanese', 'ko': 'Korean', 'zh-cn': 'Chinese (Simplified)',
    'zh-tw': 'Chinese (Traditional)', 'ar': 'Arabic', 'hi': 'Hindi'
}

def _detect_language(text: str, fallback='English'):
    """
    Detects the language of the input text using the langdetect library.
    Falls back to a default language if the library isn't available or detection fails.
    """
    if not LANGDETECT_AVAILABLE or not text or not text.strip():
        return fallback
    try:
        lang_code = detect(text[:500])
        return LANG_MAP.get(lang_code, fallback)
    except LangDetectException:
        return fallback

def safe_read(path):
    """A helper function to read a text file safely, returning an error message on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"[Error reading {os.path.basename(path)}: {e}]"

def convert_to_pil(img_in):
    """
    Converts an input image, which could be a PyTorch tensor or already a PIL Image,
    into a standard PIL Image object. This is necessary for many image processing tasks.
    """
    if img_in is None:
        return None
    if isinstance(img_in, Image.Image):
        return img_in
    if torch.is_tensor(img_in):
        arr = img_in
        if arr.ndim == 4:
            arr = arr[0]
        arr = arr.detach().cpu().numpy()
        if arr.dtype != np.uint8:
            arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
        return Image.fromarray(arr)
    return None

def encode_image(img):
    """
    Converts a PIL Image or tensor into a base64 encoded string.
    This is the format required for sending images to most modern web APIs.
    """
    pil = convert_to_pil(img)
    if pil is None:
        return None
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

class TextCleaner:
    """A utility class for various text cleaning and formatting operations."""

    @staticmethod
    def single_paragraph(text: str) -> str:
        """
        A text cleaning utility to collapse a string into a single, clean paragraph.
        It removes extra line breaks, spaces, and surrounding quotes.
        """
        text = (text or "").strip().replace("\r", " ")
        text = re.sub(r"\s+\n", " ", text)
        text = re.sub(r"\n+", " ", text)
        text = re.sub(r"\s{2,}", " ", text).strip()
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("“") and text.endswith("”")):
            text = text[1:-1].strip()
        return text

    @staticmethod
    def dedupe_sentences(text: str) -> str:
        """
        Removes duplicate sentences from a block of text while preserving the order.
        Useful for cleaning up AI-generated text that can sometimes be repetitive.
        """
        parts = re.split(r'(?<=[.!?])\s+', text.strip())
        seen = set()
        keep = []
        for s in parts:
            ss = s.strip()
            key = ss.lower()
            if ss and key not in seen:
                seen.add(key)
                keep.append(ss)
        return " ".join(keep)

    @staticmethod
    def slim_prompt_text(text: str) -> str:
        """
        A text cleaning utility that removes redundant "filler" words and phrases
        to make the final prompt more concise and efficient.
        """
        if not text:
            return text
        t = text
        t = re.sub(r"\b(and also|additionally|moreover)\b", "and", t, flags=re.IGNORECASE)
        t = re.sub(r"\bwith\b([^,]+?), and\b", r"with\1,", t, flags=re.IGNORECASE)
        t = re.sub(r"\b(and\s+){2,}", "and ", t, flags=re.IGNORECASE)
        t = re.sub(r",\s*,+", ",", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

def _parse_srt_time(time_str: str) -> float:
    """Converts SRT time format 'HH:MM:SS,ms' to seconds."""
    try:
        parts = time_str.replace(',', '.').split(':')
        if len(parts) == 3:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        pass
    return 0.0

def _srt_to_timed_segments(srt_text: str):
    """
    Parses an SRT file into a list of timed segments and a combined text string.
    Returns a tuple: (list_of_timed_segments, full_text_string).
    Each segment in the list is a tuple: (start_seconds, end_seconds, text).
    """
    segments = []
    # A robust regex to parse SRT blocks, handling various line endings.
    pattern = re.compile(
        r'(\d+)\s*[\r\n]+'
        r'(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*[\r\n]+'
        r'([\s\S]*?)(?=\n\n|\Z)',
        re.MULTILINE
    )
    matches = pattern.finditer(srt_text)
    
    for match in matches:
        start_time_str = match.group(2)
        end_time_str = match.group(3)
        text = re.sub(r'<[^>]+>', '', match.group(4)).strip().replace('\n', ' ') # Strip HTML tags and newlines
        
        if text:
            segments.append((_parse_srt_time(start_time_str), _parse_srt_time(end_time_str), text))
            
    full_text = "\n".join([seg[2] for seg in segments])
    return segments, full_text

def _lrc_to_timed_segments(lrc_text: str):
    """
    Parses LRC file content into a list of timed segments and a combined text string.
    Handles the common [mm:ss.xx]lyric format.
    """
    segments = []
    # Regex to capture time [mm:ss.xx] and the following text.
    # It ignores metadata tags like [ar:...] which don't have a time format.
    pattern = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)')
    
    lines = lrc_text.splitlines()
    raw_lyrics = []

    for line in lines:
        match = pattern.match(line.strip())
        if match:
            minutes, seconds, centiseconds, text = match.groups()
            start_time = int(minutes) * 60 + int(seconds) + float(centiseconds) / 100
            text = text.strip()
            if text:
                segments.append({'start': start_time, 'text': text})
                raw_lyrics.append(text)

    if not segments:
        return None, lrc_text # Not a valid LRC format or no timed lines found

    # Sort segments by start time, as LRC files can be unordered.
    segments.sort(key=lambda x: x['start'])

    # Create the final (start, end, text) tuples. End time is the start of the next line.
    timed_tuples = []
    for i in range(len(segments)):
        start, text = segments[i]['start'], segments[i]['text']
        end = segments[i+1]['start'] if i + 1 < len(segments) else start + 5 # Add 5s for the last line
        timed_tuples.append((start, end, text))

    return timed_tuples, "\n".join(raw_lyrics)

# --- Prompt Scheduling Utils (inspired by ComfyUI-Schedulizer by Doctor-Diffusion) ---

def _parse_schedule_prompt(prompt):
    """Parses a prompt string to separate the text from a weight if present."""
    weight = 1.0
    if ":" in prompt:
        parts = prompt.split(":")
        # This check handles prompts with colons that are not for weighting, e.g., "a woman: a warrior"
        if len(parts) > 2 or (len(parts) == 2 and not parts[1].strip().replace('.', '', 1).isdigit()):
            pass
        else:
            try:
                prompt, weight_str = ":".join(parts[:-1]), parts[-1]
                weight = float(weight_str)
                prompt = prompt.strip()
            except (ValueError, IndexError):
                # If conversion fails or parts are not as expected, it's not a weight.
                pass
    return prompt.strip(), weight

def _interpolate_schedule_prompts(schedule, frame_interval):
    """
    Inserts interpolated keyframes into a schedule to create smooth transitions.

    This function iterates through the keyframes in a schedule. For each segment
    between two keyframes, it inserts new, interpolated keyframes at a specified
    frame interval. The prompt text and weight are linearly interpolated over the
    duration of the segment.

    Args:
        schedule (OrderedDict): A dictionary mapping frame numbers to prompt strings.
        frame_interval (int): The number of frames between each new interpolated
                              keyframe. If 0 or less, no interpolation is performed.

    Returns:
        OrderedDict: The schedule with new interpolated keyframes.
    """
    if frame_interval <= 0:
        return schedule

    sorted_frames = sorted(schedule.keys())
    new_schedule = schedule.copy()

    for i in range(len(sorted_frames) - 1):
        start_frame = sorted_frames[i]
        end_frame = sorted_frames[i+1]
        start_prompt_text, start_weight = _parse_schedule_prompt(schedule[start_frame])
        end_prompt_text, end_weight = _parse_schedule_prompt(schedule[end_frame])
        num_frames_in_segment = end_frame - start_frame
        if num_frames_in_segment <= frame_interval:
            continue
        for interp_frame in range(start_frame + frame_interval, end_frame, frame_interval):
            t = (interp_frame - start_frame) / num_frames_in_segment
            interp_weight = start_weight + (end_weight - start_weight) * t
            
            # If the start and end prompts are the same, don't use interpolation syntax.
            # Just use the prompt text and interpolate the weight.
            if start_prompt_text == end_prompt_text:
                # If the prompt text is the same, we only need to interpolate the weight.
                # The prompt text must be JSON-encoded to handle special characters like quotes and colons,
                # then combined with the weight. This format is expected by downstream scheduling nodes.
                new_schedule[interp_frame] = f"{json.dumps(start_prompt_text)}:{interp_weight:.4f}"
            else:
                # Use standard interpolation syntax. The prompt text is embedded directly.
                # The final, outer json.dumps call will handle any necessary escaping for the entire string.
                new_schedule[interp_frame] = f"[{start_prompt_text}:{1 - t:.4f}][{end_prompt_text}:{t:.4f}]"

    return collections.OrderedDict(sorted(new_schedule.items()))

def _create_schedule_from_items(items, max_frames, start_frame=0, interpolate=True, interpolation_frame_interval=10):
    """
    A generic helper to create a keyframe schedule from a list of items (prompts).
    It distributes the items evenly across the specified frame range using a more
    accurate distribution method.
    """

    num_items = len(items)
    schedule = collections.OrderedDict()

    if num_items == 1:
        # If there's only one prompt, it applies for the entire duration.
        schedule[start_frame] = items[0]
    else:
        # Use linspace with endpoint=True to ensure the schedule covers the full duration.
        # We ask for num_items points, and we'll use the first num_items of them.
        keyframe_indices = np.linspace(start_frame, max_frames, num=num_items, endpoint=False, dtype=int)
        for i, item in enumerate(items):
            schedule[int(keyframe_indices[i])] = item

    if interpolate:
        schedule = _interpolate_schedule_prompts(schedule, interpolation_frame_interval)

    # Manually build the schedule string without the surrounding braces, as expected by downstream nodes.
    # Each value is individually JSON-encoded to handle special characters correctly.
    schedule_items = [f'"{str(key)}": {json.dumps(str(value))}' for key, value in schedule.items()]

    return ",\n".join(schedule_items)

    def _setup_config(self, mode, user_text, vision_model, **kwargs):
        """A shared setup pipeline for all creator nodes."""
        # --- 0. Pre-flight & Model Validation ---
        if not vision_model or "NO_MODELS_FOUND" in vision_model or "OLLAMA_UNREACHABLE" in vision_model:
            raise ValueError("No vision models found or Ollama is unreachable. Please install a vision model (e.g., 'ollama run llava') or configure a remote API key.")

        # Validate that the selected model is actually a vision model.
        available_vision_models = _get_models_by_type("vision")
        if vision_model not in available_vision_models:
            # Find a suitable vision model to suggest as a fallback.
            fallback = next((m for m in available_vision_models if "llava" in m), available_vision_models[0] if available_vision_models else FALLBACK_VISION_MODEL)
            raise ValueError(f"Model '{vision_model}' is not a vision model. Please select a vision-capable model (e.g., '{fallback}').")

        # --- 1. Prepare Config Parameters ---
        original_temp = self.INPUT_TYPES()["required"]["temperature"][1]["default"]
        original_max_len = self.INPUT_TYPES()["required"]["max_length_words"][1]["default"]
        temperature, use_chat_api, max_length_words = self._prepare_run_parameters(
            mode, kwargs.get('temperature'), kwargs.get('use_chat_api'), kwargs.get('max_length_words'), original_temp, original_max_len
        )
        language = _detect_language(user_text)
        
        config_params = kwargs.copy()
        config_params.update({
            'model': vision_model, 'language': language, 'temperature': temperature, 
            'use_chat_api': use_chat_api, 'max_length_words': max_length_words
        })
        config = PromptCrafterRunConfig(**config_params)

        # --- 2. Determine Style Profile ---
        if config.style_override and config.style_override != "None":
            original_name = re.sub(r'^\(.*\)\s', '', config.style_override)
            if original_name in NAMED_STYLE_PROFILES:
                config.style_profile = NAMED_STYLE_PROFILES[original_name]
        
        return config

def _create_lyrics_schedule(lyrics_text, max_frames, start_frame=0, interpolate=True, interpolation_frame_interval=0):
    """
    Converts song lyrics into a frame-based prompt schedule.

    - Each non-empty lyric line becomes a keyframe, distributed evenly across the timeline.
    - Interpolation is optional and off by default (via interpolation_frame_interval=0).
      When enabled, it creates smooth transitions between the main lyric lines.
    """
    lines = [line.strip() for line in lyrics_text.splitlines() if line.strip()]
    # Interpolation is rarely useful for lyrics, but keep option for flexibility
    return _create_schedule_from_items(lines, max_frames, start_frame, interpolate, interpolation_frame_interval)

def _fetch_url_content(url, debug_mode=False):
    """Fetches and cleans text content from a URL, with support for PDF text extraction."""
    try:
        print(f"\033[94m[PromptCrafter] URL detected. Fetching content from: {url}\033[0m")
        # Use the shared session for connection pooling. The User-Agent is set globally.
        response = SHARED_SESSION.get(url, timeout=20)
        response.raise_for_status()
        
        content_type = response.headers.get('content-type', '').lower()

        # Handle PDF content
        if 'application/pdf' in content_type:
            if not PYPDF_AVAILABLE:
                return False, "[Error: URL points to a PDF, but the `pypdf` library is not installed. Please run `pip install pypdf`.]"
            
            try:
                pdf_file = io.BytesIO(response.content)
                reader = PdfReader(pdf_file)
                text = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
                text = re.sub(r'\s+', ' ', text).strip()
                _debug_print(debug_mode, "Fetched PDF Content (Extracted)", (text[:1000] + "...") if len(text) > 1000 else text)
                return True, text
            except Exception as e:
                return False, f"[Error extracting text from PDF: {e}]"

        # Handle HTML/Text content (existing logic)
        elif 'text' in content_type:
            text = response.text
            text = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)
            body_match = re.search(r'<body\b[^>]*>(.*?)</body>', text, flags=re.DOTALL | re.IGNORECASE)
            if body_match:
                text = body_match.group(1)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            
            _debug_print(debug_mode, "Fetched URL Content (Cleaned)", (text[:1000] + "...") if len(text) > 1000 else text)
            return True, text
        
        # Handle unsupported content types
        else:
            return False, f"[Error: URL content type is not supported ({content_type})]"

    except requests.exceptions.RequestException as e:
        return False, f"[Error fetching URL: {e}]"

def _should_perform_web_search(user_query, model, seed, debug_mode, timeout=40):
    """
    Uses an LLM to determine if a user's query requires a web search and to
    generate an optimized search query.
    """
    if not DUCKDUCKGO_SEARCH_AVAILABLE or not user_query or user_query.strip() == DEFAULT_PROMPT_TEXT:
        return False, None

    prompt_template = textwrap.dedent("""
        Analyze the user's query. Does it ask about a recent event (in the last year), a topic where information changes rapidly (like stock prices or product releases), or a person/topic that is not a matter of common, stable knowledge?

        - If it's a general knowledge question (e.g., "What is the capital of France?", "Summarize the plot of Hamlet"), a web search is NOT needed.
        - If it asks for a creative response (e.g., "Write a poem about a cat"), a web search is NOT needed.
        - If it asks about a very recent event or a rapidly changing topic (e.g., "What were the key announcements from Apple's last event?", "Who won the F1 race last weekend?"), a web search IS needed.

        --- USER QUERY ---
        {query}
        --- END USER QUERY ---

        Based on this analysis, respond with ONLY a JSON object.
        - If a search is needed, use this format: {{"search_needed": true, "search_query": "optimized search keywords"}}
        - If no search is needed, use this format: {{"search_needed": false, "search_query": null}}
    """)
    
    check_prompt = prompt_template.format(query=user_query)
    
    ok, result_json = _reason_with_model(
        model, check_prompt, use_chat_api=True, temperature=0.0, seed=seed, 
        timeout=timeout, debug_mode=debug_mode, debug_title="Web Search Check"
    )

    if ok and isinstance(result_json, dict):
        if result_json.get("search_needed") is True and result_json.get("search_query"):
            return True, result_json.get("search_query")
    
    return False, None

def _perform_web_search(query: str, num_results=3, debug_mode=False, fast_search=False):
    """
    Performs a web search using DuckDuckGo, fetches content from the top results,
    and returns a combined context string.
    """
    if not DUCKDUCKGO_SEARCH_AVAILABLE:
        return "[Web search is disabled because `duckduckgo-search` is not installed.]"

    print(f"\033[94m[PromptCrafter] Performing web search for: '{query}'\033[0m")
    if fast_search:
        print("\033[94m[PromptCrafter] Fast search enabled. Using snippets only.\033[0m")
    search_context = ""
    try:
        with DDGS(timeout=20) as ddgs:
            # Use islice to prevent fetching too many results if the generator is slow to stop
            results = list(itertools.islice(ddgs.text(query, region='wt-wt', safesearch='moderate', timelimit='y'), num_results))
            
            if not results:
                return "[No web search results found.]"

            if fast_search:
                # Fast mode: just use snippets, don't fetch URLs.
                for result in results:
                    search_context += f"--- Web Result from {result.get('href')} ---\n"
                    search_context += f"Title: {result.get('title', 'N/A')}\n"
                    search_context += f"Snippet: {result.get('body', 'N/A')}\n\n"
            else:
                # Full mode: fetch URLs concurrently (existing logic).
                with concurrent.futures.ThreadPoolExecutor(max_workers=num_results) as executor:
                    future_to_url = {executor.submit(_fetch_url_content, result.get('href'), debug_mode): result for result in results if result.get('href')}
                    
                    fetched_contents = {}
                    for future in concurrent.futures.as_completed(future_to_url):
                        result_meta = future_to_url[future]
                        url = result_meta.get('href')
                        try:
                            ok, content = future.result()
                            fetched_contents[url] = (ok, content, result_meta)
                        except Exception as exc:
                            fetched_contents[url] = (False, f"[Error fetching URL content: {exc}]", result_meta)

                # Process results in original order
                for result in results:
                    url = result.get('href')
                    if url in fetched_contents:
                        ok, content, result_meta = fetched_contents[url]
                        search_context += f"--- Web Result from {url} ---\n"
                        search_context += f"Title: {result_meta.get('title', 'N/A')}\n"
                        search_context += f"Snippet: {result_meta.get('body', 'N/A')}\n"
                        if ok and content:
                            clean_content = TextCleaner.single_paragraph(content)
                            search_context += f"Content Summary: {clean_content[:1500]}...\n\n"
                        else:
                            search_context += f"Content: [Could not fetch or process content: {content}]\n\n"
        
        _debug_print(debug_mode, "Web Search Context", search_context)
        return search_context.strip()

    except Exception as e:
        print(f"\033[93m[PromptCrafter] Warning: An error occurred during web search: {e}\033[0m")
        return f"[An error occurred during web search: {e}]"

def _split_text_into_chunks(text, chunk_size_words):
    """
    Splits a large text into chunks of a target word size, but avoids splitting
    in the middle of sentences.
    """
    if not text:
        return []
    
    # Split the text into sentences. A simple regex is used for broad compatibility.
    sentences = re.split(r'(?<=[.?!])\s+', text.strip())
    
    chunks = []
    current_chunk_sentences = []
    current_word_count = 0
    
    for sentence in sentences:
        sentence_word_count = len(sentence.split())
        
        # If adding the next sentence would exceed the chunk size, finalize the current chunk.
        if current_chunk_sentences and (current_word_count + sentence_word_count > chunk_size_words):
            chunks.append(" ".join(current_chunk_sentences))
            current_chunk_sentences = []
            current_word_count = 0
            
        current_chunk_sentences.append(sentence)
        current_word_count += sentence_word_count

    # Add the last remaining chunk.
    if current_chunk_sentences:
        chunks.append(" ".join(current_chunk_sentences))
        
    return chunks

def _summarize_large_text(text, chunk_size_words, model, temperature, seed, debug_mode, timeout, strategy="default", user_query=None):
    """
    Performs a robust, hierarchical map-reduce summarization on large text.
    This process is designed to handle very large documents efficiently and without
    exceeding model context windows.

    1.  **Split**: The text is split into sentence-aware chunks of a target size.
    2.  **Map (Parallel)**: Each chunk is summarized concurrently using a thread pool.
    3.  **Reduce (Hierarchical)**: The summaries are then recursively combined and
        summarized in groups until a single, final summary is produced.
    """
    # --- Smart Strategy Selection ---
    # If the user provides a very simple "summarize" query, it's often better to use
    # an extractive summary which just pulls key sentences. This is faster and often
    # more what the user is looking for in this simple case.
    final_strategy = strategy
    if user_query:
        simple_summarize_queries = [
            "summarize", "summarize this", "give me a summary", "can you summarize this",
            "tldr", "tl;dr", "summary"
        ]
        if user_query.lower().strip(" .?!") in simple_summarize_queries:
            print("\033[94m[PromptCrafter] Simple summarize query detected. Switching to faster 'Extractive' strategy.\033[0m")
            final_strategy = "extractive"

    # --- 1. Split Phase ---
    chunks = _split_text_into_chunks(text, chunk_size_words)
    if not chunks:
        return "[Error: Could not split text into chunks.]"

    # --- 2. Map Phase (Summarize each chunk in parallel) ---
    summaries = [None] * len(chunks)
    print(f"\033[94m[PromptCrafter] Summarizing {len(chunks)} chunks in parallel (Map phase)...\033[0m")

    if final_strategy == "extractive":
        map_prompt_template = "Extract the most important sentences from the following text chunk. Return ONLY the extracted sentences.\n\nTEXT CHUNK:\n{chunk}"
    else: # default abstractive strategy
        map_prompt_template = "Concisely summarize the key points of the following text chunk. Focus on factual information, names, and key events. Return ONLY the summary.\n\nTEXT CHUNK:\n{chunk}"

    max_workers = min(8, len(chunks))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(
                query_model_auto, model, map_prompt_template.format(chunk=chunk),
                prefer_chat=True, temperature=temperature, seed=seed, debug_mode=debug_mode,
                timeout=timeout, 
                debug_title=f"Summarize Chunk {i+1}/{len(chunks)}"
            ): i for i, chunk in enumerate(chunks)
        }
        for future in concurrent.futures.as_completed(future_to_index):
            index = future_to_index[future]
            try:
                ok, summary_or_err = future.result()
                if ok:
                    summaries[index] = TextCleaner.single_paragraph(summary_or_err)
                else:
                    print(f"\033[93m[PromptCrafter] Warning: Could not summarize chunk {index+1}. Error: {summary_or_err}\033[0m")
            except Exception as exc:
                print(f"\033[91m[PromptCrafter] An unexpected error occurred while summarizing chunk {index+1}: {exc}\033[0m")

    successful_summaries = [s for s in summaries if s]
    if not successful_summaries:
        return "[Error: All text chunks failed to summarize. Please check the model and connection.]"

    # --- 3. Reduce Phase (Hierarchical Summarization) ---
    current_summaries = successful_summaries
    reduce_level = 1
    reduce_group_size = 5 

    while len(current_summaries) > 1:
        print(f"\033[94m[PromptCrafter] Combining {len(current_summaries)} summaries in parallel (Reduce level {reduce_level})...\033[0m")
        
        groups_to_process = ["\n\n---\n\n".join(current_summaries[i:i + reduce_group_size]) for i in range(0, len(current_summaries), reduce_group_size)]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(groups_to_process))) as executor:
            future_to_index = {
                executor.submit(
                    query_model_auto, model,
                    f"The following text consists of several summaries of a larger document. Synthesize these summaries into one final, coherent summary of the entire document.\n\nSUMMARIES:\n{group}",
                    prefer_chat=True, temperature=temperature, seed=seed, timeout=timeout,
                    debug_mode=debug_mode, debug_title=f"Reduce Level {reduce_level} - Group {i+1}/{len(groups_to_process)}"
                ): i for i, group in enumerate(groups_to_process)
            }
            
            results = [None] * len(groups_to_process)
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    ok, summary_or_err = future.result()
                    if ok: results[index] = TextCleaner.single_paragraph(summary_or_err)
                    else: print(f"\033[93m[PromptCrafter] Warning: Reduce step failed for group {index+1} at level {reduce_level}. Error: {summary_or_err}\033[0m")
                except Exception as exc:
                    print(f"\033[91m[PromptCrafter] An unexpected error occurred during reduce step for group {index+1}: {exc}\033[0m")

        current_summaries = [s for s in results if s]
        if not current_summaries:
            print(f"\033[91m[PromptCrafter] Error: All groups failed at reduce level {reduce_level}. Returning previous level's summaries.\033[0m")
            return "\n\n".join(groups_to_process)
        
        reduce_level += 1

    final_summary = current_summaries[0] if current_summaries else "[Error: Summarization resulted in an empty string.]"

    # --- 4. Final Pass (Refine summary based on original query) ---
    # This step re-introduces the user's original intent to ensure the final
    # summary is a relevant answer, not just a generic overview.
    if user_query and user_query.strip() and user_query.strip() != DEFAULT_PROMPT_TEXT:
        print("\033[94m[PromptCrafter] Performing final pass to tailor summary to user query...\033[0m")
        final_pass_prompt = textwrap.dedent("""
            You are a synthesis expert. Based on the following comprehensive summary, provide a concise and direct answer to the user's original query.
            Focus only on the information relevant to the query.

            --- COMPREHENSIVE SUMMARY ---
            {summary}
            --- END SUMMARY ---

            --- USER's ORIGINAL QUERY ---
            {query}
            --- END QUERY ---

            Return ONLY the final, targeted answer.
        """).format(summary=final_summary, query=user_query)

        ok, final_answer = query_model_auto(model, final_pass_prompt, prefer_chat=True, temperature=temperature, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title="Final Summary Pass")
        if ok:
            return TextCleaner.single_paragraph(final_answer)
        else:
            print(f"\033[93m[PromptCrafter] Warning: Final summary pass failed. Returning the general summary. Error: {final_answer}\033[0m")

    return final_summary

def audio_to_spectrogram(audio_path):
    """
    Converts an audio file into a Mel spectrogram image, which can be analyzed by a vision model.
    This function uses librosa for audio processing and matplotlib for plotting. The result is
    cached to avoid regenerating the spectrogram for the same file.
    """
    if not LIBROSA_AVAILABLE or not MATPLOTLIB_AVAILABLE:
        return "[Error: librosa or matplotlib not installed]"
    
    cache_key = _get_cache_key(audio_path, "spectrogram_v1")
    if CACHE.has(cache_key):
        print(f"\033[94m[PromptCrafter] Using cached spectrogram for {os.path.basename(audio_path)}.\033[0m")
        return CACHE.get(cache_key)

    try:
        y, sr = librosa.load(audio_path, sr=None)
        S = librosa.feature.melspectrogram(y=y, sr=sr)
        S_dB = librosa.power_to_db(S, ref=np.max)

        fig, ax = plt.subplots(figsize=(10, 4))
        librosa.display.specshow(S_dB, sr=sr, x_axis='time', y_axis='mel', ax=ax)
        ax.set(title=f'Mel spectrogram: {os.path.basename(audio_path)}')
        plt.tight_layout()
        
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        image = Image.open(buf)
        CACHE.set(cache_key, image)
        return image
    except Exception as e:
        return f"[Error generating spectrogram: {e}]"

def _validate_lyrics_against_audio(lyrics_text, audio_img, config):
    """Uses a vision model to compare lyrics against a spectrogram and correct them."""
    prompt = textwrap.dedent(f"""
        You are a lyrics alignment assistant.
        Compare the provided text (lyrics) with the singing audio represented by this spectrogram.
        Correct any misheard or missing words. Maintain line breaks and rhythm.
        
        RAW LYRICS:
        {lyrics_text}

        Return ONLY the corrected lyrics.
    """).strip()
    ok, corrected = query_model_auto(config.model, prompt, images=[audio_img], prefer_chat=True,
                                     temperature=config.temperature, seed=config.seed,
                                     debug_mode=config.debug_mode, timeout=config.timeout,
                                     debug_title="Audio-Lyric Cross-Check")
    return corrected if ok else lyrics_text

# ------------------------------------------------------------------------------------
# Style Engine
# ------------------------------------------------------------------------------------

class StyleEngine:
    """
    A cohesive class to analyze content and generate stylistic guidance.
    It determines a persona for description and a set of composition rules for generation
    based on a data-driven configuration.
    """
    def __init__(self, model, use_chat_api, temperature, seed, image=None, text=None, debug_mode=False, timeout=60):
        self.model = model
        self.use_chat_api = use_chat_api
        self.temperature = temperature
        self.seed = seed
        self.image = image
        self.text = text
        self.debug_mode = debug_mode
        self.timeout = timeout
        
        # Results are lazily populated on first access
        self._classification = None
        self._style_profile = None

    def _analyze_content(self):
        """
        Performs a lazy, cached, AI-based analysis of the provided image and/or text
        to determine the most appropriate stylistic guidance. This version uses a more
        robust two-stage process for improved accuracy.

        The process is as follows:
        1.  **Keyword Generation**: It first asks the AI for a simple list of keywords
            describing the content.
        2.  **Candidate Filtering**: It uses these keywords to perform a fast, local search,
            scoring and ranking all available `STYLE_PROFILES` to find the top 2-3
            most likely candidates.
        3.  **AI-Powered Final Selection**: If multiple strong candidates are found, it
            presents them to the AI in a second, more detailed query, asking it to
            make the final choice based on which profile's persona and inspiration
            is the best fit for the original content. This leverages the AI's nuanced
            understanding for the final, most important decision.
        4.  **Caching**: The final selected profile is cached to avoid redundant API
            calls on subsequent runs with the same content.
        """
        # --- Step 1: Lazy Execution & Caching ---
        if self._style_profile is not None:
            return

        cache_key = _get_cache_key(self.model, self.use_chat_api, self.temperature, self.seed, self.image, self.text, self.timeout, "style_engine_analysis_v6_two_stage")
        if CACHE.has(cache_key):
            self._classification, self._style_profile = CACHE.get(cache_key)
            return

        # --- Step 2: Consolidated Analysis for Keyword Generation ---
        analysis_prompt_parts = [
            "Analyze the provided context (image and/or text) and classify its primary genre, style, and mood in a few keywords.",
            "Examples: 'fantasy, epic, painting', 'sci-fi, cyberpunk', 'portrait, romantic', 'landscape, nature', 'anime, manga', 'rock, protest song'.",
            "Return ONLY a comma-separated list of keywords."
        ]
        
        if self.text:
            analysis_prompt_parts.append(f"\n--- TEXT CONTEXT ---\n{self.text[:1000]}")

        classify_prompt = "\n".join(analysis_prompt_parts)
        image_to_analyze = [self.image] if self.image is not None else None
        
        classification_timeout = max(45, self.timeout // 2)
        ok, combined_classification = query_model_auto(
            self.model, classify_prompt, images=image_to_analyze, prefer_chat=self.use_chat_api, 
            temperature=0.1, seed=self.seed, timeout=classification_timeout, 
            debug_mode=self.debug_mode, debug_title="Classify Content Persona"
        )
        if not ok: combined_classification = ""
        self._classification = combined_classification.lower()

        # --- Step 3: Candidate Filtering (Local Scoring) ---
        fallback_persona = "You are an expert art historian and cultural analyst." if self.image is not None else "You are an expert cinematic music video director."
        fallback_inspiration = "Composition inspired by the masterful blocking of Akira Kurosawa, the dramatic lighting of Caravaggio, and the atmospheric depth of Roger Deakins."
        default_profile = {"persona": fallback_persona, "inspiration": fallback_inspiration}

        if not self._classification:
            self._style_profile = default_profile
            CACHE.set(cache_key, (self._classification, self._style_profile))
            return

        # Score all available profiles based on keyword matches.
        scored_profiles = []
        for i, profile in enumerate(STYLE_PROFILES):
            score = 0
            for group in profile.get("keywords", []):
                group_score = sum(1 for kw in group if kw in self._classification)
                if len(group) > 0 and group_score == len(group):
                    group_score += len(group) # Bonus for a full match
                score = max(score, group_score)
            
            if score > 0:
                scored_profiles.append({"score": score, "index": i, "profile": profile})

        # Sort candidates by score in descending order.
        scored_profiles.sort(key=lambda x: x["score"], reverse=True)

        # --- Step 4: AI-Powered Final Selection ---
        top_candidates = scored_profiles[:3] # Consider the top 3 candidates
        
        # If we have at least two strong candidates, let the AI make the final choice.
        if len(top_candidates) >= 2:
            chosen_profile = self._choose_best_profile_with_ai(top_candidates)
            if chosen_profile:
                self._style_profile = chosen_profile
            else:
                # If the AI selection fails, fall back to the highest-scoring local match.
                self._style_profile = top_candidates[0]["profile"]
        elif top_candidates:
            # If there's only one clear candidate, use it.
            self._style_profile = top_candidates[0]["profile"]
        else:
            # If no profiles matched, use the default.
            self._style_profile = default_profile
        
        # --- Step 5: Finalize and Cache ---
        CACHE.set(cache_key, (self._classification, self._style_profile))

    def _choose_best_profile_with_ai(self, candidates):
        """
        Asks the AI to choose the best profile from a list of candidates.
        This is the second stage of the analysis, providing a more nuanced final decision.
        """
        # Build the prompt with the candidate profiles.
        candidate_text = ""
        for i, item in enumerate(candidates):
            profile = item["profile"]
            candidate_text += f"--- Profile {i+1} ---\n"
            candidate_text += f"Persona: {profile.get('persona', 'N/A')}\n"
            candidate_text += f"Inspiration: {profile.get('inspiration', 'N/A')}\n\n"

        selection_prompt_template = textwrap.dedent("""
            You are an expert art director. Based on the provided content, which of the following creative profiles is the best fit?

            --- CONTENT TO ANALYZE ---
            {text_context}

            --- CANDIDATE PROFILES ---
            {candidates}
            --- END CANDIDATE PROFILES ---

            INSTRUCTIONS:
            Analyze the content and the profiles. Respond with ONLY a JSON object containing the number of the best-fitting profile.
            Example: {{"best_profile_index": 1}}
        """).strip()

        text_context_for_prompt = f"Text: {self.text[:1000]}" if self.text else "No text provided."
        selection_prompt = selection_prompt_template.format(
            text_context=text_context_for_prompt,
            candidates=candidate_text
        )

        # Execute the query.
        reason_kwargs = {
            "use_chat_api": self.use_chat_api, "temperature": 0.0, "seed": self.seed,
            "timeout": self.timeout, "debug_mode": self.debug_mode,
            "debug_title": "StyleEngine - Final Profile Selection"
        }
        image_to_analyze = [self.image] if self.image is not None else None
        
        ok, result_json = _reason_with_model(self.model, selection_prompt, images=image_to_analyze, **reason_kwargs)

        if ok and isinstance(result_json, dict) and "best_profile_index" in result_json:
            try:
                chosen_index = int(result_json["best_profile_index"]) - 1
                if 0 <= chosen_index < len(candidates):
                    print(f"\033[92m[PromptCrafter] StyleEngine AI chose profile {chosen_index + 1} as the best fit.\033[0m")
                    return candidates[chosen_index]["profile"]
            except (ValueError, TypeError):
                print(f"\033[93m[PromptCrafter] Warning: AI returned an invalid index for profile selection: {result_json.get('best_profile_index')}\033[0m")

        print("\033[93m[PromptCrafter] Warning: AI-powered profile selection failed. Falling back to highest-scored local match.\033[0m")
        return None

    def get_persona(self):
        """Returns the expert persona determined from content analysis."""
        self._analyze_content()
        return self._style_profile.get("persona", "You are a helpful assistant.")

    def get_composition_rules(self):
        """Generates a dynamic 'artist inspiration' rule based on content classification."""
        self._analyze_content()
        inspiration = self._style_profile.get("inspiration", "")
        return [f"- {inspiration}"] if inspiration else []

# ------------------------------------------------------------------------------------
# Configuration Object
# ------------------------------------------------------------------------------------
class PromptCrafterRunConfig:
    """A simple configuration object to pass parameters between methods."""
    def __init__(self, **kwargs):
        # Set default values for all possible attributes
        self.use_deep_think = True
        self.deep_think_confidence = 0.8
        # Dynamically set attributes from kwargs
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.style_profile = None # Will be set later
        self.negative_concepts = ""

# ------------------------------------------------------------------------------------
# API Client Abstraction
# ------------------------------------------------------------------------------------
# This section defines a class-based structure for handling API calls,
# making it easier to add new providers in the future.

class BaseAPIClient:
    """Abstract base class for all API clients."""
    def __init__(self, provider, config):
        self.provider = provider
        self.config = config
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url")

    def _get_headers(self):
        """Returns the headers for the API request. To be implemented by subclasses."""
        return {}

    def _get_url(self, model_id):
        """Returns the URL for the API request. To be implemented by subclasses."""
        raise NotImplementedError(f"URL generation not implemented for {self.provider}")

    def _build_payload(self, model_id, prompt, images_b64, **kwargs):
        """Builds the payload for the API request. To be implemented by subclasses."""
        raise NotImplementedError(f"Payload building not implemented for {self.provider}")

    def _parse_response(self, data):
        """
        Parses the JSON response from the API.
        Should return a tuple: (bool_ok, content_or_error_string).
        """
        raise NotImplementedError(f"Response parsing not implemented for {self.provider}")

    def query(self, model_id, prompt, images_b64=None, timeout=60, **kwargs):
        """
        Handles a standard text/vision query by building a payload, making a request, and parsing the response.
        This base implementation is suitable for most single-endpoint, JSON-based APIs.
        """
        headers = self._get_headers()
        url = self._get_url(model_id)
        payload = self._build_payload(model_id, prompt, images_b64, **kwargs)

        ok, data_or_err = self._make_request(url=url, headers=headers, payload=payload, timeout=timeout)

        if not ok:
            return False, data_or_err

        return self._parse_response(data_or_err)

    def _make_request(self, url, headers, payload, timeout):
        """
        A shared helper for making POST requests and handling common HTTP/network errors.
        """
        try:
            response = SHARED_SESSION.post(url, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            return True, response.json()
        except requests.exceptions.RequestException as e:
            # Handle connection errors, timeouts, etc.
            return False, f"{self.provider.capitalize()} API connection error: {e}"
        except json.JSONDecodeError:
            # Handle responses that are not valid JSON
            return False, f"{self.provider.capitalize()} API returned invalid JSON. Raw response: {getattr(response, 'text', 'N/A')}"
        except Exception as e:
            # Catches other errors, including HTTPError from raise_for_status() for non-2xx responses
            raw_response = getattr(e, 'response', '') and getattr(e.response, 'text', '')
            return False, f"{self.provider.capitalize()} API error: {e}. Raw: {raw_response}"

    def is_configured(self):
        """Checks if the client is ready to be used (e.g., has an API key)."""
        return bool(self.api_key)

class OllamaClient(BaseAPIClient):
    """Client for handling local Ollama models."""
    def is_configured(self):
        return True # Ollama is local and doesn't require an API key.

    def query(self, model_id, prompt, images_b64=None, timeout=60, temperature=None, seed=None, prefer_chat=False, **kwargs):
        order = ("chat", "generate") if prefer_chat else ("generate", "chat")
        last_err = None
        for mode in order:
            payload = self._build_payload(mode, model_id, prompt, images_b64, temperature, seed)
            
            # Use the shared helper method
            ok, data_or_err = self._make_request(
                url=f"{self.base_url}/api/{mode}",
                headers={},
                payload=payload,
                timeout=timeout
            )

            if ok:
                ok_parse, text = self._parse_response(data_or_err)
                if ok_parse:
                    return True, text.strip()
                last_err = text  # Store parsing error
            else:
                last_err = data_or_err # Store the formatted error from the helper
                # If a connection error occurs, don't bother trying the other endpoint.
                if "connection error" in str(last_err).lower():
                    break

        return False, (last_err or "Unknown Ollama error")

    def _build_payload(self, endpoint, model, prompt, images_b64, temperature=None, seed=None, **kwargs):
        payload = {"model": model, "stream": False, "options": {}}
        if endpoint == "chat":
            msg = {"role": "user", "content": prompt}
            if images_b64: msg["images"] = images_b64
            payload["messages"] = [msg]
        else: # generate
            payload["prompt"] = prompt
            if images_b64: payload["images"] = images_b64
        if temperature is not None: payload["options"]["temperature"] = float(temperature)
        if seed is not None and int(seed) >= 0: payload["options"]["seed"] = int(seed)
        if not payload["options"]: del payload["options"]
        return payload

    def _parse_response(self, data):
        """Parses the content from a successful Ollama JSON response."""
        if "response" in data: return True, data.get("response", "")
        if "message" in data and isinstance(data["message"], dict): return True, data["message"].get("content", "")
        if "choices" in data and data["choices"]: return True, data["choices"][0].get("message", {}).get("content", "")
        return False, "Could not find response content in Ollama output: {data}".format(data=json.dumps(data))

class OpenAIClient(BaseAPIClient):
    """Client for OpenAI's APIs, including Chat and DALL-E."""
    def _get_headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _get_url(self, model_id):
        return f"{self.base_url}/chat/completions"

    def _build_payload(self, model_id, prompt, images_b64, **kwargs):
        temperature = kwargs.get('temperature')
        seed = kwargs.get('seed')
        content = [{"type": "text", "text": prompt}]
        if images_b64:
            for img_b64 in images_b64:
                content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64,{0}".format(img_b64)}})
        payload = {"model": model_id, "messages": [{"role": "user", "content": content}], "max_tokens": 4096}
        if temperature is not None: payload["temperature"] = float(temperature)
        if seed is not None and int(seed) >= 0: payload["seed"] = int(seed)
        return payload

    def _parse_response(self, data):
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return True, text.strip()

class AnthropicClient(BaseAPIClient):
    """Client for Anthropic's (Claude) Messages API."""
    def _get_headers(self):
        return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"}

    def _get_url(self, model_id):
        return f"{self.base_url}/messages"

    def _build_payload(self, model_id, prompt, images_b64, **kwargs):
        temperature = kwargs.get('temperature')
        content = [{"type": "text", "text": prompt}]
        if images_b64:
            for img_b64 in images_b64:
                content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}})
        payload = {"model": model_id, "messages": [{"role": "user", "content": content}], "max_tokens": 4096}
        if temperature is not None: payload["temperature"] = float(temperature)
        return payload

    def _parse_response(self, data):
        text = "".join([c.get("text", "") for c in data.get("content", [])])
        return True, text.strip()

class GoogleClient(BaseAPIClient):
    """Client for Google's Gemini API."""
    def _get_headers(self):
        return {"Content-Type": "application/json"}

    def _get_url(self, model_id):
        return f"{self.base_url}/models/{model_id}:generateContent?key={self.api_key}"

    def _build_payload(self, model_id, prompt, images_b64, **kwargs):
        temperature = kwargs.get('temperature')
        parts = [{"text": prompt}]
        if images_b64:
            for img_b64 in images_b64:
                parts.append({"inline_data": {"mime_type": "image/png", "data": img_b64}})

        payload = { "contents": [{"parts": parts}] }

        gen_config = {}
        if temperature is not None: gen_config["temperature"] = float(temperature)
        # Gemini API does not support a seed parameter for reproducibility in the same way as others.
        if gen_config: payload["generationConfig"] = gen_config

        # Set safety settings to be less restrictive, similar to other clients.
        payload["safetySettings"] = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
        return payload

    def _parse_response(self, data):
        text_parts = []
        if 'candidates' in data:
            for candidate in data.get('candidates', []):
                for part in candidate.get('content', {}).get('parts', []):
                    if 'text' in part:
                        text_parts.append(part['text'])
        if not text_parts:
            block_reason = data.get('promptFeedback', {}).get('blockReason')
            return False, f"Request blocked by Gemini API. Reason: {block_reason}" if block_reason else f"No text content in Gemini response: {json.dumps(data)}"
        return True, "".join(text_parts).strip()

# --- Client Registry and Dispatchers ---
API_CLIENTS = {
    "openai": OpenAIClient(provider="openai", config=API_CONFIG.get("openai", {})),
    "anthropic": AnthropicClient(provider="anthropic", config=API_CONFIG.get("anthropic", {})),
    "google": GoogleClient(provider="google", config=API_CONFIG.get("google", {})),
}
OLLAMA_CLIENT = OllamaClient(provider="ollama", config={"base_url": OLLAMA_BASE})

def _log_api_status():
    """Informs the user which remote APIs are configured and ready to use."""
    configured_apis = [p.upper() for p, c in API_CLIENTS.items() if c.is_configured()]
    if configured_apis:
        print("\033[92m[PromptCrafter] API support enabled for: {apis}\033[0m".format(apis=', '.join(configured_apis)))
_log_api_status()

def query_model_auto(model, prompt, images=None, **kwargs):
    """Dispatches a text/vision query to the appropriate API client."""
    images_b64 = [encode_image(im) for im in images if im is not None] if images else []
    _debug_print(kwargs.get("debug_mode", False), kwargs.get("debug_title", "") or f"Query to {model}", prompt)

    provider, model_id = "ollama", model
    if "/" in model:
        provider_candidate, model_id_candidate = model.split("/", 1)
        if provider_candidate in API_CLIENTS:
            provider, model_id = provider_candidate, model_id_candidate

    client = API_CLIENTS.get(provider) or OLLAMA_CLIENT
    if not client.is_configured():
        return False, "API key for provider '{provider}' not found. Please set the corresponding environment variable.".format(provider=provider)
    
    # Filter kwargs to only pass arguments that the client's query method accepts.
    filtered_kwargs = _filter_kwargs(client.query, kwargs)
    
    return client.query(model_id, prompt, images_b64=images_b64, **filtered_kwargs)

# ------------------------------------------------------------------------------------
# Model discovery
# ------------------------------------------------------------------------------------

def _fetch_ollama_models():
    """
    Connects to the local Ollama server to get a list of all installed models.
    This is used to populate the model dropdowns in the UI.
    Returns a tuple: (status, data).
    - status can be 'ok', 'connection_error', or 'other_error'.
    - data is the list of models on 'ok', or an error string otherwise.
    """
    try:
        resp = SHARED_SESSION.get(f"{OLLAMA_BASE}/api/tags", timeout=3)
        resp.raise_for_status()
        # Return the full model details, not just the names.
        return 'ok', resp.json().get("models", [])
    except requests.exceptions.ConnectionError as e:
        # This is the most common error if Ollama isn't running.
        print(f"\033[93m[PromptCrafter] Warning: Could not connect to Ollama. Is it running? Error: {e}\033[0m")
        return 'connection_error', str(e)
    except requests.exceptions.RequestException as e:
        # Other request-related errors (timeout, etc.)
        print(f"\033[93m[PromptCrafter] Warning: Could not fetch Ollama models. Error: {e}\033[0m")
        return 'other_error', str(e)
    except Exception as e:
        print(f"\033[93m[PromptCrafter] Warning: An unexpected error occurred while fetching Ollama models: {e}\033[0m")
        return 'other_error', str(e)

def _get_models_by_type(model_type):
    """
    A centralized and more robust function to get models of a specific type (vision, text, or all).
    It inspects model metadata to accurately determine its capabilities (vision vs. text).
    """
    ollama_status, ollama_data = _fetch_ollama_models()
    
    ollama_models_details = []
    if ollama_status == 'ok':
        ollama_models_details = ollama_data

    # A set of known vision model family names from Ollama for robust detection.
    VISION_FAMILIES = {"llava", "moondream", "bakllava", "qwen2.5vl", "fuyu"}
    
    # Filter local Ollama models based on type
    local_models = []
    if model_type == "vision":
        if ollama_status == 'ok':
            for m in ollama_models_details:
                families = m.get("details", {}).get("families") or []
                if any(f in VISION_FAMILIES for f in families) or 'clip' in families:
                    local_models.append(m["name"])
        preferred_fallback = FALLBACK_VISION_MODEL
    elif model_type == "text":
        if ollama_status == 'ok':
            for m in ollama_models_details:
                families = m.get("details", {}).get("families") or []
                if not (any(f in VISION_FAMILIES for f in families) or 'clip' in families):
                    local_models.append(m["name"])
        preferred_fallback = FALLBACK_TEXT_MODEL
    else: # all
        if ollama_status == 'ok':
            local_models = [m.get("name") for m in ollama_models_details if m.get("name")]
        preferred_fallback = FALLBACK_TEXT_MODEL # A reasonable default

    # Add remote API models
    api_models = []
    for provider, config in API_CONFIG.items():
        if config.get("api_key"):
            if model_type == "all":
                # For 'all', combine vision and text models, ensuring no duplicates
                provider_models = set(config.get("vision_models", []) + config.get("text_models", []))
            else:
                key = "vision_models" if model_type == "vision" else "text_models"
                provider_models = config.get(key, [])
            
            for model in provider_models:
                api_models.append(f"{provider}/{model}")

    available_models = sorted(list(set(local_models + api_models)))

    # If no models are found at all, return a clear message for the UI.
    if not available_models:
        if ollama_status == 'connection_error':
            return ["OLLAMA_UNREACHABLE_CHECK_SERVER"]
        return ["NO_MODELS_FOUND_OR_CONFIGURED"]

    # If the preferred fallback model is available, move it to the front to make it the default.
    # This ensures the default is always a model the user has installed.
    if preferred_fallback and preferred_fallback in available_models:
        available_models.remove(preferred_fallback)
        available_models.insert(0, preferred_fallback)
    
    # If the preferred fallback is not available, the list is already sorted, and the first
    # available model will be selected by default, which is a safe and sensible behavior.

    return available_models

def get_vision_models():
    return _get_models_by_type("vision")

def get_text_models():
    return _get_models_by_type("text")

def get_all_models():
    return _get_models_by_type("all")

# ------------------------------------------------------------------------------------
# Safeguards / Coverage helpers
# ------------------------------------------------------------------------------------

class JSONParsingError(ValueError):
    """Custom exception for errors during JSON extraction and parsing."""
    def __init__(self, message, text=None, original_exception=None):
        self.text = text
        self.original_exception = original_exception
        full_message = message
        if text:
            # Show the position of the error if available from the original exception
            pos = getattr(original_exception, 'pos', None)
            if pos is not None:
                # Provide context around the error position
                start = max(0, pos - 40)
                end = min(len(text), pos + 40)
                snippet = text[start:end]
                pointer = " " * (pos - start) + "^"
                full_message += f"\nContext around error (pos {pos}):\n{snippet}\n{pointer}"
            else:
                full_message += f"\nText snippet: {text[:200]}..."
        
        if original_exception:
            full_message += f"\nOriginal error: {original_exception}"
        super().__init__(full_message)

def _find_json_candidate(text: str) -> str | None:
    """
    Finds the most likely JSON string candidate from raw text returned by an LLM.
    This function uses a two-pass strategy:
    1.  It first looks for a JSON object or array enclosed in a markdown code block (```json ... ```),
        which is a common and reliable format for LLMs.
    2.  If no markdown block is found, it falls back to a more robust bracket-counting
        algorithm to find the first balanced JSON object or array. This handles cases
        where the JSON is embedded in conversational text.
    """
    # 1. Prioritize markdown code blocks, as they are explicitly formatted.
    # The regex looks for ```, optionally followed by 'json', then captures everything
    # between the first { or [ and the last } or ] until it sees the closing ```.
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", text, re.DOTALL)
    if match:
        return match.group(1)

    # 2. Fallback: Find the first balanced JSON object/array using bracket counting.
    # This is more robust than a simple find/rfind, as it won't be fooled by brackets in trailing text.
    
    # Find the position of the first opening brace or bracket.
    first_brace = text.find('{')
    first_bracket = text.find('[')

    start_pos = -1
    if first_brace == -1 and first_bracket == -1:
        return None # No JSON start character found.
    elif first_brace == -1:
        start_pos = first_bracket
    elif first_bracket == -1:
        start_pos = first_brace
    else:
        start_pos = min(first_brace, first_bracket)

    # Use a counter to find the matching closing bracket for a balanced object.
    balance = 0
    in_string = False
    for i in range(start_pos, len(text)):
        char = text[i]

        # Toggle in_string state if we encounter a quote that is not escaped.
        if char == '"' and (i == 0 or text[i-1] != '\\'):
            in_string = not in_string
        
        # Only count brackets if we are not inside a string literal.
        if not in_string:
            if char == '{' or char == '[':
                balance += 1
            elif char == '}' or char == ']':
                balance -= 1
        
        # When the balance counter returns to zero, we've found the end of the balanced JSON.
        if balance == 0:
            return text[start_pos : i + 1]

    # If the loop completes and balance is not 0, it means no balanced JSON was found.
    return None

def _clean_json_string(json_str: str) -> str:
    """
    Cleans a JSON string candidate to fix common, non-standard syntax produced by LLMs.
    This function is heuristic and aims to fix the most frequent errors without being
    overly aggressive and breaking valid content (like URLs) within string literals.
    """
    # 1. Remove single-line comments (//...) that start at the beginning of a line.
    cleaned_str = re.sub(r"^\s*//.*$", "", json_str, flags=re.MULTILINE)

    # 2. Remove multi-line C-style comments (/* ... */).
    cleaned_str = re.sub(r'/\*[\s\S]*?\*/', '', cleaned_str)

    # 3. Add quotes to unquoted keys, a common JS/Python-like syntax. e.g., {key: "value"} -> {"key": "value"}
    cleaned_str = re.sub(r'([{,]\s*)(\w+)(\s*:)', r'\1"\2"\3', cleaned_str)
    
    # 4. Remove trailing commas from objects and arrays. e.g., `[1, 2,]` -> `[1, 2]`
    cleaned_str = re.sub(r",\s*([}\]])", r"\1", cleaned_str)

    # 5. Replace Python/JS boolean and null literals with their JSON standard equivalents (case-insensitive).
    cleaned_str = re.sub(r'\bTrue\b', 'true', cleaned_str, flags=re.IGNORECASE)
    cleaned_str = re.sub(r'\bFalse\b', 'false', cleaned_str, flags=re.IGNORECASE)
    cleaned_str = re.sub(r'\bNone\b', 'null', cleaned_str)
    
    # 6. Safely handle unescaped control characters inside strings.
    # This is a common failure mode for LLMs, where they might include a literal
    # newline in a string instead of an escaped `\n`. A simple regex replace is
    # too risky as it can corrupt valid formatting. This state-machine approach
    # iterates through the string, only modifying characters when it's certain
    # it's inside a string literal.
    result = []
    in_string = False
    is_escaped = False
    for char in cleaned_str:
        if char == '"' and not is_escaped:
            in_string = not in_string
        
        # If we are inside a string and encounter a newline, escape it.
        if in_string and not is_escaped:
            if char == '\n':
                result.append('\\n')
                continue
            if char == '\r':
                # Just skip carriage returns, as \n is the standard.
                continue
        
        result.append(char)
        
        # Track escape characters to correctly handle '\"'
        is_escaped = (char == '\\' and not is_escaped)
            
    return "".join(result).strip()

def _extract_and_parse_json(text: str):
    """
    Extracts and parses a JSON object from a string that may contain other text.
    This function is the main entry point for robustly handling JSON from LLMs.
    
    The process is as follows:
    1.  **Find**: It calls `_find_json_candidate` to locate the most likely JSON substring.
    2.  **Clean**: It passes the candidate string to `_clean_json_string` to fix common
        syntax errors like trailing commas or unquoted keys.
    3.  **Parse (Attempt 1: JSON)**: It attempts to parse the cleaned string using `json.loads`.
    4.  **Parse (Attempt 2: Python Literal)**: If JSON parsing fails, it attempts to parse
        the cleaned string as a Python literal using `ast.literal_eval`, which is more
        lenient (handles single quotes, etc.).
    5.  **Error Handling**: If all parsing attempts fail, it raises a custom `JSONParsingError`
        with detailed context for debugging.
    """
    if not text or not text.strip():
        raise JSONParsingError("Input text is empty or contains only whitespace.")

    # Step 1: Find the most likely JSON substring from the raw model output.
    json_str_candidate = _find_json_candidate(text)
    
    if not json_str_candidate:
        text_to_parse, source_label = text, "full text response"
    else:
        text_to_parse, source_label = json_str_candidate, "extracted JSON candidate"

    # Step 2: Clean the candidate string to fix common LLM syntax errors.
    cleaned_json_str = _clean_json_string(text_to_parse)

    # Step 3: Attempt to parse with json.loads (strict).
    try:
        return json.loads(cleaned_json_str)
    except json.JSONDecodeError as json_err:
        # Step 4: If JSON fails, attempt to parse with ast.literal_eval (more lenient).
        # This is great for handling Python-style dicts (e.g., using single quotes).
        try:
            # We must replace json-style true/false/null back to Python-style for literal_eval
            pythonic_str = cleaned_json_str.replace('true', 'True').replace('false', 'False').replace('null', 'None')
            return ast.literal_eval(pythonic_str)
        except (ValueError, SyntaxError, MemoryError, TypeError) as ast_err:
            # Step 5: If all attempts fail, raise our custom, more informative error.
            raise JSONParsingError(
                f"Failed to parse {source_label} as JSON or Python literal.",
                text=cleaned_json_str,
                original_exception=json_err # Report the original JSON error as it's the primary goal
            ) from ast_err

def _reason_with_model(model, prompt, use_chat_api, temperature, seed, images=None, timeout=40, debug_mode=False, debug_title=""):
    """
    A powerful helper function that asks a model a question where the expected answer is JSON.
    It's "smart" because even if the model wraps the JSON in conversational text, this function
    will try to find and parse just the JSON part. This is crucial for getting structured data
    back from the AI for tasks like coverage checks or classification.
    """
    ok, resp = query_model_auto(model, prompt, images=images, prefer_chat=use_chat_api, temperature=temperature, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title=debug_title)
    if not ok:
        return False, "Model reasoning query failed: {resp}".format(resp=resp)
    
    try:
        # Use the robust JSON extractor to parse the response.
        parsed_json = _extract_and_parse_json(resp)
        return True, parsed_json
    except JSONParsingError as e:
        # The custom exception now contains all the details.
        return False, "Failed to parse JSON from model response. Error: {e}".format(e=e)

def _summarize_deep_think_objectives(model, initial_prompt_text, **critique_kwargs):
    """
    Distills a detailed user request into a concise list of core objectives
    to keep the Deep Think critique process focused and token-efficient.
    """
    summarize_template = textwrap.dedent("""
        You are a task analysis expert. Read the following detailed request and summarize it into a concise list of core objectives and constraints for a prompt engineer.
        Focus on mandatory subjects, style requirements, and negative constraints.

        --- FULL REQUEST ---
        {request}
        --- END FULL REQUEST ---

        Return ONLY the summarized list of objectives.
    """).strip()
    summarize_prompt = summarize_template.format(request=initial_prompt_text)
    
    summary_kwargs = critique_kwargs.copy()
    summary_kwargs['temperature'] = 0.1
    summary_kwargs.pop('debug_title', None) # Remove any incoming title to avoid conflict
    ok_summary, core_objectives = query_model_auto(model, summarize_prompt, **summary_kwargs, debug_title="Deep Think - Summarize Objectives")
    
    if not ok_summary:
        print("\033[93m[PromptCrafter] Warning: Deep Think objective summarization failed. Using full prompt text for critiques.\033[0m")
        return initial_prompt_text
    
    return core_objectives

def _run_deep_think_iteration(current_prompt, history, core_objectives, model, **critique_kwargs):
    """
    Executes a single critique-and-refine cycle within the Deep Think loop.
    """
    # --- Build a concise history log ---
    history_log = ""
    if history:
        history_log = "--- REFINEMENT HISTORY (for context) ---\n"
        # We only show the last 2 critiques to keep the context window focused and efficient.
        for j, (p, c) in enumerate(history[-2:]):
            history_log += f"Critique of previous version: {c}\n"
        history_log += "--- END REFINEMENT HISTORY ---\n\n"

    # --- Construct the critique prompt ---
    critique_template = textwrap.dedent("""
        You are a meticulous prompt editor. Your task is to critique and refine a generated prompt based on a set of core objectives.

        --- CORE OBJECTIVES ---
        {objectives}
        --- END CORE OBJECTIVES ---

        {log}
        --- CURRENT PROMPT TO CRITIQUE ---
        {prompt}
        --- END CURRENT PROMPT ---

        CRITIQUE INSTRUCTIONS:
        1.  **Analyze**: Does the "CURRENT PROMPT" fully satisfy all "CORE OBJECTIVES"?
        2.  **Review History**: Check the "REFINEMENT HISTORY" (if any). Has the current text addressed previous critiques, or is it repeating mistakes?
        3.  **Score & Refine**: Provide a confidence score (0.0-1.0) on its quality and adherence. If the score is less than 1.0, provide a concise critique explaining the issues and a `refined_prompt` that fixes them.

        Return your response as a single JSON object with three keys:
        - `confidence_score`: (float) 0.0 to 1.0
        - `critique`: (string) Your detailed critique.
        - `refined_prompt`: (string) The improved version of the prompt. If the current prompt is already perfect, return it unmodified.
    """).strip()
    critique_prompt = critique_template.format(objectives=core_objectives, log=history_log, prompt=current_prompt)
    
    # --- Execute the critique ---
    reason_kwargs = critique_kwargs.copy()
    if 'prefer_chat' in reason_kwargs:
        reason_kwargs['use_chat_api'] = reason_kwargs.pop('prefer_chat')

    iteration_num = len(history) + 1
    return _reason_with_model(model, critique_prompt, **reason_kwargs, debug_title=f"Deep Think - Critique Iteration {iteration_num}")

def _deep_think_and_refine(model, generation_prompt_text, max_iterations=3, confidence_threshold=0.8, **kwargs):
    """
    Orchestrates a multi-step self-critique and refinement loop to produce a
    higher quality prompt. This version is optimized to combine the initial generation
    and first critique into a single API call, making it more efficient.
    """
    # --- Step 1: Prepare Keyword Arguments for Text-Only Operations ---
    # These kwargs are for subsequent text-only critique iterations.
    critique_kwargs = kwargs.copy()
    critique_kwargs.pop('images', None)
    critique_kwargs.pop('images_b64', None)
    critique_kwargs.pop('debug_title', None)

    # --- Step 2: Summarize the full generation prompt into concise objectives ---
    core_objectives = _summarize_deep_think_objectives(model, generation_prompt_text, **critique_kwargs)
    _debug_print(kwargs.get("debug_mode", False), "Deep Think - Core Objectives", core_objectives)
    
    # --- Step 3: Start the iterative refinement loop ---
    current_prompt = ""
    history = []
    for i in range(max_iterations):
        iteration_num = i + 1
        _debug_print(kwargs.get("debug_mode", False), f"Deep Think - Iteration {iteration_num} Start", f"Input Prompt:\n{current_prompt or '(First iteration, generating initial draft)'}")
        
        if i == 0:
            # --- First Iteration: Generate and Self-Critique in one call ---
            initial_gen_template = textwrap.dedent("""
                You are a professional cinematic prompt engineer and a meticulous editor. Your task is to perform two steps:
                1.  **GENERATE**: Read the "FULL REQUEST" and generate a high-quality, polished prompt that fulfills it. The request may include image context, which you should use.
                2.  **CRITIQUE**: Immediately after generating, critique your own work. Analyze if your generated prompt fully satisfies all "CORE OBJECTIVES". Provide a confidence score (0.0-1.0) and a brief critique.

                --- FULL REQUEST (for generation) ---
                {full_request}
                --- END FULL REQUEST ---

                --- CORE OBJECTIVES (for self-critique) ---
                {objectives}
                --- END CORE OBJECTIVES ---

                Return your response as a single JSON object with three keys:
                - `refined_prompt`: (string) The initial prompt you generated.
                - `confidence_score`: (float) Your confidence (0.0-1.0) that the prompt meets all objectives.
                - `critique`: (string) Your brief critique explaining any potential shortcomings.
            """).strip()
            
            initial_prompt = initial_gen_template.format(full_request=generation_prompt_text, objectives=core_objectives)
            
            # The initial generation needs the full kwargs, including images.
            reason_kwargs = kwargs.copy()
            if 'prefer_chat' in reason_kwargs:
                reason_kwargs['use_chat_api'] = reason_kwargs.pop('prefer_chat')
            reason_kwargs.pop('debug_title', None) # Remove the generic title to avoid conflict
            
            ok, critique_json = _reason_with_model(model, initial_prompt, **reason_kwargs, debug_title=f"Deep Think - Initial Generation & Critique")
        else:
            # --- Subsequent Iterations: Refine based on history ---
            ok, critique_json = _run_deep_think_iteration(current_prompt, history, core_objectives, model, **critique_kwargs)
        
        if not ok or not isinstance(critique_json, dict):
            print("\033[93m[PromptCrafter] Warning: Deep Think critique failed. Proceeding with current prompt.\033[0m")
            _debug_print(kwargs.get("debug_mode", False), f"Deep Think - Iteration {iteration_num} Critique Failed", f"Error: {critique_json}")
            return (True, current_prompt) if current_prompt else (False, "Deep Think process failed at initial generation.")
        
        confidence_score = critique_json.get("confidence_score", 0.0)
        refined_prompt = critique_json.get("refined_prompt")
        critique = critique_json.get("critique", "No critique provided.")
        
        if not refined_prompt:
            print("\033[93m[PromptCrafter] Warning: Deep Think iteration did not return a refined prompt. Using previous version.\033[0m")
            refined_prompt = current_prompt
            if not refined_prompt:
                 return False, "Deep Think process failed to generate an initial prompt."

        # Log the outcome of this iteration.
        history.append((current_prompt or "Initial Generation", critique))
        _debug_print(kwargs.get("debug_mode", False), f"Deep Think - Iteration {iteration_num} Critique Result", f"Confidence: {confidence_score}\nCritique: {critique}")
        
        # Check exit conditions.
        if confidence_score >= confidence_threshold:
            _debug_print(kwargs.get("debug_mode", False), f"Deep Think - Confidence Threshold ({confidence_threshold}) Met", f"Final Prompt: {refined_prompt}")
            return True, refined_prompt

        if refined_prompt.strip() == current_prompt.strip():
            _debug_print(kwargs.get("debug_mode", False), "Deep Think - Prompt Stabilized", "Refined prompt is identical to the previous one. Finalizing.")
            return True, refined_prompt

        current_prompt = refined_prompt
    
    print("\033[93m[PromptCrafter] Warning: Deep Think loop finished without high confidence. Returning last prompt.\033[0m")
    return True, current_prompt

def _unique_keep_order(seq):
    """A helper to remove duplicate items from a list while preserving the original order."""
    seen = set()
    result = []
    for item in seq:
        if not item:
            continue
        key = item.lower().strip()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result

def _post_process_extracted_subjects(items_list, post_process_func=None):
    """
    Cleans, filters, and deduplicates a list of subjects returned by the AI.
    """
    if not items_list or not isinstance(items_list, list):
        return []

    processed_items = []
    for item in items_list:
        if not item:
            continue
        
        # Convert to string and apply the optional, task-specific cleaning function.
        processed_item = str(item)
        if post_process_func:
            processed_item = post_process_func(processed_item)
        
        # Append the cleaned item if it's not empty.
        if processed_item and processed_item.strip():
            processed_items.append(processed_item.strip())
    
    # Deduplicate the final list while preserving order and cap the length.
    return _unique_keep_order(processed_items)[:40]

def _extract_subjects(source_text, source_label, instruction_text, config, debug_title, post_process_func=None):
    """
    A generic, data-driven helper function for extracting a list of subjects from a given
    text using an AI model. It's designed to be reusable for various extraction tasks
    by customizing the instruction prompt.

    The process is as follows:
    1.  **Prompt Construction**: It builds a specific prompt that instructs the AI on what
        to extract from the `source_text`.
    2.  **AI Query**: It calls `_reason_with_model` to execute the query, which is robust
        at parsing JSON responses even if they are wrapped in conversational text.
    3.  **Post-Processing**: It passes the raw list to a dedicated helper for cleaning,
        filtering, and deduplication.
    """
    # --- Step 1: Initial Validation ---
    if not source_text or not source_text.strip() or source_text.strip() == DEFAULT_PROMPT_TEXT:
        return True, []

    # --- Step 2: Prompt Construction ---
    prompt_template = textwrap.dedent("""
        {instruction}
        Return ONLY a JSON array of strings: ["item1", "item2", ...]. No commentary.

        --- {label} ---
        {text}
        --- END {label} ---
    """)
    ask_prompt = prompt_template.format(instruction=instruction_text, label=source_label.upper(), text=source_text)
    
    # --- Step 3: AI Query ---
    ok, items_or_err = _reason_with_model(config.model, ask_prompt, config.use_chat_api, config.temperature, config.seed, debug_mode=config.debug_mode, debug_title=debug_title)
    if not ok:
        return False, items_or_err

    # --- Step 4: Post-Processing and Finalization ---
    # Delegate cleaning and filtering to a dedicated helper function.
    # This also handles cases where the model returns something other than a list.
    final_items = _post_process_extracted_subjects(items_or_err, post_process_func)
    return True, final_items

def _extract_primary_subjects(user_text, config):
    """
    Extracts mandatory subjects from the user's explicit instructions.
    This function is a specialized wrapper around the generic `_extract_subjects` helper.
    It defines a specific instruction for the AI to focus only on the user's text and
    identify the core, non-negotiable subjects for the scene. These are considered
    "primary" subjects and are given the highest priority in the final prompt.

    It also includes a post-processing function (`clean_func`) to remove any accidental
    references to source images (e.g., "the man from image 1") that the AI might include.
    """
    instruction = "From the USER INSTRUCTIONS, extract a literal list of all visual subjects, characters, and specific named objects the user explicitly wants to see in the final scene. IGNORE musical instruments, audio descriptions, tempo notes, and genre descriptions."
    
    def clean_func(item_text):
        """
        Cleans an extracted subject item. It removes references to source images and filters out
        vague, meta-level instructions that LLMs sometimes misinterpret as literal subjects.
        """
        cleaned = re.sub(r'\s*\bfrom image \d+\b\s*', ' ', item_text, flags=re.I).strip()
        
        stop_phrases = {
            "main subjects", "the subjects", "the characters", "subjects from the image", 
            "characters from the image", "an epic scene", "a scene", "main subject",
            "the main subject", "the main subjects in the images", "subjects in the images"
        }
        return "" if cleaned.lower().strip(".,'\"- ") in stop_phrases else cleaned
 
    return _extract_subjects(
        # By using the full user_text here, we ensure that all explicitly requested
        # subjects are captured, even if the _parse_user_text function splits them
        # between 'instructions' and 'context'. This is more robust.
source_text=user_text,
        source_label="USER INSTRUCTIONS",
        instruction_text=instruction,
        config=config,
        debug_title="Extract Primary Subjects",
        post_process_func=clean_func
    )

def _extract_secondary_subjects(image_context, config):
    """
    Extracts all potential subjects from the AI-generated image context descriptions.
    This function is a specialized wrapper around the generic `_extract_subjects` helper.
    It defines an instruction for the AI to scan the detailed descriptions of the
    reference images and list all potential subjects. These are considered "secondary"
    or "optional" subjects and are used to enrich the scene, but only if they are
    coherent with the primary subjects from the user's instructions.
    """
    if not image_context or image_context.startswith("No reference images provided."):
        return True, []

    instruction = "From the IMAGE DESCRIPTIONS, extract a list of all subjects, characters, and major objects."
    
    # A simple post-processing function to clean up any extra whitespace.
    clean_func = lambda item_text: re.sub(r'\s+', ' ', item_text).strip()

    return _extract_subjects(
        source_text=image_context,
        source_label="IMAGE DESCRIPTIONS",
        instruction_text=instruction,
        config=config,
        debug_title="Extract Secondary Subjects",
        post_process_func=clean_func
    )

def _extract_mandatory_tokens_with_model(image_context: str, user_text: str, config: PromptCrafterRunConfig):
    """
    Orchestrates the extraction of all subjects from both user instructions and image context.
    This function is a critical part of the prompt engineering pipeline, creating a structured
    list of subjects that guides the final prompt generation and refinement steps.

    The process is as follows:
    1.  **Caching**: Checks if this exact combination of inputs has been processed before
        to avoid redundant API calls.
    2.  **Extract Primary Subjects**: Calls `_extract_primary_subjects` to get a list of
        non-negotiable subjects from the user's direct instructions.
    3.  **Extract Secondary Subjects**: Calls `_extract_secondary_subjects` to get a list
        of all potential subjects from the AI-generated image descriptions.
    4.  **Combine & Filter**: Merges the two lists, ensuring that subjects listed as
        primary are not duplicated in the secondary list.
    5.  **Tag & Format**: Formats the final lists into a dictionary with clear tags
        (`[PRIMARY]`, `[SECONDARY]`) for use in later prompts. It also creates a
        combined `allowed_list` which is crucial for the anti-hallucination check.
    """
    # --- Step 1: Caching ---
    # A unique cache key is generated from all inputs. If this function has been run with
    # the exact same inputs before, we can return the cached result immediately.
    cache_key = _get_cache_key(config.model, image_context, config.use_chat_api, config.temperature, config.seed, user_text, "extract_tokens", config.debug_mode)
    if CACHE.has(cache_key):
        print("\033[94m[PromptCrafter] Using cached token extraction.\033[0m")
        return True, CACHE.get(cache_key)

    # --- Step 2: Extract PRIMARY (mandatory) subjects from user instructions. ---
    # These are the subjects the user has explicitly asked for and are non-negotiable.
    ok_prim, primary_subjects_or_err = _extract_primary_subjects(user_text, config)
    if not ok_prim:
        return False, primary_subjects_or_err

    # --- Critical Failure Check ---
    # If the user provided specific instructions, but the AI failed to identify any subjects,
    # it's better to stop here with a clear error message than to proceed with an empty list.
    if user_text.strip() and user_text.strip() != DEFAULT_PROMPT_TEXT and not primary_subjects_or_err:
        return False, "Model did not identify any required subjects from your instructions. Please try rephrasing."

    # --- Step 3: Extract SECONDARY (optional) subjects from image context. ---
    # These are all the subjects identified in the reference images. They are considered
    # optional and will only be used if they fit coherently with the primary subjects.
    ok_sec, secondary_subjects_or_err = _extract_secondary_subjects(image_context, config)
    if not ok_sec:
        # A failure here is not critical; we can proceed without secondary subjects.
        print(f"\033[93m[PromptCrafter] Warning: Could not extract secondary subjects: {secondary_subjects_or_err}\033[0m")
        secondary_subjects = []
    else:
        secondary_subjects = secondary_subjects_or_err

    # --- Step 4: Combine & Filter ---
    # Filter the secondary list to remove any subjects that are already in the primary list.
    # This prevents redundancy in the final prompt construction.
    primary_lower = {p.lower() for p in primary_subjects_or_err}
    clean_sec = [item for item in secondary_subjects if str(item).lower() not in primary_lower]

    # --- Step 5: Tag & Format ---
    # The subjects are tagged to make their priority clear to the AI in later steps.
    tagged = {
        "primary": [f"[PRIMARY] {s}" for s in primary_subjects_or_err],
        "secondary": [f"[SECONDARY][OPTIONAL] {s}" for s in clean_sec]
    }
    
    # Create a combined "allowed list" of all known subjects. This is a crucial tool
    # for the anti-hallucination step, where the AI is instructed to ONLY use subjects
    # from this list, preventing it from inventing new, unwanted details.
    allowed_list = primary_subjects_or_err + clean_sec
    tagged["allowed_list"] = _unique_keep_order([s for s in allowed_list if s])

    # Cache the successful result before returning.
    CACHE.set(cache_key, tagged)
    return True, tagged

# ------------------------------------------------------------------------------------
# PromptCrafter_QnA Node
# ------------------------------------------------------------------------------------

"""
The PromptCrafter_QnA node is a straightforward tool for interacting with a text-based AI.
You can ask it a question or give it an instruction, and it will generate a text response.
It can also use an optional text file as context for the query.
"""
class PromptCrafter_QnA:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # --- Core Inputs & Model ---
                "user_text": ("STRING", {"multiline": True, "default": DEFAULT_PROMPT_TEXT, "tooltip": "Your question or instruction for the model."}),
                "model": (get_all_models(), {"dynamic": True, "tooltip": "The language model (text or vision) to use for the answer."}),
                # --- Generation Control ---
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Controls creativity. Lower is more deterministic."}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "step": 1, "tooltip": "Seed for reproducible results. -1 for random. Set Temperature to 0 for full determinism."}),
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10, "tooltip": "Timeout in seconds for each API call. Increase if you get timeout errors."}),
                # --- Behavior & Safety ---
                "safe_mode": ("BOOLEAN", {"default": True, "tooltip": "Enforce SFW rules to prevent NSFW, violent, or controversial content."}),
                "debug_mode": ("BOOLEAN", {"default": False, "tooltip": "Print all intermediate prompts to the console for debugging."}),
                # --- File Output ---
                "save_to_txt": ("BOOLEAN", {"default": False, "tooltip": "Save the full Q&A context and response to a text file in the ComfyUI/output directory."}),
                "filename_prefix": ("STRING", {"multiline": False, "default": "PromptCrafter/QnA", "tooltip": "Subdirectory and prefix for the saved text file."}),
            },
            "optional": {
                # --- Optional Inputs & Features ---
                "image": ("IMAGE", {"tooltip": "Optional reference image for the query. Requires a vision model (VLM)."}),
                "auto_select_model": ("BOOLEAN", {"default": True, "tooltip": "Automatically select a vision model if an image is connected, or a text model if not."}),
                "enable_web_search": ("BOOLEAN", {"default": True, "tooltip": "Allow the node to perform a web search for questions about recent events or topics requiring current information."}),
                "fast_web_search": ("BOOLEAN", {"default": True, "tooltip": "In web search mode, only use search result snippets instead of fetching full page content. Much faster."}),
                # --- External File Context ---
                "folder_path": ("STRING", {"multiline": False, "default": "input", "tooltip": "Folder containing an optional context file (e.g., 'input' or 'input/texts')."}),
                "file_name": ("STRING", {"multiline": False, "default": "<none>", "tooltip": "The name of the text file within the specified folder."}),
                "chunk_large_context": ("BOOLEAN", {"default": True, "tooltip": "Automatically chunk and summarize context files that are too large."}),
                "chunk_size_words": ("INT", {"default": 2000, "min": 500, "max": 8000, "step": 100, "tooltip": "The approximate size of each chunk in words for summarization."}),
                "summarization_strategy": (["Default (Abstractive)", "Extractive"], {"default": "Default (Abstractive)", "tooltip": "How to summarize large context. Abstractive creates new text, Extractive pulls key sentences."}),
                # --- Conversation History ---
                "history_in": ("STRING", {"multiline": False, "default": "", "input": "hidden"}), # Hidden input for wiring
                "clear_history": ("BOOLEAN", {"default": False, "tooltip": "Set to True for one run to clear the conversation history."}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("response", "history_out")
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter (v{__version__})"
    HELP = {
        "title": "PromptCrafter QnA",
        "description": (
            "This node lets you have a text-based conversation with any supported AI model. It can summarize text, describe an image, or answer a question.\n\n"
            "**Key Features:**\n"
            "- **Web Search**: Automatically performs a web search for questions about recent events or topics requiring current information.\n"
            "- **Context Files**: Can use a text file or PDF as context for your query.\n"
            "- **Large Context Handling**: Automatically chunks and summarizes very large text files to fit within the model's context window.\n"
            "- **Conversation History**: To have a conversation, wire the `history_out` back into the `history_in` input. Use the `clear_history` toggle to start a new conversation."
        ),
        "reset": True,
    }
    DESCRIPTION = HELP["description"]

    def reset_defaults(self, **kwargs):
        """Called when user presses Reset in the help panel"""
        return {
            "temperature": 0.2,
            "seed": -1,
        }

    def execute(self, user_text, model, temperature, seed, debug_mode, safe_mode, save_to_txt, filename_prefix, image=None, auto_select_model=True, folder_path=None, file_name="<none>", chunk_large_context=True, chunk_size_words=2000, timeout=120, enable_web_search=True, fast_web_search=True, history_in="", clear_history=False, summarization_strategy="Default (Abstractive)"):
        llm_model = model
        has_image = image is not None

        if auto_select_model:
            # Get lists of available vision and text models
            vision_models_list = _get_models_by_type("vision")
            text_models_list = _get_models_by_type("text")

            is_vision_model = llm_model in vision_models_list
            is_text_model = llm_model in text_models_list

            if has_image and not is_vision_model:
                # An image is connected, but the selected model is not a vision model.
                # Find a suitable vision model to switch to.
                fallback = next((m for m in vision_models_list if "llava" in m), vision_models_list[0] if vision_models_list else FALLBACK_VISION_MODEL)
                print(f"\033[93m[PromptCrafter] Warning: Image provided to QnA node, but '{llm_model}' is not a vision model. Auto-switching to '{fallback}'.\033[0m")
                llm_model = fallback
            
            elif not has_image and is_vision_model and not is_text_model:
                # No image is connected, but the selected model is ONLY a vision model.
                # Find a suitable text model to switch to.
                fallback = next((m for m in text_models_list if "llama3" in m), text_models_list[0] if text_models_list else FALLBACK_TEXT_MODEL)
                print(f"\033[93m[PromptCrafter] Warning: No image provided to QnA node, but '{llm_model}' is a vision-only model. Auto-switching to '{fallback}'.\033[0m")
                llm_model = fallback

        # Final fallback if no model is selected at all
        if not llm_model:
            llm_model = FALLBACK_TEXT_MODEL

        context = ""
        raw_context = ""
        context_source = "None"

        # --- Step 0: Handle Conversation History ---
        history_text = ""
        if history_in and not clear_history:
            history_text = history_in.strip()

        has_file_context = folder_path and file_name and file_name != "<none>"

        # --- Step 1: Determine Context Source ---
        # Priority 1: User-provided file
        if has_file_context:
            full_folder_path = folder_path
            if not os.path.isabs(full_folder_path):
                full_folder_path = os.path.join(COMFYUI_ROOT_DIR, full_folder_path)
            fpath = os.path.join(full_folder_path, file_name)
            if os.path.exists(fpath):
                raw_context = safe_read(fpath)
                context = raw_context
                context_source = f"File ({file_name})"
            else:
                context = f"[Error: File not found at '{fpath}'. Ensure the folder path is correct relative to the ComfyUI root directory (e.g., 'input').]"
                raw_context = context
                context_source = f"File ({file_name}) - Not Found"
        
        # Priority 2: Web Search (if no file context was provided)
        elif enable_web_search:
            search_needed, search_query = _should_perform_web_search(user_text, llm_model, seed, debug_mode, timeout=timeout)
            if search_needed:
                web_context = _perform_web_search(search_query, num_results=3, debug_mode=debug_mode, fast_search=fast_web_search)
                context = web_context
                raw_context = web_context # For saving, raw and processed are the same here
                context_source = f"Web Search (query: '{search_query}')"

        # --- Step 2: Process Context (Summarization) ---
        strategy_key = "extractive" if "Extractive" in summarization_strategy else "default"
        if chunk_large_context and context and not context.startswith("[Error"):
            words = context.split()
            if len(words) > chunk_size_words:
                print(f"\033[94m[PromptCrafter] Context from {context_source} is large ({len(words)} words). Summarizing...\033[0m")
                context = _summarize_large_text(raw_context, chunk_size_words, llm_model, temperature, seed, debug_mode, timeout, strategy=strategy_key, user_query=user_text)
                _debug_print(debug_mode, "Summarized Context", context)

        # Summarize user_text if it's also large
        final_user_text = user_text
        raw_user_text = user_text
        if chunk_large_context and len(user_text.split()) > chunk_size_words:
            # Check if it's just a default prompt before summarizing
            if user_text.strip() != DEFAULT_PROMPT_TEXT:
                print("\033[94m[PromptCrafter] User text is large ({count} words). Summarizing...\033[0m".format(count=len(user_text.split())))
                final_user_text = _summarize_large_text(user_text, chunk_size_words, llm_model, temperature, seed, debug_mode, timeout, strategy=strategy_key)
                _debug_print(debug_mode, "Summarized User Text", final_user_text)

        # If user provides a context file or image but no specific query, use a smart default.
        if (context or image is not None) and user_text.strip() == DEFAULT_PROMPT_TEXT:
            if image is not None:
                final_user_text = "Describe this image in detail."
            else:
                final_user_text = "Summarize the key points of the provided context, or describe its content if it's not text."
        
        # Construct the final prompt sent to the model.
        safety_rule = "\n\n{0}".format(SAFE_MODE_RULE) if safe_mode else ""

        # Build prompt sections
        history_section = f"CONVERSATION HISTORY (for context):\n{history_text}\n\n" if history_text else ""
        context_section = f"ADDITIONAL CONTEXT (for this query only):\n{context}\n\n" if context else ""
        
        prompt = textwrap.dedent("""
            You are a helpful Q&A assistant. Answer the user's query based on the conversation history and any additional context provided.
            
            {history_section}{context_section}CURRENT USER QUERY:
            {query}
            {safety}
        """).format(history_section=history_section, context_section=context_section, query=final_user_text, safety=safety_rule).strip()

        images_to_pass = [image] if image is not None else None
        ok, resp = query_model_auto(llm_model, prompt, images=images_to_pass, prefer_chat=True, temperature=temperature, seed=seed, debug_mode=debug_mode, debug_title="QnA Prompt", timeout=timeout)

        response_text = TextCleaner.single_paragraph(resp if ok else "Ollama error: {resp}".format(resp=resp))
        # --- Update History ---
        new_history_entry = f"User: {final_user_text}\nAssistant: {response_text}"
        updated_history = f"{history_text}\n{new_history_entry}".strip() if history_text else new_history_entry
        if save_to_txt and response_text.strip():
            # Save to ComfyUI's main output directory
            base_dir = os.path.join(COMFYUI_ROOT_DIR, "output")
            safe_subdir = os.path.normpath(filename_prefix.strip()).lstrip('.').lstrip('/')
            out_dir = os.path.join(base_dir, safe_subdir)
            os.makedirs(out_dir, exist_ok=True)
            fname = "qna_{ts}.txt".format(ts=time.strftime('%Y%m%d_%H%M%S'))
            fpath = os.path.join(out_dir, fname)
            with open(fpath, "w", encoding="utf-8") as f:
                if history_text:
                    f.write("=== CONVERSATION HISTORY ===\n")
                    f.write(history_text + "\n\n")
                f.write(f"=== CONTEXT SOURCE: {context_source} ===\n\n")
                if raw_context:
                    f.write("=== CONTEXT (RAW) ===\n")
                    f.write(raw_context + "\n\n")
                    if raw_context != context: # if summarization happened
                        f.write("=== CONTEXT (SUMMARIZED) ===\n")
                        f.write(context + "\n\n")
                f.write("=== USER QUERY (RAW) ===\n" if raw_user_text != final_user_text else "=== USER QUERY ===\n")
                f.write(user_text + "\n\n")
                if raw_user_text != final_user_text:
                    f.write("=== USER QUERY (SUMMARIZED) ===\n")
                    f.write(final_user_text + "\n\n")
                f.write("=== RESPONSE ===\n")
                f.write(response_text + "\n")
        return (response_text, updated_history)

# ------------------------------------------------------------------------------------
# PromptCrafter_Captioner Node
# ------------------------------------------------------------------------------------

"""
The PromptCrafter_Captioner node uses a multimodal (vision) AI model to generate a
descriptive caption for a single image. It's designed to create captions that are
well-suited for training AI models like LoRAs, focusing on factual, comma-separated descriptions.
"""
DEFAULT_CAPTION_PROMPT = textwrap.dedent("""
    Create a concise, descriptive caption for this image, suitable for training an AI model.
    - Be factual and literal. Describe only what is visible.
    - Start with the main subject.
    - Use comma-separated phrases or tags.
    - Do not mention artist names, brand names, or copyrighted characters.
    - Example: a photo of a black cat, sitting on a red couch, in a dimly lit room, high quality.
""").strip()

class PromptCrafter_Captioner:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vision_model": (get_vision_models(), {"dynamic": True, "tooltip": "The vision language model (VLM) to use for captioning."}),
            },
            "optional": {
                # --- Single Image Mode ---
                "image": ("IMAGE", {"tooltip": "The image to be captioned (for single mode)."}),
                "filename": ("STRING", {"default": "", "tooltip": "Filename for single mode (ignored in batch mode). If empty, a timestamp is used."}),
                # --- Batch Mode ---
                "batch_mode": ("BOOLEAN", {"default": False, "tooltip": "Enable batch processing of an entire folder."}),
                "input_folder": ("STRING", {"default": "input/captions_todo", "tooltip": "Directory of images to process in batch mode (relative to ComfyUI root)."}),
                "skip_existing": ("BOOLEAN", {"default": True, "tooltip": "In batch mode, skip images that already have a corresponding .txt caption file."}),
                "max_workers": ("INT", {"default": 4, "min": 1, "max": 16, "step": 1, "tooltip": "Number of parallel threads for batch processing."}),
                "api_concurrency": ("INT", {"default": 5, "min": 1, "max": 16, "step": 1, "tooltip": "Max concurrent API requests for remote models (OpenAI, Anthropic, etc.) to avoid rate limiting."}),
                # --- Caption Content & Style ---
                "caption_prompt": ("STRING", {"multiline": True, "default": DEFAULT_CAPTION_PROMPT, "tooltip": "The prompt template used to guide the captioning model."}),                
                "caption_prefix": ("STRING", {"multiline": False, "default": "", "tooltip": "A single trigger word to add to every caption. Overridden by the trigger words file."}),
                "trigger_words_folder_path": ("STRING", {"multiline": False, "default": "input", "tooltip": "Folder containing an optional file of trigger words (one per line)."}),
                "trigger_words_file": ("STRING", {"multiline": False, "default": "<none>", "tooltip": "File with a list of trigger words to be randomly chosen from for each caption."}),
                # --- File Output ---
                "save_caption": ("BOOLEAN", {"default": True, "tooltip": "Save the caption to a text file."}),                
                "output_path": ("STRING", {"default": "captions", "tooltip": "Subdirectory within ComfyUI/output to save caption files."}),
                # --- Generation Control & Behavior ---
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
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter (v{__version__})"
    HELP = {
        "title": "PromptCrafter Image Captioner",
        "description": (
            "A powerful, dual-mode node for generating image captions.\n\n"
            "**Default Mode (Single Image):**\nSimply connect an image to the `image` input to get a caption. This is ideal for quick, one-off captioning tasks within a workflow.\n\n"
            "**Batch Mode:**\nEnable `batch_mode` to process an entire folder of images, making it perfect for creating training datasets (e.g., for LoRAs). In this mode, it saves a `.txt` caption file for each image."
        ),
        "reset": True,
    }
    DESCRIPTION = HELP["description"]

    def reset_defaults(self, **kwargs):
        """Called when user presses Reset in the help panel"""
        return {
            "temperature": 0.2,
            "seed": -1,
            "use_chat_api": False,
            "caption_prompt": DEFAULT_CAPTION_PROMPT,
        }

    def _caption_one_image(self, image_tensor, model, final_caption_prompt, use_chat_api, temperature, seed, debug_mode, timeout):
        """Helper function to run the captioning query for a single image tensor."""
        is_api_model = "/" in model
        # The input could be a batch of 1, so we take the first item.
        first_image = image_tensor[0] if torch.is_tensor(image_tensor) and image_tensor.ndim == 4 else image_tensor

        ok, caption = query_model_auto(model, prompt=final_caption_prompt, images=[first_image], prefer_chat=(use_chat_api or is_api_model), temperature=temperature, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title="Image Caption Prompt")
        
        if not ok:
            return False, "Model error: {caption}".format(caption=caption)
        
        return True, TextCleaner.single_paragraph(caption)

    def _process_single_batch_item(self, img_filename, full_folder_path, out_dir, skip_existing, model, final_caption_prompt, use_chat_api, temperature, seed, debug_mode, caption_prefix, trigger_words, save_caption, timeout, semaphore):
        """Processes a single image in a batch job. Designed to be run in a separate thread."""
        try:
            base_fname, _ = os.path.splitext(img_filename)
            caption_filepath = os.path.join(out_dir, f"{base_fname}.txt")
            if skip_existing and os.path.exists(caption_filepath):
                return "skipped", img_filename

            img_path = os.path.join(full_folder_path, img_filename)
            pil_image = Image.open(img_path).convert("RGB")
            image_tensor = comfy.utils.pil2tensor(pil_image)
            
            # Acquire semaphore before making the network call
            if semaphore:
                semaphore.acquire()
            try:
                ok, caption_text = self._caption_one_image(image_tensor, model, final_caption_prompt, use_chat_api, temperature, seed, debug_mode, timeout)
            finally:
                # Always release the semaphore
                if semaphore:
                    semaphore.release()
            
            if not ok:
                return "failed", f"Failed to caption {img_filename}: {caption_text}"

            final_caption = caption_text
            current_prefix = caption_prefix
            if trigger_words:
                current_prefix = random.choice(trigger_words)
            if current_prefix:
                final_caption = f"{current_prefix.strip()}, {final_caption}"

            if save_caption:
                with open(caption_filepath, "w", encoding="utf-8") as f:
                    f.write(final_caption)
            
            return "success", img_filename
        except Exception as e:
            return "failed", f"Error processing {img_filename}: {e}"

    def execute(self, vision_model, image=None, batch_mode=False, input_folder=None, skip_existing=True, max_workers=4, api_concurrency=5, caption_prompt=DEFAULT_CAPTION_PROMPT, caption_prefix="", trigger_words_folder_path="input", trigger_words_file="<none>", save_caption=True, output_path="captions", filename="", temperature=0.2, debug_mode=False, safe_mode=True, seed=-1, use_chat_api=False, timeout=120):
        model = vision_model or FALLBACK_VISION_MODEL
        final_caption_prompt = caption_prompt
        if safe_mode and SAFE_MODE_RULE not in final_caption_prompt:
            final_caption_prompt = "{prompt}\n{rule}".format(prompt=final_caption_prompt, rule=SAFE_MODE_RULE)

        # --- Load Trigger Words ---
        trigger_words = []
        if trigger_words_folder_path and trigger_words_file and trigger_words_file != "<none>":
            full_folder_path = trigger_words_folder_path
            if not os.path.isabs(full_folder_path):
                full_folder_path = os.path.join(COMFYUI_ROOT_DIR, full_folder_path)
            fpath = os.path.join(full_folder_path, trigger_words_file)
            if os.path.exists(fpath):
                content = safe_read(fpath)
                if not content.startswith("[Error"):
                    trigger_words = [line.strip() for line in content.splitlines() if line.strip()]
                    if trigger_words:
                        print("\033[92m[PromptCrafter] Loaded {count} trigger words from {file}.\033[0m".format(count=len(trigger_words), file=trigger_words_file))
            else:
                # This isn't a critical error, just a warning.
                print("\033[93m[PromptCrafter] Warning: Trigger words file not found at '{path}'.\033[0m".format(path=fpath))

        # --- BATCH MODE ---
        if batch_mode:
            if not input_folder:
                return ("Batch mode is enabled, but no input folder was provided.",)

            full_folder_path = input_folder
            if not os.path.isabs(full_folder_path):
                full_folder_path = os.path.join(COMFYUI_ROOT_DIR, full_folder_path)
            
            if not os.path.isdir(full_folder_path):
                return ("Input folder not found: {path}".format(path=full_folder_path),)

            image_files = [f for f in os.listdir(full_folder_path) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.bmp'))]
            if not image_files:
                return ("No images found in {path}".format(path=full_folder_path),)

            # Prepare output directory
            base_dir = os.path.join(COMFYUI_ROOT_DIR, "output")
            safe_subdir = os.path.normpath(output_path.strip()).lstrip('.').lstrip('/')
            out_dir = os.path.join(base_dir, safe_subdir)
            os.makedirs(out_dir, exist_ok=True)

            # Create a semaphore to limit concurrency for remote API calls
            is_remote_api = "/" in model
            semaphore = None
            if is_remote_api:
                semaphore = threading.Semaphore(api_concurrency)
                print(f"\033[94m[PromptCrafter] Remote API detected. Limiting concurrent requests to {api_concurrency}.\033[0m")

            processed_count = 0
            skipped_count = 0
            failed_count = 0
            failed_files = []

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Prepare futures for all images to be processed
                futures = {
                    executor.submit(
                        self._process_single_batch_item,
                        img_filename, full_folder_path, out_dir, skip_existing, model,
                        final_caption_prompt, use_chat_api, temperature, seed, debug_mode,
                        caption_prefix, trigger_words, save_caption, timeout, semaphore
                    ): img_filename for img_filename in image_files
                }

                # Process results as they complete for real-time feedback
                for future in concurrent.futures.as_completed(futures):
                    img_filename = futures[future]
                    try:
                        status, result_or_filename = future.result()
                        if status == "success":
                            processed_count += 1
                            print(f"\033[92m[PromptCrafter] Captioned: {result_or_filename}\033[0m")
                        elif status == "skipped":
                            skipped_count += 1
                        elif status == "failed":
                            failed_count += 1
                            failed_files.append(img_filename)
                            print(f"\033[93m[PromptCrafter] Warning: {result_or_filename}\033[0m")
                    except Exception as e:
                        failed_count += 1
                        failed_files.append(img_filename)
                        print(f"\033[91m[PromptCrafter] An unexpected error occurred for {img_filename}: {e}\033[0m")

            total_images = len(image_files)
            status_message = "Batch complete. Total: {total}. Captioned: {processed}.".format(
                total=total_images,
                processed=processed_count
            )
            if failed_count > 0:
                # To avoid a huge string in the UI, show the first few failed files and summarize the rest.
                failed_files_str = ", ".join(failed_files[:5])
                if failed_count > 5:
                    failed_files_str += f", and {failed_count - 5} more"
                status_message += f" Failed: {failed_count} ({failed_files_str}). Check console for details."
            else:
                status_message += " Failed: 0."

            if skipped_count > 0:
                status_message += " Skipped: {skipped}.".format(skipped=skipped_count)
            return (status_message,)

        # --- SINGLE IMAGE MODE ---
        else:
            if image is None:
                return ("No image provided for single captioning mode.",)

            ok, caption = self._caption_one_image(image, model, final_caption_prompt, use_chat_api, temperature, seed, debug_mode, timeout)
            if not ok:
                return (caption,)

            final_caption = caption

            current_prefix = caption_prefix
            if trigger_words:
                current_prefix = random.choice(trigger_words)
            if current_prefix:
                final_caption = "{prefix}, {caption}".format(prefix=current_prefix.strip(), caption=final_caption)

            if save_caption:
                base_dir = os.path.join(COMFYUI_ROOT_DIR, "output")
                safe_subdir = os.path.normpath(output_path.strip()).lstrip('.').lstrip('/')
                out_dir = os.path.join(base_dir, safe_subdir)
                os.makedirs(out_dir, exist_ok=True)
                fname = filename.strip() or "caption_{ts}_{ms}".format(ts=time.strftime('%Y%m%d_%H%M%S'), ms=int(time.time()*1000)%1000)
                fname = re.sub(r'[\\/*?:"<>|]', "", fname)
                with open(os.path.join(out_dir, f"{fname}.txt"), "w", encoding="utf-8") as f:
                    f.write(final_caption)
            
            return (final_caption,)

# ------------------------------------------------------------------------------------
# PromptCrafter Creator Nodes (Image / Video / Lyrics)
# ------------------------------------------------------------------------------------

"""
This section contains the core "creator" nodes of the PromptCrafter suite. These nodes
(ImageCreator, VideoCreator, LyricsCreator) share a common base class, `PromptCrafter_BaseCreator`,
and are designed to perform complex analysis of user instructions and reference images
to generate highly polished, cinematic prompts tailored to their specific output mode.
"""
class PromptCrafter_BaseCreator:
    """A base class containing shared logic for visual prompt creation nodes."""

    def _collect_images_with_weights(self, image_count=1, image_weights_json="{}", **kwargs):
        """Collects all connected image tensors and their weights from the dynamic inputs."""
        images_with_weights = []
        weights = {}
        try:
            # Load weights from the JSON string provided by the frontend
            weights = json.loads(image_weights_json)
        except (json.JSONDecodeError, TypeError):
            # Fallback if JSON is invalid or not a string
            print(f"\033[93m[PromptCrafter] Warning: Could not parse image_weights_json. Using default weights. Value: {image_weights_json}\033[0m")

        for i in range(1, image_count + 1): # Check up to the user-specified image_count
            image = kwargs.get(f"image_{i}")
            if image is not None:
                # Get weight from the parsed JSON, falling back to 1.0 if not found
                # Ensure the value is a float, as JSON will parse it as int/float.
                weight = float(weights.get(f"image_weight_{i}", 1.0))
                images_with_weights.append((image, weight))
        return images_with_weights

    def _prepare_run_parameters(self, prompt_type, temperature, use_chat_api, max_length_words, original_temp, original_max_len):
        """
        Sets mode-specific defaults for key execution parameters.
        This function provides a better user experience by automatically applying sensible
        defaults for temperature, chat API usage, and word count based on the selected
        prompt type (Image, Video, or Lyrics).

        Crucially, it only applies these defaults if the user has NOT manually changed
        the corresponding setting from its original default value. This allows users to
        override the automatic settings whenever they need more specific control.
        """
        # --- 1. Get Original Default Values ---
        # We fetch the original default values directly from the INPUT_TYPES definition.
        # This is the source of truth for what the "default" state of the node is.
        # By comparing the user's current input against these original defaults, we can
        # determine if the user has intentionally changed a value or if it's still at
        # its initial state. This is key to the "smart default" logic, as we only
        # want to override parameters that the user hasn't explicitly set.

        # --- 2. Set Mode-Specific Temperature and Chat API Usage ---
        # If the user has not changed the temperature from its default, we apply a
        # mode-specific value. Video and Lyrics modes often benefit from slightly higher
        # creativity (higher temperature) to generate more narrative and dynamic prompts.
        # They also tend to work better with models fine-tuned for chat, so we enable
        # `use_chat_api` for them by default. Image mode, by contrast, benefits from
        # a more stable, lower temperature for precise descriptions.
        if temperature == original_temp:
            if prompt_type == "Video":
                temperature, use_chat_api = 0.4, True

        # --- 3. Set Mode-Specific Word Count ---
        # If the user has left the max_length_words at its default (0, which means 'auto'),
        # we set a specific word count target appropriate for each mode. These values are
        # chosen based on typical use cases:
        # - Image prompts can be longer and more descriptive.
        # - Video prompts need to be concise to focus on motion and action (user feedback driven change).
        # - Lyrics prompts are generated per-segment and need to be compact.
        # If the user sets this to any non-zero value, their choice is respected.
        if max_length_words == original_max_len:
            if prompt_type == "Image":
                max_length_words = 200
            elif prompt_type == "Video":
                max_length_words = 80
            elif prompt_type == "Lyrics":
                max_length_words = 100
        
        return temperature, use_chat_api, max_length_words

    def _refine_image_video_prompt(self, draft_prompt, mode, mandatory_tokens, style_rules, config):
        """
        Performs a multi-step refinement on a draft prompt for Image or Video modes.
        This function is a key part of the quality control pipeline. It has been refactored
        to be more efficient by combining the refinement and validation steps into a
        single API call per iteration, reducing the total number of calls by up to 50%.

        The process is as follows:
        1.  **Iterative Loop**: The function loops up to a maximum number of retries to
            give the model multiple chances to get it right.
        2.  **Combined Refinement & Validation Prompt**: In each loop, it builds a single
            prompt that asks the AI to act as a master editor. This prompt instructs the
            model to both **revise** the draft and **self-validate** that the new version
            includes all mandatory subjects.
        3.  **Single API Call**: The model returns a JSON object containing the `refined_prompt`
            and a list of any `missing_items`. This combines two steps into one API call.
        4.  **Exit or Retry**: If the `missing_items` list is empty, the loop exits. If not,
            the newly revised prompt becomes the draft for the next iteration.
        """
        current_prompt = draft_prompt
        # This list contains subjects the user explicitly requested and are non-negotiable.
        primary_items_list = [re.sub(r'^\[PRIMARY\]\s*', '', t) for t in (mandatory_tokens or {}).get("primary", [])]
        
        # If there are no mandatory items, a single, simpler refinement pass is sufficient.
        if not primary_items_list:
            critique_prompt = self._build_refinement_prompt(current_prompt, mode, [], [], style_rules, config, ask_for_json=False)
            ok, revised_prompt = query_model_auto(config.model, critique_prompt, prefer_chat=config.use_chat_api, temperature=config.temperature, seed=config.seed, timeout=90, debug_mode=config.debug_mode, debug_title="Image/Video Refine (Single Pass)")
            return TextCleaner.single_paragraph(revised_prompt) if ok else current_prompt

        # --- Anti-Hallucination Step 1: Define the "Universe" of Allowed Subjects ---
        # `all_allowed` is a comprehensive list of every subject identified from both the user's
        # text and the reference images. By providing this list to the model and instructing it
        # to ONLY use subjects from it, we create a "closed world" that prevents the AI from
        # inventing (hallucinating) new, unwanted elements like extra characters or objects.
        all_allowed = (mandatory_tokens or {}).get("allowed_list", [])

        for i in range(config.max_retries + 1):
            # Build the prompt that asks the model to refine and self-validate in one step.
            critique_prompt = self._build_refinement_prompt(current_prompt, mode, primary_items_list, all_allowed, style_rules, config, ask_for_json=True)

            # Execute the single, combined query.
            reason_kwargs = {
                "use_chat_api": config.use_chat_api, "temperature": config.temperature,
                "seed": config.seed, "timeout": 90, "debug_mode": config.debug_mode,
                "debug_title": f"Image/Video Refine & Check (Try {i+1})"
            }
            reason_kwargs.pop('model', None) # Remove model from kwargs to avoid conflict
            ok, result_json = _reason_with_model(config.model, critique_prompt, **reason_kwargs)

            if not ok or not isinstance(result_json, dict):
                print(f"\033[93m[PromptCrafter] Warning: Refinement step failed to return valid JSON. Using previous version. Error: {result_json}\033[0m")
                return current_prompt # Fallback to the last known good prompt

            # Update the current prompt with the refined version from the JSON.
            current_prompt = TextCleaner.single_paragraph(result_json.get("refined_prompt", current_prompt))
            missing_items = result_json.get("missing_items", ["*validation failed*"])
            hallucinated_items = result_json.get("hallucinated_items", ["*validation failed*"])

            # If the model reports that no items are missing AND no items were hallucinated, we're done.
            if not missing_items and not hallucinated_items:
                return current_prompt

        # If the loop finishes without success, return the last attempt as a fallback.
        return current_prompt

    def _build_refinement_prompt(self, prompt_to_review, mode, primary_items, all_allowed_items, style_rules, config, ask_for_json=True):
        """Builds the detailed prompt for the image/video refinement step."""
        mode_specific_rule = ""
        if mode == "Image":
            mode_specific_rule = "- The prompt must describe a single, static frame. Remove any video-like transition phrases (e.g., 'then', 'the scene shifts') or motion verbs."
        
        strength = config.critique_strength
        if strength == "Subtle":
            critique_instruction = "- Subtly refine the DRAFT PROMPT. Focus on improving wording, flow, and clarity. Do NOT make major structural changes or add new concepts. The core description should remain the same."
        elif strength == "Heavy":
            critique_instruction = "- Radically revise the DRAFT PROMPT for maximum cinematic impact. You have creative freedom to restructure the scene, change the composition, and add descriptive flair, as long as you adhere to all MANDATORY SUBJECTS and rules. Be bold in your edit."
        else: # Normal
            critique_instruction = "- Revise the DRAFT PROMPT to meet ALL of the requirements listed above.\n- Integrate mandatory subjects naturally.\n- Remove any hallucinated subjects not in the allowed list.\n- Apply all style and mode-specific rules.\n- Enhance the prompt for cinematic quality, clarity, and impact."

        # Define the two different response formats
        json_return_format = textwrap.dedent("""
            INSTRUCTIONS:
            1.  **Revise**: Revise the DRAFT PROMPT to meet ALL of the requirements listed above.
            2.  **Validate**: After revising, perform two checks:
                - Does the new prompt contain all **MANDATORY SUBJECTS**?
                - Does the new prompt contain any subjects that were NOT in the **ALLOWED SUBJECTS** list?
            3.  **Return JSON**: Return ONLY a single JSON object with three keys:
                - `refined_prompt`: (string) The improved version of the prompt.
                - `missing_items`: (array of strings) A list of any **MANDATORY SUBJECTS** that are still missing. Should be `[]` on success.
                - `hallucinated_items`: (array of strings) A list of any subjects you included that were NOT in the original **ALLOWED SUBJECTS** list. Should be `[]` on success.
        """)
        text_return_format = f"INSTRUCTIONS:\n{critique_instruction}\n\nReturn ONLY the final, improved prompt. No commentary."

        # Choose the format based on the flag
        final_instructions = json_return_format if ask_for_json else text_return_format

        refine_template = textwrap.dedent("""
            You are a master prompt critic and editor. Your task is to review and enhance the following DRAFT PROMPT.

            --- DRAFT PROMPT ---
            {prompt_to_review}
            --- END DRAFT PROMPT ---

            --- REQUIREMENTS & RULES ---
            1.  **MANDATORY SUBJECTS (CRITICAL):** The final prompt MUST include all of the following subjects: {subjects}
            2.  **ALLOWED SUBJECTS (Anti-Hallucination):** The prompt should ONLY contain subjects from this list. If the draft contains subjects not on this list, REMOVE them or replace them with a generic equivalent from the list. Allowed list: {allowed_list}
            3.  **MODE-SPECIFIC RULES:**
                - The final prompt is for an '{mode}' generation.
                {mode_specific_rule}
            4.  **GENERAL STYLE & COMPOSITION RULES:**
            {rules}
            --- END REQUIREMENTS & RULES ---

            {instructions}
        """)

        if not primary_items:
            refine_template = refine_template.replace("1.  **MANDATORY SUBJECTS (CRITICAL):** The final prompt MUST include all of the following subjects: {subjects}\n", "")
        if not all_allowed_items:
             refine_template = refine_template.replace("2.  **ALLOWED SUBJECTS (Anti-Hallucination):** The prompt should ONLY contain subjects from this list. If the draft contains subjects not on this list, REMOVE them or replace them with a generic equivalent from the list. Allowed list: {allowed_list}\n", "")

        return refine_template.format(
            prompt_to_review=prompt_to_review,
            subjects=json.dumps(primary_items) if primary_items else "None",
            allowed_list=json.dumps(all_allowed_items) if all_allowed_items else "Any",
            mode=mode,
            mode_specific_rule=mode_specific_rule,
            rules="\n".join(style_rules),
            instructions=final_instructions
        )

    def _build_image_description_prompt(self, persona, idx, language, safe_mode):
        """Builds the prompt for describing a single image."""
        safety_rule = "\n{0}".format(SAFE_MODE_RULE) if safe_mode else ""
        desc_template = textwrap.dedent("""
            {persona_text}
            Analyze Image {idx} and provide a detailed, one-paragraph description and identify the single primary subject.

            Your task is to:
            1.  Identify the single most important subject (the focal point).
            2.  Describe the full scene, including the primary subject, secondary subjects, setting, and artistic style.
            3.  If there is any readable text, transcribe it exactly.

            Return ONLY a JSON object with two keys:
            - "primary_subject": (string) The single most important subject in the image (e.g., "a majestic stag", "a woman in an elegant dress").
            - "description": (string) The full, one-paragraph description of the entire scene.

            The final output must be in {language} only.{safety}
        """)
        return desc_template.format(
            persona_text=persona, idx=idx, language=language, safety=safety_rule
        ).strip()

    def _describe_one_image_with_persona(self, img, weight, idx, config):
        """
        Generates a detailed, persona-driven description for a single image.
        This helper function encapsulates the logic for analyzing an image's style,
        selecting an appropriate expert persona, and querying the model for a description.
        """
        # --- 1. Dynamic Persona Selection ---
        # The StyleEngine provides an expert "persona" tailored to the image content,
        # leading to richer, more specific descriptions.
        style_engine = StyleEngine(
            config.model, config.use_chat_api, config.temperature, config.seed,
            image=img, debug_mode=config.debug_mode, timeout=config.timeout
        )
        persona = style_engine.get_persona()

        # --- 2. Build and Execute Description Prompt ---
        desc_prompt = self._build_image_description_prompt(persona, idx, config.language, config.safe_mode)
        reason_kwargs = {
            "use_chat_api": config.use_chat_api, "temperature": config.temperature,
            "seed": config.seed, "timeout": config.timeout, "debug_mode": config.debug_mode,
            "debug_title": f"Image Description {idx}"
        }
        ok, result_json = _reason_with_model(config.model, desc_prompt, images=[img], **reason_kwargs)

        # --- 3. Format and Return Result ---
        if ok and isinstance(result_json, dict):
            desc_text = TextCleaner.single_paragraph(result_json.get("description", ""))
            primary_subject = result_json.get("primary_subject", "")
            return {
                "full_text": f"Image {idx} (Weight: {weight:.2f}): {desc_text}",
                "primary_subject": primary_subject
            }
        else:
            # Fallback for safety if JSON parsing fails
            return {
                "full_text": f"Image {idx} (Weight: {weight:.2f}): [Error describing image: {result_json}]",
                "primary_subject": ""
            }

    def _describe_images(self, images_with_weights, config):
        """
        Generates detailed text descriptions for a list of reference images. This function
        is a cornerstone of the prompt generation process, turning visual input into
        textual context that the AI can understand.
        """
        if not images_with_weights:
            return "No reference images provided.", []

        # --- Caching Logic ---
        images = [img for img, _ in images_with_weights]
        weights = [w for _, w in images_with_weights]
        cache_key = _get_cache_key(images, weights, config.model, config.use_chat_api, config.temperature, config.language, config.safe_mode, config.seed, "describe_images_v3")
        if CACHE.has(cache_key):
            print("\033[94m[PromptCrafter] Using cached image descriptions and primary subjects.\033[0m")
            return CACHE.get(cache_key)

        description_objects = []
        for idx, (img, weight) in enumerate(images_with_weights, start=1):
            if weight <= 0:  # Skip images with zero or negative weight
                continue
            description_objects.append(self._describe_one_image_with_persona(img, weight, idx, config))
        
        # Separate the full text for the prompt from the primary subjects
        full_text_descriptions = [d.get("full_text", "") for d in description_objects]
        primary_subjects = [d.get("primary_subject", "") for d in description_objects if d.get("primary_subject")]
        
        result_text = "\n\n".join(full_text_descriptions)
        result_tuple = (result_text, primary_subjects)
        CACHE.set(cache_key, result_tuple) # Store the final result in the cache for next time.
        return result_tuple

    def _simplify_for_diffusion(self, prompt_text, user_text, config):
        """
        Uses an LLM to simplify a complex, narrative prompt into a more direct,
        clause-based prompt that is easier for diffusion models to interpret. This version
        is highly aggressive, using the user's original text to force heavy weighting on
        critical attributes and generate counter-negatives.
        """
        if not prompt_text or not config.simplify_for_diffusion:
            return prompt_text, ""

        cache_key = _get_cache_key(prompt_text, user_text, config.model, "simplify_v3_aggressive")
        if CACHE.has(cache_key):
            cached_data = CACHE.get(cache_key)
            return cached_data.get("positive_prompt", prompt_text), cached_data.get("negative_keywords", "")

        simplification_template = textwrap.dedent("""
            You are an expert in Stable Diffusion prompting. Your task is to restructure a narrative prompt into a highly effective, direct prompt, ensuring absolute adherence to the user's core request.

            **Analysis & Restructuring Steps:**

            **Part 1: Positive Prompt Generation**
            1.  **Analyze Core Request:** The `USER'S CORE REQUEST` is the source of truth. Identify the most critical, non-negotiable subjects, attributes (e.g., hair color, clothing), and actions.
            2.  **Structure for Complex Scenes:** If there are multiple subjects, describe their interactions and spatial relationships (e.g., "a knight standing in front of a dragon," "a cat sleeping on a couch").
            3.  **Prioritize and Weight:** Create a new prompt starting with the main subject. Use HEAVY weighting like `(description:1.5)` on the most critical attributes from step 1 to FORCE the model's attention. For example, if the user demands a "white dress," the output must contain `(white dress:1.5)`.
            4.  **Clarify and Synthesize:** Rephrase the rest of the prompt into clear, comma-separated clauses. Remove narrative fluff. Synthesize contradictory environments into a single, plausible scene (e.g., 'a grassy clifftop meadow overlooking the ocean').

            **Part 2: Negative Prompt Generation**
            5.  **Extract Negative Constraints:** Analyze the `USER'S CORE REQUEST` for explicit negative instructions (e.g., "no buildings," "without people"). Add these directly to the negative keywords.
            6.  **Generate Counter-Negatives:** Based on the core positive attributes, identify their direct opposites. For example, if "white dress" is requested, a counter-negative is "black dress, dark dress". If "blonde hair" is requested, counter-negatives are "brunette, dark hair".

            --- USER'S CORE REQUEST (Source of Truth) ---
            {user_request}
            --- END USER'S CORE REQUEST ---

            --- NARRATIVE PROMPT (to be restructured) ---
            {prompt}
            --- END NARRATIVE PROMPT ---

            Return ONLY a JSON object with two keys:
            - `positive_prompt`: (string) The simplified, restructured, and heavily weighted positive prompt.
            - `negative_keywords`: (string) A comma-separated string of all negative keywords from steps 5 and 6.
        """)
        
        simplify_prompt = simplification_template.format(user_request=user_text, prompt=prompt_text)
        
        ok, result_json = query_model_auto(config.model, simplify_prompt, prefer_chat=config.use_chat_api, temperature=0.1, seed=config.seed, timeout=90, debug_mode=config.debug_mode, debug_title="Simplify for Diffusion Model (Aggressive)")

        if ok and isinstance(result_json, dict):
            positive = TextCleaner.single_paragraph(result_json.get("positive_prompt", prompt_text))
            negatives = result_json.get("negative_keywords", "")
            CACHE.set(cache_key, {"positive_prompt": positive, "negative_keywords": negatives})
            return positive, negatives
        
        # Fallback if the JSON fails
        return prompt_text, ""

    # ---------------------------------------------------------------------
    # IMAGE / VIDEO MODE with token coverage + anti-hallucination
    # ---------------------------------------------------------------------
    def _prepare_visual_prompt_context(self, user_text, images_with_weights, config):
        """Generates and parses all text-based context for visual prompt generation."""
        # Generate text context and extract primary subjects from reference images.
        image_context, primary_subjects_from_images = self._describe_images(images_with_weights, config)

        # The AI-based split into 'instructions' and 'context' was unreliable and
        # could cause important details to be de-prioritized. By treating the entire
        # user_text as the core instruction, we ensure all user requests are
        # treated with the highest priority.
        user_instructions = user_text
        user_context = ""

        # Extract mandatory and optional subjects from all context.
        tok_ok, tokens_or_msg = _extract_mandatory_tokens_with_model(image_context, user_text, config)
        mandatory_tokens = tokens_or_msg if tok_ok else {"primary": [], "secondary": [], "allowed_list": []}

        return True, (image_context, user_instructions, user_context, mandatory_tokens, primary_subjects_from_images)

    def _generate_initial_draft(self, mode, user_instructions, user_context, image_context, mandatory_tokens, images, config, primary_subjects_from_images=None):
        """Builds the initial prompt and generates the first draft from the model."""
        merge_prompt = self._build_initial_merge_prompt(mode, user_instructions, user_context, image_context, mandatory_tokens, images, config, primary_subjects_from_images)

        generation_kwargs = {
            "prefer_chat": config.use_chat_api,
            "temperature": config.temperature,
            "seed": config.seed,
            "timeout": 120,
            "debug_mode": config.debug_mode,
        }

        if config.use_deep_think:
            print("\033[94m[PromptCrafter] Deep Think enabled. Starting iterative refinement...\033[0m")
            generation_kwargs["debug_title"] = f"Initial {mode} Prompt (Deep Think)"
            generation_kwargs["images"] = images # Pass images to the deep think process
            ok, scene_prompt = _deep_think_and_refine( # The main generation prompt is now called generation_prompt_text
                config.model, merge_prompt, max_iterations=3, confidence_threshold=config.deep_think_confidence, **generation_kwargs
            )
        else:
            generation_kwargs["debug_title"] = f"Initial {mode} Prompt"
            ok, scene_prompt = query_model_auto(config.model, merge_prompt, **generation_kwargs)

        if not ok:
            return False, f"Ollama error: {scene_prompt}"
        
        return True, TextCleaner.single_paragraph(scene_prompt)

    def _finalize_visual_prompt_output(self, scene_prompt, image_context, user_text, mandatory_tokens, config, save_to_txt, filename_prefix, user_negative_prompt=""):
        """Generates the negative prompt and saves the final output to a file if requested."""
        final_negative_prompt = self._generate_negative_prompt(scene_prompt, config, user_negative_prompt=user_negative_prompt)

        if save_to_txt and scene_prompt and scene_prompt.strip():
            sections = [("IMAGE CONTEXT", image_context)]
            if user_text and user_text.strip() and user_text.strip() != DEFAULT_PROMPT_TEXT:
                sections.append(("USER TEXT", user_text))
            if mandatory_tokens:
                all_tokens = mandatory_tokens.get("primary", []) + mandatory_tokens.get("secondary", [])
                if all_tokens:
                    sections.append(("EXTRACTED TOKENS", "\n".join(all_tokens)))
            sections.append(("NEGATIVE PROMPT", final_negative_prompt))
            sections.append(("SCENE PROMPT", scene_prompt))
            
            self._save_output_to_file(filename_prefix, sections, base_filename="scene_prompt")

        return final_negative_prompt

    def _generate_visual_prompt_pipeline(self, mode, user_text, images_with_weights, save_to_txt, filename_prefix, config, negative_prompt="", **kwargs):
        """
        A shared pipeline for generating prompts in "Image" and "Video" modes.
        This function acts as a high-level controller, calling helper methods for each step.
        """
        # --- Step 1: Initial Validation ---
        images = [img for img, _ in images_with_weights]
        has_text = user_text and user_text.strip() and user_text.strip() != DEFAULT_PROMPT_TEXT
        if not images and not kwargs.get("style_reference_image") and not has_text:
            return ("No inputs provided. Please connect at least one main image, a style reference image, or provide user text.", "", "")
            
        # --- Step 2: Prepare All Generation Context ---
        ok_context, context_data = self._prepare_visual_prompt_context(user_text, images_with_weights, config)
        if not ok_context:
            return (context_data[0], "", "") # context_data[0] contains the error message
        image_context, user_instructions, user_context, mandatory_tokens, primary_subjects_from_images = context_data

        # --- Step 3: Generate Initial Draft ---
        ok_draft, draft_or_err = self._generate_initial_draft(mode, user_instructions, user_context, image_context, mandatory_tokens, images, config, primary_subjects_from_images)
        if not ok_draft:
            return (draft_or_err, image_context, "")
        scene_prompt = draft_or_err

        # --- Step 4: Refine the Draft ---
        style_rules = self._build_style_and_composition_rules(mode, images, config, user_instructions, user_context, image_context)
        scene_prompt = self._refine_image_video_prompt(scene_prompt, mode, mandatory_tokens, style_rules, config)
        
        # --- Step 4.5: Simplify for Diffusion Model ---
        new_positive, counter_negatives = self._simplify_for_diffusion(scene_prompt, user_text, config)
        scene_prompt = new_positive

        # --- Step 5: Finalize Output ---
        # Combine the user's negative prompt with the new counter-negatives
        combined_negative_input = f"{negative_prompt}, {counter_negatives}".strip().strip(',')

        final_negative_prompt = self._finalize_visual_prompt_output(
            scene_prompt, image_context, user_text, mandatory_tokens, config,
            save_to_txt, filename_prefix, user_negative_prompt=combined_negative_input
        )

        return (scene_prompt, image_context, final_negative_prompt)

    def _get_base_composition_rules(self, language):
        """Returns the static list of base composition rules for image/video prompts."""
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

    def _get_video_specific_rules(self, config, user_instructions="", user_context="", image_context=""):
        """
        Returns the list of rules specific to Wan2.2 video generation. This function
        is now context-aware, using an LLM to analyze the user's input to determine whether the
        required motion should be dynamic and action-oriented or subtle and natural.
        """
        # --- AI-Powered Motion & Camera Analysis ---
        motion_analysis_prompt = textwrap.dedent(f"""
            You are an expert film director. Analyze the provided scene context and choose the most appropriate motion style and a specific camera movement for a video prompt.

            --- SCENE CONTEXT ---
            User Instructions: {user_instructions}
            Image Descriptions: {image_context}
            --- END SCENE CONTEXT ---

            Part 1: Choose ONE motion style from the following list that best fits the overall mood and action:
            - "subtle, natural": For calm, still scenes (e.g., gentle breeze).
            - "smooth, flowing": For graceful, continuous movements (e.g., dancing, walking).
            - "dynamic, cinematic": For energetic, purposeful actions (e.g., running, dramatic gestures).
            - "intense, action-packed": For high-energy, chaotic scenes (e.g., battles, chases).

            Part 2: Based on your choice, suggest ONE specific camera movement from this list:
            - "static shot", "slow pan left", "slow pan right", "tilt up", "tilt down", "dolly zoom", "tracking shot", "handheld shaky cam", "crane shot".

            Return ONLY a JSON object with your choices.
            Example: {{"motion_style": "dynamic, cinematic", "camera_movement": "tracking shot"}}
        """).strip()

        ok, result_json = _reason_with_model(
            config.model, motion_analysis_prompt, config.use_chat_api, 0.1, config.seed,
            debug_mode=config.debug_mode, debug_title="Video Motion Style Analysis"
        )

        motion_type_adjective = "subtle, natural"  # Default value
        camera_movement_suggestion = "static shot" # Default value
        if ok and isinstance(result_json, dict):
            motion_type_adjective = result_json.get("motion_style", motion_type_adjective)
            camera_movement_suggestion = result_json.get("camera_movement", camera_movement_suggestion)

        # Provide a relevant example based on the chosen style
        if "intense" in motion_type_adjective:
            motion_example = "e.g., 'a warrior lunging forward, sword gleaming as it cuts through the air, sparks flying on impact'"
        else:
            motion_example = "e.g., 'a person standing still, their coat gently billowing in the wind, cherry blossom petals drifting past'"

        # Construct the final, context-aware motion instruction. This is a critical part of guiding the AI
        # to generate a video prompt that matches the user's intent for movement.
        motion_instruction = (
            f"- CRITICAL PRIORITY: Emphasize the subject's ACTIONS and the PHYSICS of their movement. The motion should be {motion_type_adjective}. "
            f"Describe the motion with active verbs and adverbs ({motion_example}). This detail is essential for generating faithful video movement."
        )

        camera_instruction = f"- Suggestion for Camera: Incorporate a '{camera_movement_suggestion}' to enhance the '{motion_type_adjective}' feel of the scene."

        return [
            "- Role: Expert Wan2.2 video prompt generator.",
            "- Use Wan2.2 formula: [Cinematic Shot] + [Primary Subject & Detailed Description] + [Scene & Environment] + [Detailed Action & Physics-Based Motion] + [Camera Movement & Angle] + [Visual Style & Aesthetic Controls] + [Atmosphere & Mood].",
            motion_instruction,
            camera_instruction
        ]

    def _build_style_and_composition_rules(self, mode, images, config, user_instructions="", user_context="", image_context=""):
        """
        Assembles the final, comprehensive list of style and composition rules that will guide
        the AI's generation process. It intelligently combines rules in a clear order of
        priority: Safety > Mode-Specific > Base > Dynamic Style.
        """
        all_rules = []

        # Priority 1: Safety rules are always first.
        if config.safe_mode:
            all_rules.append(SAFE_MODE_RULE)
 
        # Priority 2: Mode-specific rules come next.
        if mode == "Video":
            all_rules.extend(self._get_video_specific_rules(config, user_instructions, user_context, image_context))
 
        # Priority 3: Base composition rules that apply to all visual modes.
        all_rules.extend(self._get_base_composition_rules(config.language))
        
        # --- Priority 4: Style Rules (Override or Dynamic) ---
        # This logic now clearly shows the switch between user override and dynamic analysis.
        # If a full profile was pre-selected, use its inspiration text.
        if config.style_profile:
            inspiration = config.style_profile.get("inspiration", "")
            if inspiration: all_rules.append(f"- {inspiration}")
        # If a simple keyword style was chosen, use that.
        elif config.style_override != "None" and config.style_override in STYLE_KEYWORDS:
            all_rules.append("- Style: {style}".format(style=STYLE_KEYWORDS[config.style_override]))
        # Otherwise, perform dynamic analysis using the StyleEngine.
        else:
            style_engine_image = images[0] if images else None
            style_engine = StyleEngine(config.model, config.use_chat_api, config.temperature, config.seed, image=style_engine_image, debug_mode=config.debug_mode, timeout=config.timeout)
            all_rules.extend(style_engine.get_composition_rules())
            
        return all_rules

    def _build_instructions_section(self, mode: str, user_instructions: str) -> str:
        """Builds the user instructions section for the initial merge prompt."""
        if not user_instructions or not user_instructions.strip():
            return ""
        
        if mode == "Video":
            header = "USER INSTRUCTIONS (use as a guide, but prioritize the ACTION/MOTION rules below):"
        else:
            header = "USER INSTRUCTIONS (highest priority; if any conflict, follow these over other rules):"
        return f"{header}\n{user_instructions}\n\n"

    def _user_requests_blending_with_ai(self, user_text, primary_subjects, config):
        """
        Uses an AI model to perform a nuanced check for subject blending requests.
        This is more robust than a simple keyword search for complex instructions.
        """
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

        ok, result_json = _reason_with_model(config.model, prompt, config.use_chat_api, 0.0, config.seed, debug_mode=config.debug_mode, debug_title="Blending Intent Check")
        return ok and isinstance(result_json, dict) and result_json.get("blending_requested", False)

    def _user_requests_replacement_with_ai(self, user_text, primary_subjects, config):
        """
        Uses an AI model to perform a nuanced check for subject replacement requests.
        """
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

        ok, result_json = _reason_with_model(config.model, prompt, config.use_chat_api, 0.0, config.seed, debug_mode=config.debug_mode, debug_title="Replacement Intent Check")
        return ok and isinstance(result_json, dict) and result_json.get("replacement_requested", False)

    def _build_initial_merge_prompt(self, mode, user_instructions, user_context, image_context, mandatory_tokens, images, config, primary_subjects_from_images=None):
        """
        Constructs the initial, detailed prompt that will be sent to the AI to generate
        the first draft of the scene. This function assembles all the different pieces of
        information (user text, image context, rules) into a single, coherent set of
        instructions for the model by calling specialized helper methods for each section.
        """
        # Build the style and composition rules, including any negative concepts.
        style_composition_rules = self._build_style_and_composition_rules(mode, images, config, user_instructions, user_context, image_context)
        if config.negative_concepts:
            style_composition_rules.insert(0, f"- CRITICAL: Do NOT include any of the following concepts: {config.negative_concepts}")
        style_composition_rules_str = "\n".join(style_composition_rules)

        # Combine user instructions and context for the "source of truth" part.
        core_scene_text = user_instructions
        if user_context:
            core_scene_text += "\n\n" + user_context

        # Check if the user has provided specific instructions beyond the default text.
        has_instructions = core_scene_text and core_scene_text.strip() and core_scene_text.strip() != DEFAULT_PROMPT_TEXT

        # --- Blending & Replacement Logic ---
        # Check for keywords in the user's text that indicate a desire to merge or blend subjects.
        blend_keywords = ["blend", "merge", "combine", "hybrid", "chimera", "fused", "wearing"]
        user_wants_to_blend = any(keyword in core_scene_text.lower() for keyword in blend_keywords)

        replace_keywords = ["replace", "instead of", "substitute"]
        user_wants_to_replace = any(keyword in core_scene_text.lower() for keyword in replace_keywords)

        # If a simple keyword isn't found, use a more nuanced AI check.
        if not user_wants_to_blend and has_instructions and len(primary_subjects_from_images or []) > 1:
            user_wants_to_blend = self._user_requests_blending_with_ai(core_scene_text, primary_subjects_from_images, config)

        # Perform AI check for replacement if no simple keyword was found.
        # This is done separately from blending as they are distinct intents.
        if not user_wants_to_replace and has_instructions and len(primary_subjects_from_images or []) > 0:
            user_wants_to_replace = self._user_requests_replacement_with_ai(core_scene_text, primary_subjects_from_images, config)


        # --- Dynamic Rule Construction ---
        # Build the main task list dynamically based on user input.
        task_rules = []
        if has_instructions:
            task_rules.append("1.  The USER INSTRUCTIONS are your primary guide. The final prompt MUST fulfill the user's core request.")
            task_rules.append("2.  Use the PRIMARY SUBJECTS and INSPIRATIONAL CONTEXT to flesh out the scene, but only in ways that support and do not contradict the USER INSTRUCTIONS.")
        else:
            task_rules.append("1.  Create a **new, single, coherent scene** that features ALL of the mandatory PRIMARY SUBJECTS interacting or co-existing in a plausible way.")
            task_rules.append("2.  Use the INSPIRATIONAL CONTEXT to flesh out the environment, lighting, and mood.")

        # Add a rule based on the detected intent (blend, replace, or neither).
        if user_wants_to_replace:
            # If the user asks to replace, provide explicit permission to do so.
            task_rules.append("3.  **GUIDANCE:** The user has requested to REPLACE a subject. Identify the subject to be replaced from the image context and substitute it with the new subject from the user's instructions.")
        elif user_wants_to_blend:
            # If the user asks to blend, provide explicit permission to do so.
            task_rules.append("3.  **GUIDANCE:** The user has requested to BLEND or MERGE subjects. Fulfill this request creatively using the primary subjects as your building blocks.")
        else:
            # Add the anti-blending rule only if the user hasn't explicitly asked for blending or replacement.
            task_rules.append("3.  **CRITICAL RULE:** Do NOT merge or blend the features of the subjects. Each subject must remain distinct and separate (e.g., the stag is a stag, the eagle is an eagle. Do NOT create an eagle with antlers).")

        task_rules.append("4.  Create a single, flowing paragraph for the new cinematic prompt.")
        task_rules.append("5.  Integrate the `STYLE & COMPOSITION RULES` into your final prompt.")
        task_rules_str = "\n".join(task_rules)

        # --- Dynamic Prompt Section Construction ---
        user_instructions_section = ""
        if has_instructions:
            user_instructions_section = textwrap.dedent("""
                **USER INSTRUCTIONS (Primary Goal)**
                ---
                {core_scene}
                ---
            """).strip().format(core_scene=core_scene_text)

        # --- Final Template Assembly ---
        # This unified template is now built from the dynamic parts constructed above.
        merge_template = textwrap.dedent("""
            You are an expert prompt engineer. Your task is to create a single, coherent, and detailed prompt for an image generation model by synthesizing multiple reference images.

            **PRIMARY SUBJECTS (Mandatory Building Blocks)**
            Your final scene MUST include all of the following primary subjects:
            {primary_subjects}

            {user_instructions_section}

            **INSPIRATIONAL CONTEXT (For Atmosphere and Style ONLY)**
            Use the following full descriptions of the reference images to build the world around the primary subjects.
            ---
            {image_context}
            ---

            **YOUR TASK:**
            {task_rules}

            --- STYLE & COMPOSITION RULES ---
            {style_rules}
            ---

            Return ONLY the final, polished prompt.
        """).strip()
        return merge_template.format(
            primary_subjects=json.dumps(primary_subjects_from_images or []),
            user_instructions_section=user_instructions_section,
            image_context=image_context,
            task_rules=task_rules_str,
            style_rules=style_composition_rules_str,
        )

    def _generate_negative_prompt(self, scene_prompt, config, user_negative_prompt=""):
        """
        Generates a comprehensive negative prompt by anticipating common AI failures.
        This refactored version uses efficient, local logic instead of an API call.

        The process is as follows:
        1.  **Base Keywords**: Starts with a set of generic keywords for quality and composition.
        2.  **Contextual Analysis**: Scans the positive prompt for triggers (e.g., "person", "photorealistic")
            and adds relevant keyword sets (e.g., for anatomy, against art styles).
        3.  **User Input**: Incorporates keywords from the `negative_image` and the manual
            `negative_prompt` input.
        4.  **Combine & Deduplicate**: All keywords are combined into a single, sorted,
            deduplicated list.
        5.  **Caching**: The final result is cached to avoid re-running the AI query for the
            same positive prompt.
        """
        if not scene_prompt or "Ollama error" in scene_prompt:
            return ""

        # --- Caching Logic ---
        # The cache key is simpler as this is now a local, deterministic function.
        cache_key = _get_cache_key(scene_prompt, user_negative_prompt, "gen_negative_v7_local")
        if CACHE.has(cache_key):
            return CACHE.get(cache_key)

        # --- Step 1: Start with base keywords ---
        # Generic quality and composition keywords are almost always useful.
        keywords = set(NEGATIVE_KEYWORDS["quality"] + NEGATIVE_KEYWORDS["composition"])
        
        # Add hardcoded default negative prompts (e.g., for specific languages)
        keywords.update([kw.strip() for kw in DEFAULT_CHINESE_NEGATIVE_PROMPT.split('，') if kw.strip()])

        # --- Step 2: Context-aware keyword addition ---
        # Scan the positive prompt for trigger words and add their corresponding negative keywords.
        # This is more granular and relevant than adding entire categories.
        prompt_lower = scene_prompt.lower()
        # Use word boundaries (\b) to avoid partial matches (e.g., 'man' in 'woman').
        for trigger, neg_words in NEGATIVE_KEYWORDS["contextual"].items():
            if re.search(r'\b' + re.escape(trigger) + r'\b', prompt_lower):
                keywords.update(neg_words)

        # --- Step 3: Add user-provided concepts ---
        # This includes both the user's manual input and any counter-negatives
        # generated by the _simplify_for_diffusion step.
        # Add keywords from the user's manual input.
        if user_negative_prompt:
            user_keywords = [kw.strip() for kw in user_negative_prompt.replace("\n", ",").split(',') if kw.strip()]
            keywords.update(user_keywords)
        
        # --- Step 4: Final Assembly and Caching ---
        # Using a set handles deduplication. Sorting provides a deterministic output for caching.
        final_neg_prompt = ", ".join(sorted(list(keywords)))

        CACHE.set(cache_key, final_neg_prompt)
        return final_neg_prompt

    def _save_output_to_file(self, filename_prefix, sections, base_filename="prompt"):
        """
        A generic helper to save a list of titled sections to a unique text file.
        This function handles path creation, sanitization, and formatted writing.

        The process is as follows:
        1.  **Path Sanitization**: It takes a user-provided `filename_prefix`, which can
            include a subdirectory (e.g., "MyPrompts/scenes"), and sanitizes it to
            prevent directory traversal attacks (e.g., "../..").
        2.  **Directory Creation**: It ensures the target output directory exists within
            the main ComfyUI `output` folder.
        3.  **Unique Filename Generation**: It creates a unique filename using a base
            name and a high-resolution timestamp to prevent overwriting previous files.
        4.  **Formatted Writing**: It iterates through a list of (title, content) tuples
            and writes them to the file with clear headers, skipping any empty sections.
        """
        # --- Step 1: Prepare and Sanitize Directory Path ---
        # The base directory for all outputs is the main ComfyUI output folder.
        base_dir = os.path.join(COMFYUI_ROOT_DIR, "output")
        
        # Sanitize the user-provided subdirectory path to prevent security risks like
        # directory traversal. `os.path.normpath` collapses redundant separators (e.g., A//B -> A/B)
        # and `lstrip` removes leading dots or slashes that could be used to escape the output directory.
        safe_subdir = os.path.normpath(filename_prefix.strip()).lstrip('.').lstrip('/')
        out_dir = os.path.join(base_dir, safe_subdir)
        os.makedirs(out_dir, exist_ok=True)

        # --- Step 2: Create a Unique Filename ---
        # A unique filename is generated using the base name and a timestamp down to the
        # millisecond. This ensures that even rapid, successive runs will not overwrite
        # each other's output files.
        fname = "{base}_{ts}_{ms}.txt".format(
            base=base_filename,
            ts=time.strftime('%Y%m%d_%H%M%S'),
            ms=int(time.time() * 1000) % 1000
        )
        fpath = os.path.join(out_dir, fname)

        # --- Step 3: Write Formatted Sections to the File ---
        # The function writes the content to the file in a structured, human-readable format.
        with open(fpath, "w", encoding="utf-8") as f:
            for i, (title, content) in enumerate(sections):
                # Only write a section if its content is not empty or just whitespace.
                if content and str(content).strip():
                    f.write(f"=== {title.upper()} ===\n")
                    f.write(str(content).strip() + "\n")
                    # Add a blank line between sections for better readability, but not after the last one.
                    if i < len(sections) - 1:
                        f.write("\n")

    def _execute_visual_prompt_creator(self, mode, user_text, vision_model, **kwargs):
        """A shared execution pipeline for Image and Video creator nodes."""
        # --- 0. Pre-flight Check ---
        if not vision_model or "NO_MODELS_FOUND" in vision_model:
            error_msg = "No vision models found. Please install a vision model in Ollama (e.g., 'ollama run llava') or configure a remote API key."
            return (error_msg, "", "")

        # --- 1. Prepare Config ---
        # We access INPUT_TYPES via self to get the specific defaults for the calling child class.
        original_temp = self.INPUT_TYPES()["required"]["temperature"][1]["default"]
        original_max_len = self.INPUT_TYPES()["required"]["max_length_words"][1]["default"]
        temperature, use_chat_api, max_length_words = self._prepare_run_parameters(
            mode, kwargs.get('temperature'), kwargs.get('use_chat_api'), kwargs.get('max_length_words'), original_temp, original_max_len
        )
        language = _detect_language(user_text)
        config = PromptCrafterRunConfig(model=vision_model, language=language, temperature=temperature, use_chat_api=use_chat_api, max_length_words=max_length_words, **kwargs)
        config.negative_concepts = ""

        # --- 2. Determine Style Profile ---
        # If the user selected a named profile, load it into the config.
        # This logic now parses the formatted name from the dropdown (e.g., "(Image) Fantasy Battle")
        # to find the original profile name ("Fantasy Battle").
        if config.style_override and config.style_override != "None":
            # Remove the "(Type) " prefix to get the original name.
            original_name = re.sub(r'^\(.*\)\s', '', config.style_override)
            if original_name in NAMED_STYLE_PROFILES:
                config.style_profile = NAMED_STYLE_PROFILES[original_name]

        # --- 2. Gather Inputs ---
        images_with_weights = self._collect_images_with_weights(**kwargs)

        # --- 2.5 Check for missing image intent ---
        # This new, more powerful function handles both missing image and missing text scenarios.
        error, new_user_text = self._handle_creative_intent(user_text, images_with_weights, config)
        if error:
            return (error, "", "", "") # Return error in the prompt slot
        
        final_user_text = new_user_text or user_text

        # --- 3. Run Pipeline ---
        return self._generate_visual_prompt_pipeline(
            mode=mode,
            user_text=final_user_text,
            images_with_weights=images_with_weights,
            config=config,
            **kwargs
        )

    def _split_text_into_scenes_with_ai(self, text, config):
        """
        Uses an AI model to intelligently split a single block of text into distinct narrative scenes.
        This is used when the user provides a story in a single paragraph for scheduling.
        """
        
        prompt_template = textwrap.dedent("""
            You are an expert film script analyst. Read the following story or description. Your task is to break it down into distinct, logical scenes or camera shots. Each scene should represent a single, continuous action or a clear shift in focus.

            --- STORY ---
            {story_text}
            --- END STORY ---

            INSTRUCTIONS:
            - Identify the natural breaking points in the narrative.
            - Return ONLY a JSON object with a single key, "scenes", which contains an array of strings. Each string in the array should be one scene.
            - Do NOT add any commentary or explanation.
            - If the story is already a single, indivisible scene, return it as an array with one element.

            Example:
            Input Story: "A woman walks over to a stag and climbs up on the back to ride it. As she is riding the stag across a mountain meadow a bald eagle soars above."
            Output JSON: {{"scenes": ["A woman walks over to a stag and climbs up on its back.", "The woman rides the stag across a mountain meadow as a bald eagle soars above."]}}
        """).strip()

        split_prompt = prompt_template.format(story_text=text)

        ok, result_json = _reason_with_model(config.model, split_prompt, config.use_chat_api, 0.1, config.seed, debug_mode=config.debug_mode, debug_title="AI Scene Splitter")

        if ok and isinstance(result_json, dict) and "scenes" in result_json and isinstance(result_json["scenes"], list):
            scenes = result_json["scenes"]
            if scenes:
                print(f"\033[92m[PromptCrafter] AI successfully split the story into {len(scenes)} scenes.\033[0m")
                return scenes

        print("\033[93m[PromptCrafter] Warning: AI scene splitting failed or returned no scenes. Treating the entire text as a single scene.\033[0m")
        return [text]

    def _generate_storyboard_from_instruction_with_ai(self, user_request, image_context, primary_subjects, config):
        """
        Uses an AI model to act as a director, creating a multi-scene storyboard
        from a single high-level user instruction and image context.
        """
        print("\033[94m[PromptCrafter] Using AI to generate storyboard from user instruction...\033[0m")

        prompt_template = textwrap.dedent("""
            You are an expert film director and storyboard artist. Your task is to break down a user's high-level request into a sequence of distinct, cinematic video scenes.

            --- USER REQUEST ---
            {user_request}

            --- KEY SUBJECTS (from reference images) ---
            {subjects}

            --- INSPIRATIONAL CONTEXT (from reference images) ---
            {image_context}

            --- INSTRUCTIONS ---
            1.  Read the user's request and analyze the subjects and context.
            2.  Create a storyboard as a sequence of short, distinct scenes that logically follow the user's request.
            3.  Each scene should describe a single, clear action. Aim for 3-5 scenes unless the request is very simple.
            4.  **For each scene, suggest a cinematic camera shot (e.g., "wide shot", "close-up", "tracking shot", "low angle shot") to add visual variety.**
            5.  Focus on action and visual storytelling.
            6.  Return ONLY a JSON object with a single key, "scenes", which contains an array of strings. Each string is a scene description.

            Example:
            User Request: "A woman walks over to a stag, climbs on its back, and rides it across a meadow as an eagle soars above."
            Output JSON: {{"scenes": ["Wide shot of a woman in an elegant dress approaching a majestic stag in a mountain meadow.", "Medium shot of the woman gently climbing onto the stag's back, settling in to ride.", "Tracking shot following the stag as it walks across the sunlit meadow with the woman on its back, as a low angle shot shows a bald eagle circling in the sky above."]}}
        """).strip()

        storyboard_prompt = prompt_template.format(user_request=user_request, subjects=json.dumps(primary_subjects), image_context=image_context)

        ok, result_json = _reason_with_model(config.model, storyboard_prompt, config.use_chat_api, 0.2, config.seed, debug_mode=config.debug_mode, debug_title="AI Storyboard Generation")

        if ok and isinstance(result_json, dict) and "scenes" in result_json and isinstance(result_json["scenes"], list) and result_json["scenes"]:
            print(f"\033[92m[PromptCrafter] AI successfully generated a storyboard with {len(result_json['scenes'])} scenes.\033[0m")
            return result_json["scenes"]
        
        return [] # Return empty list on failure

    def _generate_prompt_for_scene(self, scene_text, mode, images_with_weights, image_context_for_all, style_rules, config, **kwargs):
        """
        A self-contained function to generate a prompt for a single scene.
        This is designed to be called in parallel from the main schedule handler.
        """
        # --- Caching Logic ---
        # Create a deterministic set of values from the config object for the cache key.
        config_key_parts = (
            config.model, config.language, config.temperature, config.use_chat_api,
            config.max_length_words, config.seed, config.max_retries, config.critique_strength,
            config.simplify_for_diffusion, config.use_deep_think,
            # Convert the style profile dict to a string to make it hashable
            str(config.style_profile)
        )
        cache_key = _get_cache_key(
            "gen_prompt_for_scene_v1", # Version the key
            scene_text,
            mode,
            images_with_weights,
            image_context_for_all,
            style_rules,
            config_key_parts
        )
        if CACHE.has(cache_key):
            print(f"\033[94m[PromptCrafter] Using cached prompt for scene: '{scene_text[:50]}...'\033[0m")
            return CACHE.get(cache_key)

        images = [img for img, _ in images_with_weights]

        # --- Step 1: Extract scene-specific tokens ---
        # We only need to extract tokens from the current scene's text.
        tok_ok, mandatory_tokens = _extract_mandatory_tokens_with_model(image_context_for_all, scene_text, config)
        if not tok_ok:
            return f"[Error extracting tokens for scene: {mandatory_tokens}]"

        # --- Step 2: Generate Initial Draft ---
        # We pass the pre-computed image context and style rules.
        ok_draft, draft_or_err = self._generate_initial_draft(
            mode, scene_text, "", image_context_for_all, mandatory_tokens, images, config
        )
        if not ok_draft:
            return f"[Error generating draft for scene: {draft_or_err}]"
        scene_prompt = draft_or_err

        # --- Step 3: Refine the Draft ---
        # The style rules are passed in, not recalculated.
        scene_prompt = self._refine_image_video_prompt(scene_prompt, mode, mandatory_tokens, style_rules, config)
        
        # --- Step 4: Simplify for Diffusion Model ---
        new_positive, _ = self._simplify_for_diffusion(scene_prompt, scene_text, config)
        
        # Cache the final result before returning
        CACHE.set(cache_key, new_positive)
        
        return new_positive

    def _handle_scheduled_mode(self, mode, user_text, images_with_weights, config, **kwargs):
        """
        Handles the generation of a multi-prompt schedule for Image and Video modes.
        It processes each paragraph of the user's text as a separate scene.
        """
        # The creative intent check is now handled in the main execute method before this is called.

        # --- 1. Perform all shared analysis ONCE ---
        images = [img for img, _ in images_with_weights]
        image_context_for_all, primary_subjects_from_images = self._describe_images(images_with_weights, config)
        style_rules = self._build_style_and_composition_rules(mode, images, config, user_text, "", image_context_for_all)
        # Generate a base negative prompt from the overall user text and context.
        base_negative_prompt = self._generate_negative_prompt(user_text, config, user_negative_prompt=kwargs.get("negative_prompt", ""))

        # --- 2. Split user text into scenes ---
        if '\n\n' in user_text:
            print("\033[94m[PromptCrafter] Multi-paragraph input detected. Using manual scene breaks.\033[0m")
            scenes = [p.strip() for p in user_text.split('\n\n') if p.strip()]
        else:
            # For single-paragraph input, decide whether to split it or generate a storyboard.
            # If it's a long narrative, split it. If it's a short instruction, generate a storyboard.
            if not user_text or len(user_text.split()) < 20: # Short text or empty text implies storyboard generation
                scenes = self._generate_storyboard_from_instruction_with_ai(user_text, image_context_for_all, primary_subjects_from_images, config)
            else: # Longer text is likely a story to be split
                print("\033[94m[PromptCrafter] Attempting to split single-paragraph story into scenes with AI...\033[0m")
                scenes = self._split_text_into_scenes_with_ai(user_text, config)

        if not scenes:
            return ("", "AI failed to generate a storyboard. Please try rephrasing your request or check the model.", "", "")

        print(f"\033[94m[PromptCrafter] Schedule mode enabled. Generating prompts for {len(scenes)} scenes...\033[0m")

        # --- 3. Generate prompts for each scene in parallel ---
        generated_prompts = [None] * len(scenes)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(scenes))) as executor:
            future_to_index = {
                executor.submit(self._generate_prompt_for_scene, scene_text, mode, images_with_weights, image_context_for_all, style_rules, config, **kwargs): i
                for i, scene_text in enumerate(scenes)
            }

            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    generated_prompts[index] = future.result()
                    print(f"\033[92m[PromptCrafter] Finished processing scene {index + 1}/{len(scenes)}.\033[0m")
                except Exception as exc:
                    error_msg = f"[Error processing scene {index + 1}: {exc}]"
                    generated_prompts[index] = error_msg
                    print(f"\033[91m[PromptCrafter] {error_msg}\033[0m")

        # --- 4. Create the final schedule from the generated prompts ---
        if not generated_prompts:
            # If all scene generations failed, return an error instead of an empty schedule.
            return ("", "Failed to generate prompts for any of the scenes. Please check the model and logs.", image_context_for_all, base_negative_prompt)

        schedule_json = _create_schedule_from_items(generated_prompts, kwargs.get("max_frames", 240), 0, kwargs.get("interpolate_keyframes", True), kwargs.get("interpolation_frame_interval", 10))
        
        # --- 5. Save to file if requested ---
        if kwargs.get("save_to_txt", False) and schedule_json:
            sections = [
                ("USER TEXT", user_text),
                ("IMAGE CONTEXT", image_context_for_all),
                ("NEGATIVE PROMPT", negative_prompt_for_all),
                ("SCHEDULE", schedule_json)
            ]
            self._save_output_to_file(kwargs.get("filename_prefix"), sections, base_filename="schedule")

        # The first output (prompt) is empty, the second (schedule) has the content.
        return ("", schedule_json, image_context_for_all, base_negative_prompt)


class PromptCrafter_ImageCreator(PromptCrafter_BaseCreator):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "user_text": ("STRING", {"multiline": True, "default": DEFAULT_PROMPT_TEXT, "tooltip": "Your high-level instructions, subjects to include/exclude, or lyrics."}),
                "vision_model": (get_vision_models(), {"dynamic": True, "tooltip": "The vision language model (VLM) to use for all analysis and generation."}),
                "image_count": ("INT", {"default": 1, "min": 0, "max": 3, "step": 1, "tooltip": "Number of reference images to use (max 3). The UI will update automatically."}),
                # --- Generation Control ---
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Controls creativity. Lower is more stable, higher is more varied. Set to 0 for maximum reproducibility with a seed."}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "step": 1, "tooltip": "Seed for reproducible prompt generation. -1 for random. Does not affect the initial image description phase."}),
                "max_length_words": ("INT", {"default": 0, "min": 0, "max": 400, "step": 10, "tooltip": "Optional hard limit on output word count. 0 = auto (200 words)."}),
                # --- Style & Refinement ---
                "style_override": (get_style_override_options("Image"), {"default": "None", "tooltip": "Override the dynamic style with a predefined profile or keyword set."}),
                "critique_strength": (["Subtle", "Normal", "Heavy"], {"default": "Normal", "tooltip": "How much the final critique step is allowed to change the prompt."}),
                "simplify_for_diffusion": ("BOOLEAN", {"default": True, "tooltip": "Restructure the final prompt into comma-separated clauses to improve diffusion model comprehension and reduce artifacts."}),
                # --- Technical & Behavior ---
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10, "tooltip": "Timeout in seconds for each individual API call. Increase if you get timeout errors with slow models."}),
                "max_retries": ("INT", {"default": 2, "min": 0, "max": 10, "step": 1, "tooltip": "How many times to retry if the generated prompt fails to include required subjects."}),
                "safe_mode": ("BOOLEAN", {"default": True, "tooltip": "Enforce SFW rules to prevent NSFW, violent, or controversial content."}),
                "debug_mode": ("BOOLEAN", {"default": False, "tooltip": "Print all intermediate prompts to the console for debugging."}),
                # --- File Output ---
                "save_to_txt": ("BOOLEAN", {"default": False, "tooltip": "Save the final prompt and context to a text file in the ComfyUI/output directory."}),
                "filename_prefix": ("STRING", {"default": "scene_prompts", "tooltip": "Subdirectory and prefix for the saved text file."}),
            },
            "optional": {
                "image_weights_json": ("STRING", {"default": "{}", "multiline": True}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
                # --- Scheduling Options ---
                "generate_schedule": ("BOOLEAN", {"default": False, "tooltip": "Generate a multi-prompt schedule, treating each paragraph in user_text as a separate scene."}),
                "max_frames": ("INT", {"default": 240, "min": 1, "max": 99999, "tooltip": "The total number of frames for the scheduled animation."}),
                "interpolate_keyframes": ("BOOLEAN", {"default": True, "tooltip": "Create smooth transitions between keyframes."}),
                "interpolation_frame_interval": ("INT", {"default": 10, "min": 0, "max": 100, "tooltip": "Insert a new interpolated keyframe every N frames. 0 to disable."}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "schedule", "image_context", "negative_prompt")
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter (v{__version__})"
    HELP = {
        "title": "PromptCrafter Image Creator",
        "description": (
            "A dedicated node for generating high-quality prompts for static images. It analyzes reference images and user instructions to create a detailed, cinematic prompt.\n\n"
            "**Key Features:**\n"
            "- **Deep Think**: Enables a multi-step self-critique process for higher quality prompts.\n"
            "- **Dynamic Style Engine**: Intelligently analyzes your images to apply a relevant artistic style, or you can override it with a specific choice.\n"
            "- **Subject Control**: Uses an advanced pipeline to ensure all your requested subjects are included and to prevent the AI from 'hallucinating' unwanted details.\n"
            "- **Storyboard/Scheduling**: Generate a sequence of prompts from a multi-paragraph story, perfect for creating image series or for image-to-video workflows."
        ),
        "reset": True,
    }
    DESCRIPTION = HELP["description"]

    @classmethod
    def reset_defaults(self, **kwargs): return {"temperature": 0.2, "use_chat_api": False, "max_length_words": 200, "seed": -1}

    def execute(self, user_text, vision_model, **kwargs):
        try:
            config = self._setup_config("Image", user_text, vision_model, **kwargs)
            images_with_weights = self._collect_images_with_weights(**kwargs)

            if kwargs.get("generate_schedule"):
                return self._handle_scheduled_mode("Image", user_text, images_with_weights, config, **kwargs)
            else:
                prompt, image_context, negative_prompt = self._generate_visual_prompt_pipeline(
                    mode="Image", user_text=user_text, images_with_weights=images_with_weights, config=config, **kwargs
                )
                return (prompt, "", image_context, negative_prompt)
        except ValueError as e:
            return (str(e), "", "", "")

class PromptCrafter_VideoCreator(PromptCrafter_BaseCreator):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "user_text": ("STRING", {"multiline": True, "default": DEFAULT_PROMPT_TEXT, "tooltip": "Your high-level instructions, subjects to include/exclude, or lyrics."}),
                "vision_model": (get_vision_models(), {"dynamic": True, "tooltip": "The vision language model (VLM) to use for all analysis and generation."}),
                "image_count": ("INT", {"default": 1, "min": 0, "max": 3, "step": 1, "tooltip": "Number of reference images to use (max 3). The UI will update automatically."}),
                # --- Generation Control ---
                "temperature": ("FLOAT", {"default": 0.4, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Controls creativity. Lower is more stable, higher is more varied. Set to 0 for maximum reproducibility with a seed."}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "step": 1, "tooltip": "Seed for reproducible prompt generation. -1 for random. Does not affect the initial image description phase."}),
                "max_length_words": ("INT", {"default": 0, "min": 0, "max": 400, "step": 10, "tooltip": "Optional hard limit on output word count. 0 = auto (120 words)."}),
                # --- Style & Refinement ---
                "style_override": (get_style_override_options("Video"), {"default": "None", "tooltip": "Override the dynamic style with a predefined profile or keyword set."}),
                "critique_strength": (["Subtle", "Normal", "Heavy"], {"default": "Normal", "tooltip": "How much the final critique step is allowed to change the prompt."}),
                "simplify_for_diffusion": ("BOOLEAN", {"default": True, "tooltip": "Restructure the final prompt into comma-separated clauses to improve diffusion model comprehension and reduce artifacts."}),
                # --- Technical & Behavior ---
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10, "tooltip": "Timeout in seconds for each individual API call. Increase if you get timeout errors with slow models."}),
                "max_retries": ("INT", {"default": 2, "min": 0, "max": 10, "step": 1, "tooltip": "How many times to retry if the generated prompt fails to include required subjects."}),
                "safe_mode": ("BOOLEAN", {"default": True, "tooltip": "Enforce SFW rules to prevent NSFW, violent, or controversial content."}),
                "debug_mode": ("BOOLEAN", {"default": False, "tooltip": "Print all intermediate prompts to the console for debugging."}),
                # --- File Output ---
                "save_to_txt": ("BOOLEAN", {"default": False, "tooltip": "Save the final prompt and context to a text file in the ComfyUI/output directory."}),
                "filename_prefix": ("STRING", {"default": "scene_prompts", "tooltip": "Subdirectory and prefix for the saved text file."}),
            },
            "optional": {
                "image_weights_json": ("STRING", {"default": "{}", "multiline": True}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
                # --- Scheduling Options ---
                "generate_schedule": ("BOOLEAN", {"default": False, "tooltip": "Generate a multi-prompt schedule, treating each paragraph in user_text as a separate scene."}),
                "max_frames": ("INT", {"default": 240, "min": 1, "max": 99999, "tooltip": "The total number of frames for the scheduled animation."}),
                "interpolate_keyframes": ("BOOLEAN", {"default": True, "tooltip": "Create smooth transitions between keyframes."}),
                "interpolation_frame_interval": ("INT", {"default": 10, "min": 0, "max": 100, "tooltip": "Insert a new interpolated keyframe every N frames. 0 to disable."}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "schedule", "image_context", "negative_prompt")
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter (v{__version__})"
    HELP = {
        "title": "PromptCrafter Video Creator",
        "description": (
            "A dedicated node for generating high-quality prompts for videos, following the Wan2.2 cinematic formula. It analyzes reference images and user instructions to create a detailed prompt with a focus on action and motion.\n\n"
            "**Key Features:**\n"
            "- **Wan2.2 Formula**: Structures the prompt for optimal video generation.\n"
            "- **Context-Aware Motion**: Intelligently determines if the scene requires dynamic action or subtle, natural movement.\n"
            "- **Storyboard/Scheduling**: Generate a sequence of prompts from a multi-paragraph story, perfect for creating multi-shot video scenes.\n"
            "- **Deep Think**: Enables a multi-step self-critique process for higher quality prompts.\n"
            "- **Subject Control**: Ensures all your requested subjects are included and prevents the AI from 'hallucinating' unwanted details."
        ),
        "reset": True,
    }
    DESCRIPTION = HELP["description"]

    @classmethod
    def reset_defaults(self, **kwargs): return {"temperature": 0.4, "use_chat_api": True, "max_length_words": 120, "seed": -1}

    def execute(self, user_text, vision_model, **kwargs):
        try:
            config = self._setup_config("Video", user_text, vision_model, **kwargs)
            images_with_weights = self._collect_images_with_weights(**kwargs)

            if kwargs.get("generate_schedule"):
                return self._handle_scheduled_mode("Video", user_text, images_with_weights, config, **kwargs)
            else:
                prompt, image_context, negative_prompt = self._generate_visual_prompt_pipeline(
                    mode="Video", user_text=user_text, images_with_weights=images_with_weights, config=config, **kwargs
                )
                return (prompt, "", image_context, negative_prompt)
        except ValueError as e:
            return (str(e), "", "", "")

# ------------------------------------------------------------------------------------
class PromptCrafter_LyricsCreator(PromptCrafter_BaseCreator):
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "user_text": ("STRING", {"multiline": True, "default": DEFAULT_PROMPT_TEXT, "tooltip": "Your high-level instructions, subjects to include/exclude, or lyrics."}),
                "vision_model": (get_vision_models(), {"dynamic": True, "tooltip": "The vision language model (VLM) to use for all analysis and generation."}),
                "image_count": ("INT", {"default": 1, "min": 0, "max": 3, "step": 1, "tooltip": "Number of reference images to use (max 3). The UI will update automatically."}),
                # --- Generation Control ---
                "temperature": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Controls creativity. Lower is more stable, higher is more varied."}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "step": 1, "tooltip": "Seed for reproducible prompt generation. -1 for random."}),
                "max_length_words": ("INT", {"default": 100, "min": 0, "max": 400, "step": 10, "tooltip": "Optional hard limit on output word count. 0 = auto (100 words)."}),
                # --- Style & Refinement ---
                "style_override": (get_style_override_options("Lyrics"), {"default": "None", "tooltip": "Override the dynamic style with a predefined profile or keyword set."}),
                "critique_strength": (["Subtle", "Normal", "Heavy"], {"default": "Normal", "tooltip": "How much the final critique step is allowed to change the prompt."}),
                "simplify_for_diffusion": ("BOOLEAN", {"default": False, "tooltip": "Restructure the final prompt into comma-separated clauses to improve diffusion model comprehension and reduce artifacts."}),
                # --- Technical & Behavior ---
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10, "tooltip": "Timeout in seconds for each individual API call."}),
                "max_retries": ("INT", {"default": 2, "min": 0, "max": 10, "step": 1, "tooltip": "How many times to retry if the generated prompt fails to include required subjects."}),
                "safe_mode": ("BOOLEAN", {"default": True, "tooltip": "Enforce SFW rules to prevent NSFW, violent, or controversial content."}),
                "debug_mode": ("BOOLEAN", {"default": False, "tooltip": "Print all intermediate prompts to the console for debugging."}),
                # --- File Output ---
                "save_to_txt": ("BOOLEAN", {"default": False, "tooltip": "Save the final prompt and context to a text file."}),
                "filename_prefix": ("STRING", {"default": "lyrics_prompts", "tooltip": "Subdirectory and prefix for the saved text file."}),
            },
            "optional": {
                "image_weights_json": ("STRING", {"default": "{}", "multiline": True}),
                "negative_prompt": ("STRING", {"multiline": True, "default": ""}),
                # --- Audio & Timing ---
                "audio_folder_path": ("STRING", {"multiline": False, "default": "input/audio", "tooltip": "Folder containing an optional audio file for lyric alignment."}),
                "audio_file": ("STRING", {"multiline": False, "default": "<none>", "tooltip": "The name of the audio file within the specified folder."}),
                "lyrics_folder_path": ("STRING", {"multiline": False, "default": "input/lyrics", "tooltip": "Folder containing an optional lyrics file (txt or srt)."}),
                "lyrics_file": ("STRING", {"multiline": False, "default": "<none>", "tooltip": "The name of the lyrics file within the specified folder."}),
                # --- Scheduling Options ---
                "generate_schedule": ("BOOLEAN", {"default": True, "tooltip": "Generate a multi-prompt schedule, treating each line in the lyrics as a separate scene."}),
                "song_length_seconds": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 3600.0, "step": 0.1, "tooltip": "If no SRT file is used, specify song length to create a timed schedule. 0 to disable."}),
                "fps": ("FLOAT", {"default": 16.0, "min": 1.0, "max": 120.0, "step": 0.5, "tooltip": "Frames per second for timed schedule calculation."}),
                "max_frames": ("INT", {"default": 240, "min": 1, "max": 99999, "tooltip": "If no timing info is provided, distribute prompts over this many frames."}),
                "interpolate_keyframes": ("BOOLEAN", {"default": False, "tooltip": "Create smooth transitions between keyframes. (Usually not recommended for lyrics)."}),
                "interpolation_frame_interval": ("INT", {"default": 0, "min": 0, "max": 100, "tooltip": "Insert a new interpolated keyframe every N frames. 0 to disable."}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("prompt", "schedule", "image_context", "negative_prompt")
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter (v{__version__})"
    HELP = {
        "title": "PromptCrafter Lyrics Creator",
        "description": (
            "A dedicated node for generating a visual storyboard or prompt schedule from song lyrics.\n\n"
            "**Key Features:**\n"
            "- **Audio Alignment**: Provide an audio file to have the AI cross-check and correct the lyrics.\n"
            "- **Timed Scheduling**: Provide an SRT file for perfectly timed keyframes. If no SRT is used, you can provide `song_length_seconds` and `fps` to distribute prompts over the song's duration.\n"
            "- **Untimed Scheduling**: If no timing info is provided, prompts are distributed evenly over `max_frames`.\n"
            "- **Deep Think**: Enables a multi-step self-critique process for higher quality prompts."
        ),
        "reset": True,
    }
    DESCRIPTION = HELP["description"]

    @classmethod
    def reset_defaults(self, **kwargs): return {"temperature": 0.5, "use_chat_api": True, "max_length_words": 100, "seed": -1}

    def execute(self, user_text, vision_model, **kwargs):
        try:
            # --- 1. Gather Inputs ---
            images_with_weights = self._collect_images_with_weights(**kwargs)
            lyrics_text, timed_segments, lyrics_meta = self._get_lyrics_from_input(
                user_text, kwargs.get("lyrics_folder_path"), kwargs.get("lyrics_file"), kwargs.get("debug_mode", False)
            )
            audio_path = self._get_audio_path(kwargs.get("audio_folder_path"), kwargs.get("audio_file"))

            # --- 2. Prepare Config ---
            # Use the determined lyrics for language detection for better accuracy.
            # The _setup_config method will handle all other parameter setup.
            config = self._setup_config("Lyrics", lyrics_text or user_text, vision_model, **kwargs)

            # --- 3. Run Pipeline ---
            prompt, schedule, image_context, negative_prompt = self._handle_lyrics_mode(
                lyrics=lyrics_text,
                timed_segments=timed_segments,
                images_with_weights=images_with_weights,
                user_instructions=user_text,
                lyrics_meta=lyrics_meta,
                config=config,
                audio_path=audio_path,
                generate_schedule=kwargs.get("generate_schedule", False),
                negative_prompt=kwargs.get("negative_prompt", "")
            )
            return (prompt, schedule, image_context, negative_prompt)
        except ValueError as e:
            # Return the error message in the first output slot for UI visibility.
            return (str(e), "", "", "")

    # --- Lyrics-Specific Methods ---
    def _get_audio_path(self, folder_path, file_name):
        if not folder_path or not file_name or file_name == "<none>": return None
        full_folder_path = folder_path if os.path.isabs(folder_path) else os.path.join(COMFYUI_ROOT_DIR, folder_path)
        filepath = os.path.join(full_folder_path, file_name)
        if os.path.exists(filepath): return filepath
        print(f"\033[93m[PromptCrafter] Warning: Audio file not found at '{filepath}'.\033[0m")
        return None

    def _process_lyrics_content(self, content, source_name=""):
        """Processes raw text content, detecting and parsing SRT or LRC format if present."""
        if not content or content.startswith("[Error"):
            return content, None

        # Check for SRT format first
        is_srt = (source_name and source_name.lower().endswith(".srt")) or ("-->" in content and re.search(r'\d{2}:\d{2}:\d{2},\d{3}', content))
        if is_srt:
            timed_segments, parsed_text = _srt_to_timed_segments(content)
            return parsed_text, timed_segments
        
        # Check for LRC format
        is_lrc = (source_name and source_name.lower().endswith(".lrc")) or (re.search(r'\[\d{2}:\d{2}\.\d{2,3}\]', content))
        if is_lrc:
            # Use the new LRC parser
            timed_segments, parsed_text = _lrc_to_timed_segments(content)
            if timed_segments: # If parsing was successful
                return parsed_text, timed_segments
        
        # Fallback to treating as plain text
        return content, None

    def _handle_lyrics_from_file(self, folder_path, file_name, debug_mode):
        """Handles loading lyrics from a file path or URL specified in the UI widgets."""
        # Handle URL case
        if file_name.strip().startswith(('http://', 'https://')):
            url = file_name.strip()
            metadata = ("URL", url)
            ok, content_or_error = _fetch_url_content(url, debug_mode)
            text, segments = self._process_lyrics_content(content_or_error, url)
            return text, segments, metadata

        # Handle local file case
        full_folder_path = folder_path
        if not os.path.isabs(full_folder_path):
            full_folder_path = os.path.join(COMFYUI_ROOT_DIR, full_folder_path)
        
        filepath = os.path.join(full_folder_path, file_name)
        metadata = (folder_path, file_name)
        
        if not os.path.exists(filepath):
            error_msg = f"[Error: File not found at '{filepath}'. Ensure the folder path is correct relative to the ComfyUI root directory (e.g., 'input/lyrics').]"
            return error_msg, None, metadata

        content = safe_read(filepath)
        text, segments = self._process_lyrics_content(content, file_name)
        return text, segments, metadata

    def _get_lyrics_from_input(self, user_text, lyrics_folder_path, lyrics_file, debug_mode=False) -> tuple[str, list | None, tuple | None]:
        """Determines the source of lyrics using a clear priority system and returns the content."""
        # Priority 1: An explicitly selected file from the UI widgets.
        if lyrics_folder_path and lyrics_file and lyrics_file != "<none>":
            return self._handle_lyrics_from_file(lyrics_folder_path, lyrics_file, debug_mode)

        # Priority 2: A URL pasted directly into the user_text widget.
        # We check if the stripped text is a single URL to avoid misinterpreting text that starts with 'http'.
        if user_text and user_text.strip().startswith(('http://', 'https://')) and len(user_text.strip().split()) == 1:
            url = user_text.strip()
            metadata = ("URL in user_text", url)
            ok, content_or_error = _fetch_url_content(url, debug_mode)
            text, segments = self._process_lyrics_content(content_or_error, url)
            return text, segments, metadata

        # Priority 3: Text in the main user_text widget (treated as raw lyrics).
        if user_text and user_text.strip() and user_text.strip() != DEFAULT_PROMPT_TEXT:
            text, segments = self._process_lyrics_content(user_text)
            return text, segments, None

        # Fallback: No lyrics provided.
        return "", None, None

    def _prepare_lyrics_context_sections(self, config, images, lyrics, instructions, context):
        style_inspiration_section = ""
        # --- Priority 1: Use pre-selected profile ---
        if config.style_profile:
            inspiration = config.style_profile.get("inspiration", "")
            if inspiration:
                style_inspiration_section = f"- {inspiration}\n"
        # --- Priority 2: Use keyword override ---
        elif config.style_override != "None" and config.style_override in STYLE_KEYWORDS:
            style_inspiration_section = f"- Style: {STYLE_KEYWORDS[config.style_override]}\n"
        # --- Priority 3: Dynamic analysis ---
        else:
            style_engine_image = images[0] if images else None
            style_engine = StyleEngine(config.model, config.use_chat_api, config.temperature, config.seed, image=style_engine_image, text=lyrics, debug_mode=config.debug_mode, timeout=config.timeout)
            dynamic_rules = style_engine.get_composition_rules()
            if dynamic_rules:
                style_inspiration_section = f"- {dynamic_rules[0].lstrip('- ').strip()}\n"
        
        instructions_section = f"SONG INSTRUCTIONS (use as a guide, but prioritize the ACTION/MOTION rules):\n{instructions}\n\n" if instructions and instructions.strip() else ""
        context_section = f"SONG CONTEXT & NARRATIVE (for mood and story):\n{context}\n\n" if context and context.strip() else ""
        return style_inspiration_section, instructions_section, context_section

    def _prepare_lyrics_generation_context(self, user_instructions, images_with_weights, lyrics, config):
        images = [img for img, _ in images_with_weights]
        image_context, _ = self._describe_images(images_with_weights, config)
        # The AI-based split into 'instructions' and 'context' was found to be unreliable
        # and could de-prioritize important user requests. Following the pattern from
        # the Image/Video nodes, we now treat the entire user_instructions text as
        # the primary set of instructions.
        parsed_instructions, parsed_context = user_instructions, ""
        style_inspiration_section, instructions_section, context_section = self._prepare_lyrics_context_sections(config, images, lyrics, parsed_instructions, parsed_context)
        tok_ok, mandatory_tokens = _extract_mandatory_tokens_with_model(image_context, (parsed_instructions or ""), config)
        return image_context, (mandatory_tokens if tok_ok else {}), style_inspiration_section, instructions_section, context_section

    def _generate_storyboard_global_theme(self, lyrics, instructions_section, context_section, image_context, config):
        """Generates a global theme to ensure storyboard consistency."""
        theme_prompt = textwrap.dedent(f"""
            You are a music video director. Your task is to analyze the provided source material and synthesize a "Global Theme" for a music video. This theme is a high-level summary that will ensure visual consistency across all scenes.

            **CRITICAL INSTRUCTIONS:**
            1.  **Analyze Source Material:** Your theme MUST be based on the explicit information and implicit mood of the LYRICS, INSTRUCTIONS, and IMAGE REFERENCES.
            2.  **Handle Abstract Lyrics:** If the lyrics are abstract or non-narrative, focus on interpreting the core emotions, mood, and symbolism. Translate these abstract concepts into a cohesive visual theme. For example, for lyrics about loneliness, you might suggest a theme of 'a single figure in vast, empty landscapes with a cool, desaturated color palette'.
            3.  **Avoid Contradiction:** Do NOT invent narratives or characters that contradict the source material. Your theme should be a creative interpretation, not a replacement.
            4.  **Define Core Elements:** The theme should define the core visual style, setting, character design, and mood.

            --- LYRICS ---\n{lyrics}\n--- INSTRUCTIONS ---\n{instructions_section}\n--- CONTEXT ---\n{context_section}\n--- IMAGE REFERENCES ---\n{image_context}\n---
            Return ONLY the Global Theme description in a single, concise paragraph.
        """).strip()
        ok, theme = query_model_auto(config.model, theme_prompt, prefer_chat=config.use_chat_api, temperature=config.temperature, seed=config.seed, timeout=120, debug_mode=config.debug_mode, debug_title="Storyboard Global Theme")
        return (True, TextCleaner.single_paragraph(theme)) if ok else (False, f"Could not generate storyboard theme: {theme}")

    def _handle_lyrics_mode(self, lyrics, timed_segments, images_with_weights, user_instructions, lyrics_meta, config, audio_path=None, generate_schedule=False, negative_prompt=""):
        if config.use_audio_alignment and audio_path and lyrics and not lyrics.startswith("[Error"):
            print("\033[94m[PromptCrafter] Audio file provided. Performing audio-lyric alignment...\033[0m")
            spectrogram_img = audio_to_spectrogram(audio_path)
            if isinstance(spectrogram_img, Image.Image):
                corrected_lyrics = _validate_lyrics_against_audio(lyrics, spectrogram_img, config)
                if corrected_lyrics.strip() and corrected_lyrics.strip() != lyrics.strip():
                    print("\033[92m[PromptCrafter] Lyrics corrected based on audio analysis.\033[0m")
                    lyrics = corrected_lyrics
                    # Re-process content in case correction changed SRT structure (unlikely but safe)
                    lyrics, timed_segments = self._process_lyrics_content(lyrics)
            else:
                print(f"\033[93m[PromptCrafter] Warning: Could not generate spectrogram. Error: {spectrogram_img}\033[0m")

        if not lyrics or not lyrics.strip(): return ("No lyrics provided.", "", "No reference images provided.", "")
        if lyrics.startswith("[Error"): return (f"Failed to process lyrics input: {lyrics}", "", "No reference images provided.", "")

        image_context, mandatory_tokens, style_inspiration_section, instructions_section, context_section = self._prepare_lyrics_generation_context(user_instructions, images_with_weights, lyrics, config)
        
        theme_ok, global_theme_or_err = self._generate_storyboard_global_theme(lyrics, instructions_section, context_section, image_context, config)
        if not theme_ok: return (global_theme_or_err, "", image_context, "")

        storyboard_prompts = self._process_lyrics_storyboard(lyrics, timed_segments, global_theme_or_err, mandatory_tokens, style_inspiration_section, config)
        if not storyboard_prompts or (isinstance(storyboard_prompts, str) and storyboard_prompts.startswith("Could not generate")):
            error_msg = storyboard_prompts or "Failed to generate storyboard prompts."
            return (error_msg, "", image_context, "")

        storyboard_text_for_neg_prompt = "\n\n---\n\n".join(storyboard_prompts)
        final_negative_prompt = self._generate_negative_prompt(storyboard_text_for_neg_prompt, config, user_negative_prompt=negative_prompt)

        final_output = self._create_final_lyrics_output(
            storyboard_prompts=storyboard_prompts,
            timed_segments=timed_segments,
            generate_schedule=generate_schedule,
            fps=config.fps,
            song_length_seconds=config.song_length_seconds,
            config=config
        )
        
        prompt_out = ""
        schedule_out = ""
        if generate_schedule: schedule_out = final_output
        else: prompt_out = final_output

        if config.save_to_txt: self._save_lyrics_output_to_file(config.filename_prefix, lyrics_meta, image_context, lyrics, final_negative_prompt, final_output)
        return (prompt_out, schedule_out, image_context, final_negative_prompt)

    def _create_schedule_from_srt(self, storyboard_prompts, timed_segments, fps, config):
        """Creates a timed JSON schedule from SRT file segments."""
        print("\033[94m[PromptCrafter] SRT file detected. Generating timed schedule...\033[0m")
        
        if len(storyboard_prompts) != len(timed_segments):
            return f"[Error: Mismatch between SRT segments ({len(timed_segments)}) and generated prompts ({len(storyboard_prompts)}).]"

        schedule = collections.OrderedDict()
        for i, seg in enumerate(timed_segments):
            frame = int(seg[0] * fps)
            prompt = re.sub(r'# Segment: .*?\n# Global Theme: .*?\n\n', '', storyboard_prompts[i], flags=re.DOTALL).strip()
            schedule[frame] = prompt
        
        if config.interpolate_keyframes:
            schedule = _interpolate_schedule_prompts(schedule, config.interpolation_frame_interval)

        schedule_items = [f'"{str(key)}": {json.dumps(str(value))}' for key, value in schedule.items()]
        return ",\n".join(schedule_items)

    def _create_final_lyrics_output(self, storyboard_prompts, timed_segments, generate_schedule, fps, song_length_seconds, config):
        """Dispatches to the correct schedule creation method based on user settings."""
        if not generate_schedule:
            return "\n\n---\n\n".join(storyboard_prompts)

        if timed_segments:
            return self._create_schedule_from_srt(storyboard_prompts, timed_segments, fps, config)

        if song_length_seconds > 0:
            print("\033[94m[PromptCrafter] Song length provided. Generating timed schedule...\033[0m")
            max_frames = int(song_length_seconds * fps)
        else:
            max_frames = config.max_frames

        # Fallback to using max_frames directly
        return _create_schedule_from_items(storyboard_prompts, max_frames, 0, config.interpolate_keyframes, config.interpolation_frame_interval)



    def _save_lyrics_output_to_file(self, filename_prefix, lyrics_meta, image_context, lyrics, final_negative_prompt, final_output):
        if not final_output or not final_output.strip(): return
        sections = []
        if lyrics_meta and lyrics_meta[0] and lyrics_meta[1] and lyrics_meta[1] != "<none>":
            sections.append(("LYRICS SOURCE FILE", f"folder: {lyrics_meta[0]}\nfile: {lyrics_meta[1]}"))
        sections.extend([("IMAGE CONTEXT", image_context or "No reference images provided."), ("LYRICS", (lyrics or "").strip()), ("NEGATIVE PROMPT", final_negative_prompt or ""), ("OUTPUT", final_output)])
        self._save_output_to_file(filename_prefix, sections, base_filename="lyrics_prompts")

    def _build_lyric_refinement_prompt(self, current_prompt, mandatory_items, global_theme, rules_text):
        """Builds the detailed prompt for the lyric segment refinement step."""
        refine_template = textwrap.dedent("""
            You are a master prompt critic and editor for Wan2.2 video prompts. Your task is to review and enhance the following DRAFT PROMPT for a music video segment.

            --- DRAFT PROMPT ---\n{prompt_to_review}\n--- END DRAFT PROMPT ---

            --- REQUIREMENTS & RULES ---
            1.  **MANDATORY SUBJECTS (CRITICAL):** The final prompt MUST include all of the following subjects: {subjects}
            2.  **GLOBAL THEME (for consistency):** {theme}
            3.  **Wan2.2 Formula:** The prompt should follow the structure: [Subject Description] + [Scene Description] + [Detailed Action & Physics-Based Motion] + [Aesthetics & Stylization].
            4.  **STYLE & COMPOSITION RULES:**\n{rules}
            --- END REQUIREMENTS & RULES ---

            INSTRUCTIONS:
            - Revise the DRAFT PROMPT to meet ALL of the requirements listed above.
            - Ensure the mandatory subjects are integrated naturally.
            - Enhance the prompt for cinematic quality, clarity, and impact, strictly following the Wan2.2 formula.
            - If the draft already meets all requirements, you can make minor improvements or return it as is.
            
            Return ONLY the final, improved prompt. No commentary.
        """)
        if not mandatory_items:
            refine_template = refine_template.replace("1.  **MANDATORY SUBJECTS (CRITICAL):** The final prompt MUST include all of the following subjects: {subjects}\n", "")
        
        return refine_template.format(
            prompt_to_review=current_prompt,
            subjects=json.dumps(mandatory_items) if mandatory_items else "None",
            theme=global_theme or "Not specified.",
            rules=rules_text
        )

    def _check_lyric_segment_coverage(self, prompt, mandatory_items, config, debug_title_prefix):
        """Checks if a lyric segment prompt contains all mandatory items."""
        if not mandatory_items:
            return True # Nothing to check, so coverage is met.

        coverage_prompt = f'Analyze the SCENE PROMPT below. Does it semantically contain all of the REQUIRED ITEMS? REQUIRED ITEMS: {json.dumps(mandatory_items)} SCENE PROMPT: {prompt} Respond with ONLY a JSON object: {{"missing_items": []}}.'
        
        ok, result_json = _reason_with_model(
            config.model, coverage_prompt, config.use_chat_api, 0.0, config.seed, 
            debug_mode=config.debug_mode, debug_title=f"{debug_title_prefix} Check"
        )
        
        if not ok:
            print(f"\033[93m[PromptCrafter] Warning: Coverage check failed for '{debug_title_prefix}'. Retrying. Error: {result_json}\033[0m")
            return False
            
        return not result_json.get("missing_items")

    def _refine_lyric_segment_prompt(self, draft_prompt, mandatory_items, rules_text, config, debug_title_prefix, global_theme=None):
        """
        Performs a multi-step refinement on a single prompt for a lyric segment,
        ensuring it meets all quality and subject coverage requirements.
        """
        current_prompt = draft_prompt
        for i in range(config.max_retries + 1):
            # --- Step 1: Build the comprehensive prompt for refinement ---
            critique_prompt = self._build_lyric_refinement_prompt(current_prompt, mandatory_items, global_theme, rules_text)

            # --- Step 2: Execute the refinement query ---
            ok, revised_prompt = query_model_auto(config.model, critique_prompt, prefer_chat=config.use_chat_api, temperature=config.temperature, seed=config.seed, timeout=90, debug_mode=config.debug_mode, debug_title=f"{debug_title_prefix} Refine (Try {i+1})")
            if not ok: return current_prompt
            current_prompt = TextCleaner.single_paragraph(revised_prompt)

            # --- Step 3: Check for subject coverage and decide whether to exit ---
            debug_title_for_check = f"{debug_title_prefix} (Try {i+1})"
            if self._check_lyric_segment_coverage(current_prompt, mandatory_items, config, debug_title_for_check):
                return current_prompt # Success! All items are covered.

        # If the loop finishes without success, return the last attempt as a fallback.
        return current_prompt

    def _build_storyboard_rules(self, config, style_inspiration_section):
        safety_rule = f"\n{SAFE_MODE_RULE}" if config.safe_mode else ""
        length_rule = f"- Keep each segment's prompt under {config.max_length_words} words." if config.max_length_words > 0 else "- Each segment's prompt length target: 80-120 words."
        negative_concepts_rule = f"CRITICAL: Do NOT include any of the following concepts: {config.negative_concepts}" if config.negative_concepts else ""
        return textwrap.dedent(f"""- CRITICAL: All generated prompt text MUST be in {config.language}. Do NOT use any other languages.\n{style_inspiration_section}{safety_rule}\n{negative_concepts_rule}\n- The visual elements (characters, setting, objects) should be based on the USER INSTRUCTIONS and IMAGE REFERENCES provided during the theme generation. Do not invent new core subjects.\n- The ACTION and MOOD of the prompt must be a direct visual interpretation of the specific lyric segment. Do NOT just repeat the user's original scene description.\n- CRITICAL PRIORITY: Focus on subject ACTIONS and physics-based MOTION (e.g., 'striding purposefully, coat billowing'). Keep the environment concise and supporting.\n- Maintain continuity: characters, setting, palette, lens/lighting consistent across segments.\n{length_rule}""")

    def _generate_and_refine_segment_prompt(self, segment_name, segment_text, global_theme, storyboard_rules_text, mandatory_tokens, config):
        """Generates and refines a prompt for a single lyric segment in one consolidated function."""
        # --- 1. Generate Initial Draft for the Segment ---
        draft_prompt_template = textwrap.dedent(f"""
            You are an expert Wan2.2 video prompt generator. Your task is to write a single, detailed cinematic prompt for the lyric segment below, following the Wan2.2 formula and adhering to the Global Theme.

            **Wan2.2 Formula:** [Subject Description] + [Scene Description] + [Detailed Action & Physics-Based Motion] + [Aesthetics & Stylization].

            --- GLOBAL THEME (Your guide for consistency) ---
            {global_theme}

            --- LYRIC SEGMENT: "{segment_name}" ---
            {segment_text}

            --- RULES ---
            {storyboard_rules_text}

            Return ONLY the generated prompt for this single segment.
        """).strip()

        draft_ok, draft_prompt = query_model_auto(
            config.model, draft_prompt_template, prefer_chat=config.use_chat_api,
            temperature=config.temperature, seed=config.seed, timeout=90,
            debug_mode=config.debug_mode, debug_title=f"Draft for Segment '{segment_name}'"
        )

        if not draft_ok:
            print(f"\033[93m[PromptCrafter] Warning: Failed to generate draft for segment '{segment_name}'. Error: {draft_prompt}\033[0m")
            return f"# Segment: {segment_name}\n# Global Theme: {global_theme}\n\n[Error generating prompt for this segment]"

        # --- 2. Refine the Draft ---
        scene_prompt = TextCleaner.slim_prompt_text(TextCleaner.dedupe_sentences(TextCleaner.single_paragraph(draft_prompt)))
        primary_items_list = [re.sub(r'^\[PRIMARY\]\s*', '', t) for t in (mandatory_tokens or {}).get("primary", [])]
        
        refined_prompt = self._refine_lyric_segment_prompt(
            scene_prompt, primary_items_list, storyboard_rules_text, config,
            f"Storyboard Segment '{segment_name}'", global_theme
        )

        return f"# Segment: {segment_name}\n# Global Theme: {global_theme}\n\n{TextCleaner.slim_prompt_text(refined_prompt)}"

    def _process_lyrics_storyboard(self, lyrics, timed_segments, global_theme, mandatory_tokens, style_inspiration_section, config):
        """
        A robust, iterative pipeline for generating a storyboard from lyrics.
        This version processes each lyric segment individually to prevent single-point failures.
        """
        # --- 1. Build Rules ---
        storyboard_rules_text = self._build_storyboard_rules(config, style_inspiration_section)

        # --- 2. Determine Lyric Segments ---
        if timed_segments:
            segments = [(str(i + 1), seg[2]) for i, seg in enumerate(timed_segments)]
        else:
            lines = [line.strip() for line in lyrics.splitlines() if line.strip()]
            segments = [(f"Line {i + 1}", line) for i, line in enumerate(lines)]

        if not segments:
            return "Could not segment lyrics into processable lines or sections."

        # --- 3. Process Each Segment in a Loop (Iterative Generation) ---
        print(f"\033[94m[PromptCrafter] Generating storyboard for {len(segments)} lyric segments iteratively...\033[0m")
        
        # Pre-allocate the results list to maintain order without a second loop.
        processed_prompts = [None] * len(segments)
        # Using a ThreadPoolExecutor to process segments in parallel for performance.
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(segments))) as executor:
            # Map each future to its original index to place results correctly.
            future_to_index = {
                executor.submit(self._generate_and_refine_segment_prompt, name, text, global_theme, storyboard_rules_text, mandatory_tokens, config): i
                for i, (name, text) in enumerate(segments)
            }
            
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                segment_name, _ = segments[index]
                try:
                    # Place the result directly into its final position in the list.
                    processed_prompts[index] = future.result()
                except Exception as exc:
                    error_message = f"Segment '{segment_name}' generated an exception: {exc}"
                    print(f'\033[91m[PromptCrafter] {error_message}\033[0m')
                    # Include the specific exception in the output for better debugging.
                    processed_prompts[index] = f"# Segment: {segment_name}\n# Global Theme: {global_theme}\n\n[Error: {error_message}]"

        return processed_prompts
# ------------------------------------------------------------------------------------
# Utility Nodes
# ------------------------------------------------------------------------------------
"""
The PromptCrafter_ClearCache node is a simple utility. When you run it, it clears the
in-memory cache for all PromptCrafter nodes, or checks the cache's current size.
"""
class PromptCrafter_ClearCache:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "action": (["Clear Cache", "Check Size"], {"default": "Clear Cache", "tooltip": "Choose whether to clear the cache or just check its current size."}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status",)
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /PromptCrafter (v{__version__})/Utils"
    HELP = {
        "title": "PromptCrafter Cache Utility",
        "description": "This is a utility node for managing the internal, in-memory cache. You can choose to:\n- **Clear Cache**: Removes all items from the cache. This is useful if you want to force nodes to re-run expensive API calls (like image descriptions) without restarting ComfyUI.\n- **Check Size**: Reports the current number of items in the cache without clearing it."
    }
    DESCRIPTION = HELP["description"]

    def execute(self, action):
        global CACHE
        if action == "Clear Cache":
            removed_count = CACHE.clear()
            status_message = "Cache cleared. Removed {count} items.".format(count=removed_count)
            print("\033[92m[PromptCrafter] {status}\033[0m".format(status=status_message))
        else: # Check Size
            current_size = CACHE.size()
            max_size = CACHE.max_size
            status_message = "Cache contains {current} of {max} items.".format(current=current_size, max=max_size)
        return (status_message,)

# ------------------------------------------------------------------------------------
# Node mappings
# ------------------------------------------------------------------------------------
# This is the standard way ComfyUI discovers the custom nodes in this file.
# It maps the internal class names to the names that will be used in the backend and displayed in the UI.
NODE_CLASS_MAPPINGS = {
    "PromptCrafter_QnA": PromptCrafter_QnA,
    "PromptCrafter_Captioner": PromptCrafter_Captioner,
    "PromptCrafter_ImageCreator": PromptCrafter_ImageCreator,
    "PromptCrafter_VideoCreator": PromptCrafter_VideoCreator,
    "PromptCrafter_LyricsCreator": PromptCrafter_LyricsCreator,
    "PromptCrafter_ClearCache": PromptCrafter_ClearCache,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_QnA": f"PromptCrafter QnA (v{__version__})",
    "PromptCrafter_Captioner": f"PromptCrafter Image Captioner (v{__version__})",
    "PromptCrafter_ImageCreator": f"PromptCrafter Image Prompt Creator (v{__version__})",
    "PromptCrafter_VideoCreator": f"PromptCrafter Video Prompt Creator (v{__version__})",
    "PromptCrafter_LyricsCreator": f"PromptCrafter Lyrics Creator (v{__version__})",
    "PromptCrafter_ClearCache": f"PromptCrafter Cache Utility (v{__version__})",
}