"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteConversation,
  getConversation,
  getHealth,
  getMe,
  getUsage,
  listConversations,
  logout,
  readSession,
  streamChat,
  writeSession,
} from "../lib/api";
import Admin from "../components/Admin";
import AuthGate from "../components/AuthGate";
import { Btn3, Btn12 } from "../components/Buttons";
import Details from "../components/Details";
import Feedback from "../components/Feedback";
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
  const [session, setSession] = useState(undefined);
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);
  const [messages, setMessages] = useState([]);
  const [convos, setConvos] = useState([]);
  const [convoId, setConvoId] = useState(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [theme, setTheme] = useState(null);
  const [menu, setMenu] = useState(false);
  const [view, setView] = useState("chat");
  const [usage, setUsage] = useState(null);

  const bottomRef = useRef(null);
  const inputRef = useRef(null);
  const abortRef = useRef(null);

  useEffect(() => {
    const stored = readSession();
    if (!stored) {
      setSession(null);
      return;
    }
    getMe()
      .then((me) => {
        const fresh = { name: me.name, email: me.email, tenant: me.tenant, admin: me.admin };
        writeSession(fresh);
        setSession(fresh);
      })
      .catch(() => {
        writeSession(null);
        setSession(null);
      });
  }, []);

  const refreshConvos = useCallback(() => {
    listConversations().then(setConvos).catch(() => {});
  }, []);

  useEffect(() => {
    if (!session) return;
    getHealth().then(setHealth).catch((e) => setHealthError(e.message));
    getUsage().then(setUsage).catch(() => {});
    refreshConvos();
  }, [session, refreshConvos]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    let saved = null;
    try {
      saved = localStorage.getItem("pleiades.theme");
    } catch {}
    if (saved === "light" || saved === "dark") setTheme(saved);
    else setTheme(matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
  }, []);

  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggleTheme = () => {
    const next = theme === "light" ? "dark" : "light";
    setTheme(next);
    try {
      localStorage.setItem("pleiades.theme", next);
    } catch {}
  };

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
          conversationId: convoId,
          signal: controller.signal,
          onMeta: (meta) => {
            setConvoId((cur) => cur ?? meta.conversation_id);
            patch({ meta });
          },
          onToken: (text) =>
            setMessages((m) => {
              const next = [...m];
              const last = next[next.length - 1];
              next[next.length - 1] = { ...last, content: last.content + text };
              return next;
            }),
          onDone: (done) => {
            patch({
              totalMs: performance.now() - started,
              id: done.message_id,
              rating: null,
              outcome: done.outcome,
              attempts: done.attempts,
            });
            refreshConvos();
            getUsage().then(setUsage).catch(() => {});
          },
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
    [busy, convoId, refreshConvos]
  );

  const openConvo = async (id) => {
    abortRef.current?.abort();
    setMenu(false);
    setView("chat");
    let rows;
    try {
      rows = await getConversation(id);
    } catch {
      refreshConvos();
      return;
    }
    setConvoId(id);
    setMessages(
      rows.map((m) =>
        m.role === "user"
          ? { role: "user", content: m.content }
          : {
              role: "bot",
              id: m.id,
              rating: m.rating,
              outcome: m.outcome,
              handover: m.handover,
              content: m.content,
              meta: m.sources
                ? { sources: m.sources, prompt_tokens: m.prompt_tokens, expansions: [] }
                : null,
              totalMs: m.latency_ms,
            }
      )
    );
  };

  const removeConvo = async (id) => {
    if (!window.confirm("Delete this conversation?")) return;
    await deleteConversation(id).catch(() => {});
    if (id === convoId) {
      setConvoId(null);
      setMessages([]);
    }
    refreshConvos();
  };

  const stop = () => {
    abortRef.current?.abort();
    setMessages((m) => {
      const next = [...m];
      const last = next[next.length - 1];
      if (last?.role === "bot" && !last.content)
        next[next.length - 1] = { ...last, error: "Stopped before the answer was ready." };
      return next;
    });
  };

  const exportConvo = () => {
    const title =
      convos.find((c) => c.id === convoId)?.title ||
      messages.find((m) => m.role === "user")?.content.slice(0, 80) ||
      "Conversation";
    const body = messages
      .filter((m) => m.content)
      .map((m) => {
        if (m.role === "user") return `**You:** ${m.content}`;
        const cited = (m.meta?.sources || []).map((s) => `- ${s.label}${s.section ? ` > ${s.section}` : ""}`);
        return `**Pleiades:** ${m.content}` + (cited.length ? `\n\nSources:\n${cited.join("\n")}` : "");
      })
      .join("\n\n");
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([`# ${title}\n\n${body}\n`], { type: "text/markdown" }));
    link.download = `pleiades-conversation-${new Date().toISOString().slice(0, 10)}.md`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const newConvo = () => {
    abortRef.current?.abort();
    setMenu(false);
    setView("chat");
    setConvoId(null);
    setMessages([]);
  };

  const signOut = () => {
    logout().catch(() => {});
    writeSession(null);
    setSession(null);
    setMessages([]);
    setConvos([]);
    setConvoId(null);
  };

  if (session === undefined) return null;
  if (!session) return <AuthGate onAuthenticated={setSession} />;

  return (
    <div className={`shell${menu ? " shell--menu" : ""}`}>
      <aside className="glass sidebar" id="sidebar">
        <div className="brand">
          <div className="brand__mark">P</div>
          <div>
            <h1>Pleiades</h1>
            <p>Nimbus Networks workspace</p>
          </div>
          <button type="button" className="tab menu-btn" onClick={() => setMenu(false)}>
            Close
          </button>
        </div>

        <section>
          <h2 className="side-h">Conversations</h2>
          <Btn3 variant="quiet" size="sm" onClick={newConvo} style={{ width: "100%", marginBottom: 9 }}>
            New conversation
          </Btn3>
          <div className="convos">
            {convos.length === 0 && <p className="stage__detail">No history yet</p>}
            {convos.map((c) => (
              <div className="convo" key={c.id}>
                <button
                  className={`convo__open ${c.id === convoId ? "on" : ""}`}
                  onClick={() => openConvo(c.id)}
                  title={c.title}
                >
                  {c.title}
                </button>
                <button
                  className="convo__del"
                  onClick={() => removeConvo(c.id)}
                  aria-label={`Delete ${c.title}`}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="side-h">Pipeline</h2>
          {healthError && <div className="alert">API unreachable — {healthError}</div>}
          {health && !health.has_llm && (
            <div className="alert">
              No language model is answering, so replies are quoted straight from the documents.
            </div>
          )}
          {health?.database === "fallback" && (
            <div className="alert">
              Demo mode: the main database is unreachable, so accounts reset when the server restarts.
            </div>
          )}
          {health && (
            <dl className="spec">
              <dt>Generation</dt>
              <dd>{health.backend}</dd>
              <dt>Retrieval</dt>
              <dd>ChromaDB · {health.embedder}</dd>
              <dt>Index</dt>
              <dd>
                {health.chunks} chunks · top-{health.top_k} · cosine
              </dd>
            </dl>
          )}
        </section>

        <div className="sidebar__foot">
          <div className="who">
            <div className="who__avatar">{(session.name || "?")[0].toUpperCase()}</div>
            <div style={{ minWidth: 0 }}>
              <div className="who__name">{session.name}</div>
              <div className="who__email">{session.email}</div>
            </div>
          </div>
          {session.admin && (
            <Btn3
              variant="quiet"
              size="sm"
              onClick={() => {
                setView(view === "admin" ? "chat" : "admin");
                setMenu(false);
              }}
            >
              {view === "admin" ? "Back to chat" : "Admin console"}
            </Btn3>
          )}
          <Btn3
            variant="quiet"
            size="sm"
            onClick={toggleTheme}
          >
            {theme === "light" ? "Dark mode" : "Light mode"}
          </Btn3>
          <Btn3 size="sm" onClick={signOut}>
            Sign out
          </Btn3>
        </div>
      </aside>

      <main className="glass main">
        <div className="topbar">
          <button type="button" className="tab menu-btn" onClick={() => setMenu(true)}
            aria-controls="sidebar" aria-expanded={menu}>
            Menu
          </button>
          <div>
            <h2>{view === "admin" ? "Admin console" : "Support conversation"}</h2>
            <p>
              {view === "admin"
                ? "Your organisation's last 7 days, and what needs a person"
                : `Grounded in ${health?.documents?.length ?? "the"} internal documents, with citations`}
            </p>
          </div>
          {view === "chat" && messages.some((m) => m.id) && (
            <button type="button" className="tab tab--end" onClick={exportConvo}>
              Download
            </button>
          )}
          <span className="live">
            <span className={`live__dot ${healthError ? "live__dot--off" : ""}`} />
            {healthError ? "offline" : busy ? "generating" : "ready"}
          </span>
        </div>

        {view === "admin" ? (
          <div className="thread">
            <Admin />
          </div>
        ) : (
        <>
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
                <div className="turn__avatar">P</div>
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
                  {m.meta && <Details meta={m.meta} totalMs={m.totalMs} question={messages[i - 1]?.content} />}
                  {m.outcome === "escalated" && <div className="handoff">Passed to the support team</div>}
                  {m.outcome === "answered" && (
                    <div className="checked">
                      Every figure checked against the sources{m.attempts > 1 ? " after one redraft" : ""}
                    </div>
                  )}
                  {m.id && (
                    <Feedback
                      key={m.id}
                      id={m.id}
                      rating={m.rating}
                      text={m.content}
                      handover={m.handover}
                      escalated={m.outcome === "escalated"}
                    />
                  )}
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
          {busy ? (
            <Btn3 onClick={stop}>Stop</Btn3>
          ) : (
            <Btn3 type="submit" disabled={!input.trim()}>
              Send
            </Btn3>
          )}
        </form>
        {usage?.limit != null && (
          <p className="quota">
            {Math.max(0, usage.limit - usage.used)} of {usage.limit} questions left in the last 24 hours
          </p>
        )}
        </>
        )}
      </main>
    </div>
  );
}
