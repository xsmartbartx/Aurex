"use client";

import { X } from "lucide-react";
import {
  useEffect, useRef, type ButtonHTMLAttributes, type CSSProperties, type InputHTMLAttributes, type ReactNode,
} from "react";
import { describeError } from "@/lib/api";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "default" | "ghost" | "danger";
  size?: "sm" | "md";
};

export function Button({ variant = "default", size = "md", className, ...props }: ButtonProps) {
  return (
    <button
      type="button"
      {...props}
      className={cx(
        "inline-flex shrink-0 items-center justify-center gap-1.5 rounded font-medium whitespace-nowrap",
        "transition-colors disabled:cursor-not-allowed disabled:opacity-45",
        size === "sm" ? "h-6 px-2 text-[11.5px]" : "h-8 px-3 text-[12.5px]",
        variant === "primary" && "bg-gold text-ink hover:bg-[#f6c468]",
        variant === "default" && "border border-line-strong bg-raised text-fg hover:bg-hover",
        variant === "ghost" && "text-dim hover:bg-hover hover:text-fg",
        variant === "danger" && "border border-down/40 text-down hover:bg-down/10",
        className,
      )}
    />
  );
}

export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        "h-8 w-full rounded border border-line-strong bg-ink px-2.5 text-[12.5px] text-fg",
        "placeholder:text-faint focus:border-gold-dim focus:outline-none",
        className,
      )}
    />
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11.5px] font-medium text-dim">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-faint">{hint}</span>}
    </label>
  );
}

const TONES = {
  neutral: "border-line-strong text-dim",
  gold: "border-gold/40 text-gold",
  up: "border-up/40 text-up",
  down: "border-down/40 text-down",
  info: "border-info/40 text-info",
  demo: "border-demo/40 text-demo",
} as const;

export function Badge({ tone = "neutral", children, title }: {
  tone?: keyof typeof TONES;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex h-[18px] items-center rounded-sm border px-1.5 text-[10.5px] font-medium tracking-wide uppercase",
        TONES[tone],
      )}
    >
      {children}
    </span>
  );
}

export function Panel({ title, actions, children, className, bodyClassName, footer, style }: {
  style?: CSSProperties;
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  footer?: ReactNode;
}) {
  return (
    <section style={style} className={cx("flex min-h-0 min-w-0 flex-col rounded-md border border-line bg-panel", className)}>
      {(title || actions) && (
        <header className="flex h-9 shrink-0 items-center justify-between gap-2 border-b border-line px-3">
          <h2 className="truncate text-[11.5px] font-semibold tracking-wider text-dim uppercase">{title}</h2>
          <div className="flex items-center gap-1">{actions}</div>
        </header>
      )}
      <div className={cx("min-h-0 flex-1 overflow-auto", bodyClassName)}>{children}</div>
      {footer && <footer className="shrink-0 border-t border-line px-3 py-1.5">{footer}</footer>}
    </section>
  );
}

export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T;
  options: readonly (T | { value: T; label: string })[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded border border-line-strong bg-ink p-px">
      {options.map((option) => {
        const item = typeof option === "string" ? { value: option, label: option } : option;
        return (
          <button
            key={item.value}
            type="button"
            aria-pressed={item.value === value}
            onClick={() => onChange(item.value)}
            className={cx(
              "num h-[22px] rounded-[3px] px-2 text-[11px]",
              item.value === value ? "bg-hover text-gold" : "text-dim hover:text-fg",
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex h-full min-h-24 flex-col items-center justify-center gap-1 px-6 py-8 text-center">
      <div className="text-[12.5px] font-medium text-dim">{title}</div>
      {children && <div className="max-w-sm text-[12px] text-faint">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div role="alert" className="m-3 rounded border border-down/30 bg-down/5 px-3 py-2 text-[12px] text-down">
      {describeError(error)}
      {onRetry && (
        <button className="ml-2 underline underline-offset-2" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 p-3" aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="skeleton h-4" style={{ width: `${88 - ((index * 17) % 40)}%` }} />
      ))}
    </div>
  );
}

export function Stat({ label, value, className, title }: {
  label: string;
  value: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <div title={title} className="min-w-0">
      <div className="truncate text-[10.5px] tracking-wide text-faint uppercase">{label}</div>
      <div className={cx("num truncate text-[13px]", className)}>{value}</div>
    </div>
  );
}

export function Modal({ open, onClose, title, children, width = "max-w-md" }: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  width?: string;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(event) => event.target === ref.current && onClose()}
      className={cx(
        "m-auto w-[calc(100%-2rem)] rounded-md border border-line-strong bg-panel p-0 text-fg",
        "backdrop:bg-black/60",
        width,
      )}
    >
      {open && (
        <>
          <div className="flex h-10 items-center justify-between border-b border-line px-4">
            <h2 className="text-[13px] font-semibold">{title}</h2>
            <button aria-label="Close" onClick={onClose} className="text-faint hover:text-fg">
              <X size={15} />
            </button>
          </div>
          <div className="p-4">{children}</div>
        </>
      )}
    </dialog>
  );
}

export function Tabs<T extends string>({ value, options, onChange }: {
  value: T;
  options: readonly { value: T; label: string; count?: number }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="tablist" className="flex gap-4 border-b border-line px-3">
      {options.map((option) => (
        <button
          key={option.value}
          role="tab"
          aria-selected={option.value === value}
          onClick={() => onChange(option.value)}
          className={cx(
            "-mb-px h-9 border-b-2 text-[12px] font-medium",
            option.value === value ? "border-gold text-fg" : "border-transparent text-dim hover:text-fg",
          )}
        >
          {option.label}
          {option.count !== undefined && <span className="num ml-1.5 text-faint">{option.count}</span>}
        </button>
      ))}
    </div>
  );
}

/** Shown where a plan does not include a feature. Says what is missing and where to change it. */
export function Locked({ feature, plan }: { feature: string; plan: string }) {
  return (
    <Empty title={`${feature} is not part of the ${plan} plan`}>
      An organization owner can change the plan under Settings → Plan.
    </Empty>
  );
}
