
import os
import sys

# Mock folder_paths if not present (simulating standalone mode first)
print("--- TEST 1: Standalone Mode (No folder_paths) ---")
try:
    import core.pgfx_config as config
    print(f"COMFYUI_ROOT_DIR: {config.COMFYUI_ROOT_DIR}")
    print(f"LLM_MODEL_DIR:    {config.LLM_MODEL_DIR}")
    print(f"QWEN_MODEL_DIR:   {config.QWEN_MODEL_DIR}")
    print(f"CACHE_DIR:        {config.CACHE.cache_dir}")
except ImportError as e:
    print(f"ImportError in standalone mode: {e}")
except Exception as e:
    print(f"Error in standalone mode: {e}")

# Now simulate ComfyUI environment
print("\n--- TEST 2: ComfyUI Mode (Mocked folder_paths) ---")
# Reset config to force reload
if 'core.pgfx_config' in sys.modules:
    del sys.modules['core.pgfx_config']

# Create a mock folder_paths module
class MockFolderPaths:
    base_path = "/mock/comfyui/root"
    models_dir = "/mock/comfyui/root/models"
    @staticmethod
    def get_temp_directory():
        return "/mock/comfyui/root/temp"

sys.modules['folder_paths'] = MockFolderPaths

try:
    import core.pgfx_config as config
    print(f"COMFYUI_ROOT_DIR: {config.COMFYUI_ROOT_DIR}")
    print(f"LLM_MODEL_DIR:    {config.LLM_MODEL_DIR}")
    print(f"QWEN_MODEL_DIR:   {config.QWEN_MODEL_DIR}")
    print(f"CACHE_DIR:        {config.CACHE.cache_dir}")
    
    if config.LLM_MODEL_DIR == "/mock/comfyui/root/models/LLM":
        print("SUCCESS: LLM_MODEL_DIR resolved correctly via folder_paths")
    else:
        print("FAILURE: LLM_MODEL_DIR did NOT resolve via folder_paths")

except Exception as e:
    print(f"Error in ComfyUI mode: {e}")
