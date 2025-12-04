# restaurant_ai/advisor.py
from __future__ import annotations
import statistics as stats
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import pandas as pd

# ========= 入出力データ構造 =========
@dataclass
class AdviceInput:
    city: Optional[str]
    weather_main: Optional[str]           # "Rain"/"Snow"/"Clear" etc.
    weekday: int                          # 0=Mon ... 6=Sun
    month: int                            # 1..12
    location_type: str                    # "office"|"residential"|"tourism"|"campus" etc.
    station_distance_min: Optional[int]   # 駅からの徒歩分
    daily_df: pd.DataFrame                # 必須: ["date","sales",...]
    menu_df: Optional[pd.DataFrame]       # 任意: ["name","category","gross_margin","season_tags","is_signature",...]
    kpis: Dict[str, Any]                  # WeeklySummary由来KPI

@dataclass
class AdviceOutput:
    score: float
    key_signals: List[str]
    actions: List[str]
    menu_suggestions: List[str]
    line_template: str

# ========= 簡易辞書（季節・立地・天気ヒューリスティクス） =========
SEASON_MAP = {
    1:["hotpot","spicy","soup","oily"], 2:["hotpot","soup"],
    3:["spring","light"], 4:["spring","light"],
    5:["early_summer","cold_drink","spicy"],
    6:["rainy","warm","comfort","soup"],
    7:["summer","cold","icy","light"], 8:["summer","cold","icy","spicy"],
    9:["late_summer","mild"], 10:["autumn","mild","hot"],
    11:["autumn","hot","soup"], 12:["winter","hot","oily","soup"]
}

LOCATION_WEEK_BONUS = {
    "office":      {0:+0.10,1:+0.15,2:+0.10,3:+0.05,4:+0.20,5:-0.05,6:-0.10},
    "residential": {0:-0.05,1:-0.05,2:0.00,3:0.00,4:0.00,5:+0.15,6:+0.20},
    "tourism":     {0:+0.05,1:+0.05,2:+0.05,3:+0.05,4:+0.10,5:+0.15,6:+0.15},
    "campus":      {0:+0.05,1:+0.10,2:+0.10,3:+0.10,4:+0.05,5:-0.05,6:-0.10},
}

WEATHER_EFFECT = {
    "rain": +0.12, "snow": +0.10, "drizzle": +0.08, "thunderstorm": +0.10,
    "clear": 0.00, "clouds": +0.02,
}

# ========= ユーティリティ =========
def _norm(x, lo, hi) -> float:
    if x is None: return 0.0
    if hi == lo:  return 0.0
    return max(0.0, min(1.0, (float(x) - lo) / (hi - lo)))

def _to_num_series(df: Optional[pd.DataFrame], col: str, default: float = 0.0) -> pd.Series:
    """列が無い/None でも安全に Series を返す（NaN→default）。"""
    if df is None or df.empty or col not in df.columns:
        n = 0 if df is None else len(df)
        return pd.Series([default] * n, index=(None if df is None else df.index), dtype="float64")
    s = pd.to_numeric(df[col], errors="coerce")
    return s.fillna(default)

def _menu_pick(menu_df: Optional[pd.DataFrame], tags: List[str], topn: int = 3) -> List[str]:
    if menu_df is None or menu_df.empty: return []
    take = menu_df.copy()

    # 数値列を安全にSeries化
    take["gross_margin"] = _to_num_series(take, "gross_margin", 0.0)

    # 署名フラグ
    if "is_signature" not in take.columns:
        take["is_signature"] = False
    else:
        take["is_signature"] = take["is_signature"].fillna(False).astype(bool)

    # カテゴリ/名前
    if "category" not in take.columns: take["category"] = ""
    if "name"     not in take.columns: take["name"] = "おすすめ"

    tagset = set([t.lower() for t in tags or []])

    def score_row(r) -> float:
        score = float(r.get("gross_margin", 0.0))
        stags = set((str(r.get("season_tags") or "")).lower().split(","))
        score += 0.2 * len(stags.intersection(tagset))
        if r.get("is_signature", False): score += 0.15
        return score

    take["__score__"] = take.apply(score_row, axis=1)
    picks = take.sort_values("__score__", ascending=False).head(topn)

    outs: List[str] = []
    for _, r in picks.iterrows():
        n  = str(r.get("name", "おすすめ"))
        cat = str(r.get("category", "") or "")
        gm = float(r.get("gross_margin", 0.0))
        if cat:
            outs.append(f"{n}（{cat}／粗利{gm:.0%}）")
        else:
            outs.append(f"{n}（粗利{gm:.0%}）")
    return outs

def _summarize_menu(menu_df: Optional[pd.DataFrame]) -> dict:
    """メニュー全体の健全性サマリを返す（空/列欠落でも安全）。"""
    if menu_df is None or menu_df.empty:
        return {"n_items": 0, "avg_margin": 0.0, "signature_ratio": 0.0, "top_categories": []}

    take = menu_df.copy()
    take["gross_margin"] = _to_num_series(take, "gross_margin", 0.0)
    if "is_signature" not in take.columns:
        take["is_signature"] = False
    else:
        take["is_signature"] = take["is_signature"].fillna(False).astype(bool)
    if "category" not in take.columns:
        take["category"] = ""

    n_items = len(take)
    avg_margin = float(take["gross_margin"].mean()) if n_items else 0.0
    signature_ratio = float(take["is_signature"].mean()) if n_items else 0.0
    top_categories = take["category"].value_counts().head(3).index.tolist() if n_items else []

    return {
        "n_items": n_items,
        "avg_margin": avg_margin,
        "signature_ratio": signature_ratio,
        "top_categories": top_categories,
    }

# ========= メイン：行動提案生成 =========
def generate_actionable_advice(inp: AdviceInput) -> AdviceOutput:
    signals: List[str] = []
    score = 0.5

    # 前週比
    tr = inp.kpis.get("trend_ratio")
    if tr is not None:
        if tr < 0.90: score -= 0.10; signals.append(f"前週比{tr*100:.1f}%（低調）")
        elif tr < 0.95: score -= 0.05; signals.append(f"前週比{tr*100:.1f}%（やや弱）")
        else: score += 0.03; signals.append(f"前週比{tr*100:.1f}%（堅調）")

    # リピート率
    rr = inp.kpis.get("repeat_rate_avg")
    if rr is not None:
        if rr < 0.35: score -= 0.08; signals.append(f"リピ率{rr*100:.0f}%（要てこ入れ）")
        elif rr < 0.45: score -= 0.03; signals.append(f"リピ率{rr*100:.0f}%")
        else: score += 0.02; signals.append(f"リピ率{rr*100:.0f}%（良好）")

    # 立地×曜日
    loc = (inp.location_type or "residential").lower()
    loc_map = LOCATION_WEEK_BONUS.get(loc, LOCATION_WEEK_BONUS["residential"])
    bump = float(loc_map.get(inp.weekday, 0.0))
    score += bump
    signals.append(f"立地({loc})×曜日({inp.weekday})影響={bump:+.2f}")

    # 天気
    w = (inp.weather_main or "").lower()
    if "rain" in w: wkey = "rain"
    elif "snow" in w: wkey = "snow"
    elif "drizzle" in w: wkey = "drizzle"
    elif "thunder" in w: wkey = "thunderstorm"
    elif "cloud" in w: wkey = "clouds"
    elif "clear" in w: wkey = "clear"
    else: wkey = None

    if wkey:
        wbo = WEATHER_EFFECT[wkey]
        score += wbo
        signals.append(f"天気={w}（販促弾力{wbo:+.2f})")

    # 駅距離
    dist = inp.station_distance_min
    if dist is not None:
        d_bump = _norm(dist, 5, 15) * 0.08
        score += d_bump
        signals.append(f"駅距離{dist}分（動機付け{d_bump:+.2f}）")

    # 季節タグ → メニュー候補
    season_tags = SEASON_MAP.get(int(inp.month), [])
    menu_sugs = _menu_pick(inp.menu_df, season_tags, topn=3)
    menu_summary = _summarize_menu(inp.menu_df)

    # 施策（アクション）
    actions: List[str] = []
    weak_dow = inp.kpis.get("dow_weak")
    if weak_dow is not None and weak_dow == inp.weekday:
        actions.append("“本日限定”バリュー訴求（例：トッピング無料/ポイント2倍）をLINEで16時配信")
    if wkey in {"rain","snow","drizzle","thunderstorm"}:
        actions.append("悪天候バナー＋“18–21時 10%OFF”の緊急クーポンで来店ハードルを下げる")
    if rr is not None and rr < 0.40:
        actions.append("新規客フォロー：来店翌日お礼＋7日後再来店特典（自動配信）を有効化")
    if menu_summary["avg_margin"] < 0.5:
        actions.append("粗利の低いメニューを“セット化/トッピング提案”で客単価を底上げ")
    if not actions:
        actions.append("上位メニューの画像差し替え＋口コミ即レス（★3以下）でCVR維持")

    # LINEテンプレ
    head = "🍽️ 本日のご案内\n" if wkey not in {"rain","snow"} else "🌧️ 本日のご案内\n"
    menu_str = ("・" + "\n・".join(menu_sugs)) if menu_sugs else "・本日のおすすめをご用意しています"
    line_template = f"{head}{menu_str}\n本日限定のお得情報もご用意しています。ご来店お待ちしています！"

    # スコア整形
    score = max(0.0, min(1.0, score))

    return AdviceOutput(
        score=score,
        key_signals=signals,
        actions=actions,
        menu_suggestions=menu_sugs,
        line_template=line_template,
    )
