"""Extract -> check -> (revise once) -> check. The result records both passes so the eval can show what the critic caught."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .fetch import Report
from .llm import critique, extract_signal
from .schema import CriticReport, Signal
from .verify import CheckResult, check_signal


@dataclass
class Pass:
    signal: Signal
    checks: CheckResult
    critic: CriticReport

    @property
    def unsupported(self) -> list[str]:
        return [f"{v.claim} ({v.problem or 'unsupported'})" for v in self.critic.verdicts if not v.supported]

    @property
    def clean(self) -> bool:
        return self.checks.passed and not self.unsupported

    def to_json(self) -> dict:
        return {
            "signal": self.signal.model_dump(),
            "checks": asdict(self.checks) | {"passed": self.checks.passed},
            "critic": self.critic.model_dump(),
            "clean": self.clean,
        }


@dataclass
class Result:
    report: Report
    first: Pass
    final: Pass

    @property
    def revised(self) -> bool:
        return self.first is not self.final

    def to_json(self) -> dict:
        return {
            "don_id": self.report.don_id,
            "title": self.report.title,
            "published": self.report.published,
            "url": self.report.url,
            "revised": self.revised,
            "first": self.first.to_json(),
            "final": self.final.to_json(),
        }


def _run_pass(client, report: Report, feedback: list[str] | None = None) -> Pass:
    signal = extract_signal(client, report, feedback)
    return Pass(signal, check_signal(signal, report.text), critique(client, report, signal))


def summarize(client, report: Report, revise: bool = True) -> Result:
    first = _run_pass(client, report)
    if first.clean or not revise:
        return Result(report, first, first)
    final = _run_pass(client, report, feedback=first.checks.failures + first.unsupported)
    # Never ship a revision that is worse than the draft.
    if len(final.checks.failures) + len(final.unsupported) > len(first.checks.failures) + len(first.unsupported):
        final = first
    return Result(report, first, final)
