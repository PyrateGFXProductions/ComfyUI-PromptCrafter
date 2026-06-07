import torch
from ..ComfyGuard import auditor

class PGFX_ComfyGuard_Shield:
    """
    A status node that displays the current health and security status 
    of the ComfyUI environment via ComfyGuard.
    """
    DESCRIPTION = "Displays the current hardware health and security status of the ComfyUI environment."
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "signal": ("*", {"tooltip": "Connect any signal to trigger a status update."}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("status_report", "cuda_summary")
    FUNCTION = "get_status"
    CATEGORY = "☠️PGFX /Security"
    OUTPUT_NODE = True

    def get_status(self, signal=None):
        guard_auditor = auditor.ComfyGuardAuditor()
        cuda_msg = guard_auditor.audit_cuda()
        mem_suggestions = guard_auditor.audit_memory_management()
        
        status_report = f"🛡️ PGFX ComfyGuard Status:\n"
        status_report += f"- Torch Version: {torch.__version__}\n"
        status_report += f"- CUDA Available: {torch.cuda.is_available()}\n"
        status_report += f"- VRAM: {guard_auditor.vram_gb:.2f} GB\n"
        status_report += f"- Status: {cuda_msg}\n"
        status_report += f"- Optimizer Flags: {mem_suggestions}\n"
        
        # Check for sticky shield
        import os
        shield_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ComfyGuard", "sticky_shield.txt")
        shield_active = os.path.exists(shield_path)
        status_report += f"- Constraint Shield: {'ACTIVE' if shield_active else 'NOT FOUND'}\n"

        print(f"\033[92m[ComfyGuard Shield] Status checked: {cuda_msg}\033[0m")
        
        return (status_report, cuda_msg)

NODE_CLASS_MAPPINGS = {
    "PGFX_ComfyGuard_Shield": PGFX_ComfyGuard_Shield,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_ComfyGuard_Shield": "🩺 ComfyGuard Health Check",
}
