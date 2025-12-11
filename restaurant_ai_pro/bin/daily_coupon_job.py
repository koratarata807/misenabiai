#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, List
import csv
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
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
SHOPS_YAML = CONFIG_DIR / "shops.yaml"

LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"

# ★ Vercel の tracking API のベースURL（今回の本番）
TRACKING_BASE = "https://misenavi-tracking-rbsey36xe-haya5050akibahu-6610s-projects.vercel.app/api/coupon/redirect"
# ===== Supabase クライアント =====
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # service_role のキー推奨

supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_SERVICE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
else:
    print("[WARN] SUPABASE_URL または SUPABASE_SERVICE_KEY が未設定のため、coupon_send_logs への保存はスキップします")



# ===== ユーティリティ =====

def jst_now() -> datetime:
    """JST 現在時刻を返す"""
    return datetime.now(JST)


def parse_date(date_str: str) -> Optional[datetime]:
    """文字列を datetime に変換（空は None）"""
    if not date_str:
        return None
    date_str = date_str.strip()
    if not date_str:
        return None

    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=JST)
    except ValueError:
        return None


def format_date(dt: Optional[datetime]) -> str:
    """datetime → 'YYYY-MM-DD'（None の場合は ''）"""
    if dt is None:
        return ""
    return dt.strftime("%Y-%m-%d")


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


# ===== ユーザーCSV 読み込み・書き込み =====

def get_users_csv_path(shop_conf: Dict) -> Path:
    """users_csv の実パスを取得"""
    users_csv = shop_conf.get("users_csv")
    if not users_csv:
        sid = shop_conf.get("id")
        return DATA_DIR / sid / "users.csv"

    p = Path(users_csv)
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p


def load_users(shop_conf: Dict) -> List[Dict]:
    """CSV を list[dict] として読み込む"""
    path = get_users_csv_path(shop_conf)
    if not path.exists():
        print("[WARN] users_csv が存在しません: {}".format(path), file=sys.stderr)
        return []

    users: List[Dict] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            users.append(row)

    return users


def save_users(shop_conf: Dict, users: List[Dict]) -> None:
    """CSV に書き戻す"""
    path = get_users_csv_path(shop_conf)

    if not users:
        print("[INFO] {} ユーザー0件のため保存スキップ".format(shop_conf.get("id")))
        return

    fieldnames = list(users[0].keys())
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(users)

    print("[INFO] 保存完了: {}".format(path))


# ===== LINE 送信 =====

def load_line_token(shop_conf: Dict) -> Optional[str]:
    """店舗ごとの .env から LINE トークン取得"""
    env_file = shop_conf.get("env_file")
    if not env_file:
        print("[ERROR] env_file 未設定 (shop_id={})".format(shop_conf.get("id")), file=sys.stderr)
        return None

    env_path = CONFIG_DIR / env_file
    if not env_path.exists():
        print("[ERROR] env_file 不在: {}".format(env_path), file=sys.stderr)
        return None

    env_dict = dotenv_values(env_path)
    token = env_dict.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        print("[ERROR] LINE_CHANNEL_ACCESS_TOKEN がありません: {}".format(env_path), file=sys.stderr)
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

def insert_coupon_send_logs(logs: List[Dict]) -> None:
    """coupon_send_logs にまとめてINSERT"""
    if not logs:
        return
    if supabase is None:
        print("[WARN] Supabaseクライアント未初期化のため coupon_send_logs への保存をスキップ")
        return

    try:
        supabase.table("coupon_send_logs").insert(logs).execute()
        print(f"[INFO] coupon_send_logs に {len(logs)} 行を保存しました")
    except Exception as e:
        print(f"[ERROR] coupon_send_logs へのINSERTに失敗: {e}")

# ===== 判定ロジック =====

def needs_7day_coupon(user: Dict, now: datetime) -> bool:
    reg = parse_date(user.get("registered_at", ""))
    sent = parse_date(user.get("coupon7_sent_at", ""))

    if reg is None:
        return False
    if sent is not None:
        return False

    days = (now.date() - reg.date()).days
    return days >= 7


def needs_30day_coupon(user: Dict, now: datetime) -> bool:
    reg = parse_date(user.get("registered_at", ""))
    sent = parse_date(user.get("coupon30_sent_at", ""))

    if reg is None:
        return False
    if sent is not None:
        return False

    days = (now.date() - reg.date()).days
    return days >= 30


# ===== 店舗処理 =====

def run_for_shop(shop_id: str, shop_conf: Dict, now: datetime) -> None:
    print("\n[INFO] === shop: {} ({}) ===".format(shop_id, shop_conf.get("name")))
    sent7 = 0
    sent30 = 0
    send_logs: List[Dict] = []   # ← これを追加

    url7 = shop_conf.get("coupon7_image")
    url30 = shop_conf.get("coupon30_image")
    coupon_url = shop_conf.get("coupon_url")  # 素の lin.ee など

    if not url7 or not url30:
        print("[ERROR] coupon image URL 未設定 (shop_id={})".format(shop_id))
        return

    token = load_line_token(shop_conf)
    if not token:
        return

    users = load_users(shop_conf)
    if not users:
        print("[INFO] ユーザーCSVなし → スキップ")
        return

    msg7_template = shop_conf.get("coupon_after_7days")
    msg30_template = shop_conf.get("coupon_after_30days")

    sent7 = 0
    sent30 = 0
    send_logs: List[Dict] = []  # ← ここでログ用リストを初期化

    for user in users:
        uid = user.get("user_id")
        name = user.get("display_name", "")

        if not uid:
            continue

        # 7日クーポン
        if needs_7day_coupon(user, now):
            if msg7_template:
                text7 = msg7_template.format(name=name, display_name=name)
            else:
                text7 = "{} さん、登録1週間記念のクーポンです。".format(name)

            if coupon_url:
                # tracking URL に差し替え（coupon_type=7days）
                tracking_url = build_tracking_url(shop_id, "7days", uid, coupon_url)
                ok = send_coupon_flex_message(token, uid, text7, url7, tracking_url)
            else:
                ok = send_coupon_message(token, uid, text7, url7)

            if ok:
                user["coupon7_sent_at"] = format_date(now)
                sent7 += 1
                send_logs.append(
                    {
                        "shop_id": shop_id,
                        "user_id": uid,
                        "coupon_type": "7days",
                        "sent_at": now.astimezone(timezone.utc).isoformat(),
                    }
                )

        # 30日クーポン
        if needs_30day_coupon(user, now):
            if msg30_template:
                text30 = msg30_template.format(name=name, display_name=name)
            else:
                text30 = "{} さん、登録1ヶ月記念のクーポンです。".format(name)

            if coupon_url:
                # tracking URL に差し替え（coupon_type=30days）
                tracking_url = build_tracking_url(shop_id, "30days", uid, coupon_url)
                ok = send_coupon_flex_message(token, uid, text30, url30, tracking_url)
            else:
                ok = send_coupon_message(token, uid, text30, url30)

            if ok:
                user["coupon30_sent_at"] = format_date(now)
                sent30 += 1
                send_logs.append(
                    {
                        "shop_id": shop_id,
                        "user_id": uid,
                        "coupon_type": "30days",
                        "sent_at": now.astimezone(timezone.utc).isoformat(),
                    }
                )

    # ここで送付ログをSupabaseにまとめて保存
    if send_logs:
        insert_coupon_send_logs(send_logs)

    save_users(shop_conf, users)
    print("[INFO] {}: 7日={}件 / 30日={}件".format(shop_id, sent7, sent30))

    # ここで送付ログをSupabaseに保存
    if send_logs:
        insert_coupon_send_logs(send_logs)

    save_users(shop_conf, users)
    print("[INFO] {}: 7日={}件 / 30日={}件".format(shop_id, sent7, sent30))

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