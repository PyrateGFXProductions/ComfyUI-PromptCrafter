# PGFX Example Workflows

These workflows are intended as working, end-to-end examples for testing PGFX nodes. They are intentionally simple and use standard ComfyUI nodes where possible.

**How To Load**
1. In ComfyUI, click `Load` and select a workflow JSON from `workflows/`.
2. Update model dropdowns and input files as needed.
3. Queue the prompt.

**Included Workflows**
- `PGFX_VisualCreator_SD15_Image.json`: Visual Creator to a basic SD 1.5 image pipeline (CheckpointLoaderSimple -> CLIP -> KSampler -> VAE -> SaveImage).
- `PGFX_LyricsCreator_Schedule_Export.json`: Lyrics Creator with Schedule and SRT exported via SaveTextFile.
- `PGFX_QnA_To_Text.json`: Simple QnA response saved to a text file.
- `PGFX_Captioner_Single_Image.json`: LoadImage -> Captioner -> SaveTextFile.
- `PGFX_SRT_Subtitle_Burn.json`: Audio to SRT to subtitle burn onto a single image frame.

**Dependencies**
- `PGFX_SRT_Subtitle_Burn.json` uses `VHS_LoadAudioUpload` from `comfyui-videohelpersuite`. Replace it with any node that outputs `AUDIO` if you prefer.
- Image generation workflows require an SD checkpoint and VAE available to `CheckpointLoaderSimple`.

**Notes**
- The workflows include placeholder filenames like `input/your_image.png` and `input/your_audio.wav`. Replace them with real files.
- Output text files default to `ComfyUI/output/PromptCrafter` and can be changed on each SaveTextFile node.
