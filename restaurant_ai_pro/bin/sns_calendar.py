
#!/usr/bin/env python
import argparse, pandas as pd
from datetime import datetime, timedelta
from restaurant_ai.io_utils import read_csv, write_csv

TEMPLATES = [
    "本日のおすすめ『{menu}』。{feature}。{note} ¥{price}",
    "【数量限定】{menu}：{feature}（¥{price}）。{note}",
    "{menu}が今日の主役。{feature}。#札幌グルメ #北大前 #カレー",
    "{menu} / {feature} / ¥{price}。{note}"
]

def render_post(row):
    return TEMPLATES[hash(row.get("menu","")) % len(TEMPLATES)].format(
        menu=row.get("menu","メニュー"),
        feature=row.get("item_feature","おすすめポイント"),
        price=row.get("price","-"),
        note=row.get("yield_note","")
    )

def main():
    ap = argparse.ArgumentParser(description="SNS投稿文生成")
    ap.add_argument("--csv", required=True, help="menu.csv")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--outfile", default="posts.csv")
    args = ap.parse_args()

    menu_df = read_csv(args.csv)
    today = datetime.today()
    rows = []
    for i in range(args.days):
        date = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        for _, r in menu_df.iterrows():
            rows.append({"date": date, "menu": r.get("menu"), "post_text": render_post(r)})
    out = pd.DataFrame(rows)
    write_csv(out, args.outfile)
    print(f"[OK] 投稿文CSV: {args.outfile}")

if __name__ == "__main__":
    main()
