import { listA11yReports, getAgentRun } from "@/lib/pg-client";
import { A11yFindings } from "@/components/a11y/a11y-findings";

export const dynamic = "force-dynamic";
export const metadata = { title: "Accessibility · Mission Control" };

export default async function A11yPage() {
  const reports = await listA11yReports(100);

  const findings = await Promise.all(
    reports.map(async (report) => ({
      report,
      run: report.agent_run_id ? await getAgentRun(report.agent_run_id) : null,
    }))
  );

  const pending = findings.filter((f) => f.report.status === "pending" || f.report.status === "investigating");
  const proposed = findings.filter((f) => f.report.status === "fix_proposed");
  const resolved = findings.filter(
    (f) => f.report.status === "fix_deployed" || f.report.status === "dismissed"
  );

  return (
    <main className="p-6 max-w-3xl mx-auto space-y-8">
      <div>
        <h1 className="text-xl font-semibold">Accessibility Reports</h1>
        <p className="text-sm text-neutral-400 mt-1">
          User-submitted ADA / WCAG complaints from the portfolio widget. The
          agent validates each one, proposes a code fix, and waits for your
          approval before deploying.
        </p>
      </div>

      {proposed.length > 0 && (
        <section aria-labelledby="proposed-heading">
          <h2 id="proposed-heading" className="text-sm font-semibold text-purple-400 mb-3">
            Ready to deploy ({proposed.length})
          </h2>
          <A11yFindings findings={proposed} />
        </section>
      )}

      {pending.length > 0 && (
        <section aria-labelledby="pending-heading">
          <h2 id="pending-heading" className="text-sm font-semibold text-yellow-400 mb-3">
            Pending / investigating ({pending.length})
          </h2>
          <A11yFindings findings={pending} />
        </section>
      )}

      {resolved.length > 0 && (
        <section aria-labelledby="resolved-heading">
          <h2 id="resolved-heading" className="text-sm font-semibold text-neutral-500 mb-3">
            Resolved / dismissed ({resolved.length})
          </h2>
          <A11yFindings findings={resolved} />
        </section>
      )}

      {findings.length === 0 && (
        <p className="text-sm text-neutral-400 text-center py-12">
          No reports yet. The portfolio widget will send complaints here automatically.
        </p>
      )}
    </main>
  );
}
