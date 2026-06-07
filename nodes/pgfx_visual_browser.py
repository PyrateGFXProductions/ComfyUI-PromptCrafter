import os
import sys
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
            }
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


NODE_CLASS_MAPPINGS = {
    "PGFX_VisualFolderLoader": PGFX_VisualFolderLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_VisualFolderLoader": "🖼️ PGFX Folder Image Loader",
}
