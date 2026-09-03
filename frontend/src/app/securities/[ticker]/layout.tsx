import type { ReactNode } from "react";

import { TopBar } from "@/components/TopBar";

export default function SecurityLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <TopBar />
      {children}
    </>
  );
}
