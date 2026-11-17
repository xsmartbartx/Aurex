import { ArrowRight, BookOpenText, BriefcaseBusiness, CandlestickChart, CheckCircle2, Database, FlaskConical, Network, ShieldCheck } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";
import { SitePage } from "@/components/site";

export const metadata: Metadata = {
  title: "AUREX — the financial terminal you can check",
  description:
    "Market data, filings, portfolio risk, backtests and an impact graph in one terminal. Every number shows its " +
    "source, age and license, and every AI statement links to the evidence behind it.",
};

const MODULES = [
  { icon: CandlestickChart, name: "Markets", text: "Search, charts with indicators, watchlists, alerts, screener, correlations and an event calendar." },
  { icon: BookOpenText, name: "Intelligence", text: "Questions answered from filings, figures and your own documents, with every statement cited." },
  { icon: BriefcaseBusiness, name: "Portfolio", text: "Virtual portfolios with time-weighted returns, exposures, concentration, limits and stress scenarios." },
  { icon: FlaskConical, name: "Quant", text: "Point-in-time backtests with explicit costs and latency, out-of-sample reporting and seeded Monte Carlo." },
  { icon: Network, name: "Impact Graph", text: "How a policy decision travels through rates and currencies to sectors and companies, link by link." },
  { icon: Database, name: "DataLab", text: "Every dataset with its freshness, run history, quality flags and the license that governs its use." },
];

const DIFFERENCES = [
  ["Every figure in an AI answer comes from a calculation or a cited source field", "A claim verifier withholds statements the evidence does not support, and lists them."],
  ["Answers and backtests reproduce", "Each record keeps its data cut-off and engine version; one click re-runs the calculations."],
  ["Freshness and license next to every value", "Real-time, delayed, end-of-day, historical or demonstration — never mixed up silently."],
  ["No look-ahead in research", "Values are stored with the time they became known. Backtests see only what was published."],
  ["The API is the product", "The terminal uses the same public API you get with a key. Licenses are enforced on both."],
  ["Run it where your data must stay", "Locally, on your own servers or as a cloud service, with an offline AI engine when nothing may leave."],
];

export default function Home() {
  return (
    <SitePage>
      <section className="relative overflow-hidden border-b border-line">
        <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(240,180,76,0.12),transparent_60%)]" />
        <div className="relative mx-auto max-w-6xl px-4 pt-20 pb-16 text-center">
          <p className="mb-4 text-[12px] font-medium tracking-[0.25em] text-gold uppercase">Financial intelligence terminal</p>
          <h1 className="mx-auto max-w-3xl text-[38px] leading-[1.1] font-semibold tracking-tight text-fg md:text-[52px]">
            Research you can check, down to the source.
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-[16px] leading-relaxed text-dim">
            Market data, filings, portfolio risk, backtests and an impact graph in one terminal. Every number shows
            where it came from, how old it is and what its license allows. Every AI statement links to its evidence.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Link href="/signup" className="inline-flex items-center gap-2 rounded bg-gold px-5 py-2.5 text-[14px] font-medium text-ink hover:bg-[#f6c468]">
              Start with the free plan <ArrowRight size={15} />
            </Link>
            <Link href="/pricing" className="rounded border border-line-strong px-5 py-2.5 text-[14px] text-fg hover:bg-hover">See plans</Link>
          </div>
          <p className="mt-4 text-[12px] text-faint">Demonstration data and public sources included. No card required.</p>
        </div>
        <div className="relative mx-auto max-w-5xl px-4 pb-16">
          <div className="rounded-lg border border-line-strong bg-panel p-4 shadow-2xl shadow-black/50">
            <div className="mb-3 flex items-center gap-2 text-[11px] text-faint">
              <span className="rounded-sm bg-info/15 px-1.5 py-0.5 text-info">RESEARCH AGENT</span>
              Compare two companies on growth, cash flows, debt and rate sensitivity
            </div>
            <ul className="space-y-2 text-[13px]">
              {[
                ["Revenue growth in fiscal 2025 was 8.2%.", "E17"],
                ["Free cash flow in fiscal 2025 was USD 5.75 billion.", "E18"],
                ["Debt to equity in fiscal 2025 was 0.20x.", "E21"],
              ].map(([text, id]) => (
                <li key={id} className="flex items-start gap-2">
                  <CheckCircle2 size={14} className="mt-0.5 shrink-0 text-up" />
                  <span className="text-fg">{text}</span>
                  <span className="num rounded-sm bg-gold/15 px-1 text-[10.5px] font-semibold text-gold">{id}</span>
                </li>
              ))}
              <li className="flex items-start gap-2 text-dim italic">
                <span className="mt-0.5 text-[10px] font-semibold tracking-wide text-warn not-italic">INFERENCE</span>
                Higher policy rates would weigh more on the more leveraged of the two.
              </li>
            </ul>
            <div className="mt-3 rounded border border-warn/30 bg-warn/5 px-3 py-2 text-[12px] text-dim">
              Gaps: one statement was withheld because the cited evidence did not support it. Prices are demonstration data.
            </div>
          </div>
        </div>
      </section>

      <section id="evidence" className="mx-auto max-w-6xl px-4 py-20">
        <h2 className="text-[28px] font-semibold text-fg">Built to be verified</h2>
        <p className="mt-2 max-w-2xl text-[15px] text-dim">
          Cited answers are common now. AUREX goes further: the language model never originates a figure, and nothing it
          writes reaches you unchecked.
        </p>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {DIFFERENCES.map(([title, text]) => (
            <div key={title} className="rounded-md border border-line bg-panel p-5">
              <ShieldCheck size={18} className="mb-3 text-gold" />
              <h3 className="text-[14px] font-semibold text-fg">{title}</h3>
              <p className="mt-1.5 text-[13px] leading-relaxed text-dim">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="modules" className="border-y border-line bg-ink/50">
        <div className="mx-auto max-w-6xl px-4 py-20">
          <h2 className="text-[28px] font-semibold text-fg">One terminal, six modules</h2>
          <p className="mt-2 max-w-2xl text-[15px] text-dim">On one data model, so a filing, a price series, a portfolio and a scenario can be read together.</p>
          <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {MODULES.map(({ icon: Icon, name, text }) => (
              <div key={name} className="rounded-md border border-line bg-panel p-5">
                <Icon size={18} className="mb-3 text-gold" />
                <h3 className="text-[14px] font-semibold text-fg">{name}</h3>
                <p className="mt-1.5 text-[13px] leading-relaxed text-dim">{text}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="deploy" className="mx-auto max-w-6xl px-4 py-20">
        <div className="grid gap-10 md:grid-cols-2">
          <div>
            <h2 className="text-[28px] font-semibold text-fg">Your deployment, your data policy</h2>
            <p className="mt-3 text-[15px] leading-relaxed text-dim">
              The same build runs on a laptop, on your servers or as a managed cloud service. Organizations decide whether
              questions may reach an external model provider; data whose license does not allow it never does. Tenant
              data is isolated by the database itself, and every security-relevant action is written to an append-only
              audit trail.
            </p>
          </div>
          <ul className="space-y-3 text-[14px] text-dim">
            {["Row-level security on every tenant table", "Signed sessions, scoped API keys, role-based access",
              "License register enforced at ingestion, retrieval, AI context and output",
              "Content screening keeps instructions planted in documents away from agents",
              "Offline evidence engine for deployments where nothing may leave"].map((item) => (
              <li key={item} className="flex gap-2"><CheckCircle2 size={16} className="mt-0.5 shrink-0 text-up" />{item}</li>
            ))}
          </ul>
        </div>
      </section>

      <section className="border-t border-line">
        <div className="mx-auto max-w-6xl px-4 py-16 text-center">
          <h2 className="text-[26px] font-semibold text-fg">Open the terminal</h2>
          <p className="mt-2 text-[15px] text-dim">Start on Community with public and demonstration data. Upgrade when your team needs more.</p>
          <Link href="/signup" className="mt-6 inline-flex items-center gap-2 rounded bg-gold px-5 py-2.5 text-[14px] font-medium text-ink hover:bg-[#f6c468]">
            Create a workspace <ArrowRight size={15} />
          </Link>
        </div>
      </section>
    </SitePage>
  );
}
