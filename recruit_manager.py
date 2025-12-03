import pandas as pd
from pathlib import Path

# ===== 設定 =====
# GoogleフォームのCSV（あなたの環境に合わせた絶対パス）
INPUT_CSV = "/mnt/c/Users/hayato/Downloads/e.csv"

# 出力フォルダ
OUTPUT_DIR = Path("OUTPUT/applicants")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ===== スコアリングロジック =====
def score_applicant(row):
    score = 0

    # 飲食経験あり → +3
    if "あり" in str(row.get("experience", "")):
        score += 3

    # どちらでも → +2
    if "どちらでも" in str(row.get("position", "")):
        score += 2

    # 曜日（全角・半角カンマ対応）
    days_str = str(row.get("available_days", ""))
    days_str = days_str.replace(" ", "").replace("、", ",")
    num_days = len([d for d in days_str.split(",") if d])

    if num_days >= 4:
        score += 3
    elif num_days >= 2:
        score += 1

    # 年齢（18〜30歳 → +1）
    try:
        age = int(str(row.get("age", "")).strip())
        if 18 <= age <= 30:
            score += 1
    except:
        pass

    return score


# ===== メイン処理 =====
def main():
    # --- 1. CSV読み込み ---
    df = pd.read_csv(INPUT_CSV)

    # --- 2. 列名リネーム（あなたのCSVに完全一致対応） ---
    rename_map = {
        "タイムスタンプ": "timestamp",
        "  1. お名前（必須）  ": "name",
        "  2. 年齢（必須）  ": "age",
        "  3. 希望店舗（必須）  ": "shop",
        "  4. 希望ポジション（必須）  ": "position",
        "  5. 経験（必須）  ": "experience",
        "  6. 勤務可能曜日（必須) ": "available_days",
        "  7. 勤務可能時間帯（任意）  ": "available_times",
        "  8. 最寄り駅（任意）  ": "nearest_station",
        "  9. 一言PR（任意）  ": "comment",
    }
    df = df.rename(columns=rename_map)

    # --- 3. 前処理（余計な空白・全角スペース除去） ---
    df["shop"] = df["shop"].astype(str).str.strip().str.replace("　", "")

    # --- 4. スコア列追加 ---
    df["score"] = df.apply(score_applicant, axis=1)

    # --- 5. スコア順ソート ---
    df_sorted = df.sort_values("score", ascending=False)

    # --- 6. 全体一覧出力 ---
    all_out_path = OUTPUT_DIR / "all_applicants_scored.csv"
    df_sorted.to_csv(all_out_path, index=False)
    print(f"[INFO] 全体一覧 → {all_out_path}")

        # --- 7. 店舗ごとに仕分けて出力（店内順位付き） ---
    for shop_name, sub_df in df_sorted.groupby("shop"):
        sub_df = sub_df.sort_values("score", ascending=False).reset_index(drop=True)
        sub_df.insert(0, "rank_in_shop", sub_df.index + 1)

        # 見せたい列だけに絞る（店ごとの見やすい表）
        cols_shop = [
            "rank_in_shop",
            "name",
            "age",
            "position",
            "experience",
            "available_days",
            "available_times",
            "score",
            "timestamp",
            "nearest_station",
            "comment",
        ]
        sub_df = sub_df[cols_shop]

        safe_name = shop_name.replace("/", "_").replace(" ", "_")
        out_path = OUTPUT_DIR / f"{safe_name}_ranking.csv"
        sub_df.to_csv(out_path, index=False)
        print(f"[INFO] 店舗別ランキング → {shop_name} → {out_path}")

if __name__ == "__main__":
    main()

