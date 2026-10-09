// app/api/orchestration/routing-log/route.ts
// Synthesizes routing log entries from mc-agent session events in real time.
// Falls back to local SQLite routing_log for entries inserted directly.
import { NextRequest, NextResponse } from "next/server";
import { listRoutingLog } from "@/lib/orchestration/routing-log";

const MC_AGENT = process.env.MC_AGENT_GPUHOST_URL ?? "http://localhost:4001";
const TOKEN    = process.env.MC_AGENT_TOKEN ?? "";

interface AgentEvent {
  seq: number;
  ts: string;
  event_type: string;
  payload: Record<string, unknown>;
}
interface AgentSession {
  id: string;
  started_at: string;
  last_seen: string;
  request_count: number;
  orchestrator_model_id: string | null;
  title: string | null;
  passthrough: number;
}

async function fetchAgentHeaders() {
  return { Authorization: `Bearer ${TOKEN}` };
}

async function synthesiseFromAgent(limit: number, session_id?: string) {
  const headers = await fetchAgentHeaders();

  // Fetch session list (or single session)
  let sessions: AgentSession[] = [];
  try {
    const url = session_id
      ? `${MC_AGENT}/sessions?limit=1`
      : `${MC_AGENT}/sessions?limit=${Math.min(limit, 200)}`;
    const res = await fetch(url, { headers, cache: "no-store" });
    if (!res.ok) return [];
    const all: AgentSession[] = await res.json();
    sessions = session_id ? all.filter((s) => s.id === session_id) : all;
  } catch {
    return [];
  }

  const entries: Record<string, unknown>[] = [];

  await Promise.all(
    sessions.slice(0, limit).map(async (sess) => {
      let events: AgentEvent[] = [];
      try {
        const res = await fetch(`${MC_AGENT}/sessions/${encodeURIComponent(sess.id)}/events`, {
          headers, cache: "no-store",
        });
        if (!res.ok) return;
        events = await res.json();
      } catch {
        return;
      }

      // Extract relevant events by type
      const byType: Record<string, AgentEvent> = {};
      for (const e of events) {
        if (!byType[e.event_type]) byType[e.event_type] = e;
      }

      const user   = byType["user_message"];
      const plan   = byType["orchestrator_plan"];
      const sel    = byType["agent_selected"];
      const final  = byType["final_response"];
      const agent  = byType["agent_response"];
      const err    = byType["error"];

      // Only synthesise if there's at least a user_message
      if (!user) return;

      const promptSummary = (() => {
        const msgs = (user.payload.messages as Array<{ role: string; content: unknown }>) ?? [];
        const last = [...msgs].reverse().find((m) => m.role === "user");
        return typeof last?.content === "string"
          ? last.content.slice(0, 200)
          : JSON.stringify(last?.content ?? "").slice(0, 200);
      })();

      const outcome = (() => {
        if (err) return "error";
        if (!plan && !sel) return "passthrough";
        if (final?.payload.had_repairs) return "repaired";
        return "success";
      })();

      entries.push({
        id: sess.id,                                      // string id for synthesised entries
        ts: sess.last_seen,
        session_id: sess.id,
        prompt_summary: promptSummary,
        orchestrator_model_id: plan?.payload.orchestrator_model_id ?? null,
        agent_model_id: sel?.payload.model_id ?? null,
        routing_reason: sel?.payload.reason ?? null,
        latency_plan_ms: plan?.payload.latency_ms ?? null,
        latency_agent_ms: agent?.payload.latency_ms ?? null,
        tokens_in: agent?.payload.tokens_in ?? null,
        tokens_out: agent?.payload.tokens_out ?? null,
        outcome,
        error_detail: err ? `[${err.payload.phase}] ${err.payload.message}` : null,
      });
    })
  );

  entries.sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
  return entries;
}

export async function GET(req: NextRequest) {
  const limit = Number(req.nextUrl.searchParams.get("limit") ?? "100");
  const session_id = req.nextUrl.searchParams.get("session_id") ?? undefined;

  // Try mc-agent synthesis first (live data)
  const synthesised = await synthesiseFromAgent(limit, session_id);

  // Merge with any entries in local routing_log (e.g., from reconciler or direct inserts)
  const local = listRoutingLog({ limit, session_id });

  // Deduplicate: local takes precedence over synthesised if session_id matches
  const localSessionIds = new Set(local.map((e) => e.session_id));
  const filtered = synthesised.filter((e) => !localSessionIds.has(String(e.session_id)));

  const merged = [...local, ...filtered]
    .sort((a, b) => String((b as Record<string,unknown>).ts).localeCompare(String((a as Record<string,unknown>).ts)))
    .slice(0, limit);

  return NextResponse.json(merged);
}
