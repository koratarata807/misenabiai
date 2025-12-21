FROM python:3.11-slim

WORKDIR /app

# 依存
COPY bin/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# アプリ本体（restaurant_ai_pro 内を全部入れる）
COPY . /app

ENV PORT=8080
EXPOSE 8080

# FastAPI 起動（必ず restaurant_ai_pro の server を参照）
CMD ["bash", "-lc", "uvicorn restaurant_ai_pro.bin.server:app --host 0.0.0.0 --port ${PORT}"]
