import PropertyCard from "./PropertyCard";

/**
 * The main-pane browse grid. Deliberately NOT a self-serve filter UI --
 * it mirrors whatever set of listings is currently "in view": the
 * default (all listings for an investor, own listings for a broker) on
 * login, or whatever the agent's own search_listings/get_listing/
 * underwriting-comparison calls most recently surfaced. See App.jsx's
 * activeListings/comparison state and how it's threaded here.
 */
export default function ListingsGrid({ title, subtitle, listings, recommended, loading, onReset }) {
  return (
    <div className="listings-grid-wrap">
      <div className="listings-grid-header">
        <div>
          <h1 className="listings-grid-title">{title}</h1>
          {subtitle && <p className="listings-grid-subtitle">{subtitle}</p>}
        </div>
        <div className="listings-grid-header-right">
          {onReset && (
            <button type="button" className="listings-grid-reset" onClick={onReset}>
              Show all listings
            </button>
          )}
          <span className="listings-grid-count">
            {listings.length} {listings.length === 1 ? "listing" : "listings"}
          </span>
        </div>
      </div>

      {loading && (
        <div className="listings-grid-empty">
          <div className="thinking-dots">
            <span />
            <span />
            <span />
          </div>
        </div>
      )}

      {!loading && listings.length === 0 && (
        <div className="listings-grid-empty">
          <p>No listings to show yet.</p>
        </div>
      )}

      {!loading && listings.length > 0 && (
        <div className="listings-grid">
          {listings.map((l) => (
            <PropertyCard key={l.listingId} listing={l} recommended={recommended} />
          ))}
        </div>
      )}
    </div>
  );
}
