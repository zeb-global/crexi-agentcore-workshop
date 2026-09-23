import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { login, sendMessage, resumeInterrupt } from "./api";
import LoginScreen from "./components/LoginScreen";
import ComparisonTable from "./components/ComparisonTable";
import ToolSteps from "./components/ToolTimeline";
import CostPanel from "./components/CostPanel";
import ConfirmModal from "./components/ConfirmModal";
import "./App.css";

function newId() {
  return crypto.randomUUID();
}

function emptyTurn(userText) {
  return {
    id: newId(),
    userText,
    status: "streaming", // streaming | awaiting-confirmation | done | error
    assistantMessageId: null,
    assistantText: "",
    toolCalls: [],
    toolIndex: {},
    comparison: null,
    error: null,
  };
}

export default function App() {
  const [session, setSession] = useState(null); // {accessToken, username, group}
  const [loginError, setLoginError] = useState(null);
  const [loginBusy, setLoginBusy] = useState(false);

  const [turns, setTurns] = useState([]);
  const [costEvents, setCostEvents] = useState([]);
  const [pendingInterrupt, setPendingInterrupt] = useState(null);
  const [running, setRunning] = useState(false);
  const [input, setInput] = useState("");

  const threadIdRef = useRef(newId());
  const runIdRef = useRef(null);
  const textareaRef = useRef(null);
  const scrollRef = useRef(null);

  const totalUsd = costEvents.reduce((sum, c) => sum + c.costUsd, 0);

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
            updateLastTurn((t) => ({ ...t, comparison: op.value }));
          }
        }
        break;
      case "CUSTOM":
        if (evt.name === "cost_delta") setCostEvents((prev) => [...prev, evt.value]);
        break;
      case "RUN_FINISHED":
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
    threadIdRef.current = newId();
    runIdRef.current = null;
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
    try {
      await sendMessage(
        session.accessToken,
        { threadId: threadIdRef.current, runId: runIdRef.current, text },
        handleEvent
      );
    } catch (e) {
      updateLastTurn((t) => ({ ...t, status: "error", error: e.message }));
      setRunning(false);
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
    try {
      await resumeInterrupt(
        session.accessToken,
        { threadId: threadIdRef.current, runId: runIdRef.current, interruptId: interrupt.id, approved },
        handleEvent
      );
    } catch (e) {
      updateLastTurn((t) => ({ ...t, status: "error", error: e.message }));
      setRunning(false);
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
          <span className="app-logo-sub">Workshop Assistant</span>
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
        <main className="chat-column">
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
                    {!t.assistantText && (t.status === "streaming") && (
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
                    {t.error && <div className="turn-error">Error: {t.error}</div>}
                  </div>
                </div>
              </div>
            ))}
          </div>
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
        </main>
        <aside className="side-column">
          <CostPanel costEvents={costEvents} totalUsd={totalUsd} />
        </aside>
      </div>
      <ConfirmModal interrupt={pendingInterrupt} onAnswer={handleInterruptAnswer} busy={running} />
    </div>
  );
}
