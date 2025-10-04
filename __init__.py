import os
import requests

from .modules import config, api_clients, nodes, style_profiles

__version__ = "2.0.1" # Define the version here

# Initialize SHARED_SESSION for API clients
config.SHARED_SESSION = requests.Session()
config.SHARED_SESSION.headers.update({
    'User-Agent': f'ComfyUI-PromptCraft/{__version__} (https://github.com/pythongosssss/ComfyUI-PromptCraft)'
})

# Dependency checks and logging (from original promptcrafter.py)
try:
    from langdetect import detect, LangDetectException
    config.LANGDETECT_AVAILABLE = True
except ImportError:
    config.LANGDETECT_AVAILABLE = False
    print("\033[93m[PromptCrafter] Warning: `langdetect` not found. Language detection will be disabled. Run `pip install langdetect` for automatic language support. Falling back to English.\033[0m")

try:
    from pypdf import PdfReader
    config.PYPDF_AVAILABLE = True
except ImportError:
    config.PYPDF_AVAILABLE = False
    print("\033[93m[PromptCrafter] Warning: `pypdf` not found. PDF text extraction from URLs will be disabled. Run `pip install pypdf` to enable this feature.\033[0m")

try:
    from duckduckgo_search import DDGS
    import itertools
    config.DUCKDUCKGO_SEARCH_AVAILABLE = True
except ImportError:
    config.DUCKDUCKGO_SEARCH_AVAILABLE = False
    print("\033[93m[PromptCrafter] Warning: `duckduckgo-search` not found. Web search in QnA mode will be disabled. Run `pip install duckduckgo-search` to enable this feature.\033[0m")

try:
    import librosa
    import librosa.display
    config.LIBROSA_AVAILABLE = True
except ImportError:
    config.LIBROSA_AVAILABLE = False
    print("\033[93m[PromptCrafter] Warning: `librosa` not found. Audio alignment features will be disabled. Run `pip install librosa` to enable this feature.\033[0m")

try:
    import matplotlib.pyplot as plt
    config.MATPLOTLIB_AVAILABLE = True
except ImportError:
    config.MATPLOTLIB_AVAILABLE = False
    print("\033[93m[PromptCrafter] Warning: `matplotlib` not found. Audio alignment features will be disabled. Run `pip install matplotlib` to enable this feature.\033[0m")

# Load style profiles
style_profiles._load_style_profiles()

# Node mappings for ComfyUI
from .modules.nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

WEB_DIRECTORY = "js"