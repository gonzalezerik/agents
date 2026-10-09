/**
 * WCAG triage call for the a11y agent. Any OpenAI-compatible endpoint works
 * (llama.cpp server / vLLM); the model returns a fixed set of labeled
 * sections that are parsed in code.
 */

const LLM_URL = process.env.A11Y_LLM_URL ?? "http://localhost:8080";
const LLM_MODEL = process.env.A11Y_LLM_MODEL ?? "qwen3";

export interface A11yDiagnosis {
  isValid: boolean;
  wcagCriterion: string;
  analysis: string;
  file: string | null;
  originalCode: string | null;
  patchedCode: string | null;
  confidence: number;
}

export async function diagnoseA11y(input: {
  url: string;
  description: string;
}): Promise<A11yDiagnosis | null> {
  try {
    const res = await fetch(`${LLM_URL}/v1/chat/completions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: LLM_MODEL,
        messages: [
          {
            role: "system",
            content:
              "You are an expert WCAG 2.2 auditor for a Next.js portfolio site. " +
              "Given a user's accessibility complaint, determine if it is a genuine WCAG 2.2 Level AA failure. " +
              "If it is valid, identify the source file and generate a minimal TypeScript/JSX patch. " +
              "Respond with EXACTLY these sections, nothing else:\n" +
              "IS_VALID: yes|no\n" +
              "WCAG_CRITERION: <e.g. 1.1.1 Non-text Content, or 'none'>\n" +
              "ANALYSIS: <2-4 sentences explaining why this is or is not a violation>\n" +
              "FILE: <relative path from src/ e.g. components/Gallery.tsx, or 'unknown'>\n" +
              "ORIGINAL: <the exact lines that need to change, or 'none'>\n" +
              "PATCHED: <the replacement lines with the fix applied, or 'none'>\n" +
              "CONFIDENCE: <0.0-1.0>",
          },
          {
            role: "user",
            content: `URL: ${input.url}\nUser complaint: ${input.description}`,
          },
        ],
        temperature: 0.1,
        max_tokens: 1200,
        chat_template_kwargs: { enable_thinking: false },
      }),
      signal: AbortSignal.timeout(45000),
    });
    if (!res.ok) return null;
    const data = await res.json();
    const text: string = data?.choices?.[0]?.message?.content ?? "";

    const isValidStr = text.match(/IS_VALID:\s*(yes|no)/i)?.[1]?.toLowerCase();
    const wcagCriterion = text.match(/WCAG_CRITERION:\s*([\s\S]+?)(?=\n[A-Z_]+:|$)/)?.[1]?.trim() ?? "none";
    const analysis = text.match(/ANALYSIS:\s*([\s\S]*?)(?=FILE:|$)/)?.[1]?.trim() ?? text;
    const file = text.match(/FILE:\s*([\s\S]+?)(?=\n[A-Z_]+:|$)/)?.[1]?.trim() ?? null;
    const original = text.match(/ORIGINAL:\s*([\s\S]*?)(?=PATCHED:|$)/)?.[1]?.trim() ?? null;
    const patched = text.match(/PATCHED:\s*([\s\S]*?)(?=CONFIDENCE:|$)/)?.[1]?.trim() ?? null;
    const confidenceMatch = text.match(/CONFIDENCE:\s*([\d.]+)/)?.[1];
    const confidence = confidenceMatch ? parseFloat(confidenceMatch) : 0.5;

    return {
      isValid: isValidStr === "yes",
      wcagCriterion: wcagCriterion === "none" ? "" : wcagCriterion,
      analysis,
      file: file === "unknown" || !file ? null : `src/${file.replace(/^src\//, "")}`,
      originalCode: original === "none" ? null : original,
      patchedCode: patched === "none" ? null : patched,
      confidence: Number.isFinite(confidence) ? confidence : 0.5,
    };
  } catch {
    return null;
  }
}
