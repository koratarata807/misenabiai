import os, csv
from datetime import datetime
from pathlib import Path
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_ROLE_KEY = os.environ["SUPABASE_SERVICE_ROLE_KEY"]

SHOP_ID = "shopA"
BASE_DIR = Path(__file__).resolve().parents[1]  # .../restaurant_ai_pro
CSV_PATH = BASE_DIR / "data" / "shopA" / "users.csv"

def parse_ts(s):
    if not s:
        return None
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).isoformat()
        except:
            pass
    return s

def main():
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"users.csv not found: {CSV_PATH}")

    sb = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            uid = (r.get("user_id") or r.get("line_user_id") or r.get("uid") or "").strip()
            if not uid:
                continue
            rows.append({
                "shop_id": SHOP_ID,
                "user_id": uid,
                "coupon7_sent_at": parse_ts(r.get("coupon7_sent_at")),
                "coupon30_sent_at": parse_ts(r.get("coupon30_sent_at")),
            })

    sb.table("users").upsert(rows, on_conflict="shop_id,user_id").execute()
    print(f"upserted {len(rows)} users into public.users (shop_id={SHOP_ID})")

if __name__ == "__main__":
    main()

