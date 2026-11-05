"""The structured 'outbreak signal' Claude extracts from a WHO DON report.

Every figure carries the verbatim sentence it came from, so each number can be
checked against the source mechanically instead of trusted.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class Figure(BaseModel):
    label: str = Field(description="What is counted, e.g. 'confirmed cases', 'deaths', 'suspected cases', 'CFR'.")
    value: str = Field(description="The number exactly as written in the source, e.g. '1,204' or '3.2%'.")
    as_of: Optional[str] = Field(None, description="Date or period the figure refers to, if stated.")
    quote: str = Field(description="Verbatim sentence or clause from the source that contains this value.")


class RiskLevel(BaseModel):
    scope: Literal["national", "regional", "global"]
    level: Literal["very low", "low", "moderate", "high", "very high"]
    quote: str = Field(description="Verbatim text from the Assessment section stating this level.")


class Signal(BaseModel):
    disease: str
    pathogen: Optional[str] = None
    countries: list[str]
    headline: str = Field(description="One sentence, 25 words max, for an analyst skimming a feed.")
    figures: list[Figure] = Field(description="Every key case, death and rate figure. Empty if none stated.")
    trend: Literal["increasing", "stable", "decreasing", "unclear"]
    trend_quote: Optional[str] = Field(None, description="Verbatim text supporting the trend, if any.")
    who_risk: list[RiskLevel] = Field(description="WHO's stated risk levels. Empty if WHO did not state one.")
    key_response_actions: list[str] = Field(description="Up to 4 short bullets from the Response section.")
    summary: str = Field(description="3-4 sentence brief for a public health decision-maker. Only facts in the source.")
    gaps: list[str] = Field(description="Things a reader would want that the report does not state, e.g. 'no death count'.")


SIGNAL_TOOL = {
    "name": "record_outbreak_signal",
    "description": "Record the structured outbreak signal extracted from one WHO Disease Outbreak News report.",
    "input_schema": Signal.model_json_schema(),
}


class Verdict(BaseModel):
    claim: str
    supported: bool
    evidence: Optional[str] = Field(None, description="Verbatim source text supporting the claim, if any.")
    problem: Optional[str] = Field(None, description="If unsupported: what is wrong (invented, wrong number, overstated, etc.).")


class CriticReport(BaseModel):
    verdicts: list[Verdict] = Field(description="One verdict per factual claim in the headline and summary.")


CRITIC_TOOL = {
    "name": "record_fact_check",
    "description": "Record a claim-by-claim fact check of an outbreak summary against its source report.",
    "input_schema": CriticReport.model_json_schema(),
}
