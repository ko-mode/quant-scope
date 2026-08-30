import { API_BASE_URL } from "@/lib/api/client";

export default function HomePage() {
  return (
    <main className="page">
      <h1>QuantScope</h1>
      <p className="lede">
        Quantitative equity research platform. This is the Phase&nbsp;0 scaffold - the
        research dashboard is built in Phases&nbsp;1&ndash;3.
      </p>

      <section>
        <h2>Environment</h2>
        <dl>
          <dt>API base URL</dt>
          <dd>
            <code>{API_BASE_URL}</code>
          </dd>
          <dt>Health endpoint</dt>
          <dd>
            <code>{API_BASE_URL}/health</code>
          </dd>
        </dl>
      </section>
    </main>
  );
}
