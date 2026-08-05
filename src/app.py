from __future__ import annotations

import sys
import time
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import config
from src.rag import SYSTEM_PROMPT, SupportAssistant, est_tokens, format_context, format_history

st.set_page_config(page_title="Nimbus Support Assistant", page_icon="💬", layout="wide")

SAMPLES = [
    ("Router shows a solid orange light", "My internet light is solid orange and I have no connection."),
    ("First bill looks too high", "Why is my first bill higher than my plan price?"),
    ("Router died 4 days after delivery", "My router died 4 days after delivery. Do I need to do triage first?"),
    ("Three days of downtime", "I was down for about 3 days last month. Do I get anything back?"),
    ("Compare Plus and Max", "What's the difference between Nimbus Plus and Nimbus Max?"),
    ("Out of scope question", "Who won the world cup in 2018?"),
]

st.markdown("""
<style>
    .block-container { padding-top: 2.5rem; max-width: 1100px; }
    div[data-testid="stMetricValue"] { font-size: 1.25rem; }
    .src-score { font-family: ui-monospace, monospace; font-size: .78rem;
                 background: rgba(128,128,128,.14); padding: .1rem .4rem;
                 border-radius: .3rem; }
</style>
""", unsafe_allow_html=True)


@st.cache_resource(show_spinner="Loading knowledge base…")
def load_bot() -> SupportAssistant:
    return SupportAssistant()


if not config.CHROMA_DIR.exists():
    st.error("No vector index found. Run `python -m src.ingest` first.")
    st.stop()

bot = load_bot()
st.session_state.setdefault("messages", [])


def render_sources(sources: list[dict], meta: dict) -> None:
    label = f"{len(sources)} sources · {meta['latency']:.1f}s · ~{meta['tokens']} prompt tokens"
    with st.expander(label):
        if meta.get("condensed"):
            st.caption(f"Follow-up rewritten to: `{meta['query']}`")
        if meta.get("expansions"):
            st.caption("Low retrieval confidence, so the query was expanded to:")
            for e in meta["expansions"]:
                st.caption(f"`{e}`")
        for s in sources:
            loc = f" › {s['section']}" if s["section"] else ""
            tag = f"{s['score']:.2f}" if s["score"] else "kw"
            st.markdown(
                f"<span class='src-score'>{tag}</span> "
                f"**{s['label']}**{loc}", unsafe_allow_html=True)
            st.caption(s["excerpt"] + "…")


with st.sidebar:
    st.subheader("Pipeline")
    st.caption("Generation")
    st.code(bot.backend_name, language=None)
    st.caption("Retrieval")
    st.code(f"ChromaDB · all-MiniLM-L6-v2\ncosine · top-{bot.top_k}", language=None)

    if bot.backend_name.startswith("Extractive"):
        st.warning("No LLM connected. Set a key in `.env` or run `ollama serve`, then restart.")

    st.divider()
    st.subheader("Knowledge base")
    for lbl in config.SOURCE_LABELS.values():
        st.caption(f"• {lbl}")

    st.divider()
    if st.button("Clear conversation", use_container_width=True):
        bot.reset()
        st.session_state.messages = []
        st.rerun()

st.title("Nimbus Support Assistant")
st.caption("Retrieval-Augmented Generation over enterprise knowledge bases")

if not st.session_state.messages:
    cols = st.columns(3)
    for i, (short, full) in enumerate(SAMPLES):
        if cols[i % 3].button(short, key=f"s{i}", use_container_width=True):
            st.session_state.pending = full
            st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources") is not None:
            render_sources(msg["sources"], msg["meta"])

prompt = st.chat_input("Ask about billing, hardware, plans, or troubleshooting…")
if "pending" in st.session_state:
    prompt = st.session_state.pop("pending")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        start = time.perf_counter()
        with st.spinner("Searching the knowledge base…"):
            r = bot.retrieve(prompt)
        answer = st.write_stream(bot.stream(prompt, r))
        latency = time.perf_counter() - start

        bot.remember(prompt, answer)
        sources = bot.sources(r)
        meta = {
            "latency": latency,
            "tokens": est_tokens(SYSTEM_PROMPT + format_context(r.docs)
                                 + format_history(bot.history[:-1]) + prompt),
            "query": r.query,
            "condensed": r.condensed,
            "expansions": r.expansions,
        }
        render_sources(sources, meta)

    st.session_state.messages.append(
        {"role": "assistant", "content": answer, "sources": sources, "meta": meta}
    )
