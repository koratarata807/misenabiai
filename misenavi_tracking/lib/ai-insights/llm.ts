// lib/ai-insights/llm.ts
export type GeneratedInsight = {
  summary: string;
  likely_causes: Array<{
    cause: string;
    evidence: string;
    confidence: "low" | "med" | "high";
  }>;
  recommended_actions: Array<{
    action: string;
    why: string;
  }>;
  questions_to_confirm: string[];
};

type GenerateArgs = {
  prompt: string;
  // ログや追跡用（任意）
  shopId?: string;
};

function safeJsonParse(text: string): unknown {
  // ありがちな ```json ... ``` を剥がす
  const cleaned = text
    .trim()
    .replace(/^```json\s*/i, "")
    .replace(/^```\s*/i, "")
    .replace(/```$/i, "")
    .trim();

  return JSON.parse(cleaned);
}

function isGeneratedInsight(x: any): x is GeneratedInsight {
  if (!x || typeof x !== "object") return false;
  if (typeof x.summary !== "string") return false;
  if (!Array.isArray(x.likely_causes)) return false;
  if (!Array.isArray(x.recommended_actions)) return false;
  if (!Array.isArray(x.questions_to_confirm)) return false;

  // 軽いバリデーション（厳密にしすぎない）
  for (const c of x.likely_causes) {
    if (!c || typeof c.cause !== "string" || typeof c.evidence !== "string") return false;
    if (!["low", "med", "high"].includes(c.confidence)) return false;
  }
  for (const a of x.recommended_actions) {
    if (!a || typeof a.action !== "string" || typeof a.why !== "string") return false;
  }
  for (const q of x.questions_to_confirm) {
    if (typeof q !== "string") return false;
  }
  return true;
}

export async function generateInsightWithLLM(args: GenerateArgs): Promise<GeneratedInsight> {
  const apiKey = process.env.OPENAI_API_KEY;
  if (!apiKey) {
    throw new Error("OPENAI_API_KEY is missing");
  }

  // モデルは環境変数で差し替え可能にしておく（運用上の安全策）
  const model = process.env.OPENAI_MODEL || "gpt-4o-mini";

  const controller = new AbortController();
  const timeoutMs = 12_000;
  const t = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        temperature: 0.2,
        messages: [
          {
            role: "system",
            content:
              "You are a business analytics assistant for a LINE coupon SaaS. Output MUST be valid JSON only (no markdown).",
          },
          { role: "user", content: args.prompt },
        ],
      }),
    });

    if (!res.ok) {
      const txt = await res.text().catch(() => "");
      throw new Error(`OpenAI API error: ${res.status} ${res.statusText} ${txt}`);
    }

    const json = await res.json();
    const content: string | undefined =
      json?.choices?.[0]?.message?.content ?? undefined;

    if (!content) {
      throw new Error("OpenAI returned empty content");
    }

    const parsed = safeJsonParse(content);
    if (!isGeneratedInsight(parsed)) {
      throw new Error("OpenAI returned invalid JSON schema");
    }

    // 上限を掛けてUI破綻を防ぐ（運用上のガード）
    return {
      summary: parsed.summary.slice(0, 280),
      likely_causes: parsed.likely_causes.slice(0, 3),
      recommended_actions: parsed.recommended_actions.slice(0, 3),
      questions_to_confirm: parsed.questions_to_confirm.slice(0, 3),
    };
  } finally {
    clearTimeout(t);
  }
}
