# PGFX VRGDG Bridge V1

This bridge is meant to replace the fragile front half of the current VRGDG music-video flow while leaving the existing MVC renderer intact.

## Goal

Keep using the VRGDG image-first LTX clip workflow for rendering, but stop feeding it beat-fragmented lyric chunks that reset the scene every time a line gets cut in half.

The bridge does four things:

1. Re-lock subtitle timings to full lyric lines whenever possible.
2. Merge continuity-breaking micro-segments into larger story beats.
3. Translate slang and idioms into literal narrative guidance before prompt creation.
4. Emit VRGDG-compatible `scene_srt`, `lyricsegments_json`, `storygroups_json`, and prompt maps without overwriting any existing VRGDG workflow files.

## Recommended Wiring

### 1. PromptCrafter intake

Use `PromptCrafter_LyricsCreator` as the planner/intake node.

Relevant outputs:

- `clean_lyrics_txt`
- `lyrics_srt`
- `schedule_json`
- `auto_theme` or your own theme text

### 2. Semantic bridge

Node: `PGFX_Studio_VRGDGSemanticBridge_V1`

Inputs:

- `clean_lyrics_txt: STRING`
- `lyrics_srt: STRING`
- `lyricsegments_mode: STRING`
- `lock_to_lyric_lines: BOOLEAN`
- `merge_short_segments: BOOLEAN`
- `min_segment_seconds: FLOAT`
- `max_merge_lookahead: INT`
- `custom_glossary_json: STRING`
- `custom_glossary_text: STRING`

Outputs:

- `scene_srt: STRING`
- `lyricsegments_json: STRING`
- `semantic_segments_json: STRING`
- `semantic_guidance_block: STRING`
- `bridge_report: STRING`

What it does:

- Uses the PromptCrafter `lyrics_srt` timing as the raw timing source.
- Aligns those timings back to full lyric lines from `clean_lyrics_txt`.
- Merges very short fragments into adjacent continuity beats.
- Adds literal interpretation for slang and idioms before downstream prompt generation.

### 3. Story-group bridge

Node: `PGFX_Studio_VRGDGStoryGroupBridge_V1`

Inputs:

- `semantic_segments_json: STRING`
- `global_theme: STRING`
- `story_concept: STRING`
- `character_anchor: STRING`
- `default_location: STRING`
- `default_wardrobe: STRING`
- `camera_cycle: STRING`
- `chorus_strategy: STRING`
- `semantic_guidance_block: STRING` (optional pass-through from the semantic bridge)

Outputs:

- `storygroups_json: STRING`
- `continuity_manifest_json: STRING`
- `text2image_guidance: STRING`
- `image2video_guidance: STRING`
- `bridge_report: STRING`

What it adds:

- `continuity_mode`
- `scene_family_id`
- `family_recall`
- `anchor_character_id`
- `anchor_location_id`
- `anchor_wardrobe_id`
- `semantic_notes`
- `visual_hints`

These extra keys are intentional. VRGDG batchers can still consume the standard story-group fields, while the added metadata gives you a continuity contract to preserve and eventually enforce more directly.

### 4. Schedule prompt map

Node: `PGFX_Studio_VRGDGSchedulePromptMap_V1`

Inputs:

- `schedule_json: STRING`
- `scene_srt: STRING`
- `fps: FLOAT`
- `selection_mode: STRING`

Outputs:

- `prompt_map_json: STRING`
- `prompt_count: INT`
- `bridge_report: STRING`

Purpose:

- Converts PromptCrafter schedule output into a VRGDG `prompt1 ... promptN` JSON map using the bridged `scene_srt` as the source of truth.

Use this for versioned `Text2Image_COMBINED_vrgdg_bridge_v1.json` or `Image2Video_COMBINED_vrgdg_bridge_v1.json` style artifacts if you want PromptCrafter-driven prompt timing.

### 5. Bundle validator

Node: `PGFX_Studio_VRGDGPromptPackageValidator_V1`

Inputs:

- `scene_srt: STRING`
- `lyricsegments_json: STRING`
- `storygroups_json: STRING`
- `strict: BOOLEAN`
- `text2image_json: STRING` (optional)
- `image2video_json: STRING` (optional)

Outputs:

- `text2image_json: STRING`
- `image2video_json: STRING`
- `bundle_manifest_json: STRING`
- `is_valid: BOOLEAN`
- `validation_report: STRING`

Purpose:

- Prevents the silent prompt drift that happens when scene counts and prompt counts stop matching.
- Normalizes prompt maps before they go into the VRGDG renderer workflow.

## Artifact Mapping

Recommended versioned outputs:

- `lyrics_subtitles_vrgdg_bridge_v1.srt`
- `lyricsegments_vrgdg_bridge_v1.json`
- `storygroups_vrgdg_bridge_v1.json`
- `Text2Image_COMBINED_vrgdg_bridge_v1.json`
- `Image2Video_COMBINED_vrgdg_bridge_v1.json`
- `continuity_manifest_vrgdg_bridge_v1.json`
- `bundle_manifest_vrgdg_bridge_v1.json`

Do not overwrite the current VRGDG workflow artifacts. Copy the VRGDG workflows to a new version and point the loader nodes at these bridge outputs.

## Exact JSON Contracts

### `lyricsegments_json`

VRGDG-compatible flat object:

```json
{
  "segment1_Duration_4.192": "(Verse 1) He pulled out a handgun, aimed it at the sky, yelled put your hands up, and fired two warning shots into the air [Literal meaning: pulled out the jammy = pulled out a gun or pistol; stick 'em up' = raise your hands during an armed robbery or hold-up; let two fly = fired two shots, often upward as warning shots.]",
  "segment2_Duration_3.004": "(Verse 1) ..."
}
```

### `semantic_segments_json`

Structured bridge contract:

```json
{
  "version": "vrgdg_bridge_v1",
  "segment_count": 2,
  "glossary_size": 15,
  "segments": [
    {
      "index": 1,
      "segment_key": "segment1",
      "start_sec": 0.0,
      "end_sec": 4.192,
      "duration_sec": 4.192,
      "structure_tag": "Verse 1",
      "scene_family_hint": "verse_1",
      "raw_text": "Pulled out the jammy, I aimed it at the sky...",
      "literal_text": "Pulled out a handgun, I aimed it at the sky...",
      "annotated_text": "Pulled out a handgun, I aimed it at the sky... [Literal meaning: ...]",
      "semantic_notes": "pulled out the jammy = pulled out a gun or pistol; let two fly = fired two shots, often upward as warning shots",
      "visual_hints": [
        "the character draws a handgun during a hold-up",
        "two warning shots fired up into the sky"
      ],
      "glossary_hits": []
    }
  ]
}
```

### `storygroups_json`

VRGDG-compatible story-group object with extra continuity metadata:

```json
{
  "story_summary": "A continuity-locked music video that preserves literal lyric meaning.",
  "groups": [
    {
      "index": 1,
      "subject": "lead performer, wearing dusty frontier outlaw clothes",
      "camera": "Medium shot",
      "scene_and_lighting": "desert frontier town at dusk; cinematic realism, dusty sunset light",
      "frame": "Verse 1 visual beat. He pulled out a handgun...",
      "continuity_mode": "start",
      "scene_family_id": "verse_1",
      "family_recall": false,
      "anchor_character_id": "lead",
      "anchor_location_id": "desert_frontier_town_at_dusk",
      "anchor_wardrobe_id": "dusty_frontier_outlaw_clothes",
      "semantic_notes": "jammy = gun or pistol; let two fly = fired two shots...",
      "visual_hints": [],
      "source_segment_key": "segment1"
    }
  ]
}
```

## Slang And Narrative Correction

The semantic bridge is where lyric interpretation gets fixed.

It now supports:

- built-in phrase-first slang matching
- plain-English replacement phrases for prompt text
- hidden semantic notes for LLM planning
- optional custom glossary overrides per song

### `custom_glossary_text` format

Use one line per phrase:

```text
jammy => gun or pistol | gun | a handgun visible in the character's hand | weapon, slang
let two fly => fired two shots upward as warning shots | fired two warning shots into the air | two muzzle flashes pointed toward the sky | gunfire, slang
stick 'em up => raise your hands during a hold-up | put your hands up | hands raised in surrender during a robbery | command, slang
```

A ready-made starter file is included at `workflows/PGFX_VRGDG_Slang_Glossary_Template_V1.txt`.

Format:

`phrase => meaning | replacement | visual_hint | comma,separated,tags`

### `custom_glossary_json` format

```json
{
  "jammy": {
    "meaning": "gun or pistol",
    "replacement": "gun",
    "visual_hint": "a handgun visible in the character's hand",
    "tags": ["weapon", "slang"]
  }
}
```

### Paul Revere example

For Beastie Boys `Paul Revere`, you should absolutely feed the bridge a song-specific glossary. The line:

`Pulled out the jammy, I aimed it at the sky. He yelled, "Stick 'em up!" and let two fly`

should not stay in raw slang form for planning. The bridge should convert it into literal planning guidance close to:

`He pulled out a handgun, aimed it at the sky, ordered everyone to put their hands up, and fired two warning shots into the air.`

That literal version is much easier for the prompt-generation stage to understand and keep visually coherent.

## Practical Integration Strategy

1. Keep your current VRGDG MVC renderer workflow.
2. Clone the current VRGDG prompt-creation workflow to a new version.
3. Replace the VRGDG segmentation front half with the PromptCrafter bridge chain above.
4. Save only versioned bridge artifacts.
5. Point the cloned MVC workflow at the bridge artifact folder or filenames.

That gives you better scene continuity, better lyric understanding, and a safer upgrade path without breaking the current workflow set.
