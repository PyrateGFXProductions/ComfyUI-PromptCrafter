# ComfyGuard

**ComfyGuard** is a proactive dependency manager bundled with the PGFX node suite. It helps prevent environment conflicts when installing ComfyUI custom nodes by checking for breaking changes *before* installation and giving you control over how to proceed.

This tool is in active development.

## Core Features

- Conflict detection against a target Python environment
- Version mismatch warnings
- PyTorch/CUDA safety checks (prevents accidental CPU‑only downgrades)
- Automatic target interpreter detection for intercepted installs
- Local rescue snapshots inside the active virtual environment for critical artifacts like NumPy
- Interactive and non‑interactive modes
- Optional safe‑install flow when conflicts are not detected

## Usage

To run the conflict checker:

```bash
python conflict_detector.py <path_to_requirements.txt> --python-executable <path_to_python>
```

### Arguments

- `requirements_file`: The `requirements.txt` file you want to check
- `--python-executable`: Path to the target `python` or `python.exe` (defaults to the current interpreter)
- `--non-interactive`: Runs without prompts and cancels on detected conflicts

### Example

```bash
# Check a new node's requirements against ComfyUI's venv
python ComfyGuard/conflict_detector.py ComfyUI/custom_nodes/new-node/requirements.txt --python-executable ComfyUI/venv/Scripts/python.exe
```

## Runtime Rescue Snapshots

When ComfyGuard intercepts package installs, it now resolves the actual target interpreter and refreshes a local rescue snapshot inside that same virtual environment:

```text
<venv_root>/.comfyguard_rescue/numpy/current
```

The snapshot stores the current NumPy package directory, `numpy.libs` when present, and the matching `numpy-*.dist-info` metadata. This gives local launchers a same-env fallback if NumPy is accidentally overwritten during later installs.
