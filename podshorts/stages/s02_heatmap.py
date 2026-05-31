from __future__ import annotations

import json
import re

import httpx
import numpy as np
from scipy.signal import find_peaks

from podshorts.exceptions import HeatmapParseError
from podshorts.types import Context, HeatmapInput, HeatmapMarker, HeatmapOutput

_YT_INITIAL_DATA_RE = re.compile(r"var ytInitialData\s*=\s*(\{.*?\});\s*</script>", re.DOTALL)


def run(input: HeatmapInput, ctx: Context) -> HeatmapOutput:
    logger = ctx.logger
    logger.info("Fetching heatmap for %s", input.video_id)

    html = _fetch_page(input.video_id)
    markers = _parse_heatmap(html, input.video_id, logger)

    if markers:
        _log_peak_summary(markers, logger)
    else:
        logger.warning("No heatmap data for %s — ranking will use LLM-only scoring", input.video_id)

    return HeatmapOutput(markers=markers)


def _fetch_page(video_id: str) -> str:
    url = f"https://www.youtube.com/watch?v={video_id}"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(follow_redirects=True, timeout=15.0) as client:
        resp = client.get(url, headers=headers)
    resp.raise_for_status()
    return resp.text


def _parse_heatmap(html: str, video_id: str, logger) -> list[HeatmapMarker]:
    match = _YT_INITIAL_DATA_RE.search(html)
    if not match:
        logger.warning("ytInitialData not found in page for %s", video_id)
        return []

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise HeatmapParseError(f"Failed to parse ytInitialData: {exc}", exc) from exc

    heat_markers = _walk_for_heat_markers(data)
    if not heat_markers:
        return []

    result: list[HeatmapMarker] = []
    for m in heat_markers:
        # Modern API: startMillis / durationMillis / intensityScoreNormalized
        # Legacy API: timeRangeStartMillis / markerDurationMillis / heatMarkerIntensityScoreNormalized
        start_ms = float(
            m.get("startMillis") or m.get("timeRangeStartMillis") or 0
        )
        dur_ms = float(
            m.get("durationMillis") or m.get("markerDurationMillis") or 0
        )
        intensity = float(
            m.get("intensityScoreNormalized")
            if m.get("intensityScoreNormalized") is not None
            else m.get("heatMarkerIntensityScoreNormalized", 0.0)
        )
        result.append(
            HeatmapMarker(
                start_sec=start_ms / 1000.0,
                end_sec=(start_ms + dur_ms) / 1000.0,
                intensity=intensity,
            )
        )

    return result


def _walk_for_heat_markers(data: dict) -> list[dict] | None:
    """Navigate ytInitialData to find heatmap markers.

    YouTube (2024+) stores markers in frameworkUpdates.entityBatchUpdate.mutations
    as macroMarkersListEntity with markerType MARKER_TYPE_HEATMAP.
    Older path (playerOverlays → markersMap) is tried as fallback.
    """
    # Modern path: frameworkUpdates → entityBatchUpdate → mutations
    mutations: list[dict] = (
        data.get("frameworkUpdates", {})
        .get("entityBatchUpdate", {})
        .get("mutations", [])
    )
    for mutation in mutations:
        payload = mutation.get("payload", {})
        entity = payload.get("macroMarkersListEntity", {})
        markers_list = entity.get("markersList", {})
        marker_type = markers_list.get("markerType", "")
        if "HEATMAP" in str(marker_type).upper():
            return markers_list.get("markers", []) or None

    # Legacy fallback: playerOverlays → multiMarkersPlayerBarRenderer → markersMap
    overlays = data.get("playerOverlays", {})
    overlay = overlays.get("playerOverlayRenderer", {})
    decorated = overlay.get("decoratedPlayerBarRenderer", {})
    player_bar = decorated.get("playerBar", {})
    multi = player_bar.get("multiMarkersPlayerBarRenderer", {})
    markers_map: list[dict] = multi.get("markersMap", [])

    for entry in markers_map:
        key: str = entry.get("key", "")
        value: dict = entry.get("value", {})
        if "HEATSEEKER" in key.upper() or "HEATMAP" in key.upper():
            return _extract_legacy_heat_markers(value)
        if "HEATMAP" in str(value.get("markerType", "")).upper():
            return _extract_legacy_heat_markers(value)

    return None


def _extract_legacy_heat_markers(value: dict) -> list[dict] | None:
    heatmap = value.get("heatmap", {})
    renderer = heatmap.get("heatmapRenderer", {})
    markers = renderer.get("heatMarkers", [])
    if markers:
        return [m.get("heatMarkerRenderer", m) for m in markers]
    return None


def _log_peak_summary(markers: list[HeatmapMarker], logger) -> None:
    intensities = np.array([m.intensity for m in markers])
    peaks, _ = find_peaks(intensities, prominence=0.15, distance=8)

    logger.info(
        "Heatmap: %d markers, %d peaks (prominence>=0.15)",
        len(markers),
        len(peaks),
    )

    width = 60
    step = max(1, len(intensities) // width)
    sampled = intensities[::step][:width]
    bars = "".join(_bar_char(v) for v in sampled)
    logger.info("Intensity: [%s]", bars)

    for i in peaks[:5]:
        logger.info("  Peak at %.1fs (intensity=%.3f)", markers[i].start_sec, markers[i].intensity)


def _bar_char(v: float) -> str:
    blocks = " ▁▂▃▄▅▆▇█"
    idx = min(int(v * (len(blocks) - 1)), len(blocks) - 1)
    return blocks[idx]
