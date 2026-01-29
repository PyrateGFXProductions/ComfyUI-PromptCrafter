import os
import sys

# 1. Initialize ComfyGuard (Security & Stability Tier)
# This MUST happen early to activate the interceptor and API routes
try:
    from . import ComfyGuard
    print("\033[94m[PGFX] ComfyGuard Shield Active.\033[0m")
except Exception as e:
    print(f"\033[91m[PGFX] Error initializing ComfyGuard: {e}\033[0m")

# 2. Consolidated Node Registration hub
# We import the mappings from our modular packages

from .nodes import pgfx_studio_nodes
from .nodes import pgfx_creator_nodes
from .nodes import pgfx_audio_nodes
from .nodes import pgfx_audio_srt
from .nodes import pgfx_audio_subtitles
from .nodes import pgfx_utility_nodes
from .nodes import pgfx_prompt_nodes
from .nodes import pgfx_director_nodes
from .nodes import pgfx_comfyguard_node
from .nodes import pgfx_viseme_nodes

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

for module in NODE_MODULES:
    if hasattr(module, "NODE_CLASS_MAPPINGS"):
        NODE_CLASS_MAPPINGS.update(module.NODE_CLASS_MAPPINGS)
    if hasattr(module, "NODE_DISPLAY_NAME_MAPPINGS"):
        NODE_DISPLAY_NAME_MAPPINGS.update(module.NODE_DISPLAY_NAME_MAPPINGS)

# Expose web directory if any module has it
# For now, ComfyGuard is the main one with web assets
WEB_DIRECTORY = "./ComfyGuard/web"

print(f"\033[92m[PGFX] Loaded {len(NODE_CLASS_MAPPINGS)} nodes successfully.\033[0m")
print("\033[95m[PGFX] PromptCrafter Project: Refactored & Ready.\033[0m")
