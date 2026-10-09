// app/api/orchestration/preemption/route.ts
import { NextRequest, NextResponse } from "next/server";
import { computePreemptionPreview } from "@/lib/orchestration/preemption";
import { fetchAllObservedStates } from "@/lib/orchestration/mc-agent-client";

export async function GET(req: NextRequest) {
  const model_id = req.nextUrl.searchParams.get("model_id");
  if (!model_id) return NextResponse.json({ error: "model_id required" }, { status: 400 });
  const observed = await fetchAllObservedStates();
  const preview = computePreemptionPreview(model_id, observed);
  return NextResponse.json(preview);
}
