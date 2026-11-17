"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

type Query = Parameters<typeof api.get>[1];

type State<T> = { key: string | null; data?: T; error?: unknown };

/**
 * Read from the API. `data` belongs to the current request; while a new one is in flight `loading`
 * is true and `previous` keeps the last result so a panel can stay populated instead of blanking.
 */
export function useApi<T>(path: string | null, query?: Query) {
  const key = path === null ? null : JSON.stringify([path, query ?? null]);
  const [state, setState] = useState<State<T>>({ key: null });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    const [requestPath, requestQuery] = JSON.parse(key) as [string, Query];
    api.get<T>(requestPath, requestQuery ?? undefined).then(
      (data) => !cancelled && setState({ key, data }),
      (error) => !cancelled && setState({ key, error }),
    );
    return () => {
      cancelled = true;
    };
  }, [key, tick]);

  const current = state.key === key;
  const reload = useCallback(() => setTick((value) => value + 1), []);
  return {
    data: current ? state.data : undefined,
    previous: state.data,
    error: current ? state.error : undefined,
    loading: key !== null && !current,
    reload,
  };
}

export function useDebounced<T>(value: T, delay = 200): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

function isTyping(target: EventTarget | null): boolean {
  const element = target as HTMLElement | null;
  return !!element && (["INPUT", "TEXTAREA", "SELECT"].includes(element.tagName) || element.isContentEditable);
}

/**
 * Keyboard commands. Keys are written as "mod+k", "/", "?" or two-key sequences such as "g m".
 * Single keys and sequences are ignored while the user types in a field.
 */
export function useHotkeys(bindings: Record<string, () => void>) {
  const ref = useRef(bindings);
  useEffect(() => {
    ref.current = bindings;
  });
  useEffect(() => {
    let prefix = "";
    let timer: ReturnType<typeof setTimeout> | undefined;
    function onKey(event: KeyboardEvent) {
      const map = ref.current;
      const mod = event.metaKey || event.ctrlKey;
      if (mod && !event.altKey) {
        const handler = map[`mod+${event.key.toLowerCase()}`];
        if (handler) {
          event.preventDefault();
          handler();
        }
        return;
      }
      if (event.altKey || isTyping(event.target)) return;
      const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
      if (prefix) {
        const handler = map[`${prefix} ${key}`];
        prefix = "";
        clearTimeout(timer);
        if (handler) {
          event.preventDefault();
          handler();
        }
        return;
      }
      if (Object.keys(map).some((name) => name.startsWith(`${key} `))) {
        prefix = key;
        timer = setTimeout(() => (prefix = ""), 900);
        return;
      }
      const handler = map[event.key] ?? map[key];
      if (handler) {
        event.preventDefault();
        handler();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

/** Persist a small preference in the browser. Falls back to the default when storage is unavailable. */
export function useStored<T>(name: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(initial);
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(`aurex:${name}`);
      if (raw !== null) queueMicrotask(() => setValue(JSON.parse(raw) as T));
    } catch {
      /* storage blocked: keep the default */
    }
  }, [name]);
  const update = useCallback(
    (next: T) => {
      setValue(next);
      try {
        window.localStorage.setItem(`aurex:${name}`, JSON.stringify(next));
      } catch {
        /* ignore */
      }
    },
    [name],
  );
  return [value, update];
}
