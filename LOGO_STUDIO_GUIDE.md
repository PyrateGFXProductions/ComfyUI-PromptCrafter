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

*Documentation maintained by PGFX Industrial Engineering.*
