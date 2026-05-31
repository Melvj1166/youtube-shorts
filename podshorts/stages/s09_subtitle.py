from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from podshorts.types import Context, SubtitleInput, SubtitleOutput, Word
from podshorts.utils.ffmpeg import extract_segment_audio, run_ffmpeg

_WORDS_PER_LINE = 3
_FONT_SIZE = 72
_OUTLINE_WIDTH = 4
_SUB_Y_FRAC = 0.75     # vertical position: 75% down
_COLOR_WHITE = (255, 255, 255, 255)
_COLOR_YELLOW = (255, 215, 0, 255)
_COLOR_BLACK = (0, 0, 0, 255)
_FONT_NAMES = ["Inter", "Arial", "Helvetica", "DejaVuSans", "FreeSans"]


@dataclass
class _WordEvent:
    start: float
    end: float
    line_words: list[str]      # all words in this display group
    highlight_idx: int         # which word is active


def run(input: SubtitleInput, ctx: Context) -> SubtitleOutput:
    logger = ctx.logger
    seg_id = input.cropped_path.stem.replace("_silent", "")

    sub_dir = ctx.cache_dir / ctx.video_id / "subtitled"
    sub_dir.mkdir(parents=True, exist_ok=True)

    audio_path = sub_dir / f"{seg_id}_audio.aac"
    video_nosound = sub_dir / f"{seg_id}_subbed_silent.mp4"
    output_path = sub_dir / f"{seg_id}_subtitled.mp4"

    # Extract audio from source
    logger.info("Extracting audio %.2fs–%.2fs", input.segment_start, input.segment_end)
    extract_segment_audio(
        input.source_video_path,
        audio_path,
        start=input.segment_start,
        end=input.segment_end,
    )

    # Build word events
    words = input.segment_words
    if words:
        t0 = words[0].start
        rel_words = [Word(text=w.text, start=w.start - t0, end=w.end - t0) for w in words]
    else:
        rel_words = []

    events = _build_events(rel_words)
    logger.info("Subtitle events: %d (from %d words)", len(events), len(words))

    # Burn subtitles frame-by-frame via Pillow
    font = _load_font(_FONT_SIZE)
    _burn_subtitles(input.cropped_path, video_nosound, events, font, logger)

    # Mux audio
    logger.info("Muxing audio into subtitled video")
    run_ffmpeg(
        [
            "-i", str(video_nosound),
            "-i", str(audio_path),
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "128k",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            "-y",
            str(output_path),
        ],
        description=f"mux_audio_{seg_id}",
    )

    logger.info("Subtitled output: %s", output_path)
    return SubtitleOutput(subtitled_path=output_path)


def _build_events(words: list[Word]) -> list[_WordEvent]:
    events: list[_WordEvent] = []
    for group_start in range(0, len(words), _WORDS_PER_LINE):
        group = words[group_start: group_start + _WORDS_PER_LINE]
        group_texts = [w.text.strip() for w in group]
        for i, word in enumerate(group):
            events.append(_WordEvent(
                start=word.start,
                end=word.end,
                line_words=group_texts,
                highlight_idx=i,
            ))
    return events


def _active_event(events: list[_WordEvent], timestamp: float) -> _WordEvent | None:
    for evt in events:
        if evt.start <= timestamp < evt.end:
            return evt
    return None


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in _FONT_NAMES:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            pass
    # Try common macOS system font paths
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/System/Library/Fonts/SFNS.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            pass
    return ImageFont.load_default()


def _render_subtitle(
    frame_bgr: np.ndarray,
    event: _WordEvent,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> np.ndarray:
    h, w = frame_bgr.shape[:2]
    overlay = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGBA))
    draw = ImageDraw.Draw(overlay)

    tokens = event.line_words
    # Build text segments: (text, color) pairs
    parts: list[tuple[str, tuple[int, int, int, int]]] = []
    for i, token in enumerate(tokens):
        if not token:
            continue
        color = _COLOR_YELLOW if i == event.highlight_idx else _COLOR_WHITE
        parts.append((token, color))

    # Measure total line width
    total_text = " ".join(p[0] for p in parts)
    bbox = draw.textbbox((0, 0), total_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = (w - text_w) // 2
    y = int(h * _SUB_Y_FRAC) - text_h // 2

    # Draw outline by rendering text offset in 8 directions
    for dx in range(-_OUTLINE_WIDTH, _OUTLINE_WIDTH + 1):
        for dy in range(-_OUTLINE_WIDTH, _OUTLINE_WIDTH + 1):
            if dx == 0 and dy == 0:
                continue
            _draw_line(draw, parts, font, x + dx, y + dy, outline=True)

    # Draw foreground text
    _draw_line(draw, parts, font, x, y, outline=False)

    return cv2.cvtColor(np.array(overlay), cv2.COLOR_RGBA2BGR)


def _draw_line(
    draw: ImageDraw.ImageDraw,
    parts: list[tuple[str, tuple[int, int, int, int]]],
    font,
    x: int,
    y: int,
    outline: bool,
) -> None:
    cursor = x
    for i, (token, color) in enumerate(parts):
        text = token if i == 0 else " " + token
        fill = _COLOR_BLACK if outline else color
        draw.text((cursor, y), text, font=font, fill=fill)
        bbox = draw.textbbox((cursor, y), text, font=font)
        cursor += bbox[2] - bbox[0]


def _burn_subtitles(
    input_path: Path,
    output_path: Path,
    events: list[_WordEvent],
    font,
    logger,
) -> None:
    cap = cv2.VideoCapture(str(input_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Pipe raw frames into ffmpeg for encoding
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{w}x{h}", "-pix_fmt", "bgr24",
        "-r", str(fps),
        "-i", "pipe:",
        "-c:v", "h264_videotoolbox",
        "-an",
        "-y",
        str(output_path),
    ]

    with subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        frame_num = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                timestamp = frame_num / fps
                evt = _active_event(events, timestamp)
                if evt is not None:
                    frame = _render_subtitle(frame, evt, font)
                assert proc.stdin is not None
                proc.stdin.write(frame.tobytes())
                frame_num += 1
        finally:
            cap.release()
            if proc.stdin:
                proc.stdin.close()

        _, stderr_bytes = proc.communicate()
        if proc.returncode != 0:
            from podshorts.exceptions import FFmpegError
            raise FFmpegError(cmd, proc.returncode, stderr_bytes.decode("utf-8", errors="replace"))

    logger.info("Subtitles burned: %d frames processed", frame_num)
