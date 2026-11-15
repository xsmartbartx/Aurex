"use client";

import { Plus, Search, Send, Trash2, Upload } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState, type FormEvent } from "react";
import { AnswerView, DocumentReader, DocumentRow, type DocumentItem } from "@/components/intelligence";
import { Badge, Button, cx, Empty, ErrorNote, Field, Input, Locked, Modal, Panel, Skeleton, Tabs } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import { fmtCompact, fmtDate, fmtDateTime, fmtNumber, fmtPrice } from "@/lib/format";
import { useApi, useDebounced } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Entity } from "@/lib/types";

type Tab = "ask" | "documents" | "companies" | "theses";
type HistoryItem = { id: string; kind: string; agent: string; title: string; status: string; engine: string;
  created_at: string; shared: boolean; own: boolean; supported: number };
type Agent = { name: string; title: string; purpose: string };

const EXAMPLES = [
  "Compare ORCA and PXLR on revenue growth, cash flows, debt and sensitivity to interest rates.",
  "How volatile was EURUSD over the last year, and where is the ECB deposit facility rate?",
  "Which datasets are stale or failing?",
];

function Ask() {
  const params = useSearchParams();
  const router = useRouter();
  const { can, me } = useSession();
  const [question, setQuestion] = useState(params.get("q") ?? "");
  const [agent, setAgent] = useState("research");
  const [report, setReport] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const selected = params.get("answer");
  const history = useApi<{ items: HistoryItem[] }>("/intelligence/questions");
  const agents = useApi<{ items: Agent[]; engine: string }>("/intelligence/agents");

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (question.trim().length < 3) return;
    setBusy(true);
    setMessage(null);
    try {
      const created = await api.post<{ id: string }>("/intelligence/questions",
        { question: question.trim(), agent, kind: report ? "report" : "answer" });
      setQuestion("");
      history.reload();
      router.replace(`/app/intelligence?answer=${created.id}`);
    } catch (failure) {
      setMessage(describeError(failure));
    } finally {
      setBusy(false);
    }
  }

  if (!can("intelligence.ask")) return <Locked feature="AI research" plan={me.tenant.plan_name} />;
  const limit = me.limits.ai_questions_per_day;
  const used = me.usage_today.ai_questions ?? 0;

  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)]">
      <div className="flex min-h-0 flex-col border-b border-line lg:border-r lg:border-b-0">
        <form onSubmit={submit} className="space-y-2 border-b border-line p-3">
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) void submit();
            }}
            rows={4}
            maxLength={2000}
            placeholder="Ask about companies, filings, rates, currencies or your own documents…"
            aria-label="Question"
            className="w-full resize-none rounded border border-line-strong bg-ink px-2.5 py-2 text-[13px] text-fg placeholder:text-faint focus:border-gold-dim focus:outline-none"
          />
          <div className="flex flex-wrap items-center gap-2">
            <select value={agent} onChange={(event) => setAgent(event.target.value)} aria-label="Agent"
                    className="h-7 min-w-0 flex-1 rounded border border-line-strong bg-ink px-1.5 text-[12px] text-fg">
              {(agents.data?.items ?? [{ name: "research", title: "Research Agent", purpose: "" }]).map((a) => (
                <option key={a.name} value={a.name} title={a.purpose}>{a.title}</option>
              ))}
            </select>
            {can("intelligence.reports") && (
              <label className="flex items-center gap-1 text-[11.5px] text-dim">
                <input type="checkbox" checked={report} onChange={(event) => setReport(event.target.checked)} /> Report
              </label>
            )}
            <Button type="submit" variant="primary" size="sm" disabled={busy || question.trim().length < 3}>
              <Send size={11} /> Ask
            </Button>
          </div>
          {message && <p role="alert" className="text-[11.5px] text-down">{message}</p>}
          <p className="text-[10.5px] text-faint">
            <kbd>⌘</kbd> <kbd>Enter</kbd> to ask
            {limit < 1_000_000 && ` · ${Math.max(0, limit - used)} of ${limit} questions left today`}
            {agents.data && ` · ${agents.data.engine === "offline" ? "offline evidence engine" : "AI model"}`}
          </p>
        </form>
        <div className="min-h-0 flex-1 overflow-auto">
          <div className="px-3 pt-2.5 pb-1 text-[10.5px] tracking-wider text-faint uppercase">History</div>
          {history.error ? <ErrorNote error={history.error} /> : !history.data ? <Skeleton rows={5} /> : (
            <ul>
              {history.data.items.length === 0 && (
                <li className="px-3 py-2 text-[12px] text-faint">No questions yet.</li>
              )}
              {history.data.items.map((item) => (
                <li key={item.id}>
                  <button onClick={() => router.replace(`/app/intelligence?answer=${item.id}`)}
                          className={cx("block w-full px-3 py-1.5 text-left hover:bg-raised", selected === item.id && "bg-hover")}>
                    <span className="line-clamp-2 text-[12px] text-fg">{item.title}</span>
                    <span className="flex gap-2 text-[10.5px] text-faint">
                      <span>{fmtDateTime(item.created_at)}</span>
                      {item.status === "running" ? <span className="text-gold">running</span>
                        : item.status === "failed" ? <span className="text-down">failed</span>
                          : <span>{item.supported} supported</span>}
                      {item.kind === "report" && <span className="text-gold">report</span>}
                      {!item.own && <span className="text-info">shared</span>}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <div className="min-h-0">
        {selected ? (
          <AnswerView key={selected} id={selected} onSettled={history.reload}
                      onDeleted={() => { history.reload(); router.replace("/app/intelligence"); }} />
        ) : (
          <div className="mx-auto max-w-xl px-6 py-10">
            <h1 className="text-[16px] font-semibold text-fg">Answers you can check</h1>
            <p className="mt-2 text-[12.5px] leading-relaxed text-dim">
              Every statement links to the filing passage, reported figure or calculation behind it. Figures come from
              the financial engine, never from the language model. A statement the evidence does not support is
              withheld and listed, and every answer states what is missing or stale.
            </p>
            <div className="mt-5 space-y-1.5">
              {EXAMPLES.map((example) => (
                <button key={example} onClick={() => setQuestion(example)}
                        className="block w-full rounded border border-line px-3 py-2 text-left text-[12.5px] text-dim hover:border-gold-dim hover:text-fg">
                  {example}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Documents() {
  const { can, me, atLeast } = useSession();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const term = useDebounced(query.trim(), 250);
  const recent = useApi<{ items: DocumentItem[] }>(can("intelligence.documents") ? "/intelligence/documents" : null, { limit: 60 });
  const hits = useApi<{ items: { passage: { id: number; location: string }; document: DocumentItem; headline: string }[] }>(
    term.length >= 2 ? "/intelligence/search" : null, { q: term });
  if (!can("intelligence.documents")) return <Locked feature="Document search" plan={me.tenant.plan_name} />;

  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setMessage(null);
    try {
      const result = await api.upload<{ flagged_passages: number }>("/intelligence/documents", form);
      setUploading(false);
      recent.reload();
      setMessage(result.flagged_passages
        ? `Uploaded. ${result.flagged_passages} passage(s) contain instruction-like text and are withheld from AI agents.`
        : "Uploaded and indexed.");
    } catch (failure) {
      setMessage(describeError(failure));
    }
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
      <div className="flex min-h-0 flex-col border-r border-line">
        <div className="flex shrink-0 items-center gap-2 border-b border-line p-2.5">
          <div className="relative flex-1">
            <Search size={13} className="absolute top-2 left-2.5 text-faint" />
            <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search filings, news and your documents"
                   aria-label="Search documents" className="pl-8" />
          </div>
          {atLeast("analyst") && <Button onClick={() => setUploading(true)}><Upload size={12} /> Upload</Button>}
        </div>
        {message && <p role="status" className="border-b border-line px-3 py-1.5 text-[11.5px] text-dim">{message}</p>}
        <div className="min-h-0 flex-1 overflow-auto">
          {term.length >= 2 ? (
            hits.error ? <ErrorNote error={hits.error} /> : !hits.data ? <Skeleton rows={6} /> : hits.data.items.length === 0 ? (
              <Empty title="No passage matches">Try other words, or fewer of them.</Empty>
            ) : (
              <ul className="divide-y divide-line">
                {hits.data.items.map((hit) => (
                  <li key={hit.passage.id}>
                    <button onClick={() => setOpen(hit.document.id)} className="block w-full px-3 py-2 text-left hover:bg-raised">
                      <div className="truncate text-[12.5px] text-fg">{hit.document.title}</div>
                      <div className="text-[10.5px] text-faint">{hit.passage.location} · {fmtDate(hit.document.published_at)}</div>
                      <p className="mt-1 text-[12px] text-dim">
                        {hit.headline.split(/(«[^»]*»)/).map((part, index) => part.startsWith("«")
                          ? <mark key={index} className="bg-gold/20 text-fg">{part.slice(1, -1)}</mark> : part)}
                      </p>
                    </button>
                  </li>
                ))}
              </ul>
            )
          ) : recent.error ? <ErrorNote error={recent.error} /> : !recent.data ? <Skeleton rows={8} /> : (
            <ul className="divide-y divide-line">
              {recent.data.items.map((doc) => <DocumentRow key={doc.id} doc={doc} onOpen={() => setOpen(doc.id)} />)}
            </ul>
          )}
        </div>
      </div>
      <div className="hidden min-h-0 lg:block">
        {open ? <DocumentReader key={open} id={open} onClose={() => setOpen(null)} />
          : <Empty title="Select a document">Passages flagged by content screening are marked and never reach an AI agent.</Empty>}
      </div>
      {open && (
        <div className="fixed inset-0 z-30 bg-panel lg:hidden">
          <DocumentReader id={open} onClose={() => setOpen(null)} />
        </div>
      )}
      <Modal open={uploading} onClose={() => setUploading(false)} title="Upload a document">
        <form onSubmit={upload} className="space-y-3">
          <Field label="Title"><Input name="title" required maxLength={200} /></Field>
          <Field label="File" hint="Plain text (.txt) or Markdown (.md), up to 5 MB. Private to your organization.">
            <input name="file" type="file" accept=".txt,.md,text/plain,text/markdown" required
                   className="block w-full text-[12px] text-dim file:mr-3 file:rounded file:border file:border-line-strong file:bg-raised file:px-2 file:py-1 file:text-fg" />
          </Field>
          <div className="flex justify-end"><Button type="submit" variant="primary">Upload</Button></div>
        </form>
      </Modal>
    </div>
  );
}

type Fundamentals = {
  entity: Entity; missing: string[]; engine_version: string;
  provenance: { attribution: string; license_class: string } | null;
  years: { fiscal_year: number; period_end: string;
    items: Record<string, { value: number; unit: string; label: string; filed_at: string; accession: string }>;
    ratios: Record<string, { value: number; unit: string; label: string; definition: string }> }[];
};

const ITEM_ORDER = ["revenue", "gross_profit", "operating_income", "net_income", "eps_diluted", "operating_cash_flow",
  "capex", "cash", "debt_long_term", "debt_current", "equity", "assets", "liabilities", "interest_expense"];
const RATIO_ORDER = ["revenue_growth", "gross_margin", "operating_margin", "net_margin", "free_cash_flow", "fcf_margin",
  "total_debt", "net_debt", "debt_to_equity", "interest_coverage", "return_on_equity", "current_ratio"];

function cell(value: number | undefined, unit: string | undefined): string {
  if (value === undefined) return "—";
  if (unit === "percent") return `${fmtNumber(value, 1)}%`;
  if (unit === "ratio") return `${fmtNumber(value, 2)}x`;
  if (unit === "USD/shares") return fmtNumber(value, 2);
  return fmtCompact(value);
}

function Companies() {
  const { atLeast } = useSession();
  const [query, setQuery] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const [cik, setCik] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const term = useDebounced(query.trim(), 250);
  const list = useApi<{ items: Entity[] }>("/intelligence/companies", { q: term, tracked: term ? undefined : true });
  const detail = useApi<Fundamentals>(chosen ? `/intelligence/companies/${chosen}/fundamentals` : null);
  const first = list.data?.items[0]?.id;
  useEffect(() => {
    if (!chosen && first) queueMicrotask(() => setChosen(first));
  }, [chosen, first]);

  return (
    <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)]">
      <div className="flex min-h-0 flex-col border-r border-line">
        <div className="space-y-2 border-b border-line p-2.5">
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search companies" aria-label="Search companies" />
          {atLeast("analyst") && (
            <form className="flex gap-1.5" onSubmit={async (event) => {
              event.preventDefault();
              setMessage(null);
              try {
                await api.post("/datalab/companies/track", { cik: cik.trim() });
                setCik("");
                setMessage("Queued. Filings and reported figures appear after the next import.");
              } catch (failure) {
                setMessage(describeError(failure));
              }
            }}>
              <Input value={cik} onChange={(event) => setCik(event.target.value)} placeholder="SEC CIK to track, e.g. 320193"
                     inputMode="numeric" pattern="\d{1,10}" aria-label="SEC CIK" className="h-7" />
              <Button type="submit" size="sm" disabled={!cik.trim()}><Plus size={11} /> Track</Button>
            </form>
          )}
          {message && <p role="status" className="text-[11px] text-dim">{message}</p>}
        </div>
        <ul className="min-h-0 flex-1 divide-y divide-line overflow-auto">
          {list.error ? <ErrorNote error={list.error} /> : !list.data ? <Skeleton rows={6} /> : list.data.items.map((entity) => (
            <li key={entity.id}>
              <button onClick={() => setChosen(entity.id)} className={cx("block w-full px-3 py-2 text-left hover:bg-raised", chosen === entity.id && "bg-hover")}>
                <div className="truncate text-[12.5px] text-fg">{entity.name}</div>
                <div className="text-[10.5px] text-faint">{entity.ticker ?? entity.cik ?? entity.kind} {entity.sector ? `· ${entity.sector}` : ""}</div>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="min-h-0 overflow-auto">
        {!chosen ? <Empty title="Choose a company" /> : detail.error ? <ErrorNote error={detail.error} /> : !detail.data ? <Skeleton rows={10} /> : (
          <div className="p-4">
            <div className="mb-3 flex flex-wrap items-baseline gap-2">
              <h1 className="text-[16px] font-semibold text-fg">{detail.data.entity.name}</h1>
              {detail.data.entity.ticker && <span className="num text-dim">{detail.data.entity.ticker}</span>}
              {detail.data.provenance?.license_class === "demonstration" && <Badge tone="demo">Demonstration</Badge>}
            </div>
            {detail.data.years.length === 0 ? (
              <Empty title="No reported annual figures are loaded">
                {detail.data.entity.tracked ? "The next import will add them." : "Track the company to import its filings."}
              </Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] border-collapse text-[12px]">
                  <thead>
                    <tr className="border-b border-line text-faint">
                      <th className="py-1.5 text-left font-medium">Fiscal year</th>
                      {detail.data.years.map((y) => <th key={y.fiscal_year} className="num pr-2 text-right font-medium">FY{y.fiscal_year}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {ITEM_ORDER.filter((k) => detail.data!.years.some((y) => y.items[k])).map((key) => (
                      <tr key={key} className="border-b border-line/60">
                        <td className="py-1 text-dim">{detail.data!.years.find((y) => y.items[key])!.items[key].label}</td>
                        {detail.data!.years.map((y) => (
                          <td key={y.fiscal_year} className="num pr-2 text-right text-fg"
                              title={y.items[key] ? `Filed ${y.items[key].filed_at} · ${y.items[key].accession}` : "Not reported"}>
                            {cell(y.items[key]?.value, y.items[key]?.unit)}
                          </td>
                        ))}
                      </tr>
                    ))}
                    <tr><td colSpan={99} className="pt-3 pb-1 text-[10.5px] tracking-wider text-faint uppercase">
                      Calculated by the financial engine {detail.data.engine_version}</td></tr>
                    {RATIO_ORDER.filter((k) => detail.data!.years.some((y) => y.ratios[k])).map((key) => (
                      <tr key={key} className="border-b border-line/60">
                        <td className="py-1 text-dim">{detail.data!.years.find((y) => y.ratios[key])!.ratios[key].label}</td>
                        {detail.data!.years.map((y) => (
                          <td key={y.fiscal_year} className="num pr-2 text-right text-fg" title={y.ratios[key]?.definition}>
                            {cell(y.ratios[key]?.value, y.ratios[key]?.unit)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {detail.data.missing.length > 0 && (
                  <p className="mt-3 text-[11.5px] text-faint">
                    Not reported for the latest year: {detail.data.missing.map((m) => m.replaceAll("_", " ")).join(", ")}.
                  </p>
                )}
                <p className="mt-1 text-[11px] text-faint">{detail.data.provenance?.attribution}</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

type Thesis = {
  id: string; title: string; statement: string; status: string; last_checked_at: string | null;
  conditions: { instrument: string; operator: string; value: number; series: string; unit?: string;
    latest: number | null; latest_at: string | null; holds: boolean | null }[];
  history: { at: string; status: string; detail: string }[];
};

function Theses() {
  const { can, me } = useSession();
  const list = useApi<{ items: Thesis[] }>(can("intelligence.theses") ? "/intelligence/theses" : null);
  const [creating, setCreating] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  if (!can("intelligence.theses")) return <Locked feature="Thesis monitoring" plan={me.tenant.plan_name} />;

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setMessage(null);
    try {
      await api.post("/intelligence/theses", {
        title: String(form.get("title")), statement: String(form.get("statement") ?? ""),
        conditions: [{ instrument: String(form.get("instrument")), operator: String(form.get("operator")),
          value: Number(form.get("value")) }],
      });
      setCreating(false);
      list.reload();
    } catch (failure) {
      setMessage(describeError(failure));
    }
  }

  return (
    <div className="p-3">
      <div className="mb-3 flex items-center justify-between">
        <p className="text-[12px] text-dim">A thesis lists the conditions it depends on. When new data breaks one, the thesis is marked challenged and you are notified.</p>
        <Button variant="primary" size="sm" onClick={() => setCreating(true)}><Plus size={11} /> New thesis</Button>
      </div>
      {list.error ? <ErrorNote error={list.error} /> : !list.data ? <Skeleton rows={4} /> : list.data.items.length === 0 ? (
        <Empty title="No theses yet" />
      ) : (
        <ul className="grid gap-2 md:grid-cols-2">
          {list.data.items.map((thesis) => (
            <li key={thesis.id} className="rounded border border-line bg-panel p-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="text-[13px] font-medium text-fg">{thesis.title}</div>
                  {thesis.statement && <p className="mt-0.5 text-[12px] text-dim">{thesis.statement}</p>}
                </div>
                <Badge tone={thesis.status === "holding" ? "up" : thesis.status === "challenged" ? "down" : "neutral"}>{thesis.status}</Badge>
              </div>
              <ul className="mt-2 space-y-1">
                {thesis.conditions.map((condition, index) => (
                  <li key={index} className="num flex justify-between gap-3 text-[11.5px]">
                    <span className="text-dim">{condition.instrument} {condition.operator} {fmtNumber(condition.value, 4).replace(/\.?0+$/, "")}</span>
                    <span className={condition.holds === false ? "text-down" : condition.holds ? "text-up" : "text-faint"}>
                      now {fmtPrice(condition.latest)} · {fmtDate(condition.latest_at)}
                    </span>
                  </li>
                ))}
              </ul>
              {thesis.history.length > 0 && (
                <p className="mt-2 text-[11px] text-faint">Last change {fmtDateTime(thesis.history.at(-1)!.at)}: {thesis.history.at(-1)!.detail || thesis.history.at(-1)!.status}</p>
              )}
              <div className="mt-2 flex justify-end">
                <button aria-label="Delete thesis" className="text-faint hover:text-down"
                        onClick={() => api.delete(`/intelligence/theses/${thesis.id}`).then(list.reload)}>
                  <Trash2 size={13} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
      <Modal open={creating} onClose={() => setCreating(false)} title="New thesis">
        <form onSubmit={create} className="space-y-3">
          <Field label="Title"><Input name="title" required maxLength={160} placeholder="Euro area rates stay restrictive" /></Field>
          <Field label="Statement"><Input name="statement" maxLength={4000} placeholder="Why you hold this view" /></Field>
          <div className="grid grid-cols-[1fr_auto_100px] gap-2">
            <Field label="Instrument"><Input name="instrument" required placeholder="ECBDFR" /></Field>
            <Field label="Condition">
              <select name="operator" className="h-8 rounded border border-line-strong bg-ink px-2 text-[12.5px] text-fg">
                <option value="above">stays above</option><option value="below">stays below</option>
              </select>
            </Field>
            <Field label="Value"><Input name="value" required inputMode="decimal" placeholder="2" /></Field>
          </div>
          {message && <p role="alert" className="text-[12px] text-down">{message}</p>}
          <div className="flex justify-end"><Button type="submit" variant="primary">Save and check</Button></div>
        </form>
      </Modal>
    </div>
  );
}

function Intelligence() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = (params.get("tab") as Tab) ?? "ask";
  const go = (next: Tab) => router.replace(next === "ask" ? "/app/intelligence" : `/app/intelligence?tab=${next}`);
  return (
    <div className="h-full p-2">
      <Panel className="h-full" bodyClassName="flex flex-col overflow-hidden">
        <Tabs value={tab} onChange={go} options={[{ value: "ask", label: "Ask" }, { value: "documents", label: "Documents" },
          { value: "companies", label: "Companies" }, { value: "theses", label: "Theses" }]} />
        <div className="min-h-0 flex-1 overflow-auto">
          {tab === "ask" && <Ask />}
          {tab === "documents" && <Documents />}
          {tab === "companies" && <Companies />}
          {tab === "theses" && <Theses />}
        </div>
      </Panel>
    </div>
  );
}

export default function IntelligencePage() {
  return (
    <Suspense fallback={<Skeleton rows={8} />}>
      <Intelligence />
    </Suspense>
  );
}
