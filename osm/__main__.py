"""CLI:  python -m osm {fetch,summarize,eval,score-review}"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .fetch import fetch_reports, load_reports, save_reports

DATA = Path("data/reports")
EVAL = Path("eval/latest")


def _reports(args):
    reports = load_reports(DATA)
    if not reports:
        print("No cached reports, fetching from WHO...")
        reports = fetch_reports(args.n)
        save_reports(reports, DATA)
    return reports[: args.n]


def main() -> None:
    p = argparse.ArgumentParser(prog="osm", description="Outbreak Signal Summarizer")
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch", help="Download recent WHO DON reports to data/reports/")
    f.add_argument("-n", type=int, default=20)

    s = sub.add_parser("summarize", help="Summarize one report and print the checked signal")
    s.add_argument("don_id", nargs="?", help="DON id (default: most recent cached)")
    s.add_argument("-n", type=int, default=20)
    s.add_argument("--no-revise", action="store_true")

    e = sub.add_parser("eval", help="Run the accuracy eval over N cached reports")
    e.add_argument("-n", type=int, default=20)
    e.add_argument("--no-revise", action="store_true")
    e.add_argument("--out", type=Path, default=EVAL)

    rs = sub.add_parser("rescore", help="Re-run the deterministic checks on saved eval results (no API calls)")
    rs.add_argument("--out", type=Path, default=EVAL)

    r = sub.add_parser("score-review", help="Score a human-filled review_sheet.csv")
    r.add_argument("sheet", type=Path, nargs="?", default=EVAL / "review_sheet.csv")

    args = p.parse_args()

    if args.cmd == "fetch":
        reports = fetch_reports(args.n)
        save_reports(reports, DATA)
        for rep in reports:
            print(f"{rep.don_id:16} {rep.published}  {rep.title}")
        print(f"\nSaved {len(reports)} reports to {DATA}/")

    elif args.cmd == "summarize":
        from .llm import make_client
        from .pipeline import summarize

        reports = _reports(args)
        rep = next((x for x in reports if x.don_id == args.don_id), None) if args.don_id else reports[0]
        if rep is None:
            raise SystemExit(f"{args.don_id} not in {DATA}/")
        res = summarize(make_client(), rep, revise=not args.no_revise)
        print(json.dumps(res.to_json()["final"], indent=2))
        print(f"\nRevised: {res.revised}  Clean: {res.final.clean}  Source: {rep.url}")

    elif args.cmd == "eval":
        from .evaluate import run_eval
        from .llm import make_client

        summary = run_eval(make_client(), _reports(args), args.out, revise=not args.no_revise)
        print(json.dumps(summary, indent=2))
        print(f"\nWrote {args.out}/REPORT.md and {args.out}/review_sheet.csv (fill human_verdict, then run score-review)")

    elif args.cmd == "rescore":
        from .evaluate import rescore

        print(json.dumps(rescore(args.out, load_reports(DATA)), indent=2))
        print(f"\nUpdated {args.out}/REPORT.md, metrics.json and the review sheet")

    elif args.cmd == "score-review":
        from .evaluate import score_review

        print(json.dumps(score_review(args.sheet), indent=2))


if __name__ == "__main__":
    main()
