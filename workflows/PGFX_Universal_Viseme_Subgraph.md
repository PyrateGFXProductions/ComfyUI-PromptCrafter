# PGFX Universal Viseme Subgraph

This is a reusable subgraph pattern for plugging [PGFX_UniversalVisemeGuides](/home/pyrategfx/ComfyUI/custom_nodes/ComfyUI-PromptCrafter/nodes/pgfx_viseme_nodes.py) into image-to-video workflows without hard-coding it to one model family.

## What The Node Produces

`PGFX_UniversalVisemeGuides` outputs:

- `control_images`: main mouth-guide frames
- `depth_guides`: grayscale landmark guidance frames
- `canny_guides`: outline-only landmark guidance frames
- `phoneme_debug_text`
- `is_silent`
- `instrumental_cue`

It does **not** directly modify a video model by itself. You still need a consumer branch that uses one of those image outputs.

## Recommended Drop-In Subgraph

Use this as the standard reusable block:

```text
audio alignment / word timing
        |
        v
PGFX_UniversalVisemeGuides
  - audio_meta OR word_timing_json
  - scene_start_seconds
  - scene_duration_seconds
  - fps
  - max_frames
  - image_width / image_height
        |
        +--> control_images ----> preview / blend / image-conditioning branch
        |
        +--> depth_guides ------> control-image consumer
        |
        +--> canny_guides ------> control-image consumer
        |
        +--> phoneme_debug_text -> text preview / logging
```

## Pattern 1: Preview And Timing Validation

Use this when you want to verify mouth timing before wiring it into generation.

```text
word timing json or audio_meta
        |
        v
PGFX_UniversalVisemeGuides
        |
        +--> control_images -> SaveImage / PreviewImage
        +--> phoneme_debug_text -> text/debug output
```

This is the safest first integration step because it proves:

- scene timing is correct
- frame counts match the target clip
- viseme cadence looks reasonable before any model-specific conditioning

## Pattern 2: Image-To-Video Workflows With Guide/Image Inputs

If your video model already accepts guide images, reference images, init frames, or per-frame conditioning images, wire the viseme output there.

```text
reference face image/video -----------+
                                      |
PGFX_UniversalVisemeGuides            |
  control_images ---------------------+--> image merge/composite/mask branch --> model guide input
```

Use this pattern when the target workflow has:

- an image-conditioning input
- a guide-frame input
- an init-video or reference-video branch
- a compositing stage before encode/sampling

Recommended rule:

- use `control_images` when the consumer expects full RGB guide frames
- use `depth_guides` or `canny_guides` when the consumer expects structural guidance

## Pattern 3: Control-Image Workflows

If the target workflow uses a control-image system, connect `depth_guides` and `canny_guides` into that path.

```text
PGFX_UniversalVisemeGuides
  depth_guides ----+
                   +--> control-image adapter / controlnet branch --> sampler conditioning
  canny_guides ----+
```

Important:

- [PGFX_Studio_ControlNet](/home/pyrategfx/ComfyUI/custom_nodes/ComfyUI-PromptCrafter/nodes/pgfx_studio_controlnet.py) is currently a **PGFX Studio-side conditioning bridge**, not a universal ComfyUI ControlNet injector.
- For plain ComfyUI pipelines, you still need the target workflow's own control consumer or adapter node.

## Minimal Inputs To Reuse In Any Workflow

For the most portable setup, drive the node with explicit scene timing instead of relying on one repo's `audio_meta` schema:

- `word_timing_json`
- `scene_start_seconds`
- `scene_duration_seconds`
- `fps`
- `max_frames`
- `image_width`
- `image_height`

Example `word_timing_json`:

```json
[
  {"word": "hello", "start": 0.00, "end": 0.42},
  {"word": "again", "start": 0.42, "end": 0.88}
]
```

That makes the node usable even when a workflow has no native `audio_meta` output.

## Practical LTX / Img2Vid Placement

For typical image-to-video graphs, the best insertion point is usually **before the model-specific encode/sampling stage**, not after decode.

```text
face/reference image ---> preprocess ------------------+
                                                       |
PGFX_UniversalVisemeGuides -> guide/composite branch --+--> model image/guide encoder --> sampler
```

Do not try to apply viseme guides after the final decode if your goal is better lip motion. At that point you are compositing on top of the result, not conditioning the generation.

## Safe Integration Order

1. Start with `control_images -> PreviewImage` and confirm timing.
2. Connect `depth_guides` or `canny_guides` into the target workflow's guide/control branch.
3. Only then add `control_images` blending if the model benefits from stronger mouth-shape hints.

## Current Limitation

`PGFX_UniversalVisemeGuides` is now workflow-agnostic as a **guide generator**, but universal lip-sync still requires one workflow-specific consumer:

- control-image adapter
- image-conditioning input
- guide-video input
- or a model-specific compositor/preprocessor

That separation is intentional so the node stays reusable across LTX, Hunyuan, CogVideoX, Flux-video, and custom image-to-video graphs.
