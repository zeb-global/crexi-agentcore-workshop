// Talks to the FastAPI backend's AG-UI endpoint. POST-based SSE has no
// native browser API (EventSource is GET-only), so we read the
// fetch() response body as a stream and split it on the SSE "\n\n"
// event delimiter ourselves.

// Overridable via a .env file read by Vite (VITE_-prefixed vars are
// inlined at build time) -- defaults to the Makefile's own local dev
// port so nothing breaks for the common case, but is not hardcoded for
// anyone running the backend on a different host/port.
const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

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
 * event as it arrives. Resolves when the stream ends. Pass an
 * AbortSignal via opts.signal to support a real Stop button --
 * aborting here only stops the CLIENT reading the stream; call
 * stopRun() too for a genuine server-side halt of the harness run.
 */
export async function streamAgui(accessToken, payload, onEvent, opts = {}) {
  const res = await fetch(`${API_BASE}/agui`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(payload),
    signal: opts.signal,
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

// Polled while a Legacy Portal OAuth authorization link is outstanding
// (see App.jsx) so the chat can auto-resume once the broker finishes in
// the new tab, instead of them having to come back and type something.
export async function checkLegacyOAuthStatus(sessionUri) {
  const res = await fetch(`${API_BASE}/oauth/legacy-status?session_uri=${encodeURIComponent(sessionUri)}`);
  if (!res.ok) return { completed: false };
  return res.json();
}

export function sendMessage(accessToken, { threadId, runId, text }, onEvent, opts) {
  return streamAgui(
    accessToken,
    { thread_id: threadId, run_id: runId, messages: [{ role: "user", content: text }] },
    onEvent,
    opts
  );
}

export function resumeInterrupt(accessToken, { threadId, runId, interruptId, approved }, onEvent, opts) {
  return streamAgui(
    accessToken,
    {
      thread_id: threadId,
      run_id: runId,
      resume: [{ interrupt_id: interruptId, status: "resolved", payload: { approved } }],
    },
    onEvent,
    opts
  );
}

/**
 * Genuinely halts an in-flight run server-side via StopRuntimeSession --
 * not merely abandoning the SSE stream client-side, which would leave
 * the harness (and its billed compute) running unattended.
 */
export async function stopRun(accessToken, runId) {
  const res = await fetch(`${API_BASE}/agui/stop`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify({ run_id: runId }),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`/agui/stop failed: ${text}`);
  }
  return res.json();
}

/**
 * The default browse-grid population on login -- investors get the
 * whole market, brokers get just their own listings (the backend
 * decides which, from the caller's real Cognito group).
 */
export async function fetchListings(accessToken) {
  const res = await fetch(`${API_BASE}/listings`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`/listings failed: ${text}`);
  }
  return res.json();
}
