#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flask import Flask, request, abort
from pathlib import Path
from datetime import datetime, timedelta, timezone
import csv
import yaml

JST = timezone(timedelta(hours=9))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
SHOPS_YAML = PROJECT_ROOT / "config" / "shops.yaml"


app = Flask(__name__)

def load_shops():
    """
    config/shops.yaml の形式に合わせて、
    - shops: の下にリストで [ {id: shopA, ...}, {id: shopB, ...} ]
      のような構造を {shopA: {...}, shopB: {...}} に変換して返す
    """
    with SHOPS_YAML.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    shops = {}

    # ★ パターン1：あなたが使っている形式
    # shops:
    #   - {id: shopA, ...}
    #   - {id: shopB, ...}
    if isinstance(raw, dict) and isinstance(raw.get("shops"), list):
        for item in raw["shops"]:
            sid = item.get("id")
            if sid:
                shops[sid] = item

    # ★ パターン2：将来のため shops: {shopA: {...}} にも対応
    elif isinstance(raw, dict) and isinstance(raw.get("shops"), dict):
        shops.update(raw["shops"])

    print("[DEBUG] loaded shops keys:", list(shops.keys()))
    return shops



def users_csv_path(shop_id: str) -> Path:
    shop_dir = DATA_DIR / shop_id
    shop_dir.mkdir(parents=True, exist_ok=True)
    return shop_dir / "users.csv"


def init_users_csv_if_needed(shop_id: str):
    path = users_csv_path(shop_id)
    if not path.exists():
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "user_id",
                    "display_name",
                    "registered_at",
                    "coupon7_sent_at",
                    "coupon30_sent_at",
                ],
            )
            writer.writeheader()


def load_users(shop_id: str):
    init_users_csv_if_needed(shop_id)
    users = []
    with users_csv_path(shop_id).open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            users.append(row)
    return users


def save_users(shop_id: str, users):
    path = users_csv_path(shop_id)
    with path.open("w", encoding="utf-8", newline="") as f:
        fieldnames = [
            "user_id",
            "display_name",
            "registered_at",
            "coupon7_sent_at",
            "coupon30_sent_at",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in users:
            writer.writerow(row)


def upsert_user(shop_id: str, user_id: str, registered_at):
    users = load_users(shop_id)
    found = False
    for row in users:
        if row.get("user_id") == user_id:
            # 既存：登録日は保持、表示名など拡張余地
            found = True
            break
    if not found:
        users.append(
            {
                "user_id": user_id,
                "display_name": "",
                "registered_at": registered_at.isoformat(),
                "coupon7_sent_at": "",
                "coupon30_sent_at": "",
            }
        )
    save_users(shop_id, users)


@app.route("/line/callback/<shop_id>", methods=["POST"])
def callback(shop_id):
    # shops.yamlに存在するshopかチェック（タイポ防止）
    shops = load_shops()
    if shop_id not in shops:
        print(f"[WARN] unknown shop_id: {shop_id}")
        abort(404)

    body = request.get_json()
    if body is None:
        abort(400)

    events = body.get("events", [])
    for event in events:
        etype = event.get("type")
        if etype == "follow":
            source = event.get("source", {})
            user_id = source.get("userId")
            ts = event.get("timestamp")

            if not user_id or ts is None:
                continue

            registered_at = datetime.fromtimestamp(ts / 1000, JST).date()
            upsert_user(shop_id, user_id, registered_at)
            print(f"[INFO] follow: shop={shop_id}, user_id={user_id}, reg={registered_at}")

        # 将来ここに message イベント（来店スタンプ）などを追加する

    return "OK", 200


if __name__ == "__main__":
    # ローカルテスト用
    app.run(host="0.0.0.0", port=8000, debug=True)
