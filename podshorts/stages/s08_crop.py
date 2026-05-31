from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

from podshorts.types import Context, CropInput, CropOutput
from podshorts.utils.ffmpeg import run_ffmpeg, ffmpeg_bin


def run(input: CropInput, ctx: Context) -> CropOutput:
    segment = input.segment.segment
    seg_id = segment.segment_id
    video_path = input.video_path
    tracks = input.tracks

    # Build output and temp paths
    crops_dir = ctx.cache_dir / ctx.video_id / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    output_path = crops_dir / f"{seg_id}_silent.mp4"
    tmp_dir = crops_dir / f"tmp_{seg_id}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Get source dimensions and frame rate via ffprobe
    ffprobe = ffmpeg_bin().replace("ffmpeg", "ffprobe")
    probe_result = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,r_frame_rate",
            "-of", "json",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe_result.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed for {video_path}: {probe_result.stderr}"
        )
    info = json.loads(probe_result.stdout)
    stream = info["streams"][0]
    source_w = int(stream["width"])
    source_h = int(stream["height"])
    num, den = stream["r_frame_rate"].split("/")
    fps = float(num) / float(den)

    # Crop geometry
    crop_w_raw = source_h * 9 / 16
    crop_w = int(crop_w_raw) if int(crop_w_raw) % 2 == 0 else int(crop_w_raw) - 1
    crop_h = source_h

    # Build a lookup: frame_idx -> cx
    frame_cx: dict[int, float] = {fc.frame_idx: fc.cx for fc in tracks}

    seg_start = segment.start
    seg_end = segment.end

    # Divide segment into 1-second chunks
    chunk_starts = []
    t = seg_start
    while t < seg_end:
        chunk_starts.append(t)
        t += 1.0

    chunk_paths: list[Path] = []

    for chunk_idx, chunk_start in enumerate(chunk_starts):
        chunk_end = min(chunk_start + 1.0, seg_end)

        # Compute average cx from FrameCrop entries in this 1-second window
        window_cxs = []
        if frame_cx:
            start_frame = int(math.floor(chunk_start * fps))
            end_frame = int(math.ceil(chunk_end * fps))
            for fidx in range(start_frame, end_frame + 1):
                if fidx in frame_cx:
                    window_cxs.append(frame_cx[fidx])

        if window_cxs:
            cx = sum(window_cxs) / len(window_cxs)
        else:
            cx = source_w / 2

        x = max(0, min(source_w - crop_w, int(cx - crop_w / 2)))

        chunk_path = tmp_dir / f"chunk_{chunk_idx:03d}.mp4"
        ctx.logger.debug(
            "Cropping chunk %d: t=[%.2f, %.2f] cx=%.1f x=%d",
            chunk_idx, chunk_start, chunk_end, cx, x,
        )

        run_ffmpeg(
            [
                "-ss", str(chunk_start),
                "-to", str(chunk_end),
                "-i", str(video_path),
                "-vf", f"crop={crop_w}:{crop_h}:{x}:0,scale=1080:1920",
                "-c:v", "h264_videotoolbox",
                "-an",
                "-y",
                str(chunk_path),
            ],
            description=f"crop_chunk_{chunk_idx}",
        )
        chunk_paths.append(chunk_path)

    # Write concat list
    concat_txt = tmp_dir / "concat.txt"
    with concat_txt.open("w") as f:
        for cp in chunk_paths:
            f.write(f"file '{cp.resolve()}'\n")

    # Concat chunks
    ctx.logger.debug("Concatenating %d chunks -> %s", len(chunk_paths), output_path)
    run_ffmpeg(
        [
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_txt),
            "-c", "copy",
            "-y",
            str(output_path),
        ],
        description="concat_chunks",
    )

    # Clean up temp directory
    shutil.rmtree(tmp_dir, ignore_errors=True)

    ctx.logger.info("Crop complete: %s", output_path)
    return CropOutput(cropped_path=output_path)
