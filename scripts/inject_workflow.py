import json
import os
import shutil

workflow_path = os.path.join(os.path.dirname(__file__), "..", "workflows", "PGFX_Studio_LTX2_GGUF_Local_EndToEnd.json")
backup_path = workflow_path + ".bak"

if not os.path.exists(backup_path):
    shutil.copy2(workflow_path, backup_path)

with open(workflow_path, "r") as f:
    workflow = json.load(f)

nodes = workflow["nodes"]
links = workflow["links"]

max_node_id = max([int(n["id"]) for n in nodes]) if nodes else 0
max_link_id = max([int(l[0]) for l in links]) if links else 0

def new_node_id():
    global max_node_id
    max_node_id += 1
    return max_node_id

def new_link_id():
    global max_link_id
    max_link_id += 1
    return max_link_id

# 1. Find key nodes
producer_node = next((n for n in nodes if n["type"] == "PGFX_Studio_Producer"), None)
cinematographer_node = next((n for n in nodes if n["type"] == "PGFX_Studio_Cinematographer"), None)
stitcher_trigger = next((n for n in nodes if n["type"] == "VHS_VideoCombine"), None)

if not producer_node:
    print("Error: Could not find PGFX_Studio_Producer")
    exit(1)
if not cinematographer_node:
    print("Error: Could not find PGFX_Studio_Cinematographer")
    exit(1)
if not stitcher_trigger:
    # Look for anything with Combine or Save
    stitcher_trigger = next((n for n in nodes if "VideoCombine" in n["type"] or "Save" in n["type"]), None)

print(f"Found Producer: {producer_node['id']}, Cinematographer: {cinematographer_node['id']}, Saver: {stitcher_trigger['id'] if stitcher_trigger else 'None'}")

# 2. Find links for PROJECT_CONFIG and TIMING_MAP
# Producer outputs PROJECT_CONFIG on index 0
project_config_source_id = producer_node["id"]
project_config_source_slot = 0

# Cinematographer takes TIMING_MAP on input "TIMING_MAP"
timing_map_link_id = next((inp["link"] for inp in cinematographer_node.get("inputs", []) if inp["name"] == "TIMING_MAP"), None)
timing_map_source_id = None
timing_map_source_slot = None

if timing_map_link_id:
    timing_map_link = next((l for l in links if l[0] == timing_map_link_id), None)
    if timing_map_link:
        timing_map_source_id = timing_map_link[1]
        timing_map_source_slot = timing_map_link[2]

if not timing_map_source_id:
    # Fallback to Screenwriter or AudioSplitter? Actually, let's just find the link.
    print("Warning: Could not isolate TIMING_MAP source. Checking Director...")
    # It might come straight from audio splitter. We will just hook it up to whatever is connected to Cinematographer.

# 3. Create Queue Node
queue_node_id = new_node_id()
queue_node = {
    "id": queue_node_id,
    "type": "PGFX_Studio_LTX2Queue",
    "pos": [cinematographer_node["pos"][0], cinematographer_node["pos"][1] - 300],
    "size": [315, 130],
    "flags": {},
    "order": cinematographer_node.get("order", 0) - 1,
    "mode": 0,
    "inputs": [
        {
            "name": "PROJECT_CONFIG",
            "type": "DICT",
            "link": None
        },
        {
            "name": "TIMING_MAP",
            "type": "DICT",
            "link": None
        }
    ],
    "outputs": [
        {
            "name": "PROJECT_CONFIG",
            "type": "DICT",
            "links": []
        },
        {
            "name": "TIMING_MAP",
            "type": "DICT",
            "links": []
        },
        {
            "name": "current_set_index",
            "type": "INT",
            "links": []
        },
        {
            "name": "total_sets",
            "type": "INT",
            "links": []
        },
        {
            "name": "is_final_set",
            "type": "BOOLEAN",
            "links": []
        }
    ],
    "properties": {
        "Node name for S&R": "PGFX_Studio_LTX2Queue"
    },
    "widgets_values": [
        True,
        False
    ]
}
nodes.append(queue_node)

# Create Links for Queue Node
l1_id = new_link_id()
l1 = [l1_id, project_config_source_id, project_config_source_slot, queue_node_id, 0, "DICT"]
links.append(l1)
queue_node["inputs"][0]["link"] = l1_id
queue_node["outputs"][0]["links"] = [] # Currently nothing expects it to pass through, but we could make cinematographer connect here.

if timing_map_source_id:
    l2_id = new_link_id()
    l2 = [l2_id, timing_map_source_id, timing_map_source_slot, queue_node_id, 1, "DICT"]
    links.append(l2)
    queue_node["inputs"][1]["link"] = l2_id


# 4. Create Stitcher Node
stitcher_node_id = new_node_id()
stitcher_node = {
    "id": stitcher_node_id,
    "type": "PGFX_Studio_Stitcher",
    "pos": [stitcher_trigger["pos"][0] + 400 if stitcher_trigger else 1000, stitcher_trigger["pos"][1] if stitcher_trigger else 1000],
    "size": [315, 130],
    "flags": {},
    "order": getattr(stitcher_trigger, "get", lambda x, y: 0)("order", 999) + 1 if stitcher_trigger else 999,
    "mode": 0,
    "inputs": [
        {
            "name": "PROJECT_CONFIG",
            "type": "DICT",
            "link": None
        },
        {
            "name": "is_final_set",
            "type": "BOOLEAN",
            "link": None
        },
        {
            "name": "trigger",
            "type": "*",
            "link": None
        }
    ],
    "outputs": [
        {
            "name": "final_video_path",
            "type": "STRING",
            "links": []
        }
    ],
    "properties": {
        "Node name for S&R": "PGFX_Studio_Stitcher"
    },
    "widgets_values": [
        "LTX2_Part_",
        False
    ]
}
nodes.append(stitcher_node)

# Link Stitcher PROJECT_CONFIG to Queue's passthrough
l3_id = new_link_id()
l3 = [l3_id, queue_node_id, 0, stitcher_node_id, 0, "DICT"]
links.append(l3)
stitcher_node["inputs"][0]["link"] = l3_id
queue_node["outputs"][0]["links"].append(l3_id)

# Link Stitcher is_final_set to Queue
l4_id = new_link_id()
l4 = [l4_id, queue_node_id, 4, stitcher_node_id, 1, "BOOLEAN"]
links.append(l4)
stitcher_node["inputs"][1]["link"] = l4_id
queue_node["outputs"][4]["links"].append(l4_id)

# Link Stitcher Trigger to Save Node Outputs or any other output
if stitcher_trigger and "outputs" in stitcher_trigger and len(stitcher_trigger["outputs"]) > 0:
    t_out_slot = 0 # Default to first output
    l5_id = new_link_id()
    l5 = [l5_id, stitcher_trigger["id"], t_out_slot, stitcher_node_id, 2, "*"]
    links.append(l5)
    stitcher_node["inputs"][2]["link"] = l5_id
    if not isinstance(stitcher_trigger["outputs"][t_out_slot].get("links"), list):
        stitcher_trigger["outputs"][t_out_slot]["links"] = []
    stitcher_trigger["outputs"][t_out_slot]["links"].append(l5_id)

workflow["last_node_id"] = max_node_id
workflow["last_link_id"] = max_link_id

with open(workflow_path, "w") as f:
    json.dump(workflow, f, indent=2)

print("Successfully injected PGFX_Studio_LTX2Queue and PGFX_Studio_Stitcher into the JSON workflow!")
