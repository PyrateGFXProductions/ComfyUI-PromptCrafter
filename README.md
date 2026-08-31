# ☠️ PGFX PromptCrafter — ComfyUI Node Pack

**Agentic creative tooling for ComfyUI.** A modular node pack that brings LLM-driven prompt engineering, a dual-mode image browser, a full vector+3D design studio, music generation pipelines, and production safety tools into your graph — optimized for local reasoning models (DeepSeek-R1, Llama 3.3, etc.) and modern ComfyUI Frontend V2.

---

## Screenshots

<!-- Add your screenshots to the screenshots/ folder and update the paths below -->

| Logo Designer Studio | Visual Folder Browser | MiniMax Music 3 Creator | QnA Dual-Model Chain |
|:---:|:---:|:---:|:---:|
| ![Logo Designer Studio](screenshots/logo_designer_studio.png) | ![Visual Folder Browser](screenshots/visual_folder_browser.png) | ![MiniMax Music 3 Creator](screenshots/minimax_music3_creator.png) | ![QnA Advanced](screenshots/qna_advanced.png) |

| Studio Production Line | ComfyGuard Health Check | Multi-Genre Picker | Batch Prompt Processor |
|:---:|:---:|:---:|:---:|
| ![Studio Production Line](screenshots/studio_production_line.png) | ![ComfyGuard](screenshots/comfyguard.png) | ![Genre Picker](screenshots/genre_picker.png) | ![Batch Processor](screenshots/batch_processor.png) |

---

## Who Is This For?

| If you... | You'll find... |
|-----------|----------------|
| **Design logos in-node** | A full Fabric.js + Three.js design studio with 2D/3D viewports, layer management, shape primitives, text layers, SVG import/export, GLTF/OBJ/STL 3D model loading, and keyboard nudging — all embedded directly in your ComfyUI graph |
| **Browse and caption image datasets** | A dual-mode Load/Save image node with an embedded visual browser — browse **all files** in a folder with a file-type filter (images, videos, audio, text, models, or any custom extension), thumbnail grid, dataset captioning workspace (single + batch), sidecar .txt management, duplicate scanner, and clickable breadcrumb navigation |
| **Generate music prompts with MiniMax Music 3** | A multi-genre prompt creator with 237 genres, genre blending (primary = structure, secondary = seasoning), auto-gen subjects, instrumental mode, content safety filtering, slop word replacement, and a direct API connector |
| **Want LLM-powered prompt engineering** | A QnA engine with dual-model chaining (thinker + instructor), forced JSON output, context summarization, conversation history, web search, and vision model support |
| **Build full music-video productions** | A complete Studio pipeline: Producer → Sound Engineer → Screenwriter → Creative Director → Director → Cinematographer → Editor → PostMaster, with scene routing, character tracking, and shot planning |
| **Need production safety** | ComfyGuard — a runtime interceptor that protects your environment from broken pip installs and CUDA downgrades |
| **Have legacy workflows (Film/Viseme/LTX)** | All previous nodes still load with a ⚰️ Legacy badge — they work but are no longer actively developed |

---

## Quick Start

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/PGFX/ComfyUI-PromptCrafter.git
pip install -r requirements.txt
```

Audio features (optional — won't break your torch):
```bash
pip install --no-deps torchaudio faster-whisper whisperx speechbrain
```

---

## Node Inventory

All nodes appear under the `☠️PGFX /` menu in ComfyUI. The pack currently ships **60+ active nodes** plus **50+ legacy nodes** that maintain backward compatibility.

### ✅ Active — Production Nodes

#### ☠️PGFX /Creator — AI Prompt Generation

| Node | Description |
|------|-------------|
| **✨ Image → Prompt** (`PromptCrafter_VisualCreator`) | Full-featured LLM prompt generator for image/video. Dual-model chain (thinker + instructor), reference image analysis, style profiles, scheduled prompts, and auto-save. |
| **🎤 Lyrics → Prompt** (`PromptCrafter_LyricsCreator`) | LLM-powered music video prompt generator. Creates timed prompt schedules from lyrics + audio, with WhisperX transcription, spectrogram preview, and VRGDG variable automation. |
| **✨ Easy Image → Prompt** (`PromptCrafter_VisualCreatorEasy`) | Simplified VisualCreator — quick prompt generation without deep-think or scheduling. |
| **🎤 Easy Lyrics → Prompt** (`PromptCrafter_LyricsCreatorEasy`) | Simplified LyricsCreator — generates prompt schedules from lyrics without the full configuration surface. |
| **✨ Prompt Creator (V3)** (`PromptCrafter_V3Creator`) | ComfyUI V3 API wrapper of the creator node. |

#### ☠️PGFX /Music — MiniMax Music 3

| Node | Description |
|------|-------------|
| **🎵 MiniMax Music 3 Creator** (`PromptCrafter_MiniMaxMusic3Creator`) | Creates structured captions (Global Metadata + Vocal Details + Arrangement) and full lyrics for the MiniMax-Music3 model. Multi-genre blending, auto-gen subjects, instrumental mode, content safety, slop word replacement, 237 genres, 🎲 random controls. |
| **🎵 MiniMax Music 3 API Connector** (`PromptCrafter_MiniMaxMusic3APIConnector`) | Sends structured caption + lyrics to a MiniMax Music 3 server (`/v1/audio/speech`) and returns generated WAV audio. Supports tiled decode, configurable max duration, and output path. |
| **🎵 MiniMax Music 3 Creator (V3)** | V3 API variant of the Creator. |
| **🎵 MiniMax Music 3 API Connector (V3)** | V3 API variant of the API Connector. |

#### ☠️PGFX /Logo — Logo Designer

| Node | Description |
|------|-------------|
| **PGFX Logo Designer Studio** (`PGFX_LogoDesignerStudio`) | Full embedded design studio (Fabric.js + Three.js). 2D vector canvas with shape primitives, text layers, pen tool, full drawing toolbar, layer panel with visibility/lock/rename, undo/redo history, and Figma/Illustrator-style arrow key + Shift nudging. **3D viewport** with Three.js orbit controls, GLTF/OBJ/STL model import, SVG extrusion, GLTF export, and 3D transform gizmos. Multiple environment slots, SVG export, server-side image persistence, and zero workflow file bloat. |
| **PGFX Logo Designer Agent** (`PGFX_LogoDesignerAgent`) | LLM agent that analyzes brand requirements and generates detailed logo design briefs with color palettes, typography recommendations, and style direction. |
| **🎭 PGFX MCP Agent** (`PGFX_LogoDesignerMCPAgent`) | General-purpose ComfyUI MCP Agent — chat-driven, fire-and-forget workflow builder. Picks the matching template/model for the requested media and wires in your prompt + reference media. Runs on a background thread (single `status` output, `OUTPUT_NODE`) so it never blocks ComfyUI's serial queue; finished files land in the ComfyUI output directory. |
| **📐 PGFX Image Vectorizer** (`PGFX_ImageVectorizer`) | Converts raster logo images to SVG vector format using edge detection and path tracing. |
| **PromptCrafter ✨ Image Trace to SVG** (`CP_ImageToSVG`) | Traces raster images to SVG vector paths using potrace-based algorithms. |
| **PromptCrafter 💾 Save SVG** (`CP_SaveSVG`) | Saves SVG output to disk with customizable path and filename. |
| Plus V3 API variants of all the above. |

#### ☠️PGFX /Visual Browser — File & Image Folder Browser

| Node | Description |
|------|-------------|
| **📂 Visual Folder Loader** (`PGFX_VisualFolderLoader`) | Dual-mode Load/Save image node with an embedded visual browser. **Load Mode**: Browse a folder's files (images and more), filter by type, select a file, output image + mask + caption. **Save Mode**: Connect images to save directly to the browsed folder with timestamped filenames — same folder you browse is the folder you save to. |

**Visual Folder Loader Features:**

| Feature | Description |
|---------|-------------|
| **File Grid** | Visual grid of **all files** in the current folder — images render as lazy-loaded thumbnails (with green TXT badges when they have sidecar captions); videos, audio, text, JSON, models, etc. render as type icons with filenames |
| **File-Type Filter** | Dropdown to narrow the grid by type: **All Files** (default), Images, Videos, Audio, Text/Data, or Models — plus a **Custom extension** input (e.g. `.psd`) for any other type |
| **Clickable Breadcrumb Navigation** | Path bar with clickable segments to jump to any parent folder; folder dropdown lists all subfolders |
| **Search & Pagination** | Real-time search (250ms debounce) across all file types, paginated results with prev/next controls |
| **Caption on Save** | Auto-caption every saved image with a vision model and write `.txt` sidecar — zero extra steps |
| **Execution-Time Auto-Captioning** | During workflow queue execution, auto-caption images on-the-fly (`Disabled` / `Always (Overwrite)` / `If Missing`) |
| **✨ Generate (Single)** | Generate a caption for the selected image using any vision model (Ollama, GGUF, HuggingFace — auto-listed) |
| **📝 Caption All (Batch)** | Caption every image in the folder or only missing ones, with estimated time display, live progress counter, and a 🛑 Stop button — non-image files are always skipped |
| **Ground Truth Prompting** | Enter text like "Super Hero" — it's injected as ground truth context: *"Describe this image in detail. Use the following as ground truth context: Super Hero"* |
| **Caption Output Formats** | Sidecar .txt (default), Single JSON (`captions.json`), or Single TXT Append (`captions.txt`) |
| **Duplicate Scanner 🔍** | Scans for exact (MD5) and near-duplicate (perceptual dhash) images with selectable duplicates and bulk deletion |
| **File Details Bar** | Shows file type, size, modification date, and resolution (for images) for the selected file |
| **Keyboard Shortcuts** | Escape closes overlays, Delete/Backspace triggers bulk deletion in the scanner |

#### ☠️PGFX /Text — LLM Q&A and Text Processing

| Node | Description |
|------|-------------|
| **💬 Advanced Q&A** (`PromptCrafter_QnA`) | Full-featured LLM Q&A with dual-model chain (thinker + instructor), web search, image context, conversation history, chunked context summarization, auto-save, and JSON repair. |
| **💬 Simple Q&A** (`PromptCrafter_QnA_Simple`) | Minimal LLM Q&A node — instruction-only, no formatting overhead, supports vision models and JSON mode. |
| **🖼️ Image Captioner** (`PromptCrafter_Captioner`) | Generates text descriptions of images using any vision model, with configurable captioner profiles. |
| **🎬 MiniMax H3 Image → Video Prompt** (`PromptCrafter_H3ImageToVideoPrompt`) | Generates video prompts from images specifically for MiniMax H3 video generation. |
| **🧩 Prompt Splitter (Pipe)** (`PromptCrafter_PromptChunker`) | Splits large text prompts into chunks for batched LLM calls, preserving context overlap between chunks. |

#### ☠️PGFX /Prompt — Batch Processing

| Node | Description |
|------|-------------|
| **🧰 Batch Prompt Processor** (`BatchPromptProcessor`) | Processes a batch of prompts through a configurable pipeline for bulk prompt generation from templates. |
| **⏱️ Keyframe Prompt Scheduler** (`KeyframePromptScheduler`) | Creates frame-based prompt schedules from keyframe definitions — assigns prompts to specific frame ranges for video generation. |
| Plus V3 API variants of both. |

#### ☠️PGFX /Utils — Utilities & Tools

| Node | Description |
|------|-------------|
| **🔀 Universal Switch Box** (`PGFX_UniversalSwitchBox`) | Routes any data type through a selectable switch — like a multiplexer for ComfyUI connections. Wire once, switch outputs dynamically. |
| **🖼️ Multi-Image Preview** (`PGFX_MultiImagePreview`) | Displays up to 6 images side-by-side in the ComfyUI viewport with labels and sizing control. |
| **💾 Save Text File** (`PromptCrafter_SaveTextFile`) | Saves text output to a file with customizable path, filename template, and format. |
| **📝 Text Formatter** (`PromptCrafter_Formatter`) | Formats text output with options for markdown, JSON, plain text, and custom templates. |
| **🧹 Cache Utility** (`PromptCrafter_CacheUtility`) | Manages ComfyUI node execution caches — clear, inspect, or invalidate cached outputs. |
| **🗂️ File Organizer** (`PromptCrafter_FileOrganizer`) | Organizes and renames output files with template-based naming conventions. |
| **🦙 Ollama Router Node** (`PromptCrafter_OllamaRouterNode`) | Routes LLM requests to local Ollama instances — manages model selection, health checks, and failover. |
| Plus V3 API variants of all above. |

#### ☠️PGFX /LLM — LLM Output Management

| Node | Description |
|------|-------------|
| **☠️ LLM Output Saver** (`PGFX_LLM_OutputSaver`) | Saves LLM output per batch to files, auto-combines into a single JSON on final batch with PGFX JSON repair utilities. Drop-in VRGDG replacement. |
| Plus V3 API variant. |

#### ☠️PGFX /Security — ComfyGuard

| Node | Description |
|------|-------------|
| **🩺 ComfyGuard Health Check** (`PGFX_ComfyGuard_Shield`) | Displays hardware health and security status — CUDA status, VRAM, optimizer flags, constraint shield status. Output node that renders a full status dashboard in the viewport. |
| Plus V3 API variant. |

---

### ⚰️ Legacy Nodes — Still Load, Still Work

Legacy nodes are marked with a ⚰️ prefix in the node menu. They remain fully registered in `NODE_CLASS_MAPPINGS` so **all existing workflows continue to work without changes**. No new features or V3 migration will be made to these nodes.

#### ⚰️PGFX /Studio — Full Film Crew Pipeline (18 nodes)

A complete music-video production pipeline that simulates a real film crew:

| Node | Role |
|------|------|
| **🎬 Studio Config (Producer)** | Initializes project config — resolution, FPS, output path |
| **🎙️ Studio Sound Engineer** | Analyzes audio with Silero VAD + SpeechBrain emotion recognition, segments into scenes |
| **📝 Studio Screenwriter** | WhisperX transcription, word-to-scene alignment, screenplay generation with AI correction |
| **🎨 Studio Creative Director** | Dual-model LLM chain generates visual briefs, character descriptions, per-scene shot plans |
| **🎬 Studio Director** | Produces per-scene image prompts (positive + negative) from the visual brief |
| **📷 Studio Scene Router (Cinematographer)** | Routes scene data to downstream rendering nodes |
| **🎞️ Studio Scene Exporter (Editor)** | Exports rendered scenes for final assembly |
| **🎬 Studio PostMaster** | Final compositing — assembles scenes into the final video with audio sync |
| **📋 Studio Project Context** | Manages project-level context (tone, genre, character bible) for LLM calls |
| **💾/📂 Studio Store/Load Text** | Store and retrieve arbitrary text between nodes |
| **📐 Studio Shot Planner** | Constructs LLM prompts for shot planning |
| **📋 Studio Shot Plan → Shot List** | Parses LLM shot plan output into structured shot lists |
| **👗 Studio Stylist** | Generates consistent character outfit/appearance descriptions |
| **💃 Studio Animator** | Drives lip-sync/viseme generation from screenplay text |
| **🔍 Studio Script Supervisor** | Validates screenplay continuity across scenes |
| **⚙️ Studio Sampler (Universal)** | Executes diffusion model inference for scene rendering |
| **🔗 Studio ControlNet (Viseme Bridge)** | Bridges viseme guides to ControlNet conditioning |
| **🔄 Studio Auto-Queue** | Auto-queues multiple render passes for large scene sets |

Plus 8 adapter nodes (AUDIO, PROJECT_CONFIG, TIMING_MAP, SHOT_LIST, CHARACTER_TRACK format converters).

#### ⚰️PGFX /Film — Film Project Management (10 nodes)

| Node | Description |
|------|-------------|
| **Film Project Controller** | Top-level project manager — initializes structure, tracks scenes/shots |
| **Film Character Registry** | Stores appearance, voice, and role data for multi-scene consistency |
| **Film Shot Architect** | Designs camera angles, composition, and timing per shot |
| **Film Assembler** | Assembles shots → scenes → full film with transitions |
| **Film Render Project** | Renders entire project to disk with encoding and audio mixing |
| Plus audio loaders, segmenters, config extractors, and auto-indexing nodes. |

#### ⚰️PGFX /Video — Viseme & Lip-Sync (5 nodes)

| Node | Description |
|------|-------------|
| **💋 Cinema Viseme Rig** | Phoneme-based viseme animation frames (rig guides, canny guides, lip masks) using G2P mapping with Gaussian smoothing |
| **🎭 Script-Guided Visemes** | Viseme animations aligned to scripted dialogue |
| **🌐 Universal Viseme Guides** | Mouth-shape conditioning images from any text/timing input |
| **⏱️ Word Timing JSON Builder** | Word-level timing JSON from audio metadata |
| **🔗 Viseme Conditioning Bridge** | Prepares viseme guides as ControlNet/IP-Adapter conditioning |

#### ⚰️PGFX /LTXV — LTX Video Pipeline (6 nodes)

| Node | Description |
|------|-------------|
| **LTX-2 Queue Manager** | Batched video generation queues with auto-queue support |
| **LTX-2 Video Stitcher** | Stitches rendered clips into continuous video with audio sync |
| **LTXV Latent Upsampler** | Upsamples video latents for higher resolution generation |
| **LTXV Corrective Mask** | Fixes artifacts at frame boundaries and stitching seams |
| **LTXV In Context Sampler** | Reference-frame-based temporal consistency across video segments |
| **Latent Probe** | Diagnostic node — inspects tensor shapes, statistics, device placement |

#### ⚰️PGFX /Audio — Audio Processing (4 nodes)

| Node | Description |
|------|-------------|
| **🎤 Audio Splitter v2** | Splits audio into 16-scene chunks with WhisperX transcription, AI correction, Silero VAD silence detection, and alignment caching |
| **🎤 Audio Splitter** | Earlier version with similar capabilities |
| **🎵 ACE-Step 1.5 Advanced** | Text-to-audio latent conditioning for ACE-Step 1.5 |
| **🎵 ACE-Step Latent Timeline Offset** | Timeline offset/shift for precise audio-video synchronization |

#### ⚰️PGFX /VRGDG — VRGDG Interop (4 nodes)

Semantic Bridge, StoryGroup Bridge, Schedule Prompt Map, and Prompt Package Validator for compatibility with VRGDG (Video Recipe) workflows.

#### ⚰️Other Legacy

- **📝 SRT Creator** — WhisperX subtitles with word-level alignment and AI correction
- **🎨 Subtitle Styler** — Burns SRT subtitles onto video frames with customizable font/color/position
- **🎞️ Frame Selector** — Extracts specific frames from video batches
- **🎬 LTX-2 Manifest Builder** — Builds LTX-2 pipeline manifests from project config
- **🎬 Director Agent** — Legacy LLM director for prompt generation

---

## Key Features Deep Dive

### Logo Designer Studio — Full Design Environment

A production-grade vector design studio embedded directly in your ComfyUI graph:

**2D Canvas (Fabric.js):**
- Drawing toolbar with shape primitives (rectangle, circle, triangle, polygon, star, line)
- Text layers with full formatting (font, size, color, alignment, bold/italic/underline)
- Pen tool for custom paths
- Color picker with fill and stroke controls
- Transparency/opacity per object
- Layer panel — rename, reorder, toggle visibility, lock layers
- Undo/Redo history (full canvas state snapshots)
- Figma/Illustrator-style arrow key nudging (+ Shift for 10x)
- Grid and snap-to-grid
- Zoom and pan

**3D Viewport (Three.js):**
- Orbit controls for free camera rotation
- GLTF/OBJ/STL 3D model import
- SVG-to-3D extrusion
- Transform gizmos (move, rotate, scale)
- GLTF export
- 2D ↔ 3D sync — changes in either viewport reflect in the other

**Persistence:**
- Canvas state saved/loaded with ComfyUI workflows (no file bloat)
- Server-side image persistence
- SVG export for production use
- Multiple environment slots with per-slot intensity controls

### Visual Folder Browser — Dual-Mode Image Node

A single node that replaces separate Load + Save + Caption nodes:

**Load Mode** (no input connected):
- Browse folder thumbnails in an embedded grid
- Click an image to output it as an image tensor + mask + caption
- Navigate via clickable breadcrumb path segments
- Search filenames in real-time
- Paginate through large folders

**Save Mode** (connect `images` input):
- Saves incoming images directly to the browsed folder
- Timestamped filenames (`20260610_143022_000_0000.png`)
- **Caption on Save**: Auto-caption + `.txt` sidecar written alongside — zero extra steps
- Same folder you browse = folder you save to (keeps workflows in sync)

**Dataset Captioning Workspace:**
- **Ground Truth Prompting**: Enter "Super Hero" → caption instruction becomes *"Describe this image in detail. Ground truth: Super Hero"*
- **✨ Generate**: Single-image captioning with any vision model (Ollama, GGUF, HuggingFace)
- **📝 Caption All**: Batch caption all images with estimated time, live progress, and 🛑 Stop button
- **Caption Output Formats**: Sidecar .txt, Single JSON, or Single TXT Append
- **Execution-Time Auto-Captioning**: `Disabled` / `Always (Overwrite)` / `If Missing` — runs during workflow queue

**Duplicate Scanner 🔍:**
- Exact duplicate detection (MD5 hash)
- Near-duplicate detection (perceptual dhash)
- Group-by-group preview with selectable duplicates
- Bulk deletion

### MiniMax Music 3 — End-to-End Music Generation

A complete prompt engineering pipeline for the MiniMax-Music3 model:

**Multi-Genre Mixing (HOT-Step-PGFX-Edition pattern):**
- 237 genres across 17 categories (Pop, Rock, Electronic, Hip-Hop, R&B, Jazz, Classical, Country, Folk, Metal, Latin, Asian, African, Patois, Reggae, Blues, Soul)
- First genre = **PRIMARY** (dictates song structure: verse count, section order, BPM range)
- Additional genres = **seasonings** (vocabulary/tone only, 85%→35% sliding-scale weights)
- Genre picker dropdown + direct text input field
- Clear all / randomize buttons

**Lyric Generation:**
- Auto-Gen Subject from 18 relational role templates with repeat avoidance
- Full section support: [Intro] [Verse] [Pre-Chorus] [Chorus] [Post-Chorus] [Bridge] [Instrumental] [Solo] [Outro]
- Instrumental mode toggle (omits Vocal Details section)
- Official 3-section caption: Global Metadata → Vocal Details → Arrangement (250–450 words)

**Smart Controls:**
- 🎲 Random genre (replaces primary, keeps seasonings)
- 🎲 Random BPM (genre-appropriate ranges)
- 🎲 Random Key / Scale
- Slop word replacement — genre-aware substitution of generic AI words (ethereal → genre-specific alternatives)
- Content safety mode — filters inappropriate content

**API Connector:**
- Sends caption + lyrics to MiniMax Music 3 server
- Tiled decode support for large outputs
- Configurable max duration (up to 300 seconds)
- Returns WAV audio directly

### LLM Backend — Intelligent Prompt Generation

- **Stateless Node V3** — all primary execution methods are stateless classmethods for stability across ComfyUI core updates
- **Dual-Model Chain** — thinker model reasons, then instructor model formats into structured output
- **Native Reasoning Support** — auto-detects DeepSeek-R1 and triggers Chain of Thought processing
- **Parallel Agent Execution** — run multiple LLM agents simultaneously via `PGFX_MAX_LLM_THREADS`
- **Forced JSON Mode** — guarantees structured output even on small 3B-7B local models
- **Automatic Context Summarization** — proactive "Summary Lobe" condenses long conversations to keep context windows performant
- **JSON Repair** — robust extraction, parsing, and repair of malformed LLM JSON output
- **Multi-Backend Support** — Ollama, llama.cpp, HuggingFace, LMStudio, OpenAI-compatible APIs, GGUF

### ComfyGuard — Runtime Protection

A security layer that activates at startup:
- Intercepts `pip install` calls to prevent CUDA-downgrading package installs
- Creates NumPy rescue snapshots for recovery
- Injects constraint shields and CUDA index URLs automatically
- Detects conflicting node packs and dependency issues
- Hardware health dashboard (CUDA status, VRAM, optimizer flags)
- Emergency repair endpoint accessible via the ComfyUI server API

---

## Example Workflows

The `workflows/` directory includes 12 ready-to-use example workflows:

| Workflow | Description |
|----------|-------------|
| **Studio Elite Production Line** | Full Producer → PostMaster pipeline |
| **Studio MusicVideo Master** | Complete music video production |
| **Studio LTX MusicVideo** | LTX Video-based music video |
| **Logo Designer Elite** | Logo design with LLM agent + vectorizer |
| **Lyrics To Viseme Lipsync** | Lyrics → transcription → viseme → lip-sync |
| **Cinema Viseme Rig** | Phoneme-based viseme animation |
| **LTX InContext Pipeline** | Temporal consistency with reference frames |
| **VisualThink To Video** | Image → LLM concept → video generation |
| **Dream Journal Visualizer** | Text → image visualization pipeline |
| **Synesthesia Machine** | Cross-modal audio-visual generation |
| **Stock Enhancement** | Image enhancement and upscaling pipeline |
| **Universal Switch Box Demo** | Dynamic routing with the switch box |

---

## Security & Privacy

- **No telemetry** — zero outbound connections by the node pack itself. All LLM calls default to localhost (`127.0.0.1`).
- **No hardcoded secrets** — API endpoints configured via environment variables with safe localhost defaults.
- **DOMPurify bundled** — all JS UI rendering sanitized against XSS.
- **No system access** — all subprocess calls use hardcoded FFmpeg commands with no `shell=True`. File operations use internally-constructed paths.
- **`.env` in `.gitignore`** — credential files excluded from version control by default.

---

## Node Stability Tiers

| Tier | Meaning |
|------|---------|
| ✅ **Stable** | Production-ready, regularly used in primary workflows |
| 🔧 **Beta** | Feature-complete; minor edge cases possible |
| ⚠️ **Experimental** | Active development; architecture complete but not fully field-tested |
| ⚰️ **Legacy** | Still loads and works in existing workflows, but **no longer actively developed**. Displayed with a ⚰️ Legacy badge in the Add Node menu. Will not be migrated to V3 API. |

### What's Actively Maintained

Creator nodes (Visual, Lyrics, MiniMax Music 3), Logo Designer Studio, Visual Folder Browser, QnA variants, Batch Processor, Keyframe Scheduler, all utility nodes, and ComfyGuard.

---

## Requirements

- ComfyUI (Frontend V2 recommended)
- Python 3.10+
- PyTorch (CUDA recommended)
- FFmpeg (for video assembly features)
- Local LLM backend (Ollama, llama.cpp, or HuggingFace)

---

## Further Reading

- **[HELP.md](HELP.md)** — detailed per-node documentation with input/output specs
- **`workflows/`** — 12 example workflow JSON files demonstrating pipeline patterns
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — internal architecture and design intent
- GitHub Issues — for bug reports and feature requests

---

*Maintained by PGFX Industrial Engineering.*
