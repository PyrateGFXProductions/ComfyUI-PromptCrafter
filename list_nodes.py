import urllib.request
import json

try:
    response = urllib.request.urlopen("http://127.0.0.1:8188/object_info")
    data = json.loads(response.read().decode('utf-8'))
    
    with open("all_nodes.json", "w") as f:
        json.dump(list(data.keys()), f, indent=2)
    print(f"Saved {len(data.keys())} node keys to all_nodes.json")
except Exception as e:
    print(f"Error: {e}")
