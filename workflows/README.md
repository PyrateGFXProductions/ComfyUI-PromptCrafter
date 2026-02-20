# PGFX Example Workflows

These workflows are intended as working, end-to-end examples for testing PGFX nodes. They are intentionally simple and use standard ComfyUI nodes where possible.

**How To Load**
1. In ComfyUI, click `Load` and select a workflow JSON from `workflows/`.
2. Update model dropdowns and input files as needed.
3. Queue the prompt.

**Included Workflows**
- `PGFX_VisualCreator_SD15_Image.json`: Visual Creator to a basic SD 1.5 image pipeline (CheckpointLoaderSimple -> CLIP -> KSampler -> VAE -> SaveImage).
- `PGFX_LyricsCreator_Schedule_Export.json`: Lyrics Creator with Schedule and SRT exported via SaveTextFile.
- `PGFX_LTX2_Local_MusicVideo_Starter.json`: Lyrics Creator -> LTX-2 Local Pipeline Builder starter workflow that generates local manifest + render script artifacts.
- `PGFX_LTX2_GGUF_T2V_MusicVideo_Starter.json`: Full local GGUF text-to-video starter (adapted from your `More_LTX-2` references) with PGFX LyricsCreator driving positive/negative prompts.
- `PGFX_LTX2_TransformerOnly_T2V_MusicVideo_Starter.json`: Transformer-only local starter (adapted from your wrapped LTX-2 T2V distilled workflow) with PGFX LyricsCreator driving the wrapped subgraph prompt input.
- `PGFX_Studio_LTX2_GGUF_Local_EndToEnd.json`: Full PGFX Studio chain (Producer -> SoundEngineer -> Screenwriter -> CreativeDirector -> Director -> ShotListAdapter -> Cinematographer -> Editor -> PostMaster) wired into local **audio-conditioned** LTX-2 GGUF generation (scene audio chunks feed `LTXVAudioVAEEncode` + output audio path).
- `PGFX_Studio_LTX2_TransformerOnly_Local_EndToEnd.json`: Full PGFX Studio chain wired into the local wrapped LTX-2 transformer-only graph (`ltx-2-19b-dev-fp8_transformer_only.safetensors` target).
- `PGFX_QnA_To_Text.json`: Simple QnA response saved to a text file.
- `PGFX_Captioner_Single_Image.json`: LoadImage -> Captioner -> SaveTextFile.
- `PGFX_SRT_Subtitle_Burn.json`: Audio to SRT to subtitle burn onto a single image frame.

**Dependencies**
- `PGFX_SRT_Subtitle_Burn.json` uses `VHS_LoadAudioUpload` from `comfyui-videohelpersuite`. Replace it with any node that outputs `AUDIO` if you prefer.
- Image generation workflows require an SD checkpoint and VAE available to `CheckpointLoaderSimple`.
- `PGFX_LTX2_GGUF_T2V_MusicVideo_Starter.json` is adapted from your `More_LTX-2` GGUF workflows and expects those LTX-2 node packs (e.g., `UnetLoaderGGUF`, `LTXV*` nodes, KJ audio/video VAE nodes) to be installed.
- `PGFX_LTX2_TransformerOnly_T2V_MusicVideo_Starter.json` includes a wrapped subgraph node (`9b0e709c-82c7-46c0-a2e4-5e96b6f16090`) from your source workflow and requires that environment/plugins.
- `PGFX_Studio_LTX2_GGUF_Local_EndToEnd.json` is scene-iterative with Auto-Queue enabled by default: one queue pass renders one scene in Auto-Increment mode and the Auto-Queue node schedules the remaining scenes. If Auto-Queue is disabled, keep queueing until `remaining_scenes` reaches `0`, then PostMaster stitches the final output automatically. This workflow is rebuilt from your `LTX-2 Text Audio 2 Video GGUF 12GB` reference so audio conditioning is local and per-scene.
- `PGFX_Studio_LTX2_TransformerOnly_Local_EndToEnd.json` is also scene-iterative (Auto-Increment). Add the Auto-Queue node if you want hands-free multi-scene runs.
- Lora loaders in the LTX-2 GGUF and transformer workflows are set to bypass (`mode: 4`) by default for compatibility with local installs that only have core LTX-2 models.
- `whisperx` is optional for `PGFX_Studio_Screenwriter`: if unavailable, Screenwriter now degrades gracefully. Provide `raw_lyrics_override` to get timing-based fallback lyric segmentation.
- Studio defaults are tuned for fidelity and local reliability: keep `use_prompt_template=False` for normal generation, use template mode only for explicit troubleshooting.
- Studio planning and adapters are fail-closed on incomplete scene plans/shots to prevent generic unrelated outputs.
- `PGFX_Studio_LTX2_GGUF_Local_EndToEnd.json` currently uses conservative decode settings for 12GB-class VRAM (`VAEDecodeTiled: tile_size=384, overlap=48, temporal_size=48, temporal_overlap=4`).

**Notes**
- The workflows include placeholder filenames like `input/your_image.png` and `input/your_audio.wav`. Replace them with real files.
- Output text files default to `ComfyUI/output/PromptCrafter` and can be changed on each SaveTextFile node.
