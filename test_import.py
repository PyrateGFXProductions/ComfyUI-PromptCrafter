import sys
import os

# Add custom nodes path to sys.path
sys.path.append(r"E:\ComfyUI-Easy-Install_torch-2.9.1+cu130\ComfyUI-Easy-Install\ComfyUI\custom_nodes\ComfyUI-PromptCrafter")

try:
    print("Attempting to import PGFX_CinemaVisemeRig from nodes.pgfx_viseme_nodes...")
    from nodes import pgfx_viseme_nodes
    print("Import successful!")
    print(f"Nodes found: {list(pgfx_viseme_nodes.NODE_CLASS_MAPPINGS.keys())}")
except Exception as e:
    import traceback
    print("Import failed!")
    traceback.print_exc()
