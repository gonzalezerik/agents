// app/api/orchestration/desired/route.ts
// GET → full desired state (orchestrator slot + agent pool)
// POST /orchestrator → set orchestrator
// POST /agents → add agent to pool
import { NextRequest, NextResponse } from "next/server";
import { getOrchestratorSlot, setOrchestrator, listAgentPool, addToAgentPool, removeFromAgentPool } from "@/lib/orchestration/desired-state";

export async function GET() {
  return NextResponse.json({
    orchestrator: getOrchestratorSlot(),
    agent_pool: listAgentPool(),
  });
}
