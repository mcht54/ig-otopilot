"""MarkaKarnem içerik formatları — sitedeki gerçek ölçülmüş veriler, soru/sözlük/rehber sayfaları,
tarayıcıda çalışan ücretsiz araç (yapay zekâ bütçesi harcatan analizler BİLEREK kullanılmaz)."""
from __future__ import annotations

import re

from ..film import yazma_eylemleri
from . import makale, sitemap

SITE = "https://markakarnem.com.tr"


def _harita(ad: str) -> list[str]:
    return [u for u in sitemap(f"{SITE}/sitemaps/{ad}.xml") if u.count("/") > 3]


def _kisalt(s: str, n: int = 54) -> str:
    s = re.sub(r"\s+", " ", s).strip().rstrip(".")
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def _ilk_cumle(s: str) -> str:
    return re.split(r"(?<=[.!?])\s", s.strip(), 1)[0]


def _sec(ctx, urller: list[str], on_ek: str) -> list[str]:
    kalan = [u for u in urller if f"{on_ek}:{u.rstrip('/').rsplit('/', 1)[-1]}" not in ctx["kullanilan"]]
    ctx["rnd"].shuffle(kalan)
    yedek = urller[:]
    ctx["rnd"].shuffle(yedek)
    return kalan + yedek


def _maddeler(m: dict, en_az: int = 3) -> list[str]:
    """Önce 'Kısa cevap'tan sonra gelen bölümlerin başlıklarını, yoksa paragrafların ilk cümlelerini kullanır."""
    atla = re.compile(r"(kısa cevap|ilgili|kendi durumunuzu|sık sorulan|yöntem)", re.I)
    bas = [_kisalt(b["baslik"]) for b in m["bolumler"] if not atla.search(b["baslik"])]
    if len(bas) >= en_az:
        return bas[:4]
    cumleler = [_kisalt(_ilk_cumle(x)) for b in m["bolumler"] for x in b["metin"] if len(x) > 20]
    return (bas + cumleler)[:4]


def _makale_senaryosu(ctx, url: str, etiket: str, on_ek: str) -> dict | None:
    m = makale(url)
    if not m["baslik"]:
        return None
    maddeler = _maddeler(m)
    if len(maddeler) < 2:
        return None
    kisa = next((b for b in m["bolumler"] if re.search(r"kısa cevap", b["baslik"], re.I)), None)
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return {
        "anahtar": f"{on_ek}:{slug}",
        "konu": m["baslik"],
        "anahtar_kelime": re.sub(r"[?:].*$", "", m["baslik"]).strip().lower(),
        "olgular": [f"Sayfa: {m['baslik']}", f"Özet: {m['aciklama']}",
                    *[f"{b['baslik']}: {' '.join(b['metin'])[:300]}" for b in m["bolumler"][:7]]],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": None, "etiket": etiket, "baslik": _kisalt(m["baslik"], 62),
             "alt": _kisalt(_ilk_cumle(kisa["metin"][0]), 84) if kisa and kisa["metin"] else "Cevabı 15 saniyede"},
            {"tur": "kart", "tip": "liste", "sure": 5.4, "etiket": "Kısaca", "baslik": "Bilmeniz gerekenler", "maddeler": maddeler},
            {"tur": "sayfa", "url": url, "sure": 5.5, "once_tikla": ["Reddet"], "kaydir": True, "kaydir_px": 1800, "kaydir_bas": 0.5,
             "ust_yazi": "Tamamı sitede, ücretsiz"},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Sizin durumunuz ne?", "alt": "52 kontrollü ücretsiz karnenizi çıkarın"},
        ],
        "hikaye": {"gorsel": None, "etiket": etiket, "baslik": _kisalt(m["baslik"], 60), "alt": "Cevap profildeki videoda"},
    }


def soru_cevap(ctx) -> dict | None:
    for u in _sec(ctx, _harita("sorular") + _harita("sozluk") + _harita("rehber"), "soru"):
        s = _makale_senaryosu(ctx, u, "Soru-cevap", "soru")
        if s:
            return s
    return None


def sektor_ipucu(ctx) -> dict | None:
    for u in _sec(ctx, _harita("sektorler"), "sektor"):
        s = _makale_senaryosu(ctx, u, "Sektörünüze özel", "sektor")
        if s:
            return s
    return None


def yerel_karne(ctx) -> dict | None:
    ay = ctx["simdi"].strftime("%Y-%m")
    for u in _sec(ctx, _harita("yerel"), "yerel"):
        slug = u.rstrip("/").rsplit("/", 1)[-1]
        if f"yerel:{slug}:{ay}" in ctx["kullanilan"]:
            continue
        m = makale(u)
        eksikler = []
        for b in m["bolumler"]:
            if "eksik" in b["baslik"].lower():
                for x in b["metin"]:
                    r = re.match(r"([^:]+):\s*ölçülen işletmelerin %(\d+)'?\w*\s+eksik", x)
                    if r:
                        eksikler.append((r.group(1).strip(), r.group(2)))
        sayi = re.search(r"(\d+)\s+[^.]*?işletmesinin", m["aciklama"])
        medyan = re.search(r"medyan Marka Skoru (\d+)/100", m["aciklama"])
        if len(eksikler) < 2 or not medyan:
            continue
        sektor = re.sub(r"^Sakarya\s+|\s+işletmelerinin.*$", "", m["baslik"], flags=re.I)
        bas = eksikler[0]
        return {
            "anahtar": f"yerel:{slug}:{ay}",
            "konu": f"Sakarya {sektor} dijital karnesi",
            "anahtar_kelime": f"sakarya {sektor.lower()}",
            "olgular": [m["aciklama"], *[f"{a}: ölçülen işletmelerin %{y}'sinde eksik" for a, y in eksikler],
                        *[f"{b['baslik']}: {' '.join(b['metin'])[:240]}" for b in m["bolumler"] if "yöntem" in b["baslik"].lower()]],
            "sahneler": [
                {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": None, "etiket": "Sakarya verisi",
                 "baslik": f"Sakarya'da {sektor.lower()} işletmelerini ölçtük", "alt": f"{sayi.group(1)} işletme, gerçek ölçüm" if sayi else "Gerçek ölçüm"},
                {"tur": "kart", "tip": "rakam", "sure": 3.6, "etiket": "En sık eksik", "rakam": f"%{bas[1]}", "baslik": f"{bas[0]} eksik", "alt": "Ölçülen işletmeler içinde"},
                {"tur": "kart", "tip": "liste", "sure": 5.0, "etiket": "Diğer eksikler", "baslik": "Sık görülen sorunlar",
                 "maddeler": [_kisalt(f"{a}: %{y} eksik") for a, y in eksikler[1:4]] or [_kisalt(f"{a}: %{y} eksik") for a, y in eksikler]},
                {"tur": "kart", "tip": "rakam", "sure": 3.4, "etiket": "Bölge medyanı", "rakam": medyan.group(1), "baslik": "Ortanca Marka Skoru (100 üzerinden)", "alt": "Siz bunun neresindesiniz?"},
                {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Kendi skorunuzu görün", "alt": "Ücretsiz, 52 kontrol"},
            ],
            "hikaye": {"gorsel": None, "etiket": "Sakarya verisi", "baslik": f"{sektor}: en sık eksik {bas[0].lower()}", "alt": f"Ölçülenlerin %{bas[1]}'inde"},
        }
    return None


ARAC = f"{SITE}/araclar/instagram-etkilesim-orani-hesaplama"


def arac_demo(ctx) -> dict | None:
    ay = ctx["simdi"].strftime("%Y-%m")
    if f"arac:{ay}" in ctx["kullanilan"]:
        return None
    # Sayfadaki örnekle aynı rakamlar (olgulardan doğrulanır): 2.000 takipçi, 70 beğeni, 6 yorum, 4 kaydetme
    alanlar = [("Takipçi sayısı", "2000"), ("ortalama beğeni", "70"), ("ortalama yorum", "6"), ("Ortalama kaydetme", "4")]
    eylemler, t = [], 1.0
    for etiket, deger in alanlar:
        eylemler += yazma_eylemleri(t, etiket, deger, hiz=0.12)
        t += 0.4 + len(deger) * 0.12
    eylemler += [{"t": t + 0.2, "tikla": "Etkileşim oranını hesapla"}, {"t": t + 0.3, "ust_yazi": "Sonuç anında, giriş yok"},
                 {"t": t + 0.6, "js": "(() => { const b = [...document.querySelectorAll('button')].find(e => /hesapla/i.test(e.innerText)); const y = b ? b.getBoundingClientRect().top + scrollY - 140 : scrollY + 450; scrollTo(0, y); })()"}]
    m = makale(ARAC)
    return {
        "anahtar": f"arac:{ay}",
        "konu": "Instagram etkileşim oranı nasıl hesaplanır",
        "anahtar_kelime": "instagram etkileşim oranı",
        "olgular": [m["aciklama"], *[f"{b['baslik']}: {' '.join(b['metin'])[:300]}" for b in m["bolumler"][:4]]],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": None, "etiket": "Ücretsiz araç", "baslik": "Instagram etkileşim oranınız kaç?", "alt": "Takipçi sayısı tek başına bir şey söylemez"},
            {"tur": "sayfa", "url": ARAC, "once_tikla": ["Reddet"], "sure": round(t + 3.5, 1), "ust_yazi": "Rakamlarınızı yazın",
             "once_js": ["document.querySelector('input')?.scrollIntoView({block:'center'})"], "eylemler": eylemler},
            {"tur": "kart", "tip": "liste", "sure": 5.0, "etiket": "Doğru ölçüm", "baslik": "Yanılmamak için",
             "maddeler": ["Son 10 gönderinin ortalamasını alın", "Hep aynı yöntemle hesaplayın", "Reels ve fotoğrafı ayrı ölçün"]},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Hesaplayın, kaydedin", "alt": "Giriş ve şifre gerekmez"},
        ],
        "hikaye": {"gorsel": None, "etiket": "Ücretsiz araç", "baslik": "Etkileşim oranınızı 10 saniyede hesaplayın", "alt": "Link profilde"},
    }


def ornek_rapor(ctx) -> dict | None:
    ay = ctx["simdi"].strftime("%Y-%m")
    if f"ornek:{ay}" in ctx["kullanilan"]:
        return None
    url = f"{SITE}/ornek-rapor"
    m = makale(url)
    return {
        "anahtar": f"ornek:{ay}",
        "konu": "MarkaKarnem raporunda neler var",
        "anahtar_kelime": "ücretsiz seo analizi",
        "olgular": [m["aciklama"], "Web sitesi, Google İşletme Profili ve Instagram 52 kontrolle analiz edilir.",
                    f"Rapor bölümleri: {', '.join(b['baslik'] for b in m['bolumler'][:8])}"],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": None, "etiket": "Örnek rapor", "baslik": "İşletmenizin dijital karnesi böyle görünür", "alt": "Örnek işletme üzerinden"},
            {"tur": "sayfa", "url": url, "once_tikla": ["Reddet"], "sure": 8.0, "kaydir": True, "kaydir_px": 3200, "kaydir_oran": 0.8, "ust_yazi": "Skor, öncelikli bulgular, kanal kanal kontrol"},
            {"tur": "kart", "tip": "liste", "sure": 5.0, "etiket": "52 kontrol", "baslik": "Üç kanal birden",
             "maddeler": ["Web sitesi", "Google İşletme Profili", "Instagram"]},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Kendi karnenizi çıkarın", "alt": "Ücretsiz, birkaç dakika"},
        ],
        "hikaye": {"gorsel": None, "etiket": "Örnek rapor", "baslik": "Dijital karneniz kaç puan?", "alt": "Örneği profilde izleyin"},
    }


FORMATLAR = {"soru_cevap": soru_cevap, "sektor_ipucu": sektor_ipucu, "yerel_karne": yerel_karne, "arac_demo": arac_demo, "ornek_rapor": ornek_rapor}
