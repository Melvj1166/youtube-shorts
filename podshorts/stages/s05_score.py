from podshorts.types import Context, ScoreInput, ScoreOutput


def run(input: ScoreInput, ctx: Context) -> ScoreOutput:
    # TODO: Step 5 — Ollama qwen2.5:7b, 5-dimension JSON scoring per segment.
    # Composite = hook*0.3 + standalone*0.25 + emotion*0.2 + quotability*0.15 + pacing*0.1
    raise NotImplementedError("s05_score not yet implemented")
