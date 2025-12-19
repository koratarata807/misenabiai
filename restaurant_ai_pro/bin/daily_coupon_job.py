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
import urllib.parse  # tracking用
from supabase import create_client, Client

# ===== 基本設定 =====

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
SHOPS_YAML = CONFIG_DIR / "shops.yaml"

LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"

# ★ Vercel の tracking API のベースURL（今回の本番）
TRACKING_BASE = "https://misenavi-tracking-rbsey36xe-haya5050akibahu-6610s-projects.vercel.app/api/coupon/redirect"

# ===== Supabase クライアント（DB判定の正）=====
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")  # ★統一（正）

supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
else:
    print("[ERROR] SUPABASE_URL または SUPABASE_SERVICE_ROLE_KEY が未設定です", file=sys.stderr)
    sys.exit(1)

def is_dry_run() -> bool:
    return os.getenv("DRY_RUN", "0") in ("1", "true", "TRUE", "yes", "YES")


# ===== ユーティリティ =====

def jst_now() -> datetime:
    """JST 現在時刻を返す"""
    return datetime.now(JST)


# ===== shops.yaml 読み込み =====

def load_shops() -> Dict[str, Dict]:
    """config/shops.yaml から店舗情報を読み込む"""
    if not SHOPS_YAML.exists():
        print("[ERROR] shops.yaml が見つかりません", file=sys.stderr)
        return {}

    with SHOPS_YAML.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    shops: Dict[str, Dict] = {}
    if isinstance(raw, dict) and isinstance(raw.get("shops"), list):
        for item in raw["shops"]:
            sid = item.get("id")
            if sid:
                shops[sid] = item

    return shops


# ===== LINE 送信 =====

def load_line_token(shop_conf: Dict) -> Optional[str]:
    """
    優先順位：
      1) shops.yaml の line_token_env に指定された環境変数
      2) 従来の env_file (.env) から LINE_CHANNEL_ACCESS_TOKEN を読む
    """
    # ===== (1) 環境変数方式 =====
    env_key = shop_conf.get("line_token_env")
    if env_key:
        token = os.getenv(env_key)
        if token:
            return token
        print(f"[WARN] 環境変数 {env_key} が未設定（fallbackで env_file を試します）", file=sys.stderr)

    # ===== (2) 従来の .env ファイル方式（後方互換）=====
    env_file = shop_conf.get("env_file")
    if not env_file:
        print("[ERROR] line_token_env も env_file も未設定", file=sys.stderr)
        return None

    env_path = CONFIG_DIR / env_file
    if not env_path.exists():
        print(f"[ERROR] env_file 不在: {env_path}", file=sys.stderr)
        return None

    env_dict = dotenv_values(env_path)
    token = env_dict.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        print(f"[ERROR] LINE_CHANNEL_ACCESS_TOKEN がありません: {env_path}", file=sys.stderr)
        return None

    return token


def send_coupon_message(token: str, user_id: str, text: str, image_url: str) -> bool:
    """
    シンプルなテキスト＋画像メッセージ（coupon_url が無いときのフォールバック用）
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer {}".format(token),
    }

    payload = {
        "to": user_id,
        "messages": [
            {"type": "text", "text": text},
            {
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            },
        ],
    }

    resp = requests.post(LINE_PUSH_ENDPOINT, json=payload, headers=headers)
    if resp.status_code != 200:
        print(
            "[ERROR] LINE push 失敗 user={} status={} body={}".format(
                user_id, resp.status_code, resp.text
            )
        )
        return False

    return True


def send_coupon_flex_message(
    token: str,
    user_id: str,
    text: str,
    image_url: str,
    coupon_url: str,
) -> bool:
    """画像タップでクーポンURLに飛ぶ Flex メッセージを送信"""
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer {}".format(token),
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
                        "contents": [
                            {
                                "type": "text",
                                "text": text,
                                "wrap": True,
                            }
                        ],
                    },
                },
            }
        ],
    }

    resp = requests.post(LINE_PUSH_ENDPOINT, json=payload, headers=headers)
    if resp.status_code != 200:
        print(
            "[ERROR] LINE flex push 失敗 user={} status={} body={}".format(
                user_id, resp.status_code, resp.text
            )
        )
        return False

    return True


# ===== Tracking 用 URL 生成 =====

def build_tracking_url(shop_id: str, coupon_type: str, user_id: str, dest_url: str) -> str:
    """
    実際のクーポンURL(dest_url: lin.ee など)を、
    Vercel の tracking API を通すURLに変換する。
    """
    encoded_dest = urllib.parse.quote(dest_url, safe="")
    return (
        f"{TRACKING_BASE}"
        f"?shop={shop_id}"
        f"&type={coupon_type}"
        f"&uid={user_id}"
        f"&dest={encoded_dest}"
    )


# ===== DBアクセス（判定/更新/ログ）=====

def fetch_7day_targets_from_db(shop_id: str, limit: int = 5000) -> List[Dict]:
    """
    送付対象：public.users の coupon7_sent_at is null
    返却：[{user_id, display_name}, ...]
    """
    res = (
        supabase.table("users")
        .select("user_id,display_name")
        .eq("shop_id", shop_id)
        .is_("coupon7_sent_at", "null")
        .limit(limit)
        .execute()
    )
    return res.data or []


def mark_7day_sent_in_db(shop_id: str, user_id: str, sent_at_utc_iso: str) -> None:
    """送信成功後：coupon7_sent_at を DB に反映"""
    supabase.table("users").update(
        {"coupon7_sent_at": sent_at_utc_iso}
    ).eq("shop_id", shop_id).eq("user_id", user_id).execute()


def insert_coupon_send_logs(logs: List[Dict]) -> None:
    """coupon_send_logs にまとめてINSERT（監査ログ：現状維持）"""
    if not logs:
        return
    try:
        supabase.table("coupon_send_logs").insert(logs).execute()
        print(f"[INFO] coupon_send_logs に {len(logs)} 行を保存しました")
    except Exception as e:
        print(f"[ERROR] coupon_send_logs へのINSERTに失敗: {e}")


# ===== 店舗処理（7daysのみDB判定）=====

def run_for_shop(shop_id: str, shop_conf: Dict, now: datetime) -> None:
    print("\n[INFO] === shop: {} ({}) ===".format(shop_id, shop_conf.get("name")))
    sent7 = 0
    send_logs: List[Dict] = []

    url7 = shop_conf.get("coupon7_image")
    coupon_url = shop_conf.get("coupon_url")  # 素の lin.ee など

    if not url7:
        print("[ERROR] coupon7_image URL 未設定 (shop_id={})".format(shop_id))
        return

    token = load_line_token(shop_conf)
    if not token:
        return

    msg7_template = shop_conf.get("coupon_after_7days")

    # ===== DB から送付対象を取得 =====
    targets = fetch_7day_targets_from_db(shop_id)
    target_ids = [t.get("user_id") for t in targets if t.get("user_id")]

    print(f"[INFO] 7days targets(DB): {len(target_ids)}")
    if target_ids:
        print("[INFO] targets(sample):", target_ids[:20])

    # ===== DRY_RUN =====
    if is_dry_run():
        print("[INFO] DRY_RUN=1 のため送信・更新は実行しません")
        return

    # ===== 送信 =====
    for t in targets:
        uid = t.get("user_id")
        name = (t.get("display_name") or "").strip()

        if not uid:
            continue

        if msg7_template:
            text7 = msg7_template.format(name=name, display_name=name)
        else:
            text7 = "{} さん、登録1週間記念のクーポンです。".format(name)

        if coupon_url:
            tracking_url = build_tracking_url(shop_id, "7days", uid, coupon_url)
            ok = send_coupon_flex_message(token, uid, text7, url7, tracking_url)
        else:
            ok = send_coupon_message(token, uid, text7, url7)

        if ok:
            sent7 += 1
            sent_at_utc_iso = now.astimezone(timezone.utc).isoformat()

            # ★ DB更新（重複送信防止の本丸）
            try:
                mark_7day_sent_in_db(shop_id, uid, sent_at_utc_iso)
            except Exception as e:
                print(f"[ERROR] users.coupon7_sent_at 更新失敗 shop={shop_id} uid={uid} err={e}")

            # 監査ログ（現状維持）
            send_logs.append(
                {
                    "shop_id": shop_id,
                    "user_id": uid,
                    "coupon_type": "7days",
                    "sent_at": sent_at_utc_iso,
                }
            )

    # 送付ログをSupabaseにまとめて保存
    if send_logs:
        insert_coupon_send_logs(send_logs)

    print("[INFO] {}: 7日={}件".format(shop_id, sent7))


# ===== メイン =====

def main():
    now = jst_now()
    shops = load_shops()

    if not shops:
        print("[ERROR] shops.yaml が空")
        return

    for sid, conf in shops.items():
        try:
            run_for_shop(sid, conf, now)
        except Exception as e:
            print("[ERROR] {} 実行中例外: {}".format(sid, e))


if __name__ == "__main__":
    main()
