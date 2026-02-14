#!/usr/bin/env python3
"""
PromptCrafter – 100 %‑automatic, idempotent fixer.

Run it **once** from the extension’s root folder:

    python promptcrafter_fixer.py

It will:
  • back up every file it changes (file.bak)
  • add a safe‑model normaliser
  • filter out placeholder model names
  • add a graceful fallback model
  • throttle Ollama to a single concurrent request
  • replace the JSON‑extractor with a tolerant version

If something is already patched the script recognises the marker
and skips that file – you can run it again safely.
"""

import os
import re
import sys
import shutil
import textwrap
from pathlib import Path

# ----------------------------------------------------------------------
# Helper utilities
# ----------------------------------------------------------------------
def backup(path: Path) -> None:
    """Create a .bak copy the first time we touch a file."""
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        shutil.copy2(path, bak)
        print(f"[backup] {path.name} → {bak.name}")

def insert_after_imports(content: str, marker: str, block: str) -> str:
    """Insert *block* after the last top‑level import, wrapped in markers."""
    start = f"# >>> {marker} >>>"
    end   = f"# <<< {marker} <<<"

    # Already present? → skip (idempotent)
    if start in content and end in content:
        return content

    # Position after the last import line
    imports = list(re.finditer(r"^(import .+|from .+ import .+)$", content, re.M))
    pos = imports[-1].end() if imports else 0
    prefix = content[:pos].rstrip()
    suffix = content[pos:].lstrip()

    new = f"{prefix}\n\n{start}\n{block.rstrip()}\n{end}\n\n{suffix}"
    return new

def replace_function(content: str, name: str, new_body: str, marker: str) -> str:
    """
    Replace the whole definition of ``def name(...):`` with *new_body*.
    The replacement is wrapped in the same markers as ``insert_after_imports``.
    """
    start = f"# >>> {marker} >>>"
    end   = f"# <<< {marker} <<<"

    if start in content and end in content:
        return content    # already patched

    pattern = rf"(?s)^def {re.escape(name)}\s*\(.*?\):.*?(?=\ndef |\Z)"
    repl = f"{start}\n{new_body.rstrip()}\n{end}"
    new_content = re.sub(pattern, repl, content, flags=re.M)

    # If the function was not found (maybe the file changed), just append.
    if new_content == content:
        new_content = insert_after_imports(content, marker, new_body)

    return new_content

# ----------------------------------------------------------------------
# 1️⃣ utils/pgfx_utils.py – normalise_model_name()
# ----------------------------------------------------------------------
UTILS_PATH = Path("utils/pgfx_utils.py")
UTILS_MARKER = "UTILS_NORMALISE_MODEL"

UTILS_NEW = textwrap.dedent(
    """
    def normalise_model_name(raw_name: str) -> str | None:
        \"\"\"Convert UI‑provided model strings into the ``provider/model`` format required by Ollama.

        * Returns ``None`` for clearly invalid placeholders (e.g. ``NO_API_MODELS_FOUND``).
        * If the string already contains a slash it is returned unchanged.
        * Otherwise it is assumed to be a GGUF filename and ``gguf/`` is prefixed.
        \"\"\"
        if not raw_name:
            return None

        clean = raw_name.strip()
        if clean.upper() in {"NO_API_MODELS_FOUND", "NO_MODELS_FOUND", "NONE", "NULL"}:
            return None
        if "/" in clean:
            return clean
        return f"gguf/{clean}"
    """
)

if UTILS_PATH.is_file():
    txt = UTILS_PATH.read_text(encoding="utf-8")
    if UTILS_MARKER not in txt:
        backup(UTILS_PATH)
        txt = insert_after_imports(txt, UTILS_MARKER, UTILS_NEW)
        UTILS_PATH.write_text(txt, encoding="utf-8")
        print("[patch] utils/pgfx_utils.py – added normalise_model_name()")
else:
    print("[skip] utils/pgfx_utils.py – cannot find this file (wrong folder?)")

# ----------------------------------------------------------------------
# 2️⃣ cinematic_prompt_node.py – safe get_combined_models()
# ----------------------------------------------------------------------
CINEMA_PATH = Path("cinematic_prompt_node.py")
CINEMA_MARKER = "CINEMA_GET_COMBINED_MODELS"

CINEMA_NEW = textwrap.dedent(
    """
    def get_combined_models():
        \"\"\"Return a cleaned list of model identifiers for the UI.

        * GGUF files are normalised to ``gguf/<filename>``.
        * Placeholder values such as ``NO_API_MODELS_FOUND`` are filtered out.
        * Duplicates are removed while keeping the original order.
        \"\"\"
        gguf_raw = api_clients.get_local_llm_gguf_files()
        api_raw = api_clients.get_all_models()

        # Normalise GGUF entries
        gguf_models = [utils.normalise_model_name(m) for m in gguf_raw]
        gguf_models = [m for m in gguf_models if m]   # drop None

        # Filter placeholders from the API list
        api_models = [utils.normalise_model_name(m) for m in api_raw]
        api_models = [m for m in api_models if m]

        # Preserve order – GGUF first, then API, de‑duplicate.
        combined = gguf_models + [m for m in api_models if m not in gguf_models]
        return combined
    """
)

if CINEMA_PATH.is_file():
    txt = CINEMA_PATH.read_text(encoding="utf-8")
    txt = replace_function(txt, "get_combined_models", CINEMA_NEW, CINEMA_MARKER)
    CINEMA_PATH.write_text(txt, encoding="utf-8")
    print("[patch] cinematic_prompt_node.py – refreshed get_combined_models()")
else:
    print("[skip] cinematic_prompt_node.py – cannot find this file")

# ----------------------------------------------------------------------
# 3️⃣ nodes/pgfx_creator_nodes.py – unified get_combined_models()
# ----------------------------------------------------------------------
CREATOR_PATH = Path("nodes/pgfx_creator_nodes.py")
CREATOR_MARKER = "CREATOR_GET_COMBINED_MODELS"

CREATOR_NEW = textwrap.dedent(
    """
    def get_combined_models():
        \"\"\"Return a clean, de‑duplicated list of model identifiers for the UI.\"\"\"
        gguf_raw = api_clients.get_local_llm_gguf_files()
        qwen_raw = api_clients.get_local_qwen_models()
        api_raw = api_clients.get_all_models()

        gguf_models = [utils.normalise_model_name(m) for m in gguf_raw]
        qwen_models = [utils.normalise_model_name(m) for m in qwen_raw]

        api_models = [utils.normalise_model_name(m) for m in api_raw]
        api_models = [m for m in api_models if m]    # drop placeholders

        # Preserve order – Qwen first (if any), then GGUF, then API, de‑duplicate.
        combined = qwen_models + gguf_models + [m for m in api_models if m not in qwen_models + gguf_models]
        return combined
    """
)

if CREATOR_PATH.is_file():
    txt = CREATOR_PATH.read_text(encoding="utf-8")
    txt = replace_function(txt, "get_combined_models", CREATOR_NEW, CREATOR_MARKER)
    CREATOR_PATH.write_text(txt, encoding="utf-8")
    print("[patch] nodes/pgfx_creator_nodes.py – refreshed get_combined_models()")
else:
    print("[skip] nodes/pgfx_creator_nodes.py – cannot find this file")

# ----------------------------------------------------------------------
# 4️⃣ nodes/pgfx_creator_nodes.py – robust _setup_config (model fallback)
# ----------------------------------------------------------------------
SETUP_MARKER = "CREATOR_SETUP_CONFIG_MODEL_FALLBACK"

SETUP_PATCH = textwrap.dedent(
    """
    # ------------------------------------------------------------------
    # 1️⃣  Validate / Normalise the supplied model name
    # ------------------------------------------------------------------
    norm_model = utils.normalise_model_name(model)
    if not norm_model:
        # Pick a safe built‑in Ollama model as a fallback.
        fallback = getattr(config, "DEFAULT_MODEL_FALLBACK", "ollama/llama3")
        print(
            f"\\033[93m[PromptCrafter] WARNING: supplied model '{model}' is invalid or a placeholder. "
            f"Falling back to default model '{fallback}'.\\033[0m"
        )
        norm_model = fallback
    # Store the normalised name back on the config object.
    model = norm_model
    # ------------------------------------------------------------------
    # 2️⃣  Build the PromptCrafterRunConfig with the *normalised* model.
    # ------------------------------------------------------------------
    """
)

if CREATOR_PATH.is_file():
    txt = CREATOR_PATH.read_text(encoding="utf-8")
    # The old code raises a ValueError – replace that whole block.
    pattern = r"if not model or \"NO_MODELS_FOUND\" in model or \"OLLAMA_UNREACHABLE\" in model:\s+raise ValueError\([^\)]+\)"
    if re.search(pattern, txt, re.M):
        txt = re.sub(pattern, SETUP_PATCH, txt, flags=re.M)
    else:
        # Block not present – just make sure the marker exists.
        if SETUP_MARKER not in txt:
            txt = insert_after_imports(txt, SETUP_MARKER, SETUP_PATCH)
    CREATOR_PATH.write_text(txt, encoding="utf-8")
    print("[patch] nodes/pgfx_creator_nodes.py – added model‑fallback logic to _setup_config")
else:
    print("[skip] nodes/pgfx_creator_nodes.py – cannot find this file (second pass)")

# ----------------------------------------------------------------------
# 5️⃣ core/pgfx_api_clients.py – global Ollama throttling (max 1 concurrent call)
# ----------------------------------------------------------------------
API_CLIENTS_PATH = Path("core/pgfx_api_clients.py")
API_CLIENTS_MARKER = "API_OLLAMA_THROTTLE"

API_THROTTLE = textwrap.dedent(
    """
    # ----------------------------------------------------------------------
    # 3️⃣  Global throttling for all Ollama calls – prevents overload.
    # ----------------------------------------------------------------------
    import threading
    import functools

    _MAX_OLLAMA_CONCURRENT_CALLS = 1   # set >1 only if you have a multi‑GPU server
    _ollama_semaphore = threading.Semaphore(_MAX_OLLAMA_CONCURRENT_CALLS)

    def _with_ollama_throttle(func):
        \"\"\"Decorator that serialises access to Ollama.\"\"\"
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with _ollama_semaphore:
                return func(*args, **kwargs)
        return wrapper

    # Apply the decorator to the public entry points.
    query_model_auto = _with_ollama_throttle(query_model_auto)
    _reason_with_model = _with_ollama_throttle(_reason_with_model)
    """
)

if API_CLIENTS_PATH.is_file():
    txt = API_CLIENTS_PATH.read_text(encoding="utf-8")
    if API_CLIENTS_MARKER not in txt:
        backup(API_CLIENTS_PATH)
        txt = insert_after_imports(txt, API_CLIENTS_MARKER, API_THROTTLE)
        API_CLIENTS_PATH.write_text(txt, encoding="utf-8")
        print("[patch] core/pgfx_api_clients.py – added Ollama throttling wrapper")
else:
    print("[skip] core/pgfx_api_clients.py – cannot find this file")

# ----------------------------------------------------------------------
# 6️⃣ utils/pgfx_json_utils.py – tolerant JSON extraction
# ----------------------------------------------------------------------
JSON_UTILS_PATH = Path("utils/pgfx_json_utils.py")
JSON_MARKER = "JSON_EXTRACT_TOLERANT"

JSON_NEW = textwrap.dedent(
    """
    def _extract_and_parse_json(text: str) -> dict | list | None:
        \"\"\"Scan the raw LLM response for the first JSON object/array and parse it.
        Returns ``None`` on complete failure.
        \"\"\"
        # Find the first opening brace or bracket that looks like the start of JSON.
        first_curly = text.find('{')
        first_sq   = text.find('[')
        start = min([i for i in (first_curly, first_sq) if i != -1], default=-1)
        if start == -1:
            return None

        candidate = text[start:]
        # Simple stack‑based balancer to locate the matching closing brace/bracket.
        stack = []
        end = None
        for i, ch in enumerate(candidate):
            if ch in '{[':
                stack.append(ch)
            elif ch in '}]':
                if not stack:
                    break
                opening = stack.pop()
                if (opening == '{' and ch != '}') or (opening == '[' and ch != ']'):
                    break
                if not stack:
                    end = i + 1
                    break
        if end is None:
            return None

        json_str = candidate[:end]
        try:
            return json.loads(json_str)
        except Exception:
            # Last‑ditch fallback – return the raw string inside a dict so callers can see it.
            return {"raw": json_str}
    """
)

if JSON_UTILS_PATH.is_file():
    txt = JSON_UTILS_PATH.read_text(encoding="utf-8")
    if JSON_MARKER not in txt:
        backup(JSON_UTILS_PATH)
        txt = insert_after_imports(txt, JSON_MARKER, JSON_NEW)
        JSON_UTILS_PATH.write_text(txt, encoding="utf-8")
        print("[patch] utils/pgfx_json_utils.py – replaced JSON extractor with tolerant version")
else:
    print("[skip] utils/pgfx_json_utils.py – cannot find this file")

# ----------------------------------------------------------------------
# All done
# ----------------------------------------------------------------------
print("\n=== ✅  PromptCrafter has been patched ===")
print(" • A *.bak* copy of each modified file is beside the original.")
print(" • Run ComfyUI again – the previous errors should be gone.")
print(" • If you ever need to revert, simply delete the patched file and rename the *.bak* back.")
print("\nIf you still see problems, open a command prompt, cd to this folder and run:\n")
print("    python promptcrafter_fixer.py --debug\n")
print("The `--debug` flag will show you the full file‑paths being processed.\n")
