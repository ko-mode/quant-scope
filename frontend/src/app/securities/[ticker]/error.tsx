"use client";

export default function SecurityError({ reset }: { error: Error; reset: () => void }) {
  return (
    <main className="qs-page">
      <div className="qs-notfound">
        <p className="qs-notfound__eyebrow">SERVICE UNAVAILABLE</p>
        <p className="qs-notfound__title">Couldn&rsquo;t load this security.</p>
        <p className="qs-notfound__msg">
          The API may be unreachable. Check that the backend is running, then retry.
        </p>
        <button type="button" className="qs-btn" onClick={reset}>
          Retry
        </button>
      </div>
    </main>
  );
}
