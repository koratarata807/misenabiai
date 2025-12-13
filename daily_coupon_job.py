# api/daily_coupon_job.py

import traceback
from restaurant_ai_pro.bin.daily_coupon_job import main as run_daily_job

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
