import torch
import torchaudio
import numpy as np
import comfy.samplers
import comfy.sample
import comfy.utils
from comfy.model_management import get_torch_device
from nodes import common_ksampler

# ------------------------------------------------------------------------------------
# Universal Audio-Driven Sampler
# ------------------------------------------------------------------------------------
class PGFX_Studio_Sampler:
    """
    A universal sampler that works with ALL ComfyUI models (SD, SDXL, Flux, Video, Audio)
    and includes optional audio-reactive features.
    
    This uses ComfyUI's standard common_ksampler which automatically handles:
    - Stable Diffusion 1.5, 2.x, SDXL
    - Flux models
    - Video models (LTX-2, Hunyuan Video, CogVideoX, etc.)
    - Audio models (Stable Audio, ACE-Step, etc.)
    - Any other diffusion/flow model that follows ComfyUI's MODEL interface
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "model": ("MODEL",),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
                "steps": ("INT", {"default": 20, "min": 1, "max": 10000}),
                "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0, "step":0.1, "round": 0.01}),
                "sampler_name": (comfy.samplers.KSampler.SAMPLERS, ),
                "scheduler": (comfy.samplers.KSampler.SCHEDULERS, ),
                "positive": ("CONDITIONING", ),
                "negative": ("CONDITIONING", ),
                "latent_image": ("LATENT", ),
                "denoise": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "modality": (["image", "video", "audio", "multimodal"], {"default": "video"}),
                "requires_fixed_frames": ("BOOLEAN", {"default": False}),
                "frame_rule": ("STRING", {"default": "", "tooltip": "e.g., 4n+1, multiple_of_8"}),
            },
            "optional": {
                "audio": ("AUDIO",),
                "audio_reactivity": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 1.0, "step": 0.01, "tooltip": "How strongly the audio modulates the CFG scale."}),
                "frequency_band": (["All", "Bass", "Mid", "Treble"], {"default": "All"}),
            }
        }

    RETURN_TYPES = ("LATENT",)
    FUNCTION = "sample"
    CATEGORY = "☠️PGFX /Studio"

    def _analyze_audio(self, audio, band="All"):
        """Extracts energy levels from the audio waveform using FFT."""
        if audio is None:
            return 0.0
        
        waveform = audio["waveform"]
        sample_rate = audio["sample_rate"]
        
        # Ensure mono
        if waveform.dim() > 1 and waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0)
        elif waveform.dim() > 1:
            waveform = waveform.squeeze(0)

        # Simple FFT-based band energy extraction
        n_fft = 2048
        # Pad if too short
        if waveform.shape[-1] < n_fft:
            padding = n_fft - waveform.shape[-1]
            waveform = torch.nn.functional.pad(waveform, (0, padding))
            
        spectrogram = torch.stft(waveform, n_fft=n_fft, hop_length=512, return_complex=True, window=torch.hann_window(n_fft).to(waveform.device))
        magnitude = torch.abs(spectrogram)
        
        # Frequency bins (approximate for 44.1kHz)
        # Bass: 20-250Hz, Mid: 250-4000Hz, Treble: 4000-20000Hz
        # Bin size = SampleRate / N_FFT ~= 21.5 Hz per bin
        
        if band == "Bass":
            energy = torch.mean(magnitude[1:12, :]) # ~20-250Hz
        elif band == "Mid":
            energy = torch.mean(magnitude[12:186, :]) # ~250-4000Hz
        elif band == "Treble":
            energy = torch.mean(magnitude[186:, :]) # ~4000Hz+
        else:
            energy = torch.mean(magnitude)
            
        # Normalize roughly between 0 and 1
        return torch.clamp(torch.mean(energy) * 10.0, 0.0, 1.0).item()

    def sample(self, model, seed, steps, cfg, sampler_name, scheduler, positive, negative, latent_image, denoise,
               modality, requires_fixed_frames, frame_rule, audio=None, audio_reactivity=0.0, frequency_band="All"):
        """
        Universal sampling function that works with ALL ComfyUI models.
        Optionally modulates CFG based on audio energy.
        
        This function delegates to comfy.samplers.common_ksampler which is the
        universal entry point for ALL model types in ComfyUI. It automatically
        detects the model type and uses the appropriate sampling logic.
        """
        
        # 1. Audio Analysis (Modulates CFG)
        audio_energy = 0.0
        if audio is not None and audio_reactivity > 0:
            try:
                audio_energy = self._analyze_audio(audio, frequency_band)
                # Boost CFG based on energy + reactivity
                # High energy = more defined = higher CFG
                cfg_modulation = audio_energy * audio_reactivity * 2.0 # Scale factor
                cfg += cfg_modulation
                print(f"\033[94m[PromptCrafter] Audio ({frequency_band}): Energy={audio_energy:.2f}, Modulated CFG={cfg:.2f}\033[0m")
            except Exception as e:
                print(f"\033[93m[PromptCrafter] Audio analysis failed: {e}. Proceeding without modulation.\033[0m")

        # 2. Standard ComfyUI Sampling
        # This calls the internal common_ksampler which handles ALL model types:
        # - SD 1.5, 2.x, SDXL (UNet-based)
        # - Flux (DiT-based)
        # - Video models: LTX-2, Hunyuan Video, CogVideoX, WanVideo, etc.
        # - Audio models: Stable Audio, ACE-Step, etc.
        # The model object itself contains all the necessary information about
        # its architecture, and common_ksampler routes to the correct sampler.
        try:
            return common_ksampler(
                model, seed, steps, cfg, sampler_name, scheduler, positive, negative, latent_image, denoise=denoise
            )
        except Exception as e:
            # Provide detailed error for debugging
            raise RuntimeError(f"Universal Sampler failed: {e}\nModel type: {type(model)}\nThis sampler supports ALL ComfyUI models. If you see this error, the model itself may be corrupted or incompatible with ComfyUI.")

# ------------------------------------------------------------------------------------
# Node Registration
# ------------------------------------------------------------------------------------
NODE_CLASS_MAPPINGS = {
    "PGFX_Studio_Sampler": PGFX_Studio_Sampler
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PGFX_Studio_Sampler": "???? Legacy ??? Studio Sampler (Universal)"
}
