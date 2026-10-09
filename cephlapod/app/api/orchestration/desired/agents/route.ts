// app/api/orchestration/desired/agents/route.ts
import { NextRequest, NextResponse } from "next/server";
import { listAgentPool, addToAgentPool } from "@/lib/orchestration/desired-state";

export async function GET() {
  return NextResponse.json(listAgentPool());
}

export async function POST(req: NextRequest) {
  const { model_id, auto_resume = false } = await req.json();
  if (!model_id) return NextResponse.json({ error: "model_id required" }, { status: 400 });
  const entry = addToAgentPool(model_id, auto_resume);
  return NextResponse.json(entry, { status: 201 });
}
