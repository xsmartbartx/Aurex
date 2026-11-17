import Link from "next/link";
import type { ReactNode } from "react";

export function SiteHeader() {
  return (
    <header className="sticky top-0 z-20 border-b border-line/70 bg-base/85 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
        <Link href="/" className="flex items-center gap-2" aria-label="AUREX home">
          <span className="grid h-7 w-7 place-items-center rounded-sm bg-gold text-[12px] font-black text-ink">Au</span>
          <span className="text-[14px] font-semibold tracking-[0.2em]">AUREX</span>
        </Link>
        <nav className="hidden gap-5 text-[13px] text-dim md:flex">
          <Link href="/#modules" className="hover:text-fg">Modules</Link>
          <Link href="/#evidence" className="hover:text-fg">Evidence-first AI</Link>
          <Link href="/#deploy" className="hover:text-fg">Deployment</Link>
          <Link href="/pricing" className="hover:text-fg">Pricing</Link>
          <a href="/api/v1/docs" className="hover:text-fg">API</a>
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <Link href="/login" className="rounded px-3 py-1.5 text-[13px] text-dim hover:text-fg">Sign in</Link>
          <Link href="/signup" className="rounded bg-gold px-3 py-1.5 text-[13px] font-medium text-ink hover:bg-[#f6c468]">Start free</Link>
        </div>
      </div>
    </header>
  );
}

export function SiteFooter() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 py-10 text-[12.5px] text-dim md:grid-cols-4">
        <div className="md:col-span-2">
          <div className="mb-2 flex items-center gap-2">
            <span className="grid h-6 w-6 place-items-center rounded-sm bg-gold text-[11px] font-black text-ink">Au</span>
            <span className="font-semibold tracking-[0.2em] text-fg">AUREX</span>
          </div>
          <p className="max-w-sm text-faint">
            A financial research terminal for analysis, education and simulation. AUREX does not execute trades and does
            not give investment advice. Answers produced with AI are marked as such.
          </p>
        </div>
        <div className="space-y-1.5">
          <div className="text-[11px] tracking-wider text-faint uppercase">Product</div>
          <Link href="/pricing" className="block hover:text-fg">Pricing</Link>
          <a href="/api/v1/docs" className="block hover:text-fg">API reference</a>
          <Link href="/signup" className="block hover:text-fg">Create a workspace</Link>
        </div>
        <div className="space-y-1.5">
          <div className="text-[11px] tracking-wider text-faint uppercase">Legal</div>
          <Link href="/legal/terms" className="block hover:text-fg">Terms of service</Link>
          <Link href="/legal/privacy" className="block hover:text-fg">Privacy notice</Link>
          <Link href="/legal/ai" className="block hover:text-fg">AI and data sources</Link>
        </div>
      </div>
    </footer>
  );
}

export function SitePage({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-full bg-base">
      <SiteHeader />
      <main>{children}</main>
      <SiteFooter />
    </div>
  );
}

export function Prose({ title, updated, children }: { title: string; updated: string; children: ReactNode }) {
  return (
    <article className="mx-auto max-w-3xl px-4 py-12 text-[14px] leading-relaxed text-dim [&_h2]:mt-8 [&_h2]:mb-2 [&_h2]:text-[16px] [&_h2]:font-semibold [&_h2]:text-fg [&_li]:mt-1 [&_p]:mt-3 [&_ul]:mt-2 [&_ul]:list-disc [&_ul]:pl-5">
      <h1 className="text-[26px] font-semibold text-fg">{title}</h1>
      <p className="text-[12px] text-faint">Last updated {updated}</p>
      {children}
    </article>
  );
}
