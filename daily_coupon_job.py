# api/daily_coupon_job.py

import traceback
from restaurant_ai_pro.bin.daily_coupon_job import main as run_daily_job
import os, inspect, hashlib

def _print_runtime_signature():
    f = inspect.getsourcefile(lambda: None)  # fallback
    try:
        f = __file__
    except Exception:
        pass

    try:
        p = os.path.abspath(__file__)
        b = open(p, "rb").read()
        sha = hashlib.sha256(b).hexdigest()
        print(f"[RUNTIME_DAILY] file={p}", flush=True)
        print(f"[RUNTIME_DAILY] sha256={sha}", flush=True)
        print(f"[RUNTIME_DAILY] cwd={os.getcwd()}", flush=True)
    except Exception as e:
        print(f"[RUNTIME_DAILY][ERROR] {e}", flush=True)

def main():
    _print_runtime_signature()
    print("=== daily_coupon_job START ===", flush=True)
    ...

def handler(request):
    try:
        run_daily_job()
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": '{"ok": true}'
        }
    except Exception as e:
        # エラーをレスポンスに出して、ブラウザ叩きテストで原因追えるようにする
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": (
                '{"ok": false, "error": '
                + repr(str(e))
                + ', "trace": '
                + repr(traceback.format_exc())
                + '}'
            )
        }
