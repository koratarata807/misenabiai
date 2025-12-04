
#!/usr/bin/env python
import argparse, pandas as pd
from restaurant_ai.io_utils import read_csv, write_csv

POLITE = {
    5: "嬉しいお言葉をありがとうございます。スタッフ一同の励みになります！またのご来店を心よりお待ちしております。",
    4: "ご利用ありがとうございます。よりご満足いただけるよう、引き続き工夫してまいります。",
    3: "率直なご意見をありがとうございます。ご指摘の点は改善に努めますので、次回もぜひお試しください。",
    2: "ご不便をおかけし申し訳ありません。詳細を伺い改善します。よろしければDMにてお知らせください。",
    1: "ご期待に沿えず申し訳ありません。真摯に受け止め改善いたします。DMで詳細をご共有いただければ幸いです。"
}

def draft_reply(stars, content):
    base = POLITE.get(int(stars), POLITE[3])
    add = ""
    if isinstance(content, str):
        if "遅" in content or "待" in content:
            add = " 提供時間についてのご指摘、調理と配膳の連携を見直します。"
        elif "接客" in content or "態度" in content:
            add = " 接客面はすぐに共有し、教育・指導を強化いたします。"
        elif "高い" in content or "価格" in content:
            add = " 価格に見合う価値を感じていただけるよう、品質・量・体験を改善します。"
    return base + add

def main():
    ap = argparse.ArgumentParser(description="口コミ返信ドラフト生成")
    ap.add_argument("--csv", required=True, help="reviews.csv")
    ap.add_argument("--outfile", default="reply_drafts.csv")
    args = ap.parse_args()

    df = read_csv(args.csv)
    out_rows = []
    for _, r in df.iterrows():
        reply = draft_reply(r.get("stars", 3), r.get("content",""))
        out_rows.append({
            "platform": r.get("platform",""),
            "stars": r.get("stars",""),
            "content": r.get("content",""),
            "reply_draft": reply
        })
    out = pd.DataFrame(out_rows)
    write_csv(out, args.outfile)
    print(f"[OK] 返信ドラフトCSV: {args.outfile}")

if __name__ == "__main__":
    main()
