import type { Metadata } from "next";
import { Suspense } from "react";
import { AuthForm } from "@/components/auth-form";

// The token in the address is a credential: keep it out of referrers and search engines.
export const metadata: Metadata = {
  title: "Choose a new password",
  referrer: "no-referrer",
  robots: { index: false, follow: false },
};

async function Reset({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <AuthForm mode="reset" token={token} />;
}

export default function ResetPasswordPage(props: PageProps<"/reset-password/[token]">) {
  return (
    <Suspense>
      <Reset params={props.params} />
    </Suspense>
  );
}
