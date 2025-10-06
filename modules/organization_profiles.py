# Standard library imports
import os
import json

# --- Global Organization Profile Data Structures ---
ORGANIZATION_PROFILES = []
NAMED_ORGANIZATION_PROFILES = {}

def _load_organization_profiles():
    """Loads organization profiles from the JSON file."""
    global ORGANIZATION_PROFILES, NAMED_ORGANIZATION_PROFILES
    profile_file_path = os.path.join(os.path.dirname(__file__), '..', 'organization_profiles.json')
    try:
        with open(profile_file_path, 'r', encoding='utf-8') as f:
            ORGANIZATION_PROFILES = json.load(f)
        
        NAMED_ORGANIZATION_PROFILES.clear()
        for profile in ORGANIZATION_PROFILES:
            name = profile.get("name")
            if name:
                NAMED_ORGANIZATION_PROFILES[name] = profile

    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"\033[93m[PromptCrafter] Warning: Could not load 'organization_profiles.json'. Pre-configured schemes will not be available. Error: {e}\033[0m")
        ORGANIZATION_PROFILES = []
        NAMED_ORGANIZATION_PROFILES = {}

def get_organization_profile_options():
    """Returns a list of organization profile options for the UI dropdown."""
    options = ["None (Manual Scheme)"]
    options.extend([p.get("name", "Unnamed Profile") for p in ORGANIZATION_PROFILES])
    return options