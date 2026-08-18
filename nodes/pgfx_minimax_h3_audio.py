import torch
import torch.nn.functional as F

from comfy.nested_tensor import NestedTensor


class PromptCrafter_MiniMaxH3AudioLock:
    """Replace an H3 target audio latent and keep it fixed during sampling."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "av_latent": ("LATENT",),
                "audio_vae": ("VAE",),
                "audio": ("AUDIO",),
            }
        }

    RETURN_TYPES = ("LATENT",)
    RETURN_NAMES = ("av_latent",)
    FUNCTION = "lock_audio"
    CATEGORY = "☠️PGFX /MiniMax H3"
    DESCRIPTION = "Encodes input audio into a MiniMax H3 AV latent and keeps its audio stream fixed while the video stream is denoised."

    def lock_audio(self, av_latent, audio_vae, audio):
        samples = av_latent.get("samples")
        if not isinstance(samples, NestedTensor) or len(samples.tensors) < 2:
            raise ValueError("MiniMax H3 Audio Lock requires a joint MiniMax H3 AV latent.")

        waveform = audio.get("waveform") if isinstance(audio, dict) else None
        sample_rate = audio.get("sample_rate") if isinstance(audio, dict) else None
        if waveform is None or sample_rate is None:
            raise ValueError("MiniMax H3 Audio Lock requires an AUDIO input with waveform and sample_rate.")
        if waveform.ndim != 3:
            raise ValueError("MiniMax H3 Audio Lock requires audio shaped [batch, channels, samples].")

        waveform = waveform[:1]
        if waveform.shape[1] == 1:
            waveform = waveform.expand(-1, 2, -1)
        elif waveform.shape[1] < 2:
            raise ValueError("MiniMax H3 Audio Lock requires at least one audio channel.")
        else:
            waveform = waveform[:, :2]

        target_sample_rate = audio_vae.audio_sample_rate
        if sample_rate != target_sample_rate:
            try:
                import torchaudio
            except ImportError as error:
                raise RuntimeError("Resampling H3 audio requires torchaudio in ComfyUI's Python environment.") from error
            waveform = torchaudio.functional.resample(waveform, sample_rate, target_sample_rate)

        video_latent, audio_template = samples.tensors[:2]
        encoded_audio = audio_vae.encode(waveform.movedim(1, -1))
        if encoded_audio.shape[:-1] != audio_template.shape[:-1]:
            raise ValueError("MiniMax H3 Audio Lock requires the MiniMax H3 audio VAE.")
        encoded_audio = encoded_audio.to(device=audio_template.device, dtype=audio_template.dtype)
        target_frames = audio_template.shape[-1]
        if encoded_audio.shape[-1] > target_frames:
            encoded_audio = encoded_audio[..., :target_frames]
        elif encoded_audio.shape[-1] < target_frames:
            encoded_audio = F.pad(encoded_audio, (0, target_frames - encoded_audio.shape[-1]))

        locked = av_latent.copy()
        locked["samples"] = NestedTensor((video_latent, encoded_audio, *samples.tensors[2:]))
        locked["noise_mask"] = NestedTensor((torch.ones_like(video_latent), torch.zeros_like(encoded_audio)))
        return (locked,)


NODE_CLASS_MAPPINGS = {
    "PromptCrafter_MiniMaxH3AudioLock": PromptCrafter_MiniMaxH3AudioLock,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "PromptCrafter_MiniMaxH3AudioLock": "🎵 MiniMax H3 Exact Audio Lock",
}
