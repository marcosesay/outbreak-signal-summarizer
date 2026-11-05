"""Offline tests: a synthetic report and a fake Claude client. No network or API key needed."""

import csv
from types import SimpleNamespace

from osm.evaluate import run_eval, score_review
from osm.fetch import Report, parse_item
from osm.pipeline import summarize
from osm.verify import check_signal, numbers_in

# SYNTHETIC fixture, not a real WHO report.
REPORT = Report(
    don_id="TEST-DON001",
    title="Cholera - Exampleland",
    published="2026-10-01",
    url="https://example.org/don001",
    sections={
        "Summary": "As of 20 September 2026, a total of 1,204 suspected cholera cases, including 37 deaths (CFR 3.1%), have been reported in Exampleland. Cases are increasing in the northern districts.",
        "Assessment": "WHO assesses the risk at the national level as high and the risk at the global level as low.",
        "Response": "The Ministry of Health has deployed oral cholera vaccine and rapid response teams.",
    },
)

GOOD = {
    "disease": "Cholera", "pathogen": "Vibrio cholerae", "countries": ["Exampleland"],
    "headline": "Exampleland reports 1,204 suspected cholera cases and 37 deaths; national risk high.",
    "figures": [
        {"label": "suspected cases", "value": "1,204", "as_of": "20 September 2026",
         "quote": "As of 20 September 2026, a total of 1,204 suspected cholera cases, including 37 deaths (CFR 3.1%), have been reported in Exampleland."},
        {"label": "deaths", "value": "37", "quote": "including 37 deaths (CFR 3.1%)"},
    ],
    "trend": "increasing", "trend_quote": "Cases are increasing in the northern districts.",
    "who_risk": [{"scope": "national", "level": "high", "quote": "the risk at the national level as high"}],
    "key_response_actions": ["Oral cholera vaccine deployed"],
    "summary": "Exampleland has 1,204 suspected cholera cases and 37 deaths as of 20 September 2026. WHO rates national risk high.",
    "gaps": ["No laboratory-confirmed count"],
}
BAD = GOOD | {"headline": "Exampleland reports 1,240 cholera cases.", "summary": "Exampleland has 1,240 cases and 41 deaths."}
OK_CRITIC = {"verdicts": [{"claim": "1,204 suspected cases", "supported": True, "evidence": "1,204 suspected"}]}
BAD_CRITIC = {"verdicts": [{"claim": "41 deaths", "supported": False, "problem": "source says 37"}]}


class FakeClient:
    """Returns queued tool inputs in order, mimicking client.messages.create."""

    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        block = SimpleNamespace(type="tool_use", input=self.outputs.pop(0))
        return SimpleNamespace(content=[block])


def test_numbers_parse_thousands_and_dates():
    assert numbers_in("1,204 cases on 20 September 2026, 15 deaths (3.10%)") == {"1204", "20", "2026", "15", "3.1"}


def test_clean_signal_passes_checks():
    from osm.schema import Signal
    r = check_signal(Signal.model_validate(GOOD), REPORT.text)
    assert r.passed, r.failures
    assert r.figures_value_ok == 2 and r.risk_ok == 1


def test_hallucinated_numbers_are_caught():
    from osm.schema import Signal
    r = check_signal(Signal.model_validate(BAD), REPORT.text)
    assert any("1240" in f for f in r.failures) and any("41" in f for f in r.failures)


def test_bad_draft_is_revised():
    client = FakeClient([BAD, BAD_CRITIC, GOOD, OK_CRITIC])
    res = summarize(client, REPORT)
    assert res.revised and res.final.clean and not res.first.clean
    assert "previous draft failed" in client.calls[2]["messages"][0]["content"]
    assert client.calls[0]["tool_choice"]["type"] == "tool" and client.calls[0]["temperature"] == 0


def test_eval_and_human_scoring(tmp_path):
    client = FakeClient([GOOD, OK_CRITIC])
    summary = run_eval(client, [REPORT], tmp_path, log=lambda *_: None)
    assert summary["final"]["clean_reports"] == "1/1 (100%)"
    sheet = tmp_path / "review_sheet.csv"
    rows = list(csv.DictReader(sheet.open()))
    for row in rows:
        row["human_verdict"] = "correct"
    with sheet.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    scored = score_review(sheet)
    assert scored["reports_fully_correct"] == "1/1 (100%)"
    assert (tmp_path / "REPORT.md").read_text().startswith("# Eval report")


def test_parse_api_item_strips_html():
    rep = parse_item({"DonId": "2026-DON999", "Title": "X", "UrlName": "2026-DON999",
                      "PublicationDateAndTime": "2026-10-01T00:00:00Z",
                      "Summary": "<p>Cases&nbsp;rose to <strong>12</strong>.</p>"})
    assert rep.sections["Summary"] == "Cases rose to 12." and rep.url.endswith("2026-DON999")


def test_falls_back_when_forced_tool_choice_rejected():
    from osm.llm import _tool_call

    class Picky(FakeClient):
        def create(self, **kw):
            if kw["tool_choice"]["type"] == "tool":
                raise Exception('tool_choice: type "tool" and "any" are not supported for this model.')
            return super().create(**kw)

    client = Picky([OK_CRITIC])
    assert _tool_call(client, "m", "sys", {"name": "t"}, "hi") == OK_CRITIC
    assert client.calls[0]["tool_choice"] == {"type": "auto"}


def test_spelled_out_numbers_match():
    assert numbers_in("Sixteen health workers, nine cases and twenty-one deaths") == {"16", "9", "21"}
    from osm.schema import Signal
    sig = Signal.model_validate(GOOD | {"figures": [
        {"label": "deaths", "value": "two", "quote": "Two deaths were reported in Exampleland."}]})
    src = "Two deaths were reported in Exampleland. " + REPORT.text
    assert check_signal(sig, src).figures_value_ok == 1


def test_rescore_without_api(tmp_path):
    import json
    from osm.evaluate import rescore
    run_eval(FakeClient([GOOD, OK_CRITIC]), [REPORT], tmp_path, log=lambda *_: None)
    summary = rescore(tmp_path, [REPORT])
    assert summary["final"]["clean_reports"] == "1/1 (100%)"
    assert json.loads((tmp_path / "results.jsonl").read_text())["final"]["checks"]["passed"]
