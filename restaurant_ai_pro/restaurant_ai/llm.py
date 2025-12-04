
import os
from typing import Optional

try:
    # Optional dependency; environment may not have it
    from openai import OpenAI
except Exception:
    OpenAI = None

def generate_text(prompt: str, api_key: Optional[str], model: str="gpt-4o-mini") -> str:
    """Generate text via OpenAI if available; otherwise return rule-based fallback."""
    if api_key and OpenAI is not None:
        try:
            client = OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role":"user","content":prompt}],
                temperature=0.4
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            return f"[LLM失敗: {e}]\n{_fallback(prompt)}"
    else:
        return _fallback(prompt)

def _fallback(prompt: str) -> str:
    # Very simple summarizer-like behavior: truncate and template.
    text = prompt[:400]
    return f"(簡易サマリー) 入力を受け取り、要点を端的に報告します:\n{text}..."
