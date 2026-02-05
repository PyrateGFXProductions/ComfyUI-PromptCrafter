# Standard library imports
import os
import io
import json
import csv

# Local module imports
from . import pgfx_json_utils as json_utils
from . import pgfx_utils as utils

FILE_TYPE_OPTIONS = ["txt", "json", "md", "yaml", "csv"]
FORMAT_OPTIONS = ["Plain Text", "JSON", "Markdown", "YAML", "CSV"]
OUTPUT_TARGET_OPTIONS = ["Prompt", "Schedule", "Both"]
QNA_OUTPUT_TARGET_OPTIONS = ["Response", "History", "Thinking", "Response + Thinking", "All"]
VISUAL_OUTPUT_TARGET_OPTIONS = ["Prompt", "Schedule", "Image Context", "Negative Prompt", "Prompt + Schedule", "All"]
LYRICS_OUTPUT_TARGET_OPTIONS = [
    "Prompt",
    "Schedule",
    "Image Context",
    "Negative Prompt",
    "Clean Lyrics",
    "Lyrics SRT",
    "Prompt + Schedule",
    "All",
]
AUTO_FILE_TYPE_OPTIONS = ["Match Output Format"] + FILE_TYPE_OPTIONS

_FORMAT_TO_FILE_TYPE = {
    "Plain Text": "txt",
    "JSON": "json",
    "Markdown": "md",
    "YAML": "yaml",
    "CSV": "csv",
}

_EXT_BY_TYPE = {
    "txt": ".txt",
    "json": ".json",
    "md": ".md",
    "yaml": ".yaml",
    "csv": ".csv",
}

CREATOR_FORMAT_PROFILE_OPTIONS = [
    "Custom",
    "Prompt -> Plain Text",
    "Prompt -> JSON",
    "Schedule -> JSON (Auto-save .json)",
    "Schedule -> CSV (Auto-save .csv)",
    "Schedule -> Markdown",
    "Prompt + Schedule -> JSON (Auto-save .json)",
]

CREATOR_FORMAT_PROFILES = {
    "Prompt -> Plain Text": {
        "output_target": "Prompt",
        "output_format": "Plain Text",
    },
    "Prompt -> JSON": {
        "output_target": "Prompt",
        "output_format": "JSON",
    },
    "Schedule -> JSON (Auto-save .json)": {
        "output_target": "Schedule",
        "output_format": "JSON",
        "auto_save": True,
        "auto_save_target": "Schedule",
        "auto_save_file_type": "json",
    },
    "Schedule -> CSV (Auto-save .csv)": {
        "output_target": "Schedule",
        "output_format": "CSV",
        "auto_save": True,
        "auto_save_target": "Schedule",
        "auto_save_file_type": "csv",
    },
    "Schedule -> Markdown": {
        "output_target": "Schedule",
        "output_format": "Markdown",
    },
    "Prompt + Schedule -> JSON (Auto-save .json)": {
        "output_target": "Prompt + Schedule",
        "output_format": "JSON",
        "auto_save": True,
        "auto_save_target": "Prompt + Schedule",
        "auto_save_file_type": "json",
    },
}

QNA_FORMAT_PROFILE_OPTIONS = [
    "Custom",
    "Response -> Plain Text",
    "Response -> JSON",
    "Response -> JSON (Auto-save .json)",
    "Response + Thinking -> JSON (Auto-save .json)",
]

QNA_FORMAT_PROFILES = {
    "Response -> Plain Text": {
        "output_target": "Response",
        "output_format": "Plain Text",
    },
    "Response -> JSON": {
        "output_target": "Response",
        "output_format": "JSON",
    },
    "Response -> JSON (Auto-save .json)": {
        "output_target": "Response",
        "output_format": "JSON",
        "auto_save": True,
        "auto_save_target": "Response",
        "auto_save_file_type": "json",
    },
    "Response + Thinking -> JSON (Auto-save .json)": {
        "output_target": "Response + Thinking",
        "output_format": "JSON",
        "auto_save": True,
        "auto_save_target": "Response + Thinking",
        "auto_save_file_type": "json",
    },
}


def resolve_file_type(file_type, output_format):
    if not file_type or file_type == "Match Output Format":
        return _FORMAT_TO_FILE_TYPE.get(output_format, "txt")
    return file_type


def resolve_selected_targets(selection, available_targets):
    if not available_targets:
        return set()
    if selection == "All":
        return set(available_targets)
    if selection in ("Both", "Prompt + Schedule"):
        return {t for t in ("Prompt", "Schedule") if t in available_targets}
    if selection in available_targets:
        return {selection}
    return {available_targets[0]}


def ensure_extension(filename, file_type):
    ext = _EXT_BY_TYPE.get(file_type, ".txt")
    base, current_ext = os.path.splitext(filename)
    if not base and current_ext:
        base, current_ext = current_ext, ""
    if current_ext.lower() != ext:
        filename = base + ext
    return filename


def resolve_filename_template(filename_template, replacements):
    filename = filename_template
    for key, value in (replacements or {}).items():
        filename = filename.replace("{" + str(key) + "}", str(value))
    return filename


def save_text_to_file(text, folder_path, filename_template, file_type, replacements=None):
    filename = resolve_filename_template(filename_template, replacements or {})
    filename = utils.TextCleaner.sanitize_filename(filename)
    filename = ensure_extension(filename, file_type)

    os.makedirs(folder_path, exist_ok=True)
    out_dir = os.path.abspath(folder_path)
    base_name, ext = os.path.splitext(filename)
    full_path, _ = utils._get_unique_filepath(out_dir, base_name, ext)

    with open(full_path, "w", encoding="utf-8") as f:
        f.write("" if text is None else str(text))
    return full_path


def format_text_payload(text, output_format, label="text"):
    value = "" if text is None else str(text)

    if output_format == "Plain Text":
        return value
    if output_format == "JSON":
        return json.dumps({label: value}, indent=2, ensure_ascii=False)
    if output_format == "Markdown":
        title = label.replace("_", " ").strip().title() or "Text"
        return f"# {title}\n\n{value}"
    if output_format == "YAML":
        return _yaml_from_mapping({label: value})
    if output_format == "CSV":
        return _csv_from_rows([label], [[value]])
    return value


def format_schedule_text(schedule_in, output_format):
    if output_format == "Plain Text":
        if isinstance(schedule_in, str):
            return schedule_in, None
        if isinstance(schedule_in, dict):
            return json.dumps(schedule_in, indent=2, ensure_ascii=False), None
        return "" if schedule_in is None else str(schedule_in), None

    schedule_dict = None
    if not schedule_in or (isinstance(schedule_in, str) and not schedule_in.strip()):
        schedule_dict = {}
    elif isinstance(schedule_in, dict):
        schedule_dict = schedule_in
    elif isinstance(schedule_in, str):
        schedule_dict = json_utils.extract_and_parse_json(schedule_in)

    if schedule_dict is None or not isinstance(schedule_dict, dict):
        return schedule_in if isinstance(schedule_in, str) else "", "Schedule is not valid JSON; cannot format."

    if output_format == "JSON":
        return json.dumps(schedule_dict, indent=2, ensure_ascii=False), None
    if output_format == "YAML":
        return _yaml_from_mapping(schedule_dict), None
    if output_format == "CSV":
        return _schedule_dict_to_csv(schedule_dict), None
    if output_format == "Markdown":
        return _schedule_dict_to_markdown(schedule_dict), None

    return json.dumps(schedule_dict, indent=2, ensure_ascii=False), None


def _schedule_dict_to_csv(schedule_dict):
    rows = []
    for frame, prompt in _sorted_schedule_items(schedule_dict):
        rows.append([str(frame), "" if prompt is None else str(prompt)])
    return _csv_from_rows(["frame", "prompt"], rows)


def _schedule_dict_to_markdown(schedule_dict):
    lines = ["| frame | prompt |", "| --- | --- |"]
    for frame, prompt in _sorted_schedule_items(schedule_dict):
        safe_prompt = "" if prompt is None else str(prompt)
        safe_prompt = safe_prompt.replace("|", "\\|").replace("\n", "<br>")
        lines.append(f"| {frame} | {safe_prompt} |")
    return "\n".join(lines)


def _sorted_schedule_items(schedule_dict):
    items = list(schedule_dict.items())
    try:
        return sorted(items, key=lambda kv: float(kv[0]))
    except Exception:
        return items


def _csv_from_rows(headers, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(headers)
    writer.writerows(rows)
    return buffer.getvalue().strip()


def _yaml_from_mapping(mapping):
    lines = []
    for key, value in mapping.items():
        lines.extend(_yaml_lines_for_pair(str(key), value, indent=0))
    return "\n".join(lines)


def _yaml_lines_for_pair(key, value, indent=0):
    indent_str = " " * indent
    if isinstance(value, dict):
        lines = [f"{indent_str}{key}:"]
        for sub_key, sub_val in value.items():
            lines.extend(_yaml_lines_for_pair(str(sub_key), sub_val, indent=indent + 2))
        return lines
    if isinstance(value, list):
        lines = [f"{indent_str}{key}:"]
        for item in value:
            lines.append(f"{indent_str}  - {_yaml_scalar(item)}")
        return lines
    return [f"{indent_str}{key}: {_yaml_scalar(value)}"]


def _yaml_scalar(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if "\n" in text:
        indented = "\n".join("  " + line for line in text.splitlines())
        return "|\n" + indented
    if any(ch in text for ch in [":", "{", "}", "[", "]", ",", "#", "&", "*", "!", "|", ">", "-", "?", "@", "`", "\"", "'"]):
        return json.dumps(text)
    return text
