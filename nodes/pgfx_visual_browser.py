import os
import sys

# --- Core Path Fix ---
# Force Python to register ComfyUI's root directory in its lookup paths.
# This prevents ModuleNotFoundError: No module named 'utils.install_util'
def add_comfy_root_to_path():
    current_file = os.path.abspath(__file__)
    # We are in custom_nodes/ComfyUI-PromptCrafter/nodes/pgfx_visual_browser.py
    # We need to go up 3 levels to reach custom_nodes/
    # And one more to reach the ComfyUI root.
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(current_file))))
    
    # If we are directly in custom_nodes (not nested in another folder), adjust accordingly
    if not os.path.exists(os.path.join(root, "main.py")):
        # Try one more level up just in case
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

# ------------------------------------------------------------------------------------
# Helper function to read node descriptions from HELP.md
# ------------------------------------------------------------------------------------
def get_node_description(node_name):
    """Parses HELP.md and extracts the description for a given node class name."""
    try:
        help_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "HELP.md")
        if not os.path.exists(help_path):
            return f"Help file not found for {node_name}."

        with open(help_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Match either ## `NodeName` or ## `NodeName` (Alternate Name)
        pattern = re.compile(rf"##\s*`({node_name})(?:`|\s*\(.*?\)`)\n(.*?)(?=\n##\s*`|\Z)", re.DOTALL)
        match = pattern.search(content)

        if match:
            return match.group(2).strip()
        return f"No description found in HELP.md for {node_name}."
    except Exception as e:
        return f"Error reading help file: {e}"

class PGFX_VisualFolderLoader:
    """
    A multi-image thumbnail loader that allows users to visually browse and select images 
    from their ComfyUI output directory or custom folders.
    """
    DESCRIPTION = get_node_description("PGFX_VisualFolderLoader")
    
    @classmethod
    def INPUT_TYPES(cls):
        # We populate the folder list dynamically on the frontend, but we need a starting point.
        output_dir = folder_paths.get_output_directory()
        folders = ["."]
        try:
            if os.path.exists(output_dir):
                for root, dirs, files in os.walk(output_dir):
                    for d in dirs:
                        if d.startswith("."):
                            continue
                        rel_path = os.path.relpath(os.path.join(root, d), output_dir)
                        # Use forward slashes for cross-platform compatibility in the widget
                        folders.append(rel_path.replace("\\", "/"))
        except Exception:
            pass

        return {
            "required": {
                "folder": (folders, {"default": ".", "tooltip": "Select a folder to browse. Supports recursive discovery—you can navigate into multi-level subdirectories (e.g., '2026/portraits/final')."}),
                "selected_image": ("STRING", {"default": "", "multiline": False, "tooltip": "The filename of the image selected in the visual grid. Leave empty to automatically load the newest image in the folder."}),
            }
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    FUNCTION = "load_image"
    CATEGORY = "☠️PGFX /Utils"

    def load_image(self, folder, selected_image):
        root_output = folder_paths.get_output_directory()
        target_dir = os.path.abspath(os.path.join(root_output, folder))
        
        # Security check: Ensure target_dir is inside root_output
        if not target_dir.startswith(os.path.abspath(root_output)):
            print(f"[PGFX] Security Warning: Attempted access outside output directory: {target_dir}")
            raise Exception("Access denied: Path outside output directory.")

        image_path = None
        if selected_image:
            potential_path = os.path.join(target_dir, selected_image)
            if os.path.exists(potential_path):
                image_path = potential_path
        
        # Fallback: Load newest image if none selected or selection invalid
        if not image_path:
            valid_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
            files = []
            if os.path.exists(target_dir):
                for f in os.listdir(target_dir):
                    if os.path.splitext(f)[1].lower() in valid_extensions:
                        files.append(os.path.join(target_dir, f))
            
            if files:
                # Sort by modification time
                files.sort(key=os.path.getmtime, reverse=True)
                image_path = files[0]
                print(f"[PGFX] Visual Browser: No image selected, loading newest: {os.path.basename(image_path)}")

        if not image_path or not os.path.exists(image_path):
            raise FileNotFoundError(f"Could not find an image to load in {target_dir}")

        # Decompression Bomb Bypass
        Image.MAX_IMAGE_PIXELS = None 
        
        # Load image using PIL
        img = Image.open(image_path)
        img = ImageOps.exif_transpose(img)
        
        # Handle RGB conversion
        if img.mode != 'RGB' and img.mode != 'RGBA':
            img = img.convert('RGB')
            
        # Extract Mask if RGBA
        if img.mode == 'RGBA':
            mask = np.array(img.getchannel('A')).astype(np.float32) / 255.0
            mask = 1.0 - mask # ComfyUI standard: 1.0 is masked (black), 0.0 is unmasked (white)
            mask = torch.from_numpy(mask).unsqueeze(0)
            img = img.convert('RGB')
        else:
            mask = torch.zeros((1, 64, 64), dtype=torch.float32) # Default empty mask

        # Convert to Tensor (B, H, W, C)
        image = np.array(img).astype(np.float32) / 255.0
        image = torch.from_numpy(image).unsqueeze(0)

        # Resize mask to match image if it was a default mask
        if mask.shape[1:] != image.shape[1:3]:
            mask = torch.zeros((1, image.shape[1], image.shape[2]), dtype=torch.float32)

        return (image, mask)

# --- API Endpoints ---

@PromptServer.instance.routes.get("/pgfx/browser/folders")
async def get_folders(request):
    try:
        root_output = folder_paths.get_output_directory()
        folders = ["."]
        if os.path.exists(root_output):
            for root, dirs, files in os.walk(root_output):
                for d in dirs:
                    if d.startswith("."):
                        continue
                    # Calculate relative path from root_output
                    rel_path = os.path.relpath(os.path.join(root, d), root_output)
                    # Use forward slashes for consistency across platforms and the web
                    folders.append(rel_path.replace("\\", "/"))
        
        # Sort folders for better UX
        folders.sort(key=lambda x: (x != ".", x.lower()))
        return web.json_response(folders)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.get("/pgfx/browser/images")
async def get_images(request):
    try:
        folder = request.query.get("folder", ".")
        root_output = folder_paths.get_output_directory()
        target_dir = os.path.abspath(os.path.join(root_output, folder))

        # Security check
        if not target_dir.startswith(os.path.abspath(root_output)):
            return web.json_response({"error": "Access denied"}, status=403)

        if not os.path.exists(target_dir):
            return web.json_response({"error": "Folder not found"}, status=404)

        valid_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
        images = []
        for f in os.listdir(target_dir):
            if os.path.splitext(f)[1].lower() in valid_extensions:
                full_path = os.path.join(target_dir, f)
                mtime = os.path.getmtime(full_path)
                images.append({
                    "filename": f,
                    "mtime": mtime,
                    "url": f"/view?filename={f}&subfolder={folder}&type=output"
                })

        # Sort newest first
        images.sort(key=lambda x: x["mtime"], reverse=True)
        
        return web.json_response(images)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@PromptServer.instance.routes.get("/pgfx/browser/details")
async def get_image_details(request):
    try:
        folder = request.query.get("folder", ".")
        filename = request.query.get("filename", "")
        root_output = folder_paths.get_output_directory()
        target_dir = os.path.abspath(os.path.join(root_output, folder))
        full_path = os.path.join(target_dir, filename)

        # Security check
        if not os.path.abspath(full_path).startswith(os.path.abspath(root_output)):
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
            "format": os.path.splitext(filename)[1].upper().replace(".", "")
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

NODE_CLASS_MAPPINGS = {
    "PGFX_VisualFolderLoader": PGFX_VisualFolderLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_VisualFolderLoader": "🖼️ PGFX Visual Folder Browser",
}
