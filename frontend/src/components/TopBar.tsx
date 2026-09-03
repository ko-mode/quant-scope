import Link from "next/link";

import { SecuritySearch } from "./SecuritySearch";

/** Sticky header for the security page: brand mark + compact search. */
export function TopBar() {
  return (
    <div className="qs-topbar">
      <Link href="/" className="qs-brand" aria-label="QuantScope home">
        <span className="qs-brand__mark" aria-hidden />
        <span className="qs-brand__word">QUANTSCOPE</span>
      </Link>
      <SecuritySearch variant="bar" />
    </div>
  );
}
