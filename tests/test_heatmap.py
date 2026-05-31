from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from podshorts.stages import s02_heatmap
from podshorts.types import HeatmapInput


def _make_ctx():
    ctx = MagicMock()
    ctx.video_id = "TEST123"
    return ctx


def _modern_page(markers: list[dict]) -> str:
    data = {
        "frameworkUpdates": {
            "entityBatchUpdate": {
                "mutations": [
                    {
                        "payload": {
                            "macroMarkersListEntity": {
                                "markersList": {
                                    "markerType": "MARKER_TYPE_HEATMAP",
                                    "markers": markers,
                                }
                            }
                        }
                    }
                ]
            }
        }
    }
    return f"var ytInitialData = {json.dumps(data)};</script>"


def _legacy_page(markers: list[dict]) -> str:
    data = {
        "playerOverlays": {
            "playerOverlayRenderer": {
                "decoratedPlayerBarRenderer": {
                    "playerBar": {
                        "multiMarkersPlayerBarRenderer": {
                            "markersMap": [
                                {
                                    "key": "HEATSEEKER",
                                    "value": {
                                        "heatmap": {
                                            "heatmapRenderer": {
                                                "heatMarkers": [
                                                    {"heatMarkerRenderer": m}
                                                    for m in markers
                                                ]
                                            }
                                        }
                                    },
                                }
                            ]
                        }
                    }
                }
            }
        }
    }
    return f"var ytInitialData = {json.dumps(data)};</script>"


class TestParseModernPath:
    def test_basic_markers(self):
        raw = [
            {"startMillis": "0", "durationMillis": "5000", "intensityScoreNormalized": 0.8},
            {"startMillis": "5000", "durationMillis": "5000", "intensityScoreNormalized": 0.5},
        ]
        html = _modern_page(raw)
        with patch.object(s02_heatmap, "_fetch_page", return_value=html):
            out = s02_heatmap.run(HeatmapInput(video_id="TEST123"), _make_ctx())

        assert len(out.markers) == 2
        assert out.markers[0].start_sec == pytest.approx(0.0)
        assert out.markers[0].intensity == pytest.approx(0.8)
        assert out.markers[1].start_sec == pytest.approx(5.0)

    def test_end_sec_computed_correctly(self):
        raw = [{"startMillis": "2000", "durationMillis": "3000", "intensityScoreNormalized": 0.6}]
        html = _modern_page(raw)
        with patch.object(s02_heatmap, "_fetch_page", return_value=html):
            out = s02_heatmap.run(HeatmapInput(video_id="TEST123"), _make_ctx())

        assert out.markers[0].start_sec == pytest.approx(2.0)
        assert out.markers[0].end_sec == pytest.approx(5.0)

    def test_empty_markers_returns_empty(self):
        html = _modern_page([])
        with patch.object(s02_heatmap, "_fetch_page", return_value=html):
            out = s02_heatmap.run(HeatmapInput(video_id="TEST123"), _make_ctx())
        assert out.markers == []


class TestParseLegacyPath:
    def test_legacy_heatseeker_key(self):
        raw = [
            {
                "timeRangeStartMillis": 0,
                "markerDurationMillis": 5000,
                "heatMarkerIntensityScoreNormalized": 0.7,
            }
        ]
        html = _legacy_page(raw)
        with patch.object(s02_heatmap, "_fetch_page", return_value=html):
            out = s02_heatmap.run(HeatmapInput(video_id="TEST123"), _make_ctx())

        assert len(out.markers) == 1
        assert out.markers[0].intensity == pytest.approx(0.7)
        assert out.markers[0].start_sec == pytest.approx(0.0)


class TestNoHeatmap:
    def test_no_ytInitialData_returns_empty(self):
        with patch.object(s02_heatmap, "_fetch_page", return_value="<html>no data</html>"):
            out = s02_heatmap.run(HeatmapInput(video_id="TEST123"), _make_ctx())
        assert out.markers == []
