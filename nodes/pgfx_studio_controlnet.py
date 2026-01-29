import torch
import numpy as np
from PIL import Image

class PGFX_Studio_ControlNet:
    """
    The control bridge. This node takes the viseme landmark maps (Depth, Canny) 
    and prepares them as conditioning for various video models.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "viseme_depth": ("IMAGE",),
                "viseme_canny": ("IMAGE",),
                "strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.01}),
                "start_percent": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "end_percent": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            },
            "optional": {
                "base_controlnet": ("CONTROL_NET", {"tooltip": "Optional: Daisy-chain another ControlNet here."}),
            }
        }

    RETURN_TYPES = ("CONTROL_NET_CONDITIONING", "IMAGE")
    RETURN_NAMES = ("conditioning", "preview_visemes")
    FUNCTION = "apply_visemes"
    CATEGORY = "☠️PGFX🏴‍☠️ /PromptCrafter/Studio"

    def apply_visemes(self, viseme_depth, viseme_canny, strength, start_percent, end_percent, base_controlnet=None):
        # In a real ComfyUI environment, this would interface with the ControlNet logic.
        # Since we are building a "Universal Studio", we return a custom conditioning 
        # structure that the PGFX_Studio_Sampler understands.
        
        print(f"[PGFX Studio ControlNet] Preparing viseme conditioning (Strength: {strength})")

        conditioning = {
            "depth": viseme_depth,
            "canny": viseme_canny,
            "strength": strength,
            "start_percent": start_percent,
            "end_percent": end_percent,
        }

        # For preview, we blend depths and canny
        preview = (viseme_depth * 0.5 + viseme_canny * 0.5) * strength
        
        return (conditioning, preview)

NODE_CLASS_MAPPINGS = {
    "PGFX_Studio_ControlNet": PGFX_Studio_ControlNet,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_Studio_ControlNet": "👄 Studio ControlNet (Viseme Bridge)",
}
