"use client";

import { Play, RefreshCw, Trash2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { LineChart } from "@/components/chart";
import { Badge, Button, cx, Empty, ErrorNote, Field, Input, Locked, Panel, Skeleton, Stat, Tabs } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtNumber, fmtPct, fmtRatioPct, tone } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Strategy = { name: string; label: string; params: Record<string, { min: number; max: number }> };
type Metrics = { observations?: number; start?: string; end?: string; total_return?: number | null; cagr?: number | null;
  volatility?: number | null; sharpe?: number | null; max_drawdown?: number | null };
type RunSummary = { id: string; kind: string; name: string; created_at: string; summary: Record<string, number | null> };
type Backtest = {
  label: string; engine_version: string; metrics: Metrics; benchmark: Metrics; in_sample: Metrics; out_of_sample: Metrics;
  split_date: string; trade_count: number; total_costs: number; turnover: number; time_in_market: number;
  variants_tried: number; warnings: string[]; assumptions: Record<string, string | number>;
  curve: { t: string; equity: number; benchmark: number }[];
  trades: { date: string; side: string; price: number; units: number; cost: number }[];
  data: { symbol: string; attribution: string; license_class: string; freshness_class: string };
};
type Simulation = {
  method: string; seed: number; paths: number; horizon: number; label: string; engine_version: string;
  fan: { step: number; p5: number; p25: number; p50: number; p75: number; p95: number }[];
  terminal: { p5: number; p50: number; p95: number; mean: number; probability_of_loss: number; var_95: number;
    expected_shortfall_95: number };
  history: { observations: number; mean_daily: number; volatility_daily: number };
  data: Record<string, string>;
};
type RunDetail = { id: string; kind: string; name: string; spec: Record<string, unknown>; data_as_of: string;
  engine_version: string; result: Backtest & Simulation };

const today = () => new Date().toISOString().slice(0, 10);
const yearsAgo = (n: number) => { const d = new Date(); d.setFullYear(d.getFullYear() - n); return d.toISOString().slice(0, 10); };
const DEFAULT_PARAMS: Record<string, Record<string, number>> = {
  buy_and_hold: {}, sma_cross: { fast: 50, slow: 200 }, momentum: { lookback: 120, threshold_pct: 0 },
  rsi_reversion: { window: 14, enter_below: 30, exit_above: 70 },
};

function MetricRow({ label, m }: { label: string; m: Metrics }) {
  return (
    <tr className="border-b border-line/60">
      <td className="py-1 text-dim">{label}</td>
      <td className="num text-right text-faint">{m.start ? `${fmtDate(m.start)} – ${fmtDate(m.end)}` : "—"}</td>
      <td className={cx("num text-right", tone(m.total_return))}>{fmtRatioPct(m.total_return)}</td>
      <td className={cx("num text-right", tone(m.cagr))}>{fmtRatioPct(m.cagr)}</td>
      <td className="num text-right">{m.volatility != null ? `${fmtNumber(m.volatility * 100, 1)}%` : "—"}</td>
      <td className="num text-right">{fmtNumber(m.sharpe, 2)}</td>
      <td className="num pr-1 text-right text-down">{fmtRatioPct(m.max_drawdown)}</td>
    </tr>
  );
}

function BacktestView({ run }: { run: RunDetail }) {
  const r = run.result;
  const series = useMemo(() => [
    { name: "Strategy", points: r.curve.map((p) => ({ t: p.t, v: p.equity })) },
    { name: "Buy and hold", points: r.curve.map((p) => ({ t: p.t, v: p.benchmark })) },
  ], [r.curve]);
  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="info">{r.label}</Badge><span className="num text-[12px] text-fg">{r.data.symbol}</span>
        {r.data.license_class === "demonstration" && <Badge tone="demo">Demonstration data</Badge>}
        <Badge>{`${r.variants_tried} variant${r.variants_tried > 1 ? "s" : ""} tried`}</Badge>
      </div>
      {r.warnings.map((w) => <p key={w} className="rounded border border-warn/30 bg-warn/5 px-2.5 py-1.5 text-[12px] text-warn">{w}</p>)}
      <div className="h-64 rounded border border-line"><LineChart series={series} /></div>
      <table className="w-full text-[12px]">
        <thead className="text-[10.5px] tracking-wider text-faint uppercase">
          <tr className="border-b border-line"><th className="py-1 text-left font-medium">Period</th><th className="text-right font-medium">Dates</th>
            <th className="text-right font-medium">Return</th><th className="text-right font-medium">Annualized</th>
            <th className="text-right font-medium">Volatility</th><th className="text-right font-medium">Sharpe</th>
            <th className="pr-1 text-right font-medium">Max DD</th></tr>
        </thead>
        <tbody>
          <MetricRow label="Whole period" m={r.metrics} />
          <MetricRow label="In sample" m={r.in_sample} />
          <MetricRow label="Out of sample" m={r.out_of_sample} />
          <MetricRow label="Buy and hold" m={r.benchmark} />
        </tbody>
      </table>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Trades" value={String(r.trade_count)} />
        <Stat label="Costs paid" value={fmtNumber(r.total_costs, 0)} />
        <Stat label="Turnover" value={`${fmtNumber(r.turnover, 1)}x`} />
        <Stat label="Time in market" value={`${fmtNumber(r.time_in_market * 100, 0)}%`} />
      </div>
      <div className="rounded border border-line bg-ink/40 p-2.5 text-[11.5px] text-dim">
        <div className="mb-1 text-[10.5px] tracking-wider text-faint uppercase">Assumptions</div>
        Costs {r.assumptions.cost_bps} bp + slippage {r.assumptions.slippage_bps} bp per trade · {String(r.assumptions.execution)} ·{" "}
        {String(r.assumptions.information)} · split at {fmtDate(r.split_date)} · data as known {fmtDateTime(run.data_as_of)} · engine {r.engine_version}
      </div>
      <p className="text-[11px] text-faint">{r.data.attribution}. Past results under stated assumptions; not a forecast or a recommendation.</p>
    </div>
  );
}

function SimulationView({ run }: { run: RunDetail }) {
  const r = run.result;
  const series = useMemo(() => {
    const start = new Date();
    const date = (step: number) => { const d = new Date(start); d.setDate(d.getDate() + Math.round(step * 7 / 5)); return d.toISOString().slice(0, 10); };
    const line = (key: "p5" | "p25" | "p50" | "p75" | "p95", name: string, color?: string) =>
      ({ name, color, points: r.fan.map((p) => ({ t: date(p.step), v: p[key] })) });
    return [line("p50", "Median"), line("p5", "5th pct", "#f26d78"), line("p25", "25th", "#9aa6b8"), line("p75", "75th", "#9aa6b8"),
      line("p95", "95th pct", "#3fcf8e")];
  }, [r.fan]);
  return (
    <div className="space-y-3 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="info">Monte Carlo · {r.method}</Badge>
        <span className="text-[12px] text-dim">{r.paths.toLocaleString("en-US")} paths · {r.horizon} trading days · seed {r.seed}</span>
      </div>
      <div className="h-64 rounded border border-line"><LineChart series={series} /></div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Median end value" value={fmtNumber(r.terminal.p50, 2)} />
        <Stat label="5% – 95% range" value={`${fmtNumber(r.terminal.p5, 2)} – ${fmtNumber(r.terminal.p95, 2)}`} />
        <Stat label="Probability of loss" value={`${fmtNumber(r.terminal.probability_of_loss * 100, 1)}%`} />
        <Stat label="VaR 95 / ES 95" value={`${fmtNumber(r.terminal.var_95, 1)}% / ${fmtNumber(r.terminal.expected_shortfall_95, 1)}%`} />
      </div>
      <p className="text-[11px] text-faint">
        From {r.history.observations} historical daily returns (mean {fmtPct(r.history.mean_daily * 100, 3)}, volatility{" "}
        {fmtNumber(r.history.volatility_daily * 100, 2)}%). {r.label} Engine {r.engine_version}.
      </p>
    </div>
  );
}

function RunView({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const { data, error } = useApi<RunDetail>(`/quant/runs/${id}`);
  const [check, setCheck] = useState<string | null>(null);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton rows={10} />;
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <span className="text-[13px] font-medium text-fg">{data.name}</span>
        <span className="text-[11px] text-faint">{fmtDateTime(data.data_as_of)}</span>
        <div className="ml-auto flex items-center gap-1.5">
          {check && <span className="text-[11.5px] text-dim" role="status">{check}</span>}
          <Button size="sm" onClick={async () => {
            try {
              const result = await api.post<{ identical?: boolean; reproducible?: boolean; detail?: string }>(`/quant/runs/${id}/reproduce`);
              setCheck(result.detail ?? (result.identical ? "Reproduced identically from the recorded inputs." : "The result differs from the recorded run."));
            } catch (failure) {
              setCheck(describeError(failure));
            }
          }}><RefreshCw size={11} /> Reproduce</Button>
          <Button size="sm" variant="ghost" onClick={async () => { await api.delete(`/quant/runs/${id}`); onDeleted(); }}><Trash2 size={11} /></Button>
        </div>
      </div>
      {data.kind === "backtest" ? <BacktestView run={data} /> : <SimulationView run={data} />}
    </div>
  );
}

function BacktestForm({ onDone }: { onDone: (id: string) => void }) {
  const strategies = useApi<{ items: Strategy[] }>("/quant/strategies");
  const [strategy, setStrategy] = useState("sma_cross");
  const [params, setParams] = useState<Record<string, number>>(DEFAULT_PARAMS.sma_cross);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const spec = strategies.data?.items.find((s) => s.name === strategy);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    setBusy(true);
    setMessage(null);
    try {
      const run = await api.post<{ id: string }>("/quant/backtests", {
        symbol: value("symbol"), strategy, params, start: value("start"), end: value("end"),
        in_sample_end: value("split") || null, cost_bps: Number(value("cost")), slippage_bps: Number(value("slippage")),
        latency_days: Number(value("latency")), initial_capital: Number(value("capital")),
      });
      onDone(run.id);
    } catch (failure) {
      setMessage(describeError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2.5 p-3">
      <Field label="Instrument"><Input name="symbol" required defaultValue="ORCA.DEMO" /></Field>
      <Field label="Strategy">
        <select value={strategy} onChange={(event) => { setStrategy(event.target.value); setParams(DEFAULT_PARAMS[event.target.value] ?? {}); }}
                className="h-8 w-full rounded border border-line-strong bg-ink px-2 text-[12.5px] text-fg">
          {(strategies.data?.items ?? []).map((s) => <option key={s.name} value={s.name}>{s.label}</option>)}
        </select>
      </Field>
      {spec && Object.keys(spec.params).length > 0 && (
        <div className="grid grid-cols-3 gap-2">
          {Object.entries(spec.params).map(([name, range]) => (
            <Field key={name} label={name.replaceAll("_", " ")} hint={`${range.min}–${range.max}`}>
              <Input inputMode="decimal" value={String(params[name] ?? "")} onChange={(event) => setParams({ ...params, [name]: Number(event.target.value) })} />
            </Field>
          ))}
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <Field label="Start"><Input name="start" type="date" required defaultValue={yearsAgo(5)} /></Field>
        <Field label="End"><Input name="end" type="date" required defaultValue={today()} /></Field>
      </div>
      <Field label="In-sample ends" hint="Defaults to 70% of the period"><Input name="split" type="date" /></Field>
      <div className="grid grid-cols-3 gap-2">
        <Field label="Costs (bp)"><Input name="cost" required inputMode="decimal" defaultValue="10" /></Field>
        <Field label="Slippage (bp)"><Input name="slippage" required inputMode="decimal" defaultValue="5" /></Field>
        <Field label="Latency (days)"><Input name="latency" required inputMode="numeric" defaultValue="1" /></Field>
      </div>
      <Field label="Initial capital"><Input name="capital" inputMode="decimal" defaultValue="100000" /></Field>
      {message && <p role="alert" className="text-[12px] text-down">{message}</p>}
      <Button type="submit" variant="primary" disabled={busy} className="w-full"><Play size={12} /> {busy ? "Running…" : "Run backtest"}</Button>
      <p className="text-[11px] leading-relaxed text-faint">Decisions use only data published by the end of each day and fill at a later close. Costs and latency are always applied.</p>
    </form>
  );
}

function SimulationForm({ onDone }: { onDone: (id: string) => void }) {
  const { can, me } = useSession();
  const portfolios = useApi<{ items: { id: string; name: string }[] }>(can("portfolio.use") ? "/portfolios" : null);
  const [source, setSource] = useState("symbol");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  if (!can("quant.simulate")) return <Locked feature="Simulation" plan={me.tenant.plan_name} />;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    setBusy(true);
    setMessage(null);
    try {
      const run = await api.post<{ id: string }>("/quant/simulations", {
        symbol: source === "symbol" ? value("symbol") : null, portfolio_id: source === "portfolio" ? value("portfolio") : null,
        horizon: Number(value("horizon")), paths: Number(value("paths")), method: value("method"),
        seed: value("seed") ? Number(value("seed")) : null,
      });
      onDone(run.id);
    } catch (failure) {
      setMessage(describeError(failure));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2.5 p-3">
      <Field label="Simulate">
        <select value={source} onChange={(event) => setSource(event.target.value)} className="h-8 w-full rounded border border-line-strong bg-ink px-2 text-[12.5px] text-fg">
          <option value="symbol">An instrument</option><option value="portfolio">A portfolio</option>
        </select>
      </Field>
      {source === "symbol" ? <Field label="Instrument"><Input name="symbol" required defaultValue="EURUSD" /></Field> : (
        <Field label="Portfolio">
          <select name="portfolio" required className="h-8 w-full rounded border border-line-strong bg-ink px-2 text-[12.5px] text-fg">
            {(portfolios.data?.items ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </Field>
      )}
      <div className="grid grid-cols-2 gap-2">
        <Field label="Horizon (trading days)"><Input name="horizon" inputMode="numeric" defaultValue="252" /></Field>
        <Field label="Paths"><Input name="paths" inputMode="numeric" defaultValue="2000" /></Field>
        <Field label="Method">
          <select name="method" className="h-8 w-full rounded border border-line-strong bg-ink px-2 text-[12.5px] text-fg">
            <option value="bootstrap">Bootstrap of history</option><option value="normal">Normal returns</option>
          </select>
        </Field>
        <Field label="Seed" hint="Same seed, same paths"><Input name="seed" inputMode="numeric" /></Field>
      </div>
      {message && <p role="alert" className="text-[12px] text-down">{message}</p>}
      <Button type="submit" variant="primary" disabled={busy} className="w-full"><Play size={12} /> {busy ? "Simulating…" : "Run simulation"}</Button>
    </form>
  );
}

export default function QuantPage() {
  const { can, me } = useSession();
  const runs = useApi<{ items: RunSummary[] }>("/quant/runs");
  const [mode, setMode] = useState<"backtest" | "simulation">(can("quant.backtest") ? "backtest" : "simulation");
  const [chosen, setChosen] = useState<string | null>(null);
  const selected = chosen ?? runs.data?.items[0]?.id ?? null;
  const done = (id: string) => { setChosen(id); runs.reload(); };

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 p-2 lg:grid-cols-[320px_minmax(0,1fr)]">
      <Panel bodyClassName="flex flex-col">
        <Tabs value={mode} onChange={setMode} options={[{ value: "backtest", label: "Backtest" }, { value: "simulation", label: "Simulation" }]} />
        <div className="shrink-0">
          {mode === "backtest" ? (can("quant.backtest") ? <BacktestForm onDone={done} /> : <Locked feature="Backtesting" plan={me.tenant.plan_name} />)
            : <SimulationForm onDone={done} />}
        </div>
        <div className="border-t border-line px-3 pt-2.5 pb-1 text-[10.5px] tracking-wider text-faint uppercase">Runs</div>
        <ul className="min-h-0 flex-1 overflow-auto">
          {runs.error ? <ErrorNote error={runs.error} /> : (runs.data?.items ?? []).map((run) => (
            <li key={run.id}>
              <button onClick={() => setChosen(run.id)} className={cx("block w-full px-3 py-1.5 text-left hover:bg-raised", selected === run.id && "bg-hover")}>
                <div className="truncate text-[12px] text-fg">{run.name}</div>
                <div className="flex gap-2 text-[10.5px] text-faint">
                  <span>{fmtDateTime(run.created_at)}</span>
                  {run.summary.total_return != null && <span className={tone(run.summary.total_return)}>{fmtRatioPct(run.summary.total_return)}</span>}
                  {run.summary.probability_of_loss != null && <span>P(loss) {fmtNumber(run.summary.probability_of_loss * 100, 0)}%</span>}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </Panel>
      <Panel bodyClassName="overflow-auto">
        {selected ? <RunView key={selected} id={selected} onDeleted={() => { setChosen(null); runs.reload(); }} />
          : <Empty title="No runs yet">Backtests use point-in-time data with explicit costs and latency; simulations are seeded and reproducible.</Empty>}
      </Panel>
    </div>
  );
}
