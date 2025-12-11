// app/api/user-scores/route.ts
import { NextRequest, NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabaseServer";

type ScoreRow = {
  shop_id: string;
  user_id: string;
  opens_7d: number | null;
  last_open_at: string | null;
  score: "HOT" | "WARM" | "COLD";
};

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const shopId = searchParams.get("shop_id");
  const scoreFilter = searchParams.get("score"); // "HOT" / "WARM" / "COLD"（任意）
  const limitParam = searchParams.get("limit");  // 件数制限（任意）

  if (!shopId) {
    return NextResponse.json(
      { error: "shop_id is required" },
      { status: 400 }
    );
  }

  let query = supabaseServer
    .from("coupon_user_scores")
    .select("shop_id, user_id, opens_7d, last_open_at, score")
    .eq("shop_id", shopId)
    .order("opens_7d", { ascending: false });

  if (scoreFilter) {
    query = query.eq("score", scoreFilter);
  }
  if (limitParam) {
    const n = Number(limitParam);
    if (!Number.isNaN(n) && n > 0) {
      query = query.limit(n);
    }
  }

  const { data, error } = await query;

  if (error) {
    console.error(error);
    return NextResponse.json(
      { error: error.message },
      { status: 500 }
    );
  }

  const rows: ScoreRow[] = (data ?? []) as ScoreRow[];

  return NextResponse.json({
    shop_id: shopId,
    count: rows.length,
    users: rows,
  });
}
