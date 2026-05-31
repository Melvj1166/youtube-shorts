from __future__ import annotations

from podshorts.types import Context, HeatmapMarker, Segment, SegmentInput, SegmentOutput, Word


def run(input: SegmentInput, ctx: Context) -> SegmentOutput:
    logger = ctx.logger
    words = input.words
    heatmap = input.heatmap
    duration = input.duration
    min_dur = ctx.config.min_short_duration
    max_dur = ctx.config.max_short_duration

    if not words:
        logger.info("No words found; returning empty candidates")
        return SegmentOutput(candidates=[])

    # --- Step 1: sentence boundaries via pysbd ---
    sentence_boundaries = _sentence_boundaries(words)
    logger.debug("Detected %d sentence boundaries", len(sentence_boundaries))

    # --- Step 2a: heatmap-driven candidates ---
    candidates: list[tuple[float, float]] = []

    if heatmap:
        heatmap_candidates = _heatmap_candidates(heatmap, sentence_boundaries, words, min_dur, max_dur)
        logger.debug("Heatmap-driven candidates: %d", len(heatmap_candidates))
        candidates.extend(heatmap_candidates)
    else:
        logger.debug("Heatmap empty; skipping heatmap-driven step")

    # --- Step 2b: fixed-stride fallback ---
    stride_candidates = _stride_candidates(duration, sentence_boundaries, words, min_dur, max_dur)
    logger.debug("Fixed-stride candidates: %d", len(stride_candidates))
    candidates.extend(stride_candidates)

    # --- Step 3: deduplicate by IoU > 0.5, keep higher mean heatmap intensity ---
    segments = _build_segments(candidates, words, heatmap)
    deduped = _deduplicate(segments)
    logger.info("Segments after dedup: %d (from %d raw candidates)", len(deduped), len(candidates))

    # --- Step 5: assign IDs ---
    result: list[Segment] = []
    for i, seg in enumerate(deduped):
        result.append(Segment(
            segment_id=f"seg_{i:03d}",
            start=seg.start,
            end=seg.end,
            transcript=seg.transcript,
            mean_heatmap_intensity=seg.mean_heatmap_intensity,
            word_indices=seg.word_indices,
        ))

    return SegmentOutput(candidates=result)


# ---------------------------------------------------------------------------
# Sentence boundary detection
# ---------------------------------------------------------------------------

def _sentence_boundaries(words: list[Word]) -> list[int]:
    """Return list of word indices that END a sentence (inclusive upper bound).

    We concatenate word texts with a space separator, run pysbd, then map
    character offsets back to word indices.
    """
    import pysbd

    full_text = " ".join(w.text for w in words)
    segmenter = pysbd.Segmenter(language="en", clean=False)
    sentences = segmenter.segment(full_text)

    # Build cumulative char positions per word (accounting for spaces).
    # cum_end[i] = index of the last character (inclusive) of words[i] in full_text.
    cum_end: list[int] = []
    pos = 0
    for i, word in enumerate(words):
        pos += len(word.text)
        cum_end.append(pos - 1)  # last char index of this word
        pos += 1  # space separator

    # For each sentence, find which word its last character falls in.
    boundaries: list[int] = []
    char_cursor = 0
    word_cursor = 0
    for sent in sentences:
        char_cursor += len(sent)
        # Advance word_cursor until cum_end covers the sentence end.
        sent_end_char = char_cursor - 1
        while word_cursor < len(words) - 1 and cum_end[word_cursor] < sent_end_char:
            word_cursor += 1
        boundaries.append(word_cursor)

    # Always include the last word as a boundary.
    if not boundaries or boundaries[-1] != len(words) - 1:
        boundaries.append(len(words) - 1)

    return boundaries


# ---------------------------------------------------------------------------
# Helpers: expand to sentence boundaries
# ---------------------------------------------------------------------------

def _expand_to_sentences(
    center_start: float,
    center_end: float,
    sentence_boundaries: list[int],
    words: list[Word],
    min_dur: float,
    max_dur: float,
) -> tuple[float, float] | None:
    """Expand a raw time window outward to the nearest sentence boundaries
    until the segment is within [min_dur, max_dur].  Returns None if
    a valid window cannot be formed.
    """
    # Find the sentence that contains center_start and center_end.
    # sentence_boundaries[k] is the last word index of sentence k.
    # Sentence k spans words[prev+1 .. boundaries[k]] where prev = boundaries[k-1].

    def sent_start_word(k: int) -> int:
        return 0 if k == 0 else sentence_boundaries[k - 1] + 1

    def sent_end_word(k: int) -> int:
        return sentence_boundaries[k]

    num_sents = len(sentence_boundaries)

    # Find sentence index that contains center_start.
    lo_sent = 0
    for k in range(num_sents):
        if words[sent_end_word(k)].end >= center_start:
            lo_sent = k
            break
    else:
        lo_sent = num_sents - 1

    # Find sentence index that contains center_end.
    hi_sent = lo_sent
    for k in range(lo_sent, num_sents):
        if words[sent_start_word(k)].start <= center_end:
            hi_sent = k
        else:
            break

    # Expand outward until [min_dur, max_dur] is satisfied.
    while True:
        seg_start = words[sent_start_word(lo_sent)].start
        seg_end = words[sent_end_word(hi_sent)].end
        dur = seg_end - seg_start

        if dur > max_dur:
            # Sentence block is too large; fall back to raw clamped window.
            break

        if dur >= min_dur:
            return (seg_start, seg_end)

        # Too short — try to expand.
        expanded = False
        if hi_sent < num_sents - 1:
            hi_sent += 1
            expanded = True
        if lo_sent > 0:
            lo_sent -= 1
            expanded = True
        if not expanded:
            break

    # Fall back: use the raw requested window clamped to [min_dur, max_dur].
    raw_dur = center_end - center_start
    if raw_dur < min_dur:
        center_end = center_start + min_dur
    elif raw_dur > max_dur:
        center_end = center_start + max_dur
    raw_dur = center_end - center_start
    if min_dur <= raw_dur <= max_dur:
        return (center_start, center_end)
    return None


# ---------------------------------------------------------------------------
# Heatmap-driven candidates
# ---------------------------------------------------------------------------

def _heatmap_candidates(
    heatmap: list[HeatmapMarker],
    sentence_boundaries: list[int],
    words: list[Word],
    min_dur: float,
    max_dur: float,
) -> list[tuple[float, float]]:
    from scipy.signal import find_peaks

    intensities = [m.intensity for m in heatmap]
    peak_indices, _ = find_peaks(intensities, prominence=0.15, distance=8)

    candidates: list[tuple[float, float]] = []
    for pi in peak_indices:
        marker = heatmap[pi]
        peak_ts = (marker.start_sec + marker.end_sec) / 2.0
        half = max_dur / 2.0
        raw_start = max(0.0, peak_ts - half)
        raw_end = raw_start + max_dur

        result = _expand_to_sentences(raw_start, raw_end, sentence_boundaries, words, min_dur, max_dur)
        if result is not None:
            candidates.append(result)

    return candidates


# ---------------------------------------------------------------------------
# Fixed-stride candidates
# ---------------------------------------------------------------------------

def _stride_candidates(
    duration: float,
    sentence_boundaries: list[int],
    words: list[Word],
    min_dur: float,
    max_dur: float,
) -> list[tuple[float, float]]:
    stride = 30.0
    candidates: list[tuple[float, float]] = []
    t = 0.0
    while t < duration:
        raw_end = min(t + stride, duration)
        result = _expand_to_sentences(t, raw_end, sentence_boundaries, words, min_dur, max_dur)
        if result is not None:
            candidates.append(result)
        t += stride
    return candidates


# ---------------------------------------------------------------------------
# Build Segment objects from raw (start, end) pairs
# ---------------------------------------------------------------------------

def _build_segments(
    candidates: list[tuple[float, float]],
    words: list[Word],
    heatmap: list[HeatmapMarker],
) -> list[Segment]:
    segments: list[Segment] = []
    for i, (start, end) in enumerate(candidates):
        word_indices = [j for j, w in enumerate(words) if w.start >= start and w.end <= end]
        transcript = " ".join(words[j].text for j in word_indices)
        intensity = _mean_intensity(start, end, heatmap)
        segments.append(Segment(
            segment_id=f"_tmp_{i}",
            start=start,
            end=end,
            transcript=transcript,
            mean_heatmap_intensity=intensity,
            word_indices=word_indices,
        ))
    return segments


# ---------------------------------------------------------------------------
# IoU deduplication
# ---------------------------------------------------------------------------

def _iou(a: Segment, b: Segment) -> float:
    inter_start = max(a.start, b.start)
    inter_end = min(a.end, b.end)
    intersection = max(0.0, inter_end - inter_start)
    if intersection == 0.0:
        return 0.0
    union = (a.end - a.start) + (b.end - b.start) - intersection
    return intersection / union if union > 0.0 else 0.0


def _deduplicate(segments: list[Segment]) -> list[Segment]:
    kept: list[Segment] = []
    for seg in segments:
        dominated = False
        to_remove: list[int] = []
        for ki, ks in enumerate(kept):
            if _iou(seg, ks) > 0.5:
                if seg.mean_heatmap_intensity > ks.mean_heatmap_intensity:
                    to_remove.append(ki)
                else:
                    dominated = True
                    break
        if dominated:
            continue
        # Remove dominated kept segments (in reverse order to preserve indices).
        for ki in reversed(to_remove):
            kept.pop(ki)
        kept.append(seg)
    return kept


# ---------------------------------------------------------------------------
# Heatmap intensity averaging
# ---------------------------------------------------------------------------

def _mean_intensity(start: float, end: float, heatmap: list[HeatmapMarker]) -> float:
    overlapping = [
        m.intensity
        for m in heatmap
        if m.start_sec < end and m.end_sec > start
    ]
    if not overlapping:
        return 0.0
    return sum(overlapping) / len(overlapping)
