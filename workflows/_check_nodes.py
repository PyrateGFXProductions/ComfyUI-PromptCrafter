import json
with open('workflows/PGFX_Studio_MusicVideo_Master.json', encoding='utf-8') as f:
    wf = json.load(f)
for n in wf['nodes']:
    if n['id'] in (9, 10, 11):
        print(f"--- Node {n['id']}: {n.get('type','?')} ---")
        for inp in n.get('inputs',[]):
            print(f"  input: {inp['name']} type={inp['type']} link={inp.get('link')}")
        for out in n.get('outputs',[]):
            print(f"  output: {out['name']} type={out['type']} links={out.get('links')}")
        print()
