import { NextRequest, NextResponse } from "next/server";
import { getModel, upsertModel, deleteModel, validateModel } from "@/lib/orchestration/model-registry";

export async function GET(_: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const model = getModel(id);
  if (!model) return NextResponse.json({ error: "Not found" }, { status: 404 });
  return NextResponse.json(model);
}

export async function PUT(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json();
  const warnings = validateModel({ ...body, id });
  const blocking = warnings.filter((w) => w.severity === "block");
  if (blocking.length > 0) {
    return NextResponse.json({ error: "Blocked", warnings }, { status: 422 });
  }
  const model = upsertModel({ ...body, id });
  return NextResponse.json({ model, warnings });
}

export async function DELETE(_: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const ok = deleteModel(id);
  if (!ok) return NextResponse.json({ error: "Not found" }, { status: 404 });
  return NextResponse.json({ ok: true });
}
