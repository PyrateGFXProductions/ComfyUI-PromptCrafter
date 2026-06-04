import json
import re
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

# ------------------------------------------------------------------------------------
# Helper function to read node descriptions from HELP.md
# ------------------------------------------------------------------------------------
def get_node_description(node_name):
    """Parses HELP.md and extracts the description for a given node class name."""
    try:
        import os
        help_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "HELP.md")
        if not os.path.exists(help_path):
            return f"Help file not found for {node_name}."

        with open(help_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Match either ## `NodeName` or ## `NodeName` (Alternate Name)
        pattern = re.compile(rf"##\s*`({node_name})(?:`|\s*\(.*?\)`)\n(.*?)(?=\n##\s*`|\Z)", re.DOTALL)
        match = pattern.search(content)

        if match:
            return match.group(2).strip()
        return f"No description found in HELP.md for {node_name}."
    except Exception as e:
        return f"Error reading help file: {e}"

BRIDGE_VERSION = "vrgdg_bridge_v1"
BRIDGE_CATEGORY = "☠️PGFX /Studio/Adapters"


DEFAULT_SLANG_GLOSSARY = OrderedDict(
    [
        (
            "pulled out the jammy",
            {
                "meaning": "pulled out a gun or pistol",
                "replacement": "pulled out a handgun",
                "visual_hint": "the character draws a handgun during a hold-up",
                "tags": ["weapon", "slang", "narrative_action"],
            },
        ),
        (
            "let two fly",
            {
                "meaning": "fired two shots, often upward as warning shots",
                "replacement": "fired two warning shots into the air",
                "visual_hint": "two warning shots fired up into the sky",
                "tags": ["gunfire", "slang", "narrative_action"],
            },
        ),
        (
            "stick 'em up",
            {
                "meaning": "raise your hands during an armed robbery or hold-up",
                "replacement": "put your hands up",
                "visual_hint": "hands raised in surrender during a hold-up",
                "tags": ["robbery", "command", "slang"],
            },
        ),
        (
            "stick em up",
            {
                "meaning": "raise your hands during an armed robbery or hold-up",
                "replacement": "put your hands up",
                "visual_hint": "hands raised in surrender during a hold-up",
                "tags": ["robbery", "command", "slang"],
            },
        ),
        (
            "jammy",
            {
                "meaning": "gun or pistol",
                "replacement": "gun",
                "visual_hint": "a handgun or small pistol in the character's hand",
                "tags": ["weapon", "slang"],
            },
        ),
        (
            "piece",
            {
                "meaning": "gun or firearm",
                "replacement": "gun",
                "visual_hint": "a concealed or drawn firearm",
                "tags": ["weapon", "slang"],
            },
        ),
        (
            "gat",
            {
                "meaning": "gun or firearm",
                "replacement": "gun",
                "visual_hint": "a gun held or tucked by the character",
                "tags": ["weapon", "slang"],
            },
        ),
        (
            "heater",
            {
                "meaning": "gun or firearm",
                "replacement": "gun",
                "visual_hint": "a firearm used in a tense criminal moment",
                "tags": ["weapon", "slang"],
            },
        ),
        (
            "rolled up",
            {
                "meaning": "arrived or pulled up at a location",
                "replacement": "arrived at the location",
                "visual_hint": "the character arrives on the scene with purpose",
                "tags": ["arrival", "slang"],
            },
        ),
        (
            "jack",
            {
                "meaning": "to rob, steal, or take by force",
                "replacement": "rob",
                "visual_hint": "an attempted robbery or forceful theft",
                "tags": ["crime", "slang"],
            },
        ),
        (
            "posse",
            {
                "meaning": "crew, group, or close team",
                "replacement": "crew",
                "visual_hint": "a small crew moving together with shared purpose",
                "tags": ["group", "slang"],
            },
        ),
        (
            "five-o",
            {
                "meaning": "the police",
                "replacement": "the police",
                "visual_hint": "law enforcement closing in",
                "tags": ["police", "slang"],
            },
        ),
        (
            "po-po",
            {
                "meaning": "the police",
                "replacement": "the police",
                "visual_hint": "law enforcement presence or pursuit",
                "tags": ["police", "slang"],
            },
        ),
        (
            "laid low",
            {
                "meaning": "hid or kept out of sight",
                "replacement": "stayed hidden",
                "visual_hint": "the character staying hidden and cautious",
                "tags": ["hiding", "slang"],
            },
        ),
        (
            "scope",
            {
                "meaning": "look over, inspect, or size up",
                "replacement": "size up",
                "visual_hint": "the character scans the surroundings carefully",
                "tags": ["observation", "slang"],
            },
        ),
    ]
)


def _slugify(value: str, fallback: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text or fallback


def _safe_json_loads(text: str, fallback):
    try:
        return json.loads(text)
    except Exception:
        return fallback


def _strip_code_fence(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines:
            first = lines[0].strip().lower()
            if first == "```" or first.startswith("```json"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            value = "\n".join(lines).strip()
    return value


def _normalize_line_text(text: str) -> str:
    value = str(text or "").replace("\ufeff", "").replace("\u200b", "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", str(text or "").lower())


def _overlap_score(source_text: str, target_text: str) -> float:
    source_tokens = set(_tokenize(source_text))
    target_tokens = set(_tokenize(target_text))
    if not source_tokens or not target_tokens:
        return 0.0
    shared = len(source_tokens & target_tokens)
    return shared / float(len(target_tokens))


def _format_duration(value: float) -> str:
    text = f"{float(value):.3f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _format_srt_time(seconds: float) -> str:
    total_ms = int(round(max(0.0, float(seconds)) * 1000.0))
    hours = total_ms // 3600000
    minutes = (total_ms % 3600000) // 60000
    secs = (total_ms % 60000) // 1000
    millis = total_ms % 1000
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _parse_srt_entries(srt_text: str) -> List[Dict[str, object]]:
    text = str(srt_text or "").replace("\r\n", "\n").strip()
    if not text:
        return []

    entries = []
    blocks = re.split(r"\n\s*\n+", text)
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        time_line = next((line for line in lines if "-->" in line), "")
        if not time_line:
            continue
        start_text, end_text = [part.strip() for part in time_line.split("-->", 1)]
        start = _srt_time_to_seconds(start_text)
        end = _srt_time_to_seconds(end_text)
        subtitle_lines = [line for line in lines if line != time_line and not re.fullmatch(r"\d+", line.strip())]
        subtitle_text = _normalize_line_text(" ".join(subtitle_lines))
        entries.append(
            {
                "index": len(entries) + 1,
                "start_sec": start,
                "end_sec": end,
                "duration_sec": max(0.0, end - start),
                "text": subtitle_text,
            }
        )
    return entries


def _srt_time_to_seconds(timestamp: str) -> float:
    hours, minutes, seconds_ms = timestamp.split(":")
    seconds, milliseconds = seconds_ms.split(",")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(milliseconds) / 1000.0
    )


def _parse_lyric_lines(clean_lyrics_txt: str) -> List[Dict[str, object]]:
    current_tag = ""
    lines_out = []

    for raw_line in str(clean_lyrics_txt or "").replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        tag_match = re.fullmatch(r"\[(.+?)\]", line)
        if tag_match:
            current_tag = tag_match.group(1).strip()
            continue

        inline_tag_match = re.match(r"^\[(.+?)\]\s*(.+)$", line)
        if inline_tag_match:
            current_tag = inline_tag_match.group(1).strip()
            line = inline_tag_match.group(2).strip()

        if not line:
            continue

        lines_out.append(
            {
                "index": len(lines_out) + 1,
                "structure_tag": current_tag,
                "text": _normalize_line_text(line),
            }
        )

    return lines_out


def _parse_glossary_text_lines(custom_glossary_text: str) -> Dict[str, Dict[str, object]]:
    parsed: Dict[str, Dict[str, object]] = OrderedDict()
    for raw_line in str(custom_glossary_text or "").replace("\r\n", "\n").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=>" not in line:
            continue

        term, payload = [part.strip() for part in line.split("=>", 1)]
        if not term or not payload:
            continue

        pieces = [piece.strip() for piece in payload.split("|")]
        meaning = pieces[0] if pieces else ""
        replacement = pieces[1] if len(pieces) > 1 else meaning
        visual_hint = pieces[2] if len(pieces) > 2 else ""
        tags = []
        if len(pieces) > 3:
            tags = [item.strip() for item in pieces[3].split(",") if item.strip()]

        parsed[term.lower()] = {
            "meaning": meaning,
            "replacement": replacement or meaning,
            "visual_hint": visual_hint,
            "tags": tags or ["custom"],
        }

    return parsed


def _build_glossary(custom_glossary_json: str, custom_glossary_text: str = "") -> OrderedDict:
    glossary = OrderedDict()
    for term, entry in DEFAULT_SLANG_GLOSSARY.items():
        glossary[str(term).lower()] = {
            "meaning": str(entry.get("meaning", "")).strip(),
            "replacement": str(entry.get("replacement", entry.get("meaning", ""))).strip(),
            "visual_hint": str(entry.get("visual_hint", "")).strip(),
            "tags": list(entry.get("tags", [])),
        }

    custom_text = _strip_code_fence(custom_glossary_json)
    if custom_text:
        parsed = json.loads(custom_text)
        if not isinstance(parsed, dict):
            raise ValueError("Custom glossary JSON must be an object mapping phrase -> meaning or config object.")

        for raw_term, raw_value in parsed.items():
            term = str(raw_term or "").strip().lower()
            if not term:
                continue

            if isinstance(raw_value, dict):
                meaning = str(raw_value.get("meaning", "")).strip()
                glossary[term] = {
                    "meaning": meaning,
                    "replacement": str(raw_value.get("replacement", meaning)).strip(),
                    "visual_hint": str(raw_value.get("visual_hint", "")).strip(),
                    "tags": [str(item).strip() for item in raw_value.get("tags", []) if str(item).strip()],
                }
            else:
                meaning = str(raw_value).strip()
                glossary[term] = {
                    "meaning": meaning,
                    "replacement": meaning,
                    "visual_hint": "",
                    "tags": ["custom"],
                }

    for term, value in _parse_glossary_text_lines(custom_glossary_text).items():
        glossary[term] = value

    return glossary


def _find_glossary_hits(text: str, glossary: OrderedDict) -> List[Dict[str, object]]:
    search_text = str(text or "")
    lowered = search_text.lower()
    occupied: List[Tuple[int, int]] = []
    hits = []

    terms = sorted(glossary.keys(), key=lambda value: (-len(value), value))
    for term in terms:
        if not term:
            continue
        pattern = re.escape(term)
        if term[0].isalnum():
            pattern = r"(?<!\w)" + pattern
        if term[-1].isalnum():
            pattern = pattern + r"(?!\w)"

        for match in re.finditer(pattern, lowered, flags=re.IGNORECASE):
            span = (match.start(), match.end())
            if any(not (span[1] <= taken[0] or span[0] >= taken[1]) for taken in occupied):
                continue

            occupied.append(span)
            data = glossary.get(term, {})
            hits.append(
                {
                    "term": term,
                    "matched_text": search_text[span[0] : span[1]],
                    "meaning": str(data.get("meaning", "")).strip(),
                    "replacement": str(data.get("replacement", data.get("meaning", ""))).strip(),
                    "visual_hint": str(data.get("visual_hint", "")).strip(),
                    "tags": [str(item).strip() for item in data.get("tags", []) if str(item).strip()],
                    "span": [span[0], span[1]],
                }
            )

    hits.sort(key=lambda item: item["span"][0])
    return hits


def _rewrite_text_with_glossary(text: str, glossary_hits: List[Dict[str, object]]) -> str:
    base = _normalize_line_text(text)
    if not glossary_hits:
        return base
    pieces = []
    cursor = 0
    for item in sorted(glossary_hits, key=lambda value: value["span"][0]):
        start, end = int(item["span"][0]), int(item["span"][1])
        if start < cursor:
            continue
        pieces.append(base[cursor:start])
        replacement = _normalize_line_text(item.get("replacement", "") or item.get("meaning", ""))
        replacement = _apply_replacement_case(replacement, item.get("matched_text", ""))
        pieces.append(replacement)
        cursor = end
    pieces.append(base[cursor:])
    return _normalize_line_text("".join(pieces))


def _annotate_text(text: str, glossary_hits: List[Dict[str, object]]) -> str:
    base = _normalize_line_text(text)
    if not glossary_hits:
        return base
    notes = [f"{item['term']} = {item['meaning']}" for item in glossary_hits if item.get("meaning")]
    notes_text = "; ".join(notes)
    return f"{base} [Literal meaning: {notes_text}.]"


def _apply_replacement_case(replacement: str, matched_text: str) -> str:
    value = str(replacement or "")
    source = str(matched_text or "")
    if not value:
        return value
    if source.isupper():
        return value.upper()
    if source[:1].isupper():
        return value[:1].upper() + value[1:]
    return value


def _guidance_block_from_hits(glossary_hits: List[Dict[str, object]]) -> str:
    if not glossary_hits:
        return ""
    lines = ["SLANG / CONTEXT GUIDANCE"]
    seen = set()
    for item in glossary_hits:
        key = (item.get("term"), item.get("meaning"))
        if key in seen:
            continue
        seen.add(key)
        term = str(item.get("term", "")).strip()
        meaning = str(item.get("meaning", "")).strip()
        visual_hint = str(item.get("visual_hint", "")).strip()
        if visual_hint:
            lines.append(f"- {term} = {meaning}. Visual intent: {visual_hint}.")
        else:
            lines.append(f"- {term} = {meaning}.")
    lines.append("- Use the literal narrative meaning above when planning scenes and prompts.")
    lines.append("- Preserve the original lyric text for subtitles; use these notes only as hidden guidance.")
    return "\n".join(lines)


def _build_scene_srt(segments: List[Dict[str, object]]) -> str:
    lines: List[str] = []
    for idx, segment in enumerate(segments, start=1):
        lines.append(str(idx))
        lines.append(
            f"{_format_srt_time(float(segment['start_sec']))} --> {_format_srt_time(float(segment['end_sec']))}"
        )
        lines.append(f"SCENE {idx}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _summarize_theme(global_theme: str) -> str:
    theme = _normalize_line_text(global_theme)
    if not theme:
        return "cinematic, coherent lighting continuity"
    sentences = re.split(r"(?<=[.!?])\s+", theme)
    return sentences[0][:220].strip() or theme[:220]


def _parse_camera_cycle(camera_cycle: str) -> List[str]:
    parts = [
        _normalize_line_text(item)
        for item in re.split(r"[\n,|]+", str(camera_cycle or ""))
        if _normalize_line_text(item)
    ]
    return parts or ["Medium shot", "Close-up", "Wide shot"]


def _normalize_prompt_map(data) -> OrderedDict:
    prompts = OrderedDict()
    if isinstance(data, list):
        for index, value in enumerate(data, start=1):
            prompts[f"prompt{index}"] = _prompt_value_to_string(value)
        return prompts

    if isinstance(data, dict):
        items = []
        for key, value in data.items():
            match = re.search(r"(\d+)", str(key))
            index = int(match.group(1)) if match else len(items) + 1
            items.append((index, value))
        items.sort(key=lambda item: item[0])
        for ordered_index, (_, value) in enumerate(items, start=1):
            prompts[f"prompt{ordered_index}"] = _prompt_value_to_string(value)
        return prompts

    raise ValueError("Prompt map input must be a JSON object or list.")


def _prompt_value_to_string(value) -> str:
    if isinstance(value, dict):
        if "text" in value:
            return _normalize_line_text(value.get("text", ""))
        if "description" in value:
            return _normalize_line_text(value.get("description", ""))
        return _normalize_line_text(json.dumps(value, ensure_ascii=False))
    if isinstance(value, list):
        return _normalize_line_text(" ".join(_prompt_value_to_string(item) for item in value))
    return _normalize_line_text(str(value or ""))


class PGFX_Studio_VRGDGSemanticBridge_V1:
    """
    Versioned bridge adapter that turns PromptCrafter lyric + SRT outputs into
    VRGDG-ready lyric segments and a continuity-friendly scene SRT.
    """
    DESCRIPTION = get_node_description("PGFX_Studio_VRGDGSemanticBridge_V1")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clean_lyrics_txt": ("STRING", {"multiline": True, "forceInput": True}),
                "lyrics_srt": ("STRING", {"multiline": True, "forceInput": True}),
                "lyricsegments_mode": (["annotated", "literal", "original"], {"default": "annotated"}),
                "lock_to_lyric_lines": ("BOOLEAN", {"default": True}),
                "merge_short_segments": ("BOOLEAN", {"default": True}),
                "min_segment_seconds": ("FLOAT", {"default": 2.5, "min": 0.0, "max": 30.0, "step": 0.1}),
                "max_merge_lookahead": ("INT", {"default": 4, "min": 1, "max": 12, "step": 1}),
                "custom_glossary_json": ("STRING", {"multiline": True, "default": ""}),
                "custom_glossary_text": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "scene_srt",
        "lyricsegments_json",
        "semantic_segments_json",
        "semantic_guidance_block",
        "bridge_report",
    )
    FUNCTION = "adapt"
    CATEGORY = BRIDGE_CATEGORY

    def _coerce_raw_srt_segments(
        self, srt_entries: List[Dict[str, object]]
    ) -> List[Dict[str, object]]:
        coerced = []
        for index, entry in enumerate(srt_entries, start=1):
            coerced.append(
                {
                    "index": index,
                    "start_sec": float(entry.get("start_sec", 0.0)),
                    "end_sec": float(entry.get("end_sec", 0.0)),
                    "duration_sec": max(
                        0.0,
                        float(entry.get("end_sec", 0.0)) - float(entry.get("start_sec", 0.0)),
                    ),
                    "text": _normalize_line_text(entry.get("text", "")),
                    "structure_tag": "",
                    "source_srt_indexes": [int(entry.get("index", index))],
                    "source_srt_text": _normalize_line_text(entry.get("text", "")),
                }
            )
        return coerced

    def _line_lock_segments(
        self,
        lyric_lines: List[Dict[str, object]],
        srt_entries: List[Dict[str, object]],
        max_merge_lookahead: int,
        report: List[str],
    ) -> List[Dict[str, object]]:
        if not lyric_lines:
            report.append("No lyric lines found; falling back to raw SRT segmentation.")
            return self._coerce_raw_srt_segments(srt_entries)
        if not srt_entries:
            report.append("No SRT entries found; cannot line-lock without timings.")
            return []

        if len(srt_entries) < len(lyric_lines):
            report.append(
                "SRT entries are fewer than lyric lines; falling back to one-entry-per-SRT segment."
            )
            return self._coerce_raw_srt_segments(srt_entries)

        locked = []
        srt_index = 0
        lookahead = max(1, int(max_merge_lookahead))

        for line_index, lyric_line in enumerate(lyric_lines):
            lines_remaining = len(lyric_lines) - line_index
            entries_remaining = len(srt_entries) - srt_index
            if entries_remaining <= 0:
                break

            min_entries_after = max(0, lines_remaining - 1)
            max_end_index = min(len(srt_entries) - 1, srt_index + lookahead - 1)
            max_end_index = min(max_end_index, len(srt_entries) - min_entries_after - 1)
            if max_end_index < srt_index:
                max_end_index = srt_index

            best_end_index = srt_index
            best_score = -1.0
            accumulated_text_parts: List[str] = []

            for candidate_end in range(srt_index, max_end_index + 1):
                accumulated_text_parts.append(str(srt_entries[candidate_end].get("text", "")))
                candidate_text = _normalize_line_text(" ".join(accumulated_text_parts))
                score = _overlap_score(candidate_text, str(lyric_line.get("text", "")))
                if candidate_end == srt_index and not candidate_text:
                    score = -1.0
                if score > best_score:
                    best_score = score
                    best_end_index = candidate_end

            group = srt_entries[srt_index : best_end_index + 1]
            locked.append(
                {
                    "index": len(locked) + 1,
                    "start_sec": float(group[0]["start_sec"]),
                    "end_sec": float(group[-1]["end_sec"]),
                    "duration_sec": max(0.0, float(group[-1]["end_sec"]) - float(group[0]["start_sec"])),
                    "text": str(lyric_line.get("text", "")),
                    "structure_tag": str(lyric_line.get("structure_tag", "")).strip(),
                    "source_srt_indexes": [int(item["index"]) for item in group],
                    "source_srt_text": _normalize_line_text(" ".join(str(item.get("text", "")) for item in group)),
                }
            )
            srt_index = best_end_index + 1

        if srt_index < len(srt_entries) and locked:
            tail = srt_entries[srt_index:]
            locked[-1]["end_sec"] = float(tail[-1]["end_sec"])
            locked[-1]["duration_sec"] = max(
                0.0, float(locked[-1]["end_sec"]) - float(locked[-1]["start_sec"])
            )
            locked[-1]["source_srt_indexes"].extend(int(item["index"]) for item in tail)
            locked[-1]["source_srt_text"] = _normalize_line_text(
                " ".join(
                    [
                        str(locked[-1].get("source_srt_text", "")),
                        " ".join(str(item.get("text", "")) for item in tail),
                    ]
                )
            )
            report.append(
                f"Appended {len(tail)} trailing SRT entr{'y' if len(tail) == 1 else 'ies'} to the final lyric line."
            )

        report.append(
            f"Locked {len(locked)} lyric line segment{'s' if len(locked) != 1 else ''} against {len(srt_entries)} SRT entr{'y' if len(srt_entries) == 1 else 'ies'}."
        )
        return locked

    def _merge_short_segments(
        self,
        segments: List[Dict[str, object]],
        min_segment_seconds: float,
        report: List[str],
    ) -> List[Dict[str, object]]:
        if not segments or min_segment_seconds <= 0:
            return [dict(item) for item in segments]

        merged: List[Dict[str, object]] = []
        merges = 0

        for segment in segments:
            current = dict(segment)
            duration = float(current.get("duration_sec", 0.0))
            structure_tag = str(current.get("structure_tag", "")).strip().lower()

            if duration < min_segment_seconds and merged:
                previous = merged[-1]
                prev_tag = str(previous.get("structure_tag", "")).strip().lower()
                if not structure_tag or structure_tag == prev_tag or not prev_tag:
                    previous.setdefault("source_srt_indexes", [])
                    current.setdefault("source_srt_indexes", [])
                    previous.setdefault("source_srt_text", _normalize_line_text(previous.get("text", "")))
                    current.setdefault("source_srt_text", _normalize_line_text(current.get("text", "")))
                    previous["text"] = _normalize_line_text(
                        f"{previous.get('text', '')} {current.get('text', '')}"
                    )
                    previous["source_srt_text"] = _normalize_line_text(
                        f"{previous.get('source_srt_text', '')} {current.get('source_srt_text', '')}"
                    )
                    previous["end_sec"] = float(current["end_sec"])
                    previous["duration_sec"] = max(
                        0.0, float(previous["end_sec"]) - float(previous["start_sec"])
                    )
                    previous["source_srt_indexes"].extend(current.get("source_srt_indexes", []))
                    merges += 1
                    continue

            merged.append(current)

        for index, segment in enumerate(merged, start=1):
            segment["index"] = index

        if merges:
            report.append(
                f"Merged {merges} short segment{'s' if merges != 1 else ''} into the previous continuity beat."
            )
        return merged

    def _finalize_segments(
        self,
        segments: List[Dict[str, object]],
        lyricsegments_mode: str,
        glossary: OrderedDict,
    ) -> Tuple[List[Dict[str, object]], str]:
        all_hits: List[Dict[str, object]] = []
        finalized = []

        for index, segment in enumerate(segments, start=1):
            text = _normalize_line_text(segment.get("text", ""))
            hits = _find_glossary_hits(text, glossary)
            literal_text = _rewrite_text_with_glossary(text, hits)
            annotated_text = _annotate_text(literal_text, hits)
            semantic_notes = "; ".join(
                f"{item['term']} = {item['meaning']}" for item in hits if item.get("meaning")
            )
            visual_hints = [str(item.get("visual_hint", "")).strip() for item in hits if item.get("visual_hint")]
            structure_tag = str(segment.get("structure_tag", "")).strip()
            family_hint = _slugify(structure_tag or f"segment_{index}", f"segment_{index}")

            if lyricsegments_mode == "original":
                output_text = text
            elif lyricsegments_mode == "literal":
                output_text = literal_text
            else:
                output_text = annotated_text if hits else text

            if structure_tag:
                output_text = f"({structure_tag}) {output_text}"

            finalized_segment = {
                "index": index,
                "segment_key": f"segment{index}",
                "start_sec": round(float(segment["start_sec"]), 3),
                "end_sec": round(float(segment["end_sec"]), 3),
                "duration_sec": round(float(segment["duration_sec"]), 3),
                "structure_tag": structure_tag,
                "scene_family_hint": family_hint,
                "raw_text": text,
                "literal_text": literal_text,
                "annotated_text": annotated_text,
                "output_text": output_text,
                "semantic_notes": semantic_notes,
                "visual_hints": visual_hints,
                "glossary_hits": hits,
                "source_srt_indexes": list(segment.get("source_srt_indexes", [])),
                "source_srt_text": _normalize_line_text(segment.get("source_srt_text", "")),
            }
            finalized.append(finalized_segment)
            all_hits.extend(hits)

        return finalized, _guidance_block_from_hits(all_hits)

    def adapt(
        self,
        clean_lyrics_txt,
        lyrics_srt,
        lyricsegments_mode="annotated",
        lock_to_lyric_lines=True,
        merge_short_segments=True,
        min_segment_seconds=2.5,
        max_merge_lookahead=4,
        custom_glossary_json="",
        custom_glossary_text="",
    ):
        report: List[str] = []
        glossary = _build_glossary(custom_glossary_json, custom_glossary_text)
        srt_entries = _parse_srt_entries(lyrics_srt)
        lyric_lines = _parse_lyric_lines(clean_lyrics_txt)

        if lock_to_lyric_lines:
            working_segments = self._line_lock_segments(
                lyric_lines, srt_entries, max_merge_lookahead, report
            )
        else:
            working_segments = self._coerce_raw_srt_segments(srt_entries)
            report.append("Line locking disabled; using raw SRT timing groups.")

        if merge_short_segments:
            working_segments = self._merge_short_segments(
                working_segments, float(min_segment_seconds), report
            )
        else:
            report.append("Short-segment merging disabled.")

        finalized_segments, semantic_guidance_block = self._finalize_segments(
            working_segments, lyricsegments_mode, glossary
        )

        lyricsegments_payload = OrderedDict()
        for segment in finalized_segments:
            duration_text = _format_duration(float(segment["duration_sec"]))
            key = f"{segment['segment_key']}_Duration_{duration_text}"
            lyricsegments_payload[key] = segment["output_text"]

        scene_srt = _build_scene_srt(finalized_segments)
        semantic_payload = {
            "version": BRIDGE_VERSION,
            "segment_count": len(finalized_segments),
            "glossary_size": len(glossary),
            "segments": finalized_segments,
        }

        report.append(
            f"Exported {len(finalized_segments)} VRGDG scene segment{'s' if len(finalized_segments) != 1 else ''}."
        )
        glossary_hit_count = sum(len(segment.get("glossary_hits", [])) for segment in finalized_segments)
        if glossary_hit_count:
            report.append(
                f"Applied {glossary_hit_count} glossary interpretation hit{'s' if glossary_hit_count != 1 else ''} across the segment set."
            )
        else:
            report.append("No glossary hits were applied; add custom glossary text/JSON for song-specific slang if needed.")

        return (
            scene_srt,
            json.dumps(lyricsegments_payload, indent=2, ensure_ascii=False),
            json.dumps(semantic_payload, indent=2, ensure_ascii=False),
            semantic_guidance_block,
            "\n".join(report),
        )


class PGFX_Studio_VRGDGStoryGroupBridge_V1:
    """
    Versioned bridge adapter that converts semantic lyric segments into the
    exact story-group contract VRGDG prompt batchers expect, with extra
    continuity metadata attached.
    """
    DESCRIPTION = get_node_description("PGFX_Studio_VRGDGStoryGroupBridge_V1")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "semantic_segments_json": ("STRING", {"multiline": True, "forceInput": True}),
                "global_theme": ("STRING", {"multiline": True, "forceInput": True}),
                "story_concept": ("STRING", {"multiline": True, "default": ""}),
                "character_anchor": ("STRING", {"multiline": True, "default": "lead performer"}),
                "default_location": ("STRING", {"multiline": True, "default": "a coherent recurring story location"}),
                "default_wardrobe": ("STRING", {"multiline": True, "default": ""}),
                "camera_cycle": ("STRING", {"multiline": False, "default": "Medium shot, Close-up, Wide shot"}),
                "chorus_strategy": (
                    ["reuse_same_scene_family", "reuse_with_escalation", "new_scene_each_chorus"],
                    {"default": "reuse_same_scene_family"},
                ),
            },
            "optional": {
                "semantic_guidance_block": ("STRING", {"multiline": True, "forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = (
        "storygroups_json",
        "continuity_manifest_json",
        "text2image_guidance",
        "image2video_guidance",
        "bridge_report",
    )
    FUNCTION = "adapt"
    CATEGORY = BRIDGE_CATEGORY

    def _load_segments(self, semantic_segments_json: str) -> List[Dict[str, object]]:
        parsed = json.loads(_strip_code_fence(semantic_segments_json))
        if not isinstance(parsed, dict):
            raise ValueError("Semantic segments JSON must be an object.")
        segments = parsed.get("segments")
        if not isinstance(segments, list):
            raise ValueError("Semantic segments JSON must include a 'segments' list.")
        return [dict(item) for item in segments if isinstance(item, dict)]

    def _family_for_segment(
        self,
        segment: Dict[str, object],
        chorus_strategy: str,
        seen_families: Dict[str, int],
    ) -> Tuple[str, bool]:
        structure_tag = str(segment.get("structure_tag", "")).strip()
        if not structure_tag:
            base = _slugify(segment.get("scene_family_hint", ""), f"segment_{segment.get('index', 0)}")
        else:
            base = _slugify(structure_tag, f"segment_{segment.get('index', 0)}")

        lower_tag = structure_tag.lower()
        is_chorus = "chorus" in lower_tag
        if is_chorus and chorus_strategy != "new_scene_each_chorus":
            family_id = "chorus_main"
        elif not structure_tag:
            family_id = base
        else:
            family_id = base

        recalled = family_id in seen_families
        seen_families[family_id] = seen_families.get(family_id, 0) + 1

        if is_chorus and chorus_strategy == "reuse_with_escalation" and seen_families[family_id] > 1:
            family_id = f"{family_id}_escalation_{seen_families[family_id] - 1}"
            recalled = True

        return family_id, recalled

    def _camera_for_family(
        self,
        family_id: str,
        structure_tag: str,
        family_camera_map: Dict[str, str],
        camera_cycle: List[str],
        segment_index: int,
    ) -> str:
        if family_id in family_camera_map:
            return family_camera_map[family_id]

        lower_tag = str(structure_tag or "").lower()
        if "intro" in lower_tag:
            camera = "Wide shot"
        elif "chorus" in lower_tag:
            camera = "Medium close-up"
        elif "bridge" in lower_tag:
            camera = "Wide angle"
        elif "outro" in lower_tag:
            camera = "Wide shot"
        else:
            camera = camera_cycle[(max(0, segment_index - 1)) % len(camera_cycle)]

        family_camera_map[family_id] = camera
        return camera

    def _subject_text(self, character_anchor: str, default_wardrobe: str, semantic_notes: str) -> str:
        subject = _normalize_line_text(character_anchor) or "lead performer"
        wardrobe = _normalize_line_text(default_wardrobe)
        if wardrobe and wardrobe.lower() not in subject.lower():
            subject = f"{subject}, wearing {wardrobe}"
        if not subject:
            subject = "lead performer"
        return subject

    def _frame_text(
        self,
        segment: Dict[str, object],
        family_id: str,
        continuity_mode: str,
        family_recall: bool,
    ) -> str:
        pieces = []
        structure_tag = str(segment.get("structure_tag", "")).strip()
        literal_text = _normalize_line_text(segment.get("literal_text", ""))
        semantic_notes = _normalize_line_text(segment.get("semantic_notes", ""))
        visual_hints = [str(item).strip() for item in segment.get("visual_hints", []) if str(item).strip()]

        if structure_tag:
            pieces.append(f"{structure_tag} visual beat.")
        if literal_text:
            pieces.append(literal_text)
        if visual_hints:
            pieces.append("Visual priority: " + "; ".join(visual_hints) + ".")
        elif semantic_notes:
            pieces.append("Interpret literally: " + semantic_notes + ".")

        if continuity_mode == "continue":
            pieces.append(
                "Keep the same lead identity, wardrobe, props, and spatial layout as the previous segment."
            )
        elif family_recall:
            pieces.append(
                f"Return to the recurring scene family '{family_id}' with the same lead identity and wardrobe."
            )
        else:
            pieces.append("Establish a fresh scene beat while preserving the same lead identity.")

        return _normalize_line_text(" ".join(pieces))

    def _build_guidance_blocks(self, semantic_guidance_block: str = "") -> Tuple[str, str]:
        t2i_guidance = "\n".join(
            [
                "VRGDG BRIDGE T2I CONTINUITY RULES",
                "- Treat semantic_notes and glossary_hits as hidden literal guidance, not as text to render.",
                "- If scene_family_id repeats, preserve the same lead identity, wardrobe, recurring location, and hero props.",
                "- If continuity_mode = continue, do not invent a new cast, outfit, or setting.",
                "- If family_recall is true, return to the same motif rather than inventing a new scene concept.",
                "- Keep repeated chorus groups visually related unless the family id explicitly includes an escalation suffix.",
            ]
        )
        i2v_guidance = "\n".join(
            [
                "VRGDG BRIDGE I2V CONTINUITY RULES",
                "- If continuity_mode = continue, begin from the previous shot's final-frame identity and environment.",
                "- Preserve lead facial features, hair, wardrobe, and props across repeated scene_family_id groups.",
                "- Repeated chorus scene families should feel like visual continuation or deliberate escalation, never a random reset.",
                "- Use semantic_notes only as hidden literal-action guidance.",
                "- Avoid introducing new people, outfits, or locations unless the family id changes.",
            ]
        )
        extra_guidance = _normalize_line_text(semantic_guidance_block)
        if extra_guidance:
            t2i_guidance += "\n\n" + semantic_guidance_block.strip()
            i2v_guidance += "\n\n" + semantic_guidance_block.strip()
        return t2i_guidance, i2v_guidance

    def adapt(
        self,
        semantic_segments_json,
        global_theme,
        story_concept="",
        character_anchor="lead performer",
        default_location="a coherent recurring story location",
        default_wardrobe="",
        camera_cycle="Medium shot, Close-up, Wide shot",
        chorus_strategy="reuse_same_scene_family",
        semantic_guidance_block="",
    ):
        segments = self._load_segments(semantic_segments_json)
        if not segments:
            raise ValueError("No semantic segments were found for story-group adaptation.")

        camera_choices = _parse_camera_cycle(camera_cycle)
        family_camera_map: Dict[str, str] = {}
        seen_families: Dict[str, int] = {}
        groups = []
        continuity_manifest = {
            "version": BRIDGE_VERSION,
            "group_count": 0,
            "families": {},
        }
        report = []

        previous_family = None
        theme_summary = _summarize_theme(global_theme)
        story_summary = _normalize_line_text(story_concept) or (
            "A continuity-locked music video that preserves literal lyric meaning, repeating scene families, and a stable lead identity."
        )

        location_id = _slugify(default_location, "main_location")
        wardrobe_id = _slugify(default_wardrobe, "primary_wardrobe") if _normalize_line_text(default_wardrobe) else ""

        for index, segment in enumerate(segments, start=1):
            family_id, family_recall = self._family_for_segment(segment, chorus_strategy, seen_families)
            if index == 1:
                continuity_mode = "start"
            elif family_id == previous_family:
                continuity_mode = "continue"
            else:
                continuity_mode = "hard_cut"

            camera = self._camera_for_family(
                family_id,
                str(segment.get("structure_tag", "")),
                family_camera_map,
                camera_choices,
                index,
            )
            subject = self._subject_text(
                character_anchor,
                default_wardrobe,
                str(segment.get("semantic_notes", "")),
            )
            frame = self._frame_text(segment, family_id, continuity_mode, family_recall)
            scene_and_lighting = _normalize_line_text(f"{default_location}; {theme_summary}")

            group = OrderedDict(
                [
                    ("index", index),
                    ("subject", subject),
                    ("camera", camera),
                    ("scene_and_lighting", scene_and_lighting),
                    ("frame", frame),
                    ("continuity_mode", continuity_mode),
                    ("scene_family_id", family_id),
                    ("family_recall", bool(family_recall)),
                    ("anchor_character_id", "lead"),
                    ("anchor_location_id", location_id),
                    ("anchor_wardrobe_id", wardrobe_id),
                    ("semantic_notes", str(segment.get("semantic_notes", ""))),
                    ("visual_hints", list(segment.get("visual_hints", []))),
                    ("source_segment_key", str(segment.get("segment_key", f"segment{index}"))),
                ]
            )
            groups.append(group)

            family_state = continuity_manifest["families"].setdefault(
                family_id,
                {
                    "occurrences": 0,
                    "camera": camera,
                    "location_id": location_id,
                    "wardrobe_id": wardrobe_id,
                },
            )
            family_state["occurrences"] += 1
            previous_family = family_id

        continuity_manifest["group_count"] = len(groups)
        report.append(
            f"Built {len(groups)} story group{'s' if len(groups) != 1 else ''} with {len(continuity_manifest['families'])} scene famil{'ies' if len(continuity_manifest['families']) != 1 else 'y'}."
        )
        t2i_guidance, i2v_guidance = self._build_guidance_blocks(semantic_guidance_block)

        payload = OrderedDict(
            [
                ("story_summary", story_summary),
                ("groups", groups),
            ]
        )

        return (
            json.dumps(payload, indent=2, ensure_ascii=False),
            json.dumps(continuity_manifest, indent=2, ensure_ascii=False),
            t2i_guidance,
            i2v_guidance,
            "\n".join(report),
        )


class PGFX_Studio_VRGDGSchedulePromptMap_V1:
    """
    Converts a PromptCrafter frame schedule into VRGDG's prompt1..promptN map
    using a scene SRT as the authoritative scene boundary contract.
    """
    DESCRIPTION = get_node_description("PGFX_Studio_VRGDGSchedulePromptMap_V1")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "schedule_json": ("STRING", {"multiline": True, "forceInput": True}),
                "scene_srt": ("STRING", {"multiline": True, "forceInput": True}),
                "fps": ("FLOAT", {"default": 25.0, "min": 1.0, "max": 120.0, "step": 0.5}),
                "selection_mode": (
                    ["at_or_before", "nearest", "at_or_after"],
                    {"default": "at_or_before"},
                ),
            }
        }

    RETURN_TYPES = ("STRING", "INT", "STRING")
    RETURN_NAMES = ("prompt_map_json", "prompt_count", "bridge_report")
    FUNCTION = "adapt"
    CATEGORY = BRIDGE_CATEGORY

    def _load_schedule(self, schedule_json: str) -> List[Tuple[int, str]]:
        parsed = json.loads(_strip_code_fence(schedule_json))
        items: List[Tuple[int, str]] = []
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                try:
                    frame = int(str(key))
                except Exception as exc:
                    raise ValueError(f"Invalid schedule key '{key}': {exc}") from exc
                items.append((frame, _prompt_value_to_string(value)))
        elif isinstance(parsed, list):
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                frame = item.get("frame", item.get("start_frame", item.get("index", 0)))
                prompt = item.get("prompt", item.get("positive", item.get("text", "")))
                try:
                    frame = int(frame)
                except Exception as exc:
                    raise ValueError(f"Invalid list schedule frame '{frame}': {exc}") from exc
                items.append((frame, _prompt_value_to_string(prompt)))
        else:
            raise ValueError("Schedule JSON must be an object keyed by frame index or a list of prompt entries.")

        items.sort(key=lambda item: item[0])
        if not items:
            raise ValueError("Schedule JSON did not contain any frame prompts.")
        return items

    def _select_prompt(
        self,
        schedule_items: List[Tuple[int, str]],
        target_frame: int,
        selection_mode: str,
    ) -> str:
        frames = [item[0] for item in schedule_items]

        if selection_mode == "at_or_after":
            for frame, prompt in schedule_items:
                if frame >= target_frame:
                    return prompt
            return schedule_items[-1][1]

        if selection_mode == "nearest":
            best_frame, best_prompt = min(
                schedule_items,
                key=lambda item: (abs(item[0] - target_frame), item[0]),
            )
            _ = best_frame
            return best_prompt

        chosen = schedule_items[0][1]
        for frame, prompt in schedule_items:
            if frame <= target_frame:
                chosen = prompt
            else:
                break
        return chosen

    def adapt(self, schedule_json, scene_srt, fps=25.0, selection_mode="at_or_before"):
        schedule_items = self._load_schedule(schedule_json)
        scene_entries = _parse_srt_entries(scene_srt)
        if not scene_entries:
            raise ValueError("Scene SRT did not contain any valid scene timings.")

        prompt_map = OrderedDict()
        for index, scene in enumerate(scene_entries, start=1):
            target_frame = int(round(float(scene["start_sec"]) * float(fps)))
            prompt_map[f"prompt{index}"] = self._select_prompt(
                schedule_items, target_frame, selection_mode
            )

        report = (
            f"Mapped {len(scene_entries)} scene cue{'s' if len(scene_entries) != 1 else ''} "
            f"to {len(prompt_map)} VRGDG prompt entr{'y' if len(prompt_map) == 1 else 'ies'} "
            f"from a schedule with {len(schedule_items)} frame key{'s' if len(schedule_items) != 1 else ''}."
        )
        return (
            json.dumps(prompt_map, indent=2, ensure_ascii=False),
            len(prompt_map),
            report,
        )


class PGFX_Studio_VRGDGPromptPackageValidator_V1:
    """
    Validates that the VRGDG bridge artifacts agree on scene count and emits
    normalized prompt maps so the MVC workflow does not silently drift.
    """
    DESCRIPTION = get_node_description("PGFX_Studio_VRGDGPromptPackageValidator_V1")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "scene_srt": ("STRING", {"multiline": True, "forceInput": True}),
                "lyricsegments_json": ("STRING", {"multiline": True, "forceInput": True}),
                "storygroups_json": ("STRING", {"multiline": True, "forceInput": True}),
                "strict": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "text2image_json": ("STRING", {"multiline": True, "forceInput": True}),
                "image2video_json": ("STRING", {"multiline": True, "forceInput": True}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "BOOLEAN", "STRING")
    RETURN_NAMES = (
        "text2image_json",
        "image2video_json",
        "bundle_manifest_json",
        "is_valid",
        "validation_report",
    )
    FUNCTION = "validate"
    CATEGORY = BRIDGE_CATEGORY

    def _count_storygroups(self, storygroups_json: str) -> int:
        parsed = json.loads(_strip_code_fence(storygroups_json))
        if isinstance(parsed, dict) and isinstance(parsed.get("groups"), list):
            return len(parsed["groups"])
        raise ValueError("storygroups_json must contain a top-level 'groups' list.")

    def _count_lyricsegments(self, lyricsegments_json: str) -> int:
        parsed = json.loads(_strip_code_fence(lyricsegments_json))
        if not isinstance(parsed, dict):
            raise ValueError("lyricsegments_json must be a JSON object.")
        count = 0
        for key in parsed.keys():
            if re.match(r"(?i)segment\d+_duration_", str(key)):
                count += 1
        if count <= 0:
            raise ValueError("lyricsegments_json did not contain any segmentN_Duration_* keys.")
        return count

    def _normalize_optional_prompt_map(self, text: Optional[str]) -> Tuple[str, int]:
        if text is None:
            return "", 0
        cleaned = _strip_code_fence(text)
        if not cleaned:
            return "", 0
        parsed = json.loads(cleaned)
        normalized = _normalize_prompt_map(parsed)
        return json.dumps(normalized, indent=2, ensure_ascii=False), len(normalized)

    def validate(
        self,
        scene_srt,
        lyricsegments_json,
        storygroups_json,
        strict=True,
        text2image_json="",
        image2video_json="",
    ):
        report: List[str] = []
        scene_count = len(_parse_srt_entries(scene_srt))
        lyric_count = self._count_lyricsegments(lyricsegments_json)
        group_count = self._count_storygroups(storygroups_json)
        normalized_t2i, t2i_count = self._normalize_optional_prompt_map(text2image_json)
        normalized_i2v, i2v_count = self._normalize_optional_prompt_map(image2video_json)

        manifest = OrderedDict(
            [
                ("version", BRIDGE_VERSION),
                ("scene_count", scene_count),
                ("lyricsegments_count", lyric_count),
                ("storygroups_count", group_count),
                ("text2image_count", t2i_count),
                ("image2video_count", i2v_count),
            ]
        )

        is_valid = True

        def check_equal(left_name: str, left_value: int, right_name: str, right_value: int):
            nonlocal is_valid
            if left_value != right_value:
                is_valid = False
                report.append(
                    f"COUNT MISMATCH: {left_name}={left_value}, {right_name}={right_value}."
                )

        check_equal("scene_srt", scene_count, "lyricsegments", lyric_count)
        check_equal("scene_srt", scene_count, "storygroups", group_count)
        if t2i_count:
            check_equal("scene_srt", scene_count, "text2image", t2i_count)
        if i2v_count:
            check_equal("scene_srt", scene_count, "image2video", i2v_count)

        if is_valid:
            report.append("Bundle valid. All provided bridge artifacts agree on scene count.")
        elif strict:
            report.append("Strict mode is enabled. Do not feed this bundle into VRGDG MVC until counts match.")
        else:
            report.append("Strict mode disabled. Counts do not match, but normalized outputs were still returned for inspection.")

        return (
            normalized_t2i,
            normalized_i2v,
            json.dumps(manifest, indent=2, ensure_ascii=False),
            bool(is_valid),
            "\n".join(report),
        )


NODE_CLASS_MAPPINGS = {
    "PGFX_Studio_VRGDGSemanticBridge_V1": PGFX_Studio_VRGDGSemanticBridge_V1,
    "PGFX_Studio_VRGDGStoryGroupBridge_V1": PGFX_Studio_VRGDGStoryGroupBridge_V1,
    "PGFX_Studio_VRGDGSchedulePromptMap_V1": PGFX_Studio_VRGDGSchedulePromptMap_V1,
    "PGFX_Studio_VRGDGPromptPackageValidator_V1": PGFX_Studio_VRGDGPromptPackageValidator_V1,
}


NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_Studio_VRGDGSemanticBridge_V1": "VRGDG Semantic Bridge V1",
    "PGFX_Studio_VRGDGStoryGroupBridge_V1": "VRGDG StoryGroup Bridge V1",
    "PGFX_Studio_VRGDGSchedulePromptMap_V1": "VRGDG Schedule -> Prompt Map V1",
    "PGFX_Studio_VRGDGPromptPackageValidator_V1": "VRGDG Prompt Package Validator V1",
}
