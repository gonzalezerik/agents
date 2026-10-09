// app/api/orchestration/reconcile/route.ts
import { NextRequest, NextResponse } from "next/server";
import { reconcile, getReconcilerState, setFreeze } from "@/lib/orchestration/reconciler";

export async function GET() {
  return NextResponse.json(getReconcilerState());
}

export async function POST() {
  const result = await reconcile();
  return NextResponse.json(result);
}

export async function PATCH(req: NextRequest) {
  const { frozen } = await req.json();
  setFreeze(Boolean(frozen));
  return NextResponse.json(getReconcilerState());
}
