from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from podshorts.stages.s05_score import _parse_scores
from podshorts.stages import s05_score
from podshorts.types import ScoreInput, Segment


def _seg(segment_id: str = "seg_000", start: float = 0.0, end: float = 30.0) -> Segment:
    return Segment(
        segment_id=segment_id,
        start=start,
        end=end,
        transcript="This is a test transcript with some interesting content.",
        mean_heatmap_intensity=0.6,
    )


def _make_ctx():
    ctx = MagicMock()
    ctx.config.ollama_host = "http://localhost:11434"
    ctx.config.ollama_model = "qwen2.5:7b"
    return ctx


def _ollama_response(scores: dict, reason: str = "Good segment.") -> dict:
    data = {**scores, "reason": reason}
    return {"message": {"content": json.dumps(data)}}


class TestParseScores:
    def test_valid_json(self):
        text = json.dumps({
            "hook": 8, "standalone": 7, "emotion": 6,
            "quotability": 9, "pacing": 7, "reason": "Great opener.",
        })
        scores, reason = _parse_scores(text)
        assert scores["hook"] == pytest.approx(8.0)
        assert scores["pacing"] == pytest.approx(7.0)
        assert reason == "Great opener."

    def test_strips_markdown_fences(self):
        text = "```json\n{\"hook\":7,\"standalone\":6,\"emotion\":5,\"quotability\":8,\"pacing\":6,\"reason\":\"ok\"}\n```"
        scores, reason = _parse_scores(text)
        assert scores["hook"] == pytest.approx(7.0)

    def test_missing_dimension_raises_key_error(self):
        text = json.dumps({"hook": 8, "standalone": 7})
        with pytest.raises(KeyError):
            _parse_scores(text)

    def test_invalid_json_raises(self):
        with pytest.raises(Exception):
            _parse_scores("not json at all")


class TestRunScoring:
    def test_scores_all_segments(self):
        segments = [_seg("seg_000"), _seg("seg_001", 30.0, 60.0)]
        inp = ScoreInput(candidates=segments)
        ctx = _make_ctx()

        mock_resp = _ollama_response(
            {"hook": 8, "standalone": 7, "emotion": 6, "quotability": 9, "pacing": 7}
        )

        with patch("podshorts.stages.s05_score.ollama.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            out = s05_score.run(inp, ctx)

        assert len(out.scored) == 2
        for scored in out.scored:
            assert scored.hook == pytest.approx(8.0)
            assert scored.llm_score > 0

    def test_composite_score_formula(self):
        segments = [_seg()]
        inp = ScoreInput(candidates=segments)
        ctx = _make_ctx()

        mock_resp = _ollama_response(
            {"hook": 10, "standalone": 0, "emotion": 0, "quotability": 0, "pacing": 0}
        )

        with patch("podshorts.stages.s05_score.ollama.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat.return_value = mock_resp
            mock_client_cls.return_value = mock_client

            out = s05_score.run(inp, ctx)

        # hook weight = 0.3, so composite = 10 * 0.3 = 3.0
        assert out.scored[0].llm_score == pytest.approx(3.0, abs=0.01)

    def test_fallback_on_bad_llm_response(self):
        segments = [_seg()]
        inp = ScoreInput(candidates=segments)
        ctx = _make_ctx()

        bad_resp = {"message": {"content": "not valid json"}}

        with patch("podshorts.stages.s05_score.ollama.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat.return_value = bad_resp
            mock_client_cls.return_value = mock_client

            out = s05_score.run(inp, ctx)

        assert len(out.scored) == 1
        assert out.scored[0].hook == pytest.approx(5.0)  # fallback score
