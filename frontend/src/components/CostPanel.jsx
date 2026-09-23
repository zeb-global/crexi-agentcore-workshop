import { useState } from "react";

/**
 * Tucked away by default -- a small pill showing the running total,
 * click to expand a dropdown with the per-call breakdown. Cost is a
 * secondary, facilitator-facing concern, not the primary focus of the
 * interface.
 */
export default function CostPanel({ costEvents, totalUsd }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="cost-pill-wrap">
      <button type="button" className="cost-pill" onClick={() => setOpen((o) => !o)}>
        <span className="cost-pill-dot" />
        <span className="cost-pill-amount">${totalUsd.toFixed(4)}</span>
        <span className="cost-pill-chevron">{open ? "\u25BE" : "\u25B8"}</span>
      </button>
      {open && (
        <div className="cost-dropdown">
          <div className="cost-dropdown-header">
            <span>Session cost</span>
            <span className="cost-meta">{costEvents.length} calls</span>
          </div>
          <div className="cost-list">
            {costEvents.length === 0 && <div className="cost-empty">No activity yet.</div>}
            {costEvents
              .slice(-8)
              .reverse()
              .map((c, i) => (
                <div key={i} className="cost-row">
                  <div className="cost-row-top">
                    <span className="cost-model">{c.label}</span>
                    <span className="cost-usd">${c.costUsd.toFixed(4)}</span>
                  </div>
                  <div className="cost-tokens">
                    {c.inputTokens}&nbsp;in&nbsp;&middot;&nbsp;{c.outputTokens}&nbsp;out
                  </div>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
