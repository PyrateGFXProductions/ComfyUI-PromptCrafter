import urllib.request
import json
import time

def queue_prompt(prompt):
    p = {"prompt": prompt}
    data = json.dumps(p).encode('utf-8')
    req = urllib.request.Request("http://127.0.0.1:8188/prompt", data=data)
    return json.loads(urllib.request.urlopen(req).read().decode('utf-8'))

# Minimal test for PGFX_Studio_Producer
test_prompt = {
    "1": {
        "inputs": {
            "project_name": "ValidationTest",
            "resolution": "854x480",
            "fps": 24,
            "root_output_path": "PGFX_Tests"
        },
        "class_type": "PGFX_Studio_Producer"
    },
    "2": {
        "inputs": {
            "STUDIO_BINDER": ["1", 0],
            "audio": None, # Will probably fail if mandatory, but SoundEngineer is next
            "profile": "None (Manual Input)"
        },
        "class_type": "PGFX_Studio_SoundEngineer"
    }
}

try:
    print("Submitting Studio Producer + Sound Engineer test...")
    result = queue_prompt(test_prompt)
    print(f"SUCCESS: Prompt queued! ID: {result.get('prompt_id')}")
except Exception as e:
    print(f"FAILURE: {e}")
    # Try to read the error response body if possible
    if hasattr(e, 'read'):
        print(f"Server response: {e.read().decode('utf-8')}")
