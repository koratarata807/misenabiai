// app/api/campaign-stats/route.ts
import { NextRequest, NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabaseServer";

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
    return NextResponse.json(
      { error: "shop_id is required" },
      { status: 400 }
    );
  }

  const { data, error } = await supabaseServer
    .from("coupon_campaign_cv")
    .select("coupon_type, opened_users, visits, visit_rate")
    .eq("shop_id", shopId)
    .order("coupon_type", { ascending: true });

  if (error) {
    console.error(error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const campaigns: CampaignRow[] = (data ?? []).map((row) => ({
    coupon_type: row.coupon_type,
    opened_users: row.opened_users ?? 0,
    visits: row.visits ?? 0,
    visit_rate: row.visit_rate ?? 0,
  }));

  return NextResponse.json({
    shop_id: shopId,
    campaigns,
  });
}
