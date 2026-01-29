import os
import torch
import torchaudio
import math

class PromptCrafter_AudioSplitter_v2:
    """
    V2 of the audio splitter. Takes an audio input and splits it into 16 scenes based on a duration.
    It processes the audio in sets, allowing to process long audio files chunk by chunk.
    This node is inspired by the audio splitting logic in VRGDG's HumoAutomation nodes.
    """
    RETURN_TYPES = ("DICT", "FLOAT", "INT", "INT") + tuple(["AUDIO"] * 16)
    RETURN_NAMES = ("meta", "total_duration", "total_sets", "set_index") + tuple([f"audio_{i}" for i in range(1, 17)])
    FUNCTION = "split_audio"
    CATEGORY = "PromptCrafter/Audio"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "scene_duration": ("FLOAT", {"default": 4.0, "min": 0.1, "max": 60.0, "step": 0.1}),
                "set_index": ("INT", {"default": 0, "min": 0}),
                "save_chunks": ("BOOLEAN", {"default": False}),
                "output_path": ("STRING", {"default": "audio_chunks"}),
            }
        }

    def split_audio(self, audio, scene_duration, set_index, save_chunks, output_path):
        # 1. Setup and Validation
        if "waveform" not in audio or "sample_rate" not in audio:
            raise ValueError("Input 'audio' is not a valid audio dictionary.")
            
        waveform = audio["waveform"]
        sample_rate = audio["sample_rate"]
        
        if waveform.ndim == 2:
            waveform = waveform.unsqueeze(0)

        total_samples = waveform.shape[-1]
        total_duration = total_samples / sample_rate
        
        scene_count = 16
        
        # 2. Calculations
        samples_per_scene = int(scene_duration * sample_rate)
        total_scenes = math.ceil(total_samples / samples_per_scene) if samples_per_scene > 0 else 0
        total_sets = math.ceil(total_scenes / scene_count) if scene_count > 0 else 0
        
        offset_samples = set_index * scene_count * samples_per_scene

        # 3. Audio Splitting
        segments = []
        durations = []
        for i in range(scene_count):
            start_sample = offset_samples + i * samples_per_scene
            end_sample = start_sample + samples_per_scene
            
            if start_sample >= total_samples:
                # This scene is entirely past the end of the audio, so it's pure silence
                segment_waveform = torch.zeros((1, 1, samples_per_scene), dtype=waveform.dtype, device=waveform.device)
                durations.append(scene_duration)
            else:
                # This scene is at least partially in the audio
                clamped_end_sample = min(end_sample, total_samples)
                segment_waveform = waveform[..., start_sample:clamped_end_sample].clone()
                
                # Pad if the segment is shorter than a full scene
                current_length = segment_waveform.shape[-1]
                if current_length < samples_per_scene:
                    padding = samples_per_scene - current_length
                    segment_waveform = torch.nn.functional.pad(segment_waveform, (0, padding))
                
                durations.append(current_length / sample_rate)

            segments.append({"waveform": segment_waveform, "sample_rate": sample_rate})

        # 4. Save Chunks (if enabled)
        if save_chunks:
            if not os.path.exists(output_path):
                os.makedirs(output_path)
            for i, seg in enumerate(segments):
                chunk_filename = f"set_{set_index:03d}_scene_{i+1:02d}.wav"
                chunk_filepath = os.path.join(output_path, chunk_filename)
                torchaudio.save(chunk_filepath, seg["waveform"].cpu(), sample_rate)
                
        # 5. Prepare Metadata
        meta = {
            "total_duration": total_duration,
            "total_sets": total_sets,
            "set_index": set_index,
            "scene_duration": scene_duration,
            "scenes_in_this_set": len(segments),
            "durations_this_set": durations,
        }

        # 6. Return all outputs
        return (meta, total_duration, total_sets, set_index) + tuple(segments)

NODE_CLASS_MAPPINGS = {
    "PromptCrafter_AudioSplitter_v2": PromptCrafter_AudioSplitter_v2
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_AudioSplitter_v2": "Audio Splitter v2"
}
