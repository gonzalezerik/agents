const ALERTMANAGER_URL =
  process.env.ALERTMANAGER_URL ?? "http://kube-prometheus-stack-alertmanager.monitoring.svc.cluster.local:9093";

export interface ActiveAlert {
  fingerprint: string;
  alertname: string;
  severity: string;
  namespace: string | null;
  pod: string | null;
  summary: string;
  startsAt: string;
}

interface RawAlert {
  fingerprint: string;
  labels: Record<string, string>;
  annotations: Record<string, string>;
  startsAt: string;
}

export async function listActiveAlerts(): Promise<ActiveAlert[] | null> {
  try {
    const res = await fetch(`${ALERTMANAGER_URL}/api/v2/alerts?active=true`, {
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    const raw: RawAlert[] = await res.json();
    return raw.map((a) => ({
      fingerprint: a.fingerprint,
      alertname: a.labels.alertname ?? "unknown",
      severity: a.labels.severity ?? "unknown",
      namespace: a.labels.namespace ?? null,
      pod: a.labels.pod ?? null,
      summary: a.annotations.summary ?? a.annotations.description ?? "",
      startsAt: a.startsAt,
    }));
  } catch {
    return null;
  }
}
