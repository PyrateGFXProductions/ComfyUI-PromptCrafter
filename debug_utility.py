import sys
import os

# Add project path
sys.path.append(r"E:\ComfyUI-Easy-Install_torch-2.9.1+cu130\ComfyUI-Easy-Install\ComfyUI\custom_nodes\ComfyUI-PromptCrafter")

# Mock dependencies to isolate the error
from unittest.mock import MagicMock
mocks = ["torch", "PIL", "numpy", "nodes", "server", "folder_paths"]
for m in mocks:
    sys.modules[m] = MagicMock()

try:
    print("Checking for syntax or logic errors in nodes/pgfx_utility_nodes.py...")
    import nodes.pgfx_utility_nodes
    print("SUCCESS: File imported without errors.")
except Exception as e:
    import traceback
    print("FAILURE: Error detected!")
    traceback.print_exc()
