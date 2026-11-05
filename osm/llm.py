"""Claude calls: extraction, critic pass and one grounded revision."""

from __future__ import annotations

import json
import os

from .fetch import Report
from .schema import CRITIC_TOOL, SIGNAL_TOOL, CriticReport, Signal

MODEL = os.environ.get("OSM_MODEL", "claude-sonnet-5-5")
CRITIC_MODEL = os.environ.get("OSM_CRITIC_MODEL", MODEL)

EXTRACT_SYSTEM = """You turn WHO Disease Outbreak News reports into structured outbreak signals for public health analysts.

Rules, in priority order:
1. Use ONLY the report text. Never add figures, dates, countries or risk levels from your own knowledge.
2. Copy every number exactly as written (keep commas, decimals and units). Do not round, sum or convert.
3. Every figure's `quote` must be copied verbatim from the report, so it can be string-matched.
4. If WHO does not state something (deaths, trend, a risk level), leave it out and add it to `gaps`. Do not guess.
5. Prefer the most recent cumulative figures when a report gives several time points; label the as_of date.
6. Write for a busy decision-maker: plain language, no hedging filler."""

CRITIC_SYSTEM = """You are a strict fact-checker for public health briefings. A wrong case count in an outbreak brief is dangerous, so be skeptical.

Split the headline and summary into individual factual claims. For each one, decide whether the source report directly supports it.
A claim is unsupported if it: adds information not in the source, changes or rounds a number, misattributes a figure to the wrong place or date, overstates certainty or severity, or contradicts the source.
Paraphrase is fine when the meaning is unchanged."""


def _tool_call(client, model: str, system: str, tool: dict, content: str, max_tokens: int = 8000) -> dict:
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        temperature=0,
        system=system + f"\n\nAlways respond by calling the `{tool['name']}` tool exactly once.",
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": content}],
    )
    # Some models reject forced tool choice or temperature. Drop whichever setting the API names and retry.
    for _ in range(3):
        try:
            msg = client.messages.create(**kwargs)
            break
        except Exception as e:
            text = str(e)
            if "tool_choice" in text and kwargs.get("tool_choice", {}).get("type") != "auto":
                kwargs["tool_choice"] = {"type": "auto"}
            elif "temperature" in text and "temperature" in kwargs:
                kwargs.pop("temperature")
            else:
                raise
    else:
        raise RuntimeError("Could not find request settings this model accepts")

    for block in msg.content:
        if getattr(block, "type", None) == "tool_use":
            return block.input
    # Fallback: the model answered in text. Use the first JSON object it wrote.
    text = "".join(getattr(b, "text", "") for b in msg.content)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])
    raise RuntimeError("Model did not return a tool call")


def _source(report: Report) -> str:
    return f"<report id=\"{report.don_id}\" published=\"{report.published}\">\n# {report.title}\n\n{report.text}\n</report>"


def extract_signal(client, report: Report, feedback: list[str] | None = None) -> Signal:
    content = _source(report)
    if feedback:
        content += (
            "\n\nA previous draft failed these checks. Fix every one, using only the report:\n- "
            + "\n- ".join(feedback)
        )
    return Signal.model_validate(_tool_call(client, MODEL, EXTRACT_SYSTEM, SIGNAL_TOOL, content))


def critique(client, report: Report, signal: Signal) -> CriticReport:
    draft = json.dumps({"headline": signal.headline, "summary": signal.summary}, indent=2)
    content = f"{_source(report)}\n\n<draft>\n{draft}\n</draft>"
    return CriticReport.model_validate(_tool_call(client, CRITIC_MODEL, CRITIC_SYSTEM, CRITIC_TOOL, content))


def make_client():
    import anthropic

    return anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
