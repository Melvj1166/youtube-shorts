from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from podshorts.config import Settings
    from podshorts.memory.graphify_client import GraphifyClient


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


@dataclass
class VideoMetadata:
    video_id: str
    title: str
    duration_seconds: float
    uploader: str
    view_count: int
    upload_date: str
    description: str
    chapters: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Word:
    text: str
    start: float
    end: float
    speaker_id: str | None = None


@dataclass
class HeatmapMarker:
    start_sec: float
    end_sec: float
    intensity: float


@dataclass
class Segment:
    segment_id: str
    start: float
    end: float
    transcript: str
    mean_heatmap_intensity: float
    word_indices: list[int] = field(default_factory=list)


@dataclass
class ScoredSegment:
    segment: Segment
    hook: float
    standalone: float
    emotion: float
    quotability: float
    pacing: float
    llm_score: float
    reason: str
    final_score: float = 0.0
    normalized_llm_score: float = 0.0
    normalized_heatmap_intensity: float = 0.0


@dataclass
class FrameCrop:
    frame_idx: int
    cx: float
    cy: float


# ---------------------------------------------------------------------------
# Stage I/O dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DownloadInput:
    url: str


@dataclass
class DownloadOutput:
    video_path: Path
    audio_path: Path
    metadata: VideoMetadata


@dataclass
class HeatmapInput:
    video_id: str


@dataclass
class HeatmapOutput:
    markers: list[HeatmapMarker]


@dataclass
class TranscribeInput:
    audio_path: Path


@dataclass
class TranscribeOutput:
    words: list[Word]


@dataclass
class SegmentInput:
    words: list[Word]
    heatmap: list[HeatmapMarker]
    duration: float


@dataclass
class SegmentOutput:
    candidates: list[Segment]


@dataclass
class ScoreInput:
    candidates: list[Segment]
    podcast_topic: str | None = None


@dataclass
class ScoreOutput:
    scored: list[ScoredSegment]


@dataclass
class RankInput:
    scored: list[ScoredSegment]
    top_n: int = 5


@dataclass
class RankOutput:
    selected: list[ScoredSegment]


@dataclass
class FaceTrackInput:
    video_path: Path
    segments: list[ScoredSegment]


@dataclass
class FaceTrackOutput:
    # Maps segment_id -> list of per-frame crop centers
    tracks: dict[str, list[FrameCrop]] = field(default_factory=dict)


@dataclass
class CropInput:
    video_path: Path
    segment: ScoredSegment
    tracks: list[FrameCrop]


@dataclass
class CropOutput:
    cropped_path: Path


@dataclass
class SubtitleInput:
    cropped_path: Path
    segment_words: list[Word]
    source_video_path: Path
    segment_start: float
    segment_end: float


@dataclass
class SubtitleOutput:
    subtitled_path: Path


@dataclass
class ExportInput:
    subtitled_paths: list[Path]
    scored_segments: list[ScoredSegment]
    video_metadata: VideoMetadata


@dataclass
class ExportOutput:
    output_dir: Path
    metadata_path: Path


# ---------------------------------------------------------------------------
# Pipeline context (passed to every stage)
# ---------------------------------------------------------------------------


@dataclass
class Context:
    video_id: str
    cache_dir: Path
    config: Any  # Settings — typed as Any to avoid circular import at runtime
    logger: Any  # logging.Logger
    graphify: Any  # GraphifyClient | None
