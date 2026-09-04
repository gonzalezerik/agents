"use client";

import { useState } from "react";

export interface A11yFinding {
  report: {
    id: string;
    created_at: string;
    url: string;
    description: string;
    status: string;
    agent_run_id: string | null;
  };
  run: {
    id: string;
    investigation: string | null;
    confidence: number | null;
    proposed_action: {
      wcag?: string;
      file?: string;
      original?: string;
      patched?: string;
    } | null;
    applied_at: string | null;
  } | null;
}

export function A11yFindings({ findings }: { findings: A11yFinding[] }) {
  if (findings.length === 0) {
    return (
      <p className="text-sm text-neutral-400 py-8 text-center">
        No accessibility reports yet. Reports appear here when users submit
        complaints via the portfolio widget.
      </p>
    );
  }

  return (
    <ul className="space-y-4">
      {findings.map((f) => (
        <FindingCard key={f.report.id} finding={f} />
      ))}
    </ul>
  );
}

function FindingCard({ finding }: { finding: A11yFinding }) {
  const { report, run } = finding;
  const [deploying, setDeploying] = useState(false);
  const [deployResult, setDeployResult] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);

  const statusColors: Record<string, string> = {
    pending: "bg-yellow-500/15 text-yellow-400",
    investigating: "bg-blue-500/15 text-blue-400",
    fix_proposed: "bg-purple-500/15 text-purple-400",
    fix_deployed: "bg-green-500/15 text-green-400",
    dismissed: "bg-neutral-500/15 text-neutral-400",
  };

  async function deploy() {
    if (!run) return;
    setDeploying(true);
    setDeployResult(null);
    try {
      const res = await fetch(`/api/a11y/${run.id}/deploy`, { method: "POST" });
      const data = await res.json();
      if (res.ok) {
        setDeployResult("Deployed. Build job queued — portfolio will update in ~2–3 minutes.");
      } else {
        setDeployResult(`Error: ${data.error ?? "Unknown error"}`);
      }
    } catch {
      setDeployResult("Network error — try again.");
    } finally {
      setDeploying(false);
    }
  }

  const action = run?.proposed_action;
  const canDeploy =
    report.status === "fix_proposed" &&
    run &&
    !run.applied_at &&
    action?.file &&
    action?.patched;

  return (
    <li className="rounded-xl border border-neutral-800 bg-neutral-900 p-4 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-mono text-neutral-500 truncate">{report.url}</p>
          <p className="text-sm mt-1">{report.description}</p>
        </div>
        <span
          className={`shrink-0 text-xs px-2 py-0.5 rounded-full font-medium ${
            statusColors[report.status] ?? "bg-neutral-700 text-neutral-300"
          }`}
        >
          {report.status.replace("_", " ")}
        </span>
      </div>

      <p className="text-xs text-neutral-500">
        Reported {new Date(report.created_at).toLocaleString()}
      </p>

      {run && (
        <div className="text-xs space-y-1 border-t border-neutral-800 pt-3">
          {run.investigation && (
            <p className="text-neutral-300">{run.investigation}</p>
          )}
          {action?.wcag && (
            <p className="text-neutral-400">
              WCAG: <span className="text-neutral-200">{action.wcag}</span>
            </p>
          )}
          {action?.file && (
            <p className="text-neutral-400">
              File: <span className="font-mono text-neutral-200">{action.file}</span>
            </p>
          )}
          {run.confidence !== null && (
            <p className="text-neutral-400">
              Confidence:{" "}
              <span className="text-neutral-200">{Math.round(run.confidence * 100)}%</span>
            </p>
          )}

          {action?.original && action?.patched && (
            <div>
              <button
                onClick={() => setExpanded((v) => !v)}
                className="text-blue-400 hover:text-blue-300 mt-1"
                aria-expanded={expanded}
              >
                {expanded ? "Hide patch" : "Show proposed patch"}
              </button>
              {expanded && (
                <div className="mt-2 space-y-2">
                  <div>
                    <p className="text-red-400 mb-1">Original:</p>
                    <pre className="bg-neutral-800 rounded p-2 overflow-x-auto text-xs text-neutral-300 whitespace-pre-wrap">
                      {action.original}
                    </pre>
                  </div>
                  <div>
                    <p className="text-green-400 mb-1">Patched:</p>
                    <pre className="bg-neutral-800 rounded p-2 overflow-x-auto text-xs text-neutral-300 whitespace-pre-wrap">
                      {action.patched}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {run?.applied_at && (
        <p className="text-xs text-green-400">
          Deployed {new Date(run.applied_at).toLocaleString()}
        </p>
      )}

      {deployResult && (
        <p
          role="status"
          className={`text-xs ${
            deployResult.startsWith("Error") ? "text-red-400" : "text-green-400"
          }`}
        >
          {deployResult}
        </p>
      )}

      {canDeploy && !deployResult && (
        <button
          onClick={deploy}
          disabled={deploying}
          className="w-full py-2 text-sm rounded-lg bg-purple-600 hover:bg-purple-700 text-white disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-purple-400"
          aria-label={`Deploy accessibility fix for report on ${report.url}`}
        >
          {deploying ? "Deploying…" : "Deploy fix"}
        </button>
      )}
    </li>
  );
}
