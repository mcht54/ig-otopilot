"""Seslendirme + fon müziği. Kalıcı kural: her Reels anlatıcı, çarpıcı, heyecanlı, dinletecek tonda seslendirilir;
arkada telifsiz müzik çalar, konuşurken müzik kısılır. Hiçbir adım paylaşımı durdurmaz:
  anlatım metni : Gemini (denetimli) → kural metni
  ses           : Gemini TTS (markanın sesi) → edge-tts (Microsoft Türkçe nöral ses) → yalnız müzik
  müzik         : muzik/<kod>/*.mp3 ya da muzik/*.mp3 varsa o, yoksa kodla sentez (otopilot/muzik.py)
"""
from __future__ import annotations

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import os
import re
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np
import requests

from . import llm, muzik
from .ortak import KOK, log

SR = muzik.SR
GEMINI = "https://generativelanguage.googleapis.com/v1beta"
VARSAYILAN_TARZ = ("Sen heyecanlı, çarpıcı ve dinleten bir Instagram Reels anlatıcısısın. Enerjik, vurgulu, merak uyandıran, "
                   "akıcı ve hızlı tempoda; gülümseyerek konuşur gibi, doğal Türkçe telaffuzla oku. Satır sonlarında kısa nefes payı bırak.")
EDGE_VARSAYILAN = "tr-TR-AhmetNeural"
_tts_modeller: list[str] | None = None


# ---------------- anlatım metni ----------------

def konusma_metni(metin: str, marka: dict) -> str:
    """Ekran yazısını seslendirmeye uygun hâle getirir (%, ₺, adres, kısaltma)."""
    m = str(metin or "")
    m = re.sub(r"\+\s*%\s*(\d+)", r"yüzde \1 fazla", m)
    m = re.sub(r"%\s*(\d+)", r"yüzde \1", m)
    m = re.sub(r"₺\s*([\d.,]+)", r"\1 lira", m)
    m = re.sub(r"\s*\+\s*KDV", " artı KDV", m)
    m = re.sub(r"\b[\w-]+\.(?:com\.tr|net\.tr|org\.tr|com|tr|net)\b", marka["ad"], m)
    m = m.replace("&", " ve ").replace("…", "").replace("→", "").replace("|", ",")
    m = re.sub(r"\s*\([^)]*\)", "", m)          # parantez içi (İngilizce terim vb.) okunmaz
    m = re.sub(r"[#*_]", "", m)
    m = re.sub(r"\s*([?!])\s*[.!]+", r"\1", m)   # "?." "!." → tek işaret
    m = re.sub(r"\.{2,}", ".", m).replace(":.", ".").replace(": :", ":")
    return re.sub(r"\s+", " ", m).strip()


def _sahne_yazilari(sh: dict) -> list[str]:
    y = [sh.get(a) for a in ("etiket", "rakam", "baslik", "alt", "ust_yazi") if sh.get(a)]
    y += list(sh.get("maddeler", []))
    y += [e["ust_yazi"] for e in sh.get("eylemler", []) if e.get("ust_yazi")]
    return [str(x) for x in y]


def _kural_satiri(sh: dict, marka: dict, ilk: bool) -> str:
    tip = sh.get("tip") or sh.get("tur")
    b, a = sh.get("baslik") or "", sh.get("alt") or ""
    if tip == "kapak":
        s = f"{b}! {a}" if a and len(a) < 60 else f"{b}!"
    elif tip == "liste":
        s = f"{b}: " + ", ".join(sh.get("maddeler", [])[:2]) + "."
    elif tip == "rakam":
        s = f"{b}: {sh.get('rakam', '')}!"
    elif tip == "cta":
        s = f"{b}. {marka['cta']}!"
    elif sh.get("tur") == "sayfa":
        s = sh.get("ust_yazi") or next((e["ust_yazi"] for e in sh.get("eylemler", []) if e.get("ust_yazi")), "") or "İşte gerçek ekran."
    else:
        s = f"{b}. {a}" if a else b
    s = s.strip(" .") + ("!" if ilk else ".")
    return konusma_metni(s, marka)


def kural_anlatim(senaryo: dict, marka: dict) -> list[str]:
    return [_kural_satiri(sh, marka, i == 0) for i, sh in enumerate(senaryo["sahneler"])]


def _rakamlar(metin: str) -> set[str]:
    return set(re.findall(r"\d+", metin.replace(".", "")))


def anlatim_denetle(satirlar, senaryo: dict, marka: dict) -> list[str]:
    from .beyin import GENEL_YASAK
    hatalar = []
    if not isinstance(satirlar, list) or len(satirlar) != len(senaryo["sahneler"]):
        return ["satır sayısı sahne sayısıyla aynı değil"]
    izinli = _rakamlar(" ".join(map(str, senaryo.get("olgular", [])))
                       + " " + " ".join(y for sh in senaryo["sahneler"] for y in _sahne_yazilari(sh)))
    yasak = [y.lower() for y in marka.get("yasak_ifadeler", []) + GENEL_YASAK]
    for i, s in enumerate(satirlar):
        s = str(s or "")
        if not s.strip():
            hatalar.append(f"{i}: boş")
        if len(s.split()) > 32:
            hatalar.append(f"{i}: çok uzun")
        if re.search(r"https?://|www\.|#|[\U0001F300-\U0001FAFF]", s):
            hatalar.append(f"{i}: adres/etiket/emoji")
        uydurma = _rakamlar(s) - izinli
        if uydurma:
            hatalar.append(f"{i}: kaynaksız rakam {sorted(uydurma)}")
        if any(y in s.lower() for y in yasak):
            hatalar.append(f"{i}: yasak ifade")
    return hatalar


def anlatim_yaz(senaryo: dict, marka: dict) -> tuple[list[str], str]:
    """Sahne başına bir konuşma satırı. Gemini denetimden geçemezse kural metni."""
    sahneler = []
    for i, sh in enumerate(senaryo["sahneler"]):
        kelime = max(5, round(min(sh.get("sure", 3) + 2.5, 9) * 2.6))
        sahneler.append(f"{i + 1}. sahne ({sh.get('tip') or sh.get('tur')}, en çok {kelime} kelime) ekranda: " + " | ".join(_sahne_yazilari(sh)))
    sistem = (f"{marka['ad']} için Instagram Reels anlatım metni yazıyorsun. {VARSAYILAN_TARZ}\n"
              f"Hedef kitle: {marka['hedef_kitle'].strip()}\n"
              "KURALLAR: Türkçe, 'siz' diye hitap. Her sahneye TEK satır. 1. satır ilk saniyede durduran çarpıcı bir kanca "
              "(soru ya da şaşırtan tespit). Ekrandaki yazıyı kelimesi kelimesine okuma; canlı, akıcı, merak uyandıran anlatıcı dili kullan. "
              "Son satır harekete çağrı (" + marka["cta"] + "). Rakam yalnız OLGULAR'da ya da ekranda varsa. Web adresi, emoji, etiket yok. "
              f"Yasak: {', '.join(marka.get('yasak_ifadeler', []))}. Kelime sınırlarına uy.")
    istem = ("OLGULAR:\n- " + "\n- ".join(map(str, senaryo.get("olgular", []))) + "\n\nSAHNELER:\n" + "\n".join(sahneler)
             + f'\n\nYalnız JSON döndür: {{"satirlar": [{len(sahneler)} satır]}}')
    try:
        veri = llm.json_sor(sistem, istem)
        if veri:
            satirlar = [konusma_metni(s, marka) for s in veri.get("satirlar", [])]
            hatalar = anlatim_denetle(satirlar, senaryo, marka)
            if not hatalar:
                return satirlar, veri.get("_saglayici", "llm")
            log(f"anlatım denetimden geçmedi: {hatalar}; kural metni")
    except Exception as e:
        log(f"anlatım yazılamadı: {e}")
    return kural_anlatim(senaryo, marka), "kural"


# ---------------- seslendirme ----------------

def _ses_modelleri(anahtar: str) -> list[str]:
    global _tts_modeller
    if _tts_modeller is None:
        try:
            r = requests.get(f"{GEMINI}/models", params={"pageSize": 200}, headers={"x-goog-api-key": anahtar}, timeout=30)
            r.raise_for_status()
            adlar = [m["name"].removeprefix("models/") for m in r.json().get("models", [])
                     if "tts" in m["name"] and "generateContent" in m.get("supportedGenerationMethods", [])]
            def puan(a):
                s = re.search(r"gemini-(\d+(?:\.\d+)?)", a)
                return ("flash" in a, float(s.group(1)) if s else 0.0, not re.search(r"preview|exp", a))
            _tts_modeller = sorted(adlar, key=puan, reverse=True)[:3]
            log(f"gemini ses modelleri: {', '.join(_tts_modeller) or 'yok'}")
        except Exception as e:
            log(f"gemini ses modeli listesi alınamadı: {str(e)[:160]}")
            _tts_modeller = []
    return _tts_modeller


def _yeniden_ornekle(x: np.ndarray, kaynak: int) -> np.ndarray:
    if kaynak == SR or not len(x):
        return x.astype(np.float32)
    n = int(len(x) * SR / kaynak)
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


def _gemini_ses(satirlar: list[str], marka: dict) -> np.ndarray | None:
    anahtar = os.environ.get("GEMINI_API_KEY")
    if not anahtar:
        return None
    ayar = marka.get("ses") or {}
    metin = (ayar.get("tarz") or VARSAYILAN_TARZ) + " Her satırdan sonra yarım saniye dur:\n\n" + "\n".join(satirlar)
    govde = {"contents": [{"parts": [{"text": metin}]}],
             "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                 "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": ayar.get("gemini", "Puck")}}}}}
    for model in _ses_modelleri(anahtar):
        for deneme in range(2):
            if not llm.izin("gemini-ses"):
                return None
            try:
                r = requests.post(f"{GEMINI}/models/{model}:generateContent", json=govde, timeout=180,
                                  headers={"x-goog-api-key": anahtar})
                if r.status_code == 429 and ("PerDay" in r.text or "per day" in r.text.lower()):
                    llm.kota_doldu("gemini-ses", r.text)
                    return None
                if r.status_code in (429, 500, 503):
                    log(f"gemini ses {model} {r.status_code}, bekleniyor")
                    import time
                    time.sleep(10 * (deneme + 1))
                    continue
                r.raise_for_status()
                veri = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                pcm = np.frombuffer(base64.b64decode(veri["data"]), dtype="<i2").astype(np.float32) / 32768
                oran = int(re.search(r"rate=(\d+)", veri.get("mimeType", "")).group(1)) if "rate=" in veri.get("mimeType", "") else 24000
                log(f"ses: gemini {model} ({ayar.get('gemini', 'Puck')})")
                return _yeniden_ornekle(pcm, oran)
            except Exception as e:
                log(f"gemini ses {model} hata: {str(e)[:160]}")
                break
    return None


def _coz(yol: Path) -> np.ndarray:
    c = subprocess.run(["ffmpeg", "-v", "error", "-i", str(yol), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                       capture_output=True, check=True)
    return np.frombuffer(c.stdout, dtype=np.float32).copy()


def _edge_ses(satirlar: list[str], marka: dict) -> list[np.ndarray] | None:
    try:
        import edge_tts
    except ImportError:
        return None
    ayar = marka.get("ses") or {}
    ses_adi = ayar.get("edge", EDGE_VARSAYILAN)
    parcalar = []
    try:
        with tempfile.TemporaryDirectory() as d:
            for i, s in enumerate(satirlar):
                yol = Path(d) / f"{i}.mp3"
                iletisim = edge_tts.Communicate(s, ses_adi, rate=ayar.get("edge_hiz", "+12%"), pitch="+2Hz")
                # Playwright (sync) aynı iş parçacığında olay döngüsü çalıştırıyor → ayrı iş parçacığında çalıştır
                with ThreadPoolExecutor(1) as h:
                    h.submit(lambda: asyncio.run(iletisim.save(str(yol)))).result(timeout=90)
                parcalar.append(_sessizlik_kirp(_coz(yol)))
        log(f"ses: edge-tts ({ses_adi})")
        return parcalar
    except Exception as e:
        log(f"edge-tts hata: {str(e)[:160]}")
        return None


def _enerji(x: np.ndarray, pencere: float = 0.02) -> np.ndarray:
    n = max(1, int(pencere * SR))
    k = len(x) // n
    return np.sqrt(np.mean(x[: k * n].reshape(k, n) ** 2, axis=1)) if k else np.zeros(0)


def _sessizlik_kirp(x: np.ndarray) -> np.ndarray:
    e = _enerji(x)
    if not len(e):
        return x
    aktif = np.where(e > max(e.max() * 0.04, 1e-4))[0]
    if not len(aktif):
        return x[:0]
    n = int(0.02 * SR)
    return x[max(0, aktif[0] * n - n): min(len(x), (aktif[-1] + 2) * n)]


def bol(x: np.ndarray, adet: int, satirlar: list[str]) -> list[np.ndarray]:
    """Tek parça seslendirmeyi satırlara böler: en uzun (adet-1) sessizlik sınır sayılır; yetmezse harf oranıyla."""
    x = _sessizlik_kirp(x)
    if adet <= 1:
        return [x]
    e = _enerji(x)
    pen = int(0.02 * SR)
    sessiz = e < max(e.max() * 0.04, 1e-4)
    araliklar, bas = [], None
    for i, s in enumerate(sessiz):
        if s and bas is None:
            bas = i
        elif not s and bas is not None:
            if i - bas >= 8:  # ≥160 ms
                araliklar.append((i - bas, bas, i))
            bas = None
    if len(araliklar) >= adet - 1:
        sinirlar = sorted((b + s) // 2 * pen for _, b, s in sorted(araliklar, reverse=True)[: adet - 1])
    else:  # yedek: harf sayısına göre
        oran = np.cumsum([len(s) for s in satirlar])[:-1] / sum(len(s) for s in satirlar)
        sinirlar = [int(o * len(x)) for o in oran]
    kesik = np.split(x, sinirlar)
    return [_sessizlik_kirp(k) for k in kesik]


def seslendir(satirlar: list[str], marka: dict) -> tuple[list[np.ndarray] | None, str]:
    """Satır başına ses parçası (44,1 kHz mono). Hiçbir sağlayıcı olmazsa (None, 'yok')."""
    tek = _gemini_ses(satirlar, marka)
    if tek is not None:
        parcalar = bol(tek, len(satirlar), satirlar)
        if _makul(parcalar, satirlar):
            return parcalar, "gemini"
        log("gemini sesi satırlara makul bölünemedi; edge-tts deneniyor")
    parcalar = _edge_ses(satirlar, marka)
    if parcalar and _makul(parcalar, satirlar):
        return parcalar, "edge"
    return None, "yok"


def _makul(parcalar: list[np.ndarray], satirlar: list[str]) -> bool:
    """Her satır duyulabilir ve hızı insan konuşması aralığında mı (yarım kalan/boş/aşırı uzun ses elenir)."""
    if len(parcalar) != len(satirlar):
        return False
    for p, s in zip(parcalar, satirlar):
        sn = len(p) / SR
        if sn < 0.5 or not (5 <= len(s) / max(sn, 0.1) <= 30):
            return False
    return True


# ---------------- miks ----------------

def muzik_dosyasi(kod: str, tohum: str) -> Path | None:
    import random
    for klasor in (KOK / "muzik" / kod, KOK / "muzik"):
        parcalar = sorted(klasor.glob("*.mp3")) if klasor.exists() else []
        if parcalar:
            return random.Random(tohum).choice(parcalar)
    return None


def fon(sure: float, marka: dict, tohum: str) -> np.ndarray:
    dosya = muzik_dosyasi(marka.get("kod", ""), tohum)
    if dosya:
        m = _coz(dosya)
        m = np.tile(m, int(np.ceil(sure * SR / max(len(m), 1))))[: int(sure * SR)]
        return np.stack([m, m], axis=1) * 0.8
    return muzik.uret(sure, marka, tohum)


def miks(sure: float, konusmalar: list[tuple[float, np.ndarray]], marka: dict, tohum: str, cikti: Path) -> Path:
    """konusmalar: (başlangıç sn, mono ses). Konuşma varken müzik kısılır (ducking). 44,1 kHz stereo wav yazar."""
    n = int(sure * SR)
    ses = np.zeros(n, dtype=np.float32)
    for an, p in konusmalar:
        i = int(an * SR)
        if i < n:
            p = p[: n - i]
            tepe = np.max(np.abs(p)) or 1.0
            ses[i:i + len(p)] += p / tepe * 0.9
    m = fon(sure, marka, tohum)[:n]
    if len(m) < n:
        m = np.pad(m, ((0, n - len(m)), (0, 0)))
    if konusmalar:
        aktif = (np.abs(ses) > 0.02).astype(np.float32)
        w = int(0.25 * SR)
        aktif = np.convolve(aktif, np.ones(w) / w, mode="same").clip(0, 1)
        kazanc = 0.30 - 0.20 * np.minimum(aktif * 3, 1)  # konuşurken 0.10, arada 0.30
    else:
        kazanc = np.full(n, 0.55, dtype=np.float32)
    sonuc = m * kazanc[:, None] + ses[:, None]
    tepe = np.max(np.abs(sonuc)) or 1.0
    sonuc = (sonuc / max(tepe, 1.0) * 0.97 * 32767).astype("<i2")
    with wave.open(str(cikti), "wb") as w_:
        w_.setnchannels(2)
        w_.setsampwidth(2)
        w_.setframerate(SR)
        w_.writeframes(sonuc.tobytes())
    return cikti
