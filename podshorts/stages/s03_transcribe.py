from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from podshorts.exceptions import TranscriptionError
from podshorts.types import Context, TranscribeInput, TranscribeOutput, Word
from podshorts.utils.cache import cache_exists, cache_read, cache_write

_CACHE_STAGE = "transcribe"


def run(input: TranscribeInput, ctx: Context) -> TranscribeOutput:
    logger = ctx.logger

    if cache_exists(ctx.cache_dir, ctx.video_id, _CACHE_STAGE) and not ctx.config.force_rerun:
        logger.info("Cache hit: transcription for %s", ctx.video_id)
        return _load_from_cache(ctx)

    logger.info("Transcribing %s with faster-whisper %s", ctx.video_id, ctx.config.whisper_model)
    words = _transcribe(input.audio_path, ctx)

    if ctx.config.enable_diarization:
        logger.info("Running speaker diarization")
        words = _apply_diarization(input.audio_path, words, ctx)

    cache_write(ctx.cache_dir, ctx.video_id, _CACHE_STAGE, [asdict(w) for w in words])
    logger.info("Transcription complete: %d words", len(words))
    return TranscribeOutput(words=words)


def _transcribe(audio_path: Path, ctx) -> list[Word]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptionError("faster-whisper not installed", exc) from exc

    try:
        model = WhisperModel(
            ctx.config.whisper_model,
            device="auto",
            compute_type=ctx.config.whisper_compute_type,
        )
        segments, info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        ctx.logger.info(
            "Detected language: %s (%.0f%% confidence)",
            info.language,
            info.language_probability * 100,
        )
    except Exception as exc:
        raise TranscriptionError(str(exc), exc) from exc

    words: list[Word] = []
    for segment in segments:
        if segment.words is None:
            continue
        for w in segment.words:
            words.append(Word(text=w.word, start=w.start, end=w.end))

    return words


def _apply_diarization(audio_path: Path, words: list[Word], ctx) -> list[Word]:
    try:
        from pyannote.audio import Pipeline
    except ImportError as exc:
        raise TranscriptionError(
            "pyannote.audio not installed — install with: pip install 'podshorts[diarization]'",
            exc,
        ) from exc

    try:
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
        diarization = pipeline(str(audio_path))
    except Exception as exc:
        ctx.logger.warning("Diarization failed, skipping: %s", exc)
        return words

    # Map each word to a speaker by timestamp overlap
    updated: list[Word] = []
    for word in words:
        mid = (word.start + word.end) / 2.0
        speaker = _speaker_at(diarization, mid)
        updated.append(Word(text=word.text, start=word.start, end=word.end, speaker_id=speaker))
    return updated


def _speaker_at(diarization, timestamp: float) -> str | None:
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        if turn.start <= timestamp <= turn.end:
            return speaker
    return None


def _load_from_cache(ctx) -> TranscribeOutput:
    raw = cache_read(ctx.cache_dir, ctx.video_id, _CACHE_STAGE)
    words = [
        Word(
            text=w["text"],
            start=float(w["start"]),
            end=float(w["end"]),
            speaker_id=w.get("speaker_id"),
        )
        for w in raw
    ]
    ctx.logger.info("Loaded %d words from cache", len(words))
    return TranscribeOutput(words=words)
