import { getInvestigableAlerts } from "@/lib/agent-investigate";

export const dynamic = "force-dynamic";

export async function GET() {
  const alerts = await getInvestigableAlerts();
  return Response.json({ alerts });
}
