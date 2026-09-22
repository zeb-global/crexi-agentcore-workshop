import { useCallback, useRef, useState } from "react";
import { login, sendMessage, resumeInterrupt } from "./api";
import LoginScreen from "./components/LoginScreen";
import ComparisonTable from "./components/ComparisonTable";
import ToolTimeline from "./components/ToolTimeline";
import CostPanel from "./components/CostPanel";
import ConfirmModal from "./components/ConfirmModal";
import "./App.css";

function newId() {
  return crypto.randomUUID();
}

export default function App() {
  const [session, setSession] = useState(null); // {accessToken, username, group}
  const [loginError, setLoginError] = useState(null);
  const [loginBusy, setLoginBusy] = useState(false);

  const [messages, setMessages] = useState([]); // [{id, role, text}]
  const [toolCalls, setToolCalls] = useState([]); // [{id, name, args, result, done}]
  const [comparison, setComparison] = useState(null);
  const [costEvents, setCostEvents] = useState([]);
  const [pendingInterrupt, setPendingInterrupt] = useState(null);
  const [running, setRunning] = useState(false);
  const [input, setInput] = useState("");

  const threadIdRef = useRef(newId());
  const runIdRef = useRef(null);
  const messageIndexRef = useRef({}); // messageId -> index in messages[]
  const toolIndexRef = useRef({}); // toolCallId -> index in toolCalls[]

  const totalUsd = costEvents.reduce((sum, c) => sum + c.costUsd, 0);

  const handleEvent = useCallback((evt) => {
    switch (evt.type) {
      case "TEXT_MESSAGE_START":
        setMessages((prev) => {
          messageIndexRef.current[evt.messageId] = prev.length;
          return [...prev, { id: evt.messageId, role: evt.role, text: "" }];
        });
        break;
      case "TEXT_MESSAGE_CONTENT":
        setMessages((prev) => {
          const idx = messageIndexRef.current[evt.messageId];
          if (idx === undefined) return prev;
          const next = [...prev];
          next[idx] = { ...next[idx], text: next[idx].text + evt.delta };
          return next;
        });
        break;
      case "TOOL_CALL_START":
        setToolCalls((prev) => {
          toolIndexRef.current[evt.toolCallId] = prev.length;
          return [...prev, { id: evt.toolCallId, name: evt.toolCallName, args: "", result: null, done: false }];
        });
        break;
      case "TOOL_CALL_ARGS":
        setToolCalls((prev) => {
          const idx = toolIndexRef.current[evt.toolCallId];
          if (idx === undefined) return prev;
          const next = [...prev];
          next[idx] = { ...next[idx], args: next[idx].args + evt.delta };
          return next;
        });
        break;
      case "TOOL_CALL_END":
        setToolCalls((prev) => {
          const idx = toolIndexRef.current[evt.toolCallId];
          if (idx === undefined) return prev;
          const next = [...prev];
          next[idx] = { ...next[idx], done: true };
          return next;
        });
        break;
      case "TOOL_CALL_RESULT":
        setToolCalls((prev) => {
          const idx = toolIndexRef.current[evt.toolCallId];
          if (idx === undefined) return prev;
          const next = [...prev];
          next[idx] = { ...next[idx], result: (next[idx].result || "") + evt.content };
          return next;
        });
        break;
      case "STATE_DELTA":
        for (const op of evt.delta || []) {
          if (op.path === "/comparison") setComparison(op.value);
        }
        break;
      case "CUSTOM":
        if (evt.name === "cost_delta") setCostEvents((prev) => [...prev, evt.value]);
        break;
      case "RUN_FINISHED":
        if (evt.outcome?.type === "interrupt") {
          // We're waiting on a human now, not the backend -- release
          // the busy state so the confirm modal's buttons are clickable.
          setPendingInterrupt(evt.outcome.interrupts[0]);
          setRunning(false);
        } else {
          setPendingInterrupt(null);
          setRunning(false);
        }
        break;
      case "RUN_ERROR":
        setMessages((prev) => [...prev, { id: newId(), role: "system", text: `Error: ${evt.message}` }]);
        setRunning(false);
        break;
      default:
        break;
    }
  }, []);

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
    setMessages((prev) => [...prev, { id: newId(), role: "user", text }]);
    setRunning(true);
    runIdRef.current = newId();
    try {
      await sendMessage(
        session.accessToken,
        { threadId: threadIdRef.current, runId: runIdRef.current, text },
        handleEvent
      );
    } catch (e) {
      setMessages((prev) => [...prev, { id: newId(), role: "system", text: `Error: ${e.message}` }]);
      setRunning(false);
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
      setMessages((prev) => [...prev, { id: newId(), role: "system", text: `Error: ${e.message}` }]);
      setRunning(false);
    }
  }

  if (!session) {
    return <LoginScreen onLogin={handleLogin} error={loginError} busy={loginBusy} />;
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <span>CREXi Workshop Assistant</span>
        <span className="app-header-user">
          {session.username} · {session.group}
        </span>
      </header>
      <div className="app-body">
        <main className="chat-column">
          <div className="messages">
            {messages.map((m) => (
              <div key={m.id} className={`message message-${m.role}`}>
                {m.text}
              </div>
            ))}
            <ToolTimeline toolCalls={toolCalls} />
            <ComparisonTable comparison={comparison} />
          </div>
          <div className="composer">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
              placeholder={running ? "Working…" : "Ask about listings, market comps, or a price change…"}
              disabled={running}
            />
            <button className="btn btn-confirm" onClick={handleSend} disabled={running}>
              Send
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
