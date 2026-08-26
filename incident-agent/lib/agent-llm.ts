/** Calls the homelab's own LLM infra (gpuhost) for diagnosis + fix proposals. */

const GPUHOST_URL = process.env.GPUHOST_LLM_URL ?? "http://localhost:8002";

export interface DiagnosisResult {
  investigation: string;
  proposedFix: string;
  confidence: number;
}

export async function diagnose(context: string): Promise<DiagnosisResult | null> {
  try {
    const res = await fetch(`${GPUHOST_URL}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "qwen3.8-27b-A100-1",
        messages: [
          {
            role: "system",
            content:
              "You are the investigating agent for a homelab ops dashboard. Given an incident's raw context (alert, pod status, logs), " +
              "respond with EXACTLY three sections in this format, nothing else:\n" +
              "INVESTIGATION: <2-4 sentence root-cause analysis, grounded only in the given context, no speculation beyond it>\n" +
              "PROPOSED_FIX: <one concrete, specific action a human could take, or 'none - needs physical/manual intervention' if nothing safe can be automated>\n" +
              "CONFIDENCE: <a number 0.0-1.0 for how confident you are in the diagnosis>",
          },
          { role: "user", content: context },
        ],
        temperature: 0.2,
        max_tokens: 500,
      }),
      signal: AbortSignal.timeout(30000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const text: string = data?.choices?.[0]?.message?.content ?? "";

    const investigation = text.match(/INVESTIGATION:\s*([\s\S]*?)(?=PROPOSED_FIX:|$)/)?.[1]?.trim() ?? text;
    const proposedFix = text.match(/PROPOSED_FIX:\s*([\s\S]*?)(?=CONFIDENCE:|$)/)?.[1]?.trim() ?? "unknown";
    const confidenceMatch = text.match(/CONFIDENCE:\s*([\d.]+)/)?.[1];
    const confidence = confidenceMatch ? parseFloat(confidenceMatch) : 0.5;

    return { investigation, proposedFix, confidence: Number.isFinite(confidence) ? confidence : 0.5 };
  } catch {
    return null;
  }
}
