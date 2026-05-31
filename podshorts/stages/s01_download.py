from podshorts.exceptions import DownloadError  # noqa: F401
from podshorts.types import Context, DownloadInput, DownloadOutput


def run(input: DownloadInput, ctx: Context) -> DownloadOutput:
    # TODO: Step 2 — use yt-dlp Python API to download best mp4 <=1080p
    # and extract 16kHz mono WAV for Whisper. Cache to cache/<video_id>/video.mp4.
    raise NotImplementedError("s01_download not yet implemented")
