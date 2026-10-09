import { NextRequest, NextResponse } from "next/server";
import { listModels, upsertModel, validateModel } from "@/lib/orchestration/model-registry";
import { seedModels } from "@/lib/orchestration/seed-models";

let seeded = false;

function ensureSeeded() {
  if (!seeded) {
    const { listModels: lm } = require("@/lib/orchestration/model-registry");
    if (lm().length === 0) seedModels();
    seeded = true;
  }
}

export async function GET(req: NextRequest) {
  ensureSeeded();
  const enabledOnly = req.nextUrl.searchParams.get("enabled") === "true";
  return NextResponse.json(listModels(enabledOnly ? { enabled_only: true } : undefined));
}

export async function POST(req: NextRequest) {
  const body = await req.json();
  const warnings = validateModel(body);
  const blocking = warnings.filter((w) => w.severity === "block");
  if (blocking.length > 0) {
    return NextResponse.json({ error: "Blocked by validation", warnings }, { status: 422 });
  }
  const model = upsertModel(body);
  return NextResponse.json({ model, warnings }, { status: 201 });
}
