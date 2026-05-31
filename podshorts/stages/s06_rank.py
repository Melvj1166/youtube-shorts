from podshorts.types import Context, RankInput, RankOutput, ScoredSegment


def _normalize(values: list[float]) -> list[float]:
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [1.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def run(input: RankInput, ctx: Context) -> RankOutput:
    scored = input.scored

    if not scored:
        return RankOutput(selected=[])

    if len(scored) == 1:
        seg = scored[0]
        seg.normalized_llm_score = 1.0
        seg.normalized_heatmap_intensity = 1.0
        seg.final_score = 1.0
        return RankOutput(selected=[seg])

    llm_scores = [s.llm_score for s in scored]
    heatmap_scores = [s.segment.mean_heatmap_intensity for s in scored]

    norm_llm = _normalize(llm_scores)
    norm_heatmap = _normalize(heatmap_scores)

    for seg, nl, nh in zip(scored, norm_llm, norm_heatmap):
        seg.normalized_llm_score = nl
        seg.normalized_heatmap_intensity = nh
        seg.final_score = 0.6 * nl + 0.4 * nh

    sorted_candidates = sorted(scored, key=lambda s: s.final_score, reverse=True)

    selected: list[ScoredSegment] = []
    for candidate in sorted_candidates:
        if len(selected) >= input.top_n:
            break
        start = candidate.segment.start
        too_close = any(abs(start - sel.segment.start) < 60.0 for sel in selected)
        if not too_close:
            selected.append(candidate)

    ctx.logger.info(
        "s06_rank: selected %d/%d segments (top_n=%d)",
        len(selected),
        len(scored),
        input.top_n,
    )

    return RankOutput(selected=selected)
