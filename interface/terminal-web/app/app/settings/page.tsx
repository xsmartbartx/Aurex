"use client";

import { Check, Copy, Download, KeyRound, Trash2 } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";
import { Badge, Button, cx, Empty, ErrorNote, Field, Input, Locked, Panel, Skeleton, Tabs } from "@/components/ui";
import { API, api, describeError } from "@/lib/api";
import { fmtAge, fmtDate, fmtDateTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useSession } from "@/lib/session";

type Tab = "profile" | "organization" | "members" | "api" | "plan" | "audit" | "platform";

function useAction() {
  const [message, setMessage] = useState<{ text: string; error: boolean } | null>(null);
  async function run(action: () => Promise<unknown>, done?: string) {
    setMessage(null);
    try {
      await action();
      if (done) setMessage({ text: done, error: false });
      return true;
    } catch (failure) {
      setMessage({ text: describeError(failure), error: true });
      return false;
    }
  }
  const note = message && (
    <p role={message.error ? "alert" : "status"} className={cx("text-[12px]", message.error ? "text-down" : "text-up")}>{message.text}</p>
  );
  return { run, note };
}

function Profile() {
  const { me } = useSession();
  const router = useRouter();
  const { run, note } = useAction();
  return (
    <div className="max-w-md space-y-4 p-4">
      <div className="text-[12.5px] text-dim">
        <div className="text-fg">{me.user.display_name}</div>
        <div>{me.user.email}</div>
        <div className="mt-1 text-faint">Role in {me.tenant.name}: {me.role}</div>
      </div>
      <form className="space-y-3" onSubmit={async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        if (await run(() => api.post("/auth/password", { current: form.get("current"), new: form.get("new") }))) {
          router.replace("/login");
        }
      }}>
        <h2 className="text-[13px] font-semibold">Change password</h2>
        <Field label="Current password"><Input name="current" type="password" required autoComplete="current-password" /></Field>
        <Field label="New password" hint="At least 10 characters with an upper-case letter and a digit or symbol. All sessions end.">
          <Input name="new" type="password" required minLength={10} autoComplete="new-password" />
        </Field>
        {note}
        <Button type="submit" variant="primary">Change password</Button>
      </form>
      {me.memberships.length > 1 && (
        <div className="space-y-2">
          <h2 className="text-[13px] font-semibold">Organizations</h2>
          {me.memberships.map((m) => (
            <button key={m.tenant_id} disabled={m.tenant_id === me.tenant.id}
                    onClick={() => run(() => api.post("/auth/switch-tenant", { tenant_id: m.tenant_id })).then((ok) => ok && window.location.reload())}
                    className="flex w-full justify-between rounded border border-line px-3 py-2 text-left text-[12.5px] hover:bg-raised disabled:opacity-60">
              <span>{m.name}</span><span className="text-faint">{m.tenant_id === me.tenant.id ? "current" : m.role}</span>
            </button>
          ))}
        </div>
      )}
      <YourData />
    </div>
  );
}

function YourData() {
  const { me } = useSession();
  const router = useRouter();
  const { run, note } = useAction();
  const [confirming, setConfirming] = useState(false);
  const link = "inline-flex h-8 items-center gap-1.5 rounded border border-line-strong px-3 text-[12.5px] hover:bg-raised";
  return (
    <div className="space-y-3 border-t border-line pt-4">
      <h2 className="text-[13px] font-semibold">Your data</h2>
      <p className="text-[12px] text-dim">
        Download a copy of what AUREX stores about you, or delete your account. See the{" "}
        <a href="/legal/privacy" className="underline">privacy notice</a>.
      </p>
      <div className="flex flex-wrap gap-2">
        <a href={`${API}/auth/me/export`} download className={link}><Download size={12} /> My data</a>
        {me.role === "owner" && (
          <a href={`${API}/org/export`} download className={link}><Download size={12} /> {me.tenant.name} data</a>
        )}
      </div>
      {!confirming ? (
        <Button variant="danger" onClick={() => setConfirming(true)}>Delete my account…</Button>
      ) : (
        <form className="space-y-3 rounded border border-down/40 bg-down/5 p-3" onSubmit={async (event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          if (await run(() => api.post("/auth/me/delete", { password: String(form.get("password")) }))) {
            router.replace("/");
          }
        }}>
          <p className="text-[12px] leading-relaxed text-fg">
            Your account is deleted now and cannot be restored. Organizations where you are the only member are
            closed with all their data: watchlists, portfolios, research, imports and API keys. In organizations with
            other members you just leave. Download your data first if you want a copy. Security records and invoices
            are kept as the law requires.
          </p>
          <Field label="Your password"><Input name="password" type="password" required autoComplete="current-password" /></Field>
          {note}
          <div className="flex gap-2">
            <Button type="submit" variant="danger">Delete my account</Button>
            <Button type="button" variant="ghost" onClick={() => setConfirming(false)}>Cancel</Button>
          </div>
        </form>
      )}
    </div>
  );
}

type Org = { name: string; slug: string; plan: string; model_policy: { external_models: string }; email_configured: boolean };

function Organization() {
  const { me, atLeast } = useSession();
  const { data, error, reload } = useApi<Org>("/org");
  const { run, note } = useAction();
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton rows={4} />;
  return (
    <div className="max-w-xl space-y-5 p-4">
      <form className="space-y-3" onSubmit={async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        await run(() => api.patch("/org", { name: String(form.get("name")) }), "Saved.");
        reload();
      }}>
        <Field label="Organization name"><Input name="name" defaultValue={data.name} disabled={!atLeast("admin")} required minLength={2} maxLength={120} /></Field>
        {atLeast("admin") && <Button type="submit">Save</Button>}
      </form>
      <div className="space-y-2">
        <h2 className="text-[13px] font-semibold">AI data policy</h2>
        <p className="text-[12px] text-dim">
          Whether questions and the data they retrieve may be sent to an external model provider. With “deny”, answers
          are written by the offline evidence engine inside this deployment. Data your licenses do not clear for external
          models is never sent, whatever this setting.
        </p>
        <div className="flex gap-2">
          {(["allow", "deny"] as const).map((value) => (
            <Button key={value} variant={data.model_policy.external_models === value ? "primary" : "default"} disabled={me.role !== "owner"}
                    onClick={async () => { await run(() => api.patch("/org", { external_models: value }), "Policy updated."); reload(); }}>
              {value === "allow" ? "Allow external models" : "Keep data in this deployment"}
            </Button>
          ))}
        </div>
        {me.role !== "owner" && <p className="text-[11px] text-faint">Only the owner changes this policy.</p>}
      </div>
      {note}
    </div>
  );
}

type Members = {
  items: { user_id: string; email: string; display_name: string; role: string; joined_at: string; last_login_at: string | null; you: boolean }[];
  invites: { id: string; email: string; role: string; expires_at: string }[];
  limit: number;
};

function MembersTab() {
  const { me, can, atLeast } = useSession();
  const { data, error, reload } = useApi<Members>("/org/members");
  const { run, note } = useAction();
  const [link, setLink] = useState<string | null>(null);
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton rows={5} />;
  const admin = atLeast("admin");
  return (
    <div className="space-y-4 p-4">
      {admin && (can("org.members") ? (
        <form className="flex flex-wrap items-end gap-2" onSubmit={async (event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          await run(async () => {
            const result = await api.post<{ emailed: boolean; link: string | null }>("/org/invites",
              { email: String(form.get("email")), role: String(form.get("role")) });
            setLink(result.link);
          }, "Invitation created.");
          reload();
        }}>
          <Field label="Invite by email"><Input name="email" type="email" required className="w-64" /></Field>
          <Field label="Role">
            <select name="role" className="h-8 rounded border border-line-strong bg-ink px-2 text-[12.5px] text-fg">
              <option value="analyst">Analyst</option><option value="viewer">Viewer</option><option value="admin">Administrator</option>
            </select>
          </Field>
          <Button type="submit" variant="primary">Invite</Button>
          <span className="pb-2 text-[11px] text-faint">{data.items.length} of {data.limit >= 1_000_000 ? "unlimited" : data.limit} seats</span>
        </form>
      ) : <Locked feature="Team members" plan={me.tenant.plan_name} />)}
      {link && (
        <div className="rounded border border-gold/40 bg-gold/5 p-2.5 text-[12px]">
          Email is not configured on this deployment. Send this one-time link to the person you invited:
          <div className="mt-1.5 flex items-center gap-2">
            <code className="num min-w-0 flex-1 truncate rounded bg-ink px-2 py-1 text-[11px]">{link}</code>
            <Button size="sm" onClick={() => navigator.clipboard.writeText(link)}><Copy size={11} /> Copy</Button>
          </div>
        </div>
      )}
      {note}
      <table className="w-full text-[12.5px]">
        <thead className="text-left text-[10.5px] tracking-wider text-faint uppercase">
          <tr className="border-b border-line"><th className="py-1.5 font-medium">Member</th><th className="font-medium">Role</th>
            <th className="font-medium">Joined</th><th className="font-medium">Last sign-in</th><th /></tr>
        </thead>
        <tbody>
          {data.items.map((member) => (
            <tr key={member.user_id} className="border-b border-line/60">
              <td className="py-2"><div className="text-fg">{member.display_name}{member.you && <span className="ml-1.5 text-faint">(you)</span>}</div>
                <div className="text-[11px] text-faint">{member.email}</div></td>
              <td>
                {admin && !member.you ? (
                  <select value={member.role} onChange={async (event) => { await run(() => api.patch(`/org/members/${member.user_id}`, { role: event.target.value })); reload(); }}
                          className="h-7 rounded border border-line-strong bg-ink px-1.5 text-[12px] text-fg">
                    {["owner", "admin", "analyst", "viewer"].map((role) => <option key={role} value={role}>{role}</option>)}
                  </select>
                ) : <Badge>{member.role}</Badge>}
              </td>
              <td className="num text-dim">{fmtDate(member.joined_at)}</td>
              <td className="text-dim">{fmtAge(member.last_login_at)}</td>
              <td className="text-right">
                {admin && !member.you && (
                  <button aria-label={`Remove ${member.email}`} className="text-faint hover:text-down"
                          onClick={async () => { if (window.confirm(`Remove ${member.email} from the organization?`)) { await run(() => api.delete(`/org/members/${member.user_id}`)); reload(); } }}>
                    <Trash2 size={13} />
                  </button>
                )}
              </td>
            </tr>
          ))}
          {data.invites.map((invite) => (
            <tr key={invite.id} className="border-b border-line/60 text-dim">
              <td className="py-2">{invite.email}<div className="text-[11px] text-faint">invited · expires {fmtDate(invite.expires_at)}</div></td>
              <td><Badge tone="gold">{invite.role}</Badge></td><td /><td />
              <td className="text-right">
                <button aria-label="Revoke invitation" className="text-faint hover:text-down"
                        onClick={async () => { await run(() => api.delete(`/org/invites/${invite.id}`)); reload(); }}><Trash2 size={13} /></button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

type Key = { id: string; name: string; prefix: string; created_at: string; last_used_at: string | null; own: boolean };

function ApiKeys() {
  const { can, me } = useSession();
  const { data, error, reload } = useApi<Key[]>(can("api.keys") ? "/auth/api-keys" : null);
  const { run, note } = useAction();
  const [secret, setSecret] = useState<string | null>(null);
  if (!can("api.keys")) return <Locked feature="API access" plan={me.tenant.plan_name} />;
  if (error) return <ErrorNote error={error} />;
  return (
    <div className="max-w-3xl space-y-4 p-4">
      <p className="text-[12.5px] text-dim">
        Every function of the terminal is available through the REST API. Send the key as <code className="num text-fg">Authorization: Bearer &lt;key&gt;</code>.
        Data licenses apply to API use separately from display. Reference: <a href="/api/v1/docs" target="_blank" className="text-info hover:underline">/api/v1/docs</a>.
      </p>
      <form className="flex items-end gap-2" onSubmit={async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        await run(async () => {
          const created = await api.post<{ key: string }>("/auth/api-keys", { name: String(form.get("name")) });
          setSecret(created.key);
        });
        reload();
      }}>
        <Field label="Key name"><Input name="name" required maxLength={80} placeholder="Research notebook" className="w-64" /></Field>
        <Button type="submit" variant="primary"><KeyRound size={12} /> Create key</Button>
      </form>
      {secret && (
        <div className="rounded border border-up/40 bg-up/5 p-2.5 text-[12px]">
          Copy the key now. It is not shown again.
          <div className="mt-1.5 flex items-center gap-2">
            <code className="num min-w-0 flex-1 truncate rounded bg-ink px-2 py-1 text-[11px]">{secret}</code>
            <Button size="sm" onClick={() => navigator.clipboard.writeText(secret)}><Copy size={11} /> Copy</Button>
          </div>
        </div>
      )}
      {note}
      {!data ? <Skeleton rows={3} /> : data.length === 0 ? <Empty title="No API keys" /> : (
        <table className="w-full text-[12.5px]">
          <tbody>
            {data.map((key) => (
              <tr key={key.id} className="border-b border-line/60">
                <td className="py-2 text-fg">{key.name}</td><td className="num text-faint">{key.prefix}…</td>
                <td className="text-dim">created {fmtDate(key.created_at)}</td><td className="text-dim">used {fmtAge(key.last_used_at)}</td>
                <td className="text-right"><button aria-label="Revoke key" className="text-faint hover:text-down"
                  onClick={async () => { await run(() => api.delete(`/auth/api-keys/${key.id}`), "Key revoked."); reload(); }}><Trash2 size={13} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

type PlanCard = { code: string; name: string; audience: string; highlights: string[]; price_label: string; self_serve: boolean; limits: Record<string, number> };
type Usage = { today: Record<string, number>; limits: Record<string, number>; datasets: { dataset: string; channel: string; count: number }[] };

function PlanTab() {
  const { me } = useSession();
  const params = useSearchParams();
  const plans = useApi<{ items: PlanCard[]; billing_enabled: boolean; deployment_mode: string; sales_contact: string }>("/billing/plans");
  const usage = useApi<Usage>("/org/usage");
  const { run, note } = useAction();
  const outcome = params.get("checkout");
  const limitText = (n: number | undefined) => (n === undefined ? "—" : n >= 1_000_000 ? "unlimited" : String(n));
  return (
    <div className="space-y-5 p-4">
      {outcome === "success" && <p className="rounded border border-up/40 bg-up/5 px-3 py-2 text-[12.5px] text-up">Payment received. Your plan changes as soon as the payment provider confirms the subscription.</p>}
      {outcome === "cancelled" && <p className="text-[12.5px] text-dim">Checkout was cancelled. Nothing was charged.</p>}
      <div className="flex flex-wrap items-center gap-3">
        <div className="text-[13px]">Current plan: <b className="text-gold">{me.tenant.plan_name}</b></div>
        {plans.data?.billing_enabled && me.role === "owner" && (
          <Button size="sm" onClick={() => run(async () => { window.location.href = (await api.post<{ url: string }>("/billing/portal")).url; })}>
            Manage subscription and invoices
          </Button>
        )}
        {plans.data && !plans.data.billing_enabled && (
          <span className="text-[12px] text-faint">This is a {plans.data.deployment_mode.replace("_", "-")} deployment. Plans are assigned by its administrator.</span>
        )}
      </div>
      {note}
      {plans.error ? <ErrorNote error={plans.error} /> : !plans.data ? <Skeleton rows={4} /> : (
        <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-5">
          {plans.data.items.map((plan) => {
            const current = plan.code === me.tenant.plan;
            return (
              <div key={plan.code} className={cx("flex flex-col rounded border p-3", current ? "border-gold/60 bg-gold/5" : "border-line")}>
                <div className="flex items-baseline justify-between"><span className="text-[13.5px] font-semibold">{plan.name}</span>
                  {current && <Badge tone="gold">Current</Badge>}</div>
                <div className="num mt-0.5 text-[13px] text-gold">{plan.price_label || " "}</div>
                <p className="mt-1 text-[11.5px] text-faint">{plan.audience}</p>
                <ul className="mt-2 flex-1 space-y-1 text-[12px] text-dim">
                  {plan.highlights.map((h) => <li key={h} className="flex gap-1.5"><Check size={12} className="mt-0.5 shrink-0 text-up" />{h}</li>)}
                  <li className="text-faint">{limitText(plan.limits.ai_questions_per_day)} AI questions a day · {limitText(plan.limits.members)} seats</li>
                </ul>
                {!current && plan.self_serve && me.role === "owner" && (
                  <Button className="mt-3" variant="primary" size="sm" onClick={() => run(async () => {
                    window.location.href = (await api.post<{ url: string }>("/billing/checkout", { plan: plan.code })).url;
                  })}>Choose {plan.name}</Button>
                )}
                {!current && plan.code === "enterprise" && plans.data?.sales_contact && (
                  <a href={plans.data.sales_contact.includes("@") ? `mailto:${plans.data.sales_contact}` : plans.data.sales_contact}
                     className="mt-3 text-center text-[12px] text-info hover:underline">Contact sales</a>
                )}
              </div>
            );
          })}
        </div>
      )}
      <div>
        <h2 className="mb-2 text-[13px] font-semibold">Usage today</h2>
        {!usage.data ? <Skeleton rows={2} /> : (
          <div className="flex flex-wrap gap-6 text-[12.5px]">
            <div>AI questions <span className="num text-fg">{usage.data.today.ai_questions ?? 0}</span> / {limitText(usage.data.limits.ai_questions_per_day)}</div>
            <div>Backtests per day limit <span className="num text-fg">{limitText(usage.data.limits.backtests_per_day)}</span></div>
          </div>
        )}
        {usage.data && usage.data.datasets.length > 0 && (
          <table className="mt-3 w-full max-w-xl text-[12px]">
            <thead className="text-left text-[10.5px] tracking-wider text-faint uppercase"><tr><th className="font-medium">Dataset (30 days)</th><th className="font-medium">Use</th><th className="text-right font-medium">Reads</th></tr></thead>
            <tbody>{usage.data.datasets.map((row) => (
              <tr key={`${row.dataset}-${row.channel}`} className="border-b border-line/60"><td className="py-1 text-dim">{row.dataset}</td><td className="text-faint">{row.channel.replace("_", " ")}</td><td className="num text-right">{row.count}</td></tr>
            ))}</tbody>
          </table>
        )}
      </div>
    </div>
  );
}

type AuditRow = { id: string; occurred_at: string; action: string; outcome: string; actor: string; object_type: string; object_id: string; details: Record<string, unknown> };

function Audit() {
  const { can, me, atLeast } = useSession();
  const [action, setAction] = useState("");
  const { data, error } = useApi<{ items: AuditRow[] }>(can("org.audit") && atLeast("admin") ? "/org/audit" : null, { action });
  if (!can("org.audit")) return <Locked feature="The audit trail" plan={me.tenant.plan_name} />;
  if (!atLeast("admin")) return <Empty title="Administrators see the audit trail" />;
  if (error) return <ErrorNote error={error} />;
  return (
    <div className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <Input value={action} onChange={(e) => setAction(e.target.value)} placeholder="Filter by action, e.g. auth. or portfolio." className="w-72" />
        <span className="text-[11px] text-faint">Append-only. Records cannot be changed or deleted.</span>
      </div>
      {!data ? <Skeleton rows={8} /> : (
        <table className="w-full min-w-[720px] text-[12px]">
          <thead className="text-left text-[10.5px] tracking-wider text-faint uppercase">
            <tr className="border-b border-line"><th className="py-1.5 font-medium">Time</th><th className="font-medium">Action</th><th className="font-medium">Outcome</th><th className="font-medium">Actor</th><th className="font-medium">Object</th></tr>
          </thead>
          <tbody>
            {data.items.map((row) => (
              <tr key={row.id} className="border-b border-line/60" title={JSON.stringify(row.details)}>
                <td className="num py-1 text-dim">{fmtDateTime(row.occurred_at)}</td>
                <td className="num text-fg">{row.action}</td>
                <td className={row.outcome === "success" ? "text-up" : "text-down"}>{row.outcome}</td>
                <td className="text-dim">{row.actor}</td>
                <td className="num truncate text-faint">{row.object_type} {row.object_id.slice(0, 8)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

type TenantRow = { id: string; name: string; plan: string; status: string; members: number; created_at: string; subscription: boolean };

function PasswordResetLink() {
  const { run, note } = useAction();
  const [link, setLink] = useState<string | null>(null);
  return (
    <div className="mb-5 space-y-2">
      <form className="flex flex-wrap items-end gap-2" onSubmit={async (event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        const element = event.currentTarget;
        const form = new FormData(element);
        setLink(null);
        await run(async () => {
          const result = await api.post<{ emailed: boolean; link: string | null }>("/auth/admin/password-reset",
            { email: String(form.get("email")) });
          setLink(result.link);
          element.reset();
        }, "Password reset link created.");
      }}>
        <Field label="Password reset link for an account">
          <Input name="email" type="email" required className="w-64" placeholder="their@email.com" />
        </Field>
        <Button type="submit" variant="primary"><KeyRound size={12} /> Create link</Button>
      </form>
      {note}
      {link && (
        <div className="rounded border border-gold/40 bg-gold/5 p-2.5 text-[12px]">
          Email is not configured on this deployment. Send this link to the account holder yourself. It works once,
          for one hour, and signs them out everywhere when used:
          <div className="mt-1.5 flex items-center gap-2">
            <code className="num min-w-0 flex-1 truncate rounded bg-ink px-2 py-1 text-[11px]">{link}</code>
            <Button size="sm" onClick={() => navigator.clipboard.writeText(link)}><Copy size={11} /> Copy</Button>
          </div>
        </div>
      )}
    </div>
  );
}

function Platform() {
  const { data, error, reload } = useApi<{ items: TenantRow[] }>("/admin/tenants");
  const { run, note } = useAction();
  if (error) return <ErrorNote error={error} />;
  if (!data) return <Skeleton rows={6} />;
  return (
    <div className="p-4">
      <PasswordResetLink />
      <p className="mb-3 text-[12px] text-dim">Organizations on this deployment. Plan changes here override billing until the next subscription event.</p>
      {note}
      <table className="w-full min-w-[720px] text-[12.5px]">
        <thead className="text-left text-[10.5px] tracking-wider text-faint uppercase">
          <tr className="border-b border-line"><th className="py-1.5 font-medium">Organization</th><th className="font-medium">Plan</th><th className="font-medium">Status</th><th className="font-medium">Members</th><th className="font-medium">Created</th></tr>
        </thead>
        <tbody>
          {data.items.map((tenant) => (
            <tr key={tenant.id} className="border-b border-line/60">
              <td className="py-1.5 text-fg">{tenant.name}{tenant.subscription && <Badge tone="up">subscribed</Badge>}</td>
              <td><select value={tenant.plan} onChange={async (e) => { await run(() => api.patch(`/admin/tenants/${tenant.id}`, { plan: e.target.value })); reload(); }}
                          className="h-7 rounded border border-line-strong bg-ink px-1.5 text-[12px] text-fg">
                {["community", "pro", "quant", "business", "enterprise"].map((p) => <option key={p}>{p}</option>)}</select></td>
              <td><select value={tenant.status} onChange={async (e) => { await run(() => api.patch(`/admin/tenants/${tenant.id}`, { status: e.target.value })); reload(); }}
                          className="h-7 rounded border border-line-strong bg-ink px-1.5 text-[12px] text-fg">
                <option>active</option><option>suspended</option></select></td>
              <td className="num">{tenant.members}</td>
              <td className="num text-dim">{fmtDate(tenant.created_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Settings() {
  const params = useSearchParams();
  const router = useRouter();
  const { me } = useSession();
  const tab = (params.get("tab") as Tab) ?? "profile";
  const options: { value: Tab; label: string }[] = [
    { value: "profile", label: "Profile" }, { value: "organization", label: "Organization" }, { value: "members", label: "Members" },
    { value: "api", label: "API keys" }, { value: "plan", label: "Plan and usage" }, { value: "audit", label: "Audit trail" },
    ...(me.user.platform_admin ? [{ value: "platform" as Tab, label: "Platform" }] : []),
  ];
  return (
    <div className="h-full p-2">
      <Panel title="Settings" className="h-full" bodyClassName="flex flex-col">
        <Tabs value={tab} onChange={(next) => router.replace(`/app/settings?tab=${next}`)} options={options} />
        <div className="min-h-0 flex-1 overflow-auto">
          {tab === "profile" && <Profile />}
          {tab === "organization" && <Organization />}
          {tab === "members" && <MembersTab />}
          {tab === "api" && <ApiKeys />}
          {tab === "plan" && <PlanTab />}
          {tab === "audit" && <Audit />}
          {tab === "platform" && me.user.platform_admin && <Platform />}
        </div>
      </Panel>
    </div>
  );
}

export default function SettingsPage() {
  return <Suspense fallback={<Skeleton rows={6} />}><Settings /></Suspense>;
}
