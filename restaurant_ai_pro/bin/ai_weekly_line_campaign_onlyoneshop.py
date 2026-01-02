#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI週報（PDF生成）＋ 顧客向け 自動販促（クーポン/おすすめ）
(B案) Cloud Run前提：.envファイルは読まない。環境変数/Secretだけで完結させる。

必要環境変数（共通/基盤）
- SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY
- OPENWEATHER_KEY（任意）

店舗ごとの想定（Cloud Run env / Secret）
- LINE_TOKEN_SHOPA / LINE_TOKEN_SHOPB / ...
- SHOP_LOCATION（任意）
- SHOP_STATION_MIN（任意）
- WEEKLY_VARIANT_ID（任意）
- WEEKLY_ENABLE_BROADCAST（任意）
"""

from __future__ import annotations

import os, json, time, argparse, datetime as dt, re, random
from dataclasses import dataclass
from typing import Optional, Iterable, List, Tuple, Dict, Any

import pandas as pd
import requests
import yaml

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


# ========= (B案) .env loader（無効化） =========
def load_env_file(path: str, *, override: bool = True) -> None:
    """
    B案：Cloud Runでは .env ファイル運用をしない
    → 互換のため関数は残すが「何もしない」
    """
    return


# ========= shops.yaml loader =========
def load_shops_yaml(path: str) -> list[dict]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"shops.yaml not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        obj = yaml.safe_load(f)
    if isinstance(obj, dict) and "shops" in obj:
        shops = obj["shops"]
    elif isinstance(obj, list):
        shops = obj
    else:
        shops = obj
    if not isinstance(shops, list):
        raise ValueError("shops.yaml format error: expected list or {shops: [...]}")

    # 互換：id/line_token_env が無い店は補完しておく
    for s in shops:
        sid = str(s.get("id") or "")
        if sid and not s.get("line_token_env"):
            # shopA -> LINE_TOKEN_SHOPA
            s["line_token_env"] = f"LINE_TOKEN_{sid.upper()}"
    return shops


def pick_shop(shops: list[dict], shop_id: str) -> dict:
    for s in shops:
        if str(s.get("id")) == str(shop_id):
            return s
    raise ValueError(f"shop_id not found in shops.yaml: {shop_id}")


def export_shop_cfg_to_env(shop: dict) -> None:
    """
    shops.yaml の値を環境変数へ注入（このスクリプト内だけで使う）
    ※既存環境変数を壊さない（既にセットされているものは優先）
    """
    mapping = {
        "style": "SHOP_STYLE",
        "tel": "SHOP_TEL",
        "address": "SHOP_ADDRESS",
        "hours": "SHOP_HOURS",
        "reserve_url": "SHOP_RESERVE_URL",
        "city": "SHOP_CITY",
    }
    for k, envk in mapping.items():
        val = shop.get(k)
        if val is None or val == "":
            continue
        os.environ.setdefault(envk, str(val))


# ========= Supabase REST =========
def sb_headers() -> dict:
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not supabase_url or not supabase_key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY が未設定です。")
    return {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

def sb_get(table: str, params: dict) -> list[dict]:
    supabase_url = os.environ.get("SUPABASE_URL")
    url = f"{supabase_url}/rest/v1/{table}"
    r = requests.get(url, headers=sb_headers(), params=params, timeout=20)
    if r.status_code >= 300:
        raise RuntimeError(f"Supabase GET failed: {r.status_code} {r.text}")
    return r.json()

def sb_upsert(table: str, rows: list[dict], on_conflict: str) -> None:
    if not rows:
        return
    supabase_url = os.environ.get("SUPABASE_URL")
    url = f"{supabase_url}/rest/v1/{table}?on_conflict={on_conflict}"
    r = requests.post(url, headers=sb_headers(), json=rows, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Supabase UPSERT failed: {r.status_code} {r.text}")

def make_week_key(ts: Optional[pd.Timestamp] = None) -> str:
    t = ts or pd.Timestamp.now(tz="Asia/Tokyo")
    iso = t.isocalendar()
    return f"{iso.year}W{int(iso.week):02d}"

def make_campaign_id(shop_id: str, campaign_type: str) -> str:
    wk = make_week_key()
    return f"{shop_id}_{wk}_weekly_{campaign_type}"

def fetch_weekly_recipients(shop_id: str) -> list[str]:
    rows = sb_get(
        "users",
        params={
            "select": "line_user_id",
            "shop_id": f"eq.{shop_id}",
            "segment": "in.(HOT,WARM)",
            "line_user_id": "not.is.null",
        },
    )
    return [r.get("line_user_id") for r in rows if r.get("line_user_id")]

def log_weekly_sends(
    *,
    shop_id: str,
    campaign_id: str,
    campaign_type: str,
    variant_id: str,
    user_ids: list[str],
    sent_at_iso: str,
) -> None:
    rows = []
    for uid in user_ids:
        if not uid:
            continue
        dedupe = f"{shop_id}:{uid}:{campaign_id}"
        rows.append({
            "shop_id": shop_id,
            "user_id": uid,
            "coupon_type": "weekly",
            "campaign_id": campaign_id,
            "campaign_type": campaign_type,
            "message_variant_id": variant_id,
            "sent_at": sent_at_iso,
            "dedupe_key": dedupe,
        })
    sb_upsert("coupon_send_logs", rows, on_conflict="dedupe_key")


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


# ========= PDF生成 =========
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


# ========= LINE送信 =========
def _resolve_line_token_env(shop: dict) -> str:
    """
    優先順位：
      1) shops.yaml の line_token_env
      2) shop_id から自動生成：LINE_TOKEN_{SHOPID}
    """
    env_key = shop.get("line_token_env")
    if env_key:
        return str(env_key)
    sid = str(shop.get("id") or "")
    if sid:
        return f"LINE_TOKEN_{sid.upper()}"
    return "LINE_CHANNEL_ACCESS_TOKEN"

def _get_line_token_from_shop_env(shop: dict) -> str:
    env_key = _resolve_line_token_env(shop)
    token = os.environ.get(env_key)
    if not token:
        raise RuntimeError(f"LINE token missing. env_key={env_key}")
    return token

def _line_headers(shop: dict) -> dict:
    token = _get_line_token_from_shop_env(shop)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def send_broadcast(shop: dict, messages: list[dict]) -> Tuple[int, int]:
    if os.environ.get("DISABLE_BROADCAST", "0") == "1":
        print("[INFO] BROADCAST disabled by env (DISABLE_BROADCAST=1)")
        return (0, 0)
    r = requests.post(LINE_BROADCAST_API, headers=_line_headers(shop), json={"messages": messages}, timeout=10)
    if r.status_code == 200:
        return (1, 0)
    print(f"[WARN] BROADCAST {r.status_code}: {r.text}")
    return (0, 1)

def send_multicast(shop: dict, uids: Iterable[str], messages: list[dict], chunk: int = 500) -> Tuple[int, int]:
    ok = fail = 0
    ids = [u.strip() for u in uids if u and u.strip()]
    headers = _line_headers(shop)

    for i in range(0, len(ids), chunk):
        part = ids[i:i+chunk]
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
    return (ok, fail)

def send_messages_all_modes(
    shop: dict,
    *,
    messages: list[dict],
    enable_broadcast: bool,
    recipients: list[str],
) -> Tuple[int, int, str]:
    if enable_broadcast and os.environ.get("DISABLE_BROADCAST", "0") != "1":
        ok, fail = send_broadcast(shop, messages)
        return (ok, fail, "broadcast")

    if recipients:
        ok, fail = send_multicast(shop, recipients, messages)
        return (ok, fail, "multicast/push")

    print("[INFO] no recipients and broadcast disabled; send skipped")
    return (0, 0, "none")


# ========= 状態（週次カウンタ） =========
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

def save_weekly_state(state_path: str, st: dict, *, last_mode: Optional[str] = None) -> None:
    st["last_broadcast_at"] = now_iso()
    if last_mode is not None:
        st["last_campaign_mode"] = last_mode
    save_state(state_path, st)


# ========= キャンペーンモード判定/文面 =========
def _strip_profit_info(menu_name: str) -> str:
    if not menu_name:
        return ""
    cleaned = re.sub(r"（粗利[^）]*）", "", str(menu_name)).strip()
    if cleaned in ("おすすめ", "おすすめメニュー", ""):
        return ""
    return cleaned

def _build_menu_reason(menu_name: str, weather_main: Optional[str] = None) -> str:
    name = menu_name or ""
    w = (weather_main or "").lower()
    if any(k in name for k in ["海鮮", "刺身", "サーモン", "マグロ"]):
        return "鮮度の高い海鮮の旨みをしっかり味わえる一品です。"
    if "カレー" in name or "スパイス" in name:
        if w in {"snow", "rain", "drizzle", "thunderstorm"}:
            return "スパイスの香りで身体があたたまる、寒い日にもぴったりのメニューです。"
        return "スパイスの風味をしっかり楽しめる、人気の定番メニューです。"
    if "チーズ" in name:
        return "濃厚なチーズのコクを楽しめる、満足感の高い一皿です。"
    if any(k in name for k in ["フライ", "からあげ", "唐揚げ", "天ぷら"]):
        return "揚げたての食感がクセになる、おつまみにもおすすめのメニューです。"
    if "サラダ" in name or "野菜" in name or "ベジ" in name:
        return "野菜をたっぷり使った、さっぱりとお召し上がりいただけるメニューです。"
    if any(k in name for k in ["プリン", "ケーキ", "パフェ", "アイス"]):
        return "食後のひと休みにぴったりなデザートメニューです。"
    return "素材の味わいを生かした、スタッフおすすめの一品です。"

def decide_campaign_mode(ws: WeeklySummary, weather_main: Optional[str]) -> str:
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

EMOJI_DICT: Dict[str, list[str]] = {
    "headline": ["📣", "📢", "📌"],
    "value": ["🉐", "🔥", "✨"],
    "food": ["🍺", "🍛", "🍖", "🍽️"],
    "closing": ["🙇‍♂️", "🙏", "😊"],
}
STYLE_CONFIG: Dict[str, Dict[str, Any]] = {
    "high_tension": {"tone": "casual", "use_strong_value": True},
    "calm": {"tone": "polite", "use_strong_value": False},
    "premium": {"tone": "premium", "use_strong_value": False},
    "family": {"tone": "soft", "use_strong_value": True},
}
def _pick_emoji(category: str) -> str:
    items = EMOJI_DICT.get(category) or []
    return random.choice(items) if items else ""

def build_reserve_flex(image_url: str, reserve_url: str) -> dict:
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
                "action": {"type": "uri", "label": "予約はこちら", "uri": reserve_url},
            },
        },
    }

def build_ai_campaign_message(
    ws: WeeklySummary,
    ad,
    weather_main: Optional[str],
    campaign_mode: str,
    campaign_type: str,
    menu_df: Optional[pd.DataFrame] = None,
) -> str:
    style_key = os.environ.get("SHOP_STYLE", "high_tension")
    style_cfg = STYLE_CONFIG.get(style_key, STYLE_CONFIG["high_tension"])
    tone = style_cfg["tone"]

    period = f"{ws.start_date.date()}〜{ws.end_date.date()}"
    headline_emoji = _pick_emoji("headline")
    value_emoji = _pick_emoji("value") if style_cfg.get("use_strong_value") else ""

    if campaign_type == "regular":
        if tone in ("premium", "calm"):
            head_title = f"{headline_emoji} 週末のおすすめ（AIセレクト）"
            head_sub = f"今週（{period}）の営業状況から、AIがおすすめメニューをピックアップしました。"
        else:
            head_title = f"{headline_emoji} 週末限定のおすすめ情報{value_emoji}"
            head_sub = f"今週（{period}）のデータから、AIが“週末に特におすすめ”のメニューをまとめました。"
    else:
        if tone in ("premium", "calm"):
            head_title = f"{headline_emoji} 本日のおすすめメニューのご案内"
            head_sub = "本日の状況に合わせて、AIがおすすめメニューを選定しました。"
        else:
            head_title = f"{headline_emoji} 本日の特別なお知らせ（AI自動配信）{value_emoji}"
            head_sub = "本日の状況に合わせて、AIがおすすめメニューをご案内します。"

    def _lookup_menu_row(name_clean: str):
        if menu_df is None or "menu" not in menu_df.columns:
            return None
        hits = menu_df[menu_df["menu"].astype(str) == str(name_clean)]
        return hits.iloc[0] if not hits.empty else None

    menu_lines: List[str] = []
    raw_items = list(getattr(ad, "menu_suggestions", None) or [])[:3]

    for m in raw_items:
        name_clean = _strip_profit_info(str(m))
        if not name_clean:
            continue

        row = _lookup_menu_row(name_clean)
        feature = note = price_str = ""

        if row is not None:
            feature = str(row.get("item_feature", "")).strip()
            note = str(row.get("yield_note", "")).strip()
            price_val = row.get("price", "")
            try:
                if price_val != "":
                    price_str = f"{int(price_val)}円"
            except Exception:
                price_str = f"{price_val}円" if price_val not in (None, "") else ""

        title_line = f"・{name_clean}" + (f"（{price_str}）" if price_str else "")
        info_text = "｜".join([p for p in [feature, note] if p]) or _build_menu_reason(name_clean, weather_main)
        menu_lines.append(f"{title_line}\n　{info_text}")

    food_emoji = _pick_emoji("food")
    menu_block = f"【本日のおすすめ】{food_emoji}\n" + ("\n\n".join(menu_lines) if menu_lines else "・本日のおすすめをご用意しております。スタッフまでお尋ねください。")

    guide_block = (
        "🍽️ 本日のご案内\n"
        "本日限定のお得なセットやサービスもご用意しています。\n"
        "ご注文の際に「LINEを見た」とお伝えください。"
    )

    weather_comment = ""
    if weather_main:
        wm = weather_main.lower()
        if wm in {"rain", "snow", "drizzle", "thunderstorm"}:
            weather_comment = "今日はあいにくの空模様ですが、ゆっくりお食事をお楽しみいただけるようご用意しております。"
        else:
            weather_comment = "お出かけついでに、ぜひお立ち寄りください。"

    closing_line = f"本日もご来店を心よりお待ちしております{_pick_emoji('closing')}"

    blocks = [head_title, head_sub, "", menu_block, "", guide_block]
    if weather_comment:
        blocks += ["", weather_comment]
    blocks += ["", closing_line]

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

def build_owner_campaign_message(ws: WeeklySummary, ad, weather_main: Optional[str], campaign_mode: str, campaign_type: str) -> str:
    period = f"{ws.start_date.date()}〜{ws.end_date.date()}"
    head_title = "📊 AIキャンペーンレポート（週末定期）" if campaign_type == "regular" else "📊 AIキャンペーンレポート（臨時）"
    head_sub = f"今週（{period}）の実績と、施策サマリです。"

    kpi_lines = []
    if ws.trend_ratio is not None:
        kpi_lines.append(f"・先週比：{ws.trend_ratio * 100:.1f}%")
    kpi_lines.append(f"・総売上：¥{ws.total_sales:,.0f}")
    kpi_lines.append(f"・日平均：¥{ws.avg_day_sales:,.0f}")
    if ws.dow_weak is not None:
        jp = ["月","火","水","木","金","土","日"][ws.dow_weak]
        kpi_lines.append(f"・弱い曜日：{jp}曜日")
    if weather_main:
        wm = weather_main.lower()
        kpi_lines.append("・天候：雨/雪など" if wm in {"rain","snow","drizzle","thunderstorm"} else "・天候：良好")

    kpi_block = "【状況】\n" + "\n".join(kpi_lines)
    actions_block = "【アクション】\n" + "\n".join(f"・{a}" for a in (getattr(ad, "actions", None) or ["通常運用で問題なし"]))
    menu_block = "【おすすめ候補】\n" + "\n".join(f"・{m}" for m in (getattr(ad, "menu_suggestions", None) or ["候補なし"])[:3])

    if campaign_mode == "recovery":
        mode_block = "📉 回復モード\n・平日/悪天候の来店促進を優先\n・限定感の訴求を強める"
    elif campaign_mode == "boost":
        mode_block = "📈 テコ入れモード\n・弱曜日向けの限定訴求\n・常連向けフォロー"
    else:
        mode_block = "⭐ ブランド/客単価モード\n・映え/人気メニュー推し\n・トッピング/セット提案"

    return f"{head_title}\n{head_sub}\n\n{kpi_block}\n\n{actions_block}\n\n{menu_block}\n\n{mode_block}"


# ========= 実行（店舗単位） =========
def run_for_shop(shop: dict, *, args) -> None:
    # 1) (B案) env_fileは読まない（関数自体がno-op）
    env_file = shop.get("env_file")
    if env_file:
        load_env_file(env_file, override=True)

    # 2) shops.yaml の情報を env に注入（文面用）
    export_shop_cfg_to_env(shop)

    # 3) 入力パス確定（引数優先→shop設定）
    daily_csv = args.daily_csv or shop.get("daily_csv")
    outdir = args.outdir or shop.get("outdir") or f"OUTPUT/{shop.get('id','shop')}"
    city = args.city or shop.get("city") or os.environ.get("SHOP_CITY")

    if not daily_csv:
        raise ValueError("daily_csv is required (args.daily_csv or shop.daily_csv)")
    ensure_dir(outdir)

    daily = load_daily(daily_csv)
    ws = analyze_week(daily)

    menu_path = args.menu_csv or shop.get("menu_csv") or os.path.join(os.path.dirname(daily_csv), "menu.csv")
    menu_df = pd.read_csv(menu_path) if (menu_path and os.path.exists(menu_path)) else None

    weather_main = fetch_weather(city) if city else None

    kpis = {
        "trend_ratio": ws.trend_ratio,
        "repeat_rate_avg": ws.repeat_rate_avg,
        "dow_weak": ws.dow_weak,
        "total_sales": ws.total_sales,
    }

    inp = AdviceInput(
        city=city,
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

    pdf_path = os.path.join(outdir, "weekly_report.pdf")
    build_pdf(ws, daily, pdf_path)

    # 店長向け（任意）
    headline = (
        f"📊 AI週報\n期間：{ws.start_date.date()}〜{ws.end_date.date()}\n"
        f"総売上：¥{ws.total_sales:,.0f}\n日平均：¥{ws.avg_day_sales:,.0f}\n"
    )
    if ws.trend_ratio is not None:
        headline += f"前週比：{ws.trend_ratio*100:.1f}%\n"
    headline += "\n— 提案 —\n" + "\n".join([f"・{p}" for p in ws.proposals])

    owner_recipients = read_lines(args.recipients)

    if args.dry_run:
        print(f"[DRY] shop_id={shop.get('id')} pdf={pdf_path}")
        print("[DRY] WEEKLY_HEADLINE:", headline)

    if not (args.only_coupon or args.no_weekly_message):
        if owner_recipients:
            if args.dry_run:
                print("[DRY] send owner headline ->", len(owner_recipients))
            else:
                ok_o, fail_o, mode_o = send_messages_all_modes(
                    shop,
                    messages=[{"type": "text", "text": headline}],
                    enable_broadcast=False,
                    recipients=owner_recipients,
                )
                print(f"[SUMMARY] weekly(owner): ok={ok_o} fail={fail_o} mode={mode_o}")
        else:
            print("[INFO] owner recipients not set; skip owner headline")

    # 顧客向けは only_coupon/no_weekly_message の時だけ
    if not (args.only_coupon or args.no_weekly_message):
        return

    shop_id = str(shop.get("id") or os.environ.get("SHOP_ID") or "shopA")
    variant_id = os.environ.get("WEEKLY_VARIANT_ID", "A")

    weekly_recipients = fetch_weekly_recipients(shop_id)
    print(f"[INFO] weekly recipients(HOT/WARM): {len(weekly_recipients)} shop_id={shop_id}")

    state_dir = args.state_dir or ".state"
    state_path = os.path.join(state_dir, f"weekly_{shop_id}.json")
    st = load_weekly_state(state_path)

    cooldown_hours = int(args.cooldown_hours or shop.get("cooldown_hours") or 24)
    if not passed_cooldown(state_path, cooldown_hours):
        print(f"[INFO] cooldown active ({cooldown_hours}h). skip campaign.")
        return

    regular_sent = int(st.get("regular_sent_count", 0))
    extra_sent   = int(st.get("extra_sent_count", 0))

    today = pd.Timestamp.today()
    weekday = today.dayofweek

    is_weekend_regular = (weekday == 4)

    threshold = float(args.threshold if args.threshold is not None else shop.get("threshold", 0.95))
    weak_today   = (ws.dow_weak is not None and weekday == ws.dow_weak)
    bad_weather  = is_bad_weather(weather_main)
    bad_sales    = (ws.trend_ratio is not None and ws.trend_ratio < threshold)
    is_extra_condition = (bad_weather or weak_today or bad_sales)

    campaign_type: Optional[str] = None
    if is_weekend_regular and regular_sent < 1:
        campaign_type = "regular"
    elif is_extra_condition and extra_sent < 1 and (regular_sent + extra_sent) < 2:
        campaign_type = "extra"

    if campaign_type is None:
        print("[INFO] campaign not triggered (weekly limits / conditions).")
        return

    campaign_id = make_campaign_id(shop_id, campaign_type)
    campaign_mode = decide_campaign_mode(ws, weather_main)

    ai_message = build_ai_campaign_message(ws, ad, weather_main, campaign_mode, campaign_type, menu_df=menu_df)
    owner_message = build_owner_campaign_message(ws, ad, weather_main, campaign_mode, campaign_type)

    weekly_enable_broadcast = os.environ.get("WEEKLY_ENABLE_BROADCAST", "0") == "1"

    if args.dry_run:
        print(f"[DRY] campaign_id={campaign_id} type={campaign_type} variant={variant_id}")
        print("[DRY] OWNER_CAMPAIGN:", owner_message)
        print("[DRY] CUSTOMER_CAMPAIGN:", ai_message)
        return

    # 1) 店長/オーナー（任意）
    if owner_recipients:
        ok_o, fail_o, mode_o = send_messages_all_modes(
            shop,
            messages=[{"type": "text", "text": owner_message}],
            enable_broadcast=False,
            recipients=owner_recipients,
        )
        print(f"[SUMMARY] owner_campaign({campaign_type}): ok={ok_o} fail={fail_o} mode={mode_o}")

    # 2) 顧客
    reserve_img = os.environ.get("SHOP_RESERVE_IMAGE_URL")
    reserve_url = os.environ.get("SHOP_RESERVE_URL") or (shop.get("reserve_url") or args.coupon_url)

    messages = [{"type": "text", "text": ai_message}]
    if reserve_img and reserve_url:
        messages.append(build_reserve_flex(reserve_img, reserve_url))

    ok, fail, mode = send_messages_all_modes(
        shop,
        messages=messages,
        enable_broadcast=weekly_enable_broadcast,
        recipients=weekly_recipients,
    )
    print(f"[SUMMARY] weekly_campaign({campaign_type}): ok={ok} fail={fail} mode={mode} campaign_id={campaign_id}")

    # 3) Supabase ログ（冪等）
    sent_at_iso = now_iso()
    try:
        log_weekly_sends(
            shop_id=shop_id,
            campaign_id=campaign_id,
            campaign_type=campaign_type,
            variant_id=variant_id,
            user_ids=weekly_recipients,
            sent_at_iso=sent_at_iso,
        )
        print("[INFO] logged weekly sends to Supabase")
    except Exception as e:
        print("[WARN] failed to log weekly sends to Supabase:", str(e))

    # 4) state 更新
    if ok > 0:
        if campaign_type == "regular":
            st["regular_sent_count"] = regular_sent + 1
        else:
            st["extra_sent_count"] = extra_sent + 1
        save_weekly_state(state_path, st, last_mode=campaign_type)


def main():
    ap = argparse.ArgumentParser()

    # Cloud Run前提：repo内のデフォルトに合わせる
    ap.add_argument("--shops_yaml", default="restaurant_ai_pro/config/shops.yaml", help="shops.yaml path")
    ap.add_argument("--shop_id", default=None, help="target shop id (e.g., shopA). if omitted, run all shops")

    ap.add_argument("--daily_csv", default=None)
    ap.add_argument("--outdir",    default=None)
    ap.add_argument("--menu_csv",  default=None)
    ap.add_argument("--city",      default=None)

    ap.add_argument("--recipients", default=None, help="店長向けテスト配信（userId行区切り）")
    ap.add_argument("--coupon_url", default="https://lin.ee/coupon")

    ap.add_argument("--threshold", type=float, default=None, help="前週比の閾値（未指定なら shops.yaml の threshold or 0.95）")
    ap.add_argument("--only_coupon", action="store_true", help="顧客向けモード：販促のみ（週報テキストは送らない）")
    ap.add_argument("--no_weekly_message", action="store_true", help="週報テキストを抑止（PDFは生成）")

    ap.add_argument("--cooldown_hours", type=int, default=None, help="最低何時間は再配信しないか（未指定なら shops.yaml cooldown_hours or 24）")
    ap.add_argument("--state_dir", default=".state", help="配信状態の保存先")
    ap.add_argument("--dry_run", action="store_true", help="送信せずログのみ")
    args = ap.parse_args()

    shops = load_shops_yaml(args.shops_yaml)
    targets = [pick_shop(shops, args.shop_id)] if args.shop_id else shops

    for shop in targets:
        print("=" * 80)
        print(f"[RUN] shop_id={shop.get('id')} name={shop.get('name')}")
        run_for_shop(shop, args=args)

if __name__ == "__main__":
    main()
