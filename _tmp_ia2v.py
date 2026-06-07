import json, sys
sys.stdout.reconfigure(encoding='utf-8')
path = r'E:\ComfyUI-Easy-Install_torch-2.9.1+cu130\ComfyUI-Easy-Install\ComfyUI\user\default\workflows\LTX_2.3_ia2v_00012_+_RTXSuperScale.json'
with open(path, encoding='utf-8') as f:
    data = json.load(f)
# Show proxyWidgets references and their sub-nodes
for n in data['nodes']:
    if n['id'] == 340:
        pws = n.get('properties', {}).get('proxyWidgets', [])
        print(f'proxyWidgets for node 340:')
        for ref in pws:
            print(f'  ref: {ref}')
        break
# Find all nodes referenced by proxyWidgets
proxy_ids = set()
for n in data['nodes']:
    if n['id'] == 340:
        for ref in n.get('properties', {}).get('proxyWidgets', []):
            if len(ref) >= 2:
                proxy_ids.add(int(ref[0]))
print(f'\nProxy node IDs: {sorted(proxy_ids)}')
print(f'\nAll nodes:')
for n in data['nodes']:
    if n['id'] in proxy_ids or n['id'] in (340, 360, 269, 359):
        print(f'  Node {n["id"]:>3}: type={n["type"]:<40} wv={str(n.get("widgets_values", []))[:100]}')
        
# Find the I-A2V node implementation
