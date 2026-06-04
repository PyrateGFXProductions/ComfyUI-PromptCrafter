import json
import os

workflow_path = os.path.join(os.path.dirname(__file__), "..", "workflows", "PGFX_Studio_LTX2_GGUF_Local_EndToEnd.json")
with open(workflow_path, "r") as f:
    wf = json.load(f)

links = {}
for l in wf["links"]:
    links[l[0]] = l

for node in wf["nodes"]:
    print(f"Node {node['id']} ({node['type']}):")
    for inp in node.get("inputs", []):
        link_id = inp.get("link")
        if link_id:
            link = links.get(link_id)
            if link:
                print(f"  Input '{inp['name']}' from Node {link[1]} Slot {link[2]}")
            else:
                print(f"  Input '{inp['name']}' has broken link {link_id}")
