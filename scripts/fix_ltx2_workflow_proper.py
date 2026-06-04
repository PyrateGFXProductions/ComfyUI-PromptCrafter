import json
import os

workflow_path = os.path.join(os.path.dirname(__file__), "..", "workflows", "PGFX_Studio_LTX2_GGUF_Local_EndToEnd.json")
backup_path = workflow_path + ".bak_proper"

if not os.path.exists(backup_path):
    import shutil
    shutil.copy2(workflow_path, backup_path)

with open(workflow_path, "r") as f:
    data = json.load(f)

nodes = data.get("nodes", [])
links = data.get("links", [])

# 1. Replace Node 301 (Upsampler)
for node in nodes:
    if node["id"] == 301:
        print("Updating Node 301: LTXVLatentUpsampler -> PGFX_LTXVLatentUpsampler")
        node["type"] = "PGFX_LTXVLatentUpsampler"
        if "properties" in node:
            node["properties"]["Node name for S&R"] = "PGFX_LTXVLatentUpsampler"

# Utility to create new link
def create_link(links_arr, from_node, from_slot, to_node, to_slot, type_name):
    max_id = max([l[0] for l in links_arr]) if links_arr else 0
    new_id = max_id + 1
    new_link = [new_id, from_node, from_slot, to_node, to_slot, type_name]
    links_arr.append(new_link)
    return new_id

# 2. Insert Corrective Mask A (Stage 1)
# Original: 166 (Concat) -> Link 746 -> 289 (Sampler)
# New: 166 (Concat) -> Link 746 -> 400 (Corrective) -> Link NEW -> 289 (Sampler)

mask_a_id = 400
mask_a = {
    "id": mask_a_id,
    "type": "PGFX_LTXVCorrectiveMask",
    "pos": [-1000, 5000],
    "size": [210, 80],
    "flags": {"collapsed": True},
    "order": 41, # Between 39 and 40
    "mode": 0,
    "inputs": [{"name": "samples", "type": "LATENT", "link": 746}],
    "outputs": [{"name": "LATENT", "type": "LATENT", "links": []}],
    "properties": {"Node name for S&R": "PGFX_LTXVCorrectiveMask"}
}

# Update Link 746 destination
for link in links:
    if link[0] == 746:
        link[3] = mask_a_id
        link[4] = 0

# Create new link from 400 to 289
new_link_a = create_link(links, mask_a_id, 0, 289, 4, "LATENT")
mask_a["outputs"][0]["links"].append(new_link_a)

# Update node 289's input link
for node in nodes:
    if node["id"] == 289:
        for inp in node["inputs"]:
            if inp["name"] == "latent_image":
                inp["link"] = new_link_a

nodes.append(mask_a)

# 3. Insert Corrective Mask B (Stage 2)
# Original: 311 (Concat) -> Link 787 -> 306 (Sampler)
# New: 311 (Concat) -> Link 787 -> 401 (Corrective) -> Link NEW -> 306 (Sampler)

mask_b_id = 401
mask_b = {
    "id": mask_b_id,
    "type": "PGFX_LTXVCorrectiveMask",
    "pos": [-300, 5000],
    "size": [210, 80],
    "flags": {"collapsed": True},
    "order": 45, # After 43 (Concat) and 44 (Sampler order?) Wait, 306 order is 44.
    "mode": 0,
    "inputs": [{"name": "samples", "type": "LATENT", "link": 787}],
    "outputs": [{"name": "LATENT", "type": "LATENT", "links": []}],
    "properties": {"Node name for S&R": "PGFX_LTXVCorrectiveMask"}
}

# Update node orders to accommodate
for node in nodes:
    if node["id"] == 306:
        node["order"] = 46
    if node["id"] == 311:
        node["order"] = 44

# Update Link 787 destination
for link in links:
    if link[0] == 787:
        link[3] = mask_b_id
        link[4] = 0

# Create new link from 401 to 306
new_link_b = create_link(links, mask_b_id, 0, 306, 4, "LATENT")
mask_b["outputs"][0]["links"].append(new_link_b)

# Update node 306's input link
for node in nodes:
    if node["id"] == 306:
        for inp in node["inputs"]:
            if inp["name"] == "latent_image":
                inp["link"] = new_link_b

nodes.append(mask_b)

# Save
data["last_node_id"] = max(data["last_node_id"], 401)
data["last_link_id"] = max([l[0] for l in links])

with open(workflow_path, "w") as f:
    json.dump(data, f, indent=2)

print("Successfully patched workflow with PGFX LTXV nodes!")
