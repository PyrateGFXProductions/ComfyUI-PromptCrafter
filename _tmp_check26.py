import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open('workflows/PGFX_Studio_MusicVideo_Master.json', encoding='utf-8') as f:
    d = json.load(f)
for n in d['nodes']:
    if n['id'] == 26:
        print(f'Node 26 type={n["type"]}')
        for i in n.get('inputs', []):
            print(f'  input name={i.get("name","?")} type={i.get("type","?")} link={i.get("link","?")}')
        print(f'  wv={n.get("widgets_values", [])}')
        break
print()
# Also check: does any other node have "latents" as an input name?
for n in d['nodes']:
    for i in n.get('inputs', []):
        if i.get('name') == 'latents':
            print(f'FOUND latents on node {n["id"]} type={n["type"]}')
