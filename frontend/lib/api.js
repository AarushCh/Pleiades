const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";
const KEY = "palades.session";

export function readSession() {
  if (typeof window === "undefined") return null;
  try {
    return JSON.parse(localStorage.getItem(KEY) || "null");
  } catch {
    return null;
  }
}

export function writeSession(session) {
  if (session) localStorage.setItem(KEY, JSON.stringify(session));
  else localStorage.removeItem(KEY);
}

function authHeaders() {
  const s = readSession();
  return s?.token ? { Authorization: `Bearer ${s.token}` } : {};
}

async function jsonFetch(path, options = {}) {
  const res = await fetch(BASE + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(),
      ...(options.headers || {}),
    },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.detail || `Request failed (${res.status})`);
  return body;
}

export const signup = (payload) =>
  jsonFetch("/api/auth/signup", { method: "POST", body: JSON.stringify(payload) });

export const login = (payload) =>
  jsonFetch("/api/auth/login", { method: "POST", body: JSON.stringify(payload) });

export const getMe = () => jsonFetch("/api/auth/me");
export const getHealth = () => jsonFetch("/api/health");
export const listConversations = () => jsonFetch("/api/conversations");
export const getConversation = (id) => jsonFetch(`/api/conversations/${id}`);
export const deleteConversation = (id) =>
  jsonFetch(`/api/conversations/${id}`, { method: "DELETE" });

export async function streamChat({
  question,
  conversationId,
  signal,
  onMeta,
  onToken,
  onDone,
  onError,
}) {
  const res = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ question, conversation_id: conversationId }),
    signal,
  });

  if (!res.ok || !res.body) {
    onError(res.status === 401 ? "Session expired, sign in again" : `Request failed (${res.status})`);
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      let event = "message";
      const data = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data.push(line.slice(5).trim());
      }
      if (!data.length) continue;

      let payload;
      try {
        payload = JSON.parse(data.join("\n"));
      } catch {
        continue;
      }

      if (event === "meta") onMeta(payload);
      else if (event === "token") onToken(payload.text);
      else if (event === "done") onDone(payload);
      else if (event === "error") onError(payload.message);
    }
  }
}
