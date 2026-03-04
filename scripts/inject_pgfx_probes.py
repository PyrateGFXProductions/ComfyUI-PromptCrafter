import json
import os

workflow_path = "/home/pyrategfx/ComfyUI/custom_nodes/ComfyUI-PromptCrafter/workflows/PGFX_Studio_LTX2_GGUF_Local_EndToEnd.json"

with open(workflow_path, 'r') as f:
    data = json.load(f)

nodes = data["nodes"]
links = data["links"]

def get_next_id():
    max_id = 0
    for node in nodes:
        max_id = max(max_id, node["id"])
    return max_id + 1

def get_next_link_id():
    max_id = 0
    for link in links:
        max_id = max(max_id, link[0])
    return max_id + 1

def add_probe(source_node_id, source_output_idx, label, pos):
    probe_id = get_next_id()
    new_link_id = get_next_link_id()
    
    # 1. Update the original link that goes FROM source_node_id TO its target
    # This is complex. Better: just add the probe as a SINK (output unused)
    # or as a PASSTHROUGH. Let's do PASSTHROUGH.
    
    # Find all links CURRENTLY coming from source_node_id, source_output_idx
    affected_links = []
    for link in links:
        if link[1] == source_node_id and link[2] == source_output_idx:
            affected_links.append(link)
    
    if not affected_links:
        print(f"No links found for {source_node_id}[{source_output_idx}]")
        return
    
    # Create the Probe node
    probe_node = {
        "id": probe_id,
        "type": "PGFX_LatentProbe",
        "pos": pos,
        "size": [210, 80],
        "flags": {},
        "order": 100, # Run late/whenever needed
        "inputs": [
            {
                "name": "samples",
                "type": "LATENT",
                "link": -1 # To be filled
            }
        ],
        "outputs": [
            {
                "name": "LATENT",
                "type": "LATENT",
                "links": []
            }
        ],
        "widgets_values": [label],
        "properties": {"Node name for S&R": "PGFX_LatentProbe"}
    }
    nodes.append(probe_node)
    
    # Create link from Source to Probe
    source_to_probe_link_id = get_next_link_id()
    source_to_probe_link = [source_to_probe_link_id, source_node_id, source_output_idx, probe_id, 0, "LATENT"]
    links.append(source_to_probe_link)
    probe_node["inputs"][0]["link"] = source_to_probe_link_id
    
    # Update all original links to start from Probe instead of Source
    for link in affected_links:
        # Create a link from Probe to Original Target
        probe_to_target_link_id = get_next_link_id()
        # link format: [id, from_node, from_slot, to_node, to_slot, type]
        target_node_id = link[3]
        target_slot_idx = link[4]
        
        new_link = [probe_to_target_link_id, probe_id, 0, target_node_id, target_slot_idx, "LATENT"]
        links.append(new_link)
        
        # Update target node's input link reference
        for node in nodes:
            if node["id"] == target_node_id:
                for inp in node["inputs"]:
                    if inp["link"] == link[0]:
                        inp["link"] = probe_to_target_link_id
        
        # Remove old link
        links.remove(link)

# We want probes at:
# 1. Sampler 1 Output (289, 0)
# 2. Separate Video Output (245, 0)
# 3. Upsampler Output (301, 0)
# 4. Concat Output (311, 0)
# 5. Corrective Mask Output (401, 0)

add_probe(289, 0, "Stage 1 Sampler Out", [-1000, 5200])
add_probe(245, 0, "Stage 1 Separate Out", [-700, 5200])
add_probe(301, 0, "Stage 1 Upscale Out", [-400, 5200])
add_probe(311, 0, "Stage 2 Concat Out", [-100, 5200])
add_probe(401, 0, "Stage 2 Corrected Out", [200, 5200])

data["last_node_id"] = get_next_id() - 1
data["last_link_id"] = get_next_link_id() - 1

with open(workflow_path, 'w') as f:
    json.dump(data, f, indent=2)

print("Injected 5 probes into workflow.")
