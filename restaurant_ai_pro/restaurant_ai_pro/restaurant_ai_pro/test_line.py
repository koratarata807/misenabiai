import os
import requests
from dotenv import load_dotenv

# .env.shopA を読み込む
load_dotenv("config/.env.shopA")

token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
user_id = os.getenv("LINE_USER_ID")  # or GROUP_ID

print("TOKEN head:", token[:10] if token else None)

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}",
}

data = {
    "to": user_id,
    "messages": [
        {"type": "text", "text": "テスト送信 from Python (shopA)"}
    ],
}

r = requests.post(
    "https://api.line.me/v2/bot/message/push",
    headers=headers,
    json=data,
)
print("STATUS:", r.status_code)
print("BODY:", r.text)

