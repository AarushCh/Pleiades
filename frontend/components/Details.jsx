"use client";

import { useState } from "react";

const COMMON = new Set(
  "what when where which does have with that this your from there about would could should will into they them then than been were their after before also just only much many more most some such very like want need still".split(
    " "
  )
);

function keywords(text) {
  return [...new Set((text || "").toLowerCase().match(/[a-z0-9]{4,}/g) || [])].filter((w) => !COMMON.has(w));
}

function Highlight({ text, words }) {
  if (!words.length) return text;
  const parts = text.split(new RegExp(`(${words.join("|")})`, "gi"));
  return parts.map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part));
}

function Score({ score }) {
  if (score == null) return <span className="pill-kw">kw</span>;
  return (
    <span className="score">
      <span className="score__track">
        <span className="score__fill" style={{ width: `${Math.min(100, score * 140)}%` }} />
      </span>
      <span className="score__num">{score.toFixed(2)}</span>
    </span>
  );
}

function Source({ source, words }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button className="src__head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Score score={source.score} />
        <span className="src__label">{source.label}</span>
        {source.section && <span className="src__section">{source.section}</span>}
        <span className="src__chev" aria-hidden="true">
          {open ? "−" : "+"}
        </span>
      </button>
      {open && (
        <pre className="src__excerpt">
          <Highlight text={source.excerpt} words={words} />
        </pre>
      )}
    </div>
  );
}

export default function Details({ meta, totalMs, question }) {
  const [tab, setTab] = useState("sources");
  if (!meta) return null;

  const stages = [
    {
      name: "Condense",
      on: meta.condensed,
      detail: meta.condensed ? meta.query : "not a follow-up",
    },
    {
      name: "Expand",
      on: meta.expansions?.length > 0,
      detail: meta.expansions?.length ? `${meta.expansions.length} queries` : "skipped",
    },
    { name: "Retrieve", on: true, detail: `${meta.sources?.length ?? 0} chunks` },
    { name: "Generate", on: true, detail: `~${meta.prompt_tokens} tokens` },
  ];

  return (
    <div className="glass details">
      <div className="details__tabs">
        <button className={`tab ${tab === "sources" ? "on" : ""}`} onClick={() => setTab("sources")}>
          Sources ({meta.sources?.length ?? 0})
        </button>
        <button className={`tab ${tab === "trace" ? "on" : ""}`} onClick={() => setTab("trace")}>
          Pipeline
        </button>
        <span className="details__timing">
          {meta.retrieval_ms != null && `retrieval ${Math.round(meta.retrieval_ms)}ms`}
          {totalMs != null && ` · total ${(totalMs / 1000).toFixed(1)}s`}
        </span>
      </div>

      {tab === "sources" ? (
        <div className="srcs">
          {meta.sources?.map((s, i) => (
            <Source key={`${s.label}-${s.section}-${i}`} source={s} words={keywords(meta.query || question)} />
          ))}
        </div>
      ) : (
        <div>
          <div className="trace">
            {stages.map((s) => (
              <div key={s.name} className={`stage ${s.on ? "on" : "off"}`}>
                <span className="stage__name">{s.name}</span>
                <span className="stage__detail">{s.detail}</span>
              </div>
            ))}
          </div>
          {meta.condensed && (
            <p className="note">
              Follow-up rewritten to <code>{meta.query}</code>. The original wording is retrieved
              alongside it so no detail is lost.
            </p>
          )}
          {meta.expansions?.length > 0 && (
            <div className="note">
              Rewritten into the knowledge base&apos;s own vocabulary:
              <ul>
                {meta.expansions.map((e, i) => (
                  <li key={i}>
                    <code>{e}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
