"""Deterministic grounding checks. No model involved: these are string and number matches against the source."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .schema import Signal

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "\xa0": " "})
_NUM = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
# Numbers that are almost always structural, not epidemiological claims.
_IGNORE = {str(n) for n in range(0, 11)}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").translate(_QUOTES)).strip().lower()


_UNITS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
          "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_WORD_NUM = re.compile(
    r"\b(?:(" + "|".join(_TENS[2:]) + r")(?:[- ](" + "|".join(_UNITS[1:10]) + r"))?|(" + "|".join(_UNITS) + r"))\b",
    re.IGNORECASE,
)


def _words_to_digits(text: str) -> str:
    """WHO often spells out small counts ('two deaths', 'Sixteen health workers'). Convert them so they compare as numbers."""
    def repl(m: re.Match) -> str:
        tens, unit, single = (g.lower() if g else None for g in m.groups())
        if single:
            return str(_UNITS.index(single))
        return str(_TENS.index(tens) * 10 + (_UNITS.index(unit) if unit else 0))
    return _WORD_NUM.sub(repl, text or "")


def numbers_in(text: str) -> set[str]:
    out = set()
    for m in _NUM.findall(_words_to_digits(text)):
        n = m.replace(",", "")
        if "." in n:
            n = n.rstrip("0").rstrip(".")  # 3.50 == 3.5
        out.add(n)
    return out


def quote_found(quote: str, source: str, threshold: float = 0.92) -> bool:
    q, s = norm(quote), norm(source)
    if not q:
        return False
    if q in s:
        return True
    # Tolerate tiny copy differences (dropped punctuation, a trimmed clause).
    match = SequenceMatcher(None, s, q, autojunk=False).find_longest_match(0, len(s), 0, len(q))
    return match.size / len(q) >= threshold


@dataclass
class CheckResult:
    figures_total: int = 0
    figures_quote_ok: int = 0
    figures_value_ok: int = 0
    risk_total: int = 0
    risk_ok: int = 0
    prose_numbers_total: int = 0
    prose_numbers_ok: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def check_signal(signal: Signal, source: str) -> CheckResult:
    r = CheckResult()
    src_numbers = numbers_in(source)

    for f in signal.figures:
        r.figures_total += 1
        if quote_found(f.quote, source):
            r.figures_quote_ok += 1
        else:
            r.failures.append(f"Figure '{f.label}' quote is not verbatim in the report: \"{f.quote[:120]}\"")
        value_nums = numbers_in(f.value)
        if value_nums and value_nums <= numbers_in(f.quote) and value_nums <= src_numbers:
            r.figures_value_ok += 1
        else:
            r.failures.append(f"Figure '{f.label}' value '{f.value}' does not appear in its quote/source")

    for risk in signal.who_risk:
        r.risk_total += 1
        if quote_found(risk.quote, source) and risk.level in norm(risk.quote):
            r.risk_ok += 1
        else:
            r.failures.append(f"Risk '{risk.scope}: {risk.level}' is not supported verbatim by the Assessment")

    # Every number in the prose a human will actually read must exist in the source.
    for n in numbers_in(f"{signal.headline} {signal.summary}") - _IGNORE:
        r.prose_numbers_total += 1
        if n in src_numbers:
            r.prose_numbers_ok += 1
        else:
            r.failures.append(f"Number '{n}' in headline/summary does not appear in the report")

    return r
