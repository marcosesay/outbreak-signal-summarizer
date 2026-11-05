"""Fetch WHO Disease Outbreak News (DON) reports from WHO's public, key-less API."""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

API_URL = "https://www.who.int/api/news/diseaseoutbreaknews"
ITEM_URL = "https://www.who.int/emergencies/disease-outbreak-news/item/{url_name}"

# Narrative sections of a DON report, in the order WHO publishes them.
SECTIONS = ["Overview", "Summary", "Epidemiology", "Response", "Assessment", "Advice", "FurtherInformation"]
SELECT = ["Id", "DonId", "Title", "OverrideTitle", "UseOverrideTitle", "UrlName", "PublicationDateAndTime", *SECTIONS]


@dataclass
class Report:
    don_id: str
    title: str
    published: str
    url: str
    sections: dict[str, str]

    @property
    def text(self) -> str:
        """Full plain-text body, section by section. This is the only source the model sees."""
        return "\n\n".join(f"## {name}\n{body}" for name, body in self.sections.items() if body)

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, d: dict) -> "Report":
        return cls(**d)


def clean_html(raw: str | None) -> str:
    if not raw:
        return ""
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", raw)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def parse_item(item: dict) -> Report:
    title = item.get("OverrideTitle") if item.get("UseOverrideTitle") and item.get("OverrideTitle") else item.get("Title", "")
    url_name = item.get("UrlName") or ""
    return Report(
        don_id=item.get("DonId") or url_name or str(item.get("Id")),
        title=clean_html(title),
        published=(item.get("PublicationDateAndTime") or "")[:10],
        url=ITEM_URL.format(url_name=url_name) if url_name else "",
        sections={s: clean_html(item.get(s)) for s in SECTIONS if clean_html(item.get(s))},
    )


def fetch_reports(n: int = 20, timeout: float = 30.0) -> list[Report]:
    """Return the n most recent DON reports that have enough text to summarize."""
    params = {"$orderby": "PublicationDateAndTime desc", "$top": str(n * 2), "$select": ",".join(SELECT)}
    resp = httpx.get(API_URL, params=params, timeout=timeout, headers={"Accept": "application/json"})
    resp.raise_for_status()
    items = resp.json().get("value", [])
    reports = [parse_item(i) for i in items]
    # Skip stubs: a usable report needs real epidemiological detail.
    reports = [r for r in reports if len(r.text) > 800]
    return reports[:n]


def save_reports(reports: list[Report], folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for r in reports:
        (folder / f"{r.don_id}.json").write_text(json.dumps(r.to_json(), indent=2))


def load_reports(folder: Path) -> list[Report]:
    return [Report.from_json(json.loads(p.read_text())) for p in sorted(folder.glob("*.json"), reverse=True)]
