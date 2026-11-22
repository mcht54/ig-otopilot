"""MCHT panel "İçerik takvimi" senkronu (anahtarsız): GitHub Actions OIDC belgesiyle son 14 günün
paylaşımlarını ve platform durumlarını panele gönderir. Dijital Çırak'la aynı uç ve biçim; kanal: ig_otopilot.
Panel erişilemezse akış BOZULMAZ (hata yazılır, çıkış 0).

Kullanım (Actions'ta, `permissions: id-token: write`): python -m otopilot.panel
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import requests

from .dagitim import PLATFORM_AD
from .ortak import gecmis, log, marka, marka_kodlari, simdi

PANEL = os.environ.get("PANEL_URL", "https://panel.mchttasarim.com.tr")
AUD = "mchttasarim-panel-icerik"
KANAL = "ig_otopilot"


def _durum(v: str) -> str:
    v = str(v or "")
    if v.startswith("tiktok-taslak"):
        return "taslak"
    if v.startswith("http"):
        return "paylasildi"
    if v.startswith("HATA"):
        return "hata"
    return "bekliyor"


def ozet(gun: int = 14) -> list[dict]:
    sinir = (simdi().date() - dt.timedelta(days=gun)).isoformat()
    satirlar = []
    for kod in marka_kodlari():
        m = marka(kod)
        for k in gecmis(kod):
            if k.get("tur") != "reels" or k.get("tarih", "") < sinir:
                continue
            p = k.get("platformlar") or {}
            satirlar.append({
                "id": f"{k['tarih'].replace('-', '')}-{kod}", "gun": k["tarih"], "saat": m["saat"]["reels"],
                "baslik": k.get("baslik", ""), "bolum_no": None, "hedef": m["ad"], "sektor": kod, "konu": k.get("konu", ""),
                "durum": {"yayinlandi": "yayinlandi", "hata": "hata"}.get(k.get("durum"), "uretildi"),
                "platformlar": [{"anahtar": a, "ad": PLATFORM_AD.get(a, a), "durum": _durum(p.get(a)),
                                 "link": str(p.get(a)).split(" ")[0] if str(p.get(a, "")).startswith("https://") else None}
                                for a in ("instagram", "instagram_hikaye", "facebook", "youtube", "tiktok")],
                "satirlar": [], "duzenlenebilir": False, "kilit_nedeni": "Otomatik üretildi",
                "format": k.get("format"), "skor": k.get("skor"), "olcum": k.get("olcum"),
            })
    return sorted(satirlar, key=lambda x: (x["gun"], x["saat"]))


def _belge() -> str:
    url, tok = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"), os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not url or not tok:
        raise RuntimeError("OIDC yok (akışa 'permissions: id-token: write' gerekir)")
    r = requests.get(url, params={"audience": AUD}, headers={"Authorization": f"bearer {tok}"}, timeout=30)
    r.raise_for_status()
    return r.json()["value"]


def gonder() -> int:
    try:
        r = requests.post(f"{PANEL}/api/icerik-takvimi/senkron/{KANAL}", json={"bolumler": ozet(), "ekler": {}}, timeout=60,
                          headers={"Authorization": f"Bearer {_belge()}", "X-Requested-With": "ajans-web"})
        log(f"panel: {r.status_code} {r.text[:160]}")
    except Exception as e:
        log(f"panel senkronu atlandı: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(gonder())
