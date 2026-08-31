import base64
import io
import json
import os
import re
import textwrap
import threading
import time

import numpy as np
import torch
from PIL import Image

try:
    import requests
except ImportError:
    requests = None

from ..core import pgfx_api_clients as api_clients
from ..core import pgfx_config as config
from ..core.pgfx_base_creator import PromptCrafter_BaseCreator
from ..utils import pgfx_json_utils as json_utils

try:
    from . import pgfx_font_manager
except Exception as e:
    print(f"[PGFX Logo Studio] Could not load font manager: {e}")

try:
    from comfy_api.latest import io as v3_io
    V3_IO_AVAILABLE = True
except ImportError:
    V3_IO_AVAILABLE = False

# ------------------------------------------------------------------------------------
# Helper function to read node descriptions from HELP.md
# ------------------------------------------------------------------------------------
def get_node_description(node_name):
    """Parses HELP.md and extracts the description for a given node class name."""
    try:
        help_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "HELP.md")
        if not os.path.exists(help_path):
            return f"Help file not found for {node_name}."

        with open(help_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Match either ## `NodeName` or ## `NodeName` (Alternate Name)
        pattern = re.compile(rf"##\s*`({node_name})(?:`|\s*\(.*?\)`)\n(.*?)(?=\n##\s*`|\Z)", re.DOTALL)
        match = pattern.search(content)

        if match:
            return match.group(2).strip()
        return f"No description found in HELP.md for {node_name}."
    except Exception as e:
        return f"Error reading help file: {e}"


DEFAULT_LIBRARY = {
    "materials": {
        "default": {"description": "clean professional surface", "usage_count": 0},
        "leather": {"description": "rich premium leather grain", "usage_count": 0},
        "polished_gold": {"description": "highly reflective 24k polished gold", "usage_count": 0},
        "weathered_wood": {"description": "textured weathered oak wood with visible grain", "usage_count": 0},
        "ancient_stone": {"description": "chipped ancient mossy stone texture", "usage_count": 0},
        "brushed_steel": {"description": "industrial cold brushed stainless steel", "usage_count": 0},
        "frosted_glass": {"description": "translucent frosted glass with internal refraction", "usage_count": 0},
        "obsidian": {"description": "smooth black volcanic obsidian glass", "usage_count": 0},
        "illustrative_ink": {"description": "bold vibrant illustrative tattoo ink pigments", "usage_count": 0},
        "iridescent_pearl": {"description": "shimmering iridescent pearlescent finish", "usage_count": 0},
        "carbon_fiber": {"description": "modern black woven carbon fiber weave", "usage_count": 0},
        "liquid_chrome": {"description": "molten liquid silver chrome", "usage_count": 0},
        "rusty_iron": {"description": "corroded rusty oxidized iron", "usage_count": 0},
        "neon_gas": {"description": "glowing neon gas-filled glass tubes", "usage_count": 0},
        "matte_plastic": {"description": "minimalist clean matte plastic", "usage_count": 0},
        "marble_white": {"description": "luxurious white carrara marble with grey veins", "usage_count": 0},
        "lava_rock": {"description": "glowing molten lava rock with internal heat", "usage_count": 0},
        "ivory_bone": {"description": "smooth aged ivory bone texture", "usage_count": 0},
        "denim_fabric": {"description": "thick blue woven denim fabric texture", "usage_count": 0},
        "velvet_red": {"description": "soft rich crimson red royal velvet", "usage_count": 0},
        "holographic": {"description": "futuristic shimmering holographic foil", "usage_count": 0},
        "ice": {"description": "clear frozen ice with frosted edges", "usage_count": 0},
        "neon": {"description": "bright illuminated neon tubing", "usage_count": 0},
        "crystal": {"description": "cut translucent crystal facets", "usage_count": 0},
        "concrete": {"description": "cast concrete with gritty texture", "usage_count": 0},
        "enamel_painted": {"description": "glossy vitreous enamel coating with mirror-hard finish", "usage_count": 0},
        "jade": {"description": "polished translucent green jadeite with soft inner glow", "usage_count": 0},
        "oxidized_copper": {"description": "verdigris patina on weathered aged copper", "usage_count": 0},
        "hammered_brass": {"description": "wrought brass with visible hand-hammered indentations", "usage_count": 0},
        "porcelain": {"description": "fine translucent white ceramic with delicate glossy sheen", "usage_count": 0},
        "titanium_anodized": {"description": "gradient color-shifting anodized titanium surface", "usage_count": 0},
        "cashmere": {"description": "soft brushed luxury wool textile with gentle surface nap", "usage_count": 0},
        "crocodile_embossed": {"description": "exotic reptile leather with raised scaled texture", "usage_count": 0},
        "moonstone": {"description": "opalescent feldspar with floating blue adularescence", "usage_count": 0},
        "lacquer_red": {"description": "deep crimson urushi lacquer with piano-gloss reflection", "usage_count": 0},
        "stained_glass": {"description": "translucent colored glass panels with lead came framework", "usage_count": 0},
        "malachite": {"description": "banded bright green carbonate mineral with concentric rings", "usage_count": 0},
        "damascus_steel": {"description": "pattern welded steel with wavy layered grain structure", "usage_count": 0},
        "charred_wood": {"description": "yakisugi burnt cedar with crackled black textured surface", "usage_count": 0},
        "plaster_fresco": {"description": "aged lime plaster with mineral pigment embedded in substrate", "usage_count": 0},
    },
    "decorations": {
        "none": {"description": "", "usage_count": 0},
        "ornate_engraving": {"description": "ornate engraved detailing carved into the surface", "usage_count": 0},
        "glowing_edges": {"description": "a subtle luminous edge glow around major forms", "usage_count": 0},
        "overgrown_vines": {"description": "entwined with lush overgrown green vines", "usage_count": 0},
        "cracked_porcelain": {"description": "intricate fine porcelain cracks", "usage_count": 0},
        "gold_leaf": {"description": "flecked with 24k gold leaf gilding", "usage_count": 0},
        "bullet_holes": {"description": "riddled with cinematic bullet holes and impact marks", "usage_count": 0},
        "etched_runes": {"description": "covered in glowing ancient etched runes", "usage_count": 0},
        "dripping_slime": {"description": "dripping with thick viscous neon slime", "usage_count": 0},
        "electric_arcs": {"description": "surrounded by crackling electric arcs", "usage_count": 0},
        "barbed_wire": {"description": "wrapped in sharp rusty barbed wire", "usage_count": 0},
        "floral_accents": {"description": "decorated with vibrant blooming flowers", "usage_count": 0},
        "rivets_bolts": {"description": "reinforced with heavy industrial rivets and bolts", "usage_count": 0},
        "blood_splatter": {"description": "stained with dark dramatic blood splatters", "usage_count": 0},
        "ink_splats": {"description": "decorated with artistic messy ink splats", "usage_count": 0},
        "glowing_circuitry": {"description": "interwoven with glowing cyberpunk circuitry", "usage_count": 0},
        "filigree_silver": {"description": "ornate delicate silver filigree work", "usage_count": 0},
        "tattoo_style": {"description": "ornamental tattoo flourishes and flash-art accents", "usage_count": 0},
        "celtic_knotwork": {"description": "interwoven decorative celtic knot patterns across the surface", "usage_count": 0},
        "mandala_pattern": {"description": "intricate radial geometric mandala ornamentation", "usage_count": 0},
        "henna_tattoo": {"description": "delicate mehndi-style organic flowing pattern work", "usage_count": 0},
        "watercolor_wash": {"description": "soft diffused transparent watercolor paint splashes", "usage_count": 0},
        "gilded_accents": {"description": "raised decorative details highlighted with burnished gold leaf", "usage_count": 0},
        "embossed_pattern": {"description": "raised relief repeating texture pressed into the surface", "usage_count": 0},
        "origami_folds": {"description": "precise geometric folded paper crease patterns", "usage_count": 0},
        "enamel_cloisonne": {"description": "vibrant colored enamel cells separated by fine wire partitions", "usage_count": 0},
        "scrollwork": {"description": "ornate flowing ornamental scroll and vine motifs", "usage_count": 0},
        "mosaic_tiles": {"description": "small colored glass tile tessellation in geometric patterns", "usage_count": 0},
        "feathered_edges": {"description": "soft organic feather-like transitional border treatment", "usage_count": 0},
        "lace_overlay": {"description": "delicate intricate lace textile pattern draped over the surface", "usage_count": 0},
    },
    "actions": {
        "none": {"description": "static design pose", "usage_count": 0},
        "melting": {"description": "melting and liquefying from heat", "usage_count": 0},
        "exploding": {"description": "shattering and exploding into debris", "usage_count": 0},
        "burning": {"description": "engulfed in realistic cinematic flames", "usage_count": 0},
        "frozen": {"description": "encased in thick transparent ice", "usage_count": 0},
        "dissolving": {"description": "dissolving and crumbling into fine dust", "usage_count": 0},
        "floating": {"description": "defying gravity in a zero-G float", "usage_count": 0},
        "shattering": {"description": "broken into sharp glass-like shards", "usage_count": 0},
        "warped": {"description": "distorted and warped by force", "usage_count": 0},
        "glitching": {"description": "corrupted by digital glitch artifacts", "usage_count": 0},
        "cracked": {"description": "fractured with visible structural cracking", "usage_count": 0},
        "corroded": {"description": "eroded by corrosion and oxidation", "usage_count": 0},
        "petrifying": {"description": "slowly turning to stone from the base upward", "usage_count": 0},
        "crystallizing": {"description": "sprouting sharp geometric crystal growths across the surface", "usage_count": 0},
        "rusting": {"description": "rapid oxidation corrosion spreading like a stain", "usage_count": 0},
        "fossilizing": {"description": "being compressed and preserved as a sedimentary fossil", "usage_count": 0},
        "fracturing": {"description": "cracking in radial spiderweb fracture patterns", "usage_count": 0},
        "blooming": {"description": "flowers and organic vegetation sprouting from the surface", "usage_count": 0},
        "sublimating": {"description": "transitioning directly from solid into ethereal vapor", "usage_count": 0},
        "unraveling": {"description": "woven threads pulling loose and coming apart at the edges", "usage_count": 0},
        "imploding": {"description": "collapsing inward with violent radial compression", "usage_count": 0},
        "pixelating": {"description": "breaking apart into blocky digital pixel fragments", "usage_count": 0},
        "regrowing": {"description": "self-repairing with organic fibrous regrowth across damaged areas", "usage_count": 0},
        "tarnishing": {"description": "developing dark oxidation patina spreading across the surface", "usage_count": 0},
    },
    "environments": {
        "none": {"description": "a clean studio environment", "usage_count": 0},
        "underwater_deep": {"description": "deep underwater ocean darkness with drifting particulate", "usage_count": 0},
        "underwater_corals": {"description": "a vibrant coral reef background with marine life", "usage_count": 0},
        "space_nebula": {"description": "a colorful cosmic nebula with deep-space atmosphere", "usage_count": 0},
        "space_stars_field": {"description": "an endless star field in open space", "usage_count": 0},
        "city_night_neon": {"description": "a rainy neon-lit city street at night", "usage_count": 0},
        "city_day_busy": {"description": "a busy city scene in broad daylight", "usage_count": 0},
        "forest_mystical": {"description": "a mystical forest with mist and fireflies", "usage_count": 0},
        "forest_autumn": {"description": "an autumn forest with drifting leaves", "usage_count": 0},
        "desert_sandstorm": {"description": "a desert blasted by wind and sand", "usage_count": 0},
        "ice_cave": {"description": "inside a luminous frozen ice cave", "usage_count": 0},
        "lava_cave": {"description": "inside a volcanic cave with molten lava glow", "usage_count": 0},
        "abstract_vortex": {"description": "a swirling abstract vortex of color and motion", "usage_count": 0},
        "grid_cyberpunk": {"description": "a cyberpunk digital grid landscape", "usage_count": 0},
        "old_paper": {"description": "aged vintage paper texture with wear and stains", "usage_count": 0},
        "concrete_wall": {"description": "a gritty urban concrete wall backdrop", "usage_count": 0},
        "white_studio": {"description": "a pure white professional studio backdrop", "usage_count": 0},
        "black_void": {"description": "an infinite black cinematic void", "usage_count": 0},
        "steampunk_workshop": {"description": "a victorian brass and copper machinery workshop with steam vents", "usage_count": 0},
        "bioluminescent_cave": {"description": "an underground cavern lit by glowing bio-luminescent organisms", "usage_count": 0},
        "cherry_blossom_garden": {"description": "a serene japanese garden with drifting pink petals", "usage_count": 0},
        "crystal_cavern": {"description": "a vast underground chamber of towering geometric crystal formations", "usage_count": 0},
        "sunset_beach": {"description": "a golden hour beach landscape with gentle rolling waves", "usage_count": 0},
        "cathedral_interior": {"description": "a grand gothic cathedral with light streaming through stained glass", "usage_count": 0},
        "neon_casino": {"description": "a vibrant vegas-style casino exterior with cascading neon signs", "usage_count": 0},
        "greenhouse_jungle": {"description": "a lush overgrown glass botanical greenhouse with tropical foliage", "usage_count": 0},
        "underwater_ruins": {"description": "sunken ancient architecture draped in coral and drifting sea life", "usage_count": 0},
        "desert_night": {"description": "a clear moonlit desert with expansive star-filled night sky", "usage_count": 0},
        "zen_garden": {"description": "a raked sand meditation garden with carefully placed stones", "usage_count": 0},
        "carnival_midway": {"description": "a colorful nighttime carnival with bright amusement ride lights", "usage_count": 0},
        "temple_ruins": {"description": "ancient overgrown temple ruins being reclaimed by jungle", "usage_count": 0},
        "ballroom_elegant": {"description": "a grand chandelier-lit ballroom with gold trim and mirrored walls", "usage_count": 0},
        "alleyway_rain": {"description": "a narrow wet urban alleyway reflecting neon at night", "usage_count": 0},
    },
    "atmospherics": {
        "none": {"description": "", "usage_count": 0},
        "particles": {"description": "subtle floating particles", "usage_count": 0},
        "sparks": {"description": "small metallic sparks", "usage_count": 0},
        "fire_sparks": {"description": "embers and fire sparks", "usage_count": 0},
        "lightning": {"description": "electric lightning arcs", "usage_count": 0},
        "snow": {"description": "falling snow", "usage_count": 0},
        "rain": {"description": "rain streaks and droplets", "usage_count": 0},
        "confetti": {"description": "celebratory confetti", "usage_count": 0},
        "bubbles_env": {"description": "floating bubbles", "usage_count": 0},
        "smoke": {"description": "rolling smoke", "usage_count": 0},
        "fog": {"description": "soft atmospheric fog", "usage_count": 0},
        "dust": {"description": "dust in the air", "usage_count": 0},
        "haze": {"description": "a diffuse haze", "usage_count": 0},
        "glow": {"description": "an ambient luminous glow", "usage_count": 0},
        "neon_lights": {"description": "neon light spill and reflections", "usage_count": 0},
        "spotlight": {"description": "a focused spotlight beam", "usage_count": 0},
        "volumetric_lighting": {"description": "volumetric light shafts", "usage_count": 0},
        "underwater": {"description": "underwater caustics and suspended particulate", "usage_count": 0},
        "space_stars": {"description": "small surrounding stars", "usage_count": 0},
        "galaxy": {"description": "galactic atmospheric color", "usage_count": 0},
        "abstract_shapes": {"description": "abstract surrounding graphic shapes", "usage_count": 0},
        "matrix_code": {"description": "falling digital code patterns", "usage_count": 0},
        "fireflies": {"description": "glowing bioluminescent floating insects drifting gently", "usage_count": 0},
        "embers": {"description": "rising glowing embers and warm floating ash particles", "usage_count": 0},
        "petals": {"description": "delicate flower petals drifting and swirling on a breeze", "usage_count": 0},
        "fireworks": {"description": "distant colorful exploding firework bursts", "usage_count": 0},
        "aurora_borealis": {"description": "flowing curtains of colored atmospheric polar light", "usage_count": 0},
        "rippling_water": {"description": "gentle water surface caustics and ripple light reflections", "usage_count": 0},
        "holographic_projections": {"description": "flickering translucent holographic data display artifacts", "usage_count": 0},
        "stardust": {"description": "fine sparkling cosmic particle trails suspended in air", "usage_count": 0},
        "cobwebs": {"description": "delicate hanging spider silk strands catching the light", "usage_count": 0},
        "rainbow_prism": {"description": "spectral light refraction casting rainbow color dispersion", "usage_count": 0},
    },
    "styles": {
        "flat_vector": {"description": "professional clean flat vector illustration", "usage_count": 0},
        "creative": {"description": "cinematic professional creative direction", "usage_count": 0},
        "realistic": {"description": "ultra-realistic photorealistic rendering", "usage_count": 0},
        "3d_render": {"description": "physically based 3D render depth and lighting", "usage_count": 0},
        "tattoo_art": {"description": "bold illustrative tattoo artistry with dark linework", "usage_count": 0},
        "sticker_decal": {"description": "clean die-cut sticker with a white border", "usage_count": 0},
        "watercolor": {"description": "soft diffuse watercolor painting with paper grain texture", "usage_count": 0},
        "oil_painting": {"description": "thick impasto oil painting with visible directional brushstrokes", "usage_count": 0},
        "pop_art": {"description": "bold comic-book style with halftone dots and saturated color", "usage_count": 0},
        "art_deco": {"description": "luxurious geometric 1920s art deco with gold and chrome accents", "usage_count": 0},
        "minimal_modern": {"description": "clean sparse scandinavian minimalism with generous negative space", "usage_count": 0},
        "woodcut": {"description": "bold carved woodblock print with thick outlines and textured ink", "usage_count": 0},
        "pixel_art": {"description": "retro 8-bit video game pixel grid rendering", "usage_count": 0},
        "japanese_woodblock": {"description": "traditional ukiyo-e style with flat color fields and flowing linework", "usage_count": 0},
        "graffiti": {"description": "urban street art style with spray paint overspray and marker textures", "usage_count": 0},
        "baroque": {"description": "dramatic 17th century ornate style with deep chiaroscuro shadow", "usage_count": 0},
    },
    "design_presets": {},
}

CATEGORY_ALIASES = {
    "backgrounds": "environments",
    "effects": "atmospherics",
    "environment_effects": "atmospherics",
    "environments_effects": "atmospherics",
}

LIBRARY_ALIASES = {
    "materials": {
        "gold": "polished_gold",
        "metal": "brushed_steel",
        "steel": "brushed_steel",
        "wood": "weathered_wood",
        "stone": "ancient_stone",
        "marble": "marble_white",
        "bone": "ivory_bone",
        "denim": "denim_fabric",
        "velvet": "velvet_red",
        "chrome": "liquid_chrome",
        "plastic": "matte_plastic",
    },
    "decorations": {
        "ornate_engraving": "ornate_engraving",
        "glowing_edges": "glowing_edges",
        "electric_shock": "electric_arcs",
        "ink_drips": "ink_splats",
        "floral": "floral_accents",
    },
    "actions": {
        "explode": "exploding",
        "freeze": "frozen",
        "glitch": "glitching",
    },
    "environments": {
        "cyberpunk_city": "city_night_neon",
        "deep_ocean": "underwater_deep",
        "outer_space": "space_nebula",
        "industrial_factory": "concrete_wall",
        "volcanic_cave": "lava_cave",
        "ancient_temple": "old_paper",
        "desert_dunes": "desert_sandstorm",
        "arctic_tundra": "ice_cave",
    },
    "styles": {
        "vector": "flat_vector",
        "vector_logo": "flat_vector",
        "photo": "realistic",
        "photoreal": "realistic",
        "tattoo": "tattoo_art",
        "decal": "sticker_decal",
    },
}

STANDARD_NEGATIVES = [
    "no extra text",
    "no misspellings",
    "no substituted letters",
    "no additional symbols unless present in the source design",
    "no humans",
    "no skin",
    "no body parts",
    "no unrelated objects",
]


def _normalize_key(value):
    val = str(value or "").strip().lower()
    if val in ("null", "none"):
        return ""
    return re.sub(r"[^a-z0-9_]+", "_", val).strip("_")


def _normalize_text(value):
    text = str(value or "").replace("\r", "")
    if text.strip().lower() in ("null", "none"):
        return ""
    return re.sub(r"[ \t]+", " ", text).strip()


def _safe_float(value, default):
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value, default):
    try:
        return int(value)
    except Exception:
        return default


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _humanize_key(key):
    return str(key or "").replace("_", " ").strip()


def _entry_description(entry, fallback):
    if isinstance(entry, dict):
        desc = _normalize_text(entry.get("description", ""))
        if desc:
            return desc
    return _humanize_key(fallback)


def _dedupe_preserve(items):
    seen = set()
    out = []
    for item in items:
        value = str(item or "").strip()
        if not value:
            continue
        token = value.lower()
        if token in seen:
            continue
        seen.add(token)
        out.append(value)
    return out


def _coalesce_non_empty(*values):
    for value in values:
        if str(value or "").strip():
            return value
    return ""


def _list_phrase(items):
    cleaned = [str(i).strip() for i in items if str(i).strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    if len(cleaned) == 2:
        return f"{cleaned[0]} and {cleaned[1]}"
    return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"


def _extract_quoted_phrases(text):
    return _dedupe_preserve(re.findall(r"['\"]([^'\"]+)['\"]", str(text or "")))


def _extract_visible_text_hint(text):
    source = str(text or "")
    for pattern in (
        r"(?:text|wording|words|letters|logo)\s*(?:reads|reading|says|saying|is|are)?\s*['\"]([^'\"]+)['\"]",
        r"(?:spells?|spell out)\s*['\"]([^'\"]+)['\"]",
        r"(?:the word|the words)\s*['\"]([^'\"]+)['\"]",
    ):
        matches = re.findall(pattern, source, flags=re.IGNORECASE)
        if matches:
            return "\n".join(_dedupe_preserve(matches))
    quoted = _extract_quoted_phrases(source)
    if quoted:
        return "\n".join(quoted)
    return ""


def _extract_text_from_image_context(text):
    if not text:
        return ""
    hints = []
    for pattern in (
        r"(?:text|wording|letters?)\s*(?:that reads|reading|reads|says|showing)?\s*['\"]([^'\"]+)['\"]",
        r"(?:the words?|the text)\s+([A-Z0-9][A-Z0-9 \-]{1,80})",
    ):
        hints.extend(re.findall(pattern, str(text), flags=re.IGNORECASE))
    return "\n".join(_dedupe_preserve(hints))


def _relative_position(left, top, width, height):
    x = _safe_float(left, width / 2 if width else 512)
    y = _safe_float(top, height / 2 if height else 512)
    width = max(1.0, _safe_float(width, 1024.0))
    height = max(1.0, _safe_float(height, 1024.0))

    if x < width * 0.33:
        horizontal = "left"
    elif x > width * 0.67:
        horizontal = "right"
    else:
        horizontal = "center"

    if y < height * 0.33:
        vertical = "top"
    elif y > height * 0.67:
        vertical = "bottom"
    else:
        vertical = "middle"

    if horizontal == "center" and vertical == "middle":
        return "center"
    if horizontal == "center":
        return f"{vertical}-center"
    if vertical == "middle":
        return f"mid-{horizontal}"
    return f"{vertical}-{horizontal}"


def _shape_name(obj):
    obj_type = str(obj.get("type", "object"))
    if obj_type == "polygon":
        points = obj.get("points") or []
        count = len(points)
        if count == 6:
            return "hexagon"
        if count == 10:
            return "star"
        if count == 3:
            return "triangle"
        return "polygon"
    if obj_type == "group":
        return "imported vector group"
    if obj_type == "image":
        return "image reference"
    if obj_type == "path":
        return "drawn path"
    return obj_type.replace("-", " ")


def _summarize_canvas_json(canvas_json_text):
    summary = {
        "text": "",
        "background_color": "",
        "layout_summary": "",
        "object_count": 0,
        "has_geometry": False,
    }

    raw = str(canvas_json_text or "").strip()
    if not raw:
        return summary

    data = None
    try:
        data = json.loads(raw)
    except Exception:
        data = json_utils.extract_and_parse_json(raw)

    if not isinstance(data, dict):
        regex_texts = re.findall(r'"text"\s*:\s*"([^"]+)"', raw)
        if regex_texts:
            summary["text"] = "\n".join(_dedupe_preserve(t.replace("\\n", "\n") for t in regex_texts))
        return summary

    width = _safe_float(data.get("pgfx_canvas_width") or data.get("width"), 1024.0)
    height = _safe_float(data.get("pgfx_canvas_height") or data.get("height"), 1024.0)
    summary["background_color"] = _normalize_text(
        data.get("backgroundColor") or data.get("background") or data.get("background_color") or ""
    )

    objects = data.get("objects") if isinstance(data.get("objects"), list) else []
    summary["object_count"] = len(objects)
    summary["has_geometry"] = bool(objects)

    text_fragments = []
    layout_bits = []

    for obj in objects[:12]:
        if not isinstance(obj, dict):
            continue
        obj_type = str(obj.get("type", "object"))
        obj_name = _normalize_text(obj.get("name", ""))
        position = _relative_position(obj.get("left"), obj.get("top"), width, height)

        if obj_type in {"i-text", "text", "textbox"}:
            text_value = str(obj.get("text", "")).replace("\\n", "\n").strip()
            if text_value:
                text_fragments.append(text_value)
            font_family = _normalize_text(obj.get("fontFamily", ""))
            font_size = _safe_int(obj.get("fontSize"), 0)
            font_weight = _normalize_text(obj.get("fontWeight", ""))
            
            label = f'text "{text_value}"' if text_value else "text layer"
            if obj_name:
                label = f'"{obj_name}" ({label})'

            parts = [label, f"at {position}"]
            if font_family:
                parts.append(f"font {font_family}")
            if font_size > 0:
                parts.append(f"approx {font_size}px")
            if font_weight and font_weight not in {"normal", "400"}:
                parts.append(font_weight)
            layout_bits.append(", ".join(parts))
            continue

        shape = _shape_name(obj)
        label = f'"{obj_name}" ({shape})' if obj_name else shape
        shape_bits = [label, f"at {position}"]
        
        fill = obj.get("fill")
        if isinstance(fill, dict) and fill.get("type"):
            shape_bits.append(f"{fill.get('type')} gradient fill")
        else:
            fill_str = _normalize_text(fill or "")
            if fill_str and fill_str not in {"", "transparent"}:
                shape_bits.append(f"fill {fill_str}")
        
        if obj.get("shadow"):
            shape_bits.append("has drop shadow")

        layout_bits.append(", ".join(shape_bits))

    summary["text"] = "\n".join(_dedupe_preserve(text_fragments))
    if layout_bits:
        summary["layout_summary"] = "Source layout includes " + "; ".join(layout_bits[:8]) + "."

    # Check for Elite Agent Focus
    agent_focus = data.get("agent_focus")
    if isinstance(agent_focus, dict):
        focus_layer = agent_focus.get("target_layer")
        focus_props = agent_focus.get("properties")
        if focus_layer and focus_props:
            summary["layout_summary"] += f'\nCRITICAL AGENT FOCUS: User is currently refining the layer "{focus_layer}". Details: {focus_props}'

    # Check for 3D extrusion settings from viewport
    pgfx_3d = data.get("pgfx_3d_settings")
    if isinstance(pgfx_3d, dict):
        summary["has_3d_extrusion"] = True
        summary["extrusion_depth"] = _safe_int(pgfx_3d.get("depth"), 20)
        summary["extrusion_material"] = _normalize_key(pgfx_3d.get("material", ""))
        summary["extrusion_bevel"] = bool(pgfx_3d.get("bevel_enabled", True))
    else:
        summary["has_3d_extrusion"] = False

    return summary


def _build_keyword_map(category_data):
    keyword_map = {}
    for key, entry in category_data.items():
        phrase = _humanize_key(key)
        keyword_map[phrase] = key
        description = _entry_description(entry, key)
        keyword_map[description.lower()] = key
    return keyword_map


def _guess_choice_from_text(category, text_blob, choices, default):
    if not text_blob:
        return default

    blob = " " + re.sub(r"[^a-z0-9]+", " ", str(text_blob).lower()) + " "
    aliases = LIBRARY_ALIASES.get(category, {})

    for alias, canonical in aliases.items():
        phrase = re.sub(r"[^a-z0-9]+", " ", alias.replace("_", " ").lower()).strip()
        if canonical in choices and f" {phrase} " in blob:
            return canonical

    for key in choices:
        if key == "none":
            continue
        phrase = re.sub(r"[^a-z0-9]+", " ", key.replace("_", " ").lower()).strip()
        if f" {phrase} " in blob:
            return key

    if category == "styles":
        if "tattoo" in blob and "tattoo_art" in choices:
            return "tattoo_art"
        if "flat vector" in blob and "flat_vector" in choices:
            return "flat_vector"
        if "vector" in blob and "flat_vector" in choices:
            return "flat_vector"
        if "3d" in blob and "3d_render" in choices:
            return "3d_render"
        if ("realistic" in blob or "photoreal" in blob) and "realistic" in choices:
            return "realistic"

    return default


def _normalize_negatives(value):
    if isinstance(value, list):
        return _dedupe_preserve(_normalize_text(v) for v in value)
    if isinstance(value, str):
        chunks = re.split(r"[,;\n]+", value)
        return _dedupe_preserve(_normalize_text(chunk) for chunk in chunks)
    return []


def _format_library_for_prompt(library):
    payload = {
        "materials": sorted(library.get("materials", {}).keys()),
        "decorations": sorted(library.get("decorations", {}).keys()),
        "actions": sorted(library.get("actions", {}).keys()),
        "background_presets": sorted(library.get("environments", {}).keys()),
        "atmospherics": sorted(library.get("atmospherics", {}).keys()),
        "styles": sorted(library.get("styles", {}).keys()),
    }
    return json.dumps(payload, indent=2)


class DesignLibrary:
    _lock = threading.RLock()
    _path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "core", "design_library.json")
    _data = None

    @classmethod
    def _canonical_category(cls, category):
        key = _normalize_key(category)
        return CATEGORY_ALIASES.get(key, key)

    @classmethod
    def _copy_defaults(cls):
        return json.loads(json.dumps(DEFAULT_LIBRARY))

    @classmethod
    def _normalize_entry(cls, key, value):
        norm_key = _normalize_key(key)
        if not norm_key:
            return None, None
        if isinstance(value, dict):
            normalized = dict(value)
            normalized["description"] = _entry_description(value, norm_key)
            normalized["usage_count"] = max(0, _safe_int(value.get("usage_count", 0), 0))
            return norm_key, normalized
        return norm_key, {"description": _humanize_key(norm_key), "usage_count": 0}

    @classmethod
    def _merge_with_defaults(cls, data):
        merged = cls._copy_defaults()
        if not isinstance(data, dict):
            return merged, True

        upgraded = False
        for raw_category, entries in data.items():
            category = cls._canonical_category(raw_category)
            if category not in merged:
                merged[category] = {}
                upgraded = True
            if not isinstance(entries, dict):
                upgraded = True
                continue
            for raw_key, entry in entries.items():
                norm_key, normalized_entry = cls._normalize_entry(raw_key, entry)
                if not norm_key:
                    upgraded = True
                    continue
                if raw_key != norm_key:
                    upgraded = True
                existing = merged[category].get(norm_key)
                if existing != normalized_entry:
                    merged[category][norm_key] = normalized_entry
                    if existing is None or existing != normalized_entry:
                        upgraded = True

        return merged, upgraded

    @classmethod
    def load(cls):
        with cls._lock:
            if cls._data is not None:
                return cls._data

            raw_data = {}
            if os.path.exists(cls._path):
                try:
                    with open(cls._path, "r", encoding="utf-8") as f:
                        raw_data = json.load(f)
                except Exception:
                    raw_data = {}

            cls._data, upgraded = cls._merge_with_defaults(raw_data)
            if upgraded:
                cls.save()
            return cls._data

    @classmethod
    def save(cls):
        with cls._lock:
            if cls._data is None:
                return
            try:
                with open(cls._path, "w", encoding="utf-8") as f:
                    json.dump(cls._data, f, indent=2, ensure_ascii=True)
            except Exception:
                pass

    @classmethod
    def description(cls, category, key):
        category_key = cls._canonical_category(category)
        value_key = _normalize_key(key)
        data = cls.load()
        entry = data.get(category_key, {}).get(value_key)
        return _entry_description(entry, value_key)

    @classmethod
    def increment_usage(cls, category, key):
        category_key = cls._canonical_category(category)
        value_key = _normalize_key(key)
        data = cls.load()
        if category_key not in data:
            return
        if value_key not in data[category_key]:
            data[category_key][value_key] = {"description": _humanize_key(value_key), "usage_count": 0}
        data[category_key][value_key]["usage_count"] = max(
            0, _safe_int(data[category_key][value_key].get("usage_count", 0), 0)
        ) + 1

    @classmethod
    def add_setting(cls, category, key, description):
        category_key = cls._canonical_category(category)
        value_key = _normalize_key(key)
        if not value_key:
            return None
        data = cls.load()
        if category_key not in data:
            data[category_key] = {}
        if value_key not in data[category_key]:
            data[category_key][value_key] = {
                "description": _normalize_text(description) or _humanize_key(value_key),
                "usage_count": 0,
            }
        return value_key

    @classmethod
    def absorb_discoveries(cls, discovered_settings):
        if not isinstance(discovered_settings, dict):
            return
        for raw_category, values in discovered_settings.items():
            category = cls._canonical_category(raw_category)
            if isinstance(values, dict):
                values = [values]
            if not isinstance(values, list):
                values = [values]
            for item in values:
                if isinstance(item, dict):
                    key = item.get("key") or item.get("name") or item.get("value")
                    description = item.get("description", "")
                else:
                    key = item
                    description = _humanize_key(item)
                added_key = cls.add_setting(category, key, description)
                if added_key:
                    cls.increment_usage(category, added_key)

    @classmethod
    def save_preset(cls, name, config):
        with cls._lock:
            data = cls.load()
            if "design_presets" not in data:
                data["design_presets"] = {}
            data["design_presets"][name] = config
            cls.save()

    @classmethod
    def list_presets(cls):
        data = cls.load()
        presets = data.get("design_presets", {})
        return [{"name": k, "saved_at": v.get("saved_at", "")} for k, v in presets.items()]

    @classmethod
    def load_preset(cls, name):
        data = cls.load()
        return data.get("design_presets", {}).get(name)

    @classmethod
    def delete_preset(cls, name):
        with cls._lock:
            data = cls.load()
            if "design_presets" in data and name in data["design_presets"]:
                del data["design_presets"][name]
                cls.save()


_LIB = DesignLibrary.load()
SHARED_MATS = list(_LIB["materials"].keys())
SHARED_DECOR = list(_LIB["decorations"].keys())
SHARED_ACTS = list(_LIB["actions"].keys())
SHARED_ENVS = list(_LIB["environments"].keys())
SHARED_ATMOS = list(_LIB["atmospherics"].keys())
SHARED_STYLES = list(_LIB["styles"].keys())
SHARED_INTENTS = ["vector", "raster"]
SHARED_BG_MODES = ["simple", "preset", "custom", "none"]
SHARED_PROMPT_STYLES = ["conversational", "object_list"]

# ---------------------------------------------------------------------------
# Preset API routes
# ---------------------------------------------------------------------------
try:
    from aiohttp import web
    from server import PromptServer

    def _route(method, path):
        instance = getattr(PromptServer, "instance", None)
        if instance is None:
            return lambda func: func
        return getattr(instance.routes, method)(path)

    @_route("get", "/pgfx/presets/list")
    async def _list_presets(request):
        presets = DesignLibrary.list_presets()
        return web.json_response({"presets": presets})

    @_route("post", "/pgfx/presets/save")
    async def _save_preset(request):
        data = await request.json()
        name = (data.get("name", "") or "").strip()
        config = data.get("config", {})
        if not name:
            return web.json_response({"error": "No preset name provided"}, status=400)
        DesignLibrary.save_preset(name, config)
        return web.json_response({"status": "ok"})

    @_route("post", "/pgfx/presets/delete")
    async def _delete_preset(request):
        data = await request.json()
        name = (data.get("name", "") or "").strip()
        if not name:
            return web.json_response({"error": "No preset name provided"}, status=400)
        DesignLibrary.delete_preset(name)
        return web.json_response({"status": "ok"})

    @_route("get", "/pgfx/presets/load/{name}")
    async def _load_preset(request):
        name = request.match_info.get("name", "")
        config = DesignLibrary.load_preset(name)
        if config is None:
            return web.json_response({"error": "Preset not found"}, status=404)
        return web.json_response({"config": config})

    print("\033[96m[PGFX Logo Studio] Preset API routes registered.\033[0m")
except Exception as _e:
    print(f"\033[93m[PGFX Logo Studio] Could not register preset routes: {_e}\033[0m")


def _resolve_choice(category, raw_value, choices, default, allow_add, custom_notes, custom_note_key):
    normalized = _normalize_key(raw_value)
    
    current_library = DesignLibrary.load()
    cat_key = DesignLibrary._canonical_category(category)
    current_keys = current_library.get(cat_key, {})

    if normalized in choices or normalized in current_keys:
        return normalized

    alias = LIBRARY_ALIASES.get(category, {}).get(normalized)
    if alias in choices or alias in current_keys:
        return alias

    if allow_add and normalized:
        desc = _humanize_key(raw_value)
        added_key = DesignLibrary.add_setting(category, normalized, desc)
        if added_key:
            DesignLibrary.increment_usage(category, added_key)
            custom_notes[custom_note_key] = DesignLibrary.description(category, added_key)
    return default


def _fallback_agent_result(user_prompt, image_context, canvas_summary, creative_flair):
    combined = "\n".join([str(user_prompt or ""), str(image_context or ""), canvas_summary.get("layout_summary", "")])
    exact_text = _coalesce_non_empty(
        canvas_summary.get("text", ""),
        _extract_text_from_image_context(image_context),
        _extract_visible_text_hint(user_prompt),
    )

    if "background" in combined.lower():
        background_mode = "custom"
    else:
        background_mode = "none"

    return {
        "text_input": exact_text,
        "output_intent": "vector" if "vector" in combined.lower() else "raster",
        "background_mode": background_mode,
        "background_preset": _guess_choice_from_text("environments", combined, SHARED_ENVS, "none"),
        "background_custom_prompt": "",
        "scene_interaction": "",
        "material": _guess_choice_from_text("materials", combined, SHARED_MATS, "default"),
        "decoration": _guess_choice_from_text("decorations", combined, SHARED_DECOR, "none"),
        "action": _guess_choice_from_text("actions", combined, SHARED_ACTS, "none"),
        "environment_1": _guess_choice_from_text("atmospherics", combined, SHARED_ATMOS, "none"),
        "environment_2": "none",
        "environment_3": "none",
        "style_mode": _guess_choice_from_text("styles", combined, SHARED_STYLES, "creative"),
        "intensity": _clamp(0.8 + (creative_flair * 0.8), 0.2, 2.0),
        "subject": "logo design",
        "style": "professional logo rendering",
        "negatives": list(STANDARD_NEGATIVES),
    }


def _background_phrase(background_mode, background_preset, background_custom_prompt, canvas_summary):
    if background_mode == "preset":
        return DesignLibrary.description("environments", background_preset)
    if background_mode == "custom":
        return _normalize_text(background_custom_prompt)
    if background_mode == "simple":
        bg = _normalize_text(canvas_summary.get("background_color", ""))
        return bg or "a clean solid backdrop"
    return ""


def _style_render_phrase(output_intent, style_mode):
    intent = output_intent if output_intent in SHARED_INTENTS else "raster"
    style_key = style_mode if style_mode in SHARED_STYLES else "creative"
    style_map = {
        "flat_vector": "master-grade flat vector logo construction with razor-sharp edges, pristine silhouettes, and corporate-grade color blocking optimized for instant brand recognition at any scale",
        "creative": "visionary cinematic logo art direction with dramatic studio lighting, premium material rendering, and professional advertising-grade polish worthy of a Fortune 500 brand campaign",
        "realistic": "hyper-realistic physical logo mockup with photorealistic surface fidelity, true-to-life material physics, and commercial print-grade detail that reads as a tangible object in hand",
        "3d_render": "production-quality 3D logo visualization with dimensional depth, global illumination bounce lighting, subsurface scattering on materials, and physically accurate ray-traced reflections",
        "tattoo_art": "bold tattoo-flash inspired logo design with heavy dark linework, high-contrast hatching, and illustrative punch — a standalone graphic emblem, not applied to skin",
        "sticker_decal": "clean die-cut sticker-style logo presentation with crisp silhouette separation, subtle drop shadow, and a tactile vinyl decal finish perfect for merchandise mockups",
        "watercolor": "artistic watercolor logo treatment with flowing pigment blooms, cold-press paper grain texture, organic edge dispersion, and a hand-painted fine-art brand identity feel",
        "oil_painting": "rich impasto oil painting logo style with visible directional brushwork, thick paint build-up on canvas, subtle crackle texture, and old-master material quality",
        "pop_art": "bold pop-art logo treatment with Ben-Day dot halftone gradients, saturated primaries, thick comic-style outlines, and screen-printed poster aesthetic for maximum visual impact",
        "art_deco": "luxurious art deco logo styling with stepped geometric forms, symmetrical ornamentation, burnished precious metal accents, and the opulent typographic flair of 1920s brandmarks",
        "minimal_modern": "ultra-clean Scandinavian minimal logo design with generous negative space, restrained monochromatic palette, precise geometric balance, and single-weight line harmony",
        "woodcut": "bold carved woodblock logo style with thick relief ink lines, textured roller marks, high-contrast chiaroscuro, and a heritage hand-pulled print aesthetic for timeless branding",
        "pixel_art": "retro 8-bit pixel-art logo style with blocky square-pixel construction, indexed color palette limitations, and authentic arcade-era sprite sharpness at every edge",
        "japanese_woodblock": "traditional ukiyo-e style logo design with flat color fields, flowing sumi-e brush linework, subtle woodgrain texture overlay, and the restrained elegance of Japanese kamon family crests",
        "graffiti": "urban street-art logo style with aerosol overspray edges, marker stroke texture, paint drip effects, and raw hand-drawn energy for underground brand identity",
        "baroque": "dramatic baroque logo aesthetic with tenebristic chiaroscuro lighting, ornate scrolling embellishment, rich jewel-tone color, and the grand compositional weight of 17th-century heraldry",
    }
    base = style_map.get(style_key, DesignLibrary.description("styles", style_key))
    if intent == "vector":
        return f"{base}, vector-sharp with no anti-aliasing artifacts and flawless scaling"
    return f"{base}, rasterized as a polished high-resolution print-ready image"


def _geometry_instruction(geometry_adherence):
    adherence = _clamp(_safe_float(geometry_adherence, 1.0), 0.0, 1.0)
    if adherence >= 0.95:
        return "Strictly preserve the original geometry, composition, lettering, silhouette, and layer hierarchy with absolute precision. Do not alter any shapes or paths."
    if adherence >= 0.75:
        return "Preserve the source composition, lettering, and layout very closely; only minor surface-level stylization is allowed."
    if adherence >= 0.45:
        return "Respect the source layout as a strong blueprint, but allow moderate structural variance."
    if adherence >= 0.15:
        return "Modify the design layout and geometry freely. Alter shapes and structure while keeping the core theme recognizable."
    return "Completely reimagine the design geometry and composition. Feel free to alter shapes, layout, and structure. Use the source only as a loose thematic guide."


def _flair_instruction(creative_flair):
    flair = _clamp(_safe_float(creative_flair, 0.5), 0.0, 1.0)
    if flair >= 0.95:
        return "Inject wild creative flair, highly imaginative styling, extreme depth of detail, rich stylistic execution, and maximal artistic polish."
    if flair >= 0.75:
        return "Push bold creative execution, adding inventive details and rich surface textures that suit the chosen materials and style."
    if flair >= 0.45:
        return "Add tasteful stylization and production polish while staying loyal to the source design."
    if flair >= 0.15:
        return "Keep stylization restrained, minimal, and functional."
    return "Keep the rendering simple, plain, and clean. No extra details, no embellishments, minimal stylistic changes."


def _parse_extra_instruction(extra_instruction):
    extra_text = str(extra_instruction or "").strip()
    if not extra_text:
        return {}, ""
    parsed = json_utils.extract_and_parse_json(extra_text) if extra_text.startswith("{") else None
    if isinstance(parsed, dict):
        freeform = _normalize_text(parsed.get("freeform_extra", ""))
        return parsed, freeform
    return {}, _normalize_text(extra_text)


def _apply_intensity_to_effect(desc, intensity_val):
    desc = str(desc or "").strip()
    if not desc:
        return ""
    intensity = _clamp(_safe_float(intensity_val, 1.0), 0.0, 2.0)
    if intensity <= 0.05:
        return ""  # 0.0 disables the effect completely

    clean_desc = desc
    if intensity <= 0.45 or intensity >= 1.3:
        for prefix in ("subtle ", "soft ", "small ", "a "):
            if clean_desc.lower().startswith(prefix):
                clean_desc = clean_desc[len(prefix):]
                break

    if intensity <= 0.45:
        return f"subtle, sparse {clean_desc}"
    if intensity <= 0.8:
        return f"light {clean_desc}"
    if intensity <= 1.25:
        return desc
    if intensity <= 1.65:
        return f"dense, heavy {clean_desc}"
    return f"intense, dramatic and thick {clean_desc}"


def _build_logo_prompt(kwargs):
    canvas_json_raw = str(kwargs.get("canvas_json_data", "") or "")
    canvas_summary = _summarize_canvas_json(canvas_json_raw)
    extra_data, freeform_extra = _parse_extra_instruction(kwargs.get("extra_instruction", ""))

    raw_text = _coalesce_non_empty(
        kwargs.get("text_input", ""),
        extra_data.get("exact_text", ""),
        canvas_summary.get("text", ""),
    )
    # Collapse mid-word line breaks from SVG/canvas parsing (e.g. "P\nyrate" -> "Pyrate")
    exact_text = " ".join(raw_text.split()) if raw_text else ""

    custom_effects = _dedupe_preserve(
        [
            _normalize_text(extra_data.get("custom_environment_1", "")),
            _normalize_text(extra_data.get("custom_environment_2", "")),
            _normalize_text(extra_data.get("custom_environment_3", "")),
        ]
    )

    env_1_int = kwargs.get("environment_1_intensity", 1.0)
    env_2_int = kwargs.get("environment_2_intensity", 1.0)
    env_3_int = kwargs.get("environment_3_intensity", 1.0)

    effect_descriptions = _dedupe_preserve(
        [
            _apply_intensity_to_effect(DesignLibrary.description("atmospherics", kwargs.get("environment_1")), env_1_int),
            _apply_intensity_to_effect(DesignLibrary.description("atmospherics", kwargs.get("environment_2")), env_2_int),
            _apply_intensity_to_effect(DesignLibrary.description("atmospherics", kwargs.get("environment_3")), env_3_int),
            *custom_effects,
        ]
    )

    material_bits = _dedupe_preserve(
        [
            DesignLibrary.description("materials", kwargs.get("material")),
            _normalize_text(extra_data.get("custom_material", "")),
        ]
    )
    decoration_bits = _dedupe_preserve(
        [
            DesignLibrary.description("decorations", kwargs.get("decoration"))
            if kwargs.get("decoration") not in (None, "", "none")
            else "",
            _normalize_text(extra_data.get("custom_decoration", "")),
        ]
    )
    action_bits = _dedupe_preserve(
        [
            DesignLibrary.description("actions", kwargs.get("action"))
            if kwargs.get("action") not in (None, "", "none")
            else "",
            _normalize_text(extra_data.get("custom_action", "")),
        ]
    )

    bg_mode = kwargs.get("background_mode", "simple")
    bg_preset = kwargs.get("background_preset", "none")
    bg_custom = kwargs.get("background_custom_prompt", "")

    # Explicit 'none' is always respected — user deliberately silenced background instructions.
    # Auto-detection only triggers when the user left bg_mode at the default 'simple'.
    if bg_mode == "none":
        effective_bg_mode = "none"
    elif bg_mode == "custom" or (bg_custom and bg_custom.strip()):
        effective_bg_mode = "custom"
    elif bg_mode == "preset" or bg_preset not in (None, "", "none"):
        effective_bg_mode = "preset"
    else:
        # bg_mode is 'simple' (default) — allow Agent override via background_note
        effective_bg_mode = bg_mode

    # Only let the Agent's background_note override if the user has kept default simple settings
    if effective_bg_mode == "simple" and bg_preset == "none" and not bg_custom and "background_note" in extra_data:
        background_phrase = _normalize_text(extra_data.get("background_note", ""))
        if background_phrase:
            effective_bg_mode = "preset"
    else:
        background_phrase = _background_phrase(
            effective_bg_mode,
            bg_preset,
            bg_custom,
            canvas_summary,
        )

    subject = _normalize_text(extra_data.get("subject", "")) or "logo or wordmark design"
    scene_interaction = _normalize_text(kwargs.get("scene_interaction", ""))
    layout_summary = _coalesce_non_empty(canvas_summary.get("layout_summary", ""), extra_data.get("layout_summary", ""))

    intensity = _clamp(_safe_float(kwargs.get("intensity"), 1.0), 0.2, 2.0)
    intensity_phrase = (
        "Keep surface detail subtle and controlled."
        if intensity <= 0.55
        else "Use normal production detail."
        if intensity <= 1.2
        else "Use high surface detail and finish without changing the design."
    )

    # --- STUDIO-SIDE PRESET ENFORCEMENT ---
    # Read the Agent's enforced values from extra_data (travels via extra_instruction STRING wire).
    # This is the reliable path — combo pin wiring may be absent.
    enforced_style = extra_data.get("enforced_style_mode", "") or ""
    enforced_intent = extra_data.get("enforced_intent", "") or ""

    # Priority: Respect manual widget choices unless they are at their defaults
    user_style = kwargs.get("style_mode", "creative")
    effective_style = enforced_style if (user_style == "creative" and enforced_style in SHARED_STYLES) else user_style

    user_intent = kwargs.get("output_intent", "vector")
    effective_intent = enforced_intent if (user_intent == "vector" and enforced_intent in SHARED_INTENTS) else user_intent

    # Override style_note to use the effective values
    style_note = _style_render_phrase(effective_intent, effective_style)

    if effective_style in ("flat_vector", "tattoo_art", "sticker_decal"):
        material_bits = []
        decoration_bits = []
        action_bits = []
        effect_descriptions = []

    # Content-level guard: strip tattoo-related descriptions unless style IS tattoo_art.
    # The LLM Agent keeps choosing tattoo materials/decorations for any skull-like design.
    if effective_style != "tattoo_art":
        material_bits = [m for m in material_bits if "tattoo" not in m.lower()]
        decoration_bits = [d for d in decoration_bits if "tattoo" not in d.lower() and "flash-art" not in d.lower()]

    # --- 3D EXTRUSION CONTEXT ---
    # When the 3D Viewport was used to extrude the design, inject descriptive language
    has_3d = canvas_summary.get("has_3d_extrusion", False)
    extrusion_desc = ""
    if has_3d:
        depth = canvas_summary.get("extrusion_depth", 20)
        mat_key = canvas_summary.get("extrusion_material", "")
        mat_desc = DesignLibrary.description("materials", mat_key) if mat_key else ""
        bevel = canvas_summary.get("extrusion_bevel", True)
        parts = [f"3D extruded logo with {depth}px depth"]
        if bevel:
            parts.append("beveled edges")
        if mat_desc:
            parts.append(mat_desc)
        extrusion_desc = ", ".join(parts)

    # --- PROMPT ASSEMBLY ---
    # Branches on prompt_style: "conversational" (natural prose) or "object_list" (token list)
    prompt_style = str(kwargs.get("prompt_style", "conversational") or "conversational").lower()

    if prompt_style == "object_list":
        # ── Object List format ─────────────────────────────────────────────────
        # Produces clean comma-separated tokens optimised for Flux / SDXL.
        tokens = []

        # Style + intent
        tokens.append(style_note)

        # Production-rule additions
        if effective_style == "tattoo_art":
            tokens += ["high-contrast blackwork", "clean isolated line art", "stencil-ready", "no shading"]
        elif effective_style == "flat_vector":
            tokens += ["sharp geometric edges", "flat solid colors", "no photorealism", "no cinematic lighting"]
        elif effective_style == "sticker_decal":
            tokens += ["die-cut sticker", "distinct boundary outline", "clean silhouette"]
        elif effective_intent == "vector":
            tokens += ["crisp vector colors", "clean color separation", "no noise"]

        # Materials / decorations / actions
        tokens.extend(material_bits)
        tokens.extend(decoration_bits)
        tokens.extend(action_bits)

        # Atmospheric effects
        tokens.extend(effect_descriptions)

        # Scene interaction
        if scene_interaction:
            tokens.append(scene_interaction)

        # Background
        if effective_bg_mode in ("preset", "custom") and background_phrase:
            tokens.append(f"background: {background_phrase}")
        elif effective_bg_mode == "simple":
            tokens.append("clean solid background")

        # 3D extrusion
        if extrusion_desc:
            tokens.append(extrusion_desc)

        # Freeform
        if freeform_extra:
            tokens.append(freeform_extra)

        # Geometry / flair
        tokens.append(_geometry_instruction(kwargs.get("geometry_adherence", 1.0)))
        tokens.append(_flair_instruction(kwargs.get("creative_flair", 0.5)))

        # Intensity
        tokens.append(intensity_phrase)

        # Universal preservation clause
        tokens.append("preserve original layout")
        if exact_text:
            tokens.append(f"text: {exact_text}")
        else:
            tokens.append("preserve text exactly")

        # Filter empty and join
        prompt = ", ".join(t.rstrip(".") for t in tokens if t and t.strip())

    else:
        # ── Conversational format (default) ───────────────────────────────────
        # Natural prose that reads as instructions to the diffusion model.

        # 1. Style transformation
        style_parts = []
        if material_bits:
            style_parts.append(_list_phrase(material_bits))
        if decoration_bits and any(decoration_bits):
            style_parts.append(_list_phrase(decoration_bits))
        if action_bits and any(action_bits):
            style_parts.append(_list_phrase(action_bits))

        style_str = " ".join(style_parts).strip() if style_parts else ""

        prompt = f"Change the design style to {style_note}."
        if style_str:
            prompt += f" Apply {style_str}."

        # 1.5 Strict Production Rules
        if effective_style == "tattoo_art":
            prompt += " Use high-contrast blackwork, clean isolated line art, no shading or 3D gradients. Keep it stencil-ready."
        elif effective_style == "flat_vector":
            prompt += " Use sharp geometric edges, flat solid colors, no noise, no photorealism, and no cinematic lighting."
        elif effective_style == "sticker_decal":
            prompt += " Enforce a clean die-cut sticker presentation with a distinct boundary outline and no cluttered background."
        elif effective_intent == "vector":
            prompt += " Ensure crisp vector-like SVG separation of colors without noisy textures or soft gradients."

        # 2. Environment / atmospheric effects
        if effect_descriptions and any(effect_descriptions):
            prompt += f" Add {_list_phrase(effect_descriptions)} around the design."

        # 3. Scene interaction
        if scene_interaction:
            prompt += f" {scene_interaction}."

        # 4. 3D extrusion
        if extrusion_desc:
            prompt += f" {extrusion_desc}."

        # 5. Background
        if effective_bg_mode in ("preset", "custom") and background_phrase:
            prompt += f" Set the background to: {background_phrase}."
        elif effective_bg_mode == "simple":
            prompt += " Keep a clean solid background."
        # effective_bg_mode == "none" -> no background instruction

        # 7. Freeform extra instructions
        if freeform_extra:
            prompt += f" {freeform_extra}."

        # 8. Geometry / flair directives
        prompt += f" {_geometry_instruction(kwargs.get('geometry_adherence', 1.0))}"
        prompt += f" {_flair_instruction(kwargs.get('creative_flair', 0.5))}"

        # 9. Intensity and quality
        prompt += f" {intensity_phrase}"
        if exact_text:
            prompt += f" Preserve the original position and layout. Render the text '{exact_text}' exactly."
        else:
            prompt += " Preserve the original position, layout, and text exactly."

    return prompt


class PGFX_LogoDesignerAgent(PromptCrafter_BaseCreator):
    _pgfx_llm_controls_promoted = True
    DESCRIPTION = get_node_description("PGFX_LogoDesignerAgent")

    @classmethod
    def INPUT_TYPES(cls):
        all_models = api_clients.get_all_models()
        thinking_default = (
            config.FALLBACK_VISION_MODEL
            if hasattr(config, "FALLBACK_VISION_MODEL") and config.FALLBACK_VISION_MODEL in all_models
            else all_models[0]
        )
        instruct_default = (
            config.FALLBACK_TEXT_MODEL
            if hasattr(config, "FALLBACK_TEXT_MODEL") and config.FALLBACK_TEXT_MODEL in all_models
            else all_models[0]
        )
        return {
            "required": {
                "user_prompt": ("STRING", {"multiline": True, "placeholder": "Describe your vision...", "tooltip": "Explain your creative concept. The Elite Agent will translate this into precise Studio settings."}),
                "thinking_model": (all_models, {"default": thinking_default, "tooltip": "Select a high-intelligence 'Reasoning' model (like DeepSeek-R1) for the best architectural layout decisions."}),
                "instruct_model": (all_models, {"default": instruct_default, "tooltip": "Select a fast model to handle the final JSON configuration mapping."}),
                "image_count": ("INT", {"default": 1, "min": 1, "max": 8, "tooltip": "The number of connected reference images the Agent should analyze."}),
                "output_intent_override": (["AI DETERMINED"] + SHARED_INTENTS, {"default": "AI DETERMINED", "tooltip": "Force a specific output format (Vector or Raster), or let the Agent decide based on your prompt."}),
                "style_mode_override": (["AI DETERMINED"] + SHARED_STYLES, {"default": "AI DETERMINED", "tooltip": "Force a specific artistic style (e.g., 3D Render, Tattoo), or let the Agent analyze your intent."}),
            },
            "optional": {
                "geometry_adherence": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "creative_flair": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
                "seed": ("INT", {"default": 0, "min": -1, "max": 0xffffffffffffffff}),
                "timeout": ("INT", {"default": 120, "min": 30, "max": 600}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 2.0, "step": 0.1}),
                "max_length_words": ("INT", {"default": 0, "min": 0, "max": 1000}),
                "debug_mode": ("BOOLEAN", {"default": False}),
                "llm_device": (config.LLM_DEVICE_OPTIONS, {"default": config.DEFAULT_LLM_DEVICE}),
                "reset_context": ("BOOLEAN", {"default": True}),
                "image_weights_json": ("STRING", {"multiline": True, "default": "{}"}),
                "max_retries": ("INT", {"default": 3, "min": 0, "max": 10}),
                "safe_mode": ("BOOLEAN", {"default": True}),
                "critique_strength": (["None", "Low", "Medium", "High"], {"default": "None"}),
                "simplify_for_diffusion": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = (
        "STRING",
        SHARED_INTENTS,
        SHARED_BG_MODES,
        SHARED_ENVS,
        "STRING",
        "STRING",
        SHARED_MATS,
        SHARED_DECOR,
        SHARED_ACTS,
        SHARED_ATMOS,
        SHARED_ATMOS,
        SHARED_ATMOS,
        SHARED_STYLES,
        "FLOAT",
        "STRING",
        "INT",
        "FLOAT",
        "FLOAT",
    ) + ("IMAGE",) * 8

    RETURN_NAMES = (
        "text_input",
        "output_intent",
        "background_mode",
        "background_preset",
        "background_custom_prompt",
        "scene_interaction",
        "material",
        "decoration",
        "action",
        "environment_1",
        "environment_2",
        "environment_3",
        "style_mode",
        "intensity",
        "extra_instruction",
        "seed",
        "geometry_adherence",
        "creative_flair",
    ) + tuple(f"reference_image_{i}" for i in range(1, 9))

    FUNCTION = "think"
    CATEGORY = "☠️PGFX /Design"

    def think(
        self,
        user_prompt,
        thinking_model,
        instruct_model,
        image_count,
        output_intent_override,
        style_mode_override,
        geometry_adherence=1.0,
        creative_flair=0.5,
        seed=0,
        timeout=120,
        temperature=0.7,
        max_length_words=0,
        debug_mode=False,
        llm_device="Default (GPU)",
        reset_context=True,
        image_weights_json="{}",
        max_retries=3,
        safe_mode=True,
        critique_strength="None",
        simplify_for_diffusion=True,
        **kwargs,
    ):
        def _heal(value, default, caster):
            if value is None or value == "" or value == "None" or isinstance(value, bool):
                return default
            try:
                return caster(value)
            except Exception:
                return default

        _image_c = _heal(image_count, 1, int)
        _seed = _heal(seed, 0, int)
        _timeout = max(30, _heal(timeout, 120, int))
        _temp = min(2.0, _heal(temperature, 0.7, float))
        _geo = _clamp(_heal(geometry_adherence, 1.0, float), 0.0, 1.0)
        _flair = _clamp(_heal(creative_flair, 0.5, float), 0.0, 1.0)
        _max_l = _heal(max_length_words, 0, int)
        _retr = _heal(max_retries, 3, int)
        _dev = str(llm_device) if llm_device in config.LLM_DEVICE_OPTIONS else config.DEFAULT_LLM_DEVICE
        _crit = str(critique_strength) if critique_strength in ["None", "Low", "Medium", "High"] else "None"

        clean_kwargs = {
            "seed": _seed,
            "timeout": _timeout,
            "temperature": _temp,
            "debug_mode": bool(debug_mode),
            "llm_device": _dev,
            "reset_context": bool(reset_context),
            "image_count": _image_c,
            "safe_mode": bool(safe_mode),
            "max_retries": _retr,
            "simplify_for_diffusion": bool(simplify_for_diffusion),
            "max_length_words": _max_l,
            "style_override": "None",
            "critique_strength": _crit,
            "language": "English",
            "image_weights_json": image_weights_json,
        }

        for i in range(1, _image_c + 1):
            if f"image_{i}" in kwargs:
                clean_kwargs[f"image_{i}"] = kwargs[f"image_{i}"]

        library = DesignLibrary.load()
        allow_discovery = (
            output_intent_override == "AI DETERMINED" or style_mode_override == "AI DETERMINED"
        )

        canvas_summary = _summarize_canvas_json("")

        images_with_weights = self._collect_images_with_weights(**clean_kwargs)
        image_context = ""
        llm_images = [img for img, _ in images_with_weights if img is not None]
        if llm_images:
            run_config = self._setup_config(PGFX_LogoDesignerAgent, "Image", user_prompt, thinking_model, **clean_kwargs)
            
            # Inject a context-aware persona based on the user's specific choices
            intent_str = output_intent_override if output_intent_override != "AI DETERMINED" else "general graphic design"
            style_str = style_mode_override.replace("_", " ") if style_mode_override != "AI DETERMINED" else "professional logo design"
            
            run_config.style_profile = {
                "persona": f"You are an expert graphic designer and art director specializing in {style_str} and {intent_str} workflows."
            }
            
            describe_result = self._describe_images(images_with_weights, run_config)
            if describe_result:
                image_context = describe_result[0] or ""

        fallback = _fallback_agent_result(user_prompt, image_context, canvas_summary, _flair)
        library_snapshot = _format_library_for_prompt(library)
        reference_text = _coalesce_non_empty(
            canvas_summary.get("text", ""),
            _extract_text_from_image_context(image_context),
            _extract_visible_text_hint(user_prompt),
        )

        system_prompt = textwrap.dedent(
            f"""
            You are PGFX Logo Designer Agent.

            Your job is to convert the user's request plus any reference design imagery into structured PGFX Logo Designer Studio settings.

            Source-of-truth priority:
            1. Exact readable text and geometry visible in the supplied design reference.
            2. Explicit user instructions.
            3. Existing design library keys.

            Hard rules:
            - Never invent words, letters, slogans, or symbols.
            - If readable text exists in the design, copy it into `text_input` exactly, preserving line breaks when obvious.
            - Respect the user's composition. Higher geometry_adherence means stricter layout preservation.
            - Use the design library as the first-choice vocabulary.
            - `background_preset` must come from `background_presets`.
            - `environment_1/2/3` should be set to `none` for logo designs unless the user explicitly requests atmospheric effects. Spotlights and volumetric lighting cause visual artifacts on logos.
            - If a useful style term is missing from the library, add it under `discovered_settings` in snake_case, but still choose the closest existing runtime-safe key for the main field outputs.
            - For `tattoo_art`, `sticker_decal`, or `flat_vector` styles, default `background_mode` to `none` (isolated blank background) unless the user specifically requests a scene.
            - `tattoo_art` means an isolated flash-art graphic design. DO NOT describe it as being on a person, arm, or skin. The subject should just be the design itself.
            - `subject`: Describe ONLY the primary graphic element (e.g. "pirate skull with tricorn hat and crossed bones"). NEVER include background elements, flag descriptions, color schemes, or scene context in this field. Those belong in `background_custom_prompt` or `scene_interaction`.
            - `spatial_layout`: Briefly describe the visual composition (e.g. "skull on the right, large text on the left"). If layout is unknown, output "center".
            - NEVER choose `illustrative_ink` material or `tattoo_style` decoration unless the style_mode is explicitly `tattoo_art`. For non-tattoo styles, use `default` material and `none` decoration unless the user specifically requests something else.
            - `material` and `decoration` should match the chosen style_mode. For `3d_render` use materials like `polished_gold`, `brushed_steel`, `marble_white`. For `flat_vector` use `default`. For `creative` use contextually appropriate materials.

            Runtime-safe keys:
            {library_snapshot}

            Geometry adherence: {_geo:.2f}
            Creative flair: {_flair:.2f}
            Intent override: {output_intent_override}
            Style override: {style_mode_override}

            Return JSON only with this schema:
            {{
              "text_input": "",
              "output_intent": "vector|raster",
              "background_mode": "simple|preset|custom|none",
              "background_preset": "",
              "background_custom_prompt": "",
              "scene_interaction": "",
              "material": "",
              "decoration": "",
              "action": "",
              "environment_1": "",
              "environment_2": "",
              "environment_3": "",
              "style_mode": "",
              "intensity": 1.0,
              "subject": "",
              "spatial_layout": "center",
              "negatives": [],
              "discovered_settings": {{}}
            }}
            """
        ).strip()

        user_payload = textwrap.dedent(
            f"""
            User request:
            {user_prompt}

            Reference image notes:
            {image_context or "None"}

            Reference canvas summary:
            {canvas_summary.get("layout_summary", "") or "None"}

            Exact text hint:
            {reference_text or "None"}

            Keep the answer grounded in the visible logo design and do not improvise unrelated elements.
            """
        ).strip()

        agent_temperature = _clamp((_temp * 0.5) + (_flair * 0.35), 0.1, 1.1)
        
        # Elite Optimization: Use the specialized reasoning backend with forced JSON mode
        ok, raw_response = api_clients._reason_with_model(
            instruct_model,
            prompt=user_payload,
            system=system_prompt, # _reason_with_model will add "JSON ONLY" context if needed
            images=llm_images or None,
            temperature=agent_temperature,
            seed=_seed,
            timeout=_timeout,
            llm_device=_dev,
            reset_context=clean_kwargs["reset_context"],
        )

        parsed = raw_response if ok else None
        result = dict(fallback)
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                if value not in (None, "", []):
                    result[key] = value

        discovered = result.get("discovered_settings", {})
        DesignLibrary.absorb_discoveries(discovered)

        custom_notes = {}

        intent = (
            output_intent_override
            if output_intent_override != "AI DETERMINED"
            else (result.get("output_intent") if result.get("output_intent") in SHARED_INTENTS else fallback["output_intent"])
        )
        style_mode = (
            style_mode_override
            if style_mode_override != "AI DETERMINED"
            else _resolve_choice(
                "styles",
                result.get("style_mode"),
                SHARED_STYLES,
                fallback["style_mode"],
                allow_discovery,
                custom_notes,
                "custom_style",
            )
        )

        background_mode = str(result.get("background_mode", fallback["background_mode"])).strip().lower()
        if background_mode not in SHARED_BG_MODES:
            background_mode = "custom" if _normalize_text(result.get("background_custom_prompt", "")) else "none"

        background_preset = _resolve_choice(
            "environments",
            result.get("background_preset"),
            SHARED_ENVS,
            fallback["background_preset"],
            allow_discovery,
            custom_notes,
            "background_note",
        )

        # Force isolated styles to have no background unless explicitly customized
        if style_mode in ["tattoo_art", "sticker_decal", "flat_vector"]:
            if not _normalize_text(result.get("scene_interaction", "")) and not _normalize_text(result.get("background_custom_prompt", "")):
                background_mode = "none"
                background_preset = "none"
                if "background_note" in custom_notes:
                    del custom_notes["background_note"]

        material = _resolve_choice(
            "materials",
            result.get("material"),
            SHARED_MATS,
            fallback["material"],
            allow_discovery,
            custom_notes,
            "custom_material",
        )
        decoration = _resolve_choice(
            "decorations",
            result.get("decoration"),
            SHARED_DECOR,
            fallback["decoration"],
            allow_discovery,
            custom_notes,
            "custom_decoration",
        )
        action = _resolve_choice(
            "actions",
            result.get("action"),
            SHARED_ACTS,
            fallback["action"],
            allow_discovery,
            custom_notes,
            "custom_action",
        )
        env_1 = _resolve_choice(
            "atmospherics",
            result.get("environment_1"),
            SHARED_ATMOS,
            fallback["environment_1"],
            allow_discovery,
            custom_notes,
            "custom_environment_1",
        )
        env_2 = _resolve_choice(
            "atmospherics",
            result.get("environment_2"),
            SHARED_ATMOS,
            fallback["environment_2"],
            allow_discovery,
            custom_notes,
            "custom_environment_2",
        )
        env_3 = _resolve_choice(
            "atmospherics",
            result.get("environment_3"),
            SHARED_ATMOS,
            fallback["environment_3"],
            allow_discovery,
            custom_notes,
            "custom_environment_3",
        )

        text_input = _coalesce_non_empty(
            canvas_summary.get("text", ""),
            _normalize_text(result.get("text_input", "")),
            fallback["text_input"],
        )
        scene_interaction = _normalize_text(result.get("scene_interaction", ""))
        background_custom_prompt = _normalize_text(result.get("background_custom_prompt", ""))
        intensity = _clamp(_safe_float(result.get("intensity"), fallback["intensity"]), 0.2, 2.0)

        # --- HARDCODED PRESET ENFORCEMENT ENGINE ---
        added_negatives = []
        if style_mode == "flat_vector":
            intent = "vector"
            if material not in ("default", "none"):
                material = "none"
                custom_notes.pop("custom_material", None)
            if decoration not in ("default", "none"):
                decoration = "none"
                custom_notes.pop("custom_decoration", None)
            env_1 = env_2 = env_3 = "none"
            custom_notes.pop("custom_environment_1", None)
            custom_notes.pop("custom_environment_2", None)
            custom_notes.pop("custom_environment_3", None)
            intensity = min(intensity, 0.5)
            added_negatives = ["photoreal shading", "gradients", "3d elements", "realistic rendering"]

        elif style_mode == "tattoo_art":
            intent = "vector"
            env_1 = env_2 = env_3 = "none"
            custom_notes.pop("custom_environment_1", None)
            custom_notes.pop("custom_environment_2", None)
            custom_notes.pop("custom_environment_3", None)
            added_negatives = ["photorealistic", "human skin", "body parts", "limbs", "flesh"]
            
        elif style_mode == "sticker_decal":
            intent = "vector"
            env_1 = env_2 = env_3 = "none"
            custom_notes.pop("custom_environment_1", None)
            custom_notes.pop("custom_environment_2", None)
            custom_notes.pop("custom_environment_3", None)
            added_negatives = ["cluttered background", "photorealistic"]

        raw_negatives = _normalize_negatives(result.get("negatives", [])) + added_negatives + list(STANDARD_NEGATIVES)
        negatives = _dedupe_preserve(raw_negatives)

        subject_data = {
            "subject": _normalize_text(result.get("subject", "")) or fallback["subject"],
            "spatial_layout": _normalize_text(result.get("spatial_layout", "center")) or "center",
            "enforced_style_mode": style_mode,
            "enforced_intent": intent,
            "negatives": negatives,
            "exact_text": text_input,
            "layout_summary": canvas_summary.get("layout_summary", ""),
            **custom_notes,
        }
        final_extra = json.dumps(subject_data, ensure_ascii=True)

        for category, value in (
            ("environments", background_preset),
            ("materials", material),
            ("decorations", decoration),
            ("actions", action),
            ("atmospherics", env_1),
            ("atmospherics", env_2),
            ("atmospherics", env_3),
            ("styles", style_mode),
        ):
            if value and value != "none":
                DesignLibrary.increment_usage(category, value)

        DesignLibrary.save()

        passthrough_images = [img for img, _ in images_with_weights]
        passthrough_images.extend([None] * (8 - len(passthrough_images)))

        return (
            text_input,
            str(intent),
            background_mode,
            str(background_preset),
            background_custom_prompt,
            scene_interaction,
            str(material),
            str(decoration),
            str(action),
            str(env_1),
            str(env_2),
            str(env_3),
            str(style_mode),
            float(intensity),
            str(final_extra),
            int(_seed),
            float(_geo),
            float(_flair),
        ) + tuple(passthrough_images)


class PGFX_LogoDesignerStudio:
    DESCRIPTION = get_node_description("PGFX_LogoDesignerStudio")
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text_input": ("STRING", {"multiline": True, "default": ""}),
                "output_intent": (SHARED_INTENTS, {"default": "vector"}),
                "background_mode": (SHARED_BG_MODES, {"default": "simple"}),
                "background_preset": (SHARED_ENVS, {"default": "none"}),
                "background_custom_prompt": ("STRING", {"default": "", "multiline": True}),
                "scene_interaction": ("STRING", {"default": "", "multiline": True}),
                "material": (SHARED_MATS, {"default": "default"}),
                "decoration": (SHARED_DECOR, {"default": "none"}),
                "action": (SHARED_ACTS, {"default": "none"}),
                "environment_1": (SHARED_ATMOS, {"default": "none"}),
                "environment_1_intensity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}),
                "environment_2": (SHARED_ATMOS, {"default": "none"}),
                "environment_2_intensity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}),
                "environment_3": (SHARED_ATMOS, {"default": "none"}),
                "environment_3_intensity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}),
                "style_mode": (SHARED_STYLES, {"default": "creative"}),
                "intensity": ("FLOAT", {"default": 1.0, "min": 0.2, "max": 2.0}),
                "extra_instruction": ("STRING", {"default": "", "multiline": True}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "geometry_adherence": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "creative_flair": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05}),
                "prompt_style": (SHARED_PROMPT_STYLES, {"default": "conversational"}),
            },
            "optional": {
                "base64_image_data": ("STRING", {"multiline": True, "default": ""}),
                "canvas_json_data": ("STRING", {"multiline": True, "default": ""}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "FLOAT", "FLOAT")
    RETURN_NAMES = ("image", "mask", "flux_prompt", "geometry_adherence", "creative_flair")
    FUNCTION = "generate_data"
    CATEGORY = "☠️PGFX /Design"

    def generate_data(self, **kwargs):
        flux_prompt = _build_logo_prompt(kwargs)
        geo_val = float(kwargs.get("geometry_adherence", 1.0))
        flair_val = float(kwargs.get("creative_flair", 0.5))
        b64 = str(kwargs.get("base64_image_data", "") or "")
        img = None
        if b64:
            if b64.startswith("data:image") or ";base64," in b64 or len(b64) > 512:
                try:
                    encoded = b64.split(",", 1)[1] if "," in b64 else b64
                    img = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGBA")
                except Exception as e:
                    print(f"[PGFX Logo Studio] Error decoding base64: {e}")
            else:
                try:
                    import folder_paths
                    input_dir = folder_paths.get_input_directory()
                    path_parts = b64.replace("\\", "/").split("/")
                    full_path = os.path.join(input_dir, *path_parts)
                    if os.path.exists(full_path):
                        img = Image.open(full_path).convert("RGBA")
                    else:
                        filename = os.path.basename(b64)
                        fallback_path = os.path.join(input_dir, filename)
                        if os.path.exists(fallback_path):
                            img = Image.open(fallback_path).convert("RGBA")
                        else:
                            print(f"[PGFX Logo Studio] Warning: Image file '{b64}' not found in input directory '{input_dir}'.")
                except Exception as e:
                    print(f"[PGFX Logo Studio] Error loading image from file path '{b64}': {e}")

        if img is not None:
            try:
                arr = np.array(img).astype(np.float32) / 255.0
                return (
                    torch.from_numpy(arr[..., :3])[None,],
                    torch.from_numpy(arr[..., 3])[None,],
                    flux_prompt,
                    geo_val,
                    flair_val,
                )
            except Exception as e:
                print(f"[PGFX Logo Studio] Error processing image tensor: {e}")


        return (
            torch.zeros((1, 512, 512, 3)),
            torch.zeros((1, 512, 512)),
            flux_prompt,
            geo_val,
            flair_val,
        )


class PGFX_ImageVectorizer:
    DESCRIPTION = get_node_description("PGFX_ImageVectorizer")
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE", {"tooltip": "The source raster image to be vectorized."}),
                "preset": ([
                    "Custom (Use Manual Sliders)", 
                    "1-Color Silhouette (Ultra Fast)", 
                    "2-Color Minimalist", 
                    "4-Color Vinyl / Tattoo Decal",
                    "Clean Vector Logo (8 Colors)", 
                    "Smooth Curves & Fonts (8 Colors)", 
                    "Graphic Art (16 Colors)", 
                    "Raster Optimization (32 Colors - Web Safe)", 
                    "High Fidelity Raster (64 Colors - Heavy)"
                ], {"default": "Custom (Use Manual Sliders)", "tooltip": "Select a smart preset to automatically configure the vectorizer for specific scenarios."}),
                "mode": (["polygon", "spline"], {"default": "polygon", "tooltip": "Vectorization mode. Spline creates smooth curves. Polygon creates sharp, angular vector paths."}),
                "posterize_levels": ("INT", {"default": 32, "min": 2, "max": 256, "tooltip": "Number of colors to reduce the image to. Fewer colors mean a cleaner design and much faster processing."}),
                "dithering": ("BOOLEAN", {"default": False, "tooltip": "Enable dithering during color reduction. Best left OFF for logos, vinyl, and stencils to prevent millions of tiny speckles. Turn ON only for high-fidelity raster photos."}),
                "layering_mode": (["stacked", "cutout"], {"default": "stacked", "tooltip": "'stacked' layers shapes on top of each other. 'cutout' cuts shapes out of the background, ensuring no paths overlap (essential for CNC and Vinyl Plotters)."}),
                "color_matching": ("INT", {"default": 8, "min": 1, "max": 8, "tooltip": "Color precision for matching similar gradient shades. 8 is high precision. Lower values group similar colors aggressively."}),
                "noise_suppression": ("INT", {"default": 4, "min": 0, "max": 128, "tooltip": "Removes speckles and micro-details by dropping paths shorter than this value. Increase to 16+ for 8K images or vinyl stencils."}),
                "path_precision": ("INT", {"default": 3, "min": 1, "max": 16, "tooltip": "Precision of the vector paths. Lower values create simpler, blockier geometry. Higher values hug the pixels tighter but create more SVG nodes."}),
                "corner_threshold": ("INT", {"default": 60, "min": 1, "max": 100, "tooltip": "Corner detection sensitivity. LOWER values = smoother, more rounded curves. HIGHER values = sharper corners preserved. Set to 20-40 for best curve quality on fonts and rounded designs."}),
                "layer_difference": ("INT", {"default": 16, "min": 0, "max": 255, "tooltip": "Minimum color difference between gradient layers. LOWER values = more gradient layers (smoother color transitions). HIGHER values = fewer layers (flatter posterized look)."}),
            }
        }

    RETURN_TYPES = ("STRING", "IMAGE")
    RETURN_NAMES = ("svg_string", "image_preview")
    FUNCTION = "vectorize"
    OUTPUT_NODE = True
    CATEGORY = "☠️PGFX /Design"

    def vectorize(self, image, preset, mode, posterize_levels, dithering, layering_mode, color_matching, noise_suppression, path_precision, corner_threshold, layer_difference):
        if preset != "Custom (Use Manual Sliders)":
            if preset == "1-Color Silhouette (Ultra Fast)":
                posterize_levels = 2
                noise_suppression = 32
                path_precision = 4
                mode = "polygon"
                dithering = False
                layering_mode = "cutout"
                color_matching = 2
                corner_threshold = 80
                layer_difference = 80
            elif preset == "2-Color Minimalist":
                posterize_levels = 3
                noise_suppression = 24
                path_precision = 4
                mode = "spline"
                dithering = False
                layering_mode = "cutout"
                color_matching = 4
                corner_threshold = 35
                layer_difference = 40
            elif preset == "4-Color Vinyl / Tattoo Decal":
                posterize_levels = 4
                noise_suppression = 20
                path_precision = 4
                mode = "spline"
                dithering = False
                layering_mode = "cutout"
                color_matching = 5
                corner_threshold = 30
                layer_difference = 30
            elif preset == "Clean Vector Logo (8 Colors)":
                posterize_levels = 8
                noise_suppression = 16
                path_precision = 3
                mode = "spline"
                dithering = False
                layering_mode = "stacked"
                color_matching = 6
                corner_threshold = 45
                layer_difference = 20
            elif preset == "Smooth Curves & Fonts (8 Colors)":
                posterize_levels = 8
                noise_suppression = 4
                path_precision = 8
                mode = "spline"
                dithering = False
                layering_mode = "stacked"
                color_matching = 6
                corner_threshold = 25
                layer_difference = 12
            elif preset == "Graphic Art (16 Colors)":
                posterize_levels = 16
                noise_suppression = 12
                path_precision = 3
                mode = "polygon"
                dithering = False
                layering_mode = "stacked"
                color_matching = 7
                corner_threshold = 60
                layer_difference = 16
            elif preset == "Raster Optimization (32 Colors - Web Safe)":
                posterize_levels = 32
                noise_suppression = 8
                path_precision = 4
                mode = "polygon"
                dithering = False
                layering_mode = "stacked"
                color_matching = 8
                corner_threshold = 60
                layer_difference = 16
            elif preset == "High Fidelity Raster (64 Colors - Heavy)":
                posterize_levels = 64
                noise_suppression = 2
                path_precision = 8
                mode = "spline"
                dithering = True
                layering_mode = "stacked"
                color_matching = 8
                corner_threshold = 50
                layer_difference = 8

        try:
            import vtracer
            import nodes

            i = 255.0 * image[0].cpu().numpy()
            dither_flag = 1 if dithering else 0
            img = (
                Image.fromarray(np.clip(i, 0, 255).astype(np.uint8))
                .quantize(colors=posterize_levels, dither=dither_flag)
                .convert("RGBA")
            )
        except Exception:
            return ("Error", None)
        try:
            pixels = list(img.getdata())
            svg = vtracer.convert_pixels_to_svg(
                pixels,
                size=img.size,
                colormode="color",
                hierarchical=layering_mode,
                mode=mode,
                filter_speckle=noise_suppression,
                path_precision=path_precision,
                color_precision=color_matching,
                corner_threshold=corner_threshold,
                layer_difference=layer_difference,
            )
            preview = torch.from_numpy(np.array(img.convert("RGB")).astype(np.float32) / 255.0)[None,]
            return {"ui": nodes.PreviewImage().save_images(preview).get("ui"), "result": (svg, preview)}
        except Exception as e:
            print(f"Error in PGFX_ImageVectorizer: {e}")
            return ("<svg></svg>", None)


# ------------------------------------------------------------------------------------
# V3 Logo Designer Studio — JS canvas frontend
# ------------------------------------------------------------------------------------
if V3_IO_AVAILABLE:

    class PGFX_LogoDesignerStudioV3(v3_io.ComfyNode):
        """V3 wrapper around PGFX_LogoDesignerStudio with JS canvas support."""

        @classmethod
        def define_schema(cls):
            return v3_io.Schema(
                node_id="PGFX_LogoDesignerStudioV3",
                display_name="PGFX Logo Designer Studio (V3)",
                category="☠️PGFX /Design",
                is_output_node=True,
                description="Interactive logo design canvas with vector editing, 3D viewport, and prompt generation.",
                outputs=[
                    v3_io.Image.Output(display_name="image"),
                    v3_io.Mask.Output(display_name="mask"),
                    v3_io.String.Output(display_name="flux_prompt"),
                    v3_io.Float.Output(display_name="geometry_adherence"),
                    v3_io.Float.Output(display_name="creative_flair"),
                ],
                inputs=[
                    v3_io.String.Input("text_input", multiline=True, default=""),
                    v3_io.Combo.Input("output_intent", options=SHARED_INTENTS, default="vector"),
                    v3_io.Combo.Input("background_mode", options=SHARED_BG_MODES, default="simple"),
                    v3_io.Combo.Input("background_preset", options=SHARED_ENVS, default="none"),
                    v3_io.String.Input("background_custom_prompt", multiline=True, default=""),
                    v3_io.String.Input("scene_interaction", multiline=True, default=""),
                    v3_io.Combo.Input("material", options=SHARED_MATS, default="default"),
                    v3_io.Combo.Input("decoration", options=SHARED_DECOR, default="none"),
                    v3_io.Combo.Input("action", options=SHARED_ACTS, default="none"),
                    v3_io.Combo.Input("environment_1", options=SHARED_ATMOS, default="none"),
                    v3_io.Float.Input("environment_1_intensity", default=1.0, min=0.0, max=2.0, step=0.05),
                    v3_io.Combo.Input("environment_2", options=SHARED_ATMOS, default="none"),
                    v3_io.Float.Input("environment_2_intensity", default=1.0, min=0.0, max=2.0, step=0.05),
                    v3_io.Combo.Input("environment_3", options=SHARED_ATMOS, default="none"),
                    v3_io.Float.Input("environment_3_intensity", default=1.0, min=0.0, max=2.0, step=0.05),
                    v3_io.Combo.Input("style_mode", options=SHARED_STYLES, default="creative"),
                    v3_io.Float.Input("intensity", default=1.0, min=0.2, max=2.0),
                    v3_io.String.Input("extra_instruction", multiline=True, default=""),
                    v3_io.Int.Input("seed", default=0, min=0, max=0xffffffffffffffff),
                    v3_io.Float.Input("geometry_adherence", default=1.0, min=0.0, max=1.0, step=0.05),
                    v3_io.Float.Input("creative_flair", default=0.5, min=0.0, max=1.0, step=0.05),
                    v3_io.Combo.Input("prompt_style", options=SHARED_PROMPT_STYLES, default="conversational"),
                    v3_io.String.Input("base64_image_data", multiline=True, default="", optional=True),
                    v3_io.String.Input("canvas_json_data", multiline=True, default="", optional=True),
                ],
            )

        @classmethod
        def execute(cls, **kwargs):
            node = PGFX_LogoDesignerStudio()
            result = node.generate_data(**kwargs)
            return v3_io.NodeOutput(*result)


# ------------------------------------------------------------------------------------
# V3 Image Vectorizer — raster to SVG
# ------------------------------------------------------------------------------------
if V3_IO_AVAILABLE:

    class PGFX_ImageVectorizerV3(v3_io.ComfyNode):
        """V3 wrapper around PGFX_ImageVectorizer."""

        @classmethod
        def define_schema(cls):
            presets = [
                "Custom (Use Manual Sliders)",
                "1-Color Silhouette (Ultra Fast)",
                "2-Color Minimalist",
                "4-Color Vinyl / Tattoo Decal",
                "Clean Vector Logo (8 Colors)",
                "Smooth Curves & Fonts (8 Colors)",
                "Graphic Art (16 Colors)",
                "Raster Optimization (32 Colors - Web Safe)",
                "High Fidelity Raster (64 Colors - Heavy)",
            ]
            return v3_io.Schema(
                node_id="PGFX_ImageVectorizerV3",
                display_name="📐 PGFX Image Vectorizer (V3)",
                category="☠️PGFX /Design",
                is_output_node=True,
                description="Converts raster images to SVG vector graphics with preset configurations.",
                outputs=[
                    v3_io.String.Output(display_name="svg_string"),
                    v3_io.Image.Output(display_name="image_preview"),
                ],
                inputs=[
                    v3_io.Image.Input("image"),
                    v3_io.Combo.Input("preset", options=presets, default="Custom (Use Manual Sliders)"),
                    v3_io.Combo.Input("mode", options=["polygon", "spline"], default="polygon"),
                    v3_io.Int.Input("posterize_levels", default=32, min=2, max=256),
                    v3_io.Boolean.Input("dithering", default=False),
                    v3_io.Combo.Input("layering_mode", options=["stacked", "cutout"], default="stacked"),
                    v3_io.Int.Input("color_matching", default=8, min=1, max=8),
                    v3_io.Int.Input("noise_suppression", default=4, min=0, max=128),
                    v3_io.Int.Input("path_precision", default=3, min=1, max=16),
                    v3_io.Int.Input("corner_threshold", default=60, min=1, max=100),
                    v3_io.Int.Input("layer_difference", default=16, min=0, max=255),
                ],
            )

        @classmethod
        def execute(cls, image, preset, mode, posterize_levels, dithering, layering_mode, color_matching, noise_suppression, path_precision, corner_threshold, layer_difference):
            node = PGFX_ImageVectorizer()
            result = node.vectorize(image, preset, mode, posterize_levels, dithering, layering_mode, color_matching, noise_suppression, path_precision, corner_threshold, layer_difference)
            if isinstance(result, dict):
                return v3_io.NodeOutput(result["result"][0], result["result"][1], ui=result.get("ui"))
            return v3_io.NodeOutput(*result)


# ------------------------------------------------------------------------------------
# V3 Logo Designer Agent — LLM-powered Studio settings generator
# ------------------------------------------------------------------------------------
if V3_IO_AVAILABLE:

    class PGFX_LogoDesignerAgentV3(v3_io.ComfyNode):
        """V3 wrapper around PGFX_LogoDesignerAgent — converts user intent into Studio settings."""

        @classmethod
        def define_schema(cls):
            all_models = api_clients.get_all_models()
            thinking_default = (
                config.FALLBACK_VISION_MODEL
                if hasattr(config, "FALLBACK_VISION_MODEL") and config.FALLBACK_VISION_MODEL in all_models
                else all_models[0]
            )
            instruct_default = (
                config.FALLBACK_TEXT_MODEL
                if hasattr(config, "FALLBACK_TEXT_MODEL") and config.FALLBACK_TEXT_MODEL in all_models
                else all_models[0]
            )

            return v3_io.Schema(
                node_id="PGFX_LogoDesignerAgentV3",
                display_name="PGFX Logo Designer Agent (V3)",
                category="☠️PGFX /Design",
                description="LLM-powered agent that converts user intent into precise Logo Designer Studio settings.",
                accept_all_inputs=True,
                outputs=[
                    v3_io.String.Output(display_name="text_input"),
                    v3_io.String.Output(display_name="output_intent"),
                    v3_io.String.Output(display_name="background_mode"),
                    v3_io.String.Output(display_name="background_preset"),
                    v3_io.String.Output(display_name="background_custom_prompt"),
                    v3_io.String.Output(display_name="scene_interaction"),
                    v3_io.String.Output(display_name="material"),
                    v3_io.String.Output(display_name="decoration"),
                    v3_io.String.Output(display_name="action"),
                    v3_io.String.Output(display_name="environment_1"),
                    v3_io.String.Output(display_name="environment_2"),
                    v3_io.String.Output(display_name="environment_3"),
                    v3_io.String.Output(display_name="style_mode"),
                    v3_io.Float.Output(display_name="intensity"),
                    v3_io.String.Output(display_name="extra_instruction"),
                    v3_io.Int.Output(display_name="seed"),
                    v3_io.Float.Output(display_name="geometry_adherence"),
                    v3_io.Float.Output(display_name="creative_flair"),
                    v3_io.Image.Output(display_name="reference_image_1"),
                    v3_io.Image.Output(display_name="reference_image_2"),
                    v3_io.Image.Output(display_name="reference_image_3"),
                    v3_io.Image.Output(display_name="reference_image_4"),
                    v3_io.Image.Output(display_name="reference_image_5"),
                    v3_io.Image.Output(display_name="reference_image_6"),
                    v3_io.Image.Output(display_name="reference_image_7"),
                    v3_io.Image.Output(display_name="reference_image_8"),
                ],
                inputs=[
                    v3_io.String.Input("user_prompt", multiline=True, placeholder="Describe your vision..."),
                    v3_io.Combo.Input("thinking_model", options=all_models, default=thinking_default),
                    v3_io.Combo.Input("instruct_model", options=all_models, default=instruct_default),
                    v3_io.Int.Input("image_count", default=1, min=1, max=8),
                    v3_io.Combo.Input("output_intent_override", options=["AI DETERMINED"] + SHARED_INTENTS, default="AI DETERMINED"),
                    v3_io.Combo.Input("style_mode_override", options=["AI DETERMINED"] + SHARED_STYLES, default="AI DETERMINED"),
                    v3_io.Float.Input("geometry_adherence", default=1.0, min=0.0, max=1.0, step=0.05, optional=True),
                    v3_io.Float.Input("creative_flair", default=0.5, min=0.0, max=1.0, step=0.05, optional=True),
                    v3_io.Int.Input("seed", default=0, min=-1, max=0xffffffffffffffff, optional=True),
                    v3_io.Int.Input("timeout", default=120, min=30, max=600, optional=True),
                    v3_io.Float.Input("temperature", default=0.7, min=0.0, max=2.0, step=0.1, optional=True),
                    v3_io.Int.Input("max_length_words", default=0, min=0, max=1000, optional=True),
                    v3_io.Boolean.Input("debug_mode", default=False, optional=True),
                    v3_io.Combo.Input("llm_device", options=config.LLM_DEVICE_OPTIONS, default=config.DEFAULT_LLM_DEVICE, optional=True),
                    v3_io.Boolean.Input("reset_context", default=True, optional=True),
                    v3_io.String.Input("image_weights_json", multiline=True, default="{}", optional=True),
                    v3_io.Int.Input("max_retries", default=3, min=0, max=10, optional=True),
                    v3_io.Boolean.Input("safe_mode", default=True, optional=True),
                    v3_io.Combo.Input("critique_strength", options=["None", "Low", "Medium", "High"], default="None", optional=True),
                    v3_io.Boolean.Input("simplify_for_diffusion", default=True, optional=True),
                ],
            )

        @classmethod
        def execute(
            cls,
            user_prompt,
            thinking_model,
            instruct_model,
            image_count,
            output_intent_override,
            style_mode_override,
            geometry_adherence=1.0,
            creative_flair=0.5,
            seed=0,
            timeout=120,
            temperature=0.7,
            max_length_words=0,
            debug_mode=False,
            llm_device="Default (GPU)",
            reset_context=True,
            image_weights_json="{}",
            max_retries=3,
            safe_mode=True,
            critique_strength="None",
            simplify_for_diffusion=True,
            **kwargs,
        ):
            node = PGFX_LogoDesignerAgent()
            result = node.think(
                user_prompt,
                thinking_model,
                instruct_model,
                image_count,
                output_intent_override,
                style_mode_override,
                geometry_adherence=geometry_adherence,
                creative_flair=creative_flair,
                seed=seed,
                timeout=timeout,
                temperature=temperature,
                max_length_words=max_length_words,
                debug_mode=debug_mode,
                llm_device=llm_device,
                reset_context=reset_context,
                image_weights_json=image_weights_json,
                max_retries=max_retries,
                safe_mode=safe_mode,
                critique_strength=critique_strength,
                simplify_for_diffusion=simplify_for_diffusion,
                **kwargs,
            )
            return v3_io.NodeOutput(*result)


# ------------------------------------------------------------------------------------
# PGFX Logo Designer MCP Agent - General-purpose chat-driven workflow builder
# ------------------------------------------------------------------------------------
class PGFX_LogoDesignerMCPAgent:
    """General-purpose ComfyUI MCP Agent - chat-driven workflow builder and executor.
    
    This agent interprets natural language requests and builds/executes ComfyUI workflows
    to create images, videos, audio, and other media.
    """

    DESCRIPTION = get_node_description("PGFX_LogoDesignerMCPAgent")

    # Tool definitions for the LLM
    AGENT_TOOLS = [
        {
            "name": "search_nodes",
            "description": "Search available ComfyUI nodes by name, category, or description",
            "parameters": {
                "query": "Search query (e.g., 'load image', 'flux', 'video')",
                "category": "Optional: filter by category (e.g., 'loaders', 'samplers')"
            }
        },
        {
            "name": "get_node_info",
            "description": "Get detailed information about a specific node type, including inputs and outputs",
            "parameters": {
                "node_type": "The node class name (e.g., 'CheckpointLoaderSimple', 'KSampler')"
            }
        },
        {
            "name": "search_models",
            "description": "Search available models (checkpoints, LoRAs, VAEs, etc.)",
            "parameters": {
                "query": "Search query (e.g., 'flux', 'realistic', 'anime')",
                "model_type": "Optional: 'checkpoint', 'lora', 'vae', 'clip', etc."
            }
        },
        {
            "name": "list_models",
            "description": "List all available models by folder",
            "parameters": {
                "folder": "Optional: specific folder to list (e.g., 'checkpoints', 'loras')"
            }
        },
        {
            "name": "create_workflow",
            "description": "Create a new empty workflow",
            "parameters": {}
        },
        {
            "name": "add_node",
            "description": "Add a node to the current workflow",
            "parameters": {
                "node_type": "The node class name to add",
                "position": "Optional: [x, y] position on canvas",
                "title": "Optional: custom title for the node"
            }
        },
        {
            "name": "connect_nodes",
            "description": "Connect an output of one node to an input of another node",
            "parameters": {
                "source_node": "Source node index or title",
                "source_output": "Output slot index (0-based)",
                "target_node": "Target node index or title",
                "target_input": "Input slot name or index"
            }
        },
        {
            "name": "set_node_input",
            "description": "Set a literal value on a node input (for non-connected inputs)",
            "parameters": {
                "node": "Node index or title",
                "input_name": "Input parameter name",
                "value": "The value to set"
            }
        },
        {
            "name": "validate_workflow",
            "description": "Validate the current workflow before execution",
            "parameters": {}
        },
        {
            "name": "run_workflow",
            "description": "Execute the current workflow",
            "parameters": {
                "wait": "Whether to wait for completion (default: True)",
                "timeout": "Timeout in seconds (default: 120)"
            }
        },
        {
            "name": "get_job_status",
            "description": "Check the status of a submitted workflow",
            "parameters": {
                "prompt_id": "The prompt ID returned from run_workflow"
            }
        },
        {
            "name": "fetch_outputs",
            "description": "Download outputs from a completed workflow",
            "parameters": {
                "prompt_id": "The prompt ID",
                "output_dir": "Directory to save outputs (default: ComfyUI output folder)"
            }
        },
        {
            "name": "search_templates",
            "description": "Search pre-built workflow templates",
            "parameters": {
                "query": "Search query (e.g., 'text to image', 'video generation')"
            }
        },
        {
            "name": "run_template",
            "description": "Run a pre-built template with parameter overrides",
            "parameters": {
                "template": "Template name or ID",
                "overrides": "Dict of parameter overrides"
            }
        },
        {
            "name": "generate_image",
            "description": "Quick image generation with minimal parameters",
            "parameters": {
                "prompt": "Text prompt describing the image",
                "model": "Optional: model to use",
                "width": "Image width (default: 1024)",
                "height": "Image height (default: 1024)",
                "steps": "Sampling steps (default: 20)",
                "cfg": "CFG scale (default: 7.0)",
                "seed": "Random seed (-1 for random)"
            }
        },
        {
            "name": "generate_video",
            "description": "Quick video generation",
            "parameters": {
                "prompt": "Text prompt describing the video",
                "model": "Optional: model to use (e.g., 'wan', 'ltx')",
                "duration": "Duration in seconds",
                "fps": "Frames per second"
            }
        },
        {
            "name": "generate_audio",
            "description": "Quick audio/music generation",
            "parameters": {
                "prompt": "Text prompt describing the audio",
                "model": "Optional: model to use",
                "duration": "Duration in seconds"
            }
        },
        {
            "name": "download_model",
            "description": "Download a model from HuggingFace using huggingface-cli. Requires huggingface-hub installed.",
            "parameters": {
                "repo_id": "HuggingFace repo ID (e.g., 'MiniMaxAI/MiniMax-Music3', 'black-forest-labs/FLUX.1-dev')",
                "local_dir": "Local directory to download to (e.g., 'E:/ComfyUI-Easy-Install/models/music')",
                "filename": "Optional: specific filename to download (downloads all if empty)"
            }
        },
        {
            "name": "list_local_models",
            "description": "List models in a local directory to verify what is installed. Accepts absolute paths or folder names relative to the ComfyUI models directory (e.g., 'checkpoints', 'loras', 'unet').",
            "parameters": {
                "directory": "Directory path or folder name to list (e.g., 'checkpoints' or 'E:/path/to/models/loras')"
            }
        }
    ]

    @classmethod
    def INPUT_TYPES(cls):
        all_models = api_clients.get_all_models()
        return {
            "required": {
                "chat_message": ("STRING", {
                    "multiline": True,
                    "placeholder": "Describe what you want to create...",
                    "tooltip": "Natural language request for image, video, audio, or any ComfyUI-supported content"
                }),
                "llm_model": (all_models, {
                    "tooltip": "LLM model for interpreting requests and building workflows"
                }),
            },
            "optional": {
                "reference_image": ("IMAGE", {
                    "tooltip": "Optional input image for img2img, video starting frame, style reference, etc."
                }),
                "reference_audio": ("AUDIO", {
                    "tooltip": "Optional input audio for music, voice, sound effects"
                }),
                "model_preference": ("STRING", {
                    "default": "",
                    "tooltip": "Optional model preference (e.g., 'flux', 'wan', 'ltx', 'sdxl')"
                }),
                "comfyui_url": ("STRING", {
                    "default": "http://127.0.0.1:8188",
                    "tooltip": "ComfyUI server URL"
                }),
                "temperature": ("FLOAT", {
                    "default": 0.7,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.1,
                    "tooltip": "LLM temperature for response creativity"
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": -1,
                    "max": 0xffffffffffffffff,
                    "tooltip": "Random seed for reproducibility (-1 for random)"
                }),
                "timeout": ("INT", {
                    "default": 1800,
                    "min": 60,
                    "max": 7200,
                    "tooltip": "Workflow execution timeout in seconds (video on a 16GB card can take 15-30 min; keep this large)"
                }),
                "debug_mode": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Enable verbose logging for debugging"
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status",)
    FUNCTION = "execute"
    OUTPUT_NODE = True
    CATEGORY = "☠️PGFX /Agent"

    # Background execution state. ComfyUI runs a SINGLE serial prompt worker
    # (main.prompt_worker -> e.execute() blocks until the whole graph completes).
    # A node that submits a sub-workflow AND blocks waiting for that sub-workflow
    # deadlocks: the sub-job can never start because this node never returns.
    # We therefore run the agent loop off the worker and return immediately.
    # This is a fire-and-forget trigger node: results land in the ComfyUI output
    # directory for the user to browse (no synchronous output pins).
    _BG_LOCK = threading.Lock()
    _BG_ACTIVE = {}

    def execute(self, chat_message, llm_model, reference_image=None, reference_audio=None,
                model_preference="", comfyui_url="http://127.0.0.1:8188",
                temperature=0.7, seed=0, timeout=1800, debug_mode=False, **kwargs):

        def _placeholder_image():
            """Return a 1x1 black pixel image so downstream nodes don't crash."""
            return torch.zeros(1, 1, 1, 3, dtype=torch.float32)

        job_key = (comfyui_url, chat_message, model_preference, seed, debug_mode)

        with PGFX_LogoDesignerMCPAgent._BG_LOCK:
            if PGFX_LogoDesignerMCPAgent._BG_ACTIVE.get(job_key):
                return ("ALREADY_RUNNING: this request is already generating in the background.",)
            PGFX_LogoDesignerMCPAgent._BG_ACTIVE[job_key] = True

        def _worker():
            try:
                self._run_mcp_agent(chat_message, llm_model, reference_image, reference_audio,
                                    model_preference, comfyui_url, temperature, seed, timeout,
                                    debug_mode, _placeholder_image)
            except Exception as e:
                if debug_mode:
                    print(f"\033[95m[MCP Agent]\033[0m background error: {e}")
            finally:
                with PGFX_LogoDesignerMCPAgent._BG_LOCK:
                    PGFX_LogoDesignerMCPAgent._BG_ACTIVE.pop(job_key, None)

        threading.Thread(target=_worker, daemon=True).start()

        return ("QUEUED_ASYNC: agent is generating on the ComfyUI queue in the background. "
                "Results will appear in the ComfyUI output directory.",)

        if requests is None:
            return (_placeholder_image(), "", "{}", "ERROR: 'requests' library not installed")

        status_logs = []
        workflow_json_str = "{}"
        result_image = None
        result_text = ""

        def log(msg):
            status_logs.append(msg)
            if debug_mode:
                print(f"\033[93m[MCP Agent]\033[0m {msg}")

        def execute_comfyui_workflow(workflow):
            """Submit workflow to ComfyUI and return results."""
            try:
                if not workflow or not isinstance(workflow, dict):
                    return False, "Invalid workflow"

                payload = {"prompt": workflow}
                response = requests.post(
                    f"{comfyui_url}/prompt",
                    json=payload,
                    timeout=10
                )

                if response.status_code != 200:
                    return False, f"ComfyUI error (HTTP {response.status_code}): {response.text[:500]}"

                data = response.json()
                prompt_id = data.get("prompt_id")
                if not prompt_id:
                    return False, "No prompt_id returned from ComfyUI"

                log(f"Workflow submitted: {prompt_id}")

                start_time = time.time()
                while time.time() - start_time < timeout:
                    history_response = requests.get(
                        f"{comfyui_url}/history/{prompt_id}",
                        timeout=5
                    )

                    if history_response.status_code == 200:
                        history = history_response.json()
                        if prompt_id in history:
                            entry = history[prompt_id]
                            status = entry.get("status", {})
                            if status.get("completed", False):
                                elapsed = time.time() - start_time
                                log(f"Workflow completed in {elapsed:.1f}s")
                                return True, entry
                            if status.get("status_str") == "error":
                                msgs = status.get("messages", [])
                                return False, f"Workflow failed: {msgs}"

                    time.sleep(1)

                return False, f"Workflow timed out after {timeout}s"

            except requests.exceptions.ConnectionError:
                return False, f"Cannot connect to ComfyUI at {comfyui_url}"
            except Exception as e:
                return False, f"Error: {str(e)}"

        def download_image(filename, subfolder="", folder_type="output"):
            """Download image from ComfyUI output."""
            try:
                resp = requests.get(
                    f"{comfyui_url}/view",
                    params={"filename": filename, "subfolder": subfolder, "type": folder_type},
                    timeout=10
                )
                if resp.status_code == 200:
                    img = Image.open(io.BytesIO(resp.content))
                    img_np = np.array(img).astype(np.float32) / 255.0
                    return torch.from_numpy(img_np)[None,]
            except Exception as e:
                log(f"Error downloading image: {e}")
            return None

        # Build prompts
        system_prompt = self._build_system_prompt(model_preference)
        user_message = self._build_user_message(chat_message, reference_image, reference_audio, model_preference)

        # Query LLM
        log("Interpreting request...")
        # Detect if the selected model supports vision input (same pattern as other creator nodes)
        model_is_vision = api_clients.ModelInspector.is_vision_model({"id": llm_model})
        images_for_llm = []
        if reference_image is not None and model_is_vision:
            img_np = (reference_image[0].cpu().numpy() * 255).astype(np.uint8)
            images_for_llm.append(Image.fromarray(img_np))
            log(f"Reference image sent to vision-capable model: {llm_model}")
        elif reference_image is not None and not model_is_vision:
            log(f"Reference image attached but model '{llm_model}' is not vision-capable - will be passed to workflow as input, not sent to LLM")

        ok, llm_response = api_clients.query_model_auto(
            llm_model,
            prompt=user_message,
            system=system_prompt,
            images=images_for_llm if images_for_llm else None,
            temperature=temperature,
            seed=seed,
            timeout=120
        )

        # Retry without images if the model rejected image input (defensive fallback)
        if not ok and images_for_llm and "image input is not supported" in str(llm_response):
            log("Model rejected image input - retrying without image")
            images_for_llm = []
            ok, llm_response = api_clients.query_model_auto(
                llm_model,
                prompt=user_message,
                system=system_prompt,
                images=None,
                temperature=temperature,
                seed=seed,
                timeout=120
            )

        if not ok:
            return (_placeholder_image(), f"LLM error: {llm_response}", "{}", "LLM_FAILED")

        log("LLM response received")

        result_text = str(llm_response)

        # --- Tool call execution ---
        # Check if LLM wants to execute a tool (download, list, etc.) instead of building a workflow
        try:
            tool_call = None
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', result_text, re.DOTALL)
            if json_match:
                try:
                    tool_call = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            else:
                try:
                    tool_call = json.loads(result_text)
                except json.JSONDecodeError:
                    pass

            if tool_call and isinstance(tool_call, dict) and "tool_call" in tool_call:
                tool_name = tool_call.get("tool_call")
                params = tool_call.get("params", {})
                log(f"Executing tool: {tool_name}")

                if tool_name == "download_model":
                    repo_id = params.get("repo_id", "")
                    local_dir = params.get("local_dir", "")
                    filename = params.get("filename", "")

                    if not repo_id or not local_dir:
                        return (_placeholder_image(), "Error: download_model requires repo_id and local_dir", "{}", "TOOL_ERROR")

                    import subprocess
                    cmd = ["huggingface-cli", "download", repo_id, "--local-dir", local_dir]
                    if filename:
                        cmd.extend(["--include", filename])

                    log(f"Running: {' '.join(cmd)}")
                    try:
                        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                        output = proc.stdout + proc.stderr
                        if proc.returncode == 0:
                            log(f"Download complete: {output[-200:]}")
                            return (_placeholder_image(), f"Download successful:\n{output}", "{}", "SUCCESS")
                        else:
                            return (_placeholder_image(), f"Download failed (exit {proc.returncode}):\n{output}", "{}", "DOWNLOAD_FAILED")
                    except FileNotFoundError:
                        return (_placeholder_image(), "Error: huggingface-cli not found. Install with: pip install huggingface-hub", "{}", "TOOL_ERROR")
                    except subprocess.TimeoutExpired:
                        return (_placeholder_image(), "Error: Download timed out after 600s", "{}", "TOOL_ERROR")

                elif tool_name == "list_local_models":
                    directory = params.get("directory", "")
                    if not directory:
                        return (_placeholder_image(), "Error: list_local_models requires a directory path", "{}", "TOOL_ERROR")

                    import os
                    # Resolve path: support relative names (e.g. "checkpoints") against ComfyUI models dir
                    resolved = directory
                    if not os.path.isabs(resolved) and not os.path.isdir(resolved):
                        candidate = os.path.join(config.MODELS_DIR, directory)
                        if os.path.isdir(candidate):
                            resolved = candidate
                        else:
                            # Also try exact subdirectory match under models dir
                            for sub in sorted(os.listdir(config.MODELS_DIR)):
                                sub_path = os.path.join(config.MODELS_DIR, sub)
                                if os.path.isdir(sub_path) and sub.lower() == directory.lower():
                                    resolved = sub_path
                                    break

                    if not os.path.isdir(resolved):
                        available = sorted(d for d in os.listdir(config.MODELS_DIR) if os.path.isdir(os.path.join(config.MODELS_DIR, d)))
                        return (_placeholder_image(), f"Error: Directory not found: {directory}\n\nAvailable model folders:\n" + "\n".join(f"  {d}/" for d in available), "{}", "TOOL_ERROR")

                    files = []
                    for f in sorted(os.listdir(resolved)):
                        fpath = os.path.join(resolved, f)
                        if os.path.isfile(fpath):
                            size_mb = os.path.getsize(fpath) / (1024 * 1024)
                            files.append(f"{f}  ({size_mb:.1f} MB)")
                        else:
                            files.append(f"{f}/")

                    listing = f"Contents of {resolved}:\n" + "\n".join(files[:50])
                    if len(files) > 50:
                        listing += f"\n... and {len(files) - 50} more items"
                    return (_placeholder_image(), listing, "{}", "SUCCESS")

                else:
                    return (_placeholder_image(), f"Unknown tool: {tool_name}", "{}", "TOOL_ERROR")

        except Exception as e:
            log(f"Tool execution error: {e}")

        # --- Workflow execution ---
        try:
            workflow_obj = None

            # Look for JSON code blocks
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', result_text, re.DOTALL)
            if json_match:
                workflow_obj = json.loads(json_match.group(1))
            else:
                # Try parsing entire response as JSON
                try:
                    workflow_obj = json.loads(result_text)
                except json.JSONDecodeError:
                    pass

            if workflow_obj and isinstance(workflow_obj, dict) and ("nodes" in workflow_obj or "links" in workflow_obj):
                workflow_json_str = json.dumps(workflow_obj, indent=2)
                log("Executing workflow...")
                success, result = execute_comfyui_workflow(workflow_obj)

                if success:
                    outputs = result.get("outputs", {})
                    for node_id, node_output in outputs.items():
                        if "images" in node_output:
                            for img_info in node_output["images"]:
                                img_tensor = download_image(
                                    img_info["filename"],
                                    img_info.get("subfolder", ""),
                                    img_info.get("type", "output")
                                )
                                if img_tensor is not None:
                                    result_image = img_tensor
                                    log(f"Image downloaded: {img_info['filename']}")
                                    break
                        if result_image is not None:
                            break

                    return (result_image if result_image is not None else _placeholder_image(), result_text, workflow_json_str, "SUCCESS")
                else:
                    return (_placeholder_image(), result_text, workflow_json_str, f"EXECUTION_FAILED: {result}")
            else:
                return (_placeholder_image(), result_text, workflow_json_str, "TEXT_RESPONSE")

        except json.JSONDecodeError:
            return (_placeholder_image(), result_text, workflow_json_str, "TEXT_RESPONSE")
        except Exception as e:
            return (_placeholder_image(), f"Error: {str(e)}\n\n{result_text}", workflow_json_str, "ERROR")

    @staticmethod
    def _video_preview_frame(video_path):
        try:
            import mcp_agent as _ma
            return _ma.video_preview_tensor(video_path)
        except Exception:
            pass
        if not video_path or not os.path.isfile(video_path):
            return None
        try:
            import subprocess
            preview_png = video_path + ".preview.png"
            subprocess.run(
                ["ffmpeg", "-y", "-i", video_path, "-frames:v", "1", preview_png],
                capture_output=True, timeout=60
            )
            if not os.path.isfile(preview_png):
                return None
            with Image.open(preview_png) as im:
                arr = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
            return torch.from_numpy(arr)[None]
        except Exception:
            return None

    def _run_mcp_agent(self, chat_message, llm_model, reference_image, reference_audio,
                       model_preference, comfyui_url, temperature, seed, timeout, debug_mode,
                       placeholder_fn):
        import sys
        import os as _os
        _pkg = _os.path.dirname(_os.path.abspath(__file__))
        if _pkg not in sys.path:
            sys.path.insert(0, _pkg)
        import mcp_agent

        try:
            import folder_paths
            out_dir = folder_paths.get_output_directory()
        except Exception:
            out_dir = _os.path.normpath(_os.path.join(_os.path.dirname(config.MODELS_DIR), "output"))

        model_is_vision = api_clients.ModelInspector.is_vision_model({"id": llm_model})
        vision_images = []
        if reference_image is not None and model_is_vision:
            try:
                img_np = (reference_image[0].cpu().numpy() * 255).astype("uint8")
                vision_images = [Image.fromarray(img_np)]
            except Exception as e:
                log_text = f"[MCP Agent] could not prepare reference image for LLM: {e}"
                if debug_mode:
                    print(f"\033[95m{log_text}\033[0m")

        call_count = [0]

        def llm_call(system_prompt, history):
            conv = []
            for m in history:
                role = m.get("role")
                content = m.get("content", "")
                if role in ("user", "assistant"):
                    conv.append(f"{role.upper()}:\n{content}")
            prompt = "\n\n".join(conv)
            images = vision_images if (call_count[0] == 0 and vision_images) else None
            call_count[0] += 1
            ok, res = api_clients.query_model_auto(
                llm_model,
                prompt=prompt,
                system=system_prompt,
                images=images,
                temperature=temperature,
                seed=seed,
                timeout=120
            )
            if not ok and images is not None and res:
                err_l = str(res).lower()
                if "image input" in err_l or "support image" in err_l or "cannot read" in err_l:
                    ok, res = api_clients.query_model_auto(
                        llm_model,
                        prompt=prompt,
                        system=system_prompt,
                        images=None,
                        temperature=temperature,
                        seed=seed,
                        timeout=120
                    )
            return ok, str(res)

        session = mcp_agent.AgentSession(
            comfyui_url=comfyui_url,
            timeout=int(timeout),
            debug=bool(debug_mode),
            out_dir=out_dir,
            can_preview=True,
            models_dir=getattr(config, "MODELS_DIR", None),
            llm_unloader=api_clients.unload_local_llm_vram,
        )

        result = session.run(chat_message, reference_image=reference_image,
                             reference_audio=reference_audio, max_rounds=14, llm_call=llm_call)

        # Agent is done: release the local LLM again so it never sits resident holding
        # VRAM between jobs. ComfyUI models were already freed post-generation by the
        # agent; this evicts the LLM that reloaded for the last agent query. Without it,
        # a later generation has to contend with an idle LLM still parked in VRAM.
        try:
            api_clients.unload_local_llm_vram()
        except Exception:
            pass

        if not result.get("ok"):
            return (placeholder_fn(), f"Agent failed: {result.get('error')}", "{}", "AGENT_FAILED")

        summary = result.get("summary", "")
        files = result.get("files", [])

        workflow_json_str = json.dumps(files, indent=2) if files else "{}"
        preview = result.get("preview_tensor")
        if preview is None and result.get("success_image") in (None, False) and files:
            try:
                import mcp_agent as _ma
                for f in files:
                    preview = _ma.video_preview_tensor(f)
                    if preview is not None:
                        break
            except Exception:
                preview = None
        if preview is not None:
            return (preview, summary, workflow_json_str, "SUCCESS")
        return (placeholder_fn(), summary, workflow_json_str,
                "SUCCESS" if result.get("success_image") else "SUCCESS_FILE_ONLY")

    def _build_system_prompt(self, model_preference):
        tools_desc = json.dumps(self.AGENT_TOOLS, indent=2)
        model_hint = ""
        if model_preference:
            model_hint = f"\nUser prefers to use: {model_preference}"

        models_dir_hint = ""
        try:
            models_dir_hint = f"\nComfyUI models directory (use this base for list_local_models): {config.MODELS_DIR}"
        except Exception:
            pass

        return f"""You are a ComfyUI MCP Agent - an AI assistant that creates media using ComfyUI.

Your job is to interpret user requests and create ComfyUI workflows to produce the requested content.

AVAILABLE TOOLS:
{tools_desc}
{model_hint}{models_dir_hint}

WORKFLOW CREATION PROCESS:
1. Understand what the user wants to create
2. Search for appropriate nodes and models
3. Build a ComfyUI API-format workflow
4. Submit the workflow for execution
5. Return the results

WORKFLOW FORMAT:
ComfyUI workflows are JSON objects with "nodes" and "links" arrays. Each node has:
- "id": unique identifier (integer)
- "type": node class name (string)
- "inputs": list of input connections (each is [source_node_id, source_output_slot])
- "widgets_values": list of widget values in order

EXAMPLE WORKFLOW (text-to-image):
{{
  "last_node_id": 6,
  "last_link_id": 5,
  "nodes": [
    {{
      "id": 1,
      "type": "CheckpointLoaderSimple",
      "pos": [0, 0],
      "size": [300, 100],
      "inputs": [],
      "outputs": [
        {{ "name": "MODEL", "type": "MODEL", "links": [1] }},
        {{ "name": "CLIP", "type": "CLIP", "links": [2] }},
        {{ "name": "VAE", "type": "VAE", "links": [5] }}
      ],
      "widgets_values": ["model_name.safetensors"]
    }},
    {{
      "id": 2,
      "type": "CLIPTextEncode",
      "pos": [400, 0],
      "size": [300, 100],
      "inputs": [
        {{ "name": "clip", "type": "CLIP", "link": 2 }}
      ],
      "outputs": [
        {{ "name": "CONDITIONING", "type": "CONDITIONING", "links": [3] }}
      ],
      "widgets_values": ["beautiful landscape, mountains, sunset"]
    }},
    {{
      "id": 3,
      "type": "CLIPTextEncode",
      "pos": [400, 150],
      "size": [300, 100],
      "inputs": [
        {{ "name": "clip", "type": "CLIP", "link": 2 }}
      ],
      "outputs": [
        {{ "name": "CONDITIONING", "type": "CONDITIONING", "links": [4] }}
      ],
      "widgets_values": ["blurry, low quality, deformed"]
    }},
    {{
      "id": 4,
      "type": "EmptyLatentImage",
      "pos": [0, 200],
      "size": [300, 100],
      "inputs": [],
      "outputs": [
        {{ "name": "LATENT", "type": "LATENT", "links": [6] }}
      ],
      "widgets_values": [1024, 1024, 1]
    }},
    {{
      "id": 5,
      "type": "KSampler",
      "pos": [800, 0],
      "size": [300, 200],
      "inputs": [
        {{ "name": "model", "type": "MODEL", "link": 1 }},
        {{ "name": "positive", "type": "CONDITIONING", "link": 3 }},
        {{ "name": "negative", "type": "CONDITIONING", "link": 4 }},
        {{ "name": "latent_image", "type": "LATENT", "link": 6 }}
      ],
      "outputs": [
        {{ "name": "LATENT", "type": "LATENT", "links": [7] }}
      ],
      "widgets_values": [0, "fixed", 20, 7.0, "euler", "normal", 1.0]
    }},
    {{
      "id": 6,
      "type": "VAEDecode",
      "pos": [1200, 0],
      "size": [300, 100],
      "inputs": [
        {{ "name": "samples", "type": "LATENT", "link": 7 }},
        {{ "name": "vae", "type": "VAE", "link": 5 }}
      ],
      "outputs": [
        {{ "name": "IMAGE", "type": "IMAGE", "links": [8] }}
      ],
      "widgets_values": []
    }},
    {{
      "id": 7,
      "type": "SaveImage",
      "pos": [1600, 0],
      "size": [300, 100],
      "inputs": [
        {{ "name": "images", "type": "IMAGE", "link": 8 }}
      ],
      "outputs": [],
      "widgets_values": ["MCP_output"]
    }}
  ],
  "links": [
    [1, 1, 0, 5, 0],
    [2, 1, 1, 2, 0],
    [3, 2, 0, 5, 1],
    [4, 3, 0, 5, 2],
    [5, 1, 2, 6, 1],
    [6, 4, 0, 5, 3],
    [7, 5, 0, 6, 0],
    [8, 6, 0, 7, 0]
  ]
}}

IMPORTANT RULES:
- Reference images provided by the user are available as INPUT to your workflow (e.g., LoadImage node, img2img, ControlNet)
- Do NOT assume the LLM can "see" the reference image - describe how to use it in the workflow, not what it contains
- Always return a valid ComfyUI API-format workflow as JSON
- Use common node types: CheckpointLoaderSimple, CLIPTextEncode, KSampler, VAEDecode, SaveImage
- For image generation, use the pattern shown above
- For video generation, add VideoCombine or similar output nodes
- Use real model filenames that exist on the system
- Return the workflow as a JSON code block in your response
- Include helpful text explaining what you are creating{model_hint}

TOOL CALLS (when user asks to download or list models):
When the user asks to download a model or list local files, return a JSON code block with:
{{
  "tool_call": "download_model",
  "params": {{
    "repo_id": "owner/repo",
    "local_dir": "/path/to/destination",
    "filename": "optional specific file"
  }}
}}

Or for listing:
{{
  "tool_call": "list_local_models",
  "params": {{
    "directory": "/path/to/list"
  }}
}}

Do NOT return a workflow when making a tool call - just the tool_call JSON.

RESPONSE FORMAT:
1. Explain what you are creating and why you chose specific settings
2. Return the complete workflow JSON inside a ```json code block (or tool_call JSON)
3. Explain any notable parameters or choices"""

    def _build_user_message(self, chat_message, reference_image, reference_audio, model_preference):
        parts = [chat_message]
        if reference_image is not None:
            parts.append("\n[Reference image attached - use as input for img2img, ControlNet, or style reference]")
        if reference_audio is not None:
            parts.append("\n[Reference audio attached - use as input for audio processing]")
        if model_preference:
            parts.append(f"\n[Model preference: {model_preference}]")
        return "\n".join(parts)


# ------------------------------------------------------------------------------------
# Node Mappings
# ------------------------------------------------------------------------------------
NODE_CLASS_MAPPINGS = {
    "PGFX_LogoDesignerStudio": PGFX_LogoDesignerStudio,
    "PGFX_LogoDesignerAgent": PGFX_LogoDesignerAgent,
    "PGFX_LogoDesignerMCPAgent": PGFX_LogoDesignerMCPAgent,
    "PGFX_ImageVectorizer": PGFX_ImageVectorizer,
}
if V3_IO_AVAILABLE:
    NODE_CLASS_MAPPINGS["PGFX_LogoDesignerStudioV3"] = PGFX_LogoDesignerStudioV3
    NODE_CLASS_MAPPINGS["PGFX_ImageVectorizerV3"] = PGFX_ImageVectorizerV3
    NODE_CLASS_MAPPINGS["PGFX_LogoDesignerAgentV3"] = PGFX_LogoDesignerAgentV3

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_LogoDesignerStudio": "PGFX Logo Designer Studio",
    "PGFX_LogoDesignerAgent": "PGFX Logo Designer Agent",
    "PGFX_LogoDesignerMCPAgent": "🎭 PGFX MCP Agent",
    "PGFX_ImageVectorizer": "📐 PGFX Image Vectorizer",
}
if V3_IO_AVAILABLE:
    NODE_DISPLAY_NAME_MAPPINGS["PGFX_LogoDesignerStudioV3"] = "PGFX Logo Designer Studio (V3)"
    NODE_DISPLAY_NAME_MAPPINGS["PGFX_ImageVectorizerV3"] = "📐 PGFX Image Vectorizer (V3)"
    NODE_DISPLAY_NAME_MAPPINGS["PGFX_LogoDesignerAgentV3"] = "PGFX Logo Designer Agent (V3)"
