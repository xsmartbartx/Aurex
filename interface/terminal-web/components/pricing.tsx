"use client";

import { Check } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

type Plan = { code: string; name: string; audience: string; highlights: string[]; price_label: string; limits: Record<string, number> };
type Catalog = { items: Plan[]; sales_contact: string; signup_open: boolean };

const limit = (n?: number) => (n === undefined ? "—" : n >= 1_000_000 ? "Unlimited" : n.toLocaleString("en-US"));

export function PricingTable() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    fetch("/api/v1/billing/plans").then((r) => (r.ok ? r.json() : Promise.reject())).then(setCatalog, () => setFailed(true));
  }, []);
  if (failed) return <p className="mt-10 text-center text-[13px] text-faint">Plans could not be loaded. Try again shortly.</p>;
  if (!catalog) return <div className="mt-10 grid gap-3 md:grid-cols-5">{[0, 1, 2, 3, 4].map((i) => <div key={i} className="skeleton h-80" />)}</div>;
  return (
    <div className="mt-10 grid gap-3 md:grid-cols-2 xl:grid-cols-5">
      {catalog.items.map((plan) => {
        const featured = plan.code === "pro";
        const contact = plan.code === "enterprise";
        const href = contact && catalog.sales_contact
          ? (catalog.sales_contact.includes("@") ? `mailto:${catalog.sales_contact}` : catalog.sales_contact)
          : "/signup";
        return (
          <div key={plan.code} className={`flex flex-col rounded-md border p-5 ${featured ? "border-gold/60 bg-gold/5" : "border-line bg-panel"}`}>
            <div className="flex items-center justify-between">
              <h2 className="text-[16px] font-semibold text-fg">{plan.name}</h2>
              {featured && <span className="rounded-sm bg-gold px-1.5 text-[10px] font-semibold text-ink uppercase">Popular</span>}
            </div>
            <div className="num mt-2 min-h-7 text-[20px] font-semibold text-gold">{plan.price_label}</div>
            <p className="mt-1 text-[12.5px] text-faint">{plan.audience}</p>
            <ul className="mt-4 flex-1 space-y-2 text-[13px] text-dim">
              {plan.highlights.map((h) => <li key={h} className="flex gap-2"><Check size={14} className="mt-0.5 shrink-0 text-up" />{h}</li>)}
              <li className="flex gap-2"><Check size={14} className="mt-0.5 shrink-0 text-up" />{limit(plan.limits.ai_questions_per_day)} AI questions a day</li>
              <li className="flex gap-2"><Check size={14} className="mt-0.5 shrink-0 text-up" />{limit(plan.limits.members)} {plan.limits.members === 1 ? "seat" : "seats"}</li>
            </ul>
            {(contact ? catalog.sales_contact : catalog.signup_open) && (
              <Link href={href} className={`mt-5 rounded px-3 py-2 text-center text-[13px] font-medium ${featured ? "bg-gold text-ink hover:bg-[#f6c468]" : "border border-line-strong text-fg hover:bg-hover"}`}>
                {contact ? "Contact sales" : plan.code === "community" ? "Start free" : `Start with ${plan.name}`}
              </Link>
            )}
          </div>
        );
      })}
    </div>
  );
}
