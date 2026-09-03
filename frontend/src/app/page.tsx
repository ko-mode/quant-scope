import { SecuritySearch } from "@/components/SecuritySearch";

export default function HomePage() {
  return (
    <main>
      <div className="qs-landing">
        <p className="qs-landing__eyebrow">QUANTITATIVE EQUITY RESEARCH</p>
        <h1 className="qs-landing__headline">Search a security to begin research.</h1>
        <SecuritySearch variant="hero" />
      </div>
      <p className="qs-footline">
        US exchange-listed equities · Daily adjusted price history · Source: Tiingo
      </p>
    </main>
  );
}
