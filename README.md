# PodShorts

Turn any YouTube podcast into vertical short videos. Runs fully local on Apple Silicon — no paid APIs required.

**One command:**
```bash
podshorts run "https://www.youtube.com/watch?v=<id>"
```
**Produces:** `output/<video_id>/short_01.mp4 … short_05.mp4` + `metadata.json` with captions and hashtags.

---

## Requirements

- macOS (Apple Silicon M-series)
- [Homebrew](https://brew.sh) ffmpeg: `brew install ffmpeg`
- [Ollama](https://ollama.com) with `qwen2.5:7b`: `ollama pull qwen2.5:7b`
- Python 3.11+
- [uv](https://docs.astral.sh/uv/): `brew install uv`

---

## Installation

```bash
git clone https://github.com/you/podshorts
cd podshorts
uv sync
```

Verify everything is in order:
```bash
podshorts doctor
```

---

## Usage

### Produce shorts from a URL

```bash
podshorts run "https://www.youtube.com/watch?v=<id>"
```

Options:

| Flag | Default | Description |
|------|---------|-------------|
| `--top-n` | 5 | Number of shorts to produce |
| `--force` | off | Re-run all stages, ignoring cache |
| `--config` | `.env` | Path to custom config file |

### Inspect segments without rendering

```bash
podshorts inspect <video_id>
```

Runs stages 2–6 (scoring only, no video encoding) and prints a ranked table.

### Manage cache

```bash
podshorts cache list
podshorts cache clear <video_id>
```

---

## Configuration

Copy `.env.example` and adjust:

```bash
cp .env.example .env
```

Key settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `qwen2.5:7b` | LLM for scoring and captions |
| `TOP_N_SHORTS` | `5` | Shorts to produce per video |
| `CACHE_DIR` | `cache` | Intermediate file cache |
| `OUTPUT_DIR` | `output` | Final output directory |

---

## Pipeline

Each stage runs in sequence, writing to `cache/<video_id>/`. Stages are skipped on re-runs unless `--force` is passed.

| # | Stage | What it does |
|---|-------|-------------|
| 1 | Download | yt-dlp downloads video + extracts 16kHz mono audio |
| 2 | Heatmap | Parses YouTube "Most Replayed" engagement data |
| 3 | Transcribe | faster-whisper large-v3 with word-level timestamps |
| 4 | Segment | pysbd sentence boundaries + heatmap peak detection → candidates |
| 5 | Score | Ollama LLM rates each segment on 5 virality dimensions |
| 6 | Rank | Composite score (LLM 60% + heatmap 40%), greedy top-N |
| 7 | Face Track | MediaPipe BlazeFace → Kalman-smoothed speaker centroids |
| 8 | Crop | FFmpeg 9:16 reframe with per-second centroid pan |
| 9 | Subtitle | Karaoke-style word highlighting burned in via Pillow + OpenCV |
| 10 | Export | libx264 CRF 20 + faststart, Ollama caption/hashtag generation |

---

## Output

```
output/<video_id>/
├── short_01.mp4
├── short_02.mp4
├── ...
└── metadata.json
```

`metadata.json` example:
```json
{
  "video_id": "jNQXAC9IVRw",
  "title": "Podcast Title",
  "uploader": "Channel Name",
  "source_url": "https://www.youtube.com/watch?v=jNQXAC9IVRw",
  "shorts": [
    {
      "filename": "short_01.mp4",
      "segment_id": "seg_003",
      "source_start": 423.5,
      "source_end": 461.2,
      "duration": 37.7,
      "llm_scores": {
        "hook": 9.0,
        "standalone": 8.0,
        "emotion": 7.5,
        "quotability": 9.5,
        "pacing": 7.0,
        "composite": 8.5,
        "final": 8.7
      },
      "reason": "Strong hook, self-contained insight, emotionally resonant.",
      "suggested_caption": "The one thing nobody tells you about...",
      "suggested_hashtags": ["#podcast", "#mindset", "#growth", "#insights", "#shorts"]
    }
  ]
}
```

---

## Development

```bash
# Run tests
uv run pytest

# Lint
uv run ruff check podshorts/
```

---

## Architecture Notes

See [DECISIONS.md](DECISIONS.md) for recorded architectural choices (FFmpeg strategy, subtitle renderer, face tracking API migration, etc.).

**Hard constraints:**
- No `print()` — use the structured logger from `ctx.logger`
- No global state — all config flows through `Context`
- No cloud APIs in the critical path — everything runs on-device
