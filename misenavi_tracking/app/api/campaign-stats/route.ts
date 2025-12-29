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

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const shopId = searchParams.get("shop_id");

  if (!shopId) {
    return NextResponse.json({ error: "shop_id is required" }, { status: 400 });
  }

  // ========== 1) 既存のCVビューからキャンペーン別KPIを取得 ==========
  const { data, error } = await supabaseServer
    .from("coupon_campaign_cv")
    .select("coupon_type, opened_users, visits, visit_rate")
    .eq("shop_id", shopId)
    .order("coupon_type", { ascending: true });

  if (error) {
    console.error(error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const campaigns = (data ?? []).map((row: CampaignRow) => ({
    coupon_type: row.coupon_type,
    opened_users: row.opened_users ?? 0,
    visits: row.visits ?? 0,
    visit_rate: row.visit_rate ?? 0,
  }));

  // ========== 2) sentUsers を Supabase（coupon_send_logs）から取得 ==========
  // 送信先ユーザーIDは coupon_send_logs.user_id を利用
  const { data: sendLogs, error: sendError } = await supabaseServer
    .from("coupon_send_logs")
    .select("user_id")
    .eq("shop_id", shopId);

  if (sendError) {
    console.error(sendError);
    return NextResponse.json({ error: sendError.message }, { status: 500 });
  }

  // ユニーク送信人数
  const sentUsers = new Set((sendLogs ?? []).map((r) => r.user_id)).size;

  // ========== 3) 店舗の総評KPI（合算） ==========
  const openedUsers = campaigns.reduce((a, c) => a + c.opened_users, 0);
  const visits = campaigns.reduce((a, c) => a + c.visits, 0);

  const openRate = sentUsers > 0 ? openedUsers / sentUsers : 0;
  const ctr = sentUsers > 0 ? visits / sentUsers : 0;

  // v1.1：前週比較はまだ無し（後で7d/prev7d VIEWで実装）
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

  // ========== 5) UIで使いやすい形に整形 ==========
  const insight = {
    period: "v1.1",
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
