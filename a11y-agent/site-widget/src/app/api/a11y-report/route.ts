import { NextResponse } from "next/server";
import { db } from "@/db";
import { a11yReports } from "@/db/schema";
import { headers } from "next/headers";

export async function POST(request: Request) {
  let body: { url?: string; description?: string; userAgent?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const { url, description, userAgent } = body;
  if (!url || !description) {
    return NextResponse.json({ error: "url and description are required" }, { status: 400 });
  }
  if (description.length > 2000) {
    return NextResponse.json({ error: "description too long" }, { status: 400 });
  }

  const headersList = await headers();
  const ip =
    headersList.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";

  const [report] = await db
    .insert(a11yReports)
    .values({ url, description, userAgent: userAgent ?? null, ip })
    .returning({ id: a11yReports.id });

  // Fire-and-forget to ops agent — never block the user response on this
  const webhookUrl = process.env.MISSION_CONTROL_WEBHOOK_URL;
  const webhookSecret = process.env.MISSION_CONTROL_WEBHOOK_SECRET;
  if (webhookUrl && webhookSecret && report) {
    fetch(webhookUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Webhook-Secret": webhookSecret,
      },
      body: JSON.stringify({ reportId: report.id, url, description }),
    }).catch(() => {});
  }

  return NextResponse.json({ ok: true });
}
