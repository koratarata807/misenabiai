
import os
from dataclasses import dataclass

@dataclass
class Settings:
    OPENAI_API_KEY: str|None = os.getenv("OPENAI_API_KEY")
    MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    TZ: str = os.getenv("APP_TZ", "Asia/Tokyo")

SETTINGS = Settings()
