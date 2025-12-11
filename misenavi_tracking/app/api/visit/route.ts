// app/api/visit/route.ts
import { NextRequest, NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabaseServer";

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const shopId = searchParams.get("shop_id");
  const couponType = searchParams.get("coupon_type") ?? "7days";

  if (!shopId) {
    return NextResponse.json(
      { error: "shop_id is required" },
      { status: 400 }
    );
  }

  const userAgent = req.headers.get("user-agent") ?? "";
  const ip = req.headers.get("x-forwarded-for") ?? "";

  const { error } = await supabaseServer.from("coupon_events").insert({
    shop_id: shopId,
    user_id: null,          // ★ 第1段階は匿名でOK（DB側で NULL 許可済み）
    coupon_type: couponType,
    event_type: "visited",  // ★ CVイベント
    user_agent: userAgent,
    ip_hash: ip,            // 本当は hash 化したほうがベター
  });

  if (error) {
    console.error(error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  // とりあえず Google にリダイレクト（あとで店舗ごとのサンクスページに差し替え）
  return NextResponse.redirect("https://www.google.com");
}
