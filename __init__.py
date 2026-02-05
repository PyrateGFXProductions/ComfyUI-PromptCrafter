import os
import sys
import importlib
import importlib.util

from .core import pgfx_config as config

# 1. Initialize ComfyGuard (Security & Stability Tier)
# This MUST happen early to activate the interceptor and API routes
try:
    from . import ComfyGuard
    print("\033[94m[PGFX] ComfyGuard Shield Active.\033[0m")
except Exception as e:
    print(f"\033[91m[PGFX] Error initializing ComfyGuard: {e}\033[0m")

# 2. Dependency flags (non-invasive detection)
def _set_flag(flag_name, module_name):
    setattr(config, flag_name, importlib.util.find_spec(module_name) is not None)

_set_flag("LANGDETECT_AVAILABLE", "langdetect")
_set_flag("PYPDF_AVAILABLE", "pypdf")
_set_flag("DUCKDUCKGO_SEARCH_AVAILABLE", "duckduckgo_search")
_set_flag("LIBROSA_AVAILABLE", "librosa")
_set_flag("MATPLOTLIB_AVAILABLE", "matplotlib")
_set_flag("PIEXIF_AVAILABLE", "piexif")

# 3. Consolidated Node Registration hub
# We import the mappings from our modular packages, but guard optional deps.

def _safe_import(rel_path, label):
    try:
        return importlib.import_module(rel_path, package=__name__)
    except Exception as e:
        print(f"\033[93m[PGFX] Skipping {label}: {e}\033[0m")
        return None

pgfx_studio_nodes = _safe_import(".nodes.pgfx_studio_nodes", "pgfx_studio_nodes")
pgfx_creator_nodes = _safe_import(".nodes.pgfx_creator_nodes", "pgfx_creator_nodes")
pgfx_audio_nodes = _safe_import(".nodes.pgfx_audio_nodes", "pgfx_audio_nodes")
pgfx_audio_srt = _safe_import(".nodes.pgfx_audio_srt", "pgfx_audio_srt")
pgfx_audio_subtitles = _safe_import(".nodes.pgfx_audio_subtitles", "pgfx_audio_subtitles")
pgfx_utility_nodes = _safe_import(".nodes.pgfx_utility_nodes", "pgfx_utility_nodes")
pgfx_prompt_nodes = _safe_import(".nodes.pgfx_prompt_nodes", "pgfx_prompt_nodes")
pgfx_director_nodes = _safe_import(".nodes.pgfx_director_nodes", "pgfx_director_nodes")
pgfx_comfyguard_node = _safe_import(".nodes.pgfx_comfyguard_node", "pgfx_comfyguard_node")
pgfx_viseme_nodes = _safe_import(".nodes.pgfx_viseme_nodes", "pgfx_viseme_nodes")

# --- MERGE ALL MAPPINGS ---
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

# Priority list for merging (can be used to override if needed)
NODE_MODULES = [
    pgfx_studio_nodes,
    pgfx_creator_nodes,
    pgfx_audio_nodes,
    pgfx_audio_srt,
    pgfx_audio_subtitles,
    pgfx_utility_nodes,
    pgfx_prompt_nodes,
    pgfx_director_nodes,
    pgfx_comfyguard_node,
    pgfx_viseme_nodes,
]
NODE_MODULES = [m for m in NODE_MODULES if m is not None]

for module in NODE_MODULES:
    if hasattr(module, "NODE_CLASS_MAPPINGS"):
        NODE_CLASS_MAPPINGS.update(module.NODE_CLASS_MAPPINGS)
    if hasattr(module, "NODE_DISPLAY_NAME_MAPPINGS"):
        NODE_DISPLAY_NAME_MAPPINGS.update(module.NODE_DISPLAY_NAME_MAPPINGS)

# Expose web directory if any module has it
# For now, ComfyGuard is the main one with web assets
WEB_DIRECTORY = "./js"

print(f"\033[92m[PGFX] Loaded {len(NODE_CLASS_MAPPINGS)} nodes successfully.\033[0m")
print("\033[95m[PGFX] PromptCrafter Project: Refactored & Ready.\033[0m")
