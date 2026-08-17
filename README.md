# ☠️ PGFX PromptCrafter — ComfyUI Node Pack

**Agentic creative tooling for ComfyUI.** A modular node pack that brings LLM-driven prompt engineering, creative asset tools, and a full vector design studio into your graph — optimized for local reasoning models (DeepSeek-R1, Llama 3.3, etc.) and modern ComfyUI Frontend V2.

---

## Who is this for?

| If you... | You'll find... |
|-----------|----------------|
| Want LLM-powered prompt engineering | A QnA engine with dual-model chaining, forced JSON output, context summarization, and visual/lyrics creator nodes |
| Generate music with MiniMax Music 3 | A multi-genre prompt creator with 237 genres, auto-gen subjects, instrumental mode, and direct API connector |
| Design assets in-comsole | A persistent Fabric.js vector design studio with full toolbar, layer management, and keyboard shortcuts |
| Browse, caption, and organize image datasets | An embedded visual folder browser with dataset captioning workspace and duplicate scanner |
| Care about production safety | ComfyGuard — a runtime interceptor that protects your environment from broken pip installs and CUDA downgrades |
| Have legacy workflows (Studio/Film/Viseme/LTX) | All previous nodes still load with a ⚰️ Legacy badge — they work but are no longer actively developed |

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

Nodes are organized into 12 categories in the ComfyUI menu under `☠️PGFX /`:

| Category | Nodes | Status |
|----------|-------|--------|
| **/Creator** | Visual Creator, Lyrics Creator (full + easy variants), **MiniMax Music 3 Creator + API Connector** (V1 + V3) | ✅ Stable |
| **/Design** | Logo Designer Studio, Logo Designer Agent, Image Vectorizer (SVG) | ✅ Stable |
| **/Visual Browser** | Folder Image Loader (browse, caption, save, scan) | ✅ Active |
| **/Utils** | QnA (Advanced, Simple), Universal Switch Box, Multi-Image Preview, Save Text File, File Organizer, Cache Utility, Formatter, Prompt Chunker, Captioner, Ollama Router | ✅ Stable |
| **/Text** | Batch Prompt Processor, Keyframe Prompt Scheduler | ✅ Stable |
| **/LLM** | LLM Output Saver | ✅ Stable |
| **/Security** | ComfyGuard Health Check | ✅ Stable |
| **/Studio** | Full Film Crew pipeline (Producer → PostMaster, all adapters) | ⚰️ Legacy |
| **/Film** | Project Controller, Character Registry, Shot Architect, Assembler, etc. | ⚰️ Legacy |
| **/Viseme** | Cinema Rig, Script-Guided, Universal Guide, Word Timing, Conditioning Bridge | ⚰️ Legacy |
| **/LTX2 / LTXV** | Queue Manager, Stitcher, Latent Upsampler, Corrective Mask, In Context Sampler | ⚰️ Legacy |
| **/Audio** | Audio Splitter (v1 + v2), ACE-Step 1.5 Advanced, SRT Creator, Subtitle Styler | ⚰️ Legacy |
| **/VRGDG** | Semantic Bridge, StoryGroup Bridge, Schedule Prompt Map, Prompt Package Validator | ⚰️ Legacy |
| **/Director** | Director Agent | ⚰️ Legacy |

---

## Architecture Highlights

### LLM Backend
- **Stateless Node v3** — all primary execution methods are refactored as stateless classmethods, ensuring stability across ComfyUI core updates
- **Native reasoning support** — auto-detects DeepSeek-R1 and triggers Chain of Thought processing
- **Parallel agent execution** — run multiple LLM agents simultaneously via `PGFX_MAX_LLM_THREADS`
- **Forced JSON mode** — guarantees structured output even on small 3B-7B local models
- **Automatic context summarization** — a proactive "Summary Lobe" condenses long QnA conversations to keep context windows performant

### Logo Designer Studio
A production-grade vector design environment (Fabric.js) embedded in your graph:
- Full drawing toolbar, text layers, shape primitives
- Three environment slots with per-slot intensity controls
- Keyboard nudging (Figma/Illustrator-style arrow key + Shift)
- SVG export, server-side image persistence, no workflow file bloat

### Visual Folder Browser — PGFX_VisualFolderLoader

A **dual-mode Load/Save** image node with an embedded visual browser, dataset captioning workspace, duplicate scanner, and path explorer — all inside your graph.

#### Dual Load/Save Mode
- **Load Mode** (default, no input connected): Browse a folder's images in the built-in grid, select one, and it outputs the image + mask + caption. Supports pagination, search, and subfolder navigation via clickable path breadcrumbs.
- **Save Mode** (connect the `images` input): Any incoming image tensor is saved directly to the folder with timestamped filenames (`20260610_143022_000_0000.png`) and passed through as output. **No separate save node needed** — the same folder you browse is the folder you save to, keeping generation, upscale, and animation workflows in sync.
- **Caption on Save** (save mode + `caption_on_save = Enabled`): Every image saved through the `images` input is automatically captioned by the vision model and a `.txt` sidecar is written alongside it — zero extra steps. The first image's caption is also exposed via the `caption` output pin.
- The `folder` path supports absolute paths or paths relative to ComfyUI's output directory. Editable by double-clicking the path bar.

#### Dataset Captioning Workspace
- **Ground Truth Prompting:** When you enter text in `caption_prompt` (e.g. "Super Hero"), it's injected as **ground truth context** into a comprehensive caption instruction: *"Describe this image in detail. Use the following as ground truth context for what is depicted: Super Hero"* — no more generic "man in tights" descriptions.
- **✨ Generate (Single Image):** Generates a caption using any vision model (Ollama, GGUF, HuggingFace — auto-listed in the `caption_model` dropdown). Auto-saves to a `.txt` sidecar file next to the image. Combined status shows `✨ Generated ✅ Saved` or `✨ Generated ⚠️ Auto-save failed`.
- **📝 Caption All (Batch):** Captions every image in the folder (or only missing ones). Each caption is **automatically saved** as a `.txt` sidecar after generation (not just displayed). **Time warning** — shows estimated duration before starting (e.g. `~12 minutes` for 50 images) because captioning can take 5–30+ seconds per image. Live progress counter, per-image save status, and a **🛑 Stop Batch** button to cancel mid-way.
- **💾 Save:** Manually edit any caption in the textarea and save it as a `.txt` sidecar.
- **Caption Output Format** (`caption_output` widget): Choose between **Sidecar .txt** (one `.txt` file per image — default), **Single JSON** (all captions in a single `captions.json` file keyed by image name), or **Single TXT Append** (all captions appended to a single `captions.txt` file with `filename: caption` entries). This applies to Generate, Batch Caption, Caption on Save, and execution-time auto-captioning.
- **Real-Time TXT Badges:** Images with existing sidecar `.txt` files display a green `TXT` badge in the grid corner.
- **Execution-Time Auto-Captioning:** The node's `auto_captioning` input (`Disabled` / `Always (Overwrite)` / `If Missing`) runs the vision model during workflow queue execution, writing sidecar files automatically. The generated caption is also exposed via the third `caption` output pin.
- **Duplicate Scanner 🔍:** Scans the current folder for exact (MD5) and near-duplicate (perceptual dhash) images. Results are displayed in an overlay with selectable duplicates, group-by-group previews, and bulk deletion.

#### Path Bar & Navigation
- Clickable breadcrumb segments let you jump directly to any parent folder.
- Folder dropdown (📂 ▼) lists all subfolders with a parent "Up" option and shows the resolved absolute path.
- Double-click the path bar to type a path manually.
- Pagination (`◀ Prev` / `Next ▶`) with per-page info.
- Search input filters filenames in real-time (250ms debounce).
- Image details bar shows resolution, file size, date, and format for the selected image.
- Keyboard support: Escape closes overlays, Delete/Backspace triggers bulk deletion in the duplicate scanner.

### ComfyGuard
Runtime protection that activates at startup:
- Intercepts `pip install` calls to prevent CUDA-downgrading package installs
- Creates NumPy rescue snapshots for recovery
- Injects constraint shields and CUDA index URLs automatically
- Emergency repair endpoint accessible via the ComfyUI server API

### MiniMax Music 3 — Prompt Creator + API Connector

End-to-end music generation pipeline for the MiniMax-Music3 model, adapted from HOT-Step-PGFX-Edition patterns:

- **Multi-Genre Mixing** — Build an ordered genre blend list via dropdown picker or direct text input. First genre = PRIMARY (dictates song structure: verse count, section order). Each additional genre = seasoning (vocabulary/tone only, with 85%→35% sliding-scale weights). 237 genres across 17 categories including Patois variants.
- **Auto-Gen Subject** — Generate random song subjects from 18 relational role templates with deque-based repeat avoidance.
- **Instrumental Mode** — Toggle to omit the Vocal Details section entirely.
- **🎲 Random Controls** — Genre (replaces primary, keeps seasonings), BPM (genre-appropriate ranges), Key, Scale.
- **Slop Word Replacement** — Genre-aware replacement of generic AI words (ethereal, shimmer, cascade, neon).
- **Content Safety** — Optional `safe_mode` filters inappropriate content from captions and lyrics.
- **Official 3-Section Caption** — Global Metadata + Vocal Details + Arrangement (250–450 words).
- **Full Lyric Support** — All 9 section tags: [Intro] [Verse] [Pre-Chorus] [Chorus] [Post-Chorus] [Bridge] [Instrumental] [Solo] [Outro].
- **V1 + V3 API** — Both legacy V1 and modern V3 ComfyUI API nodes available.
- **Direct API Connector** — Sends caption + lyrics to MiniMax Music 3 server (`/v1/audio/speech`), returns WAV with tiled decode support.

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
| ⚰️ **Legacy** | Still loads and works in existing workflows, but **no longer actively developed**. Displayed with a ⚰️ Legacy badge in the node menu. Will not be migrated to ComfyUI V3 API. Consider replacing with alternatives where possible. |

### Legacy Node Policy

Legacy nodes remain registered in `NODE_CLASS_MAPPINGS` so **all existing workflows continue to work without changes**. They are marked in `NODE_DISPLAY_NAME_MAPPINGS` with a ⚰️ Legacy prefix in the Add Node menu. No new features, V3 migration, or bug fixes will be made to legacy nodes.

**What stays:** Creator nodes (including MiniMax Music 3), Logo Designer Studio, Visual Browser, QnA variants, core utilities, ComfyGuard, and Text nodes are actively maintained.

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
- **`workflows/`** — example workflow JSON files demonstrating pipeline patterns
- GitHub Issues — for bug reports and feature requests

---

*Maintained by PGFX Industrial Engineering.*
