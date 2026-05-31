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
