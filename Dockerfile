FROM python:3.11-slim

WORKDIR /app

# requirements
COPY restaurant_ai_pro/bin/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# アプリ本体
COPY restaurant_ai_pro /app/restaurant_ai_pro

ENV PORT=8080
EXPOSE 8080

# ★ restaurant_ai_pro を明示的に Python ルートとして起動
CMD ["bash", "-lc", "python -m uvicorn restaurant_ai_pro.bin.server:app --host 0.0.0.0 --port ${PORT}"]
