# restaurant_ai_pro/bin/cron_meo.py
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import sys
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from meo.runner import run_meo_for_shop

CONFIG_PATH = PROJECT_ROOT / "config" / "shops.yaml"


def load_shops():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    shops = []
    for item in raw.get("shops", []):
        # place_id & location_id がある店舗だけ MEO 対象
        if item.get("place_id") and item.get("location_id"):
            shops.append(item)
    return shops


def main():
    shops = load_shops()
    for shop in shops:
        print(f"=== MEO RUN: {shop['id']} ({shop.get('name', '')}) ===")
        run_meo_for_shop(shop)


if __name__ == "__main__":
    main()
