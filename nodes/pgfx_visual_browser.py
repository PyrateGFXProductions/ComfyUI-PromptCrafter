import os
import sys
import re
import hashlib
import asyncio
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

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


class PGFX_VisualFolderLoader:
    DESCRIPTION = get_node_description("PGFX_VisualFolderLoader")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "folder": ("STRING", {"default": ".", "multiline": False, "tooltip": "Folder path. Can be absolute (e.g. C:/Users/name/Pictures) or relative to the ComfyUI output directory."}),
                "selected_image": ("STRING", {"default": "", "multiline": False, "tooltip": "Filename of the selected image. Leave empty to auto-load the newest image."}),
            },
            "optional": {
                "caption_model": ("STRING", {"default": "", "tooltip": "Vision model for auto-captioning (e.g. gguf/llava-v1.6, or an Ollama/OpenAI model name). Leave empty to disable captioning."}),
                "caption_prompt": ("STRING", {"default": "Describe this image in detail, focusing on the subject, setting, composition, lighting, and style.", "multiline": True, "tooltip": "Prompt template sent to the vision model when generating captions."}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    FUNCTION = "load_image"
    CATEGORY = "☠️PGFX /Utils"

    def load_image(self, folder, selected_image):
        target_dir = resolve_path(folder)
        if not os.path.exists(target_dir):
            raise FileNotFoundError(f"Folder not found: {target_dir}")

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

        return (image, mask)


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
                all_images.append({
                    "filename": entry.name,
                    "mtime": mtime,
                    "path": full_path,
                    "url": f"/pgfx/browser/serve?path={quote(full_path)}",
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
        txt_path = os.path.normpath(os.path.join(target_dir, os.path.splitext(filename)[0] + ".txt"))
        if not txt_path.startswith(os.path.normpath(target_dir)):
            return web.json_response({"error": "Access denied"}, status=403)
        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                text = f.read()
            return web.json_response({"caption": text, "source": "file"})
        return web.json_response({"caption": "", "source": "none"})
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
        target_dir = resolve_path(folder)
        txt_path = os.path.normpath(os.path.join(target_dir, os.path.splitext(filename)[0] + ".txt"))
        if not txt_path.startswith(os.path.normpath(target_dir)):
            return web.json_response({"error": "Access denied"}, status=403)
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(caption)
        return web.json_response({"success": True, "path": txt_path})
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
        prompt_text = body.get("prompt", "Describe this image in detail.")
        temperature = float(body.get("temperature", 0.2))

        if not model:
            return web.json_response({"error": "No vision model specified"}, status=400)

        target_dir = resolve_path(folder)
        image_path = os.path.normpath(os.path.join(target_dir, filename))
        if not image_path.startswith(os.path.normpath(target_dir)):
            return web.json_response({"error": "Access denied"}, status=403)
        if not os.path.exists(image_path):
            return web.json_response({"error": "File not found"}, status=404)

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
        prompt_text = body.get("prompt", "Describe this image in detail.")
        overwrite = body.get("overwrite", False)
        concurrency = int(body.get("concurrency", 2))

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
            txt_path = os.path.join(target_dir, os.path.splitext(entry.name)[0] + ".txt")
            if not overwrite and os.path.exists(txt_path):
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
                ok, caption = api_clients.query_model_auto(
                    model, prompt=prompt_text, images=[img_tensor],
                    prefer_chat=True, temperature=0.2, seed=42, timeout=120,
                    llm_device="Default (GPU)",
                )
                if ok and caption:
                    caption = caption.strip().strip("'\"").strip()
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(caption)
                    results["success"].append(entry.name)
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
