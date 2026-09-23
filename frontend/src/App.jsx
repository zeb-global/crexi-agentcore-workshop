import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { login, sendMessage, resumeInterrupt, stopRun, fetchListings } from "./api";
import LoginScreen from "./components/LoginScreen";
import ListingsGrid from "./components/ListingsGrid";
import ComparisonTable from "./components/ComparisonTable";
import ToolSteps from "./components/ToolTimeline";
import CostPanel from "./components/CostPanel";
import ConfirmModal from "./components/ConfirmModal";
import RunStatusBar from "./components/RunStatusBar";
import "./App.css";

function newId() {
  return crypto.randomUUID();
}

function emptyTurn(userText) {
  return {
    id: newId(),
    userText,
    status: "streaming", // streaming | awaiting-confirmation | done | error | stopped
    assistantMessageId: null,
    assistantText: "",
    toolCalls: [],
    toolIndex: {},
    comparison: null,
    error: null,
  };
}

// Normalizes an underwriting_comparison's per-property shape (snake_case,
// e.g. asking_price/price_per_unit) into the same camelCase shape plain
// listings use (askingPrice/units/...), so PropertyCard can render both
// without knowing which source it came from. Used to push a comparison's
// properties onto the grid (in addition to rendering the same data
// inline in chat via ComparisonTable -- both, not either/or).
function comparisonToListings(comparison) {
  if (!comparison?.properties) return [];
  return comparison.properties.map((p) => ({
    listingId: p.listingId,
    name: p.name,
    units: p.units,
    askingPrice: p.askingPrice ?? p.asking_price,
    price_per_unit: p.price_per_unit,
    cap_rate: p.cap_rate,
    dscr: p.dscr,
    cash_on_cash: p.cash_on_cash,
    meets_criteria: p.meets_criteria,
  }));
}

export default function App() {
  const [session, setSession] = useState(null); // {accessToken, username, group}
  const [loginError, setLoginError] = useState(null);
  const [loginBusy, setLoginBusy] = useState(false);

  const [turns, setTurns] = useState([]);
  const [costEvents, setCostEvents] = useState([]);
  const [pendingInterrupt, setPendingInterrupt] = useState(null);
  const [running, setRunning] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [currentTool, setCurrentTool] = useState(null);
  const [input, setInput] = useState("");

  // Chat rail width, in px -- draggable via the divider between it and
  // the browse column (see handleResizeStart below). Persisted across
  // reloads so a chosen layout sticks.
  const [railWidth, setRailWidth] = useState(() => {
    const saved = Number(localStorage.getItem("crexi-rail-width"));
    return saved && saved >= 320 && saved <= 720 ? saved : 400;
  });
  const resizingRef = useRef(false);

  // Default grid population (all listings for an investor, own listings
  // for a broker) fetched directly on login -- separate from whatever
  // the agent has most recently surfaced, which OVERRIDES this while
  // present (see activeListings below).
  const [defaultListings, setDefaultListings] = useState([]);
  const [defaultListingsLoading, setDefaultListingsLoading] = useState(false);

  // Whatever the agent's own search_listings/get_listing/underwriting
  // calls most recently returned -- the grid mirrors THIS when present,
  // falling back to defaultListings. Cleared by the "Show all listings"
  // button below, which is the only way back to the default view once
  // the grid has narrowed -- there was previously no way back at all.
  const [activeListings, setActiveListings] = useState(null);
  const [comparisonMeta, setComparisonMeta] = useState(null); // {criteria, recommended} for the current comparison, if any

  const threadIdRef = useRef(newId());
  const runIdRef = useRef(null);
  const abortRef = useRef(null);
  const textareaRef = useRef(null);
  const scrollRef = useRef(null);

  const totalUsd = costEvents.reduce((sum, c) => sum + c.costUsd, 0);

  const gridListings = activeListings ?? defaultListings;
  const gridTitle = session?.group === "brokers" ? "My Listings" : "Columbus Multifamily";
  const gridSubtitle = comparisonMeta
    ? `Underwriting comparison — cap rate ≥ ${comparisonMeta.criteria?.cap_rate_min ?? "—"}%`
    : session?.group === "brokers"
      ? "Listings you own"
      : "All listings in your market";
  const showResetButton = activeListings !== null;

  // Autosize the composer textarea as the user types.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [input]);

  // Keep the transcript pinned to the latest content while streaming.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns]);

  // Drag-to-resize the chat rail. Attaches document-level listeners only
  // while a drag is in progress, so it costs nothing the rest of the time.
  function handleResizeStart(e) {
    e.preventDefault();
    resizingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function onMove(moveEvent) {
      if (!resizingRef.current) return;
      const newWidth = window.innerWidth - moveEvent.clientX;
      const clamped = Math.min(720, Math.max(320, newWidth));
      setRailWidth(clamped);
    }
    function onUp() {
      resizingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      setRailWidth((w) => {
        localStorage.setItem("crexi-rail-width", String(w));
        return w;
      });
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }

  // Default grid: fetched once per session, straight from the backend,
  // independent of chat -- this is what's on screen before anyone asks
  // the agent anything.
  useEffect(() => {
    if (!session) return;
    setDefaultListingsLoading(true);
    fetchListings(session.accessToken)
      .then((data) => setDefaultListings(data.listings || []))
      .catch(() => setDefaultListings([]))
      .finally(() => setDefaultListingsLoading(false));
  }, [session]);

  function updateLastTurn(fn) {
    setTurns((prev) => {
      if (prev.length === 0) return prev;
      const next = [...prev];
      next[next.length - 1] = fn(next[next.length - 1]);
      return next;
    });
  }

  const handleEvent = useCallback((evt) => {
    switch (evt.type) {
      case "TEXT_MESSAGE_START":
        updateLastTurn((t) => ({ ...t, assistantMessageId: evt.messageId }));
        break;
      case "TEXT_MESSAGE_CONTENT":
        updateLastTurn((t) =>
          t.assistantMessageId === evt.messageId
            ? { ...t, assistantText: t.assistantText + evt.delta }
            : t
        );
        break;
      case "TOOL_CALL_START":
        setCurrentTool(evt.toolCallName);
        updateLastTurn((t) => {
          const toolIndex = { ...t.toolIndex, [evt.toolCallId]: t.toolCalls.length };
          return {
            ...t,
            toolIndex,
            toolCalls: [
              ...t.toolCalls,
              { id: evt.toolCallId, name: evt.toolCallName, args: "", result: null, done: false },
            ],
          };
        });
        break;
      case "TOOL_CALL_ARGS":
        updateLastTurn((t) => {
          const idx = t.toolIndex[evt.toolCallId];
          if (idx === undefined) return t;
          const toolCalls = [...t.toolCalls];
          toolCalls[idx] = { ...toolCalls[idx], args: toolCalls[idx].args + evt.delta };
          return { ...t, toolCalls };
        });
        break;
      case "TOOL_CALL_END":
        updateLastTurn((t) => {
          const idx = t.toolIndex[evt.toolCallId];
          if (idx === undefined) return t;
          const toolCalls = [...t.toolCalls];
          toolCalls[idx] = { ...toolCalls[idx], done: true };
          return { ...t, toolCalls };
        });
        break;
      case "TOOL_CALL_RESULT":
        updateLastTurn((t) => {
          const idx = t.toolIndex[evt.toolCallId];
          if (idx === undefined) return t;
          const toolCalls = [...t.toolCalls];
          toolCalls[idx] = {
            ...toolCalls[idx],
            result: (toolCalls[idx].result || "") + evt.content,
          };
          return { ...t, toolCalls };
        });
        break;
      case "STATE_DELTA":
        for (const op of evt.delta || []) {
          if (op.path === "/comparison") {
            // Both: renders inline in THIS turn's chat bubble AND updates
            // the grid to show the compared properties with their
            // underwriting metrics (cap rate, DSCR, cash-on-cash) and a
            // "Recommended" ribbon on the winner.
            updateLastTurn((t) => ({ ...t, comparison: op.value }));
            setActiveListings(comparisonToListings(op.value));
            setComparisonMeta({ criteria: op.value.criteria, recommended: op.value.recommended });
          } else if (op.path === "/activeListings") {
            setActiveListings(op.value);
            setComparisonMeta(null);
          }
        }
        break;
      case "CUSTOM":
        if (evt.name === "cost_delta") setCostEvents((prev) => [...prev, evt.value]);
        break;
      case "RUN_FINISHED":
        setCurrentTool(null);
        if (evt.outcome?.type === "interrupt") {
          setPendingInterrupt(evt.outcome.interrupts[0]);
          updateLastTurn((t) => ({ ...t, status: "awaiting-confirmation" }));
          setRunning(false);
        } else {
          updateLastTurn((t) => ({ ...t, status: "done" }));
          setPendingInterrupt(null);
          setRunning(false);
        }
        break;
      case "RUN_ERROR":
        setCurrentTool(null);
        updateLastTurn((t) => ({ ...t, status: "error", error: evt.message }));
        setRunning(false);
        break;
      default:
        break;
    }
  }, []);

  function handleLogout() {
    setSession(null);
    setTurns([]);
    setCostEvents([]);
    setPendingInterrupt(null);
    setRunning(false);
    setCurrentTool(null);
    setActiveListings(null);
    setComparisonMeta(null);
    setDefaultListings([]);
    threadIdRef.current = newId();
    runIdRef.current = null;
  }

  // The only way back to the default grid once chat has narrowed it --
  // does not touch chat history, only which listings the grid shows.
  function handleShowAllListings() {
    setActiveListings(null);
    setComparisonMeta(null);
  }

  async function handleLogin(username, password) {
    setLoginBusy(true);
    setLoginError(null);
    try {
      const result = await login(username, password);
      setSession({ accessToken: result.accessToken, username: result.username, group: result.group });
    } catch (e) {
      setLoginError(e.message);
    } finally {
      setLoginBusy(false);
    }
  }

  async function handleSend() {
    if (!input.trim() || running) return;
    const text = input.trim();
    setInput("");
    setTurns((prev) => [...prev, emptyTurn(text)]);
    setRunning(true);
    runIdRef.current = newId();
    abortRef.current = new AbortController();
    try {
      await sendMessage(
        session.accessToken,
        { threadId: threadIdRef.current, runId: runIdRef.current, text },
        handleEvent,
        { signal: abortRef.current.signal }
      );
    } catch (e) {
      if (e.name !== "AbortError") {
        updateLastTurn((t) => ({ ...t, status: "error", error: e.message }));
      }
      setRunning(false);
      setCurrentTool(null);
    }
  }

  function handleComposerKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  async function handleInterruptAnswer(approved) {
    const interrupt = pendingInterrupt;
    setPendingInterrupt(null);
    setRunning(true);
    abortRef.current = new AbortController();
    try {
      await resumeInterrupt(
        session.accessToken,
        { threadId: threadIdRef.current, runId: runIdRef.current, interruptId: interrupt.id, approved },
        handleEvent,
        { signal: abortRef.current.signal }
      );
    } catch (e) {
      if (e.name !== "AbortError") {
        updateLastTurn((t) => ({ ...t, status: "error", error: e.message }));
      }
      setRunning(false);
      setCurrentTool(null);
    }
  }

  // Genuine server-side stop: halts the harness's Runtime session via
  // StopRuntimeSession (not just abandoning our own read of the SSE
  // stream, which would leave the run -- and its billed compute --
  // going unattended on AWS's side).
  async function handleStop() {
    if (!runIdRef.current || stopping) return;
    setStopping(true);
    try {
      await stopRun(session.accessToken, runIdRef.current);
    } catch (e) {
      console.error("Failed to stop run server-side:", e);
    } finally {
      abortRef.current?.abort();
      setStopping(false);
      setRunning(false);
      setCurrentTool(null);
      updateLastTurn((t) => (t.status === "streaming" ? { ...t, status: "stopped" } : t));
    }
  }

  if (!session) {
    return <LoginScreen onLogin={handleLogin} error={loginError} busy={loginBusy} />;
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span className="app-logo">
          CREX<span className="app-logo-accent">i</span>
          <span className="app-logo-sub">{session.group === "brokers" ? "Broker Workspace" : "Investor Workspace"}</span>
        </span>
        <span className="app-header-user">
          <span className="app-header-name">{session.username}</span>
          <span className="app-header-group">{session.group}</span>
          <button className="btn-link" onClick={handleLogout}>
            Sign out
          </button>
        </span>
      </header>
      <div className="app-body">
        <main className="browse-column">
          <ListingsGrid
            title={gridTitle}
            subtitle={gridSubtitle}
            listings={gridListings}
            recommended={comparisonMeta?.recommended}
            loading={defaultListingsLoading && gridListings.length === 0}
            onReset={showResetButton ? handleShowAllListings : null}
          />
        </main>

        <div
          className="resize-handle"
          onMouseDown={handleResizeStart}
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize chat panel"
        />

        <aside className="chat-rail" style={{ width: railWidth }}>
          <div className="chat-rail-header">
            <span className="chat-rail-title">Assistant</span>
            <CostPanel costEvents={costEvents} totalUsd={totalUsd} />
          </div>

          <div className="messages" ref={scrollRef}>
            {turns.length === 0 && (
              <div className="empty-state">
                <div className="empty-state-mark">C</div>
                <p>Ask about listings, market comps, or a price change.</p>
              </div>
            )}
            {turns.map((t) => (
              <div key={t.id} className="turn">
                <div className="turn-user-row">
                  <div className="bubble-user">{t.userText}</div>
                </div>
                <div className="turn-assistant-row">
                  <div className="assistant-avatar">C</div>
                  <div className="assistant-content">
                    <ToolSteps toolCalls={t.toolCalls} />
                    {t.assistantText && (
                      <div className="assistant-text">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{t.assistantText}</ReactMarkdown>
                        {t.status === "streaming" && <span className="stream-cursor" />}
                      </div>
                    )}
                    {!t.assistantText && t.status === "streaming" && (
                      <div className="thinking-dots" aria-label="thinking">
                        <span />
                        <span />
                        <span />
                      </div>
                    )}
                    {t.comparison && <ComparisonTable comparison={t.comparison} />}
                    {t.status === "awaiting-confirmation" && (
                      <div className="turn-note">Waiting on your confirmation…</div>
                    )}
                    {t.status === "stopped" && <div className="turn-note">Stopped.</div>}
                    {t.error && <div className="turn-error">Error: {t.error}</div>}
                  </div>
                </div>
              </div>
            ))}
          </div>

          <RunStatusBar running={running} currentTool={currentTool} onStop={handleStop} stopping={stopping} />

          <div className="composer">
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleComposerKeyDown}
              placeholder={running ? "Working…" : "Ask about listings, market comps, or a price change…"}
              disabled={running}
            />
            <button
              className="btn-send"
              onClick={handleSend}
              disabled={running || !input.trim()}
              aria-label="Send"
              title="Send"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path d="M2 8L14 2L9.5 14L7.5 9L2 8Z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
              </svg>
            </button>
          </div>
        </aside>
      </div>
      <ConfirmModal interrupt={pendingInterrupt} onAnswer={handleInterruptAnswer} busy={running} />
    </div>
  );
}
