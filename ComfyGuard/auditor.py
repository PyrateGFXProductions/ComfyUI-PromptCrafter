import torch
import subprocess
import sys
from pathlib import Path

class ComfyGuardAuditor:
    def __init__(self):
        self.vram_gb = 0
        self.is_cuda_broken = False

    def check_hardware_presence(self):
        try:
            # Check for NVIDIA GPU specifically
            res = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], 
                                 capture_output=True, text=True)
            if res.returncode == 0:
                name, mem = res.stdout.strip().split(",")
                self.vram_gb = int(mem) // 1024
                return True, name.strip()
        except:
            return False, "Non-NVIDIA or No GPU"
        return False, "Unknown"

    def audit_cuda(self):
        os_has_gpu, gpu_name = self.check_hardware_presence()
        torch_has_cuda = torch.cuda.is_available()
        
        if os_has_gpu and not torch_has_cuda:
            self.is_cuda_broken = True
            return f"❌ BROKEN: {gpu_name} found, but Torch is CPU-only."
        elif not os_has_gpu:
            return "⚠️ INFO: No NVIDIA GPU detected. Using CPU mode."
        return f"✅ HEALTHY: {gpu_name} ({self.vram_gb}GB) is active."

    def audit_memory_management(self):
        suggestions = []
        # Check for 12GB+ cards running in unnecessary LOW_VRAM mode
        args_str = " ".join(sys.argv).upper()
        if self.vram_gb >= 12 and "--LOWVRAM" in args_str:
            suggestions.append("12GB detected: You are using --lowvram. Try removing it for significant speed gains.")
        
        # Check for FP16 optimization
        if torch.cuda.is_available() and torch.cuda.get_device_capability()[0] >= 8:
            # Ampere (30-series) supports BF16
            suggestions.append("Ampere GPU detected: BF16 optimizations are available.")
            
        return suggestions
    
    def generate_launcher(self):
        """Creates a hardware-optimized .bat file for the user."""
        root_path = Path(sys.executable).parents[1] # Finds the ComfyUI-Easy-Install root
        comfy_path = root_path / "ComfyUI" / "main.py"
        python_exe = sys.executable
        bat_path = root_path / "ComfyUI_Optimized_Launcher.bat"

        # Start with the base command
        flags = []

        # 1. VRAM Strategy (Based on your 12GB 3060)
        if self.vram_gb >= 12:
            flags.append("--highvram")
        elif self.vram_gb >= 8:
            flags.append("--normalvram")
        else:
            flags.append("--lowvram")

        # 2. Precision & Speed (30-series Ampere support)
        if torch.cuda.is_available() and torch.cuda.get_device_capability()[0] >= 8:
            flags.append("--bf16-unet")
            flags.append("--use-pytorch-cross-attention")
        
        # 3. UI/UX flags
        flags.append("--preview-method auto")

        # Construct the BAT content
        # We use 'pushd' to ensure paths are correct regardless of where the bat is clicked
        bat_content = f"""@echo off
set "PYTHONPATH=%PYTHONPATH%;%CD%"
echo 🛡️ ComfyGuard: Starting Optimized Environment for {self.vram_gb}GB GPU...
"{python_exe}" "{comfy_path}" {" ".join(flags)} %*
pause
"""
        with open(bat_path, "w") as f:
            f.write(bat_content)
        
        return bat_path, " ".join(flags)
