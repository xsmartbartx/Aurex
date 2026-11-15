// Number and date formatting. Finance conventions: tabular digits, explicit signs on changes, UTC dates.

const DASH = "—";

export function fmtNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return value.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** Price-like values: more decimals for small magnitudes (FX rates), fewer for large ones. */
export function fmtPrice(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  const abs = Math.abs(value);
  const digits = abs >= 1000 ? 2 : abs >= 10 ? 2 : abs >= 1 ? 4 : 5;
  return fmtNumber(value, digits);
}

export function fmtSigned(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return sign + fmtNumber(Math.abs(value), digits);
}

export function fmtPct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  return `${fmtSigned(value, digits)}%`;
}

/** A fraction (0.153) as a percentage (+15.30%). */
export function fmtRatioPct(value: number | null | undefined, digits = 2): string {
  return value === null || value === undefined ? DASH : fmtPct(value * 100, digits);
}

export function fmtCompact(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return DASH;
  const abs = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  if (abs >= 1e12) return `${sign}${(abs / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

export function tone(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "text-dim";
  return value > 0 ? "text-up" : "text-down";
}

export function fmtDate(value: string | Date | null | undefined): string {
  if (!value) return DASH;
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return DASH;
  return date.toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
}

export function fmtDateTime(value: string | Date | null | undefined): string {
  if (!value) return DASH;
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return DASH;
  return (
    date.toLocaleString("en-GB", {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "UTC",
    }) + " UTC"
  );
}

/** "3 h ago", "2 d ago". Used for data age, where relative time is what the reader needs. */
export function fmtAge(value: string | Date | null | undefined, now: Date = new Date()): string {
  if (!value) return DASH;
  const date = typeof value === "string" ? new Date(value) : value;
  const seconds = Math.max(0, (now.getTime() - date.getTime()) / 1000);
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400 * 2) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export const FRESHNESS_LABEL: Record<string, string> = {
  real_time: "Real-time",
  delayed: "Delayed",
  end_of_day: "End of day",
  historical: "Historical",
  demonstration: "Demonstration",
};

export const TYPE_LABEL: Record<string, string> = {
  equity: "Equity", etf: "ETF", index: "Index", bond: "Bond", fx: "FX", commodity: "Commodity",
  crypto: "Crypto", macro: "Macro", rate: "Rate",
};

export function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());
}
