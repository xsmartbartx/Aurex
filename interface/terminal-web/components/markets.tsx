"use client";

import { Download, Pin, Plus, Trash2, X } from "lucide-react";
import { useState } from "react";
import { api, API, describeError } from "@/lib/api";
import { fmtDate, fmtNumber, fmtPct, fmtPrice, fmtRatioPct, fmtSigned, tone, TYPE_LABEL } from "@/lib/format";
import { useApi, useDebounced, useStored } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { ChartData, InstrumentDetail, SearchHit, Watchlist } from "@/lib/types";
import { PriceChart } from "./chart";
import { FreshnessBadge, ProvenanceLine, StatusBadge } from "./provenance";
import { Badge, Button, cx, Empty, ErrorNote, Input, Segmented, Skeleton, Stat } from "./ui";

const RANGES = ["1M", "3M", "6M", "YTD", "1Y", "3Y", "5Y", "MAX"] as const;
const INTERVALS = ["1D", "1W", "1M"] as const;
const OVERLAYS = [
  { id: "sma:20", label: "SMA 20" }, { id: "sma:50", label: "SMA 50" }, { id: "ema:20", label: "EMA 20" },
  { id: "bollinger:20", label: "Bollinger" },
] as const;

/** Header with the last value, its change and where the number comes from. */
export function InstrumentHeader({ detail }: { detail: InstrumentDetail }) {
  const { instrument, quote, entity } = detail;
  return (
    <div className="flex flex-wrap items-end gap-x-5 gap-y-1">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <h1 className="num text-[17px] font-semibold tracking-tight">{instrument.symbol}</h1>
          <Badge>{TYPE_LABEL[instrument.type] ?? instrument.type}</Badge>
          {quote && <FreshnessBadge freshness={quote.freshness_class} />}
          {quote && <StatusBadge status={quote.status} />}
        </div>
        <div className="truncate text-[12px] text-dim">
          {instrument.name}
          {instrument.venue ? ` · ${instrument.venue}` : ""}
          {entity?.sector ? ` · ${entity.sector}` : ""}
        </div>
      </div>
      {quote && (
        <div className="flex items-baseline gap-3">
          <span className="num text-[22px] leading-none font-semibold">{fmtPrice(quote.last)}</span>
          <span className={cx("num text-[13px]", tone(quote.change))}>
            {fmtSigned(quote.change, Math.abs(quote.last ?? 0) < 10 ? 4 : 2)} ({fmtPct(quote.change_pct)})
          </span>
          <span className="text-[11px] text-faint">
            {quote.unit} · {fmtDate(quote.ref_time)}
          </span>
        </div>
      )}
    </div>
  );
}

/** Chart with interval, range and indicator controls. Every figure below it comes from the engine. */
export function ChartView({ symbol, compact = false }: { symbol: string; compact?: boolean }) {
  const { can } = useSession();
  const [range, setRange] = useStored<(typeof RANGES)[number]>("chart-range", "1Y");
  const [interval, setInterval] = useStored<(typeof INTERVALS)[number]>("chart-interval", "1D");
  const [mode, setMode] = useStored<"candles" | "line">("chart-mode", "candles");
  const [overlays, setOverlays] = useStored<string[]>("chart-overlays", []);
  const detail = useApi<InstrumentDetail>(symbol ? `/markets/instruments/${encodeURIComponent(symbol)}` : null);
  const series = detail.data?.series[0];
  const chart = useApi<ChartData>(series ? `/markets/series/${series.id}/chart` : null,
    { range, interval, indicator: overlays });
  const data = chart.data ?? (chart.previous?.series.id === series?.id ? chart.previous : undefined);

  if (detail.error) return <ErrorNote error={detail.error} onRetry={detail.reload} />;
  if (!detail.data) return <Skeleton rows={6} />;
  const toggle = (id: string) => setOverlays(overlays.includes(id) ? overlays.filter((o) => o !== id) : [...overlays, id]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className={cx("shrink-0 border-b border-line", compact ? "px-3 py-2" : "px-4 py-3")}>
        <InstrumentHeader detail={detail.data} />
      </div>
      {!series ? (
        <Empty title="No licensed price series for this instrument">
          {detail.data.price_data_note} Open Intelligence for the company&apos;s filings and reported figures.
        </Empty>
      ) : (
        <>
          <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-line px-3 py-1.5">
            <Segmented label="Range" value={range} options={RANGES} onChange={setRange} />
            <Segmented label="Interval" value={interval} options={INTERVALS} onChange={setInterval} />
            {series.has_ohlc && (
              <Segmented label="Chart type" value={mode} onChange={setMode}
                         options={[{ value: "candles", label: "Candles" }, { value: "line", label: "Line" }]} />
            )}
            {!compact && (
              <div className="flex flex-wrap items-center gap-1">
                {OVERLAYS.map((overlay) => (
                  <button
                    key={overlay.id}
                    aria-pressed={overlays.includes(overlay.id)}
                    onClick={() => toggle(overlay.id)}
                    className={cx("num h-6 rounded border px-2 text-[11px]",
                      overlays.includes(overlay.id) ? "border-info/50 text-info" : "border-line-strong text-dim hover:text-fg")}
                  >
                    {overlay.label}
                  </button>
                ))}
              </div>
            )}
            {data?.provenance.export_allowed && can("export.data") && (
              <a
                href={`${API}/markets/series/${series.id}/export?range=${range}`}
                className="ml-auto inline-flex h-6 items-center gap-1 rounded px-2 text-[11px] text-dim hover:bg-hover hover:text-fg"
                title="Download the series as CSV with its source and license"
              >
                <Download size={12} /> CSV
              </a>
            )}
          </div>
          <div className={cx("relative min-h-0 flex-1", compact ? "min-h-40" : "min-h-64")}>
            {chart.error ? (
              <ErrorNote error={chart.error} onRetry={chart.reload} />
            ) : !data ? (
              <Skeleton rows={8} />
            ) : data.points.length === 0 ? (
              <Empty title="No observations in this range">Choose a longer range, or check the dataset in DataLab.</Empty>
            ) : (
              <div className={cx("absolute inset-0 p-1", chart.loading && "opacity-60")}>
                <PriceChart points={data.points} indicators={data.indicators} mode={mode} />
              </div>
            )}
          </div>
          {data && (
            <div className="shrink-0 border-t border-line">
              {!compact && (
                <div className="grid grid-cols-3 gap-x-4 gap-y-2 px-4 py-2.5 sm:grid-cols-6">
                  <Stat label={`Return ${data.range}`} value={fmtRatioPct(data.summary.total_return)}
                        className={tone(data.summary.total_return)} />
                  <Stat label="Annualized" value={fmtRatioPct(data.summary.cagr)} className={tone(data.summary.cagr)}
                        title="Compound annual growth rate over the visible range" />
                  <Stat label="Volatility" value={fmtRatioPct(data.summary.volatility).replace("+", "")}
                        title="Annualized standard deviation of returns" />
                  <Stat label="Max drawdown" value={fmtRatioPct(data.summary.max_drawdown)} className="text-down" />
                  <Stat label="High" value={fmtPrice(data.summary.high)} />
                  <Stat label="Low" value={fmtPrice(data.summary.low)} />
                </div>
              )}
              <div className="border-t border-line px-3 py-1.5">
                <ProvenanceLine provenance={data.provenance} asOf={data.as_of} />
                {data.quality.suspect > 0 && (
                  <div className="mt-1 text-[11px] text-warn">
                    {data.quality.suspect} value{data.quality.suspect > 1 ? "s" : ""} in this range failed a quality
                    rule and {data.quality.suspect > 1 ? "are" : "is"} marked suspect.
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** Watchlists with live figures. Pinned instruments stay on top. */
export function WatchlistView({ activeSymbol, onSelect }: { activeSymbol?: string; onSelect: (symbol: string) => void }) {
  const { atLeast } = useSession();
  const lists = useApi<{ items: Watchlist[] }>("/markets/watchlists");
  const [chosen, setChosen] = useStored<string | null>("watchlist", null);
  const [adding, setAdding] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const term = useDebounced(adding.trim(), 180);
  const suggestions = useApi<{ items: SearchHit[] }>(term ? "/markets/instruments" : null, { q: term, limit: 6 });
  const all = (lists.data ?? lists.previous)?.items ?? [];
  const list = all.find((w) => w.id === chosen) ?? all[0];
  const canEdit = atLeast("analyst") && !!list?.owner;

  async function act(action: () => Promise<unknown>) {
    setMessage(null);
    try {
      await action();
      lists.reload();
    } catch (error) {
      setMessage(describeError(error));
    }
  }

  if (lists.error) return <ErrorNote error={lists.error} onRetry={lists.reload} />;
  if (!list) return <Skeleton rows={6} />;
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-1.5 border-b border-line px-2 py-1.5">
        <select
          aria-label="Watchlist"
          value={list.id}
          onChange={(event) => setChosen(event.target.value)}
          className="h-7 min-w-0 flex-1 rounded border border-line-strong bg-ink px-1.5 text-[12px] text-fg"
        >
          {all.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}{w.shared ? " (shared)" : ""}
            </option>
          ))}
        </select>
        {atLeast("analyst") && (
          <Button size="sm" variant="ghost" title="New watchlist" onClick={() => {
            const name = window.prompt("Name of the new watchlist");
            if (name?.trim()) void act(() => api.post<Watchlist>("/markets/watchlists", { name: name.trim() })
              .then((created) => setChosen(created.id)));
          }}>
            <Plus size={13} />
          </Button>
        )}
      </div>
      {canEdit && (
        <div className="relative shrink-0 border-b border-line p-2">
          <Input value={adding} onChange={(event) => setAdding(event.target.value)} placeholder="Add symbol or name"
                 aria-label="Add an instrument" className="h-7" />
          {term && (suggestions.data?.items.length ?? 0) > 0 && (
            <ul className="absolute inset-x-2 top-10 z-20 rounded border border-line-strong bg-raised py-1 shadow-lg shadow-black/40">
              {suggestions.data!.items.map((hit) => (
                <li key={hit.instrument.id}>
                  <button
                    className="flex h-7 w-full items-center gap-2 px-2 text-left text-[12px] hover:bg-hover"
                    onClick={() => {
                      setAdding("");
                      void act(() => api.post(`/markets/watchlists/${list.id}/items`, { instrument: hit.instrument.symbol }));
                    }}
                  >
                    <span className="num w-20 shrink-0 truncate text-fg">{hit.instrument.symbol}</span>
                    <span className="truncate text-dim">{hit.instrument.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {message && <div role="alert" className="shrink-0 px-3 py-1.5 text-[11.5px] text-down">{message}</div>}
      <div className="min-h-0 flex-1 overflow-auto">
        {list.items.length === 0 ? (
          <Empty title="This watchlist is empty">
            {canEdit ? "Type a symbol above, or press ⌘K to search." : "Its owner has not added instruments yet."}
          </Empty>
        ) : (
          <table className="w-full border-collapse text-[12px]">
            <tbody>
              {list.items.map((item) => (
                <tr
                  key={item.id}
                  onClick={() => onSelect(item.instrument.symbol)}
                  className={cx("group cursor-pointer border-b border-line hover:bg-raised",
                    item.instrument.symbol === activeSymbol && "bg-hover")}
                >
                  <td className="max-w-0 py-1.5 pl-3">
                    <div className="flex items-center gap-1.5">
                      {item.pinned && <Pin size={10} className="shrink-0 text-gold" />}
                      <span className="num truncate font-medium text-fg">{item.instrument.symbol}</span>
                    </div>
                    <div className="truncate text-[11px] text-faint">{item.instrument.name}</div>
                  </td>
                  <td className="num w-20 py-1.5 pr-2 text-right">
                    {item.quote ? fmtPrice(item.quote.last) : <span className="text-[10.5px] text-faint">no price</span>}
                    {item.quote?.freshness_class === "demonstration" && (
                      <div className="text-[9.5px] tracking-wide text-demo uppercase">demo</div>
                    )}
                  </td>
                  <td className={cx("num w-16 py-1.5 pr-2 text-right", tone(item.quote?.change_pct))}>
                    {item.quote ? fmtPct(item.quote.change_pct) : ""}
                  </td>
                  {canEdit && (
                    <td className="w-12 pr-1.5 text-right opacity-0 group-hover:opacity-100 focus-within:opacity-100">
                      <button
                        title={item.pinned ? "Unpin" : "Pin to top"}
                        className="p-1 text-faint hover:text-gold"
                        onClick={(event) => {
                          event.stopPropagation();
                          void act(() => api.patch(`/markets/watchlists/${list.id}/items/${item.id}`, { pinned: !item.pinned }));
                        }}
                      >
                        <Pin size={12} />
                      </button>
                      <button
                        title="Remove"
                        className="p-1 text-faint hover:text-down"
                        onClick={(event) => {
                          event.stopPropagation();
                          void act(() => api.delete(`/markets/watchlists/${list.id}/items/${item.id}`));
                        }}
                      >
                        <X size={12} />
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

type Alert = {
  id: string; condition: string; threshold: number; note: string; active: boolean;
  last_triggered_at: string | null; instrument_id: string | null; series: { name: string; unit: string };
};

const CONDITION_LABEL: Record<string, string> = {
  above: "rises above", below: "falls below", change_pct_above: "gains more than (%)",
  change_pct_below: "loses more than (%)",
};

/** Price alerts for one instrument. Rules are checked after each import of new data. */
export function AlertsView({ detail }: { detail: InstrumentDetail }) {
  const { can, me } = useSession();
  const alerts = useApi<{ items: Alert[] }>(can("markets.alerts") ? "/markets/alerts" : null);
  const [condition, setCondition] = useState("above");
  const [threshold, setThreshold] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  if (!can("markets.alerts")) {
    return <Empty title={`Alerts are not part of the ${me.tenant.plan_name} plan`}>Alerts start with the Pro plan.</Empty>;
  }
  if (!detail.series.length) return <Empty title="Alerts need a price series" />;
  const mine = (alerts.data?.items ?? []).filter((a) => a.instrument_id === detail.instrument.id);

  async function create() {
    setMessage(null);
    try {
      await api.post("/markets/alerts", { instrument: detail.instrument.symbol, condition, threshold });
      setThreshold("");
      alerts.reload();
    } catch (error) {
      setMessage(describeError(error));
    }
  }

  return (
    <div className="p-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="text-[11.5px] text-dim">
          Notify me when {detail.instrument.symbol}
          <select value={condition} onChange={(event) => setCondition(event.target.value)}
                  className="mt-1 block h-8 rounded border border-line-strong bg-ink px-2 text-[12.5px] text-fg">
            {Object.entries(CONDITION_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </label>
        <Input value={threshold} onChange={(event) => setThreshold(event.target.value)} inputMode="decimal"
               placeholder={detail.quote ? fmtPrice(detail.quote.last) : "Value"} aria-label="Threshold" className="w-28" />
        <Button variant="primary" disabled={!threshold || Number.isNaN(Number(threshold))} onClick={create}>
          Add alert
        </Button>
      </div>
      {message && <p role="alert" className="mt-2 text-[12px] text-down">{message}</p>}
      <ul className="mt-3 divide-y divide-line">
        {mine.length === 0 && <li className="py-3 text-[12px] text-faint">No alerts on this instrument.</li>}
        {mine.map((alert) => (
          <li key={alert.id} className="flex items-center gap-3 py-2 text-[12.5px]">
            <span className={alert.active ? "text-fg" : "text-faint line-through"}>
              {CONDITION_LABEL[alert.condition]} <span className="num">{fmtNumber(alert.threshold, 4)}</span>
            </span>
            <span className="text-[11px] text-faint">
              {alert.last_triggered_at ? `last fired ${fmtDate(alert.last_triggered_at)}` : "not fired yet"}
            </span>
            <button className="ml-auto text-[11.5px] text-dim hover:text-fg"
                    onClick={() => api.patch(`/markets/alerts/${alert.id}`, { active: !alert.active }).then(alerts.reload)}>
              {alert.active ? "Pause" : "Resume"}
            </button>
            <button aria-label="Delete alert" className="text-faint hover:text-down"
                    onClick={() => api.delete(`/markets/alerts/${alert.id}`).then(alerts.reload)}>
              <Trash2 size={13} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function InstrumentFacts({ detail }: { detail: InstrumentDetail }) {
  const { instrument, entity, series, quote } = detail;
  const rows: [string, string][] = [
    ["Type", TYPE_LABEL[instrument.type] ?? instrument.type],
    ["Currency", instrument.currency ?? "—"],
    ["Venue", instrument.venue ?? "—"],
    ["Status", instrument.status],
    ["Dataset", instrument.dataset],
    ["License class", instrument.license_class.replaceAll("_", " ")],
  ];
  if (series[0]) rows.push(["Series", `${series[0].code} · ${series[0].unit} · frequency ${series[0].frequency}`]);
  if (quote) rows.push(["Previous value", fmtPrice(quote.previous)]);
  if (entity) {
    rows.push(["Issuer", entity.name]);
    if (entity.industry) rows.push(["Industry", entity.industry]);
    if (entity.cik) rows.push(["SEC CIK", entity.cik]);
  }
  return (
    <dl className="grid grid-cols-1 gap-x-8 gap-y-1.5 p-3 text-[12.5px] sm:grid-cols-2">
      {rows.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-4 border-b border-line py-1">
          <dt className="text-faint">{label}</dt>
          <dd className="truncate text-right text-fg">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
