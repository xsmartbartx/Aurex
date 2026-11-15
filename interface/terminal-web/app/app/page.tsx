"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { PANELS } from "@/components/panels";
import { Button, Empty, ErrorNote, Input, Panel, Segmented, Skeleton } from "@/components/ui";
import { api, describeError } from "@/lib/api";
import { useApi, useStored } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Workspace } from "@/lib/types";

type Layout = Workspace["layout"];
const PRESETS = [
  { value: "two-one", label: "2 + 1" }, { value: "one-two", label: "1 + 2" }, { value: "columns", label: "Columns" },
  { value: "rows", label: "Rows" }, { value: "grid", label: "Grid" }, { value: "single", label: "Single" },
] as const;

/** Grid placement per preset. Below the `lg` breakpoint every preset stacks into one column. */
function placement(preset: string, count: number, index: number): { grid: CSSProperties; cell: CSSProperties } {
  const side = Math.max(count - 1, 1);
  switch (preset) {
    case "single":
      return { grid: { gridTemplateColumns: "1fr" }, cell: {} };
    case "columns":
      return { grid: { gridTemplateColumns: `repeat(${Math.min(count, 4)}, minmax(0, 1fr))` }, cell: {} };
    case "rows":
      return { grid: { gridTemplateColumns: "1fr", gridAutoRows: "minmax(0, 1fr)" }, cell: {} };
    case "two-one":
      return {
        grid: { gridTemplateColumns: "minmax(0, 2fr) minmax(0, 1fr)", gridTemplateRows: `repeat(${side}, minmax(0, 1fr))` },
        cell: index === 0 ? { gridRow: `1 / span ${side}` } : {},
      };
    case "one-two":
      return {
        grid: { gridTemplateColumns: "minmax(0, 1fr) minmax(0, 2fr)", gridTemplateRows: `repeat(${side}, minmax(0, 1fr))` },
        cell: index === count - 1 ? { gridRow: `1 / span ${side}`, gridColumn: 2 } : { gridColumn: 1 },
      };
    default:
      return { grid: { gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gridAutoRows: "minmax(0, 1fr)" }, cell: {} };
  }
}

export default function WorkspacePage() {
  const { can, atLeast } = useSession();
  const { data, error, reload } = useApi<{ items: Workspace[] }>("/markets/workspaces");
  const [chosen, setChosen] = useStored<string | null>("workspace", null);
  const [draft, setDraft] = useState<{ id: string | null; name: string; layout: Layout } | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  if (error) return <ErrorNote error={error} onRetry={reload} />;
  if (!data) return <Skeleton rows={8} />;
  const workspace = data.items.find((w) => w.id === chosen) ?? data.items[0];
  const layout = draft?.layout ?? workspace.layout;
  const editable = can("markets.workspaces") && atLeast("analyst");

  async function save(asDefault = false) {
    if (!draft) return;
    setMessage(null);
    try {
      const body = { name: draft.name.trim() || "Workspace", layout: draft.layout, is_default: asDefault };
      const saved = draft.id ? await api.put<Workspace>(`/markets/workspaces/${draft.id}`, body)
        : await api.post<Workspace>("/markets/workspaces", body);
      setChosen(saved.id);
      setDraft(null);
      reload();
    } catch (failure) {
      setMessage(describeError(failure));
    }
  }

  const update = (next: Partial<Layout>) => draft && setDraft({ ...draft, layout: { ...draft.layout, ...next } });

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex min-h-10 shrink-0 flex-wrap items-center gap-2 border-b border-line px-3 py-1.5">
        {draft ? (
          <>
            <Input value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                   aria-label="Workspace name" maxLength={80} className="h-7 w-44" />
            <Segmented label="Layout" value={draft.layout.preset as (typeof PRESETS)[number]["value"]} options={PRESETS}
                       onChange={(preset) => update({ preset })} />
            <select
              aria-label="Add a panel" value=""
              disabled={draft.layout.panels.length >= 6}
              onChange={(event) => event.target.value && update({ panels: [...draft.layout.panels, { type: event.target.value, config: {} }] })}
              className="h-7 rounded border border-line-strong bg-ink px-1.5 text-[12px] text-fg"
            >
              <option value="">+ Add panel</option>
              {Object.entries(PANELS).map(([type, spec]) => <option key={type} value={type}>{spec.label}</option>)}
            </select>
            <div className="ml-auto flex items-center gap-1.5">
              {message && <span role="alert" className="text-[11.5px] text-down">{message}</span>}
              {draft.id && data.items.length > 1 && (
                <Button size="sm" variant="danger" onClick={async () => {
                  await api.delete(`/markets/workspaces/${draft.id}`);
                  setDraft(null);
                  setChosen(null);
                  reload();
                }}>Delete</Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => { setDraft(null); setMessage(null); }}>Cancel</Button>
              <Button size="sm" onClick={() => save(true)}>Save as default</Button>
              <Button size="sm" variant="primary" onClick={() => save(false)}>Save</Button>
            </div>
          </>
        ) : (
          <>
            <select aria-label="Workspace" value={workspace.id} onChange={(event) => setChosen(event.target.value)}
                    className="h-7 rounded border border-line-strong bg-ink px-1.5 text-[12.5px] font-medium text-fg">
              {data.items.map((w) => <option key={w.id} value={w.id}>{w.name}{w.is_default ? " · default" : ""}</option>)}
            </select>
            <span className="hidden text-[11.5px] text-faint md:block">
              Panels follow the selected instrument. Press <kbd>⌘K</kbd> to change it.
            </span>
            {editable && (
              <div className="ml-auto flex gap-1.5">
                <Button size="sm" variant="ghost" onClick={() => setDraft({ id: null, name: "New workspace", layout: workspace.layout })}>
                  <Plus size={12} /> New
                </Button>
                <Button size="sm" onClick={() => setDraft({ id: workspace.id, name: workspace.name, layout: workspace.layout })}>
                  Edit layout
                </Button>
              </div>
            )}
          </>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-2 lg:overflow-hidden">
        {layout.panels.length === 0 ? <Empty title="This workspace has no panels">Add a panel to begin.</Empty> : (
          <div className="grid gap-2 max-lg:!grid-cols-1 max-lg:!grid-rows-none lg:h-full"
               style={placement(layout.preset, layout.panels.length, 0).grid}>
            {layout.panels.map((panel, index) => {
              const spec = PANELS[panel.type];
              return (
                <Panel
                  key={`${panel.type}-${index}`}
                  title={draft ? (
                    <select aria-label="Panel type" value={panel.type}
                            onChange={(event) => update({ panels: layout.panels.map((p, i) => i === index ? { type: event.target.value, config: {} } : p) })}
                            className="h-6 rounded border border-line-strong bg-ink px-1 text-[11.5px] text-fg normal-case">
                      {Object.entries(PANELS).map(([type, item]) => <option key={type} value={type}>{item.label}</option>)}
                    </select>
                  ) : spec?.label ?? panel.type}
                  actions={draft && (
                    <button aria-label="Remove panel" className="text-faint hover:text-down"
                            onClick={() => update({ panels: layout.panels.filter((_, i) => i !== index) })}>
                      <Trash2 size={13} />
                    </button>
                  )}
                  style={placement(layout.preset, layout.panels.length, index).cell}
                  className="min-h-72 max-lg:!col-auto max-lg:!row-auto lg:min-h-0"
                  bodyClassName={spec?.scroll === false ? "overflow-hidden" : undefined}
                >
                  {spec ? spec.render(panel.config) : <Empty title="This panel type is not available" />}
                </Panel>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
