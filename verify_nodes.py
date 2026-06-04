import urllib.request
import json
import sys

try:
    response = urllib.request.urlopen("http://127.0.0.1:8188/object_info")
    data = json.loads(response.read().decode('utf-8'))
    
    target_nodes = ["PGFX_UniversalSwitchBox", "PGFX_CinemaVisemeRig", "PGFX_Studio_Producer"]
    results = {}
    
    for node in target_nodes:
        if node in data:
            results[node] = "OK"
        else:
            results[node] = "MISSING"
            
    print(json.dumps(results, indent=2))
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)
