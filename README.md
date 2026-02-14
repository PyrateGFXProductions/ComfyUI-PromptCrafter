# ☠️ PGFX PromptCrafter for ComfyUI

ComfyUI-PromptCrafter is the **PGFX node suite** for ComfyUI. It started as a prompt‑crafting toolkit and has grown into a full creative pipeline with **Studio**, **Creator**, **Audio**, **Video**, **Text**, and **Utility** nodes, plus **ComfyGuard** for dependency safety.

Compatibility note: many internal node IDs still use the `PromptCrafter_` prefix for workflow stability, while the UI labels and menu categories use the **PGFX** brand.

---

## ✨ Highlights

- **PGFX Studio Pipeline**: A multi‑stage, role‑based workflow for music‑video and narrative content (Producer → Sound Engineer → Screenwriter → Director → Cinematographer → Editor → PostMaster).
- **Creator Nodes**: High‑quality prompt generation for images, videos, and lyrics with style profiles and dual‑model workflows.
- **Audio & Timing**: Audio splitters, transcription, and SRT generation to drive consistent scene timing.
- **Video Tools**: Subtitle burning for frame sequences and video pipelines.
- **Think/Instruct Chains**: Deterministic paired nodes for structured reasoning and strict output control.
- **Utilities**: QnA, Captioner, File Organizer, Formatter, Save Text, Cache Utility, Prompt Chunker, Image Switcher.
- **ComfyGuard**: A bundled dependency conflict detector for safer installs.

---

=======
## 🧪 Example Workflows

Functional, end-to-end workflow examples are included in `workflows/`. See `workflows/README.md` for details and dependencies.

- `PGFX_VisualCreator_SD15_Image.json`
- `PGFX_LyricsCreator_Schedule_Export.json`
- `PGFX_QnA_To_Text.json`
- `PGFX_Captioner_Single_Image.json`
- `PGFX_SRT_Subtitle_Burn.json`

---

## 🧭 Menu Categories

The nodes are organized under the PGFX menu in ComfyUI:

- `☠️PGFX🏴‍☠️ /Studio`
- `☠️PGFX🏴‍☠️ /Studio/IO`
- `☠️PGFX🏴‍☠️ /Studio/Director`
- `☠️PGFX🏴‍☠️ /Studio/Agents`
- `☠️PGFX🏴‍☠️ /Studio/02_Narrative`
- `☠️PGFX🏴‍☠️ /Studio/Adapters`
- `☠️PGFX🏴‍☠️ /Creator`
- `☠️PGFX🏴‍☠️ /Audio`
- `☠️PGFX🏴‍☠️ /Audio/Legacy`
- `☠️PGFX🏴‍☠️ /Video`
- `☠️PGFX🏴‍☠️ /Text/Think`
- `☠️PGFX🏴‍☠️ /Text/Instruct`
- `☠️PGFX🏴‍☠️ /Utils`
- `☠️PGFX🏴‍☠️ /Utils/Security`

---

## 🚀 Installation

1. Navigate to your `ComfyUI/custom_nodes/` directory.
2. Clone this repository:
   ```bash
   git clone https://github.com/PyrateGFXProductions/ComfyUI-PromptCrafter.git
   ```
3. Install requirements:
   ```bash
   pip install -r requirements.txt
   ```
4. Restart ComfyUI.

Optional: use ComfyGuard (see `ComfyGuard/README.md`) before installing third‑party node packs.

---

## 🧠 Model Backends

The suite supports multiple local and API‑style backends. You choose models from node dropdowns.

- Local GGUF via llama‑cpp‑python (e.g., models in `ComfyUI/models/LLM`)
- Local HuggingFace Transformers (if installed)
- Ollama
- OpenAI‑compatible endpoints

---

## 🧩 Node Sets (Short Reference)

**Creator**
- `✨ Visual Creator` — high‑quality visual prompt generation
- `🎤 Lyrics Creator` — lyrics‑to‑prompt/storyboard generation

**Audio**
- `🎤 Audio Splitter v2` — audio segmentation with timing metadata
- `📝 SRT Creator` — subtitle generation from audio
- `🎤 Audio Splitter v2 (Legacy)` — legacy pipeline compatibility

**Video**
- `📝 Subtitle Styler` — burn subtitles onto frame sequences

**Text / Think / Instruct**
- `🧠 ... Think` nodes — structured reasoning
- `✍️ ... Instruct` nodes — strict formatting and schema adherence

**Utilities**
- `💬 QnA` — conversational AI with optional images, files, and web search
- `🖼️ Image Captioner` — VLM‑driven captioning and tagging
- `🗂️ File Organizer` — rule‑based media sorting
- `📝 Text Formatter` — reusable templated text
- `💾 Save Text File` — structured file output
- `🧹 Cache Utility` — reset internal caches
- `🧩 Prompt Chunker`, `🔀 Image Switcher`, `🧰 Batch Prompt Processor`, `⏱️ Keyframe Prompt Scheduler`

**PGFX Studio**
- `🎬 Producer`, `🔊 Sound Engineer`, `✍️ Screenwriter`, `🧠 Creative Director`, `🎥 Director`, `📹 Cinematographer`, `🎞️ Editor`, `🏗️ PostMaster`
- `💾 Store Text`, `📂 Load Text`, `🧭 Project Context`
- `🔌 Studio Adapters` (PROJECT_CONFIG, TIMING_MAP, SHOT_LIST, etc.)

---

## 🛠️ Profiles & Customization

Profiles live in the repo root and are used by dropdowns and presets:

- `style_profiles.json`
- `captioner_profiles.json`
- `organization_profiles.json`

Director profiles are currently defined in code (`core/profiles/pgfx_director_profiles.py`).

After editing profiles, restart ComfyUI to refresh dropdowns.

---

## 🔧 Troubleshooting

- **Model not found**: Ensure your local model path is correct and supported by the selected backend.
- **GGUF or HF issues**: Verify your Python environment has the required libraries installed.
- **Stale outputs**: Run `🧹 Cache Utility` to clear internal caches.
- **Web search disabled**: Enable `enable_web_search` in `💬 QnA` when needed.
<<<<<<< HEAD

---

## ⚡ Performance Tuning

PromptCrafter now includes built-in GGUF auto-tuning, so users do not need a custom launcher script.

- `PGFX_GGUF_AUTO_TUNE=1` (default): enable automatic tuning based on available VRAM.
- `PGFX_GGUF_PROFILE=safe|balanced|speed`:
  - `safe`: lower VRAM pressure, highest stability.
  - `balanced` (default): moderate speed with safer memory behavior.
  - `speed`: keeps more on GPU and may keep vision models loaded longer.
- Manual overrides (advanced): `PGFX_VISION_GGUF_N_GPU_LAYERS`, `PGFX_VISION_GGUF_N_BATCH`, `PGFX_VISION_GGUF_N_UBATCH`, `PGFX_GGUF_UNLOAD_VISION_AFTER_QUERY`.

Notes:

- If logs show `n_gpu_layers=0`, your vision GGUF is CPU-dominant and will be much slower.
- If ComfyUI is killed while loading downstream generation models, keep `balanced`/`safe` and do not force `PGFX_GGUF_UNLOAD_VISION_AFTER_QUERY=0`.
=======

---

## ❤️ Support the Project

If these tools save you time or inspire your work, consider supporting:

- Buy me a coffee: https://ko-fi.com/pyrategfxproductions
- YouTube: https://www.youtube.com/@PyrateGFXProductions
- Civitai: https://civitai.com/user/PyrateGFXProductions

---

## 📜 License

MIT License. See `LICENSE`.

