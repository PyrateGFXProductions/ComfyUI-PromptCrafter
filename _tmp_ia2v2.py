import json, sys
sys.stdout.reconfigure(encoding='utf-8')
path = r'E:\ComfyUI-Easy-Install_torch-2.9.1+cu130\ComfyUI-Easy-Install\ComfyUI\user\default\workflows\LTX_2.3_ia2v_00012_+_RTXSuperScale.json'
with open(path, encoding='utf-8') as f:
    data = json.load(f)

# Show full node 340 properties with proxyWidgets detail
for n in data['nodes']:
    if n['id'] == 340:
        props = n.get('properties', {})
        print('Node 340 properties keys:', list(props.keys()))
        print('widgets_values:', n.get('widgets_values', []))
        print()
        # Show extra properties that might hold widget values
        for k, v in props.items():
            if k != 'proxyWidgets':
                print(f'  {k}: {json.dumps(v, ensure_ascii=False)[:300]}')
            else:
                print(f'  proxyWidgets: {json.dumps(v, ensure_ascii=False)[:500]}')
        print()
        # Show inputs with their labels and link info
        for inp in n.get('inputs', []):
            name = inp.get('name', '?')
            lbl = inp.get('label', '')
            itype = inp.get('type', '?')
            link = inp.get('link', None)
            print(f'  input: name={name:<15} label={str(lbl):<20} type={itype:<15} link={link}')
        print()
        for out in n.get('outputs', []):
            print(f'  output: name={out.get("name","?")} type={out.get("type","?")} links={out.get("links",[])}')

# Also: is the I-A2V node from ComfyUI-LTXVideo? Search for the UUID
