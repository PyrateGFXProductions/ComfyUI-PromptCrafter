import os
import sys
import subprocess
import torch
import shutil
from pathlib import Path
from aiohttp import web
from server import PromptServer

# Import your modules
from .auditor import ComfyGuardAuditor

# --- GLOBAL SETTINGS ---
GUARD_DISABLED = False 
BASE_PATH = Path(__file__).parent

def get_sticky_versions():
    """Generates a shield file if it doesn't exist."""
    import pkg_resources
    shield_path = BASE_PATH / "sticky_shield.txt"
    if not shield_path.exists():
        with open(shield_path, "w") as f:
            for dist in pkg_resources.working_set:
                # We lock EVERYTHING currently working
                f.write(f"{dist.project_name}=={dist.version}\n")
    return shield_path

# --- THE INTERCEPTOR ---
original_popen = subprocess.Popen

class ComfyGuardInterceptor(original_popen):
    def __init__(self, args, **kwargs):
        global GUARD_DISABLED
        
        # We only intercept PIP INSTALL calls
        is_install = isinstance(args, list) and "pip" in args and "install" in args
        
        if not GUARD_DISABLED and is_install:
            print(f"\n[ComfyGuard] 🛡️ INTERCEPTING INSTALL...")
            
            # 1. Use 'uv' if available (it's faster and smarter for conflicts)
            uv_path = shutil.which("uv")
            if uv_path:
                # Rewrite ['python', '-m', 'pip', 'install', ...] 
                # to ['uv', 'pip', 'install', ...]
                if "pip" in args:
                    pip_idx = args.index("pip")
                    args = [uv_path] + args[pip_idx:]
                    print("✅ Using UV Resolver (Circular Dependency Protection Active)")

            # 2. Inject Constraint Shield (The Sticky Versions)
            shield_file = get_sticky_versions()
            if "-c" not in args and "--constraint" not in args:
                args.extend(["--constraint", str(shield_file)])
                print(f"✅ Constraint Shield Applied: {shield_file.name}")

            # 3. Inject CUDA Index (The CPU-Downgrade Protection)
            if "+cu" in torch.__version__:
                cuda_tag = torch.__version__.split("+")[-1]
                index_url = f"https://download.pytorch.org/whl/{cuda_tag}"
                if "--extra-index-url" not in args:
                    args.extend(["--extra-index-url", index_url])
                    print(f"✅ CUDA Index Injected: {cuda_tag}")

            print(f"[ComfyGuard] 🚀 Executing: {' '.join(args)}\n")

        super().__init__(args, **kwargs)

# Activate the Interceptor
subprocess.Popen = ComfyGuardInterceptor

# --- API ROUTES FOR THE UI ---

@PromptServer.instance.routes.get("/comfyguard/status")
async def get_status(request):
    auditor = ComfyGuardAuditor()
    status_msg = auditor.audit_cuda()
    return web.json_response({
        "cuda_broken": auditor.is_cuda_broken,
        "vram_gb": auditor.vram_gb,
        "torch_version": torch.__version__,
        "suggestions": auditor.audit_memory_management(),
        "status_msg": status_msg
    })

@PromptServer.instance.routes.post("/comfyguard/repair")
async def do_repair(request):
    global GUARD_DISABLED
    GUARD_DISABLED = True
    
    # Identify repair targets
    cuda_tag = torch.__version__.split("+")[-1] if "+cu" in torch.__version__ else "cu121"
    base_ver = torch.__version__.split('+')[0]
    
    # Use UV if possible for the repair
    exe = shutil.which("uv") or sys.executable
    prefix = ["pip"] if shutil.which("uv") else ["-m", "pip"]
    
    cmd = [exe] + prefix + [
        "install", f"torch=={base_ver}", "torchvision", "torchaudio",
        "--force-reinstall", "--no-deps",
        "--index-url", f"https://download.pytorch.org/whl/{cuda_tag}"
    ]
    
    print(f"[ComfyGuard] 🛠️ EMERGENCY REPAIR: {' '.join(cmd)}")
    subprocess.Popen(cmd)
    
    GUARD_DISABLED = False
    return web.json_response({"status": "success"})

@PromptServer.instance.routes.post("/comfyguard/generate_launcher")
async def create_launcher(request):
    auditor = ComfyGuardAuditor()
    auditor.check_hardware_presence()
    path, flags = auditor.generate_launcher()
    return web.json_response({
        "status": "success", 
        "message": f"Optimized Launcher created at: {path}\nFlags applied: {flags}"
    })

@PromptServer.instance.routes.post("/comfyguard/update_shield")
async def update_shield(request):
    """Force-updates the sticky_shield.txt with the current environment."""
    shield_path = BASE_PATH / "sticky_shield.txt"
    import pkg_resources
    with open(shield_path, "w") as f:
        for dist in pkg_resources.working_set:
            f.write(f"{dist.project_name}=={dist.version}\n")
    return web.json_response({"status": "success", "message": "Shield updated to current versions!"})


# ComfyUI Node setup
NODE_CLASS_MAPPINGS = {}
WEB_DIRECTORY = "./web"
