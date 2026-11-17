"use client";

import { AlertTriangle, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { LineChart } from "@/components/chart";
import { Badge, Button, cx, Empty, ErrorNote, Field, Input, Locked, Modal, Panel, Skeleton, Stat, Tabs } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import { fmtDate, fmtNumber, fmtPct, fmtPrice, tone } from "@/lib/format";
import { useApi, useStored } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Shock = { target_type: string; target: string; shock_pct: number };
type Preset = { name: string; description: string; shocks: Shock[] };
type PortfolioItem = { id: string; name: string; base_currency: string; own: boolean; limits: Record<string, number> };
type Position = {
  instrument: string; name?: string; quantity: number; currency: string; price: number | null; priced: boolean;
  value: number; cost: number; unrealized: number; unrealized_pct: number | null; realized: number; weight: number;
  sector?: string | null; type?: string; license_class?: string;
};
type Group = { name: string; value: number; weight: number };
type Analytics = {
  empty: boolean; gaps: string[]; as_of?: string; base_currency: string; value: number; net_invested: number;
  result: number; positions: Position[]; cash: { currency: string; amount: number; value: number }[];
  performance: {
    total_return?: number; annualized_return?: number | null; volatility?: number; max_drawdown?: number;
    sharpe?: number | null; method?: string; engine_version?: string;
    benchmark?: { total_return?: number; excess_return?: number; beta?: number | null; note?: string };
  };
  exposures: { sector: Group[]; currency: Group[]; type: Group[];
    concentration: { hhi: number; effective_positions: number | null; largest_weight: number | null; top5_weight: number | null } };
  breaches: { limit: string; subject: string; value: number; threshold: number }[];
  history: { t: string; value: number; index: number; benchmark?: number }[];
  sources: { dataset: string; attribution: string; license_class: string }[];
};
type Txn = { id: string; type: string; executed_on: string; symbol: string | null; quantity: number; price: number;
  fees: number; currency: string; note: string };
type ScenarioResult = { before: number; after: number; impact: number; impact_pct: number | null; label: string;
  positions: { instrument: string; before: number; after: number; impact: number; rule: string }[] };

function Bars({ title, rows, currency }: { title: string; rows: Group[]; currency: string }) {
  return (
    <div>
      <div className="mb-1.5 text-[10.5px] tracking-wider text-faint uppercase">{title}</div>
      <ul className="space-y-1">
        {rows.slice(0, 8).map((row) => (
          <li key={row.name} className="text-[11.5px]" title={`${currency} ${fmtNumber(row.value, 0)}`}>
            <div className="flex justify-between gap-2"><span className="truncate text-dim">{row.name}</span>
              <span className="num text-fg">{fmtNumber(row.weight, 1)}%</span></div>
            <div className="mt-0.5 h-1 rounded bg-raised">
              <div className="h-1 rounded bg-gold/70" style={{ width: `${Math.min(100, Math.max(0, row.weight))}%` }} />
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Scenarios({ portfolioId, presets, base }: { portfolioId: string; presets: Record<string, Preset>; base: string }) {
  const { can, me } = useSession();
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [custom, setCustom] = useState<Shock>({ target_type: "all", target: "", shock_pct: -10 });
  if (!can("portfolio.scenarios")) return <Locked feature="Scenario analysis" plan={me.tenant.plan_name} />;

  async function run(shocks: Shock[]) {
    setMessage(null);
    try {
      setResult(await api.post<ScenarioResult>(`/portfolios/${portfolioId}/scenario`, { shocks }));
    } catch (failure) {
      setMessage(describeError(failure));
    }
  }

  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap gap-1.5">
        {Object.entries(presets).map(([key, preset]) => (
          <Button key={key} size="sm" title={preset.description} onClick={() => run(preset.shocks)}>{preset.name}</Button>
        ))}
      </div>
      <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); void run([custom]); }}>
        <label className="text-[11px] text-faint">Shock
          <select value={custom.target_type} onChange={(event) => setCustom({ ...custom, target_type: event.target.value })}
                  className="mt-1 block h-7 rounded border border-line-strong bg-ink px-1.5 text-[12px] text-fg">
            {["all", "instrument", "sector", "type", "currency"].map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </label>
        {custom.target_type !== "all" && (
          <Input aria-label="Target" placeholder={{ instrument: "ORCA.DEMO", sector: "Utilities", type: "equity", currency: "USD" }[custom.target_type]}
                 value={custom.target} onChange={(event) => setCustom({ ...custom, target: event.target.value })} className="h-7 w-32" />
        )}
        <Input aria-label="Shock in percent" inputMode="decimal" value={String(custom.shock_pct)} className="h-7 w-20"
               onChange={(event) => setCustom({ ...custom, shock_pct: Number(event.target.value) || 0 })} />
        <span className="pb-1.5 text-[11px] text-faint">%</span>
        <Button type="submit" size="sm" variant="primary">Run</Button>
      </form>
      {message && <p role="alert" className="text-[12px] text-down">{message}</p>}
      {result && (
        <div>
          <div className="flex flex-wrap items-baseline gap-4">
            <Stat label="Impact" value={`${base} ${fmtNumber(result.impact, 0)}`} className={tone(result.impact)} />
            <Stat label="Impact %" value={fmtPct(result.impact_pct)} className={tone(result.impact_pct)} />
            <Stat label="Value after" value={`${base} ${fmtNumber(result.after, 0)}`} />
          </div>
          <table className="mt-2 w-full text-[11.5px]">
            <tbody>
              {result.positions.map((row) => (
                <tr key={row.instrument} className="border-b border-line/60">
                  <td className="num py-1 text-fg">{row.instrument}</td>
                  <td className="text-faint">{row.rule || "no shock"}</td>
                  <td className={cx("num text-right", tone(row.impact))}>{fmtNumber(row.impact, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1.5 text-[11px] text-faint">{result.label}</p>
        </div>
      )}
    </div>
  );
}

function Transactions({ portfolioId, onChange }: { portfolioId: string; onChange: () => void }) {
  const { atLeast } = useSession();
  const list = useApi<{ items: Txn[] }>(`/portfolios/${portfolioId}/transactions`);
  const [adding, setAdding] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [kind, setKind] = useState("buy");

  async function act(action: () => Promise<unknown>, done?: string) {
    setMessage(null);
    try {
      await action();
      list.reload();
      onChange();
      if (done) setMessage(done);
    } catch (failure) {
      setMessage(describeError(failure));
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    await act(() => api.post(`/portfolios/${portfolioId}/transactions`, {
      type: kind, executed_on: value("date"), instrument: value("instrument") || null,
      quantity: value("quantity") || "1", price: value("price"), fees: value("fees") || "0",
      currency: value("currency") || null, note: value("note"),
    }));
    setAdding(false);
  }

  const trade = kind === "buy" || kind === "sell";
  return (
    <div>
      {atLeast("analyst") && (
        <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
          <Button size="sm" onClick={() => setAdding(true)}><Plus size={11} /> Add transaction</Button>
          <label className="inline-flex h-6 cursor-pointer items-center gap-1 rounded border border-line-strong bg-raised px-2 text-[11.5px] text-fg hover:bg-hover">
            <Upload size={11} /> Import CSV
            <input type="file" accept=".csv,text/csv" className="hidden" onChange={(event) => {
              const file = event.target.files?.[0];
              event.target.value = "";
              if (!file) return;
              const form = new FormData();
              form.append("file", file);
              void act(() => api.upload<{ added: number }>(`/portfolios/${portfolioId}/import`, form), "Imported.");
            }} />
          </label>
          <span className="text-[11px] text-faint">CSV columns: date, type, symbol, quantity, price, fees, currency, note</span>
        </div>
      )}
      {message && <p role="status" className="px-3 py-1.5 text-[11.5px] text-dim">{message}</p>}
      {list.error ? <ErrorNote error={list.error} /> : !list.data ? <Skeleton rows={5} /> : list.data.items.length === 0 ? (
        <Empty title="No transactions" />
      ) : (
        <table className="w-full min-w-[640px] text-[12px]">
          <thead className="text-left text-[10.5px] tracking-wider text-faint uppercase">
            <tr className="border-b border-line">
              <th className="py-1.5 pl-3 font-medium">Date</th><th className="font-medium">Type</th>
              <th className="font-medium">Instrument</th><th className="text-right font-medium">Quantity</th>
              <th className="text-right font-medium">Price</th><th className="text-right font-medium">Fees</th>
              <th className="pl-3 font-medium">Note</th><th />
            </tr>
          </thead>
          <tbody>
            {list.data.items.map((row) => (
              <tr key={row.id} className="border-b border-line/60">
                <td className="num py-1 pl-3 text-dim">{fmtDate(row.executed_on)}</td>
                <td className="text-fg">{row.type}</td>
                <td className="num text-fg">{row.symbol ?? "—"}</td>
                <td className="num text-right">{row.type === "buy" || row.type === "sell" ? fmtNumber(row.quantity, 4).replace(/\.?0+$/, "") : ""}</td>
                <td className="num text-right">{row.currency} {fmtPrice(row.price)}</td>
                <td className="num text-right text-dim">{row.fees ? fmtNumber(row.fees, 2) : ""}</td>
                <td className="max-w-48 truncate pl-3 text-faint">{row.note}</td>
                <td className="pr-2 text-right">
                  {atLeast("analyst") && (
                    <button aria-label="Delete transaction" className="text-faint hover:text-down"
                            onClick={() => act(() => api.delete(`/portfolios/${portfolioId}/transactions/${row.id}`))}>
                      <Trash2 size={12} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <Modal open={adding} onClose={() => setAdding(false)} title="Add transaction">
        <form onSubmit={submit} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Type">
              <select value={kind} onChange={(event) => setKind(event.target.value)}
                      className="h-8 w-full rounded border border-line-strong bg-ink px-2 text-[12.5px] text-fg">
                {["buy", "sell", "deposit", "withdrawal", "dividend", "fee", "interest"].map((t) => <option key={t}>{t}</option>)}
              </select>
            </Field>
            <Field label="Date"><Input name="date" type="date" required defaultValue={new Date().toISOString().slice(0, 10)} /></Field>
            {trade && <Field label="Instrument"><Input name="instrument" required placeholder="ORCA.DEMO" /></Field>}
            {trade && <Field label="Quantity"><Input name="quantity" required inputMode="decimal" /></Field>}
            <Field label={trade ? "Price per unit" : "Amount"}><Input name="price" required inputMode="decimal" /></Field>
            {trade && <Field label="Fees"><Input name="fees" inputMode="decimal" defaultValue="0" /></Field>}
            <Field label="Currency" hint={trade ? "Defaults to the instrument's currency" : undefined}>
              <Input name="currency" maxLength={3} placeholder={trade ? "" : "EUR"} required={!trade} />
            </Field>
            <Field label="Note"><Input name="note" maxLength={200} /></Field>
          </div>
          {message && <p role="alert" className="text-[12px] text-down">{message}</p>}
          <div className="flex justify-end"><Button type="submit" variant="primary">Add</Button></div>
        </form>
      </Modal>
    </div>
  );
}

function PortfolioView({ item, presets, onDeleted }: { item: PortfolioItem; presets: Record<string, Preset>; onDeleted: () => void }) {
  const { atLeast } = useSession();
  const { data, error, reload } = useApi<Analytics>(`/portfolios/${item.id}/analytics`);
  const [tab, setTab] = useState<"holdings" | "transactions">("holdings");
  const [side, setSide] = useState<"exposure" | "scenarios">("exposure");
  const series = useMemo(() => {
    if (!data || data.empty) return [];
    const lines = [{ name: "Portfolio", points: data.history.map((p) => ({ t: p.t, v: p.index - 100 })) }];
    if (data.history.some((p) => p.benchmark !== undefined)) {
      lines.push({ name: "Benchmark", points: data.history.filter((p) => p.benchmark !== undefined)
        .map((p) => ({ t: p.t, v: (p.benchmark as number) - 100 })) });
    }
    return lines;
  }, [data]);

  if (error) return <ErrorNote error={error} onRetry={reload} />;
  if (!data) return <Skeleton rows={10} />;
  const base = data.base_currency ?? item.base_currency;
  const perf = data.performance ?? {};

  return (
    <div className="flex min-h-0 flex-col gap-2">
      {data.empty ? (
        <Panel title={item.name} actions={atLeast("analyst") && <Button size="sm" variant="ghost" onClick={async () => {
          if (window.confirm(`Delete "${item.name}" and its transactions?`)) {
            await api.delete(`/portfolios/${item.id}`);
            onDeleted();
          }
        }}><Trash2 size={11} /> Delete</Button>}>
          <Transactions portfolioId={item.id} onChange={reload} />
        </Panel>
      ) : (
        <>
          <Panel>
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 px-4 py-3 sm:grid-cols-4 xl:grid-cols-8">
              <Stat label={`Value (${base})`} value={fmtNumber(data.value, 0)} />
              <Stat label="Net invested" value={fmtNumber(data.net_invested, 0)} />
              <Stat label="Result" value={fmtNumber(data.result, 0)} className={tone(data.result)} />
              <Stat label="Time-weighted" value={fmtPct(perf.total_return)} className={tone(perf.total_return)} title={perf.method} />
              <Stat label="Annualized" value={fmtPct(perf.annualized_return)} className={tone(perf.annualized_return)} />
              <Stat label="Volatility" value={`${fmtNumber(perf.volatility, 1)}%`} />
              <Stat label="Max drawdown" value={fmtPct(perf.max_drawdown)} className="text-down" />
              <Stat label="vs benchmark" value={perf.benchmark?.excess_return !== undefined ? fmtPct(perf.benchmark.excess_return) : "—"}
                    className={tone(perf.benchmark?.excess_return)}
                    title={perf.benchmark?.beta != null ? `Beta ${fmtNumber(perf.benchmark.beta, 2)}` : perf.benchmark?.note} />
            </div>
            {(data.breaches.length > 0 || data.gaps.length > 0) && (
              <div className="space-y-1 border-t border-line px-4 py-2 text-[11.5px]">
                {data.breaches.map((b) => (
                  <div key={`${b.limit}-${b.subject}`} className="flex items-center gap-1.5 text-down">
                    <AlertTriangle size={12} /> {b.subject} at {fmtNumber(b.value, 1)}% breaches {b.limit.replaceAll("_", " ")} of {b.threshold}%
                  </div>
                ))}
                {data.gaps.map((gap) => <div key={gap} className="text-faint">{gap}</div>)}
              </div>
            )}
          </Panel>
          <div className="grid min-h-0 grid-cols-1 gap-2 xl:grid-cols-[minmax(0,1fr)_360px]">
            <div className="flex min-h-0 flex-col gap-2">
              <Panel title="Time-weighted return vs benchmark" className="h-72" bodyClassName="overflow-hidden p-1">
                <LineChart series={series} percent />
              </Panel>
              <Panel bodyClassName="overflow-auto">
                <Tabs value={tab} onChange={setTab} options={[{ value: "holdings", label: "Holdings", count: data.positions.filter((p) => p.quantity).length },
                  { value: "transactions", label: "Transactions" }]} />
                {tab === "holdings" ? (
                  <table className="w-full min-w-[720px] text-[12px]">
                    <thead className="text-left text-[10.5px] tracking-wider text-faint uppercase">
                      <tr className="border-b border-line">
                        <th className="py-1.5 pl-3 font-medium">Instrument</th><th className="font-medium">Sector</th>
                        <th className="text-right font-medium">Quantity</th><th className="text-right font-medium">Price</th>
                        <th className="text-right font-medium">Value {base}</th><th className="text-right font-medium">Weight</th>
                        <th className="pr-3 text-right font-medium">Unrealized</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.positions.filter((p) => p.quantity).map((p) => (
                        <tr key={p.instrument} className="border-b border-line/60">
                          <td className="py-1.5 pl-3"><div className="num font-medium text-fg">{p.instrument}</div>
                            <div className="max-w-56 truncate text-[11px] text-faint">{p.name}</div></td>
                          <td className="text-dim">{p.sector ?? "—"}</td>
                          <td className="num text-right">{fmtNumber(p.quantity, 2).replace(/\.00$/, "")}</td>
                          <td className="num text-right">{p.priced ? `${p.currency} ${fmtPrice(p.price)}` : <Badge tone="gold">at cost</Badge>}</td>
                          <td className="num text-right text-fg">{fmtNumber(p.value, 0)}</td>
                          <td className="num text-right">{fmtNumber(p.weight, 1)}%</td>
                          <td className={cx("num pr-3 text-right", tone(p.unrealized))}>{fmtNumber(p.unrealized, 0)} <span className="text-[10.5px]">({fmtPct(p.unrealized_pct, 1)})</span></td>
                        </tr>
                      ))}
                      {data.cash.map((c) => (
                        <tr key={c.currency} className="border-b border-line/60 text-dim">
                          <td className="py-1.5 pl-3">Cash {c.currency}</td><td>Cash</td><td /><td />
                          <td className="num text-right">{fmtNumber(c.value, 0)}</td>
                          <td className="num text-right">{data.value ? fmtNumber(c.value / data.value * 100, 1) : "—"}%</td><td />
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <Transactions portfolioId={item.id} onChange={reload} />}
              </Panel>
            </div>
            <Panel bodyClassName="overflow-auto">
              <Tabs value={side} onChange={setSide} options={[{ value: "exposure", label: "Exposure" }, { value: "scenarios", label: "Scenarios" }]} />
              {side === "exposure" ? (
                <div className="space-y-4 p-3">
                  <div className="grid grid-cols-2 gap-3">
                    <Stat label="Largest position" value={`${fmtNumber(data.exposures.concentration.largest_weight, 1)}%`} />
                    <Stat label="Effective positions" value={fmtNumber(data.exposures.concentration.effective_positions, 1)}
                          title="1 / Herfindahl-Hirschman index of position weights" />
                  </div>
                  <Bars title="Sector" rows={data.exposures.sector} currency={base} />
                  <Bars title="Currency" rows={data.exposures.currency} currency={base} />
                  <Bars title="Asset type" rows={data.exposures.type} currency={base} />
                  <p className="text-[11px] text-faint">
                    As of {fmtDate(data.as_of)} · engine {perf.engine_version} ·{" "}
                    {data.sources.map((s) => s.dataset).join(", ")}
                  </p>
                </div>
              ) : <Scenarios portfolioId={item.id} presets={presets} base={base} />}
            </Panel>
          </div>
        </>
      )}
    </div>
  );
}

export default function PortfolioPage() {
  const { can, me, atLeast } = useSession();
  const list = useApi<{ items: PortfolioItem[]; presets: Record<string, Preset> }>(can("portfolio.use") ? "/portfolios" : null);
  const [chosen, setChosen] = useStored<string | null>("portfolio", null);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  if (!can("portfolio.use")) return <div className="p-2"><Panel title="Portfolio"><Locked feature="Portfolio analytics" plan={me.tenant.plan_name} /></Panel></div>;
  if (list.error) return <ErrorNote error={list.error} onRetry={list.reload} />;
  if (!list.data) return <Skeleton rows={10} />;
  const item = list.data.items.find((p) => p.id === chosen) ?? list.data.items[0];

  async function act(action: () => Promise<{ id: string }>) {
    setMessage(null);
    try {
      const created = await action();
      setChosen(created.id);
      setCreating(false);
      list.reload();
    } catch (failure) {
      setMessage(describeError(failure));
    }
  }

  return (
    <div className="flex min-h-full flex-col gap-2 p-2">
      <div className="flex flex-wrap items-center gap-2 px-1">
        {list.data.items.length > 0 && (
          <select aria-label="Portfolio" value={item?.id} onChange={(event) => setChosen(event.target.value)}
                  className="h-8 rounded border border-line-strong bg-ink px-2 text-[12.5px] font-medium text-fg">
            {list.data.items.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.base_currency}</option>)}
          </select>
        )}
        {atLeast("analyst") && (
          <>
            <Button size="sm" onClick={() => setCreating(true)}><Plus size={11} /> New portfolio</Button>
            <Button size="sm" variant="ghost" onClick={() => act(() => api.post<{ id: string }>("/portfolios/demo"))}>
              <Sparkles size={11} /> Demonstration portfolio
            </Button>
          </>
        )}
        <span className="ml-auto text-[11px] text-faint">Virtual portfolios for analysis. AUREX does not connect to brokers or place orders.</span>
      </div>
      {message && <p role="alert" className="px-1 text-[12px] text-down">{message}</p>}
      {!item ? (
        <Panel><Empty title="No portfolio yet">Create one, or start from the demonstration portfolio to try every analytic.</Empty></Panel>
      ) : (
        <PortfolioView key={item.id} item={item} presets={list.data.presets} onDeleted={() => { setChosen(null); list.reload(); }} />
      )}
      <Modal open={creating} onClose={() => setCreating(false)} title="New portfolio">
        <form className="space-y-3" onSubmit={(event) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const num = (name: string) => (form.get(name) ? Number(form.get(name)) : null);
          void act(() => api.post<{ id: string }>("/portfolios", {
            name: String(form.get("name")), base_currency: String(form.get("base")),
            benchmark: String(form.get("benchmark") || "") || null,
            limits: { max_position_pct: num("max_position"), max_sector_pct: num("max_sector") },
          }));
        }}>
          <Field label="Name"><Input name="name" required maxLength={100} /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Base currency">
              <select name="base" className="h-8 w-full rounded border border-line-strong bg-ink px-2 text-[12.5px] text-fg">
                {["EUR", "USD", "GBP", "CHF"].map((c) => <option key={c}>{c}</option>)}
              </select>
            </Field>
            <Field label="Benchmark" hint="A priced instrument, e.g. DEMO10.DEMO"><Input name="benchmark" maxLength={40} /></Field>
            <Field label="Max position %"><Input name="max_position" inputMode="decimal" /></Field>
            <Field label="Max sector %"><Input name="max_sector" inputMode="decimal" /></Field>
          </div>
          {message && <p role="alert" className="text-[12px] text-down">{message}</p>}
          <div className="flex justify-end"><Button type="submit" variant="primary">Create</Button></div>
        </form>
      </Modal>
    </div>
  );
}
