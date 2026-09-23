export default function CostPanel({ costEvents, totalUsd }) {
  return (
    <div className="cost-panel">
      <div className="cost-panel-header">Session cost</div>
      <div className="cost-total">${totalUsd.toFixed(4)}</div>
      <div className="cost-meta">{costEvents.length} model/tool calls</div>
      <div className="cost-list">
        {costEvents.length === 0 && <div className="cost-empty">No activity yet.</div>}
        {costEvents
          .slice(-6)
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
  );
}
