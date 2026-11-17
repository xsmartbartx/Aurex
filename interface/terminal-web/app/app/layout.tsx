import type { Metadata } from "next";
import { AppShell } from "@/components/shell";
import { SessionProvider } from "@/lib/session";

export const metadata: Metadata = { robots: { index: false } };


export default function TerminalLayout({ children }: LayoutProps<"/app">) {
  return (
    <SessionProvider>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
