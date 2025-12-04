#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI週報＋自動提案（日次データ）→ 条件に応じてLINEクーポン自動配信
＋ 「新規が30日以内にリピートした顧客」へ特典メッセージ送付
＋ Broadcast対応（追加されている全員へ一斉配信）

必須環境変数:
- LINE_CHANNEL_ACCESS_TOKEN
- OPENWEATHER_KEY（天気連動を使う場合）

使い方（例）:
  python3 ai_weekly_line_campaign.py \
    --daily_csv data/daily.csv \
    --visits_csv data/visits.csv \
    --line_map_csv data/line_map.csv \
    --recipients data/line_recipients.txt \
    --outdir OUTPUT \
    --city "Sapporo,JP" \
    --coupon_url "https://lin.ee/your-coupon" \
    --threshold 0.95
"""

from __future__ import annotations
import os, argparse, json, time, math
from dataclasses import dataclass
from typing import Optional, Iterable, List, Tuple

import pandas as pd
import requests

# =========================
# Matplotlib: 日本語フォント設定
# =========================
import matplotlib
matplotlib.use("Agg")
from matplotlib import rcParams, font_manager as fm
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/ipaexfont/ipaexg.ttf",
    "/usr/share/fonts/opentype/ipaexg.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/mnt/c/Windows/Fonts/meiryo.ttc",
    "/mnt/c/Windows/Fonts/YuGothR.ttc",
    "/mnt/c/Windows/Fonts/msgothic.ttc",
]
JP_FONT_PATH = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
if JP_FONT_PATH:
    JP = fm.FontProperties(fname=JP_FONT_PATH)
    rcParams["font.family"] = JP.get_name()
else:
    JP = None
    rcParams["font.family"] = "DejaVu Sans"
rcParams["axes.unicode_minus"] = False
rcParams["pdf.fonttype"] = 42
rcParams["ps.fonttype"]  = 42

# =========================
# ユーティリティ
# =========================
def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def read_lines(path: str) -> list[str]:
    if not path or not os.path.exists(path): return []
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]

def to_date(s) -> pd.Timestamp:
    return pd.to_datetime(s).normalize()

# =========================
# データ読み込み
# =========================
def load_daily(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    if "date" not in df.columns or "sales" not in df.columns:
        raise ValueError("daily_csv に 'date','sales' 列が必要です。")
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    if "dow" not in df.columns:
        df["dow"] = df["date"].dt.dayofweek
    for c in ["sales","guests","new_customers","repeat_rate"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("date")

def load_visits(csv_path: Optional[str]) -> Optional[pd.DataFrame]:
    if not csv_path or not os.path.exists(csv_path):
        return None
    v = pd.read_csv(csv_path)
    if "date" not in v.columns or "customer_id" not in v.columns:
        raise ValueError("visits_csv は 'date','customer_id' を含む必要があります。")
    v["date"] = pd.to_datetime(v["date"]).dt.tz_localize(None)
    return v.sort_values(["customer_id","date"])

def load_line_map(csv_path: Optional[str]) -> Optional[pd.DataFrame]:
    if not csv_path or not os.path.exists(csv_path):
        return None
    m = pd.read_csv(csv_path, dtype=str)
    if "customer_id" not in m.columns or "line_user_id" not in m.columns:
        raise ValueError("line_map_csv は 'customer_id','line_user_id' を含む必要があります。")
    return m

# =========================
# 週次サマリー
# =========================
@dataclass
class WeeklySummary:
    start_date: Optional[pd.Timestamp]
    end_date: Optional[pd.Timestamp]
    total_sales: float
    avg_day_sales: float
    total_guests: Optional[float]
    repeat_rate_avg: Optional[float]
    dow_weak: Optional[int]
    trend_ratio: Optional[float]
    msg_proposals: List[str]

def analyze_week(daily: pd.DataFrame) -> WeeklySummary:
    if daily.empty:
        return WeeklySummary(None,None,0.0,0.0,None,None,None,None,["データなし"])
    end = daily["date"].max()
    start = end - pd.Timedelta(days=6)
    this_w = daily[(daily["date"]>=start)&(daily["date"]<=end)].copy()
    prev_w = daily[(daily["date"]>=start-pd.Timedelta(days=7))&(daily["date"]<start)].copy()

    total_sales = float(this_w["sales"].sum())
    avg_day_sales = float(this_w.groupby(this_w["date"].dt.date)["sales"].sum().mean())

    total_guests = float(this_w["guests"].sum()) if "guests" in this_w.columns else None
    rr = None
    if "repeat_rate" in this_w.columns:
        s = this_w["repeat_rate"].dropna()
        s = s[(s>=0)&(s<=1)]
        if len(s): rr = float(s.mean())

    dow_sales = this_w.groupby("dow")["sales"].mean() if len(this_w) else pd.Series(dtype=float)
    dow_weak = int(dow_sales.idxmin()) if len(dow_sales) else None

    trend_ratio = None
    if len(prev_w)>0 and prev_w["sales"].sum()>0:
        trend_ratio = float(total_sales / prev_w["sales"].sum())

    props: List[str] = []
    if trend_ratio and trend_ratio < 0.95:
        props.append("前週比マイナス：来店促進施策を強化（クーポン／SNS露出）")
    if dow_weak is not None:
        jp = ["月","火","水","木","金","土","日"][dow_weak]
        props.append(f"{jp}曜日が弱い傾向：当日限定割引やSNS投稿時間の見直し推奨")
    if rr and rr < 0.4:
        props.append("リピート率低下：初回来店後1週間のフォロー配信を強化")
    if not props:
        props.append("全体は堅調：上位メニューの画像更新と口コミ返信の継続を推奨")

    return WeeklySummary(start, end, total_sales, avg_day_sales, total_guests, rr, dow_weak, trend_ratio, props)

# =========================
# PDFレポート
# =========================
def _apply_jp_to_axes(ax):
    if JP is None: return
    for lab in ax.get_xticklabels() + ax.get_yticklabels():
        lab.set_fontproperties(JP)
    if ax.get_title(): ax.set_title(ax.get_title(), fontproperties=JP)
    if ax.get_xlabel(): ax.set_xlabel(ax.get_xlabel(), fontproperties=JP)
    if ax.get_ylabel(): ax.set_ylabel(ax.get_ylabel(), fontproperties=JP)

def build_pdf(summary: WeeklySummary, daily: pd.DataFrame, out_pdf: str) -> None:
    with PdfPages(out_pdf) as pdf:
        fig = plt.figure(figsize=(8.27, 11.69))
        fig.text(0.10, 0.92, "AI週報（自動生成）", fontproperties=JP, fontsize=18, weight="bold")
        y = 0.86
        lines = [
            f"期間：{summary.start_date.date()}〜{summary.end_date.date()}",
            f"総売上：¥{summary.total_sales:,.0f}",
            f"日平均：¥{summary.avg_day_sales:,.0f}",
        ]
        if summary.total_guests is not None:
            lines.append(f"総来客：{int(summary.total_guests):,}名")
        if summary.repeat_rate_avg is not None:
            lines.append(f"平均リピート率：{summary.repeat_rate_avg*100:.1f}%")
        if summary.trend_ratio is not None:
            lines.append(f"前週比：{summary.trend_ratio*100:.1f}%")
        if summary.dow_weak is not None:
            jp = ["月","火","水","木","金","土","日"][summary.dow_weak]
            lines.append(f"弱い曜日：{jp}曜日")
        lines.append("— 提案 —")
        lines += [f"・{p}" for p in summary.msg_proposals]
        for ln in lines:
            fig.text(0.10, y, ln, fontproperties=JP, fontsize=12)
            y -= 0.04
        ax = fig.add_axes([0.10, 0.10, 0.80, 0.30])
        last14 = daily[daily["date"]>=summary.end_date - pd.Timedelta(days=13)]
        ax.plot(last14["date"], last14["sales"], marker="o")
        ax.set_title("直近14日 売上推移")
        ax.set_xlabel("日付")
        ax.set_ylabel("売上（円）")
        _apply_jp_to_axes(ax)
        fig.autofmt_xdate()
        pdf.savefig(fig)
        plt.close(fig)

# =========================
# 天気取得（OpenWeather）
# =========================
def fetch_weather(city: Optional[str]=None) -> Optional[str]:
    key = os.environ.get("OPENWEATHER_KEY")
    if not key or not city: return None
    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        resp = requests.get(url, params={"q": city, "appid": key}, timeout=8)
        if resp.status_code != 200:
            return None
        main = (resp.json().get("weather") or [{}])[0].get("main")
        return str(main)
    except Exception:
        return None

def is_bad_weather(main: Optional[str]) -> bool:
    if not main: return False
    return main.lower() in {"rain","snow","drizzle","thunderstorm"}

# =========================
# LINE クライアント
# =========================
LINE_PUSH_API = "https://api.line.me/v2/bot/message/push"
LINE_MULTICAST_API = "https://api.line.me/v2/bot/message/multicast"
LINE_BROADCAST_API = "https://api.line.me/v2/bot/message/broadcast"

def _line_headers() -> dict:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("環境変数 LINE_CHANNEL_ACCESS_TOKEN が未設定です。")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def send_line_broadcast(text: str) -> bool:
    headers = _line_headers()
    payload = {"messages": [{"type": "text", "text": text}]}
    try:
        r = requests.post(LINE_BROADCAST_API, headers=headers,
                          data=json.dumps(payload), timeout=10)
        return (r.status_code == 200)
    except Exception:
        return False

def send_line_text_chunked(to_user_ids: Iterable[str], text: str, chunk_size: int = 500) -> None:
    uids = [u.strip() for u in to_user_ids if u and u.strip()]
    if not uids:
        return
    headers = _line_headers()
    for i in range(0, len(uids), chunk_size):
        chunk = uids[i:i+chunk_size]
        payload = {"to": chunk, "messages": [{"type": "text", "text": text}]}
        r = requests.post(LINE_MULTICAST_API, headers=headers, data=json.dumps(payload), timeout=10)
        if r.status_code == 200:
            continue
        for uid in chunk:
            data = {"to": uid, "messages": [{"type": "text", "text": text}]}
            requests.post(LINE_PUSH_API, headers=headers, data=json.dumps(data), timeout=10)
            time.sleep(0.2)

def build_coupon_message(title: str, description: str, url: str, validity: Optional[str]=None) -> str:
    body = f"🎟️ {title}\n{description}\n\nクーポンはこちら👇\n{url}"
    if validity: body += f"\n有効期限：{validity}"
    return body

# =========================
# リピート検出
# =========================
def detect_repeat_within_30days(visits: pd.DataFrame, line_map: Optional[pd.DataFrame],
                                window_end: pd.Timestamp) -> List[str]:
    if visits is None or line_map is None or visits.empty or line_map.empty:
        return []
    week_start = window_end - pd.Timedelta(days=6)
    out: List[str] = []
    for cid, g in visits.groupby("customer_id"):
        g = g.sort_values("date")
        if len(g) < 2: continue
        first = g.iloc[0]["date"]
        g2 = g[g["date"] > first]
        within = g2[g2["date"] <= first + pd.Timedelta(days=30)]
        if within.empty: continue
        recent = within[(within["date"]>=week_start)&(within["date"]<=window_end)]
        if recent.empty: continue
        row = line_map[line_map["customer_id"]==str(cid)]
        if row.empty: continue
        line_id = row.iloc[0]["line_user_id"]
        out.append(line_id)
    return list(set(out))

# =========================
# メイン
# =========================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily_csv", required=True)
    ap.add_argument("--visits_csv", default=None)
    ap.add_argument("--line_map_csv", default=None)
    ap.add_argument("--recipients", default="data/line_recipients.txt")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--city", default=None)
    ap.add_argument("--coupon_url", default="https://lin.ee/your-coupon")
    ap.add_argument("--threshold", type=float, default=0.95)
    args = ap.parse_args()

    ensure_dir(args.outdir)
    daily = load_daily(args.daily_csv)
    visits = load_visits(args.visits_csv)
    line_map = load_line_map(args.line_map_csv)
    recipients = read_lines(args.recipients)

    ws = analyze_week(daily)
    pdf_path = os.path.join(args.outdir, "weekly_report.pdf")
    build_pdf(ws, daily, pdf_path)

    # === 週報送信 ===
    headline = (f"📊 AI週報\n期間：{ws.start_date.date()}〜{ws.end_date.date()}\n"
                f"総売上：¥{ws.total_sales:,.0f}\n日平均：¥{ws.avg_day_sales:,.0f}\n")
    if ws.trend_ratio is not None:
        headline += f"前週比：{ws.trend_ratio*100:.1f}%\n"
    headline += "\n— 提案 —\n" + "\n".join([f"・{p}" for p in ws.msg_proposals])

    try:
        sent = send_line_broadcast(headline)
        if not sent and recipients:
            send_line_text_chunked(recipients, headline)
    except Exception as e:
        print(f"[LINE warn] 週報送信失敗: {e}")

    # === クーポン送信（トレンド×天気） ===
    should_coupon = False
    if ws.trend_ratio and ws.trend_ratio < args.threshold:
        weather = fetch_weather(args.city)
        bad = is_bad_weather(weather)
        weak_today = (ws.dow_weak is not None and ws.end_date.dayofweek == ws.dow_weak)
        should_coupon = bad or weak_today
        if should_coupon:
            msg = build_coupon_message("本日18–21時限定 10%OFF",
                                       "天候・トレンドを踏まえ、今夜限定のクーポンをご案内します。",
                                       args.coupon_url, validity="本日限り")
            try:
                sent = send_line_broadcast(msg)
                if not sent and recipients:
                    send_line_text_chunked(recipients, msg)
            except Exception as e:
                print(f"[LINE warn] クーポン送信失敗: {e}")

    # === 新規→30日以内リピート特典 ===
    if visits is not None and line_map is not None:
        ids = detect_repeat_within_30days(visits, line_map, ws.end_date)
        if ids:
            text = ("🎁 再来店ありがとうございます！特典をご利用ください\n"
                    "初回来店から30日以内の再来店特典です。スタッフにこの画面をご提示ください。")
            try:
                send_line_text_chunked(ids, text)
            except Exception as e:
                print(f"[LINE warn] 特典送信失敗: {e}")

if __name__ == "__main__":
    main()
