// app/api/orchestration/desired/orchestrator/route.ts
import { NextRequest, NextResponse } from "next/server";
import { setOrchestrator, getOrchestratorSlot } from "@/lib/orchestration/desired-state";

export async function GET() {
  return NextResponse.json(getOrchestratorSlot());
}

export async function PUT(req: NextRequest) {
  const { model_id } = await req.json();
  const slot = setOrchestrator(model_id ?? null, "dashboard");
  return NextResponse.json(slot);
}
