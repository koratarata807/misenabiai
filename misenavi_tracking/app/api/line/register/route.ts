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

    const sb = supabaseServer; // ★ () なし

    // id は存在しないので取らない
    const { data: existing, error: selErr } = await sb
      .from("users")
      .select("user_id, shop_id, welcome_coupon_sent_at")
      .eq("user_id", user_id)
      .maybeSingle();

    if (selErr) {
      console.error("[line/register] select error:", selErr);
      return NextResponse.json(
        { ok: false, error: `db select error: ${selErr.message}` },
        { status: 500 }
      );
    }

    const coupon = buildCoupon(shop_id);

    // 存在しない → insert（初回付与）
    if (!existing) {
      const { error: insErr } = await sb.from("users").insert({
        user_id,
        display_name,
        shop_id,
        registered_at: new Date().toISOString(),
        welcome_coupon_sent_at: new Date().toISOString(),
      });

      if (insErr) {
        console.error("[line/register] insert error:", insErr);
        return NextResponse.json(
          { ok: false, error: `db insert error: ${insErr.message}` },
          { status: 500 }
        );
      }

      return NextResponse.json({
        ok: true,
        status: "granted",
        coupon,
      });
    }

    // 既受領
    if (existing.welcome_coupon_sent_at) {
      // メタだけ更新（任意）
      const { error: updMetaErr } = await sb
        .from("users")
        .update({ display_name, shop_id })
        .eq("user_id", user_id);

      if (updMetaErr) {
        console.warn("[line/register] meta update warn:", updMetaErr);
      }

      return NextResponse.json({
        ok: true,
        status: "already_granted",
        coupon,
      });
    }

    // 未付与 → 付与して granted
    const { error: updErr } = await sb
      .from("users")
      .update({
        display_name,
        shop_id,
        welcome_coupon_sent_at: new Date().toISOString(),
      })
      .eq("user_id", user_id);

    if (updErr) {
      console.error("[line/register] update error:", updErr);
      return NextResponse.json(
        { ok: false, error: `db update error: ${updErr.message}` },
        { status: 500 }
      );
    }

    return NextResponse.json({
      ok: true,
      status: "granted",
      coupon,
    });
  } catch (e: any) {
    console.error("[line/register] exception:", e);
    return NextResponse.json(
      { ok: false, error: e?.message ?? "unknown error" },
      { status: 500 }
    );
  }
}
