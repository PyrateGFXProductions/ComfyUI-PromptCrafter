# Standard library imports
import os
import shutil
import re
import json
import time
import random
import copy
import concurrent.futures
import threading
import collections
import warnings
import textwrap
from pathlib import Path
from typing import Union

# Third-party imports
import torch
from PIL import Image
import librosa

# ComfyUI imports
import comfy.utils

# Local module imports
from ..core import pgfx_api_clients as api_clients
from ..core import pgfx_config as config
from ..core.profiles import pgfx_style_profiles as style_profiles
from ..utils import pgfx_utils as utils
from ..utils import pgfx_json_utils as json_utils
from ..utils import pgfx_text_io as text_io
from ..core.profiles import pgfx_organization_profiles as organization_profiles
from . import pgfx_audio_nodes as pgfx_splitter_v2
from . import pgfx_audio_srt as pgfx_srt_creator
from ..core.profiles import pgfx_captioner_profiles as captioner_profiles
from . import pgfx_creator_nodes as creator_nodes
from ..core import pgfx_thinking_engine as thinking_process

# Suppress the specific UserWarning from speechbrain that is triggered by whisperx
# warnings.filterwarnings("ignore", category=UserWarning, module='speechbrain.inference')

# ------------------------------------------------------------------------------------
# Helper function to read node descriptions from HELP.md
# ------------------------------------------------------------------------------------
def get_node_description(node_name):
    """Parses HELP.md and extracts the description for a given node class name."""
    try:
        help_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "HELP.md")
        if not os.path.exists(help_path):
            return f"Help file not found for {node_name}."

        with open(help_path, "r", encoding="utf-8") as f:
            content = f.read()

        pattern = re.compile(rf"## `{node_name}`\n(.*?)(?=\n## `|\Z)", re.DOTALL)
        match = pattern.search(content)

        if match:
            return match.group(1).strip()
        else:
            # Fallback for the custom profiles section
            if node_name == "Customizing Profiles":
                pattern = re.compile(r"## Customizing Profiles\n(.*)", re.DOTALL)
                match = pattern.search(content)
                if match:
                    return match.group(1).strip()
            return f"No description found in HELP.md for {node_name}."

    except Exception as e:
        return f"Error reading help file: {e}"

def _llm_runtime_optional_inputs():
    return {
        "llm_device": (
            config.LLM_DEVICE_OPTIONS,
            {
                "default": config.DEFAULT_LLM_DEVICE,
                "tooltip": "Where local LLM inference should run. 'Default (GPU)' uses configured acceleration; 'CPU' forces CPU for local GGUF/HF models.",
            },
        ),
        "reset_context": (
            "BOOLEAN",
            {
                "default": config.DEFAULT_LLM_STATELESS,
                "tooltip": "If enabled, resets local model context before each call to avoid carrying prior conversation state.",
            },
        ),
    }

def _resolve_llm_runtime_kwargs(source):
    return {
        "llm_device": source.get("llm_device", config.DEFAULT_LLM_DEVICE),
        "reset_context": bool(source.get("reset_context", config.DEFAULT_LLM_STATELESS)),
    }

def _json_only_requested(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    if "json" not in lower:
        return False
    if "```json" in lower:
        return True
    triggers = (
        "return only valid json",
        "return only json",
        "return only a json",
        "return only a raw json",
        "return only a raw json object",
        "return only the json",
        "output only json",
        "json only",
        "return a single json object",
        "return only the full json object",
    )
    return any(t in lower for t in triggers)

def _extract_expected_json_keys(text: str):
    if not text:
        return []
    # 1) Explicit count line wins (real task, not example)
    lyrics_count = re.search(r"lyrics to fix:\s*\((\d+)\s*segments?\)", text, re.IGNORECASE)
    if lyrics_count:
        try:
            count = int(lyrics_count.group(1))
            if count > 0:
                return [f"lyricSegment{i}" for i in range(1, count + 1)]
        except Exception:
            pass
    # 2) Explicit assignments win next (lyricSegmentN=...)
    assign_lyric = [f"lyricSegment{m.group(1)}" for m in re.finditer(r"\blyricsegment(\d+)\s*=", text, re.IGNORECASE)]
    if assign_lyric:
        return _sort_segment_keys(assign_lyric)
    return []

def _diff_expected_keys(parsed_keys, expected_keys):
    expected_set = set(expected_keys)
    parsed_set = set(parsed_keys)
    missing = [k for k in expected_keys if k not in parsed_set]
    extra = sorted([k for k in parsed_set if k not in expected_set])
    return missing, extra

def _sort_segment_keys(keys):
    seen = set()
    ordered = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    def _key_num(k):
        m = re.search(r"(\d+)$", k)
        return int(m.group(1)) if m else 0
    return sorted(ordered, key=_key_num)

def _build_json_schema_for_keys(keys):
    if not keys:
        return None
    return {
        "type": "object",
        "properties": {k: {"type": "string"} for k in keys},
        "required": keys,
        "additionalProperties": False,
    }

def _strip_code_fences(text: str) -> str:
    if text is None:
        return ""
    raw = str(text)
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw.strip()

def _ensure_escaped_quote_value(value: str) -> str:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    label_match = re.match(r"^\s*(\([^)]+\))\s*(.*)$", text, re.DOTALL)
    if label_match:
        label = label_match.group(1).strip()
        rest = label_match.group(2).strip()
        if rest.startswith('\\"') and rest.endswith('\\"'):
            return f"{label} {rest}"
        if rest.startswith('"') and rest.endswith('"'):
            rest = rest[1:-1].strip()
        return f"{label} \\\"{rest}\\\""
    if text.startswith('\\"') and text.endswith('\\"'):
        return text
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1].strip()
    return f"\\\"{text}\\\""

def _enforce_value_quotes(parsed, expected_keys=None):
    if not isinstance(parsed, dict):
        return parsed
    ordered_keys = expected_keys if expected_keys else list(parsed.keys())
    rebuilt = {}
    for key in ordered_keys:
        if key in parsed:
            rebuilt[key] = _ensure_escaped_quote_value(parsed[key])
    for key, val in parsed.items():
        if key not in rebuilt:
            rebuilt[key] = _ensure_escaped_quote_value(val)
    return rebuilt

def _force_lyricsegment_keys(parsed):
    if not isinstance(parsed, dict):
        return parsed
    remapped = {}
    for key, val in parsed.items():
        k = str(key)
        m = re.match(r"^lyricsegment(\d+)$", k, re.IGNORECASE)
        if m:
            new_key = f"lyricSegment{m.group(1)}"
        else:
            m = re.match(r"^segment(\d+)$", k, re.IGNORECASE)
            if m:
                new_key = f"lyricSegment{m.group(1)}"
            else:
                new_key = key
        if new_key in remapped:
            continue
        remapped[new_key] = val
    return remapped

def _rekey_by_order(parsed, expected_keys=None):
    if not isinstance(parsed, dict) or not expected_keys:
        return parsed
    if len(parsed) != len(expected_keys):
        return parsed
    items = list(parsed.items())
    def _key_num(k):
        m = re.search(r"(\d+)$", str(k))
        return int(m.group(1)) if m else None
    nums = [ _key_num(k) for k, _ in items ]
    if all(n is not None for n in nums):
        items = sorted(items, key=lambda kv: _key_num(kv[0]))
    return {expected_keys[i]: items[i][1] for i in range(len(expected_keys))}


# ------------------------------------------------------------------------------------
# PromptCrafter_QnA Node
# ------------------------------------------------------------------------------------
class PromptCrafter_QnA:
    DESCRIPTION = get_node_description("PromptCrafter_QnA")
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "instruction": ("STRING", {"multiline": True, "default": config.DEFAULT_PROMPT_TEXT, "tooltip": "Your primary question or instruction for the model."} ),
                "subject": ("STRING", {"multiline": True, "default": "", "tooltip": "Optional: The subject, topic, or any additional text to provide context for your instruction."} ),
                "model": (api_clients.get_all_models(), {"tooltip": "The language model (text or vision) to use for the answer."} ),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Controls creativity. Lower is more deterministic."} ),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "step": 1, "tooltip": "Seed for reproducible results. -1 for random. Set Temperature to 0 for full determinism."} ),
                "timeout": ("INT", {"default": 300, "min": 30, "max": 600, "step": 10, "tooltip": "Timeout in seconds for each API call. Increase if you get timeout errors."} ),
                "safe_mode": ("BOOLEAN", {"default": True, "tooltip": "Enforce SFW rules to prevent NSFW, violent, or controversial content."} ),
                "debug_mode": ("BOOLEAN", {"default": False, "tooltip": "Print all intermediate prompts to the console for debugging."} ),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
            "optional": {
                "thinking_model": (api_clients.get_all_models(), {"tooltip": "Optional: The 'thinker' model for the dual-model chain. Overrides the main model for reasoning."} ),
                "instruct_model": (api_clients.get_all_models(), {"tooltip": "Optional: The 'instruct' model for the dual-model chain. Used for strict JSON formatting."} ),
                **_llm_runtime_optional_inputs(),
                "image": ("IMAGE", {"tooltip": "Optional reference image for the query. Requires a vision model (VLM)."} ),
                "auto_select_model": ("BOOLEAN", {"default": True, "tooltip": "Automatically select a vision model if an image is connected, or a text model if not."} ),
                "enable_web_search": ("BOOLEAN", {"default": True, "tooltip": "Allow the node to perform a web search for questions about recent events or topics requiring current information."} ),
                "fast_web_search": ("BOOLEAN", {"default": True, "tooltip": "In web search mode, only use search result snippets instead of fetching full page content. Much faster."} ),
                "folder_path": ("STRING", {"multiline": False, "default": "input", "tooltip": "Folder containing an optional context file (e.g., 'input' or 'input/texts')."} ),
                "file_name": ("STRING", {"multiline": False, "default": "<none>", "tooltip": "The name of the text file within the specified folder."} ),
                "chunk_large_context": ("BOOLEAN", {"default": True, "tooltip": "Automatically chunk and summarize context files that are too large."} ),
                "chunk_size_words": ("INT", {"default": 2000, "min": 500, "max": 8000, "step": 100, "tooltip": "The approximate size of each chunk in words for summarization."} ),
                "summarization_strategy": (["Default (Abstractive)", "Extractive"], {"default": "Default (Abstractive)", "tooltip": "How to summarize large context. Abstractive creates new text, Extractive pulls key sentences."} ),
                "instruct_output_mode": (["Answer JSON (Default)", "User Output (No Parsing)", "User Output (Parse JSON)"], {"default": "Answer JSON (Default)", "tooltip": "How to format/parse the instructor output."}),
                "format_profile": (text_io.QNA_FORMAT_PROFILE_OPTIONS, {"default": "Custom", "tooltip": "Quick presets for output formatting and auto-save."}),
                "output_target": (text_io.QNA_OUTPUT_TARGET_OPTIONS, {"default": "Response", "tooltip": "Which QnA output(s) to format."}),
                "output_format": (text_io.FORMAT_OPTIONS, {"default": "Plain Text", "tooltip": "Format to apply to the selected output(s)."}),
                "auto_save": ("BOOLEAN", {"default": False, "tooltip": "Auto-save the selected output(s) to a file."}),
                "auto_save_target": (text_io.QNA_OUTPUT_TARGET_OPTIONS, {"default": "Response", "tooltip": "Which output(s) to auto-save."}),
                "auto_save_folder_path": ("STRING", {"multiline": False, "default": "ComfyUI/output/PromptCrafter", "tooltip": "Folder to save files into."}),
                "auto_save_filename_template": ("STRING", {"multiline": False, "default": "{seed}_{model_name}_{target}.txt", "tooltip": "Filename template. Supports {model_name}, {seed}, {user_text}, {custom_var}, {target}, {format}, {file_type}."}),
                "auto_save_file_type": (text_io.AUTO_FILE_TYPE_OPTIONS, {"default": "Match Output Format", "tooltip": "File extension for auto-saved files."}),
                "auto_save_custom_var": ("STRING", {"multiline": False, "default": "", "tooltip": "Custom placeholder value for {custom_var} in the filename template."}),
                "max_tokens": ("INT", {"default": 4096, "min": 256, "max": 32768, "step": 256, "tooltip": "Max tokens for the instructor output. Increase for long JSON."}),
                "history_in": ("STRING", {"multiline": False, "default": "", "input": "hidden"}),
                "clear_history": ("BOOLEAN", {"default": False, "tooltip": "Set to True for one run to clear the conversation history."} ),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("response", "history_out", "thinking_process")
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Utils"
    
    def execute(self, instruction, subject, model, **kwargs):
        try:
            llm_runtime_kwargs = _resolve_llm_runtime_kwargs(kwargs)
            thinking_model = kwargs.get("thinking_model")
            instruct_model = kwargs.get("instruct_model")
            user_text = f"INSTRUCTION:\n{instruction}\n\nSUBJECT:\n{subject}" if subject else instruction
            debug_mode = kwargs.get('debug_mode', False)
            seed = kwargs.get('seed', -1)
            timeout = kwargs.get('timeout', 120)
            image = kwargs.get('image')
            instruct_output_mode = kwargs.get('instruct_output_mode', "Answer JSON (Default)")
            format_profile = kwargs.get('format_profile', "Custom")
            output_target = kwargs.get('output_target', "Response")
            output_format = kwargs.get('output_format', "Plain Text")
            auto_save = kwargs.get('auto_save', False)
            auto_save_target = kwargs.get('auto_save_target', "Response")
            auto_save_folder_path = kwargs.get('auto_save_folder_path', "ComfyUI/output/PromptCrafter")
            auto_save_filename_template = kwargs.get('auto_save_filename_template', "{seed}_{model_name}_{target}.txt")
            auto_save_file_type = kwargs.get('auto_save_file_type', "Match Output Format")
            auto_save_custom_var = kwargs.get('auto_save_custom_var', "")
            max_tokens = kwargs.get('max_tokens', 4096)
            force_json = _json_only_requested(user_text)
            expected_keys = _extract_expected_json_keys(user_text)
            expected_schema = _build_json_schema_for_keys(expected_keys)
            if force_json:
                ok, response = api_clients.query_model_auto(
                    model,
                    prompt=user_text,
                    images=[image] if image is not None else [],
                    prefer_chat=False,
                    temperature=0.0,
                    seed=0,
                    timeout=timeout,
                    max_tokens=max_tokens,
                    no_chat_fallback=True,
                    template="{{ .Prompt }}",
                    format="json",
                    debug_mode=debug_mode,
                    debug_title="QnA (JSON Strict)",
                    **llm_runtime_kwargs,
                )
                if not ok:
                    raise Exception(response)
                response_text = "" if response is None else str(response).strip()
                response_text = _strip_code_fences(response_text)
                if not response_text:
                    return ("", "", "")
                try:
                    parsed = json.loads(response_text)
                except Exception as e:
                    raise Exception(f"JSON-only response requested but model returned invalid JSON: {e}")
                if expected_keys:
                    if not isinstance(parsed, dict):
                        raise Exception("JSON-only response requested but model returned non-object JSON.")
                parsed = _force_lyricsegment_keys(parsed)
                parsed = _enforce_value_quotes(parsed, expected_keys)
                response_text = json.dumps(parsed, indent=2, ensure_ascii=False)
                return (response_text, "", "")


            if format_profile and format_profile != "Custom":
                profile = text_io.QNA_FORMAT_PROFILES.get(format_profile)
                if profile:
                    output_target = profile.get("output_target", output_target)
                    output_format = profile.get("output_format", output_format)
                    auto_save = profile.get("auto_save", auto_save)
                    auto_save_target = profile.get("auto_save_target", auto_save_target)
                    auto_save_file_type = profile.get("auto_save_file_type", auto_save_file_type)

            def _resolve_qna_targets(value):
                if value == "All":
                    return {"Response", "History", "Thinking"}
                if value == "Response + Thinking":
                    return {"Response", "Thinking"}
                if value in {"Response", "History", "Thinking"}:
                    return {value}
                return {"Response"}

            def _strip_code_fences(text):
                if text is None:
                    return ""
                raw = str(text)
                match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, re.DOTALL)
                if match:
                    return match.group(1).strip()
                return raw

            def _format_and_maybe_save(response_text, history_text, thinking_text):
                response_out = "" if response_text is None else str(response_text)
                history_out = "" if history_text is None else str(history_text)
                thinking_out = "" if thinking_text is None else str(thinking_text)

                format_targets = _resolve_qna_targets(output_target)
                if "Response" in format_targets:
                    response_out = _strip_code_fences(response_out)
                    parsed_json = None
                    should_parse = output_format == "JSON" or instruct_output_mode == "User Output (Parse JSON)"
                    if should_parse:
                        parsed_json = json_utils.extract_and_parse_json(response_out)
                    if parsed_json is not None:
                        response_out = json.dumps(parsed_json, indent=2, ensure_ascii=False)
                        if output_format == "JSON":
                            format_targets = set(t for t in format_targets if t != "Response")
                    elif output_format == "JSON":
                        if response_out.lstrip().startswith(("{", "[")):
                            format_targets = set(t for t in format_targets if t != "Response")
                if "Response" in format_targets:
                    response_out = text_io.format_text_payload(response_out, output_format, label="response")
                if "History" in format_targets:
                    history_out = text_io.format_text_payload(history_out, output_format, label="history")
                if "Thinking" in format_targets:
                    thinking_out = text_io.format_text_payload(thinking_out, output_format, label="thinking_process")

                if auto_save:
                    save_targets = _resolve_qna_targets(auto_save_target)
                    resolved_type = text_io.resolve_file_type(auto_save_file_type, output_format)
                    base_replacements = {
                        "model_name": model,
                        "seed": seed,
                        "user_text": instruction,
                        "custom_var": auto_save_custom_var,
                        "format": output_format.replace(" ", "_").lower(),
                        "file_type": resolved_type,
                    }
                    target_map = {
                        "Response": response_out,
                        "History": history_out,
                        "Thinking": thinking_out,
                    }
                    for target_name, text_val in target_map.items():
                        if target_name not in save_targets:
                            continue
                        if not text_val or not str(text_val).strip():
                            continue
                        replacements = dict(base_replacements)
                        replacements["target"] = target_name.lower()
                        try:
                            text_io.save_text_to_file(
                                text_val,
                                auto_save_folder_path,
                                auto_save_filename_template,
                                resolved_type,
                                replacements=replacements,
                            )
                        except Exception as e:
                            print(f"\033[91m[PromptCrafter] Auto-save failed for {target_name}: {e}\033[0m")

                return response_out, history_out, thinking_out

            # --- DUAL-MODEL Q&A PATH ---
            if thinking_model and instruct_model and thinking_model != "None" and instruct_model != "None":
                print(f"\033[94m[PromptCrafter] Dual-Model mode activated for Q&A.\033[0m")

                # 1. Define Prompts and Schema for Q&A
                thinking_prompt = textwrap.dedent(f"""
                    You are an expert researcher and analyst. Your task is to thoroughly analyze the user's question and any provided context (text or image) to formulate a comprehensive, step-by-step plan for the answer.

                    **USER'S QUERY:**
                    {user_text}

                    **YOUR TASK:**
                    1.  **Deconstruct the Query:** What is the user's core question? Are there any implicit sub-questions?
                    2.  **Analyze Context:** Review any provided text or image context. What key information is available?
                    3.  **Formulate a Strategy:** Outline the steps needed to construct a high-quality answer. What topics must be covered? In what order?
                    4.  **Draft Key Points:** Write down the essential points, facts, or arguments that will form the basis of the final answer.

                    Write down your detailed reasoning and a clear plan for the final response.
                """).strip()

                expect_json = True
                if instruct_output_mode == "Answer JSON (Default)":
                    instruct_schema = {
                        "answer": "string (The final, well-structured, and comprehensive answer to the user's query, written in clear language.)"
                    }

                    instruct_prompt = textwrap.dedent(f"""
                        Based on the following detailed reasoning and plan, generate a final JSON object containing the complete answer.

                        **REASONING & PLAN:**
                        {{reasoning}}

                        **USER QUESTION:**
                        {user_text}

                        **JSON SCHEMA:**
                        {json.dumps(instruct_schema, indent=2)}

                        Return ONLY a raw JSON object. Do not wrap the JSON in markdown code fences.
                    """).strip()
                elif instruct_output_mode == "User Output (Parse JSON)":
                    instruct_prompt = textwrap.dedent(f"""
                        Use the user's instructions below to produce the final output.
                        Follow all formatting and output rules exactly.
                        Return ONLY a raw JSON object. Do not wrap the JSON in markdown code fences.

                        **USER INSTRUCTIONS:**
                        {user_text}

                        **REASONING & PLAN:**
                        {{reasoning}}
                    """).strip()
                else:
                    expect_json = False
                    instruct_prompt = textwrap.dedent(f"""
                        Use the user's instructions below to produce the final output.
                        Follow all formatting and output rules exactly (including code blocks if requested).
                        Return ONLY the final output.

                        **USER INSTRUCTIONS:**
                        {user_text}

                        **REASONING & PLAN:**
                        {{reasoning}}
                    """).strip()

                # 2. Execute the chain of thought
                ok, result_data, reasoning_log = utils.chain_of_thought_process(
                    thinking_prompt=thinking_prompt,
                    thinking_model=thinking_model,
                    instruct_prompt=instruct_prompt,
                    instruct_model=instruct_model,
                    images=[image] if image is not None else [],
                    debug_mode=debug_mode,
                    seed=seed,
                    timeout=timeout,
                    expect_json=expect_json,
                    max_tokens=max_tokens,
                    **llm_runtime_kwargs,
                )

                # 3. Unpack and return results (with a fallback if JSON parsing fails)
                if ok:
                    if instruct_output_mode == "Answer JSON (Default)" and isinstance(result_data, dict):
                        final_answer = (result_data.get("answer") or "").strip()
                        if final_answer:
                            response_out, history_out, thinking_out = _format_and_maybe_save(final_answer, "", reasoning_log)
                            return (response_out, history_out, thinking_out)
                    elif instruct_output_mode == "User Output (Parse JSON)" and isinstance(result_data, (dict, list)):
                        final_answer = json.dumps(result_data, indent=2, ensure_ascii=False)
                        response_out, history_out, thinking_out = _format_and_maybe_save(final_answer, "", reasoning_log)
                        return (response_out, history_out, thinking_out)
                    elif instruct_output_mode == "User Output (No Parsing)" and isinstance(result_data, str) and result_data.strip():
                        response_out, history_out, thinking_out = _format_and_maybe_save(result_data.strip(), "", reasoning_log)
                        return (response_out, history_out, thinking_out)

                # Fallback: if the instructor couldn't return valid JSON, request plain text.
                fallback_answer = ""
                ok_fallback = False
                if reasoning_log and reasoning_log.strip():
                    if instruct_output_mode == "Answer JSON (Default)":
                        fallback_prompt = textwrap.dedent(f"""
                            Use the reasoning below to answer the user's question directly.
                            Return ONLY a raw JSON object matching this schema: {json.dumps({"answer": "string"}, ensure_ascii=False)}.
                            Do not wrap the JSON in markdown code fences.

                            REASONING & PLAN:
                            {reasoning_log}

                            USER QUESTION:
                            {user_text}
                        """).strip()
                    elif instruct_output_mode == "User Output (Parse JSON)":
                        fallback_prompt = textwrap.dedent(f"""
                            Use the reasoning below to answer the user's instructions.
                            Return ONLY a raw JSON object. Do not wrap the JSON in markdown code fences.

                            USER INSTRUCTIONS:
                            {user_text}

                            REASONING & PLAN:
                            {reasoning_log}
                        """).strip()
                    else:
                        fallback_prompt = textwrap.dedent(f"""
                            Use the reasoning below to answer the user's question directly.
                            Return ONLY the final answer text. No JSON, no markdown, no extra commentary.

                            REASONING & PLAN:
                            {reasoning_log}

                            USER QUESTION:
                            {user_text}
                        """).strip()

                    ok_fallback, fallback_answer = api_clients.query_model_auto(
                        instruct_model,
                        prompt=fallback_prompt,
                        images=[],
                        prefer_chat=True,
                        temperature=kwargs.get('temperature', 0.2),
                        seed=seed,
                        timeout=timeout,
                        max_tokens=max_tokens,
                        debug_mode=debug_mode,
                        debug_title="Dual-Model Stage 2: Instructor (Text Fallback)",
                        **llm_runtime_kwargs,
                    )

                if ok_fallback and fallback_answer and fallback_answer.strip():
                    response_out, history_out, thinking_out = _format_and_maybe_save(fallback_answer.strip(), "", reasoning_log)
                    return (response_out, history_out, thinking_out)

                if not ok:
                    raise Exception(f"Dual-Model Chain failed: {result_data}")
                raise Exception("Dual-Model Chain failed: Instructor returned invalid or empty JSON, and fallback text generation failed.")

            # --- SINGLE-MODEL (LEGACY) Q&A PATH ---
            else:
                # 1. Set up the configuration for this run
                config_params = {
                    'model': model,
                    'language': utils._detect_language(instruction),
                    'temperature': kwargs.get('temperature', 0.2),
                    'max_length_words': 0, # Not applicable for QnA
                    'use_chat_api': True,
                    'use_deep_think': False, # Not applicable for QnA
                    'auto_select_model': kwargs.get('auto_select_model', True),
                    'seed': seed,
                    'timeout': timeout,
                    'debug_mode': debug_mode,
                    'safe_mode': kwargs.get('safe_mode', True),
                    'style_profile': {}, # Not applicable for QnA
                    'llm_device': llm_runtime_kwargs.get("llm_device"),
                    'reset_context': llm_runtime_kwargs.get("reset_context"),
                }

                from dataclasses import fields
                config_fields = {f.name for f in fields(config.PromptCrafterRunConfig)}
                filtered_params = {k: v for k, v in config_params.items() if k in config_fields}
                run_config = config.PromptCrafterRunConfig(**filtered_params)

                # 2. Prepare parameters for the ThoughtProcess QnA lobe
                qna_params = {
                    'qna_instruction': instruction,
                    'qna_subject': subject,
                    'qna_image': image,
                    'qna_history_in': kwargs.get('history_in', ''),
                    'qna_clear_history': kwargs.get('clear_history', False),
                    'qna_folder_path': kwargs.get('folder_path'),
                    'qna_file_name': kwargs.get('file_name', '<none>'),
                    'qna_enable_web_search': kwargs.get('enable_web_search', True),
                    'qna_fast_web_search': kwargs.get('fast_web_search', True),
                    'qna_summarization_strategy': kwargs.get('summarization_strategy', "Default (Abstractive)"),
                    'qna_chunk_large_context': kwargs.get('chunk_large_context', True),
                    'qna_chunk_size_words': kwargs.get('chunk_size_words', 2000),
                    'qna_safe_mode': kwargs.get('safe_mode', True),
                }

                # 3. Instantiate and run the central thinking process
                thought_process = thinking_process.ThoughtProcess(
                    run_config=run_config,
                    user_text=instruction,
                    negative_prompt="",
                    image_context="",
                    primary_subjects_from_images=[],
                    mode="QnA",
                    **qna_params
                )

                response_text, updated_history = thought_process.run()

                response_out, history_out, thinking_out = _format_and_maybe_save(
                    response_text,
                    updated_history,
                    "Thinking process not available in single-model mode."
                )
                return (response_out, history_out, thinking_out)

        except Exception as e:
            print(f"\033[91m[PromptCrafter] Error in QnA node: {e}\033[0m")
            import traceback
            traceback.print_exc()
            return (f"An error occurred: {e}", "", "")

# ------------------------------------------------------------------------------------
# PromptCrafter_QnA_Simple Node
# ------------------------------------------------------------------------------------
class PromptCrafter_QnA_Simple:
    DESCRIPTION = "Minimal Q&A node that mirrors the old Gemini API behavior. Instruction-only, no formatting."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": config.DEFAULT_PROMPT_TEXT, "tooltip": "Your question or instructions for the model."}),
                "model": (api_clients.get_all_models(), {"tooltip": "The model to use."}),
            },
            # Keep hidden workflow prompt metadata under a unique key to avoid
            # colliding with the user-facing "prompt" input value.
            "hidden": {"workflow_prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
            "optional": {
                "image": ("IMAGE", {"tooltip": "Optional reference image (requires a vision model)."}),
                **_llm_runtime_optional_inputs(),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("response",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Utils"

    def execute(self, prompt, model, image=None, **kwargs):
        try:
            llm_runtime_kwargs = _resolve_llm_runtime_kwargs(kwargs)
            user_text = "" if prompt is None else str(prompt)
            force_json = _json_only_requested(user_text)
            expected_keys = _extract_expected_json_keys(user_text)
            expected_schema = _build_json_schema_for_keys(expected_keys)
            if not user_text.strip():
                return ("",)

            model_name = "" if model is None else str(model)
            is_gguf_model = model_name.lower().startswith("gguf/")
            is_vision_request = image is not None
            llm_device_choice = str(llm_runtime_kwargs.get("llm_device", config.DEFAULT_LLM_DEVICE)).strip().lower()
            cpu_mode = llm_device_choice in {"cpu", "host", "cpu-only", "cpu only"}
            # Keep QnA outputs concise and avoid large KV allocations before the
            # downstream video pipeline starts.
            safe_max_tokens = 768 if is_vision_request else 1536
            gguf_runtime_kwargs = {}
            if is_gguf_model:
                gguf_runtime_kwargs["unload_after_query"] = True
                gguf_runtime_kwargs["unload_vision_after_query"] = is_vision_request
                gguf_runtime_kwargs["vision_projector_use_gpu"] = False
                if is_vision_request and cpu_mode:
                    # Keep QnA vision inference off the GPU so downstream video
                    # sampler/preview stages retain VRAM headroom.
                    gguf_runtime_kwargs["n_gpu_layers"] = 0
                    gguf_runtime_kwargs["n_batch"] = 64
                    gguf_runtime_kwargs["n_ubatch"] = 32

            ok, response = api_clients.query_model_auto(
                model,
                prompt=user_text,
                images=[image] if image is not None else [],
                prefer_chat=False,
                temperature=0.0,
                seed=0,
                timeout=120,
                max_tokens=safe_max_tokens,
                no_chat_fallback=True,
                template="{{ .Prompt }}",
                format=("json" if force_json else None),
                debug_mode=False,
                debug_title="Simple QnA",
                **gguf_runtime_kwargs,
                **llm_runtime_kwargs,
            )

            if not ok:
                return (f"An error occurred: {response}",)

            response_text = "" if response is None else str(response).strip()
            if force_json:
                response_text = _strip_code_fences(response_text)
                try:
                    parsed = json.loads(response_text)
                except Exception as e:
                    raise Exception(f"JSON-only response requested but model returned invalid JSON: {e}")
                if expected_keys:
                    if not isinstance(parsed, dict):
                        raise Exception("JSON-only response requested but model returned non-object JSON.")
                parsed = _force_lyricsegment_keys(parsed)
                parsed = _enforce_value_quotes(parsed, expected_keys)
                response_text = json.dumps(parsed, indent=2, ensure_ascii=False)
            if not response_text:
                return ("",)

            return (response_text,)
        except Exception as e:
            print(f"\033[91m[PromptCrafter] Error in Simple QnA node: {e}\033[0m")
            import traceback
            traceback.print_exc()
            return (f"An error occurred: {e}",)

# ------------------------------------------------------------------------------------
# PromptCrafter THINK/INSTRUCT Nodes (Deterministic, Paired)
# ------------------------------------------------------------------------------------
class PromptCrafter_LyricsThink:
    DESCRIPTION = "THINK node for lyric correction and section labeling. Outputs plain text lines."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "input_text": ("STRING", {"multiline": True, "default": ""}),
                "model": (api_clients.get_all_models(), {"tooltip": "The model to use for reasoning."}),
            },
            "optional": {
                **_llm_runtime_optional_inputs(),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("lyrics_think_output",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Text/Think"

    def execute(self, input_text, model, llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS):
        raw_text = "" if input_text is None else str(input_text)
        if not raw_text.strip():
            return ("[ERROR] Input text is empty.",)

        non_empty_lines = [line for line in raw_text.splitlines() if line.strip()]
        segment_count = len(non_empty_lines)

        prompt = textwrap.dedent(f"""
            You are a lyric correction and alignment engine.

            Your task is to correct and expand segmented lyric transcriptions without changing their order or timing.

            INPUT RULES:
            - There are exactly {segment_count} lyric segments.
            - Each segment corresponds to a fixed 4-second time window.
            - Segment numbering and order are locked.

            WHAT YOU MUST DO:
            - Fix typos, misheard words, capitalization, and minor grammar.
            - Preserve the original meaning, tone, and mood.
            - Preserve each segment's place in the song.

            DO NOT:
            - Move words between segments.
            - Merge or split segments.
            - Pull lyrics from other sections of the song.

            SHORT SEGMENT EXPANSION (MANDATORY):
            - If a segment has fewer than 3 words, you must expand it.
            - If it is part of an existing lyric line, add nearby words from the same line in the reference lyrics.
            - If it is a vocal or instrumental moment, invent a short lyrical phrase (3–7 words).
            - It must sound natural and stylistically consistent.
            - No filler syllables unless present in the song.

            SECTION LABELS:
            - Assign a label such as Intro, Verse, Pre-Chorus, Chorus, Bridge, Outro.

            OUTPUT FORMAT (STRICT):
            - Plain text only.
            - No JSON.
            - No code blocks.
            - One segment per line, exactly:
              lyricSegment<N> | <SectionLabel> | <Corrected lyric text>

            EXAMPLE OUTPUT:
            lyricSegment1 | Intro | I don’t believe it anymore
            lyricSegment2 | Intro | don’t touch me, stay away from me now
            lyricSegment3 | Verse | falling through the tunnel in the city

            FINAL RULE:
            - Output exactly {segment_count} lines, one per segment.

            INPUT:
            {raw_text}
        """).strip()

        ok, response = api_clients.query_model_auto(
            model,
            prompt=prompt,
            temperature=0.2,
            seed=0,
            llm_device=llm_device,
            reset_context=reset_context,
        )
        if not ok:
            return (f"[ERROR] Model call failed: {response}",)

        response_text = "" if response is None else str(response)
        if not response_text.strip():
            return ("[ERROR] Model returned empty output.",)
        return (response_text,)


class PromptCrafter_LyricsInstruct:
    DESCRIPTION = "INSTRUCT node that converts LyricsThink output into strict JSON."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "lyrics_think_output": ("STRING", {"multiline": True, "default": ""}),
                "model": (api_clients.get_all_models(), {"tooltip": "The model to use for formatting."}),
            },
            "optional": {
                **_llm_runtime_optional_inputs(),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("lyrics_json",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Text/Instruct"

    def execute(self, lyrics_think_output, model, llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS):
        if not lyrics_think_output or not str(lyrics_think_output).strip():
            return ("[ERROR] LyricsThink output is empty.",)

        prompt = textwrap.dedent(f"""
            You are a formatting engine. Convert the input into JSON.

            RULES:
            - Do not rewrite or infer.
            - Do not add or remove segments.
            - Each input line is: lyricSegmentN | SectionLabel | Corrected lyric text
            - Output JSON with keys lyricSegmentN and values: (SectionLabel) "Corrected lyric text"

            Return ONLY the JSON object.

            INPUT:
            {lyrics_think_output}
        """).strip()

        ok, response = api_clients.query_model_auto(
            model,
            prompt=prompt,
            temperature=0.0,
            seed=0,
            llm_device=llm_device,
            reset_context=reset_context,
        )
        if not ok:
            return (f"[ERROR] Model call failed: {response}",)

        response_text = "" if response is None else str(response)
        if not response_text.strip():
            return ("[ERROR] Model returned empty output.",)
        return (response_text,)


class PromptCrafter_VisualThink:
    DESCRIPTION = "THINK node for visual concept generation. Outputs labeled plain text."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "input_text": ("STRING", {"multiline": True, "default": ""}),
                "model": (api_clients.get_all_models(), {"tooltip": "The model to use for reasoning."}),
            },
            "optional": {
                **_llm_runtime_optional_inputs(),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("visual_think_output",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Text/Think"

    def execute(self, input_text, model, llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS):
        if not input_text or not str(input_text).strip():
            return ("[ERROR] Input text is empty.",)

        prompt = textwrap.dedent(f"""
            You are a visual concept generator for a music video.

            OUTPUT FORMAT (EXACT labels, plain text):
            STYLE:
            CAMERA LANGUAGE:
            LIGHTING:
            MOOD:
            COLOR PALETTE:
            ERA:

            INPUT:
            {input_text}
        """).strip()

        ok, response = api_clients.query_model_auto(
            model,
            prompt=prompt,
            temperature=0.2,
            seed=0,
            llm_device=llm_device,
            reset_context=reset_context,
        )
        if not ok:
            return (f"[ERROR] Model call failed: {response}",)

        response_text = "" if response is None else str(response)
        if not response_text.strip():
            return ("[ERROR] Model returned empty output.",)
        return (response_text,)


class PromptCrafter_VisualInstruct:
    DESCRIPTION = "INSTRUCT node that converts VisualThink output into JSON."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "visual_think_output": ("STRING", {"multiline": True, "default": ""}),
                "model": (api_clients.get_all_models(), {"tooltip": "The model to use for formatting."}),
            },
            "optional": {
                **_llm_runtime_optional_inputs(),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("visual_json",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Text/Instruct"

    def execute(self, visual_think_output, model, llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS):
        if not visual_think_output or not str(visual_think_output).strip():
            return ("[ERROR] VisualThink output is empty.",)

        prompt = textwrap.dedent(f"""
            You are a formatting engine. Convert the VisualThink output into JSON.

            RULES:
            - Use the content exactly as provided.
            - Do not add or remove information.
            - JSON keys must be: style, camera_language, lighting, mood, palette, era
            - Return ONLY the JSON object.

            INPUT:
            {visual_think_output}
        """).strip()

        ok, response = api_clients.query_model_auto(
            model,
            prompt=prompt,
            temperature=0.0,
            seed=0,
            llm_device=llm_device,
            reset_context=reset_context,
        )
        if not ok:
            return (f"[ERROR] Model call failed: {response}",)

        response_text = "" if response is None else str(response)
        if not response_text.strip():
            return ("[ERROR] Model returned empty output.",)
        return (response_text,)


class PromptCrafter_QnAThink:
    DESCRIPTION = "THINK node for open-ended reasoning. Plain text output only."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "model": (api_clients.get_all_models(), {"tooltip": "The model to use for reasoning."}),
            },
            "optional": {
                **_llm_runtime_optional_inputs(),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("qna_think_output",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Text/Think"

    def execute(self, prompt, model, llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS):
        if not prompt or not str(prompt).strip():
            return ("[ERROR] Prompt is empty.",)

        full_prompt = textwrap.dedent(f"""
            Provide a clear, plain-text response. No JSON. No code blocks.

            INPUT:
            {prompt}
        """).strip()

        ok, response = api_clients.query_model_auto(
            model,
            prompt=full_prompt,
            temperature=0.2,
            seed=0,
            llm_device=llm_device,
            reset_context=reset_context,
        )
        if not ok:
            return (f"[ERROR] Model call failed: {response}",)

        response_text = "" if response is None else str(response)
        if not response_text.strip():
            return ("[ERROR] Model returned empty output.",)
        return (response_text,)


class PromptCrafter_QnAInstruct:
    DESCRIPTION = "INSTRUCT node that formats QnAThink output based on an explicit instruction."

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "qna_think_output": ("STRING", {"multiline": True, "default": ""}),
                "format_instruction": ("STRING", {"multiline": True, "default": ""}),
                "model": (api_clients.get_all_models(), {"tooltip": "The model to use for formatting."}),
            },
            "optional": {
                **_llm_runtime_optional_inputs(),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("formatted_output",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Text/Instruct"

    def execute(self, qna_think_output, format_instruction, model, llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS):
        if not qna_think_output or not str(qna_think_output).strip():
            return ("[ERROR] QnAThink output is empty.",)
        if not format_instruction or not str(format_instruction).strip():
            return ("[ERROR] Format instruction is empty.",)

        prompt = textwrap.dedent(f"""
            Format the content according to the instruction. No new content. No reasoning.
            Return ONLY the formatted output.

            FORMAT INSTRUCTION:
            {format_instruction}

            CONTENT:
            {qna_think_output}
        """).strip()

        ok, response = api_clients.query_model_auto(
            model,
            prompt=prompt,
            temperature=0.0,
            seed=0,
            llm_device=llm_device,
            reset_context=reset_context,
        )
        if not ok:
            return (f"[ERROR] Model call failed: {response}",)

        response_text = "" if response is None else str(response)
        if not response_text.strip():
            return ("[ERROR] Model returned empty output.",)
        return (response_text,)

# ------------------------------------------------------------------------------------
# PromptCrafter_Captioner Node
# ------------------------------------------------------------------------------------
class PromptCrafter_Captioner:
    DESCRIPTION = get_node_description("PromptCrafter_Captioner")
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vision_model": (api_clients.get_all_models(), {"tooltip": "The vision language model (VLM) to use for captioning."}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
            "optional": {
                "image": ("IMAGE", {"tooltip": "The image to be captioned (for single mode)."}),
                "filename": ("STRING", {"default": "", "tooltip": "Filename for single mode (ignored in batch mode). If empty, a timestamp is used."} ),
                "batch_mode": ("BOOLEAN", {"default": False, "tooltip": "Enable batch processing of an entire folder."} ),
                "input_folder": ("STRING", {"default": "input/captions_todo", "tooltip": "Directory of images to process in batch mode (relative to ComfyUI root)."}),
                "skip_existing": ("BOOLEAN", {"default": True, "tooltip": "In batch mode, skip images that already have a corresponding .txt caption file."} ),
                "captioner_profile": (captioner_profiles.get_captioner_profile_options(), {"default": "Default (Training Style)", "tooltip": "Select a pre-configured captioning prompt. Overrides the manual prompt text box."} ),
                "max_workers": ("INT", {"default": 4, "min": 1, "max": 16, "step": 1, "tooltip": "Number of parallel threads for batch processing."} ),
                "caption_prompt": ("STRING", {"multiline": True, "default": config.DEFAULT_CAPTION_PROMPT, "tooltip": "The prompt template used to guide the captioning model."} ),
                "caption_prefix": ("STRING", {"multiline": False, "default": "", "tooltip": "A single trigger word to add to every caption. Overridden by the trigger words file."} ),
                "trigger_words_folder_path": ("STRING", {"multiline": False, "default": "input", "tooltip": "Folder containing an optional file of trigger words (one per line)."}),
                "trigger_words_file": ("STRING", {"multiline": False, "default": "<none>", "tooltip": "File with a list of trigger words to be randomly chosen from for each caption."} ),
                "save_caption": ("BOOLEAN", {"default": True, "tooltip": "Save the caption to a text file."} ),
                "save_in_input_folder": ("BOOLEAN", {"default": True, "tooltip": "If True, saves the .txt caption file in the batch mode input folder alongside the image. If False, saves to the output_path."} ),
                "add_caption_to_metadata": ("BOOLEAN", {"default": True, "tooltip": "Write the caption to the image's metadata (e.g., EXIF). Requires `piexif` library."} ),
                "rename_file_with_caption": ("BOOLEAN", {"default": False, "tooltip": "In batch mode, rename the image file based on the generated caption. Makes files searchable."} ),
                "output_path": ("STRING", {"default": "captions", "tooltip": "Subdirectory within ComfyUI/output to save caption files."} ),
                "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "Controls creativity. Lower is more deterministic."} ),
                "seed": ("INT", {"default": -1, "min": -1, "max": 0xffffffffffffffff, "step": 1, "tooltip": "Seed for reproducible results. -1 for random."} ),
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600, "step": 10, "tooltip": "Timeout in seconds for each API call. Increase if you get timeout errors with slow models."} ),
                "safe_mode": ("BOOLEAN", {"default": True, "tooltip": "Enforce SFW rules to prevent NSFW, violent, or controversial content."} ),
                **_llm_runtime_optional_inputs(),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("caption",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Utils"

    def _sanitize_filename(self, text, max_length=150):
        """Sanitizes a string to be a valid filename."""
        # Replace spaces and common delimiters with underscores
        text = re.sub(r'[\s,]+', '_', text)
        # Remove any characters that are not valid in filenames
        text = re.sub(r'[\\/*?:"<<>>|]', '', text)
        # Remove leading/trailing underscores and truncate
        return text.strip('_')[:max_length]

    def _caption_one_image(self, image_tensor, vision_model, final_caption_prompt, temperature, seed, debug_mode, timeout, llm_device, reset_context):
        """Helper function to run the captioning query for a single image tensor."""
        first_image = image_tensor[0] if torch.is_tensor(image_tensor) and image_tensor.ndim == 4 else image_tensor
        ok, caption = api_clients.query_model_auto(
            vision_model,
            prompt=final_caption_prompt,
            images=[first_image],
            prefer_chat=True,
            temperature=temperature,
            seed=seed,
            timeout=timeout,
            debug_mode=debug_mode,
            debug_title="Image Caption Prompt",
            llm_device=llm_device,
            reset_context=reset_context,
        )
        return (True, utils.TextCleaner.single_paragraph(caption)) if ok else (False, f"Model error: {caption}")
    
    def execute(self, vision_model, image=None, batch_mode=False, input_folder=None, skip_existing=True, captioner_profile="Default (Training Style)", max_workers=4, caption_prompt=config.DEFAULT_CAPTION_PROMPT, caption_prefix="", trigger_words_folder_path="input", trigger_words_file="<none>", save_caption=True, save_in_input_folder=True, add_caption_to_metadata=True, rename_file_with_caption=False, output_path="captions", filename="", temperature=0.2, debug_mode=False, safe_mode=True, seed=-1, timeout=120, llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS, **kwargs):
        model = vision_model or config.FALLBACK_VISION_MODEL
        
        final_caption_prompt = caption_prompt # Default to manual input
        if captioner_profile != "None (Manual Prompt)":
            profile = captioner_profiles.NAMED_CAPTIONER_PROFILES.get(captioner_profile)
            if profile and "prompt" in profile:
                final_caption_prompt = profile["prompt"]
                print(f"\033[92m[PromptCrafter] Using captioner profile: '{captioner_profile}'\033[0m")

        if safe_mode and config.SAFE_MODE_RULE not in final_caption_prompt:
            final_caption_prompt = f"{final_caption_prompt}\n{config.SAFE_MODE_RULE}"

        trigger_words = []
        fpath = utils._get_verified_path(trigger_words_folder_path, trigger_words_file)
        if fpath:
            content = utils.safe_read(fpath)
            if not content.startswith("[Error"):
                trigger_words = [line.strip() for line in content.splitlines() if line.strip()]
                if trigger_words: print(f"\033[92m[PromptCrafter] Loaded {len(trigger_words)} trigger words from {trigger_words_file}.\033[0m")

        if batch_mode:
            if not input_folder: return ("Batch mode is enabled, but no input folder was provided.",)
            full_folder_path = utils._get_verified_path(input_folder, is_dir=True)
            if not full_folder_path: return (f"Input folder not found: {input_folder}",)

            image_files = [f for f in os.listdir(full_folder_path) if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp"))]
            if not image_files: return (f"No images found in {full_folder_path}",)

            # Determine the output directory for caption files
            if save_in_input_folder:
                out_dir = full_folder_path
            else:
                out_dir = utils._get_and_create_output_dir(output_path)
                if not out_dir: return (f"Could not create or access output path: {output_path}",)

            processed_count, renamed_count, skipped_count, failed_count = 0, 0, 0, 0
            failed_files = []

            # --- FIX 1: Corrected ThreadPoolExecutor Dictionary Syntax ---
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_img = {
                    executor.submit(
                        self._caption_one_image,
                        utils.pil2tensor(Image.open(os.path.join(full_folder_path, img)).convert("RGB")),
                        model,
                        final_caption_prompt,
                        temperature,
                        seed,
                        debug_mode,
                        timeout,
                        llm_device,
                        reset_context,
                    ): img
                    for img in image_files
                }
                # -----------------------------------------------------------

                for future in concurrent.futures.as_completed(future_to_img):
                    img_filename = future_to_img[future]
                    try:
                        base_fname, img_ext = os.path.splitext(img_filename)
                        
                        # The path for the caption file depends on where we are saving it
                        if save_in_input_folder:
                            caption_filepath = os.path.join(full_folder_path, f"{base_fname}.txt")
                        else:
                            caption_filepath = os.path.join(out_dir, f"{base_fname}.txt")

                        if skip_existing and os.path.exists(caption_filepath):
                            skipped_count += 1
                            continue

                        ok, caption_text = future.result()
                        if not ok:
                            failed_count += 1
                            failed_files.append(img_filename)
                            print(f"\033[93m[PromptCrafter] Warning: Failed to caption {img_filename}: {caption_text}\033[0m")
                            continue

                        current_prefix = random.choice(trigger_words) if trigger_words else caption_prefix
                        final_caption = f"{current_prefix.strip()}, {caption_text}" if current_prefix else caption_text

                        if rename_file_with_caption:
                            sanitized_base_name = self._sanitize_filename(caption_text)
                            
                            # --- FIX 3: Corrected f-string for batch mode fallback ---
                            if not sanitized_base_name:
                                sanitized_base_name = f"caption_{int(time.time()*1000)}" 
                            # -------------------------------------------------------

                            # When renaming, the new image and caption always live in the input folder
                            # Use the new utility to get a unique path
                            new_img_path, final_sanitized_name = utils._get_unique_filepath(full_folder_path, sanitized_base_name, img_ext)
                            sanitized_base_name = final_sanitized_name # Update base name to the unique version
                            new_caption_path = os.path.join(full_folder_path, f"{sanitized_base_name}.txt")
                            
                            if save_caption:
                                with open(new_caption_path, "w", encoding="utf-8") as f: f.write(final_caption)
                            
                            os.rename(os.path.join(full_folder_path, img_filename), new_img_path)
                            if add_caption_to_metadata:
                                utils._add_metadata_to_image(new_img_path, final_caption)
                            renamed_count += 1
                            print(f"\033[92m[PromptCrafter] Renamed & Captioned: {img_filename} -> {os.path.basename(new_img_path)}\033[0m")
                        else:
                            if save_caption:
                                with open(caption_filepath, "w", encoding="utf-8") as f: f.write(final_caption)
                            processed_count += 1
                            if add_caption_to_metadata:
                                utils._add_metadata_to_image(os.path.join(full_folder_path, img_filename), final_caption)
                            print(f"\033[92m[PromptCrafter] Captioned: {img_filename}\033[0m")

                    except Exception as e:
                        failed_count += 1
                        failed_files.append(img_filename)
                        print(f"\033[91m[PromptCrafter] An unexpected error occurred for {img_filename}: {e}\033[0m")

            status_message = f"Batch complete. Total: {len(image_files)}."
            if processed_count > 0: status_message += f" Captioned: {processed_count}."
            if renamed_count > 0: status_message += f" Renamed: {renamed_count}."
            if failed_count > 0:
                failed_files_str = ", ".join(failed_files[:5])
                if failed_count > 5: failed_files_str += f", and {failed_count - 5} more"
                status_message += f" Failed: {failed_count} ({failed_files_str})."
            else:
                status_message += " Failed: 0."
            if skipped_count > 0: status_message += f" Skipped: {skipped_count}."
            return (status_message,)

        else: # Single Mode
            if image is None: return ("No image provided for single captioning mode.",)
            if rename_file_with_caption:
                print("\033[93m[PromptCrafter] Warning: 'rename_file_with_caption' is only available in batch mode and will be ignored.\033[0m")

            ok, caption = self._caption_one_image(image, model, final_caption_prompt, temperature, seed, debug_mode, timeout, llm_device, reset_context)
            if not ok: return (caption,)

            current_prefix = random.choice(trigger_words) if trigger_words else caption_prefix
            final_caption = f"{current_prefix.strip()}, {caption}" if current_prefix else caption

            if save_caption:
                out_dir = utils._get_and_create_output_dir(output_path)
                # Ensure out_dir is valid; fall back to creating the requested output_path or use CWD
                if not out_dir:
                    try:
                        os.makedirs(output_path, exist_ok=True)
                        out_dir = os.path.abspath(output_path)
                    except Exception:
                        out_dir = os.getcwd()
                        print(f"\033[93m[PromptCrafter] Warning: Could not create output path '{output_path}', falling back to current working directory: {out_dir}\033[0m")

                # --- FIX 2: Corrected f-string for single mode filename ---
                fname = filename.strip() or f"caption_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time()*1000)%1000}"
                # -------------------------------------------------------
                fname = self._sanitize_filename(fname, max_length=200)
                file_path = os.path.join(out_dir, f"{fname}.txt")
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(final_caption)
            
            # This part is tricky for single mode as we don't have the original file path.
            # This implementation assumes the user will save the image manually, and the metadata
            # won't be added. A more advanced implementation would require a file path input.
            if add_caption_to_metadata:
                print("\033[93m[PromptCrafter] Warning: 'add_caption_to_metadata' is only fully supported in batch mode where file paths are known. Metadata was not written in single mode.\033[0m")

            return (final_caption,)

# ------------------------------------------------------------------------------------
# PromptCrafter_AudioSplitter Node
# ------------------------------------------------------------------------------------
class PromptCrafter_AudioSplitter(creator_nodes.PromptCrafter_BaseCreator):
    DESCRIPTION = "Splits an audio input into 16 chunks based on timing data from a LyricsCreator 'audio_meta' output."
    
    RETURN_TYPES = tuple(["AUDIO"] * 16)
    RETURN_NAMES = tuple([f"audio_{i}" for i in range(1, 17)])
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /Creator"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "audio_meta": ("DICT", {"tooltip": "The 'audio_meta' output from a PromptCrafter_LyricsCreator node."}),
                "set_index": ("INT", {"default": 0, "min": 0, "max": 999, "tooltip": "The current batch/set number (e.g., 0 for first 16 scenes, 1 for next 16)."}),
            }
        }

    def execute(self, audio, audio_meta, set_index=0):
        try:
            # --- DEBUG: Inspect incoming audio_meta ---
            if isinstance(audio_meta, dict) and audio_meta:
                print(f"\033[95m[PromptCrafter_AudioSplitter DEBUG] Received audio_meta keys: {list(audio_meta.keys())}\033[0m")
            else:
                print(f"\033[95m[PromptCrafter_AudioSplitter DEBUG] Received audio_meta is not a dictionary. Type: {type(audio_meta)}\033[0m")
            # -----------------------------------------

            # --- 1. Unpack Audio and Meta ---
            if not isinstance(audio, dict) or "waveform" not in audio:
                raise ValueError("Invalid AUDIO input. Expected a dictionary with 'waveform' and 'sample_rate'.")
            
            waveform = audio["waveform"]
            sample_rate = int(audio["sample_rate"])

            if waveform.ndim == 2:
                waveform = waveform.unsqueeze(0) # (C, T) -> (B, C, T)

            total_samples = waveform.shape[-1]
            total_duration_sec = total_samples / sample_rate

            if not isinstance(audio_meta, dict):
                raise ValueError("Invalid 'audio_meta' input. Expected a dictionary from PromptCrafter_LyricsCreator.")

            timed_segments = audio_meta.get("timed_segments")
            fps = float(audio_meta.get("fps", 16.0))
            scene_splitting_mode = audio_meta.get("scene_splitting_mode", "Structural Tag")
            
            scene_samples = 0
            
            # --- 2. Determine Scene Length in Samples ---
            if scene_splitting_mode == 'Frame Length':
                frames_per_scene = int(audio_meta.get("max_scene_frames", 120))
                scene_samples = int(frames_per_scene * (sample_rate / fps))
            elif scene_splitting_mode == 'Fixed Duration':
                duration_per_scene = float(audio_meta.get("max_scene_duration_seconds", 5.0))
                scene_samples = int(duration_per_scene * sample_rate)
            
            segments = []
            scene_count = 16 # This node always outputs 16 scenes
            
            # --- 3. Split Audio ---
            if timed_segments:
                # Path A: We have real timing data from Whisper/alignment
                print(f"[PromptCrafter_AudioSplitter] Splitting audio using {len(timed_segments)} timed segments.")
                
                # Get the 16 segments for the current set_index
                start_idx = set_index * scene_count
                end_idx = start_idx + scene_count
                segments_for_this_set = timed_segments[start_idx:end_idx]
                
                for i in range(scene_count):
                    if i < len(segments_for_this_set):
                        start_sec, end_sec, _ = segments_for_this_set[i]
                        start_samp = int(start_sec * sample_rate)
                        end_samp = int(end_sec * sample_rate)
                        
                        # Clamp to audio boundaries
                        start_samp = max(0, start_samp)
                        end_samp = min(total_samples, end_samp)
                        
                        seg = waveform[..., start_samp:end_samp]
                    else:
                        # Pad with silence if no more segments
                        seg = torch.zeros((waveform.shape[0], waveform.shape[1], 1000), dtype=waveform.dtype, device=waveform.device) # 1000 samples of silence
                    
                    segments.append({"waveform": seg, "sample_rate": sample_rate})

            elif scene_samples > 0:
                # Path B: No timing data, but we have a fixed scene length
                print(f"[PromptCrafter_AudioSplitter] Splitting audio into fixed chunks of {scene_samples} samples.")
                
                offset_samples = set_index * scene_count * scene_samples
                
                for i in range(scene_count):
                    start_samp = offset_samples + (i * scene_samples)
                    end_samp = start_samp + scene_samples
                    
                    # Clamp to audio boundaries
                    start_samp = max(0, start_samp)
                    end_samp = min(total_samples, end_samp)
                    
                    seg = waveform[..., start_samp:end_samp]
                    
                    # Pad segment with silence if it's short (e.g., end of audio)
                    current_len = seg.shape[-1]
                    if current_len < scene_samples and current_len > 0:
                        pad_len = scene_samples - current_len
                        pad = torch.zeros((seg.shape[0], seg.shape[1], pad_len), dtype=seg.dtype, device=seg.device)
                        seg = torch.cat([seg, pad], dim=-1)
                    elif current_len <= 0:
                        # Full silence if we're past the audio
                        seg = torch.zeros((waveform.shape[0], waveform.shape[1], scene_samples), dtype=waveform.dtype, device=waveform.device)

                    segments.append({"waveform": seg, "sample_rate": sample_rate})
            
            else:
                # Path C: Fallback (e.g., "Structural Tag" with no timing)
                # This is less ideal, but provides a fallback.
                print(f"[PromptCrafter_AudioSplitter] Warning: No timing data. Splitting audio evenly across {total_duration_sec}s.")
                total_scenes_approx = max(1, len(audio_meta.get("timed_segments", []))) # A guess
                if total_scenes_approx <= 1: total_scenes_approx = int(total_duration_sec / 5.0) # 5s guess
                
                scene_samples = int(total_samples / max(1, total_scenes_approx))
                # Now run the logic from Path B with this guess
                offset_samples = set_index * scene_count * scene_samples
                for i in range(scene_count):
                    start_samp = offset_samples + (i * scene_samples)
                    end_samp = start_samp + scene_samples
                    start_samp = max(0, min(total_samples -1, start_samp))
                    end_samp = max(0, min(total_samples, end_samp))
                    seg = waveform[..., start_samp:end_samp]
                    segments.append({"waveform": seg, "sample_rate": sample_rate})
            
            # Ensure we always return 16 outputs
            if len(segments) < scene_count:
                silence_samples = scene_samples if scene_samples > 0 else int(sample_rate * 4.0) # 4s silence
                silence = torch.zeros((waveform.shape[0], waveform.shape[1], silence_samples), dtype=waveform.dtype, device=waveform.device)
                for _ in range(scene_count - len(segments)):
                    segments.append({"waveform": silence, "sample_rate": sample_rate})
            
            return tuple(segments)

        except Exception as e:
            # On failure, return 16 Nones
            print(f"\033[91m[PromptCrafter_AudioSplitter] Error: {e}\033[0m")
            import traceback
            traceback.print_exc()
            return (None,) * 16

# ------------------------------------------------------------------------------------
# PromptCrafter_Formatter Node (Enhanced)
# ------------------------------------------------------------------------------------
class PromptCrafter_Formatter:
    DESCRIPTION = "Formats prompts or schedules. Can apply templates or add prefixes/suffixes to individual prompts or all keyframes in a schedule."
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["Build from Template", "Edit Single Prompt", "Bulk Edit Schedule"], {"default": "Build from Template", "tooltip": "Choose the formatting operation."}),
            },
            "optional": {
                "prompt_in": ("STRING", {"multiline": True, "default": "", "tooltip": "The main prompt string to format."}),
                "schedule_in": ("STRING", {"multiline": True, "default": "", "tooltip": "The schedule JSON string to format."}),
                
                # For "Simple Template" mode
                "template_text": ("STRING", {"multiline": True, "default": "A high-quality photo of {a}, in the style of {b}.", "tooltip": "Template for 'Simple Template' mode. Use {a}, {b}, {prompt}, {schedule}, etc."}),
                "var_a": ("STRING", {"multiline": False, "default": "", "tooltip": "Replaces {a} in the template."}),
                "var_b": ("STRING", {"multiline": False, "default": "", "tooltip": "Replaces {b} in the template."}),
                "var_c": ("STRING", {"multiline": False, "default": "", "tooltip": "Replaces {c} in the template."}),
                "var_d": ("STRING", {"multiline": False, "default": "", "tooltip": "Replaces {d} in the template."}),

                # For "Apply to Prompt/Schedule" modes
                "prefix": ("STRING", {"multiline": False, "default": "", "tooltip": "Text to add to the beginning of the prompt(s)."}),
                "suffix": ("STRING", {"multiline": False, "default": "", "tooltip": "Text to add to the end of the prompt(s)."}),
                "find_text": ("STRING", {"multiline": False, "default": "", "tooltip": "Text to find (case-sensitive)."}),
                "replace_with": ("STRING", {"multiline": False, "default": "", "tooltip": "Text to replace with."}),
                "output_target": (text_io.OUTPUT_TARGET_OPTIONS, {"default": "Prompt", "tooltip": "Which output(s) to format."}),
                "output_format": (text_io.FORMAT_OPTIONS, {"default": "Plain Text", "tooltip": "Format to apply to the selected output(s)."}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("formatted_prompt", "formatted_schedule")
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Utils"

    def _format_text(self, text, prefix, suffix, find_text, replace_with):
        """Helper function to apply formatting rules to a single text string."""
        
        # 1. Start with the core text
        processed_text = text if text else ""
        
        # 2. Find/Replace
        if find_text:
            processed_text = processed_text.replace(find_text, replace_with)
        
        # 3. Add Prefix/Suffix
        # Use a list to join non-empty parts, avoiding comma/space issues
        parts = []
        if prefix:
            parts.append(prefix.strip())
        if processed_text:
            parts.append(processed_text)
        if suffix:
            parts.append(suffix.strip())
            
        # Join with ", " only if multiple parts exist
        return ", ".join(parts)

    def execute(self, mode, prompt_in="", schedule_in="", template_text="", var_a="", var_b="", var_c="", var_d="", prefix="", suffix="", find_text="", replace_with="", output_target="Prompt", output_format="Plain Text"):
        
        out_prompt = prompt_in
        out_schedule = schedule_in

        if mode == "Build from Template":
            placeholders = {
                "{a}": str(var_a),
                "{b}": str(var_b),
                "{c}": str(var_c),
                "{d}": str(var_d),
                "{prompt}": str(prompt_in),
                "{schedule}": str(schedule_in),
            }
            formatted_text = template_text
            for placeholder, value in placeholders.items():
                formatted_text = formatted_text.replace(placeholder, value)
            
            # In this mode, the main output is the formatted template text.
            out_prompt = formatted_text
            # Pass the original schedule through unchanged
            out_schedule = schedule_in 
        
        elif mode == "Edit Single Prompt":
            out_prompt = self._format_text(prompt_in, prefix, suffix, find_text, replace_with)
            # Pass schedule through unchanged
            out_schedule = schedule_in

        elif mode == "Bulk Edit Schedule":
            if not schedule_in:
                return (prompt_in, "") # Pass prompt, return empty schedule
            
            try:
                schedule_data = json_utils.extract_and_parse_json(schedule_in) or {}
                
                if not isinstance(schedule_data, dict):
                    raise ValueError("schedule_in is not a JSON object")

                new_schedule = {}
                # Iterate through the schedule (which is a dict of "frame": "prompt")
                for frame, prompt_text in schedule_data.items():
                    # Apply the same formatting rules to each prompt
                    new_schedule[frame] = self._format_text(prompt_text, prefix, suffix, find_text, replace_with)
                
                # Re-serialize the schedule to a string
                out_schedule = json.dumps(new_schedule, indent=4)
                # Pass prompt through unchanged
                out_prompt = prompt_in
            
            except json.JSONDecodeError:
                error_msg = "[PromptCrafter Formatter] Error: schedule_in is not valid JSON. Cannot apply to schedule."
                print(f"\033[91m{error_msg}\033[0m")
                out_prompt = error_msg # Output error to prompt string
                out_schedule = schedule_in # Pass through the broken schedule
            except Exception as e:
                error_msg = f"[PromptCrafter Formatter] Error processing schedule: {e}"
                print(f"\033[91m{error_msg}\033[0m")
                out_prompt = error_msg
                out_schedule = schedule_in

        if output_target in ("Prompt", "Both"):
            out_prompt = text_io.format_text_payload(out_prompt, output_format, label="prompt")
        if output_target in ("Schedule", "Both"):
            formatted_schedule, schedule_err = text_io.format_schedule_text(out_schedule, output_format)
            if schedule_err:
                print(f"\033[91m[PromptCrafter Formatter] {schedule_err}\033[0m")
            else:
                out_schedule = formatted_schedule

        return (out_prompt, out_schedule)

# ------------------------------------------------------------------------------------
# PromptCrafter_SaveTextFile Node
# ------------------------------------------------------------------------------------
class PromptCrafter_SaveTextFile:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text_to_save": ("STRING", {"multiline": True}),
                "folder_path": ("STRING", {"default": "ComfyUI/output/PromptCrafter"}),
                "filename_template": ("STRING", {"default": "{seed}_{model_name}.txt"}),
            },
            "optional": {
                "model_name": ("STRING", {"multiline": False, "default": ""}),
                "seed": ("STRING", {"multiline": False, "default": ""}),
                "user_text": ("STRING", {"multiline": False, "default": ""}),
                "custom_var": ("STRING", {"multiline": False, "default": ""}),
                "file_type": (text_io.FILE_TYPE_OPTIONS, {"default": "txt", "tooltip": "File extension to use."}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("save_status",)
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Utils"

    def execute(self, text_to_save, folder_path, filename_template, model_name="", seed="", user_text="", custom_var="", file_type="txt"):
        replacements = {
            "model_name": model_name,
            "seed": seed,
            "user_text": user_text,
            "custom_var": custom_var,
        }

        filename = text_io.resolve_filename_template(filename_template, replacements)
        filename = utils.TextCleaner.sanitize_filename(filename)
        filename = text_io.ensure_extension(filename, file_type)

        # Ensure the directory exists
        os.makedirs(folder_path, exist_ok=True)

        # Prevent overwrites by generating a unique filename
        base_name, ext = os.path.splitext(filename)
        out_dir = os.path.abspath(folder_path)
        full_path, _ = utils._get_unique_filepath(out_dir, base_name, ext)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write("" if text_to_save is None else str(text_to_save))

        return (f"Saved to {full_path}",)

# ------------------------------------------------------------------------------------
# PromptCrafter_FileOrganizer Node
# ------------------------------------------------------------------------------------
class PromptCrafter_FileOrganizer:
    DESCRIPTION = get_node_description("PromptCrafter_FileOrganizer")
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (api_clients.get_all_models(), {"tooltip": "The language model to use for all analysis and generation. Vision-capable models are required if using images."} ),
                "input_folder": ("STRING", {"default": "output/unorganized", "tooltip": "The folder containing the files you want to organize (relative to ComfyUI root)."}),
                "output_folder": ("STRING", {"default": "output/organized", "tooltip": "The root folder where organized subdirectories will be created (relative to ComfyUI root)."}),
                "organization_profile": (organization_profiles.get_organization_profile_options(), {"default": "None (Manual Scheme)", "tooltip": "Select a pre-configured organization scheme. Overrides the manual scheme text box."}),
                "organization_scheme": ("STRING", {
                    "multiline": True,
                    "default": "# Define rules, one per line. The first match will be used.\n# Format: CRITERION: VALUE -> FOLDER_NAME\n# Criteria: image_resolution, image_description_contains, captionfile_contains, filename_contains, metadata_contains, content_keyword\n\nimage_resolution: >1920x1080 -> High_Resolution/4K_ish\nimage_resolution: ==512x512 -> Square_Images/512x512\nimage_description_contains: cat -> By_Embedded_Caption/Cats\ncaptionfile_contains: dog -> By_Text_File/Dogs\nfilename_contains: car -> By_Filename/Cars\nmetadata_contains: AnimateDiff -> By_Workflow/Animations\ncontent_keyword: landscape -> By_VLM_Content/Landscapes",
                    "tooltip": "Rules for organizing files. 'image_resolution' checks dimensions (e.g., >1024x768). 'image_description_contains' reads embedded EXIF/PNG descriptions. 'captionfile_contains' reads .txt files. 'filename_contains' checks the filename. 'metadata_contains' checks the ComfyUI workflow."
                }),
                "action": (["Copy", "Move"], {"default": "Copy", "tooltip": "Copy files (safer) or move them to the new location."}),
                "dry_run": ("BOOLEAN", {"default": False, "tooltip": "Simulate the organization process and report actions without moving or copying files."}),
                "analysis_priority": (["Metadata First", "Content First", "Metadata Only"], {"default": "Metadata First", "tooltip": "The order of analysis. 'Metadata First' is fastest."}),
                "fallback_folder": ("STRING", {"default": "_unorganized", "tooltip": "Subfolder for files that do not match any rule."}),
                "auto_generate_scheme": ("BOOLEAN", {"default": False, "tooltip": "Automatically generate an organization scheme by analyzing a sample of files. Overrides the manual scheme."} ),
            },
            "optional": {
                "run_organization": ("BOOLEAN", {"default": False, "tooltip": "Toggle to True to start the organization process. It will run once per execution."}),
                "max_workers": ("INT", {"default": 4, "min": 1, "max": 16, "step": 1, "tooltip": "Number of parallel threads for processing files." }),
                "recursive": ("BOOLEAN", {"default": False, "tooltip": "Process files in all subdirectories of the input folder as well."}),
                "create_log_file": ("BOOLEAN", {"default": False, "tooltip": "Create a text log file summarizing all operations in the output folder."}),
                "log_filename": ("STRING", {"default": "organization_log.txt", "tooltip": "The name of the log file to be created in the output folder."}),
                "delete_source_folder_on_move": ("BOOLEAN", {"default": False, "tooltip": "After a successful 'Move' operation, delete the original input folder if it's empty. Use with caution."}),
                **_llm_runtime_optional_inputs(),
            }
        }
    
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("summary", "dry_run_plan", "generated_scheme_out")
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /Utils"
    OUTPUT_NODE = True

    def _read_metadata(self, image_path):
        """Safely reads PNG info metadata from an image file."""
        try:
            with Image.open(image_path) as img:
                if "prompt" in img.info and img.info["prompt"]:
                    return json.loads(img.info["prompt"])
                if "workflow" in img.info and img.info["workflow"]:
                    workflow_data = img.info["workflow"]
                    return json.loads(workflow_data)
        except (json.JSONDecodeError, IOError, TypeError, KeyError, AttributeError):
            return None
        return None

    def _check_resolution_rule(self, image_size, rule_value):
        """Parses a resolution rule and checks if the image size matches."""
        # image_size is a tuple (width, height)
        # rule_value is a string like ">1024x768" or "==512x512"
        match = re.match(r"([<>=!]{1,2})\s*(\d+)[xX](\d+)", rule_value.strip())
        if not match:
            return False

        op, target_w_str, target_h_str = match.groups()
        img_w, img_h = image_size
        target_w, target_h = int(target_w_str), int(target_h_str)

        # Define a mapping from operator string to a lambda function
        ops = {
            ">": lambda a, b: a > b,
            "<": lambda a, b: a < b,
            ">=": lambda a, b: a >= b,
            "<=": lambda a, b: a <= b,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
        }

        op_func = ops.get(op)
        if not op_func:
            return False

        # The rule matches if BOTH width and height satisfy the condition
        return op_func(img_w, target_w) and op_func(img_h, target_h)

    def _recursively_find_value(self, data, search_value, case_sensitive=False):
        """Iteratively search for a value within a nested dict/list structure."""
        stack = collections.deque([data])
        if not isinstance(search_value, str):
            return False
        search_key = search_value if case_sensitive else search_value.lower()

        while stack:
            current_item = stack.pop()
            if isinstance(current_item, dict):
                stack.extend(current_item.values())
            elif isinstance(current_item, list):
                stack.extend(current_item)
            elif isinstance(current_item, str):
                current_val = current_item if case_sensitive else current_item.lower()
                if search_key in current_val:
                    return True
        return False

    def _get_target_for_file(self, file_path, rules, vision_model, analysis_priority, file_info_cache, llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS):
        """Analyzes a single file and returns the target subfolder name."""
        base_name, _ = os.path.splitext(os.path.basename(file_path))
        file_info = file_info_cache.get(file_path, {})
        # --- Resolution Analysis (perform once if needed) ---
        image_size = None
        has_resolution_rules = any(r[0] == 'image_resolution' for r in rules)

        if has_resolution_rules and file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            try:
                with Image.open(file_path) as img:
                    image_size = img.size
                for criterion, value, folder in rules:
                    if criterion == "image_resolution" and self._check_resolution_rule(image_size, value):
                        return folder
            except Exception: pass # Fail silently if image is not readable

        # --- File-based Analysis (Filename and Caption File) ---
        if analysis_priority != "Content First":
            # 1. Check filename
            for criterion, value, folder in rules:
                if criterion == "filename_contains":
                    if value.lower() in base_name.lower():
                        return folder
            
            # 2. Check for embedded image description (PNG Description or EXIF UserComment)
            image_description = file_info.get("image_description")
            if image_description:
                for criterion, value, folder in rules:
                    if criterion == "image_description_contains" and value.lower() in image_description.lower():
                        return folder

            # 3. Check for and read companion caption file (.txt)
            caption_content = file_info.get("caption_content")
            if caption_content:
                for criterion, value, folder in rules:
                    if criterion == "captionfile_contains" and value.lower() in caption_content.lower():
                        return folder

        # --- Embedded ComfyUI Workflow Metadata Analysis ---
        if analysis_priority != "Content First":
            metadata = file_info.get("metadata")
            if metadata:
                for criterion, value, folder in rules:
                    if criterion == "metadata_contains":
                        if self._recursively_find_value(metadata, value, case_sensitive=False):
                            return folder
                    elif criterion == "prompt_keyword":
                        for node in metadata.get("nodes", []):
                            if node.get("type") in ["CLIPTextEncode", "KSampler"]:
                                if self._recursively_find_value(node.get("properties", {}), value):
                                    return folder
            if analysis_priority == "Metadata Only":
                return None # Stop here if only metadata analysis is requested

        # --- Content Analysis (VLM) ---
        if vision_model and any(r[0] == 'content_keyword' for r in rules):
            try:
                pil_image = Image.open(file_path).convert("RGB")
                image_tensor = utils.pil2tensor(pil_image)
                
                prompt = "Describe this image in a few keywords. Focus on the main subject, style, and setting. Example: 'photo, car, city street, nighttime'"
                ok, caption = api_clients.query_model_auto(
                    vision_model,
                    prompt=prompt,
                    images=[image_tensor[0]],
                    prefer_chat=True,
                    temperature=0.1,
                    seed=1,
                    timeout=60,
                    llm_device=llm_device,
                    reset_context=reset_context,
                )
                
                if ok:
                    for criterion, value, folder in rules:
                        if criterion == "content_keyword" and value.lower() in caption.lower():
                            return folder
            except Exception as e:
                print(f"\033[93m[FileOrganizer] Warning: Content analysis failed for {os.path.basename(file_path)}: {e}\033[0m")

        return None

    def _generate_scheme_with_ai(self, file_groups, model, max_workers, llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS, debug_mode=False):
        """Analyzes a sample of files and uses an LLM to generate an organization scheme."""
        print(f"\033[94m[FileOrganizer] Auto-generating organization scheme by analyzing a sample of files...\033[0m")
        
        # Take a sample of up to 15 file groups to analyze
        sample_groups = file_groups[:15]
        file_profiles = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_profile = {
                executor.submit(self._summarize_file_for_scheme, self._get_representative_file(group)): group
                for group in sample_groups
            }
            for future in concurrent.futures.as_completed(future_to_profile):
                profile = future.result()
                if profile:
                    file_profiles.append(profile)

        if not file_profiles:
            return None, "Could not generate summaries for any sample files. Unable to create a scheme."

        # Convert the list of profile dicts into a nicely formatted JSON string for the prompt
        profiles_json_text = json.dumps(file_profiles, indent=2)
        
        prompt = textwrap.dedent(f"""
            You are an expert data analyst and file organization assistant. Your task is to create a logical organization scheme based on a sample of file profiles.

            **Available Rule Criteria & Syntax:**
            - `image_resolution`: Checks image dimensions. Use operators `=`, `>`, `<`. Example: `image_resolution: >1024x1024 -> High_Resolution`
            - `image_description_contains`: Checks embedded metadata (EXIF/PNG). Most reliable for content. Example: `image_description_contains: cat -> By_Subject/Cats`
            - `captionfile_contains`: Checks an associated `.txt` file. Example: `captionfile_contains: dog -> By_Text_File/Dogs`
            - `filename_contains`: Checks the file's name. Good for types like 'screenshot'. Example: `filename_contains: screenshot -> By_Type/Screenshots`

            --- FILE PROFILES (Sample Data) ---
            {profiles_json_text}
            ---

            INSTRUCTIONS:
            1.  **Analyze & Correlate:** Read all file profiles. Identify common themes, subjects, styles, AND image resolutions.
            2.  **Select Best Criterion:** For each theme you identify, determine the BEST rule criterion to use.
                - If you see common resolutions (e.g., many `512x512` images), create an `image_resolution` rule.
                - For content themes, prefer `image_description_contains` if available, otherwise use `captionfile_contains`.
            3.  **Create Rules:** Generate 5-10 powerful rules based on your analysis. The format is `criterion: keyword -> Folder/Subfolder`.
            4.  **Be Smart:** Create logical, hierarchical folder structures (e.g., `By_Style/Anime`, `By_Subject/Cats`). Use lowercase keywords.
            5.  **Prioritize:** Focus on rules that will categorize the most files.

            Return ONLY the rules, one per line. Do not include commentary or code blocks.

            Example Output:
            image_resolution: ==512x512 -> By_Resolution/Square_512
            image_description_contains: cat -> By_Subject/Cats
            image_description_contains: dog -> By_Subject/Dogs
            captionfile_contains: cyberpunk -> By_Theme/Cyberpunk
            filename_contains: screenshot -> By_Type/Screenshots
        """).strip()

        ok, scheme = api_clients.query_model_auto(
            model,
            prompt,
            prefer_chat=True,
            temperature=0.1,
            seed=1,
            timeout=120,
            debug_mode=debug_mode,
            debug_title="Auto-Generate Scheme",
            llm_device=llm_device,
            reset_context=reset_context,
        )
        return (scheme, None) if ok else (None, f"AI scheme generation failed: {scheme}")

    def _group_files_by_basename(self, directory, extensions, recursive=False):
        """
        Groups files in a directory by their base name, ensuring associated files (like image.png and image.txt) are processed together.
        Can optionally process subdirectories recursively.
        """
        initial_groups = collections.defaultdict(list)
        
        if recursive:
            for root, _, files in os.walk(directory):
                for f in files:
                    if f.lower().endswith(extensions):
                        full_path = os.path.join(root, f)
                        base_name_path, _ = os.path.splitext(full_path)
                        initial_groups[base_name_path].append(full_path)
        else:
            for f in os.listdir(directory):
                if f.lower().endswith(extensions) and os.path.isfile(os.path.join(directory, f)):
                    base_name_path, _ = os.path.splitext(os.path.join(directory, f))
                    initial_groups[base_name_path].append(os.path.join(directory, f))

        return list(initial_groups.values())

    def _get_representative_file(self, file_group):
        """
        Selects the best file from a group for analysis (prefers PNGs for metadata, then other images).
        """
        image_files = [f for f in file_group if f.lower().endswith(('.png', '.jpg', '.jpeg', '.webp'))]
        png_files = [f for f in image_files if f.lower().endswith('.png')]
        
        if png_files: return png_files[0]
        if image_files: return image_files[0]
        return file_group[0] if file_group else None

    def _process_file_group(self, file_group, rules, vision_model, analysis_priority, fallback_folder, full_input_path, full_output_path, action, file_info_cache, dry_run=False, create_log_file=False, llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS):
        """
        Determines the target folder for a group of files and performs the move/copy action.
        This function is designed to be run in a thread pool.
        Returns a tuple: (status, processed_count, log_messages)
        """
        if not file_group:
            return "skipped_empty", 0, []

        representative_file = self._get_representative_file(file_group) # noqa
        target_subfolder = self._get_target_for_file(
            representative_file,
            rules,
            vision_model,
            analysis_priority,
            file_info_cache,
            llm_device=llm_device,
            reset_context=reset_context,
        )
        
        if target_subfolder is None:
            target_subfolder = fallback_folder
        
        dest_dir = os.path.join(full_output_path, target_subfolder)

        if not dry_run:
            # This check is important for thread safety.
            if not os.path.isdir(dest_dir):
                try:
                    os.makedirs(dest_dir, exist_ok=True)
                except OSError as e:
                    # Handles race condition where another thread creates the directory between the check and the call.
                    if not os.path.isdir(dest_dir):
                        raise e

        processed_count = 0
        log_messages = []
        for file_path in file_group:
            if not os.path.exists(file_path): continue
            
            dest_path = os.path.join(dest_dir, os.path.basename(file_path))
            
            if os.path.abspath(file_path) == os.path.abspath(dest_path):
                continue

            if dry_run:
                action_verb = "MOVE" if action == "Move" else "COPY"
                relative_file_path = os.path.relpath(file_path, full_input_path)
                log_msg = f"[Dry Run] Would {action_verb} '{relative_file_path}' to '{os.path.relpath(dest_dir, full_output_path)}'"
                print(f"\033[96m{log_msg}\033[0m")
                if create_log_file: log_messages.append(log_msg)
                processed_count += 1
            else:
                try:
                    if action == "Move":
                        shutil.move(file_path, dest_path)
                    else: # Copy
                        shutil.copy2(file_path, dest_path)
                    if create_log_file:
                        action_verb_past = "Moved" if action == "Move" else "Copied"
                        log_messages.append(f"OK: {action_verb_past} '{os.path.relpath(file_path, full_input_path)}' to '{os.path.relpath(dest_dir, full_output_path)}'")
                    processed_count += 1
                except FileExistsError:
                    # This is an expected outcome if the file is already there.
                    continue
                except Exception as e:
                    # Catch other potential errors during file operation.
                    print(f"\033[91m[FileOrganizer] Error processing file {file_path}: {e}\033[0m")
                    if create_log_file: log_messages.append(f"FAIL: Error processing '{os.path.relpath(file_path, full_input_path)}': {e}")
                    return "failed", 0, log_messages

        status = "moved" if action == "Move" else "copied"
        return status, processed_count, log_messages

    def _summarize_file_for_scheme(self, file_path):
        """Generates a structured summary of a file's text-based metadata for scheme generation."""
        if not file_path:
            return None

        profile = {
            "filename": os.path.basename(file_path),
            "image_resolution": None,
            "image_description": None,
            "caption_content": None,
        }

        # Read image resolution if it's an image file
        if file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
            try:
                with Image.open(file_path) as img:
                    profile["image_resolution"] = f"{img.width}x{img.height}"
            except Exception:
                pass # Fail silently if image is unreadable

        # Read embedded image description (from EXIF/PNG)
        image_description = utils._read_image_description(file_path)
        if image_description:
            profile["image_description"] = image_description.strip()

        # Read companion .txt file
        caption_path = os.path.splitext(file_path)[0] + ".txt"
        if os.path.exists(caption_path):
            try:
                with open(caption_path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                    if content:
                        profile["caption_content"] = content
            except Exception:
                pass
        return profile

    def execute(self, model, input_folder, output_folder, organization_profile, organization_scheme, action, dry_run, analysis_priority, fallback_folder, auto_generate_scheme=False, run_organization=False, max_workers=4, recursive=False, create_log_file=False, log_filename="organization_log.txt", delete_source_folder_on_move=False, llm_device=config.DEFAULT_LLM_DEVICE, reset_context=config.DEFAULT_LLM_STATELESS, **kwargs):
        if not run_organization:
            return ("Organization not started. Set 'run_organization' to True.", "", "")

        full_input_path = utils._get_verified_path(input_folder, is_dir=True)
        if not full_input_path:
            return (f"Error: Input folder not found at '{input_folder}'.", "", "")
        
        full_output_path = utils._get_and_create_output_dir(output_folder)
        
        log_messages = []
        if create_log_file:
            log_messages.append(f"--- PromptCrafter File Organizer Log ---")
            log_messages.append(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            log_messages.append(f"Input Folder: {full_input_path}")
            log_messages.append(f"Output Folder: {full_output_path}")
            log_messages.append(f"Action: {action} | Recursive: {recursive}")
            log_messages.append("-" * 40)

        if dry_run:
            print("\033[96m[FileOrganizer] DRY RUN MODE ENABLED. No files will be moved or copied.\033[0m")
        
        supported_ext = ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.mp4', '.mov', '.txt')
        file_groups = self._group_files_by_basename(full_input_path, supported_ext, recursive=recursive)

        if not file_groups: return ("No supported files found in the input folder.", "", "")

        final_scheme = organization_scheme or ""  # Set empty string as default
        generated_scheme_out = ""
        if auto_generate_scheme:
            generated_scheme, error = self._generate_scheme_with_ai(
                file_groups,
                model,
                max_workers,
                llm_device=llm_device,
                reset_context=reset_context,
                debug_mode=kwargs.get("debug_mode", False),
            )
            if error:
                return (f"Error during auto-scheme generation: {error}", "", "")
            # Ensure we never assign None to final_scheme
            final_scheme = generated_scheme or ""
            print(f"\033[92m[FileOrganizer] Using auto-generated scheme:\n{final_scheme}\033[0m")
        elif organization_profile != "None (Manual Scheme)":
            profile = organization_profiles.NAMED_ORGANIZATION_PROFILES.get(organization_profile)
            if profile and "scheme" in profile:
                # Use .get and default to empty string to avoid None
                final_scheme = profile.get("scheme", "") or ""
                print(f"\033[92m[FileOrganizer] Using scheme from profile: '{organization_profile}'\033[0m")

        generated_scheme_out = final_scheme if auto_generate_scheme else ""
        rules = []
        for line in final_scheme.splitlines():
            line = line.strip()
            if line.startswith("#") or "->" not in line: continue
            try:
                condition, folder = line.split("->")
                criterion, value = condition.split(":", 1)
                rules.append((criterion.strip(), value.strip(), folder.strip()))
            except ValueError:
                print(f"\033[93m[FileOrganizer] Warning: Skipping invalid rule: {line}\033[0m")
        
        if not rules: return ("Error: No valid organization rules were defined.", "", generated_scheme_out)

        counts = collections.Counter()
        total_files_processed = 0
        all_op_logs = []

        # Pre-cache file info in parallel to avoid redundant reads later
        file_info_cache = {}
        print(f"\033[94m[FileOrganizer] Pre-analyzing {len(file_groups)} file groups in parallel...\033[0m")
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_rep_file = {
                executor.submit(self._summarize_file_for_scheme, self._get_representative_file(group)): self._get_representative_file(group)
                for group in file_groups if self._get_representative_file(group)
            }

            for future in concurrent.futures.as_completed(future_to_rep_file):
                rep_file = future_to_rep_file[future]
                try:
                    summary = future.result()
                    if summary:
                        file_info_cache[rep_file] = summary
                except Exception as e:
                    print(f"\033[93m[FileOrganizer] Warning: Could not pre-analyze file {os.path.basename(rep_file)}: {e}\033[0m")

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Create a future for each file group
            future_to_group = {
                executor.submit(
                    self._process_file_group,
                    group,
                    rules,
                    model,
                    analysis_priority,
                    fallback_folder,
                    full_input_path,
                    full_output_path,
                    action,
                    file_info_cache,
                    dry_run,
                    create_log_file,
                    llm_device,
                    reset_context,
                ): group
                for group in file_groups
            }

            completed_count = 0
            for future in concurrent.futures.as_completed(future_to_group):
                completed_count += 1
                print(f"\033[92m[FileOrganizer] Processing... ({completed_count}/{len(file_groups)})\033[0m", end='\r')
                group = future_to_group[future]
                try:
                    status, num_processed, op_logs = future.result()
                    if op_logs: all_op_logs.extend(op_logs)
                    counts[status] += num_processed
                    total_files_processed += num_processed
                except Exception as e:
                    counts["failed"] += len(group)
                    print(f"\033[91m[FileOrganizer] Error processing group for {os.path.basename(group[0])}: {e}\033[0m")
        print("\n\033[92m[FileOrganizer] Processing complete.\033[0m")

        total_groups = len(file_groups)
        summary_prefix = "Dry Run Complete!" if dry_run else "Organization Complete!"
        summary = f"{summary_prefix} Processed {total_files_processed} files across {total_groups} groups.\n"
        if dry_run:
            summary += f"Actions that would be taken:\n"

        if counts['copied'] > 0: summary += f"- Copied: {counts['copied']} files\n"
        if counts['moved'] > 0: summary += f"- Moved: {counts['moved']} files\n"
        if counts['failed'] > 0: summary += f"- Failed: {counts['failed']} files\n"
        summary = summary.strip()

        # --- Delete source folder if requested and conditions are met ---
        if delete_source_folder_on_move and not recursive and action == "Move" and not dry_run and counts['failed'] == 0 and counts['moved'] > 0:
            try:
                # Safety check: only delete if the folder is now empty.
                if not os.listdir(full_input_path):
                    shutil.rmtree(full_input_path)
                    delete_msg = f"\nSuccessfully deleted empty source folder: {input_folder}"
                    print(f"\033[92m[FileOrganizer]{delete_msg}\033[0m")
                    summary += delete_msg.strip()
                else:
                    delete_msg = f"\nSource folder '{input_folder}' was not deleted because it is not empty after the move operation."
                    print(f"\033[93m[FileOrganizer] Warning:{delete_msg}\033[0m")
                    summary += delete_msg.strip()
            except Exception as e:
                delete_msg = f"\nError deleting source folder '{input_folder}': {e}"
                print(f"\033[91m[FileOrganizer]{delete_msg}\033[0m")
                summary += delete_msg.strip()
        elif delete_source_folder_on_move and recursive:
            delete_msg = "\n'delete_source_folder_on_move' is disabled when 'recursive' is enabled to prevent accidental deletion of parent folders."
            print(f"\033[93m[FileOrganizer] Info:{delete_msg}\033[0m")
            summary += delete_msg.strip()

        if create_log_file:
            log_messages.extend(sorted(all_op_logs))
            log_messages.append("-" * 40)
            log_messages.append(summary.replace('\n', '\n' + ' ' * 4)) # Indent summary for readability
            
            # Ensure full_output_path is a valid string (utils._get_and_create_output_dir may return None on failure)
            if not full_output_path:
                try:
                    os.makedirs(output_folder, exist_ok=True)
                    full_output_path = os.path.abspath(output_folder)
                except Exception:
                    # Fallback to current working directory if we cannot create the requested folder
                    full_output_path = os.getcwd()

            log_file_path = os.path.join(full_output_path, log_filename)
            try:
                with open(log_file_path, "w", encoding="utf-8") as f:
                    f.write("\n".join(log_messages))
                print(f"\033[92m[FileOrganizer] Operation log saved to: {log_file_path}\033[0m")
            except Exception as e:
                print(f"\033[91m[FileOrganizer] Error writing log file: {e}\033[0m")

        dry_run_plan_str = "\n".join(sorted(all_op_logs)) if dry_run else ""

        return (summary, dry_run_plan_str, generated_scheme_out)

# ------------------------------------------------------------------------------------
# PromptCrafter_CacheUtility Node
# ------------------------------------------------------------------------------------
class PromptCrafter_CacheUtility:
    DESCRIPTION = get_node_description("PromptCrafter_CacheUtility")
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"action": (["Clear Cache", "Check Size"], {"default": "Clear Cache"})}}
    INPUT_IS_CHANGED = "ALWAYS"

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status",)
    FUNCTION = "execute"
    CATEGORY = f"☠️PGFX🏴‍☠️ /Utils"

    def execute(self, action):
        if action == "Clear Cache":
            removed_count = config.CACHE.clear()
            status_message = f"Cache cleared. Removed {removed_count} items."
            print(f"\033[92m[PromptCrafter] {status_message}\033[0m")
        else:
            status_message = f"Cache contains {config.CACHE.size} of {config.CACHE.max_size} items."
        return (status_message,)

# ------------------------------------------------------------------------------------
# PromptCrafter_ImageSwitcher Node
# ------------------------------------------------------------------------------------
# In nodes.py, locate and replace the PromptCrafter_ImageSwitcher class:

class PromptCrafter_ImageSwitcher:
    DESCRIPTION = "Switches between multiple image inputs based on an index or randomly, triggered by a signal."
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                # NEW: Switching mode selector
                "image_count": ("INT", {"default": 2, "min": 2, "max": 16, "step": 1, "tooltip": "The number of image input pins to generate. Use the 'Manual Refresh' button to apply changes."}),
                "switching_mode": (["Chronological (Index)", "Random Select"], {"default": "Chronological (Index)", "tooltip": "Method to choose the image: incremental using the index or pure random selection."}),
                "signal": ("*", {"optional": True, "tooltip": "A signal from another node to force execution/switching."}),
            },
            "optional": {
                # Input for the chronological mode
                "current_index": ("INT", {"default": 0, "min": 0, "max": 1000, "step": 1, "tooltip": "The 0-based index of the image to select (only used in Chronological mode)."}),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT")
    RETURN_NAMES = ("selected_image", "selected_index")
    FUNCTION = "switch_image"
    CATEGORY = "☠️PGFX🏴‍☠️ /Utils"

    def switch_image(self, switching_mode, image_count, current_index=0, signal=None, **kwargs):
        images = []
        
        # 1. Collect all connected dynamic image inputs based on image_count
        for i in range(1, image_count + 1):
            key = f"image_{i}"
            # Only append the image tensor if the pin exists and is connected
            if key in kwargs and kwargs[key] is not None:
                images.append(kwargs[key])
        
        if not images:
            raise ValueError("PromptCrafter_ImageSwitcher: No images were provided or connected to the dynamic pins.")

        num_images = len(images)
        selected_index = 0

        # 2. Implement switching logic based on mode
        if switching_mode == "Chronological (Index)":
            # Use the user's index (clamped to prevent out-of-bounds error)
            selected_index = max(0, min(num_images - 1, current_index))
        
        elif switching_mode == "Random Select":
            # Select a random index from the connected images (0 to num_images - 1)
            selected_index = random.randint(0, num_images - 1)
        
        # 3. Return the selected image and the index used
        selected_image = images[selected_index]
        return (selected_image, selected_index)

# ------------------------------------------------------------------------------------
# PromptCrafter_PromptChunker Node
# ------------------------------------------------------------------------------------
class PromptCrafter_PromptChunker:
    DESCRIPTION = "Splits a delimited string (e.g., from a VRGDG-compatible LyricsCreator) into multiple outputs for distribution in a workflow."
    
    MAX_OUTPUTS = 50

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "pipe_separated_prompts": ("STRING", {"multiline": True, "default": ""}),
                "scene_count": ("INT", {"default": 16, "min": 1, "max": cls.MAX_OUTPUTS}),
                "delimiter": ("STRING", {"default": "|"}),
            }
        }

    FUNCTION = "execute"
    CATEGORY = "☠️PGFX🏴‍☠️ /Utils"

    RETURN_TYPES = tuple(["STRING"] * MAX_OUTPUTS)
    RETURN_NAMES = tuple(f"prompt_scene_{i+1}" for i in range(MAX_OUTPUTS))

    @classmethod
    def IS_DYNAMIC(cls):
        return True

    @classmethod
    def get_output_types(cls, **kwargs):
        scene_count = int(kwargs.get("scene_count", 16))
        return tuple(["STRING"] * scene_count)

    @classmethod
    def get_output_names(cls, **kwargs):
        scene_count = int(kwargs.get("scene_count", 16))
        return tuple(f"prompt_scene_{i+1}" for i in range(scene_count))

    def execute(self, pipe_separated_prompts, scene_count, delimiter="|"):
        prompts = [p.strip() for p in pipe_separated_prompts.split(delimiter)]
        
        output_prompts = []
        for i in range(scene_count):
            if i < len(prompts):
                output_prompts.append(prompts[i])
            else:
                output_prompts.append("")
        
        return tuple(output_prompts)

NODE_CLASS_MAPPINGS = {
    "PromptCrafter_QnA": PromptCrafter_QnA_Simple,
    "PromptCrafter_QnA_Advanced": PromptCrafter_QnA,
    "PromptCrafter_QnA_Simple": PromptCrafter_QnA_Simple,
    "PromptCrafter_LyricsThink": PromptCrafter_LyricsThink,
    "PromptCrafter_LyricsInstruct": PromptCrafter_LyricsInstruct,
    "PromptCrafter_VisualThink": PromptCrafter_VisualThink,
    "PromptCrafter_VisualInstruct": PromptCrafter_VisualInstruct,
    "PromptCrafter_QnAThink": PromptCrafter_QnAThink,
    "PromptCrafter_QnAInstruct": PromptCrafter_QnAInstruct,
    "PromptCrafter_Captioner": PromptCrafter_Captioner,
    "PromptCrafter_AudioSplitter": PromptCrafter_AudioSplitter,
    "PromptCrafter_CacheUtility": PromptCrafter_CacheUtility,
    "PromptCrafter_FileOrganizer": PromptCrafter_FileOrganizer,
    "PromptCrafter_Formatter": PromptCrafter_Formatter,
    "PromptCrafter_SaveTextFile": PromptCrafter_SaveTextFile,
    "PromptCrafter_ImageSwitcher": PromptCrafter_ImageSwitcher,
    "PromptCrafter_PromptChunker": PromptCrafter_PromptChunker,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_QnA": "💬 QnA",
    "PromptCrafter_QnA_Advanced": "💬 QnA (Advanced)",
    "PromptCrafter_QnA_Simple": "💬 QnA (Simple)",
    "PromptCrafter_LyricsThink": "🧠 Lyrics Think",
    "PromptCrafter_LyricsInstruct": "✍️ Lyrics Instruct",
    "PromptCrafter_VisualThink": "🧠 Visual Think",
    "PromptCrafter_VisualInstruct": "✍️ Visual Instruct",
    "PromptCrafter_QnAThink": "🧠 QnA Think",
    "PromptCrafter_QnAInstruct": "✍️ QnA Instruct",
    "PromptCrafter_Captioner": "🖼️ Image Captioner",
    "PromptCrafter_VisualCreator": "✨ Visual Creator",
    "PromptCrafter_SRTCreator": "📝 SRT Creator",
    "PromptCrafter_LyricsCreator": "🎤 Lyrics Creator",
    "PromptCrafter_AudioSplitter_v2": "🎤 Audio Splitter v2",
    "PromptCrafter_AudioSplitter": "🎤 Audio Splitter",
    "PromptCrafter_CacheUtility": "🧹 Cache Utility",
    "PromptCrafter_FileOrganizer": "🗂️ File Organizer",
    "PromptCrafter_Formatter": "📝 Text Formatter",
    "PromptCrafter_SaveTextFile": "💾 Save Text File",
    "PromptCrafter_ImageSwitcher": "🔀 Image Switcher",
    "PromptCrafter_PromptChunker": "🧩 Prompt Chunker",
}

