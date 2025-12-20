import { NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabaseServer";

type CouponPayload = {
  title: string;
  expires_text: string;
  note?: string;
  image_url?: string;
  coupon_code?: string;
};

function buildCoupon(_shop_id: string): CouponPayload {
  // P0ミニマム：後で店別にDB化してOK
  return {
    title: "ドリンク1杯無料",
    expires_text: "本日限り",
    note: "会計前にこの画面をスタッフへ提示してください。",
  };
}

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const user_id = String(body.user_id ?? "");
    const display_name = String(body.display_name ?? "");
    const shop_id = String(body.shop_id ?? "");

    if (!user_id || !shop_id) {
      return NextResponse.json(
        { ok: false, error: "missing user_id or shop_id" },
        { status: 400 }
      );
    }

    const sb = supabaseServer;

    // ① user_id で既存ユーザーを取得（あなたの制約が user_id unique なのでこれが正）
    const { data: existing, error: selErr } = await sb
      .from("users")
      .select("id, user_id, shop_id, welcome_coupon_sent_at")
      .eq("user_id", user_id)
      .maybeSingle();

    if (selErr) {
      console.error("[line/register] select error:", selErr);
      return NextResponse.json({ ok: false, error: "db select error" }, { status: 500 });
    }

    const coupon = buildCoupon(shop_id);

    // ② 存在しない → insert（初回付与）
    if (!existing) {
      const { data: ins, error: insErr } = await sb
        .from("users")
        .insert({
          user_id,
          display_name,
          shop_id,
          registered_at: new Date().toISOString(),
          welcome_coupon_sent_at: new Date().toISOString(), // ★ 初回付与
        })
        .select("id, welcome_coupon_sent_at")
        .single();

      if (insErr) {
        console.error("[line/register] insert error:", insErr);
        return NextResponse.json({ ok: false, error: "db insert error" }, { status: 500 });
      }

      return NextResponse.json({
        ok: true,
        status: "granted",
        coupon,
        user: { id: ins.id },
      });
    }

    // ③ 既に welcome_coupon_sent_at がある → 既受領
    if (existing.welcome_coupon_sent_at) {
      // display_name / shop_id は最新に寄せたいなら更新だけしてもOK（任意）
      const { error: updMetaErr } = await sb
        .from("users")
        .update({
          display_name,
          shop_id,
        })
        .eq("id", existing.id);

      if (updMetaErr) {
        // メタ更新失敗は致命にしない（P0安定優先）
        console.warn("[line/register] meta update warn:", updMetaErr);
      }

      return NextResponse.json({
        ok: true,
        status: "already_granted",
        coupon,
        user: { id: existing.id },
      });
    }

    // ④ 既存だが未付与 → 今付与して granted
    const { error: updErr } = await sb
      .from("users")
      .update({
        display_name,
        shop_id,
        welcome_coupon_sent_at: new Date().toISOString(),
      })
      .eq("id", existing.id);

    if (updErr) {
      console.error("[line/register] update error:", updErr);
      return NextResponse.json({ ok: false, error: "db update error" }, { status: 500 });
    }

    return NextResponse.json({
      ok: true,
      status: "granted",
      coupon,
      user: { id: existing.id },
    });
  } catch (e: any) {
    console.error("[line/register] exception:", e);
    return NextResponse.json(
      { ok: false, error: e?.message ?? "unknown error" },
      { status: 500 }
    );
  }
}
