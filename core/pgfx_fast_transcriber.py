# Third-party imports
try:
    # Attempt to import all necessary components. An error in any of these
    # indicates the installation is incomplete or has conflicts.
    from transformers import pipeline
    import torch
    INSANELY_FAST_WHISPER_AVAILABLE = True
except (ImportError, ModuleNotFoundError) as e:
    # Catching ModuleNotFoundError as well for broader compatibility.
    print(f"[PromptCrafter] Info: 'insanely-fast-whisper' is not available. Details: {e}")
    INSANELY_FAST_WHISPER_AVAILABLE = False

def transcribe_audio(audio_path, model_size="large-v3", language=None):
    """
    Transcribes an audio file using the insanely-fast-whisper library.

    Returns:
        A tuple containing:
        - full_text (str): The complete transcribed text.
        - timed_segments (list): A list of tuples, where each tuple is (start_time, end_time, text).
        - spectrogram_data: Always None for this implementation.
    """
    if not INSANELY_FAST_WHISPER_AVAILABLE:
        raise ImportError("The 'insanely-fast-whisper' library is not installed. Please install it to use this feature.")

    pipe = pipeline(
        # ADDED: Explicitly define the task for the transformers pipeline
        task="automatic-speech-recognition",
        
        # CHANGED: Explicitly pass the model path via the 'model' keyword argument
        model=f"openai/whisper-{model_size}",
        
        device="cuda:0" if torch.cuda.is_available() else "cpu",
        dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    )

    output = pipe(
        audio_path,
        chunk_length_s=30,
        batch_size=24,
        return_timestamps=True,
        language=language if language and language != "auto-detect" else None,
    )

    timed_segments = [(chunk['timestamp'][0], chunk['timestamp'][1], chunk['text'].strip()) for chunk in output['chunks']]
    full_text = output['text']

    return full_text, timed_segments, None