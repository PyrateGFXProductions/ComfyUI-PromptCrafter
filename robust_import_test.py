from unittest.mock import MagicMock
import sys
import os
import traceback

# Add project root to sys.path
root_path = r"E:\ComfyUI-Easy-Install_torch-2.9.1+cu130\ComfyUI-Easy-Install\ComfyUI\custom_nodes\ComfyUI-PromptCrafter"
sys.path.append(root_path)

# Mock common dependencies
mock_modules = ["torch", "torchvision", "torchvision.transforms", "nodes", "server", "PIL", "g2p_en", "nltk", "folder_paths"]
for mod in mock_modules:
    try:
        __import__(mod)
    except ImportError:
        print(f"Module {mod} not found, mocking...")
        sys.modules[mod] = MagicMock()

try:
    print("\nAttempting import of PGFX_Studio_Producer...")
    import nodes.pgfx_studio_nodes as s_nodes
    print("SUCCESS: Studio Module imported!")
    print(f"Nodes in MAPPINGS: {list(s_nodes.NODE_CLASS_MAPPINGS.keys())}")
except Exception:
    print("FAILURE: Studio Import failed!")
    traceback.print_exc()
