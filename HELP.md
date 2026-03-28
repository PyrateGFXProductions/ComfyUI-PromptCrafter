# PGFX PromptCrafter — Help

This file provides the text shown in ComfyUI’s `?` tooltip for PGFX nodes.
For full documentation and examples, see `README.md`.

---

## `PromptCrafter_QnA`
A flexible Q&A assistant node that can use text, images, optional web search, and conversation history.

Key behaviors:
- Accepts a primary instruction plus optional subject/context.
- Supports text‑only and vision‑enabled models.
- Can read external context files and chunk/summarize large inputs.
- Can optionally perform web search for time‑sensitive topics.

Outputs:
- `response`
- `history_out`
- `thinking_process`

---

## `PromptCrafter_Captioner`
A VLM‑powered image captioner for datasets and libraries.

Key behaviors:
- Single‑image or batch folder processing.
- Optional profile presets and custom caption prompts.
- Optional trigger word injection for training workflows.
- Optional file renaming and metadata writing.

---

## `PromptCrafter_FileOrganizer`
Organizes images and media into folders using rule‑based schemes.

Key behaviors:
- Rules can target filename, caption text, metadata, resolution, or VLM content.
- Supports dry‑run planning, copy/move, and recursive traversal.
- Can auto‑generate a scheme with AI when enabled.

---

## `PromptCrafter_CacheUtility`
Clears internal caches so nodes re‑evaluate inputs (useful after file edits).

---

## `PromptCrafter_VideoFrameSelector`
Selects exact frames or frame ranges from a generated video clip represented as an `IMAGE` batch.

Key behaviors:
- Supports single-frame, frame-range, last-N, and CSV index selection.
- Accepts negative indices so `-1` means the final frame, `-2` the frame before that, etc.
- Outputs both the full selected batch and one chosen frame for downstream looping workflows.
- Generates a labeled contact-sheet preview so you can inspect candidate frames visually before saving.

Outputs:
- `selected_frames`
- `selected_frame`
- `contact_sheet`
- `selected_count`
- `selected_frame_index`
- `selection_info`

Tip:
- Connect `selected_frame` into your next image-to-video start frame input.
- Connect `selected_frames` or `selected_frame` into a normal `SaveImage` node to save full-resolution stills.

---

## `PromptCrafter_LTX2LocalPipelineBuilder`
Builds local-only LTX-2 render artifacts from PromptCrafter schedule JSON.

Key behaviors:
- Converts keyframe schedule JSON into scene-wise local CLI commands.
- Outputs a manifest JSON plus a runnable shell script.
- Writes files to disk optionally for immediate local execution.
- Does not require platform API usage.

---

## Customizing Profiles
Profiles are stored in the repo root and control dropdown presets:

- `style_profiles.json`
- `captioner_profiles.json`
- `organization_profiles.json`

Director profiles are currently defined in code (`core/profiles/pgfx_director_profiles.py`).
After editing profiles, restart ComfyUI to refresh dropdown options.
