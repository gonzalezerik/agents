/**
 * Minimal in-cluster Kubernetes API client using the pod's own
 * ServiceAccount token (mission-control-agent - defined 2026-07-29,
 * unused until this pod actually started running in-cluster on
 * 2026-08-25). No kubernetes client library needed for read-only list
 * calls - just the projected token + the cluster CA.
 *
 * Requires NODE_EXTRA_CA_CERTS to point at the projected CA (set in the
 * Deployment env) so plain fetch() trusts the in-cluster API server.
 */
import fs from "fs";

const K8S_API = "https://kubernetes.default.svc.cluster.local";
const TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token";

function readToken(): string | null {
  try {
    return fs.readFileSync(TOKEN_PATH, "utf8").trim();
  } catch {
    return null;
  }
}

export async function k8sGet<T = unknown>(apiPath: string): Promise<T | null> {
  const token = readToken();
  if (!token) return null;
  try {
    const res = await fetch(`${K8S_API}${apiPath}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export interface ArgoApplicationSummary {
  name: string;
  namespace: string;
  syncStatus: string;
  healthStatus: string;
  repoPath: string | null;
}

interface ArgoApplicationListResponse {
  items?: Array<{
    metadata: { name: string; namespace: string };
    spec?: { source?: { path?: string } };
    status?: {
      sync?: { status?: string };
      health?: { status?: string };
    };
  }>;
}

/** List every ArgoCD Application in the cluster - the auto-discovery source of truth. */
export async function listArgoApplications(): Promise<ArgoApplicationSummary[] | null> {
  const data = await k8sGet<ArgoApplicationListResponse>("/apis/argoproj.io/v1alpha1/applications");
  if (!data?.items) return null;
  return data.items.map((item) => ({
    name: item.metadata.name,
    namespace: item.metadata.namespace,
    syncStatus: item.status?.sync?.status ?? "Unknown",
    healthStatus: item.status?.health?.status ?? "Unknown",
    repoPath: item.spec?.source?.path ?? null,
  }));
}
