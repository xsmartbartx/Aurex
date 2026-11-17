"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AlertsView, ChartView, InstrumentFacts, WatchlistView } from "@/components/markets";
import { Empty, Panel, Skeleton, Tabs, cx } from "@/components/ui";
import { fmtPct, fmtPrice, tone, TYPE_LABEL } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { InstrumentDetail, SearchHit } from "@/lib/types";

const GROUPS = [
  { type: "fx", label: "Currencies" }, { type: "rate", label: "Rates and yields" },
  { type: "macro", label: "Macro" }, { type: "equity", label: "Equities" }, { type: "index", label: "Indices" },
] as const;

function Browse({ active, onSelect }: { active: string; onSelect: (symbol: string) => void }) {
  const [type, setType] = useState<string>("fx");
  const { data, error } = useApi<{ items: SearchHit[] }>("/markets/instruments", { type, priced: true, limit: 200 });
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap gap-1 border-b border-line p-2">
        {GROUPS.map((group) => (
          <button key={group.type} aria-pressed={type === group.type} onClick={() => setType(group.type)}
                  className={cx("h-6 rounded border px-2 text-[11px]",
                    type === group.type ? "border-gold/50 text-gold" : "border-line-strong text-dim hover:text-fg")}>
            {group.label}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {error ? <Empty title="Could not load instruments" /> : !data ? <Skeleton rows={8} /> : data.items.length === 0 ? (
          <Empty title={`No ${TYPE_LABEL[type] ?? type} data loaded`}>Check the dataset status in DataLab.</Empty>
        ) : (
          <table className="w-full border-collapse text-[12px]">
            <tbody>
              {data.items.map(({ instrument, quote }) => (
                <tr key={instrument.id} onClick={() => onSelect(instrument.symbol)}
                    className={cx("cursor-pointer border-b border-line hover:bg-raised", instrument.symbol === active && "bg-hover")}>
                  <td className="max-w-0 py-1.5 pl-3">
                    <div className="num truncate font-medium text-fg">{instrument.symbol}</div>
                    <div className="truncate text-[11px] text-faint">{instrument.name}</div>
                  </td>
                  <td className="num w-20 py-1.5 pr-2 text-right">{fmtPrice(quote?.last)}</td>
                  <td className={cx("num w-16 py-1.5 pr-3 text-right", tone(quote?.change_pct))}>{fmtPct(quote?.change_pct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Markets() {
  const params = useSearchParams();
  const router = useRouter();
  const { active, setActive } = useSession();
  const symbol = params.get("symbol") ?? params.get("instrument") ?? active;
  const [side, setSide] = useState<"watchlist" | "browse">("watchlist");
  const [tab, setTab] = useState<"overview" | "alerts">("overview");
  const detail = useApi<InstrumentDetail>(`/markets/instruments/${encodeURIComponent(symbol)}`);

  const select = (next: string) => {
    setActive(next);
    router.replace(`/app/markets?symbol=${encodeURIComponent(next)}`);
  };

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 p-2 lg:grid-cols-[300px_minmax(0,1fr)]">
      <Panel className="max-h-72 lg:max-h-none" bodyClassName="flex flex-col overflow-hidden">
        <Tabs value={side} onChange={setSide}
              options={[{ value: "watchlist", label: "Watchlist" }, { value: "browse", label: "Browse" }]} />
        <div className="min-h-0 flex-1">
          {side === "watchlist" ? <WatchlistView activeSymbol={symbol} onSelect={select} />
            : <Browse active={symbol} onSelect={select} />}
        </div>
      </Panel>
      <div className="flex min-h-0 min-w-0 flex-col gap-2">
        <Panel className="min-h-[420px] flex-[3]" bodyClassName="overflow-hidden">
          <ChartView symbol={symbol} />
        </Panel>
        <Panel className="min-h-44 flex-1" bodyClassName="flex flex-col overflow-hidden">
          <Tabs value={tab} onChange={setTab}
                options={[{ value: "overview", label: "Instrument" }, { value: "alerts", label: "Alerts" }]} />
          <div className="min-h-0 flex-1 overflow-auto">
            {!detail.data ? <Skeleton rows={3} /> : tab === "overview" ? <InstrumentFacts detail={detail.data} />
              : <AlertsView detail={detail.data} />}
          </div>
        </Panel>
      </div>
    </div>
  );
}

export default function MarketsPage() {
  return (
    <Suspense fallback={<Skeleton rows={8} />}>
      <Markets />
    </Suspense>
  );
}
