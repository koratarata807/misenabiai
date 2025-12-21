# restaurant_ai_pro/bin/server.py
import os
import requests
from fastapi import FastAPI, Header, HTTPException, Depends

import importlib
import hashlib

# ★A：必ず restaurant_ai_pro 経由で読む（bin衝突を根絶）
daily_mod = importlib.import_module("restaurant_ai_pro.bin.daily_coupon_job")
run_daily = getattr(daily_mod, "main")

# ===== 起動時に「実際に読んだファイル」を確実に出す =====
try:
    p = getattr(daily_mod, "__file__", None)
    print(f"[RUNTIME] daily_mod={daily_mod.__name__}", flush=True)
    print(f"[RUNTIME] daily_file={p}", flush=True)
    if p and os.path.exists(p):
        b = open(p, "rb").read()
        print(f"[RUNTIME] daily_sha256={hashlib.sha256(b).hexdigest()}", flush=True)
except Exception as e:
    print(f"[RUNTIME][ERROR] fingerprint error: {e}", flush=True)

print("### BOOT: restaurant_ai_pro.bin.server loaded ###", flush=True)
print("### BOOT JOB_KEY env set? =>", "YES" if os.getenv("JOB_KEY") else "NO", "###", flush=True)
print("### BOOT SUPABASE_URL set? =>", "YES" if os.getenv("SUPABASE_URL") else "NO", "###", flush=True)
print(
    "### BOOT SUPABASE_SERVICE_ROLE_KEY set? =>",
    "YES" if os.getenv("SUPABASE_SERVICE_ROLE_KEY") else "NO",
    "###",
    flush=True,
)

app = FastAPI()
LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"


def require_job_key(x_job_key: str | None = Header(default=None, alias="x-job-key")):
    expected = os.getenv("JOB_KEY")
    print(f"### AUTH DEBUG got={x_job_key!r} expected={expected!r} ###", flush=True)
    if not expected:
        raise HTTPException(status_code=500, detail="JOB_KEY is not set")
    if x_job_key != expected:
        raise HTTPException(status_code=401, detail=f"unauthorized got={x_job_key!r}")
    return True


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/jobs/daily-coupon")
def daily_coupon(_auth=Depends(require_job_key)):
    run_daily()
    return {"ok": True}


@app.post("/jobs/test-line")
def test_line(_auth=Depends(require_job_key)):
    token = os.getenv("LINE_TOKEN_SHOPA")
    user_id = os.getenv("TEST_LINE_USER_ID")

    if not token:
        raise HTTPException(status_code=500, detail="LINE_TOKEN_SHOPA is not set")
    if not user_id:
        raise HTTPException(status_code=500, detail="TEST_LINE_USER_ID is not set")

    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    payload = {"to": user_id, "messages": [{"type": "text", "text": "✅ Cloud Run からのテスト送信です"}]}

    r = requests.post(LINE_PUSH_ENDPOINT, json=payload, headers=headers, timeout=10)
    if r.status_code != 200:
        raise HTTPException(status_code=500, detail=f"LINE push failed: {r.text}")

    return {"ok": True}
