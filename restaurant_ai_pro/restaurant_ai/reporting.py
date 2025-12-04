
from __future__ import annotations

# =========================
# 日本語フォント設定（堅牢版）
# =========================
import os
import matplotlib
matplotlib.use("Agg")  # 非GUI
from matplotlib import rcParams, font_manager as fm

# フォント候補（WSL/Ubuntu と Windows を両対応）
CANDIDATES = [
    "/usr/share/fonts/opentype/ipaexfont/ipaexg.ttf",            # IPAex Gothic (推奨)
    "/usr/share/fonts/opentype/ipaexg.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",  # Noto CJK JP
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/mnt/c/Windows/Fonts/meiryo.ttc",       # Windowsフォント（WSLから参照可）
    "/mnt/c/Windows/Fonts/YuGothR.ttc",
    "/mnt/c/Windows/Fonts/msgothic.ttc",
]
FONT_PATH = next((p for p in CANDIDATES if os.path.exists(p)), None)

if FONT_PATH:
    JP = fm.FontProperties(fname=FONT_PATH)
    rcParams["font.family"] = JP.get_name()
else:
    JP = None  # 最低限のフォールバック（数字のみでも出るように）
    rcParams["font.family"] = "DejaVu Sans"

rcParams["axes.unicode_minus"] = False
rcParams["pdf.fonttype"] = 42   # TrueType埋め込み
rcParams["ps.fonttype"]  = 42
# =========================

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd
from .analytics import WeeklySummary


def _apply_jp_to_axes(ax):
    """軸・凡例のフォントをJPに統一"""
    if JP is None:
        return
    title = ax.get_title()
    if title:
        ax.set_title(title, fontproperties=JP)
    for lab in ax.get_xticklabels() + ax.get_yticklabels():
        lab.set_fontproperties(JP)
    xl = ax.get_xlabel()
    yl = ax.get_ylabel()
    if xl:
        ax.set_xlabel(xl, fontproperties=JP)
    if yl:
        ax.set_ylabel(yl, fontproperties=JP)
    leg = ax.get_legend()
    if leg:
        for t in leg.get_texts():
            t.set_fontproperties(JP)


def plot_hourly(df: pd.DataFrame, png_path: str) -> None:
    by_hour = df.groupby("hour")["sales"].sum().sort_index()
    fig = plt.figure()
    ax = fig.add_subplot(111)
    by_hour.plot(kind="bar", ax=ax)
    ax.set_title("時間帯別売上（合計）")
    ax.set_xlabel("時間帯")
    ax.set_ylabel("売上（円）")
    _apply_jp_to_axes(ax)
    fig.tight_layout()
    fig.savefig(png_path)
    plt.close(fig)


def build_pdf(summary: WeeklySummary, df: pd.DataFrame, pdf_path: str) -> None:
    by_hour = df.groupby("hour")["sales"].sum().sort_index()
    with PdfPages(pdf_path) as pdf:
        # Page 1: KPI
        fig1 = plt.figure(figsize=(8.27, 11.69))  # A4縦
        # 見出し
        fig1.text(0.10, 0.92, "週報（自動生成）",
                  fontproperties=JP, fontsize=18, weight="bold" if JP else None)
        # 本文
        y = 0.86
        lines = [
            f"総売上：¥{summary.total_sales:,}",
            f"日平均：¥{summary.avg_day_sales:,}",
        ]
        if summary.total_guests is not None:
            lines.append(f"総来客：{summary.total_guests}名")
        if summary.repeat_rate_avg is not None:
            lines.append(f"平均リピート率：{summary.repeat_rate_avg*100:.1f}%")
        lines += [
            f"最盛時間帯：{summary.best_hour}時（売上：¥{summary.best_hour_sales:,}）",
            "来週の提案：上位メニューの写真刷新／★3以下口コミは即返信／夜の客単価UP施策",
        ]
        for ln in lines:
            fig1.text(0.10, y, ln, fontproperties=JP, fontsize=12)
            y -= 0.04

        pdf.savefig(fig1)
        plt.close(fig1)

        # Page 2: 時間帯別バー
        fig2 = plt.figure(figsize=(8.27, 11.69))
        ax = fig2.add_subplot(111)
        by_hour.plot(kind="bar", ax=ax)
        ax.set_title("時間帯別売上（合計）")
        ax.set_xlabel("時間帯")
        ax.set_ylabel("売上（円）")
        _apply_jp_to_axes(ax)
        fig2.tight_layout()
        pdf.savefig(fig2)
        plt.close(fig2)
