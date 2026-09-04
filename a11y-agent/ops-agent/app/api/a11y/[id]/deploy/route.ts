import { NextResponse } from "next/server";
import { getAgentRun, markRunApplied, getA11yReport, updateA11yReportStatus } from "@/lib/pg-client";
import { fetchForgejoFile, createOrUpdateForgejoFile } from "@/lib/forgejo-client";
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

  // Commit to Forgejo
  const committed = await createOrUpdateForgejoFile(
    PORTFOLIO_OWNER,
    PORTFOLIO_REPO,
    action.file,
    newContent,
    `fix(a11y): ${action.wcag ?? "WCAG fix"} in ${action.file} [agent-run:${id}]`
  );
  if (!committed) {
    return NextResponse.json({ error: "Forgejo commit failed" }, { status: 502 });
  }

  // Trigger portfolio build — Kaniko Job in portfolio namespace
  const buildTriggered = await triggerPortfolioBuild(id);

  await markRunApplied(id, buildTriggered ? "committed + build triggered" : "committed (build trigger failed)");
  if (action.reportId) {
    await updateA11yReportStatus(action.reportId, "fix_deployed");
  }

  return NextResponse.json({ ok: true, committed: true, buildTriggered });
}

async function triggerPortfolioBuild(runId: string): Promise<boolean> {
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

  const { ok } = await k8sRequest(
    "POST",
    `/apis/batch/v1/namespaces/portfolio/jobs`,
    job
  );
  if (!ok) return false;

  // Rollout restart: patch deployment with timestamp annotation to force new pods
  const patch = {
    spec: {
      template: {
        metadata: {
          annotations: { "kubectl.kubernetes.io/restartedAt": new Date().toISOString() },
        },
      },
    },
  };
  const { ok: patchOk } = await k8sRequest(
    "PATCH",
    `/apis/apps/v1/namespaces/portfolio/deployments/portfolio`,
    patch
  );

  return patchOk;
}
