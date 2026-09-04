import Link from "next/link";
import { notFound } from "next/navigation";

import { SecurityHeader } from "@/components/SecurityHeader";
import { SecurityTabs } from "@/components/SecurityTabs";
import { isNotFound } from "@/lib/api/client";
import { getSecurity } from "@/lib/api/securities";
import type { SecurityRead } from "@/lib/api/types";

export default async function SecurityPage({
  params,
}: {
  params: Promise<{ ticker: string }>;
}) {
  const { ticker } = await params;

  let security: SecurityRead;
  try {
    security = await getSecurity(ticker, { cache: "no-store" });
  } catch (error) {
    if (isNotFound(error)) notFound();
    throw error; // -> error.tsx (API unreachable etc.)
  }

  return (
    <main className="qs-page">
      <Link href="/" className="qs-back">
        ← All securities
      </Link>
      <SecurityHeader security={security} />
      <SecurityTabs ticker={security.ticker} />
    </main>
  );
}
