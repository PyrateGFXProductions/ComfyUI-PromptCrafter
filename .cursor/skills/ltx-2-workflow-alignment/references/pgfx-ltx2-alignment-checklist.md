# PGFX LTX-2 Alignment Checklist

## Purpose
Use this checklist to implement LTX-2-only workflow parity in PGFX PromptCrafter without breaking existing contracts.

## Non-Negotiable Scope
- Allow only LTX-2 model family targeting.
- Exclude `LTXV-13B-0.9.x` paths, presets, and workflow assumptions.
- Keep compatibility with existing PGFX data contracts.

## Repository Mapping
### Prompt target formats
- `nodes/pgfx_creator_nodes.py`
  - Add user-facing `LTX-2` target format options.
- `core/pgfx_base_creator.py`
  - Add formatter branch for `LTX-2`.

### Music-video prompt grammar
- `core/pgfx_thinking_engine.py`
  - Update VRG camera/shot constraints and category handling for LTX-2-friendly language.
- `nodes/pgfx_studio_nodes.py`
  - Update Creative Director and Director prompts to use LTX-2-compatible shot/motion vocabulary.

### Prompt sanitization
- `nodes/pgfx_studio_nodes.py`
  - Revisit prompt length caps and sanitization rules that may remove useful cinematic detail.

### Scene execution and assembly
- `nodes/pgfx_studio_nodes.py`
  - Preserve `SHOT_LIST` and `TIMING_MAP` structure.
  - Ensure Cinematographer and Editor path remains deterministic after prompt updates.

### Workflow artifacts
- `workflows/`
  - Add LTX-2-centered examples:
    - music-video flow
    - movie-maker flow
    - cartoon/stylized flow

## Quality Gates
1. Keep all new model references explicitly LTX-2.
2. Keep old project functionality intact for non-LTX pipelines.
3. Keep line-of-action clear: generate -> review -> retake/extend -> finalize.
4. Keep negative prompt handling coherent across Creator and Studio.
5. Keep scene timing deterministic and aligned with `TIMING_MAP`.

## Acceptance Criteria
- Users can select LTX-2 format directly in relevant nodes.
- Generated prompts keep cinematic detail and avoid over-truncation.
- Music-video workflow keeps audio-driven timing and supports lip-sync-friendly scene direction.
- No newly introduced references to legacy LTXV model families.
