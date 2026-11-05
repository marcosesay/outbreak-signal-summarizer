"""Streamlit viewer:  streamlit run app.py"""

import json
from pathlib import Path

import streamlit as st

from osm.fetch import fetch_reports, load_reports, save_reports

DATA, EVAL = Path("data/reports"), Path("eval/latest/results.jsonl")
st.set_page_config(page_title="Outbreak Signal Summarizer", layout="wide")
st.title("Outbreak Signal Summarizer")
st.caption("Claude summaries of WHO Disease Outbreak News, with every figure checked against the source.")


def show(final: dict, url: str):
    sig, checks = final["signal"], final["checks"]
    st.subheader(sig["headline"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Trend", sig["trend"])
    c2.metric("Grounding checks", "pass" if checks["passed"] else f"{len(checks['failures'])} failed")
    bad = [v for v in final["critic"]["verdicts"] if not v["supported"]]
    c3.metric("Critic", "all claims supported" if not bad else f"{len(bad)} unsupported")
    st.write(sig["summary"])
    if sig["figures"]:
        st.markdown("**Figures** (each with its source sentence)")
        for f in sig["figures"]:
            with st.expander(f"{f['label']}: {f['value']}" + (f"  ·  as of {f['as_of']}" if f.get("as_of") else "")):
                st.markdown(f"> {f['quote']}")
    for r in sig["who_risk"]:
        st.markdown(f"**WHO risk ({r['scope']}):** {r['level']}  \n> {r['quote']}")
    if sig["gaps"]:
        st.markdown("**Not stated in the report:** " + "; ".join(sig["gaps"]))
    for x in checks["failures"] + [f"{v['claim']} ({v.get('problem')})" for v in bad]:
        st.warning(x)
    st.markdown(f"[Read the WHO report]({url})")


live, results = st.tabs(["Summarize a report", "Eval results"])

with live:
    if st.button("Fetch latest WHO reports"):
        save_reports(fetch_reports(20), DATA)
    reports = load_reports(DATA)
    if not reports:
        st.info("No reports cached yet. Click 'Fetch latest WHO reports'.")
    else:
        rep = st.selectbox("Report", reports, format_func=lambda r: f"{r.published}  {r.title}")
        if st.button("Summarize", type="primary"):
            from osm.llm import make_client
            from osm.pipeline import summarize

            with st.spinner("Extracting, checking, fact-checking..."):
                res = summarize(make_client(), rep)
            if res.revised:
                st.info("The first draft failed a check and was revised. See the Eval tab for what gets caught.")
            show(res.to_json()["final"], rep.url)

with results:
    if not EVAL.exists():
        st.info("Run `python -m osm eval -n 20` to populate this tab.")
    else:
        rows = [json.loads(line) for line in EVAL.read_text().splitlines()]
        st.json(json.loads((EVAL.parent / "metrics.json").read_text()))
        pick = st.selectbox("Report", rows, format_func=lambda r: f"{r['published']}  {r['title']}")
        show(pick["final"], pick["url"])
