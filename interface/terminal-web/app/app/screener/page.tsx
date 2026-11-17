"use client";

import { ArrowDown, ArrowUp } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FreshnessBadge } from "@/components/provenance";
import { Button, cx, Empty, ErrorNote, Input, Locked, Panel, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { fmtCompact, fmtNumber, fmtPct, fmtPrice, tone, TYPE_LABEL } from "@/lib/format";
import { useSession } from "@/lib/session";
import type { Instrument } from "@/lib/types";

type Row = {
  instrument: Instrument; last: number; unit: string; as_of: string; sector?: string | null;
  return_1m: number | null; return_3m: number | null; return_1y: number | null; volatility: number | null;
  max_drawdown: number | null; revenue?: number | null; revenue_growth?: number | null;
  net_margin?: number | null; debt_to_equity?: number | null; return_on_equity?: number | null;
};
type Result = { rows: Row[]; total: number; note: string; engine_version: string };

const COLUMNS: { key: keyof Row; label: string; title?: string; kind: "pct" | "ratio" | "money" }[] = [
  { key: "return_1m", label: "1M", kind: "pct" }, { key: "return_3m", label: "3M", kind: "pct" },
  { key: "return_1y", label: "1Y", kind: "pct" },
  { key: "volatility", label: "Vol", title: "Annualized volatility, last 12 months", kind: "pct" },
  { key: "max_drawdown", label: "Max DD", title: "Largest peak-to-trough decline, last 12 months", kind: "pct" },
  { key: "revenue", label: "Revenue", title: "Latest fiscal year", kind: "money" },
  { key: "revenue_growth", label: "Rev. growth", kind: "pct" }, { key: "net_margin", label: "Net margin", kind: "pct" },
  { key: "debt_to_equity", label: "Debt/Eq.", kind: "ratio" }, { key: "return_on_equity", label: "ROE", kind: "pct" },
];
const FILTERS: { key: string; label: string }[] = [
  { key: "return_1y", label: "1Y return %" }, { key: "volatility", label: "Volatility %" },
  { key: "revenue_growth", label: "Revenue growth %" }, { key: "net_margin", label: "Net margin %" },
  { key: "debt_to_equity", label: "Debt / equity" },
];
const TYPES = ["", "equity", "fx", "rate", "macro", "index"];

export default function ScreenerPage() {
  const router = useRouter();
  const { can, me, setActive } = useSession();
  const [type, setType] = useState("equity");
  const [bounds, setBounds] = useState<Record<string, { min: string; max: string }>>({});
  const [sort, setSort] = useState<{ key: string; descending: boolean }>({ key: "return_1y", descending: true });
  const [state, setState] = useState<{ result?: Result; error?: unknown; loading: boolean }>({ loading: true });
  const [applied, setApplied] = useState(0);
  const allowed = can("markets.screener");

  useEffect(() => {
    if (!allowed) return;
    let cancelled = false;
    const filters: Record<string, { min?: number; max?: number }> = {};
    for (const [key, value] of Object.entries(bounds)) {
      const min = value.min === "" ? undefined : Number(value.min);
      const max = value.max === "" ? undefined : Number(value.max);
      if ((min !== undefined && !Number.isNaN(min)) || (max !== undefined && !Number.isNaN(max))) filters[key] = { min, max };
    }
    api.post<Result>("/markets/screener", { types: type ? [type] : [], filters, sort: sort.key, descending: sort.descending })
      .then((result) => !cancelled && setState({ result, loading: false }),
        (error) => !cancelled && setState({ error, loading: false }));
    return () => {
      cancelled = true;
    };
    // Filters are applied on demand (button or Enter), sort and type immediately.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [allowed, type, sort, applied]);

  if (!allowed) return <div className="h-full p-2"><Panel title="Screener" className="h-full"><Locked feature="The screener" plan={me.tenant.plan_name} /></Panel></div>;
  const result = state.result;
  const cell = (row: Row, column: (typeof COLUMNS)[number]) => {
    const value = row[column.key] as number | null | undefined;
    if (column.kind === "money") return fmtCompact(value);
    if (column.kind === "ratio") return fmtNumber(value, 2);
    return column.key === "volatility" ? fmtPct(value).replace("+", "") : fmtPct(value);
  };

  return (
    <div className="h-full p-2">
      <Panel title="Screener" className="h-full" bodyClassName="flex flex-col overflow-hidden"
             footer={result && <p className="text-[11px] text-faint">{result.note} Engine {result.engine_version}.</p>}>
        <form className="flex shrink-0 flex-wrap items-end gap-3 border-b border-line px-3 py-2.5"
              onSubmit={(event) => { event.preventDefault(); setApplied((n) => n + 1); }}>
          <label className="text-[11px] text-faint">
            Asset type
            <select value={type} onChange={(event) => setType(event.target.value)}
                    className="mt-1 block h-7 rounded border border-line-strong bg-ink px-1.5 text-[12px] text-fg">
              {TYPES.map((t) => <option key={t} value={t}>{t ? TYPE_LABEL[t] : "All priced"}</option>)}
            </select>
          </label>
          {FILTERS.map((filter) => (
            <fieldset key={filter.key} className="text-[11px] text-faint">
              <legend>{filter.label}</legend>
              <div className="mt-1 flex gap-1">
                {(["min", "max"] as const).map((side) => (
                  <Input key={side} inputMode="decimal" placeholder={side} aria-label={`${filter.label} ${side}`}
                         value={bounds[filter.key]?.[side] ?? ""} className="h-7 w-16"
                         onChange={(event) => setBounds({ ...bounds, [filter.key]: { ...(bounds[filter.key] ?? { min: "", max: "" }), [side]: event.target.value } })} />
                ))}
              </div>
            </fieldset>
          ))}
          <Button type="submit" size="md" variant="primary" className="h-7">Apply</Button>
          {Object.keys(bounds).length > 0 && (
            <Button variant="ghost" className="h-7" onClick={() => { setBounds({}); setApplied((n) => n + 1); }}>Clear</Button>
          )}
          <span className="num ml-auto self-center text-[11.5px] text-faint">{result ? `${result.total} match${result.total === 1 ? "" : "es"}` : ""}</span>
        </form>
        <div className="min-h-0 flex-1 overflow-auto">
          {state.error ? <ErrorNote error={state.error} /> : !result ? <Skeleton rows={10} /> : result.rows.length === 0 ? (
            <Empty title="No instrument matches these criteria">Widen a range or clear the filters.</Empty>
          ) : (
            <table className="w-full min-w-[980px] border-collapse text-[12px]">
              <thead className="sticky top-0 bg-panel text-[10.5px] tracking-wider text-faint uppercase">
                <tr className="border-b border-line">
                  <th className="py-2 pl-3 text-left font-medium">Instrument</th>
                  <th className="text-left font-medium">Sector</th>
                  <th className="pr-3 text-right font-medium">Last</th>
                  {COLUMNS.map((column) => (
                    <th key={column.key} title={column.title} className="pr-3 text-right font-medium">
                      <button className={cx("inline-flex items-center gap-0.5 uppercase hover:text-fg", sort.key === column.key && "text-gold")}
                              onClick={() => setSort({ key: column.key, descending: sort.key === column.key ? !sort.descending : true })}>
                        {column.label}
                        {sort.key === column.key && (sort.descending ? <ArrowDown size={10} /> : <ArrowUp size={10} />)}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.rows.map((row) => (
                  <tr key={row.instrument.id} className="cursor-pointer border-b border-line hover:bg-raised"
                      onClick={() => { setActive(row.instrument.symbol); router.push(`/app/markets?symbol=${encodeURIComponent(row.instrument.symbol)}`); }}>
                    <td className="py-1.5 pl-3">
                      <div className="flex items-center gap-2">
                        <span className="num font-medium text-fg">{row.instrument.symbol}</span>
                        {row.instrument.license_class === "demonstration" && <FreshnessBadge freshness="demonstration" />}
                      </div>
                      <div className="max-w-64 truncate text-[11px] text-faint">{row.instrument.name}</div>
                    </td>
                    <td className="text-dim">{row.sector ?? "—"}</td>
                    <td className="num pr-3 text-right">{fmtPrice(row.last)}</td>
                    {COLUMNS.map((column) => (
                      <td key={column.key} className={cx("num pr-3 text-right",
                        column.kind === "pct" && !["volatility"].includes(column.key) ? tone(row[column.key] as number | null) : "text-dim")}>
                        {cell(row, column)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Panel>
    </div>
  );
}
