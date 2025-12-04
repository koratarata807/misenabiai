#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
シフト自動割り当て（みせナビAI・バックオフィス拡張・拡張版）

追加ルール：
- 新人は金土の夜（start_hour >= 17）の枠では必ずベテランと同枠になるように調整
- 各シフト枠に最低 min_kitchen 人のキッチン要員（role に「キッチン」を含む）が入るよう優先配置
- shift_requirements.csv に start_hour / end_hour を持たせ、時間帯を細分化（例：17-19, 19-23）
"""

import argparse
import os
from typing import Dict, List, Tuple

import pandas as pd

# 曜日の優先度（大きいほど先に割当）
DAY_PRIORITY: Dict[str, int] = {
    "月": 1,
    "火": 1,
    "水": 1,
    "木": 1,
    "金": 3,  # 金・土を高優先度
    "土": 3,
    "日": 2,
}

DAY_ORDER: Dict[str, int] = {
    "月": 0,
    "火": 1,
    "水": 2,
    "木": 3,
    "金": 4,
    "土": 5,
    "日": 6,
}

SLOT_ORDER: Dict[str, int] = {
    "LUNCH": 0,
    "DINNER": 1,
}

def parse_available_days(raw: str) -> List[str]:
    """'月,火,金' のような文字列を ['月','火','金'] に変換"""
    if pd.isna(raw):
        return []
    text = str(raw).replace("曜日", "")
    text = text.replace("，", ",")
    return [x.strip() for x in text.split(",") if x.strip()]


def load_staff_master(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # bool系（0/1）を int に統一
    for col in ["is_newbie", "can_lunch", "can_dinner"]:
        if col in df.columns:
            df[col] = df[col].astype(int)
    df["available_days_list"] = df["available_days"].apply(parse_available_days)
    return df


def load_shift_requirements(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    # デフォルト値（列が無い場合に備えて）
    if "min_veterans" not in df.columns:
        df["min_veterans"] = 1
    if "min_kitchen" not in df.columns:
        df["min_kitchen"] = 1

    # 並び順：ピーク優先（DAY_PRIORITY、DINNER優先）
    def _priority(row):
        day_pri = DAY_PRIORITY.get(row["day"], 1)
        slot_pri = 2 if row["slot"] == "DINNER" else 1
        return (day_pri, slot_pri)

    df["_priority"] = df.apply(_priority, axis=1)
    df = df.sort_values(by="_priority", ascending=False).reset_index(drop=True)
    return df


def is_available_for_slot(staff: pd.Series, day: str, slot: str) -> bool:
    """そのスタッフが指定の曜日・時間帯区分（LUNCH/DINNER）に入れるかの判定"""
    if day not in staff["available_days_list"]:
        return False
    if slot == "LUNCH" and staff.get("can_lunch", 1) != 1:
        return False
    if slot == "DINNER" and staff.get("can_dinner", 1) != 1:
        return False
    return True


def is_kitchen(staff: pd.Series) -> bool:
    """role に 'キッチン' を含むかでキッチン判定"""
    role = str(staff.get("role", ""))
    return "キッチン" in role


def select_staff_for_shift(
    staff_df: pd.DataFrame,
    assigned_counts: Dict[str, int],
    day: str,
    slot: str,
    start_hour: int,
    end_hour: int,
    required_staff: int,
    min_veterans: int,
    min_kitchen: int,
) -> List[pd.Series]:
    """
    1枠（day, slot, start_hour, end_hour）に対してどのスタッフを入れるか決定する。

    ルール：
      - 金土かつ start_hour >= 17 の枠は、最低1人はベテランを入れる（可能な限り）
      - min_veterans, min_kitchen を満たすようにベテラン＆キッチンを優先配置
      - その上で required_staff に達するまで、シフト数の少ない人から詰める
    """

    # 金土の夜は強制的に min_veterans を 1 以上に
    if day in ["金", "土"] and start_hour >= 17:
        if min_veterans < 1:
            min_veterans = 1

    # 利用可能なスタッフのみ候補に
    candidates: List[pd.Series] = []
    for _, s in staff_df.iterrows():
        sid = s["staff_id"]
        if not is_available_for_slot(s, day, slot):
            continue
        if assigned_counts.get(sid, 0) >= s["max_shifts"]:
            continue
        candidates.append(s)

    if not candidates:
        return []

    # ベテラン／新人／キッチンで分類
    veterans = [s for s in candidates if s["is_newbie"] == 0]
    newbies = [s for s in candidates if s["is_newbie"] == 1]
    kitchens = [s for s in candidates if is_kitchen(s)]

    # シフト割当数の少ない人を優先できるようにソート
    def sort_by_assigned(pool: List[pd.Series]) -> List[pd.Series]:
        return sorted(pool, key=lambda s: assigned_counts.get(s["staff_id"], 0))

    veterans = sort_by_assigned(veterans)
    newbies = sort_by_assigned(newbies)
    kitchens = sort_by_assigned(kitchens)

    selected: List[pd.Series] = []

    # 1) ベテラン枠の確保
    used_ids = set()
    for s in veterans:
        if len(selected) >= required_staff:
            break
        if len([x for x in selected if x["is_newbie"] == 0]) >= min_veterans:
            break
        sid = s["staff_id"]
        if sid in used_ids:
            continue
        selected.append(s)
        used_ids.add(sid)

    # 2) キッチン枠の確保（まだ min_kitchen に達していなければ）
    def current_kitchen_count(sel: List[pd.Series]) -> int:
        return sum(1 for x in sel if is_kitchen(x))

    for s in kitchens:
        if len(selected) >= required_staff:
            break
        if current_kitchen_count(selected) >= min_kitchen:
            break
        sid = s["staff_id"]
        if sid in used_ids:
            continue
        selected.append(s)
        used_ids.add(sid)

    # 3) 残りをベテラン優先で埋め、その後新人で埋める
    def fill_from_pool(pool: List[pd.Series]):
        nonlocal selected, used_ids
        for s in pool:
            if len(selected) >= required_staff:
                break
            sid = s["staff_id"]
            if sid in used_ids:
                continue
            selected.append(s)
            used_ids.add(sid)

    fill_from_pool(veterans)
    fill_from_pool(newbies)

    return selected


def schedule_shifts(
    staff_df: pd.DataFrame,
    req_df: pd.DataFrame,
) -> Tuple[pd.DataFrame, pd.DataFrame, float]:
    """全枠についてシフトを割り当てるメイン処理"""
    assigned_counts: Dict[str, int] = {sid: 0 for sid in staff_df["staff_id"]}
    schedule_rows = []

    for _, req in req_df.iterrows():
        day = req["day"]
        slot = req["slot"]
        start_hour = int(req["start_hour"])
        end_hour = int(req["end_hour"])
        required_staff = int(req["required_staff"])
        min_veterans = int(req.get("min_veterans", 1))
        min_kitchen = int(req.get("min_kitchen", 1))

        slot_hours = float(end_hour - start_hour)

        selected = select_staff_for_shift(
            staff_df,
            assigned_counts,
            day,
            slot,
            start_hour,
            end_hour,
            required_staff,
            min_veterans,
            min_kitchen,
        )

        if not selected:
            # 誰も割り当てられない場合は不足として記録
            schedule_rows.append(
                {
                    "day": day,
                    "slot": slot,
                    "start_hour": start_hour,
                    "end_hour": end_hour,
                    "staff_id": None,
                    "name": None,
                    "role": None,
                    "is_newbie": None,
                    "hourly_wage": None,
                    "slot_hours": slot_hours,
                    "labor_cost": None,
                    "note": "スタッフ不足",
                }
            )
            continue

        for s in selected:
            sid = s["staff_id"]
            assigned_counts[sid] += 1
            labor_cost = s["hourly_wage"] * slot_hours

            schedule_rows.append(
                {
                    "day": day,
                    "slot": slot,
                    "start_hour": start_hour,
                    "end_hour": end_hour,
                    "staff_id": sid,
                    "name": s["name"],
                    "role": s["role"],
                    "is_newbie": s["is_newbie"],
                    "hourly_wage": s["hourly_wage"],
                    "slot_hours": slot_hours,
                    "labor_cost": labor_cost,
                    "note": "",
                }
            )

    schedule_df = pd.DataFrame(schedule_rows)

    # スタッフ別集計
    summary_rows = []
    for _, s in staff_df.iterrows():
        sid = s["staff_id"]
        summary_rows.append(
            {
                "staff_id": sid,
                "name": s["name"],
                "assigned_shifts": assigned_counts.get(sid, 0),
                "min_shifts": s["min_shifts"],
                "max_shifts": s["max_shifts"],
            }
        )
    summary_df = pd.DataFrame(summary_rows)

    total_labor_cost = schedule_df["labor_cost"].fillna(0).sum()
    return schedule_df, summary_df, float(total_labor_cost)


def main():
    import math

    parser = argparse.ArgumentParser(description="シフト自動割り当てツール（拡張版）")
    parser.add_argument("--staff", required=True, help="スタッフマスタCSVのパス")
    parser.add_argument("--requirements", required=True, help="シフト必要人数CSVのパス")
    parser.add_argument("--out_schedule", default="weekly_shift_schedule.csv")
    parser.add_argument("--out_summary", default="weekly_shift_summary.csv")
    parser.add_argument(
        "--target_sales",
        type=float,
        default=700000.0,
        help="週の目標売上（人件費率計算用）",
    )
    parser.add_argument(
        "--max_labor_ratio",
        type=float,
        default=0.25,
        help="許容人件費率（例：0.25 = 25%%）",
    )
    args = parser.parse_args()

    if not os.path.exists(args.staff):
        raise FileNotFoundError(f"スタッフマスタが見つかりません: {args.staff}")
    if not os.path.exists(args.requirements):
        raise FileNotFoundError(f"シフト必要人数ファイルが見つかりません: {args.requirements}")

    staff_df = load_staff_master(args.staff)
    req_df = load_shift_requirements(args.requirements)

    schedule_df, summary_df, total_labor_cost = schedule_shifts(staff_df, req_df)

    schedule_df.to_csv(args.out_schedule, index=False)
    summary_df.to_csv(args.out_summary, index=False)

    labor_ratio = None
    if args.target_sales > 0 and not math.isinf(args.target_sales):
        labor_ratio = total_labor_cost / args.target_sales

    print("====== シフト自動割り当て 完了 ======")
    print(f"出力（シフト案）          : {args.out_schedule}")
    print(f"出力（スタッフ別集計）    : {args.out_summary}")
    print(f"推計人件費合計            : {int(total_labor_cost):,} 円")
    if labor_ratio is not None:
        print(f"想定人件費率              : {labor_ratio*100:.1f} %（目標 {args.max_labor_ratio*100:.1f} %）")
        if labor_ratio > args.max_labor_ratio:
            print("⚠ 人件費率が目標を超えています。必要人数や時給設定を見直してください。")

    # ここまでは既存 ----------------
    # 出力前に day, slot, time 順で並べ替え（表示用）
    schedule_df["day_order"] = schedule_df["day"].map(DAY_ORDER).fillna(99).astype(int)
    schedule_df["slot_order"] = schedule_df["slot"].map(SLOT_ORDER).fillna(99).astype(int)

    schedule_df = schedule_df.sort_values(
        by=["day_order", "slot_order", "start_hour", "end_hour", "staff_id"],
        ascending=True
    ).drop(columns=["day_order", "slot_order"])

    schedule_df.to_csv(args.out_schedule, index=False)
    summary_df.to_csv(args.out_summary, index=False)


    # ▼ ここから追加：人間用ビューを作る
    human_rows = []
    if not schedule_df.empty:
        # スタッフ不足の行も含めて、day, slot, start_hour, end_hour ごとに集約
        for (day, slot, start_hour, end_hour), group in schedule_df.groupby(
            ["day", "slot", "start_hour", "end_hour"], dropna=False
        ):
            if group["staff_id"].isna().all():
                # 全員 None = スタッフ不足だけの枠
                staff_list_str = ""
                detail = "スタッフ不足"
            else:
                staffs = []
                kitchen_count = 0
                newbie_count = 0
                for _, row in group.dropna(subset=["staff_id"]).iterrows():
                    name = row["name"]
                    role = row["role"]
                    is_newbie = int(row["is_newbie"]) if pd.notna(row["is_newbie"]) else 0
                    tag_role = role if isinstance(role, str) else ""
                    tag_newbie = "新人" if is_newbie == 1 else "ベテラン"
                    staffs.append(f"{name}({tag_role},{tag_newbie})")
                    if "キッチン" in str(role):
                        kitchen_count += 1
                    if is_newbie == 1:
                        newbie_count += 1

                staff_list_str = " / ".join(staffs)
                detail = f"人数{len(staffs)} / キッチン{kitchen_count} / 新人{newbie_count}"

            time_str = f"{int(start_hour)}-{int(end_hour)}" if pd.notna(start_hour) else ""
            human_rows.append(
                {
                    "day": day,
                    "slot": slot,
                    "time": time_str,
                    "staff_list": staff_list_str,
                    "detail": detail,
                }
            )

        human_df = pd.DataFrame(human_rows)

        human_df["day_order"] = human_df["day"].map(DAY_ORDER).fillna(99).astype(int)
        human_df["slot_order"] = human_df["slot"].map(SLOT_ORDER).fillna(99).astype(int)

        human_df = human_df.sort_values(
            by=["day_order", "slot_order", "time"],
            ascending=True
        ).drop(columns=["day_order", "slot_order"])

        out_human = "weekly_shift_human.csv"
        human_df.to_csv(out_human, index=False)

        print(f"見やすいシフト一覧（人間用） : {out_human}")

if __name__ == "__main__":
    main()
