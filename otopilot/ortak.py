"""Ortak yollar, marka profili, saat ve kalıcı durum (geçmiş) yardımcıları."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import unicodedata
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

KOK = Path(__file__).resolve().parent.parent
MARKALAR = KOK / "markalar"
DURUM = KOK / "durum"
CIKTI = KOK / "cikti"
SABLON = KOK / "sablon"
FONT = KOK / "fontlar"
TR = ZoneInfo("Europe/Istanbul")

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"


def simdi() -> dt.datetime:
    zorla = os.environ.get("OTOPILOT_SAAT")  # test: "2026-11-22T12:40"
    if zorla:
        return dt.datetime.fromisoformat(zorla).replace(tzinfo=TR)
    return dt.datetime.now(TR)


def bugun() -> str:
    return simdi().date().isoformat()


def marka_kodlari() -> list[str]:
    return sorted(p.stem for p in MARKALAR.glob("*.yaml"))


def marka(kod: str) -> dict:
    with open(MARKALAR / f"{kod}.yaml", encoding="utf-8") as f:
        m = yaml.safe_load(f)
    m["logo_yol"] = str(KOK / m["logo"])
    if m.get("maskot"):
        m["maskot_yol"] = str(KOK / m["maskot"])
    return m


def slug(s: str) -> str:
    s = s.replace("ı", "i").replace("İ", "i")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


_GIZLI = [
    (re.compile(r"(access_token|api_key|key|token|client_secret|refresh_token)=([^&\s\"']+)", re.I), r"\1=***"),
    (re.compile(r"(Bearer|OAuth)\s+[A-Za-z0-9._\-]{12,}", re.I), r"\1 ***"),
    (re.compile(r"\b(EAA[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{20,}|AQ\.[A-Za-z0-9_\-]{20,}|ya29\.[A-Za-z0-9_\-]+|gsk_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,})"), "***"),
]


def gizle(metin: str) -> str:
    """Depo herkese açık: hata mesajlarında geçebilecek anahtar/jetonları loga ve kayıt dosyasına yazmadan önce siler."""
    for desen, yerine in _GIZLI:
        metin = desen.sub(yerine, metin)
    return metin


def log(*a) -> None:
    print(f"[{simdi():%H:%M:%S}]", gizle(" ".join(str(x) for x in a)), flush=True)


# ---------------- kalıcı geçmiş ----------------

def _gecmis_yol(kod: str) -> Path:
    return DURUM / kod / "gecmis.json"


def gecmis(kod: str) -> list[dict]:
    p = _gecmis_yol(kod)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def gecmis_yaz(kod: str, kayitlar: list[dict]) -> None:
    p = _gecmis_yol(kod)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(gizle(json.dumps(kayitlar, ensure_ascii=False, indent=1)), encoding="utf-8")


def gecmis_guncelle(kod: str, kayit: dict) -> None:
    """Aynı tarih+tür kaydı varsa üstüne yazar, yoksa ekler."""
    ks = gecmis(kod)
    ks = [k for k in ks if not (k.get("tarih") == kayit["tarih"] and k.get("tur") == kayit["tur"])]
    ks.append(kayit)
    ks.sort(key=lambda k: (k.get("tarih", ""), k.get("tur", "")))
    gecmis_yaz(kod, ks)


def kullanilan_anahtarlar(kod: str, gun: int = 120) -> set[str]:
    sinir = (simdi().date() - dt.timedelta(days=gun)).isoformat()
    return {k["anahtar"] for k in gecmis(kod) if k.get("anahtar") and k.get("tarih", "") >= sinir}


def json_kaydet(yol: Path, veri) -> None:
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_text(json.dumps(veri, ensure_ascii=False, indent=1), encoding="utf-8")
