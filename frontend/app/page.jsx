"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getHealth, resetSession, streamChat } from "../lib/api";
import { Btn3, Btn12 } from "../components/Buttons";
import Details from "../components/Details";
import Markdown from "../components/Markdown";

const SAMPLES = [
  {
    title: "Solid orange light",
    note: "Pulls the manual and a matching resolved ticket",
    text: "My internet light is solid orange and I have no connection. What do I do?",
  },
  {
    title: "Router died in 4 days",
    note: "DOA clause overrides the normal triage rule",
    text: "My router died 4 days after it arrived. Do I have to do the triage steps first?",
  },
  {
    title: "Three days of downtime",
    note: "Needs the billing FAQ and the SLA table together",
    text: "I was down for about 3 days last month. Do I get anything back?",
  },
  {
    title: "Compare plans",
    note: "Structured lookup from the catalog",
    text: "What is the difference between the Plus and Max plans?",
  },
  {
    title: "First bill too high",
    note: "The most common real billing complaint",
    text: "Why is my first bill higher than my plan price?",
  },
  {
    title: "Out of scope",
    note: "Should refuse rather than guess",
    text: "Who won the world cup in 2018?",
  },
];

export default function Page() {
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState(null);
  const [theme, setTheme] = useState("dark");

  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => {
    getHealth().then(setHealth).catch((e) => setHealthError(e.message));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const send = useCallback(
    async (question) => {
      const q = question.trim();
      if (!q || busy) return;

      setInput("");
      setBusy(true);
      setMessages((m) => [...m, { role: "user", content: q }, { role: "bot", content: "" }]);

      const controller = new AbortController();
      abortRef.current = controller;
      const started = performance.now();

      const patch = (fields) =>
        setMessages((m) => {
          const next = [...m];
          next[next.length - 1] = { ...next[next.length - 1], ...fields };
          return next;
        });

      try {
        await streamChat({
          question: q,
          sessionId,
          signal: controller.signal,
          onMeta: (meta) => {
            setSessionId((cur) => cur ?? meta.session_id);
            patch({ meta });
          },
          onToken: (text) =>
            setMessages((m) => {
              const next = [...m];
              const last = next[next.length - 1];
              next[next.length - 1] = { ...last, content: last.content + text };
              return next;
            }),
          onDone: () => patch({ totalMs: performance.now() - started }),
          onError: (message) => patch({ error: message }),
        });
      } catch (e) {
        if (e.name !== "AbortError") patch({ error: e.message });
      } finally {
        setBusy(false);
        abortRef.current = null;
        inputRef.current?.focus();
      }
    },
    [busy, sessionId]
  );

  const clear = async () => {
    abortRef.current?.abort();
    await resetSession(sessionId);
    setMessages([]);
  };

  return (
    <div className="shell">
      <aside className="glass sidebar">
        <div className="brand">
          <div className="brand__mark">N</div>
          <div>
            <h1>Nimbus Support</h1>
            <p>Enterprise RAG assistant</p>
          </div>
        </div>

        <section>
          <h2 className="side-h">Pipeline</h2>
          {healthError && <div className="alert">API unreachable — {healthError}</div>}
          {health && (
            <dl className="spec">
              <dt>Generation</dt>
              <dd>{health.backend}</dd>
              <dt>Retrieval</dt>
              <dd>ChromaDB · all-MiniLM-L6-v2</dd>
              <dt>Index</dt>
              <dd>
                {health.chunks} chunks · top-{health.top_k} · cosine
              </dd>
            </dl>
          )}
          {health && !health.has_llm && (
            <div className="alert">
              No language model connected. Retrieval works; answers are extracted verbatim.
            </div>
          )}
        </section>

        <section>
          <h2 className="side-h">Knowledge base</h2>
          <ul className="kb">
            {health?.documents.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </section>

        <div className="sidebar__foot">
          <Btn3
            variant="quiet"
            size="sm"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          >
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </Btn3>
          <Btn3 size="sm" onClick={clear} disabled={!messages.length}>
            Clear conversation
          </Btn3>
        </div>
      </aside>

      <main className="glass main">
        <div className="topbar">
          <div>
            <h2>Support conversation</h2>
            <p>Grounded in five internal documents, with citations</p>
          </div>
          <span className="live">
            <span className={`live__dot ${healthError ? "live__dot--off" : ""}`} />
            {healthError ? "offline" : busy ? "generating" : "ready"}
          </span>
        </div>

        <div className="thread">
          {messages.length === 0 && (
            <div className="welcome">
              <span className="welcome__kicker">Retrieval-Augmented Generation</span>
              <h2>Ask about billing, hardware, plans or troubleshooting</h2>
              <p>
                Every answer is grounded in the knowledge base and cites the document and section
                it came from. Pick a question to see the retrieval pipeline work.
              </p>
              <div className="samples">
                {SAMPLES.map((s) => (
                  <Btn12
                    key={s.title}
                    title={s.title}
                    note={s.note}
                    disabled={busy}
                    onClick={() => send(s.text)}
                  />
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) =>
            m.role === "user" ? (
              <div className="turn--user" key={i}>
                <div className="bubble">{m.content}</div>
              </div>
            ) : (
              <div className="turn--bot" key={i}>
                <div className="turn__avatar">N</div>
                <div className="turn__body">
                  {m.content ? (
                    <Markdown text={m.content} />
                  ) : m.error ? null : (
                    <div className="dots">
                      <span />
                      <span />
                      <span />
                    </div>
                  )}
                  {m.error && <div className="alert">{m.error}</div>}
                  {m.meta && <Details meta={m.meta} totalMs={m.totalMs} />}
                </div>
              </div>
            )
          )}
          <div ref={bottomRef} />
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            send(input);
          }}
        >
          <input
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about billing, hardware, plans, or troubleshooting…"
            disabled={busy}
            aria-label="Your question"
          />
          <Btn3 type="submit" disabled={busy || !input.trim()}>
            {busy ? "Sending" : "Send"}
          </Btn3>
        </form>
      </main>
    </div>
  );
}
