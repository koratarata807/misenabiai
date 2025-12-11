// app/api/user-segments/route.ts
import { NextRequest, NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabaseServer";

type SegmentType = "HOT" | "WARM" | "COLD";

type SegmentRow = {
  shop_id: string;
  user_id: string;
  segment: SegmentType;
  open_count: number;
  days_since_last_open: number;
  last_opened_at: string | null;
};

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const shopId = searchParams.get("shop_id");
  const segmentParam = searchParams.get("segment") as SegmentType | null;

  // shop_id が必須
  if (!shopId) {
    return NextResponse.json(
      { error: "shop_id is required" },
      { status: 400 }
    );
  }

  // segment は HOT / WARM / COLD のいずれか（未指定なら HOT）
  const allowed: SegmentType[] = ["HOT", "WARM", "COLD"];
  const segment: SegmentType = segmentParam && allowed.includes(segmentParam)
    ? segmentParam
    : "HOT";

  const { data, error } = await supabaseServer
    .from("coupon_user_segments")
    .select(
      "shop_id, user_id, segment, open_count, days_since_last_open, last_opened_at"
    )
    .eq("shop_id", shopId)
    .eq("segment", segment)
    .order("open_count", { ascending: false })
    .limit(50);

  if (error) {
    console.error("[user-segments] Supabase error:", error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({
    shop_id: shopId,
    segment,
    users: (data ?? []) as SegmentRow[],
  });
}
