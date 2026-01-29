# ComfyGuard

**ComfyGuard** is a smart, proactive dependency manager designed to prevent environment conflicts when installing custom nodes for ComfyUI. It acts as a safety layer, checking for potential breaking changes *before* installation and giving the user control over how to proceed.

This tool is currently in its initial development phase.

## Core Features (MVP)

- **Conflict Detection:** Scans a `requirements.txt` file and compares it against a specified Python environment.
- **Version Checking:** Flags version mismatches between required and installed packages.
- **PyTorch/CUDA Safety:** Specifically warns if an installation is likely to downgrade a CUDA-enabled PyTorch installation to a CPU-only version.
- **Interactive Mode:** If conflicts are found, it prompts the user with clear choices: cancel or proceed.
- **Non-Interactive Mode:** Can be run in automated scripts, automatically canceling installation if conflicts are detected.
- **Safe Installation:** If no conflicts are found, it prompts the user for confirmation before running the `pip install` command.

## Usage

To run the conflict checker, use the following command:

```bash
python conflict_detector.py <path_to_requirements.txt> --python-executable <path_to_python>
```

### Arguments

- `requirements_file`: The path to the `requirements.txt` file you want to check and install.
- `--python-executable`: (Optional) The path to the `python.exe` or `python` binary of the environment you want to check (e.g., your ComfyUI's embedded Python or venv). Defaults to the Python running the script.
- `--non-interactive`: (Optional) If set, the script will not prompt for user input. It will automatically proceed with installation if no conflicts are found, and automatically cancel if conflicts are present.

### Example

```bash
# Run a check for a new node's requirements against ComfyUI's venv
python ComfyGuard/conflict_detector.py ComfyUI/custom_nodes/new-node/requirements.txt --python-executable ComfyUI/venv/Scripts/python.exe
```
