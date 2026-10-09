// app/api/orchestration/sessions/[id]/events/route.ts
import { NextRequest, NextResponse } from "next/server";

const MC_AGENT = process.env.MC_AGENT_GPUHOST_URL ?? "http://localhost:4001";
const TOKEN    = process.env.MC_AGENT_TOKEN ?? "";

export async function GET(_: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const res = await fetch(
    `${MC_AGENT}/sessions/${encodeURIComponent(id)}/events`,
    { headers: { Authorization: `Bearer ${TOKEN}` }, cache: "no-store" }
  );
  return NextResponse.json(await res.json(), { status: res.status });
}
