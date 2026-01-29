import subprocess
import sys
from pathlib import Path
import argparse

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt
from packaging.requirements import Requirement
from packaging.version import Version
from packaging.specifiers import SpecifierSet

console = Console()

def get_installed_packages(python_executable: Path):
    """Gets installed packages from a specified python environment using pip freeze."""
    if not python_executable.exists():
        console.print(f"[bold red]Error: Python executable not found at {python_executable}[/bold red]")
        return None
    try:
        result = subprocess.run([str(python_executable), "-m", "pip", "freeze"], capture_output=True, text=True, check=True)
        installed = {}
        for line in result.stdout.strip().split("\n"):
            if "==" in line:
                name, version_str = line.split("==", 1)
                installed[name.lower()] = Version(version_str)
        return installed
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        console.print(f"[bold red]Error: Could not get installed packages. Is pip installed?[/bold red]")
        console.print(e)
        return None

def parse_requirements(requirements_path: Path):
    """Parses a requirements.txt file."""
    if not requirements_path.exists():
        console.print(f"[bold red]Error: Requirements file not found at {requirements_path}[/bold red]")
        return None
    try:
        with open(requirements_path, "r") as f:
            return [Requirement(line) for line in f if line.strip() and not line.strip().startswith("#")]
    except Exception as e:
        console.print(f"[bold red]Error parsing requirements file: {e}[/bold red]")
        return None

def load_compat_db():
    """Loads the compatibility database."""
    db_path = Path(__file__).parent / "compatibility_db.json"
    if not db_path.exists():
        return None
    try:
        import json
        with open(db_path, "r") as f:
            return json.load(f)
    except Exception as e:
        console.print(f"[yellow]Warning: Could not load compatibility database: {e}[/yellow]")
        return None

def check_conflicts(requirements, installed_packages, compat_db):
    """Checks for conflicts between requirements and installed packages."""
    conflicts = []
    # Find the torch version first, as it's a key dependency
    installed_torch_version = None
    if 'torch' in installed_packages:
        installed_torch_version = str(installed_packages['torch'])

    for req in requirements:
        req_name_lower = req.name.lower()
        if req_name_lower in installed_packages:
            installed_version = installed_packages[req_name_lower]
            suggestion = None

            # Check for a suggestion in the compatibility database
            if compat_db and installed_torch_version and 'torch' in compat_db:
                if installed_torch_version in compat_db['torch']:
                    if req.name in compat_db['torch'][installed_torch_version]:
                        suggestion = compat_db['torch'][installed_torch_version][req.name]

            if not req.specifier.contains(installed_version):
                conflict = {
                    "name": req.name,
                    "required": str(req.specifier),
                    "installed": str(installed_version),
                    "type": "Version Mismatch",
                    "suggestion": suggestion
                }
                conflicts.append(conflict)
            
            # Special check for torch trying to be installed without CUDA
            if req.name == "torch" and "+" not in str(req.specifier) and installed_version.local:
                 conflict = {
                    "name": req.name,
                    "required": str(req.specifier),
                    "installed": str(installed_version),
                    "type": "Potential CPU Downgrade",
                    "suggestion": None # No suggestion for this type of conflict yet
                }
                 conflicts.append(conflict)

    return conflicts

def create_backup(python_executable: Path) -> Path | None:
    """Creates a backup of the current environment's packages."""
    import datetime
    backup_dir = Path("./ComfyGuard/backups")
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"comfyguard_backup_{timestamp}.txt"
    
    console.print(f"\n[bold]Creating environment backup at: {backup_file}[/bold]")
    try:
        with open(backup_file, "w") as f:
            result = subprocess.run(
                [str(python_executable), "-m", "pip", "freeze"],
                capture_output=True, text=True, check=True
            )
            f.write(result.stdout)
        console.print("[green]Backup created successfully.[/green]")
        return backup_file
    except Exception as e:
        console.print(f"[bold red]Error creating backup: {e}[/bold red]")
        return None


# Add this to your existing conflict_detector.py

def get_cuda_index_url(installed_version):
    """
    Determines the correct PyTorch CUDA index URL based on the installed version.
    Example: if 2.8.0+cu128 is installed, it returns the cu128 index.
    """
    version_str = str(installed_version)
    if "+cu" in version_str:
        cuda_tag = version_str.split("+")[-1] # e.g., 'cu128'
        return f"https://download.pytorch.org/whl/{cuda_tag}"
    return "https://download.pytorch.org/whl/cu121" # Default to a safe common denominator

def safe_install_requirements(python_executable, requirements_path, installed_packages):
    """
    THE BREAKTHROUGH LOGIC:
    If torch is being installed, this function FORCES the CUDA index URL
    so that pip doesn't default to the CPU version from PyPI.
    """
    backup_file = create_backup(python_executable)
    
    # Check if torch/torchvision/xformers are in the requirements
    needs_cuda_index = False
    with open(requirements_path, 'r') as f:
        req_content = f.read().lower()
        if any(pkg in req_content for pkg in ["torch", "torchvision", "xformers"]):
            needs_cuda_index = True

    command = [str(python_executable), "-m", "pip", "install", "-r", str(requirements_path)]
    
    if needs_cuda_index:
        cuda_url = get_cuda_index_url(installed_packages.get('torch', 'cu121'))
        console.print(f"[bold cyan]ComfyGuard Action:[/bold cyan] Injecting CUDA Index URL to prevent CPU downgrade: {cuda_url}")
        command.extend(["--extra-index-url", cuda_url])

    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
        for line in process.stdout:
            console.print(line, end="")
        process.wait()
        if process.returncode == 0:
            console.print("\n[bold green]Installation completed successfully.[/bold green]")
            return True
        else:
            console.print(f"\n[bold red]Installation failed with exit code {process.returncode}.[/bold red]")
            return False
    except FileNotFoundError:
        console.print(f"[bold red]Error: Command not found. Is '{python_executable}' a valid python executable?[/bold red]")
        return False
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred during installation: {e}[/bold red]")
        return False

def rollback_from_backup(python_executable: Path, backup_file: Path):
    """Rolls back the environment using a pip freeze backup file."""
    if not backup_file.exists():
        console.print(f"[bold red]Error: Backup file not found at {backup_file}[/bold red]")
        return False

    console.print(f"\n[bold yellow]Rolling back environment from backup: {backup_file}[/bold yellow]")

    try:
        # Step 1: Get packages to uninstall
        console.print("[bold]Step 1: Calculating packages to remove...[/bold]")
        
        with open(backup_file, "r") as f:
            backup_pkgs = {line.strip().split('==')[0].lower() for line in f if '==' in line}

        current_pkgs_dict = get_installed_packages(python_executable)
        if current_pkgs_dict is None:
            raise Exception("Could not get current package list.")
        current_pkgs = set(current_pkgs_dict.keys())
        
        to_uninstall = current_pkgs - backup_pkgs
        
        # Step 2: Uninstall unexpected packages
        if to_uninstall:
            console.print(f"Packages to uninstall: [cyan]{', '.join(to_uninstall)}[/cyan]")
            uninstall_command = [str(python_executable), "-m", "pip", "uninstall", "-y"] + list(to_uninstall)
            uninstall_process = subprocess.Popen(uninstall_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
            for line in uninstall_process.stdout:
                console.print(line, end="")
            uninstall_process.wait()
            if uninstall_process.returncode != 0:
                console.print(f"\n[bold red]Uninstall step failed with exit code {uninstall_process.returncode}.[/bold red]")
                return False
            console.print("\n[green]Uninstall step completed.[/green]")
        else:
            console.print("[green]No packages to remove.[/green]")

        # Step 3: Reinstall packages from backup
        console.print("\n[bold]Step 2: Restoring packages from backup...[/bold]")
        console.print("[yellow]This will force-reinstall all packages listed in the backup file.[/yellow]")
        reinstall_command = [str(python_executable), "-m", "pip", "install", "--force-reinstall", "-r", str(backup_file)]
        
        reinstall_process = subprocess.Popen(reinstall_command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
        for line in reinstall_process.stdout:
            console.print(line, end="")
        reinstall_process.wait()
        
        if reinstall_process.returncode == 0:
            console.print("\n[bold green]Rollback completed successfully.[/bold green]")
            return True
        else:
            console.print(f"\n[bold red]Rollback failed with exit code {reinstall_process.returncode}.[/bold red]")
            return False

    except FileNotFoundError:
        console.print(f"[bold red]Error: Command not found. Is '{python_executable}' a valid python executable?[/bold red]")
        return False
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred during rollback: {e}[/bold red]")
        return False


def main():
    parser = argparse.ArgumentParser(description="A smart dependency manager for ComfyUI environments.")
    
    # Mode selection
    parser.add_argument("requirements_file", type=Path, nargs='?', default=None, help="Path to the requirements.txt file to check/install.")
    parser.add_argument("--rollback", type=Path, metavar="BACKUP_FILE", help="Rollback the environment using a specified backup file.")

    # General options
    parser.add_argument(
        "--python-executable",
        type=Path,
        default=sys.executable,
        help="Path to the Python executable in the target environment (e.g., ComfyUI's venv)."
    )
    parser.add_argument("--non-interactive", action="store_true", help="Do not prompt for user input.")
    
    args = parser.parse_args()

    # Rollback Mode
    if args.rollback:
        if args.non_interactive:
            rollback_from_backup(args.python_executable, args.rollback)
        else:
            console.print(f"[bold yellow]You are about to rollback the environment '{args.python_executable}' using backup file '{args.rollback}'.[/bold yellow]")
            choice = Prompt.ask(
                "\n[bold]Are you sure you want to proceed?[/bold]",
                choices=["y", "n"],
                default="n",
                console=console
            )
            if choice == "y":
                rollback_from_backup(args.python_executable, args.rollback)
            else:
                console.print("[yellow]Rollback cancelled by user.[/yellow]")
        sys.exit(0)

    # Default Mode: Check and Install
    if not args.requirements_file:
        parser.error("the following arguments are required: requirements_file (unless --rollback is specified)")

    console.print(f"[bold cyan]Scanning environment '{args.python_executable}'...[/bold cyan]")

    # For this test, we'll use a simulated environment to guarantee a known torch version
    installed_packages = get_installed_packages(args.python_executable)
    # installed_packages = {
    #     "torch": Version("2.8.0+cu128"),
    #     "torchvision": Version("0.18.0+cu128"),
    #     "xformers": Version("0.0.25"),
    #     "numpy": Version("1.26.4"),
    # }
    
    if installed_packages is None:
        sys.exit(1)

    requirements = parse_requirements(args.requirements_file)
    if requirements is None:
        sys.exit(1)

    compat_db = load_compat_db()
    conflicts = check_conflicts(requirements, installed_packages, compat_db)

    if not conflicts:
        console.print("[bold green][OK] No conflicts found. It seems safe to install.[/bold green]")
        if args.non_interactive:
            install_requirements(args.python_executable, args.requirements_file)
            sys.exit(0)
        else:
            choice = Prompt.ask(
                "\n[bold]Proceed with installation?[/bold]",
                choices=["y", "n"],
                default="y",
                console=console
            )
            if choice == "y":
                install_requirements(args.python_executable, args.requirements_file)
                sys.exit(0)
            else:
                console.print("[yellow]Installation cancelled by user.[/yellow]")
                sys.exit(0)

    console.print("[bold yellow][!] Potential Conflicts Detected![/bold yellow]")
    console.print("Installing these packages may break your environment.")

    table = Table(title="Conflict Details")
    table.add_column("Package", style="cyan")
    table.add_column("Required Version", style="magenta")
    table.add_column("Installed Version", style="green")
    table.add_column("Conflict Type", style="red")
    table.add_column("Suggestion", style="yellow")

    has_suggestion = False
    for c in conflicts:
        suggestion_text = c.get('suggestion') or ""
        if suggestion_text:
            has_suggestion = True
        table.add_row(c['name'], c['required'], c['installed'], c['type'], suggestion_text)

    console.print(table)

    if args.non_interactive:
        console.print("\n[yellow]--non-interactive flag set. Installation cancelled due to conflicts.[/yellow]")
        sys.exit(1) # Exit with a non-zero code to indicate failure/cancellation

    prompt_text = "\n[bold]What would you like to do? ([/bold]c[bold])ancel / ([/bold]p[bold])roceed[/bold]"
    choices = ["c", "p"]
    if has_suggestion:
        prompt_text += " / ([bold]a[bold])pply suggestion"
        choices.append("a")

    while True:
        choice = Prompt.ask(
            prompt_text,
            choices=choices,
            default="c",
            console=console
        )
        if choice == "c":
            console.print("[yellow]Installation cancelled by user.[/yellow]")
            sys.exit(0)
        elif choice == "p":
            install_requirements(args.python_executable, args.requirements_file)
            sys.exit(0)
        elif choice == "a" and has_suggestion:
            console.print("[bold cyan]Applying suggested versions... (SIMULATED)[/bold cyan]")
            # Here we would implement the logic to create a temporary, corrected
            # requirements file and then call install_requirements on it.
            sys.exit(0)



if __name__ == "__main__":
    main()
