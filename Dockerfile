FROM python:3.11-slim

WORKDIR /app

# 依存
COPY restaurant_ai_pro/bin/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# アプリ本体（repo 全部）
COPY . /app

# ★ここが重要：パッケージ import を確実化
ENV PYTHONPATH=/app
ENV PORT=8080
EXPOSE 8080

# ★ここが重要：起動ターゲットを絶対指定
CMD ["bash", "-lc", "uvicorn restaurant_ai_pro.bin.server:app --host 0.0.0.0 --port ${PORT}"]
