// app/api/orchestration/sessions/route.ts
// Proxies mc-agent /sessions so the dashboard can list past conversations
import { NextRequest, NextResponse } from "next/server";

const MC_AGENT = process.env.MC_AGENT_GPUHOST_URL ?? "http://localhost:4001";
const TOKEN    = process.env.MC_AGENT_TOKEN ?? "";

function agentHeaders() {
  return { Authorization: `Bearer ${TOKEN}` };
}

export async function GET(req: NextRequest) {
  const limit = req.nextUrl.searchParams.get("limit") ?? "100";
  const res = await fetch(`${MC_AGENT}/sessions?limit=${limit}`, { headers: agentHeaders(), cache: "no-store" });
  return NextResponse.json(await res.json(), { status: res.status });
}
