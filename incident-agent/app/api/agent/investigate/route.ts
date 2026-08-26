import { investigateAlert } from "@/lib/agent-investigate";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const fingerprint = body?.fingerprint;
  if (typeof fingerprint !== "string") {
    return Response.json({ error: "fingerprint required" }, { status: 400 });
  }
  const run = await investigateAlert(fingerprint);
  if (!run) {
    return Response.json({ error: "could not investigate - alert not found or DB unavailable" }, { status: 502 });
  }
  return Response.json({ run });
}
