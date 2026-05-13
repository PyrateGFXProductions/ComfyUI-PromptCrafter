import torch
import numpy as np
from PIL import Image
import io
import os
import time
import logging

# Local module imports
from ..core import pgfx_config as config
from ..utils import pgfx_utils as utils

# Set up logging for the brand
logger = logging.getLogger("PromptCrafter")

# Dependency Guard
try:
    import vtracer
except ImportError:
    vtracer = None
    logger.warning("PromptCrafter: 'vtracer' library not found. Image to SVG node will be disabled. To fix: pip install vtracer")

class CP_ImageToSVG:
    """
    PromptCrafter Image to SVG
    Converts model-generated images into vector SVG files locally.
    """
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "colormode": (["color", "bw"], {"default": "color"}),
                "hierarchical": (["stacked", "cutout"], {"default": "stacked"}),
                "color_precision": ("INT", {"default": 6, "min": 1, "max": 8}),
                "layer_difference": ("INT", {"default": 16, "min": 0, "max": 255}),
                "path_precision": ("INT", {"default": 3, "min": 1, "max": 10}),
                "simplify_tolerance": ("INT", {"default": 2, "min": 0, "max": 10}),
            },
            "optional": {
                "filename_prefix": ("STRING", {"default": "PromptCrafter_Vector"}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING",)
    RETURN_NAMES = ("svg_raw", "file_path",)
    FUNCTION = "vectorize"
    CATEGORY = "☠️PGFX🏴‍☠️ /Vector"

    def vectorize(self, image, colormode, hierarchical, color_precision, layer_difference, path_precision, simplify_tolerance, filename_prefix="PromptCrafter_Vector"):
        if vtracer is None:
            raise ImportError("PromptCrafter: The 'vtracer' library is required for the Image to SVG node but is not installed. Please run: pip install vtracer")

        # 1. Convert ComfyUI Tensor [B, H, W, C] to PIL Image
        # We process the first image in the batch
        i = 255. * image[0].cpu().numpy()
        img = Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
        
        # 2. Convert PIL to bytes for vtracer
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_bytes = img_byte_arr.getvalue()

        # 3. Run local vectorization
        svg_str = vtracer.convert_raw_image_to_svg(
            img_bytes,
            img_format="png",
            colormode=colormode,
            hierarchical=hierarchical,
            color_precision=color_precision,
            layer_difference=layer_difference,
            path_precision=path_precision,
            length_threshold=float(simplify_tolerance),
            splice_threshold=simplify_tolerance * 10, # Scale to a reasonable degree range
            filter_speckle=simplify_tolerance
        )

        # 4. Handle Saving (Optional but helpful)
        file_path = ""
        if filename_prefix and filename_prefix.strip():
            output_dir = os.path.join(config.COMFYUI_ROOT_DIR, "output", "svg")
            os.makedirs(output_dir, exist_ok=True)
            
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            full_path, _ = utils._get_unique_filepath(output_dir, f"{filename_prefix}_{timestamp}", ".svg")
            
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(svg_str)
            file_path = full_path

        return (svg_str, file_path,)

class CP_SaveSVG:
    """
    PromptCrafter Save SVG
    Saves a raw SVG string to the output directory.
    """
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "svg_raw": ("STRING", {"forceInput": True}),
                "filename_prefix": ("STRING", {"default": "PromptCrafter_SVG"}),
                "output_path": ("STRING", {"default": "svg"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("file_path",)
    FUNCTION = "save_svg"
    OUTPUT_NODE = True
    CATEGORY = "☠️PGFX🏴‍☠️ /Vector"

    def save_svg(self, svg_raw, filename_prefix, output_path):
        # 1. Resolve Output Directory
        base_output = os.path.join(config.COMFYUI_ROOT_DIR, "output")
        target_dir = os.path.join(base_output, output_path)
        os.makedirs(target_dir, exist_ok=True)

        # 2. Generate Unique Filename
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        base_name = f"{filename_prefix}_{timestamp}"
        full_path, _ = utils._get_unique_filepath(target_dir, base_name, ".svg")

        # 3. Write File
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(svg_raw)

        print(f"\033[92m[PGFX] SVG saved to: {full_path}\033[0m")
        return (full_path,)

# Node mappings for ComfyUI
NODE_CLASS_MAPPINGS = {
    "CP_ImageToSVG": CP_ImageToSVG,
    "CP_SaveSVG": CP_SaveSVG
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CP_ImageToSVG": "PromptCrafter ✨ Image to SVG",
    "CP_SaveSVG": "PromptCrafter 💾 Save SVG"
}
