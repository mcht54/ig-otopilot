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

_BIR = ["", "bir", "iki", "üç", "dört", "beş", "altı", "yedi", "sekiz", "dokuz"]
_ON = ["", "on", "yirmi", "otuz", "kırk", "elli", "altmış", "yetmiş", "seksen", "doksan"]


def sayi_yazi(n: int) -> str:
    """0–999999 Türkçe okunuşu (seslendirme rakamı yanlış okumasın, doğrulama da tutarlı olsun)."""
    if n == 0:
        return "sıfır"
    if n >= 1_000_000:
        return str(n)
    def uc(x: int) -> str:
        y, o, b = x // 100, (x // 10) % 10, x % 10
        return " ".join(p for p in (("yüz" if y == 1 else f"{_BIR[y]} yüz") if y else "", _ON[o], _BIR[b]) if p)
    bin_, kalan = divmod(n, 1000)
    bas = ("bin" if bin_ == 1 else f"{uc(bin_)} bin") if bin_ else ""
    return " ".join(p for p in (bas, uc(kalan)) if p)


def _rakamlari_yaz(m: str) -> str:
    m = re.sub(r"(\d)\.(\d{3})\b", r"\1\2", m)  # 1.700 → 1700
    return re.sub(r"\b\d{1,6}\b", lambda x: sayi_yazi(int(x.group(0))), m)


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
    m = re.sub(r"(^|[.!?]\s+)\d+[.)]\s+", r"\1", m)  # "1. Tasarımı seçin" → "Tasarımı seçin"
    m = m.replace(" — ", ", ").replace("—", ", ")
    m = re.sub(r"[#*_]", "", m)
    m = re.sub(r"\s*([?!])\s*[.!]+", r"\1", m)   # "?." "!." → tek işaret
    m = re.sub(r"\.{2,}", ".", m).replace(":.", ".").replace(": :", ":")
    m = _rakamlari_yaz(m)
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
        y = sh.get("ust_yazi") or next((e["ust_yazi"] for e in sh.get("eylemler", []) if e.get("ust_yazi")), "")
        s = f"Şimdi gerçek ekranda bakalım: {y}" if y else "Şimdi gerçek ekranda bakalım."
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


def anlatim_yaz(senaryo: dict, marka: dict, kod: str | None = None) -> tuple[list[str], str]:
    """Sahne başına bir konuşma satırı. Gemini denetimden geçemezse kural metni."""
    sahneler = []
    for i, sh in enumerate(senaryo["sahneler"]):
        kelime = max(4, min(13, round(sh.get("sure", 3) * 2.3)))  # Reels 15-30 sn: kısa, vurucu
        sahneler.append(f"{i + 1}. sahne ({sh.get('tip') or sh.get('tur')}, en çok {kelime} kelime) ekranda: " + " | ".join(_sahne_yazilari(sh)))
    sistem = (f"{marka['ad']} için Instagram Reels anlatım metni yazıyorsun. {VARSAYILAN_TARZ}\n"
              f"Hedef kitle: {marka['hedef_kitle'].strip()}\n"
              "KURALLAR: Türkçe, 'siz' diye hitap. Her sahneye TEK satır. 1. satır ilk saniyede durduran çarpıcı bir kanca "
              "(soru ya da şaşırtan tespit). Ekrandaki yazıyı kelimesi kelimesine okuma; canlı, akıcı, merak uyandıran anlatıcı dili kullan. "
              "Son satır harekete çağrı (" + marka["cta"] + "). Rakam yalnız OLGULAR'da ya da ekranda varsa. Web adresi, emoji, etiket yok. "
              "OLGULAR'da ya da ekranda olmayan hiçbir özellik, hizmet, süre, kargo/teslimat, fiyat ya da vaat SÖYLEME. "
              "Toplam en çok 60 kelime; video 30 saniyeyi geçmesin. "
              f"Yasak: {', '.join(marka.get('yasak_ifadeler', []))}. Kelime sınırlarına uy.")
    if kod or marka.get("kod"):
        from . import strateji
        sistem += "\n" + strateji.baglam(kod or marka["kod"], marka)
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


def _gemini_ses(satirlar: list[str], marka: dict, ses_adi: str) -> np.ndarray | None:
    """Gemini TTS. HİÇBİR YÖNERGE VERİLMEZ: model Türkçe talimatı da İngilizce kısa yönergeyi de sesli okudu
    (2026-11-23, iki ayrı hata). Yalnız okunacak Türkçe metin gider; ton ünlem/noktalama ve ses seçimiyle gelir."""
    anahtar = os.environ.get("GEMINI_API_KEY")
    if not anahtar:
        return None
    metin = "\n".join(satirlar)
    govde = {"contents": [{"parts": [{"text": metin}]}],
             "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                 "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": ses_adi}}}}}
    for model in _ses_modelleri(anahtar):
        if f"gemini-ses:{model}" in llm._kota_doldu:
            continue
        for deneme in range(2):
            if not llm.izin("gemini-ses"):
                return None
            try:
                r = requests.post(f"{GEMINI}/models/{model}:generateContent", json=govde, timeout=180,
                                  headers={"x-goog-api-key": anahtar})
                if r.status_code == 429 and ("PerDay" in r.text or "per day" in r.text.lower()):
                    llm.kota_doldu(f"gemini-ses:{model}", r.text)
                    break
                if r.status_code in (429, 500, 503):
                    log(f"gemini ses {model} {r.status_code}, bekleniyor")
                    import time
                    time.sleep(10 * (deneme + 1))
                    continue
                r.raise_for_status()
                veri = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
                pcm = np.frombuffer(base64.b64decode(veri["data"]), dtype="<i2").astype(np.float32) / 32768
                oran = int(re.search(r"rate=(\d+)", veri.get("mimeType", "")).group(1)) if "rate=" in veri.get("mimeType", "") else 24000
                log(f"ses: gemini {model} ({ses_adi})")
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


YEDEK_SESLER = ["Kore", "Charon", "Puck", "Zephyr", "Fenrir"]


def seslendir(satirlar: list[str], marka: dict) -> tuple[list[np.ndarray] | None, str]:
    """Satır başına ses parçası (44,1 kHz mono). Her parça yazıya dökülüp metinle karşılaştırılır (Türkçe mi, doğru mu);
    geçmezse başka Gemini sesiyle yeniden denenir. Hiçbiri geçmezse (None, 'yok') → video yalnız müzikle çıkar.
    Kötü/yanlış ses yayına çıkmaz (2026-11-23: talimat okuma, yabancı dille başlama, robotik yedek ses şikâyetleri)."""
    ayar = marka.get("ses") or {}
    sesler = list(dict.fromkeys([ayar.get("gemini", "Puck"), *YEDEK_SESLER]))[:3]
    for ses_adi in sesler:
        tek = _gemini_ses(satirlar, marka, ses_adi)
        if tek is None:
            break  # anahtar/kota yok
        if not _toplam_makul(tek, satirlar):
            log(f"gemini sesi ({ses_adi}) metne göre fazla uzun/kısa → reddedildi")
            continue
        parcalar = bol(tek, len(satirlar), satirlar)
        if not _makul(parcalar, satirlar):
            log(f"gemini sesi ({ses_adi}) satırlara makul bölünemedi → reddedildi")
            continue
        sonuc = dogrula(parcalar, satirlar)
        if sonuc is True:
            return parcalar, "gemini"
        if sonuc is None and _toplam_makul(tek, satirlar):
            log("ses doğrulama modeli çalışmadı; yalnız süre denetimiyle kabul edildi")
            return parcalar, "gemini-denetimsiz"
        log(f"gemini sesi ({ses_adi}) dinleme denetiminden geçmedi → başka sesle yeniden")
    if not ayar.get("edge_izinli"):
        log("geçerli ses yok → video yalnız müzik ve ekran yazılarıyla çıkacak (kötü ses yayınlanmaz)")
        return None, "yok"
    log("edge-tts deneniyor")
    parcalar = _edge_ses(satirlar, marka)
    if parcalar and _makul(parcalar, satirlar) and dogrula(parcalar, satirlar) is not False:
        return parcalar, "edge"
    return None, "yok"


# ---------------- dinleme denetimi (Whisper, yerel, ücretsiz) ----------------

_whisper = None
BENZERLIK_ESIK = 0.62


def _sade(t: str) -> str:
    t = _rakamlari_yaz(str(t or "").replace("%", " yüzde "))
    t = t.lower().translate(str.maketrans("çğıöşüâîû", "cgiosuaiu"))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def benzerlik(a: str, b: str) -> float:
    import difflib
    return difflib.SequenceMatcher(None, _sade(a), _sade(b)).ratio()


def _model():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel(os.environ.get("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    return _whisper


def dinle(p: np.ndarray) -> tuple[str, str, float]:
    """Ses parçasını yazıya döker: (metin, dil, dil olasılığı)."""
    x = np.interp(np.linspace(0, len(p) - 1, int(len(p) * 16000 / SR)), np.arange(len(p)), p).astype(np.float32)
    parcalar, bilgi = _model().transcribe(x, beam_size=1, vad_filter=False, condition_on_previous_text=False)
    return " ".join(s.text for s in parcalar).strip(), bilgi.language, float(bilgi.language_probability)


def dogrula(parcalar: list[np.ndarray], satirlar: list[str]) -> bool | None:
    """True: hepsi Türkçe ve metinle uyumlu. False: en az biri değil. None: denetim modeli çalışmadı.
    İçerik loglanmaz; yalnız oranlar."""
    try:
        sonuc = []
        for p, s in zip(parcalar, satirlar):
            metin, dil, olas = dinle(p)
            b = benzerlik(metin, s)
            sonuc.append((dil, round(olas, 2), round(b, 2)))
            if dil != "tr" or b < BENZERLIK_ESIK:
                log(f"dinleme denetimi: satır {len(sonuc)} dil={dil} ({olas:.2f}) benzerlik={b:.2f} → RED")
                return False
        log(f"dinleme denetimi geçti: {sonuc}")
        return True
    except Exception as e:
        log(f"dinleme denetimi çalışmadı: {type(e).__name__}: {str(e)[:120]}")
        return None


HIZ = (9.0, 24.0)  # Türkçe seslendirmede saniyedeki harf (boşluk dahil) makul aralığı


def _konusma_suresi(x: np.ndarray) -> float:
    """Sessizlikler hariç konuşma süresi (sn)."""
    e = _enerji(x)
    if not len(e):
        return 0.0
    return float(np.sum(e > max(e.max() * 0.04, 1e-4)) * 0.02)


def _toplam_makul(x: np.ndarray, satirlar: list[str]) -> bool:
    """Tüm ses, metnin uzunluğuna uygun mu? Talimat ya da fazladan cümle okunduysa konuşma süresi şişer → False."""
    sn = _konusma_suresi(x)
    harf = sum(len(s) for s in satirlar)
    return sn > 0.5 and HIZ[0] <= harf / sn <= HIZ[1] * 1.15


def _makul(parcalar: list[np.ndarray], satirlar: list[str]) -> bool:
    """Her satır duyulabilir ve hızı insan konuşması aralığında mı (yarım kalan/boş/fazladan okuma elenir)."""
    if len(parcalar) != len(satirlar):
        return False
    for p, s in zip(parcalar, satirlar):
        sn = _konusma_suresi(p)
        if sn < 0.4 or not (HIZ[0] * 0.8 <= len(s) / max(sn, 0.1) <= HIZ[1] * 1.3):
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
    """konusmalar: (başlangıç sn, mono ses). Konuşma varken müzik kısılır (ducking). 44,1 kHz stereo wav yazar.
    Cızırtı önlemi (2026-11-23): dosya videodan 0.5 sn uzun, son 0.8 sn yumuşak söner, tepe -1 dBFS altında (kırpılma yok)."""
    n_video = int(sure * SR)
    n = n_video + int(0.5 * SR)
    ses = np.zeros(n, dtype=np.float32)
    for an, p in konusmalar:
        i = int(an * SR)
        if i < n:
            p = np.array(p[: n - i], dtype=np.float32)
            tepe = np.max(np.abs(p)) or 1.0
            p = p / tepe * 0.9
            gi, ci = min(len(p), int(0.015 * SR)), min(len(p), int(0.06 * SR))  # tık/cızırtı olmasın: kenarlar yumuşak
            if gi:
                p[:gi] *= np.linspace(0, 1, gi)
            if ci:
                p[-ci:] *= np.linspace(1, 0, ci) ** 2
            ses[i:i + len(p)] += p
    m = fon(sure, marka, tohum)[:n]
    if len(m) < n:
        m = np.pad(m, ((0, n - len(m)), (0, 0)))
    if konusmalar:
        aktif = (np.abs(ses) > 0.02).astype(np.float32)
        w = int(0.25 * SR)
        aktif = np.convolve(aktif, np.ones(w) / w, mode="same").clip(0, 1)
        kazanc = 0.50 - 0.24 * np.minimum(aktif * 3, 1)  # konuşurken 0.26 (arkada net duyulur), arada 0.50
    else:
        kazanc = np.full(n, 0.70, dtype=np.float32)
    sonuc = m * kazanc[:, None] + ses[:, None]
    son_bas = max(0, n_video - int(0.8 * SR))
    zarf = np.ones(n, dtype=np.float32)
    zarf[son_bas:n_video] = np.linspace(1, 0, n_video - son_bas) ** 2
    zarf[n_video:] = 0
    sonuc = sonuc * zarf[:, None]
    tepe = float(np.max(np.abs(sonuc))) or 1.0
    sonuc = (sonuc / tepe * 0.79 * 32767).astype("<i2")  # tepe ≈ -2 dBFS: AAC kodlamada taşma/kırpılma payı
    with wave.open(str(cikti), "wb") as w_:
        w_.setnchannels(2)
        w_.setsampwidth(2)
        w_.setframerate(SR)
        w_.writeframes(sonuc.tobytes())
    return cikti
