# Standard library imports
import os
from dataclasses import dataclass, field
import textwrap

# Local module imports
# Import 'cache' here to resolve the circular dependency and allow direct initialization.
from . import pgfx_cache as cache


def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}

# --- Constants ---
DEFAULT_PROMPT_TEXT = "Describe your idea here. You can use multiple paragraphs to define scenes for a schedule."
FALLBACK_TEXT_MODEL = "llama3:latest" # A sensible default for text-only tasks
FALLBACK_VISION_MODEL = "qwen2.5vl:7b" # The recommended model for this node pack
DEFAULT_CAPTION_PROMPT = textwrap.dedent("""
    Create a concise, descriptive caption for this image, suitable for training an AI model.
    - Be factual and literal. Describe only what is visible.
    - Start with the main subject.
    - Use comma-separated phrases or tags.
    - Do not mention artist names, brand names, or copyrighted characters.
    - Example: a photo of a black cat, sitting on a red couch, in a dimly lit room, high quality.
""").strip()

MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 1.5
DEFAULT_MAX_TOKENS = 4096

# --- LLM Runtime Controls ---
LLM_DEVICE_OPTIONS = ["Default (GPU)", "CPU"]
_raw_llm_device = os.getenv("PGFX_LLM_DEVICE", "default").strip().lower()
DEFAULT_LLM_DEVICE = "CPU" if _raw_llm_device in {"cpu", "host"} else "Default (GPU)"
# Stateless by default to prevent cross-request conversational carryover.
DEFAULT_LLM_STATELESS = _env_flag("PGFX_LLM_STATELESS", "1")
# Allow users to run multiple LLM agents in parallel (useful for multi-GPU or powerful CPUs).
MAX_CONCURRENT_LLM_THREADS = int(os.getenv("PGFX_MAX_LLM_THREADS", "1"))


# --- Path and Global State Configuration ---
# --- Path and Global State Configuration ---
try:
    import folder_paths
    COMFYUI_ROOT_DIR = folder_paths.base_path
    MODELS_DIR = folder_paths.models_dir
    TEMP_DIR = folder_paths.get_temp_directory()
except ImportError:
    # Fallback for standalone/testing usage (non-ComfyUI environment)
    COMFYUI_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    MODELS_DIR = os.path.join(COMFYUI_ROOT_DIR, "models")
    TEMP_DIR = os.path.join(COMFYUI_ROOT_DIR, "temp")

LLM_MODEL_DIR = os.path.join(MODELS_DIR, "LLM")
QWEN_MODEL_DIR = os.path.join(MODELS_DIR, "Qwen")

# List of directories to scan for HuggingFace models
HF_MODEL_DIRS = [LLM_MODEL_DIR, QWEN_MODEL_DIR]

# Initialize the disk cache directly here to prevent race conditions.
cache_dir = os.path.join(TEMP_DIR, "comfyui-promptcrafter_cache")
CACHE = cache.DiskCache(cache_dir=cache_dir, max_size_gb=2.0)
SHARED_SESSION = None

# --- Model Caching ---
PRELOAD_MODELS = [] # List of model_ids (e.g., "gguf/llama-3-8b-instruct.Q4_K_M.gguf") to load at startup
MAX_CACHED_MODELS = 2 # Maximum number of GGUF models to keep in VRAM/RAM cache

# --- GGUF Runtime Defaults ---
# Large values (e.g. 16384) can allocate multi-GB KV caches and easily OOM on consumer GPUs.
DEFAULT_GGUF_N_CTX = int(os.getenv("PGFX_GGUF_N_CTX", "4096"))
MIN_GGUF_N_CTX = int(os.getenv("PGFX_GGUF_MIN_N_CTX", "1024"))
GGUF_DEFAULT_TIMEOUT_SECONDS = int(os.getenv("PGFX_GGUF_TIMEOUT_SECONDS", "180"))
GGUF_AUTO_TUNE = _env_flag("PGFX_GGUF_AUTO_TUNE", "1")
GGUF_PROFILE = os.getenv("PGFX_GGUF_PROFILE", "balanced").strip().lower()
if GGUF_PROFILE not in {"safe", "balanced", "speed"}:
    GGUF_PROFILE = "balanced"
# GPU offload defaults: keep text models fast by default, keep vision models stable by default.
DEFAULT_GGUF_N_GPU_LAYERS_WAS_SET = os.getenv("PGFX_GGUF_N_GPU_LAYERS") is not None
VISION_GGUF_N_GPU_LAYERS_WAS_SET = os.getenv("PGFX_VISION_GGUF_N_GPU_LAYERS") is not None
DEFAULT_GGUF_N_GPU_LAYERS = int(os.getenv("PGFX_GGUF_N_GPU_LAYERS", "-1"))
VISION_GGUF_N_GPU_LAYERS = int(os.getenv("PGFX_VISION_GGUF_N_GPU_LAYERS", "0"))
# Conservative batch defaults to avoid CUDA VMM spikes during decode on 8-12GB cards.
DEFAULT_GGUF_N_BATCH_WAS_SET = os.getenv("PGFX_GGUF_N_BATCH") is not None
DEFAULT_GGUF_N_UBATCH_WAS_SET = os.getenv("PGFX_GGUF_N_UBATCH") is not None
VISION_GGUF_N_BATCH_WAS_SET = os.getenv("PGFX_VISION_GGUF_N_BATCH") is not None
VISION_GGUF_N_UBATCH_WAS_SET = os.getenv("PGFX_VISION_GGUF_N_UBATCH") is not None
DEFAULT_GGUF_N_BATCH = int(os.getenv("PGFX_GGUF_N_BATCH", "512"))
DEFAULT_GGUF_N_UBATCH = int(os.getenv("PGFX_GGUF_N_UBATCH", "256"))
VISION_GGUF_N_BATCH = int(os.getenv("PGFX_VISION_GGUF_N_BATCH", "128"))
VISION_GGUF_N_UBATCH = int(os.getenv("PGFX_VISION_GGUF_N_UBATCH", "64"))
# Retrying GPU OOM loads in CPU mode can crash some llama.cpp builds; keep off by default.
GGUF_ENABLE_CPU_RETRY = _env_flag("PGFX_GGUF_ENABLE_CPU_RETRY", "0")
# Large vision GGUFs frequently collide with downstream diffusion/ACE loads on 8-12GB GPUs.
# Unload after query by default; set PGFX_GGUF_UNLOAD_VISION_AFTER_QUERY=0 to keep cached.
GGUF_UNLOAD_VISION_AFTER_QUERY_WAS_SET = os.getenv("PGFX_GGUF_UNLOAD_VISION_AFTER_QUERY") is not None
GGUF_UNLOAD_VISION_AFTER_QUERY = _env_flag("PGFX_GGUF_UNLOAD_VISION_AFTER_QUERY", "1")
# Vision projector (mmproj/mtmd) is large and can hard-abort llama.cpp on CUDA OOM.
# Keep projector on CPU by default; enable with PGFX_GGUF_VISION_PROJECTOR_USE_GPU=1 if you have ample VRAM.
GGUF_VISION_PROJECTOR_USE_GPU_WAS_SET = os.getenv("PGFX_GGUF_VISION_PROJECTOR_USE_GPU") is not None
GGUF_VISION_PROJECTOR_USE_GPU = _env_flag("PGFX_GGUF_VISION_PROJECTOR_USE_GPU", "0")
# Qwen3-VL grounding can degrade when image tokens are too low.
# Set PGFX_QWEN_VL_IMAGE_MIN_TOKENS=1024+ for better grounding/lip-sync prompt reliability.
QWEN_VL_IMAGE_MIN_TOKENS_WAS_SET = os.getenv("PGFX_QWEN_VL_IMAGE_MIN_TOKENS") is not None
QWEN_VL_IMAGE_MIN_TOKENS = max(0, int(os.getenv("PGFX_QWEN_VL_IMAGE_MIN_TOKENS", "1024")))
# Qwen-VL MRope models (Qwen3-VL) cannot use llama.cpp's context shift (seq_add).
# Increase n_ctx to avoid triggering the shift when processing large images.
# Set PGFX_QWEN_VL_MIN_N_CTX=4096 (or lower) to reduce VRAM usage if you use small images.
QWEN_VL_MIN_N_CTX = int(os.getenv("PGFX_QWEN_VL_MIN_N_CTX", "8192"))

# --- Dependency Flags (set at runtime in __init__.py) ---
LLAMA_CPP_AVAILABLE = False
QWEN_VL_AVAILABLE = False
LANGDETECT_AVAILABLE = False
PYPDF_AVAILABLE = False
DUCKDUCKGO_SEARCH_AVAILABLE = False
LIBROSA_AVAILABLE = False
MATPLOTLIB_AVAILABLE = False
PIEXIF_AVAILABLE = False
FFMPEG_PYTHON_AVAILABLE = False

# --- API Configuration ---
LOCAL_SERVER_CONFIG = {
    "ollama": {
                "base_url": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
        "timeout": int(os.getenv("OLLAMA_TIMEOUT", "120")),
        "enabled": True,
    },
    "lmstudio": {
                "base_url": os.getenv("LMSTUDIO_BASE_URL", "http://127.0.0.1:1234"),
        "timeout": int(os.getenv("LMSTUDIO_TIMEOUT", "120")),
        "enabled": False, # Users can enable this if they use LM Studio
    },
    "text-generation-webui": {
                "base_url": os.getenv("OOBABOOGA_BASE_URL", "http://127.0.0.1:5000"),
        "timeout": int(os.getenv("OOBABOOGA_TIMEOUT", "120")),
        "enabled": False, # Users can enable this if they use text-generation-webui
    }
}
# --- Style and Prompting Configuration ---

SAFE_MODE_RULE = "CRITICAL SAFETY RULE: Do not generate content that is NSFW, sexually explicit, violent, gory, or depicts hate speech. All output must be safe for work."

# --- Model format and LTX-2.3 Prompting Guidelines ---

MODEL_FORMAT_OPTIONS = [
    "Generic (SD1.5, SD2.1)",
    "Fooocus",
    "Stable Diffusion 3",
    "Stable Cascade",
    "FLUX / Qwen / Hunyuan",
    "FLUX.2 (Image / Editing)",
    "ACE-Step 1.5 (Music / Lyrics)",
    "MiniMax H3 (Video / Audio)",
    "LTX-2.3 (Video / Audio / Retake)",
    # Kept for workflows saved before the clearer LTX-2.3 label was added.
    "LTX-2 (Audio/Lip Sync/Retake)",
]


def is_ltx23_target(target_model_format: str) -> bool:
    """Return whether a target format should use the LTX-2.3 video profile."""
    normalized = str(target_model_format or "").strip().lower()
    return normalized.startswith("ltx-2") or normalized in {"ltx2", "generic video (wan, etc.)"}


def is_flux2_target(target_model_format: str) -> bool:
    """Return whether a target format should use the FLUX.2 image profile."""
    normalized = str(target_model_format or "").strip().lower()
    return "flux" in normalized


def is_acestep_target(target_model_format: str) -> bool:
    """Return whether a target format should use the ACE-Step 1.5 profile."""
    normalized = str(target_model_format or "").strip().lower()
    return "ace-step" in normalized or "ace step" in normalized or "acestep" in normalized


def is_h3_target(target_model_format: str) -> bool:
    """Return whether a target format should use the MiniMax H3 profile."""
    normalized = str(target_model_format or "").strip().lower()
    return "h3" in normalized or "minimax" in normalized


def get_model_prompt_guidelines(target_model_format: str, mode: str = "Video") -> str:
    """Return the shared model-specific prompt profile for a target format."""
    if is_h3_target(target_model_format):
        return f"""
MODEL-SPECIFIC PROMPTING GUIDELINES (MiniMax H3 {mode} Generation):
{H3_PROMPT_GUIDELINES}

{H3_PROMPT_CATEGORIES}
""".strip()
    if is_acestep_target(target_model_format):
        return f"""
MODEL-SPECIFIC PROMPTING GUIDELINES (ACE-Step 1.5 {mode} Generation):
{ACESTEP_PROMPT_GUIDELINES}

{ACESTEP_PROMPT_CATEGORIES}
""".strip()
    if is_flux2_target(target_model_format):
        return f"""
MODEL-SPECIFIC PROMPTING GUIDELINES (FLUX.2 {mode} Generation):
{FLUX2_PROMPT_GUIDELINES}

{FLUX2_PROMPT_CATEGORIES}
""".strip()
    if is_ltx23_target(target_model_format):
        return f"""
MODEL-SPECIFIC PROMPTING GUIDELINES (LTX-2.3 {mode} Generation):
{LTX2_PROMPT_GUIDELINES}

{LTX2_VIDEO_PROMPT_CATEGORIES}
""".strip()
    return ""


FLUX2_PROMPT_GUIDELINES = """
FLUX.2 PROMPTING GUIDELINES:
- Do not use negative prompts. Describe the desired result positively, such as "sharp focus throughout" or "an empty street".
- Put the most important information first. Use the order: main subject, key action or pose, critical style, essential context, then secondary details.
- Use natural language and specific nouns. For most images, aim for 10-80 words; use longer prompts only when the scene needs complex control.
- Associate every important color with a specific object. Use exact hex codes when color matching matters, for example "the sofa in hex #1B6B6F".
- For photorealism, name a camera, lens, film stock, lighting setup, or era when it contributes to the intended look.
- For typography, put the exact text in quotation marks and specify its placement, font character, size, color, and relationship to the layout.
- Use structured JSON when a complex scene has several subjects, relationships, colors, or production fields that need independent control. Natural language remains preferable for simple or exploratory prompts.
- For multi-reference editing, state the role of each image explicitly: subject identity, clothing, pose, background, composition, or style.
- Prompt in the language that best represents the desired cultural context when that improves authenticity.
""".strip()

FLUX2_PROMPT_CATEGORIES = """
FLUX.2 DETAIL VOCABULARY:
- Structure: subject, action, style, context; foreground, background, position, composition, camera angle, lens, depth of field.
- Photorealism: Sony A7IV, Fujifilm X-T5, Hasselblad X2D, Canon 5D Mark IV, 35mm lens, 80mm lens, f/1.4, f/2.8, shallow depth of field, HDR, direct flash, Kodak Portra 400, film grain, 2000s digicam.
- Typography and design: headline, subtext, callout, serif, sans serif, handwritten, industrial lettering, centered, below the main text, large headline, small body copy, editorial layout.
- Color: color #FF5733, hex #1B6B6F, exact color match, gradient from #02EB3C to #EDFA3C, warm terracotta, deep teal, golden amber.
- Lighting and context: natural daylight, soft diffused light, three-point softbox, golden hour, neon, overcast, studio background, documentary, editorial, minimalist.
""".strip()

ACESTEP_PROMPT_GUIDELINES = """
ACE-STEP 1.5 PROMPTING GUIDELINES:
- Treat generation as an iterative human-guided process. Produce a strong, usable direction that leaves room for musical variation instead of trying to specify every sound.
- Caption is the global musical portrait: genre, mood, instruments, vocal character, timbre, production texture, era, and overall energy.
- Lyrics are the temporal script: lyric content, section structure, vocal delivery, instrumental breaks, and energy changes over time.
- Keep Caption and Lyrics consistent. Instruments, vocal style, emotion, and energy described in one must not contradict the other.
- Use specific combinations of genre, emotion, instruments, timbre, production, vocal traits, rhythm, and structure. Resolve conflicting styles as a temporal evolution rather than mixing incompatible instructions at once.
- Keep complex style descriptions in Caption. Keep section tags concise so the model does not mistake long instructions for lyrics.
- For instrumental music, use [Instrumental] or concise instrumental sections such as [Intro - ambient], [Main Theme - piano], and [Outro - fade out].
- Keep lyric lines singable. Aim for roughly 6-10 syllables per line and similar line lengths within the same section. Use blank lines between sections.
- Use parentheses for background vocals or harmonies, uppercase sparingly for stronger vocal intensity, and stretched vowels only when musically necessary.
- Prefer one coherent core metaphor or image system across a song. Avoid adjective stacking, forced rhymes, mixed metaphors, blurred section boundaries, and lines too long for one breath.
- Treat BPM, key, time signature, vocal language, and duration as metadata controls when dedicated inputs exist. Do not duplicate them in Caption unless the user explicitly asks for them there.
""".strip()

ACESTEP_PROMPT_CATEGORIES = """
ACE-STEP 1.5 DETAIL VOCABULARY:
- Caption dimensions: pop, rock, jazz, electronic, hip-hop, R&B, folk, classical, lo-fi, synthwave; melancholic, uplifting, energetic, dreamy, dark, nostalgic, euphoric, intimate.
- Instruments: acoustic guitar, piano, synth pads, 808 drums, strings, brass, electric bass, choir, drum machine.
- Timbre and production: warm, bright, crisp, muddy, airy, punchy, lush, raw, polished, lo-fi, high-fidelity, live recording, studio-polished, bedroom pop.
- Vocal direction: female vocal, male vocal, breathy, powerful, falsetto, raspy, whispered, spoken word, belting, harmonies, call and response, ad-lib.
- Structure tags: [Intro], [Verse], [Verse 1], [Pre-Chorus], [Chorus], [Bridge], [Outro], [Build], [Drop], [Breakdown], [Instrumental], [Guitar Solo], [Piano Interlude], [Fade Out].
- Tag modifiers: use one concise modifier, such as [Chorus - anthemic], [Bridge - whispered], or [Intro - ambient].
- Energy: low energy, restrained, building energy, high energy, explosive, melancholic, euphoric, dreamy, aggressive.
- Audio control: reference audio controls global timbre, mixing, performance, and atmosphere; source audio controls melody, rhythm, chords, and orchestration in Cover mode; Repaint controls a specified local interval.
- Model planning: No LM is appropriate when the user supplies the plan or uses constrained audio workflows; 0.6B favors speed and low VRAM; 1.7B is the default balance; 4B favors complex or long-tail styles. Turbo is the daily 8-step choice; SFT is the slower CFG-tunable choice; Base is for extract, lego, complete, and fine-tuning workflows.
""".strip()

H3_PROMPT_GUIDELINES = """
MINIMAX H3 PROMPTING GUIDELINES:
- First identify the input mode: T2VA, I2VA, FL2VA, L2VA, or full-reference Ref2VA.
- For T2VA, build the complete audiovisual timeline from text with no alignment line. For I2VA, begin from the supplied first frame and develop forward. For FL2VA, describe the continuous visual path between first and last frames. For L2VA, infer a plausible opening and converge toward the supplied last frame.
- For base modes, write the whole clip as one continuous shot: only [Shot 1], no timestamp, camera motion instead of a cut. Use exactly three fields in order: integrated_multimodal_description, overall_soundscape, non_diegetic_music.
- For I2VA, the first line must be exactly: For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
- For FL2VA, the first line must be exactly: How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video. (Replace S.SS with the actual end time.)
- For L2VA, the first line must be exactly: How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video. (Replace S.SS with the actual end time.)
- For Ref2VA, preserve these exact fields and order: subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, non_diegetic_music.
- In Ref2VA, later cuts begin with [Shot N] At MM:SS.mmm using exactly three decimal places. Base modes never cut; keep one [Shot 1] and use camera movement.
- Describe each shot by composition, subjects, environment, actions, camera, synchronized sound, and the exact point where referenced content appears.
- Keep dialogue and synchronized effects in the timeline, continuing ambience and physical sounds in overall_soundscape, and audience-only score in non_diegetic_music. Use N/A when no score is wanted.
- Write rewrite sections in English, but preserve dialogue, lyrics, and visible scene text in their original language.
- In Ref2VA, use <Subject N> for reusable visible content, <Picture N> for concrete frame anchors, <Video N> for whole-video structure, and <Audio N> only for active audio copy/reference. Define every label before use and keep its meaning stable.
- In dialogue, assign stable speaker IDs as (S1), (S2); keep only the language tag and exact spoken words inside <d>. Preserve visible text in English double quotation marks.
- Use concrete audiovisual instructions rather than a plot summary. Do not invent unresolved references or timing that does not match the request.
- Keep the complete output under 7000 characters so it can be submitted to MiniMax H3 without truncation.
- Keep visual and audio intent integrated while separating diegetic sound from non-diegetic music.
""".strip()

H3_PROMPT_CATEGORIES = """
MINIMAX H3 STRUCTURE VOCABULARY:
- Base fields: integrated_multimodal_description, overall_soundscape, non_diegetic_music.
- Full-reference fields: subject_definitions, summary, retention_analysis, detailed_description, overall_soundscape, non_diegetic_music.
- I2VA alignment line: For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
- FL2VA alignment line: How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.
- L2VA alignment line: How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.
- Camera moves: push in, pull out, truck left/right, pedestal, pan, tilt, arc, tracking, POV, roll, static shot, handheld, dolly in/out, orbit. End camera motion with one of: with small amplitude, with large amplitude, at slow speed, at fast speed.
- Banned with camera moves: slide, shake, zoom in, zoom out, and any pure speed or direction words that are not in the allowed endings.
- Visual detail: shot size, composition, subject position, environment, lighting, action, camera movement, transitions, keyframe continuity.
- Audio detail: ambience, dialogue, voice direction, sound effects, musical score, intensity, timing, and whether each sound is diegetic or non-diegetic.
- overall_soundscape: 3-5 real sounds (ambience, physical sounds, non-verbal human sounds); never repeat dialogue or music, never write invented words.
- Reference modes: first frame, last frame, start frame, end frame, continuous path, retained subject identity, retained wardrobe, retained composition, retained audio character.
""".strip()

LTX2_PROMPT_GUIDELINES = """
LTX-2.3 PROMPTING GUIDELINES:
- Specificity wins. Describe multiple subjects, spatial relationships, actions, materials, lighting, and atmosphere when they matter.
- Direct the scene like a director: state foreground/background, left/right placement, facing direction, distance, and the dominant shot idea.
- Use verbs, especially for image-to-video. Name who moves, what changes, how the camera moves, and any environmental motion.
- Avoid static, photo-like descriptions. Give the scene one dominant event or shot idea instead of several competing moments.
- Describe texture and material: fabric, hair, stone, metal, wood, surface finish, wear, reflections, and edge detail.
- Compose native portrait video intentionally when the output is vertical; do not describe a landscape that should merely be cropped.
- Describe audio when wanted: ambience, music, sound effects, dialogue, language, accent, voice quality, and volume. Put spoken dialogue in quotation marks.
- Use present tense and one flowing paragraph of 4-8 descriptive sentences. Organize the prompt as subject, action, camera, then mood.
- Match detail to shot scale: close-ups need precise facial, hair, fabric, and surface detail; wide shots need spatial and environmental detail.
- Avoid abstract emotional labels without visible cues, readable text or logos, complex physics, overloaded scenes, conflicting lighting, and unnecessary instructions.
""".strip()

LTX2_VIDEO_PROMPT_CATEGORIES = """
LTX-2.3 DETAIL VOCABULARY:
- Camera: follows, tracks, pans across, circles around, tilts upward, pushes in, pulls back, overhead, handheld, over-the-shoulder, wide establishing shot, static frame, slow dolly in.
- Scale: expansive or epic, intimate or claustrophobic, wide, medium, close-up.
- Pacing: slow motion, time-lapse, rapid cuts, lingering shot, continuous shot, freeze-frame, fade-in, fade-out.
- Film characteristics: film grain, lens flare, jittery stop-motion, pixelated edges.
- Lighting: flickering candles, neon glow, natural sunlight, dramatic shadows, backlight, soft rim light, warm tungsten, cool blue ambient.
- Texture: rough stone, smooth metal, worn fabric, glossy surfaces, weathered wood, matte finish.
- Atmosphere and color: fog, rain, dust, smoke, mist, particles, golden hour, overcast, vibrant, muted, monochromatic, high contrast, warm or cool tones.
- Audio and voice: coffee shop noise, wind and rain, forest ambience, traffic hum, ocean waves, whisper, mutter, shout, scream, clear voice, robotic voice, radio distortion.
""".strip()
DEFAULT_CHINESE_NEGATIVE_PROMPT = "模糊，畸形，失真，低质量，丑陋，额外肢体，残缺，水印，签名，文本，错误，解剖不当"

NEGATIVE_KEYWORDS = {
    "quality": ["blurry", "distorted", "low quality", "ugly", "jpeg artifacts", "pixelated"],
    "composition": ["bad composition", "cropped", "cut off", "out of frame", "tiling"],
    "anatomy": ["deformed", "disfigured", "malformed", "mutated", "extra limbs", "missing limbs", "bad anatomy"],
    "text": ["watermark", "signature", "text", "username", "logo"],
    "contextual": {
        "person": ["cartoon", "3d", "disney", "cgi", "rendering", "anime"],
        "photograph": ["drawing", "painting", "illustration", "sketch"],
        "landscape": ["people", "animals", "vehicles"],
    }
}

@dataclass
class PromptCrafterRunConfig:
    """A dataclass to hold all runtime configuration for a node execution."""
    # Core execution params
    model: str
    language: str
    temperature: float
    seed: int
    timeout: int
    debug_mode: bool
    safe_mode: bool
    
    # Prompt generation params
    image_count: int
    max_length_words: int
    style_override: str
    critique_strength: str
    max_retries: int
    simplify_for_diffusion: bool

    # --- Fields with default values ---
    use_chat_api: bool = True
    use_deep_think: bool = True
    deep_think_confidence: float = 0.8
    negative_concepts: str = ""
    style_profile: dict = field(default_factory=dict)
    thinking_model: str = ""
    instruct_model: str = ""

    # Lyrics-specific params
    interpolate_keyframes: bool = False
    interpolation_frame_interval: int = 0
    fps: float = 16.0
    song_length_seconds: float = 0.0
    use_audio_alignment: bool = True

    # Target format / model-specific guidelines
    target_model_format: str = "Generic (SD1.5, SD2.1)"

    # Brain/Lobe controls
    artistry: float = 0.5
    creativity: float = 0.5
    llm_device: str = "Default (GPU)"
    reset_context: bool = True

    def __post_init__(self):
        # Ensure numeric types are correct
        self.temperature = float(self.temperature)
        self.seed = int(self.seed)
        self.timeout = int(self.timeout)
        self.max_length_words = int(self.max_length_words)
        self.max_retries = int(self.max_retries)
        self.image_count = int(self.image_count)
        # Ensure lyrics-specific numeric types are correct
        self.fps = float(self.fps)
        self.song_length_seconds = float(self.song_length_seconds)
        self.artistry = float(self.artistry)
        self.creativity = float(self.creativity)
        device_choice = str(self.llm_device).strip().lower()
        self.llm_device = "CPU" if device_choice in {"cpu", "host"} else "Default (GPU)"
        self.reset_context = bool(self.reset_context)
