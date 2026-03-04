import os
import sys
import importlib
import importlib.util
import warnings

from .core import pgfx_config as config

# SpeechBrain 1.x emits a deprecation redirect warning via stdlib inspect
# when older paths are probed by downstream dependencies (e.g. whisperx).
warnings.filterwarnings(
    "ignore",
    message=r"Module 'speechbrain\.pretrained' was deprecated, redirecting to 'speechbrain\.inference'\.",
    category=UserWarning,
)

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
pgfx_ltx2_nodes = _safe_import(".nodes.pgfx_ltx2_nodes", "pgfx_ltx2_nodes")
<<<<<<< HEAD
pgfx_llm_nodes = _safe_import(".nodes.pgfx_llm_nodes", "pgfx_llm_nodes")
=======
>>>>>>> 3be85876973145a59aba6be58b3da295ed05466a

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
    pgfx_ltx2_nodes,
<<<<<<< HEAD
    pgfx_llm_nodes,
=======
>>>>>>> 3be85876973145a59aba6be58b3da295ed05466a
]
NODE_MODULES = [m for m in NODE_MODULES if m is not None]

for module in NODE_MODULES:
    if hasattr(module, "NODE_CLASS_MAPPINGS"):
        NODE_CLASS_MAPPINGS.update(module.NODE_CLASS_MAPPINGS)
    if hasattr(module, "NODE_DISPLAY_NAME_MAPPINGS"):
        NODE_DISPLAY_NAME_MAPPINGS.update(module.NODE_DISPLAY_NAME_MAPPINGS)


def _promote_llm_controls_to_required(node_cls):
    """
    Ensure `llm_device` and `reset_context` are visible by default in ComfyUI.
    Some UIs hide optional widgets, so we promote these two controls to required
    whenever they were declared as optional.
    """
    if getattr(node_cls, "_pgfx_llm_controls_promoted", False):
        return

    original = node_cls.__dict__.get("INPUT_TYPES")
    if original is None:
        return

    def _call_original(cls):
        if isinstance(original, classmethod):
            return original.__func__(cls)
        return original()

    @classmethod
    def _patched_input_types(cls):
        types = _call_original(cls)
        if not isinstance(types, dict):
            return types

        required = dict(types.get("required", {}))
        optional = dict(types.get("optional", {}))

        changed = False
        for key in ("llm_device", "reset_context"):
            if key in optional and key not in required:
                required[key] = optional.pop(key)
                changed = True

        if not changed:
            return types

        patched = dict(types)
        patched["required"] = required
        patched["optional"] = optional
        return patched

    node_cls.INPUT_TYPES = _patched_input_types
    node_cls._pgfx_llm_controls_promoted = True


for _node_cls in NODE_CLASS_MAPPINGS.values():
    _promote_llm_controls_to_required(_node_cls)

# Expose web directory if any module has it
# For now, ComfyGuard is the main one with web assets
WEB_DIRECTORY = "./js"

print(f"\033[92m[PGFX] Loaded {len(NODE_CLASS_MAPPINGS)} nodes successfully.\033[0m")
print("\033[95m[PGFX] PromptCrafter Project: Refactored & Ready.\033[0m")
