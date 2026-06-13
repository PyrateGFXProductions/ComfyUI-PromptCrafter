# Standard library imports
import json
import textwrap

# Local module imports
from ..core import pgfx_api_clients as api_clients
from ..core import pgfx_config as config
from . import pgfx_creator_nodes as creator_nodes
from ..utils import pgfx_utils as utils
from ..utils import pgfx_json_utils as json_utils

def _normalize_model_name(model_entry):
    if isinstance(model_entry, (list, tuple)) and model_entry:
        return model_entry[0]
    return model_entry

def _select_model_default(all_llm_models, predicate, fallback="disabled"):
    for model_entry in all_llm_models:
        model_name = _normalize_model_name(model_entry)
        if isinstance(model_name, str) and predicate(model_name):
            return model_name
    if all_llm_models:
        first = _normalize_model_name(all_llm_models[0])
        return first if isinstance(first, str) else fallback
    return fallback

class PromptCrafter_DirectorAgent:
    """
    An agentic node that uses a "Dual-Model Chain" (Thinking + Instruct) to create a
    video edit decision list based on lyrics, audio analysis, and visual styles.
    """
    DESCRIPTION = "Uses a dual-model chain to create a video edit decision list from lyrics and styles."

    @classmethod
    def INPUT_TYPES(cls):
        # --- UPGRADE: Use the modern, unified model loader from creator_nodes ---
        try:
            all_llm_models = creator_nodes.get_combined_models()
            if not all_llm_models:
                all_llm_models = ["disabled"]
            # Set defaults using the robust pattern from nodes_studio.py
            thinking_default = _select_model_default(
                all_llm_models,
                lambda name: "Qwen3-VL-8b-Thinking" in name
            )
            instruct_default = _select_model_default(
                all_llm_models,
                lambda name: "Qwen3-VL-8b-Instruct" in name
            )
        except Exception as e:
            print(f"[DirectorAgent] Error loading models: {e}")
            all_llm_models = ["disabled"]
            thinking_default = "disabled"
            instruct_default = "disabled"

        return {
            "required": {
                "thinking_model": (all_llm_models, {"default": thinking_default, "tooltip": "The 'thinker' model for reasoning. Supports local GGUF and API models."}),
                "instruct_model": (all_llm_models, {"default": instruct_default, "tooltip": "The 'clerk' model for strict JSON formatting. Supports local GGUF and API models."}),
                "whisper_data": ("STRING", {"multiline": True, "default": '{"segments": []}', "tooltip": "The JSON output from a WhisperX/Whisper node."}),
                "style_list": ("STRING", {"multiline": True, "default": "Style_A\nStyle_B", "tooltip": "A list of available visual styles, one per line."}),
                "debug_mode": ("BOOLEAN", {"default": False, "tooltip": "Print all intermediate prompts and logs to the console."}),
            },
            "optional": {
                "image_a": ("IMAGE", {"tooltip": "Optional reference image for the first style in the list."}),
                "image_b": ("IMAGE", {"tooltip": "Optional reference image for the second style in the list."}),
                "llm_device": (config.LLM_DEVICE_OPTIONS, {"default": config.DEFAULT_LLM_DEVICE, "tooltip": "Where local LLM inference should run. 'Default (GPU)' uses configured acceleration; 'CPU' forces CPU for local GGUF/HF models."}),
                "reset_context": ("BOOLEAN", {"default": config.DEFAULT_LLM_STATELESS, "tooltip": "If enabled, resets local model context before each call to avoid carrying prior conversation state."}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("decision_json", "reasoning_log")
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Studio"

    def execute(self, thinking_model, instruct_model, whisper_data, style_list, debug_mode, image_a=None, image_b=None, llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS):
        
        # 1. Parse and Validate Inputs
        try:
            whisper_json = json_utils.extract_and_parse_json(whisper_data) or {}
            segments = whisper_json.get("segments", [])
            if not segments:
                return ("{}", "[ERROR] Whisper data contains no segments.")
        except json.JSONDecodeError:
            return ("{}", "[ERROR] Invalid JSON in whisper_data. Please connect a valid Whisper node output.")

        styles = [s.strip() for s in style_list.splitlines() if s.strip()]
        if not styles:
            return ("{}", "[ERROR] No styles provided in style_list.")

        images = []
        if image_a is not None: images.append(image_a)
        if image_b is not None: images.append(image_b)

        # 2. Define Prompts and Schema for the Dual-Model Chain
        lyrics_for_prompt = "\n".join([f"- {seg['start']:.2f}s: \"{seg['text'].strip()}\"" for seg in segments])
        
        thinking_prompt = textwrap.dedent(f"""
            You are an expert music video director. Your task is to analyze the emotional rhythm of a song and plan a visually engaging video edit.
            You need to sync different visual styles to the song's beats and lyrical themes.

            **CONTEXT:**
            - **Available Visual Styles:** {', '.join(styles)}
            - **Song Lyrics & Timestamps:**
            {lyrics_for_prompt}

            **YOUR TASK:**
            Think step-by-step. Analyze the song's structure, energy, and lyrical content. 
            - When does the energy shift? 
            - Which style fits the verse vs. the chorus?
            - Should the cuts be fast or slow?
            - How can you create a compelling visual narrative?

            Based on your analysis, write down your reasoning and a plan for the edit. Describe the flow and justify your style choices for different sections of the song.
        """).strip()

        cut_list_schema = {
            "cuts": [
                {
                    "timestamp": "float (The start time of the segment in seconds)",
                    "style": "string (The name of the style to use from the available list)",
                    "transition": "string (Optional: describe the transition, e.g., 'hard cut', 'fade to black')"
                }
            ]
        }

        instruct_prompt = textwrap.dedent(f"""
            Based on the following reasoning from the director, generate the final output.
            Your response MUST be ONLY a valid JSON object that adheres strictly to the provided schema.

            **Director's Reasoning:**
            {{reasoning}}

            **JSON Schema:**
            ```json
            {json.dumps(cut_list_schema, indent=2)}
            ```

            Return ONLY the JSON object. Do not include any other text, commentary, or code fences.
        """).strip()

        # 3. Execute the Dual-Model Chain
        try:
            # --- UPGRADE: Call the chain of thought process directly with the full model ID ---
            ok, result_data, reasoning_log = utils.chain_of_thought_process(
                thinking_prompt=thinking_prompt,
                thinking_model=thinking_model,
                instruct_prompt=instruct_prompt,
                instruct_model=instruct_model,
                images=images,
                debug_mode=debug_mode,
                seed=123,
                timeout=300,
                llm_device=llm_device,
                reset_context=reset_context,
            )

            if not ok:
                return ("{}", f"[ERROR] The dual-model chain failed.\n--- REASONING LOG ---\n{reasoning_log}\n--- ERROR ---\n{result_data}")

            decision_json = json.dumps(result_data, indent=2)
            
            return (decision_json, reasoning_log)

        except Exception as e:
            import traceback
            error_message = f"[FATAL ERROR] An unexpected exception occurred in the DirectorAgent node: {e}"
            reasoning_log = traceback.format_exc()
            return ("{}", f"{error_message}\n\n{reasoning_log}")


# Make sure the new node is registered for ComfyUI to find
NODE_CLASS_MAPPINGS = {
    "PromptCrafter_DirectorAgent": PromptCrafter_DirectorAgent
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_DirectorAgent": "???? Legacy ?? Director Agent"
}
