import json

workflow_path = "/home/pyrategfx/ComfyUI/custom_nodes/ComfyUI-PromptCrafter/workflows/PGFX_Studio_LTX2_GGUF_Local_EndToEnd.json"
with open(workflow_path, "r") as f:
    wf = json.load(f)

nodes = {str(n["id"]): n for n in wf["nodes"]}
links = {str(l[0]): l for l in wf["links"]}

def trace_latent_links(start_node_id):
    node = nodes.get(str(start_node_id))
    if not node:
        return
    print(f"\n--- Tracing Latent path backwards from Node {start_node_id}: {node['type']} ---")
    for inp in node.get("inputs", []):
        if "latent" in inp.get("name", "").lower() or "samples" in inp.get("name", "").lower():
            link_id = inp.get("link")
            if link_id:
                link = links.get(str(link_id))
                if link:
                    src_id = link[1]
                    src_slot = link[2]
                    print(f"  Input '{inp['name']}' comes from Node {src_id} (Slot {src_slot}): {nodes.get(str(src_id), {}).get('type')}")
                    trace_latent_links(src_id)
                else:
                    print(f"  Input '{inp['name']}' has broken link {link_id}")


trace_latent_links(289)  # SamplerCustomAdvanced (the one failing, node 40 ordered)
trace_latent_links(306)  # The other sampler
