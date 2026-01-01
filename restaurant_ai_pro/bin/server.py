# restaurant_ai_pro/bin/server.py
import os
import sys
import requests
import importlib
import hashlib
from contextlib import contextmanager
from fastapi import FastAPI, Header, HTTPException, Depends

app = FastAPI()
LINE_PUSH_ENDPOINT = "https://api.line.me/v2/bot/message/push"

# ===== BOOT LOG =====
print("### BOOT: restaurant_ai_pro.bin.server loaded ###", flush=True)
print("### BOOT JOB_KEY set? =>", "YES" if os.getenv("JOB_KEY") else "NO", flush=True)
print("### BOOT SUPABASE_URL set? =>", "YES" if os.getenv("SUPABASE_URL") else "NO", flush=True)
print(
    "### BOOT SUPABASE_SERVICE_ROLE_KEY set? =>",
    "YES" if os.getenv("SUPABASE_SERVICE_ROLE_KEY") else "NO",
    flush=True,
)

# ===== AUTH =====
def require_job_key(x_job_key: str | None = Header(default=None, alias="x-job-key")):
    expected = os.getenv("JOB_KEY")
    print(f"### AUTH DEBUG got={x_job_key!r} expected={expected!r} ###", flush=True)
    if not expected:
        raise HTTPException(status_code=500, detail="JOB_KEY is not set")
    if x_job_key != expected:
        raise HTTPException(status_code=401, detail=f"unauthorized got={x_job_key!r}")
    return True


# ===== util: argv patch =====
@contextmanager
def _patch_argv(argv: list[str]):
    old = sys.argv[:]
    sys.argv = argv
    try:
        yield
    finally:
        sys.argv = old


# ===== lazy loaders =====
def _load_daily():
    mod = importlib.import_module("restaurant_ai_pro.bin.daily_coupon_job")

    # debug fingerprint
    try:
        p = getattr(mod, "__file__", None)
        print(f"[RUNTIME] daily_mod={mod.__name__}", flush=True)
        print(f"[RUNTIME] daily_file={p}", flush=True)
        if p and os.path.exists(p):
            b = open(p, "rb").read()
            print(f"[RUNTIME] daily_sha256={hashlib.sha256(b).hexdigest()}", flush=True)
    except Exception as e:
        print(f"[RUNTIME][ERROR] daily fingerprint error: {e}", flush=True)

    run = getattr(mod, "main", None)
    if not callable(run):
        raise RuntimeError("daily_coupon_job.main not found")
    return run


def _load_weekly():
    mod = importlib.import_module("restaurant_ai_pro.bin.ai_weekly_line_campaign_onlyoneshop")

    # debug fingerprint
    try:
        p = getattr(mod, "__file__", None)
        print(f"[RUNTIME] weekly_mod={mod.__name__}", flush=True)
        print(f"[RUNTIME] weekly_file={p}", flush=True)
        if p and os.path.exists(p):
            b = open(p, "rb").read()
            print(f"[RUNTIME] weekly_sha256={hashlib.sha256(b).hexdigest()}", flush=True)
    except Exception as e:
        print(f"[RUNTIME][ERROR] weekly fingerprint error: {e}", flush=True)

    run = getattr(mod, "main", None)
    if not callable(run):
        raise RuntimeError("weekly.main not found")
    return run


# ===== health =====
@app.get("/health")
def health():
    return {"ok": True}


# ===== DAILY =====
@app.post("/jobs/daily-coupon")
def daily_coupon(_auth=Depends(require_job_key)):
    try:
        run_daily = _load_daily()
        run_daily()
        return {"ok": True}
    except Exception as e:
        print(f"[ERROR] daily_coupon failed: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===== WEEKLY (single or all shops) =====
@app.post("/jobs/weekly-coupon")
def weekly_coupon(
    _auth=Depends(require_job_key),
    x_shop_id: str | None = Header(default=None, alias="x-shop-id"),
):
    """
    - x-shop-id があれば単店舗
    - 無ければ全店舗（--shop_id を渡さない）
    """
    try:
        run_weekly = _load_weekly()

        # 事故りやすいデフォルトを “存在する方” に寄せる
        shops_yaml = os.getenv("SHOPS_YAML", "restaurant_ai_pro/config/shops.yaml")

        argv = [
            "ai_weekly_line_campaign_onlyoneshop.py",
            "--shops_yaml", shops_yaml,
            "--only_coupon",
        ]

        # 単店舗指定：ヘッダ優先 → env fallback
        shop_id = x_shop_id or os.getenv("SHOP_ID")
        if shop_id:
            argv += ["--shop_id", shop_id]

        if os.getenv("DRY_RUN", "0") == "1":
            argv.append("--dry_run")

        print("[WEEKLY] argv =", argv, flush=True)

        with _patch_argv(argv):
            run_weekly()

        return {"ok": True, "mode": "single" if shop_id else "all", "shop_id": shop_id}
    except Exception as e:
        print(f"[ERROR] weekly_coupon failed: {e}", flush=True)
        raise HTTPException(status_code=500, detail=str(e))


# ===== TEST =====
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
