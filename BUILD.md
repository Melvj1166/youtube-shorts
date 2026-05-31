# BUILD.md — PodShorts: AI Podcast-to-Shorts Automation Pipeline

> **Read this entire document before writing any code.** This is your master spec. Do not deviate without surfacing the change to the user first.

---

## 0. Mission

Build a fully local, end-to-end Python pipeline that takes a YouTube podcast URL and outputs 3–5 ready-to-publish vertical short videos (9:16, ≤60s, burned-in styled subtitles, speaker-aware framing). The system must run entirely on an Apple Silicon MacBook (M4 Pro) using local models — no paid APIs required for the core pipeline.

**Target outcome:** `python -m podshorts run "<youtube_url>"` produces `output/<video_id>/short_01.mp4 ... short_05.mp4` plus a `metadata.json` with captions, hashtags, and source timestamps.

---

## 1. Operating Principles (read these every session)

1. **Local-first.** Default to local models (Whisper via faster-whisper, Ollama for LLM). Cloud APIs are optional fallbacks gated behind config flags.
2. **Apple Silicon native.** Use Metal/MPS/CoreML acceleration wherever supported. Test that `torch.backends.mps.is_available()` returns True at startup.
3. **Module isolation.** Each pipeline stage is a standalone module with a typed input dataclass and typed output dataclass. No stage reaches into another's internals.
4. **Cache aggressively.** Every expensive operation (download, transcription, face detection) writes its output to `cache/<video_id>/<stage>.json` or `.npz`. Re-runs skip completed stages unless `--force` is passed.
5. **Fail loud, fail early.** Validate inputs at stage boundaries. Raise typed exceptions (`StageError`, `DependencyMissingError`). Never silently swallow errors.
6. **No mocks in production code.** If something cannot be implemented yet, raise `NotImplementedError` with a TODO comment — do not stub with fake data.
7. **Use Graphify for memory.** Persist project state, decisions, and discovered constraints via the Graphify memory system as you go. At session start, query Graphify for prior context on `podshorts` namespace.
8. **Surface tradeoffs.** When choosing between two reasonable approaches (e.g., MoviePy vs raw FFmpeg), state the tradeoff in the commit message or a `DECISIONS.md` entry.

---

## 2. Project Structure (create exactly this)

```
podshorts/
├── build.md                    # this file
├── DECISIONS.md                # append-only architectural decisions
├── README.md                   # user-facing docs (write last)
├── pyproject.toml              # uv-managed
├── .env.example
├── podshorts/
│   ├── __init__.py
│   ├── __main__.py             # CLI entrypoint via Typer
│   ├── config.py               # Pydantic settings, loads .env
│   ├── types.py                # shared dataclasses for stage I/O
│   ├── exceptions.py
│   ├── pipeline.py             # orchestrator
│   ├── stages/
│   │   ├── __init__.py
│   │   ├── s01_download.py     # yt-dlp wrapper
│   │   ├── s02_heatmap.py      # YouTube most-replayed parsing
│   │   ├── s03_transcribe.py   # faster-whisper, word timestamps
│   │   ├── s04_segment.py      # sentence-aligned candidate segments
│   │   ├── s05_score.py        # Ollama LLM virality scoring
│   │   ├── s06_rank.py         # composite ranking, pick top N
│   │   ├── s07_face_track.py   # MediaPipe face centroids per frame
│   │   ├── s08_crop.py         # FFmpeg 9:16 reframe with smoothed pan
│   │   ├── s09_subtitle.py     # ASS subtitle generation + burn-in
│   │   └── s10_export.py       # final encode + metadata.json
│   ├── memory/
│   │   ├── __init__.py
│   │   └── graphify_client.py  # Graphify wrapper for persistent memory
│   └── utils/
│       ├── ffmpeg.py
│       ├── cache.py
│       └── logging.py
├── cache/                      # gitignored, per-video intermediates
├── output/                     # gitignored, final shorts
└── tests/
    ├── test_heatmap.py
    ├── test_segment.py
    ├── test_score.py
    └── fixtures/
```

---

## 3. Pipeline Contract — Stage-by-Stage Specification

Each stage has a single function `run(input: InputType, ctx: Context) -> OutputType`. `Context` carries `video_id`, `cache_dir`, `config`, `logger`, and a `graphify` client.

### Stage 1 — Download (`s01_download.py`)
**Input:** `DownloadInput(url: str)`
**Output:** `DownloadOutput(video_path: Path, audio_path: Path, metadata: VideoMetadata)`

- Use `yt-dlp` Python API (not subprocess) — import `yt_dlp`.
- Download best `mp4` ≤1080p video and extract a separate 16kHz mono WAV for Whisper.
- `VideoMetadata` includes: `video_id`, `title`, `duration_seconds`, `uploader`, `view_count`, `upload_date`, `description`, `chapters` (if present).
- Cache key: `video_id`. Skip if `cache/<video_id>/video.mp4` exists.
- Raise `DownloadError` on private/region-locked/age-gated videos.

### Stage 2 — Engagement Heatmap (`s02_heatmap.py`)
**Input:** `HeatmapInput(video_id: str)`
**Output:** `HeatmapOutput(markers: list[HeatmapMarker])` where `HeatmapMarker = (start_sec: float, end_sec: float, intensity: float)`

- Fetch `https://www.youtube.com/watch?v=<id>` HTML, locate the `ytInitialData` JSON blob (regex `var ytInitialData = ({.*?});`).
- Walk JSON to `playerOverlays → ... → decoratedPlayerBarRenderer → playerBar → multiMarkersPlayerBarRenderer → markersMap`.
- Find the entry whose `key` contains `HEATSEEKER` or `markerType: MARKER_TYPE_HEATMAP`. Extract `heatmap → heatmapRenderer → heatMarkers`.
- Each heat marker: `timeRangeStartMillis`, `markerDurationMillis`, `heatMarkerIntensityScoreNormalized` (0.0–1.0).
- Run `scipy.signal.find_peaks` on the intensity series with `prominence=0.15, distance=8` to identify peaks. Return ALL markers (not just peaks) — ranking stage uses the full signal.
- If no heatmap exists (small channels), return empty list. Downstream must handle this — segment ranking falls back to LLM-only scoring.

### Stage 3 — Transcription (`s03_transcribe.py`)
**Input:** `TranscribeInput(audio_path: Path)`
**Output:** `TranscribeOutput(words: list[Word])` where `Word = (text: str, start: float, end: float, speaker_id: str | None)`

- Use `faster-whisper` with `model_size="large-v3"`, `device="auto"` (will pick Metal on M4), `compute_type="int8"`.
- Enable `word_timestamps=True`.
- Optional: run `pyannote.audio` speaker diarization in parallel if `config.enable_diarization` is True. Map each word to a speaker by timestamp overlap.
- Cache full result as JSON.

### Stage 4 — Segmentation (`s04_segment.py`)
**Input:** `SegmentInput(words: list[Word], heatmap: list[HeatmapMarker], duration: float)`
**Output:** `SegmentOutput(candidates: list[Segment])`

- Build sentence boundaries from word stream using `pysbd` (operate on the concatenated text, then map back to word indices).
- Generate candidate segments by sliding a window:
  - For each heatmap peak, create a candidate centered on the peak, expanded outward to the nearest sentence boundaries, clamped to 20–60 seconds.
  - Additionally, generate fixed-stride candidates (every 30s) to ensure coverage when heatmap is sparse.
- Deduplicate overlapping candidates (>50% IoU → keep the one with higher heatmap intensity).
- Each `Segment` carries: `start`, `end`, `transcript`, `mean_heatmap_intensity`, `word_indices`.

### Stage 5 — LLM Scoring (`s05_score.py`)
**Input:** `ScoreInput(candidates: list[Segment], podcast_topic: str | None)`
**Output:** `ScoreOutput(scored: list[ScoredSegment])`

- Use Ollama via the official Python client. Default model: `qwen2.5:7b` (configurable).
- For each candidate, send this prompt structure:

```
SYSTEM: You are a viral short-form video editor. Score the segment 0-10 on
five dimensions. Return ONLY valid JSON, no prose.

USER: Podcast: {topic}
Duration: {duration}s
Transcript: """{transcript}"""

Score these dimensions 0-10:
- hook: Does the opening grab attention in <3 seconds?
- standalone: Does it make sense without prior context?
- emotion: Does it evoke surprise, humor, insight, or strong opinion?
- quotability: Is there a memorable line?
- pacing: Is the energy appropriate for short-form?

Return: {"hook": N, "standalone": N, "emotion": N, "quotability": N, "pacing": N, "reason": "one sentence"}
```

- Parse with strict JSON validation. Retry once with stricter instructions on parse failure.
- Composite LLM score = weighted mean: hook×0.3 + standalone×0.25 + emotion×0.2 + quotability×0.15 + pacing×0.1.

### Stage 6 — Ranking (`s06_rank.py`)
**Input:** `RankInput(scored: list[ScoredSegment], top_n: int = 5)`
**Output:** `RankOutput(selected: list[ScoredSegment])`

- Final score = `0.6 * normalized_llm_score + 0.4 * normalized_heatmap_intensity`.
- Enforce minimum gap of 60s between selected segments (no two shorts from the same moment).
- Return top N sorted by final score, descending.

### Stage 7 — Face Tracking (`s07_face_track.py`)
**Input:** `FaceTrackInput(video_path: Path, segments: list[ScoredSegment])`
**Output:** `FaceTrackOutput(tracks: dict[segment_id, list[FrameCrop]])` where `FrameCrop = (frame_idx, cx, cy)` (crop center in source video coordinates).

- Use MediaPipe Face Detection (short-range model) at the source video FPS.
- Only process frames within selected segment ranges (don't waste compute on the whole video).
- If multiple faces detected, pick the one whose voice is currently active using diarization timestamps. If diarization disabled, pick the largest face.
- Smooth the centroid trajectory with a 1D Kalman filter (use `filterpy.kalman.KalmanFilter`) — state = [cx, cy, vx, vy].
- For frames with no detection, hold last known position.

### Stage 8 — Cropping (`s08_crop.py`)
**Input:** `CropInput(video_path, segment, tracks)`
**Output:** `CropOutput(cropped_path: Path)` — silent 1080×1920 mp4 for this segment.

- Target output: 1080×1920, h264, yuv420p, source FPS preserved.
- Compute crop window: width = `source_h * 9/16` (assuming 16:9 source), height = `source_h`. Center on smoothed face centroid, clamp to source bounds.
- Use FFmpeg's `crop` filter with the `sendcmd` filter or per-frame expressions. For per-frame dynamic cropping, build a `zoompan`-style expression OR generate a temporary subtitle-format file the `crop` filter reads via `eif:t`.
- **Pragmatic alternative:** if per-frame crop expressions get unwieldy, segment the video into 1-second chunks each with a fixed (averaged) crop center, concat them. This is acceptable.
- Use `-c:v h264_videotoolbox` for hardware-accelerated encoding on Apple Silicon.

### Stage 9 — Subtitles (`s09_subtitle.py`)
**Input:** `SubtitleInput(cropped_path: Path, segment_words: list[Word])`
**Output:** `SubtitleOutput(subtitled_path: Path)`

- Generate an `.ass` (Advanced SubStation Alpha) file with per-word karaoke timing.
- Style: large bold sans-serif, 1–3 words per displayed line, centered at 75% vertical position, white text with black outline (4px), current-word highlighted in yellow (`#FFD700`).
- Font: `Inter` (fallback `Arial`), size 72, bold.
- Use FFmpeg `subtitles` filter to burn in, preserving the audio from the original segment (extracted separately from source video).
- Audio extraction: `ffmpeg -i source.mp4 -ss <start> -to <end> -c:a aac segment_audio.aac`, then mux with cropped video.

### Stage 10 — Export (`s10_export.py`)
**Input:** `ExportInput(subtitled_paths: list[Path], scored_segments: list[ScoredSegment], video_metadata: VideoMetadata)`
**Output:** Files written to `output/<video_id>/`.

- Re-encode each final short to web-optimized: `h264 high profile`, CRF 20, `+faststart`, AAC 128k audio.
- Generate `metadata.json` with per-short: source_start, source_end, llm_scores, suggested_caption, suggested_hashtags.
- Generate captions/hashtags by sending each segment's transcript to the LLM with prompt:
  ```
  Write an Instagram Reels caption (≤125 chars, 1 hook line + 1 value line) and 5 relevant hashtags. JSON only.
  ```

---

## 4. Configuration (`config.py`)

Pydantic `BaseSettings` loaded from `.env`. Fields:

```python
class Settings(BaseSettings):
    # Models
    whisper_model: str = "large-v3"
    whisper_compute_type: str = "int8"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"

    # Pipeline
    top_n_shorts: int = 5
    min_short_duration: int = 20
    max_short_duration: int = 60
    enable_diarization: bool = False

    # Paths
    cache_dir: Path = Path("./cache")
    output_dir: Path = Path("./output")

    # Memory
    graphify_namespace: str = "podshorts"
    graphify_endpoint: str | None = None
    graphify_api_key: str | None = None

    # Behavior
    force_rerun: bool = False
    log_level: str = "INFO"
```

---

## 5. Graphify Memory Integration

The user is using Graphify for persistent memory across Claude Code sessions. Implement `memory/graphify_client.py` as a thin wrapper. Use it for:

1. **Session start:** Query `graphify.recall(namespace="podshorts", query="project state")` and surface what's already built.
2. **Decision logging:** After any non-trivial architectural choice, call `graphify.remember(namespace="podshorts", key="decision:<topic>", value=<rationale>)`.
3. **Per-video learnings:** When a pipeline run produces unusual results (no heatmap, all low LLM scores, face tracking failures), log the observation so future runs can adapt.
4. **Bug fixes:** When you fix a bug that took more than one attempt, store the symptom→cause→fix triple.

Wrap all Graphify calls in try/except — if Graphify is unreachable, log a warning and continue. Memory is augmentation, not a hard dependency.

---

## 6. CLI Surface (Typer)

```bash
podshorts run <youtube_url> [--top-n 5] [--force] [--config path/to/.env]
podshorts cache list
podshorts cache clear <video_id>
podshorts inspect <video_id>     # show heatmap + scored segments without rendering
podshorts doctor                  # verify ffmpeg, ollama, mps availability
```

`doctor` must check: FFmpeg present + has `h264_videotoolbox`, Ollama reachable + target model pulled, `torch.backends.mps.is_available()`, faster-whisper installed, MediaPipe importable.

---

## 7. Dependencies

`pyproject.toml` (uv). Pin major versions only:

```toml
[project]
dependencies = [
    "yt-dlp>=2024.10",
    "faster-whisper>=1.0",
    "ollama>=0.3",
    "mediapipe>=0.10",
    "filterpy>=1.4",
    "pysbd>=0.3",
    "scipy>=1.13",
    "numpy>=1.26",
    "pydantic>=2.7",
    "pydantic-settings>=2.3",
    "typer>=0.12",
    "rich>=13.7",
    "ffmpeg-python>=0.2",
    "httpx>=0.27",
]

[project.optional-dependencies]
diarization = ["pyannote.audio>=3.3"]
dev = ["pytest>=8.0", "pytest-asyncio", "ruff"]
```

Install with `uv pip install -e ".[diarization,dev]"`.

---

## 8. Execution Plan — Build in This Order

You MUST build incrementally. Do not write the entire pipeline before testing. Each step ends with a working CLI command.

**Step 1.** Scaffold project, write `config.py`, `types.py`, `exceptions.py`, `pipeline.py` skeleton, CLI with `doctor` command. Test: `podshorts doctor` passes on the user's machine.

**Step 2.** Implement `s01_download.py` + caching. Test: download a 5-minute test video, confirm files exist.

**Step 3.** Implement `s02_heatmap.py`. Test: pick a popular podcast video known to have a heatmap, dump the markers, sanity-check the peaks visually (print ASCII bar chart).

**Step 4.** Implement `s03_transcribe.py`. Test: transcribe the 5-minute video, confirm word timestamps look right.

**Step 5.** Implement `s04_segment.py` + `s05_score.py` + `s06_rank.py`. Test: run `podshorts inspect <id>` and print top 5 segments with scores.

**Step 6.** Implement `s07_face_track.py` + `s08_crop.py` on ONE selected segment. Verify the output visually before scaling to multiple segments.

**Step 7.** Implement `s09_subtitle.py`. Verify subtitles render correctly in QuickTime/VLC.

**Step 8.** Implement `s10_export.py` + full `run` command end-to-end.

**Step 9.** Write `README.md`, polish error messages, add a `--dry-run` flag that runs everything except video encoding.

After each step: commit with a clear message, update `DECISIONS.md` if anything non-obvious was chosen, log the milestone to Graphify.

---

## 9. Testing Discipline

- Unit tests for `s02_heatmap` (use a saved HTML fixture), `s04_segment` (synthetic word streams), `s06_rank` (synthetic scored segments).
- Integration test: a `tests/test_smoke.py` that runs the full pipeline on a 2-minute Creative Commons video and asserts at least one short is produced.
- Don't test against the live YouTube API in CI — always use fixtures.

---

## 10. Hard Rules (do not violate)

1. **No fake data fallbacks.** If a stage can't run, raise — don't return placeholder shorts.
2. **No global state.** Everything passes through `Context`.
3. **No subprocess.run for ffmpeg.** Use `ffmpeg-python` or build commands explicitly with `subprocess.Popen` and proper error capture — never silent shell calls.
4. **No hardcoded paths.** All paths flow through `Settings`.
5. **No emoji in code or logs.**
6. **No `print()`.** Use the `rich`-backed logger from `utils/logging.py`.
7. **No new top-level dependencies without updating `pyproject.toml` AND `DECISIONS.md`.**
8. **Never commit `cache/` or `output/`.** `.gitignore` must exclude both.

---

## 11. Definition of Done

The project is complete when:

- `podshorts doctor` returns all green on the M4 Pro.
- `podshorts run <any_long_podcast_url>` produces 5 vertical MP4 shorts in `output/`.
- Each short: 9:16, ≤60s, burned-in karaoke subtitles, speaker centered, audio in sync, encoder = videotoolbox.
- `metadata.json` includes captions and hashtags per short.
- `README.md` documents install, doctor, and run.
- All unit tests pass. The smoke test produces at least one short.
- Graphify contains a final entry: `key="status", value="v1 complete"`.

---

## 12. Kickoff Instructions for Claude Code

When the user starts a session:

1. Read this file in full.
2. Query Graphify for prior `podshorts` state.
3. Run `podshorts doctor` if the project exists; otherwise begin at Step 1.
4. State the current step and what you intend to do, then proceed.
5. After each meaningful change: commit, update Graphify, surface the diff summary.

Do not ask the user broad open-ended questions like "what should we build next?" — the plan is in this document. Ask only when a specific decision requires user input (e.g., "Heatmap unavailable for this video. Fall back to LLM-only ranking, or abort?").

---

End of BUILD.md