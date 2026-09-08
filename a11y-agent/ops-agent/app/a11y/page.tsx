import { listA11yReports, getAgentRun } from "@/lib/pg-client";
import { A11yFindings } from "@/components/a11y/a11y-findings";
import { PageShell } from "@/components/ui/page-shell";

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
    <PageShell breadcrumb="Accessibility" title="A11y Reports">
      <div className="max-w-3xl space-y-8">
        <div>
          <p className="text-sm text-[oklch(0.68_0.010_260)] mt-1">
            User-submitted ADA / WCAG complaints from the portfolio widget. The
            agent validates each one, proposes a code fix, and waits for your
            approval before deploying.
          </p>
        </div>

        {proposed.length > 0 && (
          <section aria-labelledby="proposed-heading">
            <h2 id="proposed-heading" className="text-sm font-semibold text-[oklch(0.65_0.15_280)] mb-3">
              Ready to deploy ({proposed.length})
            </h2>
            <A11yFindings findings={proposed} />
          </section>
        )}

        {pending.length > 0 && (
          <section aria-labelledby="pending-heading">
            <h2 id="pending-heading" className="text-sm font-semibold text-[oklch(0.78_0.16_68)] mb-3">
              Pending / investigating ({pending.length})
            </h2>
            <A11yFindings findings={pending} />
          </section>
        )}

        {resolved.length > 0 && (
          <section aria-labelledby="resolved-heading">
            <h2 id="resolved-heading" className="text-sm font-semibold text-[oklch(0.54_0.008_260)] mb-3">
              Resolved / dismissed ({resolved.length})
            </h2>
            <A11yFindings findings={resolved} />
          </section>
        )}

        {findings.length === 0 && (
          <p className="text-sm text-[oklch(0.54_0.008_260)] text-center py-12">
            No reports yet. The portfolio widget will send complaints here automatically.
          </p>
        )}
      </div>
    </PageShell>
  );
}
