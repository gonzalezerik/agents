import { NextResponse } from "next/server";
import { investigateA11yComplaint } from "@/lib/a11y-agent";

export async function POST(request: Request) {
  const secret = request.headers.get("x-webhook-secret");
  if (secret !== process.env.MISSION_CONTROL_WEBHOOK_SECRET) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }

  let body: { reportId?: string; url?: string; description?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const { reportId, url, description } = body;
  if (!reportId || !url || !description) {
    return NextResponse.json({ error: "reportId, url, description required" }, { status: 400 });
  }

  // Respond immediately; run investigation in background
  investigateA11yComplaint({ reportId, url, description }).catch(console.error);

  return NextResponse.json({ ok: true, reportId });
}
