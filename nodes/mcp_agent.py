"""Real ComfyUI MCP agent runtime for PGFX_LogoDesignerMCPAgent.

Implements the same semantics as a ComfyUI MCP server: a genuine iterative
tool loop where each tool call is executed FOR REAL against the running
ComfyUI (template catalog, node/model discovery, UI->API workflow
conversion, /prompt submission, polling, output download) and its result is
fed back to the LLM until the request is fulfilled.
"""

import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

UI_ONLY_NODE_TYPES = {"Note", "MarkdownNote", "PrimitiveNode", "GetNode", "SetNode", "Reroute"}

SAVE_NODE_TYPES = {
    "SaveImage", "SaveVideo", "SaveAnimatedWEBP", "SaveAnimatedPNG",
    "PreviewImage", "PreviewVideo", "VHS_VideoCombine", "VHS_VideoSave",
    "SaveAudio", "SaveAudioWebsocket",
}

OUTPUT_TYPE_HINTS = ("IMAGE", "VIDEO", "GIF", "AUDIO", "MASK", "VHS_VIDEO", "WEBP")

NODE_MODE_MUTED = 2
NODE_MODE_BYPASS = 4

BUILTIN_TEMPLATE_FIXES = {
    "video_minimax_h3_r2v": {
        119: "MiniMaxH3\\minimax_h3_video_vae_fp16.safetensors",
        120: "MiniMaxH3\\minimax_h3_audio_vae_fp32.safetensors",
        127: "MiniMaxH3\\minimax_h3_ref2va_pruned_nvfp4.safetensors",
        128: "MiniMaxH3\\qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
        145: "MiniMaxH3\\h3-realism-people-t2v-i2v-r2v.safetensors",
    }
}


def _pkg_dir():
    return os.path.dirname(os.path.abspath(__file__))


def template_catalog_dir():
    for rel in ("resources", "templates"):
        cand = os.path.join(_pkg_dir(), rel)
        if os.path.isdir(cand):
            return cand
    return os.path.join(_pkg_dir(), "resources")


def _json_default(o):
    if hasattr(o, "item"):
        try:
            return o.item()
        except Exception:
            pass
    return str(o)


def _http_get(comfyui_url, path, params=None, timeout=15):
    import requests
    resp = requests.get(f"{comfyui_url}{path}", params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _http_post(comfyui_url, path, payload, timeout=15):
    import requests
    resp = requests.post(f"{comfyui_url}{path}", json=payload, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:1000]}")
    return resp.json()


_downloads = {}
_downloads_lock = threading.Lock()


def _comfy_bin():
    return os.environ.get("COMFY_BIN") or shutil.which("comfy") or "comfy"


def _comfy_cli(args, timeout=300):
    """Run a comfy-cli subcommand with --json --where local and unwrap envelope/1."""
    full = [_comfy_bin()] + list(args)
    if "--json" not in full:
        full.append("--json")
    if "--where" not in full:
        full += ["--where", "local"]
    try:
        p = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return {"error": f"comfy CLI not found (looked for '{_comfy_bin()}'). Install comfy-cli or set COMFY_BIN.", "unsupported": True}
    except subprocess.TimeoutExpired:
        return {"error": f"comfy CLI timed out after {timeout}s"}
    raw = (p.stdout or "").strip()
    data = None
    if raw:
        try:
            data = json.loads(raw)
        except Exception:
            return {"error": "comfy CLI returned non-JSON output", "stdout_tail": raw[-1000:], "stderr_tail": (p.stderr or "")[-1000:]}
    if isinstance(data, dict) and data.get("envelope") == "envelope/1":
        data = data.get("data", data)
    if p.returncode != 0:
        if not isinstance(data, dict):
            data = {}
        data["error"] = data.get("error") or (p.stderr or "").strip()[-1000:] or f"comfy CLI exited {p.returncode}"
        if p.stderr:
            data["stderr_tail"] = (p.stderr or "")[-1000:]
    return data if data is not None else {"error": "comfy CLI produced no output"}


def load_object_info(comfyui_url):
    return _http_get(comfyui_url, "/object_info")


def iter_installed_templates():
    try:
        import comfyui_workflow_templates
        infra = getattr(comfyui_workflow_templates, "infra", None)
        if infra is not None and hasattr(infra, "iter_templates"):
            for t in infra.iter_templates():
                yield t
    except Exception:
        return
    try:
        from comfyui_workflow_templates import iter_templates
        for t in iter_templates():
            yield t
    except Exception:
        return


def _template_meta(t):
    name = getattr(t, "name", None) or str(getattr(t, "title", "")).split(":")[0].strip()
    title = getattr(t, "title", None) or getattr(t, "name", "")
    return name, title


_QUERY_STOPWORDS = {"to", "of", "for", "and", "the", "a", "an", "in", "on", "with", "from", "at", "by"}


def _matches_query(query, hay):
    if not query:
        return True
    tokens = [t for t in str(query).lower().split() if t and t not in _QUERY_STOPWORDS]
    hay = str(hay).lower()
    return not tokens or all(t in hay for t in tokens)


def search_templates(query=""):
    results = []
    seen = set()
    for t in iter_installed_templates():
        try:
            name, title = _template_meta(t)
        except Exception:
            continue
        if not name:
            continue
        key = str(name).lower()
        if key in seen:
            continue
        seen.add(key)
        if not _matches_query(query, f"{name} {title}"):
            continue
        results.append({"name": name, "title": title})
    results.sort(key=lambda r: r["name"])
    builtin = []
    for f in sorted(glob_files(template_catalog_dir(), "*.json")):
        file_name = os.path.splitext(os.path.basename(f))[0]
        builtin.append({"name": file_name, "title": file_name, "builtin": True, "path": f})
    if not _matches_query(query, " ".join(b["name"] for b in builtin) + " minimax mini max video h3 image audio reference ref2v r2v"):
        for b in list(builtin):
            if not _matches_query(query, b["name"]):
                builtin.remove(b)
    results.extend(builtin)
    return results


def glob_files(directory, pattern):
    import glob
    if not os.path.isdir(directory):
        return []
    return glob.glob(os.path.join(directory, pattern))


def _load_template_json():
    path = os.path.join(_pkg_dir(), "resources", "video_minimax_h3_r2v.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return None


def _resolve_template_source(name):
    builtin_map = {"video_minimax_h3_r2v": _load_template_json,
                   "minimax_h3_r2v": _load_template_json}
    if name in builtin_map and builtin_map[name] is not None:
        return builtin_map[name](), True
    only_ext = os.path.splitext(name)[1]
    if only_ext:
        name = os.path.splitext(name)[0]
        if name in builtin_map:
            return builtin_map[name](), True
    return None, False


def fetch_template_json(name):
    ui, builtin = _resolve_template_source(name)
    if ui is not None:
        return ui, builtin
    for t in iter_installed_templates():
        try:
            tname, _ = _template_meta(t)
        except Exception:
            continue
        if tname == name:
            raw = None
            try:
                raw = t.template_json
            except AttributeError:
                raw = getattr(t, "json", None) or getattr(t, "raw_json", None)
            if callable(raw):
                raw = raw()
            if raw is None:
                txt = getattr(t, "template", None)
                if callable(txt):
                    txt = txt()
                if isinstance(txt, str):
                    try:
                        raw = json.loads(txt)
                    except Exception:
                        raw = None
            if raw is None:
                data = getattr(t, "data", None)
                if data is not None:
                    raw = data
            if isinstance(raw, dict):
                return raw, False
    return None, False


def apply_builtin_fixes(name, template, reference_audio=None):
    fixes = BUILTIN_TEMPLATE_FIXES.get(name)
    if not fixes:
        return template
    nodes = template.get("nodes", [])
    for n in nodes:
        nid = str(n.get("id", ""))
        value = fixes.get(nid)
        if value is None and nid.isdigit():
            value = fixes.get(int(nid))
        if value is None:
            continue
        wv = n.get("widgets_values") or []
        if wv:
            wv[0] = value
            n["widgets_values"] = wv
    if reference_audio:
        _wire_reference_audio(template, reference_audio)
    return template


def _wire_reference_audio(template, audio_filename):
    nodes = template.get("nodes", []) or []
    n136 = next((n for n in nodes if str(n.get("id")) == "136"), None)
    if n136 is None:
        return template
    ins_list = n136.get("inputs") or []
    tgt = None
    in_slot = None
    for i, ins in enumerate(ins_list):
        if ins.get("name") == "ref_audios.ref_audio_0":
            tgt, in_slot = ins, i
            break
    if tgt is None:
        return template
    links = template.get("links", []) or []
    used = [l[0] for l in links if isinstance(l, list) and l]
    new_link = (max(used) + 1) if used else 0
    nid = max((n.get("id", 0) for n in nodes), default=0) + 1
    tgt["link"] = new_link
    links.append([new_link, nid, 0, 136, in_slot, "AUDIO"])
    nodes.append({"id": nid, "type": "LoadAudio", "pos": [600, 260], "size": [260, 100],
                  "inputs": [], "outputs": [{"name": "audio", "type": "AUDIO", "link": new_link, "slot_index": 0}],
                  "widgets_values": [audio_filename],
                  "properties": {"Node name for S&R": "LoadAudio"}, "mode": 0})
    template["links"] = links
    return template


def apply_user_context(ui_graph, object_info=None, image_ref=None, audio_ref=None, prompt=None):
    """Deterministically wire the USER's prompt + reference media into a template.

    The LLM should NOT be trusted to author the prompt or copy media filenames
    (weak local models echo the template's built-in demo). We overwrite the
    relevant slots directly so the generated output always uses the user's
    actual prompt and reference image/audio, never the demo content.
    """
    if not (image_ref or audio_ref or prompt):
        return []
    if prompt is not None:
        prompt = prompt if str(prompt).strip() else None
    if not (image_ref or audio_ref or prompt):
        return []
    changes = []
    for n in ui_graph.get("nodes", []) or []:
        ntype = n.get("type", "")
        nid = str(n.get("id"))
        if image_ref and ntype == "LoadImage" and set_slot(ui_graph, f"{nid}.image", image_ref, object_info):
            changes.append(f"{nid}.image -> {image_ref}")
        if audio_ref and ntype == "LoadAudio" and set_slot(ui_graph, f"{nid}.audio", audio_ref, object_info):
            changes.append(f"{nid}.audio -> {audio_ref}")
        if prompt:
            if ntype == "PrimitiveStringMultiline" and set_slot(ui_graph, f"{nid}.value", prompt, object_info):
                changes.append(f"{nid}.value -> <prompt>")
            elif ntype == "CLIPTextEncode" and set_slot(ui_graph, f"{nid}.text", prompt, object_info):
                changes.append(f"{nid}.text -> <prompt>")
    return changes


def _spec_default(spec_in):
    if not spec_in or not isinstance(spec_in, list) or len(spec_in) < 2:
        return None
    first, opts = spec_in[0], spec_in[1]
    if isinstance(opts, dict) and opts.get("default") is not None:
        return opts["default"]
    if isinstance(first, list) and first:
        return first[0]
    return None


def _is_primitive_widget(spec_in):
    if not spec_in or not isinstance(spec_in, list) or not spec_in:
        return False
    first = spec_in[0]
    if isinstance(first, list):
        return True
    if not isinstance(first, str):
        return False
    if len(spec_in) < 2 or not isinstance(spec_in[1], dict):
        return False
    opts = spec_in[1]
    if "default" in opts or "options" in opts:
        return True
    if first in ("INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"):
        return True
    return False


def _sanitize_widget(value, spec_in):
    if not spec_in or not isinstance(spec_in, list) or len(spec_in) < 2:
        return value
    first, opts = spec_in[0], spec_in[1]
    if isinstance(first, list):
        if isinstance(value, str) and first and value not in first:
            default = opts.get("default") if isinstance(opts, dict) else None
            if isinstance(default, str) and default in first:
                return default
            return first[0]
        return value
    if first in ("INT", "FLOAT") and isinstance(opts, dict):
        try:
            mn = opts.get("min")
            mx = opts.get("max")
            if mn is not None and value < mn:
                return opts["default"] if opts.get("default") is not None else mn
            if mx is not None and value > mx:
                return opts["default"] if opts.get("default") is not None else mx
        except (TypeError, ValueError):
            pass
    return value


def _resolve_reroute(node_id, slot, reroute_src):
    seen = set()
    curr_id, curr_slot = node_id, slot
    while str(curr_id) in reroute_src:
        if curr_id in seen:
            break
        seen.add(curr_id)
        curr_id, curr_slot = reroute_src[str(curr_id)]
    return curr_id, curr_slot


def ui_to_api(ui_graph, object_info):
    out = {}
    nodes = {n.get("id"): n for n in ui_graph.get("nodes", [])}
    src_by_link = {}
    reroute_src = {}
    for link in ui_graph.get("links", []) or []:
        if isinstance(link, list) and len(link) >= 5:
            src_by_link[link[0]] = (link[1], link[2])
            tgt_type = nodes.get(link[3], {}).get("type", "")
            if tgt_type in ("Reroute", "RerouteUI", "RerouteInput"):
                reroute_src[str(link[3])] = (link[1], link[2])
    for n in nodes.values():
        ntype = n.get("type", "")
        if ntype in UI_ONLY_NODE_TYPES:
            continue
        mode = n.get("mode", 0)
        if mode in (NODE_MODE_MUTED, NODE_MODE_BYPASS):
            continue
        spec = object_info.get(ntype)
        if not spec:
            continue
        required = spec.get("input", {}).get("required", {}) or {}
        optional = spec.get("input", {}).get("optional", {}) or {}
        input_order = list(required.keys()) + [k for k in optional.keys() if k not in required]
        node_inputs = n.get("inputs", []) or []
        widgets = n.get("widgets_values", []) or []
        widget_idx = 0
        inp = {}
        linked = set()
        for idx, ins in enumerate(node_inputs):
            if isinstance(ins, dict):
                lid = ins.get("link")
                src = src_by_link.get(lid) if lid is not None else None
                if src is None:
                    continue
                iname = ins.get("name", "")
                nid0, slot0 = _resolve_reroute(src[0], src[1], reroute_src)
                inp[iname] = [str(nid0), slot0]
                linked.add((iname, idx))
        for name in input_order:
            base_linked = [key for key in linked if key[0] == name]
            if base_linked:
                continue
            if any(k.startswith(name + ".") for k in inp):
                continue
            spec_in = required.get(name)
            if spec_in is None:
                spec_in = optional.get(name)
            if not _is_primitive_widget(spec_in):
                continue
            if widget_idx < len(widgets):
                value = widgets[widget_idx]
                widget_idx += 1
                if value == "" or value is None:
                    value = _spec_default(spec_in)
                inp[name] = _sanitize_widget(value, spec_in)
            else:
                default = _spec_default(spec_in)
                if default is not None:
                    inp[name] = default
        out[str(n.get("id"))] = {"class_type": ntype, "inputs": inp}
    return out


def normalize_api_prompt(workflow, object_info):
    if isinstance(workflow, dict):
        if "nodes" in workflow and "links" in workflow:
            return ui_to_api(workflow, object_info)
        if all(isinstance(v, dict) and "class_type" in v for v in workflow.values()):
            return workflow
    raise ValueError("Workflow must be UI-format (nodes/links) or API-format (class_type map)")


def check_graph_io(api, object_info):
    save_count = 0
    produce_count = 0
    named = []
    for node in api.values():
        ctype = node.get("class_type")
        if ctype in SAVE_NODE_TYPES:
            save_count += 1
        spec = (object_info or {}).get(ctype)
        if spec:
            outs = spec.get("output_types") or spec.get("output") or []
            if any(any(h in str(o).upper() for h in OUTPUT_TYPE_HINTS) for o in outs):
                produce_count += 1
                named.append(ctype)
    notes = []
    if save_count == 0:
        notes.append("No SaveImage/SaveVideo/save node in the graph - outputs may exist but be unretrievable.")
    if produce_count == 0:
        notes.append("Graph has NO node producing IMAGE/VIDEO/GIF/AUDIO output - the job will produce nothing retrievable.")
    return {"save_count": save_count, "produce_count": produce_count, "producers": named, "notes": notes,
            "block": produce_count == 0}


def _normalize_node_errors(node_errors):
    if not isinstance(node_errors, dict):
        return None
    out = []
    for nid, info in node_errors.items():
        if not isinstance(info, dict):
            continue
        for e in info.get("errors") or []:
            if not isinstance(e, dict):
                continue
            extra = e.get("extra_info")
            if not isinstance(extra, dict):
                extra = {}
            out.append({
                "node_id": str(nid),
                "message": e.get("message"),
                "details": e.get("details"),
                "input_name": extra.get("input_name"),
            })
    return out


def submit_prompt(comfyui_url, api_prompt, timeout=20):
    import uuid
    import requests
    payload = {"prompt": api_prompt, "client_id": "pgfx-mcp-agent-%s" % uuid.uuid4().hex[:8]}
    try:
        resp = requests.post(f"{comfyui_url}/prompt", json=payload, timeout=timeout)
    except requests.exceptions.ConnectionError:
        return {"ok": False, "error": "ComfyUI connection refused (is the server running?)"}
    body = {}
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text[:400]}
    if resp.status_code >= 400:
        node_errors = body.get("node_errors") if isinstance(body, dict) else None
        if not node_errors and isinstance(body, dict):
            node_errors = (body.get("error_details") or {}).get("node_errors")
        return {"ok": False, "http": resp.status_code,
                "error": (body.get("error") if isinstance(body, dict) else resp.text[:400]),
                "node_errors": _normalize_node_errors(node_errors)}
    if isinstance(body, dict):
        body["ok"] = True
    return body


def wait_for_completion(comfyui_url, prompt_id, timeout=300, log=None):
    import requests
    start = time.time()
    conn_losses = 0
    last_log = 0.0
    while time.time() - start < timeout:
        now = time.time()
        if log is not None and now - last_log >= 30:
            last_log = now
            try:
                log(f"job {prompt_id} still running ({int(now - start)}s elapsed / {int(timeout)}s budget)")
            except Exception:
                last_log = 0.0
        try:
            resp = requests.get(f"{comfyui_url}/history/{prompt_id}", timeout=5)
            conn_losses = 0
        except requests.exceptions.ConnectionError:
            conn_losses += 1
            if conn_losses >= 6:
                return None, False, "ComfyUI connection lost while awaiting job (server restarted/crashed)"
            time.sleep(2)
            continue
        except Exception:
            conn_losses += 1
            time.sleep(1)
            continue
        if resp.status_code == 200:
            history = resp.json()
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") in ("error",):
                    return entry, False, f"workflow error: {status.get('messages', [])}"
                if status.get("completed"):
                    return entry, True, ""
        time.sleep(4)
    return None, False, f"timeout after {timeout}s"


def _output_items(record):
    for node_out in (record.get("outputs", {}) or {}).values():
        for key in ("images", "gifs", "videos", "audio", "files"):
            for item in node_out.get(key, []) or []:
                yield item


def download_outputs(comfyui_url, record, out_dir, can_preview):
    import requests
    tensor = None
    pil_reader = None
    if can_preview:
        try:
            from PIL import Image as _PIL
            pil_reader = _PIL.open
        except Exception:
            pil_reader = None
    saved = []
    for item in _output_items(record):
        fname = item.get("filename")
        if not fname:
            continue
        sub = item.get("subfolder", "")
        ftype = item.get("type", "output")
        try:
            resp = requests.get(f"{comfyui_url}/view", params={"filename": fname, "subfolder": sub, "type": ftype}, timeout=15)
            resp.raise_for_status()
        except Exception as e:
            saved.append(fname + f" (download failed: {e})")
            continue
        dest_dir = os.path.join(out_dir, sub) if sub else out_dir
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, os.path.basename(fname))
        with open(dest, "wb") as fh:
            fh.write(resp.content)
        saved.append(dest)
        if tensor is None and pil_reader is not None:
            try:
                img = pil_reader(io.BytesIO(resp.content))
                img_np = np_img(img)
                tensor = img_np
            except Exception:
                pass
    return saved, tensor


def np_img(pil_img):
    import numpy as np
    img = pil_img.convert("RGB")
    arr = np.array(img).astype(np.float32) / 255.0
    return torch_from(arr)


def torch_from(arr):
    import torch
    return torch.from_numpy(arr)[None,]


def preview_tensor_from_file(path):
    try:
        from PIL import Image as _PIL
        img = _PIL.open(path)
        return np_img(img)
    except Exception:
        return None


def video_preview_tensor(path):
    if not path or not os.path.isfile(str(path)):
        return None
    name = str(path).lower()
    if not name.endswith((".mp4", ".mov", ".webm", ".avi", ".mkv")):
        return None
    import subprocess
    png = str(path) + ".preview.png"
    try:
        r = subprocess.run([_find_ffmpeg(), "-y", "-i", str(path), "-frames:v", "1", png],
                           capture_output=True, timeout=90)
        if r.returncode != 0 or not os.path.isfile(png):
            return None
        return preview_tensor_from_file(png)
    except Exception:
        return None


def _find_ffmpeg():
    import shutil
    candidates = []
    env_ff = os.environ.get("FFMPEG")
    if env_ff:
        candidates.append(env_ff)
    try:
        w = shutil.which("ffmpeg")
        if w:
            candidates.append(w)
    except Exception:
        pass
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.append(os.path.join(local, "Microsoft", "WinGet", "Links", "ffmpeg.exe"))
    for c in candidates:
        if c and os.path.isfile(str(c)):
            return str(c)
    return "ffmpeg"


def _ensure_video_preview(saved, tensor):
    if tensor is None and saved:
        for p in saved:
            tensor = video_preview_tensor(p)
            if tensor is not None:
                break
    return tensor


def list_model_files(comfyui_url, folder=""):
    out = []
    if folder:
        try:
            resp = _http_get(comfyui_url, f"/models/{folder}")
            for f in resp.get("files", []) or []:
                out.append(f.get("name", ""))
        except Exception:
            try:
                found = _inprocess_models(folder)
                out = found
            except Exception:
                out = []
    else:
        try:
            resp = _http_get(comfyui_url, "/models")
            out = resp.get("models", [])
        except Exception:
            out = []
    return out


def _inprocess_models(folder):
    import folder_paths
    names = folder_paths.get_filename_list(folder)
    return names


def list_node_names(comfyui_url, query="", category=""):
    try:
        info = load_object_info(comfyui_url)
    except Exception:
        info = {}
    results = []
    query_l = query.lower()
    cat_l = category.lower()
    for cls, spec in sorted(info.items()):
        disp = spec.get("display_name", "") or cls
        node_cat = spec.get("category", "")
        if cat_l and cat_l not in node_cat.lower() and cat_l != "all":
            continue
        if query_l:
            hay = f"{cls} {disp} {node_cat}".lower()
            if query_l not in hay:
                continue
        results.append({"name": cls, "display_name": disp, "category": node_cat, "output_types": spec.get("output_types", [])})
    return results


def describe_node(comfyui_url, node_type):
    info = load_object_info(comfyui_url)
    spec = info.get(node_type)
    if not spec:
        return None
    return {"name": node_type, "display_name": spec.get("display_name"), "category": spec.get("category"),
            "description": spec.get("description", ""), "input": spec.get("input", {}), "output_types": spec.get("output_types", [])}


def list_slots(ui_graph, object_info=None):
    slots = []
    for n in ui_graph.get("nodes", []) or []:
        ntype = n.get("type")
        nid = str(n.get("id"))
        node_inputs = n.get("inputs", []) or []
        widgets = n.get("widgets_values", []) or []
        linked_names = set()
        for ins in node_inputs:
            if isinstance(ins, dict) and ins.get("link"):
                linked_names.add(ins["name"])
        spec = (object_info or {}).get(ntype) if object_info else None
        if spec:
            required = spec.get("input", {}).get("required", {}) or {}
            optional = spec.get("input", {}).get("optional", {}) or {}
            order = list(required.keys()) + [k for k in optional if k not in required]
        else:
            order = [ins.get("name") for ins in node_inputs if isinstance(ins, dict) and ins.get("name")]
        wi = 0
        for name in order:
            if name in linked_names:
                continue
            if name.endswith(".") or any(k.startswith(name + ".") for k in linked_names):
                continue
            spec_in = None
            if spec:
                spec_in = spec.get("input", {}).get("required", {}).get(name) or spec.get("input", {}).get("optional", {}).get(name)
            if spec and not _is_primitive_widget(spec_in):
                continue
            value = widgets[wi] if wi < len(widgets) else None
            if value is not None:
                slots.append({"node_id": nid, "class_type": ntype, "input": name, "value": value, "address": f"{nid}.{name}"})
            wi += 1
    return slots


def _widget_index_for(ui_node, input_name, object_info=None):
    ntype = ui_node.get("type")
    node_inputs = ui_node.get("inputs", []) or []
    widgets = ui_node.get("widgets_values", []) or []
    linked_names = set()
    for ins in node_inputs:
        if isinstance(ins, dict) and ins.get("link"):
            linked_names.add(ins["name"])
    spec = (object_info or {}).get(ntype) if object_info else None
    if spec:
        required = spec.get("input", {}).get("required", {}) or {}
        optional = spec.get("input", {}).get("optional", {}) or {}
        order = list(required.keys()) + [k for k in optional if k not in required]
        wi = 0
        for name in order:
            if name in linked_names:
                continue
            spec_in = required.get(name) or optional.get(name)
            if not _is_primitive_widget(spec_in):
                continue
            if name == input_name:
                return wi
            wi += 1
        return None
    wi = 0
    for ins in node_inputs:
        if not isinstance(ins, dict):
            continue
        if ins.get("link"):
            continue
        if ins.get("name") == input_name:
            return wi
        wi += 1
    return None


def set_slot(ui_graph, address, value, object_info=None):
    mobj = re.fullmatch(r"(\d+)\.(.+)", str(address))
    if not mobj:
        raise ValueError(f"invalid slot address: {address}")
    nid, input_name = mobj.group(1), mobj.group(2)
    for n in ui_graph.get("nodes", []) or []:
        if str(n.get("id")) != nid:
            continue
        idx = _widget_index_for(n, input_name, object_info)
        if idx is None:
            return False
        widgets = n.get("widgets_values", []) or []
        while len(widgets) <= idx:
            widgets.append(None)
        widgets[idx] = value
        n["widgets_values"] = widgets
        return True
    return False


def system_stats(comfyui_url):
    return _http_get(comfyui_url, "/system_stats", timeout=10)


def free_memory(comfyui_url, unload_models=True):
    import requests
    try:
        resp = requests.post(f"{comfyui_url}/free", json={"unload_models": unload_models, "free_memory": unload_models}, timeout=10)
        if resp.status_code < 400:
            return "ok"
        return f"free returned HTTP {resp.status_code}"
    except Exception as e:
        return f"free failed: {e}"


def tool_search_nodes(comfyui_url, params):
    return list_node_names(comfyui_url, params.get("query", ""), params.get("category", ""))


def tool_get_node_info(comfyui_url, params):
    spec = describe_node(comfyui_url, params.get("node_type", ""))
    if spec is None:
        return {"error": f"node type not found: {params.get('node_type')}"}
    return spec


def tool_list_models(comfyui_url, params):
    folder = params.get("folder", "")
    return list_model_files(comfyui_url, folder)


def tool_search_models(comfyui_url, params, models_dir=None):
    query = (params.get("query", "") or "").lower()
    folder = params.get("folder", "") or params.get("model_type", "")
    if folder:
        files = list_model_files(comfyui_url, folder)
        if query:
            files = [f for f in files if query in f.lower()]
        return {folder: files[:100]}
    import folder_paths
    roots = {}
    for root in folder_paths.folder_names_and_paths:
        roots[root] = folder_paths.get_filename_list(root)
    result = {}
    for root, files in roots.items():
        if query:
            files = [f for f in files if query in f.lower()]
        if files:
            result[root] = files[:100]
    return result


def tool_search_templates(comfyui_url, params):
    return search_templates(params.get("query", ""))


def tool_fetch_template(comfyui_url, params, out_dir=None, audio_ref=None, image_ref=None, prompt=None):
    name = params.get("name", "")
    out_path = params.get("out_path") or ""
    ui, builtin = fetch_template_json(name)
    if ui is None:
        return {"error": f"template not found: {name}"}
    try:
        object_info = load_object_info(comfyui_url)
    except Exception as e:
        object_info = {}
    if builtin:
        ui = apply_builtin_fixes(name, ui, reference_audio=audio_ref)
    media_changes = apply_user_context(ui, object_info, image_ref=image_ref, audio_ref=audio_ref, prompt=prompt)
    try:
        slots = list_slots(ui, object_info)
    except Exception:
        slots = []
    if not out_path:
        base = out_dir or tempfile.gettempdir()
        out_path = os.path.join(base, f"{name}.json")
    try:
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(ui, fh, indent=2)
        written = True
    except Exception as e:
        written = False
        out_path = ""
    errors = []
    try:
        normalize_api_prompt(ui, object_info)
    except Exception as e:
        errors.append(str(e))
    return {"name": name, "builtin": builtin, "path": out_path, "written": written,
            "node_count": len(ui.get("nodes", []) or []),
            "slots": slots,
            "media_injected": media_changes,
            "local_check": {"checked": True, "runnable": not errors, "errors": errors},
            "note": "Next: set inputs with set_workflow_slot(path, overrides), pre-flight with validate_workflow(path), execute with run_workflow(path), then fetch_outputs(prompt_id, out_dir)."}


def tool_get_template(comfyui_url, params):
    name = params.get("name", "")
    ui, builtin = fetch_template_json(name)
    if ui is None:
        return {"error": f"template not found: {name}"}
    try:
        object_info = load_object_info(comfyui_url)
    except Exception as e:
        object_info = {}
    errors = []
    try:
        normalize_api_prompt(ui, object_info)
    except Exception as e:
        errors.append(str(e))
    return {"name": name, "builtin": builtin, "node_count": len(ui.get("nodes", []) or []),
            "local_check": {"checked": True, "runnable": not errors, "errors": errors}}


def _node_map(comfyui_url):
    try:
        return load_object_info(comfyui_url)
    except Exception:
        return {}


def tool_nodes(comfyui_url, params):
    action = params.get("action", "search")
    info = _node_map(comfyui_url)
    if action == "get":
        return tool_get_node_info(comfyui_url, {"node_type": params.get("name", "")})
    if action in ("search", "list"):
        results = []
        query_l = (params.get("query", "") or "").lower()
        cat = (params.get("category", "") or "").lower()
        produces = (params.get("produces", "") or "").upper()
        accepts = (params.get("accepts", "") or "").upper()
        pack = (params.get("pack", "") or "").lower()
        label = (params.get("label", "") or "").lower()
        for cls, spec in sorted(info.items()):
            disp = str(spec.get("display_name", "") or cls)
            node_cat = spec.get("category", "")
            if cat and cat != "all" and cat not in node_cat.lower():
                continue
            if query_l and query_l not in f"{cls} {disp} {node_cat}".lower():
                continue
            if label and label not in disp.lower():
                continue
            if pack:
                p = spec.get("python_module", "") or ""
                if not p.lower().startswith(pack) and pack not in p.lower():
                    # object_info rarely exposes pack; only filter if it looks like a module path
                    pass
            outs = [str(o).upper() for o in spec.get("output_types", []) or spec.get("output", []) or []]
            ins = []
            for grp in spec.get("input", {}).values():
                if isinstance(grp, dict):
                    for typ in grp.values():
                        if isinstance(typ, (list, tuple)) and typ and isinstance(typ[0], str):
                            ins.append(typ[0].upper())
            if produces and produces not in outs:
                continue
            if accepts and not any(accepts in str(i) for i in ins):
                continue
            results.append({"name": cls, "display_name": disp, "category": node_cat, "output_types": spec.get("output_types", [])})
        return results
    if action == "types":
        counts = {}
        for cls, spec in info.items():
            for grp in spec.get("input", {}).values():
                if isinstance(grp, dict):
                    for typ in grp.values():
                        if isinstance(typ, (list, tuple)) and typ and isinstance(typ[0], str):
                            counts[typ[0]] = counts.get(typ[0], 0) + 1
            for o in spec.get("output_types", []) or spec.get("output", []) or []:
                counts[str(o)] = counts.get(str(o), 0) + 1
        return [{"type": t, "connections": c} for t, c in sorted(counts.items(), key=lambda x: -x[1])]
    if action == "categories":
        cats = {}
        for cls, spec in info.items():
            cats.setdefault(spec.get("category", ""), []).append(cls)
        return [{"category": c, "nodes": v} for c, v in sorted(cats.items())]
    if action in ("upstream", "downstream"):
        name = params.get("name", "")
        limit = int(params.get("limit", 20) or 20)
        if not name or name not in info:
            return {"error": f"node '{name}' not found (action={action} needs a valid name)"}
        spec = info[name]
        want = spec.get("output_types", []) if action == "downstream" else None
        accept = set()
        if action == "upstream":
            for grp in spec.get("input", {}).values():
                if isinstance(grp, dict):
                    for typ in grp.values():
                        if isinstance(typ, (list, tuple)) and typ and isinstance(typ[0], str):
                            accept.add(typ[0].upper())
        out = []
        for cls, s in info.items():
            if cls == name:
                continue
            if action == "downstream":
                accepts_any = False
                for grp in s.get("input", {}).values():
                    if isinstance(grp, dict):
                        for typ in grp.values():
                            if isinstance(typ, (list, tuple)) and typ and isinstance(typ[0], str):
                                if typ[0].upper() in [str(w).upper() for w in (want or [])]:
                                    accepts_any = True
                if accepts_any:
                    out.append({"name": cls, "display_name": s.get("display_name", cls)})
            else:
                prods = [str(o).upper() for o in s.get("output_types", []) or []]
                if any(p in accept for p in prods):
                    out.append({"name": cls, "display_name": s.get("display_name", cls)})
            if len(out) >= limit:
                break
        return out
    if action == "path":
        from_type = params.get("from_type", "").upper()
        to_type = params.get("to_type", "").upper()
        max_depth = int(params.get("max_depth", 6) or 6)
        max_paths = int(params.get("max_paths", 10) or 10)
        if not from_type or not to_type:
            return {"error": "path requires from_type and to_type"}
        paths = []
        def _emit(t):
            return [str(o).upper() for o in info[t].get("output_types", []) or []] if t in info else []
        def _accept(t):
            s = set()
            for grp in info[t].get("input", {}).values():
                if isinstance(grp, dict):
                    for typ in grp.values():
                        if isinstance(typ, (list, tuple)) and typ and isinstance(typ[0], str):
                            s.add(typ[0].upper())
            return s
        def walk(cur, chain):
            if len(chain) > max_depth or len(paths) >= max_paths:
                return
            for nxt, s in info.items():
                if nxt in chain:
                    continue
                if cur not in _accept(nxt):
                    continue
                new_chain = chain + [nxt]
                if to_type in _emit(nxt) or to_type in _accept(nxt) and nxt != cur:
                    if to_type in _emit(nxt):
                        paths.append(new_chain)
                walk(nxt, new_chain)
        for start, s in info.items():
            if from_type in _emit(start):
                walk(start, [start])
        return {"from_type": from_type, "to_type": to_type, "paths": paths[:max_paths]}
    if action == "search":
        return list_node_names(comfyui_url, params.get("query", ""), params.get("category", ""))
    return {"error": f"unknown nodes action: {action}"}


def _load_ui_file(workflow_path):
    if not workflow_path or not os.path.isfile(str(workflow_path)):
        raise ValueError(f"workflow_path does not point to an existing file: {workflow_path}")
    with open(workflow_path, "r", encoding="utf-8") as fh:
        obj = json.load(fh)
    if not isinstance(obj, dict) or "nodes" not in obj:
        raise ValueError("file is not a UI-format workflow; write one with fetch_template(out_path=...)")
    return obj


def tool_list_workflow_slots(comfyui_url, params):
    path = params.get("workflow_path", "")
    try:
        ui = _load_ui_file(path)
    except Exception as e:
        return {"error": str(e)}
    try:
        object_info = load_object_info(comfyui_url)
    except Exception:
        object_info = {}
    return list_slots(ui, object_info)


def tool_set_workflow_slot(comfyui_url, params):
    path = params.get("workflow_path", "")
    try:
        ui = _load_ui_file(path)
    except Exception as e:
        return {"error": str(e)}
    try:
        object_info = load_object_info(comfyui_url)
    except Exception:
        object_info = {}
    changed = 0
    overrides = params.get("overrides", []) or []
    if isinstance(overrides, dict):
        items = overrides.items()
    else:
        items = [(o.get("address"), o.get("value")) for o in overrides]
    for address, value in items:
        if address and set_slot(ui, address, value, object_info):
            changed += 1
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(ui, fh, indent=2)
        saved = True
    except Exception as e:
        saved = False
    return {"changed": changed, "saved": saved, "path": path, "slots": list_slots(ui, object_info)}


def tool_validate_workflow(comfyui_url, params):
    path = params.get("workflow_path", "")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
    except Exception as e:
        return {"valid": False, "errors": [f"cannot read {path}: {e}"], "warnings": []}
    try:
        object_info = load_object_info(comfyui_url)
    except Exception:
        object_info = {}
    errors, warnings = [], []
    try:
        api = normalize_api_prompt(obj, object_info)
    except ValueError as e:
        return {"valid": False, "errors": [str(e)], "warnings": []}
    for nid, call in (api or {}).items():
        ctype = call.get("class_type")
        if ctype not in object_info:
            errors.append(f"node {nid}: class_type '{ctype}' not installed")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "node_count": len(api or {})}


def tool_run_template(comfyui_url, params, timeout, out_dir, can_preview, audio_ref=None, image_ref=None, prompt=None, log=None):
    name = params.get("name", "")
    ui, builtin = fetch_template_json(name)
    if ui is None:
        return {"error": f"template not found: {name}"}
    object_info = load_object_info(comfyui_url)
    overrides = params.get("params") or params.get("overrides", []) or []
    if isinstance(overrides, dict):
        items = overrides.items()
    else:
        items = [(o.get("address"), o.get("value")) for o in overrides]
    for address, value in items:
        if address:
            set_slot(ui, address, value, object_info)
    if builtin:
        ui = apply_builtin_fixes(name, ui, reference_audio=audio_ref)
    apply_user_context(ui, object_info, image_ref=image_ref, audio_ref=audio_ref, prompt=prompt)
    api = normalize_api_prompt(ui, object_info)
    io_check = check_graph_io(api, object_info)
    if io_check["block"]:
        return {"ok": False, "error": "workflow produces no retrievable output",
                "io": io_check["notes"],
                "guidance": "The graph has no node that outputs IMAGE/VIDEO/GIF/AUDIO. Pick a template that emits saves an image or video (inspect with get_template), then re-run. Do not submit a graph that can produce nothing."}
    io_note = {"io": io_check["notes"]} if io_check["notes"] else {}
    submit = submit_prompt(comfyui_url, api)
    if not submit.get("ok"):
        return {"ok": False, "submit_error": True, "error": submit.get("error"),
                "node_errors": submit.get("node_errors"), **io_note,
                "guidance": "Patch the failing input on the fetched workflow with set_workflow_slot using the EXACT input_name key from node_errors (these are literal JSON keys - keep dotted names like resize_type.width), then re-run. Do NOT rebuild or strip the template."}
    prompt_id = submit.get("prompt_id")
    record, ok, err = wait_for_completion(comfyui_url, prompt_id, timeout, log=log)
    if not ok:
        if record is not None and prompt_id:
            try:
                tool_job(comfyui_url, {"action": "cancel", "prompt_id": prompt_id}, 10)
            except Exception:
                pass
        extra = {}
        if record is None and prompt_id:
            extra = {"still_running": True,
                     "note": "wait budget exhausted - the job may STILL be running server-side. Poll job(action='wait', prompt_id=...) for the outcome, or fetch_outputs when it finishes. Do not resubmit from scratch."}
        return {"prompt_id": prompt_id, "ok": False, "error": err, **io_note, **extra}
    saved, tensor = download_outputs(comfyui_url, record, out_dir, can_preview)
    tensor = _ensure_video_preview(saved, tensor)
    return {"prompt_id": prompt_id, "ok": True, "files": saved, "preview_tensor": tensor}


def tool_run_workflow(comfyui_url, params, timeout, log=None, image_ref=None, audio_ref=None, prompt=None):
    path = params.get("workflow_path", "")
    if not path or not os.path.isfile(str(path)):
        return {"error": "workflow_path must be a path to a runnable workflow JSON (write one with fetch_template(out_path=...))"}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
    except Exception as e:
        return {"error": str(e)}
    object_info = load_object_info(comfyui_url)
    apply_user_context(obj, object_info, image_ref=image_ref, audio_ref=audio_ref, prompt=prompt)
    try:
        api = normalize_api_prompt(obj, object_info)
    except ValueError as e:
        return {"error": str(e)}
    io_check = check_graph_io(api, object_info)
    if io_check["block"]:
        return {"ok": False, "error": "workflow produces no retrievable output",
                "io": io_check["notes"],
                "guidance": "The graph has no node that outputs IMAGE/VIDEO/GIF/AUDIO. Re-fetch a template that emits an image or video (inspect with get_template), then re-run."}
    io_note = {"io": io_check["notes"]} if io_check["notes"] else {}
    submit = submit_prompt(comfyui_url, api)
    if not submit.get("ok"):
        return {"ok": False, "submit_error": True, "error": submit.get("error"),
                "node_errors": submit.get("node_errors"), **io_note,
                "guidance": "Patch the failing input with set_workflow_slot on this workflow_path using the EXACT input_name key from node_errors (literal JSON keys - keep dotted names like resize_type.width), then re-run. Do NOT rebuild or strip the template."}
    prompt_id = submit.get("prompt_id")
    if not params.get("wait", True):
        return {"prompt_id": prompt_id, "submitted": True,
                "note": "poll with job(action='wait', prompt_id=...), then fetch_outputs(prompt_id, out_dir=...)"}
    record, ok, err = wait_for_completion(comfyui_url, prompt_id, timeout, log=log)
    if not ok:
        if record is not None and prompt_id:
            try:
                tool_job(comfyui_url, {"action": "cancel", "prompt_id": prompt_id}, 10)
            except Exception:
                pass
        extra = {}
        if record is None and prompt_id:
            extra = {"still_running": True,
                     "note": "wait budget exhausted - the job may STILL be running server-side. Poll job(action='wait', prompt_id=...) for the outcome, or fetch_outputs when it finishes. Do not resubmit from scratch."}
        return {"prompt_id": prompt_id, "ok": False, "error": err, **io_note, **extra,
                "note": "fetch_outputs(prompt_id, out_dir=...) will list whatever was produced"}
    return {"prompt_id": prompt_id, "ok": True, "status": (record or {}).get("status", {}).get("status_str"),
            **io_note,
            "note": "done. Run fetch_outputs(prompt_id, out_dir=...) to download the generated files."}


def tool_job(comfyui_url, params, timeout=3600, log=None):
    prompt_id = params.get("prompt_id", "")
    action = params.get("action", "status")
    if action == "cancel":
        try:
            resp = _http_post(comfyui_url, "/queue", {"delete": [prompt_id]}, timeout=10)
        except Exception as e:
            return {"error": str(e)}
        return {"cancelled": True, "note": "queued/running job will be stopped at next queue iteration"}
    record = None
    if prompt_id:
        try:
            history = _http_get(comfyui_url, f"/history/{prompt_id}")
            record = history.get(prompt_id)
        except Exception:
            record = None
    if action == "wait":
        if record is not None:
            return {"prompt_id": prompt_id, "status": "done", **_job_summary(prompt_id, record)}
        wt = max(1, int(params.get("timeout") or timeout))
        waited, ok, err = wait_for_completion(comfyui_url, prompt_id, wt, log=log)
        if waited is not None:
            return {"prompt_id": prompt_id, "status": "done", **_job_summary(prompt_id, waited)}
        return {"prompt_id": prompt_id, "status": "running", "error": err,
                "note": "job not finished within polling budget; call job(action='status') or job(action='wait', timeout=...) again"}
    if record is None:
        return {"prompt_id": prompt_id, "status": "pending", "note": "not yet in history - still queued/running"}
    return {"prompt_id": prompt_id, "status": "done", **_job_summary(prompt_id, record)}


def _job_summary(prompt_id, record):
    status = (record or {}).get("status", {}) or {}
    error = None
    st = status.get("status_str")
    if st == "error":
        error = {"exception_message": status.get("messages", [None])[0] if status.get("messages") else None,
                 "node_type": status.get("node_type")}
    return {"prompt_id": prompt_id, "status": st or "done",
            "outputs": list(((record or {}).get("outputs", {}) or {}).keys()), "error": error}


def tool_fetch_outputs(comfyui_url, params, out_dir=None, can_preview=True):
    prompt_id = params.get("prompt_id", "")
    if not prompt_id:
        return {"error": "prompt_id is required"}
    out_dir = params.get("out_dir") or out_dir
    if not out_dir:
        out_dir = tempfile.gettempdir()
    try:
        os.makedirs(out_dir, exist_ok=True)
    except Exception:
        pass
    try:
        history = _http_get(comfyui_url, f"/history/{prompt_id}")
        record = history.get(prompt_id)
    except Exception as e:
        return {"error": f"failed to query job: {e}", "files": []}
    if not record:
        return {"prompt_id": prompt_id, "error": "job not found in history", "files": []}
    saved, tensor = download_outputs(comfyui_url, record, out_dir, can_preview)
    tensor = _ensure_video_preview(saved, tensor)
    return {"prompt_id": prompt_id, "ok": True, "files": saved, "preview_tensor": tensor}


def tool_server_info(comfyui_url, params):
    try:
        stats = system_stats(comfyui_url)
    except Exception as e:
        return {"running": False, "error": str(e)}
    devices = stats.get("devices", []) or []
    dev = []
    for d in devices:
        vram = d.get("vram_total")
        dev.append({"name": d.get("name"), "vram_total": vram, "vram_free": d.get("vram_free"),
                    "torch": d.get("torch_vram_total") is not None})
    return {"running": True, "url": comfyui_url,
            "comfyui_version": (stats.get("system", {}) or {}).get("comfyui_version"),
            "devices": dev, "system": stats.get("system", {})}


def tool_system_stats(comfyui_url, params):
    try:
        return system_stats(comfyui_url)
    except Exception as e:
        return {"error": str(e)}


def tool_free_memory(comfyui_url, params):
    return {"result": free_memory(comfyui_url)}


# ---------------------------------------------------------------------------
# Lifecycle / asset / partner / cloud / introspection tools (comfy-cli & local)
# ---------------------------------------------------------------------------

def tool_launch_comfyui(comfyui_url, params):
    extra = params.get("extra_args") or []
    args = ["launch", "--background"]
    if extra:
        args += ["--"] + [str(x) for x in extra]
    return _comfy_cli(args)


def tool_stop_comfyui(comfyui_url, params):
    return _comfy_cli(["stop"])


def tool_restart_comfyui(comfyui_url, params):
    extra = params.get("extra_args") or []
    args = ["launch", "--background"]
    if extra:
        args += ["--"] + [str(x) for x in extra]
    _comfy_cli(["stop"])
    return _comfy_cli(args)


def tool_update_comfyui(comfyui_url, params):
    target = params.get("target", "comfy")
    if target not in ("comfy", "all", "cli"):
        return {"error": f"unknown update target: {target} (pick comfy|all|cli)"}
    return _comfy_cli(["update", target], timeout=1800)


def tool_switch_comfyui_version(comfyui_url, params):
    version = params.get("version", "")
    if not version:
        return {"error": "version is required (e.g. 0.24.0, latest, nightly)"}
    return _comfy_cli(["update", "comfy", "--version", str(version)], timeout=900)


def tool_install_node(comfyui_url, params):
    names = params.get("names") or []
    if not names:
        return {"error": "names (registry pack ids) is required"}
    return _comfy_cli(["node", "install"] + [str(n) for n in names] + ["--exit-on-fail"], timeout=1800)


def tool_which(comfyui_url, params):
    return _comfy_cli(["which"])


def tool_project(comfyui_url, params):
    action = params.get("action", "status")
    if action == "init":
        return _comfy_cli(["project", "init"])
    return _comfy_cli(["project", "status"])


def tool_get_logs(comfyui_url, params):
    tail = int(params.get("tail", 200) or 200)
    args = ["logs", "--tail", str(tail)]
    if params.get("port"):
        args += ["--port", str(params["port"])]
    result = _comfy_cli(args)
    if isinstance(result, dict) and result.get("unsupported"):
        return result
    if isinstance(result, dict) and result.get("lines"):
        return result
    return result


def tool_discover(comfyui_url, params):
    args = ["discover"]
    if params.get("schemas_only") is not False:
        args += ["--schemas-only"]
    return _comfy_cli(args)


def tool_list_partner_models(comfyui_url, params):
    args = ["generate", "list"]
    for k in ("partner", "style", "query"):
        v = params.get(k)
        if v:
            args += [f"--{k.replace('_', '-')}", str(v)]
    if "limit" in params:
        args += ["--limit", str(params["limit"])]
    if "offset" in params:
        args += ["--offset", str(params["offset"])]
    return _comfy_cli(args)


def tool_partner_model_schema(comfyui_url, params):
    model = params.get("model", "")
    if not model:
        return {"error": "model (alias) is required"}
    return _comfy_cli(["generate", "schema", str(model)])


def tool_partner_generate(comfyui_url, params):
    model = params.get("model", "")
    if not model:
        return {"error": "model (alias) is required"}
    args = ["generate", str(model)]
    for k, v in (params.get("params") or {}).items():
        args += [f"--{k}={v}"]
    if params.get("out_path"):
        args += ["--download", str(params["out_path"])]
    if params.get("timeout_seconds"):
        args += ["--timeout", str(params["timeout_seconds"])]
    args += ["--yes"]
    return _comfy_cli(args, timeout=int(params.get("timeout_seconds", 600)) + 30)


def tool_emit_partner_workflow(comfyui_url, params):
    model = params.get("model", "")
    out_path = params.get("out_path", "")
    if not model:
        return {"error": "model (alias) is required"}
    if not out_path:
        return {"error": "out_path is required"}
    args = ["generate", str(model)]
    for k, v in (params.get("params") or {}).items():
        args += [f"--{k}={v}"]
    args += ["--emit-workflow", str(out_path)]
    return _comfy_cli(args)


def tool_auth_status(comfyui_url, params):
    return _comfy_cli(["cloud", "whoami"])


def tool_auth_login(comfyui_url, params):
    return _comfy_cli(["cloud", "login", "--no-browser", "--timeout", "600"])


def tool_billing_status(comfyui_url, params):
    return _comfy_cli(["cloud", "status"])


def _models_dir():
    try:
        import folder_paths
        return folder_paths.models_dir
    except Exception:
        return None


def tool_download_model(comfyui_url, params):
    url = params.get("url", "")
    if not url:
        return {"error": "url is required"}
    rel = params.get("relative_path") or "models"
    filename = params.get("filename")
    did = uuid.uuid4().hex[:12]
    with _downloads_lock:
        _downloads[did] = {"status": "starting", "url": url, "dest": None,
                           "bytes": 0, "total": -1, "error": None}

    def _run():
        import requests
        try:
            base = _models_dir()
            if base and rel.startswith("models"):
                base = os.path.dirname(base)
            dest_dir = os.path.join(base or tempfile.gettempdir(), rel.replace("/", os.sep))
            os.makedirs(dest_dir, exist_ok=True)
            dest = os.path.join(dest_dir, filename or os.path.basename(url.split("?")[0]))
            with requests.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with _downloads_lock:
                    _downloads[did]["dest"] = dest
                    _downloads[did]["total"] = int(r.headers.get("content-length", -1))
                with open(dest, "wb") as fh:
                    for chunk in r.iter_content(1024 * 1024):
                        fh.write(chunk)
                        with _downloads_lock:
                            _downloads[did]["bytes"] += len(chunk)
            with _downloads_lock:
                _downloads[did]["status"] = "completed"
        except Exception as e:
            with _downloads_lock:
                _downloads[did]["status"] = "failed"
                _downloads[did]["error"] = str(e)

    threading.Thread(target=_run, daemon=True).start()
    return {"download_id": did, "status": "starting", "dest": None,
            "note": "track progress with download(action='status', download_id=...)"}


def tool_download(comfyui_url, params):
    did = params.get("download_id", "")
    if not did:
        return {"error": "download_id is required"}
    action = params.get("action", "status")
    with _downloads_lock:
        rec = _downloads.get(did)
    if rec is None:
        return {"download_id": did, "status": "unknown", "error": "no such download_id"}
    if action == "cancel":
        with _downloads_lock:
            rec["status"] = "cancelled"
        return {"download_id": did, "status": "cancelled"}
    if action == "wait":
        import requests
        start = time.time()
        wt = int(params.get("timeout_seconds") or 25)
        while time.time() - start < wt:
            with _downloads_lock:
                r = dict(rec)
            if r["status"] in ("completed", "failed", "cancelled"):
                return {"download_id": did, **r}
            time.sleep(1)
        with _downloads_lock:
            r = dict(rec)
        return {"download_id": did, "timed_out": True, **r}
    with _downloads_lock:
        r = dict(rec)
    total = r.get("total", -1)
    percent = round(r["bytes"] * 100.0 / total, 1) if total and total > 0 else None
    return {"download_id": did, "status": r["status"], "completed_bytes": r["bytes"],
            "total_bytes": total, "percent": percent, "dest": r.get("dest"), "error": r.get("error")}


def tool_upload_file(comfyui_url, params):
    paths = params.get("paths") or []
    if not paths:
        return {"error": "paths (list of existing local file paths) is required"}
    try:
        import folder_paths
        in_dir = folder_paths.get_input_directory()
    except Exception:
        in_dir = None
    if not in_dir:
        return {"error": "could not resolve ComfyUI input directory"}
    uploaded = []
    for p in paths:
        p = str(p)
        if not os.path.isfile(p):
            uploaded.append({"path": p, "error": "file not found"})
            continue
        dest = os.path.join(in_dir, os.path.basename(p))
        overwrite = bool(params.get("overwrite", False))
        if not overwrite and os.path.exists(dest):
            stem, ext = os.path.splitext(os.path.basename(p))
            dest = os.path.join(in_dir, f"{stem}_{uuid.uuid4().hex[:6]}{ext}")
        shutil.copyfile(p, dest)
        uploaded.append({"path": p, "staged_as": os.path.basename(dest)})
    return {"uploaded": uploaded}


def _list_workflow_notes_from_obj(obj):
    notes = []
    for n in obj.get("nodes", []) or []:
        ntype = n.get("type", "")
        if ntype not in ("Note", "MarkdownNote"):
            continue
        wv = n.get("widgets_values") or []
        notes.append({
            "id": str(n.get("id")),
            "type": ntype,
            "title": n.get("title", ""),
            "text": (wv[0] if wv else "") or "",
            "pos": n.get("pos"),
            "size": n.get("size"),
        })
    return notes


def tool_list_workflow_notes(comfyui_url, params):
    path = params.get("workflow_path", "")
    if not path or not os.path.isfile(str(path)):
        return {"error": "workflow_path must point to an existing workflow JSON"}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
    except Exception as e:
        return {"error": str(e)}
    if not isinstance(obj, dict) or "nodes" not in obj or "links" not in obj:
        return {"error": "API-format export has no note nodes; re-fetch a frontend-format template"}
    notes = _list_workflow_notes_from_obj(obj)
    return {"workflow": path, "count": len(notes), "notes": notes}


def tool_vary_workflow(comfyui_url, params):
    path = params.get("workflow_path", "")
    slots = params.get("slots", []) or []
    out_dir = params.get("out_dir") or ""
    try:
        obj = _load_ui_file(path)
    except Exception as e:
        return {"error": str(e)}
    try:
        object_info = load_object_info(comfyui_url)
    except Exception:
        object_info = {}
    # Normalize slots to [{address, values:[...]}]
    norm = []
    for s in slots:
        if isinstance(s, dict) and "address" in s and "values" in s:
            norm.append((s["address"], list(s["values"])))
        elif isinstance(s, str):
            m = re.match(r"(.+?)=\[(.*)\]$", s, re.DOTALL)
            if not m:
                return {"error": f"slot string must be 'ADDR=[v1, v2, ...]': {s}"}
            try:
                vals = json.loads("[" + m.group(2) + "]")
            except Exception as e:
                return {"error": f"could not parse values for {m.group(1)}: {e}"}
            norm.append((m.group(1), vals))
    if not norm:
        return {"error": "slots is required"}
    lengths = {len(v) for _, v in norm}
    if len(lengths) != 1:
        return {"error": "all slot value lists must be the same length (they are zipped)"}
    n = lengths.pop()
    variants = []
    for i in range(n):
        v = json.loads(json.dumps(obj))
        for address, values in norm:
            set_slot(v, address, values[i], object_info)
        variants.append(v)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        stem = os.path.splitext(os.path.basename(path))[0]
        written = []
        for i, v in enumerate(variants):
            p = os.path.join(out_dir, f"{stem}_{i}.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(v, fh, indent=2)
            written.append(p)
        return {"count": len(written), "files": written}
    return {"count": len(variants), "variants": variants}


def tool_workflow_deps(comfyui_url, params):
    path = params.get("workflow_path", "")
    if not path or not os.path.isfile(str(path)):
        return {"error": "workflow_path must point to an existing workflow JSON"}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            obj = json.load(fh)
    except Exception as e:
        return {"error": str(e)}
    # Gather node classes
    classes = set()
    nodes = obj.get("nodes") or []
    if isinstance(nodes, list):
        for n in nodes:
            if n.get("type"):
                classes.add(n["type"])
    else:
        for ctype in (obj.values() if isinstance(obj, dict) else []):
            if isinstance(ctype, dict) and ctype.get("class_type"):
                classes.add(ctype["class_type"])
    # Known builtin classes (no pack needed)
    builtin = {"KSampler", "KSamplerAdvanced", "CheckpointLoaderSimple", "CLIPTextEncode",
               "EmptyLatentImage", "VAEDecode", "VAEEncode", "SaveImage", "LoadImage",
               "ModelSamplingDiscrete", "SamplerCustom", "BasicScheduler", "CreateVideo",
               "SaveVideo", "LoadAudio", "VAELoader", "UNETLoader", "CLIPLoader",
               "LoraLoaderModelOnly", "RandomNoise", "PrimitiveStringMultiline",
               "PrimitiveInt", "PrimitiveFloat", "PrimitiveBoolean", "ComfyMathExpression",
               "ResolutionSelector", "EmptyImage", "SaveAudio", "PreviewImage", "PreviewVideo"}
    result = _comfy_cli(["node", "deps-in-workflow", "--workflow", path, "--output", os.path.join(tempfile.gettempdir(), f"deps_{uuid.uuid4().hex[:6]}.json")])
    if isinstance(result, dict) and result.get("error") and result.get("unsupported"):
        # Fallback: best-effort class -> pack mapping for well-known custom nodes
        custom = [c for c in classes if c not in builtin]
        fallback = {}
        for c in custom:
            fallback[c] = {"state": "unknown"}
        return {"custom_nodes": fallback, "unknown_nodes": list(custom), "note": "comfy-cli unavailable; names listed but packs unresolved"}
    return result


def tool_node_dependencies(comfyui_url, params):
    pack = params.get("pack", "")
    args = ["node", "deps"]
    if pack:
        args.append(str(pack))
    if params.get("registry_id"):
        args += ["--registry", str(params["registry_id"])]
    return _comfy_cli(args)


def tool_generate_image(comfyui_url, params):
    prompt = params.get("prompt", "")
    if not prompt:
        return {"error": "prompt is required"}
    # Prefer an installed text-to-image template; fall back to a minimal t2i graph.
    cands = search_templates("image")
    name = None
    for c in cands:
        n = c.get("name", "")
        if any(k in n.lower() for k in ("t2i", "text_to_image", "text-to-image", "sd", "flux", "image")):
            name = n
            break
    builtin_name = None
    if name:
        params2 = dict(params)
        params2["name"] = name
        params2["overrides"] = {}
        return _run_template_tool(comfyui_url, params2)
    # Minimal SD1.5-style text-to-image graph.
    checkpoint = params.get("checkpoint")
    return _minimal_t2i(comfyui_url, prompt, checkpoint)


def _run_template_tool(comfyui_url, params):
    ui, builtin = fetch_template_json(params.get("name", ""))
    if ui is None:
        return {"error": "no text-to-image template available (and no minimal graph)"}
    object_info = load_object_info(comfyui_url)
    api = normalize_api_prompt(ui, object_info)
    submit = submit_prompt(comfyui_url, api)
    if not submit.get("ok"):
        return {"ok": False, "error": submit.get("error"), "node_errors": submit.get("node_errors")}
    prompt_id = submit.get("prompt_id")
    if not params.get("wait", True):
        return {"prompt_id": prompt_id, "submitted": True, "note": "poll with job(action='status')"}
    record, ok, err = wait_for_completion(comfyui_url, prompt_id, 120)
    if not ok:
        return {"prompt_id": prompt_id, "ok": False, "error": err}
    return {"prompt_id": prompt_id, "ok": True, "status": (record or {}).get("status", {}).get("status_str")}


def _minimal_t2i(comfyui_url, prompt, checkpoint=None, width=1024, height=1024, steps=20, cfg=7.0, seed=-1):
    import folder_paths
    ckpt = checkpoint
    if not ckpt:
        try:
            lst = folder_paths.get_filename_list("checkpoints")
            ckpt = lst[0] if lst else None
        except Exception:
            ckpt = None
    if not ckpt:
        return {"error": "no checkpoint installed and no template available; install a checkpoint or use generate_image on a machine with one"}
    wf = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "", "clip": ["4", 1]}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0], "seed": seed, "steps": steps, "cfg": cfg, "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["4", 2]}},
        "10": {"class_type": "SaveImage", "inputs": {"images": ["9", 0], "filename_prefix": "pgfx_mcp_t2i"}},
    }
    submit = submit_prompt(comfyui_url, wf)
    if not submit.get("ok"):
        return {"ok": False, "error": submit.get("error"), "node_errors": submit.get("node_errors")}
    prompt_id = submit.get("prompt_id")
    record, ok, err = wait_for_completion(comfyui_url, prompt_id, 120)
    if not ok:
        return {"prompt_id": prompt_id, "ok": False, "error": err}
    return {"prompt_id": prompt_id, "ok": True, "status": (record or {}).get("status", {}).get("status_str")}


TOOLS = [
    # Run & monitor
    {"name": "run_workflow", "description": "Executor: run a workflow JSON file. wait=true blocks for the result; wait=false submits and returns prompt_id.", "parameters": {"workflow_path": "path", "wait": "true|false"}},
    {"name": "generate_image", "description": "Text prompt -> image in one call (uses a text-to-image template or a minimal checkpoint graph).", "parameters": {"prompt": "text", "checkpoint": "optional checkpoint name"}},
    {"name": "run_template", "description": "One-shot template fetch+fill+run+download. params are {slot: value} overrides.", "parameters": {"name": "template name", "params": "slot overrides"}},
    {"name": "job", "description": "Inspect/await a submitted job. action: status | wait | watch | cancel | queue; timeout for wait/watch.", "parameters": {"action": "status|wait|cancel|queue", "prompt_id": "job id", "timeout": "seconds (wait/watch)"}},
    {"name": "fetch_outputs", "description": "Download a finished job's outputs into out_dir.", "parameters": {"prompt_id": "job id", "out_dir": "output directory"}},
    # Partner models (hosted, spend credits)
    {"name": "list_partner_models", "description": "Catalog of hosted partner models (Flux/Ideogram/DALL-E/Recraft...). style/partner/query filters.", "parameters": {"style": "", "partner": "", "query": "", "limit": "", "offset": ""}},
    {"name": "partner_model_schema", "description": "Callable parameters for one partner model.", "parameters": {"model": "alias"}},
    {"name": "partner_generate", "description": "Run a hosted partner model (SPENDS credits). params forwarded verbatim.", "parameters": {"model": "alias", "params": "dict", "out_path": "save template", "timeout_seconds": "int"}},
    {"name": "emit_partner_workflow", "description": "Write a runnable workflow that drives a partner model's node locally (no spend).", "parameters": {"model": "alias", "out_path": "path", "params": "dict"}},
    # Resource
    {"name": "system_stats", "description": "Live VRAM per device + RAM free/total.", "parameters": {}},
    {"name": "free_memory", "description": "Unload ComfyUI models + reset executor cache.", "parameters": {"unload_models": "bool", "free_memory": "bool"}},
    # Discovery / templates / building
    {"name": "server_info", "description": "Server is up? version, GPU/VRAM/RAM, freshness. Call FIRST.", "parameters": {}},
    {"name": "nodes", "description": "Search/inspect node classes. action: search|get|list|upstream|downstream|path|types|categories.", "parameters": {"action": "", "query": "", "name": "", "produces": "", "accepts": "", "category": "", "pack": "", "label": "", "from_type": "", "to_type": "", "max_depth": "", "max_paths": ""}},
    {"name": "search_models", "description": "List/search model files. query matches filenames; folder lists one folder.", "parameters": {"query": "text", "folder": "optional folder"}},
    {"name": "search_templates", "description": "Find a built-in workflow template by free-text query.", "parameters": {"query": "text"}},
    {"name": "get_template", "description": "Inspect one template + whether this install can run it (local_check).", "parameters": {"name": "template name", "check_local": "bool"}},
    {"name": "fetch_template", "description": "Write a template's runnable workflow JSON to out_path; returns path + slots + local_check.", "parameters": {"name": "template name", "out_path": "absolute path", "check_local": "bool"}},
    {"name": "list_workflow_slots", "description": "List settable inputs of a workflow file (addresses + current values).", "parameters": {"workflow_path": "path"}},
    {"name": "list_workflow_notes", "description": "Read a template's authored Note/MarkdownNote documentation (trigger words, links, caveats).", "parameters": {"workflow_path": "path"}},
    {"name": "set_workflow_slot", "description": "Set slot values (prompt/seed/steps/model) on a fetched workflow.", "parameters": {"workflow_path": "path", "overrides": "list of {address,value}"}},
    {"name": "vary_workflow", "description": "Fan a workflow into variants over zipped slot value lists.", "parameters": {"workflow_path": "path", "slots": "list of ADDR=[v1,v2...]", "out_dir": "optional dir"}},
    {"name": "validate_workflow", "description": "Pre-flight a workflow against installed node classes.", "parameters": {"workflow_path": "path"}},
    {"name": "workflow_deps", "description": "Which node packs a workflow needs (resolves classes -> pack ids).", "parameters": {"workflow_path": "path"}},
    {"name": "node_dependencies", "description": "A node pack's declared Python requirements vs the installed venv.", "parameters": {"pack": "installed pack name", "registry_id": "not-yet-installed registry pack"}},
    # Auth / billing / project
    {"name": "auth_status", "description": "Comfy Cloud credential status for partner-API nodes.", "parameters": {}},
    {"name": "auth_login", "description": "Start Comfy Cloud sign-in; returns a login_url.", "parameters": {}},
    {"name": "billing_status", "description": "Comfy Cloud credit balance / tier / concurrency.", "parameters": {}},
    {"name": "project", "description": "Report (status) or create (init) the comfy-cli project.", "parameters": {"action": "status|init"}},
    {"name": "which", "description": "Which ComfyUI install/workspace comfy-cli targets.", "parameters": {}},
    # Lifecycle / assets
    {"name": "launch_comfyui", "description": "Start the local ComfyUI detached. extra_args forwarded.", "parameters": {"extra_args": "list"}},
    {"name": "stop_comfyui", "description": "Stop the ComfyUI comfy-cli launched.", "parameters": {}},
    {"name": "restart_comfyui", "description": "Stop then launch the local ComfyUI.", "parameters": {"extra_args": "list"}},
    {"name": "update_comfyui", "description": "Update ComfyUI core / node packs / cli (target=comfy|all|cli).", "parameters": {"target": "comfy|all|cli"}},
    {"name": "switch_comfyui_version", "description": "Move ComfyUI to a specific version (destructive; roll back/forward).", "parameters": {"version": "e.g. 0.24.0|latest|nightly"}},
    {"name": "install_node", "description": "Install custom node packs by registry id (runs third-party code).", "parameters": {"names": "list of registry ids"}},
    {"name": "upload_file", "description": "Stage source images/masks into ComfyUI input dir.", "parameters": {"paths": "list of absolute paths", "overwrite": "bool"}},
    {"name": "download_model", "description": "Download a model file by URL into the models dir (background).", "parameters": {"url": "http(s) url", "relative_path": "models|models/loras", "filename": "optional name"}},
    {"name": "download", "description": "Track a download_model transfer. action: status|wait|cancel.", "parameters": {"action": "status|wait|cancel", "download_id": "id", "timeout_seconds": "for wait"}},
    {"name": "get_logs", "description": "Tail the background ComfyUI's captured log for debugging.", "parameters": {"tail": "lines", "port": "optional"}},
    {"name": "discover", "description": "comfy-cli's self-describing command surface (schemas).", "parameters": {"schemas_only": "bool"}},
]


class AgentSession:
    def __init__(self, comfyui_url, timeout=300, debug=False, out_dir=None, can_preview=True, models_dir=None, llm_unloader=None):
        self.comfyui_url = comfyui_url.rstrip("/")
        self.timeout = timeout
        self.debug = debug
        self.out_dir = out_dir
        self.can_preview = can_preview
        self.models_dir = models_dir
        self.llm_unloader = llm_unloader
        self.ref_audio_file = None
        self.ref_image_file = None
        self.user_message = None
        self._freed = False

    def log(self, msg):
        if self.debug:
            print(f"\033[95m[MCP Agent]\033[0m {msg}")

    def stage_media(self, reference_image, reference_audio):
        staged = []
        try:
            import folder_paths
            in_dir = folder_paths.get_input_directory()
        except Exception:
            in_dir = None
        if reference_image is not None:
            try:
                import torch
                img = reference_image[0].cpu().numpy()
                from PIL import Image as _PIL
                if img.ndim == 3 and img.shape[2] == 3:
                    if img.max() <= 1.01:
                        img = img * 255
                    pil = _PIL.fromarray(img.astype("uint8"))
                    dest = "pgfx_mcp_ref_image.png"
                    if in_dir:
                        pil.save(os.path.join(in_dir, dest))
                        self.ref_image_file = dest
                        staged.append({"file": dest, "type": "image", "note": "reference_image, usable via LoadImage/LoadAudio file widgets"})
                        self.log(f"staged reference image -> {dest}")
            except Exception as e:
                self.log(f"stage image failed: {e}")
        if reference_audio is not None:
            try:
                import torch
                audio = reference_audio.get("waveform")
                sr = reference_audio.get("sample_rate", 44100)
                if audio is not None:
                    import soundfile as sf
                    wav = audio.squeeze(0).cpu().numpy()
                    dest = "pgfx_mcp_ref_audio.wav"
                    if in_dir:
                        audio_sub = os.path.join(in_dir, "audio")
                        try:
                            os.makedirs(audio_sub, exist_ok=True)
                        except Exception:
                            audio_sub = None
                        sf.write(os.path.join(in_dir, dest), wav.T, int(sr))
                        if audio_sub:
                            sf.write(os.path.join(audio_sub, dest), wav.T, int(sr))
                        self.ref_audio_file = dest
                        staged.append({"file": dest, "type": "audio", "note": "reference_audio, usable by any LoadAudio/LoadImage filename widget; reference it in the prompt via the target template's documented tags (e.g. <Audio 1>)"})
                        self.log(f"staged reference audio -> {dest}")
            except Exception as e:
                self.log(f"stage audio failed: {e}")
        return staged

    def execute_tool(self, name, params):
        if name in ("run_template", "run_workflow") and not self._freed:
            if self.llm_unloader is not None:
                try:
                    rel = self.llm_unloader()
                    if rel:
                        self.log(f"released local LLM VRAM: {rel}")
                except Exception:
                    pass
            try:
                free_memory(self.comfyui_url)
            except Exception:
                pass
            self._freed = True
        if name == "server_info":
            return {"content": tool_server_info(self.comfyui_url, params)}
        if name == "nodes":
            return {"content": tool_nodes(self.comfyui_url, params)}
        if name == "search_models":
            return {"content": tool_search_models(self.comfyui_url, params, self.models_dir)}
        if name == "search_templates":
            return {"content": tool_search_templates(self.comfyui_url, params)}
        if name == "get_template":
            return {"content": tool_get_template(self.comfyui_url, params)}
        if name == "fetch_template":
            return {"content": tool_fetch_template(self.comfyui_url, params, self.out_dir, self.ref_audio_file, self.ref_image_file, self.user_message)}
        if name == "list_workflow_slots":
            return {"content": tool_list_workflow_slots(self.comfyui_url, params)}
        if name == "set_workflow_slot":
            return {"content": tool_set_workflow_slot(self.comfyui_url, params)}
        if name == "validate_workflow":
            return {"content": tool_validate_workflow(self.comfyui_url, params)}
        if name == "run_template":
            return {"preview": True, "content": tool_run_template(self.comfyui_url, params, self.timeout, self.out_dir, self.can_preview, self.ref_audio_file, self.ref_image_file, self.user_message, log=self.log)}
        if name == "run_workflow":
            return {"content": tool_run_workflow(self.comfyui_url, params, self.timeout, log=self.log, image_ref=self.ref_image_file, audio_ref=self.ref_audio_file, prompt=self.user_message)}
        if name == "job":
            return {"content": tool_job(self.comfyui_url, params, log=self.log)}
        if name == "fetch_outputs":
            return {"preview": True, "content": tool_fetch_outputs(self.comfyui_url, params, self.out_dir, self.can_preview)}
        if name == "system_stats":
            return {"content": tool_system_stats(self.comfyui_url, params)}
        if name == "free_memory":
            return {"content": tool_free_memory(self.comfyui_url, params)}
        # Extended (comfy-cli + local) tools
        if name == "generate_image":
            return {"preview": True, "content": tool_generate_image(self.comfyui_url, params)}
        if name == "list_workflow_notes":
            return {"content": tool_list_workflow_notes(self.comfyui_url, params)}
        if name == "vary_workflow":
            return {"content": tool_vary_workflow(self.comfyui_url, params)}
        if name == "workflow_deps":
            return {"content": tool_workflow_deps(self.comfyui_url, params)}
        if name == "node_dependencies":
            return {"content": tool_node_dependencies(self.comfyui_url, params)}
        if name == "upload_file":
            return {"content": tool_upload_file(self.comfyui_url, params)}
        if name == "download_model":
            return {"content": tool_download_model(self.comfyui_url, params)}
        if name == "download":
            return {"content": tool_download(self.comfyui_url, params)}
        if name == "list_partner_models":
            return {"content": tool_list_partner_models(self.comfyui_url, params)}
        if name == "partner_model_schema":
            return {"content": tool_partner_model_schema(self.comfyui_url, params)}
        if name == "partner_generate":
            return {"content": tool_partner_generate(self.comfyui_url, params)}
        if name == "emit_partner_workflow":
            return {"content": tool_emit_partner_workflow(self.comfyui_url, params)}
        if name == "auth_status":
            return {"content": tool_auth_status(self.comfyui_url, params)}
        if name == "auth_login":
            return {"content": tool_auth_login(self.comfyui_url, params)}
        if name == "billing_status":
            return {"content": tool_billing_status(self.comfyui_url, params)}
        if name == "which":
            return {"content": tool_which(self.comfyui_url, params)}
        if name == "project":
            return {"content": tool_project(self.comfyui_url, params)}
        if name == "get_logs":
            return {"content": tool_get_logs(self.comfyui_url, params)}
        if name == "discover":
            return {"content": tool_discover(self.comfyui_url, params)}
        if name == "launch_comfyui":
            return {"content": tool_launch_comfyui(self.comfyui_url, params)}
        if name == "stop_comfyui":
            return {"content": tool_stop_comfyui(self.comfyui_url, params)}
        if name == "restart_comfyui":
            return {"content": tool_restart_comfyui(self.comfyui_url, params)}
        if name == "update_comfyui":
            return {"content": tool_update_comfyui(self.comfyui_url, params)}
        if name == "switch_comfyui_version":
            return {"content": tool_switch_comfyui_version(self.comfyui_url, params)}
        if name == "install_node":
            return {"content": tool_install_node(self.comfyui_url, params)}
        return {"content": {"error": f"unknown tool: {name}"}}

    def system_prompt(self, staged):
        tools_desc = json.dumps(TOOLS, indent=2)
        media_note = ""
        if staged:
            media_note = "\nREFERENCE MEDIA STAGED INTO ComfyUI INPUT FOLDER (usable by LoadImage/LoadAudio/whoever by filename):\n" + \
                "\n".join(f"- {m['file']} ({m['type']}) {m['note']}" for m in staged)
        models_dir_note = f"\nComfyUI models directory: {self.models_dir}" if self.models_dir else ""
        return f"""You are a ComfyUI MCP Agent - a general-purpose agent that drives the ENTIRE local ComfyUI on behalf of the user.

You have the same tool surface as a ComfyUI MCP server. Use the tools to ACTUALLY do the work - search and run real templates, query real node schemas, list real installed models, run workflows, poll jobs, fetch outputs, manage VRAM. NEVER fabricate workflows by hand and never claim success without running something.

Server URL: {self.comfyui_url}{models_dir_note}
Timeout per run: {self.timeout}s

AVAILABLE TOOLS:
{tools_desc}{media_note}

HOW TO WORK (mirror the official ComfyUI MCP flow exactly):
1. server_info FIRST - confirm the server is up.
2. DECIDE the model/pipeline from the user's request, never assume one: image -> an image template (FLUX/SDXL/SD1.5); audio -> an audio/TTS template (ACE-Step/fish-audio); video -> a video template (LTX-Video/Wan/H3); animation -> an AnimateDiff workflow. Find it via search_templates -> get_template(name) (local_check) -> fetch_template(name, out_path) which WRITES a runnable workflow JSON to disk and returns its path. All later work operates on that path.
3. list_workflow_slots(path) to see settable node_id.input addresses and current values; set_workflow_slot(path, overrides) to change them (model filenames must be EXACT installed names from search_models - never guess).
4. validate_workflow(path) before running. Then run_workflow(path, wait=true) to execute; it returns a prompt_id. Then fetch_outputs(prompt_id, out_dir=...) to download the generated files. Report the absolute file paths in "files".
5. run_template(name, overrides) is the one-shot convenience (fetch+fill+run+download) - use it when you are already confident of the template and its slots.
6. If VRAM is an issue or a run fails with out-of-memory, free_memory and retry.

TEMPLATE INTEGRITY (non-negotiable):
- A fetched template is a tuned graph. NEVER strip, mute, simplify, or delete its nodes, conditioning chains, LoRA/distilled paths, sigmas, or pass-through wiring. Change ONLY the prompt text, seed, and user-requested parameters (e.g. size/count). If an image-dependent path is a bypassed toggle, LEAVE it as-is.
- Server validation errors are the source of truth. When a run reports node_errors, read each input_name EXACTLY (it is the literal JSON key - keep dotted names like resize_type.width or values.a) and patch precisely that key on the workflow file with set_workflow_slot, then re-run. Never regenerate or hand-rebuild the template.

ROUTING & EXPECTATIONS:
- A single empty search is INCONCLUSIVE, not proof. Broaden it (drop version numbers, try the bare family name) before concluding a template/model/route is absent. Evidence beats assumption: a search that RETURNED something, or a run that succeeded, outranks a later empty lookup - never deny a route on an empty result alone.
- Some model families (MiniMax H3 is a current example) exist as BOTH a local OSS template (video_minimax_h3_*) and a paid API template (api_minimax_h3_*). Tell them apart by TEMPLATE NAME, never assume a family has only one route. This node runs everything LOCALLY for free.
- H3 on THIS machine (RTX 5060 Ti 16 GB): roughly 9-15 minutes per 5s clip at 480p, and generation time grows EXPONENTIALLY with pixel count. Quote the estimate before running. Faster = shorter duration/lower resolution; quality = ~768p canvas then upscale. If a run OOMs, lower the resolution or shorten duration - slow is not impossible, but OOM on 16 GB is real.
- The H3 image-to-video template ships with one deliberately disconnected helper node; validation may flag it - expected. Proceed once the main path is wired; do not treat it as a dead end.
- A graph must save/emit its output (SaveImage/SaveVideo/save node) to be retrievable. If a run reports it produces no output, re-fetch a template that saves, rather than running a graph that can only waste compute.

EXECUTE FAST - DO NOT SPEND ROUNDS SEARCHING:
- You are the client: the MODEL IS NEVER FIXED. Pick the template that matches the requested output type. Fetch it, wire the user's prompt text and any staged reference media into its slots, run, fetch outputs. Do not assume a reference image/audio forces any one model - wire it into whichever template the user's request calls for.
- Only call nodes/search_models/search_templates once to confirm a name if you must. Every round wasted on discovery instead of execution is a failure.
- YOU MAY NOT REPLY done until a workflow actually executed (run_template/run_workflow) AND its outputs were downloaded via fetch_outputs. Setting up slots is NOT success. If you have nothing real to show, run the template.
- If run_workflow/run_template returns a validation error, fix the reported node's input via set_workflow_slot on the fetched path and re-run; do not abandon the pipeline.

REFERENCE MEDIA: reference images are staged as PNG files, reference audio as WAV files (see REFERENCE MEDIA STAGED section). Use them by filename in template file widgets (e.g. LoadImage 'image', LoadAudio 'audio') and reference them in prompts via the template's documented tags (<Picture 1>, <Audio 1>, etc.).

CREATE vs EXECUTE: choose a tool for each action. You may call multiple tools across multiple rounds. When the user's goal is achieved and outputs are downloaded, stop and answer with your final summary.

OUTPUT FORMAT (STRICT JSON, no markdown, no code fences):
At EVERY round you reply with exactly one JSON object:
- To call a tool: {{"tool": "<name>", "params": {{...}}, "reason": "one line"}}
- To finish: {{"done": true, "summary": "what was created and file paths", "success_image": true_or_false}}

If a required model/file is missing, say so in reason and propose the nearest alternative found by listing models."""

    def run(self, user_message, reference_image=None, reference_audio=None, max_rounds=14, llm_call=None):
        self.user_message = user_message
        staged = self.stage_media(reference_image, reference_audio)
        session_system = self.system_prompt(staged)
        if staged:
            user_message = user_message + "\n\nReference media attached: " + ", ".join(m["file"] for m in staged)
        history = [{"role": "user", "content": user_message}]
        preview_tensor = None
        files_seen = []
        executed_tools = []
        run_executed = False
        discovery_tools = {"server_info", "nodes", "search_models", "search_templates", "get_template",
                           "list_workflow_slots", "system_stats"}
        for round_idx in range(max_rounds):
            self.log(f"round {round_idx + 1}/{max_rounds}")
            if staged and len(executed_tools) >= 4:
                streak = 0
                for t in reversed(executed_tools):
                    if t in discovery_tools:
                        streak += 1
                    else:
                        break
                if streak >= 4:
                    nudge = ("\n\nSTALL WARNING: your last " + str(streak) +
                             " calls were discovery only and NOTHING has been run yet. STOP discovering. "
                             "Execute now: fetch_template(name=<chosen>, out_path='job.json') then run_workflow(path) or run_template(name=<chosen>, overrides={...}) "
                             "then fetch_outputs(prompt_id, out_dir=...). The template is already chosen - just run it.")
                    history.append({"role": "user", "content": nudge})
                    self.log("STALL WARNING injected")
            
            if self.debug:
                self.log(f"--- LLM CALL ROUND {round_idx+1} ---")
                self.log(f"SYSTEM PROMPT: {session_system}")
                self.log(f"HISTORY: {json.dumps(history, default=_json_default)}")

            ok, response = llm_call(session_system, history)
            if not ok:
                return {"ok": False, "error": f"LLM call failed: {response}", "preview_tensor": None}
            
            if self.debug:
                self.log(f"RAW RESPONSE: {response}")

            text = response
            parsed = _parse_json(text)
            if parsed is None:
                if round_idx == 0 and len(history) == 1:
                    pass
                history.append({"role": "assistant", "content": text})
                history.append({"role": "user", "content": "Your last reply was not valid JSON. Reply with exactly one JSON object: a tool call {{tool, params, reason}} or {{done, summary, success_image}}."})
                continue
            
            if self.debug:
                self.log(f"PARSED JSON: {json.dumps(parsed, default=_json_default)}")

            if parsed.get("done"):
                if not run_executed:
                    self.log("done rejected: no run tool executed")
                    history.append({"role": "assistant", "content": text})
                    history.append({"role": "user", "content": (
                        "ILLEGAL STOP: you replied done but NEVER ran a workflow. Setup/discovery alone is not success. "
                        "Pick the template for the requested output, run it (run_template(name=..., overrides={...}) or run_workflow(path)), "
                        "then fetch_outputs(prompt_id, out_dir=...) to download the outputs. Only then may you reply done.")})
                    continue
                self.log("agent done")
                return {"ok": True, "summary": parsed.get("summary", text), "success_image": bool(parsed.get("success_image", False)),
                        "preview_tensor": preview_tensor, "files": files_seen}
            tool_name = parsed.get("tool")
            params = parsed.get("params", {}) or {}
            executed_tools.append(tool_name)
            if tool_name in ("run_workflow", "run_template"):
                run_executed = True
            self.log(f"tool: {tool_name} params={json.dumps(params, default=_json_default)[:300]}")
            
            if self.debug:
                self.log(f"EXECUTING TOOL: {tool_name} with params {json.dumps(params, default=_json_default)}")

            result = self.execute_tool(tool_name, params)
            
            if self.debug:
                self.log(f"TOOL RESULT RAW: {json.dumps(result, default=_json_default)}")

            content = result["content"]
            if result.get("preview") and isinstance(content, dict) and content.get("preview_tensor") is not None:
                preview_tensor = content["preview_tensor"]
                content = dict(content)
                content.pop("preview_tensor", None)
                content["success_image"] = True
            if isinstance(content, dict) and content.get("files"):
                files_seen = list(content["files"])
            history.append({"role": "assistant", "content": f"[tool {tool_name}] {json.dumps(parsed, default=_json_default)[:800]}"})
            history.append({"role": "user", "content": f"TOOL RESULT:\n{json.dumps(content, default=_json_default)[:4000]}"})
        return {"ok": True, "summary": "Maximum rounds reached. Outputs (if any): " + json.dumps(files_seen),
                "success_image": preview_tensor is not None, "preview_tensor": preview_tensor, "files": files_seen}


def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            return None
    return None