import sys
import os
import traceback

# Setup Paths
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)

# Mock ComfyUI environment
from unittest.mock import MagicMock
mock_modules = [
    "torch", "PIL", "numpy", "nodes", "server", "folder_paths",
    "comfy.utils", "comfy.model_base", "comfy.ldm.modules.attention"
]
for m in mock_modules:
    sys.modules[m] = MagicMock()

try:
    print("Testing absolute import logic...")
    # Import as if we are inside the package
    import nodes.pgfx_utility_nodes as util_nodes
    print("SUCCESS!")
except Exception:
    print("FAILURE!")
    traceback.print_exc()
