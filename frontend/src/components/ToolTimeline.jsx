export default function ToolTimeline({ toolCalls }) {
  if (!toolCalls.length) return null;
  return (
    <div className="tool-timeline">
      <div className="tool-timeline-header">Tool activity</div>
      {toolCalls.map((t) => (
        <div key={t.id} className={`tool-row ${t.done ? "done" : "running"}`}>
          <span className="tool-name">{t.name}</span>
          {t.args && <code className="tool-args">{t.args}</code>}
          {t.result && <span className="tool-result-badge">✓ result</span>}
        </div>
      ))}
    </div>
  );
}
