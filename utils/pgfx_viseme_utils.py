import os
import re
import numpy as np
import torch
import traceback
from g2p_en import G2p
from PIL import Image, ImageDraw

# --- GLOBAL CACHE FOR G2P ---
_G2P_INSTANCE = None

def get_g2p():
    """Returns a cached instance of G2p."""
    global _G2P_INSTANCE
    if _G2P_INSTANCE is None:
        try:
            import nltk
            g2p_resources = [
                ('corpora', 'cmudict'),
                ('taggers', 'averaged_perceptron_tagger'),
                ('taggers', 'averaged_perceptron_tagger_eng'),
            ]
            for subdir, data in g2p_resources:
                try:
                    nltk.data.find(f'{subdir}/{data}')
                except LookupError:
                    try:
                        nltk.download(data, quiet=True)
                    except Exception:
                        pass
            _G2P_INSTANCE = G2p()
        except Exception as e:
            print(f"[PromptCrafter] Error initializing G2p: {e}")
            return None
    return _G2P_INSTANCE

# --- VISEME DATA AND HELPERS ---
CX, CY = 0.5, 0.7

VISEME_TO_LANDMARK_MAP = {
    "SIL": [(CX-0.15, CY-0.02), (CX-0.12, CY-0.01), (CX-0.06, CY+0.00), (CX+0.00, CY+0.00), (CX+0.06, CY+0.00), (CX+0.12, CY-0.01), (CX+0.15, CY-0.02), (CX+0.12, CY-0.01), (CX+0.06, CY+0.00), (CX+0.00, CY+0.00), (CX-0.06, CY+0.00), (CX-0.12, CY-0.01), (CX-0.12, CY-0.01), (CX-0.06, CY+0.00), (CX+0.00, CY+0.00), (CX+0.06, CY+0.00), (CX+0.12, CY-0.01), (CX+0.06, CY+0.00), (CX+0.00, CY+0.00), (CX-0.06, CY+0.00)],
    "AA": [(CX-0.16, CY-0.02), (CX-0.12, CY-0.04), (CX-0.06, CY-0.05), (CX+0.00, CY-0.05), (CX+0.06, CY-0.05), (CX+0.12, CY-0.04), (CX+0.16, CY-0.02), (CX+0.12, CY+0.08), (CX+0.06, CY+0.10), (CX+0.00, CY+0.10), (CX-0.06, CY+0.10), (CX-0.12, CY+0.08), (CX-0.12, CY-0.02), (CX-0.06, CY-0.03), (CX+0.00, CY-0.03), (CX+0.06, CY-0.03), (CX+0.12, CY-0.02), (CX+0.06, CY+0.07), (CX+0.00, CY+0.07), (CX-0.06, CY+0.07)],
    "EE": [(CX-0.20, CY-0.01), (CX-0.15, CY-0.02), (CX-0.07, CY-0.02), (CX+0.00, CY-0.02), (CX+0.07, CY-0.02), (CX+0.15, CY-0.02), (CX+0.20, CY-0.01), (CX+0.15, CY+0.02), (CX+0.07, CY+0.02), (CX+0.00, CY+0.02), (CX-0.07, CY+0.02), (CX-0.15, CY+0.02), (CX-0.15, CY-0.01), (CX-0.07, CY-0.01), (CX+0.00, CY-0.01), (CX+0.07, CY-0.01), (CX+0.15, CY-0.01), (CX+0.07, CY+0.01), (CX+0.00, CY+0.01), (CX-0.07, CY+0.01)],
    "OO": [(CX-0.08, CY-0.02), (CX-0.06, CY-0.04), (CX-0.03, CY-0.05), (CX+0.00, CY-0.05), (CX+0.03, CY-0.05), (CX+0.06, CY-0.04), (CX+0.08, CY-0.02), (CX+0.06, CY-0.04), (CX+0.03, CY+0.05), (CX+0.00, CY+0.05), (CX-0.03, CY+0.05), (CX-0.06, CY+0.04), (CX-0.05, CY-0.02), (CX-0.03, CY-0.03), (CX+0.00, CY-0.03), (CX+0.03, CY-0.03), (CX+0.05, CY-0.02), (CX+0.03, CY+0.03), (CX+0.00, CY+0.03), (CX-0.03, CY+0.03)],
    "S_L": [(CX-0.18, CY-0.01), (CX-0.14, CY-0.02), (CX-0.07, CY-0.02), (CX+0.00, CY-0.02), (CX+0.07, CY-0.02), (CX+0.14, CY-0.02), (CX+0.18, CY-0.01), (CX+0.14, CY+0.02), (CX+0.07, CY+0.02), (CX+0.00, CY+0.02), (CX-0.07, CY+0.02), (CX-0.14, CY+0.02), (CX-0.14, CY-0.01), (CX-0.07, CY-0.01), (CX+0.00, CY-0.01), (CX+0.07, CY-0.01), (CX+0.14, CY-0.01), (CX+0.07, CY+0.01), (CX+0.00, CY+0.01), (CX-0.07, CY+0.01)],
    "DENTAL": [(CX-0.17, CY-0.02), (CX-0.13, CY-0.03), (CX-0.07, CY-0.03), (CX+0.00, CY-0.03), (CX+0.07, CY-0.03), (CX+0.13, CY-0.03), (CX+0.17, CY-0.02), (CX+0.13, CY+0.03), (CX+0.07, CY+0.03), (CX+0.00, CY+0.03), (CX-0.07, CY+0.03), (CX-0.13, CY+0.03), (CX-0.13, CY-0.01), (CX-0.07, CY-0.01), (CX+0.00, CY-0.01), (CX+0.07, CY-0.01), (CX+0.13, CY-0.01), (CX+0.07, CY+0.01), (CX+0.00, CY+0.01), (CX-0.07, CY+0.01)],
    "LABIODENTAL": [(CX-0.17, CY-0.02), (CX-0.13, CY-0.03), (CX-0.07, CY-0.03), (CX+0.00, CY-0.03), (CX+0.07, CY-0.03), (CX+0.13, CY-0.03), (CX+0.17, CY-0.02), (CX+0.13, CY+0.02), (CX+0.07, CY+0.01), (CX+0.00, CY+0.01), (CX-0.07, CY+0.01), (CX-0.13, CY+0.02), (CX-0.13, CY-0.01), (CX-0.07, CY-0.01), (CX+0.00, CY-0.01), (CX+0.07, CY-0.01), (CX+0.13, CY-0.01), (CX+0.07, CY-0.00), (CX+0.00, CY-0.00), (CX-0.07, CY-0.00)],
    "O_SH": [(CX-0.15, CY-0.01), (CX-0.12, CY-0.03), (CX-0.06, CY-0.04), (CX+0.00, CY-0.04), (CX+0.06, CY-0.04), (CX+0.12, CY-0.03), (CX+0.15, CY-0.01), (CX+0.12, CY+0.04), (CX+0.06, CY+0.06), (CX+0.00, CY+0.06), (CX-0.06, CY+0.06), (CX-0.12, CY+0.04), (CX-0.11, CY-0.01), (CX-0.06, CY-0.02), (CX+0.00, CY-0.02), (CX+0.06, CY-0.02), (CX+0.11, CY-0.01), (CX+0.06, CY+0.03), (CX+0.00, CY+0.03), (CX-0.06, CY+0.03)],
}

PHONEME_TO_VISEME_MAP = {
    'SIL': {'viseme': 'SIL', 'weight': 1.0}, 
    'F': {'viseme': 'LABIODENTAL', 'weight': 0.2}, 
    'V': {'viseme': 'LABIODENTAL', 'weight': 0.2}, 
    'TH': {'viseme': 'DENTAL', 'weight': 0.2}, 
    'DH': {'viseme': 'DENTAL', 'weight': 0.2}, 
    'P': {'viseme': 'SIL', 'weight': 0.15}, 
    'B': {'viseme': 'SIL', 'weight': 0.15}, 
    'M': {'viseme': 'SIL', 'weight': 0.4}, 
    'AA': {'viseme': 'AA', 'weight': 0.8}, 
    'AE': {'viseme': 'AA', 'weight': 0.8}, 
    'AH': {'viseme': 'AA', 'weight': 0.7}, 
    'AO': {'viseme': 'AA', 'weight': 0.9}, 
    'AW': {'viseme': 'AA', 'weight': 0.9}, 
    'AY': {'viseme': 'AA', 'weight': 0.9}, 
    'IY': {'viseme': 'EE', 'weight': 0.8}, 
    'IH': {'viseme': 'EE', 'weight': 0.6}, 
    'EH': {'viseme': 'EE', 'weight': 0.7}, 
    'EY': {'viseme': 'EE', 'weight': 0.8}, 
    'OW': {'viseme': 'OO', 'weight': 0.9}, 
    'OY': {'viseme': 'OO', 'weight': 0.9}, 
    'UW': {'viseme': 'OO', 'weight': 1.0}, 
    'UH': {'viseme': 'OO', 'weight': 0.6}, 
    'L': {'viseme': 'S_L', 'weight': 0.3}, 
    'S': {'viseme': 'S_L', 'weight': 0.3}, 
    'Z': {'viseme': 'S_L', 'weight': 0.3}, 
    'R': {'viseme': 'OO', 'weight': 0.4}, 
    'W': {'viseme': 'OO', 'weight': 0.4}, 
    'Y': {'viseme': 'EE', 'weight': 0.4}, 
    'CH': {'viseme': 'O_SH', 'weight': 0.3}, 
    'JH': {'viseme': 'O_SH', 'weight': 0.3}, 
    'SH': {'viseme': 'O_SH', 'weight': 0.3}, 
    'ZH': {'viseme': 'O_SH', 'weight': 0.3}, 
    'G': {'viseme': 'AA', 'weight': 0.2}, 
    'K': {'viseme': 'AA', 'weight': 0.2}, 
    'NG': {'viseme': 'AA', 'weight': 0.3}, 
    'N': {'viseme': 'S_L', 'weight': 0.3}, 
    'HH': {'viseme': 'AA', 'weight': 0.2}
}

EMOTION_PROFILES = {
    "HAPPY": {"keywords": ["happy", "joy", "smile", "laugh", "bright", "love", "vibrant", "glee"], "modifier": [0.0, -0.015]},
    "SAD": {"keywords": ["sad", "cry", "tear", "grief", "sorrow", "lonely", "down", "blue"], "modifier": [0.0, 0.015]},
    "ANGRY": {"keywords": ["angry", "rage", "fury", "shout", "hate", "fight", "protest"], "modifier": [0.0, 0.005]},
    "SURPRISED": {"keywords": ["wow", "oh", "omg", "surprise", "shocked", "gasp"], "modifier": [0.0, 0.0]}
}

COARTICULATION_PROFILES = {
    "Default": {"influence": 0.5, "smoothing": 2, "weights": (0.15, 0.70, 0.15)},
    "Singing": {"influence": 0.7, "smoothing": 3, "weights": (0.10, 0.80, 0.10)},
    "Fast Speech": {"influence": 0.3, "smoothing": 1, "weights": (0.20, 0.60, 0.20)},
    "None": {"influence": 0.0, "smoothing": 0, "weights": (0.00, 1.00, 0.00)},
}

def gaussian_smooth_landmarks(landmarks_series, sigma=1.0):
    """
    Applies a 1D Gaussian temporal filter using pure numpy to eliminate jitter.
    landmarks_series: [total_frames, num_landmarks, 2]
    """
    if len(landmarks_series) < 3 or sigma <= 0:
        return landmarks_series
        
    series_np = np.array(landmarks_series) # [F, L, 2]
    f_count = series_np.shape[0]
    
    # 1. Create Gaussian Kernel
    radius = int(3 * sigma)
    x = np.arange(-radius, radius + 1)
    kernel = np.exp(-(x**2) / (2 * sigma**2))
    kernel = kernel / kernel.sum()
    
    # 2. Apply convolution along temporal axis (axis 0)
    smoothed = np.copy(series_np)
    for l in range(series_np.shape[1]): # For each landmark
        for d in range(2): # For X and Y
            # Pad ends to prevent "black bars" / closing mouth at start/end
            signal = series_np[:, l, d]
            padded = np.pad(signal, radius, mode='edge')
            smoothed[:, l, d] = np.convolve(padded, kernel, mode='valid')
            
    return smoothed.tolist()

def get_mouth_mask(landmarks, width, height, padding=0.2):
    """
    Generates a lip-focused mask based on landmark bounding box.
    """
    pts = np.array([(x * width, y * height) for x, y in landmarks])
    min_x, min_y = np.min(pts, axis=0)
    max_x, max_y = np.max(pts, axis=0)
    
    w = max_x - min_x
    h = max_y - min_y
    
    # Add padding
    min_x = max(0, min_x - w * padding)
    min_y = max(0, min_y - h * padding)
    max_x = min(width, max_x + w * padding)
    max_y = min(height, max_y + h * padding)
    
    mask = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle([min_x, min_y, max_x, max_y], fill=255)
    return mask

def calculate_dynamic_intensity(frame_time, word_start, word_end):
    """Calculates sinusoidal intensity for visemes during a word's duration."""
    if word_start is None or word_end is None or word_end <= word_start:
        return 1.0
    word_duration = word_end - word_start
    progress = max(0.0, min(1.0, (frame_time - word_start) / word_duration))
    dynamic_multiplier = (1.0 - 0.2) * np.sin(progress * np.pi) + 0.2
    return min(float(dynamic_multiplier), 1.0)

def blend_landmarks(prev_lm, curr_lm, next_lm, profile_name="Singing"):
    """Blends landmarks based on coarticulation weights."""
    profile = COARTICULATION_PROFILES.get(profile_name, COARTICULATION_PROFILES["Default"])
    w_prev, w_curr, w_next = profile.get("weights", (0.15, 0.70, 0.15))
    
    blended = []
    for i in range(len(curr_lm)):
        p_pt = prev_lm[i] if i < len(prev_lm) else curr_lm[i]
        n_pt = next_lm[i] if i < len(next_lm) else curr_lm[i]
        x = (p_pt[0] * w_prev) + (curr_lm[i][0] * w_curr) + (n_pt[0] * w_next)
        y = (p_pt[1] * w_prev) + (curr_lm[i][1] * w_curr) + (n_pt[1] * w_next)
        blended.append((x, y))
    return blended

def apply_emotion_modifier(points, emotion_name, intensity, width, height):
    """Applies emotional deformation to viseme points."""
    profile = EMOTION_PROFILES.get(emotion_name)
    if not profile or intensity <= 0:
        return points
    
    ndx, ndy = profile["modifier"]
    dx, dy = ndx * intensity * width, ndy * intensity * height
    
    new_points = list(points)
    # Corners of the mouth (0 and 6) and surrounding points
    for i in range(len(points)):
        if i in [0, 6]: 
            new_points[i] = (points[i][0] + dx, points[i][1] + dy)
        elif i in [1, 5, 7, 11]: 
            new_points[i] = (points[i][0] + dx * 0.5, points[i][1] + dy * 0.5)
    return new_points

def draw_landmarks_helper(draw, landmarks_norm, width, height, draw_style, dot_color, line_color, fill_color, dot_size, line_thickness, emotion, emotion_intensity):
    """Draws viseme landmarks onto a PIL image."""
    outer_lip_indices = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 0]
    inner_lip_indices = [12, 13, 14, 15, 16, 17, 18, 19, 12]
    
    points = [(nx * width, ny * height) for nx, ny in landmarks_norm]
    
    if emotion != "NEUTRAL" and emotion_intensity > 0:
        points = apply_emotion_modifier(points, emotion, emotion_intensity, width, height)
        
    outer_lip_points = [points[i] for i in outer_lip_indices]
    inner_lip_points = [points[i] for i in inner_lip_indices]
    
    if draw_style in ["Outline", "Filled Outline"]:
        draw.line(outer_lip_points, fill=line_color, width=line_thickness, joint="curve")
        draw.line(inner_lip_points, fill=line_color, width=line_thickness, joint="curve")
    if draw_style == "Filled Outline": 
        draw.polygon(inner_lip_points, fill=fill_color)
    if draw_style == "Dots":
        for x, y in points: 
            draw.ellipse((x - dot_size // 2, y - dot_size // 2, x + dot_size // 2, y + dot_size // 2), fill=dot_color)

def pil_to_tensor(images_pil):
    """Converts a PIL image or list of images to a PyTorch tensor [B, H, W, C]."""
    if not isinstance(images_pil, list):
        images_pil = [images_pil]
    images_np = [np.array(img).astype(np.float32) / 255.0 for img in images_pil]
    return torch.stack([torch.from_numpy(img) for img in images_np])

def tensor_to_pil(tensor):
    """Converts a PyTorch tensor [B, H, W, C] to a list of PIL images."""
    if tensor is None or tensor.numel() == 0:
        return []
    images_np = (tensor.cpu().numpy() * 255).astype(np.uint8)
    return [Image.fromarray(img) for img in images_np]
