FROM python:3.11-slim

WORKDIR /app

# 依存
COPY restaurant_ai_pro/bin/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# アプリ本体：restaurant_ai_pro をパッケージとして配置
COPY restaurant_ai_pro /app/restaurant_ai_pro

ENV PORT=8080
EXPOSE 8080

# FastAPI 起動（A: restaurant_ai_pro 経由で起動）
CMD ["bash", "-lc", "uvicorn restaurant_ai_pro.bin.server:app --host 0.0.0.0 --port ${PORT}"]
