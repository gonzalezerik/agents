// app/api/orchestration/desired/agents/[id]/route.ts
import { NextRequest, NextResponse } from "next/server";
import { removeFromAgentPool, setAutoResume } from "@/lib/orchestration/desired-state";

export async function DELETE(_: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const ok = removeFromAgentPool(decodeURIComponent(id));
  if (!ok) return NextResponse.json({ error: "Not in pool" }, { status: 404 });
  return NextResponse.json({ ok: true });
}

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { auto_resume } = await req.json();
  setAutoResume(decodeURIComponent(id), Boolean(auto_resume));
  return NextResponse.json({ ok: true });
}
