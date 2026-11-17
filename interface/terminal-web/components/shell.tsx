"use client";

import {
  Bell, BookOpenText, BriefcaseBusiness, CandlestickChart, Database, FlaskConical, LayoutDashboard, LogOut,
  Network, Search, Settings, SlidersHorizontal,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { fmtAge, fmtPct, fmtPrice, tone, TYPE_LABEL } from "@/lib/format";
import { useApi, useDebounced, useHotkeys } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Dataset, Notification, SearchHit } from "@/lib/types";
import { Badge, cx, Modal } from "./ui";

const NAV = [
  { href: "/app", label: "Workspace", icon: LayoutDashboard, key: "w" },
  { href: "/app/markets", label: "Markets", icon: CandlestickChart, key: "m" },
  { href: "/app/screener", label: "Screener", icon: SlidersHorizontal, key: "s" },
  { href: "/app/intelligence", label: "Intelligence", icon: BookOpenText, key: "i" },
  { href: "/app/portfolio", label: "Portfolio", icon: BriefcaseBusiness, key: "p" },
  { href: "/app/quant", label: "Quant", icon: FlaskConical, key: "q" },
  { href: "/app/graph", label: "Graph", icon: Network, key: "g" },
  { href: "/app/datalab", label: "DataLab", icon: Database, key: "d" },
] as const;

const SHORTCUTS: [string, string][] = [
  ["⌘K  or  /", "Search instruments and commands"],
  ["g then w m s i p q g d", "Go to Workspace, Markets, Screener, Intelligence, Portfolio, Quant, Graph, DataLab"],
  ["g then ,", "Settings"],
  ["↑ ↓  Enter", "Move and select in lists"],
  ["Esc", "Close a dialog"],
  ["?", "This list"],
];

function isActive(pathname: string, href: string): boolean {
  return href === "/app" ? pathname === "/app" : pathname.startsWith(href);
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { me, signOut } = useSession();
  const [palette, setPalette] = useState(false);
  const [help, setHelp] = useState(false);

  const bindings = useMemo(() => {
    const map: Record<string, () => void> = {
      "mod+k": () => setPalette(true),
      "/": () => setPalette(true),
      "?": () => setHelp(true),
      "g ,": () => router.push("/app/settings"),
    };
    for (const item of NAV) map[`g ${item.key}`] = () => router.push(item.href);
    return map;
  }, [router]);
  useHotkeys(bindings);

  return (
    <div className="flex h-full flex-col bg-base">
      <header className="flex h-11 shrink-0 items-center gap-3 border-b border-line bg-ink px-3">
        <Link href="/app" className="flex items-center gap-2" aria-label="AUREX workspace">
          <span className="grid h-6 w-6 place-items-center rounded-sm bg-gold text-[11px] font-black text-ink">Au</span>
          <span className="hidden text-[13px] font-semibold tracking-[0.18em] text-fg sm:block">AUREX</span>
        </Link>
        <button
          onClick={() => setPalette(true)}
          className="flex h-7 min-w-0 flex-1 items-center gap-2 rounded border border-line-strong bg-base px-2.5 text-left text-faint hover:border-gold-dim sm:max-w-xl"
        >
          <Search size={13} />
          <span className="truncate text-[12px]">Search instruments, run a command, ask a question…</span>
          <kbd className="ml-auto hidden sm:block">⌘K</kbd>
        </button>
        <div className="ml-auto flex items-center gap-1">
          <Notifications />
          <Link
            href="/app/settings"
            title="Settings (g ,)"
            className={cx("grid h-7 w-7 place-items-center rounded text-dim hover:bg-hover hover:text-fg",
              pathname.startsWith("/app/settings") && "text-gold")}
          >
            <Settings size={15} />
          </Link>
          <div className="mx-1 hidden h-5 w-px bg-line md:block" />
          <div className="hidden min-w-0 text-right leading-tight md:block">
            <div className="max-w-40 truncate text-[11.5px] text-fg">{me.user.display_name}</div>
            <div className="max-w-40 truncate text-[10.5px] text-faint">{me.tenant.name}</div>
          </div>
          <button
            onClick={signOut}
            title="Sign out"
            className="grid h-7 w-7 place-items-center rounded text-dim hover:bg-hover hover:text-fg"
          >
            <LogOut size={14} />
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav aria-label="Modules" className="hidden w-[52px] shrink-0 flex-col border-r border-line bg-ink py-2 sm:flex xl:w-44">
          {NAV.map((item) => {
            const active = isActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                title={`${item.label} (g ${item.key})`}
                aria-current={active ? "page" : undefined}
                className={cx(
                  "mx-1.5 mb-0.5 flex h-8 items-center gap-2.5 rounded px-2.5 text-[12.5px]",
                  active ? "bg-hover text-gold" : "text-dim hover:bg-raised hover:text-fg",
                )}
              >
                <item.icon size={16} className="shrink-0" />
                <span className="hidden xl:block">{item.label}</span>
                <kbd className="ml-auto hidden border-0 bg-transparent text-faint xl:block">g {item.key}</kbd>
              </Link>
            );
          })}
        </nav>
        <main className="min-h-0 min-w-0 flex-1 overflow-auto">{children}</main>
      </div>

      <nav aria-label="Modules" className="flex h-12 shrink-0 items-stretch border-t border-line bg-ink sm:hidden">
        {NAV.filter((item) => ["w", "m", "i", "p", "d"].includes(item.key)).map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={cx("flex flex-1 flex-col items-center justify-center gap-0.5 text-[10px]",
              isActive(pathname, item.href) ? "text-gold" : "text-dim")}
          >
            <item.icon size={16} />
            {item.label}
          </Link>
        ))}
      </nav>

      <StatusBar onHelp={() => setHelp(true)} />
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
      <Modal open={help} onClose={() => setHelp(false)} title="Keyboard commands">
        <dl className="space-y-2.5">
          {SHORTCUTS.map(([keys, text]) => (
            <div key={keys} className="grid grid-cols-[150px_1fr] items-baseline gap-3">
              <dt className="num text-[11.5px] text-gold">{keys}</dt>
              <dd className="text-[12.5px] text-dim">{text}</dd>
            </div>
          ))}
        </dl>
      </Modal>
    </div>
  );
}

function StatusBar({ onHelp }: { onHelp: () => void }) {
  const { me } = useSession();
  const { data } = useApi<{ items: Dataset[] }>("/datalab/datasets");
  const [now, setNow] = useState<Date | null>(null);
  useEffect(() => {
    const update = () => setNow(new Date());
    const first = setTimeout(update, 0);
    const timer = setInterval(update, 20_000);
    return () => {
      clearTimeout(first);
      clearInterval(timer);
    };
  }, []);
  const attention = (data?.items ?? []).filter((d) => d.enabled && ["stale", "failed"].includes(d.status));
  const loaded = (data?.items ?? []).filter((d) => d.status === "ok").length;
  return (
    <footer className="hidden h-6 shrink-0 items-center gap-4 border-t border-line bg-ink px-3 text-[10.5px] text-faint sm:flex">
      <Link href="/app/datalab" className="flex items-center gap-1.5 hover:text-fg">
        <span className={cx("h-1.5 w-1.5 rounded-full", attention.length ? "bg-warn" : "bg-up")} />
        {data ? (attention.length ? `${attention.length} dataset${attention.length > 1 ? "s need" : " needs"} attention`
          : `${loaded} datasets current`) : "Checking data…"}
      </Link>
      <span title="Engine that writes AI answers. Figures always come from the financial engine.">
        AI: {me.deployment.ai_engine === "offline" ? "offline evidence engine" : me.deployment.ai_model}
      </span>
      <span>Plan: {me.tenant.plan_name}</span>
      <span className="ml-auto hidden lg:block">Analysis and simulation only. Not investment advice.</span>
      <button onClick={onHelp} className="hover:text-fg">
        <kbd>?</kbd> shortcuts
      </button>
      <span className="num">
        {now ? now.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) : "--:--"} UTC
      </span>
    </footer>
  );
}

function Notifications() {
  const [open, setOpen] = useState(false);
  const { data, reload } = useApi<{ unread: number; items: Notification[] }>("/markets/notifications");
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const timer = setInterval(reload, 60_000);
    return () => clearInterval(timer);
  }, [reload]);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => !box.current?.contains(event.target as Node) && setOpen(false);
    window.addEventListener("mousedown", close);
    return () => window.removeEventListener("mousedown", close);
  }, [open]);
  const unread = data?.unread ?? 0;
  return (
    <div ref={box} className="relative">
      <button
        onClick={() => setOpen((value) => !value)}
        aria-label={`Notifications, ${unread} unread`}
        className="relative grid h-7 w-7 place-items-center rounded text-dim hover:bg-hover hover:text-fg"
      >
        <Bell size={15} />
        {unread > 0 && (
          <span className="num absolute -top-0.5 -right-0.5 grid h-3.5 min-w-3.5 place-items-center rounded-full bg-gold px-0.5 text-[9px] font-bold text-ink">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-1 w-80 rounded-md border border-line-strong bg-panel shadow-xl shadow-black/50">
          <div className="flex h-9 items-center justify-between border-b border-line px-3">
            <span className="text-[11.5px] font-semibold tracking-wider text-dim uppercase">Notifications</span>
            {unread > 0 && (
              <button
                className="text-[11px] text-gold hover:underline"
                onClick={() => api.post("/markets/notifications/read", {}).then(reload)}
              >
                Mark all read
              </button>
            )}
          </div>
          <ul className="max-h-80 overflow-auto">
            {(data?.items ?? []).length === 0 && (
              <li className="px-3 py-6 text-center text-[12px] text-faint">
                Nothing yet. Alerts and thesis signals appear here.
              </li>
            )}
            {(data?.items ?? []).map((item) => (
              <li key={item.id} className={cx("border-b border-line px-3 py-2 last:border-0", !item.read && "bg-raised")}>
                <Link href={item.link || "/app"} onClick={() => setOpen(false)} className="block">
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-[12px] font-medium text-fg">{item.title}</span>
                    <span className="shrink-0 text-[10.5px] text-faint">{fmtAge(item.created_at)}</span>
                  </div>
                  {item.body && <p className="mt-0.5 text-[11.5px] text-dim">{item.body}</p>}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

type Command = { id: string; label: string; hint?: string; run: () => void };

function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const { setActive, signOut } = useSession();
  const [query, setQuery] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const term = useDebounced(query.trim(), 160);
  const { data, previous } = useApi<{ items: SearchHit[] }>(open ? "/markets/instruments" : null,
    { q: term, limit: 8 });
  const hits = useMemo(() => (data ?? previous)?.items ?? [], [data, previous]);

  const commands = useMemo<Command[]>(() => {
    const go = (href: string) => () => router.push(href);
    const all: Command[] = [
      ...NAV.map((item) => ({ id: item.href, label: `Go to ${item.label}`, hint: `g ${item.key}`, run: go(item.href) })),
      { id: "settings", label: "Go to Settings", hint: "g ,", run: go("/app/settings") },
      { id: "keys", label: "API keys", run: go("/app/settings?tab=api") },
      { id: "members", label: "Members and roles", run: go("/app/settings?tab=members") },
      { id: "plan", label: "Plan and billing", run: go("/app/settings?tab=plan") },
      { id: "licenses", label: "Data licenses", run: go("/app/datalab?tab=licenses") },
      { id: "signout", label: "Sign out", run: () => void signOut() },
    ];
    const needle = query.trim().toLowerCase();
    return needle ? all.filter((c) => c.label.toLowerCase().includes(needle)) : all.slice(0, 5);
  }, [query, router, signOut]);

  useEffect(() => {
    // A modal dialog focuses its first control (the close button); the search field is what is wanted.
    if (open) input.current?.focus();
  }, [open]);

  const asksQuestion = query.trim().split(/\s+/).length >= 3 || query.trim().endsWith("?");
  const rows = useMemo(() => {
    const list: { key: string; node: ReactNode; run: () => void }[] = [];
    if (asksQuestion) {
      list.push({
        key: "ask",
        node: (
          <>
            <BookOpenText size={14} className="text-gold" />
            <span className="truncate">Ask AUREX: “{query.trim()}”</span>
            <span className="ml-auto text-[10.5px] text-faint">answer with evidence</span>
          </>
        ),
        run: () => router.push(`/app/intelligence?q=${encodeURIComponent(query.trim())}`),
      });
    }
    for (const hit of hits) {
      const { instrument, quote } = hit;
      list.push({
        key: instrument.id,
        node: (
          <>
            <span className="num w-24 shrink-0 truncate font-medium text-fg">{instrument.symbol}</span>
            <span className="min-w-0 flex-1 truncate text-dim">{instrument.name}</span>
            <Badge>{TYPE_LABEL[instrument.type] ?? instrument.type}</Badge>
            {quote ? (
              <span className="num w-32 shrink-0 text-right">
                {fmtPrice(quote.last)} <span className={tone(quote.change_pct)}>{fmtPct(quote.change_pct)}</span>
              </span>
            ) : (
              <span className="w-32 shrink-0 text-right text-[10.5px] text-faint">no price data</span>
            )}
          </>
        ),
        run: () => {
          setActive(instrument.symbol);
          router.push(`/app/markets?symbol=${encodeURIComponent(instrument.symbol)}`);
        },
      });
    }
    for (const command of commands) {
      list.push({
        key: command.id,
        node: (
          <>
            <span className="text-faint">›</span>
            <span>{command.label}</span>
            {command.hint && <kbd className="ml-auto">{command.hint}</kbd>}
          </>
        ),
        run: command.run,
      });
    }
    return list;
  }, [asksQuestion, hits, commands, query, router, setActive]);

  const selected = Math.min(index, Math.max(rows.length - 1, 0));
  const close = () => {
    setQuery("");
    setIndex(0);
    onClose();
  };

  return (
    <Modal open={open} onClose={close} title="Search and commands" width="max-w-2xl">
      <div className="-m-4">
        <div className="flex items-center gap-2 border-b border-line px-4">
          <Search size={14} className="text-faint" />
          <input
            ref={input}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setIndex(0);
            }}
            onKeyDown={(event) => {
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setIndex(Math.min(selected + 1, rows.length - 1));
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setIndex(Math.max(selected - 1, 0));
              } else if (event.key === "Enter" && rows[selected]) {
                event.preventDefault();
                rows[selected].run();
                close();
              }
            }}
            placeholder="Symbol, company, command, or a question"
            aria-label="Search"
            className="h-11 w-full bg-transparent text-[13.5px] text-fg placeholder:text-faint focus:outline-none"
          />
        </div>
        <ul role="listbox" className="max-h-[52vh] overflow-auto py-1">
          {rows.length === 0 && <li className="px-4 py-6 text-center text-[12px] text-faint">No match.</li>}
          {rows.map((row, i) => (
            <li key={row.key} role="option" aria-selected={i === selected}>
              <button
                onMouseEnter={() => setIndex(i)}
                onClick={() => {
                  row.run();
                  close();
                }}
                className={cx("flex h-9 w-full items-center gap-3 px-4 text-left text-[12.5px]",
                  i === selected ? "bg-hover text-fg" : "text-dim")}
              >
                {row.node}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </Modal>
  );
}
