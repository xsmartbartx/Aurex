import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthForm } from "@/components/auth-form";

export const metadata: Metadata = { title: "Join your team" };

async function Invite({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <AuthForm mode="invite" inviteToken={token} />;
}

export default function InvitePage(props: PageProps<"/invite/[token]">) {
  return (
    <Suspense>
      <Invite params={props.params} />
    </Suspense>
  );
}
