# PGFX Agent Profile (Locked)

Locked on 2026-02-11 for the PGFX Studio music video generation project.
This is the authoritative contract for ComfyUI node creation and workflow engineering in this repository.

## ComfyUI Execution Model Summary

- ComfyUI is a typed, dependency-driven graph (DAG), not a top-to-bottom script.
- A node executes only when all required typed inputs are available.
- Node contracts are strict: `INPUT_TYPES`, `RETURN_TYPES`, `RETURN_NAMES`, and `FUNCTION` must match runtime behavior.
- Shared workflow state must move through explicit `DICT` pins, not implicit process globals.

## Canonical Pin Types (Only These)

Use only:

- `MODEL`
- `CLIP`
- `VAE`
- `IMAGE`
- `LATENT`
- `CONDITIONING`
- `AUDIO`
- `MASK`
- `STRING`
- `INT`
- `FLOAT`
- `BOOLEAN`
- `DICT`

Do not invent new pin types.

## Output and Tuple Discipline

- `RETURN_TYPES` order is the output contract.
- If `RETURN_TYPES = ("IMAGE", "MASK")`, return exactly `image, mask` in that order.
- Do not wrap typed outputs in untyped containers.

## PROJECT_STATE Contract

- Shared state pin: `project_state: ("DICT",)`.
- PGFX nodes mutate only their namespace in `project_state`.
- State-passing nodes return exactly `RETURN_TYPES = ("DICT",)` and `return project_state,`.
- No implicit global state and no hidden path state; required paths must be explicit in `project_state` (or explicit node inputs).

## No Core Duplication

PGFX nodes orchestrate planning/state transformation and must not reimplement Comfy core behaviors.
Use existing nodes for generation and control (for example KSampler, CLIPTextEncode, ControlNetApply, VAEDecode, VHS, AnimateDiff, IPAdapter, pose/depth/segmentation community nodes).

## Node Naming, Registration, and Category

- Use unique PGFX node class names and display names.
- Register nodes in `NODE_CLASS_MAPPINGS` (and `NODE_DISPLAY_NAME_MAPPINGS` when needed).
- Custom nodes must reside under `ComfyUI/custom_nodes/` and follow ComfyUI loading conventions.

## Planning and Rendering Separation

- Planning nodes produce metadata/state only and do not render image/video outputs.
- Rendering nodes consume planning outputs and call existing render/control nodes.
- Preferred planning namespaces:
  - `project_state["concept_prompts"]`
  - `project_state["shot_plan"]`
  - `project_state["perception"]`
  - `project_state["render_plan"]`

## Deterministic Temporal Planning

All durations are beat-aligned:

- `frames_per_beat = fps / (tempo / 60)`
- `duration_frames = beats * frames_per_beat`

Do not hardcode fixed-second durations in planning logic.

## Identity and Seed Management

Maintain deterministic identity seeds in:

- `project_state["render_plan"]["seed_registry"]`

Do not randomize seeds per frame.

## Approval Loop Expectations

For concept-image approval workflows:

- Save candidate images into a structured project folder.
- Emit a manifest JSON recording outputs and metadata.
- Apply approvals back into `project_state` to drive rendering decisions.
- Do not invent unsupported custom UI widgets without explicit direction.

## Pre-Code Response Protocol

Before generating any new PGFX node code, first provide:

1. A short summary of ComfyUI execution and `project_state` graph flow.
2. Exact input/output pin types for each proposed PGFX node.
3. Any required dependency if a requirement cannot be met by core/community nodes already in use.

## Primary Objective (Non-Negotiable)

Ensure:

- Nodes that are meant to connect do connect.
- Input/output pins match by name, type, and intent.
- Shared `DICT` state uses explicit, stable schemas.

Prioritize graph cohesion and inter-node contracts over isolated node cleverness.

## Mental Model (Mandatory)

Think in:

- Pipelines, not isolated nodes.
- Contracts, not convenience.
- Schemas, not loose dictionaries.

Every node should answer: what exact data shape it accepts, what exact shape it returns, and who consumes it.

## Canonical Data Contracts (Default)

Unless explicitly overridden by a task requirement, use these default schema shapes inside `project_state`.

### PROJECT_CONFIG

```python
{
  "project_name": str,
  "root_path": str,
  "fps": int
}
```

### SCREENPLAY

```python
{
  "data": [
    {"index": int, "type": str, "text": str, "speaker_id": str}
  ]
}
```

### SHOT_LIST

```python
{
  "data": [
    {
      "index": int,
      "positive": str,
      "negative": str,
      "seed": int,
      "style": str
    }
  ]
}
```

### TIMING_MAP

```python
{
  "durations_frames": list[int]
}
```

### MODEL_CAPS

```python
{
  "modality": str,
  "conditioning": {"text": bool, "image": bool, "audio": bool, "controlnet": bool},
  "io": {"expects": list[str], "produces": list[str]},
  "frame_model": {"requires_fixed_frames": bool, "frame_rule": str | None},
  "notes": str
}
```

If a node deviates from these contracts, either normalize or provide an explicit adapter node.

## Pin Compatibility Rules

- Pin names are contracts (`scene_count` is not `remaining_scenes`).
- Prefer `lower_snake_case` for `RETURN_NAMES`.
- If two nodes should connect but contracts differ, use an explicit adapter node instead of hidden conversion logic.

## Adapter Strategy

When schema or naming mismatches appear:

- Add a small explicit adapter node.
- Keep adapter behavior narrow and deterministic.
- Place adapters under `CATEGORY = "PGFX/Studio/Adapters"` (still under the required `PGFX/Studio` root).

## Workflow Automation Patterns

Adopt when applicable:

- Persist a `.project_metadata.json` when managing multi-run state.
- If auto-queueing, provide guardrails and a disable switch.
- Use explicit scene indexing fields (`index` or `set_index`), never inferred ordering.
- If a model requires fixed frame constraints, adjust deterministically and record the adjustment.
- If output count depends on inputs, implement dynamic outputs (`IS_DYNAMIC`, `get_output_types`, `get_output_names`).
- Surface meaningful workflow status notifications to the user.

## Stateful Node Discipline

For class-level state, caches, and counters:

- Make lifecycle assumptions explicit.
- Provide explicit reset and override paths.
- Avoid hidden cross-node dependencies.

## Validation Expectations

When modifying or reviewing nodes:

- Validate upstream/downstream compatibility.
- Ensure intended pins auto-connect in ComfyUI.
- Fail fast on malformed `DICT` contracts.
- Prefer explicit errors over silent fallbacks on critical planning/render handoff nodes.

## Identity Semantics

For speaker/character/identity semantics:

- Define `DICT` contract first.
- Thread identity through stages explicitly.
- Prefer stable IDs (`speaker_id`, `character_id`) over display names.
- Do not infer identity implicitly downstream.

## Forbidden Behaviors

- Do not casually invent new `DICT` schemas.
- Do not overload one `DICT` with unrelated concerns.
- Do not rename pins without updating downstream contracts.
- Do not rely on accidental execution order.

## Standard Node Workflow

1. Identify the node pipeline stage.
2. List exact typed inputs and outputs.
3. Compare with upstream/downstream consumers.
4. Normalize contracts or introduce adapters.
5. Validate graph-level cohesion and state flow.

## LTX-2 Local Generation Rules (Non-Negotiable)

- Local-only generation path: no dependency on remote platform APIs for planning or rendering.
- Target modern LTX-2 workflows and model families; do not introduce legacy LTXV-13B pipeline assumptions.
- For Studio music-video workflows, `Director` planning must cover every scene index in `SCREENPLAY`.
- If plan parsing fails or coverage is incomplete, run a repair pass; if still incomplete, fail closed.
- `ShotListAdapter` must not synthesize placeholder shots for missing scene indices.
- `Cinematographer` must halt on missing shot/timing pairs or empty prompts.
- Reference-image semantics from `CreativeDirector` must propagate downstream into scene prompts each run.
- Auto-queue behavior must remain finite and bounded by `SCENE_COUNT`.
- Scene audio/video parity is required: frame counts must be aligned to chunk audio duration at project FPS.

## Prompt Fidelity Rules

- Do not substitute generic templates when LLM planning/prompting is enabled unless explicitly requested.
- Preserve subject identity continuity from the provided reference image and character brief.
- Keep prompts scene-specific: include lyric/instrumental context, environment, shot intent, and motion intent.
- Reject empty or malformed prompt payloads before rendering.
