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
        "anahtar": f"isletme:{ctx['simdi'].isocalendar().week}",
        "konu": "Belgeli tesisler için komisyonsuz listeleme",
        "anahtar_kelime": "sapanca bungalov işletmesi",
        "olgular": [m["aciklama"], *[f"{b['baslik']}: {' '.join(b['metin'])[:300]}" for b in m["bolumler"][:6]]],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": fotolar[0], "etiket": "Tesis sahiplerine", "baslik": "Belgeli bungalovunuzu komisyonsuz listeleyin", "alt": "Misafir sizi doğrudan arasın"},
            {"tur": "kart", "tip": "liste", "sure": 5.2, "gorsel": fotolar[1], "etiket": "Nasıl çalışır?", "baslik": "Aracı yok, komisyon yok",
             "maddeler": ["Misafir sizi telefon veya WhatsApp ile arar", "Kurucu tesisler ücretsiz listelenir", "Görüntülenme ve tıklamaları panelde görürsünüz"]},
            {"tur": "sayfa", "url": f"{SITE}/isletmeler-icin/", "sure": 5.5, "kaydir": True, "kaydir_px": 1800, "ust_yazi": "Başvuru 4 adım"},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Yalnız belgeli tesisler", "alt": "Başvuru sitede: İşletmeler için"},
        ],
        "hikaye": {"gorsel": fotolar[2], "etiket": "Tesis sahipleri", "baslik": "Komisyonsuz listeleme", "alt": "Kurucu tesisler ücretsiz"},
    }


# ---------------- tesis sahiplerine (kuruluş aşaması) ----------------
# Tüm bilgiler sitenin "İşletmeler için" sayfasından; olmayan rakam/vaat yok.

ISLETME_CTA = {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Tesisinizi ücretsiz ekleyin", "alt": "Başvuru 5 dakika, link profilde"}


def _isletme_sayfasi() -> dict:
    return makale(f"{SITE}/isletmeler-icin/")


def _bolum(m: dict, desen: str) -> list[str]:
    b = next((x for x in m["bolumler"] if re.search(desen, x["baslik"], re.I)), None)
    return [re.sub(r"\*\*", "", t) for t in (b["metin"] if b else [])]


def _isletme_olgulari(m: dict) -> list[str]:
    return [m["aciklama"], *[f"{b['baslik']}: {' '.join(b['metin'])[:400]}" for b in m["bolumler"][:6]]]


def _foto(ctx) -> list[str]:
    f = FOTOLAR[:]
    ctx["rnd"].shuffle(f)
    return f


def sahte_ilan_isletme(ctx) -> dict | None:
    m, f = _isletme_sayfasi(), _foto(ctx)
    return {
        "anahtar": f"sahte-isletme:{ctx['simdi'].isocalendar().week}", "konu": "İşletmenin fotoğraflarıyla açılan sahte hesaplar",
        "anahtar_kelime": "sapanca bungalov işletmesi", "olgular": _isletme_olgulari(m),
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": f[0], "etiket": "Tesis sahiplerine", "baslik": "Bungalovunuzun fotoğraflarıyla sahte hesap açılmış olabilir", "alt": "Misafiriniz de siz de zarar görüyorsunuz"},
            {"tur": "kart", "tip": "liste", "sure": 5.4, "gorsel": f[1], "etiket": "Nasıl korunursunuz?", "baslik": "Doğrulanmış tesis olun",
             "maddeler": ["Belgeniz Bakanlık kaydıyla eşleştirilir", "Sahiplik telefonla teyit edilir", "Doğrulanmış numaranız başka hesapta kullanılamaz"]},
            {"tur": "sayfa", "url": f"{SITE}/isletmeler-icin/", "sure": 5.5, "kaydir": True, "kaydir_px": 2200, "kaydir_bas": 0.3, "ust_yazi": "Neden bu kadar kontrol?"},
            dict(ISLETME_CTA),
        ],
        "hikaye": {"gorsel": f[2], "etiket": "Tesis sahipleri", "baslik": "Sahte ilana karşı doğrulanmış tesis olun", "alt": "Başvuru profildeki linkte"},
    }


def kurucu_tesis(ctx) -> dict | None:
    m, f = _isletme_sayfasi(), _foto(ctx)
    if not any("kurucu" in t.lower() for t in _isletme_olgulari(m)):
        return None  # kurucu tesis avantajı sayfada artık yazmıyorsa anlatılmaz
    return {
        "anahtar": f"kurucu:{ctx['simdi'].isocalendar().week}", "konu": "Kurucu tesis avantajı",
        "anahtar_kelime": "sapanca bungalov işletmesi", "olgular": _isletme_olgulari(m),
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": f[0], "etiket": "Kurucu tesis", "baslik": "İlk katılan belgeli tesisler ücretsiz listeleniyor", "alt": "Sonraki dönem için indirimli fiyat garantisi"},
            {"tur": "kart", "tip": "liste", "sure": 5.4, "gorsel": f[1], "etiket": "Neler kazanırsınız?", "baslik": "Kurucu tesis olmanın avantajı",
             "maddeler": ["İlk dönem ücretsiz listeleme", "Misafir sizi doğrudan arar, komisyon yok", "Görüntülenme ve tıklamalar panelde"]},
            {"tur": "sayfa", "url": f"{SITE}/tesis-ekle/", "sure": 5.0, "kaydir": True, "kaydir_px": 1400, "ust_yazi": "Başvuru formu 5 dakika"},
            dict(ISLETME_CTA),
        ],
        "hikaye": {"gorsel": f[2], "etiket": "Kurucu tesis", "baslik": "İlk dönem ücretsiz listeleme", "alt": "Başvuru profildeki linkte"},
    }


def basvuru_adimlari(ctx) -> dict | None:
    m, f = _isletme_sayfasi(), _foto(ctx)
    adimlar = [_kisalt(_ilk_cumle(x), 54) for x in _bolum(m, r"başvuru adım")][:4]
    if len(adimlar) < 3:
        return None
    return {
        "anahtar": f"basvuru:{ctx['simdi'].isocalendar().week}", "konu": "Tesis başvurusu adım adım",
        "anahtar_kelime": "bungalov işletme başvurusu", "olgular": _isletme_olgulari(m),
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": f[0], "etiket": "Tesis sahiplerine", "baslik": "Belgeli tesisinizi listelemek 4 adım", "alt": "Kimler başvurabilir? Videonun sonunda"},
            {"tur": "kart", "tip": "liste", "sure": 6.0, "gorsel": f[1], "etiket": "Adım adım", "baslik": "Başvuru nasıl işler?", "maddeler": adimlar},
            {"tur": "kart", "tip": "liste", "sure": 4.6, "gorsel": f[2], "etiket": "Kimler başvurabilir?", "baslik": "Bakanlık belgesi olan tesisler",
             "maddeler": ["Turizm İşletmesi Belgesi", "Basit Konaklama belgesi", "Turizm Amaçlı Konut İzin Belgesi"]},
            dict(ISLETME_CTA),
        ],
        "hikaye": {"gorsel": f[3], "etiket": "Başvuru", "baslik": "Belgeli tesisinizi 4 adımda listeleyin", "alt": "Form profildeki linkte"},
    }


def belgeli_ayirt(ctx) -> dict | None:
    sayi, tarih = _belgeli_sayi()
    if not sayi:
        return None
    m, f = _isletme_sayfasi(), _foto(ctx)
    return {
        "anahtar": f"ayirt:{ctx['simdi'].isocalendar().week}", "konu": "Belgeli tesisin misafire güven vermesi",
        "anahtar_kelime": "sapanca belgeli bungalov",
        "olgular": [f"Sapanca'da {sayi} belgeli konaklama tesisi kaydı var ({tarih}).", *_isletme_olgulari(m)],
        "sahneler": [
            {"tur": "kart", "tip": "rakam", "sure": 3.4, "gorsel": f[0], "etiket": "Bakanlık kaydı", "rakam": sayi, "baslik": "Sapanca'daki belgeli tesis sayısı", "alt": f"{tarih} verisi" if tarih else None},
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": f[1], "etiket": "Tesis sahiplerine", "baslik": "Misafir sizi sahte ilanlardan nasıl ayırt etsin?", "alt": "Belgeniz görünür olsun"},
            {"tur": "kart", "tip": "liste", "sure": 5.0, "gorsel": f[2], "etiket": "Doğrulanmış tesis", "baslik": "Misafirin güvendiği şeyler",
             "maddeler": ["Bakanlık belgesi doğrulanmış", "Telefon numarası doğrulanmış", "Misafir sizinle doğrudan konuşur"]},
            dict(ISLETME_CTA),
        ],
        "hikaye": {"gorsel": f[3], "etiket": "Belgeli tesis", "baslik": "Belgeniz misafire güven versin", "alt": "Başvuru profildeki linkte"},
    }


FORMATLAR = {"guvenlik_ipucu": guvenlik_ipucu, "rehber": rehber, "belge_sorgula": belge_sorgula, "isletme_davet": isletme_davet,
             "sahte_ilan_isletme": sahte_ilan_isletme, "kurucu_tesis": kurucu_tesis, "basvuru_adimlari": basvuru_adimlari,
             "belgeli_ayirt": belgeli_ayirt}


# ---------------- aşama ----------------

def tesis_sayisi() -> int | None:
    """Sitede yayında olan tesis sayısı (site haritasındaki /bungalov/<tesis> adresleri). Okunamazsa None."""
    try:
        return sum(1 for u in sitemap(f"{SITE}/sitemap.xml") if re.search(r"/bungalov/[^/]+/?$", u))
    except Exception:
        return None


def asama_ayari(m: dict) -> dict:
    """Listede tesis yokken (kuruluş) içerik tesis sahiplerine döner; misafir videolarında 'listede tesis var' denmez.
    3 ve üzeri tesis yayına girince kendiliğinden misafir odağına geçer."""
    n = tesis_sayisi()
    if n is None or n >= 3:
        return {}
    k = (m.get("asamalar") or {}).get("kurulus") or {}
    return {"formatlar": k.get("formatlar", m["formatlar"]), "cta": k.get("cta", m["cta"]), "asama": "kurulus", "tesis_sayisi": n}


def kurulus_temizle(s: dict) -> dict:
    """Misafir videolarındaki 'belgeli bungalovlar listede' kapanışını kuruluşta bilgilendirici kapanışla değiştirir."""
    for sh in s.get("sahneler", []):
        if sh.get("tip") == "cta" and sh is not ISLETME_CTA and not str(sh.get("baslik", "")).startswith("Tesisinizi"):
            sh["baslik"], sh["alt"] = "Kapora göndermeden önce kontrol edin", "Rehberin tamamı profildeki linkte"
    return s
