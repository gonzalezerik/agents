import { listAgentRuns } from "@/lib/pg-client";

export const dynamic = "force-dynamic";

export async function GET() {
  const runs = await listAgentRuns();
  return Response.json({ runs });
}
