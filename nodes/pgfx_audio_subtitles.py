import torch
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import os
import re

def parse_srt_to_segments(srt_content):
    """Converts an SRT formatted string into a list of timed segments."""
    segments = []
    # This regex handles multiline subtitles and variations in line endings
    pattern = re.compile(r'(\d+)\s*[\r\n]+(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*[\r\n]+([\s\S]*?)(?=\n\n|\Z)', re.MULTILINE) 
    
    def time_to_seconds(t):
        h, m, s_ms = t.split(':')
        s, ms = s_ms.split(',')
        return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000

    for match in pattern.finditer(srt_content):
        start_time = time_to_seconds(match.group(2))
        end_time = time_to_seconds(match.group(3))
        text = match.group(4).strip().replace('\n', ' ')
        segments.append({'start': start_time, 'end': end_time, 'text': text})
    return segments

class PromptCrafter_SubtitleStyler:
    DESCRIPTION = "Burns subtitles onto video frames using timed text data and customizable styling."

    @classmethod
    def INPUT_TYPES(cls):
        # On Windows, the default fonts are usually in C:/Windows/Fonts
        # On Linux, they are in /usr/share/fonts/
        # On macOS, /System/Library/Fonts/
        # We provide a common default, but users should be encouraged to use full paths.
        default_font = "arial.ttf"
        if os.name != 'nt':
             # A common font on Linux
            if os.path.exists("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
                 default_font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            else: # A common font on macOS
                 default_font = "/System/Library/Fonts/Supplemental/Arial.ttf"


        return {
            "required": {
                "images": ("IMAGE",),
                "fps": ("FLOAT", {"default": 24.0, "min": 1.0}),
                # Styling
                "font_name": ("STRING", {"default": default_font, "tooltip": "Name of the font file (e.g., arial.ttf) or full path to a .ttf or .otf file."}),
                "font_size": ("INT", {"default": 48, "min": 8, "max": 512}),
                "font_color": ("STRING", {"default": "#FFFFFF"}),
                "position_y": ("INT", {"default": 90, "min": 0, "max": 100, "step": 1, "tooltip": "Vertical position in % from the top of the frame."}),
                "align": (["center", "left", "right"],),
                "stroke_width": ("INT", {"default": 2, "min": 0, "max": 20}),
                "stroke_color": ("STRING", {"default": "#000000"}),
            },
            "optional": {
                "meta_dict": ("DICT", {"tooltip": "Connect the 'meta' output from an Audio Splitter. This takes priority over srt_content."} ),
                "srt_content": ("STRING", {"multiline": True, "forceInput": True, "tooltip": "SRT formatted text to burn as subtitles."}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "burn_subtitles"
    CATEGORY = "☠️PGFX🏴‍☠️ /Video"

    def burn_subtitles(self, images, fps, font_name, font_size, font_color, position_y, align, stroke_width, stroke_color, meta_dict=None, srt_content=None):
        
        # 1. Determine subtitle source and parse it
        timed_segments = []
        if meta_dict and "word_segments" in meta_dict:
            word_segments = meta_dict.get("word_segments", [])
            if word_segments:
                print(f"[SubtitleStyler] Using 'meta_dict' with {len(word_segments)} word segments.")
                # Group words into lines for display. A simple heuristic is used here.
                current_line_words = []
                line_start_time = None
                for i, word_info in enumerate(word_segments):
                    word_text = word_info.get('word')
                    if not word_text or 'start' not in word_info or 'end' not in word_info: continue

                    if line_start_time is None: line_start_time = word_info['start']
                    
                    current_line_words.append(word_text.strip())
                    
                    is_last_word = (i == len(word_segments) - 1)
                    if len(current_line_words) >= 8 or is_last_word or word_text.strip().endswith(('.', '?', '!')):
                        timed_segments.append({
                            "start": line_start_time,
                            "end": word_info['end'],
                            "text": " ".join(current_line_words)
                        })
                        current_line_words = []
                        line_start_time = None

        elif srt_content:
            print(f"[SubtitleStyler] Using 'srt_content'.")
            timed_segments = parse_srt_to_segments(srt_content)

        if not timed_segments:
            print("[SubtitleStyler] No valid subtitle data provided. Returning original images.")
            return (images,)

        # 2. Load font
        try:
            font = ImageFont.truetype(font_name, font_size)
        except IOError:
            print(f"[SubtitleStyler] Font '{font_name}' not found. Using default font.")
            font = ImageFont.load_default()

        # 3. Process images
        output_frames = []
        total_frames = images.shape[0]
        for i in range(total_frames):
            current_time = i / fps
            
            text_to_display = ""
            for segment in timed_segments:
                if segment['start'] <= current_time < segment['end']:
                    text_to_display = segment['text']
                    break
            
            frame_tensor = images[i]
            img_np = (frame_tensor.cpu().numpy() * 255).astype(np.uint8)
            pil_image = Image.fromarray(img_np)
            draw = ImageDraw.Draw(pil_image)

            if text_to_display:
                # Get text bounding box for accurate positioning
                try:
                    # Pillow >= 10.0.0
                    bbox = draw.textbbox((0, 0), text_to_display, font=font, stroke_width=stroke_width)
                    text_width = bbox[2] - bbox[0]
                    text_height = bbox[3] - bbox[1]
                except AttributeError:
                    # Fallback for older Pillow
                    text_width, text_height = draw.textsize(text_to_display, font=font)

                img_width, img_height = pil_image.size
                
                y = (img_height * position_y / 100) - (text_height / 2)
                
                if align == "center":
                    x = (img_width - text_width) / 2
                elif align == "left":
                    x = img_width * 0.05 # 5% margin
                else: # right
                    x = img_width * 0.95 - text_width
                
                draw.text((x, y), text_to_display, font=font, fill=font_color, stroke_width=stroke_width, stroke_fill=stroke_color)

            out_np = np.array(pil_image).astype(np.float32) / 255.0
            output_frames.append(torch.from_numpy(out_np))

        print(f"[SubtitleStyler] Subtitles burned onto {len(output_frames)} frames.")
        return (torch.stack(output_frames),)

NODE_CLASS_MAPPINGS = {
    "PromptCrafter_SubtitleStyler": PromptCrafter_SubtitleStyler
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_SubtitleStyler": "📝 Subtitle Styler"
}
