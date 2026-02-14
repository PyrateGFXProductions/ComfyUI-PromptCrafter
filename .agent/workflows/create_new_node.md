---
description: Create a new custom node for ComfyUI-PromptCrafter causing strict adherence to project standards.
---

This workflow guides you through creating a new custom node, ensuring it meets all project standards for quality, compatibility, and code style.

1.  **Preparation**
    -   Review `docs/DEVELOPMENT_GUIDELINES.md` to refresh on code style and path handling.
    -   Identify the correct category for the node (e.g., `PromptCrafter/Utils`, `PromptCrafter/LLM`).

2.  **Create Node File**
    -   Create a new `.py` file in `nodes/` or an appropriate subdirectory.
    -   **Name:** Use `snake_case` for the filename (e.g., `nodes/my_new_node.py`).

3.  **Implement Node Class**
    -   Define the class name in `CamelCase`.
    -   **Add Docstring:** REQUIRED. Describe functionality and attributes.
    -   **Add Type Hints:** REQUIRED for all methods.
    -   **Define `INPUT_TYPES`:**
        -   Use strict types (`STRING`, `INT`, `IMAGE`, etc.).
        -   Use `folder_paths` if handling file inputs.
    -   **Define `RETURN_TYPES` and `RETURN_NAMES`:**
        -   Ensure names are descriptive and `lower_snake_case`.
    -   **Implement `FUNCTION`:** Set this to the name of your processing method.
    -   **Implement `CATEGORY`:** strict format `PromptCrafter/<Subcategory>`.

    ```python
    import torch
    import folder_paths

    class MyNewNode:
        """
        [Description of what the node does]
        """
        def __init__(self):
            pass

        @classmethod
        def INPUT_TYPES(cls):
            return {
                "required": {
                    "image": ("IMAGE",),
                    "param": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 10.0}),
                }
            }

        RETURN_TYPES = ("IMAGE",)
        RETURN_NAMES = ("processed_image",)
        FUNCTION = "process"
        CATEGORY = "PromptCrafter/Example"

        def process(self, image: torch.Tensor, param: float) -> tuple[torch.Tensor]:
            # Implementation here
            return (image,)
    ```

4.  **Register Node**
    -   Open `__init__.py` in the root (or subpackage).
    -   Import your node class.
    -   Add it to `NODE_CLASS_MAPPINGS` with a unique, descriptive key.
    -   Add a display name to `NODE_DISPLAY_NAME_MAPPINGS` (Optional but recommended for UI).

5.  **Verify Cross-Platform Paths**
    -   **Check:** Did you use `os.path.join`?
    -   **Check:** Did you use `folder_paths` for loading/saving?
    -   **Check:** Are there any hardcoded `/` or `\`? -> REMOVE THEM.

6.  **Local Testing**
    -   Run ComfyUI and verify the node loads without errors.
    -   Connect the node in a workflow and test correct data processing.

7.  **Final Code Polish**
    -   Run `black .` to format the code.
    -   Verify all docstrings are present.

8.  **Commit**
    -   Commit the new file + `__init__.py` changes.
