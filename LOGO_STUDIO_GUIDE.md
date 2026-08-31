# 🎨 PGFX Logo Studio: The Design Window Masterclass
**Operational Tier: Enterprise Premier**

The **PGFX Design Window** is the crown jewel of the PromptCrafter suite. It is a fully-featured vector design environment built for precise manual logo construction inside ComfyUI.

---

## 🏎️ 7. Manual Design Source Of Truth
The automated CAD handoff path has been retired. The Studio canvas itself is now the canonical design source.

### **The Recommended Workflow**
1.  **Build or refine the logo in the Studio**: Use the design window to place text, shapes, and styling exactly where you want them.
2.  **Let the Agent interpret, not redraw**: Use the **Logo Designer Agent** to convert your intent and any reference imagery into prompt-safe Studio settings.
3.  **Generate from the saved layout**: The Studio node reads its own saved canvas JSON and turns that geometry, text, and styling into the downstream prompt.

### **Why This Is Better**
This keeps the workflow faithful to the user-created composition instead of asking the Agent to synthesize a layout from scratch.

---

## 🧬 8. Evolutionary Style Discovery
The suite is a "Creative Sponge." It autonomously expands its own design dictionary as you work.

### **Bilateral Discovery**
1.  **Prompt Discovery**: If you use a new, unique keyword in your prompt (e.g., *"Iridescent Slime"*), the Agent will categorize it as a new material and save it to the permanent library.
2.  **Visual Discovery**: If your reference images contain a unique motif, the AI Vision model will extract and categorize it automatically.
3.  **The Ranking System**: Every style is ranked by **usage_count**. Over time, the AI learns your preferences and prioritizes "Proven Industrial Styles."

---

## 📏 9. Precision Balancing
Use the **High-Precision Linear Sliders** for surgical control:
- **Geometry Adherence**: 
    - **1.0**: Clinical strictness (CAD precision).
    - **0.5**: Artistic flow (The Sweet Spot).
    - **0.1**: Loose sketch suggestion.
- **Creative Flair**:
    - **1.0**: Ornate masterpiece (Max complexity).
    - **0.5**: Professional balance.
    - **0.1**: Minimalist tech.

---

## 🎮 STUDIO CONTROLS

### Drawing Tools
- **D**: Free-draw Mode (Pencil/Spray/Circle)
- **S**: Selection Mode (Move/Edit)
- **Brush Settings**: Set size, color, and opacity in the top bar.

### Navigation
- **Mouse Wheel**: Zoom In/Out
- **Middle Mouse Click**: Pan/Grab Canvas

### Keyboard
- **TAB / SHIFT+TAB**: Cycle Objects
- **DEL / BACKSPACE**: Delete Selected
- **Arrow Keys**: Nudge Object (1px)
- **SHIFT + Arrow Keys**: Nudge Object (10px)

### Shortcuts
- **Double-Click**: Edit Text Layers
- **Drag Handles**: Scale / Rotate

### Sync Note
Editing the 'Primary Text' (the first one added) will auto-sync with the node's text input on Save.

---

## 📋 NODE WIDGET REFERENCE

This window = visual layout only.

The following widgets on the node control the AI prompt sent to your model:

**output_intent**
- `VECTOR`: Enforces strict flat 2-D. No lighting, no 3D. Best for vinyl/screen-print.
- `RASTER`: Enables shading, depth, cinematic lighting for print/photo use.

**background_mode**
- `simple`: Solid background colour (use Canvas BG above).
- `preset`: Use a named environment scene.
- `custom`: Write your own background description.
- `none`: No background instruction sent to model.

**background_preset**
Active when background_mode = preset. Selects a scene environment (e.g. space nebula, city street).

**background_custom_prompt**
Active when background_mode = custom. Describe any background you want.

**scene_interaction**
Describes how the design physically interacts with its environment. E.g. "Letters sinking into sand."

**material**
Changes the perceived surface of all design elements (e.g. gold, marble, neon).

**decoration**
Adds surface ornamentation on top of the material (e.g. glowing_edges, ornate_engraving).

**action**
Applies a dynamic physical process to the design (e.g. burning, dissolving, floating).

**environment_1/2/3**
Three independent atmospheric effect slots. Adds particles, fog, lightning, etc. around the design.

**environment_1_intensity / environment_2_intensity / environment_3_intensity**
Per-slot intensity for each environment effect. 0.0 = disabled. 0.5 = subtle/sparse. 1.0 = normal. 1.5 = heavy. 2.0 = dramatic/intense.

**style_mode**
- `flat_vector`: Pure 2-D, no shading (best for vinyl).
- `creative`: Cinematic lighting and artistic direction.
- `realistic`: Photorealistic rendering.
- `3d_render`: Full physically-based 3-D render look.

**intensity**
0.2 = very subtle styling. 1.0 = normal. 2.0 = extreme detail.

**extra_instruction**
Free-form text appended verbatim to the final model prompt.

---

## 🤖 MCP Agent — Chat-Driven Media Creation

The **PGFX MCP Agent** (`🎭 PGFX MCP Agent`) is a general-purpose agent that creates any type of media from natural language requests. It operates outside the Logo Designer pipeline and has access to all ComfyUI capabilities.

### Quick Start
1. Add the `🎭 PGFX MCP Agent` node to your workflow
2. Select an LLM model from the dropdown
3. Send a chat message describing what you want to create
4. The node returns `QUEUED_ASYNC` immediately and generates in the background
5. Browse the ComfyUI output directory with a thumbnail/load node to see the finished files

> **Note:** The agent is a fire-and-forget trigger node (`OUTPUT_NODE`). It runs on a background thread so it never blocks ComfyUI's single serial queue worker. Results are written to disk, not returned through output pins.

### Example Prompts
- "Create a cyberpunk cityscape at night with neon lights"
- "Generate a realistic portrait of a woman with red hair"
- "Make a short video of a cat walking"
- "Download MiniMaxAI/MiniMax-Music3 to E:/models/music"
- "List models in E:/models/checkpoints"

### Output
| Output | Type | Description |
|--------|------|-------------|
| `status` | STRING | `QUEUED_ASYNC` on submit (or `ALREADY_RUNNING` for a duplicate). Generated media appears in the ComfyUI output directory. |

### Tool Calls
The agent can execute tool calls for model management:
- **Download models**: "Download [repo_id] to [local_dir]"
- **List local files**: "List models in [directory]"

Requires `huggingface-hub` to be installed for downloads.

---

*Documentation maintained by PGFX Industrial Engineering.*
