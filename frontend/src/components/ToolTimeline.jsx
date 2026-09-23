import { useState } from "react";

const LABELS = {
  "code-interpreter": "Running underwriting",
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

export default function ToolSteps({ toolCalls }) {
  const [expanded, setExpanded] = useState(null); // toolCallId currently showing detail

  if (!toolCalls.length) return null;

  return (
    <div className="tool-steps">
      {toolCalls.map((t, i) => {
        const isOpen = expanded === t.id;
        const isLast = i === toolCalls.length - 1;
        return (
          <div key={t.id} className={`tool-step ${t.done ? "tool-step-done" : "tool-step-active"}`}>
            <div className="tool-step-rail">
              <span className="tool-step-dot" />
              {!isLast && <span className="tool-step-line" />}
            </div>
            <div className="tool-step-body">
              <button
                type="button"
                className="tool-step-summary"
                onClick={() => setExpanded(isOpen ? null : t.id)}
                aria-expanded={isOpen}
              >
                <span className="tool-step-name">{friendlyName(t.name)}</span>
                {!t.done && <span className="tool-step-spinner" />}
                <span className="tool-step-chevron">{isOpen ? "\u25BE" : "\u25B8"}</span>
              </button>
              {isOpen && (
                <div className="tool-step-detail">
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
          </div>
        );
      })}
    </div>
  );
}
