# Standard library imports
import os
import json
import textwrap

# Local module imports
from .. import pgfx_config as config
from ...utils import pgfx_utils as utils
from .. import pgfx_api_clients as api_clients

# --- Global Style Data Structures ---
STYLE_PROFILES = []
NAMED_STYLE_PROFILES = {}
STYLE_KEYWORDS = {}

def _load_style_profiles():
    """Loads style profiles from the JSON file."""
    global STYLE_PROFILES, NAMED_STYLE_PROFILES, STYLE_KEYWORDS
    style_file_path = os.path.join(os.path.dirname(__file__), '..', '..', 'style_profiles.json')
    try:
        with open(style_file_path, 'r', encoding='utf-8') as f:
            STYLE_PROFILES = json.load(f)
        
        NAMED_STYLE_PROFILES.clear()
        STYLE_KEYWORDS.clear()
        for profile in STYLE_PROFILES:
            name = profile.get("name")
            if name:
                NAMED_STYLE_PROFILES[name] = profile
                keywords = profile.get("keywords", [])
                if keywords and isinstance(keywords, list):
                    flat_keywords = [item for sublist in keywords for item in sublist]
                    STYLE_KEYWORDS[name] = ", ".join(flat_keywords)

    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"\033[93m[PromptCrafter] Warning: Could not load 'style_profiles.json'. Dynamic styles will be limited. Error: {e}\033[0m")
        STYLE_PROFILES = []
        NAMED_STYLE_PROFILES = {}
        STYLE_KEYWORDS = {}

def get_style_override_options(mode="Image"):
    """Returns a list of style override options for the UI dropdown."""
    options = ["None"]
    for profile in STYLE_PROFILES:
        if mode in profile.get("modes", ["Image", "Video", "Lyrics"]):
            options.append(f"({profile.get('type', 'Style')}) {profile.get('name', 'Unnamed Style')}")
    return sorted(options)

class StyleEngine:
    """A cohesive class to analyze content and generate stylistic guidance."""
    def __init__(self, model, use_chat_api, temperature, seed, image=None, text=None, mode="Image", debug_mode=False, timeout=60, **kwargs):
        self.model = model
        self.use_chat_api = use_chat_api
        self.temperature = temperature
        self.seed = seed
        self.image = image
        self.text = text
        self.mode = mode
        self.debug_mode = debug_mode
        self.timeout = timeout
        self._style_profile = None

    def _get_default_profile(self):
        """Returns a sensible default profile."""
        return {"persona": "You are an expert art historian.", "inspiration": "Composition inspired by Akira Kurosawa."}
    
    def _get_style_profile_options(self):
        """Get all available style profile options for dropdown menus."""
        return list(NAMED_STYLE_PROFILES.keys()) + ["None (Manual)", "Custom"]
    
    def get_keywords(self):
        """Returns a list of keywords for the style profile."""
        self.get_profile()
        if isinstance(self._style_profile, dict) and "name" in self._style_profile:
            return STYLE_KEYWORDS.get(self._style_profile["name"], "")
        return ""
    
    def get_keywords_str(self):
        """Returns a string of keywords for the style profile."""
        keywords = self.get_keywords()
        if isinstance(keywords, str) and len(keywords) > 0:
            return f" ({keywords})"
        return ""
    
    def get_profile_str(self):
        """Returns a string of the style profile."""
        self.get_profile()
        if isinstance(self._style_profile, dict) and "name" in self._style_profile:
            return self._style_profile.get("name", "Unknown Profile")
        return "Default Profile"
    
    def _select_profile_with_ai(self, prompt_text, images, profiles_to_select_from, **kwargs):
        """Queries the AI with a given prompt to select a style profile."""
        ok, result_json = api_clients._reason_with_model(
            self.model, prompt_text, images=images, use_chat_api=self.use_chat_api, 
            temperature=0.0, seed=self.seed, timeout=self.timeout, debug_mode=self.debug_mode, debug_title="StyleEngine Profile Selection"
        )
        if ok and isinstance(result_json, dict) and "best_profile_index" in result_json:
            try:
                chosen_index = int(result_json["best_profile_index"]) - 1
                if 0 <= chosen_index < len(profiles_to_select_from):
                    return profiles_to_select_from[chosen_index]
            except (ValueError, TypeError):
                pass
        return None
    
    def get_profile(self):
        """
        Orchestrates the analysis of content to determine the best style profile.
        This method handles caching and calls helper methods for the analysis steps.
        """
        if self._style_profile is not None: 
            return self._style_profile

        cache_key = utils._get_cache_key(self.model, self.use_chat_api, self.temperature, self.seed, self.image, self.text, self.timeout, "style_engine_analysis_v9", **self.__dict__)
        if config.CACHE.has(cache_key):
            self._style_profile = config.CACHE.get(cache_key)
            return self._style_profile

        chosen_profile = self._find_best_profile()
        
        self._style_profile = chosen_profile or self._get_default_profile()
        config.CACHE.set(cache_key, self._style_profile)
        return self._style_profile

    def _build_selection_prompt(self):
        """Constructs the prompt for style selection and returns it with the filtered profiles."""
        filtered_profiles = [p for p in STYLE_PROFILES if self.mode in p.get("modes", ["Image", "Video", "Lyrics"])]
        if not filtered_profiles:
            filtered_profiles = STYLE_PROFILES # Fallback to all if no profiles match the mode

        candidate_text = "".join(
            f"--- Profile {i+1} ---\n"
            f"Persona: {p.get('persona', 'N/A')}\n"
            f"Inspiration: {p.get('inspiration', 'N/A')}\n"
            f"Keywords: {p.get('keywords', [])}\n\n"
            for i, p in enumerate(filtered_profiles)
        )
        
        abstract_text_instruction = ""
        if self.text:
            abstract_text_instruction = textwrap.dedent("""
                **SPECIAL INSTRUCTIONS FOR TEXT ANALYSIS:**
                If the text appears to be abstract, poetic, or song lyrics, do NOT focus on the literal words. Instead, interpret the underlying **mood, emotion, and symbolism** to find the best-fitting creative profile. For example, for lyrics about loneliness, a profile related to 'vast, empty landscapes' or 'cool, desaturated colors' would be a good fit.
            """).strip()
        
        selection_prompt_template = textwrap.dedent("""
            You are an expert art director. Analyze the provided content (image and/or text) and select the most fitting creative profile from the list below.
            {abstract_text_instruction}
            --- CONTENT TO ANALYZE ---
{text_context}
--- AVAILABLE CREATIVE PROFILES ---
{candidates}--- END PROFILES ---
            INSTRUCTIONS: Respond with ONLY a JSON object containing the number of the best-fitting profile. Example: {{"best_profile_index": 1}}.
        """).strip()
        
        text_context_for_prompt = f"Text: {self.text[:1000]}" if self.text else "No text provided."
        
        return selection_prompt_template.format(
            abstract_text_instruction=abstract_text_instruction,
            text_context=text_context_for_prompt,
            candidates=candidate_text
        ), filtered_profiles

    def _find_best_profile(self):
        """Finds the best style profile by querying the AI model."""
        selection_prompt, filtered_profiles = self._build_selection_prompt()
        image_to_analyze = [self.image] if self.image is not None else None
        return self._select_profile_with_ai(selection_prompt, image_to_analyze, filtered_profiles)

    def get_persona(self):
        self.get_profile()
        if isinstance(self._style_profile, dict):
            return self._style_profile.get("persona", "You are a helpful assistant.")
        return "You are a helpful assistant."
    
    def get_composition_rules(self):
        self.get_profile()
        if isinstance(self._style_profile, dict):
            inspiration = self._style_profile.get("inspiration", "")
            return [f"- {inspiration}"] if inspiration else []
        return []
# Load profiles on module import
_load_style_profiles()
