import type { Metadata } from "next";
import { Prose, SitePage } from "@/components/site";

export const metadata: Metadata = { title: "Terms of service" };

export default function Terms() {
  return (
    <SitePage>
      <Prose title="Terms of service" updated="15 November 2026">
        <p>
          These terms govern the use of this AUREX deployment. The operator named in the order form or on the pricing
          page provides the service. The operator should have these terms reviewed by counsel for its jurisdiction
          before offering the service to customers.
        </p>
        <h2>1. The service</h2>
        <p>
          AUREX is a research terminal for analysis, education and simulation. It displays market, macroeconomic and
          company data, answers questions with cited evidence, and calculates portfolio, backtest and scenario results
          under assumptions you set.
        </p>
        <h2>2. No investment advice, no trading</h2>
        <ul>
          <li>Nothing in AUREX is a personal recommendation, investment advice or an offer to buy or sell anything.</li>
          <li>AUREX does not connect to brokers and does not execute orders. Portfolios are virtual.</li>
          <li>Scenarios, simulations and backtests describe what would follow from stated assumptions. They are not forecasts.</li>
          <li>Decisions you take using AUREX are your own. Check figures against their sources before relying on them.</li>
        </ul>
        <h2>3. Data and licenses</h2>
        <p>
          Data comes from the providers listed in DataLab under their licenses. AUREX shows each dataset&apos;s freshness and
          license class and enforces the license register for display, export, API use and use by AI models. You agree
          not to redistribute data outside what its license permits. Demonstration data describes fictional companies
          and must not be presented as market data.
        </p>
        <h2>4. AI-generated content</h2>
        <p>
          Answers produced by the AI engine are marked as AI-generated. Statements that the claim verifier cannot match to
          evidence are withheld and listed. AI output can still be incomplete or wrong; the evidence links let you check it.
        </p>
        <h2>5. Accounts and acceptable use</h2>
        <ul>
          <li>Keep credentials and API keys secret. You are responsible for activity under your organization&apos;s accounts.</li>
          <li>Do not attempt to access other organizations&apos; data, bypass plan limits, overload the service or upload malicious content.</li>
          <li>Uploaded documents remain yours and stay private to your organization.</li>
        </ul>
        <h2>6. Plans, fees and cancellation</h2>
        <p>
          Paid plans are billed in advance through the payment provider shown at checkout. You can cancel at any time from
          Settings → Plan and usage; the plan stays active until the end of the paid period and then returns to Community.
        </p>
        <h2>7. Availability and liability</h2>
        <p>
          The service is provided with reasonable care but without a guarantee of uninterrupted availability or of the
          accuracy of third-party data. To the extent permitted by law, the operator&apos;s liability is limited to the fees
          paid in the twelve months before the claim.
        </p>
        <h2>8. Changes</h2>
        <p>Material changes to these terms are announced in the terminal at least 30 days before they take effect.</p>
      </Prose>
    </SitePage>
  );
}
