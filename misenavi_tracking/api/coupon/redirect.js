import { createClient } from "@supabase/supabase-js";
import crypto from "crypto";

// ===== Supabase =====
// ※ Vercel には service_role を入れる（流出厳禁）
// 環境変数名は SUPABASE_SERVICE_ROLE_KEY に統一
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY
);

// ===== Storage bucket =====
const BUCKET = "tracking-logs";

// ===== 店舗ごとの CSV ファイル名（競合を減らすため日次分割） =====
function csvFileForShop(shop_id, yyyyMMdd) {
  return `logs_${shop_id}_${yyyyMMdd}.csv`; // logs_shopA_20251214.csv など
}

// ===== device 判定 =====
function detectDevice(ua = "") {
  const u = String(ua).toLowerCase();
  if (u.includes("iphone") || u.includes("android") || u.includes("mobile")) return "mobile";
  if (u.includes("ipad")) return "tablet";
  if (u.includes("windows") || u.includes("macintosh")) return "desktop";
  return "unknown";
}

// ===== session_id 生成 =====
function generateSessionId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return crypto.randomBytes(16).toString("hex");
}

// ===== YYYYMMDD 生成（UTC基準でOK。JSTにしたいならここだけ調整） =====
function yyyymmddUTC(d = new Date()) {
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${y}${m}${day}`;
}

// ===== dest ホワイトリスト（オープンリダイレクト対策） =====
// 必要に応じて追加
const ALLOWED_DEST_HOSTS = new Set([
  "lin.ee",
  "line.me",
  // "yourdomain.com",
]);

function safeDecodeDest(dest) {
  try {
    return decodeURIComponent(dest);
  } catch {
    return null;
  }
}

function isAllowedDest(urlStr) {
  try {
    const u = new URL(urlStr);
    return ALLOWED_DEST_HOSTS.has(u.hostname);
  } catch {
    return false;
  }
}

// ===== CSV append =====
async function appendCsv(shop_id, record) {
  const day = yyyymmddUTC(new Date(record.timestamp));
  const fileName = csvFileForShop(shop_id, day);

  // shop_id もCSVに入れる（後で分析しやすい）
  const line =
    [
      record.timestamp,
      record.shop_id,
      record.user_id,
      record.coupon_type,
      record.event_type,
      record.ip_hash,
      JSON.stringify(record.user_agent).replace(/,/g, " "), // カンマ潰し
    ].join(",") + "\n";

  // 既存ファイルがあれば追記、なければヘッダ付き新規
  const { data: exist } = await supabase.storage.from(BUCKET).download(fileName);

  let newContent;
  if (exist) {
    const text = await exist.text();
    newContent = text + line;
  } else {
    const header = "timestamp,shop_id,user_id,coupon_type,event_type,ip_hash,user_agent\n";
    newContent = header + line;
  }

  // upload（upsert）
  const { error } = await supabase.storage.from(BUCKET).upload(fileName, newContent, {
    upsert: true,
    contentType: "text/csv",
  });
  if (error) throw error;
}

// ===== メイン handler =====
export default async function handler(req, res) {
  // ===== 必須パラメータ =====
  const shop = req.query.shop;
  const type = req.query.type;
  const uid = req.query.uid;
  const dest = req.query.dest;

  // オプション
  const campaign = req.query.campaign;
  const ref = req.query.ref;
  const path = req.query.path;

  // ===== まずリダイレクト先を確定（失敗しても必ず飛ばす） =====
  let redirectUrl = "https://google.com";
  const decoded = dest ? safeDecodeDest(dest) : null;
  if (decoded && isAllowedDest(decoded)) {
    redirectUrl = decoded;
  }

  // ===== パラメータ欠損時はログだけ残してリダイレクト =====
  // （trackingは壊さない、ユーザー体験を落とさない）
  if (!shop || !type || !uid) {
    console.warn("[redirect] missing query", { shop, type, uid });
    return res.redirect(302, redirectUrl);
  }

  // ===== request 情報 =====
  const ua = req.headers["user-agent"] || "";
  const ip =
    req.headers["x-forwarded-for"] ||
    req.socket?.remoteAddress ||
    "unknown";

  const ip_hash = crypto
    .createHash("sha256")
    .update(String(ip))
    .digest("hex");

  const nowIso = new Date().toISOString();
  const device_type = detectDevice(ua);
  const session_id = generateSessionId();

  const dbRecord = {
    shop_id: String(shop),
    user_id: String(uid),
    coupon_type: String(type),
    event_type: "opened",
    user_agent: String(ua),
    ip_hash,
    campaign_id: campaign ? String(campaign) : "default",
    referrer: ref ? String(ref) : "",
    path: path ? String(path) : "",
    session_id,
    device_type,
    created_at: nowIso, // テーブル側で自動なら不要だが明示してもOK
  };

  const csvRecord = {
    timestamp: nowIso,
    shop_id: String(shop),
    user_id: String(uid),
    coupon_type: String(type),
    event_type: "opened",
    user_agent: String(ua),
    ip_hash,
  };

  // ===== DB Insert（失敗してもリダイレクトは必ず成功させる） =====
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

  // ===== CSV Append（失敗してもリダイレクトは必ず成功させる） =====
  try {
    await appendCsv(String(shop), csvRecord);
  } catch (e) {
    console.error("[appendCsv error]", e);
  }

  // ===== redirect =====
  return res.redirect(302, redirectUrl);
}
