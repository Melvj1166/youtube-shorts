from __future__ import annotations

import logging
from pathlib import Path

from podshorts.config import Settings
from podshorts.exceptions import StageError
from podshorts.memory.graphify_client import make_graphify_client
from podshorts.types import (
    Context,
    DownloadInput,
    HeatmapInput,
    RankInput,
    ScoreInput,
    SegmentInput,
    TranscribeInput,
)
from podshorts.utils.logging import get_logger


def build_context(video_id: str, config: Settings, logger: logging.Logger) -> Context:
    graphify = make_graphify_client(
        namespace=config.graphify_namespace,
        endpoint=config.graphify_endpoint,
        api_key=config.graphify_api_key,
    )
    return Context(
        video_id=video_id,
        cache_dir=config.cache_dir,
        config=config,
        logger=logger,
        graphify=graphify,
    )


def run_pipeline(url: str, config: Settings) -> Path:
    """Run the full PodShorts pipeline for a YouTube URL.

    Returns the output directory path.
    """
    from podshorts.stages import (
        s01_download,
        s02_heatmap,
        s03_transcribe,
        s04_segment,
        s05_score,
        s06_rank,
        s07_face_track,
        s08_crop,
        s09_subtitle,
        s10_export,
    )

    logger = get_logger("podshorts.pipeline", config.log_level)
    config.ensure_dirs()

    # Stage 1: Download (to get video_id)
    logger.info("Stage 1: Downloading %s", url)
    dl_input = DownloadInput(url=url)
    # Temp context before we know video_id
    tmp_ctx = Context(
        video_id="__unknown__",
        cache_dir=config.cache_dir,
        config=config,
        logger=logger,
        graphify=None,
    )
    dl_output = s01_download.run(dl_input, tmp_ctx)
    video_id = dl_output.metadata.video_id

    ctx = build_context(video_id, config, logger)

    try:
        ctx.graphify.recall(f"video:{video_id}")
    except Exception:
        pass

    # Stage 2: Heatmap
    logger.info("Stage 2: Fetching engagement heatmap")
    hm_output = s02_heatmap.run(HeatmapInput(video_id=video_id), ctx)

    # Stage 3: Transcription
    logger.info("Stage 3: Transcribing audio")
    tr_output = s03_transcribe.run(TranscribeInput(audio_path=dl_output.audio_path), ctx)

    # Stage 4: Segmentation
    logger.info("Stage 4: Building candidate segments")
    seg_output = s04_segment.run(
        SegmentInput(
            words=tr_output.words,
            heatmap=hm_output.markers,
            duration=dl_output.metadata.duration_seconds,
        ),
        ctx,
    )

    # Stage 5: LLM Scoring
    logger.info("Stage 5: Scoring %d candidates", len(seg_output.candidates))
    score_output = s05_score.run(
        ScoreInput(candidates=seg_output.candidates),
        ctx,
    )

    # Stage 6: Ranking
    logger.info("Stage 6: Ranking segments")
    rank_output = s06_rank.run(
        RankInput(scored=score_output.scored, top_n=config.top_n_shorts),
        ctx,
    )

    # Stage 7: Face tracking
    logger.info("Stage 7: Face tracking")
    from podshorts.types import FaceTrackInput
    track_output = s07_face_track.run(
        FaceTrackInput(
            video_path=dl_output.video_path,
            segments=rank_output.selected,
        ),
        ctx,
    )

    # Stage 8-9: Crop + Subtitle per segment
    from podshorts.types import CropInput, SubtitleInput
    subtitled_paths = []
    for scored_seg in rank_output.selected:
        seg_id = scored_seg.segment.segment_id
        tracks = track_output.tracks.get(seg_id, [])

        logger.info("Stage 8: Cropping segment %s", seg_id)
        crop_out = s08_crop.run(
            CropInput(
                video_path=dl_output.video_path,
                segment=scored_seg,
                tracks=tracks,
            ),
            ctx,
        )

        seg_words = [
            w for i, w in enumerate(tr_output.words)
            if i in set(scored_seg.segment.word_indices)
        ]

        logger.info("Stage 9: Adding subtitles to segment %s", seg_id)
        sub_out = s09_subtitle.run(
            SubtitleInput(
                cropped_path=crop_out.cropped_path,
                segment_words=seg_words,
                source_video_path=dl_output.video_path,
                segment_start=scored_seg.segment.start,
                segment_end=scored_seg.segment.end,
            ),
            ctx,
        )
        subtitled_paths.append(sub_out.subtitled_path)

    # Stage 10: Export
    logger.info("Stage 10: Exporting finals")
    from podshorts.types import ExportInput
    export_out = s10_export.run(
        ExportInput(
            subtitled_paths=subtitled_paths,
            scored_segments=rank_output.selected,
            video_metadata=dl_output.metadata,
        ),
        ctx,
    )

    try:
        ctx.graphify.remember(f"run:{video_id}", "completed")
    except Exception:
        pass

    return export_out.output_dir


def inspect_pipeline(video_id: str, config: Settings) -> None:
    """Run stages 2-6 (no video encoding) and print segment scores."""
    from podshorts.stages import (
        s02_heatmap,
        s03_transcribe,
        s04_segment,
        s05_score,
        s06_rank,
    )
    from podshorts.types import HeatmapInput, TranscribeInput, SegmentInput, ScoreInput, RankInput

    logger = get_logger("podshorts.inspect", config.log_level)
    ctx = build_context(video_id, config, logger)

    video_path = config.cache_dir / video_id / "video.mp4"
    audio_path = config.cache_dir / video_id / "audio.wav"

    if not video_path.exists():
        raise StageError("inspect", f"No cached video for {video_id}. Run 'podshorts run' first.")

    hm_output = s02_heatmap.run(HeatmapInput(video_id=video_id), ctx)
    tr_output = s03_transcribe.run(TranscribeInput(audio_path=audio_path), ctx)

    from podshorts.utils.ffmpeg import probe_duration
    duration = probe_duration(video_path)

    seg_output = s04_segment.run(
        SegmentInput(
            words=tr_output.words,
            heatmap=hm_output.markers,
            duration=duration,
        ),
        ctx,
    )
    score_output = s05_score.run(
        ScoreInput(candidates=seg_output.candidates),
        ctx,
    )
    rank_output = s06_rank.run(
        RankInput(
            scored=score_output.scored,
            top_n=config.top_n_shorts,
        ),
        ctx,
    )

    from rich.console import Console
    from rich.table import Table
    console = Console()
    table = Table(title=f"Top segments for {video_id}")
    table.add_column("#", style="cyan")
    table.add_column("Start", style="green")
    table.add_column("End", style="green")
    table.add_column("LLM", style="yellow")
    table.add_column("Heatmap", style="magenta")
    table.add_column("Final", style="bold white")
    table.add_column("Reason")

    for i, s in enumerate(rank_output.selected, 1):
        table.add_row(
            str(i),
            f"{s.segment.start:.1f}s",
            f"{s.segment.end:.1f}s",
            f"{s.llm_score:.2f}",
            f"{s.segment.mean_heatmap_intensity:.2f}",
            f"{s.final_score:.2f}",
            s.reason[:60],
        )
    console.print(table)
