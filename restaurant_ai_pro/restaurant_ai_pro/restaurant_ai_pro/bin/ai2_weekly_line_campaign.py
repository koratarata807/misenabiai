#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI週報（PDF生成）＋ 顧客向け 自動販促（クーポン/おすすめ）
- 週報テキストは --only_coupon で抑止（顧客向け運用）
- LINE送信は Broadcast優先 → 失敗時 Multicast → 最後に Push へフォールバック
- 誤配信防止：--cooldown_hours（既定24h）、DISABLE_BROADCAST=1 で一括停止
- 送信サマリ（件数/失敗）を標準出力に記録（ランナーがファイルに吸い上げ）

必要環境変数
- LINE_CHANNEL_ACCESS_TOKEN（必須）
- OPENWEATHER_KEY（任意：天気連動を使う場合）
- MPLBACKEND=Agg（PDF生成時のGUI省略、ランナーが設定）
"""

from __future__ import annotations
import os, json, time, argparse, datetime as dt
from dataclasses import dataclass
from typing import Optional, Iterable, List, Tuple

import pandas as pd
import requests

# 外部モジュール（あなたのパッケージ）
from restaurant_ai.advisor import AdviceInput, generate_actionable_advice

# ========= Matplotlib（日本語フォント/Agg） =========
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

# ========= 定数 =========
LINE_PUSH_API       = "https://api.line.me/v2/bot/message/push"
LINE_MULTICAST_API  = "https://api.line.me/v2/bot/message/multicast"
LINE_BROADCAST_API  = "https://api.line.me/v2/bot/message/broadcast"
OPENWEATHER_URL     = "https://api.openweathermap.org/data/2.5/weather"

# ========= ユーティリティ =========
def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def read_lines(path: Optional[str]) -> list[str]:
    if not path or not os.path.exists(path): return []
    with open(path, "r", encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip()]

def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")

# ========= データ読み込み／分析 =========
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
    return df.sort_values("date").reset_index(drop=True)

@dataclass
class WeeklySummary:
    start_date: pd.Timestamp
    end_date:   pd.Timestamp
    total_sales: float
    avg_day_sales: float
    total_guests: Optional[float]
    repeat_rate_avg: Optional[float]
    dow_weak: Optional[int]
    trend_ratio: Optional[float]
    proposals: List[str]

def analyze_week(daily: pd.DataFrame) -> WeeklySummary:
    if daily.empty:
        today = pd.Timestamp.today().normalize()
        return WeeklySummary(today, today, 0.0, 0.0, None, None, None, None, ["データなし"])
    end = daily["date"].max().normalize()
    start = end - pd.Timedelta(days=6)
    this_w = daily[(daily["date"]>=start)&(daily["date"]<=end)].copy()
    prev_w = daily[(daily["date"]>=start-pd.Timedelta(days=7))&(daily["date"]<start)].copy()

    total_sales   = float(this_w["sales"].sum())
    avg_day_sales = float(this_w.groupby(this_w["date"].dt.date)["sales"].sum().mean())

    total_guests = float(this_w["guests"].sum()) if "guests" in this_w.columns else None

    rr = None
    if "repeat_rate" in this_w.columns:
        s = this_w["repeat_rate"].dropna()
        s = s[(s>=0)&(s<=1)]
        if len(s): rr = float(s.mean())

    dow_sales = this_w.groupby("dow")["sales"].mean() if len(this_w) else pd.Series(dtype=float)
    dow_weak  = int(dow_sales.idxmin()) if len(dow_sales) else None

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

# ========= PDF生成（内部用） =========
def _apply_jp(ax):
    if JP is None: return
    if ax.get_title():  ax.set_title(ax.get_title(),  fontproperties=JP)
    if ax.get_xlabel(): ax.set_xlabel(ax.get_xlabel(), fontproperties=JP)
    if ax.get_ylabel(): ax.set_ylabel(ax.get_ylabel(), fontproperties=JP)
    for lab in ax.get_xticklabels() + ax.get_yticklabels():
        lab.set_fontproperties(JP)

def build_pdf(summary: WeeklySummary, daily: pd.DataFrame, out_pdf: str) -> None:
    ensure_dir(os.path.dirname(out_pdf))
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
        lines += [f"・{p}" for p in summary.proposals]
        for ln in lines:
            fig.text(0.10, y, ln, fontproperties=JP, fontsize=12); y -= 0.04

        ax = fig.add_axes([0.10, 0.10, 0.80, 0.30])
        last14 = daily[daily["date"]>=summary.end_date - pd.Timedelta(days=13)]
        ax.plot(last14["date"], last14["sales"], marker="o")
        ax.set_title("直近14日 売上推移")
        ax.set_xlabel("日付"); ax.set_ylabel("売上（円）")
        _apply_jp(ax)
        fig.autofmt_xdate()
        pdf.savefig(fig); plt.close(fig)

# ========= 天気 =========
def fetch_weather(city: Optional[str]) -> Optional[str]:
    key = os.environ.get("OPENWEATHER_KEY")
    if not key or not city: return None
    try:
        r = requests.get(OPENWEATHER_URL, params={"q":city, "appid":key}, timeout=8)
        if r.status_code != 200: return None
        return (r.json().get("weather") or [{}])[0].get("main")
    except Exception:
        return None

def is_bad_weather(main: Optional[str]) -> bool:
    if not main: return False
    return main.lower() in {"rain","snow","drizzle","thunderstorm"}

# ========= LINE 送信 =========
def _line_headers() -> dict:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("環境変数 LINE_CHANNEL_ACCESS_TOKEN が未設定です。")
    return {"Authorization": f"Bearer {token}", "Content-Type":"application/json"}

def send_broadcast(text: str) -> Tuple[int,int]:
    """return: (ok, fail)"""
    if os.environ.get("DISABLE_BROADCAST","0") == "1":
        print("[INFO] BROADCAST disabled by env (DISABLE_BROADCAST=1)")
        return (0, 0)
    headers = _line_headers()
    payload = {"messages":[{"type":"text","text":text}]}
    r = requests.post(LINE_BROADCAST_API, headers=headers, json=payload, timeout=10)
    if r.status_code == 200:
        return (1, 0)
    print(f"[WARN] BROADCAST {r.status_code}: {r.text}")
    return (0, 1)

def send_multicast(uids: Iterable[str], text: str, chunk: int = 500) -> Tuple[int,int]:
    headers = _line_headers()
    ok=fail=0
    ids = [u.strip() for u in uids if u and u.strip()]
    for i in range(0, len(ids), chunk):
        part = ids[i:i+chunk]
        payload = {"to": part, "messages":[{"type":"text","text":text}]}
        r = requests.post(LINE_MULTICAST_API, headers=headers, json=payload, timeout=10)
        if r.status_code == 200: ok += len(part)
        else:
            print(f"[WARN] MULTICAST {r.status_code}: {r.text} (fallback to push)")
            # フォールバック to push
            for uid in part:
                pr = requests.post(LINE_PUSH_API, headers=headers,
                                   json={"to":uid, "messages":[{"type":"text","text":text}]},
                                   timeout=10)
                if pr.status_code == 200: ok += 1
                else: fail += 1; time.sleep(0.2)
    return (ok, fail)

def send_text_all_modes(text: str,
                        enable_broadcast: bool,
                        recipients: list[str]) -> Tuple[int,int,str]:
    """
    送信方針:
      1) enable_broadcast==True かつ DISABLE_BROADCAST!=1 → broadcast
      2) recipients があれば multicast（失敗は push フォールバック）
    戻り: (ok, fail, mode)  mode in {"broadcast","multicast/push","none"}
    """
    if enable_broadcast and os.environ.get("DISABLE_BROADCAST","0") != "1":
        ok, fail = send_broadcast(text)
        return (ok, fail, "broadcast")
    if recipients:
        ok, fail = send_multicast(recipients, text)
        return (ok, fail, "multicast/push")
    print("[INFO] no recipients and broadcast disabled; send skipped")
    return (0, 0, "none")

# ========= 文面生成 =========
def build_coupon_message(title: str, description: str, url: str, validity: Optional[str]=None) -> str:
    body = f"🎟️ {title}\n{description}\n\nクーポンはこちら👇\n{url}"
    if validity: body += f"\n有効期限：{validity}"
    return body

def build_recommendation(summary: WeeklySummary, weather_main: Optional[str]) -> str:
    tips = []
    if weather_main and weather_main.lower() in {"rain","snow"}:
        tips.append("🌧️ 雨/雪の日は温かいメニューが人気です")
    if summary.dow_weak is not None:
        jp = ["月","火","水","木","金","土","日"][summary.dow_weak]
        tips.append(f"📅 {jp}曜日は限定メニューを強化中")
    head = "🍽️ 本日のおすすめ\n"
    body = "・スパイスチキンカレー：寒い日にぴったり\n・バターチキン：お子様にも人気\n"
    tail = "\n".join(tips) if tips else "今夜のご来店をお待ちしています！"
    return f"{head}{body}\n{tail}"

# ========= 状態（クールダウン） =========
def load_state(path: str) -> dict:
    if not os.path.exists(path): return {}
    try:
        with open(path,"r",encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def save_state(path: str, obj: dict) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path,"w",encoding="utf-8") as f: json.dump(obj,f,ensure_ascii=False,indent=2)

def passed_cooldown(state_path: str, hours: int) -> bool:
    if hours <= 0: return True
    st = load_state(state_path)
    ts = st.get("last_broadcast_at")
    if not ts: return True
    try:
        last = dt.datetime.fromisoformat(ts)
    except Exception:
        return True
    delta = dt.datetime.now().astimezone() - last.astimezone()
    return (delta.total_seconds() >= hours*3600)

# ========= main =========
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily_csv", required=True)
    ap.add_argument("--outdir",    required=True)
    ap.add_argument("--recipients", default=None, help="テスト配信用（userId行区切り）")
    ap.add_argument("--city",       default=None)
    ap.add_argument("--coupon_url", default="https://lin.ee/coupon")
    ap.add_argument("--threshold",  type=float, default=0.95, help="前週比を下回ると販促発火")
    ap.add_argument("--enable_broadcast", action="store_true")
    ap.add_argument("--only_coupon", action="store_true", help="顧客向けモード：週報テキストは送らない")
    ap.add_argument("--no_weekly_message", action="store_true", help="週報テキストを抑止（PDFは生成）")
    ap.add_argument("--cooldown_hours", type=int, default=24, help="最低何時間は再配信しないか")
    ap.add_argument("--state_dir", default=".state", help="配信状態（最終送信時刻等）の保存先")
    ap.add_argument("--dry_run", action="store_true", help="送信せずログのみ")
    args = ap.parse_args()

    ensure_dir(args.outdir)
    daily = load_daily(args.daily_csv)
    ws = analyze_week(daily)

    # === AI提案生成（advisor連携） ===
    menu_path = os.path.join(os.path.dirname(args.daily_csv), "menu.csv")
    menu_df = pd.read_csv(menu_path) if os.path.exists(menu_path) else None

    kpis = {
        "trend_ratio": ws.trend_ratio,
        "repeat_rate_avg": ws.repeat_rate_avg,
        "dow_weak": ws.dow_weak,
        "total_sales": ws.total_sales,
    }

    weather_main = fetch_weather(args.city) if args.city else None

    inp = AdviceInput(
        city=args.city,
        weather_main=weather_main,
        weekday=pd.Timestamp.today().dayofweek,
        month=pd.Timestamp.today().month,
        location_type=os.environ.get("SHOP_LOCATION", "residential"),
        station_distance_min=int(os.environ.get("SHOP_STATION_MIN", "8")),
        daily_df=daily,
        menu_df=menu_df,
        kpis=kpis,
    )
    ad = generate_actionable_advice(inp)

    # LINE配信用本文（AI提案＋おすすめ＋テンプレ）
    ai_message = (
        "— 提案（AI）—\n"
        + "\n".join([f"・{a}" for a in ad.actions])
        + "\n\n— おすすめ —\n"
        + (
            "\n".join([f"・{m}" for m in ad.menu_suggestions])
            if ad.menu_suggestions
            else "・本日のおすすめをご用意しています"
        )
        + "\n\n"
        + ad.line_template
    )

    # PDFは常に生成（内部成果物）
    pdf_path = os.path.join(args.outdir, "weekly_report.pdf")
    build_pdf(ws, daily, pdf_path)

    # 週報テキスト（オーナー向け等）
    headline = (
        f"📊 AI週報\n期間：{ws.start_date.date()}〜{ws.end_date.date()}\n"
        f"総売上：¥{ws.total_sales:,.0f}\n日平均：¥{ws.avg_day_sales:,.0f}\n"
    )
    if ws.trend_ratio is not None:
        headline += f"前週比：{ws.trend_ratio*100:.1f}%\n"
    headline += "\n— 提案 —\n" + "\n".join([f"・{p}" for p in ws.proposals])

    recipients = read_lines(args.recipients)

    # === 週報テキスト送信（顧客向けは通常オフ） ===
    if not (args.only_coupon or args.no_weekly_message):
        print("[INFO] sending weekly headline...")
        if args.dry_run:
            print("[DRY] WEEKLY:", headline)
        else:
            ok, fail, mode = send_text_all_modes(headline, args.enable_broadcast, recipients)
            print(f"[SUMMARY] weekly: ok={ok} fail={fail} mode={mode}")

    # === 販促条件判定（天気×前週比×弱曜日） ===
    weather = fetch_weather(args.city) if args.city else None
    bad = is_bad_weather(weather)
    weak_today = (ws.dow_weak is not None and pd.Timestamp.today().dayofweek == ws.dow_weak)
    if ws.trend_ratio is None:
        trigger = weak_today or bad
    else:
        bad_sales = ws.trend_ratio is not None and ws.trend_ratio < args.threshold
        trigger = bad_sales or bad


    # === クールダウン確認 ===
    state_path = os.path.join(args.state_dir, "broadcast.json")
    if not passed_cooldown(state_path, args.cooldown_hours):
        print(f"[INFO] cooldown active ({args.cooldown_hours}h). skip campaign.")
        trigger = False

    # === クーポン/おすすめ送信（顧客向け） ===
    if (args.only_coupon or args.no_weekly_message) and trigger:
        campaign = ai_message  # ← AI提案を配信本文に設定
        if args.dry_run:
            print("[DRY] CAMPAIGN:", campaign)
        else:
            ok, fail, mode = send_text_all_modes(campaign, args.enable_broadcast, recipients)
            print(f"[SUMMARY] campaign: ok={ok} fail={fail} mode={mode}")
            if ok > 0:
                st = {"last_broadcast_at": now_iso(), "last_campaign_mode": mode}
                save_state(state_path, st)
    else:
        print("[INFO] campaign not triggered (conditions not met or weekly mode).")

if __name__ == "__main__":
    main()
