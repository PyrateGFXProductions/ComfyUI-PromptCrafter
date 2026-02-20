---
name: ltx-2-workflow-alignment
description: Enforce and implement LTX-2-only video workflow alignment for PGFX PromptCrafter. Use when requests mention LTX, LTX-2, AI music video, AI movie maker, cartoon video maker, audio-to-video, lip sync, retake/extend, or LTX API/ComfyUI workflow parity. Reject legacy LTXV-13B-0.9.x model paths and keep all recommendations and implementation scoped to LTX-2 capabilities.
---

# LTX-2 Workflow Alignment

## Overview

Apply a strict LTX-2-only implementation policy and map LTX generation patterns into PGFX PromptCrafter nodes, prompt grammar, and workflow JSONs. Keep recommendations implementation-ready and tied to concrete repository files.

## Workflow
1. Enforce model-family scope before planning.
2. Gather current PGFX implementation points that affect prompt format, shot planning, schedule generation, and scene rendering.
3. Map LTX-2 generation capabilities to PGFX data contracts and nodes.
4. Apply changes that preserve PGFX contracts while improving LTX-2 parity.
5. Validate behavior with deterministic checks and document residual gaps.

## Hard Scope Rules
- Refuse legacy `LTXV-13B-0.9.x` model targeting.
- Keep all model recommendations in the `LTX-2` family.
- Preserve existing PGFX contracts (`PROJECT_CONFIG`, `TIMING_MAP`, `SHOT_LIST`) unless explicit refactor approval is provided.
- Prefer additive adapters and format modes over breaking schema changes.

## Implementation Checklist
1. Add explicit LTX-2 target model format options where prompts are formatted.
2. Remove or relax camera/shot vocabulary constraints that block LTX-2 prompting fidelity.
3. Review prompt sanitization length caps for over-truncation of cinematic detail.
4. Build or update workflows for LTX-2 text/image/audio generation and iterative retake/extend loops.
5. Keep negative-prompt and continuity logic coherent across Creator and Studio paths.

## Required File Targets
- `core/pgfx_base_creator.py`
- `nodes/pgfx_creator_nodes.py`
- `core/pgfx_thinking_engine.py`
- `nodes/pgfx_studio_nodes.py`
- `workflows/`

## Validation
- Run skill structure validation:
  - `python /home/pyrategfx/.codex/skills/.system/skill-creator/scripts/quick_validate.py .cursor/skills/ltx-2-workflow-alignment`
- Verify new guidance remains LTX-2-only:
  - `rg -n "(?i)ltxv-13b|0\\.9\\.7|legacy ltxv" .cursor/skills/ltx-2-workflow-alignment`

## References
- Load `references/pgfx-ltx2-alignment-checklist.md` for repository-specific mapping and acceptance criteria.
