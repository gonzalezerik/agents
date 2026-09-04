"use client";

import { useState, useEffect } from "react";

interface Session {
  id: string;
  started_at: string;
  last_seen: string;
  client_ip: string;
  passthrough: number;
  request_count: number;
  orchestrator_model_id: string | null;
  title: string | null;
}

type EventType =
  | "user_message" | "orchestrator_plan" | "agent_selected" | "tool_call"
  | "tool_result" | "agent_response" | "final_response" | "error"
  | "repair" | "passthrough_forward";

interface SessionEvent {
  id: number;
  session_id: string;
  seq: number;
  ts: string;
  event_type: EventType;
  payload: Record<string, unknown>;
}

const EVENT_COLORS: Record<string, string> = {
  user_message:       "text-blue-300 bg-blue-900/20",
  orchestrator_plan:  "text-purple-300 bg-purple-900/20",
  agent_selected:     "text-[#7C87FF] bg-[#7C87FF]/10",
  tool_call:          "text-yellow-300 bg-yellow-900/20",
  tool_result:        "text-yellow-200 bg-yellow-900/10",
  agent_response:     "text-green-300 bg-green-900/20",
  final_response:     "text-green-400 bg-green-900/30",
  error:              "text-red-300 bg-red-900/20",
  repair:             "text-orange-300 bg-orange-900/20",
  passthrough_forward:"text-[#8A8F98] bg-[#23252A]",
};

export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [expandedEvent, setExpandedEvent] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/orchestration/sessions")
      .then((r) => r.json())
      .then((d) => { setSessions(d); setLoading(false); });
  }, []);

  async function openSession(id: string) {
    setSelected(id);
    setExpandedEvent(null);
    const res = await fetch(`/api/orchestration/sessions/${encodeURIComponent(id)}/events`);
    setEvents(await res.json());
  }

  return (
    <div className="p-6 max-w-7xl">
      <h1 className="text-xl font-semibold text-[#D0D6E0] mb-6">Sessions</h1>

      <div className="flex gap-6 h-[calc(100vh-140px)]">
        {/* Session list */}
        <div className="w-80 flex-shrink-0 overflow-y-auto space-y-1">
          {loading && <p className="text-[#62666D] text-sm">Loading…</p>}
          {sessions.map((s) => (
            <button
              key={s.id}
              onClick={() => openSession(s.id)}
              className={`w-full text-left p-3 rounded-lg transition-colors ${
                selected === s.id
                  ? "bg-[#7C87FF]/20 border border-[#7C87FF]/40"
                  : "bg-[#0F1011] border border-[#23252A] hover:border-[#7C87FF]/30"
              }`}
            >
              <p className="text-sm text-[#D0D6E0] truncate font-medium">
                {s.title ?? s.id.slice(0, 20) + "…"}
              </p>
              <p className="text-xs text-[#62666D] mt-1">
                {new Date(s.last_seen).toLocaleString()} · {s.request_count} req
              </p>
              {s.passthrough === 1 && (
                <span className="text-xs text-[#8A8F98]">passthrough</span>
              )}
            </button>
          ))}
          {!loading && sessions.length === 0 && (
            <p className="text-[#62666D] text-sm">No sessions yet</p>
          )}
        </div>

        {/* Event timeline */}
        <div className="flex-1 overflow-y-auto space-y-2 min-w-0">
          {!selected && (
            <div className="flex items-center justify-center h-full text-[#62666D] text-sm">
              Select a session to view its full event log
            </div>
          )}

          {selected && events.length === 0 && (
            <p className="text-[#62666D] text-sm">No events recorded</p>
          )}

          {events.map((evt) => {
            const colorClass = EVENT_COLORS[evt.event_type] ?? "text-[#D0D6E0] bg-[#23252A]";
            const isExpanded = expandedEvent === evt.id;

            return (
              <div
                key={evt.id}
                className="rounded-lg border border-[#23252A] overflow-hidden"
              >
                <button
                  onClick={() => setExpandedEvent(isExpanded ? null : evt.id)}
                  className="w-full flex items-center gap-3 px-4 py-3 hover:bg-[#23252A]/50 transition-colors text-left"
                >
                  <span className={`flex-shrink-0 text-xs px-2 py-0.5 rounded font-mono font-medium ${colorClass}`}>
                    {evt.event_type}
                  </span>
                  <span className="text-xs text-[#62666D] flex-shrink-0">
                    #{evt.seq} · {new Date(evt.ts).toLocaleTimeString()}
                  </span>
                  <span className="text-xs text-[#8A8F98] truncate flex-1">
                    {summariseEvent(evt)}
                  </span>
                  <span className="text-[#62666D] text-xs flex-shrink-0">{isExpanded ? "▲" : "▼"}</span>
                </button>

                {isExpanded && (
                  <div className="border-t border-[#23252A] bg-[#08090A] px-4 py-3">
                    <pre className="text-xs text-[#D0D6E0] overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed">
                      {JSON.stringify(evt.payload, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function summariseEvent(evt: SessionEvent): string {
  const p = evt.payload;
  switch (evt.event_type) {
    case "user_message": {
      const msgs = p.messages as Array<{ role: string; content: unknown }>;
      const last = msgs?.findLast?.((m) => m.role === "user");
      const text = typeof last?.content === "string" ? last.content : JSON.stringify(last?.content);
      return (text ?? "").slice(0, 120);
    }
    case "orchestrator_plan":
      return `→ latency ${p.latency_ms}ms`;
    case "agent_selected":
      return `${p.model_id ?? "none"} — ${p.reason ?? ""}`.slice(0, 120);
    case "tool_call":
      return `${p.tool_name ?? ""}(${JSON.stringify(p.input ?? {}).slice(0, 80)})`;
    case "tool_result":
      return String(p.content ?? "").slice(0, 120);
    case "agent_response":
      return `${p.model_id} · ${p.tokens_in}→${p.tokens_out} tok · ${p.latency_ms}ms`;
    case "final_response":
      return `${p.stop_reason} · ${p.total_latency_ms}ms${p.had_repairs ? " · repaired" : ""}`;
    case "error":
      return `[${p.phase}] ${p.message}`;
    case "repair":
      return `${p.tool_name ?? ""} ${p.repaired ? "repaired" : "UNRECOVERABLE"}`;
    case "passthrough_forward":
      return `→ ${p.model_id}:${p.port} (${p.reason})`;
    default:
      return JSON.stringify(p).slice(0, 80);
  }
}
