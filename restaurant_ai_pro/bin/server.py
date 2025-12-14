# restaurant_ai_pro/bin/server.py
import os
from fastapi import FastAPI, Header, HTTPException
from bin.daily_coupon_job import main as run_daily

app = FastAPI()

@app.get("/health")
def health():
  return {"ok": True}

@app.post("/jobs/daily-coupon")
def daily_coupon(x_job_key: str = Header(default="")):
  if x_job_key != os.getenv("JOB_KEY"):
    raise HTTPException(status_code=401, detail="unauthorized")
  run_daily()
  return {"ok": True}
