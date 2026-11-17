import type { Metadata } from "next";
import { PricingTable } from "@/components/pricing";
import { SitePage } from "@/components/site";

export const metadata: Metadata = { title: "Pricing", description: "AUREX plans from free to enterprise." };

export default function PricingPage() {
  return (
    <SitePage>
      <section className="mx-auto max-w-6xl px-4 py-16">
        <h1 className="text-center text-[34px] font-semibold text-fg">Plans</h1>
        <p className="mx-auto mt-2 max-w-xl text-center text-[15px] text-dim">
          Every plan runs the same build. Plans differ in what they unlock, not in how carefully the numbers are checked.
        </p>
        <PricingTable />
        <p className="mx-auto mt-10 max-w-3xl text-center text-[12px] text-faint">
          Licensed market data from commercial providers is offered on the Enterprise plan under separate agreements.
          AUREX provides analysis and simulation only; it does not execute trades or give investment advice.
        </p>
      </section>
    </SitePage>
  );
}
