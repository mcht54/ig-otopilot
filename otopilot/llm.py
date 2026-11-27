"""Ücretsiz LLM katmanı: önce Gemini (ücretsiz katman), olmazsa Groq; ikisi de yoksa None döner
ve çağıran taraf kural motoruna düşer. Hiçbir ücretli servis kullanılmaz."""
from __future__ import annotations

import json
import os
import re
import time

import requests

from .ortak import log

# Model adları sabit yazılmaz: Google eski modelleri emekliye ayırınca (404) otomasyon kural metnine düşüyordu.
# GEMINI_MODELLER verilirse önce onlar denenir; ardından hesabın erişebildiği en yeni "flash" modeller kendiliğinden bulunur.
GEMINI_MODELLER = [m for m in os.environ.get("GEMINI_MODELLER", "").split(",") if m]
_ATLA = ("image", "tts", "audio", "live", "embed", "vision", "thinking", "learnlm", "robotics", "computer")
_kesif: list[str] | None = None


def model_sirala(adlar: list[str]) -> list[str]:
    """Kararlı modeller önce (önizlemeler habersiz kalkabiliyor), sonra en yeni sürüm, tam > lite."""
    def puan(ad: str):
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", ad)
        surum = float(m.group(1)) if m else 0.0
        return (not re.search(r"preview|exp", ad), surum, "lite" not in ad, -len(ad))
    secilen = [a for a in adlar if "flash" in a and not any(x in a for x in _ATLA)]
    return sorted(dict.fromkeys(secilen), key=puan, reverse=True)


def _gemini_modelleri(anahtar: str) -> list[str]:
    global _kesif
    if _kesif is None:
        try:
            r = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"pageSize": 200},
                             headers={"x-goog-api-key": anahtar}, timeout=30)
            r.raise_for_status()
            adlar = [m["name"].removeprefix("models/") for m in r.json().get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", [])]
            _kesif = model_sirala(adlar)[:4]
            log(f"gemini modelleri: {', '.join(_kesif) or 'yok'}")
        except Exception as e:
            log(f"gemini model listesi alınamadı: {str(e)[:160]}")
            _kesif = []
    return list(dict.fromkeys(GEMINI_MODELLER + _kesif))
# 2026-11-26: llama-3.3-70b-versatile Groq'tan kaldırıldı; sıra = Türkçesi en doğal olan önce. Kaldırılan model atlanır.
GROQ_MODELLER = [m for m in (os.environ.get("GROQ_MODEL", ""), "qwen/qwen3.8-27b", "openai/gpt-oss-120b") if m]
GROQ_MODEL = GROQ_MODELLER[0]

# ÜCRET FRENİ: yalnız ücretsiz katman. Gemini projelerine ödeme hesabı BAĞLANMAZ (bağlı değilken kota dolunca Google
# ücret yazmaz, 429 döner). Ek güvence: çalıştırma başına istek tavanı + günlük kota dolunca o çalıştırmada bir daha denenmez.
ISTEK_TAVANI = int(os.environ.get("YZ_ISTEK_TAVANI", "80"))
_sayac = {"istek": 0}
_kota_doldu: set[str] = set()


def izin(saglayici: str) -> bool:
    """Bu çalıştırmada bu sağlayıcıya istek atılabilir mi (tavan / kota freni)."""
    if saglayici in _kota_doldu:
        return False
    if _sayac["istek"] >= ISTEK_TAVANI:
        if "tavan" not in _kota_doldu:
            log(f"yapay zekâ istek tavanı ({ISTEK_TAVANI}) doldu; bu çalıştırmada kural metni/yedek ses kullanılacak")
            _kota_doldu.add("tavan")
        return False
    _sayac["istek"] += 1
    return True


def kota_doldu(saglayici: str, yanit_metni: str = "") -> None:
    if saglayici not in _kota_doldu:
        log(f"{saglayici}: günlük ücretsiz kota doldu; bu çalıştırmada bir daha denenmeyecek (ücretli katmana geçilmez)")
    _kota_doldu.add(saglayici)
    try:  # panel "Yapay zekâ" rozeti (2026-11-27): durum/kota.json (rakam/anahtar yok)
        import pathlib
        from .kota_kaydi import kaydet
        tur = "groq" if saglayici == "groq" else ("_ses" if saglayici.startswith("gemini-ses") else
                                                    ("_ara" if saglayici.startswith("gemini-ara") else "gemini_metin"))
        if not tur.startswith("_"):
            kaydet(pathlib.Path(__file__).resolve().parent.parent / "durum", tur)
    except Exception:  # noqa: BLE001
        pass


def kota_ayrinti(r) -> tuple[str, bool]:
    """429 yanıtından yalnız quotaId ve retryDelay alanları (gövde/anahtar loglanmaz). (log metni, günlük kota mı) döner.
    JSON çözülemezse ya da alan yoksa metindeki 'PerDay' / 'per day' ifadesine bakılır."""
    kimlikler, gecikme = [], ""
    try:
        j = r.json()
        hata = j.get("error") if isinstance(j, dict) else None
        ayrintilar = (hata.get("details") or []) if isinstance(hata, dict) else []
        for d in ayrintilar:
            tur = str(d.get("@type", ""))
            if tur.endswith("QuotaFailure"):
                kimlikler += [str(v.get("quotaId", ""))[:120] for v in d.get("violations", []) if v.get("quotaId")]
            elif tur.endswith("RetryInfo"):
                gecikme = str(d.get("retryDelay", ""))[:20]
    except Exception:
        pass
    metin = getattr(r, "text", "") or ""
    gunluk = any("PerDay" in k for k in kimlikler) or "PerDay" in metin or "per day" in metin.lower()
    parca = [f"quotaId={','.join(kimlikler)}"] if kimlikler else []
    if gecikme:
        parca.append(f"retryDelay={gecikme}")
    return " ".join(parca) or "ayrıntı yok", gunluk


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
    for model in _gemini_modelleri(anahtar):
        if f"gemini:{model}" in _kota_doldu:
            continue
        for deneme in range(2):
            if not izin("gemini"):
                return None
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
                if r.status_code == 429:
                    ayrinti, gunluk = kota_ayrinti(r)
                    log(f"gemini {model} HTTP 429 ({ayrinti})")
                    if gunluk:
                        kota_doldu(f"gemini:{model}", r.text)  # kota model başına: sıradaki ücretsiz modele geç
                        break
                if r.status_code == 429 or r.status_code >= 500:
                    log(f"gemini {model} {r.status_code}, bekleniyor")
                    time.sleep(8 * (deneme + 1))
                    continue
                if r.status_code >= 400:
                    log(f"gemini {model} HTTP {r.status_code}")
                r.raise_for_status()
                return r.json()["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:  # ağ, kota, beklenmeyen yanıt
                log(f"gemini {model} hata: {str(e)[:160]}")
                break
    return None


_groq_bekleme = 0  # bir çalıştırmada en çok 3 dakikalık-sınır beklemesi


def _groq(sistem: str, istem: str) -> str | None:
    anahtar = os.environ.get("GROQ_API_KEY")
    if not anahtar or not izin("groq"):
        return None
    for model in dict.fromkeys(GROQ_MODELLER):
        try:
            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {anahtar}"},
                json={
                    "model": model,
                    "temperature": 0.9,
                    "response_format": {"type": "json_object"},
                    "messages": [{"role": "system", "content": sistem}, {"role": "user", "content": istem}],
                },
                timeout=90,
            )
            if r.status_code == 429:
                # Ücretsiz katmanda iki tür sınır var: dakikalık (TPM/RPM, birkaç saniye sonra açılır) ve günlük.
                # Kısa bekleme isteniyorsa bekleyip AYNI ücretsiz anahtarla bir kez daha denenir; günlükse durulur. Ücretliye asla geçilmez.
                try:
                    bekle = float(r.headers.get("retry-after") or 0)
                except ValueError:
                    bekle = 0
                gunluk_mu = "per day" in r.text.lower() or "tpd" in r.text.lower() or "rpd" in r.text.lower() or bekle > 120
                if not gunluk_mu and _groq_bekleme < 3:
                    globals()["_groq_bekleme"] = _groq_bekleme + 1
                    log(f"groq dakikalık sınır; {int(bekle or 20)} sn bekleniyor (ücretsiz katman)")
                    time.sleep(min(max(bekle, 5), 65))
                    r = requests.post("https://api.groq.com/openai/v1/chat/completions", headers={"Authorization": f"Bearer {anahtar}"},
                                      json={"model": model, "temperature": 0.9, "response_format": {"type": "json_object"},
                                            "messages": [{"role": "system", "content": sistem}, {"role": "user", "content": istem}]}, timeout=90)
                    if r.ok:
                        return r.json()["choices"][0]["message"]["content"]
                if r.status_code == 429:
                    kota_doldu("groq", r.text)
                    return None
            if r.status_code in (400, 404) and "model" in r.text.lower():  # model kaldırılmış/desteklenmiyor → sıradaki
                log(f"groq {model} kullanılamıyor ({r.status_code}); sıradaki model")
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log(f"groq {model} hata: {str(e)[:160]}")
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


def ara(istem: str) -> dict | None:
    """Google Arama destekli Gemini çağrısı (ücretsiz katman). {"metin", "kaynaklar": [{uri, baslik}]} ya da None."""
    anahtar = os.environ.get("GEMINI_API_KEY")
    if not anahtar:
        return None
    for model in _gemini_modelleri(anahtar):
        if f"gemini-ara:{model}" in _kota_doldu:
            continue
        for deneme in range(2):
            if not izin("gemini-ara"):
                return None
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  headers={"x-goog-api-key": anahtar}, timeout=120,
                                  json={"contents": [{"parts": [{"text": istem}]}], "tools": [{"google_search": {}}],
                                        "generationConfig": {"temperature": 0.4}})
                if r.status_code >= 400:  # yalnız durum kodu (gövde/anahtar loglanmaz)
                    ayrinti = f" ({kota_ayrinti(r)[0]})" if r.status_code == 429 else ""
                    log(f"gemini arama {model} HTTP {r.status_code}{ayrinti}")
                if r.status_code == 429 and kota_ayrinti(r)[1]:
                    kota_doldu(f"gemini-ara:{model}", r.text)
                    break
                if r.status_code in (429, 500, 503):
                    time.sleep(8 * (deneme + 1))
                    continue
                r.raise_for_status()
                c = r.json()["candidates"][0]
                gm = c.get("groundingMetadata") or {}
                return {"metin": "".join(p.get("text", "") for p in c["content"]["parts"]),
                        "kaynaklar": [{"uri": ch.get("web", {}).get("uri", ""), "baslik": ch.get("web", {}).get("title", "")}
                                      for ch in gm.get("groundingChunks", [])]}
            except Exception as e:
                log(f"gemini arama {model} hata: {str(e)[:160]}")
                break
    return None


def var_mi() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY"))
