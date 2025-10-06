## `PromptCrafter_ImageCreator`
**Purpose:** Generates high-quality, detailed prompts for creating static images.
**How to Use:** Provide a high-level idea in `user_text` and optionally connect reference `image` inputs. The node analyzes your inputs, determines a creative style, and generates a polished prompt.
* **`user_text`**: Your main instruction. Describe the scene, subjects, and mood.
* **`image_count`**: Sets the number of available `image` and `image_weight` inputs.
* **`image_weight`**: Controls the influence of a specific reference image.
* **`style_override`**: Force a specific artistic style (e.g., "Cyberpunk", "Fantasy Battle") instead of letting the AI decide.
* **`style_tags`**: A comma-separated list of style names to blend together. Overrides the `style_override` dropdown.
* **`generate_schedule`**: If enabled, it will treat multi-paragraph text in `user_text` as a sequence of scenes, generating a schedule of prompts for animations or slideshows.

## `PromptCrafter_VideoCreator`
**Purpose:** Similar to the Image Creator, but specifically tuned for generating cinematic video prompts for models like AnimateDiff.
**How to Use:** The workflow is the same as the Image Creator, but the output prompt will be structured to emphasize **action, motion, and camera movement**.
* **Key Difference:** This node's AI persona is a "film director" and it will automatically suggest motion styles (e.g., "smooth, flowing") and camera movements (e.g., "tracking shot") to create more dynamic results.

## `PromptCrafter_LyricsCreator`
**Purpose:** A powerful and unique node for creating a complete visual storyboard from song lyrics.
**How to Use:** Provide lyrics via the `user_text` input or a `.srt`/`.lrc` file. You can also provide a high-level visual concept in `user_text` to guide the AI.
* **Creative Autopilot:** If you only provide lyrics, the AI will act as a creative director, inventing a visual theme, characters, and setting from scratch based on the song's mood.
* **`lyrics_file`**: Use this to load a timed `.srt` or `.lrc` file. This will generate a schedule where prompts are perfectly synced to the lyrics.
* **`audio_file`**: (Experimental) Provide the song's audio file to help the AI cross-reference and potentially correct the lyrics.
* **`generate_schedule`**: Should almost always be **True**. This formats the output for animation nodes.

## `PromptCrafter_QnA`
**Purpose:** A conversational AI assistant that can answer questions and use external information for context.
**How to Use:** Ask a question in `user_text`. You can chain the `history_out` to `history_in` on a new node to continue the conversation.
* **`enable_web_search`**: Allows the node to perform a web search for questions about recent events or topics requiring current information.
* **`file_name`**: Provide a `.txt` or `.pdf` file as a context document for the AI to read and answer questions about.
* **`image`**: Connect an image and ask a question about it (requires a vision model).
* **`auto_select_model`**: Automatically switches to a vision model if an image is connected, or a text model if not. Highly recommended to keep this on.

## `PromptCrafter_Image_Captioner`
**Purpose:** Automatically generates descriptive captions for images, ideal for dataset creation or organizing your library.
**How to Use:** Can be used in single mode (one image) or batch mode (an entire folder).
* **`captioner_profile`**: Select a pre-configured captioning prompt for different use cases (e.g., "Training Style", "Detailed Scene Description"). Overrides the manual prompt text box.
* **`batch_mode`**: Enable to process all images in the `input_folder`.
* **`skip_existing`**: In batch mode, it won't re-caption an image that already has a `.txt` file.
* **`rename_file_with_caption`**: A powerful feature that renames your image file based on the generated caption (e.g., `a_photo_of_a_cat.png`), making your collection instantly searchable.
* **`add_caption_to_metadata`**: Writes the caption directly into the image's EXIF/PNG metadata.

## `PromptCrafter_FileOrganizer`
**Purpose:** A powerful utility to automatically sort your images and other files into folders based on a flexible ruleset.
**How to Use:** Point it to an `input_folder`, define your rules in `organization_scheme`, and set `run_organization` to True.
* **`organization_profile`**: Select a pre-configured set of rules from a dropdown. This is an easy way to get started without writing rules manually. Choosing a profile will override any text in the `organization_scheme` box.
* **`organization_scheme`**: The core of the node. You define rules like `captionfile_contains: cat -> By_Subject/Cats` or `image_resolution: >1920x1080 -> High_Resolution`.
* **`auto_generate_scheme`**: Let the AI analyze a sample of your files and create a logical organization scheme for you.
* **`action`**: Choose to `Copy` files (safer) or `Move` them.
* **`dry_run`**: A safe way to test your rules. It will print what it *would* do without actually moving any files.

## `PromptCrafter_ClearCache`
**Purpose:** A simple utility to manage the node pack's internal cache.
**How to Use:** If you find a node is not updating its output after you change an input (e.g., you edited a text file it's reading), run this node with the "Clear Cache" action. This forces all nodes to re-evaluate their inputs from scratch.

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

`{`\
`    "name": "Sort by Checkpoint Model",`\
`    "description": "Sorts images into folders based on the checkpoint model used.",`\
`    "scheme": "# This scheme uses metadata to find the model name.\\nmetadata_contains: Juggernaut.safetensors -> By_Model/Juggernaut\\nmetadata_contains: Dreamshaper.safetensors -> By_Model/Dreamshaper\\n# Add more model rules here"`\
`}`

**Important Notes:**
*   **Valid JSON**: Ensure the file remains valid JSON after your edits. A missing or extra comma is a common source of errors. You can use an online JSON validator to check your file if you have issues.
*   **Newline Characters (`\n`)**: In the `"scheme"` string, each rule **must** be separated by `\n`. This is how you create new lines within a JSON string.
*   **Restart ComfyUI**: After saving your changes to `organization_profiles.json`, you must restart ComfyUI for the new profiles to appear in the dropdown menu.

### Adding Custom Captioner Profiles

You can add your own custom captioning prompts to the `captioner_profile` dropdown in the `PromptCrafter_Image_Captioner` node.

1.  **Locate the File**: Open the `captioner_profiles.json` file located in your `ComfyUI/custom_nodes/ComfyUI-PromptCrafter/` directory.

2.  **Understand the Structure**: The file is an array of profile objects. Each object defines a unique captioning style with three key parts:
    *   `"name"`: The name of the profile that will appear in the dropdown menu (e.g., "My Custom Tagger").
    *   `"description"`: A short explanation of what your profile does.
    *   `"prompt"`: The full prompt that will be sent to the AI model to generate the caption. You can use `\n` for newlines to structure your prompt clearly.

3.  **Add Your Profile**:
    *   Copy an existing profile object (from `{` to `}`).
    *   Paste it at the end of the list, just before the closing `]`. Remember to add a comma `,` after the preceding profile's closing `}`.
    *   Modify the values to define your new captioning prompt.

**Example of a new custom captioner profile:**

`{`\
`    "name": "My Custom Tagger",`\
`    "description": "Generates tags for a specific character.",`\
`    "prompt": "You are a dataset tagger. Your most important tag is 'my_character_name'. Start the caption with this tag, then describe the rest of the image with comma-separated tags."`\
`}`

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

`{`\
`    "name": "Gothic Horror",`\
`    "type": "Style",`\
`    "modes": ["Image", "Video"],`\
`    "persona": "You are a master of gothic literature and horror cinematography.",`\
`    "inspiration": "Composition inspired by the chiaroscuro of Caravaggio and the unsettling atmosphere of a Guillermo del Toro film."`\
`}`

**Important Notes:**
*   **Restart ComfyUI**: After saving your changes to `style_profiles.json`, you must restart ComfyUI for the new styles to appear in the dropdown menus.
*   **JSON Validity**: Always ensure your file is valid JSON. Use an online validator if you're unsure.