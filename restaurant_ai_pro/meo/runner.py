# restaurant_ai_pro/meo/runner.py

from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from .fetcher import fetch_meo_snapshot, save_ranking_log

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs" / "meo"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def run_meo_for_shop(shop: Dict[str, Any]) -> None:
    """
    単一店舗の MEO 処理フロー（第1段階）:
      1. Google API からスナップショット取得
      2. ランキングログを CSV に追記
      ※ 将来的にはここに「AI解析/自動投稿/自動返信」を追加していく
    """
    shop_id = shop["id"]
    try:
        snapshot = fetch_meo_snapshot(shop)
        save_ranking_log(snapshot)
        # TODO: analyzer / auto_post / auto_review_reply / scorer をここに差し込む

        print(f"[MEO] {shop_id}: snapshot fetched & ranking logged.")

    except Exception as e:
        log_path = LOG_DIR / f"{shop_id}.log"
        with log_path.open("a", encoding="utf-8") as f:
            ts = datetime.now(JST).isoformat()
            f.write(f"[{ts}] ERROR: {e}\n")
        print(f"[MEO] {shop_id}: ERROR → {e}")
