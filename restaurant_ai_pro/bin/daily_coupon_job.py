#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List
import os
import sys
import requests
import yaml
from dotenv import dotenv_values
import urllib.parse
from supabase import create_client, Client

# =========================================================
# REV / ENV識別
# =========================================================

REV = os.getenv("APP_REV", "rev_not_set")
# datetimeはクラスなので datetime.utcnow() を使う（datetime.datetime ではない）
print(f"[REV] {REV} {datetime.utcnow().isoformat()}Z", flush=True)

# Supabase接続先の識別用（末尾だけ出す）
def _url_suffix(url: str, n: int = 18) -> str:
    if not url:
        return "None"
    return url[-n:]


# =========================================================
# 基本設定
# =========================================================

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
SHOPS_YAML = CONFIG_DIR / "shops.yaml"

LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"

TRACKING_BASE = (
    "https://misenavi-tracking-rbsey36xe-haya5050akibahu-6610s-projects.vercel.app"
    "/api/coupon/redirect"
)

# =========================================================
# Supabase
# =========================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("[ERROR] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing", file=sys.stderr, flush=True)
    sys.exit(1)

print(f"[ENV] SUPABASE_URL_suffix={_url_suffix(SUPABASE_URL)}", flush=True)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# どの列を “DBキー” として使うか（環境変数で固定可能）
# 例：Cloud Run env に USER_KEY_COL=line_user_id を入れる
USER_KEY_COL = os.getenv("USER_KEY_COL", "").strip() or None  # Noneなら自動判定
print(f"[ENV] USER_KEY_COL={USER_KEY_COL or 'AUTO'}", flush=True)


def is_dry_run() -> bool:
    return os.getenv("DRY_RUN", "0").lower() in ("1", "true", "yes")


def jst_now() -> datetime:
    return datetime.now(JST)


# =========================================================
# shops.yaml
# =========================================================

def load_shops() -> Dict[str, Dict]:
    if not SHOPS_YAML.exists():
        print("[ERROR] shops.yaml not found", file=sys.stderr, flush=True)
        return {}

    with SHOPS_YAML.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    shops: Dict[str, Dict] = {}
    for item in raw.get("shops", []):
        sid = item.get("id")
        if sid:
            shops[sid] = item
    return shops


# =========================================================
# LINE
# =========================================================

def load_line_token(shop_conf: Dict) -> Optional[str]:
    """
    優先順位：
      1) 環境変数（Cloud Run / 本番）
      2) env_file（ローカル検証用）
    """
    env_key = shop_conf.get("line_token_env")
    if env_key:
        token = os.getenv(env_key)
        if token:
            return token

    env_file = shop_conf.get("env_file")
    if not env_file:
        return None

    env_path = CONFIG_DIR / env_file
    if not env_path.exists():
        return None

    envs = dotenv_values(env_path)
    return envs.get("LINE_CHANNEL_ACCESS_TOKEN")


def send_coupon_message(token: str, user_id: str, text: str, image_url: str) -> bool:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "to": user_id,
        "messages": [
            {"type": "text", "text": text},
            {"type": "image", "originalContentUrl": image_url, "previewImageUrl": image_url},
        ],
    }

    r = requests.post(LINE_PUSH_ENDPOINT, json=payload, headers=headers, timeout=10)
    if r.status_code != 200:
        print(f"[ERROR] LINE push failed uid={user_id} status={r.status_code} body={r.text}", flush=True)
        return False
    return True


def send_coupon_flex_message(token: str, user_id: str, text: str, image_url: str, coupon_url: str) -> bool:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    payload = {
        "to": user_id,
        "messages": [
            {
                "type": "flex",
                "altText": text,
                "contents": {
                    "type": "bubble",
                    "hero": {
                        "type": "image",
                        "url": image_url,
                        "size": "full",
                        "aspectRatio": "20:13",
                        "aspectMode": "cover",
                        "action": {"type": "uri", "label": "クーポンを開く", "uri": coupon_url},
                    },
                    "body": {
                        "type": "box",
                        "layout": "vertical",
                        "contents": [{"type": "text", "text": text, "wrap": True}],
                    },
                },
            }
        ],
    }

    r = requests.post(LINE_PUSH_ENDPOINT, json=payload, headers=headers, timeout=10)
    if r.status_code != 200:
        print(f"[ERROR] LINE flex push failed uid={user_id} status={r.status_code} body={r.text}", flush=True)
        return False
    return True


# =========================================================
# Tracking
# =========================================================

def build_tracking_url(shop_id: str, coupon_type: str, user_id: str, dest: str) -> str:
    return (
        f"{TRACKING_BASE}"
        f"?shop={shop_id}"
        f"&type={coupon_type}"
        f"&uid={user_id}"
        f"&dest={urllib.parse.quote(dest, safe='')}"
    )


# =========================================================
# DB：キー自動判定 & 冪等性ガード
# =========================================================

def detect_user_key_col(shop_id: str) -> str:
    """
    USER_KEY_COL が未設定の場合、usersから1件取って
    user_id / line_user_id のどちらが実データとして使われていそうかを推定する。
    """
    if USER_KEY_COL:
        return USER_KEY_COL

    # 1件だけ見て判定（安全に両方select）
    res = (
        supabase.table("users")
        .select("user_id,line_user_id,shop_id")
        .eq("shop_id", shop_id)
        .limit(1)
        .execute()
    )
    row = (res.data or [None])[0]
    if not row:
        # データ無いなら一旦user_idで（ログで気づける）
        print(f"[KEY][AUTO] users empty for shop_id={shop_id} -> fallback user_id", flush=True)
        return "user_id"

    # 値が入ってそうな方を優先
    if row.get("user_id"):
        print(f"[KEY][AUTO] choose user_id (sample has user_id)", flush=True)
        return "user_id"
    if row.get("line_user_id"):
        print(f"[KEY][AUTO] choose line_user_id (sample has line_user_id)", flush=True)
        return "line_user_id"

    # どっちも空ならfallback
    print(f"[KEY][AUTO] sample has neither -> fallback user_id", flush=True)
    return "user_id"


def already_sent_today(shop_id: str, user_id: str, coupon_type: str, now_utc: datetime) -> bool:
    """
    ⑤ 冪等性ガード：同日・同種の送信が coupon_send_logs にあれば送らない
    """
    day_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    day_end = (now_utc.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()

    res = (
        supabase.table("coupon_send_logs")
        .select("id")
        .eq("shop_id", shop_id)
        .eq("user_id", user_id)
        .eq("coupon_type", coupon_type)
        .gte("sent_at", day_start)
        .lt("sent_at", day_end)
        .limit(1)
        .execute()
    )
    return bool(res.data)


# =========================================================
# DB 共通（経過日数＋未送信）
# =========================================================

def fetch_targets_from_db(
    shop_id: str,
    now_utc: datetime,
    days: int,
    sent_col: str,
    user_key_col: str,
    limit: int = 5000,
) -> List[Dict]:
    """
    条件：
      - shop_id 一致
      - {sent_col} is null（未送信）
      - registered_at <= now - days（経過）
    """
    cutoff = (now_utc - timedelta(days=days)).isoformat()

    res = (
        supabase.table("users")
        .select("user_id,line_user_id,display_name,registered_at")
        .eq("shop_id", shop_id)
        .is_(sent_col, None)
        .lte("registered_at", cutoff)
        .limit(limit)
        .execute()
    )

    rows = res.data or []

    # ④：送信に使うUID（LINEのUxxx）を確定させる
    # user_key_col が user_id でも line_user_id でも、送信用に uid を作っておく
    for r in rows:
        r["_uid"] = r.get(user_key_col) or r.get("user_id") or r.get("line_user_id")

    # uidがない行は除外（ログで気づける）
    filtered = [r for r in rows if r.get("_uid")]
    if len(filtered) != len(rows):
        print(f"[WARN] targets missing uid filtered out: {len(rows)-len(filtered)}", flush=True)

    return filtered


def mark_sent(shop_id: str, uid: str, sent_col: str, sent_at: str, user_key_col: str):
    """
    ③ 原因確定版（BEFORE/UPDATE/AFTER）
    """
    url_suf = _url_suffix(SUPABASE_URL)

    # BEFORE
    before = (
        supabase.table("users")
        .select(f"shop_id,{user_key_col},registered_at,coupon7_sent_at,coupon30_sent_at,welcome_coupon_sent_at")
        .eq("shop_id", shop_id)
        .eq(user_key_col, uid)
        .limit(1)
        .execute()
    )
    exists = bool(before.data)
    print(
        f"[MARK_SENT][BEFORE] url_suf={url_suf} exists={exists} shop_id={shop_id} {user_key_col}={uid} col={sent_col}",
        flush=True,
    )
    if exists:
        print(f"[MARK_SENT][BEFORE_ROW] {before.data[0]}", flush=True)

    # UPDATE
    res = (
        supabase.table("users")
        .update({sent_col: sent_at})
        .eq("shop_id", shop_id)
        .eq(user_key_col, uid)
        .select(f"shop_id,{user_key_col},coupon7_sent_at,coupon30_sent_at,welcome_coupon_sent_at")
        .execute()
    )
    updated_rows = res.data or []
    updated_n = len(updated_rows)
    print(
        f"[MARK_SENT][UPDATE] url_suf={url_suf} updated={updated_n} shop_id={shop_id} {user_key_col}={uid} col={sent_col} -> {sent_at}",
        flush=True,
    )
    if updated_n > 0:
        print(f"[MARK_SENT][UPDATE_ROW] {updated_rows[0]}", flush=True)

    # AFTER
    after = (
        supabase.table("users")
        .select(f"shop_id,{user_key_col},registered_at,coupon7_sent_at,coupon30_sent_at,welcome_coupon_sent_at")
        .eq("shop_id", shop_id)
        .eq(user_key_col, uid)
        .limit(1)
        .execute()
    )
    after_exists = bool(after.data)
    print(
        f"[MARK_SENT][AFTER] url_suf={url_suf} exists={after_exists} shop_id={shop_id} {user_key_col}={uid}",
        flush=True,
    )
    if after_exists:
        print(f"[MARK_SENT][AFTER_ROW] {after.data[0]}", flush=True)

    # DIAG
    if not exists:
        print("[MARK_SENT][DIAG] BEFOREで行が見えてない → WHERE不一致(列名/値/shop_id) or 別DB", flush=True)
    elif exists and updated_n == 0:
        print("[MARK_SENT][DIAG] 行は存在するが update=0 → RLS/権限/型/WHERE条件ミスの可能性", flush=True)
    elif updated_n > 0 and after_exists:
        print("[MARK_SENT][DIAG] update成功 → DB永続化OK（次はダッシュボード側/接続先を疑う）", flush=True)


def insert_coupon_send_logs(rows: List[Dict]):
    if not rows:
        return
    try:
        supabase.table("coupon_send_logs").insert(rows).execute()
        print(f"[INFO] coupon_send_logs inserted={len(rows)}", flush=True)
    except Exception as e:
        print(f"[ERROR] coupon_send_logs insert failed: {e}", flush=True)


# =========================================================
# 店舗処理（7days + 30days）
# =========================================================

def run_for_shop(shop_id: str, shop_conf: Dict, now_jst: datetime):
    print(f"\n[INFO] === shop: {shop_id} ({shop_conf.get('name')}) ===", flush=True)

    token = load_line_token(shop_conf)
    if not token:
        print("[ERROR] LINE token missing", flush=True)
        return

    # ④：この店舗で使うDBキー列を決める（AUTO or env固定）
    user_key_col = detect_user_key_col(shop_id)
    print(f"[KEY] shop_id={shop_id} user_key_col={user_key_col}", flush=True)

    coupon_url = shop_conf.get("coupon_url")  # lin.eeなど（あればtrackingへ）

    img7 = shop_conf.get("coupon7_image")
    msg7_tpl = shop_conf.get("coupon_after_7days")

    img30 = shop_conf.get("coupon30_image") or img7
    msg30_tpl = shop_conf.get("coupon_after_30days") or msg7_tpl

    if not img7:
        print("[ERROR] coupon7_image missing (shops.yaml)", flush=True)
        return

    now_utc = now_jst.astimezone(timezone.utc)

    targets7 = fetch_targets_from_db(shop_id, now_utc, 7, "coupon7_sent_at", user_key_col)
    targets30 = fetch_targets_from_db(shop_id, now_utc, 30, "coupon30_sent_at", user_key_col)

    print(f"[INFO] 7days targets(DB): {len(targets7)}", flush=True)
    print(f"[INFO] 30days targets(DB): {len(targets30)}", flush=True)

    if is_dry_run():
        print("[INFO] DRY_RUN=1 → send skipped", flush=True)
        return

    logs: List[Dict] = []

    def _send(uid: str, text: str, image_url: str, ctype: str) -> bool:
        if coupon_url:
            tracking = build_tracking_url(shop_id, ctype, uid, coupon_url)
            return send_coupon_flex_message(token, uid, text, image_url, tracking)
        return send_coupon_message(token, uid, text, image_url)

    for days, targets, sent_col, tpl, img in [
        (7, targets7, "coupon7_sent_at", msg7_tpl, img7),
        (30, targets30, "coupon30_sent_at", msg30_tpl, img30),
    ]:
        for t in targets:
            uid = t.get("_uid")
            if not uid:
                continue

            name = (t.get("display_name") or "").strip()
            text = tpl.format(name=name, display_name=name) if tpl else f"{name}さん、登録{days}日記念のクーポンです。"
            ts = now_utc.isoformat()
            ctype = f"{days}days"

            # ⑤：冪等性ガード（同日同種は送らない）
            if already_sent_today(shop_id, uid, ctype, now_utc):
                print(f"[SKIP] already sent today shop_id={shop_id} uid={uid} type={ctype}", flush=True)
                continue

            ok = _send(uid, text, img, ctype)
            if ok:
                # ③：原因確定ログ + 永続化
                mark_sent(shop_id, uid, sent_col, ts, user_key_col)

                # 送信ログ（分母）
                logs.append({"shop_id": shop_id, "user_id": uid, "coupon_type": ctype, "sent_at": ts})

    insert_coupon_send_logs(logs)
    print(f"[INFO] {shop_id}: logs={len(logs)}", flush=True)


# =========================================================
# main
# =========================================================

def main():
    _runtime_sig()
    print("=== daily_coupon_job START ===", flush=True)
    now = jst_now()
    shops = load_shops()
    if not shops:
        print("[ERROR] shops empty", flush=True)
        return

    for sid, conf in shops.items():
        try:
            run_for_shop(sid, conf, now)
        except Exception as e:
            print(f"[ERROR] shop={sid} exception: {e}", flush=True)


if __name__ == "__main__":
    main()

# ===== DEBUG SIGNATURE (TEMP) =====
import os as _os, hashlib as _hashlib

def _runtime_sig():
    try:
        p = _os.path.abspath(__file__)
        b = open(p, "rb").read()
        print(f"[RUNTIME_DAILY] file={p}", flush=True)
        print(f"[RUNTIME_DAILY] sha256={_hashlib.sha256(b).hexdigest()}", flush=True)
        print(f"[RUNTIME_DAILY] cwd={_os.getcwd()}", flush=True)
    except Exception as e:
        print(f"[RUNTIME_DAILY][ERROR] {e}", flush=True)
