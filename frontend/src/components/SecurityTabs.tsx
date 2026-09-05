"use client";

import { useState } from "react";

import { ComparisonPanel } from "./ComparisonPanel";
import { FactorsPanel } from "./FactorsPanel";
import { PricePanel } from "./PricePanel";
import { RiskReturnPanel } from "./RiskReturnPanel";

type Tab = "price" | "risk" | "compare" | "factors";

const FUTURE_TABS = ["Fundamentals"] as const;

/**
 * Section tabs for the security detail page. Price, Risk & Return,
 * Comparison (Phase 3A) and Factors (Phase 3B) are functional; the rest are
 * visibly disabled with a "SOON" badge and render no content - no
 * placeholder data, no fake interactivity.
 */
export function SecurityTabs({ ticker }: { ticker: string }) {
  const [tab, setTab] = useState<Tab>("price");

  return (
    <>
      <div className="qs-tabs" role="tablist" aria-label="Security sections">
        <button
          type="button"
          role="tab"
          className="qs-tab"
          aria-selected={tab === "price"}
          onClick={() => setTab("price")}
        >
          Price
        </button>
        <button
          type="button"
          role="tab"
          className="qs-tab"
          aria-selected={tab === "risk"}
          onClick={() => setTab("risk")}
        >
          Risk &amp; Return
        </button>
        <button
          type="button"
          role="tab"
          className="qs-tab"
          aria-selected={tab === "compare"}
          onClick={() => setTab("compare")}
        >
          Comparison
        </button>
        <button
          type="button"
          role="tab"
          className="qs-tab"
          aria-selected={tab === "factors"}
          onClick={() => setTab("factors")}
        >
          Factors
        </button>
        {FUTURE_TABS.map((label) => (
          <div key={label} className="qs-tab--soon" aria-disabled="true">
            {label}
            <span className="qs-tab__soon">SOON</span>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 12 }}>
        {tab === "price" && <PricePanel ticker={ticker} />}
        {tab === "risk" && <RiskReturnPanel ticker={ticker} />}
        {tab === "compare" && <ComparisonPanel ticker={ticker} />}
        {tab === "factors" && <FactorsPanel ticker={ticker} />}
      </div>
    </>
  );
}
