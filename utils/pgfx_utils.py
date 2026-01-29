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
import requests

# Local module imports
from ..core import pgfx_config as config
from ..core import pgfx_api_clients as api_clients
from . import pgfx_json_utils as json_utils

# >>> UTILS_NORMALISE_MODEL >>>

def normalise_model_name(raw_name: str) -> str | None:
    """Convert UI‑provided model strings into the ``provider/model`` format required by Ollama.

    * Returns ``None`` for clearly invalid placeholders (e.g. ``NO_API_MODELS_FOUND``).
    * If the string already contains a slash it is returned unchanged.
    * Otherwise it is assumed to be a GGUF filename and ``gguf/`` is prefixed.
    """
    if not raw_name:
        return None

    clean = raw_name.strip()
    if clean.upper() in {"NO_API_MODELS_FOUND", "NO_MODELS_FOUND", "NONE", "NULL"}:
        return None
    if "/" in clean:
        return clean
    return f"gguf/{clean}"
# <<< UTILS_NORMALISE_MODEL <<<

# --- Dependency-specific imports ---
if config.PYPDF_AVAILABLE: from pypdf import PdfReader
if config.DUCKDUCKGO_SEARCH_AVAILABLE: from duckduckgo_search import DDGS
if config.LIBROSA_AVAILABLE: import librosa
if config.MATPLOTLIB_AVAILABLE:
    try:
        import matplotlib
        matplotlib.use('Agg')  # Use a non-interactive backend to prevent display errors
        import matplotlib.pyplot as plt
    except ImportError:
        matplotlib = None
        plt = None
else:
    matplotlib = None
    plt = None

# ------------------------------------------------------------------------------------
# General Utilities
# ------------------------------------------------------------------------------------

def _debug_print(debug_mode, title, content):
    """Prints debug information to the console if debug_mode is True."""
    if debug_mode:
        if os.name == 'nt':
            print(f"\n{'='*20} DEBUG: {title} {'='*20}")
            print(content)
            print(f"{ '='* (42 + len(title))}\n")
        else:
            print(f"\n\033[95m{'='*20} DEBUG: {title} {'='*20}\033[0m")
            print(content)
            print(f"\033[95m{'='* (42 + len(title))}\033[0m\n")

def _hash_none(data, hasher, update_hash_func):
    hasher.update(b"NoneType")

def _hash_primitive(data, hasher, update_hash_func):
    hasher.update(b"primitive")
    hasher.update(repr(data).encode('utf-8'))

def _hash_str_bytes(data, hasher, update_hash_func):
    hasher.update(b"str_or_bytes")
    hasher.update(data if isinstance(data, bytes) else data.encode('utf-8'))

def _hash_tensor(data, hasher, update_hash_func):
    hasher.update(b"torch.Tensor")
    hasher.update(str(data.shape).encode('utf-8'))
    hasher.update(str(data.dtype).encode('utf-8'))
    hasher.update(str(data.device).encode('utf-8'))
    tensor_bytes = data.cpu().numpy().tobytes()
    hasher.update(tensor_bytes[:1024])
    hasher.update(tensor_bytes[-1024:])

def _hash_pil_image(data, hasher, update_hash_func):
    hasher.update(b"PIL.Image")
    hasher.update(data.tobytes())

def _hash_list_tuple(data, hasher, update_hash_func):
    hasher.update(b"list_or_tuple")
    for item in data:
        update_hash_func(item)

def _hash_set(data, hasher, update_hash_func):
    hasher.update(b"set")
    for item in sorted(list(data), key=repr):
        update_hash_func(item)

def _hash_dict(data, hasher, update_hash_func):
    hasher.update(b"dict")
    try:
        sorted_keys = sorted(data.keys())
    except TypeError:
        sorted_keys = sorted(data.keys(), key=repr)
    for key in sorted_keys:
        update_hash_func(key)
        update_hash_func(data[key])

# Dispatch dictionary for type-specific hashing functions.
_HASH_DISPATCH = {
    type(None): _hash_none,
    str: _hash_str_bytes,
    bytes: _hash_str_bytes,
    int: _hash_primitive,
    float: _hash_primitive,
    bool: _hash_primitive,
    torch.Tensor: _hash_tensor,
    Image.Image: _hash_pil_image,
    list: _hash_list_tuple,
    tuple: _hash_list_tuple,
    set: _hash_set,
    dict: _hash_dict,
}

def _get_cache_key(*args, **kwargs):
    """
    Creates a unique and deterministic key for caching based on the node's inputs.
    This function recursively handles complex data types for robust and efficient hashing.
    """
    hasher = hashlib.sha256()
    all_args = list(args)

    def update_hash(data):
        """A nested helper to recursively update the hash with type-specific handling."""
        data_type = type(data)
        handler = _HASH_DISPATCH.get(data_type)

        if handler:
            handler(data, hasher, update_hash)
            return

        # --- Fallback for unhandled or complex objects ---
        try:
            hasher.update(b"pickled_object")
            hasher.update(pickle.dumps(data))
        except (pickle.PicklingError, TypeError):
            if hasattr(data, '__dict__'):
                hasher.update(b"object_dict")
                update_hash(data.__dict__)
            else:
                hasher.update(b"repr_fallback")
                hasher.update(repr(data).encode('utf-8'))

    for arg in all_args:
        update_hash(arg)

    # Sort kwargs by key to ensure deterministic hash order
    for key in sorted(kwargs.keys()):
        update_hash(key)
        update_hash(kwargs[key])

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
        from langdetect import detect, LangDetectException
        LANG_MAP = {'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German', 'it': 'Italian', 'pt': 'Portuguese', 'nl': 'Dutch', 'ru': 'Russian', 'ja': 'Japanese', 'ko': 'Korean', 'zh-cn': 'Chinese (Simplified)', 'zh-tw': 'Chinese (Traditional)', 'ar': 'Arabic', 'hi': 'Hindi'}
        lang_code = detect(text[:500])
        return LANG_MAP.get(lang_code, fallback)
    except LangDetectException:
        return fallback

def _get_and_create_output_dir(output_path: str, debug_mode: bool = False) -> str | None:
    """Constructs, validates, and creates a sanitized output directory, returning the absolute path or None on failure."""
    if not output_path or not isinstance(output_path, str):
        print(f"\033[91m[PromptCrafter] Error: Invalid output_path provided: {output_path}\033[0m")
        return None

    base_dir = os.path.abspath(os.path.join(config.COMFYUI_ROOT_DIR, "output"))
    
    # Sanitize the subdirectory part of the path to remove invalid characters and prevent traversal.
    # This is more robust than just lstrip.
    invalid_chars = r'[<>:"/\\|?*]'
    safe_subdir = re.sub(invalid_chars, '_', output_path.strip())
    safe_subdir = os.path.normpath(safe_subdir)

    out_dir = os.path.join(base_dir, safe_subdir)

    # Security check: ensure the final path is within the intended output directory
    if os.path.commonpath([base_dir]) != os.path.commonpath([base_dir, out_dir]):
        print(f"\033[91m[PromptCrafter] Error: Invalid output path '{output_path}' attempts to go outside the ComfyUI output directory.\033[0m")
        return None
        
    if os.path.exists(out_dir):
        if not os.path.isdir(out_dir):
            print(f"\033[91m[PromptCrafter] Error: A file exists at the target output path '{out_dir}' and is blocking directory creation.\033[0m")
            return None
        return out_dir # Directory already exists and is valid.

    try:
        os.makedirs(out_dir, exist_ok=True)
        print(f"\033[92m[PromptCrafter] Created output directory: {os.path.relpath(out_dir, base_dir)}\033[0m")
        return out_dir
    except OSError as e:
        # This handles race conditions where a file is created after the os.path.exists check,
        # as well as permission errors.
        print(f"\033[91m[PromptCrafter] Error: Could not create output directory at '{out_dir}'. Reason: {e}\033[0m")
        return None

def _save_output_to_file(filename_prefix, sections, base_filename="prompt"):
    """Saves generated content sections to a timestamped text file."""
    out_dir = _get_and_create_output_dir(filename_prefix)
    if out_dir is None:
        print(f"\033[91m[PromptCrafter] Error: Could not determine output directory for saving file.\033[0m")
        return
    fname = f"{base_filename}_{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000}.txt"
    fpath = os.path.join(out_dir, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        for i, (title, content) in enumerate(sections):
            if content and str(content).strip():
                f.write(f"=== {title.upper()} ===\n{str(content).strip()}\n")
                if i < len(sections) - 1: f.write("\n")

# ------------------------------------------------------------------------------------
# File System Utilities
# ------------------------------------------------------------------------------------

def _get_unique_filepath(directory, base_name, extension):
    """
    Generates a unique file path by appending a counter if the file already exists.
    """
    counter = 1
    new_path = os.path.join(directory, f"{base_name}{extension}")
    original_base_name = base_name
    while os.path.exists(new_path):
        base_name = f"{original_base_name}_{counter}"
        new_path = os.path.join(directory, f"{base_name}{extension}")
        counter += 1
    return new_path, base_name

# ------------------------------------------------------------------------------------
# Text & JSON Processing
# ------------------------------------------------------------------------------------

# Make the JSON parsing functions available through the 'utils' module for other files that use them.
JSONParsingError = json_utils.JSONParsingError
_extract_and_parse_json = json_utils._extract_and_parse_json

class TextCleaner:
    """A utility class for various text cleaning and formatting operations."""
    @staticmethod
    def single_paragraph(text: str) -> str:
        text = (text or "").strip()
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

    @staticmethod
    def sanitize_filename(text, max_length=150):
        """Sanitizes a string to be a valid filename."""
        # Replace spaces and common delimiters with underscores
        text = re.sub(r'[\s,]+', '_', text)
        # Remove any characters that are not valid in filenames
        text = re.sub(r'[\\/*?:"<>|]', '', text)
        # Remove leading/trailing underscores and truncate
        return text.strip('_')[:max_length]

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
    """
    Converts a PIL Image or tensor into a base64 encoded string.
    This is the format required for sending images to most modern web APIs.
    """
    pil = convert_to_pil(img)
    if pil is None:
        return None
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def pil2tensor(image: Image.Image) -> torch.Tensor:
    """Converts a PIL image to a PyTorch tensor."""
    return torch.from_numpy(np.array(image).astype(np.float32) / 255.0).unsqueeze(0)

def _add_metadata_to_image(image_path, caption_text):
    """
    Adds the provided caption text to the image's metadata and saves it in place.
    Supports PNG (tEXt chunk) and JPEG (EXIF UserComment).
    """
    if not config.PIEXIF_AVAILABLE:
        print("\033[93m[PromptCrafter] Warning: Cannot add metadata. `piexif` library is not installed.\033[0m")
        return False

    try:
        img = Image.open(image_path)
        img_format = img.format.upper() if img.format else ""

        if img_format == 'PNG':
            from PIL.PngImagePlugin import PngInfo
            metadata = PngInfo()
            # Use the 'Description' key, which is a standard for captions.
            metadata.add_text("Description", caption_text)
            img.save(image_path, pnginfo=metadata)
            return True
        elif img_format in ['JPEG', 'JPG']:
            import piexif
            import piexif.helper
            # Load existing EXIF data or create a new dictionary
            exif_data = img.info.get('exif', b'')
            exif_dict = piexif.load(exif_data)
            
            # Set the UserComment tag, which is flexible and supports unicode.
            user_comment = piexif.helper.UserComment.dump(caption_text, encoding="unicode")
            exif_dict['Exif'][piexif.ExifIFD.UserComment] = user_comment
            
            exif_bytes = piexif.dump(exif_dict)
            img.save(image_path, exif=exif_bytes)
            return True
        else:
            return False # Format not supported for metadata writing
    except Exception as e:
        print(f"\033[91m[PromptCrafter] Error adding metadata to {os.path.basename(image_path)}: {e}\033[0m")
        return False

def _read_image_description(image_path):
    """
    Reads a descriptive text string from standard image metadata fields.
    Supports PNG (tEXt Description) and JPEG (EXIF UserComment).
    Returns the description string or None if not found.
    """
    if not os.path.exists(image_path):
        return None

    try:
        img = Image.open(image_path)
        # Ensure we load the metadata, some lazy-loading might skip it.
        img.load() 
        img_format = getattr(img, 'format', '').upper()

        if img_format == 'PNG':
            # PIL stores tEXt chunks like 'Description' in the .info dictionary
            return img.info.get("Description")
        
        elif img_format in ['JPEG', 'JPG']:
            if not config.PIEXIF_AVAILABLE: return None
            import piexif
            import piexif.helper
            
            exif_data = img.info.get('exif')
            if not exif_data: return None
            
            exif_dict = piexif.load(exif_data)
            user_comment_bytes = exif_dict.get('Exif', {}).get(piexif.ExifIFD.UserComment)
            return piexif.helper.UserComment.load(user_comment_bytes) if user_comment_bytes else None
    except Exception:
        return None # Fail silently if image is corrupt or metadata is unreadable

def _add_metadata_to_video(video_path, comment_text):
    """
    Adds a comment to the video's metadata using ffmpeg-python.
    This is a non-destructive operation that creates a new file and replaces the old one.
    """
    if not config.FFMPEG_PYTHON_AVAILABLE:
        print("\033[93m[PromptCrafter] Warning: Cannot add metadata to video. `ffmpeg-python` is not installed.\033[0m")
        return False

    try:
        import ffmpeg
        
        # Define a temporary output path
        temp_output_path = f"{os.path.splitext(video_path)[0]}_temp.mp4"

        # Create the ffmpeg stream
        stream = ffmpeg.input(video_path)
        stream = ffmpeg.output(stream, temp_output_path,
                               **{'metadata': f'comment={comment_text}', 'c': 'copy'})
        
        # Run ffmpeg, overwriting the temporary file if it exists
        ffmpeg.run(stream, overwrite_output=True, quiet=True)

        # Replace the original file with the new one
        os.replace(temp_output_path, video_path)
        return True
    except Exception as e:
        print(f"\033[91m[PromptCrafter] Error adding metadata to video {os.path.basename(video_path)}: {e}\033[0m")
        return False

def audio_to_spectrogram(audio_data, sample_rate):
    """
    Converts raw audio data (numpy array) into a Mel spectrogram image tensor using torchaudio and matplotlib.
    This function is optimized for creating a visual preview.
    """
    if not config.MATPLOTLIB_AVAILABLE:
        print("\033[93m[PromptCrafter] Warning: matplotlib not installed. Returning a placeholder tensor for spectrogram.\033[0m")
        return torch.zeros((1, 64, 64, 3), dtype=torch.float32)

    # Use a hash of the audio data for caching instead of a file path
    data_hash = hashlib.sha256(audio_data.tobytes()).hexdigest()
    cache_key = _get_cache_key(data_hash, sample_rate, "spectrogram_v4_torchaudio_tensor")

    if config.CACHE.has(cache_key):
        print(f"\033[94m[PromptCrafter] Using cached spectrogram tensor.\033[0m")
        cached_data = config.CACHE.get(cache_key)
        if torch.is_tensor(cached_data):
            return cached_data

    try:
        # --- NEW: Use torchaudio for computation ---
        import torchaudio.transforms as T
        
        # 1. Convert numpy audio to a torch tensor
        audio_tensor = torch.from_numpy(audio_data)
        if audio_tensor.ndim == 1:
            audio_tensor = audio_tensor.unsqueeze(0) # Add batch dimension if mono

        # 2. Define the transforms
        # Ensure tensor is on the correct device for computation
        device = "cuda" if torch.cuda.is_available() else "cpu"
        audio_tensor = audio_tensor.to(device)

        mel_spectrogram_transform = T.MelSpectrogram(
            sample_rate=sample_rate,
            n_fft=2048,
            hop_length=512,
            n_mels=128,
            f_max=8000
        ).to(device)

        # 3. Compute the Mel spectrogram
        mel_spec = mel_spectrogram_transform(audio_tensor)

        # 4. Convert power to decibels
        to_db = T.AmplitudeToDB(stype='power', top_db=80)
        S_dB_tensor = to_db(mel_spec)

        # --- EXISTING: Use matplotlib for plotting the tensor data ---
        # Move tensor to CPU and convert to numpy for plotting
        S_dB = S_dB_tensor.squeeze(0).cpu().numpy()

        fig, ax = plt.subplots(figsize=(10, 4))
        # Use librosa.display as it's excellent for plotting spectrograms
        if config.LIBROSA_AVAILABLE:
            import librosa.display
            librosa.display.specshow(S_dB, sr=sample_rate, x_axis='time', y_axis='mel', ax=ax, fmax=8000)
        else:
            # Fallback if librosa is somehow not available but matplotlib is
            ax.imshow(S_dB, aspect='auto', origin='lower')

        ax.set(title='Mel Spectrogram')
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        
        image = Image.open(buf).convert("RGB")
        tensor_image = pil2tensor(image)
        config.CACHE.set(cache_key, tensor_image)
        return tensor_image

    except Exception as e:
        print(f"\033[91m[PromptCrafter] Error generating spectrogram: {e}. Returning a placeholder tensor.\033[0m")
        return torch.zeros((1, 64, 64, 3), dtype=torch.float32)

# ------------------------------------------------------------------------------------
# Timed Text & Scheduling
# ------------------------------------------------------------------------------------

def format_srt_time(seconds):
    """Converts seconds (float) to SRT time format 'HH:MM:SS,ms'."""
    if seconds < 0: seconds = 0
    millis = int((seconds - int(seconds)) * 1000)
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def to_srt(timed_segments):
    """Converts a list of timed segments into an SRT formatted string."""
    if not timed_segments:
        return ""
    
    srt_blocks = []
    for i, (start, end, text) in enumerate(timed_segments, 1):
        srt_blocks.append(f"{i}\n{format_srt_time(start)} --> {format_srt_time(end)}\n{text.strip()}\n")
    return "\n".join(srt_blocks)

def _parse_srt_time(time_str: str) -> float:
    """Converts SRT time format 'HH:MM:SS,ms' to seconds."""
    try:
        parts = time_str.replace(',', '.').split(':')
        if len(parts) == 3:
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        return 0.0
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
    pattern = re.compile(r'(\[\d{2}:\d{2}\.\d{2,3}\])(.*)')
    for line in lrc_text.splitlines():
        match = pattern.match(line.strip())
        if match:
            time_str, text = match.groups()
            try:
                minutes, seconds, centiseconds = map(float, time_str.strip('[]').split(':') + [time_str.strip('[]').split('.')[-1]])
                start_time = minutes * 60 + seconds + centiseconds / 100
                text = text.strip()
                if text:
                    segments.append({'start': start_time, 'text': text})
                    raw_lyrics.append(text)
            except ValueError:
                continue
    if not segments: return None, lrc_text
    segments.sort(key=lambda x: x['start'])
    timed_tuples = []
    for i in range(len(segments)):
        start, text = segments[i]['start'], segments[i]['text']
        end = segments[i+1]['start'] if i + 1 < len(segments) else start + 5
        timed_tuples.append((start, end, text))
    return timed_tuples, "\n".join(raw_lyrics)

LYRICS_FORMATS = [
    {
        "name": "SRT",
        "extensions": [".srt"],
        "pattern": re.compile(r'\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}'),
        "parser": _srt_to_timed_segments
    },
    {
        "name": "LRC",
        "extensions": [".lrc"],
        "pattern": re.compile(r'\[\d{2}:\d{2}\.\d{2,3}\]'),
        "parser": _lrc_to_timed_segments
    }
]

def _process_lyrics_content(content, source_name=""):
    """Detects format (SRT, LRC, plain text) and processes lyrics content accordingly."""
    if not content or content.startswith("[Error"):
        return content, None
    for fmt in LYRICS_FORMATS:
        if (source_name and any(source_name.lower().endswith(ext) for ext in fmt["extensions"])) or fmt["pattern"].search(content):
            segments, text = fmt["parser"](content)
            if segments: return text, segments
    return content, None

def _get_verified_path(folder_path, file_name=None, is_dir=False):
    """Constructs and verifies a path, returning the absolute path or None if not found."""
    if not folder_path: return None
    if not is_dir and (not file_name or file_name == "<none>"): return None
    full_folder_path = folder_path if os.path.isabs(folder_path) else os.path.join(config.COMFYUI_ROOT_DIR, folder_path)
    if is_dir:
        if os.path.isdir(full_folder_path): return full_folder_path
        print(f"\033[93m[PromptCrafter] Warning: Directory not found at '{full_folder_path}'.\033[0m")
        return None
    else:
        if file_name is None:
            return None
        filepath = os.path.join(full_folder_path, file_name)
        if os.path.exists(filepath): return filepath
        print(f"\033[93m[PromptCrafter] Warning: File not found at '{filepath}'.\033[0m")
        return None

def _get_audio_path(folder_path, file_name):
    """Constructs and verifies the path to an audio file."""
    return _get_verified_path(folder_path, file_name)

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
            # --- FIX: Simplify interpolation to prevent malformed/repetitive prompts ---
            # This logic was creating unwanted artifacts. A simple hold is more robust.
            # The schedule already contains the start and end frames for a prompt.
            # We just need to ensure the prompt is held. The start_prompt is sufficient.
            new_schedule[interp_frame] = start_prompt_text
    return collections.OrderedDict(sorted(new_schedule.items()))

def _process_timed_segments(timed_segments, fps, min_duration_secs=3.0, max_duration_secs=10.0):
    """
    Merges short timed segments into longer, more coherent scenes suitable for video generation.
    """
    if not timed_segments:
        return []

    processed_segments = []
    current_text_parts = []
    current_start_time = timed_segments[0][0]

    for i, (start, end, text) in enumerate(timed_segments):
        current_text_parts.append(text)
        current_duration = end - current_start_time
        is_last_segment = (i == len(timed_segments) - 1)
        next_segment_has_gap = (not is_last_segment and (timed_segments[i+1][0] - end) > 1.0)

        if is_last_segment or current_duration >= max_duration_secs or (current_duration >= min_duration_secs and next_segment_has_gap):
            processed_segments.append((current_start_time, end, " ".join(current_text_parts)))
            current_text_parts = []
            if not is_last_segment:
                current_start_time = timed_segments[i+1][0]
    return processed_segments

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
    return "{\n" + ",\n".join(schedule_items) + "\n}"

def _handle_lyrics_from_file(folder_path, file_name):
    """Handles loading and processing lyrics from a local file path."""
    filepath = _get_verified_path(folder_path, file_name)
    if not filepath:
        return f"[Error: File not found.]", None, (folder_path, file_name)
    content = safe_read(filepath)
    text, segments = _process_lyrics_content(content, file_name)
    return text, segments, (folder_path, file_name)

def _handle_lyrics_from_url(url, debug_mode):
    """Handles fetching and processing lyrics from a URL."""
    ok, content_or_error = _fetch_url_content(url, debug_mode)
    text, segments = _process_lyrics_content(content_or_error, url)
    return text, segments, ("URL", url)

def _get_lyrics_from_input(user_text, lyrics_folder_path, lyrics_file, debug_mode=False):
    """Orchestrates loading lyrics from various sources (file, URL, direct text)."""
    # Priority 1: An explicitly selected file (which could be a local file or a URL in the filename field).
    if lyrics_folder_path and lyrics_file and lyrics_file != "<none>":
        if lyrics_file.strip().startswith(('http://', 'https://')):
            return _handle_lyrics_from_url(lyrics_file.strip(), debug_mode)
        else:
            return _handle_lyrics_from_file(lyrics_folder_path, lyrics_file)
    # Priority 2: Text in the main user_text widget.
    if user_text and user_text.strip() and user_text.strip() != config.DEFAULT_PROMPT_TEXT:
        text, segments = _process_lyrics_content(user_text)
        return text, segments, None
    # Fallback: No lyrics provided.
    return "", None, None

# ------------------------------------------------------------------------------------
# Web & Content Fetching
# ------------------------------------------------------------------------------------

def _fetch_url_content(url, debug_mode=False):
    """Fetches and cleans text content from a URL, with support for PDF text extraction."""
    try:
        print(f"\033[94m[PromptCrafter] URL detected. Fetching content from: {url}\033[0m")
        session = getattr(config, "SHARED_SESSION", None)
        if session is None:
            session = requests
        response = session.get(url, timeout=20)
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
            return False, f"[Error: URL content type is not supported ({content_type}) ]"
    except requests.exceptions.RequestException as e:
        return False, f"[Error fetching URL: {e}]"

def _should_perform_web_search(user_query, model, seed, debug_mode, timeout=40):
    """Uses an LLM to determine if a user's query requires a web search."""
    from . import api_clients
    if not config.DUCKDUCKGO_SEARCH_AVAILABLE or not user_query or user_query.strip() == config.DEFAULT_PROMPT_TEXT:
        return False, None
    
    current_date = time.strftime('%Y-%m-%d')
    prompt_template = textwrap.dedent(f"""
        You are an expert assistant that decides when to use a web search tool to answer a user's query.
        Your internal knowledge was last updated in early 2023. The current date is {current_date}.

        Analyze the user's query below. You must determine if a web search is necessary to provide an accurate and up-to-date answer.

        **SEARCH IS REQUIRED IF:**
        - The query asks for information about events that happened after early 2023.
        - The query asks for real-time or rapidly changing information (e.g., stock prices, weather, sports scores, product availability).
        - The query asks for "the latest" or "current" information on any topic.
        - The query mentions a specific, non-famous person, a niche product, or a recent company.
        - The query includes a URL and asks for its content.

        **SEARCH IS NOT REQUIRED IF:**
        - The query is a general knowledge question (e.g., "What is the capital of France?").
        - The query asks for a creative task (e.g., "Write a poem about the ocean").
        - The query asks about historical events or stable, well-known facts from before 2023.

        ---
        USER QUERY:
        {user_query}
        ---

        Based on your analysis, respond with ONLY a JSON object.
        - If a search is needed, provide a concise, keyword-focused search query.
        - Format: {{"search_needed": true, "search_query": "optimized search keywords for a search engine"}}
        - If no search is needed: {{"search_needed": false, "search_query": null}}
    """).strip()
    check_prompt = prompt_template
    ok, result_json = api_clients._reason_with_model(model, check_prompt, use_chat_api=True, temperature=0.0, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title="Web Search Check")
    if ok and isinstance(result_json, dict) and result_json.get("search_needed") and result_json.get("search_query"):
        return True, result_json.get("search_query")
    return False, None

def _perform_web_search(query: str, num_results=3, debug_mode=False, fast_search=False, max_concurrent_fetches=5):
    """Performs a web search using DuckDuckGo and returns a combined context string."""
    if not config.DUCKDUCKGO_SEARCH_AVAILABLE: return "[Web search is disabled because `duckduckgo-search` is not installed.]"
    print(f"\033[94m[PromptCrafter] Performing web search for: '{query}'\033[0m")
    if fast_search: print(f"\033[94m[PromptCrafter] Fast search enabled. Using snippets only.\033[0m")
    search_context = ""
    try:
        with DDGS(timeout=20) as ddgs:
            results = list(itertools.islice(ddgs.text(query, region='wt-wt', safesearch='moderate', timelimit='y'), num_results))
            if not results: return "[No web search results found.]"
            if fast_search:
                for result in results:
                    search_context += f"---\nTitle: {result.get('title', 'N/A')}\nSnippet: {result.get('body', 'N/A')}\n\n"
            else:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(num_results, max_concurrent_fetches)) as executor:
                    future_to_url = {executor.submit(_fetch_url_content, result.get('href'), debug_mode): result for result in results if result.get('href')}
                    fetched_contents = {}
                    for future in concurrent.futures.as_completed(future_to_url):
                        result_meta = future_to_url[future]
                        url = result_meta.get('href')
                        try:
                            is_ok, content_or_err = future.result()
                            fetched_contents[url] = (is_ok, content_or_err, result_meta)
                        except Exception as exc:
                            fetched_contents[url] = (False, f"[Error fetching URL content: {exc}]", result_meta)
                for result in results:
                    url = result.get('href')
                    if url in fetched_contents:
                        ok, content, result_meta = fetched_contents[url]
                        search_context += f"--- Web Result from {url} ---\nTitle: {result_meta.get('title', 'N/A')}\nSnippet: {result_meta.get('body', 'N/A')}\n"
                        if ok and content:
                            search_context += f"Content Summary: {TextCleaner.single_paragraph(content)[:1500]}...\n\n"
                        else:
                            search_context += f"Content: [Could not fetch or process content. Reason: {content}]\n\n"
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
    # This regex is more robust and handles various sentence-ending punctuation.
    sentence_matches = re.finditer(r'[^.!?]+(?:[.!?]|\Z)', text.strip())
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
    final_strategy = strategy
    if user_query:
        simple_summarize_queries = ["summarize", "summarize this", "give me a summary", "can you summarize this", "tldr", "tl;dr", "summary"]
        if user_query.lower().strip(" .?!") in simple_summarize_queries:
            print("\033[94m[PromptCrafter] Simple summarize query detected. Switching to faster 'Extractive' strategy for initial pass.\033[0m")
            final_strategy = "extractive"

    cpu_count = os.cpu_count()
    max_workers = min(32, (cpu_count if cpu_count else 1) + 4)

    def map_chunk_to_summary(chunk, i):
        from . import api_clients
        map_prompt_template = "Extract the most important sentences from the following text chunk. Return ONLY the extracted sentences.\n\nTEXT CHUNK:\n{chunk}" if final_strategy == "extractive" else "Concisely summarize the key points of the following text chunk. Focus on factual information, names, and key events. Return ONLY the summary.\n\nTEXT CHUNK:\n{chunk}"
        ok, summary_or_err = api_clients.query_model_auto(model, map_prompt_template.format(chunk=chunk), prefer_chat=True, temperature=temperature, seed=seed, debug_mode=debug_mode, timeout=timeout, debug_title=f"Summarize Chunk {i+1}")
        if ok: return TextCleaner.single_paragraph(summary_or_err)
        print(f"\033[93m[PromptCrafter] Warning: Could not summarize chunk {i+1}. Error: {summary_or_err}\033[0m")
        return None

    def reduce_group(group, i, level, total_groups):
        from . import api_clients
        reduce_prompt = f"The following text consists of several summaries of a larger document. Synthesize these summaries into one final, coherent summary of the entire document.\n\nSUMMARIES:\n{group}"
        ok, summary_or_err = api_clients.query_model_auto(model, reduce_prompt, prefer_chat=True, temperature=temperature, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title=f"Reduce Level {level} - Group {i+1}/{total_groups}")
        if ok: return TextCleaner.single_paragraph(summary_or_err)
        print(f"\033[93m[PromptCrafter] Warning: Reduce step failed for group {i+1} at level {level}. Error: {summary_or_err}\033[0m")
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        # --- Map Phase ---
        print("\033[94m[PromptCrafter] Starting parallel summarization of text chunks (Map phase)...")
        chunk_iterator = _split_text_into_chunks(text, chunk_size_words)
        # Use a generator expression to filter out failed summaries without creating an intermediate list
        current_summaries = (s for s in executor.map(map_chunk_to_summary, chunk_iterator, itertools.count(0)) if s)
        
        # Convert to list once, after the map phase is complete
        summaries_list = list(current_summaries)
        if not current_summaries:
            return "[Error: All text chunks failed to summarize.]"

        # --- Reduce Phase ---
        reduce_level = 1
        while len(summaries_list) > 1:
            # Dynamically adjust group size to balance progress and context window limits
            reduce_group_size = max(2, min(5, (len(summaries_list) + max_workers - 1) // max_workers))
            print(f"\033[94m[PromptCrafter] Combining {len(summaries_list)} summaries into groups of ~{reduce_group_size} (Reduce level {reduce_level})...")
            
            groups_to_process = ["\n\n---\n\n".join(summaries_list[i:i + reduce_group_size]) for i in range(0, len(summaries_list), reduce_group_size)]
            
            # Process groups in parallel
            future_reduced_summaries = executor.map(reduce_group, groups_to_process, itertools.count(0), itertools.repeat(reduce_level), itertools.repeat(len(groups_to_process)))
            reduced_summaries = list(s for s in future_reduced_summaries if s)

            if not reduced_summaries:
                print(f"\033[91m[PromptCrafter] Error: All groups failed at reduce level {reduce_level}. Returning previous level's summaries.\033[0m")
                return "\n\n".join(summaries_list)
            
            summaries_list = reduced_summaries
            reduce_level += 1

    final_summary = summaries_list[0] if summaries_list else "[Error: Summarization resulted in an empty string.]"

    # Final pass to tailor the summary to the user's query, if one was provided.
    if user_query and user_query.strip() and user_query.strip() != config.DEFAULT_PROMPT_TEXT and final_strategy != 'extractive':
        print("\033[94m[PromptCrafter] Performing final pass to tailor summary to user query...")
        final_pass_prompt = textwrap.dedent(f"""
            You are a synthesis expert. Based on the following comprehensive summary, provide a concise and direct answer to the user's original query. Focus only on the information relevant to the query.
---
COMPREHENSIVE SUMMARY ---
{final_summary}
--- END SUMMARY ---
--- USER's ORIGINAL QUERY ---
{user_query}
--- END QUERY ---
            Return ONLY the final, targeted answer.
        """).strip()
        from . import api_clients
        ok, final_answer = api_clients.query_model_auto(model, final_pass_prompt, prefer_chat=True, temperature=temperature, seed=seed, timeout=timeout, debug_mode=debug_mode, debug_title="Final Summary Pass")
        if ok: return TextCleaner.single_paragraph(final_answer)
        else: print(f"\033[93m[PromptCrafter] Warning: Final summary pass failed. Returning the general summary. Error: {final_answer}\033[0m")

    return final_summary

# ------------------------------------------------------------------------------------
# Advanced Prompt Generation Helpers (moved from nodes.py)
# ------------------------------------------------------------------------------------
def _extract_mandatory_tokens_with_model(image_context: str, user_text: str, run_config: 'config.PromptCrafterRunConfig', primary_subjects_from_images: list | None = None):
    cache_key = _get_cache_key(run_config.model, image_context, run_config.use_chat_api, run_config.temperature, run_config.seed, user_text, primary_subjects_from_images, "extract_tokens_v2", run_config.debug_mode)
    from . import api_clients
    if config.CACHE.has(cache_key):
        print("\033[94m[PromptCrafter] Using cached token extraction.\033[0m")
        return True, config.CACHE.get(cache_key)

    has_user_text = user_text and user_text.strip() and user_text.strip() != config.DEFAULT_PROMPT_TEXT

    # --- Determine Primary and Secondary Subjects ---
    # If the user provides text, their instructions are the source of truth for primary subjects.
    # Subjects from images become secondary, inspirational context.
    if has_user_text:
        ok_prim, primary_subjects = _extract_primary_subjects(user_text, run_config)
        if not ok_prim: return False, primary_subjects
        secondary_subjects = primary_subjects_from_images or []
    else: # No user text, so subjects from images are primary.
        primary_subjects = primary_subjects_from_images or []
        ok_sec, secondary_subjects = _extract_secondary_subjects(image_context, run_config)
        if not ok_sec: print(f"\033[93m[PromptCrafter] Warning: Could not extract secondary subjects: {secondary_subjects}\033[0m")
        secondary_subjects = secondary_subjects if ok_sec else []
    if has_user_text and not primary_subjects:
        return False, "Model did not identify any required subjects from your instructions. Please try rephrasing."

    # Combine and filter the lists.
    primary_lower = {p.lower() for p in primary_subjects}
    clean_sec = [item for item in secondary_subjects if str(item).lower() not in primary_lower]

    tagged = {"primary": [f"[PRIMARY] {s}" for s in primary_subjects], "secondary": [f"[SECONDARY][OPTIONAL] {s}" for s in clean_sec]}
    primary_list = primary_subjects if isinstance(primary_subjects, list) else [primary_subjects]
    tagged["allowed_list"] = _unique_keep_order(primary_list + clean_sec)
    config.CACHE.set(cache_key, tagged)
    return True, tagged

def _extract_subjects(source_text, source_label, instruction_text, run_config, debug_title, post_process_func=None):
    from . import api_clients
    if not source_text or not source_text.strip() or source_text.strip() == config.DEFAULT_PROMPT_TEXT: return True, []
    ask_prompt = textwrap.dedent(f"""
        {instruction_text}
        Return ONLY a JSON array of strings: ["item1", "item2", ...]. No commentary.
        ---
        {source_label.upper()} ---
        {source_text}
        --- END {source_label.upper()} ---
    """).strip()
    ok, items_or_err = api_clients._reason_with_model(run_config.model, ask_prompt, use_chat_api=run_config.use_chat_api, temperature=run_config.temperature, seed=run_config.seed, debug_mode=run_config.debug_mode, debug_title=debug_title)
    if not ok: return False, items_or_err
    return True, _post_process_extracted_subjects(items_or_err, post_process_func)

def _extract_primary_subjects(user_text, run_config):
    instruction = "From the USER INSTRUCTIONS, extract a literal list of all visual subjects, characters, and specific named objects the user explicitly wants to see in the final scene. IGNORE musical instruments, audio descriptions, tempo notes, and genre descriptions. CRITICALLY: Pay close attention to the user's specific inputs (e.g., text under 'Character:' or 'Style/Theme:'). IGNORE any subjects mentioned only in example prompts or generic instructional text."
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

    # If summarization failed, fall back to a single, non-iterative call
    if core_objectives == generation_prompt_text:
        print("\033[93m[PromptCrafter] Warning: Deep Think summarization failed. Falling back to single-pass generation.\033[0m")
        fallback_kwargs = kwargs.copy()
        fallback_kwargs['debug_title'] = "Deep Think Fallback Generation"
        return api_clients.query_model_auto(model, generation_prompt_text, **fallback_kwargs)

    current_prompt, history = "", []

    for i in range(max_iterations):
        iteration_num = len(history) + 1
        _debug_print(kwargs.get("debug_mode", False), f"Deep Think - Iteration {iteration_num} Start", f"Input Prompt:\n{current_prompt or '(First iteration, generating initial draft)'}")
        if not current_prompt: # Only do initial generation if we have no prompt to start with
            initial_gen_template = textwrap.dedent(f"""
                You are a professional cinematic prompt engineer and a meticulous editor. Your task is to perform two steps:
                1.  **GENERATE**: Read the "FULL REQUEST" and generate a high-quality, polished prompt that fulfills all "CORE OBJECTIVES".
                2.  **CRITIQUE**: Immediately after generating, critique your own work. Analyze if your generated prompt fully satisfies all "CORE OBJECTIVES". Provide a confidence score (0.0-1.0) and a brief critique.
                ---
                FULL REQUEST (for generation)
{generation_prompt_text}
---
                CORE OBJECTIVES (for self-critique)
{core_objectives}
---
                Return your response as a single JSON object with three keys: `refined_prompt` (string), `confidence_score` (float), and `critique` (string).

                Example of a perfect response:
                {{
                    "refined_prompt": "A cinematic, ultra-realistic 8K photo of a majestic lion with a golden mane, standing on a rocky cliff overlooking a misty savanna at sunrise. Volumetric lighting, epic scale, National Geographic style.",
                    "confidence_score": 0.95,
                    "critique": "The prompt successfully incorporates the primary subject (lion), the setting (savanna at sunrise), and the style (cinematic, realistic). The weighting on 'majestic' could be slightly increased for more emphasis, but it meets all core objectives."
                }}
            """).strip()
            # Modify kwargs for this specific call to set the correct debug title
            initial_gen_kwargs = kwargs.copy()
            initial_gen_kwargs['debug_title'] = f"Deep Think - Initial Generation & Critique"
            ok, critique_json = api_clients._reason_with_model(model, initial_gen_template, **initial_gen_kwargs)
        else:
            ok, critique_json = _run_deep_think_iteration(current_prompt, history, core_objectives, model, **kwargs)
        
        if not ok or not isinstance(critique_json, dict):
            _debug_print(kwargs.get("debug_mode", False), f"Deep Think - Iteration {iteration_num} Critique Failed", f"Error: {critique_json}")
            return (True, current_prompt) if current_prompt else (False, f"Deep Think process failed at initial generation. Reason: {critique_json}")
        
        confidence_score = critique_json.get("confidence_score", 0.0)
        refined_prompt = critique_json.get("refined_prompt")
        critique = critique_json.get("critique", "No critique provided.")
        
        if not refined_prompt:
            _debug_print(kwargs.get("debug_mode", False), "Deep Think - Iteration did not return refined prompt", "Using previous version.")
            if not current_prompt: return False, "Deep Think process failed to generate an initial prompt."
            refined_prompt = current_prompt

        history.append((current_prompt or "Initial Generation", critique))
        _debug_print(kwargs.get("debug_mode", False), f"Deep Think - Iteration {iteration_num} Critique Result", f"Confidence: {confidence_score}\nCritique: {critique}")

        if confidence_score >= confidence_threshold:
            _debug_print(kwargs.get("debug_mode", False), f"Deep Think - Confidence Threshold ({confidence_threshold}) Met", f"Final Prompt: {refined_prompt}")
            return True, refined_prompt
        if refined_prompt.strip() == current_prompt.strip():
            _debug_print(kwargs.get("debug_mode", False), "Deep Think - Prompt Stabilized", "Refined prompt is identical to the previous one. Finalizing.")
            return True, refined_prompt
        current_prompt = refined_prompt
    
    _debug_print(kwargs.get("debug_mode", False), "Deep Think - Loop Finished", "Loop finished without high confidence. Returning last prompt.")
    return True, current_prompt

def _summarize_deep_think_objectives(model, initial_prompt_text, **kwargs):
    from . import api_clients

    # Extract only the user instructions to make summarization more efficient
    user_instructions_match = re.search(r"USER INSTRUCTIONS \(Primary Goal\)\n---\n(.*?)\n---", initial_prompt_text, re.DOTALL)
    text_to_summarize = user_instructions_match.group(1).strip() if user_instructions_match else initial_prompt_text

    summarize_template = textwrap.dedent(f"""
        You are a task analysis expert. Read the following detailed request and summarize it into a concise list of core objectives and constraints for a prompt engineer.
        Focus on mandatory subjects, style requirements, and negative constraints.
        ---
        FULL REQUEST
{text_to_summarize}
---
        Return ONLY the summarized list of objectives.
    """).strip()
    summary_kwargs = kwargs.copy()
    summary_kwargs['temperature'] = 0.1
    summary_kwargs.pop('debug_title', None)
    ok_summary, core_objectives = api_clients.query_model_auto(model, summarize_template, **summary_kwargs, debug_title="Deep Think - Summarize Objectives")
    if not ok_summary:
        print(f"\033[93m[PromptCrafter] Warning: Deep Think objective summarization failed. Using full prompt text for critiques. Error: {core_objectives}\033[0m")
        return initial_prompt_text
    return core_objectives

def _run_deep_think_iteration(current_prompt, history, core_objectives, model, **kwargs):
    from . import api_clients
    history_log = ""
    if history:
        history_log_parts = ["--- REFINEMENT HISTORY (for context) ---"]
        # Provide a more structured history to the model
        for i, (prev_prompt, critique) in enumerate(history[-3:], 1): # Show up to the last 3 critiques
            history_log_parts.append(f"Critique of Version {i}: {critique}")
            if prev_prompt:
                history_log_parts.append(f"Prompt of Version {i}:\n{prev_prompt}\n---")
        history_log = "\n".join(history_log_parts)
    
    critique_template = textwrap.dedent(f"""
        You are a meticulous prompt editor. Your task is to critique and refine a generated prompt based on a set of core objectives.
        --- CORE OBJECTIVES ---
{core_objectives}
--- END CORE OBJECTIVES ---
        {history_log}
--- CURRENT PROMPT TO CRITIQUE ---
{current_prompt}
--- END CURRENT PROMPT ---
        CRITIQUE INSTRUCTIONS:
        1. **Analyze**: Does the "CURRENT PROMPT" fully satisfy all "CORE OBJECTIVES"?
        2. **Review History**: Check the "REFINEMENT HISTORY". Has the current text addressed previous critiques?
        3. **Score & Refine**: Provide a confidence score (0.0-1.0). If the score is less than 1.0, provide a concise critique and a `refined_prompt` that fixes the issues.
        Return your response as a single JSON object with three keys: `confidence_score` (float), `critique` (string), and `refined_prompt` (string).
    """).strip()
    
    iter_kwargs = {k: v for k, v in kwargs.items() if k not in ['images', 'images_b64']}
    return api_clients._reason_with_model(model, critique_template, **iter_kwargs, debug_title=f"Deep Think - Critique Iteration {len(history) + 1}")

def _generate_negative_prompt(scene_prompt, run_config, user_negative_prompt=""): # noqa
    """Generates a comprehensive negative prompt using a hybrid approach of base keywords and AI-driven contextual analysis."""
    from . import api_clients
    if not scene_prompt or "Ollama error" in scene_prompt:
        return ""
    
    # Use a new cache key that includes the model, reflecting the AI-driven nature
    cache_key = _get_cache_key(scene_prompt, user_negative_prompt, run_config.model, "gen_negative_v8_hybrid")
    if config.CACHE.has(cache_key):
        return config.CACHE.get(cache_key)

    # 1. Start with the base keywords (quality, composition, etc.)
    keywords = set(config.NEGATIVE_KEYWORDS["quality"] + config.NEGATIVE_KEYWORDS["composition"])
    keywords.update([kw.strip() for kw in config.DEFAULT_CHINESE_NEGATIVE_PROMPT.split('，') if kw.strip()])

    # 2. Add user-provided negative prompts
    if user_negative_prompt:
        keywords.update([kw.strip() for kw in user_negative_prompt.replace("\n", ",").split(',') if kw.strip()])

    # 3. Use LLM to generate context-specific negative keywords
    ai_prompt = textwrap.dedent(f"""
        You are an expert prompt analyst. Your task is to select relevant negative keywords for the given prompt from the provided categories.

        **Analyze the PROMPT and determine its primary subject type and style.**
        - Is the main subject a `person` or `animal`? If so, you should include the `anatomy` keywords.
        - Is the style `photograph` or `photorealistic`? If so, you should include the `photograph` counter-style keywords.
        - Is the scene a `landscape`? If so, you should include the `landscape` keywords.

        **Keyword Categories:**
        - `anatomy`: {json.dumps(config.NEGATIVE_KEYWORDS["anatomy"])}
        - `photograph`: {json.dumps(config.NEGATIVE_KEYWORDS["contextual"]["photograph"])}
        - `landscape`: {json.dumps(config.NEGATIVE_KEYWORDS["contextual"]["landscape"])}

        ---
        PROMPT: "{scene_prompt}"
        ---
        Return ONLY a JSON array of strings containing the keywords from the categories you selected based on your analysis.
    """).strip()

    ok, ai_keywords = api_clients._reason_with_model(run_config.model, ai_prompt, use_chat_api=run_config.use_chat_api, temperature=0.1, seed=run_config.seed, debug_mode=run_config.debug_mode, debug_title="AI Negative Prompt Generation")
    if ok and isinstance(ai_keywords, list):
        keywords.update([str(kw).strip() for kw in ai_keywords if kw])

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
        if cached_data is not None:
            return cached_data.get("positive_prompt", prompt_text), cached_data.get("negative_keywords", "")
        else:
            return prompt_text, ""
    
    simplification_template = textwrap.dedent('''
        You are an expert in Stable Diffusion prompting. Your task is to restructure a narrative prompt into a highly effective, direct prompt, ensuring absolute adherence to the user's core request.
        **Part 1: Positive Prompt Generation**
        1. **Analyze Core Request:** The `USER'S CORE REQUEST` is the source of truth. Identify the most critical, non-negotiable subjects and attributes.
        2. **Structure for Complex Scenes:** If there are multiple subjects, describe their interactions and spatial relationships.
        3. **Prioritize and Weight:** Create a new prompt starting with the main subject. Use HEAVY weighting like `(description:1.5)` on the most critical attributes from step 1 to FORCE the model's attention. The weight value should be between 1.1 and 1.5.
        4. **Clarify and Synthesize:** Rephrase the rest of the prompt into clear, comma-separated clauses. Remove narrative fluff (e.g., "the man walked over to the car" becomes "man walking to a car").
        5. **Negative Constraints:** Do NOT include negative concepts (e.g., "no people", "without buildings") in the positive prompt. These belong in the negative prompt.
        **Part 2: Negative Prompt Generation**
        5. **Extract Negative Constraints:** Analyze the `USER'S CORE REQUEST` for explicit negative instructions (e.g., "no buildings").
        6. **Generate Counter-Negatives:** Based on the core positive attributes, identify their direct opposites (e.g., if "white dress" is requested, a counter-negative is "black dress").
        ---
        Example: If the core request is "(a majestic dragon:1.4), red scales", a good counter-negative would be "blue scales, green scales".
        ---
        USER'S CORE REQUEST (Source of Truth)
{user_text}
---
        ---
        NARRATIVE PROMPT (to be restructured)
{prompt_text}
---
        Return ONLY a JSON object with two keys: `positive_prompt` (string) and `negative_keywords` (string).
    ''').format(user_text=user_text, prompt_text=prompt_text)
    ok, result_json = api_clients._reason_with_model(run_config.model, simplification_template, use_chat_api=run_config.use_chat_api, temperature=0.1, seed=run_config.seed, timeout=90, debug_mode=run_config.debug_mode, debug_title="Simplify for Diffusion Model (Aggressive)")
    if ok and isinstance(result_json, dict):
        positive = TextCleaner.single_paragraph(result_json.get("positive_prompt", prompt_text))
        negatives = result_json.get("negative_keywords", "")
        config.CACHE.set(cache_key, {"positive_prompt": positive, "negative_keywords": negatives})
        return positive, negatives
    return prompt_text, ""

def _split_text_into_scenes_with_ai(text, run_config):
    '''Uses an LLM to split a single block of text into a list of scenes.'''
    # --- OPTIMIZATION: Summarize long text to prevent huge prompts ---
    text_lines = text.splitlines()
    if len(text_lines) > 40:
        text_to_process = "\n".join(text_lines[:20] + ["..."] + text_lines[-20:])
    else:
        text_to_process = text

    from . import api_clients
    prompt_template = textwrap.dedent('''
        You are an expert film script analyst. Read the following story. Your task is to break it down into distinct, logical scenes or camera shots.
        ---
        STORY
{text_to_process}
---
        INSTRUCTIONS: Identify the natural breaking points. Return ONLY a JSON object with a single key, "scenes", which contains an array of strings. Each string is one scene.
        Example: Input: "A woman walks to a stag and climbs on its back. She rides it across a meadow as an eagle soars above." Output: {{"scenes": ["A woman walks to a stag and climbs up on its back.", "The woman rides the stag across a meadow as an eagle soars above."]}}
    ''').format(
        text_to_process=text_to_process
    )
    ok, result_json = api_clients._reason_with_model(run_config.model, prompt_template, use_chat_api=run_config.use_chat_api, temperature=0.1, seed=run_config.seed, debug_mode=run_config.debug_mode, debug_title="AI Scene Splitter")
    if ok and isinstance(result_json, dict) and "scenes" in result_json and isinstance(result_json["scenes"], list) and result_json["scenes"]:
        print(f"\033[92m[PromptCrafter] AI successfully split the story into {len(result_json['scenes'])} scenes.\033[0m")
        return result_json["scenes"]
    print("\033[93m[PromptCrafter] Warning: AI scene splitting failed. Falling back to splitting by line breaks.\033[0m")
    # Fallback to splitting by lines if AI fails, ensuring we don't send a huge chunk.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines if lines else [text]

def _generate_storyboard_from_instruction_with_ai(user_request, image_context, primary_subjects, run_config):
    '''Uses an LLM to generate a storyboard from a high-level user instruction.'''
    from . import api_clients
    print("\033[94m[PromptCrafter] Using AI to generate storyboard from user instruction...")
    prompt_template = textwrap.dedent('''
        You are an expert film director. Your task is to break down a user's high-level request into a sequence of distinct, cinematic video scenes.
        ---
        USER REQUEST
{user_request}
---
        KEY SUBJECTS (from reference images)
{primary_subjects_json}
---
        INSPIRATIONAL CONTEXT (from reference images)
{image_context}
        ---
        INSTRUCTIONS:
        1. Read the user's request and analyze the subjects and context.
        2. Create a storyboard as a sequence of 3-5 distinct scenes that logically follow the user's request.
        3. For each scene, suggest a cinematic camera shot (e.g., "wide shot", "close-up", "tracking shot").
        4. Return ONLY a JSON object with a single key, "scenes", which contains an array of strings. Each string is a scene description.
    ''').format(
        user_request=user_request,
        primary_subjects_json=json.dumps(primary_subjects),
        image_context=image_context
    )
    ok, result_json = api_clients._reason_with_model(run_config.model, prompt_template, use_chat_api=run_config.use_chat_api, temperature=0.2, seed=run_config.seed, debug_mode=run_config.debug_mode, debug_title="AI Storyboard Generation")
    if ok and isinstance(result_json, dict) and "scenes" in result_json and isinstance(result_json["scenes"], list) and result_json["scenes"]:
        print(f"\033[92m[PromptCrafter] AI successfully generated a storyboard with {len(result_json['scenes'])} scenes.\033[0m")
        return result_json["scenes"]
    return []


# ------------------------------------------------------------------------------------
# Dual-Model Chain of Thought
# ------------------------------------------------------------------------------------


# In utils.py, modify the chain_of_thought_process function signature and implementation:

def chain_of_thought_process(thinking_prompt, thinking_model, instruct_prompt, instruct_model, images=None, **kwargs):
    """
    Executes a two-step cognitive process using a 'thinker' and an 'instructor' model.
    1.  The 'thinker' model generates a natural language reasoning based on the initial prompt.
    2.  The 'instructor' model takes that reasoning and formats it into a structured output.
    Returns: A dictionary with 'result' (parsed JSON or text) and 'reasoning' (text), or an error string.
    """
    debug_mode = kwargs.get('debug_mode', False)
    expect_json = kwargs.get('expect_json', True)
    timeout = kwargs.get('timeout', 120)  # Add timeout parameter with default
    
    # --- STAGE 1: The Thinker (Reasoning) ---
    print(f"\033[94m[PromptCrafter] Dual-Model Chain: Kicking off Stage 1 (Thinking) with {thinking_model}...\033[0m")
    thinker_kwargs = kwargs.copy()
    thinker_kwargs.setdefault('prefer_chat', True)
    thinker_kwargs.setdefault('temperature', 0.4)
    thinker_kwargs.setdefault('debug_title', "Dual-Model Stage 1: Thinker")
    thinker_kwargs['timeout'] = timeout  # Pass timeout to thinker

    ok, reasoning_text = api_clients.query_model_auto(
        thinking_model,
        prompt=thinking_prompt,
        images=images,
        **thinker_kwargs
    )

    if not ok:
        error_message = f"Dual-Model Stage 1 (Thinking) failed: {reasoning_text}"
        print(f"\033[91m[PromptCrafter] {error_message}\033[0m")
        return False, error_message, ""

    if not reasoning_text or not reasoning_text.strip():
        error_message = "Dual-Model Stage 1 (Thinking) returned an empty response. This can happen with very large or complex prompts. Aborting."
        print(f"\033[91m[PromptCrafter] {error_message}\033[0m")
        return False, error_message, reasoning_text

    _debug_print(debug_mode, "Dual-Model Stage 1: Reasoning Output", reasoning_text)

    # --- STAGE 2: The Clerk (Formatting) ---
    print(f"\033[94m[PromptCrafter] Dual-Model Chain: Starting Stage 2 (Instruct) with {instruct_model}...\033[0m")
    
    if "{reasoning}" in instruct_prompt:
        final_instruct_prompt = instruct_prompt.replace("{reasoning}", reasoning_text)
    else:
        final_instruct_prompt = f"{instruct_prompt}\n\n--- REASONING FOR CONTEXT ---\n{reasoning_text}"

    instructor_kwargs = kwargs.copy()
    instructor_kwargs['images'] = None
    instructor_kwargs['timeout'] = timeout  # Pass timeout to instructor

    if expect_json:
        instructor_kwargs.setdefault('temperature', 0.0)
        instructor_kwargs.setdefault('debug_title', "Dual-Model Stage 2: Instructor (JSON)")
        ok, final_output = api_clients._reason_with_model(
            instruct_model,
            prompt=final_instruct_prompt,
            **instructor_kwargs
        )
    else:
        instructor_kwargs.setdefault('temperature', 0.2)
        instructor_kwargs.setdefault('debug_title', "Dual-Model Stage 2: Instructor (Text)")
        ok, final_output = api_clients.query_model_auto(
            instruct_model,
            prompt=final_instruct_prompt,
            **instructor_kwargs
        )

    if not ok:
        error_message = f"Dual-Model Stage 2 (Instruct) failed: {final_output}"
        print(f"\033[91m[PromptCrafter] {error_message}\033[0m")
        return False, error_message, reasoning_text

    _debug_print(debug_mode, "Dual-Model Stage 2: Final Output", final_output)

    return True, final_output, reasoning_text
