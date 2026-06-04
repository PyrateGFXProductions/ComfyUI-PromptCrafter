import json
import os

workflow_path = os.path.join(os.path.dirname(__file__), "..", "workflows", "PGFX_Studio_LTX2_GGUF_Local_EndToEnd.json")

with open(workflow_path, "r") as f:
    wf = json.load(f)

# Find Nodes of Interest
solid_mask_node = None
for n in wf["nodes"]:
    if n["id"] == 249:
        solid_mask_node = n
    if n["id"] == 343:
        stitcher_node = n

# 1. Fix SolidMask (Node 249) value.
# It seems "value" is an input that expects a float, but we can set it via widgets.
# Let's see if we can convert the input back to a widget or just set the widget value
if solid_mask_node:
    # Try to remove the "value" input constraint and set the widget to 1.0 (white/fully opaque)
    new_inputs = [inp for inp in solid_mask_node.get("inputs", []) if inp.get("name") != "value"]
    solid_mask_node["inputs"] = new_inputs
    
    # Ensure the widgets contain a full value (SolidMask normally has value, width, height in widget)
    # the existing widgets are probably the ones not connected as inputs
    if not solid_mask_node.get("widgets_values"):
        solid_mask_node["widgets_values"] = [1.0]
    elif len(solid_mask_node.get("widgets_values")) == 0:
        solid_mask_node["widgets_values"] = [1.0]
    elif isinstance(solid_mask_node["widgets_values"][0], float):
        solid_mask_node["widgets_values"][0] = 1.0 # Ensure it's 1.0 so the mask isn't empty/0

# 2. Fix Stitcher (Node 343)
if stitcher_node:
    new_inputs = [inp for inp in stitcher_node.get("inputs", []) if inp.get("name") != "trigger"]
    stitcher_node["inputs"] = new_inputs

# 3. Write back
with open(workflow_path, "w") as f:
    json.dump(wf, f, indent=2)

print("Finished patching PGFX_Studio_LTX2_GGUF_Local_EndToEnd.json")
