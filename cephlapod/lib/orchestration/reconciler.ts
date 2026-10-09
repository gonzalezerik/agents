import { getDb } from "./db";
import { getOrchestratorSlot, listAgentPool } from "./desired-state";
import { fetchAllObservedStates } from "./mc-agent-client";
import { startModel, stopModel } from "./mc-agent-client";
import type { ReconcilerState, ReconcilerAction, HostObservedState } from "./types";

const MAX_TRANSITIONS_PER_MINUTE = 2;

// ── Freeze ────────────────────────────────────────────────────────────────────

export function getReconcilerState(): ReconcilerState {
  const db = getDb();
  const row = db.prepare("SELECT * FROM reconciler_state WHERE id = 1").get() as Record<string, unknown>;
  return {
    frozen: (row.frozen as number) === 1,
    last_run: row.last_run as string | null,
    last_error: row.last_error as string | null,
    pending_actions: [],
    transition_count_last_minute: row.transition_count_last_minute as number,
  };
}

export function setFreeze(frozen: boolean): void {
  getDb().prepare("UPDATE reconciler_state SET frozen = ? WHERE id = 1").run(frozen ? 1 : 0);
}

function recordTransition() {
  const db = getDb();
  const now = new Date().toISOString();
  const state = db.prepare("SELECT transition_count_last_minute, last_transition_window_start FROM reconciler_state WHERE id = 1").get() as
    { transition_count_last_minute: number; last_transition_window_start: string | null };

  const windowStart = state.last_transition_window_start
    ? new Date(state.last_transition_window_start).getTime()
    : 0;
  const inWindow = Date.now() - windowStart < 60_000;
  const count = inWindow ? state.transition_count_last_minute + 1 : 1;

  db.prepare("UPDATE reconciler_state SET transition_count_last_minute = ?, last_transition_window_start = ? WHERE id = 1")
    .run(count, inWindow ? state.last_transition_window_start : now);
}

function isRateLimited(): boolean {
  const db = getDb();
  const row = db.prepare("SELECT transition_count_last_minute, last_transition_window_start FROM reconciler_state WHERE id = 1").get() as
    { transition_count_last_minute: number; last_transition_window_start: string | null };
  if (!row.last_transition_window_start) return false;
  const windowStart = new Date(row.last_transition_window_start).getTime();
  if (Date.now() - windowStart >= 60_000) return false;
  return row.transition_count_last_minute >= MAX_TRANSITIONS_PER_MINUTE;
}

// ── Diff computation ──────────────────────────────────────────────────────────

export function computeDiff(observed: HostObservedState[]): ReconcilerAction[] {
  const desired_orch = getOrchestratorSlot();
  const desired_pool = listAgentPool();

  const actions: ReconcilerAction[] = [];
  const runningIds = new Set(observed.flatMap((h) => h.running_models.map((m) => m.model_id)));

  // Orchestrator: ensure it's running
  if (desired_orch.model_id && !runningIds.has(desired_orch.model_id)) {
    actions.push({ type: "start", model_id: desired_orch.model_id });
  }

  // Agent pool: ensure all pool members are running
  for (const entry of desired_pool) {
    if (!runningIds.has(entry.model_id)) {
      actions.push({ type: "start", model_id: entry.model_id });
    }
  }

  // Auto-resume: models with auto_resume that stopped unexpectedly
  for (const entry of desired_pool.filter((e) => e.auto_resume)) {
    if (!runningIds.has(entry.model_id)) {
      // Already covered by "start" above; tag reason for logging
      const existing = actions.find((a) => a.type === "start" && a.model_id === entry.model_id);
      if (!existing) actions.push({ type: "restore", model_id: entry.model_id, reason: "auto-resume" });
    }
  }

  return actions;
}

// ── Reconcile ─────────────────────────────────────────────────────────────────

export async function reconcile(): Promise<{ actions_taken: number; skipped: string | null }> {
  const db = getDb();
  const now = new Date().toISOString();

  const state = getReconcilerState();
  if (state.frozen) {
    return { actions_taken: 0, skipped: "frozen" };
  }
  if (isRateLimited()) {
    return { actions_taken: 0, skipped: "rate-limited (max 2 transitions/min)" };
  }

  let actions_taken = 0;
  let last_error: string | null = null;

  try {
    const observed = await fetchAllObservedStates();
    const actions = computeDiff(observed);

    for (const action of actions) {
      if (isRateLimited()) break;

      try {
        if (action.type === "start") {
          // mc-agent resolves host from model_id prefix
          const host_id = action.model_id.split(":")[0];
          await startModel(host_id, action.model_id);
          recordTransition();
          actions_taken++;
        } else if (action.type === "stop") {
          const host_id = action.model_id.split(":")[0];
          await stopModel(host_id, action.model_id, action.reason);
          recordTransition();
          actions_taken++;
        } else if (action.type === "restore") {
          const host_id = action.model_id.split(":")[0];
          await startModel(host_id, action.model_id);
          recordTransition();
          actions_taken++;
        }
      } catch (err) {
        last_error = String(err);
      }
    }
  } catch (err) {
    last_error = String(err);
  }

  db.prepare("UPDATE reconciler_state SET last_run = ?, last_error = ? WHERE id = 1")
    .run(now, last_error);

  return { actions_taken, skipped: null };
}
