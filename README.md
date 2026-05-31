# ☠️ PGFX PromptCrafter — ComfyUI Node Pack

> **Professional agentic creative pipeline tooling for ComfyUI.**  
> Bridges the gap between manual design precision, LLM-driven prompt engineering, and GPU-accelerated generative rendering.

---

## 📋 Table of Contents

- [Overview](#overview)
- [Node Status Legend](#node-status-legend)
- [🎨 Logo Designer Suite](#-logo-designer-suite)
- [✨ Creator Nodes](#-creator-nodes)
- [🎬 Studio Nodes](#-studio-nodes)
- [🎵 Audio Nodes](#-audio-nodes)
- [🎞️ Film Assembly Nodes](#%EF%B8%8F-film-assembly-nodes)
- [🔧 LTX-2 / LTXV Nodes](#-ltx-2--ltxv-nodes)
- [🛠️ Utility Nodes](#%EF%B8%8F-utility-nodes)
- [💬 LLM / QnA Nodes](#-llm--qna-nodes)
- [🔌 Director Nodes](#-director-nodes)
- [🖼️ Image Vectorizer](#%EF%B8%8F-image-vectorizer)
- [🛡️ ComfyGuard](#%EF%B8%8F-comfyguard)
- [⚙️ Installation](#%EF%B8%8F-installation)
- [🔗 Dependencies Reference](#-dependencies-reference)

---

## Overview

**ComfyUI-PromptCrafter** is a multi-purpose node pack organized around a **"Film Crew"** metaphor: every node fills a professional role in a cinematic production pipeline — from Producers and Directors down to Sound Engineers and Cinematographers. At its heart is a fully interactive **Logo Designer Studio** powered by a persistent Fabric.js canvas embedded directly in the ComfyUI graph.

The pack is split into several tiers:

| Tier | Stability | Notes |
|------|-----------|-------|
| **Creator Nodes** | ✅ Active & Reliable | Frequently used, well-tested |
| **Logo Designer** | 🔧 Active Development | Under active debug; core features functional |
| **Studio Nodes** | ⚠️ WIP / Partially Tested | Architecture complete; not fully field-tested |
| **Film Nodes** | ⚠️ WIP / Partially Tested | Pipeline-level; limited real-world validation |
| **LTX-2 Nodes** | ⚠️ WIP / Partially Tested | Experimental LTX-2 / LTXV integration |
| **Audio Nodes** | ⚠️ WIP / Mixed | Some work well; torchaudio-dependent nodes untested by default |
| **Utility Nodes** | ⚠️ Mixed | Some created as possible use-cases; not all tested |
| **LLM/QnA Nodes** | ✅ Functional | Used, though lightly validated |
| **Director Nodes** | ⚠️ Lightly Tested | Created; not frequently relied upon |

---

## Node Status Legend

| Badge | Meaning |
|-------|---------|
| ✅ **Active** | Regularly used; functionality confirmed |
| 🔧 **Active Dev** | Under current development/debugging |
| ⚠️ **WIP** | Work-in-progress; architecture done but limited real-world testing |
| 🧪 **Experimental** | Created as a proof-of-concept; may not work reliably |
| 🗑️ **Deprecated** | Legacy/superseded; kept for workflow compatibility |

---

## 🎨 Logo Designer Suite

> **Status: 🔧 Active Development**  
> The centrepiece of the pack. A fully integrated vector design studio embedded in the ComfyUI graph.

### PGFX Logo Designer Studio
**Class:** `PGFX_LogoDesignerStudio`  
**Category:** `☠️PGFX🏴‍☠️ /Design`

A persistent **Fabric.js** canvas workspace with a full professional toolbar, wired directly into the ComfyUI prompt pipeline.

**Features:**
- 🖼️ **Persistent Canvas** — Design state is serialized as JSON and uploaded as a server-side image on save. Large canvas data never bloats the workflow file, eliminating the `Failed to save workflow draft` error.
- ✏️ **Pro Drawing Toolbar** — Free-hand Pencil, Spray, and Circle brushes with live opacity and size controls.
- 📐 **Vector Primitive Library** — Instant generation of Rectangles, Circles, Triangles, Stars, and Hexagons.
- 🅰️ **Text Layers** — Multiple independent text objects with font, size, colour, and weight controls. Text is synced safely to avoid duplication on re-open.
- 🖌️ **Background Modes** — `simple` (canvas colour), `preset` (named scene), `custom` (free text), or `none` (disabled). Chosen mode is always forwarded to the prompt.
- 🌫️ **Three Environment Slots** — `environment_1`, `environment_2`, `environment_3` let you stack independent atmospheric effects (particles, fog, lightning, smoke, etc.).
- 🎚️ **Per-Environment Intensity** — Each environment slot has its own `_intensity` slider (0.0–2.0). `0.0` disables the effect; `0.5` = subtle/sparse; `1.0` = normal; `1.5` = heavy; `2.0` = dramatic/intense.
- 🎨 **Style Sliders** — `geometry_adherence` (0–1) and `creative_flair` (0–1) with high-contrast prompt variance at extremes.
- 📝 **Prompt Style** — Toggle between `conversational` (natural prose) and `object_list` (token-based) generation modes.
- 🔌 **Float Outputs** — `geometry_adherence` and `creative_flair` are exposed as FLOAT output pins, wireable into samplers, ControlNet, or any downstream node.

**Inputs (key):**

| Input | Type | Description |
|-------|------|-------------|
| `base64_image_data` | STRING | Canvas image data (auto-managed; uploaded to server on save) |
| `canvas_json_data` | STRING | Fabric.js JSON state (auto-managed) |
| `text_input` | STRING | Fallback text if no canvas text layer is present |
| `output_intent` | COMBO | `vector` (flat 2-D) or `raster` (shading / depth) |
| `background_mode` | COMBO | `simple`, `preset`, `custom`, or `none` |
| `background_preset` | COMBO | Named scene environment (active when `background_mode = preset`) |
| `background_custom_prompt` | STRING | Free-text background description (active when `background_mode = custom`) |
| `scene_interaction` | STRING | Describes how the design interacts with its environment |
| `material` | COMBO | Surface finish applied to all elements (gold, marble, neon, etc.) |
| `decoration` | COMBO | Surface ornamentation on top of the material |
| `action` | COMBO | Dynamic physical process applied to the design |
| `environment_1` | COMBO | First atmospheric effect slot |
| `environment_1_intensity` | FLOAT (0–2) | Intensity for `environment_1`. `0` = disabled; `1` = normal; `2` = extreme |
| `environment_2` | COMBO | Second atmospheric effect slot |
| `environment_2_intensity` | FLOAT (0–2) | Intensity for `environment_2` |
| `environment_3` | COMBO | Third atmospheric effect slot |
| `environment_3_intensity` | FLOAT (0–2) | Intensity for `environment_3` |
| `style_mode` | COMBO | `flat_vector`, `creative`, `realistic`, or `3d_render` |
| `intensity` | FLOAT (0.2–2) | Overall prompt detail level (0.2 = subtle; 1.0 = normal; 2.0 = extreme) |
| `geometry_adherence` | FLOAT (0–1) | How strictly the model preserves the source geometry |
| `creative_flair` | FLOAT (0–1) | Degree of creative embellishment allowed |
| `prompt_style` | COMBO | `conversational` or `object_list` |
| `extra_instruction` | STRING | Free-form text appended verbatim to the final prompt |
| `seed` | INT | Generation seed |

**Outputs:**

| Output | Type | Description |
|--------|------|-------------|
| `image` | IMAGE | Canvas composite rendered to a tensor |
| `mask` | MASK | Alpha mask extracted from the canvas |
| `flux_prompt` | STRING | The fully assembled generation prompt |
| `geometry_adherence` | FLOAT | Passthrough slider value |
| `creative_flair` | FLOAT | Passthrough slider value |

---

### PGFX Logo Designer Agent
**Class:** `PGFX_LogoDesignerAgent`  
**Category:** `☠️PGFX🏴‍☠️ /Logo Designer`  
**Status: 🔧 Active Dev**

The AI consultant that translates user intent and reference imagery into Studio node settings. It reads the `design_library.json` to stay grounded in discovered styles and materials.

> **Note:** All manual widget values take priority over Agent suggestions. The Agent is for users who want settings auto-populated — manual overrides always win.

**Key Features:**
- 🧬 **Evolutionary Design Library** — Autonomously discovers and categorises new materials, motifs, and styles from prompts and reference images, ranking them by usage frequency.
- 📦 **Prompt-Aware Handoff** — Translates creative instructions into Studio-compatible JSON settings.

---

### 📐 PGFX Image Vectorizer
**Class:** `PGFX_ImageVectorizer`  
**Category:** `☠️PGFX🏴‍☠️ /Logo Designer`  
**Status: ✅ Active**

Converts raster images to SVG vector format with built-in protection against crashes on high-resolution inputs.

**Features:**
- 🔌 **Universal API Adaptors** — Compatible with multiple vectorization backends.
- 🛡️ **8K Posterization Crash Protection** — Guards against memory overflow on very large images.
- 📋 **Preview Output** — Returns both SVG string and an IMAGE preview tensor.

---

## ✨ Creator Nodes

> **Status: ✅ Active & Reliable**  
> The most frequently used nodes in the pack. Production-grade agentic prompt generators.

### ✨ Visual Creator
**Class:** `PromptCrafter_VisualCreator`  
**Category:** `☠️PGFX🏴‍☠️ /Creator`

Full-featured image and video prompt generator. Supports single and dual-model chains, scheduled keyframe outputs, and deep-think refinements.

**Key capabilities:**
- 📸 **Multi-Modal** — Accepts up to 5 reference images with individual weighting.
- 🧠 **Dual-Model Chain** — Separate `thinking_model` (reasoning) and `instruct_model` (JSON output) for higher quality results.
- 🎞️ **Schedule Mode** — Outputs a `{frame: prompt}` JSON schedule for video pipelines.
- 📤 **Auto-Save** — Optional automatic saving of outputs to file with configurable naming templates.
- 🎯 **Target Model Format** — Tailored output for SD1.5, SD2.1, FLUX, LTX-2, Stable Diffusion 3, and more.
- 🔧 **Response Modes** — `Predictable` (deterministic, temperature=0) or `Creative` (free exploration).

**Outputs:** `prompt`, `schedule`, `image_context`, `negative_prompt`, `model_out`, `seed_out`, + up to 5 passthrough `reference_image_N` pins.

---

### ✨ Easy Visual Creator
**Class:** `PromptCrafter_VisualCreatorEasy`  
**Status: ✅ Active**

Simplified Visual Creator with pre-optimised defaults. Fewer knobs — just point it at a model and write your instruction.

---

### 🎤 Lyrics Creator
**Class:** `PromptCrafter_LyricsCreator`  
**Category:** `☠️PGFX🏴‍☠️ /Creator`  
**Status: ✅ Active**

Music video director. Takes lyrics + optional audio and generates a scene-by-scene prompt schedule, SRT subtitles, and audio metadata.

**Key capabilities:**
- 🎙️ **WhisperX Integration** — Transcribes and aligns audio with lyrics (optional; requires `faster-whisper`).
- 📽️ **Scene Splitting** — `Structural Tag`, `Fixed Duration`, or `Frame Length` modes.
- 🧠 **Dual-Model Chain** — Same thinker/instructor architecture as Visual Creator.
- 📋 **Auto-Talent Direction** — Automatic character, environment, lighting, shots, and expression generation.
- 📊 **Spectrogram Preview** — Visual audio preview output.

**Outputs:** `prompt`, `schedule`, `image_context`, `negative_prompt`, `clean_lyrics_txt`, `lyrics_srt`, `model_out`, `seed_out`, `audio_meta`, `spectrogram_preview`, `signal`, + 9 auto-populated creative fields + 5 passthrough images + `schedule_json`.

---

### 🎤 Easy Lyrics Creator
**Class:** `PromptCrafter_LyricsCreatorEasy`  
**Status: ✅ Active**

Simplified Lyrics Creator with sane defaults for fast video prompt generation.

---

## 🎬 Studio Nodes

> **Status: ⚠️ WIP / Partially Tested**  
> Full pipeline orchestration suite. Architecture is designed and implemented; not fully field-tested in production.

### Core Film Crew

| Display Name | Class | Role |
|---|---|---|
| 🎬 Studio Producer (Config) | `PGFX_Studio_Producer` | Sets global `PROJECT_CONFIG` — project name, dimensions, FPS |
| 🔊 Studio Sound Engineer (Audio) | `PGFX_Studio_SoundEngineer` | VAD, emotion detection, Mel-Band RoFormer stem separation |
| 🧠 Studio Creative Director (Concept) | `PGFX_Studio_CreativeDirector` | High-level concept and theme generation |
| ✍️ Studio Screenwriter (Lyrics) | `PGFX_Studio_Screenwriter` | Lyric alignment and narrative scripting |
| 🎥 Studio Director (Prompts) | `PGFX_Studio_Director` | Shot-by-shot prompt generation from SHOT_LIST |
| 📹 Studio Cinematographer (Shot) | `PGFX_Studio_Cinematographer` | Per-scene camera & style decisions |
| 🎞️ Studio Editor (Scene Saver) | `PGFX_Studio_Editor` | Persists rendered scene clips to disk |
| 🏗️ Studio PostMaster (Final Render) | `PGFX_Studio_PostMaster` | Final assembly and output composition |

### Pipeline Context & Storage

| Display Name | Class | Description |
|---|---|---|
| 🧭 Studio Project Context | `PGFX_Studio_ProjectContext` | Provides shared project metadata to downstream nodes |
| 💾 Studio Store Text | `PGFX_Studio_StoreText` | Persists a string to disk between pipeline runs |
| 📂 Studio Load Text | `PGFX_Studio_LoadText` | Loads previously stored strings from disk |

### Shot Planning

| Display Name | Class | Description |
|---|---|---|
| 🧠 Studio Shot Planner Prompt Builder | `PGFX_Studio_ShotPlannerPromptBuilder` | Builds the LLM prompt for automated shot planning |
| 🧱 Studio Shot Plan To Shot List | `PGFX_Studio_ShotPlanToShotList` | Converts LLM shot plan JSON → `SHOT_LIST` dict |
| 🎨 Studio Stylist (Looks) | `PGFX_Studio_Stylist` | Assigns style metadata to each shot |
| 👄 Studio Animator (Visemes) | `PGFX_Studio_Animator` | Manages viseme sequence data for lip-sync animation |
| 📋 Studio Script Supervisor (Review) | `PGFX_Studio_ScriptSupervisor` | Validates pipeline data integrity and generates review reports |

### Adapters (Data Normalisation Layer)

These nodes normalise and validate typed data contracts (`PROJECT_CONFIG`, `TIMING_MAP`, `SHOT_LIST`, `CHARACTER_TRACK`) between pipeline stages.

| Display Name | Class | Description |
|---|---|---|
| 🔌 Studio Adapter (AUDIO→audio) | `PGFX_Studio_AudioPinAdapter` | Type-bridges AUDIO dict to standard audio pin |
| 🔌 Studio Adapter (PROJECT_CONFIG core) | `PGFX_Studio_ProjectConfigValidator` | Validates PROJECT_CONFIG and extracts core keys |
| 📐 Studio Adapter (PROJECT_CONFIG → Size) | `PGFX_Studio_ProjectConfigToSize` | Extracts `width`, `height`, `fps` and aligns to block size |
| 🔌 Studio Adapter (TIMING_MAP core) | `PGFX_Studio_TimingMapAdapter` | Validates/normalises TIMING_MAP; derives `durations_frames` |
| 🔌 Studio Adapter (Scene Count) | `PGFX_Studio_SceneCountAdapter` | Normalises scene count and computes remaining scenes |
| 🔁 Studio Auto-Queue (Scenes) | `PGFX_Studio_AutoQueue` | Dispatches additional ComfyUI queue jobs for each scene |
| 🔌 Studio Adapter (SHOT_LIST core) | `PGFX_Studio_ShotListAdapter` | Validates SHOT_LIST against TIMING_MAP |
| 🔌 Studio Adapter (CHARACTER_TRACK core) | `PGFX_Studio_CharacterTrackAdapter` | Validates CHARACTER_TRACK and aligns to TIMING_MAP |

### Universal Sampler & ControlNet

| Display Name | Class | Status |
|---|---|---|
| 🎤 Studio Sampler (Universal) | `PGFX_Studio_Sampler` | ⚠️ WIP — Unified KSampler-compatible node |
| 👄 Studio ControlNet (Viseme Bridge) | `PGFX_Studio_ControlNet` | ⚠️ WIP — ControlNet adapter for viseme-driven animation |

---

## 🎵 Audio Nodes

> **Status: ⚠️ WIP / Mixed**  
> Nodes that require `torchaudio`, `whisperx`, `faster-whisper`, or `speechbrain` are **skipped at startup** unless those packages are installed. See [Installation](#%EF%B8%8F-installation) for safe install instructions.

### 🎤 Audio Splitter v2
**Class:** `PromptCrafter_AudioSplitter_v2`  
**Category:** `☠️PGFX🏴‍☠️ /Audio`  
**Status: ⚠️ WIP** (requires `whisperx`, `faster-whisper`, `torchaudio`)

Intelligently segments long audio tracks into 16-scene batches for iterative video generation workflows.

**Key Features:**
- 🔇 **Silence Detection** — Silero VAD identifies non-vocal sections and replaces them with cinematic B-roll instructions.
- ✍️ **Script Correction** — An LLM corrects WhisperX's raw transcript against a user-provided ground-truth script.
- 📁 **Smart Output Versioning** — Detects project hash changes and auto-increments output folder versions.
- 🔁 **Auto-Queue** — Dispatches subsequent render jobs automatically when the audio requires more than 1 set.
- 💾 **Alignment Caching** — Saves word-alignment JSON to disk to avoid redundant transcription on re-runs.

**Outputs:** 16x AUDIO chunks + metadata dict, index, timestamps, instruction string, TIMING_MAP fragment.

---

### Other Audio Nodes

| Display Name | Class | File | Status |
|---|---|---|---|
| 🎤 Audio Splitter | `PromptCrafter_AudioSplitter` | `pgfx_utility_nodes.py` | ⚠️ WIP |
| Audio SRT Creator | *(via pgfx_audio_srt.py)* | `pgfx_audio_srt.py` | ⚠️ WIP |
| Audio Subtitles | *(via pgfx_audio_subtitles.py)* | `pgfx_audio_subtitles.py` | ⚠️ WIP |
| Audio Splitter (Legacy) | *(via pgfx_audio_splitter_legacy.py)* | `pgfx_audio_splitter_legacy.py` | 🗑️ Legacy |
| Enhanced Audio | *(via pgfx_audio_nodes_enhanced.py)* | `pgfx_audio_nodes_enhanced.py` | ⚠️ WIP |

---

## 🎞️ Film Assembly Nodes

> **Status: ⚠️ WIP / Partially Tested**  
> A full production orchestration layer for building long-form AI film projects shot-by-shot.

| Display Name | Class | Description |
|---|---|---|
| Film Project Controller | `PGFX_FilmProjectController` | Top-level project state manager for multi-shot renders |
| Film Character Registry | `PGFX_FilmCharacterRegistry` | Stores and retrieves character profiles and style overrides |
| Film Shot Architect | `PGFX_FilmShotArchitect` | Builds SHOT_LIST and TIMING_MAP from creative inputs |
| Film Save Shot Video | `PGFX_FilmSaveShotVideo` | Saves an individual rendered shot clip to disk |
| Film Audio Loader | `PGFX_FilmAudioLoader` | Loads audio from disk into AUDIO dict format |
| Film Assembler | `PGFX_FilmAssembler` | FFmpeg-based final assembly; concatenates shots + audio |
| Film Render Project | `PGFX_FilmRenderProject` | Persists render progress across sequential queue runs |
| Film Shot Config Extractor | `PGFX_FilmShotConfigExtractor` | Extracts per-shot prompt, seed, dimensions, audio from SHOT_LIST/TIMING_MAP |
| Film Audio Segmenter | `PGFX_FilmAudioSegmenter` | Extracts a single shot's audio from TIMING_MAP |
| Film Auto Shot Index | `PGFX_FilmAutoShotIndex` | Reads active shot index from PROJECT_CONFIG render plan |

> **Note:** `PGFX_FilmAssembler` and `PGFX_FilmShotConfigExtractor` both use FFmpeg and require it to be on `PATH`.

---

## 🔧 LTX-2 / LTXV Nodes

> **Status: ⚠️ WIP / Experimental**  
> Patching and orchestration utilities for the LTX-2 (LTXAV) video model family.

| Display Name | Class | Description |
|---|---|---|
| 🎬 LTX-2 Queue Manager | `PGFX_Studio_LTX2Queue` | Auto-queues sequential LTX-2 generation sets based on TIMING_MAP clip count |
| 🎞️ LTX-2 Video Stitcher | `PGFX_Studio_Stitcher` | Gathers rendered clips + audio and calls FFmpeg to produce the final MP4 |
| 🎥 PGFX LTXV Latent Upsampler | `PGFX_LTXVLatentUpsampler` | Enhanced latent upsampler that preserves and spatially rescales noise masks for LTXV pipelines |
| 🛡️ PGFX LTXV Corrective Mask | `PGFX_LTXVCorrectiveMask` | Ensures a valid `noise_mask` shape for LTXV samplers; handles AV NestedTensor branches |
| 🔍 PGFX Latent Probe | `PGFX_LatentProbe` | Debug node that prints full latent shape/dtype/device info to stderr |

**Module-level patches applied on load (in `pgfx_ltx2_nodes.py`):**
- **CPU-safe Attention Patch** — Prevents attention dimension crashes on non-CUDA inference.
- **GGUF Linear Shape Patch** — Transposes mismatched weight matrices from GGUF exports.
- **LTXAV Connector Auto-Merge** — Automatically injects missing `audio_embeddings_connector` / `video_embeddings_connector` tensors from a separately-stored safetensors file when the UNet loads without them.

---

## 🛠️ Utility Nodes

> **Status: ⚠️ Mixed**  
> A collection of workflow helpers. Some are frequently used; others were created as proof-of-concept and never fully validated.

### Image & Video

| Display Name | Class | Status | Description |
|---|---|---|---|
| 🖼️ Multi-Image Preview | `PGFX_MultiImagePreview` | ✅ Active | Side-by-side image comparison with up to 16 slots and passthrough outputs |
| 🎞️ Frame Selector | `PromptCrafter_VideoFrameSelector` | ⚠️ WIP | Extracts a specific frame from a video tensor by index |
| 🔀 Image Switcher | `PromptCrafter_ImageSwitcher` | ✅ Active | Selects one of N connected images by index or random mode |

### Text & Prompt Utilities

| Display Name | Class | Status | Description |
|---|---|---|---|
| 📝 Text Formatter | `PromptCrafter_Formatter` | ✅ Active | String manipulation: trim, replace, upper/lower, regex, etc. |
| 🧩 Prompt Chunker | `PromptCrafter_PromptChunker` | ✅ Active | Splits a pipe-delimited prompt string into up to 50 individual scene outputs |
| 💾 Save Text File | `PromptCrafter_SaveTextFile` | ✅ Active | Saves any string output to a `.txt` or `.json` file on disk |

### LLM & Model Utilities

| Display Name | Class | Status | Description |
|---|---|---|---|
| 🦙 Ollama Router Node | `PromptCrafter_OllamaRouterNode` | ✅ Active | OpenRouter-compatible drop-in adapter that routes to local Ollama models. Supports chat history, image inputs, PDF text extraction, and auto-segment repair for truncated responses |
| 🖼️ Image Captioner | `PromptCrafter_Captioner` | ✅ Active | Generates descriptive captions for images using a connected vision-language model |

### Audio & File Management

| Display Name | Class | Status | Description |
|---|---|---|---|
| 🎤 Audio Splitter | `PromptCrafter_AudioSplitter` | ⚠️ WIP | Legacy audio segmenter (prefer v2) |
| 🧹 Cache Utility | `PromptCrafter_CacheUtility` | ✅ Active | Clears model caches, temp files, or triggers garbage collection |
| 🗂️ File Organizer | `PromptCrafter_FileOrganizer` | 🧪 Experimental | Moves/copies/renames output files based on configurable rules |

### Pipeline Bridges (Undocumented / Experimental)

| Display Name | Class | Status |
|---|---|---|
| 🧠 Lyrics Think | `PromptCrafter_LyricsThink` | 🧪 Experimental |
| ✍️ Lyrics Instruct | `PromptCrafter_LyricsInstruct` | 🧪 Experimental |
| 🧠 Visual Think | `PromptCrafter_VisualThink` | 🧪 Experimental |
| ✍️ Visual Instruct | `PromptCrafter_VisualInstruct` | 🧪 Experimental |
| 🧠 QnA Think | `PromptCrafter_QnAThink` | 🧪 Experimental |
| ✍️ QnA Instruct | `PromptCrafter_QnAInstruct` | 🧪 Experimental |
| 🎬 LTX-2 Local Pipeline Builder | `PromptCrafter_LTX2LocalPipelineBuilder` | 🧪 Experimental |

---

## 💬 LLM / QnA Nodes

> **Status: ✅ Functional**

| Display Name | Class | Description |
|---|---|---|
| 💬 QnA | `PromptCrafter_QnA` | General-purpose question-and-answer node (alias for Simple) |
| 💬 QnA (Simple) | `PromptCrafter_QnA_Simple` | Lightweight single-turn LLM query node |
| 💬 QnA (Advanced) | `PromptCrafter_QnA_Advanced` | Full-featured QnA with temperature, seed, retry, deep-think, and image inputs |

---

## 🔌 Director Nodes

> **Status: ⚠️ Lightly Tested**

| Display Name | Class | Description |
|---|---|---|
| *(Director Nodes)* | via `pgfx_director_nodes.py` | High-level shot planning with deterministic and agentic modes. Created and registered; not frequently relied upon in current workflows. |

---

## 🖼️ Image Vectorizer

See [PGFX Image Vectorizer](#-pgfx-image-vectorizer) in the Logo Designer Suite section above.

---

## 🛡️ ComfyGuard

**Class:** `PGFX_ComfyGuard`  
**Status: ✅ Active**

Security and stability interceptor that activates at startup to protect the ComfyUI environment from potentially harmful node operations.

---

## ⚙️ Installation

### Basic Setup

```bash
pip install -r requirements.txt
```

This installs only the **safe core dependencies** that will not break your CUDA/PyTorch environment.

### ⚠️ Critical: Torch / CUDA Safety

Many popular nodes (and some pip packages) silently reinstall a CPU-only `torch`, breaking CUDA. This pack checks your CUDA status at startup and warns you immediately.

> **If CUDA goes missing after installing another node pack**, the most common fix is:
> ```bash
> pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
> ```
> Replace `cu121` with your actual CUDA version.

### Audio Features (Optional)

Audio-dependent nodes (`Audio Splitter v2`, `Lyrics Creator` with alignment, `SRT Creator`) require these packages. Install them **without letting pip pull in a new torch**:

```bash
pip install --no-deps torchaudio faster-whisper whisperx speechbrain insanely-fast-whisper whisper-ctranslate2
```

> Always ensure your `torchaudio` version matches your `torch` version.

### LLM Backends

The Creator and QnA nodes support multiple model backends:

| Backend | Format | Notes |
|---------|--------|-------|
| Ollama | `ollama/model-name` | Recommended for local inference |
| GGUF (llama.cpp) | `gguf/path/to/model.gguf` | Quantised local models |
| HuggingFace | `hf/org/model-name` | Pulls from Hub on first use |
| OpenAI-compatible | API key in config | Remote endpoint |

---

## 🔗 Dependencies Reference

| Package | Required For | Install Method |
|---------|-------------|----------------|
| `torch`, `torchvision` | All nodes | Pre-installed via ComfyUI |
| `pillow`, `numpy` | All image nodes | `requirements.txt` |
| `langdetect` | Language detection | `requirements.txt` |
| `pypdf` | PDF text extraction (Ollama Router) | `requirements.txt` |
| `librosa` | Audio analysis fallback | `requirements.txt` |
| `matplotlib` | Spectrogram preview | `requirements.txt` |
| `torchaudio` | Audio Splitter v2, Lyrics Creator | `pip install --no-deps torchaudio` |
| `faster-whisper` | Audio transcription | `pip install --no-deps faster-whisper` |
| `whisperx` | Forced word alignment | `pip install --no-deps whisperx` |
| `speechbrain` | Advanced audio models | `pip install --no-deps speechbrain` |
| `ffmpeg` | Film Assembler, LTX-2 Stitcher | System package (`winget install ffmpeg`) |

---

## 📁 Repository Structure

```
ComfyUI-PromptCrafter/
├── nodes/
│   ├── pgfx_logo_designer.py          # Logo Designer Studio, Agent, Vectorizer
│   ├── pgfx_creator_nodes.py          # Visual Creator, Lyrics Creator (+ Easy variants)
│   ├── pgfx_studio_nodes.py           # Full Studio pipeline (Film Crew nodes + Adapters)
│   ├── pgfx_studio_sampler.py         # Universal Sampler node
│   ├── pgfx_studio_controlnet.py      # ControlNet Viseme Bridge node
│   ├── pgfx_audio_nodes.py            # Audio Splitter v2 (main)
│   ├── pgfx_audio_nodes_enhanced.py   # Enhanced audio processing
│   ├── pgfx_audio_srt.py              # SRT/subtitle generation
│   ├── pgfx_audio_subtitles.py        # Subtitle rendering
│   ├── pgfx_audio_splitter_legacy.py  # Legacy splitter (deprecated)
│   ├── pgfx_film_nodes.py             # Film Assembly pipeline
│   ├── pgfx_ltx2_nodes.py             # LTX-2/LTXV specialised nodes + patches
│   ├── pgfx_utility_nodes.py          # All utility nodes (QnA, Captioner, Formatter, etc.)
│   ├── pgfx_director_nodes.py         # Director nodes
│   ├── pgfx_llm_nodes.py              # Low-level LLM utility nodes
│   ├── pgfx_prompt_nodes.py           # Basic prompt passthrough nodes
│   ├── pgfx_viseme_nodes.py           # Viseme generation for lip-sync
│   ├── pgfx_vrgdg_bridge_nodes.py     # VRGDG workflow bridge nodes
│   ├── pgfx_comfyguard_node.py        # ComfyGuard security node
│   ├── pgfx_font_manager.py           # Font management utilities
│   └── image_to_svg.py                # Image→SVG conversion helper
├── js/
│   └── pgfx_logo_designer.js          # Fabric.js canvas UI (Logo Designer Studio)
├── core/                              # Shared config, API clients, JSON utilities
├── utils/                             # Shared Python utilities
├── style_profiles.json                # Style override profiles
├── captioner_profiles.json            # Image captioner prompt profiles
├── organization_profiles.json         # Organisation / output format profiles
├── requirements.txt                   # Safe core dependencies
└── README.md                          # This file
```

---

*Documentation maintained by PGFX Industrial Engineering. Last updated: 2026-05-31.*
