const ASSET_TYPE_LABELS = {
  multifamily: "Multifamily",
  retail: "Retail",
  "mixed-use": "Mixed-Use",
};

function formatMoney(n) {
  if (n == null) return "—";
  return `$${Number(n).toLocaleString()}`;
}

function formatPricePerUnit(askingPrice, units) {
  if (!askingPrice || !units) return null;
  return Math.round(askingPrice / units);
}

/**
 * Renders one listing. Works for both a plain listing (from /listings or
 * a live search_listings/get_listing tool result) and a listing enriched
 * with underwriting metrics (cap_rate, dscr, cash_on_cash, meets_criteria)
 * once a comparison has run -- the same card, extra rows if the data is
 * there.
 */
export default function PropertyCard({ listing, recommended, onSelect }) {
  const pricePerUnit = listing.price_per_unit ?? formatPricePerUnit(listing.askingPrice, listing.units);
  const hasUnderwriting = listing.cap_rate !== undefined;
  const isRecommended = recommended && listing.listingId === recommended.listingId;

  return (
    <button
      type="button"
      className={`property-card ${isRecommended ? "property-card-recommended" : ""}`}
      onClick={() => onSelect?.(listing)}
    >
      {isRecommended && <div className="property-ribbon">Recommended</div>}
      <div className="property-card-top">
        <span className={`asset-badge asset-badge-${listing.assetType || "multifamily"}`}>
          {ASSET_TYPE_LABELS[listing.assetType] || listing.assetType || "Property"}
        </span>
        {listing.valueAdd && <span className="value-add-badge">Value-Add</span>}
      </div>
      <div className="property-card-name">{listing.name}</div>
      <div className="property-card-market">{listing.market?.replace(/-/g, " ") || ""}</div>

      <div className="property-card-stats">
        <div className="property-stat">
          <span className="property-stat-value">{listing.units ?? "—"}</span>
          <span className="property-stat-label">Units</span>
        </div>
        <div className="property-stat">
          <span className="property-stat-value">{formatMoney(listing.askingPrice)}</span>
          <span className="property-stat-label">Asking</span>
        </div>
        <div className="property-stat">
          <span className="property-stat-value">{pricePerUnit ? formatMoney(pricePerUnit) : "—"}</span>
          <span className="property-stat-label">$ / Unit</span>
        </div>
      </div>

      {hasUnderwriting && (
        <div className="property-card-underwriting">
          <div className={`uw-stat ${listing.meets_criteria ? "uw-pass" : "uw-fail"}`}>
            <span className="uw-stat-value">{listing.cap_rate}%</span>
            <span className="uw-stat-label">Cap Rate</span>
          </div>
          <div className="uw-stat">
            <span className="uw-stat-value">{listing.dscr}</span>
            <span className="uw-stat-label">DSCR</span>
          </div>
          <div className="uw-stat">
            <span className="uw-stat-value">{listing.cash_on_cash}%</span>
            <span className="uw-stat-label">Cash/Cash</span>
          </div>
          <span className={`meets-badge ${listing.meets_criteria ? "meets-yes" : "meets-no"}`}>
            {listing.meets_criteria ? "Meets criteria" : "Below floor"}
          </span>
        </div>
      )}

      {listing.brokerId && (
        <div className="property-card-broker">Listed by {listing.brokerId}</div>
      )}
    </button>
  );
}
