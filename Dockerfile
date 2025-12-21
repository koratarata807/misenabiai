FROM python:3.11-slim

WORKDIR /app

# 依存
COPY restaurant_ai_pro/bin/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# ソース全部
COPY . /app

ENV PORT=8080
EXPOSE 8080

# ★重要：restaurant_ai_pro の server を起動
CMD ["bash", "-lc", "python -c \"import restaurant_ai_pro.bin.server as s; print('[BOOT_OK]');\" && uvicorn restaurant_ai_pro.bin.server:app --host 0.0.0.0 --port ${PORT}"]
