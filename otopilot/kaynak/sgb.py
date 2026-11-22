"""Sapanca Güvenilir Bungalov içerik formatları — sitedeki gerçek rehberler ve veriler.
Fotoğraflar temsilidir; belirli bir tesis övülmez/kötülenmez."""
from __future__ import annotations

import re

from . import getir, makale, sitemap, temiz

SITE = "https://sapancaguvenilirbungalov.com.tr"
FOTOLAR = [f"{SITE}/img/bungalov/{a}.jpg" for a in (
    "orman-icinde-a-frame-bungalov", "gol-manzarali-jakuzili-bungalov", "bungalov-ic-mekan-sicak-havuz",
    "ahsap-verandali-bungalov", "orman-icinde-ahsap-bungalov", "somineli-bungalov-salon", "sobali-tiny-house-ic-mekan")]
GUVENLIK = ("dolandir", "kacak", "kamera", "dikkat", "guvenli", "belge", "sorgula", "kapora")


def rehberler() -> list[str]:
    return [u for u in sitemap(f"{SITE}/sitemap.xml") if "/rehber/" in u and "/ar/" not in u and u.rstrip("/") != f"{SITE}/rehber"]


def _ilk_cumle(s: str) -> str:
    return re.split(r"(?<=[.!?])\s", s.strip(), 1)[0]


def _baslik_sade(s: str) -> str:
    """Tekrarlayan öneki at: "Sapanca'da bungalov kiralarken kapora…" → "Kapora…"."""
    s = re.sub(r"^Sapanca(?:'|’)da\s+bungalov\s+kiralarken\s+", "", s, flags=re.I)
    return s[:1].upper() + s[1:]


def _kisalt(s: str, n: int = 58) -> str:
    s = re.sub(r"\s+", " ", s).strip().rstrip(".")
    s = re.sub(r"^\d+[.)]\s*", "", s)
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def _makale_senaryosu(ctx, url: str, etiket: str) -> dict | None:
    m = makale(url)
    bolumler = [b for b in m["bolumler"] if len(b["baslik"]) > 6 and not re.search(r"(sık sorulan|ilgili|kaynak|sonuç)", b["baslik"], re.I)]
    if len(bolumler) < 2:
        return None
    fotolar = FOTOLAR[:]
    ctx["rnd"].shuffle(fotolar)
    kapak = m["gorsel"] or fotolar[0]
    maddeler = [_kisalt(b["baslik"]) for b in bolumler[:4]]
    olgular = [f"Makale: {m['baslik']}", f"Özet: {m['aciklama']}"]
    for b in bolumler[:6]:
        olgular.append(f"{b['baslik']}: {' '.join(b['metin'])[:300]}")
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return {
        "anahtar": f"rehber:{slug}",
        "konu": m["baslik"],
        "anahtar_kelime": "sapanca bungalov",
        "olgular": olgular,
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": kapak, "etiket": etiket, "baslik": _kisalt(_baslik_sade(m["baslik"]), 62), "alt": "Kaydedin, tatilden önce lazım olacak"},
            {"tur": "kart", "tip": "liste", "sure": 5.6, "gorsel": fotolar[1], "etiket": "Kısaca", "baslik": "Bilmeniz gerekenler", "maddeler": maddeler[:4]},
            {"tur": "sayfa", "url": url, "sure": 6.0, "kaydir": True, "kaydir_px": 2200, "kaydir_bas": 0.5, "ust_yazi": "Rehberin tamamı sitede"},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Yalnız Bakanlık belgeli bungalovlar", "alt": "Komisyon yok, tesisle doğrudan görüşün"},
        ],
        "hikaye": {"gorsel": fotolar[2], "etiket": etiket, "baslik": _kisalt(bolumler[0]["baslik"], 60), "alt": "Rehber profilde"},
    }


def _rehber_sec(ctx, guvenlik: bool) -> list[str]:
    hepsi = rehberler()
    secilen = [u for u in hepsi if any(k in u for k in GUVENLIK) == guvenlik]
    kalan = [u for u in secilen if f"rehber:{u.rstrip('/').rsplit('/', 1)[-1]}" not in ctx["kullanilan"]]
    ctx["rnd"].shuffle(kalan)
    yedek = secilen[:]
    ctx["rnd"].shuffle(yedek)
    return kalan + yedek


def guvenlik_ipucu(ctx) -> dict | None:
    for url in _rehber_sec(ctx, True):
        s = _makale_senaryosu(ctx, url, "Güvenli tatil")
        if s:
            return s
    return None


def rehber(ctx) -> dict | None:
    for url in _rehber_sec(ctx, False):
        s = _makale_senaryosu(ctx, url, "Sapanca rehberi")
        if s:
            return s
    return None


def _belgeli_sayi() -> tuple[str, str]:
    t = getir(f"{SITE}/sapanca-belgeli-tesis-sayisi/").text
    m = re.search(r"Sapanca(?:&#x27;|')da (\d+) belgeli", t)
    tarih = re.search(r"(\w+ 20\d\d) itibarıyla", temiz(t))
    return (m.group(1) if m else "", tarih.group(1) if tarih else "")


def belge_sorgula(ctx) -> dict | None:
    sayi, tarih = _belgeli_sayi()
    hafta = ctx["simdi"].isocalendar().week
    fotolar = FOTOLAR[:]
    ctx["rnd"].shuffle(fotolar)
    url = f"{SITE}/rehber/bakanlik-belgesi-nasil-sorgulanir/"
    m = makale(url)
    sorgu = next((b for b in m["bolumler"] if re.search(r"nasıl yapılır|adım", b["baslik"], re.I)), None)
    adimlar = [_kisalt(_ilk_cumle(x), 54) for x in (sorgu["metin"] if sorgu else [])][:4]
    if len(adimlar) < 3:
        adimlar = ["Bakanlık belgeli tesis sorgusunu açın", "Sakarya / Sapanca'yı seçin", "Tesis adını arayın, bilgileri karşılaştırın"]
    sahneler = [
        {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": fotolar[0], "etiket": "Kapora göndermeden önce", "baslik": "Bungalovun belgesi var mı? Kapora göndermeden bakın", "alt": "Adım adım anlatıyoruz"},
        {"tur": "kart", "tip": "liste", "sure": 5.4, "gorsel": fotolar[1], "etiket": "Adım adım", "baslik": "Belge nasıl sorgulanır?", "maddeler": adimlar},
    ]
    if sayi:
        sahneler.append({"tur": "kart", "tip": "rakam", "sure": 3.6, "gorsel": fotolar[2], "etiket": "Bakanlık kaydı", "rakam": sayi,
                         "baslik": "Sapanca'daki belgeli tesis sayısı", "alt": f"{tarih} verisi" if tarih else None})
    sahneler += [
        {"tur": "sayfa", "url": f"{SITE}/dogrulama/nasil-dogruluyoruz/", "sure": 5.5, "kaydir": True, "kaydir_px": 1800, "ust_yazi": "Biz her tesisi böyle doğruluyoruz"},
        {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Belgesi doğrulanmış bungalovlar", "alt": "Komisyon yok, doğrudan iletişim"},
    ]
    return {
        "anahtar": f"belge:{hafta}",
        "konu": "Bungalov belgesi nasıl sorgulanır",
        "anahtar_kelime": "bungalov belge sorgulama",
        "olgular": [f"Sapanca'da {sayi} belgeli konaklama tesisi kaydı var ({tarih})." if sayi else "",
                    *[f"{b['baslik']}: {' '.join(b['metin'])[:300]}" for b in m["bolumler"][:5]]],
        "sahneler": sahneler,
        "hikaye": {"gorsel": fotolar[3], "etiket": "Güvenli tatil", "baslik": "Kapora göndermeden önce belgeyi sorun", "alt": "Nasıl yapılacağı profilde"},
    }


def isletme_davet(ctx) -> dict | None:
    ay = ctx["simdi"].strftime("%Y-%m")
    m = makale(f"{SITE}/isletmeler-icin/")
    fotolar = FOTOLAR[:]
    ctx["rnd"].shuffle(fotolar)
    return {
        "anahtar": f"isletme:{ay}",
        "konu": "Belgeli tesisler için komisyonsuz listeleme",
        "anahtar_kelime": "sapanca bungalov işletmesi",
        "olgular": [m["aciklama"], *[f"{b['baslik']}: {' '.join(b['metin'])[:300]}" for b in m["bolumler"][:6]]],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": fotolar[0], "etiket": "Tesis sahiplerine", "baslik": "Belgeli bungalovunuzu komisyonsuz listeleyin", "alt": "Misafir sizi doğrudan arasın"},
            {"tur": "kart", "tip": "liste", "sure": 5.2, "gorsel": fotolar[1], "etiket": "Nasıl çalışır?", "baslik": "Aracı yok, komisyon yok",
             "maddeler": ["Misafir sizi telefon veya WhatsApp ile arar", "Kurucu tesisler ücretsiz listelenir", "Görüntülenme ve tıklamaları panelde görürsünüz"]},
            {"tur": "sayfa", "url": f"{SITE}/isletmeler-icin/", "sure": 5.5, "kaydir": True, "kaydir_px": 1800, "ust_yazi": "Başvuru 3 adım"},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Yalnız belgeli tesisler", "alt": "Başvuru sitede: İşletmeler için"},
        ],
        "hikaye": {"gorsel": fotolar[2], "etiket": "Tesis sahipleri", "baslik": "Komisyonsuz listeleme", "alt": "Kurucu tesisler ücretsiz"},
    }


FORMATLAR = {"guvenlik_ipucu": guvenlik_ipucu, "rehber": rehber, "belge_sorgula": belge_sorgula, "isletme_davet": isletme_davet}
