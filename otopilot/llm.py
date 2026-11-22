"""Ücretsiz LLM katmanı: önce Gemini (ücretsiz katman), olmazsa Groq; ikisi de yoksa None döner
ve çağıran taraf kural motoruna düşer. Hiçbir ücretli servis kullanılmaz."""
from __future__ import annotations

import json
import os
import re
import time

import requests

from .ortak import log

GEMINI_MODELLER = [m for m in os.environ.get("GEMINI_MODELLER", "gemini-2.5-flash,gemini-2.0-flash").split(",") if m]
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


def _json_ayikla(metin: str):
    metin = metin.strip()
    metin = re.sub(r"^```(?:json)?\s*|\s*```$", "", metin)
    try:
        return json.loads(metin)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", metin, re.S)
        if m:
            return json.loads(m.group(0))
        raise


def _gemini(sistem: str, istem: str) -> str | None:
    anahtar = os.environ.get("GEMINI_API_KEY")
    if not anahtar:
        return None
    for model in GEMINI_MODELLER:
        for deneme in range(2):
            try:
                r = requests.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": anahtar},
                    json={
                        "systemInstruction": {"parts": [{"text": sistem}]},
                        "contents": [{"role": "user", "parts": [{"text": istem}]}],
                        "generationConfig": {"temperature": 0.9, "responseMimeType": "application/json"},
                    },
                    timeout=90,
                )
                if r.status_code == 429 or r.status_code >= 500:
                    log(f"gemini {model} {r.status_code}, bekleniyor")
                    time.sleep(8 * (deneme + 1))
                    continue
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:  # ağ, kota, beklenmeyen yanıt
                log(f"gemini {model} hata: {str(e)[:160]}")
                break
    return None


def _groq(sistem: str, istem: str) -> str | None:
    anahtar = os.environ.get("GROQ_API_KEY")
    if not anahtar:
        return None
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {anahtar}"},
            json={
                "model": GROQ_MODEL,
                "temperature": 0.9,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": sistem}, {"role": "user", "content": istem}],
            },
            timeout=90,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log(f"groq hata: {str(e)[:160]}")
        return None


def json_sor(sistem: str, istem: str) -> dict | None:
    """JSON nesnesi döndürür; hiçbir sağlayıcı çalışmazsa None."""
    for ad, f in (("gemini", _gemini), ("groq", _groq)):
        yanit = f(sistem, istem)
        if not yanit:
            continue
        try:
            veri = _json_ayikla(yanit)
            if isinstance(veri, dict):
                veri["_saglayici"] = ad
                return veri
        except Exception as e:
            log(f"{ad} JSON çözülemedi: {e}")
    return None


def var_mi() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY"))
