import Link from "next/link";

export default function SecurityNotFound() {
  return (
    <main className="qs-page">
      <div className="qs-notfound">
        <p className="qs-notfound__eyebrow">404 · UNKNOWN TICKER</p>
        <p className="qs-notfound__title">No security found for that ticker.</p>
        <p className="qs-notfound__msg">
          Check the ticker symbol, or search for a company by name.
        </p>
        <Link href="/" className="qs-btn">
          ← Back to search
        </Link>
      </div>
    </main>
  );
}
