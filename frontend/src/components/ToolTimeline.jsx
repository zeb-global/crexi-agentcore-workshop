import { useState } from "react";

const LABELS = {
  "code-interpreter": "Running underwriting (Code Interpreter)",
  submit_underwriting_result: "Submitting verified comparison",
  get_legacy_credentials: "Resolving legacy-desk credentials",
  confirm_listing_change: "Requesting confirmation",
  browser: "Browser session",
};

function friendlyName(name) {
  if (LABELS[name]) return LABELS[name];
  // Gateway tools arrive as "<target>___<tool>", e.g. market-data___search_listings
  const parts = name.split("___");
  const tool = parts[parts.length - 1] || name;
  return tool.replace(/_/g, " ");
}

export default function ToolTimeline({ toolCalls }) {
  const [expanded, setExpanded] = useState(null); // toolCallId currently showing detail

  if (!toolCalls.length) return null;

  return (
    <div className="tool-timeline">
      <div className="tool-timeline-header">This turn's activity</div>
      <div className="tool-timeline-list">
        {toolCalls.map((t) => {
          const isOpen = expanded === t.id;
          return (
            <div key={t.id} className="tool-row-compact">
              <button
                type="button"
                className="tool-row-summary"
                onClick={() => setExpanded(isOpen ? null : t.id)}
                aria-expanded={isOpen}
              >
                <span className={`tool-status ${t.done ? "done" : "running"}`}>
                  {t.done ? "✓" : "…"}
                </span>
                <span className="tool-name">{friendlyName(t.name)}</span>
                <span className="tool-chevron">{isOpen ? "▾" : "▸"}</span>
              </button>
              {isOpen && (
                <div className="tool-row-detail">
                  {t.args && (
                    <>
                      <div className="tool-detail-label">Arguments</div>
                      <code className="tool-detail-code">{t.args}</code>
                    </>
                  )}
                  {t.result && (
                    <>
                      <div className="tool-detail-label">Result</div>
                      <code className="tool-detail-code">
                        {t.result.length > 400 ? t.result.slice(0, 400) + "…" : t.result}
                      </code>
                    </>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
