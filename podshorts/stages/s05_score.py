from __future__ import annotations

import json

import ollama

from podshorts.exceptions import LLMError
from podshorts.types import Context, ScoreInput, ScoreOutput, ScoredSegment

_SYSTEM_PROMPT = (
    "You are a viral short-form video editor. Score the segment 0-10 on "
    "five dimensions. Return ONLY valid JSON, no prose."
)

_USER_PROMPT_TEMPLATE = """\
Podcast: {topic}
Duration: {duration}s
Transcript: \"\"\"{transcript}\"\"\"

Score these dimensions 0-10:
- hook: Does the opening grab attention in <3 seconds?
- standalone: Does it make sense without prior context?
- emotion: Does it evoke surprise, humor, insight, or strong opinion?
- quotability: Is there a memorable line?
- pacing: Is the energy appropriate for short-form?

Return: {{"hook": N, "standalone": N, "emotion": N, "quotability": N, "pacing": N, "reason": "one sentence"}}"""

_RETRY_SYSTEM_PROMPT = (
    "Return ONLY a valid JSON object with keys: "
    "hook, standalone, emotion, quotability, pacing (each 0-10), and reason (string). "
    "No prose, no markdown, no explanation."
)

_DIMENSIONS = ("hook", "standalone", "emotion", "quotability", "pacing")
_WEIGHTS = {"hook": 0.3, "standalone": 0.25, "emotion": 0.2, "quotability": 0.15, "pacing": 0.1}
_FALLBACK_SCORE = 5.0
_FALLBACK_REASON = "parse_failed"


def run(input: ScoreInput, ctx: Context) -> ScoreOutput:
    logger = ctx.logger
    client = ollama.Client(host=ctx.config.ollama_host)
    model = ctx.config.ollama_model

    logger.info(
        "Scoring %d candidate segments with model %s",
        len(input.candidates),
        model,
    )

    scored: list[ScoredSegment] = []
    for segment in input.candidates:
        scores, reason = _score_segment(segment, input.podcast_topic, client, model, logger)
        llm_score = (
            scores["hook"] * _WEIGHTS["hook"]
            + scores["standalone"] * _WEIGHTS["standalone"]
            + scores["emotion"] * _WEIGHTS["emotion"]
            + scores["quotability"] * _WEIGHTS["quotability"]
            + scores["pacing"] * _WEIGHTS["pacing"]
        )
        logger.debug(
            "Segment %s: llm_score=%.3f reason=%r",
            segment.segment_id,
            llm_score,
            reason,
        )
        scored.append(
            ScoredSegment(
                segment=segment,
                hook=scores["hook"],
                standalone=scores["standalone"],
                emotion=scores["emotion"],
                quotability=scores["quotability"],
                pacing=scores["pacing"],
                llm_score=llm_score,
                reason=reason,
            )
        )

    return ScoreOutput(scored=scored)


def _score_segment(
    segment,
    podcast_topic: str | None,
    client: ollama.Client,
    model: str,
    logger,
) -> tuple[dict[str, float], str]:
    duration = round(segment.end - segment.start, 1)
    topic = podcast_topic or "Unknown"

    user_prompt = _USER_PROMPT_TEMPLATE.format(
        topic=topic,
        duration=duration,
        transcript=segment.transcript,
    )

    # First attempt
    try:
        text = _chat(client, model, _SYSTEM_PROMPT, user_prompt)
        return _parse_scores(text)
    except (ValueError, KeyError):
        logger.warning(
            "Segment %s: JSON parse failed on first attempt, retrying",
            segment.segment_id,
        )

    # Retry with stricter prompt
    retry_user = (
        f"Return ONLY valid JSON with keys hook, standalone, emotion, "
        f"quotability, pacing (integers 0-10) and reason (string). "
        f"Transcript: \"\"\"{segment.transcript}\"\"\""
    )
    try:
        text = _chat(client, model, _RETRY_SYSTEM_PROMPT, retry_user)
        return _parse_scores(text)
    except (ValueError, KeyError):
        logger.warning(
            "Segment %s: JSON parse failed on retry, using fallback scores",
            segment.segment_id,
        )

    fallback = {dim: _FALLBACK_SCORE for dim in _DIMENSIONS}
    return fallback, _FALLBACK_REASON


def _chat(client: ollama.Client, model: str, system: str, user: str) -> str:
    try:
        response = client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            options={"temperature": 0.2},
        )
        return response["message"]["content"]
    except Exception as exc:
        raise LLMError(f"Ollama request failed: {exc}", exc) from exc


def _parse_scores(text: str) -> tuple[dict[str, float], str]:
    # Strip markdown fences if present
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Remove first and last fence lines
        inner = lines[1:] if lines[0].startswith("```") else lines
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        stripped = "\n".join(inner).strip()

    data = json.loads(stripped)

    scores: dict[str, float] = {}
    for dim in _DIMENSIONS:
        val = data[dim]  # raises KeyError if missing
        scores[dim] = float(val)

    reason: str = str(data.get("reason", ""))
    return scores, reason
