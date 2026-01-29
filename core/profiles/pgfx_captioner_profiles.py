# Standard library imports
import os
import json

# --- Global Captioner Profile Data Structures ---
CAPTIONER_PROFILES = []
NAMED_CAPTIONER_PROFILES = {}

def _load_captioner_profiles():
    """Loads captioner profiles from the JSON file."""
    global CAPTIONER_PROFILES, NAMED_CAPTIONER_PROFILES
    profile_file_path = os.path.join(os.path.dirname(__file__), '..', 'captioner_profiles.json')
    try:
        with open(profile_file_path, 'r', encoding='utf-8') as f:
            CAPTIONER_PROFILES = json.load(f)
        
        NAMED_CAPTIONER_PROFILES.clear()
        for profile in CAPTIONER_PROFILES:
            name = profile.get("name")
            if name:
                NAMED_CAPTIONER_PROFILES[name] = profile

    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"\033[93m[PromptCrafter] Warning: Could not load 'captioner_profiles.json'. Pre-configured captioning prompts will not be available. Error: {e}\033[0m")
        CAPTIONER_PROFILES = []
        NAMED_CAPTIONER_PROFILES = {}

def get_captioner_profile_options():
    """Returns a list of captioner profile options for the UI dropdown."""
    options = ["None (Manual Prompt)"]
    options.extend([p.get("name", "Unnamed Profile") for p in CAPTIONER_PROFILES])
    return options