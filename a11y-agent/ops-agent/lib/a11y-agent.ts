import { diagnoseA11y } from "./agent-llm";
import { fetchForgejoFile } from "./forgejo-client";
import { insertAgentRun } from "./pg-client";
import {
  getA11yReport,
  insertA11yReport,
  linkA11yReportToRun,
  updateA11yReportStatus,
} from "./pg-client";

const PORTFOLIO_OWNER = process.env.PORTFOLIO_REPO_OWNER ?? "portfolio-owner";
const PORTFOLIO_REPO = process.env.PORTFOLIO_REPO_NAME ?? "portfolio";

/** Called from the webhook route when a new a11y report arrives from the portfolio. */
export async function investigateA11yComplaint(payload: {
  reportId: string;
  url: string;
  description: string;
}): Promise<void> {
  const { reportId, url, description } = payload;

  await updateA11yReportStatus(reportId, "investigating");

  // Feed to LLM for validation + fix generation
  const diagnosis = await diagnoseA11y({ url, description });

  if (!diagnosis || !diagnosis.isValid) {
    const runId = await insertAgentRun({
      entity: `a11y:${reportId}`,
      summary: `A11y report from ${url} dismissed — not a valid WCAG issue`,
      mode: "report-only",
      tool_access: "read-only",
      outcome: "investigated",
      tool_name: null,
      confidence: diagnosis?.confidence ?? 0,
      investigation: diagnosis?.analysis ?? "LLM determined this is not a genuine WCAG issue.",
      proposed_action: null,
    });
    await linkA11yReportToRun(reportId, runId ?? "");
    await updateA11yReportStatus(reportId, "dismissed");
    await notifyNtfy(
      "A11y report dismissed",
      `${url}\n\nReason: ${diagnosis?.analysis ?? "not a WCAG violation"}`
    );
    return;
  }

  // If valid, try to fetch the source file to attach the proposed patch
  let sourceContext = "";
  if (diagnosis.file) {
    const fileResult = await fetchForgejoFile(
      PORTFOLIO_OWNER,
      PORTFOLIO_REPO,
      diagnosis.file
    );
    if (fileResult) {
      // Truncate to avoid massive context in proposed_action JSONB
      sourceContext = fileResult.content.slice(0, 3000);
    }
  }

  const agentRun = await insertAgentRun({
    entity: `a11y:${reportId}`,
    summary: `A11y fix proposed for ${url} — ${diagnosis.wcagCriterion}`,
    mode: "report-only",
    tool_access: "read-only",
    outcome: "proposed fix",
    tool_name: "a11y-agent",
    confidence: diagnosis.confidence,
    investigation: diagnosis.analysis,
    proposed_action: {
      type: "a11y-patch",
      file: diagnosis.file,
      wcag: diagnosis.wcagCriterion,
      original: diagnosis.originalCode,
      patched: diagnosis.patchedCode,
      reportId,
      sourceContext: sourceContext || undefined,
    },
  });

  await linkA11yReportToRun(reportId, agentRun?.id ?? "");
  await updateA11yReportStatus(reportId, "fix_proposed");

  await notifyNtfy(
    "A11y fix ready for review",
    `${url}\nWCAG: ${diagnosis.wcagCriterion}\nFile: ${diagnosis.file ?? "unknown"}\nConfidence: ${Math.round(diagnosis.confidence * 100)}%\n\nOpen ops dashboard to deploy.`
  );
}

async function notifyNtfy(title: string, body: string) {
  const ntfyUrl = process.env.NTFY_URL ?? "http://ntfy.ntfy.svc.cluster.local:80";
  const topic = process.env.NTFY_TOPIC ?? "ops";
  try {
    await fetch(`${ntfyUrl}/${topic}`, {
      method: "POST",
      headers: { Title: title },
      body,
    });
  } catch {}
}
