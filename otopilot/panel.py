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
    if v.startswith(("HATA", "BELIRSIZ")):
        return "hata"
    return "bekliyor"


def _anlatim_satirlari(anlatim: list[str] | None) -> list[dict]:
    return [{"id": f"a{i}", "kim": f"Anlatıcı · {i + 1}. sahne", "metin": t, "ekran": False} for i, t in enumerate(anlatim or [])]


def ozet(gun: int = 14) -> list[dict]:
    from . import plan
    bugun = simdi().date().isoformat()
    sinir = (simdi().date() - dt.timedelta(days=gun)).isoformat()
    satirlar = []
    for kod in marka_kodlari():
        m = marka(kod)
        for k in gecmis(kod):
            if k.get("tur") != "reels" or k.get("tarih", "") < sinir:
                continue
            if k.get("durum") == "onizleme" and k.get("tarih", "") < bugun:
                continue  # yayın açılmadan önceki deneme üretimi; hiç paylaşılmadı, panelde "bekliyor" diye kalmasın
            p = k.get("platformlar") or {}
            satirlar.append({
                "id": f"{k['tarih'].replace('-', '')}-{kod}", "gun": k["tarih"], "saat": m["saat"]["reels"],
                "baslik": k.get("baslik", ""), "bolum_no": None, "hedef": m["ad"], "sektor": kod, "konu": k.get("konu", ""),
                "durum": {"yayinlandi": "yayinlandi", "hata": "hata"}.get(k.get("durum"), "uretildi"),
                "platformlar": [{"anahtar": a, "ad": PLATFORM_AD.get(a, a), "durum": _durum(p.get(a)),
                                 "link": str(p.get(a)).split(" ")[0] if str(p.get(a, "")).startswith("https://") else None}
                                for a in ("instagram", "instagram_hikaye", "facebook", "facebook_hikaye", "youtube", "tiktok")
                                if not str(p.get(a, "")).startswith("atlandı") and (a != "facebook_hikaye" or a in p)],  # hesabı bağlanmamış platform gösterilmez
                "satirlar": _anlatim_satirlari(k.get("anlatim")), "duzenlenebilir": False, "kilit_nedeni": "Yayınlandı",
                "gorsel": k.get("gorsel"), "neden": None,
                "format": k.get("format"), "skor": k.get("skor"), "olcum": k.get("olcum"),
            })
        yapildi = {k.get("tarih") for k in gecmis(kod) if k.get("tur") == "reels"}
        for g, o in plan.oku(kod).items():  # ileri tarihli plan (bugün henüz üretilmediyse bugünkü de)
            if g < bugun or g in yapildi:
                continue
            s = o["senaryo"]
            kapak = next((sh for sh in s["sahneler"] if sh.get("tip") == "kapak"), s["sahneler"][0])
            ekran = [{"id": "k.baslik", "kim": "Kapak başlığı (ekranda)", "metin": kapak.get("baslik") or "", "ekran": True}]
            if kapak.get("alt"):
                ekran.append({"id": "k.alt", "kim": "Kapak alt yazısı (ekranda)", "metin": kapak["alt"], "ekran": True})
            satirlar.append({
                "id": o["id"], "gun": g, "saat": m["saat"]["reels"], "baslik": kapak.get("baslik") or o["konu"], "bolum_no": None,
                "hedef": m["ad"], "sektor": kod, "konu": o["konu"], "durum": "senaryo", "platformlar": [],
                "satirlar": ekran + _anlatim_satirlari(o.get("anlatim")),
                "duzenlenebilir": g > bugun, "kilit_nedeni": None if g > bugun else "Bugün üretiliyor",
                "gorsel": o.get("gorsel"), "neden": o.get("neden"), "format": o.get("format"),
            })
    return sorted(satirlar, key=lambda x: (x["gun"], x["saat"]))


def ekler() -> dict:
    from . import plan
    return {"urunler": [{"anahtar": k, "ad": marka(k)["ad"]} for k in marka_kodlari()],
            "markalar": {k: plan.buyume(k) for k in marka_kodlari()}}


def _yanit_ozeti(r) -> str:
    """Depo ve Actions logları herkese açık: panel yanıtının içeriği yazılmaz, yalnız durum kodu ve alan/öğe sayıları."""
    try:
        j = r.json()
    except Exception:
        return f"{r.status_code} (JSON değil)"
    if isinstance(j, dict):
        alanlar = ", ".join(f"{k}={len(v) if isinstance(v, (list, dict)) else 1}" for k, v in list(j.items())[:12])
        return f"{r.status_code} [{alanlar}]"
    return f"{r.status_code} ({type(j).__name__}, {len(j) if isinstance(j, list) else 1} öğe)"


def _belge() -> str:
    url, tok = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"), os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
    if not url or not tok:
        raise RuntimeError("OIDC yok (akışa 'permissions: id-token: write' gerekir)")
    r = requests.get(url, params={"audience": AUD}, headers={"Authorization": f"bearer {tok}"}, timeout=30)
    r.raise_for_status()
    return r.json()["value"]


def gonder(donus: bool = False):
    """Takvimi panele bırakır; donus=True ise panelin bekleyen düzenleme/istek/tanıtımlarını döndürür (hata olursa {})."""
    try:
        r = requests.post(f"{PANEL}/api/icerik-takvimi/senkron/{KANAL}", json={"bolumler": ozet(), "ekler": ekler()}, timeout=60,
                          headers={"Authorization": f"Bearer {_belge()}", "X-Requested-With": "ajans-web"})
        log(f"panel: {_yanit_ozeti(r)}")
        if donus:
            return r.json() if r.ok else {}
    except Exception as e:
        log(f"panel senkronu atlandı: {e}")
    return {} if donus else 0


def onay(yuk: dict) -> None:
    if not any(yuk.get(k) for k in ("uygulanan", "reddedilen", "tanitim")):
        return
    try:
        r = requests.post(f"{PANEL}/api/icerik-takvimi/senkron/{KANAL}/onay", json=yuk, timeout=60,
                          headers={"Authorization": f"Bearer {_belge()}", "X-Requested-With": "ajans-web"})
        log(f"panel onay: {_yanit_ozeti(r)}")
    except Exception as e:
        log(f"panel onayı gönderilemedi: {e}")


if __name__ == "__main__":
    sys.exit(gonder())


def etkilesim(yuk: dict) -> dict | None:
    """Yorum/DM köprüsü: {adaylar: [id], durumlar} → {bilinmeyen, gonderilecek}; {yeni: [...], sonuc: [...]} → panel kaydeder.
    İçerik loglanmaz (depo herkese açık). Panel erişilemezse None."""
    try:
        r = requests.post(f"{PANEL}/api/icerik-takvimi/senkron/{KANAL}/etkilesim", json=yuk, timeout=60,
                          headers={"Authorization": f"Bearer {_belge()}", "X-Requested-With": "ajans-web"})
        if not r.ok:
            log(f"panel etkileşim: {r.status_code}")
            return None
        return r.json()
    except Exception as e:
        log(f"panel etkileşimine ulaşılamadı: {type(e).__name__}")
        return None
