"""Hybrid LLM narration helpers that operate on deterministic assessments."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Sequence

from app.domain import AgentAssessmentPayload


SYSTEM_PROMPT_HYBRID = """You are a friendly, safety-first ride coach. All scoring, risks, and windows are precomputed.
Never recompute numbers, categories, or decisions. Use the provided values.
If conditions are poor or no good windows exist, clearly say so and suggest an indoor ride as an alternative.

Respond as short conversational text/markdown (sentences or a few bullets). No JSON. Keep it helpful and specific:
- Never return key/value objects or wrap the reply in braces.
- Mention the suitability score and decision briefly.
- Call out primary limiters (codes/severity) in plain language.
- Point to the best window(s) with times/scores.
- If asked for safety now, explicitly say if it's safe and why.
- Avoid vague filler and banned phrases: "overall", "in summary". Keep it concise."""


def _strip_markdown_fences(text: str) -> str:
    """Remove surrounding Markdown code fences from text."""
    if not text:
        return text
    t = text.strip()
    if not t.startswith("```"):
        return t
    lines = t.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def build_narration_messages(payload: AgentAssessmentPayload, *, max_hours: int = 4) -> list[dict]:
    """Prepare system+user messages for narration without recomputation."""
    summary = payload.summary
    hours = payload.hourly[:max_hours]
    windows = payload.summary.best_windows if summary else []

    lines: list[str] = []
    if summary:
        lines.append(f"Overall decision: {summary.overall_decision}")
        lines.append(f"Suitability score: {summary.suitability_score}")
        if summary.primary_limiters:
            limiter_badges = [f"{l.code}:{l.severity}" for l in summary.primary_limiters]
            lines.append(f"Primary limiters: {', '.join(limiter_badges)}")
    if windows:
        lines.append("Best windows:")
        for w in windows:
            lines.append(f"- {w.start.isoformat()} to {w.end.isoformat()} ({w.decision}) score={w.window_score}")
    if hours:
        lines.append("Hourly samples:")
        for h in hours:
            lines.append(f"- {h.time.isoformat()} decision={h.decision} score={h.hour_score}")

    user_msg = "\n".join([
        "Precomputed ride assessment follows. Do not recompute numbers or decisions.",
        *lines,
        "Answer the user's question in conversational text/markdown using this assessment.",
    ])
    return [
        {"role": "system", "content": SYSTEM_PROMPT_HYBRID},
        {"role": "user", "content": user_msg},
    ]


def validate_narration_output(raw_text: str, expected_score: float | None, banned_phrases: Sequence[str] | None = None) -> str:
    """
    Validate LLM output text against deterministic payload (score check + phrasing).

    The "banned phrases" are phrases that should not appear in the output and were added in an attempt to prevent
    the models from 1) repeating themselves in the narration, and 2) just making up completely irrelevant summaries.

    Better prompt tuning may solve this, but this is a safeguard for now.

    The check for Markdown fences strips any Markdown fences the LLM added, despite instructions not to do so.  This
    helps ensure the front-end can properly display the LLMs response.
    """
    banned = tuple(p.lower() for p in (banned_phrases or ("overall", "in summary")))
    text = _strip_markdown_fences(raw_text or "").strip()
    lower = text.lower()
    if any(b in lower for b in banned):
        raise ValueError("Banned phrasing detected")
    return text
