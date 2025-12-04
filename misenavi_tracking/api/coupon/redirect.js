import { createClient } from "@supabase/supabase-js";
import crypto from "crypto";

// ===== Supabase =====
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_KEY   // ここは今の環境変数名に合わせておく
);

// ===== Storage bucket =====
const BUCKET = "tracking-logs";

// ===== 店舗ごとの CSV ファイル名 =====
function csvFileForShop(shop_id) {
  return `logs_${shop_id}.csv`;   // logs_shopA.csv / logs_shopB.csv ...
}

// ===== CSV append =====
async function appendCsv(shop_id, record) {
  const fileName = csvFileForShop(shop_id);

  const line = [
    record.timestamp,
    record.user_id,
    record.coupon_type,
    record.event_type,
    record.ip_hash,
    JSON.stringify(record.user_agent).replace(/,/g, " "), // カンマ潰し
  ].join(",") + "\n";

  const { data: exist } = await supabase.storage
    .from(BUCKET)
    .download(fileName);

  let newContent;
  if (exist) {
    const text = await exist.text();
    newContent = text + line;
  } else {
    const header = "timestamp,user_id,coupon_type,event_type,ip_hash,user_agent\n";
    newContent = header + line;
  }

  await supabase.storage
    .from(BUCKET)
    .upload(fileName, newContent, {
      upsert: true,
      contentType: "text/csv",
    });
}

// ===== メイン handler =====
export default async function handler(req, res) {
  try {
    const { shop, type, uid, dest } = req.query;

    const ua =
      req.headers["user-agent"] || "";
    const ip =
      req.headers["x-forwarded-for"] ||
      req.socket.remoteAddress ||
      "unknown";

    const ip_hash = crypto
      .createHash("sha256")
      .update(String(ip))
      .digest("hex");

    const nowIso = new Date().toISOString();

    // CSV 用のレコード
    const csvRecord = {
      timestamp: nowIso,
      shop_id: shop,
      user_id: uid,
      coupon_type: type,
      event_type: "opened",
      user_agent: ua,
      ip_hash,
    };

    // DB 用のレコード（timestamp はテーブルに無いので入れない）
    const dbRecord = {
      shop_id: shop,
      user_id: uid,
      coupon_type: type,
      event_type: "opened",
      user_agent: ua,
      ip_hash,
    };

    // --- DB Insert（ここを coupon_events に統一）---
    const { error: dbError } = await supabase
      .from("coupon_events")
      .insert([dbRecord]);

    if (dbError) {
      console.error("[supabase insert error]", dbError);
      // ここで return しない。CSV だけでも残したい場合は続行
    }

    // --- 店舗ごとの CSV に append ---
    await appendCsv(shop, csvRecord);

    // --- 元の URL へリダイレクト ---
    const decoded = decodeURIComponent(dest);
    return res.redirect(302, decoded);
  } catch (err) {
    console.error(err);
    return res.status(500).json({ error: "server error" });
  }
}
