"""Davetiyeler.TR içerik formatları — gerçek ürün fotoğrafları, gerçek dijital davetiye animasyonları."""
from __future__ import annotations

import re

from . import getir, iddia_temizle, sitede_var, temiz

SITE = "https://www.davetiyeler.tr"
API = f"{SITE}/wp-json/wc/store/v1"

# Ay → öne çıkacak kategoriler (sezon mantığı: kış nişan/nikah planı, bahar-yaz düğün/kına, yaz sünnet)
SEZON = {
    1: ["nisan-davetiyeleri", "nikah-davetiyeleri", "luks-davetiyeler"],
    2: ["nisan-davetiyeleri", "dugun-davetiyesi", "seffaf-davetiyeler"],
    3: ["dugun-davetiyesi", "kina-davetiyeleri", "muhurlu-davetiyeler"],
    4: ["dugun-davetiyesi", "kina-davetiyeleri", "yeni-sezon-davetiyeler"],
    5: ["dugun-davetiyesi", "sunnet-davetiyeleri", "kina-davetiyeleri"],
    6: ["sunnet-davetiyeleri", "dugun-davetiyesi", "kina-davetiyeleri"],
    7: ["sunnet-davetiyeleri", "dugun-davetiyesi", "seffaf-davetiyeler"],
    8: ["dugun-davetiyesi", "kina-davetiyeleri", "sunnet-davetiyeleri"],
    9: ["dugun-davetiyesi", "nisan-davetiyeleri", "luks-davetiyeler"],
    10: ["nikah-davetiyeleri", "nisan-davetiyeleri", "kare-davetiyeler"],
    11: ["nikah-davetiyeleri", "minimal-nikah-davetiyesi", "luks-nikah-davetiyesi"],
    12: ["nikah-davetiyeleri", "nisan-davetiyeleri", "yeni-sezon-davetiyeler"],
}

KATEGORI_AD = {
    "dugun-davetiyesi": "Düğün davetiyesi", "nisan-davetiyeleri": "Nişan davetiyesi", "nikah-davetiyeleri": "Nikah davetiyesi",
    "kina-davetiyeleri": "Kına davetiyesi", "sunnet-davetiyeleri": "Sünnet davetiyesi", "luks-davetiyeler": "Lüks davetiye",
    "seffaf-davetiyeler": "Şeffaf davetiye", "muhurlu-davetiyeler": "Mühürlü davetiye", "kare-davetiyeler": "Kare davetiye",
    "yeni-sezon-davetiyeler": "Yeni sezon davetiye", "minimal-nikah-davetiyesi": "Minimal nikah davetiyesi",
    "luks-nikah-davetiyesi": "Lüks nikah davetiyesi", "kampanyali-davetiyeler": "Kampanyalı davetiye",
}


def kategoriler() -> dict[str, dict]:
    return {c["slug"]: c for c in getir(f"{API}/products/categories", params={"per_page": 100}).json()}


def urunler(kategori_id: int, adet: int = 40, sayfa: int = 1) -> list[dict]:
    veri = getir(f"{API}/products", params={"category": kategori_id, "per_page": adet, "page": sayfa, "orderby": "date"}).json()
    sonuc = []
    for p in veri:
        if not p.get("images"):
            continue
        kod = re.search(r"Stok kodu:?\s*([A-Z0-9-]{4,})", temiz(p.get("description", "")))
        sonuc.append({
            "id": p["id"], "ad": temiz(p["name"]), "url": p["permalink"], "gorsel": p["images"][0]["src"],
            "kisa": temiz(p.get("short_description", ""))[:300], "kod": p.get("sku") or (kod.group(1) if kod else ""),
            "fiyat": int(p["prices"]["price"]) / 100 if p["prices"].get("price") else 0,
        })
    return sonuc


def kisa_ad(ad: str, en_fazla: int = 28) -> str:
    ad = re.sub(r"\s*[–-]\s*\d+\s*$", "", ad)
    ad = re.sub(r"\s*\b[Dd]avetiye(si|leri|ler)?\b", "", ad)
    ad = re.sub(r"\s{2,}", " ", ad).strip(" –-")
    return ad if len(ad) <= en_fazla else ad[: en_fazla - 1].rsplit(" ", 1)[0] + "…"


def _kategori_sec(ctx) -> tuple[str, dict]:
    kats = kategoriler()
    ay = ctx["simdi"].month
    secenek = [s for s in SEZON[ay] if s in kats]
    # aynı kategori 2 hafta içinde tekrar etmesin
    taze = [s for s in secenek if not any(k.startswith(f"kategori:{s}:") for k in ctx["kullanilan_yakin"])] or secenek
    slug = ctx["rnd"].choice(taze)
    return slug, kats[slug]


def model_vitrin(ctx) -> dict | None:
    slug, kat = _kategori_sec(ctx)
    havuz = urunler(kat["id"], 60, sayfa=ctx["rnd"].randint(1, max(1, min(5, kat["count"] // 60))))
    havuz = [u for u in havuz if f"urun:{u['id']}" not in ctx["kullanilan"]] or havuz
    ctx["rnd"].shuffle(havuz)
    sec = havuz[:4]
    if len(sec) < 4:
        return None
    tur = KATEGORI_AD.get(slug, kat["name"])
    return {
        "anahtar": f"kategori:{slug}:{ctx['tarih']}",
        "ek_anahtarlar": [f"urun:{u['id']}" for u in sec],
        "konu": f"{tur} modelleri",
        "anahtar_kelime": f"{tur.lower()} modelleri",
        "olgular": [f"Kategori: {kat['name']} ({kat['count']} model)", *[f"Model {i+1}: {u['ad']} — {u['kisa'][:140]}" for i, u in enumerate(sec)],
                    "Basılı davetiyede fiyat teklif usulüdür; adet 100-1000 arası seçilir.",
                    "Basılı davetiye alana ₺650+KDV değerinde dijital davetiye hediye (sitede yazıyor)."],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": sec[0]["gorsel"], "etiket": tur, "baslik": f"{tur} seçemeyenlere 4 model", "alt": "Sonuna kadar izleyin, favorinizi yazın"},
            {"tur": "kart", "tip": "urun", "sure": 2.6, "gorsel": sec[1]["gorsel"], "etiket": "Model 2", "baslik": kisa_ad(sec[1]["ad"], 40)},
            {"tur": "kart", "tip": "urun", "sure": 2.6, "gorsel": sec[2]["gorsel"], "etiket": "Model 3", "baslik": kisa_ad(sec[2]["ad"], 40)},
            {"tur": "kart", "tip": "izgara", "sure": 4.0, "zemin": sec[3]["gorsel"], "gorseller": [u["gorsel"] for u in sec],
             "yazilar": [kisa_ad(u["ad"]) for u in sec], "baslik": "Hangisi sizin tarzınız?", "alt": "Yoruma numarasını yazın"},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": f"{kat['count']} {tur.lower()} modeli", "alt": "Basılı davetiyeye dijital davetiye hediye"},
        ],
        "hikaye": {"gorsel": sec[0]["gorsel"], "etiket": "Yeni modeller", "baslik": f"{tur} arayanlara 4 öneri", "alt": "Hangisini seçerdiniz?"},
    }


def dijital_modeller() -> list[dict]:
    t = getir(f"{SITE}/urun/dijital-davetiye-paketi/").text
    sluglar = list(dict.fromkeys(re.findall(r"/d/(ornek-[a-z0-9-]+)/", t)))
    return [{"slug": s, "url": f"{SITE}/d/{s}/", "ad": s.removeprefix("ornek-").removeprefix("k-").replace("-", " ").title()} for s in sluglar]


def dijital_davetiye(ctx) -> dict | None:
    modeller = dijital_modeller()
    kalan = [m for m in modeller if f"dijital:{m['slug']}" not in ctx["kullanilan"]] or modeller
    if not kalan:
        return None
    m = ctx["rnd"].choice(kalan)
    urun = getir(f"{API}/products", params={"slug": "dijital-davetiye-paketi"}).json()
    fiyat = int(urun[0]["prices"]["price"]) / 100 if urun else 0
    ozellik = temiz(urun[0]["short_description"]) if urun else "Animasyonlu açılışlı, LCV'li, geri sayımlı ve haritalı dijital davetiye."
    sunnet = "sunnet" in m["slug"]
    return {
        "anahtar": f"dijital:{m['slug']}",
        "konu": f"Dijital davetiye modeli: {m['ad']}",
        "anahtar_kelime": "dijital davetiye",
        "olgular": [f"Model: {m['ad']} ({'sünnet' if sunnet else 'düğün/nişan/kına'})", f"Ürün açıklaması: {ozellik}",
                    f"Fiyat: ₺{fiyat:,.0f}".replace(",", ".") + " (sitedeki fiyat)" if fiyat else "Fiyat sitede",
                    "Oluşturma 4 adım: model seç, bilgiler, müzik ve fotoğraf, katılım (LCV) ve kaydet.",
                    "Davetiye tek bağlantıyla WhatsApp'tan paylaşılır; misafir LCV ile katılımını bildirir.",
                    f"Canlı örnek: {m['url']}"],
        "sahneler": [
            {"tur": "sayfa", "url": m["url"], "sure": 8.5, "ust_yazi": "Davetiyeniz WhatsApp'ta böyle açılır",
             "eylemler": [{"t": 1.6, "tikla": "davetiyeyi aç"}, {"t": 4.8, "ust_yazi": "Animasyonlu açılış + müzik"}]},
            {"tur": "sayfa", "url": m["url"], "sure": 6.5, "once_tikla": ["atla"], "once_js": ["document.querySelectorAll('.__ust').forEach(e=>e.remove())"],
             "kaydir": True, "kaydir_px": 2400, "kaydir_bas": 0.4, "ust_yazi": "Geri sayım, harita, LCV tek linkte"},
            {"tur": "kart", "tip": "liste", "sure": 5.0, "etiket": "4 adımda hazır", "baslik": "Dijital davetiye nasıl oluşturulur?",
             "maddeler": ["Modelinizi seçin", "İsim, tarih ve mekânı yazın", "Müzik ve fotoğraf ekleyin", "Linki WhatsApp'tan gönderin"]},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Kâğıt yok, kargo yok, bekleme yok", "alt": f"Dijital davetiye ₺{fiyat:,.0f}".replace(",", ".") if fiyat else "Hemen oluşturun"},
        ],
        "hikaye": {"gorsel": None, "kayit_url": m["url"], "etiket": "Dijital davetiye", "baslik": "Davetiyeniz telefonda böyle açılsın", "alt": "Modeli profildeki linkte"},
    }


def siparis_nasil(ctx) -> dict | None:
    kats = kategoriler()
    slug, kat = _kategori_sec(ctx)
    havuz = urunler(kat["id"], 30)
    if not havuz:
        return None
    u = ctx["rnd"].choice(havuz)
    hafta = ctx["simdi"].isocalendar().week
    return {
        "anahtar": f"siparis:{hafta}",
        "konu": "Basılı davetiye nasıl sipariş edilir",
        "anahtar_kelime": "davetiye siparişi",
        "olgular": ["Adet seçilir: 100, 200, 300, 400, 500, 600, 700, 800 veya 1000. Hane başına bir adet + birkaç yedek önerilir.",
                    "Sipariş formuna isimler, tarih, saat ve mekân yazılır.", "Fiyat için teklif istenir; baskı öncesi metin ve yazım kontrolü WhatsApp'tan yapılır.",
                    "Basılı davetiye alana ₺650+KDV değerinde dijital davetiye hediye; kod sipariş onayında e-postaya gelir.",
                    f"Örnek model: {u['ad']}"],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": u["gorsel"], "etiket": "Sipariş rehberi", "baslik": "Davetiye siparişi 3 adımda", "alt": "Kaç adet lazım? Videonun sonunda"},
            {"tur": "sayfa", "url": u["url"], "sure": 6.0, "once_tikla": ["Kabul", "Tamam"], "kaydir": True, "kaydir_px": 650, "ust_yazi": "1. Modeli seçin, adedi belirleyin"},
            {"tur": "kart", "tip": "liste", "sure": 5.4, "gorsel": u["gorsel"], "etiket": "Adım adım", "baslik": "Sonrası çok kolay",
             "maddeler": ["İsim, tarih, saat ve mekânı yazın", "Teklifinizi alın", "Yazım kontrolü WhatsApp'tan, sonra baskı"]},
            {"tur": "kart", "tip": "rakam", "sure": 3.6, "gorsel": u["gorsel"], "etiket": "İpucu", "rakam": "+%10", "baslik": "Hane sayısına yedek ekleyin", "alt": "Son dakika davetlileri unutulmasın"},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Dijital davetiye de hediye", "alt": "Basılı davetiye siparişine ₺650 değerinde"},
        ],
        "hikaye": {"gorsel": u["gorsel"], "etiket": "Sipariş ipucu", "baslik": "Kaç davetiye bastırmalı?", "alt": "Hane sayısı + %10 yedek"},
    }


def hediye_suruyor() -> bool:
    """'Basılı davetiyeye ₺650 dijital davetiye hediye' kampanyası anasayfada hâlâ yazıyor mu?"""
    return sitede_var(f"{SITE}/", r"650") and sitede_var(f"{SITE}/", r"hediye")


def kampanya(ctx) -> dict | None:
    if not hediye_suruyor():
        return None
    kats = kategoriler()
    kat = kats.get("kampanyali-davetiyeler")
    if not kat:
        return None
    havuz = urunler(kat["id"], 30)
    havuz = [u for u in havuz if f"urun:{u['id']}" not in ctx["kullanilan"]] or havuz
    ctx["rnd"].shuffle(havuz)
    sec = havuz[:4]
    if len(sec) < 3:
        return None
    hafta = ctx["simdi"].isocalendar().week
    return {
        "anahtar": f"kampanya:{hafta}",
        "ek_anahtarlar": [f"urun:{u['id']}" for u in sec],
        "konu": "Kampanyalı davetiyeler + dijital davetiye hediye",
        "anahtar_kelime": "kampanyalı davetiye",
        "olgular": [f"Kampanyalı davetiyeler kategorisinde {kat['count']} model var.",
                    "Basılı davetiye alana ₺650+KDV değerinde dijital davetiye hediye; kod sipariş onayında e-postaya gelir.",
                    *[f"{u['ad']}: {u['kisa'][:120]}" for u in sec]],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": sec[0]["gorsel"], "etiket": "Kampanya", "baslik": "Basılı davetiyeye dijital davetiye hediye", "alt": "₺650 değerinde, sipariş onayında"},
            {"tur": "kart", "tip": "izgara", "sure": 4.2, "zemin": sec[1]["gorsel"], "gorseller": [u["gorsel"] for u in sec], "yazilar": [kisa_ad(u["ad"]) for u in sec],
             "baslik": "Kampanyalı modellerden", "alt": "Hepsi profildeki linkte"},
            {"tur": "kart", "tip": "liste", "sure": 4.6, "gorsel": sec[2]["gorsel"], "etiket": "Nasıl alırım?", "baslik": "Hediye dijital davetiye",
             "maddeler": ["Basılı davetiyenizi sipariş edin", "Kodunuz e-postanıza gelsin", "Dijital modelinizi seçip paylaşın"]},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "İki davetiye, tek sipariş", "alt": "Kampanyalı modeller sitede"},
        ],
        "hikaye": {"gorsel": sec[0]["gorsel"], "etiket": "Kampanya", "baslik": "Dijital davetiye hediye", "alt": "Basılı davetiye siparişine özel"},
    }


def _hediye_kontrollu(f):
    def sar(ctx):
        s = f(ctx)
        return s if hediye_suruyor() else iddia_temizle(s, r"hediye|650\+KDV|650 değerinde", "Tüm modeller sitede")
    return sar


FORMATLAR = {"model_vitrin": _hediye_kontrollu(model_vitrin), "dijital_davetiye": _hediye_kontrollu(dijital_davetiye),
             "siparis_nasil": _hediye_kontrollu(siparis_nasil), "kampanya": kampanya}
