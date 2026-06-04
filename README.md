# ☠️ PGFX PromptCrafter — ComfyUI Node Pack

**Agentic creative tooling for ComfyUI.** A modular node pack that brings LLM-driven prompt engineering, video production pipelines, and a full vector design studio into your graph — optimized for local reasoning models (DeepSeek-R1, Llama 3.3, etc.) and modern ComfyUI Frontend V2.

---

## Who is this for?

| If you... | You'll find... |
|-----------|----------------|
| Build production ComfyUI workflows | A film-production metaphor with pipeline orchestration nodes (Producer, Director, Cinematographer, Editor, PostMaster) |
| Want LLM-powered prompt generation | A QnA engine with Think/Instruct dual-model chaining, forced JSON output, and automatic context summarization |
| Design assets in-comsole | A persistent Fabric.js vector design studio with full toolbar, layer management, and keyboard shortcuts — embedded directly in your graph |
| Work with LTX video models | LTX-2/LTXV specialized patching, sampling, and corrective masking |
| Need audio/video lip-sync | Viseme-based mouth animation guides with phonetic G2P conversion |
| Care about production safety | ComfyGuard — a runtime interceptor that protects your environment from broken pip installs and CUDA downgrades |

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

| Category | Nodes | Stability |
|----------|-------|-----------|
| **/Text** | QnA, Think/Instruct (Lyrics, Visual, QnA), Captioner, Formatter, Prompt Chunker, Ollama Router, SRT Creator | ✅ Stable / 🔧 Beta |
| **/Audio** | Audio Splitter (v2 + Legacy), Audio Load, Audio Preview, Audio Output | 🔧 Beta / ⚠️ Experimental |
| **/Video** | Frame Selector, Viseme Suite (Script-Guided, Universal Guide, Cinema Rig), Audio Subtitles | ⚠️ Experimental |
| **/Film** | Project Controller, Character Registry, Shot Architect, Assembler, Audio Loader/Segmenter, Render Project, Shot Config Extractor | ⚠️ Experimental |
| **/Studio** | Full Film Crew pipeline (Producer → PostMaster), Director, Screenwriter, Cinematographer, Editor, Stylist, Animator, Project Context, Store/Load Text | 🔧 Beta |
| **/Studio/Adapters** | Data contract validators/normalizers (PROJECT_CONFIG, TIMING_MAP, SHOT_LIST, CHARACTER_TRACK, AutoQueue) | 🔧 Beta |
| **/Utils** | Universal Switch Box, Multi-Image Preview, Save Text File, File Organizer, Cache Utility, Visual Browser | ✅ Stable |
| **/Creator** | Visual Creator, Lyrics Creator (full + easy variants) | ✅ Stable |
| **/Design** | Logo Designer Studio, Logo Designer Agent, Image Vectorizer (SVG) | ✅ Stable (Studio) / 🔧 Beta (Agent) |
| **/LLM** | LLM Router node | ✅ Stable |
| **/Security** | ComfyGuard startup interceptor | ✅ Stable |

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

### ComfyGuard
Runtime protection that activates at startup:
- Intercepts `pip install` calls to prevent CUDA-downgrading package installs
- Creates NumPy rescue snapshots for recovery
- Injects constraint shields and CUDA index URLs automatically
- Emergency repair endpoint accessible via the ComfyUI server API

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
