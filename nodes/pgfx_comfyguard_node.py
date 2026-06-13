import torch
from ..ComfyGuard import auditor

try:
    from comfy_api.latest import io as v3_io
    V3_AVAILABLE = True
except ImportError:
    V3_AVAILABLE = False

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

if V3_AVAILABLE:
    class PGFX_ComfyGuard_ShieldV3(v3_io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return v3_io.Schema(
                node_id="PGFX_ComfyGuard_ShieldV3",
                display_name="🩺 ComfyGuard Health Check (V3)",
                category="☠️PGFX /Security",
                description="Displays the current hardware health and security status of the ComfyUI environment.",
                is_output_node=True,
                inputs=[
                    v3_io.AnyType.Input("signal", optional=True),
                ],
                outputs=[
                    v3_io.String.Output(display_name="status_report"),
                    v3_io.String.Output(display_name="cuda_summary"),
                ],
            )

        @classmethod
        def execute(cls, signal=None):
            guard = PGFX_ComfyGuard_Shield()
            result = guard.get_status(signal)
            return v3_io.NodeOutput(*result)

NODE_CLASS_MAPPINGS = {
    "PGFX_ComfyGuard_Shield": PGFX_ComfyGuard_Shield,
}
if V3_AVAILABLE:
    NODE_CLASS_MAPPINGS["PGFX_ComfyGuard_ShieldV3"] = PGFX_ComfyGuard_ShieldV3

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_ComfyGuard_Shield": "🩺 ComfyGuard Health Check",
}
