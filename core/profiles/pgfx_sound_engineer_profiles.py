NAMED_SOUND_ENGINEER_PROFILES = {
    "None (Manual Input)": {},
    "Default (4s Scenes, VAD)": {
        "segment_duration": 4.0,
        "enable_vad": True,
        "vad_threshold": 0.5,
        "enable_emotion_detection": True,
    },
    "Fast Paced (2s Scenes)": {
        "segment_duration": 2.0,
        "enable_vad": True,
        "vad_threshold": 0.5,
        "enable_emotion_detection": True,
    },
    "Dialogue/Podcast (VAD Focus)": {
        "segment_duration": 8.0,
        "enable_vad": True,
        "vad_threshold": 0.3,
        "enable_emotion_detection": False,
    },
    "Music Only (No VAD/Emotion)": {
        "segment_duration": 4.0,
        "enable_vad": False,
        "vad_threshold": 0.5,
        "enable_emotion_detection": False,
    }
}

def get_profile_options():
    return list(NAMED_SOUND_ENGINEER_PROFILES.keys())