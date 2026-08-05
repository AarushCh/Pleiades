import { useState } from "react";

export function ScoreBar({ score }) {
  if (score == null) return <span className="pill pill-kw">kw</span>;
  const pct = Math.min(100, Math.round(score * 140));
  return (
    <span className="score">
      <span className="score-track">
        <span className="score-fill" style={{ width: `${pct}%` }} />
      </span>
      <span className="score-num">{score.toFixed(2)}</span>
    </span>
  );
}

export function SourceCard({ source }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={`source ${open ? "open" : ""}`}>
      <button className="source-head" onClick={() => setOpen(!open)}>
        <ScoreBar score={source.score} />
        <span className="source-label">{source.label}</span>
        {source.section && <span className="source-section">{source.section}</span>}
        <span className="chev">{open ? "−" : "+"}</span>
      </button>
      {open && <pre className="source-excerpt">{source.excerpt}</pre>}
    </div>
  );
}

export function Trace({ meta }) {
  if (!meta) return null;
  const stages = [
    { name: "Condense", active: meta.condensed, detail: meta.condensed ? meta.query : "skipped" },
    {
      name: "Expand",
      active: meta.expansions?.length > 0,
      detail: meta.expansions?.length ? `${meta.expansions.length} queries` : "skipped",
    },
    { name: "Retrieve", active: true, detail: `${meta.sources?.length ?? 0} chunks` },
    { name: "Generate", active: true, detail: `~${meta.prompt_tokens} tokens` },
  ];

  return (
    <div className="trace">
      {stages.map((s) => (
        <div key={s.name} className={`stage ${s.active ? "on" : "off"}`}>
          <span className="stage-name">{s.name}</span>
          <span className="stage-detail">{s.detail}</span>
        </div>
      ))}
    </div>
  );
}

export function Details({ meta, totalMs }) {
  const [tab, setTab] = useState("sources");
  if (!meta) return null;

  return (
    <div className="details">
      <div className="tabs">
        <button className={tab === "sources" ? "on" : ""} onClick={() => setTab("sources")}>
          Sources ({meta.sources?.length ?? 0})
        </button>
        <button className={tab === "trace" ? "on" : ""} onClick={() => setTab("trace")}>
          Pipeline
        </button>
        <span className="timing">
          {meta.retrieval_ms != null && `retrieval ${Math.round(meta.retrieval_ms)}ms`}
          {totalMs != null && ` · total ${(totalMs / 1000).toFixed(1)}s`}
        </span>
      </div>

      {tab === "sources" && (
        <div className="source-list">
          {meta.sources?.map((s, i) => (
            <SourceCard key={`${s.label}-${s.section}-${i}`} source={s} />
          ))}
        </div>
      )}

      {tab === "trace" && (
        <div>
          <Trace meta={meta} />
          {meta.condensed && (
            <p className="note">
              Follow-up rewritten to <code>{meta.query}</code>. The original wording is retrieved
              alongside it so no detail is lost.
            </p>
          )}
          {meta.expansions?.length > 0 && (
            <div className="note">
              <p>Query rewritten into policy vocabulary:</p>
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

export function Markdown({ text }) {
  const blocks = text.split(/\n{2,}/);
  return (
    <>
      {blocks.map((block, i) => {
        const lines = block.split("\n");

        if (lines.every((l) => /^\s*\|/.test(l)) && lines.length > 1) {
          const rows = lines
            .filter((l) => !/^\s*\|[\s|:-]+\|\s*$/.test(l))
            .map((l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
          const [head, ...body] = rows;
          return (
            <table className="md-table" key={i}>
              <thead>
                <tr>{head.map((c, j) => <th key={j}>{inline(c)}</th>)}</tr>
              </thead>
              <tbody>
                {body.map((r, j) => (
                  <tr key={j}>{r.map((c, k) => <td key={k}>{inline(c)}</td>)}</tr>
                ))}
              </tbody>
            </table>
          );
        }

        if (lines.every((l) => /^\s*(\d+\.|[-*])\s+/.test(l))) {
          const ordered = /^\s*\d+\./.test(lines[0]);
          const items = lines.map((l) => l.replace(/^\s*(\d+\.|[-*])\s+/, ""));
          const List = ordered ? "ol" : "ul";
          return (
            <List key={i}>
              {items.map((it, j) => (
                <li key={j}>{inline(it)}</li>
              ))}
            </List>
          );
        }

        return <p key={i}>{inline(block)}</p>;
      })}
    </>
  );
}

function inline(text) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return parts.map((p, i) => {
    if (p.startsWith("**") && p.endsWith("**")) return <strong key={i}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("`") && p.endsWith("`")) return <code key={i}>{p.slice(1, -1)}</code>;
    return <span key={i}>{p}</span>;
  });
}
