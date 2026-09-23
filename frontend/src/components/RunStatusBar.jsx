const LABELS = {
  "code-interpreter": "Running underwriting",
  code_interpreter: "Running underwriting",
  get_legacy_credentials: "Resolving legacy-desk credentials",
  confirm_listing_change: "Requesting confirmation",
  browser: "Browser session",
};

function friendlyToolName(name) {
  if (!name) return "Working";
  if (LABELS[name]) return LABELS[name];
  const parts = name.split("___");
  const tool = parts[parts.length - 1] || name;
  return tool.replace(/_/g, " ");
}

/**
 * Contextual "stop" bar -- exists ONLY while a run is actively
 * streaming, collapses to nothing the instant it finishes. onStop
 * triggers a genuine server-side halt (StopRuntimeSession), not just
 * the client giving up on reading the SSE stream.
 */
export default function RunStatusBar({ running, currentTool, onStop, stopping }) {
  if (!running) return null;

  return (
    <div className="run-status-bar">
      <span className="run-status-spinner" />
      <span className="run-status-label">{friendlyToolName(currentTool)}…</span>
      <button type="button" className="run-status-stop" onClick={onStop} disabled={stopping}>
        {stopping ? "Stopping…" : "Stop"}
      </button>
    </div>
  );
}
