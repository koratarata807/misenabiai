
from __future__ import annotations
import pandas as pd, numpy as np
from dataclasses import dataclass

@dataclass
class WeeklySummary:
    total_sales: int
    days: int
    avg_day_sales: int
    total_guests: int|None
    new_customers: int|None
    repeat_rate_avg: float|None
    best_hour: int
    best_hour_sales: int
    by_hour: dict

def summarize_sales(df: pd.DataFrame) -> WeeklySummary:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    total = int(df["sales"].sum())
    days = int(df["date"].nunique())
    avg_day = int(df.groupby("date")["sales"].sum().mean())
    guests = int(df["guests"].sum()) if "guests" in df.columns else None
    by_hour = df.groupby("hour")["sales"].sum().sort_index()
    best_hour = int(by_hour.idxmax())
    best_hour_sales = int(by_hour.max())
    new_c = int(df["new_customers"].sum()) if "new_customers" in df.columns else None
    rrate = float(df["repeat_rate"].mean()) if "repeat_rate" in df.columns else None
    return WeeklySummary(
        total_sales=total, days=days, avg_day_sales=avg_day, total_guests=guests,
        new_customers=new_c, repeat_rate_avg=rrate, best_hour=best_hour,
        best_hour_sales=best_hour_sales, by_hour=by_hour.to_dict()
    )

def simple_insights(ws: WeeklySummary) -> list[str]:
    tips = []
    tips.append(f"今週売上合計: ¥{ws.total_sales:,}（{ws.days}日） / 日平均: ¥{ws.avg_day_sales:,}")
    if ws.total_guests is not None and ws.total_guests>0:
        tips.append(f"総来客: {ws.total_guests}名 / 客単価概算: ¥{ws.total_sales//ws.total_guests:,}")
    tips.append(f"最盛時間帯: {ws.best_hour}時（売上: ¥{ws.best_hour_sales:,}）")
    if ws.new_customers is not None:
        tips.append(f"新規来店: {ws.new_customers}名")
    if ws.repeat_rate_avg is not None:
        tips.append(f"平均リピート率: {ws.repeat_rate_avg*100:.1f}%")
    tips.append("【次週提案】上位メニューの写真刷新＋週2回のSNSプッシュ／★3以下口コミは即返信")
    return tips
