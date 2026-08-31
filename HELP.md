# PGFX PromptCrafter — Help

This file provides the technical text shown in ComfyUI’s `?` tooltip for PGFX nodes.
For full feature showcases and installation guides, see `README.md`.

---

## `PGFX_VisualFolderLoader` (Visual Folder Browser & Dataset Curation Workspace)
A high-performance file and image explorer and dataset curator designed to preview any directory and manage image captions.

**Key Technical Behaviors:**
- **Full-Folder Browsing:** Lists every file in the folder — not just images. Videos, audio, text, JSON, subtitles, models, and anything else shows up in the grid, so you can inspect a directory at a glance.
- **File-Type Filter:** A dropdown next to the search box narrows the grid to **All Files** (default), Images, Videos, Audio, Text/Data, or Models. A **Custom extension** input accepts any arbitrary type (e.g. `.psd`, `mp3`) to show only files with that extension.
- **File Tiles:** Images render as lazy-loaded thumbnails; every other file type renders as a type icon with its filename (🎬 video, 🎵 audio, 📄 text, 🧠 model, 💬 subtitle, …), so non-image results are never blank or broken.
- **Recursive Deep-Scan:** Uses advanced directory walking to find every subfolder within your output path, no matter how deep.
- **Thumbnail Optimization:** Forces compressed previews (JPEG) when listing folders, preventing browser lag when viewing hundreds of high-res images.
- **Strict Pagination:** Limits rendering page size to maintain high canvas rendering frame rates.
- **Dataset Captioning Workspace:**
  - Manages `.txt` sidecar files stored next to each image, ideal for model/LoRA training datasets.
  - Displays a green `TXT` badge in the bottom-right corner of already-captioned thumbnails in the grid.
  - Supports on-demand single-image caption generation (`✨ Generate`) and sequential, cancelable batch captioning (`📝 Caption All` with a `🛑 Stop Batch` control).
  - Includes a background `auto_captioning` execution switch (`Always`, `If Missing`, `Disabled`) to write sidecar text files on the fly during workflow runs.
  - Caption operations (single and batch) only apply to images, never to non-image files.
- **Canvas Prompt Output:** Outputs a third parameter (`caption` as a `STRING`) representing the loaded image's caption text, making it easy to route tags/prompts directly into CLIP encoders.
- **Technical Metadata Panel:** Real-time extraction of file type, size, and modification date on selection; resolution is shown for images and `-` for other file types.

---

## `PGFX_UniversalSwitchBox`
An intelligent routing node for dynamic branching workflows that eliminates the need for separate signal wiring.

**Key Technical Behaviors:**
- **Signal-less Auto-Detection:** Automatically executes and routes as soon as data is detected on any input pin.
- **Universal Routing:** Supports all data types (Images, Latents, Masks, Text, etc.) via wildcard pins.
- **Switching Modes:**
    - **Auto-Detect (Priority):** Intelligently scans all connected pins (1–16) and selects the first active branch it finds.
    - **Chronological (Index):** Standard selection via numerical index.
    - **Random Select:** Picks a random active input on every execution.
- **Type-Safe Previews:** Displays a live thumbnail only if an image is being routed; otherwise, it provides a clean status indicator.

---

## `PGFX_CinemaVisemeRig`
A high-fidelity procedural animation rig designed to drive realistic mouth movements for **WanVideo** and **LTX-Video** pipelines. It eliminates "AI jitter" by using physics-based timing and temporal smoothing.

### 🚀 Recommended Workflow
1. **Drive with WhisperX:** Connect the `audio_meta` from a WhisperX node for perfect millisecond-level word timing.
2. **Smooth Your Motion:** Use a `smoothing_sigma` of **1.2 to 1.5** for cinematic fluidity.
3. **ControlNet Focus:** Connect the `lip_mask` to a ControlNet (Canny or Depth) to force the AI to focus only on the phonetic area.

### 📥 Model Requirements
To get the best results, you should have the following models installed:

*   **LivePortrait (Gold Standard):** Optimized for the "LivePortrait" target mode.
    *   [Download LivePortrait Models (HuggingFace)](https://huggingface.co/Kijai/LivePortrait_safetensors/tree/main)
*   **ControlNet Union (SDXL/Flux):** Excellent for driving the "Canny" and "Depth" modes.
    *   [Download ControlNet Union (HuggingFace)](https://huggingface.co/xinsir/controlnet-union-sdxl-1.0)
*   **MediaPipe Face:** Best for general landmark driving.

---

## `PGFX_LogoDesignerAgent`
The "Elite" AI consultant for the Logo Designer Studio.

**Elite Enhancements:**
- **Reasoning Awareness:** Automatically detects if you are using a reasoning model (like DeepSeek-R1) and wraps instructions in a `<thought>` trigger to improve complex layout accuracy.
- **Forced JSON Mode:** Natively enforces valid JSON outputs, ensuring that even 3B/7B models can reliably populate the Designer Studio settings.

---

## `PGFX_LogoDesignerMCPAgent`
A general-purpose, fire-and-forget ComfyUI MCP Agent that builds and executes workflows from natural language requests.

**Features:**
- **Chat-Driven:** Describe what you want to create in plain English - the agent interprets your request and runs the matching pipeline (image / video / audio / animation).
- **Model-Agnostic Routing:** Never hard-codes a model; it picks the template that matches the requested output type and wires your prompt + reference media into it.
- **Tool-Calling:** The LLM drives a real tool loop (template/node/model discovery, workflow fetch, slot editing, validation, submit, poll, fetch).
- **Reference Media:** Accept optional input images or audio as starting points for img2img / video / TTS.
- **Background Execution (non-blocking):** The agent runs on a background thread and returns immediately, so it never deadlocks ComfyUI's single serial queue worker. Results land in the ComfyUI output directory — browse them with a thumbnail/load node.

**Workflow:**
1. Send a chat message describing what you want to create
2. The node returns `QUEUED_ASYNC` immediately and generates in the background
3. The agent finds and runs the appropriate template, wiring in your prompt and reference media
4. Finished files (image / `.mp4` / audio) are written to the ComfyUI output directory
5. Open that folder in a thumbnail/load node to see and use the results

**Output:** a single `status` string (the node is an `OUTPUT_NODE` trigger — it has no synchronous media output pins).

---

## `PromptCrafter_QnA`
A flexible AI assistant optimized for long-form creative dialogue.

**Elite Enhancements:**
- **Automated Summary Lobe:** Monitors the length of your conversation history. When context exceeds ~1500 words, it automatically performs a "State Summary" pass to condense the history, keeping the assistant fast and accurate without losing the narrative thread.
- **Dual-Model Logic:** Allows separate "Reasoning" and "Formatting" models to work together for superior intelligence.

---

## `PGFX_LogoDesignerStudio`
A persistent vector design environment.

**Pro Features:**
- **Flicker-Free Loading:** Snaps the canvas to a perfectly centered fit immediately upon dependency load.
- **Resilient Engine:** Automatic local fallback if the Fabric.js CDN is unreachable.
- **Precision Sliders:** Features live numerical readouts for all styling adjustments (Size, Opacity, Rotation, etc.).

---

## `PromptCrafter_LyricsThink`
Specialized reasoning lobe for lyric correction.
- **Timing Alignment:** Ensures corrected lyrics match the locked 4-second segment windows.
- **Context Expansion:** Automatically generates stylistically consistent lyrics for instrumental or short segments.

---

## `PromptCrafter_VisualThink`
Creative visual direction engine.
- **Cinematic Vision:** Translates brief instructions into rich, multi-dimensional scene descriptions (Lighting, Camera, Mood, etc.).
- **Multi-Modal aware:** Analyzes connected reference images to ground descriptions in existing visual context.

---

## `PromptCrafter_OllamaRouterNode`
The ultimate bridge for local LLM power.
- **Robustness:** Built-in auto-repair for truncated JSON and segmented responses.
- **Multimodal:** Supports vision inputs and PDF text extraction directly in your graph.

---

## `PromptCrafter_FileOrganizer`
Automated asset management for heavy production cycles.
- **Rule-Based:** Automatically moves, copies, or renames output files based on your project configuration.
- **Vibe Check integration:** Synchronizes with project manifest data for strong continuity.

---

## `PromptCrafter_CacheUtility`
Performance maintenance tool.
- **VRAM Control:** Manually clear model caches or trigger system garbage collection to reclaim memory for heavy samplers.

---

## Best Practices for Local LLMs

To get the most out of the PGFX "Elite" backbone:

1. **Leverage Reasoning Models:** Use `deepseek-r1` or `o1` for the "Thinking" model slots in Creator and QnA nodes. Their internal Chain of Thought significantly improves adherence to complex "Shot List" and "Material" instructions.
2. **Hardware Scaling:** Set `PGFX_MAX_LLM_THREADS` to `2` or `4` if you have ample VRAM. This allows your "Director" and "Artist" agents to generate prompts simultaneously, drastically reducing execution time.
3. **Pattern Guidance:** The PGFX system uses **Few-Shot Prompting**. If a model is struggling, providing a single example of your desired output in the "User Prompt" will often be more effective than adding more "Strict Rules."

---

## Customizing Profiles
Profiles are stored in the repo root and control dropdown presets:
- `style_profiles.json`
- `captioner_profiles.json`
- `organization_profiles.json`

After editing profiles, restart ComfyUI to refresh dropdown options.

---

## `PromptCrafter_MiniMaxMusic3Creator`
Creates structured prompts (Caption + Lyrics) for the MiniMax-Music3 model from song ideas.

**Key Features (adapted from HOT-Step-PGFX-Edition):**
- **Multi-Genre Mixing:** Build an ordered genre blend list. First genre added = PRIMARY (dictates song structure: verse count, section order). Each additional genre = seasoning (influences vocabulary/tone only, with 85%→35% sliding-scale weights). Use the `genre_add` dropdown to pick genres one at a time, or type directly into the `genres` field (comma-separated).
- **237 Genre Options:** Full dropdown covering Pop, Rock, Electronic, Hip-Hop, R&B/Soul, Metal, Jazz, Classical, Country, Folk, Blues, Reggae (incl. Patois variants), DJ/Turntablism, Latin, Soundtrack, Experimental, Traditional/World, and more.
- **Auto-Gen Subject:** Generate random song subjects from 18 relational role templates (e.g., "something the protagonist is trying to get back to"). Avoids repeats across runs via deque tracking.
- **🎲 Random Buttons:** Toggle randomize for BPM (genre-appropriate ranges), Key, and Scale.
- **🎲 Random Genre:** Replaces the primary genre (first in list) while keeping any seasoning genres intact.
- **Instrumental Mode:** Toggle to generate instrumental tracks — omits the Vocal Details section from the caption entirely.
- **Audio Duration:** Set target track length from 15s to 300s (5 minutes).
- **Content Safety:** Optional `safe_mode` filters inappropriate content from generated captions and lyrics.
- **Slop Word Replacement:** Automatically replaces generic AI words (ethereal, shimmer, cascade, neon) with genre-appropriate alternatives.
- **Caption Validation:** Checks output has all 3 required sections (Global Metadata, Vocal Details, Arrangement) with correct word count (250–450 words).

**Required Inputs:**
- `song_idea` — Describe your song idea, mood, or vibe (empty if using Auto-Gen)
- `model` — LLM for caption/lyric generation
- `genre_add` — Dropdown picker to add genres to the blend list
- `genres` — Active genre blend (comma-separated, ordered). Edit directly or use picker above
- `clear_genres` — Wipe the genre list and start fresh
- `randomize_genre` — Replace primary genre with random selection
- `instrumental` — Generate instrumental (no vocals)
- `audio_duration` — Target length in seconds (15–300)
- `bpm` / `randomize_bpm` — Tempo (40–240 BPM)
- `key` / `randomize_key` — Musical key
- `scale` / `randomize_scale` — Major or Minor
- `lyrics` — Song lyrics with section tags (if empty, lyrics auto-generate)
- `subject_mode` — Manual / Auto-Gen / Hybrid
- `lyric_language` — Language for auto-generated lyrics (10 languages)
- `vram_optimization` — VRAM tier (8GB–24GB+)
- `temperature` — LLM creativity (0.0–1.0)
- `seed` — Random seed (-1 for random)
- `timeout` — LLM call timeout in seconds
- `debug_mode` — Verbose logging

**Optional Inputs (Advanced):**
- `emotional_progression` — Emotional arc description
- `listening_scenario` — Where/when would someone listen?
- `production_profile` — Production style description
- `vocal_gender`, `vocal_timbre`, `vocal_style` — Vocal characteristics
- `harmony_backing`, `vocal_fx` — Backing vocals and effects
- `primary_instruments`, `secondary_instruments` — Instrumentation
- `groove_progression`, `embellishments` — Rhythm and texture details
- `section_arrangement`, `arrangement_notes` — Custom section layout
- `temperature_lyrics` — Lyric generation creativity (0.0–1.0)
- `max_retries` — LLM retry attempts (0–5)
- `safe_mode` — Content safety filtering

**Outputs:**
- `caption` — 3-section structured music description (Global Metadata + Vocal Details + Arrangement)
- `lyrics` — Song text with section tags [Intro] [Verse] [Pre-Chorus] [Chorus] [Post-Chorus] [Bridge] [Instrumental] [Solo] [Outro]
- `full_prompt` — Combined caption for reference
- `song_idea_expanded` — Expanded concept text
- `model_info` — JSON with generation parameters
- `vram_usage` — JSON with VRAM optimization details
- `api_payload` — Ready-to-use API payload for the connector node

---

## `PromptCrafter_MiniMaxMusic3APIConnector`
Sends structured caption + lyrics to a MiniMax Music 3 server and returns generated audio.

**Key Features:**
- **Official API Format:** Sends POST to `/v1/audio/speech` with `input` (lyrics), `instructions` (caption), `seed`, `max_duration`, `stream`, `response_format`, `tiled_decode`.
- **VRAM-Aware Duration:** Set max_duration from 10s to 300s (5 minutes).
- **Tiled Decode:** Overlapping tile decoding to reduce VRAM usage (slight risk of seams).
- **Auto-Save:** Saves generated WAV to ComfyUI output directory.

**Inputs:**
- `api_url` — URL of running MiniMax Music 3 server (default: `http://127.0.0.1:8000`)
- `structured_caption` — From the Creator node's caption output
- `lyrics` — From the Creator node's lyrics output
- `seed` — Random seed for reproducibility (0 = random)
- `max_duration` — Target song length in seconds (10–300)
- `tiled_decode` — Enable tiled VAE decode for low VRAM
- `timeout` — Connection/generation timeout in seconds (60–3600, default: 1200)
- `output_path` — Custom output filename (default: `minimax_music3_output.wav`)
- `debug_mode` — Verbose logging

**Outputs:**
- `output_path` — Path to generated WAV file
- `status_message` — Success/error message
- `success` — Boolean indicating if generation succeeded

---

## `PromptCrafter_MiniMaxMusic3CreatorV3`
V3 API version of the MiniMax Music 3 Creator node. Same functionality as the V1 version, using the ComfyUI V3 API schema system.

See `PromptCrafter_MiniMaxMusic3Creator` for full feature description.

---

## `PromptCrafter_MiniMaxMusic3APIConnectorV3`
V3 API version of the MiniMax Music 3 API Connector node. Same functionality as the V1 version, using the ComfyUI V3 API schema system.

See `PromptCrafter_MiniMaxMusic3APIConnector` for full feature description.
