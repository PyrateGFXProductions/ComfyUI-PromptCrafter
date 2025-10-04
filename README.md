-----

# PromptCraft for ComfyUI

Do you ever struggle to find the right words for a prompt? Or maybe you have a great idea but don't want to spend hours crafting the perfect "epic" prompt? **PromptCraft** is your creative co-pilot for ComfyUI, designed to make prompt engineering easy, intuitive, and inspiring.

It was built with a simple goal: to bridge the gap between your ideas and the final image or video. Whether you want to generate a new scene based on existing images, turn song lyrics into a music video storyboard, or automatically organize your creations, PromptCraft provides the tools. It uses powerful AI language models (both local and API-based) to understand your intent and translate it into high-quality, detailed prompts that produce stunning results.

-----

## ✨ Key Features

  - **🎬 Advanced Prompt Engineering**: Goes far beyond simple text merging. It uses a dynamic **Style Engine**, a "Deep Think" self-critique loop, and robust anti-hallucination checks to produce polished, cinematic prompts.
  - **🎵 Lyrics-to-Video Storyboarding**: A unique workflow that converts song lyrics or SRT subtitle files into a series of consistent, thematically-linked video prompts, making it easier than ever to visualize a music video.
  - **✍️ Image & Video Storyboarding**: The Image and Video creator nodes can generate a sequence of prompts from a multi-paragraph story, perfect for creating image series or multi-shot video scenes.
  - **🗂️ Intelligent File Organization**: A complete, end-to-end workflow to **Caption, Rename, and Organize** your entire image library. Automatically create descriptive captions, rename files for clarity, and then sort them into folders using powerful, customizable rules.
  - **💬 Conversational Q\&A**: The `QnA` node supports follow-up questions, allowing you to have a continuous conversation with the AI. It can use text files, PDFs, or web search results as context.
  - **🔌 Broad API Support**: Out-of-the-box support for local models via **Ollama**, plus **OpenAI**, **Anthropic**, and **Google** APIs.

-----

## 📦 Nodes Overview

### Creator Nodes

  - **`PromptCraft Image Prompt Creator`**: The perfect tool for generating high-quality prompts for static images. Provide reference images and high-level instructions, and it will generate a new, detailed prompt. Enable `generate_schedule` to turn a multi-paragraph story into a sequence of image prompts for a slideshow or image-to-video workflow.
  - **`PromptCraft Video Prompt Creator`**: Designed for creating cinematic video prompts compatible with models like AnimateDiff or SVD. It focuses on action and motion. Enable `generate_schedule` to create a multi-shot video scene from a multi-paragraph script.
  - **`PromptCraft Lyrics Creator`**: A dedicated interface for the powerful lyrics-to-video workflow. This is the node to use when your primary goal is to create a visual storyboard from a song, with support for SRT files for precise timing.
      - **✨ Creative Autopilot**: A powerful feature where providing **only lyrics** allows the AI to act as a creative director. It analyzes the song's mood, invents characters and settings, and builds a complete visual world from scratch.

### Utility Nodes

  - **`PromptCraft Image Captioner`**: Automatically generates descriptive text captions for your images. It can process a single image or an entire folder in batch mode.
      - **Dataset Creation**: Creates a matching `.txt` file for each image, perfect for training LoRAs or other models.
      - **File Renaming**: Optionally renames image files based on their generated caption (e.g., `a_photo_of_a_black_cat.png`), making your collection instantly human-readable and searchable.
  - **`PromptCraft File Organizer`**: A powerful tool to automatically sort your images and videos into folders based on a flexible ruleset. It works seamlessly with the `Image Captioner`. New rule criteria include:
      - `captionfile_contains`: Sorts based on keywords found in the companion `.txt` caption file.
      - `filename_contains`: Sorts based on keywords in the file's name.
      - `metadata_contains`: Scans the image's embedded workflow metadata.
  - **`PromptCraft QnA`**: A conversational AI node that answers questions using text, images, PDFs, or even live web search results as context. It supports continuous conversations and can summarize large documents.
  - **`PromptCraft Cache Utility`**: A simple helper to clear the node pack's internal memory cache. Use this if a node isn't updating its output when you change an input.

-----

## ⚙️ Core Concepts

PromptCraft uses several advanced techniques to achieve high-quality results. Here’s a simple breakdown:

  - **Style Engine**: Instead of just using generic styles, the AI analyzes your reference images or text to create a unique artistic direction. It assigns an expert "persona" (like a *sci-fi world-builder* or *a fashion photographer*) and a dynamic "inspiration" (like *composition inspired by Akira Kurosawa*) to guide the prompt generation.
  - **"Deep Think" Refinement**: An optional process where the AI acts as its own editor. It writes a first draft of a prompt, then critiques and rewrites it based on your request and internal quality rules until a polished result is achieved.
  - **Coverage & Anti-Hallucination**: The AI double-checks its work to ensure the final prompt includes all the key subjects you asked for and removes any "hallucinated" details you didn't request.
  - **Style Customization**: While the dynamic Style Engine is powerful, you can always override it by selecting a style from the `style_override` dropdown or by adding your own custom personas to the `style_profiles.json` file.

-----

## 🚀 Installation

1.  Navigate to your `ComfyUI/custom_nodes/` directory.
2.  Clone this repository:
    ```bash
    git clone https://github.com/PyrateGFXProductions/ComfyUI-PromptCraft.git
    ```
3.  Install the required Python packages. Navigate to the new `ComfyUI-PromptCraft` directory and run:
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: This installs key libraries like `requests`, `langdetect`, and `python-dotenv`. For full functionality, it also includes optional dependencies like `duckduckgo-search` (web search), `pypdf` (PDFs), and `librosa`/`matplotlib` (audio analysis).)*
4.  Restart ComfyUI.

-----

## 🔧 Troubleshooting

If you encounter issues, here are some common solutions:

### Local Model (Ollama) Issues

  - **"Connection Error" or "Model not found"**: Make sure the Ollama application is running and that you have pulled the required model (e.g., `ollama pull llava`). The first time you use a model, it may take a moment to load into memory.

### General Issues

  - **Stale or Unexpected Results**: Use the `PromptCraft Cache Utility` node to clear the in-memory cache and force a node to re-run its logic from scratch.
  - **Errors After an Update**: Navigate to the `ComfyUI/custom_nodes/ComfyUI-PromptCraft` directory and run `git pull` to get the latest version, then restart ComfyUI.
  - **Check the Console**: Always check the terminal window where you launched ComfyUI for detailed error messages.