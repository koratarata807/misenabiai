# restaurant_ai_pro/bin/server.py
import os
import requests
import importlib
import hashlib
from fastapi import FastAPI, Header, HTTPException, Depends

app = FastAPI()
LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"

print("### BOOT: restaurant_ai_pro.bin.server loaded ###", flush=True)
print("### BOOT JOB_KEY env set? =>", "YES" if os.getenv("JOB_KEY") else "NO", "###", flush=True)
print("### BOOT SUPABASE_URL set? =>", "YES" if os.getenv("SUPABASE_URL") else "NO", "###", flush=True)
print(
    "### BOOT SUPABASE_SERVICE_ROLE_KEY set? =>",
    "YES" if os.getenv("SUPABASE_SERVICE_ROLE_KEY") else "NO",
    "###",
    flush=True,
)


def require_job_key(x_job_key: str | None = Header(default=None, alias="x-job-key")):
    expected = os.getenv("JOB_KEY")
    print(f"### AUTH DEBUG got={x_job_key!r} expected={expected!r} ###", flush=True)
    if not expected:
        raise HTTPException(status_code=500, detail="JOB_KEY is not set")
    if x_job_key != expected:
        raise HTTPException(status_code=401, detail=f"unauthorized got={x_job_key!r}")
    return True


def _load_daily():
    """
    ★重要：起動時に import しない（Cloud Run のPORT待受前に落ちるのを防ぐ）
    /jobs/daily-coupon を叩いたときにだけ import する。
    """
    daily_mod = importlib.import_module("restaurant_ai_pro.bin.daily_coupon_job")

    # ===== 実際に読んだファイルを確実に出す（デバッグ用）=====
    try:
        p = getattr(daily_mod, "__file__", None)
        print(f"[RUNTIME] daily_mod={daily_mod.__name__}", flush=True)
        print(f"[RUNTIME] daily_file={p}", flush=True)
        if p and os.path.exists(p):
            b = open(p, "rb").read()
            print(f"[RUNTIME] daily_sha256={hashlib.sha256(b).hexdigest()}", flush=True)
    except Exception as e:
        print(f"[RUNTIME][ERROR] fingerprint error: {e}", flush=True)

    run_daily = getattr(daily_mod, "main", None)
    if not callable(run_daily):
        raise RuntimeError("daily_coupon_job.main not found or not callable")

    return run_daily


@app.get("/health")
def health():
    # ★ここは絶対に軽く：Cloud Run の起動確認用
    return {"ok": True}


@app.post("/jobs/daily-coupon")
def daily_coupon(_auth=Depends(require_job_key)):
    try:
        run_daily = _load_daily()
        run_daily()
        return {"ok": True}
    except Exception as e:
        # Cloud Run 側ログに確実に残す
        print(f"[ERROR] daily_coupon failed: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


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
