from pathlib import Path


class PodShortsError(Exception):
    """Base exception for all PodShorts errors."""


class StageError(PodShortsError):
    """Raised when a pipeline stage fails."""

    def __init__(self, stage: str, message: str, cause: Exception | None = None) -> None:
        self.stage = stage
        self.cause = cause
        super().__init__(f"Stage '{stage}' failed: {message}")


class DependencyMissingError(PodShortsError):
    """Raised when a required external dependency is missing."""

    def __init__(self, dependency: str, install_hint: str = "") -> None:
        self.dependency = dependency
        msg = f"Required dependency '{dependency}' is missing."
        if install_hint:
            msg += f" Install with: {install_hint}"
        super().__init__(msg)


class DownloadError(StageError):
    """Raised for private, region-locked, age-gated, or unavailable videos."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        super().__init__("download", f"{reason} (url={url})")


class CacheError(PodShortsError):
    """Raised on cache read/write failures."""


class ConfigError(PodShortsError):
    """Raised on invalid configuration."""


class TranscriptionError(StageError):
    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__("transcribe", message, cause)


class HeatmapParseError(StageError):
    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__("heatmap", message, cause)


class LLMError(StageError):
    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__("score", message, cause)


class FFmpegError(PodShortsError):
    """Raised on FFmpeg subprocess failures."""

    def __init__(self, cmd: list[str], returncode: int, stderr: str) -> None:
        self.cmd = cmd
        self.returncode = returncode
        self.stderr = stderr
        super().__init__(f"FFmpeg exited {returncode}: {stderr[:500]}")
