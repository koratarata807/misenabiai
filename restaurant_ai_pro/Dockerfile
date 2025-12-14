FROM python:3.11-slim

WORKDIR /app

# 依存
COPY restaurant_ai_pro/bin/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# アプリ本体
COPY restaurant_ai_pro /app/restaurant_ai_pro

# Cloud Run は PORT を渡してくる
ENV PORT=8080

CMD ["bash", "-lc", "uvicorn restaurant_ai_pro.bin.server:app --host 0.0.0.0 --port ${PORT}"]
