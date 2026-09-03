import type { SecurityRead } from "@/lib/api/types";
import { assetTypeLabel, formatDate, statusLabel } from "@/lib/format";

/**
 * Compact metadata header. Presentational, server-rendered. The internal
 * database id is never shown; status is text, not colour alone.
 */
export function SecurityHeader({ security }: { security: SecurityRead }) {
  const inactive = !security.is_active;
  const stats: Array<[string, string]> = [
    ["Exchange", security.exchange],
    ["Asset type", assetTypeLabel(security.asset_type)],
    ["Currency", security.currency],
    ["Status", statusLabel(security)],
  ];

  return (
    <header>
      <div className="qs-sec-head__id">
        <span className="qs-sec-head__ticker">{security.ticker}</span>
        {inactive && (
          <span className="qs-sec-head__pill" data-testid="security-status">
            <span className="qs-dot" />
            INACTIVE
          </span>
        )}
      </div>
      <p className="qs-sec-head__name">{security.name}</p>

      <dl className="qs-stats">
        {stats.map(([label, value]) => (
          <div className="qs-stat" key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>

      {inactive && (
        <div className="qs-alert" role="note">
          <span className="qs-dot" />
          <span>
            This security is inactive.
            {security.delisted_date
              ? ` Delisted ${formatDate(security.delisted_date)}. Price history below reflects data available prior to delisting.`
              : ""}
          </span>
        </div>
      )}
    </header>
  );
}
