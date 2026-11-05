"""Accuracy eval over N reports.

Three layers, cheapest to most trustworthy:
  1. Deterministic grounding: are quotes verbatim, do figures and prose numbers exist in the source?
  2. Model critic: claim-by-claim support check of the headline and summary.
  3. Human review: a CSV of every figure and claim for a person to mark correct / incorrect.
     The human numbers are the ones to report; the automated layers are what you run on every change.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .fetch import Report
from .pipeline import Result, summarize


def _rate(ok: int, total: int) -> str:
    return f"{ok}/{total} ({ok / total:.0%})" if total else "n/a"


def metrics(results: list[dict], which: str) -> dict:
    p = [r[which] for r in results]
    c = [x["checks"] for x in p]
    verdicts = [v for x in p for v in x["critic"]["verdicts"]]
    tot = lambda k: sum(x[k] for x in c)  # noqa: E731
    return {
        "reports": len(p),
        "clean_reports": _rate(sum(x["clean"] for x in p), len(p)),
        "figure_quotes_verbatim": _rate(tot("figures_quote_ok"), tot("figures_total")),
        "figure_values_grounded": _rate(tot("figures_value_ok"), tot("figures_total")),
        "risk_levels_grounded": _rate(tot("risk_ok"), tot("risk_total")),
        "prose_numbers_grounded": _rate(tot("prose_numbers_ok"), tot("prose_numbers_total")),
        "claims_supported_by_critic": _rate(sum(v["supported"] for v in verdicts), len(verdicts)),
    }


def run_eval(client, reports: list[Report], out: Path, revise: bool = True, log=print) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    with (out / "results.jsonl").open("w") as fh:
        for i, rep in enumerate(reports, 1):
            log(f"[{i}/{len(reports)}] {rep.don_id}  {rep.title[:70]}")
            try:
                res: Result = summarize(client, rep, revise=revise)
            except Exception as e:  # keep going; record the failure
                log(f"   ERROR: {e}")
                continue
            row = res.to_json()
            results.append(row)
            fh.write(json.dumps(row) + "\n")
            status = "clean" if res.final.clean else f"{len(res.final.checks.failures) + len(res.final.unsupported)} issues"
            log(f"   {'revised, ' if res.revised else ''}{status}")

    summary = {"draft": metrics(results, "first"), "final": metrics(results, "final"),
               "revised_reports": sum(r["revised"] for r in results)}
    (out / "metrics.json").write_text(json.dumps(summary, indent=2))
    write_review_sheet(results, out / "review_sheet.csv")
    write_report(results, summary, out / "REPORT.md")
    return summary


def rescore(out: Path, reports: list[Report]) -> dict:
    """Re-run the deterministic checks on saved results. No API calls: use this after changing verify.py."""
    from dataclasses import asdict

    from .schema import Signal
    from .verify import check_signal

    by_id = {r.don_id: r for r in reports}
    results = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines() if line.strip()]
    for r in results:
        source = by_id[r["don_id"]].text
        for which in ("first", "final"):
            p = r[which]
            checks = check_signal(Signal.model_validate(p["signal"]), source)
            p["checks"] = asdict(checks) | {"passed": checks.passed}
            p["clean"] = checks.passed and all(v["supported"] for v in p["critic"]["verdicts"])
    (out / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in results))
    summary = {"draft": metrics(results, "first"), "final": metrics(results, "final"),
               "revised_reports": sum(r["revised"] for r in results)}
    (out / "metrics.json").write_text(json.dumps(summary, indent=2))
    write_report(results, summary, out / "REPORT.md")
    sheet = out / "review_sheet.csv"
    already_reviewed = sheet.exists() and any(row["human_verdict"].strip() for row in csv.DictReader(sheet.open()))
    write_review_sheet(results, out / "review_sheet.rescored.csv" if already_reviewed else sheet)
    return summary


def write_review_sheet(results: list[dict], path: Path) -> None:
    """One row per checkable item. Fill `human_verdict` with correct / incorrect / partial, then run `osm score-review`."""
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["don_id", "url", "item_type", "item", "model_evidence", "auto_check", "human_verdict", "human_note"])
        for r in results:
            final, checks = r["final"], r["final"]["checks"]
            sig = final["signal"]
            for f in sig["figures"]:
                item = f"{f['label']}: {f['value']}" + (f" (as of {f['as_of']})" if f.get("as_of") else "")
                failed = any(f"'{f['label']}'" in x for x in checks["failures"])
                w.writerow([r["don_id"], r["url"], "figure", item, f["quote"], "fail" if failed else "pass", "", ""])
            for risk in sig["who_risk"]:
                w.writerow([r["don_id"], r["url"], "risk", f"{risk['scope']}: {risk['level']}", risk["quote"], "", "", ""])
            for v in final["critic"]["verdicts"]:
                w.writerow([r["don_id"], r["url"], "claim", v["claim"], v.get("evidence") or "",
                            "pass" if v["supported"] else f"fail: {v.get('problem') or ''}", "", ""])


def score_review(path: Path) -> dict:
    rows = [r for r in csv.DictReader(path.open()) if r["human_verdict"].strip()]
    if not rows:
        return {"reviewed_items": 0}
    by = lambda t: [r for r in rows if r["item_type"] == t]  # noqa: E731
    correct = lambda rs: sum(r["human_verdict"].strip().lower() == "correct" for r in rs)  # noqa: E731
    reports = {r["don_id"] for r in rows}
    perfect = {d for d in reports if all(r["human_verdict"].strip().lower() == "correct" for r in rows if r["don_id"] == d)}
    # How often the automated checks agreed with the human.
    auto = [r for r in rows if r["auto_check"]]
    agree = sum((r["auto_check"].startswith("pass")) == (r["human_verdict"].strip().lower() == "correct") for r in auto)
    return {
        "reviewed_reports": len(reports),
        "reports_fully_correct": _rate(len(perfect), len(reports)),
        "figures_correct": _rate(correct(by("figure")), len(by("figure"))),
        "risk_levels_correct": _rate(correct(by("risk")), len(by("risk"))),
        "claims_correct": _rate(correct(by("claim")), len(by("claim"))),
        "all_items_correct": _rate(correct(rows), len(rows)),
        "auto_checks_agree_with_human": _rate(agree, len(auto)),
    }


def write_report(results: list[dict], summary: dict, path: Path) -> None:
    lines = ["# Eval report", "", f"Reports evaluated: **{len(results)}**  ", f"Revised after critic: **{summary['revised_reports']}**", "",
             "| Metric | Draft | Final |", "|---|---|---|"]
    for k in summary["final"]:
        lines.append(f"| {k.replace('_', ' ')} | {summary['draft'][k]} | {summary['final'][k]} |")
    lines += ["", "## Per report", ""]
    for r in results:
        f = r["final"]
        lines.append(f"### [{r['don_id']}]({r['url']}) {r['title']}")
        lines.append(f"> {f['signal']['headline']}")
        issues = f["checks"]["failures"] + [f"{v['claim']} ({v.get('problem')})" for v in f["critic"]["verdicts"] if not v["supported"]]
        lines.append("")
        lines.append("Status: " + ("clean" + (" after revision" if r["revised"] else "") if not issues else "**issues remain**"))
        lines += [f"- {x}" for x in issues]
        if r["revised"]:
            caught = r["first"]["checks"]["failures"] + [v["claim"] for v in r["first"]["critic"]["verdicts"] if not v["supported"]]
            lines.append("<details><summary>Caught in draft</summary>\n")
            lines += [f"- {x}" for x in caught]
            lines.append("\n</details>")
        lines.append("")
    path.write_text("\n".join(lines))
