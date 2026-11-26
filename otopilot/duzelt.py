"""Panel "Düzelt" iş emri (2026-11-26, Mücahit: "hata verenleri tek tıkla düzeltebileceğim buton, tüm hesaplara ve ekleyeceklerime").

Akış (duzelt.yml; VDS tetikleyicisi panel kuyruğunu görünce başlatır):
  1. Panel senkronundan "duzelt" iş emirlerini alır, panele "çalışıyor" bildirir.
  2. Markanın her platform bağlantısını OKUYARAK denetler (paylaşım yapmaz): Instagram hesabı, Facebook sayfa anahtarı, YouTube yetkisi, TikTok.
  3. Bugünkü içerikte KESİN hata almış platformları yeniden gönderir (calistir.eksik, elle=True). Sonucu belirsiz olan ASLA yeniden
     gönderilmez (çift paylaşım olmasın); saati gelmemiş içerik gönderilmez (eksik yalnız bugün YAYINLANMIŞ içeriği tamamlar).
  4. Adım adım raporu panele yazar; insan gerektiren adım (ör. Meta anahtarı yenileme) varsa nereden yapılacağını bağlantısıyla verir.
Bağlantı durumu durum/baglanti.json'a da yazılır (panel tablosundaki rozetler). Depo herkese açık: kimlik/anahtar/hesap adı loga ve dosyaya
YAZILMAZ; mesajlar genel sınıflardır."""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

import requests

from . import dagitim, panel
from .ortak import KOK, gecmis, gizle, log, marka_kodlari, simdi

DOSYA = KOK / "durum" / "baglanti.json"
META_ANAHTAR = ("Meta sistem kullanıcısı anahtarını yenile", "https://business.facebook.com/settings/system-users")
META_VARLIK = ("Sayfa ve Instagram hesabını sistem kullanıcısına ata", "https://business.facebook.com/settings/system-users")
YT_YETKI = ("YouTube kanal yetkisini kontrol et", "https://myaccount.google.com/connections")
PLATFORM_AD = {"instagram": "Instagram", "instagram_hikaye": "Instagram hikâye", "facebook": "Facebook Reels",
               "facebook_hikaye": "Facebook hikâye", "youtube": "YouTube Shorts", "tiktok": "TikTok"}


def _sinif(metin: str) -> str:
    """Hata metnini kimlik/anahtar içermeyen genel bir açıklamaya çevirir."""
    m = (metin or "").lower()
    if any(x in m for x in ("error validating access token", "session has expired", "invalid oauth", "code\": 190", "'code': 190", "(#190)")):
        return "Meta anahtarı geçersiz ya da süresi dolmuş"
    if "invalid_grant" in m or "token has been expired or revoked" in m:
        return "Yetki iptal edilmiş ya da süresi dolmuş"
    if "permission" in m or "(#10)" in m or "(#200)" in m or "code\": 10" in m:
        return "İzin eksik (anahtar bu hesaba yetkili değil)"
    if "timed out" in m or "timeout" in m or "connection" in m:
        return "Ağ zaman aşımı (geçici olabilir)"
    if "rate limit" in m or "(#4)" in m or "(#32)" in m or "429" in m:
        return "Platform hız sınırı (geçici)"
    return "Bağlantı denemesi başarısız"


def baglanti(kod: str) -> dict:
    """{platform: {durum: tamam|hata|yok, mesaj, zaman}} — yalnız okuma istekleri."""
    from .instagram import Instagram, InstagramHatasi
    z = simdi().isoformat(timespec="seconds")
    out: dict = {}
    ig = Instagram(kod)
    if not ig.hazir:
        out["instagram"] = {"durum": "yok", "mesaj": "Instagram anahtarı/kimliği tanımlı değil", "zaman": z}
    else:
        try:
            ig.hesap()
            out["instagram"] = {"durum": "tamam", "mesaj": "Hesap okunabiliyor", "zaman": z}
        except InstagramHatasi as e:
            out["instagram"] = {"durum": "hata", "mesaj": _sinif(str(e)), "zaman": z}
        except Exception as e:  # noqa: BLE001
            out["instagram"] = {"durum": "hata", "mesaj": _sinif(str(e)), "zaman": z}
    if dagitim.PLATFORMLAR["facebook"][0](kod):
        try:
            sayfa, t = dagitim._sayfa_anahtari(kod)
            r = requests.get(f"{dagitim.GRAPH}/{sayfa}", params={"fields": "id", "access_token": t}, timeout=30)
            out["facebook"] = {"durum": "tamam", "mesaj": "Sayfa anahtarı geçerli", "zaman": z} if r.ok else \
                {"durum": "hata", "mesaj": _sinif(r.text), "zaman": z}
        except Exception as e:  # noqa: BLE001
            out["facebook"] = {"durum": "hata", "mesaj": _sinif(str(e)), "zaman": z}
    else:
        out["facebook"] = {"durum": "yok", "mesaj": "Facebook sayfası tanımlı değil", "zaman": z}
    if dagitim.PLATFORMLAR["youtube"][0](kod):
        try:
            r = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
                "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
                "refresh_token": dagitim._e("YT_<KOD>_REFRESH_TOKEN", kod), "grant_type": "refresh_token"})
            out["youtube"] = {"durum": "tamam", "mesaj": "YouTube yetkisi geçerli", "zaman": z} if r.ok and "access_token" in r.json() else \
                {"durum": "hata", "mesaj": _sinif(r.text), "zaman": z}
        except Exception as e:  # noqa: BLE001
            out["youtube"] = {"durum": "hata", "mesaj": _sinif(str(e)), "zaman": z}
    if dagitim.PLATFORMLAR["tiktok"][0](kod):
        out["tiktok"] = {"durum": "tamam", "mesaj": "Anahtar tanımlı (TikTok yalnız taslağa gönderir)", "zaman": z}
    return out


def kaydet(veri: dict) -> None:
    eski = {}
    try:
        eski = json.loads(DOSYA.read_text())
    except Exception:  # noqa: BLE001
        pass
    DOSYA.parent.mkdir(parents=True, exist_ok=True)
    DOSYA.write_text(json.dumps({**eski, **veri}, ensure_ascii=False, indent=1))


def oku() -> dict:
    try:
        return json.loads(DOSYA.read_text())
    except Exception:  # noqa: BLE001
        return {}


def _bugun_platformlar(kod: str) -> dict:
    tarih = simdi().date().isoformat()
    k = next((x for x in gecmis(kod) if x.get("tarih") == tarih and x.get("tur") == "reels"), None)
    return dict((k or {}).get("platformlar") or {}), k


def _son_gunler_hatalari(kod: str, gun: int = 3) -> list[str]:
    """Bugünden önceki günlerde gönderilememiş platformlar (geç kaldığı için yeniden gönderilmez, bilgi olarak yazılır)."""
    bugun = simdi().date()
    sinir = (bugun - dt.timedelta(days=gun)).isoformat()
    out = []
    for k in gecmis(kod):
        if k.get("tur") != "reels" or not (sinir <= k.get("tarih", "") < bugun.isoformat()):
            continue
        for p, v in (k.get("platformlar") or {}).items():
            if str(v).startswith(("HATA", "BELIRSIZ")):
                out.append(f"{k['tarih']} {PLATFORM_AD.get(p, p)}")
    return out


def rapor(kod: str) -> dict:
    """Bir markayı düzeltir; panel raporu döner."""
    from .calistir import eksik
    adimlar, eylemler = [], []
    bg = baglanti(kod)
    kaydet({kod: bg})
    for p, x in bg.items():
        if x["durum"] != "yok":
            adimlar.append({"ad": f"{PLATFORM_AD.get(p, p)} bağlantısı", "durum": "tamam" if x["durum"] == "tamam" else "hata", "mesaj": x["mesaj"]})
    if any(x["durum"] == "hata" and "Meta anahtarı" in x["mesaj"] for p, x in bg.items() if p in ("instagram", "facebook")):
        eylemler.append(META_ANAHTAR)
    elif any(x["durum"] == "hata" and "İzin eksik" in x["mesaj"] for p, x in bg.items() if p in ("instagram", "facebook")):
        eylemler.append(META_VARLIK)
    if bg.get("youtube", {}).get("durum") == "hata":
        eylemler.append(YT_YETKI)
    once, k = _bugun_platformlar(kod)
    if not k:
        adimlar.append({"ad": "Bugünkü paylaşım", "durum": "bilgi", "mesaj": "Bugün henüz paylaşım yapılmadı; saati gelince hat kendisi paylaşır."})
    elif k.get("durum") != "yayinlandi":
        adimlar.append({"ad": "Bugünkü paylaşım", "durum": "uyari", "mesaj": "Bugünkü içerik yayınlanamadı; Instagram'a gitmeden diğer platformlara gönderilmez."})
    else:
        try:
            eksik([kod], elle=True)
        except Exception as e:  # noqa: BLE001
            adimlar.append({"ad": "Eksik platformları yeniden gönderme", "durum": "hata", "mesaj": _sinif(str(e))})
        sonra, _ = _bugun_platformlar(kod)
        for p, v in sonra.items():
            eski, yeni = str(once.get(p, "")), str(v)
            ad = PLATFORM_AD.get(p, p)
            if yeni.startswith("http") and not eski.startswith("http"):
                adimlar.append({"ad": f"{ad} yeniden gönderildi", "durum": "tamam", "mesaj": None})
            elif yeni.startswith("HATA"):
                adimlar.append({"ad": f"{ad} hâlâ gönderilemiyor", "durum": "hata", "mesaj": _sinif(yeni)})
            elif yeni.startswith("BELIRSIZ"):
                adimlar.append({"ad": f"{ad} sonucu belirsiz", "durum": "uyari",
                                "mesaj": "Çift paylaşım olmasın diye yeniden gönderilmedi; hesapta görünüyor mu bakın."})
        if all(str(v).startswith(("http", "tiktok-taslak", "atlandı")) for v in sonra.values()):
            adimlar.append({"ad": "Bugünkü paylaşım", "durum": "tamam", "mesaj": "Tüm açık platformlarda yayında."})
    eski_h = _son_gunler_hatalari(kod)
    if eski_h:
        adimlar.append({"ad": "Önceki günlerde gidemeyenler", "durum": "uyari",
                        "mesaj": ", ".join(eski_h[:6]) + " — geç kaldığı için yeniden gönderilmedi (aynı gün iki paylaşım olmasın)."})
    durum = "sorun" if any(a["durum"] == "hata" for a in adimlar) else "tamam"
    return {"durum": durum, "adimlar": adimlar, "eylemler": [{"ad": a, "link": b} for a, b in eylemler]}


def calistir() -> int:
    cevap = panel.gonder(donus=True) or {}
    isler = [k for k in cevap.get("komutlar", []) if k.get("tur") == "duzelt"]
    kodlar = marka_kodlari()
    if not isler:
        log("bekleyen düzelt iş emri yok; yalnız bağlantı durumu yenilendi")
        kaydet({k: baglanti(k) for k in kodlar})
        panel.gonder()
        return 0
    for i in isler:
        kod = (i.get("deger") or {}).get("marka")
        if kod not in kodlar:
            panel.onay({"uygulanan": [i["id"]], "duzelt": [{"id": i["id"], "durum": "sorun",
                        "adimlar": [{"ad": "Marka", "durum": "hata", "mesaj": "Bu marka IG Otopilot hattında tanımlı değil."}]}]})
            continue
        panel.onay({"duzelt": [{"id": i["id"], "durum": "calisiyor", "adimlar": [{"ad": "Hat çalışıyor", "durum": "bilgi", "mesaj": "Bağlantılar denetleniyor"}]}]})
        try:
            r = rapor(kod)
        except Exception as e:  # noqa: BLE001
            log(f"düzelt hata: {gizle(type(e).__name__)}")
            r = {"durum": "sorun", "adimlar": [{"ad": "Düzeltme yarıda kaldı", "durum": "hata", "mesaj": _sinif(str(e))}], "eylemler": []}
        log(f"düzelt: {kod} → {r['durum']} ({len(r['adimlar'])} adım)")
        panel.onay({"uygulanan": [i["id"]], "duzelt": [{"id": i["id"], **r}]})
    panel.gonder()  # tablo ve bağlantı rozetleri hemen tazelensin
    return 0


if __name__ == "__main__":
    sys.exit(calistir())
