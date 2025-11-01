import os
import requests

from .modules import config, api_clients, nodes, style_profiles, organization_profiles, captioner_profiles

# Initialize SHARED_SESSION for API clients
config.SHARED_SESSION = requests.Session()
config.SHARED_SESSION.headers.update({
    'User-Agent': f'ComfyUI-PromptCrafter (https://github.com/PyrateGFX/ComfyUI-PromptCrafter)'
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

try:
    import piexif
    import piexif.helper
    config.PIEXIF_AVAILABLE = True
except ImportError:
    config.PIEXIF_AVAILABLE = False
    print("\033[93m[PromptCrafter] Warning: `piexif` not found. Adding captions to image metadata will be disabled. Run `pip install piexif` to enable this feature.\033[0m")

# Load style profiles
style_profiles._load_style_profiles()

# Load organization profiles
organization_profiles._load_organization_profiles()

# Load captioner profiles
captioner_profiles._load_captioner_profiles()

# Perform a non-blocking check for local server status at startup
try:
    # This check is now handled inside the api_clients module itself
    # to ensure it's always non-blocking.
    # The call is kept here to trigger the check at startup.
    api_clients.check_local_server_status() 
except Exception as e:
    print(f"\033[91m[PromptCrafter] A critical error occurred during startup server checks: {e}\033[0m")

# Node mappings for ComfyUI
from .modules.nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .modules.prompt_nodes import NODE_CLASS_MAPPINGS as PROMPT_NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as PROMPT_NODE_DISPLAY_NAME_MAPPINGS

NODE_CLASS_MAPPINGS.update(PROMPT_NODE_CLASS_MAPPINGS)
NODE_DISPLAY_NAME_MAPPINGS.update(PROMPT_NODE_DISPLAY_NAME_MAPPINGS)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]

WEB_DIRECTORY = "js"