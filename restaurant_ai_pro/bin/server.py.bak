import os
import requests
from fastapi import FastAPI, Header, HTTPException

from bin.daily_coupon_job import main as run_daily

app = FastAPI()

LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/jobs/daily-coupon")
def daily_coupon(x_job_key: str = Header(default="")):
    if x_job_key != os.getenv("JOB_KEY"):
        raise HTTPException(status_code=401, detail="unauthorized")
    run_daily()
    return {"ok": True}

# ===== 追加：テスト送信（確実に1通飛ばす）=====
@app.post("/jobs/test-line")
def test_line(x_job_key: str = Header(default="")):
    if x_job_key != os.getenv("JOB_KEY"):
        raise HTTPException(status_code=401, detail="unauthorized")

    token = os.getenv("LINE_TOKEN_SHOPA")
    user_id = os.getenv("TEST_LINE_USER_ID")

    if not token:
        raise HTTPException(status_code=500, detail="LINE_TOKEN_SHOPA is missing")
    if not user_id:
        raise HTTPException(status_code=500, detail="TEST_LINE_USER_ID is missing")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    payload = {
        "to": user_id,
        "messages": [
            {"type": "text", "text": "✅ Cloud Run からテスト送信できました（misenavi）"}
        ],
    }

    r = requests.post(LINE_PUSH_ENDPOINT, json=payload, headers=headers, timeout=10)
    if r.status_code != 200:
        raise HTTPException(status_code=500, detail=f"LINE push failed: {r.status_code} {r.text}")

    return {"ok": True}
