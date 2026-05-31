from podshorts.types import Context, RankInput, RankOutput


def run(input: RankInput, ctx: Context) -> RankOutput:
    # TODO: Step 5 — final_score = 0.6*norm_llm + 0.4*norm_heatmap.
    # Enforce 60s minimum gap between selected segments.
    raise NotImplementedError("s06_rank not yet implemented")
