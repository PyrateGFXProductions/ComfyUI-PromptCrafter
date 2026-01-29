NAMED_DIRECTOR_PROFILES = {
    "None (Manual Input)": {},
    "David Fincher (Tension & Desaturation)": {
        "character_description": "A flawed but determined protagonist, often isolated and obsessive. Their expressions are subtle, conveying internal turmoil.",
        "visual_styles": [
            "Style_A: A moody, desaturated, and cinematic film noir style with deep shadows and a palette of cold blues, sickly greens, and urban grays. High contrast and dramatic, low-key lighting.",
            "Style_B: A tense, psychological thriller aesthetic with sterile, oppressive environments. Uses precise, controlled camera movements and a sense of voyeuristic observation."
        ]
    },
    "Wes Anderson (Symmetry & Whimsy)": {
        "character_description": "An eccentric, quirky character with a deadpan expression, often centered in the frame. They wear meticulously chosen, often vintage-inspired, and color-coordinated outfits.",
        "visual_styles": [
            "Style_A: A whimsical, symmetrical, and meticulously crafted diorama look. Uses a pastel color palette (e.g., millennial pink, baby blue, mint green) and flat, frontal compositions.",
            "Style_B: A nostalgic, retro-futuristic style with a warm, vintage film feel. Features detailed, often handmade-looking props and sets with a storybook quality."
        ]
    },
    "Greta Gerwig (Warm & Authentic)": {
        "character_description": "A relatable, often awkward but endearing character navigating personal growth. Their expressions are genuine, capturing moments of vulnerability and joy.",
        "visual_styles": [
            "Style_A: A warm, authentic, and naturalistic style with a sun-drenched, golden-hour glow. Uses handheld camera movements to create a sense of intimacy and realism.",
            "Style_B: A vibrant, nostalgic, and slightly chaotic style reminiscent of home videos. Features a rich, saturated color palette and a focus on genuine, unpolished human interaction."
        ]
    },
    "Denis Villeneuve (Atmospheric & Monumental)": {
        "character_description": "A solitary figure, often dwarfed by their environment, conveying a sense of awe or dread. Their face is often partially obscured by shadow or weather elements.",
        "visual_styles": [
            "Style_A: An atmospheric, brutalist, and monumental sci-fi style. Features vast, imposing structures, a muted and monochromatic color palette, and a sense of grand, oppressive scale.",
            "Style_B: A tense, hazy, and suspenseful style with a tangible atmosphere (e.g., fog, dust, smoke). Uses slow, deliberate camera movements and a palette of ochre, gray, and muted earth tones."
        ]
    }
}

def _load_director_profiles():
    """
    This function can be expanded to load profiles from external JSON files
    in the future, allowing for user-created director profiles without editing code.
    For now, it simply ensures the NAMED_DIRECTOR_PROFILES dictionary is available.
    """
    global NAMED_DIRECTOR_PROFILES
    if not NAMED_DIRECTOR_PROFILES:
        # In case of a reload issue, define a fallback
        NAMED_DIRECTOR_PROFILES = {"None (Manual Input)": {}}
    return True

def get_director_profile_options():
    """Returns a list of director profile names for use in dropdown menus."""
    _load_director_profiles()
    return list(NAMED_DIRECTOR_PROFILES.keys())