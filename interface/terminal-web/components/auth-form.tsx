"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api, describeError } from "@/lib/api";
import { Button, Field, Input } from "./ui";

function safeNext(value: string | null): string {
  // Only same-site paths are followed after sign-in.
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/app";
}

export function AuthForm({ mode, inviteToken }: { mode: "login" | "signup" | "invite"; inviteToken?: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") {
        await api.post("/auth/login", { email: value("email"), password: String(form.get("password")) });
      } else if (mode === "signup") {
        await api.post("/auth/signup", {
          email: value("email"), password: String(form.get("password")), display_name: value("name"),
          organization: value("organization"),
        });
      } else {
        await api.post("/auth/invites/accept", {
          token: inviteToken, password: String(form.get("password")), display_name: value("name"),
        });
      }
      router.replace(safeNext(params.get("next")));
    } catch (failure) {
      setError(describeError(failure));
      setBusy(false);
    }
  }

  const title = { login: "Sign in", signup: "Create your workspace", invite: "Join your team" }[mode];
  return (
    <div className="flex min-h-full items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-6 flex items-center justify-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-sm bg-gold text-[12px] font-black text-ink">Au</span>
          <span className="text-[15px] font-semibold tracking-[0.2em]">AUREX</span>
        </Link>
        <form onSubmit={submit} className="space-y-3.5 rounded-md border border-line bg-panel p-5">
          <h1 className="text-[15px] font-semibold">{title}</h1>
          {mode === "invite" && (
            <p className="text-[12px] text-dim">
              Set a password for a new account, or enter the password of your existing AUREX account.
            </p>
          )}
          {mode === "signup" && (
            <Field label="Organization">
              <Input name="organization" required minLength={2} maxLength={120} autoComplete="organization"
                     placeholder="Your company or your own name" />
            </Field>
          )}
          {mode !== "login" && (
            <Field label="Your name">
              <Input name="name" maxLength={120} autoComplete="name" />
            </Field>
          )}
          {mode !== "invite" && (
            <Field label="Email">
              <Input name="email" type="email" required autoComplete="email" autoFocus={mode === "login"} />
            </Field>
          )}
          <Field label="Password"
                 hint={mode === "login" ? undefined : "At least 10 characters with an upper-case letter and a digit or symbol."}>
            <Input name="password" type="password" required minLength={mode === "login" ? 1 : 10}
                   autoComplete={mode === "login" ? "current-password" : "new-password"} />
          </Field>
          {error && (
            <p role="alert" className="rounded border border-down/30 bg-down/5 px-2.5 py-1.5 text-[12px] text-down">
              {error}
            </p>
          )}
          <Button type="submit" variant="primary" disabled={busy} className="w-full">
            {busy ? "Working…" : title}
          </Button>
          {mode === "signup" && (
            <p className="text-[11px] leading-relaxed text-faint">
              By creating a workspace you accept the <Link href="/legal/terms" className="underline">terms</Link> and
              the <Link href="/legal/privacy" className="underline">privacy notice</Link>. AUREX provides analysis
              and simulation, not investment advice.
            </p>
          )}
        </form>
        <p className="mt-4 text-center text-[12px] text-dim">
          {mode === "login" ? (
            <>No workspace yet? <Link href="/signup" className="text-gold hover:underline">Create one</Link></>
          ) : (
            <>Already registered? <Link href="/login" className="text-gold hover:underline">Sign in</Link></>
          )}
        </p>
      </div>
    </div>
  );
}
