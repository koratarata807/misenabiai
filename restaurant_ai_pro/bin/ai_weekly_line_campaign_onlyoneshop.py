#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI週報（PDF生成）＋ 顧客向け 自動販促（クーポン/おすすめ）

- 週報テキストは --only_coupon で抑止（顧客向け運用）
- LINE送信は Broadcast優先 → 失敗時 Multicast → 最後に Push へフォールバック
- 誤配信防止：
    - cooldown_hours（最低インターバル）
    - 週次上限：regular(週末定期) 1回 + extra(悪天候/弱曜日/売上悪化) 1回 → 週最大2通
- 送信サマリ（件数/失敗）を標準出力に記録

必要環境変数
- LINE_CHANNEL_ACCESS_TOKEN（必須）
- OPENWEATHER_KEY（任意：天気連動を使う場合）
- MPLBACKEND=Agg（PDF生成時のGUI省略、ランナーが設定）
"""

from __future__ import annotations
import os, json, time, argparse, datetime as dt
from dataclasses import dataclass
from typing import Optional, Iterable, List, Tuple
import re
# ========= ENV LOADER =========
from dotenv import load_dotenv
import glob
from typing import Dict, Any
import pandas as pd
import requests
import random

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
    if path:
        os.makedirs(path, exist_ok=True)

def read_lines(path: Optional[str]) -> list[str]:
    if not path or not os.path.exists(path):
        return []
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
    for c in ["sales", "guests", "new_customers", "repeat_rate"]:
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
    this_w = daily[(daily["date"] >= start) & (daily["date"] <= end)].copy()
    prev_w = daily[(daily["date"] >= start - pd.Timedelta(days=7)) & (daily["date"] < start)].copy()

    total_sales   = float(this_w["sales"].sum())
    avg_day_sales = float(this_w.groupby(this_w["date"].dt.date)["sales"].sum().mean())

    total_guests = float(this_w["guests"].sum()) if "guests" in this_w.columns else None

    rr = None
    if "repeat_rate" in this_w.columns:
        s = this_w["repeat_rate"].dropna()
        s = s[(s >= 0) & (s <= 1)]
        if len(s):
            rr = float(s.mean())

    dow_sales = this_w.groupby("dow")["sales"].mean() if len(this_w) else pd.Series(dtype=float)
    dow_weak  = int(dow_sales.idxmin()) if len(dow_sales) else None

    trend_ratio = None
    if len(prev_w) > 0 and prev_w["sales"].sum() > 0:
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
    if JP is None:
        return
    if ax.get_title():
        ax.set_title(ax.get_title(), fontproperties=JP)
    if ax.get_xlabel():
        ax.set_xlabel(ax.get_xlabel(), fontproperties=JP)
    if ax.get_ylabel():
        ax.set_ylabel(ax.get_ylabel(), fontproperties=JP)
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
            fig.text(0.10, y, ln, fontproperties=JP, fontsize=12)
            y -= 0.04

        ax = fig.add_axes([0.10, 0.10, 0.80, 0.30])
        last14 = daily[daily["date"] >= summary.end_date - pd.Timedelta(days=13)]
        ax.plot(last14["date"], last14["sales"], marker="o")
        ax.set_title("直近14日 売上推移")
        ax.set_xlabel("日付")
        ax.set_ylabel("売上（円）")
        _apply_jp(ax)
        fig.autofmt_xdate()
        pdf.savefig(fig)
        plt.close(fig)

# ========= 天気 =========
def fetch_weather(city: Optional[str]) -> Optional[str]:
    key = os.environ.get("OPENWEATHER_KEY")
    if not key or not city:
        return None
    try:
        r = requests.get(OPENWEATHER_URL, params={"q": city, "appid": key}, timeout=8)
        if r.status_code != 200:
            return None
        return (r.json().get("weather") or [{}])[0].get("main")
    except Exception:
        return None

def is_bad_weather(main: Optional[str]) -> bool:
    if not main:
        return False
    return main.lower() in {"rain", "snow", "drizzle", "thunderstorm"}

# ========= LINE 送信 =========
def _line_headers() -> dict:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("環境変数 LINE_CHANNEL_ACCESS_TOKEN が未設定です。")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def send_broadcast(text: str) -> Tuple[int, int]:
    """return: (ok, fail)"""
    if os.environ.get("DISABLE_BROADCAST", "0") == "1":
        print("[INFO] BROADCAST disabled by env (DISABLE_BROADCAST=1)")
        return (0, 0)
    headers = _line_headers()
    payload = {"messages": [{"type": "text", "text": text}]}
    r = requests.post(LINE_BROADCAST_API, headers=headers, json=payload, timeout=10)
    if r.status_code == 200:
        return (1, 0)
    print(f"[WARN] BROADCAST {r.status_code}: {r.text}")
    return (0, 1)

def send_multicast(uids: Iterable[str], text: str, chunk: int = 500) -> Tuple[int, int]:
    headers = _line_headers()
    ok = fail = 0
    ids = [u.strip() for u in uids if u and u.strip()]
    for i in range(0, len(ids), chunk):
        part = ids[i:i+chunk]
        payload = {"to": part, "messages": [{"type": "text", "text": text}]}
        r = requests.post(LINE_MULTICAST_API, headers=headers, json=payload, timeout=10)
        if r.status_code == 200:
            ok += len(part)
        else:
            print(f"[WARN] MULTICAST {r.status_code}: {r.text} (fallback to push)")
            for uid in part:
                pr = requests.post(
                    LINE_PUSH_API,
                    headers=headers,
                    json={"to": uid, "messages": [{"type": "text", "text": text}]},
                    timeout=10,
                )
                if pr.status_code == 200:
                    ok += 1
                else:
                    fail += 1
                    time.sleep(0.2)
    return (ok, fail)

def send_text_all_modes(text: str,
                        enable_broadcast: bool,
                        recipients: list[str]) -> Tuple[int, int, str]:
    """
    送信方針:
      1) enable_broadcast==True かつ DISABLE_BROADCAST!=1 → broadcast
      2) recipients があれば multicast（失敗は push フォールバック）
    戻り: (ok, fail, mode)  mode in {"broadcast","multicast/push","none"}
    """
    if enable_broadcast and os.environ.get("DISABLE_BROADCAST", "0") != "1":
        ok, fail = send_broadcast(text)
        return (ok, fail, "broadcast")
    if recipients:
        ok, fail = send_multicast(recipients, text)
        return (ok, fail, "multicast/push")
    print("[INFO] no recipients and broadcast disabled; send skipped")
    return (0, 0, "none")

def send_messages_all_modes(messages: list[dict],
                            enable_broadcast: bool,
                            recipients: list[str]) -> Tuple[int, int, str]:
    """
    messages に LINE メッセージ配列（text, flex など）を渡して送信する版。
    """
    headers = _line_headers()

    # 1) Broadcast 優先
    if enable_broadcast and os.environ.get("DISABLE_BROADCAST", "0") != "1":
        payload = {"messages": messages}
        r = requests.post(LINE_BROADCAST_API, headers=headers, json=payload, timeout=10)
        if r.status_code == 200:
            return (1, 0, "broadcast")
        print(f"[WARN] BROADCAST {r.status_code}: {r.text}")

    # 2) recipients があれば multicast → 失敗は push フォールバック
    ids = [u.strip() for u in recipients if u and u.strip()]
    if ids:
        ok = fail = 0
        for i in range(0, len(ids), 500):
            part = ids[i:i+500]
            payload = {"to": part, "messages": messages}
            r = requests.post(LINE_MULTICAST_API, headers=headers, json=payload, timeout=10)
            if r.status_code == 200:
                ok += len(part)
            else:
                print(f"[WARN] MULTICAST {r.status_code}: {r.text} (fallback to push)")
                for uid in part:
                    pr = requests.post(
                        LINE_PUSH_API,
                        headers=headers,
                        json={"to": uid, "messages": messages},
                        timeout=10,
                    )
                    if pr.status_code == 200:
                        ok += 1
                    else:
                        fail += 1
                        time.sleep(0.2)
        return (ok, fail, "multicast/push")

    print("[INFO] no recipients and broadcast disabled; send skipped")
    return (0, 0, "none")

# ========= 状態（クールダウン & 週次カウンタ） =========
def load_state(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(path: str, obj: dict) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def passed_cooldown(state_path: str, hours: int) -> bool:
    if hours <= 0:
        return True
    st = load_state(state_path)
    ts = st.get("last_broadcast_at")
    if not ts:
        return True
    try:
        last = dt.datetime.fromisoformat(ts)
    except Exception:
        return True
    delta = dt.datetime.now().astimezone() - last.astimezone()
    return (delta.total_seconds() >= hours * 3600)

def load_weekly_state(state_path: str) -> dict:
    """
    週単位の配信回数を管理するための状態を読み込む。
    週が変わっていたらカウンタをリセットして返す。
    """
    st = load_state(state_path)
    today = pd.Timestamp.today()
    current_week = today.isocalendar()[1]

    saved_week = st.get("week_number")
    if saved_week != current_week:
        st["week_number"] = current_week
        st["regular_sent_count"] = 0
        st["extra_sent_count"] = 0
    else:
        st.setdefault("regular_sent_count", 0)
        st.setdefault("extra_sent_count", 0)
    return st

def save_weekly_state(state_path: str,
                      st: dict,
                      *,
                      last_mode: Optional[str] = None) -> None:
    """
    配信後に last_broadcast_at / last_campaign_mode / カウンタ を更新して保存。
    last_mode: "regular" or "extra" など
    """
    st["last_broadcast_at"] = now_iso()
    if last_mode is not None:
        st["last_campaign_mode"] = last_mode
    save_state(state_path, st)

# ========= キャンペーンモード判定 =========
def _strip_profit_info(menu_name: str) -> str:
    """
    顧客向け文面では「（粗利◯%）」などの内部情報を削る。
    ついでに「おすすめ」だけのダミー名称は空文字扱いにして弾く。
    """
    if not menu_name:
        return ""

    # 「（粗利...）」みたいな全角カッコ部分を削除
    cleaned = re.sub(r"（粗利[^）]*）", "", str(menu_name))
    cleaned = cleaned.strip()

    # ダミー名は出さない
    if cleaned in ("おすすめ", "おすすめメニュー", ""):
        return ""

    return cleaned

def _build_menu_reason(menu_name: str,
                       weather_main: Optional[str] = None) -> str:
    """
    メニュー名と天気から、軽いおすすめ理由を生成。
    内容は汎用テンプレ＋簡単なキーワード判定。
    """
    name = menu_name or ""
    w = (weather_main or "").lower()

    # 海鮮系
    if "海鮮" in name or "刺身" in name or "サーモン" in name or "マグロ" in name:
        return "鮮度の高い海鮮の旨みをしっかり味わえる一品です。"

    # カレー・スパイス系
    if "カレー" in name or "スパイス" in name:
        if w in {"snow", "rain", "drizzle", "thunderstorm"}:
            return "スパイスの香りで身体があたたまる、寒い日にもぴったりのメニューです。"
        else:
            return "スパイスの風味をしっかり楽しめる、人気の定番メニューです。"

    # チーズ系
    if "チーズ" in name:
        return "濃厚なチーズのコクを楽しめる、満足感の高い一皿です。"

    # 揚げ物系
    if any(k in name for k in ["フライ", "からあげ", "唐揚げ", "天ぷら"]):
        return "揚げたての食感がクセになる、おつまみにもおすすめのメニューです。"

    # サラダ・野菜系
    if "サラダ" in name or "野菜" in name or "ベジ" in name:
        return "野菜をたっぷり使った、さっぱりとお召し上がりいただけるメニューです。"

    # デザート系
    if any(k in name for k in ["プリン", "ケーキ", "パフェ", "アイス"]):
        return "食後のひと休みにぴったりなデザートメニューです。"

    # デフォルト
    return "素材の味わいを生かした、スタッフおすすめの一品です。"

def decide_campaign_mode(ws: WeeklySummary,
                         weather_main: Optional[str]) -> str:
    """
    売上トレンド × 天気 × 弱曜日 からキャンペーンモードを決定
    return: "recovery" | "boost" | "brand"
    """
    bad_weather = is_bad_weather(weather_main)
    trend = ws.trend_ratio

    mode = "brand"
    if trend is None:
        if bad_weather:
            mode = "recovery"
        elif ws.dow_weak is not None and pd.Timestamp.today().dayofweek == ws.dow_weak:
            mode = "boost"
    else:
        if trend < 0.9:
            mode = "recovery"
        elif trend < 1.0:
            mode = "boost"
        else:
            mode = "brand"

    if bad_weather and mode == "brand":
        mode = "boost"
    elif bad_weather and mode == "boost":
        mode = "recovery"
    return mode

# ========= LINE文面スタイル / 絵文字設定 =========
from typing import Dict, Any

EMOJI_DICT: Dict[str, list[str]] = {
    "headline": ["📣", "📢", "📌"],
    "value": ["🉐", "🔥", "✨"],
    "food": ["🍺", "🍛", "🍖", "🍽️"],
    "notice": ["⚠️"],
    "closing": ["🙇‍♂️", "🙏", "😊"],
}

STYLE_CONFIG: Dict[str, Dict[str, Any]] = {
    # ハイテンション系（居酒屋・焼肉など）
    "high_tension": {
        "tone": "casual",
        "use_strong_value": True,
    },
    # 落ち着いた系（カフェ・ファミリー）
    "calm": {
        "tone": "polite",
        "use_strong_value": False,
    },
    # 上品・単価高め
    "premium": {
        "tone": "premium",
        "use_strong_value": False,
    },
    # やわらかめファミリー向け
    "family": {
        "tone": "soft",
        "use_strong_value": True,
    },
}

def _pick_emoji(category: str, count: int = 1) -> str:
    """カテゴリ別絵文字のランダム取得"""
    items = EMOJI_DICT.get(category) or []
    if not items:
        return ""
    if count <= 1:
        return random.choice(items)
    return "".join(random.sample(items, k=min(count, len(items))))

def build_reserve_flex(image_url: str, reserve_url: str) -> dict:
    """画像タップで予約ページに飛ばす Flex メッセージ"""
    return {
        "type": "flex",
        "altText": "ご予約はこちら",
        "contents": {
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": image_url,
                "size": "full",
                "aspectRatio": "20:13",
                "aspectMode": "cover",
                "action": {
                    "type": "uri",
                    "label": "予約はこちら",
                    "uri": reserve_url,
                },
            },
        },
    }


# ========= AIメッセージ生成（顧客向け） =========
def build_ai_campaign_message(ws: WeeklySummary,
                              ad,
                              weather_main: Optional[str],
                              campaign_mode: str,
                              campaign_type: str,
                              menu_df: Optional[pd.DataFrame] = None) -> str:
    """
    顧客向け LINE メッセージを構成する（公式LINEっぽく改良版）。
    - 粗利などの内部情報は削除
    - おすすめメニューは 1ブロックに集約
    - menu.csv の item_feature / yield_note / price を優先して表示
    - 店舗情報（TEL/予約URL/住所/営業時間）は環境変数からフッターに自動付与
        SHOP_TEL, SHOP_RESERVE_URL, SHOP_ADDRESS, SHOP_HOURS
    """

    # ===== 店舗スタイル（文体）判定 =====
    style_key = os.environ.get("SHOP_STYLE", "high_tension")
    style_cfg = STYLE_CONFIG.get(style_key, STYLE_CONFIG["high_tension"])
    tone = style_cfg["tone"]

    # ===== 見出し（定期 or 臨時） =====
    period = f"{ws.start_date.date()}〜{ws.end_date.date()}"
    headline_emoji = _pick_emoji("headline")
    value_emoji = _pick_emoji("value") if style_cfg.get("use_strong_value") else ""

    if campaign_type == "regular":
        # 週末定期
        if tone in ("premium", "calm"):
            head_title = f"{headline_emoji} 週末のおすすめ（AIセレクト）"
            head_sub = f"今週（{period}）の営業状況から、AIがおすすめメニューをピックアップしました。"
        else:
            head_title = f"{headline_emoji} 週末限定のおすすめ情報{value_emoji}"
            head_sub = f"今週（{period}）のデータから、AIが“週末に特におすすめ”のメニューをまとめました。"
    else:
        # extra（悪天候・弱曜日など臨時）
        if tone in ("premium", "calm"):
            head_title = f"{headline_emoji} 本日のおすすめメニューのご案内"
            head_sub = "本日の状況に合わせて、AIがおすすめメニューを選定しました。"
        else:
            head_title = f"{headline_emoji} 本日の特別なお知らせ（AI自動配信）{value_emoji}"
            head_sub = "本日の状況に合わせて、AIがおすすめメニューをご案内します。"

    # ===== おすすめメニュー生成 =====
    menu_lines: List[str] = []

    def _lookup_menu_row(name_clean: str):
        if menu_df is None or "menu" not in menu_df.columns:
            return None
        hits = menu_df[menu_df["menu"].astype(str) == str(name_clean)]
        if hits.empty:
            return None
        return hits.iloc[0]

    # 1. advisor からの候補を優先
    raw_items = getattr(ad, "menu_suggestions", None) or []
    raw_items = list(raw_items)[:3]

    for m in raw_items:
        name_clean = _strip_profit_info(str(m))
        if not name_clean:
            continue

        row = _lookup_menu_row(name_clean)
        feature = ""
        note = ""
        price_str = ""

        if row is not None:
            feature = str(row.get("item_feature", "")).strip()
            note = str(row.get("yield_note", "")).strip()
            price_val = row.get("price", "")
            try:
                if price_val != "":
                    price_str = f"{int(price_val)}円"
            except Exception:
                price_str = f"{price_val}円" if price_val not in (None, "") else ""
        else:
            price_str = ""
            feature = ""
            note = ""

        title_line = f"・{name_clean}"
        if price_str:
            title_line += f"（{price_str}）"

        info_parts = [p for p in [feature, note] if p]
        if info_parts:
            info_text = "｜".join(info_parts)
        else:
            info_text = _build_menu_reason(name_clean, weather_main)

        menu_lines.append(f"{title_line}\n　{info_text}")

    # 2. advisor が何も返さなかった場合 → menu.csv 先頭から3品
    if not menu_lines and menu_df is not None and "menu" in menu_df.columns:
        for _, row in menu_df.head(3).iterrows():
            name_clean = str(row.get("menu", "")).strip()
            if not name_clean:
                continue

            feature = str(row.get("item_feature", "")).strip()
            note = str(row.get("yield_note", "")).strip()
            price_val = row.get("price", "")
            price_str = ""
            try:
                if price_val != "":
                    price_str = f"{int(price_val)}円"
            except Exception:
                price_str = f"{price_val}円" if price_val not in (None, "") else ""

            title_line = f"・{name_clean}"
            if price_str:
                title_line += f"（{price_str}）"

            info_parts = [p for p in [feature, note] if p]
            if info_parts:
                info_text = "｜".join(info_parts)
            else:
                info_text = _build_menu_reason(name_clean, weather_main)

            menu_lines.append(f"{title_line}\n　{info_text}")

    # 3. それでもなければ最後の保険メッセージ
    if menu_lines:
        food_emoji = _pick_emoji("food")
        menu_block = f"【本日のおすすめ】{food_emoji}\n" + "\n\n".join(menu_lines)
    else:
        menu_block = (
            "【本日のおすすめ】\n"
            "・本日のおすすめメニューをご用意しております。スタッフまでお尋ねください。"
        )

    # ===== 本日のご案内ブロック =====
    guide_block = (
        "🍽️ 本日のご案内\n"
        "本日限定のお得なセットやサービスもご用意しています。\n"
        "ご注文の際に「LINEを見た」とお伝えください。"
    )

    # ===== 天気コメント =====
    weather_comment = ""
    if weather_main:
        wm = weather_main.lower()
        if wm in {"rain", "snow", "drizzle", "thunderstorm"}:
            weather_comment = "今日はあいにくの空模様ですが、ゆっくりお食事をお楽しみいただけるようご用意しております。"
        else:
            weather_comment = "お出かけついでに、ぜひお立ち寄りください。"

    closing_emoji = _pick_emoji("closing")
    closing_line = f"本日もご来店を心よりお待ちしております{closing_emoji}"

    blocks = [
        head_title,
        head_sub,
        "",
        menu_block,
        "",
        guide_block,
    ]
    if weather_comment:
        blocks += ["", weather_comment]
    blocks += ["", closing_line]

    # ===== フッター（お問い合わせ・予約導線） =====
    shop_tel = os.environ.get("SHOP_TEL")
    shop_reserve = os.environ.get("SHOP_RESERVE_URL")
    shop_address = os.environ.get("SHOP_ADDRESS")
    shop_hours = os.environ.get("SHOP_HOURS")

    footer_lines: List[str] = []
    if shop_tel or shop_reserve:
        footer_lines.append("📞 お問い合わせ・ご予約はこちらから↓")
        if shop_tel:
            footer_lines.append(f"☎️ {shop_tel}")
        if shop_reserve:
            footer_lines.append(f"✅ {shop_reserve}")

    if shop_address:
        footer_lines.append(f"📍 {shop_address}")
    if shop_hours:
        footer_lines.append(f"🕒 営業時間：{shop_hours}")

    if footer_lines:
        blocks += ["", "\n".join(footer_lines)]

    return "\n".join(blocks)
    return msg

# ========= AIメッセージ生成（店長/オーナー向け） =========
def build_owner_campaign_message(ws: WeeklySummary,
                                 ad,
                                 weather_main: Optional[str],
                                 campaign_mode: str,
                                 campaign_type: str) -> str:
    """
    店長・オーナー向けの内部レポート用メッセージ。
    KPI / AIアクション / モード説明を含める。
    """

    period = f"{ws.start_date.date()}〜{ws.end_date.date()}"
    if campaign_type == "regular":
        head_title = "📊 AIキャンペーンレポート（週末定期）"
        head_sub = f"今週（{period}）の実績と、週末向けのAI施策サマリです。"
    else:
        head_title = "📊 AIキャンペーンレポート（臨時）"
        head_sub = f"本日の状況を踏まえた、AIによる臨時キャンペーン発火です。"

    # KPIサマリ
    kpi_lines = []
    if ws.trend_ratio is not None:
        tr = ws.trend_ratio * 100
        kpi_lines.append(f"・先週比：{tr:.1f}%")
    kpi_lines.append(f"・総売上：¥{ws.total_sales:,.0f}")
    kpi_lines.append(f"・日平均：¥{ws.avg_day_sales:,.0f}")
    if ws.dow_weak is not None:
        jp = ["月","火","水","木","金","土","日"][ws.dow_weak]
        kpi_lines.append(f"・弱い曜日：{jp}曜日")
    if weather_main:
        wm = weather_main.lower()
        if wm in {"rain", "snow", "drizzle", "thunderstorm"}:
            kpi_lines.append("・天候：雨/雪など、来店ハードル高め")
        else:
            kpi_lines.append("・天候：来店しやすいコンディション")

    kpi_block = "【今週の状況】\n" + "\n".join(kpi_lines)

    # AIアクション提案
    if ad.actions:
        actions_block = "【今やるべきアクション（AI提案）】\n" + "\n".join(
            f"・{a}" for a in ad.actions
        )
    else:
        actions_block = "【今やるべきアクション（AI提案）】\n・本日は特別な打ち手は不要（通常運用で問題なし）"

    # おすすめメニュー（内部用に粗利もあれば載せる）
    if getattr(ad, "menu_suggestions", None):
        menu_items = ad.menu_suggestions[:3]
        menu_block = "【本日のおすすめメニュー候補】\n" + "\n".join(
            f"・{m}" for m in menu_items
        )
    else:
        menu_block = "【本日のおすすめメニュー候補】\n・候補なし（menu_suggestions未設定）"

    # モード別コメント
    if campaign_mode == "recovery":
        mode_title = "📉 売上回復モード"
        mode_comment = (
            "売上トレンドが弱含みのため、攻めの施策を優先しています。\n"
            "・平日/悪天候時の来店を促すクーポン訴求\n"
            "・「本日限定」「今だけ」を強調した文面\n"
        )
    elif campaign_mode == "boost":
        mode_title = "📈 テコ入れモード"
        mode_comment = (
            "大きくは崩れていませんが、もう一押しで改善が見込める状況です。\n"
            "・弱曜日向けの限定メニュー\n"
            "・常連向けの再来店フォローメッセージ\n"
        )
    else:
        mode_title = "⭐ ブランド・客単価アップモード"
        mode_comment = (
            "現状好調なため、ブランド力と客単価アップに寄せています。\n"
            "・写真映えするメニューの前面押し\n"
            "・人気メニューへのトッピング提案\n"
        )
    mode_block = f"{mode_title}\n{mode_comment}"

    msg = (
        f"{head_title}\n"
        f"{head_sub}\n\n"
        f"{kpi_block}\n\n"
        f"{actions_block}\n\n"
        f"{menu_block}\n\n"
        f"{mode_block}"
    )

    return msg

# ========= main =========
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily_csv", required=True)
    ap.add_argument("--outdir",    required=True)
    ap.add_argument("--recipients", default=None, help="テスト配信用（userId行区切り）")
    ap.add_argument("--city",       default=None)
    ap.add_argument("--coupon_url", default="https://lin.ee/coupon")
    ap.add_argument(
        "--menu_csv",
        default=None,
        help="menu.csv のパス（未指定なら daily_csv と同じフォルダ/menu.csv）",
    )
    ap.add_argument(
        "--threshold",
        type=float,
        default=0.95,
        help="前週比を下回ると販促発火（extra判定の目安）",
    )
    ap.add_argument("--enable_broadcast", action="store_true")
    ap.add_argument(
        "--only_coupon",
        action="store_true",
        help="顧客向けモード：週報テキストは送らない（クーポン/販促のみ）",
    )
    ap.add_argument(
        "--no_weekly_message",
        action="store_true",
        help="週報テキストを抑止（PDFは生成）",
    )
    ap.add_argument(
        "--cooldown_hours",
        type=int,
        default=24,
        help="最低何時間は再配信しないか（時間インターバル）",
    )
    ap.add_argument(
        "--state_dir",
        default=".state",
        help="配信状態（最終送信時刻等）の保存先",
    )
    ap.add_argument(
        "--dry_run",
        action="store_true",
        help="送信せずログのみ",
    )
    args = ap.parse_args()


    ensure_dir(args.outdir)
    daily = load_daily(args.daily_csv)
    ws = analyze_week(daily)

    # === AI提案生成（advisor連携） ===
    # 1) --menu_csv が指定されていればそれを優先
    # 2) なければ daily_csv と同じフォルダの menu.csv を探す
    if args.menu_csv:
        menu_path = args.menu_csv
    else:
        menu_path = os.path.join(os.path.dirname(args.daily_csv), "menu.csv")

    menu_df = pd.read_csv(menu_path) if os.path.exists(menu_path) else None

    weather_main = fetch_weather(args.city) if args.city else None

    kpis = {
        "trend_ratio": ws.trend_ratio,
        "repeat_rate_avg": ws.repeat_rate_avg,
        "dow_weak": ws.dow_weak,
        "total_sales": ws.total_sales,
    }

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

    # === PDFは常に生成（内部成果物） ===
    pdf_path = os.path.join(args.outdir, "weekly_report.pdf")
    build_pdf(ws, daily, pdf_path)

    # === 週報テキスト（オーナー向けなど） ===
    headline = (
        f"📊 AI週報\n期間：{ws.start_date.date()}〜{ws.end_date.date()}\n"
        f"総売上：¥{ws.total_sales:,.0f}\n日平均：¥{ws.avg_day_sales:,.0f}\n"
    )
    if ws.trend_ratio is not None:
        headline += f"前週比：{ws.trend_ratio*100:.1f}%\n"
    headline += "\n— 提案 —\n" + "\n".join([f"・{p}" for p in ws.proposals])

    recipients = read_lines(args.recipients)

    # === 週報テキスト送信（オーナー/店長向けのみ） ===
    if not (args.only_coupon or args.no_weekly_message):
        print("[INFO] sending weekly headline to owner/manager...")
        if args.dry_run:
            print("[DRY] WEEKLY:", headline)
        else:
            # 店長向けなので broadcast は使わず recipients のみ
            ok, fail, mode = send_text_all_modes(headline, False, recipients)
            print(f"[SUMMARY] weekly(owner): ok={ok} fail={fail} mode={mode}")

    # === 顧客向けキャンペーン配信（週1定期 + extra 週1まで） ===
    # 顧客向けモードは only_coupon / no_weekly_message いずれかで有効化する想定
    if not (args.only_coupon or args.no_weekly_message):
        print("[INFO] customer campaign mode is off (only_coupon/no_weekly_message not set).")
        return

    state_path = os.path.join(args.state_dir, "broadcast.json")
    st = load_weekly_state(state_path)

    # 時間インターバルによるクールダウン
    if not passed_cooldown(state_path, args.cooldown_hours):
        print(f"[INFO] cooldown active ({args.cooldown_hours}h). skip campaign.")
        return

    regular_sent = st.get("regular_sent_count", 0)
    extra_sent   = st.get("extra_sent_count", 0)

    today = pd.Timestamp.today()
    weekday = today.dayofweek  # 0=Mon ... 6=Sun

    # 週末定期配信（金曜18時にバッチが走る前提）
    is_weekend_regular = (weekday == 4)  # 金曜

    # 悪天候 or 弱曜日 or 売上トレンド悪化
    weak_today   = (ws.dow_weak is not None and weekday == ws.dow_weak)
    bad_weather  = is_bad_weather(weather_main)
    bad_sales    = (ws.trend_ratio is not None and ws.trend_ratio < args.threshold)

    # extraの発火条件
    is_extra_condition = (bad_weather or weak_today or bad_sales)
    
    #デバック用
    print(
    "[DEBUG] weekday=", weekday,
    "dow_weak=", ws.dow_weak,
    "trend_ratio=", ws.trend_ratio,
    "threshold=", args.threshold,
    "bad_sales=", bad_sales,
    "bad_weather=", bad_weather,
    "weak_today=", weak_today,
    "regular_sent=", regular_sent,
    "extra_sent=", extra_sent,
 )

    # 週最大 2通まで（regular 1, extra 1）
    campaign_type: Optional[str] = None

    # 1. 定期（regular）優先
    if is_weekend_regular and regular_sent < 1:
        campaign_type = "regular"
    # 2. 臨時（extra） 上限チェック
    elif is_extra_condition and extra_sent < 1 and (regular_sent + extra_sent) < 2:
        campaign_type = "extra"

    if campaign_type is None:
        print("[INFO] campaign not triggered (weekly limits / conditions).")
        return

    # === 実際のメッセージ生成 & 送信 ===
    campaign_mode = decide_campaign_mode(ws, weather_main)

    # 顧客向け（数字なし）
    ai_message = build_ai_campaign_message(
        ws,
        ad,
        weather_main,
        campaign_mode,
        campaign_type,
        menu_df=menu_df,
    )

    # 店長/オーナー向け（数字あり）
    owner_message = build_owner_campaign_message(
        ws,
        ad,
        weather_main,
        campaign_mode,
        campaign_type,
    )

    if args.dry_run:
        print(f"[DRY] OWNER_CAMPAIGN({campaign_type}):", owner_message)
        print(f"[DRY] CUSTOMER_CAMPAIGN({campaign_type}):", ai_message)
    else:
        # 1) 店長/オーナー向け：broadcast せず recipients のみに送信
        if recipients:
            ok_o, fail_o, mode_o = send_text_all_modes(owner_message, False, recipients)
            print(f"[SUMMARY] owner_campaign({campaign_type}): ok={ok_o} fail={fail_o} mode={mode_o}")
        else:
            print("[INFO] no owner recipients configured; skip owner campaign message.")

        # 2) 顧客向け：AI本文 + 予約画像を送信
        reserve_img = os.environ.get("SHOP_RESERVE_IMAGE_URL")
        reserve_url = os.environ.get("SHOP_RESERVE_URL") or args.coupon_url
        print(f"[DEBUG] reserve_img={reserve_img}")
        print(f"[DEBUG] reserve_url={reserve_url}")

        # ① まずテキスト
        messages = [{"type": "text", "text": ai_message}]

        # ② 画像URLと予約URLが両方あるときだけ、Flex画像を追加
        if reserve_img and reserve_url:
            messages.append(build_reserve_flex(reserve_img, reserve_url))

        ok, fail, mode = send_messages_all_modes(messages, args.enable_broadcast, recipients)
        print(f"[SUMMARY] campaign({campaign_type}): ok={ok} fail={fail} mode={mode}")


        if ok > 0:
            if campaign_type == "regular":
                st["regular_sent_count"] = regular_sent + 1
            else:
                st["extra_sent_count"] = extra_sent + 1
            save_weekly_state(state_path, st, last_mode=campaign_type)

if __name__ == "__main__":
    main()

