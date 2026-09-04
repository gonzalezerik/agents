import { getModel, listModels } from "./model-registry";
import { listAgentPool } from "./desired-state";
import type { PreemptionPreview, PreemptionVictim, BlockedEntry, HostObservedState } from "./types";

/**
 * Compute preemption preview for loading `incoming_model_id`.
 * Never stores anything — pure computation from current observed state.
 */
export function computePreemptionPreview(
  incoming_model_id: string,
  observed: HostObservedState[]
): PreemptionPreview {
  const incoming = getModel(incoming_model_id);
  if (!incoming) throw new Error(`Model not found: ${incoming_model_id}`);

  const incomingHost = observed.find((h) => h.host_id === incoming.placement.host_id);
  const pool = listAgentPool();
  const poolIds = new Set(pool.map((e) => e.model_id));

  // GPU VRAM available per UUID on the target host
  const vramFree: Record<string, number> = {};
  if (incomingHost) {
    for (const gpu of incomingHost.gpus) {
      vramFree[gpu.uuid] = gpu.vram_total_mib - gpu.vram_used_mib;
    }
  }

  // Check if incoming model fits without evicting anything
  const incomingVramReq = incoming.placement.vram_req;
  const fitsNow = Object.entries(incomingVramReq).every(
    ([uuid, req]) => (vramFree[uuid] ?? 0) >= req
  );

  if (fitsNow) {
    return {
      incoming_model_id,
      victims: [],
      requires_gap: false,
      estimated_gap_sec: 0,
      blocked_after: computeBlocked(incoming_model_id, observed),
    };
  }

  // Find running models on the target GPUs that could be evicted
  const targetGpus = new Set(incoming.placement.gpus);
  const candidates = incomingHost?.running_models.filter((rm) =>
    rm.gpus.some((g) => targetGpus.has(g))
  ) ?? [];

  const victims: PreemptionVictim[] = [];
  const hypotheticalFree = { ...vramFree };

  for (const candidate of candidates) {
    const model = getModel(candidate.model_id);
    if (!model) continue;

    // Release candidate's VRAM hypothetically
    for (const [uuid, req] of Object.entries(model.placement.vram_req)) {
      hypotheticalFree[uuid] = (hypotheticalFree[uuid] ?? 0) + req;
    }

    victims.push({
      model_id: candidate.model_id,
      model_name: model.name,
      gpus_freed: candidate.gpus,
      mid_request: candidate.queue_depth !== null && candidate.queue_depth > 0,
      auto_resume: poolIds.has(candidate.model_id) &&
        (pool.find((e) => e.model_id === candidate.model_id)?.auto_resume ?? false),
    });

    const fitsAfterEviction = Object.entries(incomingVramReq).every(
      ([uuid, req]) => (hypotheticalFree[uuid] ?? 0) >= req
    );
    if (fitsAfterEviction) break;
  }

  // Determine if we can load-then-switch (enough combined VRAM) or need a gap
  const totalGpuVram: Record<string, number> = {};
  if (incomingHost) {
    for (const gpu of incomingHost.gpus) totalGpuVram[gpu.uuid] = gpu.vram_total_mib;
  }
  const fitsWithEvictions = Object.entries(incomingVramReq).every(
    ([uuid, req]) => (totalGpuVram[uuid] ?? 0) >= req
  );
  const requiresGap = !fitsWithEvictions; // can't even fit after all evictions → gap needed

  return {
    incoming_model_id,
    victims,
    requires_gap: requiresGap,
    estimated_gap_sec: requiresGap ? 15 : 0, // rough estimate; mc-agent refines at runtime
    blocked_after: computeBlocked(incoming_model_id, observed),
  };
}

/**
 * Compute which models become blocked (can't run) once `model_id` occupies its GPUs.
 * Blocked state is topology-derived, never stored.
 */
export function computeBlocked(model_id: string, observed: HostObservedState[]): BlockedEntry[] {
  const model = getModel(model_id);
  if (!model) return [];

  const occupiedGpus = new Set(model.placement.gpus);
  const allModels = listModels({ enabled_only: true });
  const host_observed = observed.find((h) => h.host_id === model.placement.host_id);

  const blocked: BlockedEntry[] = [];
  for (const other of allModels) {
    if (other.id === model_id) continue;
    if (other.placement.host_id !== model.placement.host_id) continue;

    const alreadyRunning = host_observed?.running_models.some((rm) => rm.model_id === other.id);
    if (alreadyRunning) continue;

    const conflict = other.placement.gpus.some((g) => occupiedGpus.has(g));
    if (conflict) {
      blocked.push({
        model_id: other.id,
        model_name: other.name,
        blocked_by_model_id: model_id,
        blocked_gpus: other.placement.gpus.filter((g) => occupiedGpus.has(g)),
      });
    }
  }
  return blocked;
}
