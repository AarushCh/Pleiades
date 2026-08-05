import { useCallback, useEffect, useRef, useState } from "react";
import { getHealth, resetSession, streamChat } from "./api";
import { Details, Markdown } from "./components";

const SAMPLES = [
  {
    title: "Solid orange light",
    text: "My internet light is solid orange and I have no connection. What do I do?",
    note: "Pulls the manual and a matching resolved ticket",
  },
  {
    title: "Router died in 4 days",
    text: "My router died 4 days after it arrived. Do I have to do the triage steps first?",
    note: "DOA clause overrides the normal triage rule",
  },
  {
    title: "Three days of downtime",
    text: "I was down for about 3 days last month. Do I get anything back?",
    note: "Needs the billing FAQ and the SLA table together",
  },
  {
    title: "Compare plans",
    text: "What is the difference between the Plus and Max plans?",
    note: "Structured lookup from the catalog",
  },
  {
    title: "First bill too high",
    text: "Why is my first bill higher than my plan price?",
    note: "The most common real billing complaint",
  },
  {
    title: "Out of scope",
    text: "Who won the world cup in 2018?",
    note: "Should refuse rather than guess",
  },
];

export default function App() {
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState(null);

  const bottomRef = useRef(null);
  const abortRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    getHealth().then(setHealth).catch((e) => setHealthError(e.message));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(
    async (question) => {
      const q = question.trim();
      if (!q || busy) return;

      setInput("");
      setBusy(true);
      setMessages((m) => [...m, { role: "user", content: q }, { role: "assistant", content: "" }]);

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
            if (!sessionId) setSessionId(meta.session_id);
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
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">N</div>
          <div>
            <h1>Nimbus Support</h1>
            <p>Enterprise RAG assistant</p>
          </div>
        </div>

        <section>
          <h2>Pipeline</h2>
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
          <h2>Knowledge base</h2>
          <ul className="kb">
            {health?.documents.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </section>

        <div className="sidebar-foot">
          <button className="ghost" onClick={clear} disabled={!messages.length}>
            Clear conversation
          </button>
        </div>
      </aside>

      <main className="main">
        <div className="thread">
          {messages.length === 0 && (
            <div className="welcome">
              <h2>Ask about billing, hardware, plans or troubleshooting</h2>
              <p>
                Answers are grounded in five internal documents and cite the section they came
                from. Try one of these:
              </p>
              <div className="samples">
                {SAMPLES.map((s) => (
                  <button key={s.title} onClick={() => send(s.text)} disabled={busy}>
                    <strong>{s.title}</strong>
                    <span>{s.note}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((m, i) =>
            m.role === "user" ? (
              <div className="turn user" key={i}>
                <div className="bubble">{m.content}</div>
              </div>
            ) : (
              <div className="turn assistant" key={i}>
                <div className="avatar">N</div>
                <div className="body">
                  {m.content ? (
                    <Markdown text={m.content} />
                  ) : m.error ? null : (
                    <div className="thinking">
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
          />
          <button type="submit" disabled={busy || !input.trim()}>
            {busy ? "…" : "Send"}
          </button>
        </form>
      </main>
    </div>
  );
}
