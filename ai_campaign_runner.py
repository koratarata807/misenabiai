#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全店舗ランナー
- shops.yaml を読み、店舗ごとに .env.<shopId> をロードして本体を実行
- 1店舗失敗しても他店舗は継続（障害分離）
- 店舗別ログ logs/<shopId>.log に STDOUT/STDERR/EXIT を蓄積
- DISABLE_BROADCAST=1 で一斉配信を全体停止
- --only <shopId> で対象店舗を絞り込み可能
"""
import os
import sys
import subprocess
import pathlib
import datetime as dt
import argparse
import yaml
from dotenv import load_dotenv

ROOT = pathlib.Path(__file__).resolve().parents[1]   # プロジェクト直下
BIN  = ROOT.joinpath("bin")

def find_config_path(relpath: str) -> pathlib.Path:
    """
    config は ①ROOT/config ②ROOT/bin/config の順で探索
    """
    p1 = ROOT.joinpath("config", relpath)
    if p1.exists():
        return p1
    p2 = BIN.joinpath("config", relpath)
    if p2.exists():
        return p2
    return p1  # デフォルトは ROOT/config 側（存在しなければ open 時に例外）

def load_yaml(path: pathlib.Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def log_path(shop_id: str) -> pathlib.Path:
    logs = ROOT.joinpath("logs")
    logs.mkdir(parents=True, exist_ok=True)
    return logs.joinpath(f"{shop_id}.log")

def run_shop(shop: dict):
    sid = shop["id"]

    # 1) 店舗ごとの .env をロード（あれば）
    env_file = find_config_path(f".env.{sid}")
    if env_file.exists():
        load_dotenv(env_file)  # ← 外部ライブラリの load_dotenv
        print(f"[INFO] loaded {env_file}")
    else:
        print(f"[WARN] missing {env_file} (continue)")
    print(f"[DEBUG] shop={shop['id']} threshold={shop.get('threshold')} cooldown={shop.get('cooldown_hours')} broadcast={shop.get('broadcast')}")

    # 2) 起動コマンドを構築
    cmd = [
        sys.executable, str(BIN.joinpath("ai2_weekly_line_campaign.py")),
        "--daily_csv", shop["daily_csv"],
        "--outdir",    shop["outdir"],
        "--city",      shop.get("city", ""),
        "--coupon_url",shop.get("coupon_url", "https://lin.ee/coupon"),
        "--threshold", str(shop.get("threshold", 0.95)),
        "--cooldown_hours", str(shop.get("cooldown_hours", 24)),
        "--state_dir", str(ROOT.joinpath(".state", sid)),
        "--only_coupon",          # 顧客向け運用（週報テキストは送らない）
        # 必要に応じて --dry_run をここに付け足して検証も可
    ]

    if "menu_csv" in shop:
        cmd.extend(["--menu_csv", shop["menu_csv"]])

        
    # broadcast 許可（緊急停止フラグ優先）
    if shop.get("broadcast", False) and os.environ.get("DISABLE_BROADCAST", "0") != "1":
        cmd.append("--enable_broadcast")

    # 3) 実行環境
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)   # bin外からも restaurant_ai を import できるように
    env["MPLBACKEND"] = "Agg"

    # 4) 実行＆ログ
    ts = dt.datetime.now().isoformat(timespec="seconds")
    lp = log_path(sid)
    with open(lp, "a", encoding="utf-8") as lg:
        lg.write(f"\n[{ts}] RUN {sid}\nCMD: {' '.join(cmd)}\n")
        try:
            p = subprocess.run(cmd, cwd=str(ROOT), env=env,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, check=False)
            if p.stdout:
                lg.write(p.stdout)
            if p.stderr:
                lg.write("\n[STDERR]\n" + p.stderr)
            lg.write(f"\nEXIT={p.returncode}\n")
        except Exception as e:
            lg.write(f"[EXC] {e}\n")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/shops.yaml",
                    help="shops.yaml のパス（ROOT/config or bin/config を自動探索）")
    ap.add_argument("--only", default=None, help="この shopId のみ実行（例: shopA）")
    args = ap.parse_args()

    cfg_path = find_config_path(os.path.basename(args.config)) \
        if not os.path.isabs(args.config) else pathlib.Path(args.config)
    cfg = load_yaml(cfg_path)

    targets = cfg["shops"]
    if args.only:
        targets = [s for s in targets if s["id"] == args.only]
        if not targets:
            print(f"[ERROR] shop '{args.only}' not found in {cfg_path}")
            sys.exit(1)

    for shop in targets:
        try:
            run_shop(shop)
        except Exception as e:
            ts = dt.datetime.now().isoformat(timespec="seconds")
            with open(log_path(shop["id"]), "a", encoding="utf-8") as lg:
                lg.write(f"\n[{ts}] FATAL {e}\n")

if __name__ == "__main__":
    main()

