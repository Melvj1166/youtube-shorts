from __future__ import annotations

from pathlib import Path

import yt_dlp

from podshorts.exceptions import DownloadError, StageError
from podshorts.types import Context, DownloadInput, DownloadOutput, VideoMetadata
from podshorts.utils.ffmpeg import extract_audio


def run(input: DownloadInput, ctx: Context) -> DownloadOutput:
    logger = ctx.logger

    # --- extract info first (no download) to get video_id for cache check ---
    try:
        info = _extract_info(input.url)
    except yt_dlp.utils.DownloadError as exc:
        msg = str(exc).lower()
        if any(k in msg for k in ("private", "age", "region", "unavailable", "not available")):
            raise DownloadError(input.url, str(exc)) from exc
        raise StageError("download", str(exc), exc) from exc

    video_id: str = info["id"]
    video_dir = ctx.cache_dir / video_id
    video_dir.mkdir(parents=True, exist_ok=True)

    video_path = video_dir / "video.mp4"
    audio_path = video_dir / "audio.wav"

    # --- download video if not cached ---
    if video_path.exists() and not ctx.config.force_rerun:
        logger.info("Cache hit: %s (video)", video_id)
    else:
        logger.info("Downloading video %s", video_id)
        _download_video(input.url, video_path)

    # --- extract audio if not cached ---
    if audio_path.exists() and not ctx.config.force_rerun:
        logger.info("Cache hit: %s (audio)", video_id)
    else:
        logger.info("Extracting 16kHz mono WAV for %s", video_id)
        extract_audio(video_path, audio_path, sample_rate=16000, channels=1)

    metadata = VideoMetadata(
        video_id=video_id,
        title=info.get("title", ""),
        duration_seconds=float(info.get("duration") or 0),
        uploader=info.get("uploader") or info.get("channel") or "",
        view_count=int(info.get("view_count") or 0),
        upload_date=info.get("upload_date") or "",
        description=info.get("description") or "",
        chapters=info.get("chapters") or [],
    )

    return DownloadOutput(
        video_path=video_path,
        audio_path=audio_path,
        metadata=metadata,
    )


def _extract_info(url: str) -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _download_video(url: str, output_path: Path) -> None:
    # Download best mp4 <= 1080p; fall back to bestvideo+bestaudio merge if needed
    opts = {
        "format": "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best[height<=1080]",
        "outtmpl": str(output_path),
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        # Overwrite if force_rerun already removed the file
        "overwrites": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            ydl.download([url])
        except yt_dlp.utils.DownloadError as exc:
            msg = str(exc).lower()
            if any(k in msg for k in ("private", "age", "region", "unavailable", "not available")):
                raise DownloadError(url, str(exc)) from exc
            raise StageError("download", str(exc), exc) from exc
