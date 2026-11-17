import type { Metadata } from "next";
import { Prose, SitePage } from "@/components/site";

export const metadata: Metadata = { title: "Privacy notice" };

export default function Privacy() {
  return (
    <SitePage>
      <Prose title="Privacy notice" updated="15 November 2026">
        <p>
          This notice describes how this AUREX deployment processes personal data. The operator of the deployment is the
          controller. For organizations on a business plan the operator acts as processor for the content their members
          create, under a data processing agreement.
        </p>
        <h2>What is processed</h2>
        <ul>
          <li>Account data: email address, display name, password hash, organization and role.</li>
          <li>Content you create: watchlists, portfolios, questions, answers, theses, uploaded documents and backtests.</li>
          <li>Security records: sign-in events, audit events and request logs. Logs exclude passwords, tokens, email addresses and document content.</li>
          <li>Billing data, handled by the payment provider. AUREX stores only the provider&apos;s customer and subscription references.</li>
        </ul>
        <h2>Purposes and legal bases</h2>
        <ul>
          <li>Providing the service you signed up for (contract).</li>
          <li>Security, fraud prevention and the audit trail (legitimate interest; legal obligation where applicable).</li>
          <li>Billing and accounting (contract; legal obligation).</li>
        </ul>
        <h2>AI model providers</h2>
        <p>
          When an organization allows external models, a question and the evidence retrieved for it are sent to the
          configured model provider to write the answer. Organizations can turn this off in Settings → Organization; the
          offline evidence engine then answers inside the deployment. Data whose license does not permit external model
          use is never sent.
        </p>
        <h2>Retention</h2>
        <p>
          Account and content data are kept while the account exists and deleted within 30 days after closure, except
          audit records and invoices, which are kept as long as the law requires.
        </p>
        <h2>Your rights</h2>
        <p>
          You can access, correct, export or delete your data, object to processing and complain to a supervisory
          authority. Contact the operator of this deployment to exercise these rights.
        </p>
      </Prose>
    </SitePage>
  );
}
