"use client";

import { Check, ChevronDown, ChevronRight, Lock, Minus } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, useState } from "react";
import { FreshnessBadge } from "@/components/provenance";
import { Badge, Button, cx, Empty, ErrorNote, Panel, Skeleton, Tabs } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import { fmtAge, fmtDate, fmtDateTime, titleCase } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Dataset, License, Run } from "@/lib/types";

const STATUS_TONE = { ok: "up", stale: "gold", failed: "down", never_run: "neutral", not_configured: "gold" } as const;
const STATUS_TEXT: Record<string, string> = {
  ok: "Current", stale: "Stale", failed: "Failed", never_run: "Not loaded", not_configured: "Not configured",
};

function every(minutes: number): string {
  if (minutes < 120) return `every ${minutes} min`;
  if (minutes < 2880) return `every ${Math.round(minutes / 60)} h`;
  return `every ${Math.round(minutes / 1440)} d`;
}

function Runs({ dataset }: { dataset: Dataset }) {
  const { data, error } = useApi<{ items: Run[] }>(`/datalab/datasets/${dataset.code}/runs`, { limit: 8 });
  return (
    <div className="grid gap-4 bg-ink/60 px-4 py-3 lg:grid-cols-[1fr_320px]">
      <div>
        <div className="mb-1.5 text-[10.5px] tracking-wider text-faint uppercase">Recent runs</div>
        {error ? <ErrorNote error={error} /> : !data ? <Skeleton rows={3} /> : data.items.length === 0 ? (
          <p className="text-[12px] text-faint">No run recorded yet.</p>
        ) : (
          <table className="w-full text-[11.5px]">
            <thead className="text-left text-faint">
              <tr><th className="py-1 font-normal">Started</th><th className="font-normal">Result</th>
                <th className="font-normal">Stored</th><th className="font-normal">Quality</th></tr>
            </thead>
            <tbody>
              {data.items.map((run) => (
                <tr key={run.id} className="border-t border-line align-top">
                  <td className="num py-1 pr-3 whitespace-nowrap text-dim">{fmtDateTime(run.started_at)}</td>
                  <td className={cx("pr-3", run.status === "success" ? "text-up" : run.status === "failed" ? "text-down" : "text-dim")}>
                    {run.status}{run.error_code ? ` · ${run.error_code.replaceAll("_", " ")}` : ""}
                    {run.error_detail && <div className="text-faint">{run.error_detail}</div>}
                  </td>
                  <td className="num pr-3 text-dim">
                    {Object.entries(run.stored).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${k}`).join(", ") || "no change"}
                  </td>
                  <td className="num text-dim">
                    {Object.entries(run.quality).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${k.replaceAll("_", " ")}`).join(", ") || "clean"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="text-[11.5px] text-dim">
        <div className="mb-1.5 text-[10.5px] tracking-wider text-faint uppercase">Source and license</div>
        <p>{dataset.description}</p>
        <p className="mt-2 text-faint">{dataset.license.attribution}</p>
        {dataset.license.terms_url && (
          <a href={dataset.license.terms_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-info hover:underline">
            Provider terms
          </a>
        )}
      </div>
    </div>
  );
}

function Datasets() {
  const { me } = useSession();
  const { data, error, reload } = useApi<{ items: Dataset[] }>("/datalab/datasets");
  const [open, setOpen] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  if (error) return <ErrorNote error={error} onRetry={reload} />;
  if (!data) return <Skeleton rows={7} />;

  async function act(action: () => Promise<{ detail?: string } | unknown>, done: string) {
    try {
      const result = (await action()) as { detail?: string } | undefined;
      setMessage(result?.detail ?? done);
      reload();
    } catch (failure) {
      setMessage(describeError(failure));
    }
  }

  return (
    <>
      {message && <div className="border-b border-line px-4 py-1.5 text-[12px] text-dim" role="status">{message}</div>}
      <div className="overflow-x-auto">
        <table className="w-full min-w-[820px] border-collapse text-[12.5px]">
          <thead className="text-left text-[10.5px] tracking-wider text-faint uppercase">
            <tr className="border-b border-line">
              <th className="w-8" /><th className="py-2 font-medium">Dataset</th><th className="font-medium">Freshness</th>
              <th className="font-medium">Status</th><th className="font-medium">Latest data</th>
              <th className="font-medium">Imported</th><th className="font-medium">Schedule</th>
              <th className="pr-4 text-right font-medium">Content</th>
              {me.user.platform_admin && <th className="pr-3 text-right font-medium">Operations</th>}
            </tr>
          </thead>
          <tbody>
            {data.items.map((dataset) => (
              <Fragment key={dataset.id}>
                <tr className={cx("border-b border-line hover:bg-raised", !dataset.accessible && "opacity-60")}>
                  <td className="pl-3">
                    <button aria-label="Show runs" aria-expanded={open === dataset.code}
                            onClick={() => setOpen(open === dataset.code ? null : dataset.code)} className="text-faint hover:text-fg">
                      {open === dataset.code ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </button>
                  </td>
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2 font-medium text-fg">
                      {dataset.name}
                      {!dataset.accessible && <Lock size={11} className="text-faint" aria-label="Not in your plan" />}
                      {dataset.private && <Badge tone="info">Private</Badge>}
                    </div>
                    <div className="text-[11px] text-faint">{dataset.provider} · <span className="num">{dataset.code}</span></div>
                  </td>
                  <td><FreshnessBadge freshness={dataset.freshness_class} delay={dataset.license.required_delay_minutes} /></td>
                  <td>
                    <Badge tone={STATUS_TONE[dataset.status as keyof typeof STATUS_TONE] ?? "neutral"}>
                      {STATUS_TEXT[dataset.status] ?? dataset.status}
                    </Badge>
                    {dataset.status_detail && dataset.status !== "ok" && (
                      <div className="mt-0.5 max-w-56 text-[11px] text-faint">{dataset.status_detail}</div>
                    )}
                  </td>
                  <td className="num text-dim">{fmtDate(dataset.latest_ref_time)}</td>
                  <td className="num text-dim">{fmtAge(dataset.last_success_at)}</td>
                  <td className="text-dim">{dataset.enabled ? every(dataset.interval_minutes) : "paused"}</td>
                  <td className="num pr-4 text-right text-dim">
                    {[["series", dataset.counts.series], ["instruments", dataset.counts.instruments],
                      ["documents", dataset.counts.documents]].filter(([, n]) => Number(n) > 0)
                      .map(([k, n]) => `${Number(n).toLocaleString("en-US")} ${k}`).join(" · ") || "—"}
                  </td>
                  {me.user.platform_admin && (
                    <td className="pr-3">
                      {!dataset.private && (
                        <div className="flex justify-end gap-1">
                          {dataset.connector !== "sec_company" && (
                            <Button size="sm" onClick={() => act(() => api.post(`/datalab/datasets/${dataset.code}/run`), "Run queued")}>
                              Run now
                            </Button>
                          )}
                          <Button size="sm" variant="ghost"
                                  onClick={() => act(() => api.patch(`/datalab/datasets/${dataset.code}`, { enabled: !dataset.enabled }),
                                    dataset.enabled ? "Schedule paused" : "Schedule resumed")}>
                            {dataset.enabled ? "Pause" : "Resume"}
                          </Button>
                        </div>
                      )}
                    </td>
                  )}
                </tr>
                {open === dataset.code && (
                  <tr className="border-b border-line"><td colSpan={9}><Runs dataset={dataset} /></td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const USES: [keyof License, string][] = [
  ["allow_display", "Display"], ["allow_export", "Export"], ["allow_api", "API"], ["allow_derived", "Derived data"],
  ["allow_model_external", "External AI"], ["allow_model_local", "Local AI"],
];

function Licenses() {
  const { data, error } = useApi<{ items: License[] }>("/datalab/licenses");
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton rows={5} />;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] border-collapse text-[12.5px]">
        <thead className="text-left text-[10.5px] tracking-wider text-faint uppercase">
          <tr className="border-b border-line">
            <th className="py-2 pl-4 font-medium">License record</th><th className="font-medium">Class</th>
            {USES.map(([, label]) => <th key={label} className="text-center font-medium">{label}</th>)}
            <th className="pr-4 font-medium">Expires</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((license) => (
            <tr key={license.code} className="border-b border-line align-top">
              <td className="max-w-md py-2.5 pr-4 pl-4">
                <div className="font-medium text-fg">{license.provider} <span className="num text-[11px] text-faint">{license.code}</span></div>
                <div className="mt-0.5 text-[11.5px] text-dim">{license.notes}</div>
              </td>
              <td className="pt-2.5"><Badge tone={license.data_class === "demonstration" ? "demo" : license.data_class === "public" ? "info" : "gold"}>
                {titleCase(license.data_class)}</Badge></td>
              {USES.map(([key, label]) => (
                <td key={label} className="pt-2.5 text-center" title={`${label}: ${license[key] ? "permitted" : "not permitted"}`}>
                  {license[key] ? <Check size={14} className="inline text-up" aria-label="permitted" />
                    : <Minus size={14} className="inline text-faint" aria-label="not permitted" />}
                </td>
              ))}
              <td className="num pt-2.5 pr-4 text-dim">{license.expires_at ? fmtDate(license.expires_at) : "no expiry"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-4 py-3 text-[11.5px] text-faint">
        The register is enforced by the system at four points: ingestion, retrieval, AI context assembly and output.
        A use that is not permitted here is refused, including through the API and exports.
      </p>
    </div>
  );
}

function DataLab() {
  const params = useSearchParams();
  const [tab, setTab] = useState<"datasets" | "licenses">(params.get("tab") === "licenses" ? "licenses" : "datasets");
  return (
    <div className="h-full p-2">
      <Panel title="DataLab" bodyClassName="flex flex-col" className="h-full">
        <Tabs value={tab} onChange={setTab}
              options={[{ value: "datasets", label: "Datasets and freshness" }, { value: "licenses", label: "License register" }]} />
        <div className="min-h-0 flex-1 overflow-auto">{tab === "datasets" ? <Datasets /> : <Licenses />}</div>
      </Panel>
    </div>
  );
}

export default function DataLabPage() {
  return (
    <Suspense fallback={<Empty title="Loading DataLab" />}>
      <DataLab />
    </Suspense>
  );
}
