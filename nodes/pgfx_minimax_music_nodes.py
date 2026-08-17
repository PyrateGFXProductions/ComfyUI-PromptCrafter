"""
MiniMax Music 3 Prompt Creator Node
Generates structured prompts for MiniMax-Music3 model from song ideas.
Follows official ComfyUI workflow format with Caption + Lyrics inputs.
Includes multi-genre mixing, auto-gen subjects, and quality validation.

Patterns adapted from HOT-Step-PGFX-Edition:
- Multi-genre selection with primary/secondary blending
- Auto-gen subject generation with role templates
- Genre blend rules (primary=recipe, secondary=spices)
- Slop word replacement and quality validation
"""

import os
import re
import json
import random
import textwrap
from collections import deque
from typing import Optional, List, Dict, Tuple

# ComfyUI imports
import folder_paths

# Local module imports
from ..core import pgfx_api_clients as api_clients

try:
    from comfy_api.latest import io as v3_io
    V3_IO_AVAILABLE = True
except ImportError:
    V3_IO_AVAILABLE = False

# MiniMax Music 3 supported section tags (official)
MINIMAX_SECTION_TAGS = [
    "Intro", "Verse", "Pre-Chorus", "Chorus", "Post-Chorus",
    "Bridge", "Instrumental", "Solo", "Outro"
]


# ------------------------------------------------------------------------------------
# Helper function to read node descriptions from HELP.md
# ------------------------------------------------------------------------------------
def get_node_description(node_name):
    """Parses HELP.md and extracts the description for a given node class name."""
    try:
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


def get_combined_models():
    """Helper to get a combined list of local-first models and configured providers."""
    gguf_files = api_clients.get_local_llm_gguf_files()
    gguf_models = [f"gguf/{m}" for m in gguf_files if "not installed" not in m and "not_found" not in m and "error_scanning" not in m]
    
    hf_models = api_clients.get_local_hf_models()
    hf_models_formatted = [f"hf/{m}" for m in hf_models if "not installed" not in m]

    api_models = api_clients.get_all_models()
    # Combine lists, ensuring local models are listed first.
    combined = hf_models_formatted + gguf_models + [m for m in api_models if m not in hf_models_formatted + gguf_models]
    return combined


# ------------------------------------------------------------------------------------
# Genre Vocabulary Modules (adapted from HOT-Step)
# ------------------------------------------------------------------------------------
# Each genre has: whitelist (vocabulary), blacklist (banned words), structure hints
GENRE_VOCABULARY_MODULES = {
    "lo_fi": {
        "whitelist": [
            "vinyl", "crackle", "hiss", "tape", "warm", "mellow", "chill", "dusty",
            "faded", "wobbly", "detuned", "soft", "hazy", "dreamy", "nostalgic",
            "bedroom", "rain", "window", "night", "midnight", "candle", "glow",
            " Rhodes", "piano", "keys", "chords", "jazzy", "swing", "boom-bap",
            "drums", "kick", "snare", "hi-hat", "bass", "sub", "low-pass"
        ],
        "blacklist": [
            "neon", "ethereal", "shimmer", "cascade", "glitter",
            "sparkle", "radiant", "luminous", "celestial", "transcendent"
        ],
        "structure": "I-V-C-V-C-Inst-C-O",
        "verse_lines": 4,
        "chorus_lines": 4,
        "hook_style": "Rhodes chords + vocal hums"
    },
    "hiphop": {
        "whitelist": [
            "bars", "flow", "beat", "rhyme", "street", "night", "city", "grind",
            "hustle", "dream", "real", "concrete", "block", "crown", "throne",
            "mic", "booth", "track", "808", "kick", "snare", "hi-hat", "bass",
            "sample", "loop", "scratch", "vinyl", "crate", "MPC"
        ],
        "blacklist": [
            "ethereal", "shimmer", "cascade", "neon", "glitter", "sparkle"
        ],
        "structure": "I-V-C-V-C-V-C-O",
        "verse_lines": 8,
        "chorus_lines": 4,
        "hook_style": "Catchy chorus with repetition"
    },
    "reggae": {
        "whitelist": [
            "rhythm", "skank", "one-drop", "riddim", "bass", "drum", "guitar",
            "chop", "bubble", "offbeat", "nyabinghi", "dub", "reverb", "delay",
            "island", "sun", "beach", "sea", "palm", "wind", "herb", "livity",
            "irie", "positive", "vibration", "root", "culture", "sound system"
        ],
        "blacklist": [
            "ethereal", "shimmer", "cascade", "neon", "glitter", "sparkle"
        ],
        "structure": "I-V-C-V-C-IL-C-O",
        "verse_lines": 4,
        "chorus_lines": 4,
        "hook_style": "Offbeat skank + bass-heavy chorus"
    },
    "rock": {
        "whitelist": [
            "guitar", "riff", "power", "chord", "drums", "kick", "snare",
            "crash", "bass", "distortion", "overdrive", "amp", "stack",
            "stage", "crowd", "scream", "anthem", "rebel", "fire", "thunder",
            "lightning", "storm", "heart", "soul", "raw", "grit"
        ],
        "blacklist": [
            "ethereal", "shimmer", "cascade", "neon", "glitter", "sparkle"
        ],
        "structure": "I-V-C-V-C-B-Solo-C-O",
        "verse_lines": 4,
        "chorus_lines": 4,
        "hook_style": "Guitar riff + vocal hook"
    },
    "jazz": {
        "whitelist": [
            "piano", "trumpet", "saxophone", "double-bass", "brushes", "ride",
            "swing", "walking", "comping", "solo", "improvise", "blue", "note",
            "chord", "extension", "7th", "9th", "13th", "smoke", "club",
            "late", "night", "whiskey", "glass", "cigarette", "shadow"
        ],
        "blacklist": [
            "ethereal", "shimmer", "cascade", "neon", "glitter", "sparkle"
        ],
        "structure": "I-V-Solo-V-Solo-V-C-O",
        "verse_lines": 4,
        "chorus_lines": 4,
        "hook_style": "Solo improvisation over changes"
    },
    "electronic": {
        "whitelist": [
            "synth", "bass", "drop", "build", "kick", "sub", "wobble", "lead",
            "arpeggio", "sequence", "filter", "cutoff", "resonance", "delay",
            "reverb", "compressor", "sidechain", "four-on-the-floor", "breakdown",
            "buildup", "riser", "downlifter", "atmosphere"
        ],
        "blacklist": [
            "ethereal", "shimmer", "cascade", "neon", "glitter", "sparkle"
        ],
        "structure": "I-Build-Drop-V-Build-Drop-Bridge-Build-Drop-O",
        "verse_lines": 4,
        "chorus_lines": 4,
        "hook_style": "The drop"
    },
    "pop": {
        "whitelist": [
            "melody", "hook", "chorus", "verse", "bridge", "pre-chorus",
            "catchy", "singalong", "radio", "single", "hit", "vocal", "harmony",
            "layer", "stack", "ad-lib", "run", "belt", "falsetto"
        ],
        "blacklist": [
            "ethereal", "shimmer", "cascade", "neon", "glitter", "sparkle"
        ],
        "structure": "I-V-PC-C-V-PC-C-B-C-C-O",
        "verse_lines": 4,
        "chorus_lines": 4,
        "hook_style": "Memorable chorus hook"
    },
    "metal": {
        "whitelist": [
            "riff", "chug", "double-kick", "blast", "breakdown", "solo",
            "shred", "distortion", "gain", "amp", "stack", "cab", "metal",
            "thunder", "war", "death", "fire", "steel", "iron", "blood",
            "skull", "bone", "rage", "hate", "pain", "void"
        ],
        "blacklist": [
            "ethereal", "shimmer", "cascade", "neon", "glitter", "sparkle"
        ],
        "structure": "I-V-C-V-C-B-Solo-C-O",
        "verse_lines": 4,
        "chorus_lines": 4,
        "hook_style": "Heavy riff + vocal growl"
    },
    "folk": {
        "whitelist": [
            "acoustic", "guitar", "fingerpick", "strum", "banjo", "fiddle",
            "mandolin", "harmonica", "harmony", "campfire", "dust", "road",
            "home", "mountain", "river", "field", "sky", "bird", "wind",
            "whisper", "story", "tale", "tradition", "heritage"
        ],
        "blacklist": [
            "ethereal", "shimmer", "cascade", "neon", "glitter", "sparkle"
        ],
        "structure": "I-V-C-V-C-V-C-O",
        "verse_lines": 6,
        "chorus_lines": 4,
        "hook_style": "Fingerpicked chorus"
    },
    "blues": {
        "whitelist": [
            "guitar", "slide", "bend", "note", "blue", "12-bar", "shuffle",
            "boogie", "walking", "bass", "harmonica", "piano", "honky-tonk",
            "whiskey", "train", "highway", "dust", "dirt", "road", "woman",
            "man", "heart", "ache", "pain", "trouble"
        ],
        "blacklist": [
            "ethereal", "shimmer", "cascade", "neon", "glitter", "sparkle"
        ],
        "structure": "I-V-C-V-C-V-C-O",
        "verse_lines": 4,
        "chorus_lines": 4,
        "hook_style": "12-bar blues progression"
    },
    "country": {
        "whitelist": [
            "guitar", "twang", "steel", "fiddle", "banjo", "truck", "dirt",
            "road", "home", "girl", "boy", "heart", "love", "beer", "bar",
            "dance", "boots", "hat", "sun", "moon", "star", "field", "farm"
        ],
        "blacklist": [
            "ethereal", "shimmer", "cascade", "neon", "glitter", "sparkle"
        ],
        "structure": "I-V-C-V-C-V-C-O",
        "verse_lines": 4,
        "chorus_lines": 4,
        "hook_style": "Twangy chorus with hook"
    },
    "rnb": {
        "whitelist": [
            "soul", "groove", "bass", "keys", "piano", "synth", "vocal",
            "run", "ad-lib", "falsetto", "harmony", "layer", "midnight",
            "bedroom", "candle", "whisper", "touch", "skin", "desire",
            "passion", "intimate", "slow", "smooth"
        ],
        "blacklist": [
            "ethereal", "shimmer", "cascade", "neon", "glitter", "sparkle"
        ],
        "structure": "I-V-C-V-C-B-C-O",
        "verse_lines": 4,
        "chorus_lines": 4,
        "hook_style": "Smooth vocal hook"
    },
    "synthwave": {
        "whitelist": [
            "synth", "analog", "retro", "neon", "chrome", "outrun", "drive",
            "night", "city", "car", "highway", "sunset", "horizon", "laser",
            "grid", "cyber", "digital", "arcade", "pixel", "8-bit", "wave"
        ],
        "blacklist": [
            "ethereal", "shimmer", "cascade", "glitter", "sparkle"
        ],
        "structure": "I-V-C-V-C-Solo-C-O",
        "verse_lines": 4,
        "chorus_lines": 4,
        "hook_style": "Arpeggiated synth hook"
    },
    "ambient": {
        "whitelist": [
            "pad", "drone", "atmosphere", "texture", "space", "reverb",
            "delay", "filter", "swell", "wash", "tone", "frequency",
            "spectrum", "harmonic", "resonance", "ethereal", "vast",
            "infinite", "void", "silence", "stillness", "calm", "peace"
        ],
        "blacklist": [
            "glitter", "sparkle", "neon"
        ],
        "structure": "I-Evolving-O",
        "verse_lines": 0,
        "chorus_lines": 0,
        "hook_style": "Textural evolution"
    }
}

# Slop word replacements (generic AI words -> genre-appropriate)
SLOP_REPLACEMENTS = {
    "_default": {
        "ethereal": ["warm", "soft", "gentle", "mellow", "hazy", "dreamy", "floaty", "airy", "light"],
        "shimmer": ["glow", "gleam", "shine", "light", "glimmer"],
        "cascade": ["flow", "pour", "fall", "spill", "wash"],
        "neon": ["warm", "amber", "golden", "soft", "muted"],
        "glitter": ["dust", "grain", "speck", "fleck", "particle"],
        "sparkle": ["glint", "gleam", "flash", "flicker", "glimmer"],
        "radiant": ["bright", "warm", "glowing", "vivid"],
        "luminous": ["bright", "lit", "glowing", "warm", "soft"],
        "celestial": ["sky", "star", "moon", "solar", "astral"],
        "transcendent": ["deep", "profound", "vast", "infinite", "boundless"]
    },
    "lo_fi": {
        "ethereal": ["warm", "soft", "dusty", "faded", "mellow"],
        "shimmer": ["crackle", "hiss", "wobble", "warble", "flutter"],
        "cascade": ["wash", "drift", "float", "glide", "fade"],
        "neon": ["amber", "warm", "golden", "dim", "soft"]
    },
    "hiphop": {
        "ethereal": ["real", "raw", "street", "hard", "cold"],
        "shimmer": ["glint", "gleam", "shine", "reflect", "catch"],
        "cascade": ["pour", "drop", "fall", "hit", "slam"],
        "neon": ["street", "sodium", "harsh", "urban", "city"]
    },
    "metal": {
        "ethereal": ["dark", "cold", "heavy", "thick", "brutal"],
        "shimmer": ["glint", "gleam", "flash", "burn", "scorch"],
        "cascade": ["crash", "smash", "break", "shatter", "destroy"],
        "neon": ["blood", "fire", "ash", "smoke", "ember"]
    }
}

# Genre structure templates for blend hints
GENRE_STRUCTURE_TEMPLATES = {
    "lo_fi": {
        "structure": "I-V-C-V-Inst-C-O",
        "description": "Intro sets mood, two verses with chorus, instrumental break, final chorus, outro fade",
        "verse_lines": 4,
        "chorus_lines": 4,
        "bridge_notes": "Instrumental section or minimal vocals",
        "hook_style": "Rhodes chords + vocal hums, wordless melodies"
    },
    "hiphop": {
        "structure": "I-V-C-V-C-V-C-O",
        "description": "Extended verses, shorter choruses, strong hooks",
        "verse_lines": 8,
        "chorus_lines": 4,
        "bridge_notes": "Often a beat switch or tempo change",
        "hook_style": "Repetitive, memorable, often with ad-libs"
    },
    "reggae": {
        "structure": "I-V-C-V-C-IL-C-O",
        "description": "Classic one-drop rhythm, instrumental breaks",
        "verse_lines": 4,
        "chorus_lines": 4,
        "bridge_notes": "Dub breakdown with heavy reverb and delay",
        "hook_style": "Offbeat skank, bass-heavy"
    },
    "rock": {
        "structure": "I-V-C-V-C-B-Solo-C-O",
        "description": "Guitar-driven, solo section, powerful choruses",
        "verse_lines": 4,
        "chorus_lines": 4,
        "bridge_notes": "Guitar solo or breakdown",
        "hook_style": "Power chords + vocal hook"
    },
    "jazz": {
        "structure": "I-V-Solo-V-Solo-V-C-O",
        "description": "Solo improvisation over changes",
        "verse_lines": 4,
        "chorus_lines": 4,
        "bridge_notes": "Extended solo sections",
        "hook_style": "Solo improvisation"
    },
    "electronic": {
        "structure": "I-Build-Drop-V-Build-Drop-Bridge-Build-Drop-O",
        "description": "Build-drop pattern, breakdown sections",
        "verse_lines": 4,
        "chorus_lines": 4,
        "bridge_notes": "Breakdown with atmospheric elements",
        "hook_style": "The drop"
    },
    "pop": {
        "structure": "I-V-PC-C-V-PC-C-B-C-C-O",
        "description": "Pre-chorus leads to chorus, strong hooks",
        "verse_lines": 4,
        "chorus_lines": 4,
        "bridge_notes": "Contrasting bridge section",
        "hook_style": "Memorable, singable chorus"
    },
    "metal": {
        "structure": "I-V-C-V-C-B-Solo-C-O",
        "description": "Heavy riffs, breakdowns, technical solos",
        "verse_lines": 4,
        "chorus_lines": 4,
        "bridge_notes": "Breakdown or solo",
        "hook_style": "Heavy riff + vocal hook"
    },
    "folk": {
        "structure": "I-V-C-V-C-V-C-O",
        "description": "Storytelling verses, melodic choruses",
        "verse_lines": 6,
        "chorus_lines": 4,
        "bridge_notes": "Instrumental break or key change",
        "hook_style": "Fingerpicked melody"
    },
    "blues": {
        "structure": "I-V-C-V-C-V-C-O",
        "description": "12-bar progression, call and response",
        "verse_lines": 4,
        "chorus_lines": 4,
        "bridge_notes": "Guitar solo",
        "hook_style": "12-bar blues hook"
    },
    "country": {
        "structure": "I-V-C-V-C-V-C-O",
        "description": "Narrative verses, catchy choruses",
        "verse_lines": 4,
        "chorus_lines": 4,
        "bridge_notes": "Fiddle or steel guitar solo",
        "hook_style": "Twangy hook"
    },
    "rnb": {
        "structure": "I-V-C-V-C-B-C-O",
        "description": "Smooth verses, vocal runs in chorus",
        "verse_lines": 4,
        "chorus_lines": 4,
        "bridge_notes": "Vocal bridge with runs",
        "hook_style": "Smooth vocal hook"
    },
    "synthwave": {
        "structure": "I-V-C-V-C-Solo-C-O",
        "description": "Arpeggiated synths, driving beats",
        "verse_lines": 4,
        "chorus_lines": 4,
        "bridge_notes": "Synth solo",
        "hook_style": "Arpeggiated hook"
    },
    "ambient": {
        "structure": "I-Evolving-O",
        "description": "No traditional structure, evolving textures",
        "verse_lines": 0,
        "chorus_lines": 0,
        "bridge_notes": "N/A",
        "hook_style": "Textural evolution"
    }
}


# ------------------------------------------------------------------------------------
# Content Safety Filter
# ------------------------------------------------------------------------------------
# Basic inappropriate content patterns for safe_mode
UNSAFE_PATTERNS = [
    r'\b(kill|murder|stab|shoot|bomb|terrorist)\b',
    r'\b(nigger|faggot|retard|spic|chink|kike)\b',
    r'\b(rape|molest|pedophile|child abuse)\b',
    r'\b(suicide|self-harm|cut myself|end my life)\b',
]


def check_content_safety(text: str) -> Tuple[bool, str]:
    """
    Check text for potentially inappropriate content.
    Returns (is_safe, message).
    """
    if not text:
        return True, ""
    
    for pattern in UNSAFE_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            return False, f"Potentially unsafe content detected: {matches[0]}"
    
    return True, ""
def resolve_genre_from_styles(genres: List[str]) -> Dict[str, str]:
    """
    Resolve user-selected genre strings to internal module keys.
    First selected genre is PRIMARY (dictates structure).
    Additional genres are SECONDARY (influence vocabulary/tone).
    
    Maps all 222 HOT-Step genres to internal vocabulary modules.
    Returns: { primary: genreKey, all: [genreKey, ...] }
    """
    # Complete mapping of all 222 genres to internal module keys
    genre_map = {
        # Pop (18)
        "pop": "pop", "synth-pop": "pop", "electropop": "pop",
        "dance pop": "pop", "dream pop": "pop", "indie pop": "pop",
        "art pop": "pop", "bubblegum pop": "pop", "teen pop": "pop",
        "power pop": "pop", "chamber pop": "pop", "baroque pop": "pop",
        "k-pop": "pop", "j-pop": "pop", "c-pop": "pop",
        "sophisti-pop": "pop", "hyperpop": "pop", "city pop": "pop",
        # Rock (22)
        "rock": "rock", "alternative rock": "rock", "indie rock": "rock",
        "classic rock": "rock", "hard rock": "rock", "soft rock": "rock",
        "progressive rock": "rock", "psychedelic rock": "rock", "post-rock": "rock",
        "punk rock": "rock", "pop punk": "rock", "garage rock": "rock",
        "surf rock": "rock", "grunge": "rock", "shoegaze": "rock",
        "math rock": "rock", "stoner rock": "rock", "blues rock": "rock",
        "folk rock": "rock", "post-punk": "rock", "emo": "rock",
        "noise rock": "rock", "punk": "rock",
        # Electronic (25)
        "electronic": "electronic", "edm": "electronic", "house": "electronic",
        "deep house": "electronic", "tech house": "electronic",
        "progressive house": "electronic", "techno": "electronic",
        "minimal techno": "electronic", "trance": "electronic",
        "psytrance": "electronic", "drum and bass": "electronic", "dnb": "electronic",
        "dubstep": "electronic", "future bass": "electronic", "ambient": "ambient",
        "downtempo": "electronic", "chillwave": "electronic",
        "synthwave": "synthwave", "retrowave": "synthwave",
        "idm": "electronic", "breakbeat": "electronic", "garage": "electronic",
        "hardstyle": "electronic", "electro": "electronic",
        "vaporwave": "electronic", "glitch": "electronic",
        # Hip-Hop (15)
        "hip-hop": "hiphop", "hip hop": "hiphop", "rap": "hiphop",
        "trap": "hiphop", "lo-fi hip-hop": "lo_fi", "lofi hip-hop": "lo_fi",
        "boom bap": "hiphop", "drill": "hiphop", "grime": "hiphop",
        "cloud rap": "hiphop", "conscious hip-hop": "hiphop",
        "gangsta rap": "hiphop", "mumble rap": "hiphop",
        "old school hip-hop": "hiphop", "phonk": "hiphop",
        "crunk": "hiphop", "chopped and screwed": "hiphop",
        # R&B / Soul (12)
        "r&b": "rnb", "soul": "rnb", "neo-soul": "rnb",
        "contemporary r&b": "rnb", "funk": "rnb", "disco": "rnb",
        "motown": "rnb", "quiet storm": "rnb", "new jack swing": "rnb",
        "p-funk": "rnb", "afrobeats": "rnb", "gospel": "rnb",
        # Metal (17)
        "heavy metal": "metal", "thrash metal": "metal", "death metal": "metal",
        "black metal": "metal", "doom metal": "metal", "power metal": "metal",
        "progressive metal": "metal", "symphonic metal": "metal",
        "nu metal": "metal", "metalcore": "metal", "deathcore": "metal",
        "gothic metal": "metal", "sludge metal": "metal", "speed metal": "metal",
        "folk metal": "metal", "djent": "metal", "industrial metal": "metal",
        # Jazz (12)
        "jazz": "jazz", "smooth jazz": "jazz", "bebop": "jazz",
        "cool jazz": "jazz", "swing": "jazz", "jazz fusion": "jazz",
        "acid jazz": "jazz", "free jazz": "jazz", "latin jazz": "jazz",
        "bossa nova jazz": "jazz", "modal jazz": "jazz", "gypsy jazz": "jazz",
        # Classical (10)
        "classical": "ambient", "orchestral": "ambient",
        "chamber music": "ambient", "opera": "ambient", "baroque": "ambient",
        "romantic": "ambient", "minimalist": "ambient",
        "contemporary classical": "ambient", "choral": "ambient",
        "neoclassical": "ambient",
        # Country (9)
        "country": "country", "country pop": "country", "country rock": "country",
        "bluegrass": "country", "americana": "country", "honky-tonk": "country",
        "outlaw country": "country", "alt-country": "country",
        "country blues": "blues",
        # Folk (10)
        "folk": "folk", "indie folk": "folk", "contemporary folk": "folk",
        "celtic": "folk", "world music": "folk", "flamenco": "folk",
        "acoustic": "folk", "singer-songwriter": "folk",
        "neofolk": "folk", "freak folk": "folk",
        # Blues (8)
        "blues": "blues", "delta blues": "blues", "chicago blues": "blues",
        "electric blues": "blues", "blues rock": "rock",
        "jump blues": "blues", "rhythm and blues": "blues",
        "boogie-woogie": "blues",
        # Reggae / Caribbean (11)
        "reggae": "reggae", "dancehall": "reggae", "ska": "reggae",
        "dub": "reggae", "roots reggae": "reggae", "reggaeton": "reggae",
        "soca": "reggae", "calypso": "reggae",
        "reggae (patois)": "reggae", "dub (patois)": "reggae",
        "dancehall (patois)": "reggae",
        # DJ / Turntablism (7)
        "dj": "hiphop", "dual dj": "hiphop", "turntablism": "hiphop",
        "scratch battle": "hiphop", "sample dj": "hiphop",
        "crate digger": "hiphop", "sampling": "hiphop",
        # Latin (10)
        "latin": "rnb", "salsa": "rnb", "bossa nova": "jazz",
        "bachata": "rnb", "cumbia": "rnb", "merengue": "rnb",
        "tango": "ambient", "latin pop": "pop", "mariachi": "country",
        "norteño": "country",
        # Soundtrack / Cinematic (9)
        "film score": "ambient", "epic": "ambient", "cinematic": "ambient",
        "video game music": "electronic", "orchestral soundtrack": "ambient",
        "trailer music": "ambient", "dark ambient": "ambient",
        "fantasy": "ambient", "sci-fi": "electronic",
        # Experimental / Other (11)
        "experimental": "electronic", "avant-garde": "ambient",
        "noise": "ambient", "industrial": "metal", "new age": "ambient",
        "meditation": "ambient", "lo-fi": "lo_fi",
        "post-industrial": "metal", "art rock": "rock",
        "drone": "ambient", "musique concrète": "ambient",
        # Traditional / World (7)
        "klezmer": "jazz", "bhangra": "reggae", "andean": "folk",
        "nordic folk": "folk", "balkan": "folk",
        # Legacy aliases
        "lofi": "lo_fi", "chillhop": "lo_fi",
    }
    
    resolved = []
    for g in genres:
        key = genre_map.get(g.lower(), genre_map.get(g.lower().strip()))
        if key is None:
            # Fallback: try to match partial strings
            key = "pop"
        if key not in resolved:
            resolved.append(key)
    
    if not resolved:
        resolved = ["pop"]
    
    return {
        "primary": resolved[0],
        "all": resolved
    }


def merge_genre_modules(genre_keys: List[str]) -> Dict:
    """
    Merge multiple genre modules when >1 genre is selected.
    Primary genre takes full priority for structure.
    Secondary genres use a sliding-scale weight (85% -> 35% floor)
    to sample a proportional fraction of their vocabulary.
    This ensures every chosen genre makes a perceptible contribution
    without any single secondary overwhelming the primary.
    """
    if not genre_keys:
        return GENRE_VOCABULARY_MODULES.get("pop", {})

    # --- Sliding scale weight constants ---
    MAX_WEIGHT = 0.85   # first seasoning is strongly present
    MIN_FLOOR  = 0.35   # minimum — always musically perceptible (~9 words)

    primary_key = genre_keys[0]
    primary = GENRE_VOCABULARY_MODULES.get(primary_key, {})

    merged = {
        "whitelist": list(primary.get("whitelist", [])),
        "blacklist": list(primary.get("blacklist", [])),
        "structure": primary.get("structure", "I-V-C-V-C-O"),
        "verse_lines": primary.get("verse_lines", 4),
        "chorus_lines": primary.get("chorus_lines", 4),
        "hook_style": primary.get("hook_style", "")
    }

    secondaries = genre_keys[1:]
    n = len(secondaries)
    for i, key in enumerate(secondaries):
        # Linear interpolation: position 0 → MAX_WEIGHT, position n-1 → MIN_FLOOR
        t = i / max(n - 1, 1) if n > 1 else 0.0
        weight = MAX_WEIGHT - t * (MAX_WEIGHT - MIN_FLOOR)

        secondary = GENRE_VOCABULARY_MODULES.get(key, {})
        whitelist = secondary.get("whitelist", [])
        blacklist = secondary.get("blacklist", [])

        # Sample a fraction of the secondary's whitelist proportional to weight
        n_words = max(1, int(len(whitelist) * weight))
        sampled = random.sample(whitelist, min(n_words, len(whitelist)))
        for word in sampled:
            if word not in merged["whitelist"]:
                merged["whitelist"].append(word)

        # Always include blacklist additions (full — these are always relevant)
        for word in blacklist:
            if word not in merged["blacklist"]:
                merged["blacklist"].append(word)

    return merged


def filter_slop_words(text: str, genre_keys: List[str]) -> str:
    """Replace generic AI slop words with genre-appropriate alternatives."""
    result = text
    all_replacements = {}
    
    # Load default replacements
    all_replacements.update(SLOP_REPLACEMENTS.get("_default", {}))
    
    # Load genre-specific replacements
    for key in genre_keys:
        all_replacements.update(SLOP_REPLACEMENTS.get(key, {}))
    
    for slop_word, alternatives in all_replacements.items():
        pattern = re.compile(r'\b' + re.escape(slop_word) + r'\b', re.IGNORECASE)
        if pattern.search(result):
            replacement = random.choice(alternatives)
            result = pattern.sub(replacement, result)
    
    return result


def build_genre_blend_hint(primary_key: str, all_keys: List[str]) -> str:
    """
    Build a genre blend hint with explicit vocabulary weights.
    - Primary genre dictates SONG STRUCTURE (non-negotiable)
    - Secondary genres influence VOCABULARY, TONE, and INSTRUMENTATION ONLY
    - Weight diminishes with position: 85% → 35% floor (linear interpolation)
    """
    MAX_WEIGHT = 0.85
    MIN_FLOOR  = 0.35

    primary_template = GENRE_STRUCTURE_TEMPLATES.get(primary_key, {})

    hint_parts = [
        f"PRIMARY GENRE: {primary_key.upper()} — Dictates SONG STRUCTURE (non-negotiable).",
        f"Structure: {primary_template.get('structure', 'I-V-C-V-C-O')}",
        f"Verse lines: {primary_template.get('verse_lines', 4)}",
        f"Chorus lines: {primary_template.get('chorus_lines', 4)}",
        f"Hook style: {primary_template.get('hook_style', 'Standard hook')}",
        ""
    ]

    secondaries = [k for k in all_keys[1:] if k != primary_key]
    if secondaries:
        n = len(secondaries)
        hint_parts.append("SECONDARY GENRES (influence VOCABULARY, TONE, INSTRUMENTATION ONLY — not structure):")
        for i, key in enumerate(secondaries):
            t = i / max(n - 1, 1) if n > 1 else 0.0
            weight = MAX_WEIGHT - t * (MAX_WEIGHT - MIN_FLOOR)
            hint_parts.append(
                f"  • {key.upper()}: {int(weight * 100)}% vocabulary influence"
            )
        hint_parts.append("")
        hint_parts.append(
            f"Think of it as: {primary_key} is the recipe; "
            + ", ".join(f"{k} ({int((MAX_WEIGHT - (i / max(n-1,1)) * (MAX_WEIGHT - MIN_FLOOR)) * 100)}% spice)" for i, k in enumerate(secondaries))
            + "."
        )
        hint_parts.append("Do NOT change verse pattern, line count, or section order based on secondary genres.")

    return "\n".join(hint_parts)


# ------------------------------------------------------------------------------------
# Auto-Gen Subject Generation (adapted from HOT-Step)
# ------------------------------------------------------------------------------------
SUBJECT_ROLE_TEMPLATES = [
    "something the protagonist is trying to get back to",
    "something the protagonist is trying to escape",
    "something the protagonist lost and cannot find",
    "something the protagonist is about to lose",
    "something the protagonist promised to protect",
    "someone the protagonist used to know",
    "something the protagonist left behind",
    "something the protagonist is waiting for",
    "something the protagonist has outgrown",
    "something the protagonist must let go of",
    "something the protagonist is hiding from everyone",
    "something the protagonist inherited that they never wanted",
    "someone the protagonist is becoming",
    "something the protagonist keeps returning to",
    "something the protagonist built that is now falling apart",
    "something the protagonist owns that they cannot sell",
    "something the protagonist remembers wrongly",
    "something the protagonist is afraid to find out"
]

# Track recently used subjects to avoid repeats (deque maintains insertion order)
_recent_subject_roles = deque(maxlen=6)


def build_subject_guidance() -> str:
    """
    Pick a random subject role template (avoiding recent repeats).
    Returns guidance for the LLM to generate lyrics around a concrete subject.
    """
    global _recent_subject_roles
    
    # Pick from available roles (avoid recent repeats)
    recent_set = set(_recent_subject_roles)
    available = [r for r in SUBJECT_ROLE_TEMPLATES if r not in recent_set]
    if not available:
        _recent_subject_roles.clear()
        available = SUBJECT_ROLE_TEMPLATES
    
    role = random.choice(available)
    _recent_subject_roles.append(role)
    
    return (
        f"SUBJECT ROLE (the subject's relationship to the protagonist): {role}.\n"
        f"The lyrics must be built entirely around ONE concrete subject that fills this role.\n"
        f"Do NOT write about the music, the production, or abstract emotions.\n"
        f"Write about the subject — a person, place, object, or memory — using physical details."
    )


# ------------------------------------------------------------------------------------
# MiniMax Music 3 Structured Caption Builder
# ------------------------------------------------------------------------------------
class MiniMaxMusic3StructuredCaptionBuilder:
    """
    Builds structured captions for MiniMax Music 3 following the official prompting guide.
    
    The structured caption contains THREE sections (in this exact order):
    1. Global Metadata: genre, BPM, key, scale, emotional progression, listening scenario, production profile
    2. Vocal Details: vocal gender, timbre, performance style, harmony, backing vocals, vocal effects
    3. Arrangement: instruments, groove, section-level instrument evolution, textures, spatial effects
    
    Section tags are executable structural instructions; lyric text conveys mood only.
    """
    
    # Canonical section tag mapping: any case variant → correct capitalization
    SECTION_TAG_CANONICAL = {
        "intro": "Intro",
        "verse": "Verse",
        "pre-chorus": "Pre-Chorus",
        "prechorus": "Pre-Chorus",
        "pre chorus": "Pre-Chorus",
        "chorus": "Chorus",
        "post-chorus": "Post-Chorus",
        "postchorus": "Post-Chorus",
        "post chorus": "Post-Chorus",
        "bridge": "Bridge",
        "instrumental": "Instrumental",
        "solo": "Solo",
        "outro": "Outro",
        "hook": "Chorus",        # alias
        "refrain": "Chorus",     # alias
        "interlude": "Instrumental",  # alias
    }

    @staticmethod
    def _normalize_section_tag(tag_content: str) -> str:
        """Normalize a section tag to official MiniMax capitalization.
        e.g. '[verse]' → '[Verse]', '[PRE-CHORUS]' → '[Pre-Chorus]'
        Also handles local directives: '[Chorus - full band]' → '[Chorus - full band]'
        """
        # Split on first hyphen or dash that follows a known tag name
        # Pattern: [TagName optional-directive]
        inner = tag_content.strip()
        # Check if there's a local directive (e.g. 'Chorus - full band')
        directive = ""
        for sep in [" - ", ": ", "/"]:
            if sep in inner:
                parts = inner.split(sep, 1)
                inner = parts[0].strip()
                directive = sep + parts[1].strip()
                break

        canonical = MiniMaxMusic3StructuredCaptionBuilder.SECTION_TAG_CANONICAL.get(
            inner.lower(), None
        )
        if canonical:
            return f"[{canonical}{directive}]"
        # Unknown tag — preserve original capitalization but keep brackets
        return f"[{tag_content}]"

    @staticmethod
    def _validate_lyrics_structure(lyrics: str) -> str:
        """
        Validate and normalize lyrics structure for MiniMax Music 3.
        Ensures section tags are present, on their own lines, and properly capitalized.
        Supported: [Intro], [Verse], [Pre-Chorus], [Chorus], [Post-Chorus],
                   [Bridge], [Instrumental], [Solo], [Outro]
        """
        if not lyrics or not lyrics.strip():
            return ""

        lines = [line.strip() for line in lyrics.splitlines()]
        if not any(line for line in lines):
            return ""

        # Normalize section tag capitalization on every line that is a tag
        normalized_lines = []
        for line in lines:
            m = re.match(r'^\[([^\]]+)\]\s*$', line)
            if m:
                normalized_lines.append(
                    MiniMaxMusic3StructuredCaptionBuilder._normalize_section_tag(m.group(1))
                )
            else:
                normalized_lines.append(line)
        lines = normalized_lines
        
        # Check if lyrics already have section tags
        has_tags = any(re.match(r'\[.*?\]', line) for line in lines if line)
        
        if not has_tags:
            # No tags present - add basic structure
            non_empty = [line for line in lines if line.strip()]
            total_lines = len(non_empty)
            
            if total_lines <= 4:
                tagged_lines = []
                mid = total_lines // 2
                for i, line in enumerate(non_empty):
                    if i == 0:
                        tagged_lines.append("[Verse]")
                    elif i == mid:
                        tagged_lines.append("[Chorus]")
                    tagged_lines.append(line)
                lines = tagged_lines
            else:
                intro_lines = max(1, total_lines // 8)
                verse_lines = max(2, total_lines // 4)
                chorus_lines = max(2, total_lines // 4)
                bridge_lines = max(1, total_lines // 8)
                
                tagged_lines = []
                idx = 0
                
                tagged_lines.append("[Intro]")
                for _ in range(int(intro_lines)):
                    if idx < total_lines:
                        tagged_lines.append(non_empty[idx])
                        idx += 1
                
                if idx < total_lines:
                    tagged_lines.append("[Verse]")
                    for _ in range(int(verse_lines)):
                        if idx < total_lines:
                            tagged_lines.append(non_empty[idx])
                            idx += 1
                
                if idx < total_lines:
                    tagged_lines.append("[Chorus]")
                    for _ in range(int(chorus_lines)):
                        if idx < total_lines:
                            tagged_lines.append(non_empty[idx])
                            idx += 1
                
                if bridge_lines > 0 and idx < total_lines:
                    tagged_lines.append("[Bridge]")
                    for _ in range(int(bridge_lines)):
                        if idx < total_lines:
                            tagged_lines.append(non_empty[idx])
                            idx += 1
                
                if idx < total_lines:
                    tagged_lines.append("[Outro]")
                    while idx < total_lines:
                        tagged_lines.append(non_empty[idx])
                        idx += 1
                
                lines = tagged_lines
        
        return "\n".join(lines)
    
    @staticmethod
    def _validate_caption(caption: str) -> Tuple[bool, str]:
        """
        Validate caption content quality.

        The official MiniMax Music 3 format uses FLAT natural language (no ### headers).
        We validate by checking for meaningful musical content, not markdown structure.
        Returns (is_valid, error_message or cleaned_caption).
        """
        if not caption or not caption.strip():
            return False, "Caption is empty"

        # Strip any accidental markdown headers the LLM may have added
        # (Official format is flat text — headers are for human reference only)
        cleaned = re.sub(r'^#{1,3}\s*\w[^\n]*\n', '', caption, flags=re.MULTILINE)
        cleaned = cleaned.strip()
        if not cleaned:
            return False, "Caption empty after stripping markdown headers"

        # Check word count (official limits: 100 min, 600 max; 5000 token hard cap)
        word_count = len(cleaned.split())
        if word_count < 50:
            return False, f"Caption too short ({word_count} words, minimum 50)"
        if word_count > 600:
            # Truncate gracefully at sentence boundary near 600-word mark
            words = cleaned.split()
            cleaned = " ".join(words[:600])
            print(f"|-- Caption trimmed from {word_count} to 600 words")

        # Validate that musical essentials are present
        has_bpm   = bool(re.search(r'\b\d{2,3}\s*(?:bpm|BPM|beats per minute)\b', cleaned))
        has_key   = bool(re.search(r'\b[A-G][b#]?\s+(?:major|minor|Major|Minor)\b', cleaned))
        has_genre = bool(re.search(r'\b(?:pop|rock|jazz|hip.hop|lofi|lo.fi|electronic|folk|blues|metal|reggae|r&b|soul|country|ambient|synthwave|classical|funk|disco|trap|drill)\b', cleaned, re.IGNORECASE))

        if not has_genre:
            return False, "Caption missing genre information"
        # BPM and key are soft warnings — LLM may phrase them differently
        if not has_bpm:
            print("|-- ⚠️ Caption may be missing explicit BPM value")
        if not has_key:
            print("|-- ⚠️ Caption may be missing explicit key/scale")

        return True, cleaned
    
    @staticmethod
    def _build_global_metadata(
        genre: str,
        subgenre: str,
        bpm: int,
        key: str,
        scale: str,
        emotional_progression: str,
        listening_scenario: str,
        production_profile: str
    ) -> str:
        """Build the Global Metadata section as flat natural language (no markdown headers).
        
        Official format: flat prose paragraph — genre/subgenre, BPM, key, emotional arc,
        listening scenario, and production profile all in one cohesive block.
        Example: 'Lo-fi hip-hop / jazz-hop. 78 BPM, F minor. Warm and melancholic throughout...'
        """
        parts = []

        # Line 1: genre + BPM + key
        genre_line = genre
        if subgenre:
            genre_line += f" / {subgenre}"
        genre_line += f". {bpm} BPM, {key} {scale.lower()}."
        parts.append(genre_line)

        if emotional_progression:
            parts.append(f"Global Emotional Progression: {emotional_progression}")

        if listening_scenario:
            parts.append(f"Application Scenarios & Imagery: {listening_scenario}")

        if production_profile:
            parts.append(f"Sonics & Production Profile: {production_profile}")

        return " ".join(parts)
    
    @staticmethod
    def _build_vocal_details(
        vocal_gender: str,
        vocal_timbre: str,
        vocal_style: str,
        harmony_backing: str,
        vocal_fx: str,
        instrumental: bool = False
    ) -> str:
        """Build the Vocal Details section as flat natural language.
        
        Returns empty string if instrumental=True — the official spec says
        to omit this section entirely for instrumental tracks.
        """
        if instrumental:
            return ""  # Omit vocal section for instrumental tracks

        parts = []

        if vocal_gender or vocal_timbre:
            gender_desc = vocal_gender or "Vocals"
            if vocal_timbre:
                gender_desc += f". {vocal_timbre}"
            parts.append(gender_desc)

        if vocal_style:
            parts.append(f"Vocal Style: {vocal_style}")

        if harmony_backing:
            parts.append(f"Harmony/Backing Vocals: {harmony_backing}")

        if vocal_fx:
            parts.append(f"Vocal FX: {vocal_fx}")

        return " ".join(parts) if parts else ""
    
    @staticmethod
    def _build_arrangement(
        primary_instruments: str,
        secondary_instruments: str,
        groove_progression: str,
        embellishments: str,
        section_arrangement: str,
        arrangement_notes: str
    ) -> str:
        """Build the Arrangement section as flat natural language.
        
        Official format: section-by-section timeline in prose, describing
        instrument lifecycles, groove development, textures, and spatial effects.
        """
        parts = []

        if primary_instruments:
            parts.append(f"Instruments: {primary_instruments}")

        if secondary_instruments:
            parts.append(f"Secondary: {secondary_instruments}")

        if groove_progression:
            parts.append(f"Groove: {groove_progression}")

        if embellishments:
            parts.append(f"Textures & FX: {embellishments}")

        if section_arrangement:
            parts.append(f"Section Evolution: {section_arrangement}")

        if arrangement_notes:
            parts.append(f"Notes: {arrangement_notes}")

        return " ".join(parts) if parts else ""


# ------------------------------------------------------------------------------------
# MiniMax Music 3 Creator Node
# ------------------------------------------------------------------------------------
class PromptCrafter_MiniMaxMusic3Creator:
    """
    Creates structured prompts for MiniMax Music 3 model from song ideas.
    
    Features (adapted from HOT-Step-PGFX-Edition):
    - Multi-genre selection with primary/secondary blending
    - Auto-gen subject generation with role templates
    - Genre blend rules (primary=recipe, secondary=spices)
    - Slop word replacement and quality validation
    
    Following the official ComfyUI workflow, this node outputs:
    - Caption: 3-section structured music description (Global Metadata → Vocal Details → Arrangement)
    - Lyrics: Song text with section tags [Intro] [Verse] [Chorus] [Bridge] [Outro]
    """
    
    DESCRIPTION = get_node_description("PromptCrafter_MiniMaxMusic3Creator")
    
    # VRAM optimization options (matches official workflow parameter)
    VRAM_OPTIONS = [
        "24GB+ (Full Quality)",
        "16-24GB (Optimized)",
        "8-16GB (Low VRAM)",
        "8GB or less (CPU Offload)"
    ]
    
    # Language options for lyrics (flat strings — ComfyUI dropdown validation rejects tuples)
    LYRIC_LANGUAGES = [
        "English", "Chinese", "Japanese", "Korean", "Spanish",
        "French", "German", "Italian", "Portuguese", "Russian",
    ]
    
    # Language name -> code mapping
    LYRIC_LANGUAGE_CODES = {
        "English": "en", "Chinese": "zh", "Japanese": "ja", "Korean": "ko",
        "Spanish": "es", "French": "fr", "German": "de", "Italian": "it",
        "Portuguese": "pt", "Russian": "ru",
    }
    
    # Genre options - All 222 genres from HOT-Step-PGFX-Edition
    # Organized by category for easy selection
    GENRE_OPTIONS = [
        # Pop (18)
        "Pop", "Synth-Pop", "Electropop", "Dance Pop", "Dream Pop", "Indie Pop",
        "Art Pop", "Bubblegum Pop", "Teen Pop", "Power Pop", "Chamber Pop", "Baroque Pop",
        "K-Pop", "J-Pop", "C-Pop", "Sophisti-Pop", "Hyperpop", "City Pop",
        # Rock (22)
        "Rock", "Alternative Rock", "Indie Rock", "Classic Rock", "Hard Rock", "Soft Rock",
        "Progressive Rock", "Psychedelic Rock", "Post-Rock", "Punk Rock", "Pop Punk",
        "Garage Rock", "Surf Rock", "Grunge", "Shoegaze", "Math Rock", "Stoner Rock",
        "Folk Rock", "Post-Punk", "Emo", "Noise Rock",
        # Electronic (25)
        "Electronic", "EDM", "House", "Deep House", "Tech House", "Progressive House",
        "Techno", "Minimal Techno", "Trance", "Psytrance", "Drum and Bass", "Dubstep",
        "Future Bass", "Ambient", "Downtempo", "Chillwave", "Synthwave", "Retrowave",
        "IDM", "Breakbeat", "Garage", "Hardstyle", "Electro", "Vaporwave", "Glitch",
        # Hip-Hop (15)
        "Hip-Hop", "Rap", "Trap", "Lo-Fi Hip-Hop", "Boom Bap", "Drill", "Grime",
        "Cloud Rap", "Conscious Hip-Hop", "Gangsta Rap", "Mumble Rap",
        "Old School Hip-Hop", "Phonk", "Crunk", "Chopped and Screwed",
        # R&B / Soul (12)
        "R&B", "Soul", "Neo-Soul", "Contemporary R&B", "Funk", "Disco",
        "Motown", "Quiet Storm", "New Jack Swing", "P-Funk", "Afrobeats", "Gospel",
        # Metal (17)
        "Heavy Metal", "Thrash Metal", "Death Metal", "Black Metal", "Doom Metal",
        "Power Metal", "Progressive Metal", "Symphonic Metal", "Nu Metal", "Metalcore",
        "Deathcore", "Gothic Metal", "Sludge Metal", "Speed Metal", "Folk Metal",
        "Djent", "Industrial Metal",
        # Jazz (12)
        "Jazz", "Smooth Jazz", "Bebop", "Cool Jazz", "Swing", "Jazz Fusion",
        "Acid Jazz", "Free Jazz", "Latin Jazz", "Bossa Nova Jazz", "Modal Jazz", "Gypsy Jazz",
        # Classical (10)
        "Classical", "Orchestral", "Chamber Music", "Opera", "Baroque",
        "Romantic", "Minimalist", "Contemporary Classical", "Choral", "Neoclassical",
        # Country (9)
        "Country", "Country Pop", "Country Rock", "Bluegrass", "Americana",
        "Honky-Tonk", "Outlaw Country", "Alt-Country", "Country Blues",
        # Folk (10)
        "Folk", "Indie Folk", "Contemporary Folk", "Celtic", "World Music",
        "Flamenco", "Acoustic", "Singer-Songwriter", "Neofolk", "Freak Folk",
        # Blues (8)
        "Blues", "Delta Blues", "Chicago Blues", "Electric Blues", "Blues Rock",
        "Jump Blues", "Rhythm and Blues", "Boogie-Woogie",
        # Reggae / Caribbean (11)
        "Reggae", "Dancehall", "Ska", "Dub", "Roots Reggae", "Reggaeton",
        "Soca", "Calypso", "Reggae (Patois)", "Dub (Patois)", "Dancehall (Patois)",
        # DJ / Turntablism (7)
        "DJ", "Dual DJ", "Turntablism", "Scratch Battle", "Sample DJ",
        "Crate Digger", "Sampling",
        # Latin (10)
        "Latin", "Salsa", "Bossa Nova", "Bachata", "Cumbia", "Merengue",
        "Tango", "Latin Pop", "Mariachi", "Norteño",
        # Soundtrack / Cinematic (9)
        "Film Score", "Epic", "Cinematic", "Video Game Music", "Orchestral Soundtrack",
        "Trailer Music", "Dark Ambient", "Fantasy", "Sci-Fi",
        # Experimental / Other (11)
        "Experimental", "Avant-Garde", "Noise", "Industrial", "New Age",
        "Meditation", "Lo-Fi", "Post-Industrial", "Art Rock", "Drone", "Musique Concrète",
        # Traditional / World (5)
        "Klezmer", "Bhangra", "Andean", "Nordic Folk", "Balkan",
    ]
    
    # (GENRE_OPTIONS_WITH_EMPTY removed — replaced by genre_add dropdown + genres list)

    # Picker dropdown: placeholder + ALL genres (GENRE_OPTIONS + picker extras)
    GENRE_PICKER_OPTIONS = ["── pick genre to add ──"] + GENRE_OPTIONS + [
        # Additional picker-only aliases not in GENRE_OPTIONS
        "Alternative Hip-Hop", "Ambient Classical", "Bass Music", "Bedroom Pop",
        "Chillhop", "Chillout", "Contemporary Christian", "Darkwave",
        "Epic Orchestral", "Fusion Jazz", "G-Funk", "Jazz Funk", "Jazzhop",
        "Metal", "Miami Bass", "Nu Jazz", "Post-Metal", "Samba",
        "Soul Blues", "Soundtrack", "Tape Music", "Traditional Folk",
        "UK Garage", "Worship", "2-Step", "Afropop",
    ]
    
    # Subject generation mode options
    SUBJECT_MODE_OPTIONS = [
        "Manual (use song_idea)",
        "Auto-Gen (random subject)",
        "Hybrid (auto-subject + manual vibe)"
    ]
    
    @classmethod
    def INPUT_TYPES(cls):
        combined_models = get_combined_models()
        return {
            "required": {
                "song_idea": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Describe your song idea, mood, or vibe. If using Auto-Gen subject mode, this is the mood/vibe while the subject is auto-generated."
                }),
                "model": (combined_models, {
                    "tooltip": "The language model to use for expanding the song idea into a structured caption and generating lyrics."
                }),
                "genre_add": (cls.GENRE_PICKER_OPTIONS, {
                    "default": "── pick genre to add ──",
                    "tooltip": "Select a genre/style to add it to the blend list below. First added = PRIMARY (structure). Each additional = seasoning (85%→35% sliding scale)."
                }),
                "genres": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": "Active genre blend (comma-separated, ordered). Edit directly or use genre_add dropdown above. FIRST = Primary. To clear: delete all text."
                }),
                "clear_genres": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "⚠️ Clear the entire genre list and start fresh."
                }),
                "randomize_genre": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "🎲 RANDOM: Replace the primary genre (first in list) with a random selection, keeping any seasoning genres."
                }),
                "instrumental": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Generate an instrumental track (no vocals). Omits the Vocal Details section from the caption entirely."
                }),
                "audio_duration": ("INT", {
                    "default": 60,
                    "min": 15,
                    "max": 300,
                    "step": 15,
                    "tooltip": "Target audio duration in seconds (15–300s, max 5 minutes). Longer tracks need more tokens and VRAM."
                }),
                "bpm": ("INT", {
                    "default": 120,
                    "min": 40,
                    "max": 240,
                    "tooltip": "Beats per minute. Affects the tempo and energy of the song."
                }),
                "randomize_bpm": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "🎲 RANDOM: Pick a random BPM appropriate for the genre."
                }),
                "key": (["C", "C#", "Db", "D", "D#", "Eb", "E", "F", "F#", "Gb", "G", "G#", "Ab", "A", "A#", "Bb", "B"], {
                    "default": "C",
                    "tooltip": "Musical key for the song."
                }),
                "randomize_key": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "🎲 RANDOM: Pick a random musical key."
                }),
                "scale": (["Major", "Minor"], {
                    "default": "Major",
                    "tooltip": "Scale type. Major sounds brighter, minor sounds darker/melancholic."
                }),
                "randomize_scale": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "🎲 RANDOM: Pick Major or Minor randomly."
                }),
                "lyrics": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Song lyrics with section tags. Tags control structure; lyric text conveys mood. If empty, lyrics will be generated."
                }),
                "subject_mode": (cls.SUBJECT_MODE_OPTIONS, {
                    "default": "Manual (use song_idea)",
                    "tooltip": "Manual: use your song_idea as-is. Auto-Gen: generate a random subject with role template. Hybrid: auto-subject + your vibe."
                }),
                "lyric_language": (cls.LYRIC_LANGUAGES, {
                    "default": "English",
                    "tooltip": "Language for lyric generation if no lyrics are provided."
                }),
                "vram_optimization": (cls.VRAM_OPTIONS, {
                    "default": "24GB+ (Full Quality)",
                    "tooltip": "VRAM optimization level. Lower settings use less VRAM but may be slower."
                }),
                "temperature": ("FLOAT", {
                    "default": 0.7,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.05,
                    "tooltip": "Creativity level. Lower = more deterministic, higher = more creative."
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 0xffffffffffffffff,
                    "tooltip": "Random seed. -1 for random."
                }),
                "timeout": ("INT", {
                    "default": 120,
                    "min": 30,
                    "max": 600,
                    "step": 10,
                    "tooltip": "Timeout for LLM calls in seconds."
                }),
                "debug_mode": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Enable verbose logging for debugging."
                }),
            },
            "optional": {
                "emotional_progression": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Describe the emotional arc (e.g., 'Laid-back and dreamy throughout, deepens in the middle and dissolves softly at the end')."
                }),
                "listening_scenario": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Where would someone listen to this? (e.g., 'Studying, raining-outside, headphones-on late-night listening')."
                }),
                "production_profile": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Production style (e.g., 'Bedroom production: muddy warm texture, heavy vinyl crackle, tape hiss')."
                }),
                "vocal_gender": ("STRING", {
                    "default": "",
                    "tooltip": "Vocal gender (e.g., 'Male', 'Female', 'Androgynous', 'Duet'). Leave empty for instrumental."
                }),
                "vocal_timbre": ("STRING", {
                    "default": "",
                    "tooltip": "Vocal timbre (e.g., 'Soft and breathy', 'Deep and gravelly', 'Powerful and resonant')."
                }),
                "vocal_style": ("STRING", {
                    "default": "",
                    "tooltip": "Performance style (e.g., 'Hushed half-sung half-spoken delivery, lazy behind-the-beat phrasing')."
                }),
                "harmony_backing": ("STRING", {
                    "default": "",
                    "tooltip": "Harmony and backing vocals (e.g., 'Sparse murmured double-tracked harmonies, occasional wordless hums')."
                }),
                "vocal_fx": ("STRING", {
                    "default": "",
                    "tooltip": "Vocal effects (e.g., 'Drenched in tape delay and warm spring reverb')."
                }),
                "primary_instruments": ("STRING", {
                    "default": "",
                    "tooltip": "Primary instruments (e.g., 'Dusty boom-bap drums, warm Rhodes piano chords, mellow jazzy guitar')."
                }),
                "secondary_instruments": ("STRING", {
                    "default": "",
                    "tooltip": "Secondary instruments (e.g., 'Low round sub bass, brushed hi-hats, muted trumpet ghost notes')."
                }),
                "groove_progression": ("STRING", {
                    "default": "",
                    "tooltip": "How the groove evolves (e.g., 'Soft thumping kick, cracked snare with lazy swing')."
                }),
                "embellishments": ("STRING", {
                    "default": "",
                    "tooltip": "Textures and spatial effects (e.g., 'Constant vinyl crackle as texture, heavy vinyl crackle')."
                }),
                "section_arrangement": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Section-by-section arrangement (e.g., 'Intro: rain and vinyl noise, solo Rhodes chords fading in. Verses: minimal — drums, bass, Rhodes.')."
                }),
                "arrangement_notes": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Additional arrangement notes."
                }),
                "temperature_lyrics": ("FLOAT", {
                    "default": 0.8,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.05,
                    "tooltip": "Temperature for lyric generation (if lyrics are empty)."
                }),
                "max_retries": ("INT", {
                    "default": 2,
                    "min": 0,
                    "max": 5,
                    "tooltip": "Number of retries for LLM calls."
                }),
                "safe_mode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Enable safety filtering for generated content."
                }),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }
    
    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING", "STRING", "STRING", "DICT")
    RETURN_NAMES = (
        "caption",
        "lyrics",
        "full_prompt",
        "song_idea_expanded",
        "model_info",
        "vram_usage",
        "api_payload"
    )
    FUNCTION = "execute"
    CATEGORY = "☠️PGFX /Creator"
    
    def execute(
        self,
        song_idea,
        model,
        genre_add,
        genres,
        clear_genres,
        randomize_genre,
        instrumental,
        audio_duration,
        bpm,
        randomize_bpm,
        key,
        randomize_key,
        scale,
        randomize_scale,
        lyrics,
        subject_mode,
        lyric_language,
        vram_optimization,
        temperature,
        seed,
        timeout,
        debug_mode,
        emotional_progression=None,
        listening_scenario=None,
        production_profile=None,
        vocal_gender=None,
        vocal_timbre=None,
        vocal_style=None,
        harmony_backing=None,
        vocal_fx=None,
        primary_instruments=None,
        secondary_instruments=None,
        groove_progression=None,
        embellishments=None,
        section_arrangement=None,
        arrangement_notes=None,
        temperature_lyrics=0.8,
        max_retries=2,
        safe_mode=True,
        **kwargs
    ):
        """
        Execute the MiniMax Music 3 prompt creation pipeline.
        
        Features:
        - Multi-genre mixing with primary/secondary blend rules
        - Auto-gen subject generation with role templates
        - Slop word replacement
        - Caption validation
        - Random buttons for genre, BPM, key, scale
        """
        print("\n" + "🎵" * 20)
        print("🎵 [PGFX MiniMax Music 3] CREATE METHOD TRIGGERED 🎵")
        print("🎵" * 20)
        
        # --- HANDLE RANDOMIZATION ---
        # Randomize BPM if requested (genre-appropriate ranges)
        if randomize_bpm:
            genre_bpm_ranges = {
                "lo_fi": (70, 90), "hiphop": (80, 110), "trap": (130, 160),
                "reggae": (70, 90), "rock": (100, 140), "metal": (120, 180),
                "jazz": (100, 160), "blues": (80, 120), "folk": (80, 120),
                "country": (100, 140), "pop": (100, 130), "rnb": (80, 120),
                "electronic": (120, 150), "synthwave": (100, 130), "ambient": (60, 100)
            }
            # Resolve genre to internal key first, then look up BPM range
            resolved_for_bpm = resolve_genre_from_styles([genre])
            bpm_range = genre_bpm_ranges.get(resolved_for_bpm["primary"], (80, 140))
            bpm = random.randint(bpm_range[0], bpm_range[1])
            print(f"|-- 🎲 Random BPM: {bpm} (range: {bpm_range[0]}-{bpm_range[1]} for {resolved_for_bpm['primary']})")
        
        # Randomize key if requested
        if randomize_key:
            key = random.choice(["C", "C#", "Db", "D", "D#", "Eb", "E", "F", "F#", "Gb", "G", "G#", "Ab", "A", "A#", "Bb", "B"])
            print(f"|-- 🎲 Random key: {key}")
        
        # Randomize scale if requested
        if randomize_scale:
            scale = random.choice(["Major", "Minor"])
            print(f"|-- 🎲 Random scale: {scale}")
        
        # Resolve lyric language name to code
        if isinstance(lyric_language, str):
            lyric_lang_name = lyric_language
            lyric_lang_code = self.LYRIC_LANGUAGE_CODES.get(lyric_language, "en")
        else:
            lyric_lang_code = "en"
            lyric_lang_name = "English"
        
        # --- 1. RESOLVE GENRES ---
        print("|-- Step 1: Resolving genres...")

        # clear_genres wipes the list
        if clear_genres:
            genres = ""
            print("|-- Genre list cleared")

        # genre_add: if a real genre was chosen from the dropdown, append it
        PLACEHOLDER = "── pick genre to add ──"
        if genre_add and genre_add != PLACEHOLDER:
            existing = [g.strip() for g in genres.split(",") if g.strip()] if genres else []
            if genre_add not in existing:
                existing.append(genre_add)
            genres = ", ".join(existing)
            print(f"|-- Added genre from picker: {genre_add}")

        # Parse the ordered genres string (comma-separated, order matters)
        genre_list = [g.strip() for g in genres.split(",") if g.strip()] if genres else []
        if not genre_list:
            genre_list = ["Lo-Fi"]
            print("|-- No genres selected, defaulting to Lo-Fi")

        # Randomize replaces only the PRIMARY genre (position 0), preserving seasoning
        if randomize_genre:
            genre_list[0] = random.choice(self.GENRE_OPTIONS)
            print(f"|-- 🎲 Random primary genre: {genre_list[0]}")

        genre = genre_list[0]  # primary for backward compat references below
        secondary_list = genre_list[1:]
        genre_secondary_str = ", ".join(secondary_list) if secondary_list else ""

        # Resolve display names to internal module keys
        genre_resolution = resolve_genre_from_styles(genre_list)
        primary_key = genre_resolution["primary"]
        all_keys = genre_resolution["all"]

        # Merge genre modules with sliding-scale weights
        merged_module = merge_genre_modules(all_keys)

        # Build genre blend hint with weight percentages
        genre_blend_hint = build_genre_blend_hint(primary_key, all_keys)

        print(f"|-- Genre blend: {genre_list}")
        print(f"|-- Primary key: {primary_key}")
        print(f"|-- Secondary keys: {all_keys[1:] if len(all_keys) > 1 else 'None'}")
        print(f"|-- Instrumental: {instrumental}")
        print(f"|-- Audio duration: {audio_duration}s")
        
        # --- 2. HANDLE SUBJECT GENERATION ---
        print("|-- Step 2: Handling subject generation...")
        
        # Build subject guidance based on mode
        subject_guidance = ""
        if subject_mode == "Auto-Gen (random subject)":
            subject_guidance = build_subject_guidance()
            expanded_idea = f"Auto-generated subject. {subject_guidance}"
            if song_idea and song_idea.strip():
                expanded_idea += f"\n\nUser's mood/vibe: {song_idea}"
        elif subject_mode == "Hybrid (auto-subject + manual vibe)":
            subject_guidance = build_subject_guidance()
            if song_idea and song_idea.strip():
                expanded_idea = f"{song_idea}\n\n{subject_guidance}"
            else:
                expanded_idea = f"Auto-generated subject. {subject_guidance}"
        else:
            # Manual mode
            if not song_idea or not song_idea.strip():
                expanded_idea = f"A {genre.lower()} song in {key} {scale.lower()} at {bpm} BPM."
            else:
                expanded_idea = song_idea
        
        print(f"|-- Subject mode: {subject_mode}")
        
        # --- 3. EXPAND SONG IDEA INTO STRUCTURED CAPTION ---
        print("|-- Step 3: Expanding song idea into structured caption...")
        
        caption_builder = MiniMaxMusic3StructuredCaptionBuilder()
        
        # Build the prompt for expanding the song idea into the 3-section format
        expand_prompt = textwrap.dedent(f"""
            You are an expert music producer and songwriter acting as a MiniMax Music 3 Caption Rewriter.
            
            Transform the user's musical intent into a professional structured caption with THREE sections.
            Use natural-language reasoning. Be specific enough to guide generation without becoming an essay.
            
            **GENRE BLEND RULES:**
            {genre_blend_hint}
            
            **SONG IDEA / SUBJECT:**
            {expanded_idea}
            
            **MUSICAL PARAMETERS:**
            - Primary Genre: {genre} ({primary_key})
            - Secondary Genres: {', '.join(all_keys[1:]) if len(all_keys) > 1 else 'None'}
            - BPM: {bpm}
            - Key: {key}
            - Scale: {scale}
            
            **GENRE VOCABULARY (use these words):**
            {', '.join(merged_module.get('whitelist', [])[:20])}...
            
            **AVOID THESE WORDS (slop/overused):**
            {', '.join(merged_module.get('blacklist', []))}
            
            **ADDITIONAL DETAILS (if provided):**
            - Emotional Progression: {emotional_progression if emotional_progression else 'Not specified'}
            - Listening Scenario: {listening_scenario if listening_scenario else 'Not specified'}
            - Production Profile: {production_profile if production_profile else 'Not specified'}
            - Vocal Gender: {vocal_gender if vocal_gender else 'Not specified'}
            - Vocal Timbre: {vocal_timbre if vocal_timbre else 'Not specified'}
            - Vocal Style: {vocal_style if vocal_style else 'Not specified'}
            - Harmony/Backing: {harmony_backing if harmony_backing else 'Not specified'}
            - Vocal FX: {vocal_fx if vocal_fx else 'Not specified'}
            - Primary Instruments: {primary_instruments if primary_instruments else 'Not specified'}
            - Secondary Instruments: {secondary_instruments if secondary_instruments else 'Not specified'}
            - Groove Progression: {groove_progression if groove_progression else 'Not specified'}
            - Embellishments: {embellishments if embellishments else 'Not specified'}
            - Section Arrangement: {section_arrangement if section_arrangement else 'Not specified'}
            - Arrangement Notes: {arrangement_notes if arrangement_notes else 'Not specified'}
            
            **OUTPUT FORMAT — FLAT NATURAL LANGUAGE (NO MARKDOWN HEADERS):**

            Write three consecutive prose paragraphs separated by blank lines:

            PARAGRAPH 1 — Global Metadata:
            Start with: "[Genre] / [Subgenre(s)]. [BPM] BPM, [Key] [scale]."
            Then describe emotional progression, listening scenarios, and production profile.
            {'INSTRUMENTAL TRACK — Do not mention or imply any vocals.' if instrumental else ''}

            PARAGRAPH 2 — {'OMIT THIS SECTION ENTIRELY (instrumental track).' if instrumental else 'Vocal Details:'}
            {'(skip entirely)' if instrumental else 'Describe vocal gender, timbre, performance style, harmonies, backing vocals, and vocal effects in one flowing paragraph.'}

            PARAGRAPH 3 — Arrangement:
            Describe the song as a section-by-section timeline using the genre structure template: {merged_module.get('structure', 'I-V-C-V-C-O')}
            Explain primary and secondary instrument lifecycles, groove development, transitions, textures, and spatial effects.
            Prefer concrete musical changes over decorative prose.

            **RULES:**
            - NO markdown headers (no ###, no **, no bullet points)
            - NO JSON or code fences
            - Target 200–400 words total
            - Every explicit user constraint must be preserved
            - No fabricated BPM or key unless explicitly provided
            - Use genre-appropriate vocabulary from the lists above
            - Avoid words from the blacklist above

            Return ONLY the three paragraphs of flat text. No commentary, no labels, no preamble.
        """).strip()
        
        # Query LLM for caption expansion
        structured_caption = ""
        for attempt in range(max_retries + 1):
            try:
                ok, result = api_clients.query_model_auto(
                    model,
                    expand_prompt,
                    prefer_chat=True,
                    temperature=temperature,
                    seed=seed,
                    timeout=timeout,
                    llm_device="Default (GPU)",
                    reset_context=True,
                    debug_mode=debug_mode,
                    debug_title="MiniMax Music 3 Caption Expansion"
                )
                
                if ok and result and result.strip():
                    raw_caption = result.strip()
                    
                    # Apply slop word replacement
                    structured_caption = filter_slop_words(raw_caption, all_keys)
                    
                    # Safety check (if enabled)
                    if safe_mode:
                        is_safe, safety_msg = check_content_safety(structured_caption)
                        if not is_safe:
                            print(f"|-- ⚠️ Safety filter triggered: {safety_msg}")
                            if attempt < max_retries:
                                print(f"|-- Retrying due to safety filter...")
                                continue
                    
                    # Validate caption format
                    is_valid, validation_msg = caption_builder._validate_caption(structured_caption)
                    if is_valid:
                        print(f"|-- Caption expansion successful (attempt {attempt + 1})")
                        break
                    else:
                        print(f"|-- Caption validation failed: {validation_msg}")
                        if attempt < max_retries:
                            print(f"|-- Retrying...")
                        else:
                            # Use the caption anyway if all attempts fail validation
                            print("|-- Using caption despite validation issues")
                            break
                else:
                    if attempt < max_retries:
                        print(f"|-- Caption expansion failed, retrying... (attempt {attempt + 1})")
                    else:
                        # Fallback to basic caption
                        structured_caption = self._build_fallback_caption(
                            genre, genre_secondary_str, bpm, key, scale,
                            emotional_progression, listening_scenario, production_profile,
                            vocal_gender, vocal_timbre, vocal_style, harmony_backing, vocal_fx,
                            primary_instruments, secondary_instruments, groove_progression, embellishments,
                            section_arrangement, arrangement_notes, instrumental
                        )
                        print("|-- Using fallback caption (all attempts failed)")
            except Exception as e:
                if attempt < max_retries:
                    print(f"|-- Error expanding caption: {e}, retrying...")
                else:
                    structured_caption = self._build_fallback_caption(
                        genre, genre_secondary_str, bpm, key, scale,
                        emotional_progression, listening_scenario, production_profile,
                        vocal_gender, vocal_timbre, vocal_style, harmony_backing, vocal_fx,
                        primary_instruments, secondary_instruments, groove_progression, embellishments,
                        section_arrangement, arrangement_notes, instrumental
                    )
                    print(f"|-- Using fallback caption due to error: {e}")
        
        # --- 4. HANDLE LYRICS ---
        print("|-- Step 4: Processing lyrics...")
        
        if lyrics and lyrics.strip():
            # User provided lyrics - validate and normalize structure
            processed_lyrics = caption_builder._validate_lyrics_structure(lyrics)
            print("|-- Using provided lyrics with normalized structure")
        else:
            # Generate lyrics using LLM
            print("|-- No lyrics provided, generating...")
            
            # Build subject guidance for lyrics
            lyric_subject_guidance = ""
            if subject_guidance:
                lyric_subject_guidance = f"\n\n**SUBJECT GUIDANCE:**\n{subject_guidance}\n"
            
            # Build vocabulary hints for lyrics
            vocab_hints = ""
            if merged_module.get("whitelist"):
                vocab_hints = f"\n\n**GENRE VOCABULARY (use these words):** {', '.join(merged_module['whitelist'][:15])}..."
            if merged_module.get("blacklist"):
                vocab_hints += f"\n\n**AVOID THESE WORDS:** {', '.join(merged_module['blacklist'])}"
            
            genre_display = genre
            if genre_secondary_str:
                genre_display += f" / {genre_secondary_str}"

            lyric_gen_prompt = textwrap.dedent(f"""
                You are a talented songwriter writing for {genre_display}.
                
                **GENRE STRUCTURE RULES (NON-NEGOTIABLE):**
                {genre_blend_hint}
                
                **MOOD/THEME:** {expanded_idea}
                **LANGUAGE:** {lyric_lang_name}
                **BPM:** {bpm}
                **KEY:** {key} {scale}
                {lyric_subject_guidance}
                {vocab_hints}
                
                **CRITICAL RULES:**
                1. Write about PHYSICAL OBJECTS and CONCRETE DETAILS, not abstract emotions
                2. Every line must connect to the subject (if auto-generated) or theme
                3. Never write about the music itself (no "this song", "this beat", "this melody")
                4. Use the "Grease Spot Rule" — write about mundane, physical details
                5. Maintain narrative coherence throughout
                6. Follow the genre structure exactly (verse lines: {merged_module.get('verse_lines', 4)}, chorus lines: {merged_module.get('chorus_lines', 4)})
                
                **STRUCTURAL REQUIREMENTS:**
                - Use section tags: [Intro], [Verse], [Pre-Chorus], [Chorus], [Post-Chorus], [Bridge], [Instrumental], [Solo], [Outro]
                - Section tags are the ONLY executable structural instructions; the lyric text conveys mood only
                - Keep lines singable (6-14 syllables for verses, 8-16 for choruses)
                - Use one coherent metaphor or image system across the song
                - Add parenthetical stage directions for mood (e.g., "(rain on the window)")
                - Avoid adjective stacking, forced rhymes, and mixed metaphors
                - The lyrics must match the mood and theme described above
                
                **OUTPUT FORMAT:**
                Return ONLY the lyrics with section tags. No commentary, no explanation.
                
                Example:
                [Intro]
                Mmm...
                (rain on the window)
                Ooh...

                [Verse]
                Midnight and the canvas glows
                Dragging little wires where the current flows
                
                [Instrumental]

                [Verse]
                Queue another frame, let the motion breathe
                Pictures start to move like the falling leaves

                [Chorus]
                Mmm... let it render on
                (take your time, take your time)
                Ooh... by the morning it'll all be done

                [Bridge]
                Rain keeps drawing pictures on the glass...
                My machine keeps dreaming...
                Neither of us fast...

                [Outro]
                Mmm...
                (node to node)
                Ooh... goodnight
            """).strip()
            
            for attempt in range(max_retries + 1):
                try:
                    ok, result = api_clients.query_model_auto(
                        model,
                        lyric_gen_prompt,
                        prefer_chat=True,
                        temperature=temperature_lyrics,
                        seed=seed,
                        timeout=timeout,
                        llm_device="Default (GPU)",
                        reset_context=True,
                        debug_mode=debug_mode,
                        debug_title="MiniMax Music 3 Lyric Generation"
                    )
                    
                    if ok and result and result.strip():
                        # Apply slop word replacement to lyrics
                        clean_lyrics = filter_slop_words(result.strip(), all_keys)
                        
                        # Safety check (if enabled)
                        if safe_mode:
                            is_safe, safety_msg = check_content_safety(clean_lyrics)
                            if not is_safe:
                                print(f"|-- ⚠️ Safety filter triggered on lyrics: {safety_msg}")
                                if attempt < max_retries:
                                    print(f"|-- Retrying due to safety filter...")
                                    continue
                        
                        processed_lyrics = caption_builder._validate_lyrics_structure(clean_lyrics)
                        print(f"|-- Lyric generation successful (attempt {attempt + 1})")
                        break
                    else:
                        if attempt < max_retries:
                            print(f"|-- Lyric generation failed, retrying... (attempt {attempt + 1})")
                        else:
                            processed_lyrics = ""
                            print("|-- Lyric generation failed, proceeding without lyrics")
                except Exception as e:
                    if attempt < max_retries:
                        print(f"|-- Error generating lyrics: {e}, retrying...")
                    else:
                        processed_lyrics = ""
                        print(f"|-- Lyric generation failed due to error: {e}")
        
        # --- 5. BUILD FULL PROMPT ---
        print("|-- Step 5: Building full prompt...")
        
        # Full prompt combines caption and lyrics for reference
        full_prompt = structured_caption
        
        # --- 6. BUILD API PAYLOAD ---
        print("|-- Step 6: Building API payload...")
        
        # Determine VRAM optimization settings
        vram_settings = self._get_vram_settings(vram_optimization)
        
        # Build the API payload following MiniMax Music 3 official format
        # max_new_tokens = audio_duration * 25 fps (official: 25 frames/sec)
        max_new_tokens = audio_duration * 25
        api_payload = {
            "model": "MiniMaxAI/MiniMax-Music3",
            "input": processed_lyrics,
            "instructions": structured_caption,
            "response_format": "wav",
            "seed": seed if seed >= 0 else 0,
            "max_new_tokens": max_new_tokens,
            "audio_duration": audio_duration,
            "stream": False
        }
        
        # Add VRAM optimization settings to payload
        api_payload["vram_optimization"] = vram_settings
        
        # Build model info
        model_info = {
            "model_name": model,
            "genres": genre_list,
            "primary_genre": genre,
            "primary_genre_key": primary_key,
            "secondary_genres": all_keys[1:] if len(all_keys) > 1 else [],
            "genre_blend_weights": {
                genre_list[i]: (
                    1.0 if i == 0 else
                    round(0.85 - (((i - 1) / max(len(genre_list) - 2, 1)) * 0.5), 2)
                    if len(genre_list) > 2 else 0.85
                )
                for i in range(len(genre_list))
            },
            "instrumental": instrumental,
            "audio_duration": audio_duration,
            "bpm": bpm,
            "key": key,
            "scale": scale,
            "subject_mode": subject_mode,
            "lyric_language": lyric_lang_name,
            "vram_optimization": vram_optimization,
            "temperature": temperature,
            "seed": seed
        }
        
        # Build VRAM usage info
        vram_usage = {
            "optimization_level": vram_optimization,
            "estimated_vram": vram_settings["estimated_vram"],
            "max_duration": vram_settings["max_duration"],
            "tiled_decode": vram_settings["tiled_decode"],
            "notes": vram_settings["notes"]
        }
        
        print("|-- MiniMax Music 3 prompt creation complete!")
        print("="*40 + "\n")
        
        return (
            structured_caption,
            processed_lyrics,
            full_prompt,
            expanded_idea,
            json.dumps(model_info, indent=2),
            json.dumps(vram_usage, indent=2),
            api_payload
        )
    
    def _build_fallback_caption(
        self,
        genre, genre_secondary_str, bpm, key, scale,
        emotional_progression, listening_scenario, production_profile,
        vocal_gender, vocal_timbre, vocal_style, harmony_backing, vocal_fx,
        primary_instruments, secondary_instruments, groove_progression, embellishments,
        section_arrangement, arrangement_notes,
        instrumental=False
    ):
        """Build a flat-text fallback caption when LLM expansion fails."""
        builder = MiniMaxMusic3StructuredCaptionBuilder()

        global_metadata = builder._build_global_metadata(
            genre, genre_secondary_str, bpm, key, scale,
            emotional_progression or f"A {genre.lower()} song with {scale.lower()} mood",
            listening_scenario or "General listening",
            production_profile or "Professional studio production"
        )

        vocal_details = builder._build_vocal_details(
            vocal_gender or "Vocals",
            vocal_timbre or "Clear and expressive",
            vocal_style or "Melodic and emotional",
            harmony_backing or "Subtle backing harmonies",
            vocal_fx or "Light reverb",
            instrumental=instrumental
        )

        arrangement = builder._build_arrangement(
            primary_instruments or f"{genre} instrumentation",
            secondary_instruments or "Supporting instruments",
            groove_progression or f"Steady {bpm} BPM groove",
            embellishments or "Warm production textures",
            section_arrangement or "",
            arrangement_notes or ""
        )

        parts = [p for p in [global_metadata, vocal_details, arrangement] if p]
        return "\n\n".join(parts)
    
    def _get_vram_settings(self, vram_optimization: str) -> dict:
        """
        Get VRAM optimization settings based on GPU tier.
        
        Settings match the official ComfyUI workflow:
        - max_duration: Target song length in seconds (up to ~300s / 5 minutes)
        - tiled_decode: Decode audio VAE in overlapping tiles to cut VRAM usage
        """
        settings = {
            "24GB+ (Full Quality)": {
                "estimated_vram": "~22GB",
                "max_duration": 300,
                "tiled_decode": False,
                "notes": "Full quality, no offloading. Generates up to 5 minutes of audio.",
                "offload": "none",
                "dtype": "bfloat16"
            },
            "16-24GB (Optimized)": {
                "estimated_vram": "~16GB",
                "max_duration": 240,
                "tiled_decode": True,
                "notes": "Auto CPU offloading + tiled decode. Fits in 16GB VRAM.",
                "offload": "auto",
                "dtype": "bfloat16"
            },
            "8-16GB (Low VRAM)": {
                "estimated_vram": "~8GB",
                "max_duration": 180,
                "tiled_decode": True,
                "notes": "Aggressive CPU offloading + tiled decode. Slower but works.",
                "offload": "aggressive",
                "dtype": "bfloat16"
            },
            "8GB or less (CPU Offload)": {
                "estimated_vram": "~6GB",
                "max_duration": 120,
                "tiled_decode": True,
                "notes": "Maximum CPU offloading + tiled decode. Very slow but works on 8GB.",
                "offload": "maximum",
                "dtype": "bfloat16"
            }
        }
        
        return settings.get(vram_optimization, settings["24GB+ (Full Quality)"])


# ------------------------------------------------------------------------------------
# MiniMax Music 3 API Connector Node
# ------------------------------------------------------------------------------------
class PromptCrafter_MiniMaxMusic3APIConnector:
    """
    Sends prompts to MiniMax Music 3 API/server and returns audio.
    
    This node connects to a running MiniMax Music 3 server (SGLang-Omni or compatible)
    and generates audio from the structured caption + lyrics.
    
    Parameters match the official ComfyUI workflow:
    - Caption (instructions): Structured music description
    - Lyrics (input): Song text with section tags
    - max_duration: Target song length in seconds (up to ~300s / 5 minutes)
    - seed: Random seed for reproducibility
    - tiled_decode: Decode audio VAE in overlapping tiles to reduce VRAM
    """
    
    DESCRIPTION = get_node_description("PromptCrafter_MiniMaxMusic3APIConnector")
    
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_url": ("STRING", {
                    "default": "http://127.0.0.1:8000",
                    "tooltip": "URL of the MiniMax Music 3 server (SGLang-Omni or compatible API)."
                }),
                "structured_caption": ("STRING", {
                    "multiline": True,
                    "forceInput": True,
                    "tooltip": "The structured caption from the MiniMax Music 3 Creator node."
                }),
                "lyrics": ("STRING", {
                    "multiline": True,
                    "forceInput": True,
                    "tooltip": "The lyrics from the MiniMax Music 3 Creator node."
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 0xffffffffffffffff,
                    "tooltip": "Random seed for reproducible generation."
                }),
                "max_duration": ("INT", {
                    "default": 120,
                    "min": 10,
                    "max": 300,
                    "tooltip": "Target song length in seconds (default 120 = 2 minutes; max ~300 = 5 minutes)."
                }),
                "tiled_decode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Decode audio VAE in overlapping tiles to cut VRAM usage. Slightly slower with small risk of seams."
                }),
                "timeout": ("INT", {
                    "default": 1200,
                    "min": 60,
                    "max": 3600,
                    "tooltip": "Timeout for the generation request in seconds."
                }),
                "output_path": ("STRING", {
                    "default": "minimax_music3_output.wav",
                    "tooltip": "Output file path for the generated audio."
                }),
            },
            "optional": {
                "debug_mode": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Enable verbose logging for debugging."
                }),
            },
        }
    
    RETURN_TYPES = ("STRING", "STRING", "BOOLEAN")
    RETURN_NAMES = (
        "output_path",
        "status_message",
        "success"
    )
    FUNCTION = "generate"
    CATEGORY = "☠️PGFX /Creator"
    
    def generate(
        self,
        api_url,
        structured_caption,
        lyrics,
        seed,
        max_duration,
        tiled_decode,
        timeout,
        output_path,
        debug_mode=False,
        **kwargs
    ):
        """Generate audio using MiniMax Music 3 API."""
        import urllib.request
        import urllib.error
        
        print("\n" + "🎵" * 20)
        print("🎵 [PGFX MiniMax Music 3 API] GENERATE TRIGGERED 🎵")
        print("🎵" * 20)
        
        try:
            # Build the request body following official format
            request_body = {
                "model": "MiniMaxAI/MiniMax-Music3",
                "input": lyrics,
                "instructions": structured_caption,
                "response_format": "wav",
                "seed": seed,
                "max_duration": max_duration,
                "stream": False
            }
            
            # Add tiled_decode setting
            if tiled_decode:
                request_body["tiled_decode"] = True
            
            if debug_mode:
                print(f"|-- Request URL: {api_url}/v1/audio/speech")
                print(f"|-- Request body: {json.dumps(request_body, indent=2)}")
            
            # Make the request
            url = f"{api_url.rstrip('/')}/v1/audio/speech"
            data = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=timeout) as response:
                wav_data = response.read()
            
            if not wav_data:
                raise RuntimeError("Server returned empty response")
            
            # Save the audio file
            output_full_path = os.path.join(
                folder_paths.get_output_directory(),
                output_path
            )
            os.makedirs(os.path.dirname(output_full_path), exist_ok=True)
            
            with open(output_full_path, "wb") as f:
                f.write(wav_data)
            
            status_msg = f"Successfully generated audio: {output_full_path}"
            print(f"|-- {status_msg}")
            print("="*40 + "\n")
            
            return (output_full_path, status_msg, True)
            
        except urllib.error.HTTPError as e:
            error_msg = f"HTTP Error {e.code}: {e.read().decode(errors='replace')}"
            print(f"|-- {error_msg}")
            return ("", error_msg, False)
            
        except urllib.error.URLError as e:
            error_msg = f"Connection error: {e.reason}"
            print(f"|-- {error_msg}")
            return ("", error_msg, False)
            
        except Exception as e:
            error_msg = f"Generation failed: {str(e)}"
            print(f"|-- {error_msg}")
            return ("", error_msg, False)


# ------------------------------------------------------------------------------------
# V3 API Nodes (if available)
# ------------------------------------------------------------------------------------
if V3_IO_AVAILABLE:
    class PromptCrafter_MiniMaxMusic3CreatorV3(v3_io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return v3_io.Schema(
                node_id="PromptCrafter_MiniMaxMusic3CreatorV3",
                display_name="🎵 MiniMax Music 3 Creator (V3)",
                category="☠️PGFX /Creator",
                description="Creates structured captions + lyrics for MiniMax Music 3 from song ideas with multi-genre mixing.",
                inputs=[
                    v3_io.String.Input("song_idea", multiline=True, default=""),
                    v3_io.String.Input("model"),
                    v3_io.Combo.Input("genre_add", options=PromptCrafter_MiniMaxMusic3Creator.GENRE_PICKER_OPTIONS, default="── pick genre to add ──"),
                    v3_io.String.Input("genres", default=""),
                    v3_io.Boolean.Input("clear_genres", default=False),
                    v3_io.Boolean.Input("randomize_genre", default=False),
                    v3_io.Boolean.Input("instrumental", default=False),
                    v3_io.Int.Input("audio_duration", default=60, min=15, max=300),
                    v3_io.Int.Input("bpm", default=120, min=40, max=240),
                    v3_io.Boolean.Input("randomize_bpm", default=False),
                    v3_io.Combo.Input("key", options=["C", "C#", "Db", "D", "D#", "Eb", "E", "F", "F#", "Gb", "G", "G#", "Ab", "A", "A#", "Bb", "B"], default="C"),
                    v3_io.Boolean.Input("randomize_key", default=False),
                    v3_io.Combo.Input("scale", options=["Major", "Minor"], default="Major"),
                    v3_io.Boolean.Input("randomize_scale", default=False),
                    v3_io.String.Input("lyrics", multiline=True, default=""),
                    v3_io.Combo.Input("subject_mode", options=PromptCrafter_MiniMaxMusic3Creator.SUBJECT_MODE_OPTIONS, default="Manual (use song_idea)"),
                    v3_io.Combo.Input("lyric_language", options=PromptCrafter_MiniMaxMusic3Creator.LYRIC_LANGUAGES, default="English"),
                    v3_io.Combo.Input("vram_optimization", options=PromptCrafter_MiniMaxMusic3Creator.VRAM_OPTIONS, default="24GB+ (Full Quality)"),
                    v3_io.Float.Input("temperature", default=0.7, min=0.0, max=1.0),
                    v3_io.Int.Input("seed", default=-1, min=-1),
                    v3_io.Int.Input("timeout", default=120, min=30, max=600),
                    v3_io.Boolean.Input("debug_mode", default=False),
                    v3_io.String.Input("emotional_progression", multiline=True, default=""),
                    v3_io.String.Input("listening_scenario", multiline=True, default=""),
                    v3_io.String.Input("production_profile", multiline=True, default=""),
                    v3_io.String.Input("vocal_gender", default=""),
                    v3_io.String.Input("vocal_timbre", default=""),
                    v3_io.String.Input("vocal_style", default=""),
                    v3_io.String.Input("harmony_backing", default=""),
                    v3_io.String.Input("vocal_fx", default=""),
                    v3_io.String.Input("primary_instruments", default=""),
                    v3_io.String.Input("secondary_instruments", default=""),
                    v3_io.String.Input("groove_progression", default=""),
                    v3_io.String.Input("embellishments", default=""),
                    v3_io.String.Input("section_arrangement", multiline=True, default=""),
                    v3_io.String.Input("arrangement_notes", multiline=True, default=""),
                    v3_io.Float.Input("temperature_lyrics", default=0.8, min=0.0, max=1.0),
                    v3_io.Int.Input("max_retries", default=2, min=0, max=5),
                    v3_io.Boolean.Input("safe_mode", default=True),
                ],
                outputs=[
                    v3_io.String.Output(display_name="caption"),
                    v3_io.String.Output(display_name="lyrics"),
                    v3_io.String.Output(display_name="full_prompt"),
                    v3_io.String.Output(display_name="song_idea_expanded"),
                    v3_io.String.Output(display_name="model_info"),
                    v3_io.String.Output(display_name="vram_usage"),
                    v3_io.Dict.Output(display_name="api_payload"),
                ],
            )
        
        @classmethod
        def execute(cls, **kwargs):
            # Forward to V1 implementation
            node = PromptCrafter_MiniMaxMusic3Creator()
            return node.execute(**kwargs)
    
    class PromptCrafter_MiniMaxMusic3APIConnectorV3(v3_io.ComfyNode):
        @classmethod
        def define_schema(cls):
            return v3_io.Schema(
                node_id="PromptCrafter_MiniMaxMusic3APIConnectorV3",
                display_name="🎵 MiniMax Music 3 API Connector (V3)",
                category="☠️PGFX /Creator",
                description="Sends prompts to MiniMax Music 3 API and returns audio.",
                inputs=[
                    v3_io.String.Input("api_url", default="http://127.0.0.1:8000"),
                    v3_io.String.Input("structured_caption", multiline=True),
                    v3_io.String.Input("lyrics", multiline=True),
                    v3_io.Int.Input("seed", default=0, min=0),
                    v3_io.Int.Input("max_duration", default=120, min=10, max=300),
                    v3_io.Boolean.Input("tiled_decode", default=True),
                    v3_io.Int.Input("timeout", default=1200, min=60, max=3600),
                    v3_io.String.Input("output_path", default="minimax_music3_output.wav"),
                    v3_io.Boolean.Input("debug_mode", default=False),
                ],
                outputs=[
                    v3_io.String.Output(display_name="output_path"),
                    v3_io.String.Output(display_name="status_message"),
                    v3_io.Boolean.Output(display_name="success"),
                ],
            )
        
        @classmethod
        def execute(cls, **kwargs):
            # Forward to V1 implementation
            node = PromptCrafter_MiniMaxMusic3APIConnector()
            return node.generate(**kwargs)


# ------------------------------------------------------------------------------------
# Node Registration (required for ComfyUI to discover these nodes)
# ------------------------------------------------------------------------------------
NODE_CLASS_MAPPINGS = {
    "PromptCrafter_MiniMaxMusic3Creator": PromptCrafter_MiniMaxMusic3Creator,
    "PromptCrafter_MiniMaxMusic3APIConnector": PromptCrafter_MiniMaxMusic3APIConnector,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_MiniMaxMusic3Creator": "🎵 MiniMax Music 3 Creator",
    "PromptCrafter_MiniMaxMusic3APIConnector": "🎵 MiniMax Music 3 API Connector",
}

# Add V3 nodes to mappings if available
if V3_IO_AVAILABLE:
    NODE_CLASS_MAPPINGS["PromptCrafter_MiniMaxMusic3CreatorV3"] = PromptCrafter_MiniMaxMusic3CreatorV3
    NODE_CLASS_MAPPINGS["PromptCrafter_MiniMaxMusic3APIConnectorV3"] = PromptCrafter_MiniMaxMusic3APIConnectorV3
    NODE_DISPLAY_NAME_MAPPINGS["PromptCrafter_MiniMaxMusic3CreatorV3"] = "🎵 MiniMax Music 3 Creator (V3)"
    NODE_DISPLAY_NAME_MAPPINGS["PromptCrafter_MiniMaxMusic3APIConnectorV3"] = "🎵 MiniMax Music 3 API Connector (V3)"
