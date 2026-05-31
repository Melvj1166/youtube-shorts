from __future__ import annotations

import json
import re
from pathlib import Path

from podshorts.types import Context, ExportInput, ExportOutput, ScoredSegment
from podshorts.utils.ffmpeg import run_ffmpeg


def run(input: ExportInput, ctx: Context) -> ExportOutput:
    logger = ctx.logger
    video_id = input.video_metadata.video_id

    out_dir = ctx.config.output_dir / video_id
    out_dir.mkdir(parents=True, exist_ok=True)

    shorts_meta: list[dict] = []

    for idx, (path, scored) in enumerate(
        zip(input.subtitled_paths, input.scored_segments), start=1
    ):
        short_name = f"short_{idx:02d}.mp4"
        dest = out_dir / short_name

        logger.info("Exporting %s → %s", path.name, short_name)
        _reencode(path, dest)

        caption, hashtags = _generate_caption(scored, ctx)

        shorts_meta.append({
            "filename": short_name,
            "segment_id": scored.segment.segment_id,
            "source_start": scored.segment.start,
            "source_end": scored.segment.end,
            "duration": scored.segment.end - scored.segment.start,
            "llm_scores": {
                "hook": scored.hook,
                "standalone": scored.standalone,
                "emotion": scored.emotion,
                "quotability": scored.quotability,
                "pacing": scored.pacing,
                "composite": scored.llm_score,
                "final": scored.final_score,
            },
            "reason": scored.reason,
            "suggested_caption": caption,
            "suggested_hashtags": hashtags,
        })

    metadata = {
        "video_id": video_id,
        "title": input.video_metadata.title,
        "uploader": input.video_metadata.uploader,
        "source_url": f"https://www.youtube.com/watch?v={video_id}",
        "shorts": shorts_meta,
    }

    metadata_path = out_dir / "metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    logger.info("Metadata written: %s", metadata_path)

    try:
        if ctx.graphify:
            ctx.graphify.remember(f"export:{video_id}", f"{len(shorts_meta)} shorts exported")
    except Exception:
        pass

    return ExportOutput(output_dir=out_dir, metadata_path=metadata_path)


def _reencode(src: Path, dest: Path) -> None:
    # Web-optimized: h264 high profile, CRF 20, +faststart, AAC 128k
    # Use libx264 for CRF (videotoolbox doesn't support CRF mode)
    run_ffmpeg(
        [
            "-i", str(src),
            "-c:v", "libx264",
            "-profile:v", "high",
            "-crf", "20",
            "-movflags", "+faststart",
            "-c:a", "aac",
            "-b:a", "128k",
            "-y",
            str(dest),
        ],
        description=f"export_{dest.stem}",
    )


def _generate_caption(scored: ScoredSegment, ctx: Context) -> tuple[str, list[str]]:
    transcript = scored.segment.transcript[:800]  # keep prompt manageable
    system_prompt = (
        "You are a social media content writer. "
        "Return ONLY valid JSON, no prose."
    )
    user_prompt = (
        f'Transcript: """{transcript}"""\n\n'
        "Write an Instagram Reels caption (≤125 chars, 1 hook line + 1 value line) "
        "and 5 relevant hashtags.\n"
        'Return: {"caption": "...", "hashtags": ["#...", "#...", "#...", "#...", "#..."]}'
    )

    try:
        import ollama  # noqa: PLC0415
        client = ollama.Client(host=ctx.config.ollama_host)
        response = client.chat(
            model=ctx.config.ollama_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            options={"temperature": 0.4},
        )
        text = response["message"]["content"]
        return _parse_caption_response(text)
    except Exception as exc:
        ctx.logger.warning("Caption generation failed for %s: %s", scored.segment.segment_id, exc)
        return scored.segment.transcript[:125], []


def _parse_caption_response(text: str) -> tuple[str, list[str]]:
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"```\s*$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        data = json.loads(cleaned)
        caption = str(data.get("caption", ""))[:125]
        hashtags = [str(h) for h in data.get("hashtags", [])[:5]]
        return caption, hashtags
    except json.JSONDecodeError:
        return text[:125], []
