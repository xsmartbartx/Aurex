"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState, type FormEvent } from "react";
import { api, describeError } from "@/lib/api";
import { Button, Field, Input } from "./ui";

type Mode = "login" | "signup" | "invite" | "forgot" | "reset";

const PASSWORD_HINT = "At least 10 characters with an upper-case letter and a digit or symbol.";

function safeNext(value: string | null): string {
  // Only same-site paths are followed after sign-in.
  return value && value.startsWith("/") && !value.startsWith("//") ? value : "/app";
}

export function AuthForm({ mode, token }: { mode: Mode; token?: string }) {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // After "forgot": whether this deployment sends email, so the page can say what happens next.
  const [requested, setRequested] = useState<{ emailEnabled: boolean } | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const value = (name: string) => String(form.get(name) ?? "").trim();
    const password = String(form.get("password") ?? "");
    if (mode === "reset" && password !== String(form.get("confirm") ?? "")) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (mode === "login") {
        await api.post("/auth/login", { email: value("email"), password });
      } else if (mode === "signup") {
        await api.post("/auth/signup", {
          email: value("email"), password, display_name: value("name"), organization: value("organization"),
        });
      } else if (mode === "invite") {
        await api.post("/auth/invites/accept", { token, password, display_name: value("name") });
      } else if (mode === "forgot") {
        const answer = await api.post<{ email_enabled: boolean }>("/auth/password/forgot", { email: value("email") });
        setRequested({ emailEnabled: answer.email_enabled });
        setBusy(false);
        return;
      } else {
        await api.post("/auth/password/reset", { token, password });
        router.replace("/login?reset=1");
        return;
      }
      router.replace(safeNext(params.get("next")));
    } catch (failure) {
      setError(describeError(failure));
      setBusy(false);
    }
  }

  const title = {
    login: "Sign in", signup: "Create your workspace", invite: "Join your team",
    forgot: "Reset your password", reset: "Choose a new password",
  }[mode];
  const button = { forgot: "Send reset link", reset: "Set new password" }[mode as "forgot" | "reset"] ?? title;
  const asksForEmail = mode === "login" || mode === "signup" || mode === "forgot";
  const asksForName = mode === "signup" || mode === "invite";
  const newPassword = mode !== "login";

  return (
    <div className="flex min-h-full items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">
        <Link href="/" className="mb-6 flex items-center justify-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-sm bg-gold text-[12px] font-black text-ink">Au</span>
          <span className="text-[15px] font-semibold tracking-[0.2em]">AUREX</span>
        </Link>
        {requested ? (
          <div role="status" className="space-y-3 rounded-md border border-line bg-panel p-5">
            <h1 className="text-[15px] font-semibold">{title}</h1>
            {requested.emailEnabled ? (
              <p className="text-[12.5px] leading-relaxed text-dim">
                If an account uses that address, a link to set a new password is on its way. It works once, for one
                hour. Nothing arrived? Check spam, or ask your workspace administrator.
              </p>
            ) : (
              <p className="text-[12.5px] leading-relaxed text-dim">
                This AUREX deployment does not send email. Ask the administrator of this deployment for a password
                reset link.
              </p>
            )}
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-3.5 rounded-md border border-line bg-panel p-5">
            <h1 className="text-[15px] font-semibold">{title}</h1>
            {mode === "login" && params.get("reset") === "1" && (
              <p role="status" className="rounded border border-up/30 bg-up/5 px-2.5 py-1.5 text-[12px] text-up">
                Your password was changed. Sign in with the new one.
              </p>
            )}
            {mode === "invite" && (
              <p className="text-[12px] text-dim">
                Set a password for a new account, or enter the password of your existing AUREX account.
              </p>
            )}
            {mode === "forgot" && (
              <p className="text-[12px] text-dim">Enter the email of your account and we will send you a reset link.</p>
            )}
            {mode === "signup" && (
              <Field label="Organization">
                <Input name="organization" required minLength={2} maxLength={120} autoComplete="organization"
                       placeholder="Your company or your own name" />
              </Field>
            )}
            {asksForName && (
              <Field label="Your name">
                <Input name="name" maxLength={120} autoComplete="name" />
              </Field>
            )}
            {asksForEmail && (
              <Field label="Email">
                <Input name="email" type="email" required autoComplete="email"
                       autoFocus={mode === "login" || mode === "forgot"} />
              </Field>
            )}
            {mode !== "forgot" && (
              <Field label={mode === "reset" ? "New password" : "Password"} hint={newPassword ? PASSWORD_HINT : undefined}>
                <Input name="password" type="password" required minLength={newPassword ? 10 : 1}
                       autoComplete={newPassword ? "new-password" : "current-password"} autoFocus={mode === "reset"} />
              </Field>
            )}
            {mode === "reset" && (
              <Field label="Repeat the new password">
                <Input name="confirm" type="password" required minLength={10} autoComplete="new-password" />
              </Field>
            )}
            {mode === "login" && (
              <p className="-mt-1 text-right text-[11.5px]">
                <Link href="/forgot-password" className="text-dim hover:text-gold hover:underline">Forgot password?</Link>
              </p>
            )}
            {error && (
              <p role="alert" className="rounded border border-down/30 bg-down/5 px-2.5 py-1.5 text-[12px] text-down">
                {error}
              </p>
            )}
            <Button type="submit" variant="primary" disabled={busy} className="w-full">
              {busy ? "Working…" : button}
            </Button>
            {mode === "signup" && (
              <p className="text-[11px] leading-relaxed text-faint">
                By creating a workspace you accept the <Link href="/legal/terms" className="underline">terms</Link> and
                the <Link href="/legal/privacy" className="underline">privacy notice</Link>. AUREX provides analysis
                and simulation, not investment advice.
              </p>
            )}
          </form>
        )}
        <p className="mt-4 text-center text-[12px] text-dim">
          {mode === "login" ? (
            <>No workspace yet? <Link href="/signup" className="text-gold hover:underline">Create one</Link></>
          ) : (
            <>{mode === "signup" || mode === "invite" ? "Already registered?" : "Remembered it?"}{" "}
              <Link href="/login" className="text-gold hover:underline">Sign in</Link></>
          )}
        </p>
      </div>
    </div>
  );
}
