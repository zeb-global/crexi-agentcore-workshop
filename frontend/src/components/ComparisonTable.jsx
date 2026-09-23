export default function ComparisonTable({ comparison }) {
  if (!comparison) return null;
  const { criteria, properties, recommended } = comparison;
  return (
    <div className="comparison-card">
      <div className="comparison-header">
        Underwriting comparison — cap rate ≥ {criteria?.cap_rate_min}%
      </div>
      <div className="comparison-table-scroll">
        <table>
          <thead>
            <tr>
              <th>Property</th>
              <th>Units</th>
              <th>Asking</th>
              <th>NOI</th>
              <th>Cap rate</th>
              <th>$/unit</th>
              <th>DSCR</th>
              <th>CoC</th>
              <th>Meets?</th>
            </tr>
          </thead>
          <tbody>
            {properties?.map((p) => (
              <tr
                key={p.listingId}
                className={p.listingId === recommended?.listingId ? "recommended" : ""}
              >
                <td>{p.name}</td>
                <td>{p.units}</td>
                <td>${(p.askingPrice ?? p.asking_price)?.toLocaleString()}</td>
                <td>${p.noi?.toLocaleString()}</td>
                <td>{p.cap_rate}%</td>
                <td>${p.price_per_unit?.toLocaleString()}</td>
                <td>{p.dscr}</td>
                <td>{p.cash_on_cash}%</td>
                <td>{p.meets_criteria ? "✓" : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {recommended && (
        <div className="comparison-recommendation">Recommended: {recommended.name}</div>
      )}
    </div>
  );
}
