// app/api/orchestration/observed/route.ts
// Polls mc-agent on all hosts, returns merged observed state
import { NextResponse } from "next/server";
import { fetchAllObservedStates } from "@/lib/orchestration/mc-agent-client";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export async function GET() {
  const states = await fetchAllObservedStates();
  return NextResponse.json(states);
}
