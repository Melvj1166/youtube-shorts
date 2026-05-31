from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from podshorts.exceptions import DependencyMissingError, FFmpegError
from podshorts.utils.logging import get_logger

logger = get_logger(__name__)


def require_ffmpeg() -> str:
    """Return the ffmpeg binary path, raising DependencyMissingError if absent."""
    result = subprocess.run(
        ["which", "ffmpeg"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise DependencyMissingError("ffmpeg", "brew install ffmpeg")
    return result.stdout.strip()


def has_videotoolbox() -> bool:
    """Return True if ffmpeg supports h264_videotoolbox (Apple Silicon HW encoder)."""
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=False,
    )
    return "h264_videotoolbox" in result.stdout


def run_ffmpeg(args: Sequence[str], description: str = "ffmpeg") -> None:
    """Run ffmpeg with explicit error capture. Raises FFmpegError on non-zero exit."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", *args]
    logger.debug("Running %s: %s", description, " ".join(cmd))

    with subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ) as proc:
        _, stderr_bytes = proc.communicate()
        returncode = proc.returncode

    if returncode != 0:
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        raise FFmpegError(cmd, returncode, stderr)


def probe_duration(video_path: Path) -> float:
    """Return video duration in seconds via ffprobe."""
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise FFmpegError(
            ["ffprobe", str(video_path)],
            result.returncode,
            result.stderr,
        )
    return float(result.stdout.strip())


def extract_audio(
    video_path: Path,
    output_path: Path,
    sample_rate: int = 16000,
    channels: int = 1,
) -> None:
    """Extract audio from video as WAV."""
    run_ffmpeg(
        [
            "-i", str(video_path),
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-vn",
            "-y",
            str(output_path),
        ],
        description="extract_audio",
    )


def extract_segment_audio(
    video_path: Path,
    output_path: Path,
    start: float,
    end: float,
) -> None:
    """Extract a time-range audio segment from a video as AAC."""
    run_ffmpeg(
        [
            "-i", str(video_path),
            "-ss", str(start),
            "-to", str(end),
            "-c:a", "aac",
            "-y",
            str(output_path),
        ],
        description="extract_segment_audio",
    )
