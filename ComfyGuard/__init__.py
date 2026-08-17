import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import torch
from aiohttp import web
from server import PromptServer

# Import your modules
from .auditor import ComfyGuardAuditor

# --- GLOBAL SETTINGS ---
GUARD_DISABLED = False 
BASE_PATH = Path(__file__).parent
RESCUE_DIR_NAME = ".comfyguard_rescue"
NUMPY_RESCUE_NAME = "numpy"

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


def _resolve_candidate_path(raw_path, cwd=None):
    if not raw_path:
        return None

    path = Path(str(raw_path)).expanduser()
    if not path.is_absolute():
        base_dir = Path(cwd) if cwd else Path.cwd()
        path = base_dir / path

    try:
        return path.resolve()
    except FileNotFoundError:
        return path.absolute()


def get_target_python_executable(args=None, cwd=None):
    if isinstance(args, list):
        for flag in ("--python", "-p"):
            if flag in args:
                flag_idx = args.index(flag)
                if flag_idx + 1 < len(args):
                    candidate = _resolve_candidate_path(args[flag_idx + 1], cwd)
                    if candidate is not None:
                        return str(candidate)

        if args:
            first_arg = _resolve_candidate_path(args[0], cwd)
            if first_arg is not None and first_arg.name.lower().startswith("python"):
                return str(first_arg)

    venv_root = os.environ.get("VIRTUAL_ENV")
    if venv_root:
        scripts_dir = "Scripts" if os.name == "nt" else "bin"
        python_name = "python.exe" if os.name == "nt" else "python"
        candidate = Path(venv_root) / scripts_dir / python_name
        if candidate.exists():
            return str(candidate.resolve())

    return sys.executable


def get_environment_context(python_executable):
    python_path = _resolve_candidate_path(python_executable)
    if python_path is None:
        return None

    probe_code = (
        "import json, sys, sysconfig; "
        "print(json.dumps({"
        "'executable': sys.executable, "
        "'prefix': sys.prefix, "
        "'purelib': sysconfig.get_path('purelib')"
        "}))"
    )
    result = subprocess.run(
        [str(python_path), "-c", probe_code],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            f"[ComfyGuard] Warning: could not inspect target python {python_path}: "
            f"{result.stderr.strip()}"
        )
        return None

    try:
        info = json.loads(result.stdout.strip())
    except json.JSONDecodeError as exc:
        print(f"[ComfyGuard] Warning: invalid environment probe output for {python_path}: {exc}")
        return None

    env_root = Path(info["prefix"]).expanduser()
    if not env_root.is_absolute():
        env_root = (Path.cwd() / env_root).resolve()
    else:
        env_root = env_root.resolve()

    if not (env_root / "pyvenv.cfg").exists():
        fallback_root = Path(info["executable"]).resolve().parent.parent
        if (fallback_root / "pyvenv.cfg").exists():
            env_root = fallback_root

    if not (env_root / "pyvenv.cfg").exists():
        print(f"[ComfyGuard] Warning: target python does not appear to be in a virtual environment: {python_path}")
        return None

    site_packages = Path(info["purelib"]).expanduser()
    if not site_packages.is_absolute():
        site_packages = (Path.cwd() / site_packages).resolve()
    else:
        site_packages = site_packages.resolve()

    return {
        "python": str(Path(info["executable"]).resolve()),
        "env_root": env_root,
        "site_packages": site_packages,
    }


def ensure_numpy_rescue_snapshot(python_executable):
    context = get_environment_context(python_executable)
    if context is None:
        return None

    site_packages = context["site_packages"]
    numpy_dir = site_packages / "numpy"
    numpy_libs_dir = site_packages / "numpy.libs"
    dist_info_dirs = sorted(site_packages.glob("numpy-*.dist-info"))

    if not numpy_dir.is_dir() or not dist_info_dirs:
        print(f"[ComfyGuard] Warning: NumPy rescue snapshot skipped; NumPy artifacts not found in {site_packages}")
        return None

    dist_info_dir = dist_info_dirs[0]
    rescue_root = context["env_root"] / RESCUE_DIR_NAME / NUMPY_RESCUE_NAME
    current_root = rescue_root / "current"
    manifest_path = current_root / "manifest.json"
    numpy_version = dist_info_dir.name[len("numpy-") : -len(".dist-info")]

    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = None
        if (
            manifest
            and manifest.get("python") == context["python"]
            and manifest.get("site_packages") == str(site_packages)
            and manifest.get("numpy_dist_info") == dist_info_dir.name
            and (current_root / "numpy").is_dir()
        ):
            return current_root

    temp_root = rescue_root / ".current_tmp"
    if temp_root.exists():
        shutil.rmtree(temp_root)
    temp_root.mkdir(parents=True, exist_ok=True)

    shutil.copytree(numpy_dir, temp_root / "numpy")
    if numpy_libs_dir.is_dir():
        shutil.copytree(numpy_libs_dir, temp_root / "numpy.libs")
    shutil.copytree(dist_info_dir, temp_root / dist_info_dir.name)

    manifest = {
        "package": NUMPY_RESCUE_NAME,
        "numpy_version": numpy_version,
        "numpy_dist_info": dist_info_dir.name,
        "python": context["python"],
        "site_packages": str(site_packages),
        "rescue_root": str(current_root),
    }
    (temp_root / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    if current_root.exists():
        shutil.rmtree(current_root)
    temp_root.replace(current_root)

    print(f"[ComfyGuard] Rescue snapshot refreshed: {current_root}")
    return current_root


def ensure_runtime_rescue_snapshot(args=None, cwd=None):
    try:
        target_python = get_target_python_executable(args=args, cwd=cwd)
        return ensure_numpy_rescue_snapshot(target_python)
    except Exception as exc:
        print(f"[ComfyGuard] Warning: failed to refresh rescue snapshot: {exc}")
        return None

# --- THE INTERCEPTOR ---
original_popen = subprocess.Popen

class ComfyGuardInterceptor(original_popen):
    def __init__(self, args, **kwargs):
        global GUARD_DISABLED
        
        # We only intercept PIP INSTALL calls
        is_install = isinstance(args, list) and "pip" in args and "install" in args
        
        if not GUARD_DISABLED and is_install:
            print(f"\n[ComfyGuard] 🛡️ INTERCEPTING INSTALL...")
            target_python = get_target_python_executable(args=args, cwd=kwargs.get("cwd"))
            ensure_numpy_rescue_snapshot(target_python)
            
            # 1. Use 'uv' if available (it's faster and smarter for conflicts)
            uv_path = shutil.which("uv")
            if uv_path:
                # Rewrite ['python', '-m', 'pip', 'install', ...] 
                # to ['uv', 'pip', 'install', ...]
                if "pip" in args:
                    pip_idx = args.index("pip")
                    args = [uv_path] + args[pip_idx:]
                    if target_python and "--python" not in args and "-p" not in args and "--system" not in args:
                        install_idx = args.index("install")
                        args[install_idx + 1:install_idx + 1] = ["--python", target_python]
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

# Process interception changes behavior for every custom node in the host process.
# Keep it opt-in so installing PromptCrafter cannot rewrite another node's pip calls.
if os.getenv("PGFX_ENABLE_COMFYGUARD_INTERCEPTOR") == "1":
    subprocess.Popen = ComfyGuardInterceptor
    ensure_runtime_rescue_snapshot()
    print("[ComfyGuard] Global pip interceptor enabled.")
else:
    print("[ComfyGuard] Global pip interceptor disabled. Set PGFX_ENABLE_COMFYGUARD_INTERCEPTOR=1 to enable it.")


def _route(method, path):
    """Register an optional route without requiring PromptServer during module import."""
    instance = getattr(PromptServer, "instance", None)
    if instance is None:
        return lambda func: func
    return getattr(instance.routes, method)(path)

# --- API ROUTES FOR THE UI ---

@_route("get", "/comfyguard/status")
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

@_route("post", "/comfyguard/repair")
async def do_repair(request):
    global GUARD_DISABLED
    GUARD_DISABLED = True
    
    # Identify repair targets
    cuda_tag = torch.__version__.split("+")[-1] if "+cu" in torch.__version__ else "cu121"
    base_ver = torch.__version__.split('+')[0]
    target_python = get_target_python_executable()
    ensure_numpy_rescue_snapshot(target_python)
    
    # Use UV if possible for the repair
    uv_path = shutil.which("uv")
    if uv_path:
        cmd = [
            uv_path,
            "pip",
            "install",
            "--python",
            target_python,
            f"torch=={base_ver}",
            "torchvision",
            "torchaudio",
            "--force-reinstall",
            "--no-deps",
            "--index-url",
            f"https://download.pytorch.org/whl/{cuda_tag}",
        ]
    else:
        cmd = [
            target_python,
            "-m",
            "pip",
            "install",
            f"torch=={base_ver}",
            "torchvision",
            "torchaudio",
            "--force-reinstall",
            "--no-deps",
            "--index-url",
            f"https://download.pytorch.org/whl/{cuda_tag}",
        ]
    
    print(f"[ComfyGuard] 🛠️ EMERGENCY REPAIR: {' '.join(cmd)}")
    subprocess.Popen(cmd)
    
    GUARD_DISABLED = False
    return web.json_response({"status": "success"})

@_route("post", "/comfyguard/generate_launcher")
async def create_launcher(request):
    auditor = ComfyGuardAuditor()
    auditor.check_hardware_presence()
    path, flags = auditor.generate_launcher()
    return web.json_response({
        "status": "success", 
        "message": f"Optimized Launcher created at: {path}\nFlags applied: {flags}"
    })

@_route("post", "/comfyguard/update_shield")
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
