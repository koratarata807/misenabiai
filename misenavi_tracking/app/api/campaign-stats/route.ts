// app/api/campaign-stats/route.ts
import { NextRequest, NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabaseServer";
import { decideInsightV1 } from "@/lib/ai-insights/rules";

type CampaignRow = {
  coupon_type: string;
  opened_users: number | null;
  visits: number | null;
  visit_rate: number | null;
};

function clamp01(x: number) {
  if (!Number.isFinite(x)) return 0;
  if (x < 0) return 0;
  if (x > 1) return 1;
  return x;
}

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const shopId = searchParams.get("shop_id");

  if (!shopId) {
    return NextResponse.json({ error: "shop_id is required" }, { status: 400 });
  }

  // v1.1：直近7日固定（母数が膨張して指標が死ぬのを防ぐ）
  const now = new Date();
  const sinceIso = new Date(
    now.getTime() - 7 * 24 * 60 * 60 * 1000
  ).toISOString();

  // ========== 1) 既存CVビューからキャンペーン別KPI ==========
  const { data: cvData, error: cvError } = await supabaseServer
    .from("coupon_campaign_cv")
    .select("coupon_type, opened_users, visits, visit_rate")
    .eq("shop_id", shopId)
    .order("coupon_type", { ascending: true });

  if (cvError) {
    console.error(cvError);
    return NextResponse.json({ error: cvError.message }, { status: 500 });
  }

  const campaignsBase = (cvData ?? []).map((row: CampaignRow) => ({
    coupon_type: row.coupon_type,
    opened_users: row.opened_users ?? 0,
    visits: row.visits ?? 0,
    visit_rate: row.visit_rate ?? 0,
  }));

  // ========== 2) sentUsers を coupon_send_logs から取得（直近7日） ==========
  const { data: sendLogs, error: sendError } = await supabaseServer
    .from("coupon_send_logs")
    .select("user_id, sent_at")
    .eq("shop_id", shopId)
    .gte("sent_at", sinceIso);

  if (sendError) {
    console.error(sendError);
    return NextResponse.json({ error: sendError.message }, { status: 500 });
  }

  const sentUsers = new Set((sendLogs ?? []).map((r: any) => r.user_id)).size;

  // ========== 3) 店舗KPI（合算） ==========
  const openedUsers = campaignsBase.reduce((a, c) => a + c.opened_users, 0);
  const visits = campaignsBase.reduce((a, c) => a + c.visits, 0);

  const openRate = sentUsers > 0 ? clamp01(openedUsers / sentUsers) : 0;
  const ctr = sentUsers > 0 ? clamp01(visits / sentUsers) : 0;

  // v1.1：前週比較はまだ無し
  const openRateDelta = 0;
  const ctrDelta = 0;

  // ========== 4) しきい値（業務ルール）で判定 ==========
  const decision = decideInsightV1({
    sentUsers,
    openRate,
    ctr,
    openRateDelta,
    ctrDelta,
  });

  // ========== 5) campaigns も表示崩れ防止のため rate を 0〜1 に統一 ==========
  const campaigns = campaignsBase.map((c) => ({
    ...c,
    // v1.1：coupon_type別のsent_usersはまだ分離できてないので店全体母数を参考値として返す
    sent_users: sentUsers,
    open_rate: sentUsers > 0 ? clamp01(c.opened_users / sentUsers) : 0,
    visit_rate: sentUsers > 0 ? clamp01(c.visits / sentUsers) : 0,
  }));

  // ========== 6) UI用の insight ==========
  const insight = {
    period: "last7d",
    kpi: {
      sentUsers,
      openedUsers,
      visits,
      openRate,
      ctr,
      openRateDelta,
      ctrDelta,
    },
    severity: decision.severity,
    topics: decision.topics,
    flags: decision.flags,
    summary:
      decision.severity === "warning"
        ? "注意：パフォーマンスが低下しています。"
        : decision.severity === "info"
        ? "参考：改善ポイントがあります。"
        : "良好：配信は安定しています。",
  };

  return NextResponse.json({
    shop_id: shopId,
    campaigns,
    insight,
  });
}
