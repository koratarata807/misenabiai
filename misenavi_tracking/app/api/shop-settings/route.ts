// app/api/shop-settings/route.ts
import { NextRequest, NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabaseServer";

// GET ?shop_id=shopA 用（必要なら）
export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const shopId = searchParams.get("shop_id");

  if (!shopId) {
    return NextResponse.json({ error: "shop_id is required" }, { status: 400 });
  }

  const { data, error } = await supabaseServer
    .from("shops")
    .select(
      `
      id,
      name,
      coupon_url,
      coupon7_image,
      coupon30_image,
      coupon_after_7days,
      coupon_after_30days
      `
    )
    .eq("id", shopId)
    .single();

  if (error || !data) {
    return NextResponse.json(
      { error: error?.message ?? "shop not found" },
      { status: 500 }
    );
  }

  return NextResponse.json({ shop: data });
}

// ★ フォームからの更新用
export async function PUT(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body || !body.shop_id) {
    return NextResponse.json(
      { error: "shop_id is required" },
      { status: 400 }
    );
  }

  const { shop_id, name, coupon_url, coupon7_image, coupon30_image, coupon_after_7days, coupon_after_30days } =
    body;

  const { data, error } = await supabaseServer
    .from("shops")
    .update({
      name,
      coupon_url,
      coupon7_image,
      coupon30_image,
      coupon_after_7days,
      coupon_after_30days,
    })
    .eq("id", shop_id)
    .select()
    .single();

  if (error) {
    console.error(error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  return NextResponse.json({ shop: data });
}
