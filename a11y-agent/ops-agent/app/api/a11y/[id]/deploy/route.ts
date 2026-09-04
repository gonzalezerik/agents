import { NextResponse } from "next/server";
import { getAgentRun, markRunApplied, updateA11yReportStatus } from "@/lib/pg-client";
import { fetchForgejoFile, createOrUpdateForgejoFile } from "@/lib/forgejo-client";
import { sendEmail, emailFixStarting, emailDeployed } from "@/lib/email-client";
import fs from "fs";

const K8S_API = "https://kubernetes.default.svc.cluster.local";
const PORTFOLIO_OWNER = process.env.PORTFOLIO_REPO_OWNER ?? "portfolio-owner";
const PORTFOLIO_REPO = process.env.PORTFOLIO_REPO_NAME ?? "portfolio";

function k8sToken(): string | null {
  try {
    return fs.readFileSync("/var/run/secrets/kubernetes.io/serviceaccount/token", "utf8").trim();
  } catch {
    return null;
  }
}

async function k8sRequest(
  method: string,
  path: string,
  body?: unknown
): Promise<{ ok: boolean; status: number; data?: unknown }> {
  const token = k8sToken();
  if (!token) return { ok: false, status: 0 };
  try {
    const res = await fetch(`${K8S_API}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(15000),
    });
    const data = res.headers.get("content-type")?.includes("json")
      ? await res.json()
      : undefined;
    return { ok: res.ok, status: res.status, data };
  } catch {
    return { ok: false, status: 0 };
  }
}

export async function POST(
  _req: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;

  const run = await getAgentRun(id);
  if (!run) return NextResponse.json({ error: "Run not found" }, { status: 404 });

  const action = run.proposed_action as {
    type?: string;
    file?: string;
    original?: string;
    patched?: string;
    reportId?: string;
    wcag?: string;
    reporterEmail?: string;
  } | null;

  if (!action || action.type !== "a11y-patch") {
    return NextResponse.json({ error: "No deployable a11y patch on this run" }, { status: 400 });
  }
  if (!action.file || !action.patched) {
    return NextResponse.json({ error: "Patch incomplete — cannot deploy" }, { status: 400 });
  }
  if (run.applied_at) {
    return NextResponse.json({ error: "Already deployed" }, { status: 409 });
  }

  // Fetch current source file
  const currentFile = await fetchForgejoFile(PORTFOLIO_OWNER, PORTFOLIO_REPO, action.file);
  if (!currentFile) {
    return NextResponse.json({ error: "Source file not found in Forgejo" }, { status: 422 });
  }

  // Apply patch — exact string replacement; fail if block has drifted
  if (!action.original || !currentFile.content.includes(action.original)) {
    return NextResponse.json(
      { error: "Original code block not found in current source. File may have changed; review manually." },
      { status: 422 }
    );
  }
  const newContent = currentFile.content.replace(action.original, action.patched);

  // Email: "fix is starting" — send before triggering build
  const reporterEmail = action.reporterEmail ?? null;
  const wcagLabel = action.wcag ?? "WCAG fix";
  const reportUrl = action.reportId ? `https://gonzalezerik.com` : "gonzalezerik.com";
  if (reporterEmail) {
    sendEmail(
      reporterEmail,
      "Accessibility fix approved & deploying — gonzalezerik.com",
      emailFixStarting(reportUrl, wcagLabel)
    ).catch(console.error);
  }

  // Commit to Forgejo
  const committed = await createOrUpdateForgejoFile(
    PORTFOLIO_OWNER,
    PORTFOLIO_REPO,
    action.file,
    newContent,
    `fix(a11y): ${wcagLabel} in ${action.file} [agent-run:${id}]`
  );
  if (!committed) {
    return NextResponse.json({ error: "Forgejo commit failed" }, { status: 502 });
  }

  // Trigger portfolio build — Kaniko Job in portfolio namespace
  const { triggered, jobName } = await triggerPortfolioBuild(id);

  await markRunApplied(id, triggered ? "committed + build triggered" : "committed (build trigger failed)");
  if (action.reportId) {
    await updateA11yReportStatus(action.reportId, "fix_deployed");
  }

  // Background: poll build completion, verify live, send deployed email
  if (reporterEmail && jobName) {
    verifyAndNotifyDeployed({
      reporterEmail,
      reportUrl,
      wcag: wcagLabel,
      jobName,
    }).catch(console.error);
  }

  return NextResponse.json({ ok: true, committed: true, buildTriggered: triggered });
}

async function triggerPortfolioBuild(runId: string): Promise<{ triggered: boolean; jobName: string | null }> {
  const forgejoUrl = process.env.FORGEJO_URL ?? "https://forgejo.example.com";
  const registryHost = new URL(forgejoUrl).hostname;
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19).toLowerCase();
  const jobName = `portfolio-build-a11y-${ts}`;

  const job = {
    apiVersion: "batch/v1",
    kind: "Job",
    metadata: {
      name: jobName,
      namespace: "portfolio",
      labels: { "triggered-by": "a11y-agent", "agent-run-id": runId },
    },
    spec: {
      ttlSecondsAfterFinished: 3600,
      template: {
        spec: {
          restartPolicy: "Never",
          initContainers: [
            {
              name: "git-clone",
              image: "alpine/git:latest",
              command: [
                "sh",
                "-c",
                `git clone https://portfolio-owner:$(FORGEJO_TOKEN)@${registryHost}/portfolio-owner/portfolio /workspace`,
              ],
              env: [
                {
                  name: "FORGEJO_TOKEN",
                  valueFrom: { secretKeyRef: { name: "forgejo-registry-creds", key: "password" } },
                },
              ],
              volumeMounts: [{ name: "workspace", mountPath: "/workspace" }],
            },
          ],
          containers: [
            {
              name: "kaniko",
              image: "gcr.io/kaniko-project/executor:latest",
              args: [
                "--context=/workspace",
                `--destination=${registryHost}/portfolio-owner/portfolio:latest`,
                "--skip-tls-verify",
                "--cache=true",
              ],
              volumeMounts: [
                { name: "workspace", mountPath: "/workspace" },
                { name: "docker-config", mountPath: "/kaniko/.docker" },
              ],
            },
          ],
          volumes: [
            { name: "workspace", emptyDir: {} },
            {
              name: "docker-config",
              secret: {
                secretName: "forgejo-registry-creds",
                items: [{ key: ".dockerconfigjson", path: "config.json" }],
              },
            },
          ],
        },
      },
    },
  };

  const { ok } = await k8sRequest("POST", `/apis/batch/v1/namespaces/portfolio/jobs`, job);
  if (!ok) return { triggered: false, jobName: null };

  return { triggered: true, jobName };
}

/** Polls Kaniko build, waits for pod readiness, verifies HTTP, sends deployed email. */
async function verifyAndNotifyDeployed(opts: {
  reporterEmail: string;
  reportUrl: string;
  wcag: string;
  jobName: string;
}) {
  const { reporterEmail, reportUrl, wcag, jobName } = opts;
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  // Poll Kaniko job for up to 10 minutes (30 × 20s)
  let buildOk = false;
  for (let i = 0; i < 30; i++) {
    await sleep(20_000);
    const { data } = await k8sRequest("GET", `/apis/batch/v1/namespaces/portfolio/jobs/${jobName}`);
    const s = (data as { status?: { succeeded?: number; failed?: number } } | undefined)?.status;
    if ((s?.succeeded ?? 0) > 0) { buildOk = true; break; }
    if ((s?.failed ?? 0) > 0) break;
  }

  // After build succeeds: delete current portfolio pod so it restarts with new image
  if (buildOk) {
    const { data: podList } = await k8sRequest(
      "GET",
      "/api/v1/namespaces/portfolio/pods?labelSelector=app%3Dportfolio"
    );
    const pods = ((podList as { items?: { metadata?: { name?: string } }[] } | undefined)?.items ?? []);
    for (const pod of pods) {
      const podName = pod.metadata?.name;
      if (podName) {
        await k8sRequest("DELETE", `/api/v1/namespaces/portfolio/pods/${podName}`);
      }
    }
  }

  // Wait for a ready portfolio pod (up to 3 minutes, 18 × 10s)
  let podReady = false;
  for (let i = 0; i < 18; i++) {
    await sleep(10_000);
    const { data } = await k8sRequest(
      "GET",
      "/api/v1/namespaces/portfolio/pods?labelSelector=app%3Dportfolio"
    );
    const items = ((data as { items?: unknown[] } | undefined)?.items ?? []) as {
      status?: { containerStatuses?: { ready?: boolean }[] };
    }[];
    podReady = items.some((p) => p.status?.containerStatuses?.[0]?.ready === true);
    if (podReady) break;
  }

  // HTTP check against the internal portfolio service
  let liveVerified = false;
  if (podReady) {
    try {
      const r = await fetch("http://portfolio.portfolio.svc.cluster.local", {
        signal: AbortSignal.timeout(10_000),
      });
      liveVerified = r.ok;
    } catch {}
  }

  await sendEmail(
    reporterEmail,
    "Accessibility fix is live — gonzalezerik.com",
    emailDeployed(reportUrl, wcag, liveVerified)
  );
}
