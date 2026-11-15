// Shapes returned by the API. Kept close to the wire format; optional fields are optional there too.

export type Provenance = {
  dataset: string;
  dataset_name: string;
  provider: string;
  license_class: string;
  attribution: string;
  terms_url: string;
  freshness_class: string;
  delay_minutes: number;
  status: string;
  last_success_at: string | null;
  latest_ref_time: string | null;
  export_allowed: boolean;
};

export type Instrument = {
  id: string;
  symbol: string;
  name: string;
  type: string;
  currency: string | null;
  venue: string | null;
  status: string;
  entity_id: string | null;
  dataset: string;
  license_class: string;
  has_prices: boolean;
};

export type Quote = {
  instrument_id: string;
  series_id: string;
  series_code: string;
  unit: string;
  currency: string | null;
  last: number | null;
  previous: number | null;
  change: number | null;
  change_pct: number | null;
  ref_time: string | null;
  freshness_class: string;
  status: string;
  license_class: string;
};

export type Series = {
  id: string;
  code: string;
  name: string;
  kind: string;
  unit: string;
  currency: string | null;
  frequency: string;
  has_ohlc: boolean;
  instrument_id: string | null;
  latest_ref_time: string | null;
  latest_value: number | null;
};

export type Point = {
  t: string;
  v: number;
  o: number | null;
  h: number | null;
  l: number | null;
  vol: number | null;
  q: string;
  known_at: string | null;
  version: number;
};

export type Indicator = { kind: string; window: number; lines: Record<string, (number | null)[]> };

export type ChartData = {
  series: Series;
  provenance: Provenance;
  as_of: string | null;
  interval: string;
  range: string;
  points: Point[];
  indicators: Indicator[];
  summary: {
    observations?: number;
    start?: string | null;
    end?: string | null;
    first?: number | null;
    last?: number | null;
    total_return?: number | null;
    cagr?: number | null;
    volatility?: number | null;
    sharpe?: number | null;
    max_drawdown?: number | null;
    high?: number | null;
    low?: number | null;
    engine_version: string;
  };
  quality: { suspect: number; demonstration: number };
};

export type Entity = {
  id: string;
  key: string;
  kind: string;
  name: string;
  ticker: string | null;
  cik: string | null;
  country: string | null;
  sector: string | null;
  industry: string | null;
  tracked: boolean;
  facts_synced_at: string | null;
};

export type InstrumentDetail = {
  instrument: Instrument;
  series: Series[];
  quote: Quote | null;
  entity: Entity | null;
  price_data: "available" | "not_licensed";
  price_data_note: string | null;
};

export type SearchHit = { instrument: Instrument; quote: Quote | null };

export type WatchlistItem = {
  id: string;
  instrument: Instrument;
  quote: Quote | null;
  pinned: boolean;
  position: number;
  note: string;
};

export type Watchlist = { id: string; name: string; shared: boolean; owner: boolean; items: WatchlistItem[] };

export type Me = {
  user: { id: string; email: string; display_name: string; platform_admin: boolean };
  tenant: { id: string; name: string; slug: string; plan: string; plan_name: string; status: string };
  role: string;
  entitlements: string[];
  limits: Record<string, number>;
  usage_today: Record<string, number>;
  memberships: { tenant_id: string; name: string; role: string }[];
  deployment: { mode: string; billing_enabled: boolean; ai_engine: string; ai_model: string };
};

export type License = {
  code: string;
  provider: string;
  data_class: string;
  terms_url: string;
  attribution: string;
  allow_display: boolean;
  allow_export: boolean;
  allow_api: boolean;
  allow_derived: boolean;
  allow_model_external: boolean;
  allow_model_local: boolean;
  required_delay_minutes: number;
  territories: string;
  expires_at: string | null;
  notes: string;
};

export type Dataset = {
  id: string;
  code: string;
  name: string;
  description: string;
  provider: string;
  connector: string;
  freshness_class: string;
  interval_minutes: number;
  enabled: boolean;
  status: string;
  status_detail: string;
  last_run_at: string | null;
  last_success_at: string | null;
  latest_ref_time: string | null;
  private: boolean;
  accessible: boolean;
  license: License;
  counts: Record<string, number>;
};

export type Run = {
  id: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  trigger: string;
  received: Record<string, number>;
  stored: Record<string, number>;
  quality: Record<string, number>;
  error_code: string;
  error_detail: string;
};

export type DocumentItem = {
  id: string;
  doc_type: string;
  title: string;
  url: string | null;
  published_at: string;
  entity_id: string | null;
  entity_name: string | null;
  passage_count: number;
  screening: string;
  private: boolean;
  dataset: string;
  license_class: string;
  attribution: string;
};

export type Notification = {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string;
  created_at: string;
  read: boolean;
};

export type CalendarEvent = { id: string; kind: string; title: string; scheduled_at: string; entity_id: string | null };

export type Workspace = {
  id: string;
  name: string;
  layout: { preset: string; panels: { type: string; config: Record<string, unknown> }[] };
  is_default: boolean;
};
