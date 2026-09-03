export default function Loading() {
  return (
    <main className="qs-page" aria-busy="true" aria-label="Loading security">
      <span className="qs-back" style={{ opacity: 0 }}>
        ← All securities
      </span>
      <div className="qs-skel" style={{ height: 30, width: 160, marginBottom: 8 }} />
      <div className="qs-skel" style={{ height: 16, width: 260, marginBottom: 16 }} />
      <div className="qs-skel" style={{ height: 480, border: "1px solid var(--border)" }} />
    </main>
  );
}
