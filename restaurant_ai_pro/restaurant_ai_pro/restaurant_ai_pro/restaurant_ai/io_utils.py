
import os, pandas as pd
from typing import Optional

def ensure_dir(path: str)->None:
    os.makedirs(path, exist_ok=True)

def read_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(f"CSV not found: {path}")
    try:
        df = pd.read_csv(path)
    except Exception as e:
        raise RuntimeError(f"Failed to read CSV {path}: {e}")
    if df.empty:
        raise ValueError(f"CSV has no rows: {path}")
    return df

def write_csv(df: pd.DataFrame, path: str) -> None:
    df.to_csv(path, index=False, encoding="utf-8")

# ========== LINE BROADCAST ==========

import os
import requests
from dotenv import load_dotenv

# shopA の設定を読み込む（必要に応じて動的切替にしてもOK）
load_dotenv("config/.env.shopA")

def broadcast_line(messages):
    """
    LINE公式アカウントの友だち全員にブロードキャスト配信する関数。

    Parameters
    ----------
    messages : list
        LINE Messaging API形式のメッセージ配列
    """
    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    data = {"messages": messages}

    resp = requests.post(
        "https://api.line.me/v2/bot/message/broadcast",
        headers=headers,
        json=data,
    )
    return resp
