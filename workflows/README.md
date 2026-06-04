# ☠️ PGFX PromptCrafter — Official Demos

This directory contains the "Elite" standard demo workflows for the PGFX node suite. These workflows have been rebuilt from the ground up to showcase the **Unified Studio Binder** architecture and the **Cinema Grade** procedural animation tools.

---

### 🎬 1. Studio Elite Production Line
`PGFX_Studio_Elite_Production_Line.json`
*   **The Workflow:** A complete, automated movie production line.
*   **The Chain:** Producer ➔ Sound Engineer ➔ Screenwriter ➔ Creative Director ➔ Director ➔ Cinematographer ➔ Editor ➔ PostMaster.
*   **Key Feature:** Uses the unified `STUDIO_BINDER` to pass project state through all 8 cinematic departments.

---

### 👄 2. Cinema Viseme Rig Demo
`PGFX_Cinema_Viseme_Rig_Demo.json`
*   **The Workflow:** High-fidelity procedural mouth animation.
*   **Key Feature:** Showcases **Gaussian Temporal Smoothing** and **Weighted Phonetic Timing** to eliminate jitter.
*   **Outputs:** Optimized guides for **LivePortrait**, **ControlNet (Canny)**, and **Lip-Focus Masks**.

---

### 🔀 3. Universal Switch Box Demo
`PGFX_Universal_Switch_Box_Demo.json`
*   **The Workflow:** Intelligent, signal-less branching for complex graphs.
*   **Key Feature:** Demonstrates **Auto-Detect (Priority)** mode. The node automatically routes the first active pipeline branch it detects without needing separate signal wires.
*   **Universal:** Supports Images, Latents, Text, and Masks via wildcard pins.

---

### 🎨 4. Logo Designer Elite Demo
`PGFX_Logo_Designer_Elite_Demo.json`
*   **The Workflow:** Professional vector design environment with Agentic reasoning.
*   **Key Feature:** Showcases the **Layers Panel**, **Advanced Gradients**, and the **"Send to Agent"** bridge for precise AI refinements.
*   **Final Output:** Direct conversion to high-quality SVG via the **PGFX Image Vectorizer**.

---

### 📥 Requirements & Setup
For the best experience, ensure you have the following custom nodes installed:
1.  **ComfyUI-PromptCrafter** (This pack)
2.  **LivePortrait** (Recommended for Cinema Rig)
3.  **ComfyUI-Audio** (For WhisperX integration)
4.  **ControlNet Union** (For cinematic phonetic drivers)

*Maintained by PGFX Industrial Engineering. Last updated: 2026-06-03.*
