
import sys
import json
from pathlib import Path

# This script assumes 'gguf' is installed in the environment.
# It's often a dependency of llama-cpp-python.

try:
    from gguf import GGUFReader
except ImportError:
    print(json.dumps({"error": "The 'gguf' package is not installed or not found. Please run 'pip install gguf'."}))
    sys.exit(1)

def read_gguf_metadata(file_path):
    """
    Reads key metadata from a GGUF file and prints it as JSON.
    """
    metadata_to_extract = [
        'general.architecture',
        'general.name',
        'general.quantization_version',
        'qwen.embedding_length',
        'qwen2.context_length',
        'qwen2.rope.freq_base',
        'tokenizer.ggml.model',
        'tokenizer.chat_template',
    ]
    
    try:
        reader = GGUFReader(file_path, 'r')
        
        found_metadata = {}
        for field in reader.fields.values():
            if field.name in metadata_to_extract:
                if field.parts and len(field.parts) > field.data[0]:
                    value = field.parts[field.data[0]]
                    if isinstance(value, bytes):
                        value = value.decode('utf-8', errors='ignore')
                    found_metadata[field.name] = value

        print(json.dumps(found_metadata, indent=2))

    except Exception as e:
        print(json.dumps({"error": f"Error reading GGUF file: {e}"}))
        sys.exit(1)

if __name__ == "__main__":
    model_path = r"E:\ComfyUI-Easy-Install\ComfyUI\models\LLM\Qwen3-VL-8b-Thinking\Qwen3-VL-8B-Thinking-q8_0.gguf"
    
    if not Path(model_path).exists():
        print(json.dumps({"error": f"Model file not found at {model_path}"}))
        sys.exit(1)
        
    read_gguf_metadata(model_path)
