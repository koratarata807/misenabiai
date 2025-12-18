import { NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabaseServer";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const { user_id, display_name, shop_id } = body;

    if (!user_id || !shop_id) {
      return NextResponse.json(
        { ok: false, error: "missing user_id or shop_id" },
        { status: 400 }
      );
    }

    const { error } = await supabaseServer
      .from("users")
      .upsert(
        {
          user_id,
          display_name,
          shop_id,
          registered_at: new Date().toISOString(),
        },
        {
          onConflict: "user_id",
        }
      );

    if (error) {
      console.error("[line/register] supabase error:", error);
      return NextResponse.json(
        { ok: false, error: "db error" },
        { status: 500 }
      );
    }

    return NextResponse.json({ ok: true });
  } catch (e: any) {
    console.error("[line/register] exception:", e);
    return NextResponse.json(
      { ok: false, error: e?.message ?? "unknown error" },
      { status: 500 }
    );
  }
}
