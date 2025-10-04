# Standard library imports
import os
import re
import io
import json
import textwrap
import base64
import pickle
import time
import concurrent.futures
import itertools
import hashlib
import ast
from PIL import Image
import torch
import collections
import numpy as np

# Local module imports
from . import config

# --- Dependency-specific imports ---
if config.LANGDETECT_AVAILABLE: from langdetect import detect, LangDetectException
if config.PYPDF_AVAILABLE: from pypdf import PdfReader
if config.DUCKDUCKGO_SEARCH_AVAILABLE: from duckduckgo_search import DDGS
if config.LIBROSA_AVAILABLE: import librosa
if config.MATPLOTLIB_AVAILABLE: import matplotlib.pyplot as plt

# ------------------------------------------------------------------------------------
# General Utilities
# ------------------------------------------------------------------------------------

def _debug_print(debug_mode, title, content):
    """Prints debug information to the console if debug_mode is True."""
    if debug_mode:
        print(f"\n\033[95m{'='*20} DEBUG: {title} {'='*20}\033[0m")
        print(content)
        print(f"\033[95m{'='* (42 + len(title))}\033[0m\n")

def _get_cache_key(*args):
    """
    Creates a unique and deterministic key for caching based on the node's inputs.
    This function recursively handles complex data types for robust hashing.
    """
    hasher = hashlib.sha256()

    def update_hash(data):
        """A nested helper to recursively update the hash."""
        if isinstance(data, torch.Tensor):
            hasher.update(data.cpu().numpy().tobytes())
        elif isinstance(data, Image.Image):
            hasher.update(data.tobytes())
        elif isinstance(data, (list, tuple)):
            for item in data:
                update_hash(item)
        elif isinstance(data, dict):
            for key in sorted(data.keys()):
                update_hash(key)
                update_hash(data[key])
        else:
            # For simple types and other pickle-able objects
            try:
                hasher.update(pickle.dumps(data))
            except (pickle.PicklingError, TypeError):
                # Fallback for unpickleable types
                hasher.update(str(data).encode('utf-8'))

    for arg in args:
        update_hash(arg)

    return hasher.hexdigest()

def safe_read(path):
    """A helper function to read a text file safely, returning an error message on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"[Error reading {os.path.basename(path)}: {e}]"

def _detect_language(text: str, fallback='English'):
    """Detects the language of the input text using the langdetect library."""
    if not config.LANGDETECT_AVAILABLE or not text or not text.strip():
        return fallback
    try:
        LANG_MAP = {'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German', 'it': 'Italian', 'pt': 'Portuguese', 'nl': 'Dutch', 'ru': 'Russian', 'ja': 'Japanese', 'ko': 'Korean', 'zh-cn': 'Chinese (Simplified)', 'zh-tw': 'Chinese (Traditional)', 'ar': 'Arabic', 'hi': 'Hindi'}
        lang_code = detect(text[:500])
        return LANG_MAP.get(lang_code, fallback)
    except LangDetectException:
        return fallback

def _save_output_to_file(filename_prefix, sections, base_filename="prompt"):
    """Saves generated content sections to a timestamped text file."""
    base_dir = os.path.join(config.COMFYUI_ROOT_DIR, "output")
    safe_subdir = os.path.normpath(filename_prefix.strip()).lstrip('.').lstrip('/')
    out_dir = os.path.join(base_dir, safe_subdir)
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{base_filename}_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000}.txt"
    fpath = os.path.join(out_dir, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        for i, (title, content) in enumerate(sections):
            if content and str(content).strip():
                f.write(f"=== {title.upper()} ===\n{str(content).strip()}\n")
                if i < len(sections) - 1: f.write("\n")

# ------------------------------------------------------------------------------------
# Text & JSON Processing
# ------------------------------------------------------------------------------------

class TextCleaner:
    """A utility class for various text cleaning and formatting operations."""
    @staticmethod
    def single_paragraph(text: str) -> str:
        text = (text or "").strip()
        # Replace any sequence of whitespace characters (including newlines, tabs, etc.) with a single space.
        # This is more efficient than multiple separate regex substitutions.
        text = re.sub(r'\s+', ' ', text).strip()
        if (text.startswith('"') and text.endswith('"')) or (text.startswith("“") and text.endswith("”")):
            text = text[1:-1].strip()
        return text

    @staticmethod
    def dedupe_sentences(text: str) -> str:
        parts = re.split(r'(?<=[.!?])\s+', text.strip())
        seen, keep = set(), []
        for s in parts:
            ss, key = s.strip(), s.strip().lower()
            if ss and key not in seen:
                seen.add(key)
                keep.append(ss)
        return " ".join(keep)

    @staticmethod
    def slim_prompt_text(text: str) -> str:
        if not text: return text
        t = re.sub(r"\b(and also|additionally|moreover)\b", "and", text, flags=re.IGNORECASE)
        t = re.sub(r"\bwith\b([^,]+?), and\b", r"with\1,", t, flags=re.IGNORECASE)
        t = re.sub(r"\b(and\s+){2,}", "and ", t, flags=re.IGNORECASE)
        t = re.sub(r",\s*,+", ",", t)
        return re.sub(r"\s+", " ", t).strip()

class JSONParsingError(ValueError):
    """Custom exception for errors during JSON extraction and parsing."""
    def __init__(self, message, text=None, original_exception=None):
        self.text = text
        self.original_exception = original_exception
        full_message = message
        if text:
            pos = getattr(original_exception, 'pos', None)
            if pos is not None:
                start, end = max(0, pos - 40), min(len(text), pos + 40)
                snippet, pointer = text[start:end], " " * (pos - start) + "^"
                full_message += f"\nContext around error (pos {pos}):\n{snippet}\n{pointer}"
            else:
                full_message += f"\nText snippet: {text[:200]}..."
        if original_exception: full_message += f"\nOriginal error: {original_exception}"
        super().__init__(full_message)

def _find_json_candidate(text: str) -> str | None:
    """Finds the most likely JSON string candidate from raw text returned by an LLM."""
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", text, re.DOTALL)
    if match: return match.group(1)
    
    first_brace, first_bracket = text.find('{'), text.find('[')
    if first_brace == -1 and first_bracket == -1: return None
    start_pos = min(first_brace, first_bracket) if first_brace != -1 and first_bracket != -1 else max(first_brace, first_bracket)

    balance, in_string = 0, False
    for i in range(start_pos, len(text)):
        char = text[i]
        if char == '"' and (i == 0 or text[i-1] != '\\'): in_string = not in_string
        if not in_string:
            if char in '{[': balance += 1
            elif char in '}]': balance -= 1
        if balance == 0: return text[start_pos : i + 1]
    return None

def _clean_json_string(json_str: str) -> str:
    """Cleans a JSON string candidate to fix common, non-standard syntax produced by LLMs."""
    cleaned_str = re.sub(r"^\s*//.*$", "", json_str, flags=re.MULTILINE)
    cleaned_str = re.sub(r'/\*[\s\S]*?\*/', '', cleaned_str) # Remove /* ... */ comments
    
    # Convert single-quoted keys and values to double-quoted
    cleaned_str = re.sub(r"([{,]\s*)'([^']*)'(\s*:)", r'\1"\2"\3', cleaned_str) # Keys
    cleaned_str = re.sub(r"(: \s*)'([^']*)'(\s*[,}])", r'\1"\2"\3', cleaned_str) # Values

    cleaned_str = re.sub(r"([{,]\s*)([a-zA-Z0-9_.-]+)(\s*:)", r'\1"\2"\3', cleaned_str) # Add quotes to unquoted keys (including hyphens/dots)
    cleaned_str = re.sub(r",\s*([}\]])", r"\1", cleaned_str) # Remove trailing commas
    cleaned_str = re.sub(r'\bTrue\b', 'true', cleaned_str, flags=re.IGNORECASE) # Standardize booleans
    cleaned_str = re.sub(r'\bFalse\b', 'false', cleaned_str, flags=re.IGNORECASE) # Standardize booleans
    cleaned_str = re.sub(r'\bNone\b', 'null', cleaned_str)
    
    result, in_string, is_escaped = [], False, False
    for char in cleaned_str:
        if char == '"' and not is_escaped: in_string = not in_string
        if in_string and not is_escaped:
            if char == '\n': result.append('\\n'); continue
            if char == '\r': continue
        result.append(char)
        is_escaped = (char == '\\' and not is_escaped)
    return "".join(result).strip()

def _extract_and_parse_json(text: str):
    """Extracts and parses a JSON object from a string that may contain other text."""
    if not text or not text.strip(): raise JSONParsingError("Input text is empty or contains only whitespace.")
    json_str_candidate = _find_json_candidate(text)
    text_to_parse, source_label = (json_str_candidate, "extracted JSON candidate") if json_str_candidate else (text, "full text response")
    cleaned_json_str = _clean_json_string(text_to_parse)
    try:
        return json.loads(cleaned_json_str)
    except json.JSONDecodeError as json_err:
        try:
            pythonic_str = cleaned_json_str.replace('true', 'True').replace('false', 'False').replace('null', 'None')
            return ast.literal_eval(pythonic_str)
        except (ValueError, SyntaxError, MemoryError, TypeError) as ast_err:
            raise JSONParsingError(f"Failed to parse {source_label} as JSON or Python literal.", text=cleaned_json_str, original_exception=ast_err) from ast_err

# ------------------------------------------------------------------------------------
# Image & Audio Processing
# ------------------------------------------------------------------------------------

def convert_to_pil(img_in):
    """Converts a PyTorch tensor or PIL Image into a standard PIL Image object."""
    if img_in is None: return None
    if isinstance(img_in, Image.Image): return img_in
    if torch.is_tensor(img_in):
        arr = img_in[0] if img_in.ndim == 4 else img_in
        arr = arr.detach().cpu().numpy()
        if arr.dtype != np.uint8: arr = np.clip(arr * 255.0, 0, 255).astype(np.uint8)
        return Image.fromarray(arr)
    return None

def encode_image(img):
    """Converts a PIL Image or tensor into a base64 encoded string for web APIs."""
    pil = convert_to_pil(img)
    if pil is None: return None
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def audio_to_spectrogram(audio_path):
    """Converts an audio file into a Mel spectrogram image."""
    if not config.LIBROSA_AVAILABLE or not config.MATPLOTLIB_AVAILABLE: return "[Error: librosa or matplotlib not installed]"
    cache_key = _get_cache_key(audio_path, "spectrogram_v1")
    if config.CACHE.has(cache_key):
        print(f"\033[94m[PromptCrafter] Using cached spectrogram for {os.path.basename(audio_path)}.\033[0m")
        return config.CACHE.get(cache_key)
    try:
        y, sr = librosa.load(audio_path, sr=None)
        S = librosa.feature.melspectrogram(y=y, sr=sr)
        S_dB = librosa.power_to_db(S, ref=np.max)
        fig, ax = plt.subplots(figsize=(10, 4))
        librosa.display.specshow(S_dB, sr=sr, x_axis='time', y_axis='mel', ax=ax)
        ax.set(title=f'Mel spectrogram: {os.path.basename(audio_path)}')
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        image = Image.open(buf)
        config.CACHE.set(cache_key, image)
        return image
    except Exception as e:
        return f"[Error generating spectrogram: {e}]"

# ------------------------------------------------------------------------------------
# Timed Text & Scheduling
# ------------------------------------------------------------------------------------

def _parse_srt_time(time_str: str) -> float:
    """Converts SRT time format 'HH:MM:SS,ms' to seconds."""
    try:
        parts = time_str.replace(',', '.').split(':')
        if len(parts) == 3:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        return 0.0

def _srt_to_timed_segments(srt_text: str):
    """Parses an SRT file into timed segments and a combined text string."""
    segments = []
    pattern = re.compile(r'(\d+)\s*[\r\n]+(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*[\r\n]+([\s\S]*?)(?=\n\n|\Z)', re.MULTILINE)
    for match in pattern.finditer(srt_text):
        text = re.sub(r'<[^>]+>', '', match.group(4)).strip().replace('\n', ' ')
        if text: segments.append((_parse_srt_time(match.group(2)), _parse_srt_time(match.group(3)), text))
    return segments, "\n".join([seg[2] for seg in segments])

def _lrc_to_timed_segments(lrc_text: str):
    """Parses LRC file content into timed segments and a combined text string."""
    segments, raw_lyrics = [], []
    pattern = re.compile(r'\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)')
    for line in lrc_text.splitlines():
        match = pattern.match(line.strip())
        if match:
            minutes, seconds, centiseconds, text = match.groups()
            start_time = int(minutes) * 60 + int(seconds) + float(centiseconds) / 100
            text = text.strip()
            if text:
                segments.append({'start': start_time, 'text': text})
                raw_lyrics.append(text)
    if not segments: return None, lrc_text
    segments.sort(key=lambda x: x['start'])
    timed_tuples = []
    for i in range(len(segments)):
        start, text = segments[i]['start'], segments[i]['text']
        end = segments[i+1]['start'] if i + 1 < len(segments) else start + 5
        timed_tuples.append((start, end, text))
    return timed_tuples, "\n".join(raw_lyrics)

def _process_lyrics_content(content, source_name=""):
    """Detects format (SRT, LRC, plain text) and processes lyrics content accordingly."""
    if not content or content.startswith("[Error"): return content, None
    if (source_name and source_name.lower().endswith(".srt")) or ("-->" in content and re.search(r'\d{2}:\d{2}:\d{2},\d{3}', content)):
        segments, text = _srt_to_timed_segments(content)
        return text, segments
    if (source_name and source_name.lower().endswith(".lrc")) or (re.search(r'\[\d{2}:\d{2}\.\d{2,3}\]', content)):
        timed_segments, parsed_text = _lrc_to_timed_segments(content)
        if timed_segments: return parsed_text, timed_segments
    return content, None

def _get_audio_path(folder_path, file_name):
    """Constructs and verifies the path to an audio file."""
    if not folder_path or not file_name or file_name == "<none>": return None
    full_folder_path = folder_path if os.path.isabs(folder_path) else os.path.join(config.COMFYUI_ROOT_DIR, folder_path)
    filepath = os.path.join(full_folder_path, file_name)
    if os.path.exists(filepath): return filepath
    print(f"\033[93m[PromptCrafter] Warning: Audio file not found at '{filepath}'.\033[0m")
    return None

def _parse_schedule_prompt(prompt):
    """Parses a prompt string to separate the text from a weight if present."""
    weight = 1.0
    if ":" in prompt:
        parts = prompt.split(":")
        if not (len(parts) > 2 or (len(parts) == 2 and not parts[1].strip().replace('.', '', 1).isdigit())):
            try:
                prompt, weight_str = ":".join(parts[:-1]), parts[-1]
                weight = float(weight_str)
                prompt = prompt.strip()
            except (ValueError, IndexError): pass
    return prompt.strip(), weight

def _interpolate_schedule_prompts(schedule, frame_interval):
    """Inserts interpolated keyframes into a schedule to create smooth transitions."""
    if frame_interval <= 0: return schedule
    sorted_frames = sorted(schedule.keys())
    new_schedule = schedule.copy()
    for i in range(len(sorted_frames) - 1):
        start_frame, end_frame = sorted_frames[i], sorted_frames[i+1]
        start_prompt_text, start_weight = _parse_schedule_prompt(schedule[start_frame])
        end_prompt_text, end_weight = _parse_schedule_prompt(schedule[end_frame])
        num_frames_in_segment = end_frame - start_frame
        if num_frames_in_segment <= frame_interval: continue
        for interp_frame in range(start_frame + frame_interval, end_frame, frame_interval):
            t = (interp_frame - start_frame) / num_frames_in_segment
            if start_prompt_text == end_prompt_text:
                interp_weight = start_weight + (end_weight - start_weight) * t
                new_schedule[interp_frame] = f"{json.dumps(start_prompt_text)}:{interp_weight:.4f}"
            else:
                new_schedule[interp_frame] = f"[{start_prompt_text}:{1 - t:.4f}][{end_prompt_text}:{t:.4f}]"
    return collections.OrderedDict(sorted(new_schedule.items()))

def _create_schedule_from_items(items, max_frames, start_frame=0, interpolate=True, interpolation_frame_interval=10):
    """A generic helper to create a keyframe schedule from a list of items (prompts)."""
    num_items = len(items)
    schedule = collections.OrderedDict()
    if num_items == 1:
        schedule[start_frame] = items[0]
    else:
        keyframe_indices = np.linspace(start_frame, max_frames, num=num_items, endpoint=False, dtype=int)
        for i, item in enumerate(items):
            schedule[int(keyframe_indices[i])] = item
    if interpolate:
        schedule = _interpolate_schedule_prompts(schedule, interpolation_frame_interval)
    schedule_items = [f'"{str(key)}": {json.dumps(str(value))}' for key, value in schedule.items()]
    return ",\n".join(schedule_items)

def _get_lyrics_from_input(user_text, lyrics_folder_path, lyrics_file, debug_mode=False):
    """Orchestrates loading lyrics from various sources (file, URL, direct text)."""
    def handle_lyrics_from_file(folder_path, file_name):
        if file_name.strip().startswith(('http://', 'https://')):
            url = file_name.strip()
            ok, content_or_error = _fetch_url_content(url, debug_mode)
            text, segments = _process_lyrics_content(content_or_error, url)
            return text, segments, ("URL", url)
        full_folder_path = folder_path if os.path.isabs(folder_path) else os.path.join(config.COMFYUI_ROOT_DIR, folder_path)
        filepath = os.path.join(full_folder_path, file_name)
        if not os.path.exists(filepath): return f"[Error: File not found at '{filepath}'.]", None, (folder_path, file_name)
        content = safe_read(filepath)
        text, segments = _process_lyrics_content(content, file_name)
        return text, segments, (folder_path, file_name)

    if lyrics_folder_path and lyrics_file and lyrics_file != "<none>": return handle_lyrics_from_file(lyrics_folder_path, lyrics_file)
    if user_text and user_text.strip() and user_text.strip() != config.DEFAULT_PROMPT_TEXT:
        text, segments = _process_lyrics_content(user_text)
        return text, segments, None
    return "", None, None

# ------------------------------------------------------------------------------------
# Web & Content Fetching
# ------------------------------------------------------------------------------------

def _fetch_url_content(url, debug_mode=False):
    """Fetches and cleans text content from a URL, with support for PDF text extraction."""
    try:
        print(f"\033[94m[PromptCrafter] URL detected. Fetching content from: {url}\033[0m")
        response = config.SHARED_SESSION.get(url, timeout=20)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '').lower()

        if 'application/pdf' in content_type:
            if not config.PYPDF_AVAILABLE: return False, "[Error: URL points to a PDF, but `pypdf` is not installed.]"
            try:
                pdf_file = io.BytesIO(response.content)
                reader = PdfReader(pdf_file)
                text = "\n".join(page.extract_text() for page in reader.pages if page.extract_text())
                text = re.sub(r'\s+', ' ', text).strip()
                _debug_print(debug_mode, "Fetched PDF Content (Extracted)", (text[:1000] + "...") if len(text) > 1000 else text)
                return True, text
            except Exception as e: return False, f"[Error extracting text from PDF: {e}]"
        elif 'text' in content_type:
            text = response.text
            text = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', text, flags=re.DOTALL | re.IGNORECASE)
            body_match = re.search(r'<body\b[^>]*>(.*?)</body>', text, flags=re.DOTALL | re.IGNORECASE)
            if body_match: text = body_match.group(1)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            _debug_print(debug_mode, "Fetched URL Content (Cleaned)", (text[:1000] + "...") if len(text) > 1000 else text)
            return True, text
        else:
            return False, f"[Error: URL content type is not supported ({content_type})]"
    except requests.exceptions.RequestException as e:
        return False, f"[Error fetching URL: {e}]"

def _should_perform_web_search(user_query, model, seed, debug_mode, timeout=40):
    """Uses an LLM to determine if a user's query requires a web search."""
    from . import api_clients
    if not config.DUCKDUCKGO_SEARCH_AVAILABLE or not user_query or user_query.strip() == config.DEFAULT_PROMPT_TEXT:
        return False, None
    prompt_template = textwrap.dedent("""
        Analyze the user's query. Does it ask about a recent event (in the last year), a topic where information changes rapidly (like stock prices or product releases), or a person/topic that is not a matter of common, stable knowledge?
        - If it's a general knowledge question (e.g., "What is the capital of France?"), a web search is NOT needed.
        - If it asks for a creative response (e.g., "Write a poem about a cat"), a web search is NOT needed.
        - If it asks about a very recent event or a rapidly changing topic (e.g., "What were the key announcements from Apple's last event?"), a web search IS needed.
        --- USER QUERY ---\n{query}\n--- END USER QUERY ---
        Based on this analysis, respond with ONLY a JSON object.
        - If a search is needed, use this format: {{"search_needed": true, "search_query": "optimized search keywords"}}
        - If no search is needed, use this format: {{"search_needed": false, "search_query": null}}
    """)
    check_prompt = prompt_template.format(query=user_query)
    ok, result_json = api_clients._reason_with_model(model, check_prompt, use_chat_api=True, temperature=0.0, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title="Web Search Check")
    if ok and isinstance(result_json, dict) and result_json.get("search_needed") and result_json.get("search_query"):
        return True, result_json.get("search_query")
    return False, None

def _perform_web_search(query: str, num_results=3, debug_mode=False, fast_search=False):
    """Performs a web search using DuckDuckGo and returns a combined context string."""
    if not config.DUCKDUCKGO_SEARCH_AVAILABLE: return "[Web search is disabled because `duckduckgo-search` is not installed.]"
    print(f"\033[94m[PromptCrafter] Performing web search for: '{query}'\033[0m")
    if fast_search: print("\033[94m[PromptCrafter] Fast search enabled. Using snippets only.\033[0m")
    search_context = ""
    try:
        with DDGS(timeout=20) as ddgs:
            results = list(itertools.islice(ddgs.text(query, region='wt-wt', safesearch='moderate', timelimit='y'), num_results))
            if not results: return "[No web search results found.]"
            if fast_search:
                for result in results:
                    search_context += f"--- Web Result from {result.get('href')} ---\nTitle: {result.get('title', 'N/A')}\nSnippet: {result.get('body', 'N/A')}\n\n"
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=num_results) as executor:
                    future_to_url = {executor.submit(_fetch_url_content, result.get('href'), debug_mode): result for result in results if result.get('href')}
                    fetched_contents = {}
                    for future in concurrent.futures.as_completed(future_to_url):
                        result_meta = future_to_url[future]
                        url = result_meta.get('href')
                        try:
                            ok, content = future.result()
                            fetched_contents[url] = (ok, content, result_meta)
                        except Exception as exc:
                            fetched_contents[url] = (False, f"[Error fetching URL content: {exc}]", result_meta)
                for result in results:
                    url = result.get('href')
                    if url in fetched_contents:
                        ok, content, result_meta = fetched_contents[url]
                        search_context += f"--- Web Result from {url} ---\nTitle: {result_meta.get('title', 'N/A')}\nSnippet: {result_meta.get('body', 'N/A')}\n"
                        if ok and content:
                            clean_content = TextCleaner.single_paragraph(content)
                            search_context += f"Content Summary: {clean_content[:1500]}...\n\n"
                        else:
                            search_context += f"Content: [Could not fetch or process content: {content}]\n\n"
        _debug_print(debug_mode, "Web Search Context", search_context)
        return search_context.strip()
    except Exception as e:
        print(f"\033[93m[PromptCrafter] Warning: An error occurred during web search: {e}\033[0m")
        return f"[An error occurred during web search: {e}]"

# ------------------------------------------------------------------------------------
# Large Text Summarization (Map-Reduce)
# ------------------------------------------------------------------------------------

def _split_text_into_chunks(text, chunk_size_words):
    """
    Yields sentence-aware chunks of a target word size from a large text.
    This is a generator function to be memory-efficient with very large texts.
    """
    if not text: return

    # Use finditer to create an iterator of sentences, avoiding a large list in memory.
    sentence_matches = re.finditer(r'[^.!?]+[.!?]', text.strip())
    current_chunk_sentences, current_word_count = [], 0

    for match in sentence_matches:
        sentence = match.group(0).strip()
        if not sentence: continue

        sentence_word_count = len(sentence.split())
        if current_chunk_sentences and (current_word_count + sentence_word_count > chunk_size_words):
            yield " ".join(current_chunk_sentences)
            current_chunk_sentences, current_word_count = [], 0
        current_chunk_sentences.append(sentence)
        current_word_count += sentence_word_count

    if current_chunk_sentences:
        yield " ".join(current_chunk_sentences)

def _summarize_large_text(text, chunk_size_words, model, temperature, seed, debug_mode, timeout, strategy="default", user_query=None):
    """Performs a hierarchical map-reduce summarization on large text."""
    from . import api_clients
    final_strategy = strategy
    if user_query:
        simple_summarize_queries = ["summarize", "summarize this", "give me a summary", "can you summarize this", "tldr", "tl;dr", "summary"]
        if user_query.lower().strip(" .?!") in simple_summarize_queries:
            print("\033[94m[PromptCrafter] Simple summarize query detected. Switching to faster 'Extractive' strategy.\033[0m")
            final_strategy = "extractive"

    chunk_iterator = _split_text_into_chunks(text, chunk_size_words)
    map_prompt_template = "Extract the most important sentences from the following text chunk. Return ONLY the extracted sentences.\n\nTEXT CHUNK:\n{chunk}" if final_strategy == "extractive" else "Concisely summarize the key points of the following text chunk. Focus on factual information, names, and key events. Return ONLY the summary.\n\nTEXT CHUNK:\n{chunk}"
    
    def map_chunk_to_summary(chunk, i):
        from . import api_clients
        ok, summary_or_err = api_clients.query_model_auto(model, map_prompt_template.format(chunk=chunk), prefer_chat=True, temperature=temperature, seed=seed, debug_mode=debug_mode, timeout=timeout, debug_title=f"Summarize Chunk {i+1}")
        if ok: return TextCleaner.single_paragraph(summary_or_err)
        print(f"\033[93m[PromptCrafter] Warning: Could not summarize chunk {i+1}. Error: {summary_or_err}\033[0m")
        return None

    print(f"\033[94m[PromptCrafter] Starting parallel summarization of text chunks (Map phase)...\033[0m")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        # Use map to process chunks as they are yielded, improving memory efficiency
        future_summaries = executor.map(map_chunk_to_summary, chunk_iterator, itertools.count(1))
        successful_summaries = [s for s in future_summaries if s]

    if not successful_summaries: return "[Error: All text chunks failed to summarize.]"

    current_summaries, reduce_level, reduce_group_size = successful_summaries, 1, 5
    while len(current_summaries) > 1:
        print(f"\033[94m[PromptCrafter] Combining {len(current_summaries)} summaries in parallel (Reduce level {reduce_level})...\033[0m")
        groups_to_process = ["\n\n---\n\n".join(current_summaries[i:i + reduce_group_size]) for i in range(0, len(current_summaries), reduce_group_size)]
        
        def reduce_group(group, i):
            from . import api_clients
            ok, summary_or_err = api_clients.query_model_auto(model, f"The following text consists of several summaries of a larger document. Synthesize these summaries into one final, coherent summary of the entire document.\n\nSUMMARIES:\n{group}", prefer_chat=True, temperature=temperature, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title=f"Reduce Level {reduce_level} - Group {i+1}/{len(groups_to_process)}")
            if ok: return TextCleaner.single_paragraph(summary_or_err)
            print(f"\033[93m[PromptCrafter] Warning: Reduce step failed for group {i+1} at level {reduce_level}. Error: {summary_or_err}\033[0m")
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            future_to_index = {executor.submit(api_clients.query_model_auto, model, f"The following text consists of several summaries of a larger document. Synthesize these summaries into one final, coherent summary of the entire document.\n\nSUMMARIES:\n{group}", prefer_chat=True, temperature=temperature, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title=f"Reduce Level {reduce_level} - Group {i+1}/{len(groups_to_process)}"): i for i, group in enumerate(groups_to_process)}
            from . import api_clients
            results = [None] * len(groups_to_process)
            for future in concurrent.futures.as_completed(future_to_index):
                index = future_to_index[future]
                try:
                    ok, summary_or_err = future.result()
                    if ok: results[index] = TextCleaner.single_paragraph(summary_or_err)
                    else: print(f"\033[93m[PromptCrafter] Warning: Reduce step failed for group {index+1} at level {reduce_level}. Error: {summary_or_err}\033[0m")
                except Exception as exc: print(f"\033[91m[PromptCrafter] An unexpected error occurred during reduce step for group {index+1}: {exc}\033[0m")
        current_summaries = [s for s in results if s] # Filter out failed reductions
        if not current_summaries:
            print(f"\033[91m[PromptCrafter] Error: All groups failed at reduce level {reduce_level}. Returning previous level's summaries.\033[0m")
            return "\n\n".join(groups_to_process)
        reduce_level += 1

    final_summary = current_summaries[0] if current_summaries else "[Error: Summarization resulted in an empty string.]"

    if user_query and user_query.strip() and user_query.strip() != config.DEFAULT_PROMPT_TEXT:
        print("\033[94m[PromptCrafter] Performing final pass to tailor summary to user query...\033[0m")
        final_pass_prompt = textwrap.dedent(f"""
            You are a synthesis expert. Based on the following comprehensive summary, provide a concise and direct answer to the user's original query.
            Focus only on the information relevant to the query.
            --- COMPREHENSIVE SUMMARY ---\n{final_summary}\n--- END SUMMARY ---
            --- USER's ORIGINAL QUERY ---\n{user_query}\n--- END QUERY ---
            Return ONLY the final, targeted answer.
        """)
        from . import api_clients
        ok, final_answer = api_clients.query_model_auto(model, final_pass_prompt, prefer_chat=True, temperature=temperature, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title="Final Summary Pass")
        if ok: return TextCleaner.single_paragraph(final_answer)
        else: print(f"\033[93m[PromptCrafter] Warning: Final summary pass failed. Returning the general summary. Error: {final_answer}\033[0m")

    return final_summary

# ------------------------------------------------------------------------------------
# Advanced Prompt Generation Helpers (moved from nodes.py)
# ------------------------------------------------------------------------------------
def _extract_mandatory_tokens_with_model(image_context: str, user_text: str, run_config: 'config.PromptCrafterRunConfig'):
    cache_key = _get_cache_key(run_config.model, image_context, run_config.use_chat_api, run_config.temperature, run_config.seed, user_text, "extract_tokens", run_config.debug_mode)
    from . import api_clients
    if config.CACHE.has(cache_key):
        print("\033[94m[PromptCrafter] Using cached token extraction.\033[0m")
        return True, config.CACHE.get(cache_key)

    ok_prim, primary_subjects_or_err = _extract_primary_subjects(user_text, run_config)
    if not ok_prim: return False, primary_subjects_or_err
    if user_text.strip() and user_text.strip() != config.DEFAULT_PROMPT_TEXT and not primary_subjects_or_err:
        return False, "Model did not identify any required subjects from your instructions. Please try rephrasing."

    ok_sec, secondary_subjects_or_err = _extract_secondary_subjects(image_context, run_config)
    secondary_subjects = secondary_subjects_or_err if ok_sec else []
    if not ok_sec: print(f"\033[93m[PromptCrafter] Warning: Could not extract secondary subjects: {secondary_subjects_or_err}\033[0m")

    primary_lower = {p.lower() for p in primary_subjects_or_err}
    clean_sec = [item for item in secondary_subjects if str(item).lower() not in primary_lower]

    tagged = {"primary": [f"[PRIMARY] {s}" for s in primary_subjects_or_err], "secondary": [f"[SECONDARY][OPTIONAL] {s}" for s in clean_sec]}
    tagged["allowed_list"] = _unique_keep_order(primary_subjects_or_err + clean_sec)
    config.CACHE.set(cache_key, tagged)
    return True, tagged

def _extract_subjects(source_text, source_label, instruction_text, run_config, debug_title, post_process_func=None):
    from . import api_clients
    if not source_text or not source_text.strip() or source_text.strip() == config.DEFAULT_PROMPT_TEXT: return True, []
    ask_prompt = textwrap.dedent(f"""
        {instruction_text}
        Return ONLY a JSON array of strings: ["item1", "item2", ...]. No commentary.
        --- {source_label.upper()} ---\n{source_text}\n--- END {source_label.upper()} ---
    """)
    ok, items_or_err = api_clients._reason_with_model(run_config.model, ask_prompt, run_config.use_chat_api, run_config.temperature, run_config.seed, debug_mode=run_config.debug_mode, debug_title=debug_title)
    if not ok: return False, items_or_err
    return True, _post_process_extracted_subjects(items_or_err, post_process_func)

def _extract_primary_subjects(user_text, run_config):
    instruction = "From the USER INSTRUCTIONS, extract a literal list of all visual subjects, characters, and specific named objects the user explicitly wants to see in the final scene. IGNORE musical instruments, audio descriptions, tempo notes, and genre descriptions."
    def clean_func(item_text):
        cleaned = re.sub(r'\s*\bfrom image \d+\b\s*', ' ', item_text, flags=re.I).strip()
        stop_phrases = {"main subjects", "the subjects", "the characters", "subjects from the image", "characters from the image", "an epic scene", "a scene", "main subject", "the main subject", "the main subjects in the images", "subjects in the images"}
        return "" if cleaned.lower().strip(".,'\"- ") in stop_phrases else cleaned
    return _extract_subjects(source_text=user_text, source_label="USER INSTRUCTIONS", instruction_text=instruction, run_config=run_config, debug_title="Extract Primary Subjects", post_process_func=clean_func)

def _extract_secondary_subjects(image_context, run_config):
    if not image_context or image_context.startswith("No reference images provided."): return True, []
    instruction = "From the IMAGE DESCRIPTIONS, extract a list of all subjects, characters, and major objects."
    return _extract_subjects(source_text=image_context, source_label="IMAGE DESCRIPTIONS", instruction_text=instruction, run_config=run_config, debug_title="Extract Secondary Subjects", post_process_func=lambda item_text: re.sub(r'\s+', ' ', item_text).strip())

def _post_process_extracted_subjects(items_list, post_process_func=None):
    if not items_list or not isinstance(items_list, list): return []
    processed_items = []
    for item in items_list:
        if not item: continue
        processed_item = str(item)
        if post_process_func: processed_item = post_process_func(processed_item)
        if processed_item and processed_item.strip(): processed_items.append(processed_item.strip())
    return _unique_keep_order(processed_items)[:40]

def _unique_keep_order(seq):
    seen, result = set(), []
    for item in seq:
        if not item: continue
        key = item.lower().strip()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result

def _deep_think_and_refine(model, generation_prompt_text, max_iterations=3, confidence_threshold=0.8, **kwargs):
    from . import api_clients
    core_objectives = _summarize_deep_think_objectives(model, generation_prompt_text, **kwargs)
    _debug_print(kwargs.get("debug_mode", False), "Deep Think - Core Objectives", core_objectives or "Could not be summarized.")

    # --- Persistent State Logic ---
    # Use a cache key based on the core request to persist the refinement state.
    state_cache_key = _get_cache_key(model, generation_prompt_text, "deep_think_state_v4")
    current_prompt, history = "", []
    if config.CACHE.has(state_cache_key):
        print("\033[94m[PromptCrafter] Deep Think: Resuming from persistent state.\033[0m")
        loaded_state = config.CACHE.get(state_cache_key)
        if isinstance(loaded_state, tuple) and len(loaded_state) == 2:
            current_prompt, history = loaded_state
        else:
            print("\033[93m[PromptCrafter] Warning: Invalid Deep Think state in cache. Starting fresh.\033[0m")

    for i in range(max_iterations):
        iteration_num = len(history) + 1
        _debug_print(kwargs.get("debug_mode", False), f"Deep Think - Iteration {iteration_num} Start", f"Input Prompt:\n{current_prompt or '(First iteration, generating initial draft)'}")
        if not current_prompt: # Only do initial generation if we have no prompt to start with
            initial_gen_template = textwrap.dedent(f"""
                You are a professional cinematic prompt engineer and a meticulous editor. Your task is to perform two steps:
                1. **GENERATE**: Read the "FULL REQUEST" and generate a high-quality, polished prompt that fulfills all "CORE OBJECTIVES".
                2. **CRITIQUE**: Immediately after generating, critique your own work. Analyze if your generated prompt fully satisfies all "CORE OBJECTIVES". Provide a confidence score (0.0-1.0) and a brief critique.
                --- FULL REQUEST (for generation) ---\n{generation_prompt_text}\n--- END FULL REQUEST ---
                --- CORE OBJECTIVES (for self-critique) ---\n{core_objectives}\n--- END CORE OBJECTIVES ---
                Return your response as a single JSON object with three keys: `refined_prompt` (string), `confidence_score` (float), and `critique` (string).
            """).strip()
            ok, critique_json = api_clients._reason_with_model(model, initial_gen_template, **kwargs, debug_title=f"Deep Think - Initial Generation & Critique")
        else:
            ok, critique_json = _run_deep_think_iteration(current_prompt, history, core_objectives, model, **kwargs)
        
        if not ok or not isinstance(critique_json, dict):
            print(f"\033[93m[PromptCrafter] Warning: Deep Think critique failed. Proceeding with current prompt. Error: {critique_json}\033[0m")
            return (True, current_prompt) if current_prompt else (False, "Deep Think process failed at initial generation.")
        
        confidence_score = critique_json.get("confidence_score", 0.0)
        refined_prompt = critique_json.get("refined_prompt")
        critique = critique_json.get("critique", "No critique provided.")
        
        if not refined_prompt:
            print("\033[93m[PromptCrafter] Warning: Deep Think iteration did not return a refined prompt. Using previous version.\033[0m")
            if not current_prompt: return False, "Deep Think process failed to generate an initial prompt."
            refined_prompt = current_prompt

        history.append((current_prompt or "Initial Generation", critique))
        _debug_print(kwargs.get("debug_mode", False), f"Deep Think - Iteration {iteration_num} Critique Result", f"Confidence: {confidence_score}\nCritique: {critique}")

        # Persist the new state to the cache after each successful iteration
        config.CACHE.set(state_cache_key, (refined_prompt, history))
        
        if confidence_score >= confidence_threshold:
            _debug_print(kwargs.get("debug_mode", False), f"Deep Think - Confidence Threshold ({confidence_threshold}) Met", f"Final Prompt: {refined_prompt}")
            return True, refined_prompt
        if refined_prompt.strip() == current_prompt.strip():
            _debug_print(kwargs.get("debug_mode", False), "Deep Think - Prompt Stabilized", "Refined prompt is identical to the previous one. Finalizing.")
            return True, refined_prompt
        current_prompt = refined_prompt
    
    print("\033[93m[PromptCrafter] Warning: Deep Think loop finished without high confidence. Returning last prompt.\033[0m")
    return True, current_prompt

def _summarize_deep_think_objectives(model, initial_prompt_text, **kwargs):
    from . import api_clients
    summarize_template = textwrap.dedent(f"""
        You are a task analysis expert. Read the following detailed request and summarize it into a concise list of core objectives and constraints for a prompt engineer.
        Focus on mandatory subjects, style requirements, and negative constraints.
        --- FULL REQUEST ---\n{initial_prompt_text}\n--- END FULL REQUEST ---
        Return ONLY the summarized list of objectives.
    """).strip()
    summary_kwargs = kwargs.copy()
    summary_kwargs['temperature'] = 0.1
    summary_kwargs.pop('debug_title', None)
    ok_summary, core_objectives = api_clients.query_model_auto(model, summarize_template, **summary_kwargs, debug_title="Deep Think - Summarize Objectives")
    if not ok_summary:
        print("\033[93m[PromptCrafter] Warning: Deep Think objective summarization failed. Using full prompt text for critiques.\033[0m")
        return initial_prompt_text
    return core_objectives

def _run_deep_think_iteration(current_prompt, history, core_objectives, model, **kwargs):
    from . import api_clients
    history_log = ""
    if history:
        history_log = "--- REFINEMENT HISTORY (for context) ---\n"
        for j, (p, c) in enumerate(history[-2:]): history_log += f"Critique of previous version: {c}\n"
        history_log += "--- END REFINEMENT HISTORY ---\n\n"
    
    critique_template = textwrap.dedent(f"""
        You are a meticulous prompt editor. Your task is to critique and refine a generated prompt based on a set of core objectives.
        --- CORE OBJECTIVES ---\n{core_objectives}\n--- END CORE OBJECTIVES ---
        {history_log}--- CURRENT PROMPT TO CRITIQUE ---\n{current_prompt}\n--- END CURRENT PROMPT ---
        CRITIQUE INSTRUCTIONS:
        1. **Analyze**: Does the "CURRENT PROMPT" fully satisfy all "CORE OBJECTIVES"?
        2. **Review History**: Check the "REFINEMENT HISTORY". Has the current text addressed previous critiques?
        3. **Score & Refine**: Provide a confidence score (0.0-1.0). If the score is less than 1.0, provide a concise critique and a `refined_prompt` that fixes the issues.
        Return your response as a single JSON object with three keys: `confidence_score` (float), `critique` (string), and `refined_prompt` (string).
    """).strip()
    
    reason_kwargs = kwargs.copy()
    reason_kwargs.pop('images', None); reason_kwargs.pop('images_b64', None);
    if 'prefer_chat' in reason_kwargs: reason_kwargs['use_chat_api'] = reason_kwargs.pop('prefer_chat')
    return api_clients._reason_with_model(model, critique_template, **reason_kwargs, debug_title=f"Deep Think - Critique Iteration {len(history) + 1}")

def _generate_negative_prompt(scene_prompt, run_config, user_negative_prompt=""):
    """Generates a comprehensive negative prompt based on keywords and context."""
    if not scene_prompt or "Ollama error" in scene_prompt: return ""
    cache_key = _get_cache_key(scene_prompt, user_negative_prompt, "gen_negative_v7_local")
    if config.CACHE.has(cache_key): return config.CACHE.get(cache_key)

    keywords = set(config.NEGATIVE_KEYWORDS["quality"] + config.NEGATIVE_KEYWORDS["composition"])
    keywords.update([kw.strip() for kw in config.DEFAULT_CHINESE_NEGATIVE_PROMPT.split('，') if kw.strip()])

    prompt_lower = scene_prompt.lower()
    for trigger, neg_words in config.NEGATIVE_KEYWORDS["contextual"].items():
        if re.search(r'\b' + re.escape(trigger) + r'\b', prompt_lower): keywords.update(neg_words)

    if user_negative_prompt:
        keywords.update([kw.strip() for kw in user_negative_prompt.replace("\n", ",").split(',') if kw.strip()])
    
    final_neg_prompt = ", ".join(sorted(list(keywords)))
    config.CACHE.set(cache_key, final_neg_prompt)
    return final_neg_prompt

def _simplify_for_diffusion(prompt_text, user_text, run_config):
    """Restructures a narrative prompt into a weighted, direct prompt for diffusion models."""
    from . import api_clients
    if not prompt_text or not run_config.simplify_for_diffusion: return prompt_text, ""
    cache_key = _get_cache_key(prompt_text, user_text, run_config.model, "simplify_v3_aggressive")
    if config.CACHE.has(cache_key):
        cached_data = config.CACHE.get(cache_key)
        return cached_data.get("positive_prompt", prompt_text), cached_data.get("negative_keywords", "")
    
    simplification_template = textwrap.dedent(f"""
        You are an expert in Stable Diffusion prompting. Your task is to restructure a narrative prompt into a highly effective, direct prompt, ensuring absolute adherence to the user's core request.
        **Part 1: Positive Prompt Generation**
        1. **Analyze Core Request:** The `USER'S CORE REQUEST` is the source of truth. Identify the most critical, non-negotiable subjects and attributes.
        2. **Structure for Complex Scenes:** If there are multiple subjects, describe their interactions and spatial relationships.
        3. **Prioritize and Weight:** Create a new prompt starting with the main subject. Use HEAVY weighting like `(description:1.5)` on the most critical attributes from step 1 to FORCE the model's attention.
        4. **Clarify and Synthesize:** Rephrase the rest of the prompt into clear, comma-separated clauses. Remove narrative fluff.
        **Part 2: Negative Prompt Generation**
        5. **Extract Negative Constraints:** Analyze the `USER'S CORE REQUEST` for explicit negative instructions (e.g., "no buildings").
        6. **Generate Counter-Negatives:** Based on the core positive attributes, identify their direct opposites (e.g., if "white dress" is requested, a counter-negative is "black dress").
        --- USER'S CORE REQUEST (Source of Truth) ---\n{user_text}\n--- END USER'S CORE REQUEST ---
        --- NARRATIVE PROMPT (to be restructured) ---\n{prompt_text}\n--- END NARRATIVE PROMPT ---
        Return ONLY a JSON object with two keys: `positive_prompt` (string) and `negative_keywords` (string).
    """)
    ok, result_json = api_clients.query_model_auto(run_config.model, simplification_template, prefer_chat=run_config.use_chat_api, temperature=0.1, seed=run_config.seed, timeout=90, debug_mode=run_config.debug_mode, debug_title="Simplify for Diffusion Model (Aggressive)")
    if ok and isinstance(result_json, dict):
        positive = TextCleaner.single_paragraph(result_json.get("positive_prompt", prompt_text))
        negatives = result_json.get("negative_keywords", "")
        config.CACHE.set(cache_key, {"positive_prompt": positive, "negative_keywords": negatives})
        return positive, negatives
    return prompt_text, ""

def _split_text_into_scenes_with_ai(text, run_config):
    """Uses an LLM to split a single block of text into a list of scenes."""
    from . import api_clients
    prompt_template = textwrap.dedent(f"""
        You are an expert film script analyst. Read the following story. Your task is to break it down into distinct, logical scenes or camera shots.
        --- STORY ---\n{text}\n--- END STORY ---
        INSTRUCTIONS: Identify the natural breaking points. Return ONLY a JSON object with a single key, "scenes", which contains an array of strings. Each string is one scene.
        Example: Input: "A woman walks to a stag and climbs on its back. She rides it across a meadow as an eagle soars above." Output: {{"scenes": ["A woman walks to a stag and climbs on its back.", "The woman rides the stag across a meadow as an eagle soars above."]}}
    """).strip()
    ok, result_json = api_clients._reason_with_model(run_config.model, prompt_template, run_config.use_chat_api, 0.1, run_config.seed, debug_mode=run_config.debug_mode, debug_title="AI Scene Splitter")
    if ok and isinstance(result_json, dict) and "scenes" in result_json and isinstance(result_json["scenes"], list) and result_json["scenes"]:
        print(f"\033[92m[PromptCrafter] AI successfully split the story into {len(result_json['scenes'])} scenes.\033[0m")
        return result_json["scenes"]
    print("\033[93m[PromptCrafter] Warning: AI scene splitting failed. Treating the entire text as a single scene.\033[0m")
    return [text]

def _generate_storyboard_from_instruction_with_ai(user_request, image_context, primary_subjects, run_config):
    """Uses an LLM to generate a storyboard from a high-level user instruction."""
    from . import api_clients
    print("\033[94m[PromptCrafter] Using AI to generate storyboard from user instruction...\033[0m")
    prompt_template = textwrap.dedent(f"""
        You are an expert film director. Your task is to break down a user's high-level request into a sequence of distinct, cinematic video scenes.
        --- USER REQUEST ---\n{user_request}\n--- KEY SUBJECTS (from reference images) ---\n{json.dumps(primary_subjects)}\n--- INSPIRATIONAL CONTEXT (from reference images) ---\n{image_context}
        --- INSTRUCTIONS ---
        1. Read the user's request and analyze the subjects and context.
        2. Create a storyboard as a sequence of 3-5 distinct scenes that logically follow the user's request.
        3. For each scene, suggest a cinematic camera shot (e.g., "wide shot", "close-up", "tracking shot").
        4. Return ONLY a JSON object with a single key, "scenes", which contains an array of strings. Each string is a scene description.
    """).strip()
    ok, result_json = api_clients._reason_with_model(run_config.model, prompt_template, run_config.use_chat_api, 0.2, run_config.seed, debug_mode=run_config.debug_mode, debug_title="AI Storyboard Generation")
    if ok and isinstance(result_json, dict) and "scenes" in result_json and isinstance(result_json["scenes"], list) and result_json["scenes"]:
        print(f"\033[92m[PromptCrafter] AI successfully generated a storyboard with {len(result_json['scenes'])} scenes.\033[0m")
        return result_json["scenes"]
    return []