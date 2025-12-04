# restaurant_ai_pro/meo/fetcher.py

from pathlib import Path
from datetime import datetime, timezone, timedelta
import csv
from typing import Dict, Any

from .google_client import GooglePlacesClient, GoogleBusinessClient

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = PROJECT_ROOT / "data" / "meo"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def fetch_meo_snapshot(shop: Dict[str, Any]) -> Dict[str, Any]:
    """
    1店舗ぶんの MEO 関連データを Google API からまとめて取得する。

    shop 例:
      {
        "id": "shopA",
        "place_id": "...",
        "location_id": "locations/123456",
        "meo": {
            "keywords": [...],
            "location": "43.0,141.3"  # あれば
        }
      }
    """
    shop_id = shop["id"]
    place_id = shop["place_id"]
    location_id = shop["location_id"]
    meo_conf = shop.get("meo", {})
    keywords = meo_conf.get("keywords", [])
    loc_str = meo_conf.get("location")  # "lat,lng" 形式があれば使う

    places = GooglePlacesClient()
    biz = GoogleBusinessClient()

    # 店舗基本情報
    details = places.get_place_details(place_id)

    # キーワード別順位
    rankings = {}
    for kw in keywords:
        rank = places.get_ranking(
            target_place_id=place_id,
            keyword=kw,
            location=loc_str,
        )
        rankings[kw] = rank

    # 口コミ・投稿・写真（自動処理の材料になる）
    reviews = biz.list_reviews(location_id)
    posts = biz.list_posts(location_id)
    photos = biz.list_photos(location_id)

    snapshot = {
        "shop_id": shop_id,
        "timestamp": datetime.now(JST).isoformat(),
        "details": details,
        "rankings": rankings,
        "reviews": reviews,
        "posts": posts,
        "photos": photos,
    }
    return snapshot


def save_ranking_log(snapshot: Dict[str, Any]) -> None:
    """
    キーワードごとの順位を CSV に追記する。
    店舗ごとにファイルを分ける（例: shopA_ranking_log.csv）。
    """
    shop_id = snapshot["shop_id"]
    rankings = snapshot["rankings"]
    ts = snapshot["timestamp"]

    outfile = DATA_DIR / f"{shop_id}_ranking_log.csv"
    is_new = not outfile.exists()

    with outfile.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if is_new:
            w.writerow(["timestamp", "keyword", "rank"])
        for kw, rank in rankings.items():
            w.writerow([ts, kw, rank])
