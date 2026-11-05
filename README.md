# Outbreak Signal Summarizer

Turns WHO Disease Outbreak News (DON) reports into short, structured briefs for public health decision-makers, and checks every number against the source before it ships.

A wrong case count in an outbreak brief is worse than no brief. So the design goal here isn't "summarize well," it's "never state a figure the report doesn't support."

## How it works

```
WHO DON API ──> extract (Claude) ──> grounding checks ──> critic (Claude) ──┐
                     ^                                                       │
                     └──────────── one revision with the failures ───────────┘
```

1. **Fetch.** Pulls recent reports from WHO's public DON API (no key needed) and strips them to plain text, section by section. That text is the only thing the model sees.
2. **Extract.** Claude fills a strict schema via forced tool use: disease, countries, headline, case and death figures, trend, WHO's stated risk levels, response actions, a 3-4 sentence summary, and `gaps` (what the report doesn't say). Every figure and risk level must carry the verbatim sentence it came from.
3. **Check, deterministically.** No model involved. Quotes are string-matched against the source, each figure's value must appear in its quote, risk levels must appear in the Assessment text, and every number in the headline and summary must exist in the report.
4. **Critique.** A second Claude pass splits the headline and summary into individual claims and marks each supported or unsupported, flagging rounding, invented detail, misattribution or overstated severity.
5. **Revise once.** If anything failed, Claude redrafts with the specific failures as feedback. A revision that is worse than the draft is discarded.

## Eval results

20 most recent DON reports (May to November 2026, mostly the DRC Bundibugyo Ebola outbreak, plus MERS, Nipah, yellow fever, hantavirus and others). Full per-report output is in [`eval/latest/REPORT.md`](eval/latest/REPORT.md).

| Metric | Final |
|---|---|
| Reports clean (all checks + critic pass) | 20/20 |
| Figure quotes verbatim in source | 212/212 |
| Figure values grounded | 212/212 |
| WHO risk levels grounded | 64/64 |
| Numbers in headline/summary found in source | 178/178 |
| Claims supported (critic) | 260/260 |

8 of 20 drafts were sent back for revision. Example: a draft for DON608 said contact follow-up was "about 70%" in Ituri and North Kivu. That figure isn't in the report, the prose check caught it, and the revised brief dropped it.

**What these numbers don't prove.** The automated layers check that output is *grounded*, not that it's the *right* summary (for example, that it picked the most important figure). That's what the human review layer is for: `eval/latest/review_sheet.csv` lists every figure, risk level and claim with its evidence, for a person to mark correct or incorrect. Human review of this run is in progress, and `score-review` also reports how often the automated checks agreed with the reviewer.

## Run it

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...

python -m osm fetch -n 20          # cache recent reports to data/reports/
python -m osm summarize            # brief the most recent report
python -m osm summarize 2026-DON622
python -m osm eval -n 20           # full eval, writes eval/latest/
python -m osm rescore              # re-run deterministic checks on saved results, no API calls
python -m osm score-review         # score a filled-in review sheet

streamlit run app.py               # viewer: summarize live or browse eval results
```

Model defaults to `claude-sonnet-5-5`. Override with `OSM_MODEL`, and set `OSM_CRITIC_MODEL` to use a different model for the fact-check pass.

Tests run offline against a synthetic report and a fake client: `pytest`.

## Layout

```
osm/fetch.py      WHO API client and HTML cleanup
osm/schema.py     the outbreak signal schema (Pydantic, used as the tool schema)
osm/llm.py        extraction and critic prompts
osm/verify.py     deterministic grounding checks
osm/pipeline.py   extract, check, revise once
osm/evaluate.py   eval runner, metrics, review sheet, report
app.py            Streamlit viewer
```

## Limits

- Summaries cover one report at a time. There's no tracking of an outbreak across successive reports yet.
- English DON reports only.
- Grounding checks catch invented or altered numbers. They can't catch a correct number from the report applied to the wrong place in prose; that falls to the critic and human review.

Built by [Marco Sesay](https://github.com/marcosesay). Source data: [WHO Disease Outbreak News](https://www.who.int/emergencies/disease-outbreak-news).
