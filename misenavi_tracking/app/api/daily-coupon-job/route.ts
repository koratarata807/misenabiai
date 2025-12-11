// app/api/daily-coupon-job/route.ts
import { NextRequest, NextResponse } from "next/server";
import { supabaseServer } from "@/lib/supabaseServer";

// 将来ここに LINE のチャネルアクセストークンなどを使う
// const LINE_CHANNEL_ACCESS_TOKEN = process.env.LINE_CHANNEL_ACCESS_TOKEN;

export async function GET(_req: NextRequest) {
  // JST 現在時刻（ログ用）
  const now = new Date();
  const jst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  const ranAt = jst.toISOString();

  // TODO:
  // ここに「全店舗分の 7日 / 30日クーポンを送るロジック」を移植していく。
  // いまは動作確認のために、軽いログだけ残す。

  try {
    // 例：cron_job_logs みたいなテーブルを作っておけば、実行履歴も見れる
    // （まだテーブル作っていなければ、この insert はコメントアウトでOK）
    /*
    await supabaseServer.from("cron_job_logs").insert({
      job_name: "daily_coupon_job",
      ran_at: ranAt,
      status: "ok",
    });
    */

    console.log("[daily-coupon-job] ran at", ranAt);

    return NextResponse.json({
      ok: true,
      job: "daily_coupon_job",
      ran_at: ranAt,
    });
  } catch (e: any) {
    console.error("[daily-coupon-job] error", e);
    return NextResponse.json(
      { ok: false, error: e?.message ?? "unknown error" },
      { status: 500 }
    );
  }
}
