// Talks to the FastAPI backend's AG-UI endpoint. POST-based SSE has no
// native browser API (EventSource is GET-only), so we read the
// fetch() response body as a stream and split it on the SSE "\n\n"
// event delimiter ourselves.

const API_BASE = "http://localhost:8000";

export async function login(username, password) {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || "Login failed");
  }
  return res.json();
}

/**
 * Streams one /agui turn. Calls onEvent(parsedJson) for every AG-UI
 * event as it arrives. Resolves when the stream ends.
 */
export async function streamAgui(accessToken, payload, onEvent) {
  const res = await fetch(`${API_BASE}/agui`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`/agui failed: ${text}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sepIndex;
    while ((sepIndex = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);
      const line = rawEvent.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const jsonText = line.slice("data:".length).trim();
      if (!jsonText) continue;
      try {
        onEvent(JSON.parse(jsonText));
      } catch (e) {
        console.error("Failed to parse AG-UI event:", jsonText, e);
      }
    }
  }
}

export function sendMessage(accessToken, { threadId, runId, text }, onEvent) {
  return streamAgui(
    accessToken,
    { thread_id: threadId, run_id: runId, messages: [{ role: "user", content: text }] },
    onEvent
  );
}

export function resumeInterrupt(accessToken, { threadId, runId, interruptId, approved }, onEvent) {
  return streamAgui(
    accessToken,
    {
      thread_id: threadId,
      run_id: runId,
      resume: [{ interrupt_id: interruptId, status: "resolved", payload: { approved } }],
    },
    onEvent
  );
}
