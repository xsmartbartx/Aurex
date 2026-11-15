"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";
import { api, describeError } from "@/lib/api";
import { fmtAge, fmtCompact, fmtDate, fmtNumber, fmtPct, fmtPrice, fmtRatioPct, tone } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { CalendarEvent, ChartData, Dataset, InstrumentDetail, Notification } from "@/lib/types";
import { Sparkline } from "./chart";
import { ChartView, InstrumentHeader, WatchlistView } from "./markets";
import { FreshnessBadge, ProvenanceLine } from "./provenance";
import { DocumentRow, type DocumentItem } from "./intelligence";
import { Badge, Button, cx, Empty, ErrorNote, Skeleton, Stat } from "./ui";

function QuotePanel() {
  const { active } = useSession();
  const detail = useApi<InstrumentDetail>(`/markets/instruments/${encodeURIComponent(active)}`);
  const series = detail.data?.series[0];
  const chart = useApi<ChartData>(series ? `/markets/series/${series.id}/chart` : null, { range: "3M", interval: "1D" });
  if (detail.error) return <ErrorNote error={detail.error} />;
  if (!detail.data) return <Skeleton rows={3} />;
  return (
    <div className="space-y-3 p-3">
      <InstrumentHeader detail={detail.data} />
      {chart.data && (
        <>
          <Sparkline values={chart.data.points.map((p) => p.v)} width={260} height={44} />
          <div className="grid grid-cols-3 gap-3">
            <Stat label="3M return" value={fmtRatioPct(chart.data.summary.total_return)} className={tone(chart.data.summary.total_return)} />
            <Stat label="Volatility" value={fmtRatioPct(chart.data.summary.volatility).replace("+", "")} />
            <Stat label="Max drawdown" value={fmtRatioPct(chart.data.summary.max_drawdown)} className="text-down" />
          </div>
          <ProvenanceLine provenance={chart.data.provenance} />
        </>
      )}
      {!series && <p className="text-[12px] text-faint">{detail.data.price_data_note}</p>}
    </div>
  );
}

function CalendarPanel() {
  const { data, error } = useApi<{ items: CalendarEvent[] }>("/markets/calendar", { days_back: 365, days_ahead: 60 });
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton rows={5} />;
  if (data.items.length === 0) {
    return <Empty title="No events recorded">Filings and data releases appear here as they are imported.</Empty>;
  }
  return (
    <ul className="divide-y divide-line">
      {data.items.slice(0, 40).map((event) => (
        <li key={event.id} className="flex items-baseline gap-3 px-3 py-1.5 text-[12px]">
          <span className="num w-[76px] shrink-0 text-faint">{fmtDate(event.scheduled_at)}</span>
          <Badge>{event.kind}</Badge>
          <span className="min-w-0 truncate text-dim" title={event.title}>{event.title}</span>
        </li>
      ))}
    </ul>
  );
}

function DatasetsPanel() {
  const { data, error } = useApi<{ items: Dataset[] }>("/datalab/datasets");
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton rows={5} />;
  return (
    <ul className="divide-y divide-line">
      {data.items.map((dataset) => (
        <li key={dataset.id} className="flex items-center gap-2 px-3 py-1.5 text-[12px]">
          <span className={cx("h-1.5 w-1.5 shrink-0 rounded-full",
            dataset.status === "ok" ? "bg-up" : dataset.status === "failed" ? "bg-down" : "bg-warn")}
                title={dataset.status.replaceAll("_", " ")} />
          <Link href="/app/datalab" className="min-w-0 flex-1 truncate text-dim hover:text-fg">{dataset.name}</Link>
          <FreshnessBadge freshness={dataset.freshness_class} />
          <span className="num w-16 shrink-0 text-right text-faint">{fmtAge(dataset.last_success_at)}</span>
        </li>
      ))}
    </ul>
  );
}

function NotificationsPanel() {
  const { data, error } = useApi<{ items: Notification[] }>("/markets/notifications");
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton rows={4} />;
  if (data.items.length === 0) return <Empty title="No notifications">Alerts and thesis signals appear here.</Empty>;
  return (
    <ul className="divide-y divide-line">
      {data.items.map((item) => (
        <li key={item.id} className="px-3 py-2">
          <Link href={item.link || "/app"} className="block">
            <div className="flex justify-between gap-2 text-[12px]">
              <span className={item.read ? "text-dim" : "font-medium text-fg"}>{item.title}</span>
              <span className="shrink-0 text-[10.5px] text-faint">{fmtAge(item.created_at)}</span>
            </div>
            {item.body && <p className="text-[11.5px] text-faint">{item.body}</p>}
          </Link>
        </li>
      ))}
    </ul>
  );
}

type Movers = { items: { instrument: { id: string; symbol: string; name: string }; quote: { last: number | null; change_pct: number | null } | null }[] };

function MoversPanel({ type }: { type: string }) {
  const { setActive } = useSession();
  const { data, error } = useApi<Movers>("/markets/instruments", { type, priced: true, limit: 60 });
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton rows={5} />;
  const rows = data.items.filter((r) => r.quote?.change_pct !== null && r.quote?.change_pct !== undefined)
    .sort((a, b) => Math.abs(b.quote!.change_pct!) - Math.abs(a.quote!.change_pct!)).slice(0, 12);
  if (rows.length === 0) return <Empty title="No data loaded for this group" />;
  return (
    <table className="w-full border-collapse text-[12px]">
      <tbody>
        {rows.map(({ instrument, quote }) => (
          <tr key={instrument.id} onClick={() => setActive(instrument.symbol)} className="cursor-pointer border-b border-line hover:bg-raised">
            <td className="num py-1.5 pl-3 font-medium text-fg">{instrument.symbol}</td>
            <td className="max-w-0 truncate text-faint">{instrument.name}</td>
            <td className="num w-20 text-right">{fmtPrice(quote?.last)}</td>
            <td className={cx("num w-16 pr-3 text-right", tone(quote?.change_pct))}>{fmtPct(quote?.change_pct)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export type PanelSpec = { label: string; render: (config: Record<string, unknown>) => ReactNode; scroll?: boolean };

/** Panels available in a workspace. Modules add theirs through `registerPanel`. */
export const PANELS: Record<string, PanelSpec> = {
  chart: { label: "Chart", render: () => <LinkedChart />, scroll: false },
  watchlist: { label: "Watchlist", render: () => <LinkedWatchlist />, scroll: false },
  quote: { label: "Quote", render: () => <QuotePanel /> },
  movers: { label: "Largest moves", render: (config) => <MoversPanel type={String(config.type ?? "fx")} /> },
  calendar: { label: "Calendar", render: () => <CalendarPanel /> },
  datasets: { label: "Data freshness", render: () => <DatasetsPanel /> },
  notifications: { label: "Notifications", render: () => <NotificationsPanel /> },
};

export function registerPanel(type: string, spec: PanelSpec) {
  PANELS[type] = spec;
}

function LinkedChart() {
  const { active } = useSession();
  return <ChartView symbol={active} compact />;
}

function LinkedWatchlist() {
  const { active, setActive } = useSession();
  return <WatchlistView activeSymbol={active} onSelect={setActive} />;
}

function DocumentsPanel() {
  const router = useRouter();
  const { data, error } = useApi<{ items: DocumentItem[] }>("/intelligence/documents", { limit: 30 });
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton rows={5} />;
  if (data.items.length === 0) return <Empty title="No documents yet">Filings, news and uploads appear here.</Empty>;
  return (
    <ul className="divide-y divide-line">
      {data.items.map((doc) => (
        <DocumentRow key={doc.id} doc={doc} onOpen={() => router.push("/app/intelligence?tab=documents")} />
      ))}
    </ul>
  );
}

function AssistantPanel() {
  const router = useRouter();
  const { active, can } = useSession();
  const [question, setQuestion] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  if (!can("intelligence.ask")) return <Empty title="AI research is not part of this plan" />;
  async function ask(event: FormEvent) {
    event.preventDefault();
    setMessage(null);
    try {
      const created = await api.post<{ id: string }>("/intelligence/questions",
        { question: question.trim(), context: { symbol: active } });
      router.push(`/app/intelligence?answer=${created.id}`);
    } catch (failure) {
      setMessage(describeError(failure));
    }
  }
  return (
    <form onSubmit={ask} className="space-y-2 p-3">
      <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={4} maxLength={2000}
                placeholder={`Ask about ${active} or anything in the data…`} aria-label="Question"
                className="w-full resize-none rounded border border-line-strong bg-ink px-2.5 py-2 text-[12.5px] text-fg placeholder:text-faint focus:border-gold-dim focus:outline-none" />
      <div className="flex items-center gap-2">
        <Button type="submit" variant="primary" size="sm" disabled={question.trim().length < 3}>Ask with evidence</Button>
        <span className="text-[11px] text-faint">Linked to {active}</span>
      </div>
      {message && <p role="alert" className="text-[12px] text-down">{message}</p>}
    </form>
  );
}

type Fundamentals = { entity: { name: string }; years: { fiscal_year: number;
  ratios: Record<string, { value: number; unit: string; label: string }>;
  items: Record<string, { value: number; unit: string; label: string }> }[] };

function FundamentalsPanel() {
  const { active } = useSession();
  const detail = useApi<InstrumentDetail>(`/markets/instruments/${encodeURIComponent(active)}`);
  const entityId = detail.data?.instrument.entity_id;
  const data = useApi<Fundamentals>(entityId ? `/intelligence/companies/${entityId}/fundamentals` : null, { years: 3 });
  if (detail.error) return <ErrorNote error={detail.error} />;
  if (!detail.data) return <Skeleton rows={4} />;
  if (!entityId) return <Empty title={`${active} has no issuer financials`}>Choose an equity to see its statements.</Empty>;
  if (data.error) return <ErrorNote error={data.error} />;
  if (!data.data) return <Skeleton rows={6} />;
  if (data.data.years.length === 0) return <Empty title="No reported annual figures loaded" />;
  const latest = data.data.years[0];
  const rows: [string, { value: number; unit: string; label: string } | undefined][] = [
    ["revenue", latest.items.revenue], ["net_income", latest.items.net_income],
    ["revenue_growth", latest.ratios.revenue_growth], ["net_margin", latest.ratios.net_margin],
    ["free_cash_flow", latest.ratios.free_cash_flow], ["debt_to_equity", latest.ratios.debt_to_equity],
    ["interest_coverage", latest.ratios.interest_coverage], ["return_on_equity", latest.ratios.return_on_equity],
  ];
  const show = (row: { value: number; unit: string }) => row.unit === "percent" ? `${fmtNumber(row.value, 1)}%`
    : row.unit === "ratio" ? `${fmtNumber(row.value, 2)}x` : fmtCompact(row.value);
  return (
    <div className="p-3">
      <div className="mb-2 text-[12px] text-dim">{data.data.entity.name} · fiscal {latest.fiscal_year}</div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
        {rows.filter(([, row]) => row).map(([key, row]) => (
          <Stat key={key} label={row!.label} value={show(row!)} />
        ))}
      </dl>
    </div>
  );
}

registerPanel("documents", { label: "Documents", render: () => <DocumentsPanel /> });
registerPanel("assistant", { label: "Ask AUREX", render: () => <AssistantPanel /> });
registerPanel("fundamentals", { label: "Fundamentals", render: () => <FundamentalsPanel /> });
