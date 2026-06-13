import os
import sys
import re
import hashlib
import asyncio
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

# V3 API support
try:
    from comfy_api.latest import io as v3_io
    V3_AVAILABLE = True
except ImportError:
    V3_AVAILABLE = False

def add_comfy_root_to_path():
    current_file = os.path.abspath(__file__)
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))
    if not os.path.exists(os.path.join(root, "main.py")):
        root = os.path.dirname(root)
    if root not in sys.path:
        sys.path.insert(0, root)
    return root

add_comfy_root_to_path()

import torch
import numpy as np
from PIL import Image, ImageOps
import folder_paths
from server import PromptServer
from aiohttp import web
import io
import json

_preview_cache = {}
from ..core import pgfx_api_clients as api_clients
from ..utils import pgfx_utils as utils

def get_node_description(node_name):
    try:
        help_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "HELP.md")
        if not os.path.exists(help_path):
            return f"Help file not found for {node_name}."
        import re
        with open(help_path, "r", encoding="utf-8") as f:
            content = f.read()
        pattern = re.compile(rf"##\s*`({node_name})(?:`|\s*\(.*?\)`)\n(.*?)(?=\n##\s*`|\Z)", re.DOTALL)
        match = pattern.search(content)
        if match:
            return match.group(2).strip()
        return f"No description found in HELP.md for {node_name}."
    except Exception as e:
        return f"Error reading help file: {e}"


def resolve_path(folder):
    """Resolve folder to an absolute path. If relative, treat as relative to output dir."""
    norm = os.path.normpath(folder)
    if os.path.isabs(norm):
        return norm
    drive, rest = os.path.splitdrive(norm)
    if drive and not rest:
        return os.path.normpath(drive + os.sep)
    return os.path.normpath(os.path.join(folder_paths.get_output_directory(), folder))


_PROMPT_SKIP_KEYS = {"filename_prefix", "base64_image_data", "canvas_json_data"}

def _extract_original_prompt(image_path):
    """Extract the original generation prompt from PNG metadata (ComfyUI's tEXt chunk)."""
    try:
        with Image.open(image_path) as img:
            prompt_json = img.info.get("prompt")
            if not prompt_json:
                return None
            prompt_data = json.loads(prompt_json)

            # Priority 1: CLIPTextEncode text field
            for node_id, node_data in prompt_data.items():
                if "CLIPTextEncode" in node_data.get("class_type", ""):
                    text = node_data.get("inputs", {}).get("text")
                    if isinstance(text, str) and len(text.strip()) > 10:
                        return text.strip()

            # Priority 2: ShowText / text output nodes
            for node_id, node_data in prompt_data.items():
                if "ShowText" in node_data.get("class_type", ""):
                    for v in node_data.get("inputs", {}).values():
                        if isinstance(v, str) and len(v.strip()) > 20:
                            return v.strip()

            # Priority 3: collect prompt-like strings across all nodes
            parts = []
            for node_id, node_data in prompt_data.items():
                for k, v in node_data.get("inputs", {}).items():
                    if (isinstance(v, str) and len(v.strip()) > 30
                            and k not in _PROMPT_SKIP_KEYS
                            and not v.startswith("pgfx_logo/")
                            and not v.startswith("{")):
                        parts.append(v.strip())
            if parts:
                return ". ".join(parts)

            return None
    except Exception:
        return None


class PGFX_VisualFolderLoader:
    """Load images from a folder with optional auto-captioning."""
    DESCRIPTION = get_node_description("PGFX_VisualFolderLoader")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder": ("STRING", {"default": ".", "multiline": False, "tooltip": "Folder path to load images from. Can be absolute or relative to ComfyUI output directory."}),
                "selected_image": ("STRING", {"default": "", "multiline": False, "tooltip": "Filename to load. Leave empty to auto-load the newest image."}),
                "caption_model": (api_clients.get_all_models(), {"tooltip": "Vision-capable model for auto-captioning."}),
            },
            "optional": {
                "caption_prompt": ("STRING", {"default": "", "multiline": True, "placeholder": "Describe this image.", "tooltip": "Custom prompt sent to the vision model when generating captions. Leave blank to use the built-in default captioning prompt."}),
                "auto_captioning": (["Disabled", "Always (Overwrite)", "If Missing"], {"default": "Disabled", "tooltip": "Controls when auto-captioning runs during workflow execution. 'Always' overwrites existing .txt files; 'If Missing' only creates captions for images that don't already have one."}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("image", "mask", "caption")
    FUNCTION = "load_image"
    CATEGORY = "☠️PGFX /Utils"

    def _save_caption_output(self, target_dir, filename, caption, caption_output="Sidecar .txt"):
        return _write_caption_file(target_dir, filename, caption, caption_output)

    def _caption_image(self, image_path, caption_model, caption_prompt, caption_output="Sidecar .txt"):
        try:
            p_text = caption_prompt
            if not p_text or not p_text.strip():
                original_prompt = _extract_original_prompt(image_path)
                if original_prompt:
                    p_text = f"Describe this image. Original prompt: {original_prompt}"
                else:
                    p_text = "Describe this image."
            else:
                p_text = f"Describe this image. Context: {p_text}"
            with Image.open(image_path) as pimg:
                img_tensor = utils.pil2tensor(pimg.convert("RGB"))
            ok, caption = api_clients.query_model_auto(
                caption_model, prompt=p_text, images=[img_tensor],
                prefer_chat=True, temperature=0.2, seed=42, timeout=120,
                llm_device="Default (GPU)",
            )
            if ok and caption:
                caption_str = caption.strip().strip("'\"").strip()
                target_dir = os.path.dirname(image_path)
                filename = os.path.basename(image_path)
                self._save_caption_output(target_dir, filename, caption_str, caption_output)
                return caption_str
        except Exception as e:
            print(f"[PGFX] Caption-on-save error: {e}")
        return ""

    def _save_images(self, images, target_dir, caption_model=None, caption_prompt=None, caption_on_save=False, caption_output="Sidecar .txt"):
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        print(f"[PGFX Save] _save_images: shape={images.shape}, target={target_dir}")

        _model_ready = caption_model and caption_model.strip() and caption_model.strip() != "NO_MODELS_FOUND" and caption_on_save == "Enabled"

        first_img = None
        saved_caption = ""
        for i in range(images.shape[0]):
            img_tensor = images[i] if images.dim() == 4 else images
            pil_img = utils.tensor2pil(img_tensor)
            filename = f"{timestamp}_{i:04d}.png"
            path = os.path.join(target_dir, filename)
            pil_img.save(path, "PNG")
            print(f"[PGFX Save] Saved: {path}")
            if i == 0:
                first_img = pil_img
            if _model_ready:
                c = self._caption_image(path, caption_model, caption_prompt, caption_output)
                if i == 0:
                    saved_caption = c

        img = first_img
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')
        if img.mode == 'RGBA':
            mask = np.array(img.getchannel('A')).astype(np.float32) / 255.0
            mask = 1.0 - mask
            mask = torch.from_numpy(mask).unsqueeze(0)
            img = img.convert('RGB')
        else:
            mask = torch.zeros((1, 64, 64), dtype=torch.float32)
        image = np.array(img).astype(np.float32) / 255.0
        image = torch.from_numpy(image).unsqueeze(0)
        return (image, mask, saved_caption)

    def load_image(self, folder, selected_image, caption_model="NO_MODELS_FOUND", caption_prompt=None, auto_captioning="Disabled"):
        target_dir = resolve_path(folder)
        if not os.path.exists(target_dir):
            os.makedirs(target_dir, exist_ok=True)

        image_path = None
        if selected_image:
            potential_path = os.path.join(target_dir, selected_image)
            if os.path.exists(potential_path):
                image_path = potential_path

        if not image_path:
            valid_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
            files = []
            if os.path.exists(target_dir):
                for f in os.listdir(target_dir):
                    ext = os.path.splitext(f)[1].lower()
                    if ext in valid_extensions:
                        files.append(os.path.join(target_dir, f))
            if files:
                files.sort(key=os.path.getmtime, reverse=True)
                image_path = files[0]

        if not image_path or not os.path.exists(image_path):
            raise FileNotFoundError(f"No images found in {target_dir}")

        caption_str = ""
        image_filename = os.path.basename(image_path)

        _model_usable = caption_model and caption_model.strip() and caption_model.strip() != "NO_MODELS_FOUND"
        if auto_captioning != "Disabled" and _model_usable:
            needs_caption = True
            if auto_captioning == "If Missing" and _caption_exists_any(target_dir, image_filename):
                needs_caption = False
            if needs_caption:
                try:
                    p_text = caption_prompt
                    if not p_text or not p_text.strip():
                        original_prompt = _extract_original_prompt(image_path)
                        if original_prompt:
                            p_text = f"Describe this image. Original prompt: {original_prompt}"
                        else:
                            p_text = "Describe this image."
                    else:
                        p_text = f"Describe this image. Context: {p_text}"
                    with Image.open(image_path) as pimg:
                        img_tensor = utils.pil2tensor(pimg.convert("RGB"))
                    ok, caption = api_clients.query_model_auto(
                        caption_model, prompt=p_text, images=[img_tensor],
                        prefer_chat=True, temperature=0.2, seed=42, timeout=120,
                        llm_device="Default (GPU)"
                    )
                    if ok and caption:
                        caption_str = caption.strip().strip("'\"").strip()
                        self._save_caption_output(target_dir, image_filename, caption_str, "Sidecar .txt")
                except Exception as e:
                    print(f"[PGFX] Auto-captioning error on execution: {e}")

        if not caption_str:
            caption_str = _read_caption_any(target_dir, image_filename)

        Image.MAX_IMAGE_PIXELS = None
        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img)
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')
        if img.mode == 'RGBA':
            mask = np.array(img.getchannel('A')).astype(np.float32) / 255.0
            mask = 1.0 - mask
            mask = torch.from_numpy(mask).unsqueeze(0)
            img = img.convert('RGB')
        else:
            mask = torch.zeros((1, 64, 64), dtype=torch.float32)
        image = np.array(img).astype(np.float32) / 255.0
        image = torch.from_numpy(image).unsqueeze(0)
        if mask.shape[1:] != image.shape[1:3]:
            mask = torch.zeros((1, image.shape[1], image.shape[2]), dtype=torch.float32)
        return (image, mask, caption_str)


# ---------------------------------------------------------------------------
# Module-level caption output helper (used by class methods and API routes)
# ---------------------------------------------------------------------------
def _write_caption_file(target_dir, filename, caption, caption_output="Sidecar .txt"):
    """Save caption in the selected output format.
    Returns True on success, False on failure.
    """
    if not caption or not caption.strip():
        return False
    caption = caption.strip()
    norm_target = os.path.normpath(target_dir)

    try:
        if caption_output == "Single JSON":
            json_path = os.path.join(target_dir, "captions.json")
            data = {}
            if os.path.exists(json_path):
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception:
                    data = {}
            key = os.path.splitext(filename)[0]
            data[key] = caption
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True

        elif caption_output == "Single TXT Append":
            txt_path = os.path.join(target_dir, "captions.txt")
            with open(txt_path, "a", encoding="utf-8") as f:
                f.write(f"{filename}: {caption}\n\n")
            return True

        else:
            txt_path = os.path.normpath(os.path.join(target_dir, os.path.splitext(filename)[0] + ".txt"))
            if not txt_path.startswith(norm_target):
                return False
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(caption)
            return True
    except Exception as e:
        print(f"[PGFX] Write caption file error: {e}")
        return False


def _caption_exists_any(target_dir, filename):
    """Check if a caption exists for the given image in ANY known format.
    Checks sidecar .txt, captions.json, and captions.txt.
    """
    # Sidecar .txt
    txt_path = os.path.join(target_dir, os.path.splitext(filename)[0] + ".txt")
    if os.path.exists(txt_path):
        return True

    # Single JSON
    json_path = os.path.join(target_dir, "captions.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = os.path.splitext(filename)[0]
            if key in data and data[key].strip():
                return True
        except Exception:
            pass

    # Single TXT Append
    append_path = os.path.join(target_dir, "captions.txt")
    if os.path.exists(append_path):
        try:
            with open(append_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith(f"{filename}:"):
                        return True
        except Exception:
            pass

    return False


def _read_caption_any(target_dir, filename):
    """Read a caption for the given image from ANY known format.
    Tries sidecar .txt first, then captions.json, then captions.txt.
    Returns empty string if none found.
    """
    # Sidecar .txt
    txt_path = os.path.join(target_dir, os.path.splitext(filename)[0] + ".txt")
    if os.path.exists(txt_path):
        try:
            with open(txt_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass

    # Single JSON
    json_path = os.path.join(target_dir, "captions.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key = os.path.splitext(filename)[0]
            val = data.get(key, "")
            if val.strip():
                return val.strip()
        except Exception:
            pass

    # Single TXT Append
    append_path = os.path.join(target_dir, "captions.txt")
    if os.path.exists(append_path):
        try:
            with open(append_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith(f"{filename}:"):
                        return line[len(filename) + 1:].strip()
        except Exception:
            pass

    return ""


# ---------------------------------------------------------------------------
# API: serve image bytes from arbitrary path
# ---------------------------------------------------------------------------
@PromptServer.instance.routes.get("/pgfx/browser/serve")
async def serve_image(request):
    try:
        path = request.query.get("path", "")
        if not path:
            return web.json_response({"error": "Missing path"}, status=400)
        full = os.path.normpath(path)
        if not os.path.exists(full):
            return web.json_response({"error": "File not found"}, status=404)

        # Handle thumbnail preview requests to reduce client-side rendering lag
        preview = request.query.get("preview", "").lower() == "true"
        if preview:
            mtime = os.path.getmtime(full)
            cache_key = (full, mtime)
            if cache_key in _preview_cache:
                return web.Response(body=_preview_cache[cache_key], content_type="image/jpeg")

            try:
                with Image.open(full) as img:
                    img.thumbnail((180, 180))
                    # Handle alpha channels if saving to JPEG
                    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                        background = Image.new("RGB", img.size, (0, 0, 0))
                        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
                        img = background
                    elif img.mode != "RGB":
                        img = img.convert("RGB")

                    out_io = io.BytesIO()
                    img.save(out_io, format="JPEG", quality=75)
                    thumb_bytes = out_io.getvalue()

                    # Simple cache size control to prevent memory leaks
                    if len(_preview_cache) > 2000:
                        _preview_cache.clear()
                    _preview_cache[cache_key] = thumb_bytes

                return web.Response(body=thumb_bytes, content_type="image/jpeg")
            except Exception as e:
                print(f"[PGFX] Preview generation failed for {full}: {e}")

        return web.FileResponse(full)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# API: list subfolders
# ---------------------------------------------------------------------------
@PromptServer.instance.routes.get("/pgfx/browser/subfolders")
async def get_subfolders(request):
    try:
        folder = request.query.get("folder", ".")
        target_dir = resolve_path(folder)
        if not os.path.exists(target_dir):
            return web.json_response({"error": "Folder not found"}, status=404)

        subfolders = []
        for entry in os.scandir(target_dir):
            if entry.is_dir() and not entry.name.startswith("."):
                subfolders.append(entry.name)
        subfolders.sort(key=str.lower)

        parent = None
        parent_dir = os.path.dirname(target_dir)
        if parent_dir != target_dir and os.path.exists(parent_dir):
            parent = parent_dir

        return web.json_response({
            "subfolders": subfolders,
            "parent": parent,
            "current": target_dir,
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# API: list images with pagination + search
# ---------------------------------------------------------------------------
@PromptServer.instance.routes.get("/pgfx/browser/images")
async def get_images(request):
    try:
        folder = request.query.get("folder", ".")
        search = request.query.get("search", "").strip().lower()
        page = int(request.query.get("page", "0"))
        per_page = int(request.query.get("per_page", "18"))
        target_dir = resolve_path(folder)

        if not os.path.exists(target_dir):
            return web.json_response({"error": "Folder not found"}, status=404)

        valid_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
        all_images = []
        for entry in os.scandir(target_dir):
            if entry.is_file() and os.path.splitext(entry.name)[1].lower() in valid_extensions:
                if search and search not in entry.name.lower():
                    continue
                mtime = entry.stat().st_mtime
                full_path = os.path.join(target_dir, entry.name)
                has_caption = _caption_exists_any(target_dir, entry.name)
                all_images.append({
                    "filename": entry.name,
                    "mtime": mtime,
                    "path": full_path,
                    "url": f"/pgfx/browser/serve?path={quote(full_path)}",
                    "has_caption": has_caption,
                })

        all_images.sort(key=lambda x: x["mtime"], reverse=True)

        total = len(all_images)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))
        start = page * per_page
        end = start + per_page
        page_images = all_images[start:end]

        return web.json_response({
            "images": page_images,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
            "current": target_dir,
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# API: image details
# ---------------------------------------------------------------------------
@PromptServer.instance.routes.get("/pgfx/browser/details")
async def get_image_details(request):
    try:
        folder = request.query.get("folder", ".")
        filename = request.query.get("filename", "")
        target_dir = resolve_path(folder)
        full_path = os.path.normpath(os.path.join(target_dir, filename))

        if not full_path.startswith(os.path.normpath(target_dir)):
            return web.json_response({"error": "Access denied"}, status=403)
        if not os.path.exists(full_path):
            return web.json_response({"error": "File not found"}, status=404)

        stats = os.stat(full_path)
        size_bytes = stats.st_size
        size_str = f"{size_bytes / 1024:.1f} KB" if size_bytes < 1024 * 1024 else f"{size_bytes / (1024 * 1024):.1f} MB"

        mtime = stats.st_mtime
        from datetime import datetime
        date_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')

        width, height = 0, 0
        try:
            with Image.open(full_path) as img:
                width, height = img.size
        except Exception:
            pass

        return web.json_response({
            "filename": filename,
            "resolution": f"{width} x {height}",
            "size": size_str,
            "date": date_str,
            "format": os.path.splitext(filename)[1].upper().replace(".", ""),
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# API: read caption sidecar file
# ---------------------------------------------------------------------------
@PromptServer.instance.routes.get("/pgfx/browser/caption")
async def get_caption(request):
    try:
        folder = request.query.get("folder", ".")
        filename = request.query.get("filename", "")
        target_dir = resolve_path(folder)
        caption = _read_caption_any(target_dir, filename)
        source = "found" if caption else "none"
        return web.json_response({"caption": caption, "source": source})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# API: save caption sidecar file
# ---------------------------------------------------------------------------
@PromptServer.instance.routes.post("/pgfx/browser/save-caption")
async def save_caption(request):
    try:
        body = await request.json()
        folder = body.get("folder", ".")
        filename = body.get("filename", "")
        caption = body.get("caption", "")
        caption_output = body.get("caption_output", "Sidecar .txt")
        target_dir = resolve_path(folder)
        ok = _write_caption_file(target_dir, filename, caption, caption_output)
        if ok:
            return web.json_response({"success": True})
        else:
            return web.json_response({"error": "Failed to save caption"}, status=500)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# API: generate caption using vision model
# ---------------------------------------------------------------------------
@PromptServer.instance.routes.post("/pgfx/browser/generate-caption")
async def generate_caption(request):
    try:
        body = await request.json()
        folder = body.get("folder", ".")
        filename = body.get("filename", "")
        model = body.get("model", "")
        user_prompt = body.get("prompt", "")
        temperature = float(body.get("temperature", 0.2))

        if not model:
            return web.json_response({"error": "No vision model specified"}, status=400)

        target_dir = resolve_path(folder)
        image_path = os.path.normpath(os.path.join(target_dir, filename))
        if not image_path.startswith(os.path.normpath(target_dir)):
            return web.json_response({"error": "Access denied"}, status=403)
        if not os.path.exists(image_path):
            return web.json_response({"error": "File not found"}, status=404)

        if not user_prompt or not user_prompt.strip():
            original_prompt = _extract_original_prompt(image_path)
            if original_prompt:
                prompt_text = f"Describe this image. Original prompt: {original_prompt}"
            else:
                prompt_text = "Describe this image."
        else:
            prompt_text = f"Describe this image. Context: {user_prompt}"

        with Image.open(image_path) as img:
            img_tensor = utils.pil2tensor(img.convert("RGB"))

        ok, caption = await asyncio.to_thread(
            api_clients.query_model_auto,
            model,
            prompt=prompt_text,
            images=[img_tensor],
            prefer_chat=True,
            temperature=temperature,
            seed=42,
            timeout=120,
            llm_device="Default (GPU)",
        )

        if not ok:
            return web.json_response({"error": str(caption)}, status=500)

        caption = caption.strip().strip("'\"").strip()
        return web.json_response({"caption": caption, "model": model})

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# API: batch caption all uncaptioned images
# ---------------------------------------------------------------------------
@PromptServer.instance.routes.post("/pgfx/browser/caption-batch")
async def caption_batch(request):
    try:
        body = await request.json()
        folder = body.get("folder", ".")
        model = body.get("model", "")
        user_prompt = body.get("prompt", "")
        overwrite = body.get("overwrite", False)
        concurrency = int(body.get("concurrency", 2))
        caption_output = body.get("caption_output", "Sidecar .txt")

        if not model:
            return web.json_response({"error": "No vision model specified"}, status=400)

        target_dir = resolve_path(folder)
        if not os.path.exists(target_dir):
            return web.json_response({"error": "Folder not found"}, status=404)

        entries = [e for e in _list_images(target_dir)]

        # Filter to uncaptioned unless overwrite is True
        to_process = []
        already_has = 0
        for entry in entries:
            if not overwrite and _caption_exists_any(target_dir, entry.name):
                already_has += 1
                continue
            to_process.append(entry)

        total = len(to_process)
        if total == 0:
            return web.json_response({
                "processed": 0, "skipped": already_has, "total": total,
                "message": "All images already have captions." if already_has > 0 else "No images found.",
            })

        results = {"success": [], "failed": [], "skipped": already_has}

        def process_one(entry):
            try:
                txt_path = os.path.join(target_dir, os.path.splitext(entry.name)[0] + ".txt")
                if not overwrite and os.path.exists(txt_path):
                    return
                with Image.open(entry.path) as img:
                    img_tensor = utils.pil2tensor(img.convert("RGB"))
                # Build per-image prompt: user override > metadata > default
                if not user_prompt or not user_prompt.strip():
                    original_prompt = _extract_original_prompt(entry.path)
                    if original_prompt:
                        local_prompt = f"Describe this image. Original prompt: {original_prompt}"
                    else:
                        local_prompt = "Describe this image."
                else:
                    local_prompt = f"Describe this image. Context: {user_prompt}"
                ok, caption = api_clients.query_model_auto(
                    model, prompt=local_prompt, images=[img_tensor],
                    prefer_chat=True, temperature=0.2, seed=42, timeout=120,
                    llm_device="Default (GPU)",
                )
                if ok and caption:
                    caption = caption.strip().strip("'\"").strip()
                    saved = _write_caption_file(target_dir, entry.name, caption, caption_output)
                    if saved:
                        results["success"].append(entry.name)
                    else:
                        results["failed"].append({"file": entry.name, "reason": "Save failed"})
                else:
                    results["failed"].append({"file": entry.name, "reason": str(caption)})
            except Exception as ex:
                results["failed"].append({"file": entry.name, "reason": str(ex)})

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            pool.map(process_one, to_process, chunksize=1)

        return web.json_response({
            "processed": len(results["success"]),
            "failed": len(results["failed"]),
            "skipped": results["skipped"],
            "total": total,
            "errors": results["failed"][:10],  # first 10 errors
        })

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ---------------------------------------------------------------------------
# Duplicate detection utilities
# ---------------------------------------------------------------------------

def _dhash(image_path, hash_size=8):
    """Compute a perceptual difference hash (dhash) for an image.
    Returns a 64-bit integer. Similar images have similar hashes.
    """
    with Image.open(image_path) as img:
        img = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
        pixels = list(img.getdata())
        diff = 0
        for row in range(hash_size):
            for col in range(hash_size):
                idx = row * (hash_size + 1) + col
                if pixels[idx] < pixels[idx + 1]:
                    diff |= 1 << (row * hash_size + col)
        return diff


def _hamming_distance(h1, h2):
    """Number of bits different between two hashes."""
    return bin(h1 ^ h2).count("1")


def _compute_md5(filepath):
    """Compute MD5 hash for exact duplicate detection."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


VALID_IMG_EXT = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tiff', '.tif'}


def _list_images(target_dir):
    """List all image files in a directory, sorted by modification time (newest first)."""
    result = []
    try:
        for entry in os.scandir(target_dir):
            if entry.is_file() and os.path.splitext(entry.name)[1].lower() in VALID_IMG_EXT:
                result.append(entry)
    except PermissionError:
        pass
    return result


# ---------------------------------------------------------------------------
# API: scan for duplicate images
# ---------------------------------------------------------------------------
@PromptServer.instance.routes.post("/pgfx/browser/scan-duplicates")
async def scan_duplicates(request):
    try:
        body = await request.json()
        folder = body.get("folder", ".")
        threshold = int(body.get("threshold", 10))  # max hamming distance for near duplicates
        target_dir = resolve_path(folder)

        if not os.path.exists(target_dir):
            return web.json_response({"error": "Folder not found"}, status=404)

        entries = _list_images(target_dir)
        if not entries:
            return web.json_response({"groups": [], "total_duplicates": 0, "total_files": 0})

        total_files = len(entries)

        # Phase 1: MD5 for exact duplicates
        md5_map = {}
        for entry in entries:
            try:
                md5 = _compute_md5(entry.path)
                md5_map.setdefault(md5, []).append(entry)
            except Exception:
                pass

        exact_groups = [v for v in md5_map.values() if len(v) > 1]

        # Phase 2: dhash for near duplicates (skip files already in exact groups)
        exact_paths = set()
        for group in exact_groups:
            for e in group:
                exact_paths.add(e.path)

        dhash_groups = []
        remaining = [e for e in entries if e.path not in exact_paths]

        if remaining:
            hash_map = {}
            for entry in remaining:
                try:
                    h = _dhash(entry.path)
                    hash_map.setdefault(h, []).append(entry)
                except Exception:
                    pass

            hashes = list(hash_map.keys())
            used = set()
            for i, h1 in enumerate(hashes):
                if h1 in used:
                    continue
                cluster = []
                for j, h2 in enumerate(hashes):
                    if h2 in used:
                        continue
                    if h1 == h2 or _hamming_distance(h1, h2) <= threshold:
                        cluster.extend(hash_map[h2])
                        used.add(h2)
                if len(cluster) > 1:
                    dhash_groups.append(cluster)

        # Build response
        groups = []
        for group in exact_groups:
            files = []
            for entry in group:
                size_str = _format_size(entry.stat().st_size)
                files.append({
                    "filename": entry.name,
                    "path": entry.path,
                    "size": size_str,
                    "url": f"/pgfx/browser/serve?path={quote(entry.path)}",
                })
            groups.append({
                "type": "exact",
                "similarity": 1.0,
                "files": files,
            })

        for group in dhash_groups:
            files = []
            for entry in group:
                size_str = _format_size(entry.stat().st_size)
                files.append({
                    "filename": entry.name,
                    "path": entry.path,
                    "size": size_str,
                    "url": f"/pgfx/browser/serve?path={quote(entry.path)}",
                })
            groups.append({
                "type": "near",
                "similarity": 0.9,
                "files": files,
            })

        total_duplicates = sum(len(g["files"]) for g in groups)

        return web.json_response({
            "groups": groups,
            "total_duplicates": total_duplicates,
            "total_files": total_files,
            "current": target_dir,
        })

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def _format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


# ---------------------------------------------------------------------------
# API: delete files
# ---------------------------------------------------------------------------
@PromptServer.instance.routes.post("/pgfx/browser/delete-files")
async def delete_files(request):
    try:
        body = await request.json()
        paths = body.get("files", [])
        if not isinstance(paths, list) or not paths:
            return web.json_response({"error": "No files provided"}, status=400)

        deleted = []
        failed = []
        for filepath in paths:
            try:
                norm = os.path.normpath(filepath)
                if not os.path.exists(norm):
                    failed.append({"path": filepath, "reason": "File not found"})
                    continue
                os.remove(norm)
                deleted.append(filepath)
            except Exception as e:
                failed.append({"path": filepath, "reason": str(e)})

        return web.json_response({
            "deleted": deleted,
            "failed": failed,
            "total_deleted": len(deleted),
            "total_failed": len(failed),
        })

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


NODE_CLASS_MAPPINGS = {
    "PGFX_VisualFolderLoader": PGFX_VisualFolderLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_VisualFolderLoader": "🖼️ PGFX Folder Image Loader",
}
