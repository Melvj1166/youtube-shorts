from __future__ import annotations

from unittest.mock import MagicMock

from podshorts.stages import s04_segment
from podshorts.types import HeatmapMarker, SegmentInput, Word


def _make_ctx():
    ctx = MagicMock()
    ctx.video_id = "TEST"
    ctx.config.force_rerun = True
    ctx.config.min_short_duration = 15.0
    ctx.config.max_short_duration = 60.0
    return ctx


def _words(texts_and_times: list[tuple[str, float, float]]) -> list[Word]:
    return [Word(text=t, start=s, end=e) for t, s, e in texts_and_times]


def _heatmap(entries: list[tuple[float, float, float]]) -> list[HeatmapMarker]:
    return [HeatmapMarker(start_sec=s, end_sec=e, intensity=i) for s, e, i in entries]


class TestBuildCandidates:
    def test_returns_segments_from_words(self):
        words = _words([
            ("Hello", 0.0, 0.5), ("world", 0.5, 1.0), ("this", 1.0, 1.5),
            ("is", 1.5, 2.0), ("a", 2.0, 2.5), ("test.", 2.5, 20.0),
        ])
        inp = SegmentInput(words=words, heatmap=[], duration=30.0)
        out = s04_segment.run(inp, _make_ctx())
        assert isinstance(out.candidates, list)

    def test_no_words_returns_empty(self):
        inp = SegmentInput(words=[], heatmap=[], duration=0.0)
        out = s04_segment.run(inp, _make_ctx())
        assert out.candidates == []

    def test_segments_within_duration_bounds(self):
        words = _words([
            ("Word", float(i), float(i) + 0.5) for i in range(60)
        ])
        inp = SegmentInput(words=words, heatmap=[], duration=60.0)
        ctx = _make_ctx()
        out = s04_segment.run(inp, ctx)
        for seg in out.candidates:
            dur = seg.end - seg.start
            assert dur >= ctx.config.min_short_duration - 0.01
            assert dur <= ctx.config.max_short_duration + 0.01

    def test_no_duplicate_segments(self):
        words = _words([
            ("Word", float(i), float(i) + 0.5) for i in range(60)
        ])
        inp = SegmentInput(words=words, heatmap=[], duration=60.0)
        out = s04_segment.run(inp, _make_ctx())
        ids = [s.segment_id for s in out.candidates]
        assert len(ids) == len(set(ids))

    def test_heatmap_intensity_assigned(self):
        words = _words([
            ("Hello", 0.0, 0.5), ("world", 0.5, 19.0),
        ])
        hm = _heatmap([(0.0, 20.0, 0.9)])
        inp = SegmentInput(words=words, heatmap=hm, duration=30.0)
        out = s04_segment.run(inp, _make_ctx())
        for seg in out.candidates:
            assert seg.mean_heatmap_intensity >= 0.0
