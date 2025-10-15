## `PromptCrafter_ImageCreator`
**Purpose:** Generates high-quality, detailed prompts for creating static images.

**How to Use:** Provide a high-level idea in `user_text` and optionally connect reference `image` inputs. The node analyzes your inputs, determines a creative style, and generates a polished prompt.

### Parameters

| Parameter | Type | Description |
| --- | --- | --- |
| **`user_text`** | `STRING` | Your main instruction. Describe the scene, subjects, and mood. This is the primary input for the AI. |
| **`model`** | `STRING` | The language model to use for all analysis and generation. Vision-capable models are required if using images. |
| **`image_count`** | `INT` | Sets the number of available `image` and `image_weight` inputs (from 1 to 5). |
| **`image_weight_*`** | `FLOAT` | (Dynamic Input) Controls the influence of a specific reference image. Higher values give the image more weight in the analysis. |
| **`temperature`** | `FLOAT` | Controls the creativity of the AI. Lower values (e.g., 0.1) are more deterministic, while higher values (e.g., 0.8) produce more creative and unpredictable results. |
| **`seed`** | `INT` | The seed for the language model. Use -1 for a random seed, or a specific number for reproducible results (requires Temperature to be > 0). |
| **`max_length_words`** | `INT` | Sets a target maximum length for the generated prompt in words. 0 means the AI will decide the optimal length. |
| **`style_override`** | `STRING` | Force a specific artistic style (e.g., "Cyberpunk", "Fantasy Battle") from a predefined list, instead of letting the AI decide based on your inputs. |
| **`style_tags`** | `STRING` | A comma-separated list of style names to blend together (e.g., `Cyberpunk, Film Noir`). This powerful feature overrides the `style_override` dropdown and allows for unique combinations. |
| **`critique_strength`** | `STRING` | Controls how heavily the AI edits its own initial draft. `Subtle` makes minor wording changes, `Normal` is a balanced revision, and `Heavy` allows for radical, creative restructuring. |
| **`deep_think_refinements`** | `INT` | The number of iterative refinement steps for the "Deep Think" process. Each step makes the AI reconsider and improve its own output. 0 disables this feature. |
| **`simplify_for_diffusion`** | `BOOLEAN` | If True, the final prompt is passed through an additional AI step to rephrase it in a way that is more easily understood by diffusion models, often improving prompt adherence. |
| **`timeout`** | `INT` | The timeout in seconds for each API call to the language model. Increase this if you are using a slow model and getting errors. |
| **`max_retries`** | `INT` | The number of times the node will retry a failed API call. |
| **`safe_mode`** | `BOOLEAN` | If True, a rule is added to the AI's instructions to avoid generating NSFW, violent, or controversial content. |
| **`debug_mode`** | `BOOLEAN` | If True, prints detailed intermediate prompts and AI reasoning to the console, which is useful for understanding the generation process. |
| **`save_to_txt`** | `BOOLEAN` | If True, saves the full context (image analysis, user text, final prompt, etc.) to a text file in the `ComfyUI/output/scene_prompts` directory. |
| **`filename_prefix`** | `STRING` | The subdirectory and filename prefix for the saved text file. |
| **`generate_schedule`** | `BOOLEAN` | If enabled, it will treat multi-paragraph text in `user_text` as a sequence of scenes, generating a schedule of prompts for animations or slideshows. |
| **`max_frames`** | `INT` | In schedule mode, this is the total number of frames for the animation. |
| **`interpolate_keyframes`** | `BOOLEAN` | In schedule mode, this will create smooth transitions between your keyframe prompts. |
| **`interpolation_frame_interval`**| `INT` | In schedule mode, the number of frames between interpolated prompts. |

## `PromptCrafter_VideoCreator`
**Purpose:** Generates cinematic, motion-focused prompts for video models like AnimateDiff.

**How to Use:** The workflow is the same as the Image Creator. Provide a high-level idea, and the node will generate a polished prompt emphasizing **action, motion, and camera movement**. The AI acts as a "film director" to suggest dynamic shots.

### Parameters

| Parameter | Type | Description |
| --- | --- | --- |
| **`user_text`** | `STRING` | Your main instruction for the video scene. Describe the subjects, setting, mood, and desired actions. |
| **`model`** | `STRING` | The language model to use for all analysis and generation. Vision-capable models are required if using images. |
| **`image_count`** | `INT` | Sets the number of available `image` and `image_weight` inputs (from 1 to 5). |
| **`image_weight_*`** | `FLOAT` | (Dynamic Input) Controls the influence of a specific reference image on the scene's characters and environment. |
| **`temperature`** | `FLOAT` | Controls AI creativity. Higher values are better for creative video concepts. Default is `0.4`. |
| **`seed`** | `INT` | The seed for the language model. Use -1 for a random seed. |
| **`max_length_words`** | `INT` | Sets a target maximum length for the generated prompt. For video, shorter prompts (around 80 words) often work best. 0 lets the AI decide. |
| **`style_override`** | `STRING` | Force a specific cinematic style (e.g., "Epic Fantasy", "Found Footage") from a predefined list. |
| **`style_tags`** | `STRING` | A comma-separated list of style names to blend together (e.g., `Sci-Fi, Horror`). Overrides the `style_override` dropdown. |
| **`critique_strength`** | `STRING` | Controls how heavily the AI edits its own initial draft. `Heavy` can produce very creative results for video. |
| **`deep_think_refinements`** | `INT` | The number of iterative refinement steps. More steps can lead to more detailed and coherent motion descriptions. 0 disables it. |
| **`simplify_for_diffusion`** | `BOOLEAN` | If True, the prompt is rephrased for better diffusion model understanding. |
| **`timeout`** | `INT` | The timeout in seconds for each API call. |
| **`max_retries`** | `INT` | The number of times the node will retry a failed API call. |
| **`safe_mode`** | `BOOLEAN` | If True, instructs the AI to avoid generating unsafe content. |
| **`debug_mode`** | `BOOLEAN` | If True, prints detailed intermediate steps to the console. |
| **`save_to_txt`** | `BOOLEAN` | If True, saves the full generation context to a text file. |
| **`filename_prefix`** | `STRING` | The subdirectory and filename prefix for the saved text file. |
| **`generate_schedule`** | `BOOLEAN` | If enabled, treats multi-paragraph text as a sequence of scenes, generating a keyframe schedule for animations. |
| **`max_frames`** | `INT` | In schedule mode, the total number of frames for the animation. |
| **`interpolate_keyframes`** | `BOOLEAN` | In schedule mode, creates smooth transitions between keyframe prompts. |
| **`interpolation_frame_interval`**| `INT` | In schedule mode, the number of frames between interpolated prompts. |

## `PromptCrafter_LyricsCreator`
**Purpose:** A powerful and unique node for creating a complete visual storyboard from song lyrics.
**How to Use:** Provide lyrics via the `user_text` input or a `.srt`/`.lrc` file. You can also provide a high-level visual concept in `user_text` to guide the AI.
* **Creative Autopilot:** If you only provide lyrics, the AI will act as a creative director, inventing a visual theme, characters, and setting from scratch based on the song's mood.
* **`lyrics_file`**: Use this to load a timed `.srt` or `.lrc` file. This will generate a schedule where prompts are perfectly synced to the lyrics.
* **`audio_file`**: (Experimental) Provide the song's audio file to help the AI cross-reference and potentially correct the lyrics.
* **`generate_schedule`**: Should almost always be **True**. This formats the output for animation nodes.

### Parameters

| Parameter | Type | Description |
| --- | --- | --- |
| **`user_text`** | `STRING` | Your main instruction for the video scene. Can be used to provide a visual concept, or the lyrics themselves if not using a file. |
| **`lyrics_file`** | `STRING` | Path to a `.srt` or `.lrc` file containing timed lyrics. This is the recommended way to sync visuals to music. |
| **`audio_file`** | `STRING` | (Experimental) Path to an audio file (`.mp3`, `.wav`). The AI can use this to help understand the song's structure and correct lyrics. |
| **`model`** | `STRING` | The language model to use for all analysis and generation. Vision-capable models are required if using images. |
| **`image_count`** | `INT` | Sets the number of available `image` and `image_weight` inputs (from 1 to 5). |
| **`image_weight_*`** | `FLOAT` | (Dynamic Input) Controls the influence of a specific reference image on the scene's characters and environment. |
| **`temperature`** | `FLOAT` | Controls AI creativity. Higher values are better for creative video concepts. Default is `0.4`. |
| **`seed`** | `INT` | The seed for the language model. Use -1 for a random seed. |
| **`max_length_words`** | `INT` | Sets a target maximum length for each generated prompt in the sequence. 0 lets the AI decide. |
| **`style_override`** | `STRING` | Force a specific cinematic or artistic style from a predefined list. |
| **`style_tags`** | `STRING` | A comma-separated list of style names to blend together. Overrides the `style_override` dropdown. |
| **`critique_strength`** | `STRING` | Controls how heavily the AI edits its own initial draft. `Heavy` can produce very creative results. |
| **`deep_think_refinements`** | `INT` | The number of iterative refinement steps. More steps can lead to more detailed and coherent visual storytelling. 0 disables it. |
| **`simplify_for_diffusion`** | `BOOLEAN` | If True, the prompt is rephrased for better diffusion model understanding. |
| **`timeout`** | `INT` | The timeout in seconds for each API call. |
| **`max_retries`** | `INT` | The number of times the node will retry a failed API call. |
| **`safe_mode`** | `BOOLEAN` | If True, instructs the AI to avoid generating unsafe content. |
| **`debug_mode`** | `BOOLEAN` | If True, prints detailed intermediate steps to the console. |
| **`save_to_txt`** | `BOOLEAN` | If True, saves the full generation context to a text file. |
| **`filename_prefix`** | `STRING` | The subdirectory and filename prefix for the saved text file. |
| **`generate_schedule`** | `BOOLEAN` | If enabled, treats lyrics or scenes as a sequence, generating a keyframe schedule for animations. Should be True for this node. |
| **`max_frames`** | `INT` | In schedule mode, the total number of frames for the animation. |
| **`interpolate_keyframes`** | `BOOLEAN` | In schedule mode, creates smooth transitions between keyframe prompts. |
| **`interpolation_frame_interval`**| `INT` | In schedule mode, the number of frames between interpolated prompts. |

## `PromptCrafter_QnA`
**Purpose:** A conversational AI assistant that can answer questions and use external information for context.
**How to Use:** Ask a question in `user_text`. You can chain the `history_out` to `history_in` on a new node to continue the conversation.
* **`enable_web_search`**: Allows the node to perform a web search for questions about recent events or topics requiring current information.
* **`file_name`**: Provide a `.txt` or `.pdf` file as a context document for the AI to read and answer questions about.
* **`image`**: Connect an image and ask a question about it (requires a vision model).
* **`auto_select_model`**: Automatically switches to a vision model if an image is connected, or a text model if not. Highly recommended to keep this on.

### Parameters
| Parameter | Type | Description |
| --- | --- | --- |
| **`user_text`** | `STRING` | Your question or instruction for the model. |
| **`model`** | `STRING` | The language model (text or vision) to use for the answer. |
| **`temperature`** | `FLOAT` | Controls creativity. Lower is more deterministic. |
| **`seed`** | `INT` | Seed for reproducible results. -1 for random. Set Temperature to 0 for full determinism. |
| **`timeout`** | `INT` | Timeout in seconds for each API call. Increase if you get timeout errors. |
| **`safe_mode`** | `BOOLEAN` | Enforce SFW rules to prevent NSFW, violent, or controversial content. |
| **`debug_mode`** | `BOOLEAN` | Print all intermediate prompts to the console for debugging. |
| **`save_to_txt`** | `BOOLEAN` | Save the full Q&A context and response to a text file in the ComfyUI/output directory. |
| **`image`** | `IMAGE` | Optional reference image for the query. Requires a vision model (VLM). |
| **`auto_select_model`** | `BOOLEAN` | Automatically select a vision model if an image is connected, or a text model if not. |
| **`enable_web_search`** | `BOOLEAN` | Allow the node to perform a web search for questions about recent events or topics requiring current information. |
| **`fast_web_search`** | `BOOLEAN` | In web search mode, only use search result snippets instead of fetching full page content. Much faster. |
| **`folder_path`** | `STRING` | Folder containing an optional context file (e.g., 'input' or 'input/texts'). |
| **`filename_prefix`** | `STRING` | Subdirectory and prefix for the saved text file. |
| **`file_name`** | `STRING` | The name of the text file within the specified folder. |
| **`chunk_large_context`** | `BOOLEAN` | Automatically chunk and summarize context files that are too large. |
| **`chunk_size_words`** | `INT` | The approximate size of each chunk in words for summarization. |
| **`summarization_strategy`** | `STRING` | How to summarize large context. Abstractive creates new text, Extractive pulls key sentences. |
| **`history_in`** | `STRING` | Input for conversation history. |
| **`clear_history`** | `BOOLEAN` | Set to True for one run to clear the conversation history. |

## `PromptCrafter_Captioner`
**Purpose:** Automatically generates descriptive captions for images, ideal for dataset creation or organizing your library.
**How to Use:** Can be used in single mode (one image) or batch mode (an entire folder).
* **`captioner_profile`**: Select a pre-configured captioning prompt for different use cases (e.g., "Training Style", "Detailed Scene Description"). Overrides the manual prompt text box.
* **`batch_mode`**: Enable to process all images in the `input_folder`.
* **`skip_existing`**: In batch mode, it won't re-caption an image that already has a `.txt` file.
* **`rename_file_with_caption`**: A powerful feature that renames your image file based on the generated caption (e.g., `a_photo_of_a_cat.png`), making your collection instantly searchable.
* **`add_caption_to_metadata`**: Writes the caption directly into the image's EXIF/PNG metadata.

### Parameters
| Parameter | Type | Description |
| --- | --- | --- |
| **`vision_model`** | `STRING` | The vision language model (VLM) to use for captioning. |
| **`image`** | `IMAGE` | The image to be captioned (for single mode). |
| **`filename`** | `STRING` | Filename for single mode (ignored in batch mode). If empty, a timestamp is used. |
| **`batch_mode`** | `BOOLEAN` | Enable batch processing of an entire folder. |
| **`input_folder`** | `STRING` | Directory of images to process in batch mode (relative to ComfyUI root). |
| **`skip_existing`** | `BOOLEAN` | In batch mode, skip images that already have a corresponding .txt caption file. |
| **`captioner_profile`** | `STRING` | Select a pre-configured captioning prompt. Overrides the manual prompt text box. |
| **`max_workers`** | `INT` | Number of parallel threads for batch processing. |
| **`caption_prompt`** | `STRING` | The prompt template used to guide the captioning model. |
| **`caption_prefix`** | `STRING` | A single trigger word to add to every caption. Overridden by the trigger words file. |
| **`trigger_words_folder_path`** | `STRING` | Folder containing an optional file of trigger words (one per line). |
| **`trigger_words_file`** | `STRING` | File with a list of trigger words to be randomly chosen from for each caption. |
| **`save_caption`** | `BOOLEAN` | Save the caption to a text file. |
| **`save_in_input_folder`** | `BOOLEAN` | If True, saves the .txt caption file in the batch mode input folder alongside the image. If False, saves to the output_path. |
| **`add_caption_to_metadata`** | `BOOLEAN` | Write the caption to the image's metadata (e.g., EXIF). Requires `piexif` library. |
| **`rename_file_with_caption`** | `BOOLEAN` | In batch mode, rename the image file based on the generated caption. Makes files searchable. |
| **`output_path`** | `STRING` | Subdirectory within ComfyUI/output to save caption files. |
| **`temperature`** | `FLOAT` | Controls creativity. Lower is more deterministic. |
| **`seed`** | `INT` | Seed for reproducible results. -1 for random. |
| **`timeout`** | `INT` | Timeout in seconds for each API call. Increase if you get timeout errors with slow models. |
| **`safe_mode`** | `BOOLEAN` | Enforce SFW rules to prevent NSFW, violent, or controversial content. |

## `PromptCrafter_FileOrganizer`
**Purpose:** A powerful utility to automatically sort your images and other files into folders based on a flexible ruleset.
**How to Use:** Point it to an `input_folder`, define your rules in `organization_scheme`, and set `run_organization` to True.
* **`organization_profile`**: Select a pre-configured set of rules from a dropdown. This is an easy way to get started without writing rules manually. Choosing a profile will override any text in the `organization_scheme` box.
* **`organization_scheme`**: The core of the node. You define rules like `captionfile_contains: cat -> By_Subject/Cats` or `image_resolution: >1920x1080 -> High_Resolution`.
* **`auto_generate_scheme`**: Let the AI analyze a sample of your files and create a logical organization scheme for you.
* **`action`**: Choose to `Copy` files (safer) or `Move` them.
* **`dry_run`**: A safe way to test your rules. It will print what it *would* do without actually moving any files.

### Parameters
| Parameter | Type | Description |
| --- | --- | --- |
| **`model`** | `STRING` | The language model to use for all analysis and generation. Vision-capable models are required if using images. |
| **`input_folder`** | `STRING` | The folder containing the files you want to organize (relative to ComfyUI root). |
| **`output_folder`** | `STRING` | The root folder where organized subdirectories will be created (relative to ComfyUI root). |
| **`organization_profile`** | `STRING` | Select a pre-configured organization scheme. Overrides the manual scheme text box. |
| **`organization_scheme`** | `STRING` | Rules for organizing files. |
| **`action`** | `STRING` | `Copy` files (safer) or `Move` them to the new location. |
| **`dry_run`** | `BOOLEAN` | Simulate the organization process and report actions without moving or copying files. |
| **`analysis_priority`** | `STRING` | The order of analysis. 'Metadata First' is fastest. |
| **`fallback_folder`** | `STRING` | Subfolder for files that do not match any rule. |
| **`auto_generate_scheme`** | `BOOLEAN` | Automatically generate an organization scheme by analyzing a sample of files. Overrides the manual scheme. |
| **`run_organization`** | `BOOLEAN` | Toggle to True to start the organization process. It will run once per execution. |
| **`max_workers`** | `INT` | Number of parallel threads for processing files. |
| **`recursive`** | `BOOLEAN` | Process files in all subdirectories of the input folder as well. |
| **`create_log_file`** | `BOOLEAN` | Create a text log file summarizing all operations in the output folder. |
| **`log_filename`** | `STRING` | The name of the log file to be created in the output folder. |
| **`delete_source_folder_on_move`** | `BOOLEAN` | After a successful 'Move' operation, delete the original input folder if it's empty. Use with caution. |

## `PromptCrafter_CacheUtility`
**Purpose:** A simple utility to manage the node pack's internal cache. The cache stores the results of expensive operations, like image analysis or AI-based generation, to make subsequent runs faster.

**How to Use:**
*   **`Clear Cache`**: If you find a node is not updating its output after you change an input (e.g., you edited a text file it's reading), run this node with the "Clear Cache" action. This forces all nodes to re-evaluate their inputs from scratch.
*   **`Check Size`**: This action reports how many items are currently stored in the cache out of the maximum capacity. This is useful for debugging and understanding memory usage.

### Parameters
| Parameter | Type | Description |
| --- | --- | --- |
| **`action`** | `STRING` | The action to perform. Choose between `Clear Cache` to empty the cache or `Check Size` to see its current status. |

## Customizing Profiles

You can easily add your own custom styles and organization schemes to the dropdown menus in the nodes. This is done by editing the `.json` files in the `ComfyUI-PromptCrafter` directory.

### Adding Custom Organization Schemes

You can add your own pre-configured rule sets to the `PromptCrafter_FileOrganizer` node's `organization_profile` dropdown.

1.  **Locate the File**: Open the `organization_profiles.json` file located in your `ComfyUI/custom_nodes/ComfyUI-PromptCrafter/` directory.

2.  **Understand the Structure**: The file is a JSON array `[...]` containing multiple profile objects `{...}`. Each object has three parts:
    *   `"name"`: The name that will appear in the dropdown menu (e.g., "My Custom Sorting").
    *   `"description"`: A short explanation of what your profile does.
    *   `"scheme"`: A string containing your organization rules. **Important:** Rules must be separated by a newline character (`\n`).

3.  **Add Your Profile**:
    *   Copy an existing profile object (from `{` to `}`).
    *   Paste it at the end of the list, just before the closing `]`. Make sure to add a comma `,` after the preceding profile's closing `}`.
    *   Modify the `"name"`, `"description"`, and `"scheme"` values for your new profile.

**Example of a new custom profile:**

Let's say you want to add a profile to sort images by the checkpoint model used. You would add the following object to the `organization_profiles.json` file:

`{
    "name": "Sort by Checkpoint Model",
    "description": "Sorts images into folders based on the checkpoint model used.",
    "scheme": "# This scheme uses metadata to find the model name.\\nmetadata_contains: Juggernaut.safetensors -> By_Model/Juggernaut\\nmetadata_contains: Dreamshaper.safetensors -> By_Model/Dreamshaper\\n# Add more model rules here"
}
`

**Important Notes:**
*   **Valid JSON**: Ensure the file remains valid JSON after your edits. A missing or extra comma is a common source of errors. You can use an online JSON validator to check your file if you have issues.
*   **Newline Characters (`\\n`)**: In the `"scheme"` string, each rule **must** be separated by `\\n`. This is how you create new lines within a JSON string.
*   **Restart ComfyUI**: After saving your changes to `organization_profiles.json`, you must restart ComfyUI for the new profiles to appear in the dropdown menu.

### Adding Custom Captioner Profiles

You can add your own custom captioning prompts to the `captioner_profile` dropdown in the `PromptCrafter_Captioner` node.

1.  **Locate the File**: Open the `captioner_profiles.json` file located in your `ComfyUI/custom_nodes/ComfyUI-PromptCrafter/` directory.

2.  **Understand the Structure**: The file is an array of profile objects. Each object defines a unique captioning style with three key parts:
    *   `"name"`: The name of the profile that will appear in the dropdown menu (e.g., "My Custom Tagger").
    *   `"description"`: A short explanation of what your profile does.
    *   `"prompt"`: The full prompt that will be sent to the AI model to generate the caption. You can use `\\n` for newlines to structure your prompt clearly.

3.  **Add Your Profile**:
    *   Copy an existing profile object (from `{` to `}`).
    *   Paste it at the end of the list, just before the closing `]`. Remember to add a comma `,` after the preceding profile's closing `}`.
    *   Modify the values to define your new captioning prompt.

**Example of a new custom captioner profile:**

`{
    "name": "My Custom Tagger",
    "description": "Generates tags for a specific character.",
    "prompt": "You are a dataset tagger. Your most important tag is 'my_character_name'. Start the caption with this tag, then describe the rest of the image with comma-separated tags."
}
`

**Important Notes:**
*   **Restart ComfyUI**: After saving your changes to `captioner_profiles.json`, you must restart ComfyUI for the new profiles to appear in the dropdown menu.
*   **JSON Validity**: Always ensure your file is valid JSON. Use an online validator if you're unsure.
### Adding Custom Style Profiles

You can add your own creative styles to the `style_override` dropdown in the creator nodes (`ImageCreator`, `VideoCreator`, `LyricsCreator`).

1.  **Locate the File**: Open the `style_profiles.json` file located in your `ComfyUI/custom_nodes/ComfyUI-PromptCrafter/` directory.

2.  **Understand the Structure**: The file is an array of profile objects. Each object defines a unique style with several key parts:
    *   `"name"`: The name of the style that will appear in the dropdown menu (e.g., "Gothic Horror").
    *   `"type"`: A short label for the dropdown, like "Style" or "Genre".
    *   `"modes"`: An array of strings specifying which nodes this style applies to. Options are `"Image"`, `"Video"`, and `"Lyrics"`.
    *   `"persona"`: A string that tells the AI what kind of expert it should be (e.g., "You are a master of gothic literature and horror cinematography."). This is the most important part for defining the style's voice.
    *   `"inspiration"`: A string that gives the AI specific artistic or directorial influences (e.g., "Composition inspired by the chiaroscuro of Caravaggio and the unsettling atmosphere of a Guillermo del Toro film.").

3.  **Add Your Profile**:
    *   Copy an existing profile object (from `{` to `}`).
    *   Paste it at the end of the list, just before the closing `]`. Remember to add a comma `,` after the preceding profile's closing `}`.
    *   Modify the values to define your new style.

**Example of a new custom style profile:**

`{
    "name": "Gothic Horror",
    "type": "Style",
    "modes": ["Image", "Video"],
    "persona": "You are a master of gothic literature and horror cinematography.",
    "inspiration": "Composition inspired by the chiaroscuro of Caravaggio and the unsettling atmosphere of a Guillermo del Toro film."
}
`

**Important Notes:**
*   **Restart ComfyUI**: After saving your changes to `style_profiles.json`, you must restart ComfyUI for the new styles to appear in the dropdown menus.
*   **JSON Validity**: Always ensure your file is valid JSON. Use an online validator if you're unsure.