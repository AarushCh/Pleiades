"use client";

import { useEffect, useState } from "react";
import { Btn3 } from "./Buttons";
import { getComplaints, getHandovers, getJoinCode, getOverview, reseed, setInviteOnly } from "../lib/api";

function download(rows) {
  const cases = rows.map((r) => ({
    id: `complaint-${r.id}`,
    question: r.question,
    must: [],
    complaint: r.reason,
    answer_given: r.answer,
  }));
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([JSON.stringify(cases, null, 2)], { type: "application/json" }));
  link.download = `pleiades-complaints-${new Date().toISOString().slice(0, 10)}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

function Queue({ rows, empty }) {
  if (!rows) return <p className="queue__empty">Loading…</p>;
  if (!rows.length) return <p className="queue__empty">{empty}</p>;
  return (
    <ul className="queue">
      {rows.map((r) => (
        <li key={r.id} className="queue__item">
          <div className="queue__meta">
            {r.email} · {new Date(r.created_at).toLocaleString()}
            {r.asked_for_person && <span className="queue__tag">asked for a person</span>}
          </div>
          <div className="queue__q">{r.question || "Question not found"}</div>
          {r.reason && <div className="queue__why">“{r.reason}”</div>}
          <details>
            <summary>Answer given</summary>
            <p>{r.answer}</p>
          </details>
        </li>
      ))}
    </ul>
  );
}

export default function Admin() {
  const [stats, setStats] = useState(null);
  const [complaints, setComplaints] = useState(null);
  const [handovers, setHandovers] = useState(null);
  const [code, setCode] = useState(undefined);
  const [tab, setTab] = useState("handovers");
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const fail = (e) => setNotice({ text: e.message, bad: true });
    getOverview().then(setStats).catch(fail);
    getComplaints().then(setComplaints).catch(fail);
    getHandovers().then(setHandovers).catch(fail);
    getJoinCode()
      .then((r) => setCode(r.join_code))
      .catch(fail);
  }, []);

  const act = (work, done) => {
    setBusy(true);
    setNotice(null);
    work()
      .then(done)
      .catch((e) => setNotice({ text: e.message, bad: true }))
      .finally(() => setBusy(false));
  };

  const share = stats?.questions ? Math.round((100 * stats.answered) / stats.questions) : null;
  const cards = stats
    ? [
        ["Questions", stats.questions, `last ${stats.days} days`],
        ["Answered", stats.answered, share == null ? "nothing asked yet" : `${share}% without a person`],
        ["Handed over", stats.handed_over, "need a person"],
        ["Helpful", stats.helpful, `${stats.not_helpful} not helpful`],
        ["People", stats.people, "asked something"],
      ]
    : [];

  return (
    <div className="admin">
      {notice && <div className={notice.bad ? "alert" : "notice"}>{notice.text}</div>}
      <div className="cards">
        {cards.map(([label, value, sub]) => (
          <div className="glass card" key={label}>
            <span className="card__label">{label}</span>
            <span className="card__value">{value}</span>
            <span className="card__sub">{sub}</span>
          </div>
        ))}
      </div>

      <section className="glass panel">
        <div className="details__tabs">
          <button className={`tab ${tab === "handovers" ? "on" : ""}`} onClick={() => setTab("handovers")}>
            Handed over{handovers ? ` (${handovers.length})` : ""}
          </button>
          <button className={`tab ${tab === "complaints" ? "on" : ""}`} onClick={() => setTab("complaints")}>
            Not helpful{complaints ? ` (${complaints.length})` : ""}
          </button>
          {tab === "complaints" && complaints?.length > 0 && (
            <button className="tab tab--end" onClick={() => download(complaints)}>
              Download as benchmark cases
            </button>
          )}
        </div>
        {tab === "handovers" ? (
          <Queue rows={handovers} empty="Nothing handed over: every question was answered from the documents." />
        ) : (
          <Queue rows={complaints} empty="No answer has been marked not helpful." />
        )}
      </section>

      <section className="glass panel panel--row">
        <div>
          <h3>Sign-up</h3>
          <p>
            {code === undefined ? (
              "Checking…"
            ) : code ? (
              <>
                Invite-only. New accounts need the code <code>{code}</code>
              </>
            ) : (
              "Open: anyone can create an account."
            )}
          </p>
        </div>
        <div className="panel__actions">
          <Btn3
            size="sm"
            variant="quiet"
            disabled={busy || code === undefined}
            onClick={() => act(() => setInviteOnly(true), (r) => setCode(r.join_code))}
          >
            {code ? "New code" : "Make invite-only"}
          </Btn3>
          {code && (
            <Btn3
              size="sm"
              variant="quiet"
              disabled={busy}
              onClick={() => act(() => setInviteOnly(false), () => setCode(null))}
            >
              Open sign-up
            </Btn3>
          )}
        </div>
      </section>

      <section className="glass panel panel--row">
        <div>
          <h3>Knowledge base</h3>
          <p>Re-reads the documents and rebuilds the search index without a restart.</p>
        </div>
        <div className="panel__actions">
          <Btn3
            size="sm"
            variant="quiet"
            disabled={busy}
            onClick={() =>
              act(reseed, (r) =>
                setNotice({ text: `Index rebuilt: ${r.chunks} chunks, ${r.synced} documents changed.` })
              )
            }
          >
            {busy ? "Working" : "Rebuild index"}
          </Btn3>
        </div>
      </section>
    </div>
  );
}
