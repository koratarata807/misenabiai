#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import subprocess
import os
import yaml
from dotenv import dotenv_values  # pip install python-dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"

def main():
    # shops.yaml 読み込み
    with open(CONFIG_DIR / "shops.yaml", "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    shops = data.get("shops", [])

    for shop in shops:
        sid = shop["id"]

        # ① 店舗ごとの LINE トークン / 環境変数を読み込む
        # 例: config/.env.shopA_line, config/.env.shopB_line みたいな感じを想定
        env_file = CONFIG_DIR / f".env.{sid}"
        if env_file.exists():
            env_vars = dotenv_values(env_file)
        else:
            env_vars = {}

        # ベース環境を継承した上で店舗固有 env を上書き
        child_env = os.environ.copy()
        child_env.update(env_vars)

        # shops.yaml の内容で共通 ENV を設定（スクリプト側から参照されるやつ）
        child_env["SHOP_NAME"] = shop.get("name", "")
        child_env["SHOP_TEL"] = shop.get("tel", "")
        child_env["SHOP_ADDRESS"] = shop.get("address", "")
        child_env["SHOP_HOURS"] = shop.get("hours", "")
        child_env["SHOP_STYLE"] = shop.get("style", "high_tension")
        child_env["SHOP_RESERVE_URL"] = shop.get("reserve_url", "")
        child_env["SHOP_RESERVE_IMAGE_URL"] = shop.get("reserve_image", "")
        child_env["SHOP_LOCATION"] = child_env.get("SHOP_LOCATION", "residential")

        # cooldown / broadcast も ENV で渡す（または引数でもOK）
        child_env["COOLDOWN_HOURS"] = str(shop.get("cooldown_hours", 24))
        if not shop.get("broadcast", False):
            child_env["DISABLE_BROADCAST"] = "1"

        daily_csv = str((PROJECT_ROOT / shop["daily_csv"]).resolve())
        outdir    = str((PROJECT_ROOT / shop["outdir"]).resolve())
        menu_csv  = str((PROJECT_ROOT / shop.get("menu_csv", "")).resolve()) if shop.get("menu_csv") else None
        coupon_url = shop.get("coupon_url", "")

        # ② 店舗ごとに ai_weekly_campaign.py を呼ぶ
        cmd = [
            "python3",
            str(PROJECT_ROOT / "bin/ai_weekly_line_campaign_onlyoneshop.py"),
            "--daily_csv", daily_csv,
            "--outdir", outdir,
            "--only_coupon",
            "--state_dir", str(PROJECT_ROOT / ".state" / sid),
            "--city", shop.get("city", "Sapporo,JP"),
            "--coupon_url", coupon_url,
        ]

        # menu_csv が定義されていれば引数として渡す
        if menu_csv and os.path.exists(menu_csv):
            cmd += ["--menu_csv", menu_csv]

        # broadcast フラグ
        if shop.get("broadcast", False):
            cmd += ["--enable_broadcast"]

        # 閾値（売上トレンドのしきい値）
        if "threshold" in shop:
            cmd += ["--threshold", str(shop["threshold"])]

        # cooldown を ENV ベースでなく引数にしたいならこちらでもOK
        if "cooldown_hours" in shop:
            cmd += ["--cooldown_hours", str(shop["cooldown_hours"])]

        print(f"[INFO] Running campaign for {sid} ...")
        subprocess.run(cmd, env=child_env, check=False)

if __name__ == "__main__":
    main()
