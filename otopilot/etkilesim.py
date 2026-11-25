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
from .dagitim import GRAPH, _sayfa_anahtari
from .instagram import Instagram
from .ortak import log, marka, marka_kodlari, simdi

GUN = 3  # son 3 günün yorum/mesajları taranır (panel kimliğe göre ayıklar)
EN_COK_GONDERI = 12


def _zaman(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("+0000", "+00:00"))


def yorumlar(kod: str, ig: Instagram, sinir: dt.datetime) -> list[dict]:
    kendi = (ig.hesap() or {}).get("username", "")
    medya = ig._istek("GET", f"{ig.kimlik}/media", fields="id,caption,permalink,timestamp", limit=EN_COK_GONDERI).get("data", [])
    out = []
    for md in medya:
        c = ig._istek("GET", f"{md['id']}/comments", fields="id,text,username,timestamp", limit=50).get("data", [])
        for y in c:
            if y.get("username") == kendi or _zaman(y["timestamp"]) < sinir:
                continue
            out.append({"id": f"ig-yorum:{y['id']}", "kod": kod, "tur": "yorum", "hedef": y["id"], "kullanici": y.get("username", ""),
                        "metin": y.get("text", ""), "zaman": y["timestamp"], "link": md.get("permalink"),
                        "baglam": (md.get("caption") or "")[:200]})
    return out


def mesajlar(kod: str, sinir: dt.datetime) -> list[dict]:
    sayfa = os.environ.get(f"META_{kod.upper()}_PAGE_ID")
    if not sayfa or not os.environ.get("IG_TOKEN"):
        return []
    _, t = _sayfa_anahtari(kod)
    r = requests.get(f"{GRAPH}/{sayfa}/conversations", timeout=30, params={
        "platform": "instagram", "fields": "updated_time,messages.limit(5){id,message,from,created_time}", "limit": 20, "access_token": t})
    if not r.ok:
        raise RuntimeError(f"DM okunamadı ({r.status_code}): {r.json().get('error', {}).get('message', '')[:160]}")
    ig_id = os.environ.get(f"META_{kod.upper()}_IG_ID", "")
    out = []
    for k in r.json().get("data", []):
        for msj in (k.get("messages") or {}).get("data", []):
            kim = msj.get("from") or {}
            if kim.get("id") == ig_id or not msj.get("message") or _zaman(msj["created_time"]) < sinir:
                continue
            out.append({"id": f"ig-dm:{msj['id']}", "kod": kod, "tur": "dm", "hedef": kim.get("id", ""), "kullanici": kim.get("username", ""),
                        "metin": msj["message"], "zaman": msj["created_time"], "link": None, "baglam": ""})
    return out


def taslak(oge: dict, m: dict) -> dict:
    """Cevap taslağı. Spam/hakaret/alakasızsa boş taslak + not."""
    s = m.get("strateji") or {}
    sistem = (f"Sen {m['ad']} Instagram hesabını yöneten, sıcak ve yardımsever bir müşteri temsilcisisin. Türkçe, 'siz' diye, kısa (en çok 2-3 cümle) "
              "ve doğal yaz; robot gibi değil. Soruyu doğrudan cevapla. Yalnız aşağıdaki DOĞRU BİLGİLERE dayan; fiyat, stok, süre, kampanya gibi "
              f"bilmediğin bir şeyi uydurma, onun yerine siteye ({m['site_kisa']}) ya da DM/WhatsApp'a yönlendir. Emoji en çok 1. "
              "Spam, reklam, hakaret ya da alakasız ise taslak boş olsun ve 'not' alanına nedenini yaz. Kişisel veri isteme.\n"
              f"DOĞRU BİLGİLER: {' | '.join(map(str, m['deger_onerisi'] + list(s.get('ozellikler', []))))}")
    istem = (f"{'Gönderi altına yorum' if oge['tur'] == 'yorum' else 'Instagram DM'}: \"{oge['metin'][:800]}\"\n"
             + (f"Gönderinin konusu: {oge['baglam'][:200]}\n" if oge.get("baglam") else "")
             + 'JSON: {"taslak": "", "not": "", "oncelik": "yuksek|normal|dusuk", "sinif": "satin_alma|soru|sikayet|ovgu|oneri|spam|diger", '
               '"konu": "", "musteri": {"ad": "", "telefon": "", "ihtiyac": "", "hizmet": ""}}\n'
               "oncelik: satın alma/fiyat/rezervasyon sorusu = yuksek. sinif: satin_alma = almak, yaptırmak, fiyat/rezervasyon istemek; "
               "sikayet = memnuniyetsizlik, olumsuz deneyim, kızgınlık (cevabı özür + çözüm + DM/WhatsApp'a davet; savunma yok). "
               "konu: yorumun konusu 1-3 kelime, küçük harf (ör. 'fiyat', 'teslim süresi', 'tasarım beğenisi'). "
               "musteri: YALNIZ kişinin kendisinin yazdığı bilgiler (ad, telefon, ne istediği, hangi hizmet); yazmadıysa boş bırak, ASLA tahmin etme.")
    v = llm.json_sor(sistem, istem) or {}
    sinif = v.get("sinif") if v.get("sinif") in ("satin_alma", "soru", "sikayet", "ovgu", "oneri", "spam", "diger") else None
    m = v.get("musteri") if isinstance(v.get("musteri"), dict) else {}
    musteri = {k: str(m.get(k) or "")[:200] for k in ("ad", "telefon", "ihtiyac", "hizmet") if str(m.get(k) or "").strip()}
    return {"taslak": str(v.get("taslak") or "")[:900], "not": str(v.get("not") or "")[:200],
            "oncelik": "yuksek" if sinif in ("satin_alma", "sikayet") else (v.get("oncelik") if v.get("oncelik") in ("yuksek", "normal", "dusuk") else "normal"),
            "sinif": sinif, "konu": str(v.get("konu") or "")[:40].strip().lower(), "musteri": musteri or None}


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
