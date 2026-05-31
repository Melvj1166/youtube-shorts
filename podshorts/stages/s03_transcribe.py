from podshorts.types import Context, TranscribeInput, TranscribeOutput


def run(input: TranscribeInput, ctx: Context) -> TranscribeOutput:
    # TODO: Step 4 — use faster-whisper large-v3, device=auto (Metal on M4),
    # compute_type=int8, word_timestamps=True. Optional pyannote diarization.
    raise NotImplementedError("s03_transcribe not yet implemented")
