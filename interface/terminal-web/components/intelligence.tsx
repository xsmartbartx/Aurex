"use client";

import { Bot, CheckCircle2, ExternalLink, EyeOff, FileText, Lightbulb, RefreshCw, Share2, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api, describeError } from "@/lib/api";
import { fmtDate, fmtDateTime, fmtNumber } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { Badge, Button, cx, Empty, ErrorNote, Skeleton } from "./ui";

export type Claim = { text: string; evidence: string[]; status: "supported" | "assumption" | "unsupported"; note: string };
export type Evidence = {
  id: string; kind: string; label: string; value?: number; unit?: string; text?: string;
  source?: Record<string, unknown>; calculation?: { definition: string; version: string; inputs: Record<string, unknown> };
};
export type AnswerRecord = {
  id: string; kind: string; agent: string; agent_title: string; title: string; question: string;
  status: "running" | "complete" | "failed"; engine: string; model_id: string; created_at: string; shared: boolean;
  own: boolean; usage: Record<string, number>;
  data_versions: { as_of?: string; engine_version?: string; datasets?: Record<string, { status: string; license_class: string; latest_ref_time: string | null }> };
  answer: {
    title?: string; sections?: { heading: string; claims: Claim[] }[]; evidence?: Evidence[]; gaps?: string[];
    withheld?: { text: string; reason: string }[]; counts?: Record<string, number>; disclaimer?: string;
    generated_by?: { engine: string; model: string; external_provider: boolean };
    tool_calls?: { tool: string; outcome: string; evidence: string[]; ms: number }[];
    refusal?: { category: string | null } | null; error?: { code: string; message: string };
  };
};

const KIND_LABEL: Record<string, string> = {
  fact: "Reported fact", calculation: "Calculation", observation: "Observation", passage: "Document passage",
  dataset: "Dataset status",
};

function fmtEvidenceValue(item: Evidence): string {
  if (item.value === undefined || item.value === null) return "";
  const unit = item.unit ?? "";
  if (unit === "percent") return `${fmtNumber(item.value, 2)}%`;
  if (unit === "ratio") return `${fmtNumber(item.value, 2)}x`;
  if (Math.abs(item.value) >= 1e6) return `${(item.value / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 })}M ${unit}`;
  return `${item.value.toLocaleString("en-US", { maximumFractionDigits: 6 })} ${unit}`;
}

/** What a piece of evidence is and where it came from: the passage, the fact, or the calculation. */
export function EvidenceDetail({ item, onClose }: { item: Evidence; onClose?: () => void }) {
  const source = (item.source ?? {}) as Record<string, string | number | boolean | null>;
  const rows: [string, string][] = [];
  for (const [key, label] of [["dataset", "Dataset"], ["doc_type", "Document type"], ["location", "Location"],
    ["published_at", "Published"], ["period_end", "Period end"], ["filed_at", "Filed"], ["accession", "Accession"],
    ["concept", "Reported concept"], ["ref_time", "Observation date"], ["freshness_class", "Freshness"],
    ["license_class", "License class"], ["status", "Dataset status"]] as const) {
    if (source[key] !== undefined && source[key] !== null && source[key] !== "") rows.push([label, String(source[key])]);
  }
  return (
    <div className="space-y-3 text-[12.5px]">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <span className="num rounded-sm bg-gold/15 px-1.5 text-[11px] font-semibold text-gold">{item.id}</span>
            <span className="text-[10.5px] tracking-wider text-faint uppercase">{KIND_LABEL[item.kind] ?? item.kind}</span>
          </div>
          <div className="mt-1 font-medium text-fg">{item.label}</div>
        </div>
        {onClose && (
          <button aria-label="Close evidence" onClick={onClose} className="text-faint hover:text-fg"><X size={14} /></button>
        )}
      </div>
      {item.value !== undefined && item.value !== null && (
        <div className="num text-[18px] font-semibold text-fg">{fmtEvidenceValue(item)}</div>
      )}
      {item.text && item.kind === "passage" && (
        <blockquote className="border-l-2 border-gold/50 bg-ink/50 py-2 pr-2 pl-3 text-[12.5px] leading-relaxed text-dim">
          {item.text}
        </blockquote>
      )}
      {item.text && item.kind !== "passage" && <p className="text-dim">{item.text}</p>}
      {item.calculation && (
        <div className="rounded border border-line bg-ink/50 p-2.5">
          <div className="text-[10.5px] tracking-wider text-faint uppercase">Calculation · engine {item.calculation.version}</div>
          <div className="num mt-1 text-[12px] text-info">{item.calculation.definition}</div>
          <ul className="mt-1.5 space-y-0.5">
            {Object.entries(item.calculation.inputs ?? {}).map(([name, input]) => (
              <li key={name} className="num flex justify-between gap-3 text-[11.5px] text-dim">
                <span>{name.replaceAll("_", " ")}</span>
                <span className="text-fg">
                  {typeof input === "object" && input !== null && "value" in input
                    ? `${(input as { value: number }).value.toLocaleString("en-US")}${"period_end" in input ? ` · ${(input as { period_end: string }).period_end}` : ""}`
                    : String(input)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {rows.length > 0 && (
        <dl className="space-y-1">
          {rows.map(([label, value]) => (
            <div key={label} className="flex justify-between gap-4 border-b border-line pb-1 text-[11.5px]">
              <dt className="text-faint">{label}</dt>
              <dd className="num truncate text-right text-dim">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {typeof source.attribution === "string" && source.attribution && (
        <p className="text-[11px] text-faint">{source.attribution}</p>
      )}
      {typeof source.url === "string" && source.url && (
        <a href={source.url} target="_blank" rel="noreferrer noopener" className="inline-flex items-center gap-1 text-[12px] text-info hover:underline">
          Open the source document <ExternalLink size={11} />
        </a>
      )}
    </div>
  );
}

function ClaimLine({ claim, active, onCite }: { claim: Claim; active: string | null; onCite: (id: string) => void }) {
  const assumption = claim.status === "assumption";
  return (
    <li className={cx("group flex gap-2 py-1.5", assumption && "text-dim")}>
      <span className="mt-[3px] shrink-0">
        {assumption ? <Lightbulb size={13} className="text-warn" aria-label="Inference" />
          : <CheckCircle2 size={13} className="text-up" aria-label="Supported by evidence" />}
      </span>
      <span className="min-w-0 leading-relaxed">
        {assumption && <span className="mr-1.5 text-[10.5px] font-semibold tracking-wide text-warn uppercase">Inference</span>}
        <span className={assumption ? "italic" : "text-fg"}>{claim.text}</span>
        {claim.evidence.map((id) => (
          <button
            key={id}
            onClick={() => onCite(id)}
            aria-pressed={active === id}
            title="Show the evidence"
            className={cx("num ml-1 rounded-sm px-1 align-baseline text-[10.5px] font-semibold",
              active === id ? "bg-gold text-ink" : "bg-gold/15 text-gold hover:bg-gold/30")}
          >
            {id}
          </button>
        ))}
      </span>
    </li>
  );
}

/** An answer record: verified statements, evidence, gaps and what was withheld. */
export function AnswerView({ id, onDeleted, onSettled }: { id: string; onDeleted?: () => void; onSettled?: () => void }) {
  const { data, error, reload } = useApi<AnswerRecord>(`/intelligence/questions/${id}`);
  const [cited, setCited] = useState<string | null>(null);
  const [reproduced, setReproduced] = useState<{ identical: boolean; checked: number } | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const running = data?.status === "running";

  const [wasRunning, setWasRunning] = useState(false);
  useEffect(() => {
    if (!running) return;
    const timer = setTimeout(() => {
      setWasRunning(true);
      reload();
    }, 1200);
    return () => clearTimeout(timer);
  }, [running, reload, data]);
  useEffect(() => {
    // Tell the parent once a run that was in progress has finished, so lists can refresh.
    if (wasRunning && data && data.status !== "running") {
      queueMicrotask(() => setWasRunning(false));
      onSettled?.();
    }
  }, [wasRunning, data, onSettled]);

  if (error) return <ErrorNote error={error} onRetry={reload} />;
  if (!data) return <Skeleton rows={8} />;
  const answer = data.answer ?? {};
  const evidence = new Map((answer.evidence ?? []).map((e) => [e.id, e]));
  const selected = cited ? evidence.get(cited) : undefined;

  async function act(action: () => Promise<unknown>, done: string) {
    setMessage(null);
    try {
      await action();
      setMessage(done);
      reload();
    } catch (failure) {
      setMessage(describeError(failure));
    }
  }

  return (
    <div className="grid h-full min-h-0 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px]">
      <article className="min-h-0 overflow-auto px-5 py-4">
        <header className="mb-4">
          <div className="mb-1.5 flex flex-wrap items-center gap-2">
            <Badge tone="info">{data.agent_title}</Badge>
            {data.kind === "report" && <Badge tone="gold">Report</Badge>}
            <Badge tone={data.engine === "offline" ? "neutral" : "demo"}>
              <Bot size={10} className="mr-1" />
              {data.engine === "offline" ? "Offline evidence engine" : data.model_id || "AI model"}
            </Badge>
            {data.shared && <Badge tone="up">Shared with team</Badge>}
            <span className="text-[11px] text-faint">{fmtDateTime(data.created_at)}</span>
          </div>
          <h1 className="text-[17px] leading-snug font-semibold text-fg">{answer.title || data.title}</h1>
          {answer.title && answer.title !== data.question && <p className="mt-1 text-[12.5px] text-dim">{data.question}</p>}
        </header>

        {running && (
          <div className="flex items-center gap-2 rounded border border-line bg-raised px-3 py-3 text-[12.5px] text-dim" role="status">
            <RefreshCw size={13} className="animate-spin text-gold" />
            Gathering evidence and checking every statement…
          </div>
        )}
        {data.status === "failed" && (
          <ErrorNote error={new Error(answer.error?.message ?? "The run did not finish. Ask again.")} />
        )}
        {answer.refusal && (
          <div className="rounded border border-warn/40 bg-warn/5 px-3 py-2 text-[12.5px] text-warn">
            The model declined to answer this question.
          </div>
        )}

        {(answer.sections ?? []).map((section) => (
          <section key={section.heading} className="mb-4">
            <h2 className="mb-1 text-[11.5px] font-semibold tracking-wider text-dim uppercase">{section.heading}</h2>
            <ul className="divide-y divide-line/60">
              {section.claims.map((claim, index) => (
                <ClaimLine key={index} claim={claim} active={cited} onCite={(e) => setCited(cited === e ? null : e)} />
              ))}
            </ul>
          </section>
        ))}

        {data.status === "complete" && (answer.gaps?.length ?? 0) > 0 && (
          <section className="mb-4 rounded border border-warn/30 bg-warn/5 px-3 py-2.5">
            <h2 className="mb-1 text-[11.5px] font-semibold tracking-wider text-warn uppercase">Gaps and caveats</h2>
            <ul className="list-disc space-y-0.5 pl-4 text-[12.5px] text-dim">
              {answer.gaps!.map((gap) => <li key={gap}>{gap}</li>)}
            </ul>
          </section>
        )}

        {(answer.withheld?.length ?? 0) > 0 && (
          <details className="mb-4 rounded border border-line px-3 py-2 text-[12px]">
            <summary className="cursor-pointer text-dim">
              <EyeOff size={12} className="mr-1.5 inline" />
              {answer.withheld!.length} statement{answer.withheld!.length > 1 ? "s" : ""} withheld by the claim verifier
            </summary>
            <ul className="mt-2 space-y-1.5">
              {answer.withheld!.map((item, index) => (
                <li key={index} className="text-faint">
                  <span className="line-through">{item.text}</span> — {item.reason}
                </li>
              ))}
            </ul>
          </details>
        )}

        {data.status === "complete" && (
          <footer className="mt-6 space-y-2 border-t border-line pt-3 text-[11px] text-faint">
            <p>{answer.disclaimer}</p>
            <p className="num">
              {answer.counts?.supported ?? 0} supported · {answer.counts?.assumption ?? 0} inference ·{" "}
              {answer.withheld?.length ?? 0} withheld · {answer.tool_calls?.length ?? 0} tool calls · data as of{" "}
              {fmtDateTime(data.data_versions.as_of)} · engine {data.data_versions.engine_version}
              {answer.generated_by?.external_provider ? " · processed by an external model provider" : " · processed in this deployment"}
            </p>
            <div className="flex flex-wrap items-center gap-1.5 pt-1">
              <Button size="sm" onClick={() => act(async () => {
                setReproduced(await api.post<{ identical: boolean; checked: number }>(`/intelligence/questions/${id}/reproduce`));
              }, "")}>
                <RefreshCw size={11} /> Reproduce calculations
              </Button>
              {data.own && (
                <Button size="sm" variant="ghost" onClick={() => act(() => api.post(`/intelligence/questions/${id}/share`,
                  { shared: !data.shared }), data.shared ? "No longer shared" : "Shared with your team")}>
                  <Share2 size={11} /> {data.shared ? "Stop sharing" : "Share with team"}
                </Button>
              )}
              {data.own && onDeleted && (
                <Button size="sm" variant="ghost" onClick={() => act(async () => {
                  await api.delete(`/intelligence/questions/${id}`);
                  onDeleted();
                }, "")}>
                  <Trash2 size={11} /> Delete
                </Button>
              )}
              {reproduced && (
                <span className={cx("text-[11.5px]", reproduced.identical ? "text-up" : "text-down")} role="status">
                  {reproduced.checked === 0 ? "No calculations to reproduce."
                    : reproduced.identical ? `All ${reproduced.checked} calculations reproduced identically.`
                      : "Some calculations differ from the recorded values."}
                </span>
              )}
              {message && <span className="text-[11.5px] text-dim">{message}</span>}
            </div>
          </footer>
        )}
      </article>

      <aside className="hidden min-h-0 overflow-auto border-l border-line bg-ink/40 p-4 xl:block">
        {selected ? <EvidenceDetail item={selected} onClose={() => setCited(null)} /> : (
          <div>
            <div className="mb-2 text-[11px] font-semibold tracking-wider text-dim uppercase">Evidence</div>
            {(answer.evidence ?? []).length === 0 ? (
              <p className="text-[12px] text-faint">Select a citation such as <span className="num text-gold">E1</span> to see what a statement rests on.</p>
            ) : (
              <ul className="space-y-1">
                {answer.evidence!.map((item) => (
                  <li key={item.id}>
                    <button onClick={() => setCited(item.id)} className="flex w-full items-start gap-2 rounded px-1.5 py-1 text-left hover:bg-hover">
                      <span className="num mt-px shrink-0 rounded-sm bg-gold/15 px-1 text-[10.5px] font-semibold text-gold">{item.id}</span>
                      <span className="min-w-0 text-[11.5px] text-dim">{item.label}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </aside>
      {selected && (
        <div className="fixed inset-x-0 bottom-0 z-30 max-h-[60vh] overflow-auto border-t border-line-strong bg-panel p-4 shadow-2xl xl:hidden">
          <EvidenceDetail item={selected} onClose={() => setCited(null)} />
        </div>
      )}
    </div>
  );
}

export type DocumentItem = {
  id: string; doc_type: string; title: string; url: string | null; published_at: string; entity_name: string | null;
  passage_count: number; screening: string; private: boolean; license_class: string; attribution: string;
};

/** A document with its passages. Passages flagged by content screening are marked and never used by agents. */
export function DocumentReader({ id, onClose }: { id: string; onClose: () => void }) {
  const { data, error } = useApi<{ document: DocumentItem; passages: { id: number; location: string; text: string; flagged: boolean }[] }>(
    `/intelligence/documents/${id}`);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-start justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <div className="text-[13.5px] font-semibold text-fg">{data?.document.title ?? "Loading…"}</div>
          {data && (
            <div className="mt-0.5 flex flex-wrap gap-2 text-[11px] text-faint">
              <span>{data.document.doc_type}</span><span>{fmtDate(data.document.published_at)}</span>
              {data.document.private && <Badge tone="info">Private</Badge>}
              {data.document.screening === "flagged" && <Badge tone="gold">Contains flagged passages</Badge>}
              {data.document.url && <a href={data.document.url} target="_blank" rel="noreferrer noopener" className="text-info hover:underline">Original</a>}
            </div>
          )}
        </div>
        <button aria-label="Close document" onClick={onClose} className="text-faint hover:text-fg"><X size={15} /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-4 py-3">
        {error ? <ErrorNote error={error} /> : !data ? <Skeleton rows={10} /> : data.passages.length === 0 ? (
          <Empty title="Only the title is stored for this document" />
        ) : (
          <ol className="space-y-3">
            {data.passages.map((passage) => (
              <li key={passage.id} className={cx("text-[12.5px] leading-relaxed", passage.flagged && "rounded border border-warn/40 bg-warn/5 p-2")}>
                <div className="mb-0.5 text-[10.5px] tracking-wide text-faint uppercase">{passage.location}</div>
                {passage.flagged && (
                  <div className="mb-1 text-[11px] text-warn">Instruction-like content. Withheld from AI agents.</div>
                )}
                <p className="whitespace-pre-line text-dim">{passage.text}</p>
              </li>
            ))}
          </ol>
        )}
        {data && <p className="mt-4 text-[11px] text-faint">{data.document.attribution}</p>}
      </div>
    </div>
  );
}

export function DocumentRow({ doc, onOpen }: { doc: DocumentItem; onOpen: () => void }) {
  return (
    <li>
      <button onClick={onOpen} className="flex w-full items-start gap-2.5 px-3 py-2 text-left hover:bg-raised">
        <FileText size={14} className="mt-0.5 shrink-0 text-faint" />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[12.5px] text-fg">{doc.title}</span>
          <span className="flex flex-wrap gap-2 text-[11px] text-faint">
            <span className="num">{fmtDate(doc.published_at)}</span>
            <span>{doc.doc_type}</span>
            {doc.entity_name && <span className="truncate">{doc.entity_name}</span>}
            {doc.private && <span className="text-info">private</span>}
            {doc.license_class === "demonstration" && <span className="text-demo">demonstration</span>}
          </span>
        </span>
      </button>
    </li>
  );
}
