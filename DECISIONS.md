# DECISIONS.md — PodShorts Architectural Decisions

Append-only. Each entry: date, topic, decision, rationale, alternatives rejected.

---

## 2026-05-31 — Project Scaffold

**Decision:** Use `uv` + `hatchling` for packaging.
**Rationale:** uv is fast and handles Apple Silicon well; hatchling is minimal.
**Alternatives rejected:** poetry (slower), setuptools (more boilerplate).

## 2026-05-31 — FFmpeg Strategy

**Decision:** Use `ffmpeg-python` for filter graph construction; `subprocess.Popen` with explicit error capture for operations that need raw ffmpeg control.
**Rationale:** ffmpeg-python provides a Python API for complex filter chains. Direct subprocess is used where the Python API is insufficient.
**Alternatives rejected:** `subprocess.run` with shell=True (silent failures, injection risk).

## 2026-05-31 — Stage I/O

**Decision:** Each pipeline stage is a standalone function `run(input, ctx) -> output` with typed dataclasses.
**Rationale:** Module isolation — no stage reaches into another's internals. Context carries all cross-cutting concerns.
**Alternatives rejected:** Class-based stages (unnecessary OOP overhead for a linear pipeline).

## 2026-05-31 — Subtitle Rendering: Pillow over libass

**Decision:** Use Pillow + OpenCV to render subtitle overlays frame-by-frame, piped into h264_videotoolbox via subprocess.
**Rationale:** Standard Homebrew ffmpeg 8.1.1 does not include libass or libfreetype. The homebrew-ffmpeg tap does not offer a --with-libass option. Pillow renders karaoke-style word highlights correctly and requires no additional system dependencies.
**Alternatives rejected:** ffmpeg `subtitles` filter (requires libass, not available), `drawtext` filter (requires libfreetype, not available), building ffmpeg from source (too complex, breaks uv reproducibility).
