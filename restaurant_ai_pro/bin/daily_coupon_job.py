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

# ===== 基本設定 =====

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
SHOPS_YAML = CONFIG_DIR / "shops.yaml"

LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"

TRACKING_BASE = (
    "https://misenavi-tracking-rbsey36xe-haya5050akibahu-6610s-projects.vercel.app"
    "/api/coupon/redirect"
)

# ===== Supabase（前のやり方 그대로）=====

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
    print("[ERROR] SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing", file=sys.stderr)
    sys.exit(1)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def is_dry_run() -> bool:
    return os.getenv("DRY_RUN", "0").lower() in ("1", "true", "yes")


def jst_now() -> datetime:
    return datetime.now(JST)


# ===== shops.yaml =====

def load_shops() -> Dict[str, Dict]:
    if not SHOPS_YAML.exists():
        print("[ERROR] shops.yaml not found", file=sys.stderr)
        return {}

    with SHOPS_YAML.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    shops: Dict[str, Dict] = {}
    for item in raw.get("shops", []):
        sid = item.get("id")
        if sid:
            shops[sid] = item
    return shops


# ===== LINE（前のやり方 그대로）=====

def load_line_token(shop_conf: Dict) -> Optional[str]:
    """
    優先順位：
      1) 環境変数（Cloud Run / 本番）
      2) env_file（ローカル検証用）
    """
    # (1) env
    env_key = shop_conf.get("line_token_env")
    if env_key:
        token = os.getenv(env_key)
        if token:
            return token

    # (2) env_file fallback
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

    r = requests.post(LINE_PUSH_ENDPOINT, json=payload, headers=headers)
    if r.status_code != 200:
        print(f"[ERROR] LINE push failed uid={user_id} status={r.status_code} body={r.text}")
        return False
    return True


def send_coupon_flex_message(
    token: str,
    user_id: str,
    text: str,
    image_url: str,
    coupon_url: str,
) -> bool:
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
                        "action": {
                            "type": "uri",
                            "label": "クーポンを開く",
                            "uri": coupon_url,
                        },
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

    r = requests.post(LINE_PUSH_ENDPOINT, json=payload, headers=headers)
    if r.status_code != 200:
        print(f"[ERROR] LINE flex push failed uid={user_id} status={r.status_code} body={r.text}")
        return False
    return True


# ===== Tracking =====

def build_tracking_url(shop_id: str, coupon_type: str, user_id: str, dest: str) -> str:
    return (
        f"{TRACKING_BASE}"
        f"?shop={shop_id}"
        f"&type={coupon_type}"
        f"&uid={user_id}"
        f"&dest={urllib.parse.quote(dest, safe='')}"
    )


# ===== DB 共通（経過日数＋未送信）=====

def fetch_targets_from_db(
    shop_id: str,
    now_utc: datetime,
    days: int,
    sent_col: str,
    limit: int = 5000,
) -> List[Dict]:
    cutoff = (now_utc - timedelta(days=days)).isoformat()

    res = (
        supabase.table("users")
        .select("user_id,display_name")
        .eq("shop_id", shop_id)
        .is_(sent_col, "null")
        .lte("registered_at", cutoff)
        .limit(limit)
        .execute()
    )
    return res.data or []


def mark_sent(shop_id: str, user_id: str, sent_col: str, sent_at: str):
    supabase.table("users").update(
        {sent_col: sent_at}
    ).eq("shop_id", shop_id).eq("user_id", user_id).execute()


def insert_coupon_send_logs(rows: List[Dict]):
    if rows:
        supabase.table("coupon_send_logs").insert(rows).execute()


# ===== 店舗処理（7days + 30days）=====

def run_for_shop(shop_id: str, shop_conf: Dict, now_jst: datetime):
    print(f"\n[INFO] === shop: {shop_id} ({shop_conf.get('name')}) ===")

    token = load_line_token(shop_conf)
    if not token:
        print("[ERROR] LINE token missing")
        return

    coupon_url = shop_conf.get("coupon_url")

    img7 = shop_conf.get("coupon7_image")
    msg7_tpl = shop_conf.get("coupon_after_7days")

    img30 = shop_conf.get("coupon30_image") or img7
    msg30_tpl = shop_conf.get("coupon_after_30days") or msg7_tpl

    now_utc = now_jst.astimezone(timezone.utc)

    targets7 = fetch_targets_from_db(shop_id, now_utc, 7, "coupon7_sent_at")
    targets30 = fetch_targets_from_db(shop_id, now_utc, 30, "coupon30_sent_at")

    print(f"[INFO] 7days targets(DB): {len(targets7)}")
    print(f"[INFO] 30days targets(DB): {len(targets30)}")

    if is_dry_run():
        print("[INFO] DRY_RUN=1 → send skipped")
        return

    logs: List[Dict] = []

    def _send(uid: str, text: str, image_url: str, ctype: str) -> bool:
        if coupon_url:
            return send_coupon_flex_message(
                token, uid, text, image_url,
                build_tracking_url(shop_id, ctype, uid, coupon_url)
            )
        return send_coupon_message(token, uid, text, image_url)

    for days, targets, sent_col, tpl, img in [
        (7, targets7, "coupon7_sent_at", msg7_tpl, img7),
        (30, targets30, "coupon30_sent_at", msg30_tpl, img30),
    ]:
        for t in targets:
            uid = t.get("user_id")
            if not uid:
                continue
            name = (t.get("display_name") or "").strip()

            text = tpl.format(name=name, display_name=name) if tpl else f"{name}さん、登録{days}日記念のクーポンです。"
            ts = now_utc.isoformat()

            if _send(uid, text, img, f"{days}days"):
                mark_sent(shop_id, uid, sent_col, ts)
                logs.append(
                    {"shop_id": shop_id, "user_id": uid, "coupon_type": f"{days}days", "sent_at": ts}
                )

    insert_coupon_send_logs(logs)
    print(f"[INFO] {shop_id}: logs={len(logs)}")


# ===== main =====

def main():
    print("=== daily_coupon_job START ===")
    now = jst_now()
    shops = load_shops()
    if not shops:
        print("[ERROR] shops empty")
        return

    for sid, conf in shops.items():
        run_for_shop(sid, conf, now)


if __name__ == "__main__":
    main()
