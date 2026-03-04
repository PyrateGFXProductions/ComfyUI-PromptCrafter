import os
import json
import re

# ComfyUI imports
import folder_paths

# Local module imports
from ..utils import pgfx_json_utils as json_utils

class PGFX_LLM_OutputSaver:
    """
    Robustly saves LLM output per batch and auto-combines on final batch.
    Uses PGFX JSON repair utilities to handle trailing commas and markdown fences.
    
    This is a drop-in replacement for VRGDG_LLM_OutputSaver.
    """
    OUTPUT_NODE = True

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("combined_text",)
    FUNCTION = "run"
    CATEGORY = "☠️PGFX🏴‍☠️ /LLM"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "forceInput": True}),
                "batch_index": ("INT", {}),
                "is_final_batch": ("BOOLEAN", {}),
                "output_folder": ("STRING", {
                    "multiline": False,
                    "placeholder": "FULL path, e.g. A:/ComfyUI/output/llm_results"
                }),
                "base_filename": ("STRING", {"default": "LLM_Output"}),
            }
        }

    # ---------------- helpers ----------------

    def _ensure_folder(self, folder):
        folder = os.path.normpath(folder)
        os.makedirs(folder, exist_ok=True)
        return folder

    def _list_batch_files(self, folder, base_filename):
        return sorted(
            f for f in os.listdir(folder)
            if f.startswith(base_filename + "_")
            and f.lower().endswith(".txt")
            and "COMBINED" not in f
        )

    def _numeric_prompt_sort_key(self, k):
        # Sort keys like "prompt1", "prompt2", ... numerically
        m = re.search(r"(\d+)$", str(k))
        return int(m.group(1)) if m else 10**9

    # ---------------- main ----------------

    def run(
        self,
        text,
        batch_index,
        is_final_batch,
        output_folder,
        base_filename,
    ):
        print("\033[94m[PGFX] ========== LLM OUTPUT SAVER START ==========\033[0m")
        print(f"[PGFX] Batch index: {batch_index}")
        print(f"[PGFX] Is final batch: {is_final_batch}")
        print(f"[PGFX] Base filename: {base_filename}")

        combined_text = ""

        # Normalize + ensure folder
        output_folder = self._ensure_folder(output_folder)
        print(f"[PGFX] Resolved output folder: {output_folder}")

        # ---------------- save batch ----------------

        batch_filename = f"{base_filename}_{batch_index:03d}.txt"
        batch_path = os.path.join(output_folder, batch_filename)

        try:
            with open(batch_path, "w", encoding="utf-8") as f:
                f.write(text)
            print(f"[PGFX] Saved raw LLM output batch file: {batch_path}")
        except Exception as e:
            raise RuntimeError(f"Failed to save batch file: {e}")

        # ---------------- final combine ----------------

        if is_final_batch:
            print("[PGFX] Final batch detected — starting combine phase with JSON repair")

            files = self._list_batch_files(output_folder, base_filename)
            print(f"[PGFX] Batch files found: {files}")

            combined = {}
            global_prompt_index = 1

            for fname in files:
                file_path = os.path.join(output_folder, fname)
                print(f"[PGFX] Processing and repairing batch file: {file_path}")

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        raw = f.read()
                except Exception as e:
                    raise RuntimeError(f"Failed to read {fname}: {e}")

                # Use PGFX robust JSON extraction and repair
                batch_data = json_utils.extract_and_parse_json(raw)
                
                if batch_data is None:
                    print(f"\033[91m[PGFX] ❌ ERROR: Could not find valid JSON in {fname}. Content appears to be an error message or malformed.\033[0m")
                    print(f"[PGFX] Skipping {fname} to prevent crash. Your final combined JSON will be missing some prompts.")
                    continue

                if not isinstance(batch_data, dict):
                    print(f"\033[93m[PGFX] ⚠️ Warning: {fname} contained a JSON array or literal instead of an object. Skipping.\033[0m")
                    continue

                keys = list(batch_data.keys())
                # Sort numerically if they are prompt1, prompt2...
                keys_sorted = sorted(keys, key=self._numeric_prompt_sort_key)

                print(f"[PGFX] {fname} sorted keys: {keys_sorted}")

                for key in keys_sorted:
                    combined_key = f"prompt{global_prompt_index}"
                    combined[combined_key] = str(batch_data[key])
                    global_prompt_index += 1

            combined_path = os.path.join(output_folder, f"{base_filename}_COMBINED.json")

            try:
                with open(combined_path, "w", encoding="utf-8") as f:
                    json.dump(combined, f, ensure_ascii=False, indent=2)
                print(f"\033[92m[PGFX] ✅ Success! Wrote combined and fixed JSON file: {combined_path}\033[0m")
                print(f"[PGFX] Total prompts rescued: {global_prompt_index - 1}")
            except Exception as e:
                raise RuntimeError(f"Failed to write combined file: {e}")

            # Output for UI viewing
            combined_text = json.dumps(combined, ensure_ascii=False, indent=2)

        print("\033[94m[PGFX] ========== LLM OUTPUT SAVER END ==========\033[0m")
        return (combined_text,)

NODE_CLASS_MAPPINGS = {
    "PGFX_LLM_OutputSaver": PGFX_LLM_OutputSaver
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_LLM_OutputSaver": "☠️ PGFX LLM Output Saver (Robust)"
}
