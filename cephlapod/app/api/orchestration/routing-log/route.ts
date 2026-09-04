// app/api/orchestration/routing-log/route.ts
import { NextRequest, NextResponse } from "next/server";
import { listRoutingLog, getRoutingLogTranscript } from "@/lib/orchestration/routing-log";

export async function GET(req: NextRequest) {
  const limit = Number(req.nextUrl.searchParams.get("limit") ?? "100");
  const session_id = req.nextUrl.searchParams.get("session_id") ?? undefined;
  return NextResponse.json(listRoutingLog({ limit, session_id }));
}
