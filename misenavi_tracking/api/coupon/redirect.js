import { createClient } from "@supabase/supabase-js";
import crypto from "crypto";

// ===== Supabase =====
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_KEY   // Vercel には service_role を入れておくのがおすすめ
);

// ===== Storage bucket =====
const BUCKET = "tracking-logs";

// ===== 店舗ごとの CSV ファイル名 =====
function csvFileForShop(shop_id) {
  return `logs_${shop_id}.csv`;   // logs_shopA.csv / logs_shopB.csv ...
}

// ===== device 判定 =====
function detectDevice(ua = "") {
  const u = ua.toLowerCase();
  if (u.includes("iphone") || u.includes("android") || u.includes("mobile")) {
    return "mobile";
  }
  if (u.includes("ipad")) return "tablet";
  if (u.includes("windows") || u.includes("macintosh")) {
    return "desktop";
  }
  return "unknown";
}

// ===== session_id 生成 =====
function generateSessionId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return crypto.randomBytes(16).toString("hex");
}

// ===== CSV append =====
async function appendCsv(shop_id, record) {
  const fileName = csvFileForShop(shop_id);

  const line =
    [
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
    const header =
      "timestamp,user_id,coupon_type,event_type,ip_hash,user_agent\n";
    newContent = header + line;
  }

  await supabase.storage.from(BUCKET).upload(fileName, newContent, {
    upsert: true,
    contentType: "text/csv",
  });
}


// ===== メイン handler =====
export default async function handler(req, res) {
  const {
    shop,
    type,
    uid,
    dest,
    campaign,
    ref,
    path,
  } = req.query;

  const ua = req.headers["user-agent"] || "";
  const ip =
    req.headers["x-forwarded-for"] ||
    req.socket.remoteAddress ||
    "unknown";

  const ip_hash = crypto
    .createHash("sha256")
    .update(String(ip))
    .digest("hex");

  const nowIso = new Date().toISOString();
  const device_type = detectDevice(ua);
  const session_id = generateSessionId();

  const dbRecord = {
    shop_id: shop,
    user_id: uid,
    coupon_type: type,
    event_type: "opened",
    user_agent: ua,
    ip_hash,
    campaign_id: campaign || "default",
    referrer: ref || "",
    path: path || "",
    session_id,
    device_type,
  };

  const csvRecord = {
    timestamp: nowIso,
    shop_id: shop,
    user_id: uid,
    coupon_type: type,
    event_type: "opened",
    user_agent: ua,
    ip_hash,
  };

  // ===== DB Insert =====
  try {
    const { error: dbError } = await supabase
      .from("coupon_events")
      .insert([dbRecord]);

    if (dbError) {
      console.error("[supabase insert error]", dbError);
    }
  } catch (e) {
    console.error("[db insert exception]", e);
  }

  // ===== CSV Append =====
  try {
    await appendCsv(shop, csvRecord);
  } catch (e) {
    console.error("[appendCsv error]", e);
  }

  // ===== リダイレクト (必ず成功させる) =====
  let redirectUrl = "https://google.com";
  try {
    if (dest) {
      redirectUrl = decodeURIComponent(dest);
    }
  } catch (e) {
    console.error("[decode dest error]", e);
  }

  return res.redirect(302, redirectUrl);
}