from podshorts.types import Context, SegmentInput, SegmentOutput


def run(input: SegmentInput, ctx: Context) -> SegmentOutput:
    # TODO: Step 5 — use pysbd for sentence boundaries, sliding window over
    # heatmap peaks, fixed-stride fallback, dedup by >50% IoU.
    raise NotImplementedError("s04_segment not yet implemented")
