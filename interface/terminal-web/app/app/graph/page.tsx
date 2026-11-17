"use client";

import { ArrowRight, Check, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState, type FormEvent } from "react";
import { Badge, Button, cx, Empty, ErrorNote, Field, Input, Locked, Modal, Panel, Skeleton, Tabs } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import { fmtDate, fmtNumber } from "@/lib/format";
import { useApi, useDebounced } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type GraphNode = { id: string; key: string; kind: string; name: string; description: string; private: boolean; has_series: boolean };
type GraphLink = {
  id: string; source: GraphNode; target: GraphNode; relation: string; method: string; confidence: number; confidence_basis: string;
  source_ref: string; sign: number; magnitude: number | null; estimation: Record<string, unknown>; description: string;
  review_status: string; private: boolean; low_confidence: boolean; last_verified_at: string | null;
  evidence: { text: string; location: string; document: string; url: string | null } | null;
};
type Neighborhood = { node: GraphNode; links: GraphLink[] };
type Path = { end: GraphNode; effect: string; confidence: number; length: number; weakest_link: string;
  steps: { link: GraphLink; node: GraphNode; effect: string }[] };
type Scenario = { origin: GraphNode; direction: string; paths: Path[]; label: string; method: string };

const KIND_COLOR: Record<string, string> = {
  policy_event: "#f0b44c", indicator: "#5fa8ff", currency: "#b78cff", sector: "#3fcf8e", company: "#dce2ec",
  instrument: "#9aa6b8", commodity: "#f26d78", country: "#f26d78",
};
const METHOD_COLOR: Record<string, string> = {
  reported_fact: "#3fcf8e", analyst_defined: "#5fa8ff", statistical_estimate: "#b78cff", ai_extracted: "#f0b44c",
};
const METHOD_LABEL: Record<string, string> = {
  reported_fact: "Reported fact", analyst_defined: "Analyst-defined", statistical_estimate: "Statistical estimate",
  ai_extracted: "AI-extracted",
};

/** Radial view: the selected node in the middle, linked nodes around it. Dashed lines are low confidence. */
function Radial({ data, onOpen }: { data: Neighborhood; onOpen: (key: string) => void }) {
  const width = 820;
  const height = 540;
  const cx0 = width / 2;
  const cy0 = height / 2;
  const others = useMemo(() => {
    const seen = new Map<string, { node: GraphNode; links: GraphLink[] }>();
    for (const link of data.links) {
      const other = link.source.id === data.node.id ? link.target : link.source;
      const entry = seen.get(other.id) ?? { node: other, links: [] };
      entry.links.push(link);
      seen.set(other.id, entry);
    }
    return [...seen.values()];
  }, [data]);
  const radius = others.length > 14 ? 215 : 190;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full max-h-[580px] w-full" role="img" aria-label={`Links of ${data.node.name}`}>
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#66728a" />
        </marker>
      </defs>
      {others.map((entry, index) => {
        const angle = (index / Math.max(others.length, 1)) * Math.PI * 2 - Math.PI / 2;
        const x = cx0 + Math.cos(angle) * radius * 1.25;
        const y = cy0 + Math.sin(angle) * radius;
        const link = entry.links[0];
        const outgoing = link.source.id === data.node.id;
        const [x1, y1, x2, y2] = outgoing ? [cx0, cy0, x, y] : [x, y, cx0, cy0];
        const shorten = (ax: number, ay: number, bx: number, by: number, d: number) => {
          const len = Math.hypot(bx - ax, by - ay) || 1;
          return [bx - ((bx - ax) / len) * d, by - ((by - ay) / len) * d];
        };
        const [ex, ey] = shorten(x1, y1, x2, y2, 14);
        const anchor = Math.cos(angle) > 0.2 ? "start" : Math.cos(angle) < -0.2 ? "end" : "middle";
        return (
          <g key={entry.node.id} className="cursor-pointer" onClick={() => onOpen(entry.node.key)}>
            <line x1={x1} y1={y1} x2={ex} y2={ey} stroke={METHOD_COLOR[link.method] ?? "#66728a"} strokeOpacity={0.35 + link.confidence * 0.6}
                  strokeWidth={1 + link.confidence * 2} strokeDasharray={link.low_confidence ? "4 4" : undefined}
                  markerEnd={link.relation === "co_moves_with" ? undefined : "url(#arrow)"} />
            <circle cx={x} cy={y} r={7} fill={KIND_COLOR[entry.node.kind] ?? "#9aa6b8"} stroke="#0b0e14" strokeWidth={2} />
            <text x={x + (anchor === "start" ? 11 : anchor === "end" ? -11 : 0)} y={y + (anchor === "middle" ? (Math.sin(angle) > 0 ? 20 : -12) : 4)}
                  textAnchor={anchor} fontSize="11" fill="#dce2ec">
              {entry.node.name.length > 34 ? `${entry.node.name.slice(0, 33)}…` : entry.node.name}
            </text>
            <title>{`${link.relation.replaceAll("_", " ")} · ${METHOD_LABEL[link.method]} · confidence ${link.confidence.toFixed(2)}`}</title>
          </g>
        );
      })}
      <circle cx={cx0} cy={cy0} r={13} fill={KIND_COLOR[data.node.kind] ?? "#f0b44c"} stroke="#f0b44c" strokeWidth={2} />
      <text x={cx0} y={cy0 + 32} textAnchor="middle" fontSize="13" fontWeight="600" fill="#f0b44c">{data.node.name}</text>
    </svg>
  );
}

function LinkCard({ link, focus }: { link: GraphLink; focus?: string }) {
  const other = link.source.id === focus ? link.target : link.source;
  return (
    <li className="border-b border-line px-3 py-2.5 text-[12px]">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-fg">{link.source.name}</span>
        <ArrowRight size={11} className="text-faint" />
        <span className="font-medium text-fg">{link.target.name}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <Badge>{link.relation.replaceAll("_", " ")}</Badge>
        <span className="rounded-sm px-1.5 text-[10.5px] font-medium" style={{ color: METHOD_COLOR[link.method], border: `1px solid ${METHOD_COLOR[link.method]}55` }}>
          {METHOD_LABEL[link.method]}
        </span>
        <span className={cx("num text-[11px]", link.low_confidence ? "text-warn" : "text-dim")}>confidence {link.confidence.toFixed(2)}</span>
        {link.sign !== 0 && <span className="text-[11px] text-faint">{link.sign > 0 ? "same direction" : "opposite direction"}</span>}
        {link.review_status !== "accepted" && <Badge tone="gold">{link.review_status}</Badge>}
        {link.private && <Badge tone="info">Your organization</Badge>}
      </div>
      {link.description && <p className="mt-1.5 text-dim">{link.description}</p>}
      <p className="mt-1 text-[11px] text-faint">Basis: {link.confidence_basis}</p>
      {link.estimation && "observations" in link.estimation && (
        <p className="num mt-1 text-[11px] text-faint">
          r = {fmtNumber(link.magnitude, 3)} · {String(link.estimation.observations)} observations · s.e. {fmtNumber(Number(link.estimation.standard_error), 3)}
        </p>
      )}
      {link.evidence ? (
        <blockquote className="mt-1.5 border-l-2 border-gold/50 pl-2 text-[11.5px] text-dim">
          “{link.evidence.text.slice(0, 280)}{link.evidence.text.length > 280 ? "…" : ""}”
          <span className="mt-0.5 block text-[10.5px] text-faint">{link.evidence.document} · {link.evidence.location}</span>
        </blockquote>
      ) : (
        <p className="mt-1 truncate text-[11px] text-faint">
          Source: {link.source_ref.startsWith("https://") ? <a href={link.source_ref} target="_blank" rel="noreferrer noopener" className="text-info hover:underline">{link.source_ref}</a> : link.source_ref}
        </p>
      )}
      {other && <span className="sr-only">{other.name}</span>}
      {link.last_verified_at && <p className="mt-0.5 text-[10.5px] text-faint">Verified {fmtDate(link.last_verified_at)}</p>}
    </li>
  );
}

function Explore({ nodeKey, onOpen }: { nodeKey: string; onOpen: (key: string) => void }) {
  const [proposed, setProposed] = useState(false);
  const { data, error } = useApi<Neighborhood>(`/graph/nodes/${encodeURIComponent(nodeKey)}`, { proposed });
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton rows={10} />;
  return (
    <div className="grid h-full min-h-0 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="flex min-h-0 flex-col items-center justify-center p-2">
        {data.links.length === 0 ? <Empty title="No accepted links for this node" /> : <Radial data={data} onOpen={onOpen} />}
        <div className="flex flex-wrap justify-center gap-3 text-[10.5px] text-faint">
          {Object.entries(METHOD_LABEL).map(([key, label]) => (
            <span key={key} className="flex items-center gap-1"><span className="h-0.5 w-4" style={{ background: METHOD_COLOR[key] }} />{label}</span>
          ))}
          <span>dashed: confidence below 0.40</span>
          <label className="flex items-center gap-1"><input type="checkbox" checked={proposed} onChange={(e) => setProposed(e.target.checked)} /> show proposed</label>
        </div>
      </div>
      <div className="min-h-0 overflow-auto border-l border-line">
        <div className="border-b border-line px-3 py-2.5">
          <div className="text-[14px] font-semibold text-fg">{data.node.name}</div>
          <div className="text-[11px] text-faint">{data.node.kind.replaceAll("_", " ")}{data.node.has_series ? " · linked to a data series" : ""}</div>
          {data.node.description && <p className="mt-1 text-[12px] text-dim">{data.node.description}</p>}
        </div>
        <ul>{data.links.map((link) => <LinkCard key={link.id} link={link} focus={data.node.id} />)}</ul>
      </div>
    </div>
  );
}

function ScenarioView({ nodeKey }: { nodeKey: string }) {
  const [direction, setDirection] = useState<"rises" | "falls">("rises");
  const [minimum, setMinimum] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const { data, error } = useApi<Scenario>("/graph/scenario", { start: nodeKey, direction, min_confidence: minimum });
  if (error) return <ErrorNote error={error} />;
  return (
    <div className="p-3">
      <div className="mb-3 flex flex-wrap items-center gap-3 text-[12px]">
        <span className="text-dim">If <b className="text-fg">{data?.origin.name ?? "…"}</b></span>
        <select value={direction} onChange={(e) => setDirection(e.target.value as "rises" | "falls")}
                className="h-7 rounded border border-line-strong bg-ink px-1.5 text-fg">
          <option value="rises">moves up</option><option value="falls">moves down</option>
        </select>
        <label className="flex items-center gap-1.5 text-dim">minimum confidence
          <input type="range" min={0} max={0.9} step={0.1} value={minimum} onChange={(e) => setMinimum(Number(e.target.value))} />
          <span className="num w-8">{minimum.toFixed(1)}</span>
        </label>
      </div>
      {!data ? <Skeleton rows={8} /> : data.paths.length === 0 ? <Empty title="No accepted path starts here" /> : (
        <ol className="space-y-1">
          {data.paths.map((path, index) => (
            <li key={index} className="rounded border border-line">
              <button onClick={() => setOpen(open === index ? null : index)} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-raised">
                <span className={cx("w-14 shrink-0 text-[11px] font-semibold uppercase", path.effect === "rises" ? "text-up" : "text-down")}>{path.effect}</span>
                <span className="w-40 shrink-0 truncate text-[12.5px] text-fg sm:w-64" title={path.end.name}>{path.end.name}</span>
                <span className="hidden min-w-0 flex-1 truncate text-[11px] text-faint md:block">{path.steps.map((s) => s.node.name).slice(0, -1).join(" → ") || "direct"}</span>
                <span className="num w-24 shrink-0 text-right text-[11px] text-dim">
                  <span className="mr-1.5 inline-block h-1 w-10 rounded bg-raised align-middle"><span className="block h-1 rounded bg-gold" style={{ width: `${path.confidence * 100}%` }} /></span>
                  {path.confidence.toFixed(2)}
                </span>
              </button>
              {open === index && <ul className="border-t border-line">{path.steps.map((step) => <LinkCard key={step.link.id} link={step.link} />)}</ul>}
            </li>
          ))}
        </ol>
      )}
      {data && <p className="mt-3 text-[11px] text-faint">{data.label} {data.method}</p>}
    </div>
  );
}

function Review() {
  const { atLeast } = useSession();
  const { data, error, reload } = useApi<{ items: GraphLink[] }>("/graph/links/pending");
  const [message, setMessage] = useState<string | null>(null);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton rows={4} />;
  return (
    <div>
      {message && <p role="alert" className="px-3 py-1.5 text-[12px] text-down">{message}</p>}
      {data.items.length === 0 ? <Empty title="Nothing to review">Links your team proposes appear here until an administrator accepts or rejects them.</Empty> : (
        <ul>
          {data.items.map((link) => (
            <div key={link.id} className="relative">
              <LinkCard link={link} />
              {atLeast("admin") && (
                <div className="absolute top-2 right-3 flex gap-1">
                  {(["accepted", "rejected"] as const).map((decision) => (
                    <Button key={decision} size="sm" variant={decision === "accepted" ? "primary" : "ghost"} onClick={async () => {
                      setMessage(null);
                      try { await api.post(`/graph/links/${link.id}/review`, { decision }); reload(); } catch (failure) { setMessage(describeError(failure)); }
                    }}>{decision === "accepted" ? <Check size={11} /> : <X size={11} />}{decision === "accepted" ? "Accept" : "Reject"}</Button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </ul>
      )}
    </div>
  );
}

function GraphPage() {
  const params = useSearchParams();
  const router = useRouter();
  const { can, me } = useSession();
  const nodeKey = params.get("node") ?? "event:ecb-policy";
  const tab = (params.get("tab") as "explore" | "scenario" | "review") ?? "explore";
  const [query, setQuery] = useState("");
  const [proposing, setProposing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const term = useDebounced(query, 200);
  const nodes = useApi<{ items: GraphNode[] }>(can("graph.read") ? "/graph/nodes" : null, { q: term });
  const go = (key: string, next = tab) => router.replace(`/app/graph?node=${encodeURIComponent(key)}&tab=${next}`);
  if (!can("graph.read")) return <div className="p-2"><Panel title="Graph"><Locked feature="The Market Impact Graph" plan={me.tenant.plan_name} /></Panel></div>;

  async function propose(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    setMessage(null);
    try {
      await api.post("/graph/links", { source: value("source"), target: value("target"), relation: value("relation"),
        confidence: Number(value("confidence")), confidence_basis: value("basis"), source_ref: value("ref"),
        sign: Number(value("sign")), description: value("description") });
      setProposing(false);
      go(nodeKey, "review");
    } catch (failure) {
      setMessage(describeError(failure));
    }
  }

  const groups = (nodes.data?.items ?? []).reduce<Record<string, GraphNode[]>>((acc, node) => {
    (acc[node.kind] ??= []).push(node);
    return acc;
  }, {});

  return (
    <div className="grid h-full min-h-0 grid-cols-1 gap-2 p-2 lg:grid-cols-[260px_minmax(0,1fr)]">
      <Panel bodyClassName="flex flex-col">
        <div className="space-y-2 border-b border-line p-2.5">
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a node" aria-label="Find a node" />
          {can("graph.edit") && <Button size="sm" className="w-full" onClick={() => setProposing(true)}>Propose a link</Button>}
        </div>
        <div className="min-h-0 flex-1 overflow-auto py-1">
          {nodes.error ? <ErrorNote error={nodes.error} /> : !nodes.data ? <Skeleton rows={10} /> : Object.entries(groups).map(([kind, items]) => (
            <div key={kind} className="mb-1">
              <div className="px-3 pt-1.5 pb-0.5 text-[10px] tracking-wider text-faint uppercase">{kind.replaceAll("_", " ")}</div>
              {items.map((node) => (
                <button key={node.id} onClick={() => go(node.key)}
                        className={cx("flex w-full items-center gap-2 px-3 py-1 text-left text-[12px] hover:bg-raised", node.key === nodeKey && "bg-hover text-gold")}>
                  <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: KIND_COLOR[node.kind] }} />
                  <span className="truncate">{node.name}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      </Panel>
      <Panel bodyClassName="flex flex-col overflow-hidden">
        <Tabs value={tab} onChange={(next) => go(nodeKey, next)} options={[{ value: "explore", label: "Links" },
          { value: "scenario", label: "Impact scenario" }, { value: "review", label: "Review" }]} />
        <div className="min-h-0 flex-1 overflow-auto">
          {tab === "explore" && <Explore nodeKey={nodeKey} onOpen={(key) => go(key)} />}
          {tab === "scenario" && <ScenarioView nodeKey={nodeKey} />}
          {tab === "review" && <Review />}
        </div>
      </Panel>
      <Modal open={proposing} onClose={() => setProposing(false)} title="Propose a link" width="max-w-lg">
        <form onSubmit={propose} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="From (node key or name)"><Input name="source" required defaultValue={nodeKey} /></Field>
            <Field label="To"><Input name="target" required placeholder="sector:industrials" /></Field>
            <Field label="Relation">
              <select name="relation" className="h-8 w-full rounded border border-line-strong bg-ink px-2 text-[12.5px] text-fg">
                {["exposed_to", "transmits_to", "supplies", "buys_from", "competes_with", "belongs_to", "operates_in"].map((r) => <option key={r} value={r}>{r.replaceAll("_", " ")}</option>)}
              </select>
            </Field>
            <Field label="Direction">
              <select name="sign" className="h-8 w-full rounded border border-line-strong bg-ink px-2 text-[12.5px] text-fg">
                <option value="1">same direction</option><option value="-1">opposite direction</option><option value="0">not directional</option>
              </select>
            </Field>
            <Field label="Confidence (0–1)"><Input name="confidence" required inputMode="decimal" defaultValue="0.5" /></Field>
            <Field label="Source"><Input name="ref" required placeholder="URL, filing or memo" /></Field>
          </div>
          <Field label="Basis for the confidence"><Input name="basis" required /></Field>
          <Field label="Description"><Input name="description" /></Field>
          {message && <p role="alert" className="text-[12px] text-down">{message}</p>}
          <p className="text-[11px] text-faint">The link stays private to your organization and is used in scenarios only after an administrator accepts it.</p>
          <div className="flex justify-end"><Button type="submit" variant="primary">Propose</Button></div>
        </form>
      </Modal>
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<Skeleton rows={8} />}>
      <GraphPage />
    </Suspense>
  );
}
