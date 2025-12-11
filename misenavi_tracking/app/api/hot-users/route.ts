// app/api/hot-users/route.ts
import { NextRequest, NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabaseServer";

type SegmentRow = {
  shop_id: string;
  user_id: string;
  segment: "HOT" | "WARM" | "COLD";
  open_count: number;
  days_since_last_open: number;
  // last_opened_at: string | null; // ← いったん削除 or コメントアウト
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
    .from("coupon_user_segments")
    .select(
      // ← ここから last_opened_at を消す
      "shop_id, user_id, segment, open_count, days_since_last_open"
    )
    .eq("shop_id", shopId)
    .eq("segment", "HOT")
    .order("open_count", { ascending: false })
    .limit(50);

  if (error) {
    console.error(error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    shop_id: shopId,
    users: (data ?? []) as SegmentRow[],
  });
}
