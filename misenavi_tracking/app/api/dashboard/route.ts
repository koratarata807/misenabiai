import { NextRequest, NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabaseServer";

type DailyRow = {
  open_date: string;       // "2025-12-05"
  opened_users: number | null;
};

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const shopId = searchParams.get("shop_id");

  if (!shopId) {
    return NextResponse.json({ error: "shop_id is required" }, { status: 400 });
  }

  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000)
    .toISOString()
    .slice(0, 10);

  // 過去7日分（含む）を取得
  const { data, error } = await supabaseServer
    .from("coupon_open_daily")
    .select("open_date, opened_users")
    .eq("shop_id", shopId)
    .order("open_date", { ascending: false })
    .limit(7);

  if (error) {
    console.error(error);
    return NextResponse.json({ error: error.message }, { status: 500 });
  }

  const rows: DailyRow[] = data ?? [];

  const todayRow = rows.find((d) => d.open_date === today);
  const yesterdayRow = rows.find((d) => d.open_date === yesterday);

  const daily = [...rows]
    .sort((a, b) => a.open_date.localeCompare(b.open_date)) // 昇順に並べ替え
    .map((row) => ({
      date: row.open_date,
      opened_users: row.opened_users ?? 0,
    }));

  return NextResponse.json({
    shop_id: shopId,
    summary: {
      today_open_users: todayRow?.opened_users ?? 0,
      yesterday_open_users: yesterdayRow?.opened_users ?? 0,
    },
    daily,
  });
}
