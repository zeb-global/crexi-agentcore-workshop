export default function CostPanel({ costEvents, totalUsd }) {
  return (
    <div className="cost-panel">
      <div className="cost-panel-header">Cost this session</div>
      <div className="cost-total">${totalUsd.toFixed(4)}</div>
      {costEvents.slice(-5).map((c, i) => (
        <div key={i} className="cost-row">
          <span className="cost-model">{c.label}</span>
          <span className="cost-tokens">
            {c.inputTokens}in / {c.outputTokens}out
          </span>
          <span className="cost-usd">${c.costUsd.toFixed(4)}</span>
        </div>
      ))}
    </div>
  );
}
