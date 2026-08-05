const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export async function getHealth() {
  const res = await fetch(`${BASE}/api/health`);
  if (!res.ok) throw new Error(`Health check failed (${res.status})`);
  return res.json();
}

export async function resetSession(sessionId) {
  if (!sessionId) return;
  await fetch(`${BASE}/api/session/${sessionId}/reset`, { method: "POST" });
}

export async function streamChat({
  question,
  sessionId,
  signal,
  onMeta,
  onToken,
  onDone,
  onError,
}) {
  const res = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, session_id: sessionId }),
    signal,
  });

  if (!res.ok || !res.body) {
    onError(`Request failed (${res.status})`);
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
