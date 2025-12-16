FROM python:3.11-slim

WORKDIR /app

# 依存
COPY bin/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# アプリ本体（bin/, config/, data/ など全部入れる）
COPY . /app

ENV PORT=8080
EXPOSE 8080

# FastAPI 起動
CMD ["bash", "-lc", "uvicorn bin.server:app --host 0.0.0.0 --port ${PORT}"]
