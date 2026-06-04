# PGFX PromptCrafter — Help

This file provides the technical text shown in ComfyUI’s `?` tooltip for PGFX nodes.
For full feature showcases and installation guides, see `README.md`.

---

## `PGFX_VisualFolderLoader` (Visual Folder Browser)
A high-performance image explorer designed for massive output collections.

**Key Technical Behaviors:**
- **Recursive Deep-Scan:** Uses advanced directory walking to find every subfolder within your output path, no matter how deep.
- **Thumbnail Optimization:** Appends `&preview=true` to all internal requests, forcing the server to send small, compressed previews. This prevents browser lag when viewing hundreds of high-res images.
- **Strict Pagination:** Limits rendering to 12 items per page to maintain high frame rates in the ComfyUI canvas.
- **Technical Metadata Panel:** Real-time extraction of file size, resolution, and format upon selection.

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
