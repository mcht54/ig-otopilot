"""Yorum ve DM yanıtlama (insan onaylı). Her 20 dakikada:
  1) 4 hesabın son gönderilerindeki yeni yorumları ve Instagram DM'lerini toplar,
  2) panele hangilerinin yeni olduğunu sorar (tekrar taslak yazılmaz),
  3) yeniler için yapay zekâ markanın diliyle, yalnız doğru bilgiyle cevap TASLAĞI yazar,
  4) panele bırakır (telefona bildirim gider); panelde onaylanan cevapları gönderir ve sonucu bildirir.
GİZLİLİK: Depo herkese açık. Yorum/mesaj içeriği ve kullanıcı adları depoya, loglara, dosyaya YAZILMAZ; yalnız özel panel
veritabanına gider. Loglarda yalnız sayılar görünür.
"""
from __future__ import annotations

import datetime as dt
import os

import requests

from . import llm
from .guvenlik import uygunsuz
from .dagitim import GRAPH, _sayfa_anahtari
from .instagram import Instagram
from .ortak import log, marka, marka_kodlari, simdi

from . import etkilesim_ortak as ortak

GUN = ortak.GUN  # son 3 günün yorum/mesajları taranır (panel kimliğe göre ayıklar)
EN_COK_GONDERI = ortak.EN_COK_GONDERI
# 2026-11-27: toplama/taslak/sınıflama ortak çekirdekte (~/Documents/mcht-etkilesim; tüm sosyal hatlarla aynı kod). Burada yalnız bu hattın
# anahtarları ve marka bilgisi bağlanır. Öğelerde kaynak içerik (medya) panele gider: "hangi içerik kaç müşteri adayı getirdi".


def yorumlar(kod: str, ig: Instagram, sinir: dt.datetime) -> list[dict]:
    return ortak.yorumlar(ig._istek, ig.kimlik, kod, sinir, kendi=(ig.hesap() or {}).get("username", ""))


def mesajlar(kod: str, sinir: dt.datetime) -> list[dict]:
    sayfa = os.environ.get(f"META_{kod.upper()}_PAGE_ID")
    if not sayfa or not os.environ.get("IG_TOKEN"):
        return []
    _, t = _sayfa_anahtari(kod)

    def istek(yontem, yol, **p):
        r = requests.request(yontem, f"{GRAPH}/{yol}", timeout=30, params={**p, "access_token": t})
        if not r.ok:
            raise RuntimeError(f"DM okunamadı ({r.status_code}): {r.json().get('error', {}).get('message', '')[:160]}")
        return r.json()
    return ortak.mesajlar(istek, f"{sayfa}/conversations", os.environ.get(f"META_{kod.upper()}_IG_ID", ""), kod, sinir)


def taslak(oge: dict, m: dict) -> dict:
    """Cevap taslağı. Spam/hakaret/alakasızsa boş taslak + not."""
    s = m.get("strateji") or {}
    hesap = {"ad": m["ad"], "site": m["site_kisa"], "bilgiler": list(m["deger_onerisi"]) + list(s.get("ozellikler", []))}
    return ortak.taslak(oge, hesap, lambda si, i: llm.json_sor(si, i), uygunsuz)


def gonder(oge: dict) -> None:
    kod, metin = oge["kod"], oge["metin"]
    if oge["tur"] == "yorum":
        Instagram(kod)._istek("POST", f"{oge['hedef']}/replies", message=metin)
    elif oge["tur"] == "dm":
        sayfa, t = _sayfa_anahtari(kod)
        r = requests.post(f"{GRAPH}/{sayfa}/messages", timeout=30, params={"access_token": t},
                          json={"recipient": {"id": oge["hedef"]}, "message": {"text": metin}, "messaging_type": "RESPONSE"})
        if not r.ok:
            raise RuntimeError(r.json().get("error", {}).get("message", f"HTTP {r.status_code}")[:200])
    else:
        raise RuntimeError("bilinmeyen tür")


def calistir() -> int:
    from . import panel
    if os.environ.get("ETK_DENEME") == "1":
        return deneme()
    sinir = simdi().astimezone(dt.timezone.utc) - dt.timedelta(days=GUN)
    adaylar, durumlar = [], {}
    for kod in marka_kodlari():
        ig = Instagram(kod)
        d = {}
        if ig.hazir:
            try:
                adaylar += yorumlar(kod, ig, sinir)
                d["yorum"] = "ok"
            except Exception as e:
                d["yorum"] = f"hata: {str(e)[:160]}"
            try:
                adaylar += mesajlar(kod, sinir)
                d["dm"] = "ok"
            except Exception as e:
                d["dm"] = f"hata: {str(e)[:160]}"
        durumlar[kod] = d
    yanit = panel.etkilesim({"adaylar": [a["id"] for a in adaylar], "durumlar": durumlar})
    if yanit is None:
        log("etkileşim: panele ulaşılamadı; sonraki turda yeniden denenecek")
        return 0
    bilinmeyen = set(yanit.get("bilinmeyen", []))
    yeni = []
    for a in adaylar:
        if a["id"] in bilinmeyen:
            a.update(taslak(a, marka(a["kod"])))
            yeni.append(a)
    sonuc = []
    for g in yanit.get("gonderilecek", []):
        try:
            gonder(g)
            sonuc.append({"id": g["id"], "durum": "gonderildi"})
        except Exception as e:
            sonuc.append({"id": g["id"], "durum": "hata", "neden": str(e)[:200]})
    if yeni or sonuc:
        panel.etkilesim({"yeni": yeni, "sonuc": sonuc})
    log(f"etkileşim: {len(adaylar)} aday, {len(yeni)} yeni (taslak yazıldı; {sum(1 for a in yeni if a.get('sinif') == 'satin_alma')} müşteri adayı, "
        f"{sum(1 for a in yeni if a.get('sinif') == 'sikayet')} şikâyet), {sum(1 for s in sonuc if s['durum'] == 'gonderildi')} cevap gönderildi, "
        f"{sum(1 for s in sonuc if s['durum'] == 'hata')} hata; durum: " + ", ".join(f"{k} yorum={v.get('yorum', '-')[:4]} dm={v.get('dm', '-')[:4]}" for k, v in durumlar.items()))
    return 0


def deneme() -> int:
    """Yazmadan dene (ETK_DENEME=1): yorum/DM okur, sınıflar; panele yazmaz, cevap göndermez. Logda yalnız sayılar (depo herkese açık)."""
    import json
    sinir = simdi().astimezone(dt.timezone.utc) - dt.timedelta(days=int(os.environ.get("ETK_GUN", "30")))
    out = {"adaylar": [], "durumlar": {}}
    for kod in marka_kodlari():
        ig = Instagram(kod)
        d = {}
        if ig.hazir:
            for ad, f in (("yorum", lambda: yorumlar(kod, ig, sinir)), ("dm", lambda: mesajlar(kod, sinir))):
                try:
                    out["adaylar"] += f()
                    d[ad] = "ok"
                except Exception as e:  # noqa: BLE001
                    d[ad] = f"hata: {str(e)[:120]}"
        out["durumlar"][kod] = d
    for a in out["adaylar"][:40]:
        a.update(taslak(a, marka(a["kod"])))
    ozet = ortak.ozet_say({"adaylar": out["adaylar"][:40], "durumlar": out["durumlar"]})
    ozet["toplam_aday"] = len(out["adaylar"])
    ozet["kaynakli"] = sum(1 for a in out["adaylar"] if a.get("medya"))
    log("etkileşim DENEME (yazılmadı): " + json.dumps(ozet, ensure_ascii=False))
    return 0
