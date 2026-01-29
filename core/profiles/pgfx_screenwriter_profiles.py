NAMED_SCREENWRITER_PROFILES = {
    "None (Manual Input)": {},
    "Default (High Accuracy)": {
        "whisper_model": "large-v3",
        "correction_model": "ollama/qwen3-vl:8b"
    },
    "Fast Draft (English Only)": {
        "whisper_model": "tiny.en",
        "correction_model": "disabled"
    },
    "Forced Script Alignment": {
        "whisper_model": "large-v3",
        "correction_model": "disabled"
    }
}

def get_profile_options():
    return list(NAMED_SCREENWRITER_PROFILES.keys())