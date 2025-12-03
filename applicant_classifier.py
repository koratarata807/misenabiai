#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
応募者データ自動仕分けプログラム（みせナビAI・バックオフィス拡張）

機能：
- 応募者CSVを読み込み
- 条件に応じてタグ付け（夜強い／週末強い／未経験OK 等）
- スコアリングして「第一候補／保留／除外」に自動分類
- 店舗別のCSVを出力

使い方：
    python3 applicant_classifier.py applicants_2025-11-17.csv
"""

import sys
import os
import pandas as pd
import re
from datetime import datetime

# -------------------------
# 設定値（あとで調整しやすいようにここに集約）
# -------------------------

# ピークとなる曜日・時間帯（例：金土の夜）
PEAK_DAYS = ["金", "土"]
PEAK_TIME_RANGE = (17, 24)  # 17時〜24時を「夜ピーク」とみなす

# スコアの閾値
SCORE_PRIMARY = 8   # これ以上は「第一候補」
SCORE_HOLD = 4      # これ以上は「保留」、未満は「除外」

# 長期とみなす月数の目安（今回は長期フラグがあれば加点する前提で使わない）
LONG_TERM_KEYWORDS = ["長期", "半年以上", "1年以上"]

# -------------------------
# ユーティリティ関数
# -------------------------

def parse_experience_years(raw: str) -> float:
    """飲食経験年数らしき文字列から年数を抽出（なければ0）"""
    if pd.isna(raw):
        return 0.0
    text = str(raw)
    if "未経験" in text:
        return 0.0
    # 数字だけ拾う（例: "2年", "1.5年"など）
    m = re.search(r"(\d+(\.\d+)?)", text)
    if m:
        return float(m.group(1))
    return 0.0

def contains_any(text: str, keywords) -> bool:
    if pd.isna(text):
        return False
    t = str(text)
    return any(k in t for k in keywords)

def parse_available_days(raw: str):
    """勤務可能曜日の文字列から曜日リストを抽出（例: '月,火,金' → ['月','火','金']）"""
    if pd.isna(raw):
        return []
    text = str(raw).replace("曜日", "")
    # 全角コンマ対策
    text = text.replace("，", ",")
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return parts

def parse_available_hours(raw: str):
    """
    勤務可能時間帯文字列から、大まかな時間範囲を返す
    例:
        '18:00-23:00' → (18, 23)
        'ランチのみ'   → (10, 15) 仮
        'オール'      → (0, 24)
    """
    if pd.isna(raw):
        return None
    text = str(raw)

    # 明示的な時間帯 "18:00-23:00" 等
    m = re.search(r"(\d{1,2})[:：]?\d{0,2}\s*[-〜]\s*(\d{1,2})", text)
    if m:
        start = int(m.group(1))
        end = int(m.group(2))
        return (start, end)

    # キーワードベース
    if "ランチ" in text:
        return (10, 15)
    if "ディナー" in text or "夜" in text:
        return (17, 23)
    if "オール" in text or "終電" in text:
        return (0, 24)

    return None

def hours_overlap(range1, range2):
    """2つの(開始,終了)タプルの重なりがあるか判定"""
    if not range1 or not range2:
        return False
    s1, e1 = range1
    s2, e2 = range2
    return not (e1 <= s2 or e2 <= s1)

# -------------------------
# 応募者1人分のタグ付け＆スコアリング
# -------------------------

def evaluate_applicant(row: pd.Series):
    tags = []
    score = 0

    # 基本情報取得
    exp_years = parse_experience_years(row.get("飲食経験年数", ""))
    days = parse_available_days(row.get("勤務可能曜日", ""))
    hours = parse_available_hours(row.get("勤務可能時間帯", ""))
    long_term_raw = str(row.get("長期希望", "")).strip()
    commute_raw = str(row.get("通勤手段", "")).strip()
    desired_shifts_raw = str(row.get("希望月間シフト数", "")).strip()

    # === 経験年数 ===
    if exp_years == 0:
        tags.append("未経験")
        score += 1  # 未経験でもOKだが、即戦力ではない前提
    elif exp_years < 1:
        tags.append("経験1年未満")
        score += 2
    elif exp_years < 3:
        tags.append("経験1〜3年")
        score += 3
    else:
        tags.append("経験3年以上")
        score += 4  # ベテラン枠

    # === 勤務可能曜日 ===
    if any(d in days for d in PEAK_DAYS):
        tags.append("週末出勤可")
        score += 3
    if contains_any("".join(days), ["日"]):
        tags.append("日曜出勤可")
        score += 1
    if len(days) >= 4:
        tags.append("週4日以上可")
        score += 2
    elif len(days) >= 2:
        tags.append("週2〜3日可")
        score += 1
    else:
        tags.append("週1日程度")
        score -= 1

    # === 勤務時間帯 ===
    if hours_overlap(hours, PEAK_TIME_RANGE):
        tags.append("夜ピーク対応可")
        score += 3
    elif hours:
        tags.append("時間帯限定")
        score += 0  # 加点なし・減点なし
    else:
        tags.append("時間帯不明")
        score -= 1

    # === 長期希望 ===
    if contains_any(long_term_raw, ["はい", "希望する", "長期"]):
        tags.append("長期希望")
        score += 2
    elif contains_any(long_term_raw, ["短期", "3ヶ月", "期間限定"]):
        tags.append("短期希望")
        score -= 1

    # === 通勤手段 ===
    if contains_any(commute_raw, ["徒歩", "自転車"]):
        tags.append("近隣在住")
        score += 2
    elif contains_any(commute_raw, ["電車", "バス", "車"]):
        tags.append("遠方通勤")
        score += 0

    # === 希望シフト数（ざっくり） ===
    if contains_any(desired_shifts_raw, ["週4", "週5", "フル", "レギュラー"]):
        tags.append("高稼働希望")
        score += 2
    elif contains_any(desired_shifts_raw, ["週2", "週3"]):
        tags.append("中稼働希望")
        score += 1
    elif contains_any(desired_shifts_raw, ["週1", "たまに"]):
        tags.append("低稼働希望")
        score -= 1

    # 将来のために必要ならここに追加条件をどんどん足せる

    # === 採用ステータス判定 ===
    if score >= SCORE_PRIMARY:
        status = "第一候補"
    elif score >= SCORE_HOLD:
        status = "保留"
    else:
        status = "除外"

    return "|".join(tags), score, status

# -------------------------
# メイン処理
# -------------------------

def classify_applicants(input_csv: str):
    df = pd.read_csv(input_csv)

    # 結果格納用リスト
    tag_list = []
    score_list = []
    status_list = []

    for _, row in df.iterrows():
        tags, score, status = evaluate_applicant(row)
        tag_list.append(tags)
        score_list.append(score)
        status_list.append(status)

    df["AIタグ"] = tag_list
    df["AIスコア"] = score_list
    df["AIステータス"] = status_list

    # 全体ファイル出力
    base_name = os.path.splitext(os.path.basename(input_csv))[0]
    out_all = f"classified_{base_name}.csv"
    df.to_csv(out_all, index=False)
    print(f"[INFO] 全応募者の分類結果を出力しました: {out_all}")

    # 店舗別に分割（希望店舗列がある前提）
    if "希望店舗" in df.columns:
        for shop, sub in df.groupby("希望店舗"):
            # 第一候補＋保留だけを出したい場合
            sub_filtered = sub[sub["AIステータス"].isin(["第一候補", "保留"])].copy()
            out_shop = f"classified_by_shop_{shop}.csv"
            sub_filtered.to_csv(out_shop, index=False)
            print(f"[INFO] 店舗別リストを出力しました: {out_shop}（{len(sub_filtered)}件）")
    else:
        print("[WARN] '希望店舗' 列がないため、店舗別出力はスキップしました。")

def main():
    if len(sys.argv) < 2:
        print("使い方: python3 applicant_classifier.py <applicants.csv>")
        sys.exit(1)

    input_csv = sys.argv[1]
    if not os.path.exists(input_csv):
        print(f"[ERROR] ファイルが見つかりません: {input_csv}")
        sys.exit(1)

    classify_applicants(input_csv)

if __name__ == "__main__":
    main()
