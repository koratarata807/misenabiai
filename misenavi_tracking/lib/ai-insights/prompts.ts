// lib/ai-insights/prompts.ts
import type { GeneratedInsight } from "./llm";

type Decision = {
  severity: "ok" | "info" | "warning";
  topics: string[];
  flags: Record<string, boolean>;
};

type KPI = {
  sentUsers: number;
  openedUsers: number;
  visits: number;
  openRate: number;
  ctr: number;
  openRateDelta: number;
  ctrDelta: number;
};

type Campaign = {
  coupon_type: string;
  opened_users: number;
  visits: number;
  visit_rate: number;
};

export function buildInsightPrompt(params: {
  shopId: string;
  decision: Decision;
  kpi: KPI;
  campaigns: Campaign[];
}): string {
  const { shopId, decision, kpi, campaigns } = params;

  // 数字はLLMの誤読を減らすため、明示的にフォーマット
  const pct = (x: number) => `${(x * 100).toFixed(1)}%`;

  // キャンペーン別の差を見せたいので、上位だけ抜き出し
  const campaignLines = campaigns
    .slice()
    .sort((a, b) => (b.visit_rate ?? 0) - (a.visit_rate ?? 0))
    .slice(0, 6)
    .map(
      (c) =>
        `- ${c.coupon_type}: opened=${c.opened_users}, visits=${c.visits}, visit_rate=${pct(
          c.visit_rate ?? 0
        )}`
    )
    .join("\n");

  return `
あなたは「みせなびAI」の店舗向けアナリストです。
以下のデータから、"断定しすぎない" 原因仮説と改善策を提示してください。

【制約（必須）】
- 出力は JSON のみ（Markdown禁止、コードフェンス禁止）
- 原因仮説は最大3つ、各仮説に evidence（根拠）を必ず付ける
- confidence は "low"|"med"|"high" のいずれか
- recommended_actions は最大3つ、各 action に why（理由）を付ける
- 不足情報がある場合は questions_to_confirm に最大3つ入れる
- 数字に基づかない憶測は書かない（書くなら「可能性」＋根拠）

【店舗ID】
${shopId}

【判定（ルールベースの論点）】
severity: ${decision.severity}
topics:
${decision.topics.map((t) => `- ${t}`).join("\n")}

【店舗KPI（集計）】
sentUsers: ${kpi.sentUsers}
openedUsers: ${kpi.openedUsers}
visits: ${kpi.visits}
openRate: ${pct(kpi.openRate)}
ctr: ${pct(kpi.ctr)}
openRateDelta: ${kpi.openRateDelta.toFixed(4)}
ctrDelta: ${kpi.ctrDelta.toFixed(4)}

【キャンペーン別（上位）】
${campaignLines || "(no campaigns)"}

【期待するJSONスキーマ】
{
  "summary": "1〜2文の要約",
  "likely_causes": [
    {"cause":"…","evidence":"…","confidence":"low|med|high"}
  ],
  "recommended_actions": [
    {"action":"…","why":"…"}
  ],
  "questions_to_confirm": ["…"]
}
`.trim();
}

// フォールバック（LLM失敗時にUIを落とさない）
export function fallbackGeneratedInsight(decision: Decision): GeneratedInsight {
  return {
    summary:
      decision.severity === "warning"
        ? "反応が弱い可能性があります。まずは訴求点と導線の見直しを推奨します。"
        : decision.severity === "info"
        ? "改善余地があります。小さな変更で反応が伸びる可能性があります。"
        : "現状は安定しています。効果が落ちないように微調整しながら運用しましょう。",
    likely_causes: decision.topics.slice(0, 3).map((t) => ({
      cause: t,
      evidence: "ルールベース判定に基づく指摘（LLM生成は未実行）",
      confidence: "low" as const,
    })),
    recommended_actions: [
      { action: "文言（ベネフィット）を1つに絞って再作成", why: "訴求点の分散を防ぐため" },
      { action: "配信時間を夕方〜夜に寄せてA/B", why: "反応が出やすい時間帯を探索するため" },
    ],
    questions_to_confirm: ["最近、画像や文言を変更しましたか？", "配信時間帯は何時に設定していますか？"],
  };
}
