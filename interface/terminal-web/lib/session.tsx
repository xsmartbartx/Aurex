"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, ApiError } from "./api";
import { useStored } from "./hooks";
import type { Me } from "./types";

type Session = {
  me: Me;
  can: (entitlement: string) => boolean;
  atLeast: (role: "viewer" | "analyst" | "admin" | "owner") => boolean;
  reload: () => void;
  signOut: () => Promise<void>;
  /** The instrument the workspace is linked to. Panels follow it. */
  active: string;
  setActive: (symbol: string) => void;
};

const RANK = { viewer: 0, analyst: 1, admin: 2, owner: 3 } as const;
const Context = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [active, setActive] = useStored("active-instrument", "EURUSD");

  useEffect(() => {
    let cancelled = false;
    api.get<Me>("/auth/me").then(
      (data) => !cancelled && setMe(data),
      (error) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 401) {
          const next = window.location.pathname + window.location.search;
          router.replace(`/login?next=${encodeURIComponent(next)}`);
        } else {
          setFailed(error instanceof ApiError ? error.message : "The AUREX API is not reachable.");
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [router, tick]);

  const reload = useCallback(() => setTick((value) => value + 1), []);
  const signOut = useCallback(async () => {
    await api.post("/auth/logout").catch(() => undefined);
    router.replace("/login");
  }, [router]);

  const value = useMemo<Session | null>(() => {
    if (!me) return null;
    const entitlements = new Set(me.entitlements);
    return {
      me,
      can: (entitlement) => entitlements.has(entitlement),
      atLeast: (role) => RANK[me.role as keyof typeof RANK] >= RANK[role],
      reload,
      signOut,
      active,
      setActive,
    };
  }, [me, reload, signOut, active, setActive]);

  if (failed) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="max-w-sm rounded-md border border-line bg-panel p-5">
          <div className="mb-1 font-medium text-fg">Cannot reach the terminal backend</div>
          <p className="mb-4 text-dim">{failed}</p>
          <button
            className="rounded border border-line-strong px-3 py-1.5 text-fg hover:bg-hover"
            onClick={() => {
              setFailed(null);
              reload();
            }}
          >
            Try again
          </button>
        </div>
      </div>
    );
  }
  if (!value) {
    return (
      <div className="flex h-full items-center justify-center text-faint">
        <span className="num text-xs tracking-widest">AUREX · LOADING SESSION</span>
      </div>
    );
  }
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useSession(): Session {
  const session = useContext(Context);
  if (!session) throw new Error("useSession is used outside the terminal shell");
  return session;
}
