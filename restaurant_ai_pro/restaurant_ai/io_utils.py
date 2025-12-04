
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
