import os
import requests
from dotenv import load_dotenv

# .env.shopA を読み込む
load_dotenv("config/.env.shopA")

token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

print("TOKEN head:", token[:10] if token else None)

headers = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer " + token,
}

data = {
    "messages": [
        {
            "type": "text",
            "text": "テスト：LINE公式の友だち全員に送るブロードキャスト from Python (shopA)",
        }
    ]
}

response = requests.post(
    "https://api.line.me/v2/bot/message/broadcast",
    headers=headers,
    json=data,
)

print("STATUS:", response.status_code)
print("BODY:", response.text)
