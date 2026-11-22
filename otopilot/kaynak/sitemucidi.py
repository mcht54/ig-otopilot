"""Site Mucidi içerik formatları — gerçek sihirbaz ekranları ve gerçek tema önizlemeleri."""
from __future__ import annotations

from pathlib import Path

from ..film import yazma_eylemleri
from ..kayit import tikla, yeni_sayfa
from . import ekran_goruntusu, getir

SITE = "https://www.sitemucidi.com.tr"

# Özellik: (ad, ne işe yarar, esnafın derdi) — src/core/features.ts'ten, sade dille
OZELLIKLER = {
    "whatsapp": ("WhatsApp butonu", "Sitenizin köşesinde sabit duran tek dokunuşla WhatsApp'tan yazma düğmesi", "Müşteri numaranızı kopyalamakla uğraşmasın"),
    "map": ("Harita", "İletişim bölümünde adresinizi gösteren harita", "Müşteri dükkânınızı ararken kaybolmasın"),
    "appointment": ("Online randevu", "Ziyaretçi hizmet, gün ve saat seçip randevu talebi bırakır; talep e-postanıza düşer", "Telefon başında randevu yazmaktan kurtulun"),
    "quote_form": ("Teklif formu", "Ziyaretçi hizmet seçip bütçesini yazarak teklif ister", "Gece gelen teklif talebi de kaybolmasın"),
    "gallery": ("Fotoğraf galerisi", "Yaptığınız işlerin fotoğraflarını düzenli gösterir", "Müşteri işinizi görmeden karar vermez"),
    "testimonials": ("Müşteri yorumları", "Memnun müşterilerinizin sözleri sitede görünür", "İnsanlar önce başkasının deneyimine bakar"),
    "faq": ("Sık sorulan sorular", "Açılır kapanır soru-cevap bölümü", "Aynı soruyu her gün tekrar cevaplamayın"),
    "google_business": ("Google İşletme bağlantısı", "'Yol tarifi al' ve 'Google'da yorum yazın' düğmeleri", "Yorum toplamak bir dokunuşa iner"),
    "instagram_showcase": ("Instagram vitrini", "Fotoğraflarınızla Instagram tarzı ızgara ve 'Takip edin' çağrısı", "Siteye gelen Instagram'ınızı da takip etsin"),
    "seo_pro": ("Gelişmiş SEO paketi", "Yerel işletme yapılandırılmış verisi, sosyal paylaşım kartları ve SSS işaretlemesi", "Google ve yapay zekâ işletmenizi doğru anlasın"),
    "product_catalog": ("Ürün kataloğu", "Ad, fiyat etiketi, açıklama ve görselli ürün kartları", "Ürünlerinizi katalog gibi gösterin"),
    "blog": ("Blog ve duyurular", "Yazı ve duyuru yayınlama, her yazıya ayrı sayfa", "Kampanya ve haberleriniz Google'da bulunsun"),
    "multilang": ("İngilizce ikinci dil", "Sitenin İngilizce sürümü ve dil seçici", "Yabancı müşteriyi de kaçırmayın"),
}

# Sektör anahtar kelimesi → örnek işletme adı (yalnız videoda yazılır, gerçek işletme değil)
ORNEK_AD = [
    (("kuaför", "berber", "güzellik", "ışıltı", "salon"), "Işıl Güzellik Salonu"),
    (("diş", "klinik", "sağlık", "medika", "poliklinik", "şifa", "doktor", "tıp"), "Gülüş Diş Kliniği"),
    (("restoran", "kafe", "lezzet", "yemek", "pastane", "fırın"), "Lezzet Durağı"),
    (("oto", "servis", "lastik", "araç"), "Usta Oto Servis"),
    (("avukat", "hukuk"), "Yılmaz Hukuk Bürosu"),
    (("emlak", "gayrimenkul"), "Anahtar Emlak"),
    (("inşaat", "yapı", "mimar", "tadilat"), "Temel Yapı İnşaat"),
    (("veteriner", "pet", "pati"), "Pati Veteriner Kliniği"),
    (("eğitim", "kurs", "okul", "akademi", "kampüs"), "Başarı Kurs Merkezi"),
    (("lojistik", "nakliyat", "kargo", "taşımacılık"), "Hızlı Nakliyat"),
    (("spor", "fitness", "yoga", "pilates"), "Nefes Pilates Stüdyosu"),
    (("psikolog", "danışman", "terapi"), "Denge Danışmanlık"),
    (("matbaa", "baskı", "reklam", "ajans"), "Renk Matbaa"),
    (("sanayi", "endüstri", "makine", "metal", "çelik"), "Kuvvet Makine Sanayi"),
    (("otel", "pansiyon", "bungalov", "konaklama", "turizm"), "Göl Evi Konaklama"),
]


def temalar() -> list[dict]:
    return getir(f"{SITE}/api/themes").json()["themes"]


def ornek_ad(tema: dict) -> str:
    metin = " ".join([tema["name"], tema.get("tagline", ""), *tema.get("sectors", [])]).lower()
    for kelimeler, ad in ORNEK_AD:
        if any(k in metin for k in kelimeler):
            return ad
    return f"{tema['name']} {tema['sectors'][0] if tema.get('sectors') else 'İşletme'}"


def _ana_tema(slug: str) -> str:
    for ek in ("-yalin", "-vizyon"):
        if slug.endswith(ek):
            return slug[: -len(ek)]
    return slug


def _tema_sec(ctx, on_ek: str) -> dict | None:
    adaylar = [t for t in temalar() if t["slug"] == _ana_tema(t["slug"]) and f"{on_ek}:{t['slug']}" not in ctx["kullanilan"]]
    if not adaylar:
        adaylar = [t for t in temalar() if t["slug"] == _ana_tema(t["slug"])]
    return ctx["rnd"].choice(adaylar) if adaylar else None


def onizleme_html(tarayici, slug: str, ad: str, yol: Path) -> Path:
    """Sihirbazda işletme adını yazıp önizleme iframe'inin HTML'ini kaydeder (ada özel gerçek site)."""
    sayfa = yeni_sayfa(tarayici)
    try:
        sayfa.goto(f"{SITE}/olustur?tema={slug}", wait_until="networkidle", timeout=60000)
        tikla(sayfa, "Reddet")
        tikla(sayfa, "Bilgiler")
        sayfa.get_by_label("İşletme adı").first.fill(ad)
        sayfa.wait_for_timeout(500)
        tikla(sayfa, "Önizleme")
        sayfa.wait_for_timeout(2500)
        cerceve = next(f for f in sayfa.frames if f.url == "about:srcdoc")
        html = cerceve.content()
        html = html.replace("<head>", f'<head><base href="{SITE}/">', 1)
        yol.write_text(html, encoding="utf-8")
        return yol
    finally:
        sayfa.context.close()


def _sihirbaz_sahnesi(slug: str, ad: str) -> dict:
    bas_yaz = 1.6
    yaz_bitis = bas_yaz + 0.1 + len(ad) * 0.07
    return {
        "tur": "sayfa", "url": f"{SITE}/olustur?tema={slug}", "once_tikla": ["Reddet"], "bekle": 0.8,
        "ust_yazi": "1. Tasarımınızı seçin",
        "sure": round(yaz_bitis + 3.2, 2),
        "eylemler": [
            {"t": 1.1, "tikla": "Bilgiler"},
            {"t": 1.2, "ust_yazi": "2. İşletme adınızı yazın"},
            *yazma_eylemleri(bas_yaz, "İşletme adı", ad),
            {"t": yaz_bitis + 0.5, "tikla": "Önizleme"},
            {"t": yaz_bitis + 0.6, "ust_yazi": "3. Siteniz hazır"},
        ],
    }


def _kapak_gorseli(ctx, slug: str, html_yol: Path | None = None) -> str:
    yol = ctx["klasor"] / f"kapak-{slug}.png"
    url = html_yol.as_uri() if html_yol else f"{SITE}/temalar/{slug}/onizleme"
    ekran_goruntusu(ctx["tarayici"], url, yol)
    return yol.as_uri()


def sektor_demo(ctx) -> dict | None:
    tema = _tema_sec(ctx, "tema")
    if not tema:
        return None
    slug, ad = tema["slug"], ornek_ad(tema)
    sektor = (tema.get("sectors") or ["İşletmeniz"])[0]
    html_yol = onizleme_html(ctx["tarayici"], slug, ad, ctx["klasor"] / f"onizleme-{slug}.html")
    kapak = _kapak_gorseli(ctx, slug, html_yol)
    ozel = list(tema.get("highlights", []))[:3]
    for f in tema.get("supportedFeatures", []):
        if len(ozel) >= 3:
            break
        if f in OZELLIKLER and OZELLIKLER[f][0] not in ozel:
            ozel.append(OZELLIKLER[f][0])
    return {
        "anahtar": f"tema:{slug}",
        "konu": f"{sektor} için {tema['name']} teması ile 3 dakikada site",
        "anahtar_kelime": f"{sektor.lower()} web sitesi",
        "olgular": [
            f"Tema: {tema['name']} — {tema.get('tagline', '')}",
            f"Uygun sektörler: {', '.join(tema.get('sectors', []))}",
            f"Tema açıklaması: {tema.get('description', '')}",
            f"Öne çıkanlar: {'; '.join(tema.get('highlights', []))}",
            f"Videoda örnek işletme adı: {ad} (gerçek işletme değil)",
            "Site oluşturmak ücretsiz; kaydedince 7 gün denenir, yayına almak ücretlidir.",
        ],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "telefon": True, "sure": 3.0, "gorsel": kapak, "etiket": sektor,
             "baslik": f"{sektor} için 3 dakikada web sitesi", "alt": "Kod yok, ajans yok, bekleme yok."},
            _sihirbaz_sahnesi(slug, ad),
            {"tur": "sayfa", "html_yol": str(html_yol), "kaydir": True, "sure": 7.5, "kaydir_px": 3200,
             "ust_yazi": f"{tema['name']} teması — gerçek önizleme"},
            {"tur": "kart", "tip": "liste", "sure": 4.6, "gorsel": kapak, "etiket": "Hazır gelir",
             "baslik": "Bu temada neler var?", "maddeler": ozel or ["Mobil uyumlu tasarım", "WhatsApp butonu", "İletişim ve harita"]},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Sitenizi şimdi ücretsiz oluşturun", "alt": "Kaydedin, 7 gün deneyin."},
        ],
        "hikaye": {"telefon": True, "gorsel": kapak, "etiket": "Yeni video", "baslik": f"{sektor} sitesi 3 dakikada nasıl kurulur?", "alt": "Adım adım izleyin"},
    }


def ozellik(ctx) -> dict | None:
    secenek = [k for k in OZELLIKLER if f"ozellik:{k}" not in ctx["kullanilan"]] or list(OZELLIKLER)
    anahtar = ctx["rnd"].choice(secenek)
    ad, ne, dert = OZELLIKLER[anahtar]
    uygun = [t for t in temalar() if anahtar in t.get("supportedFeatures", []) and t["slug"] == _ana_tema(t["slug"])]
    tema = ctx["rnd"].choice(uygun or temalar())
    kapak = _kapak_gorseli(ctx, tema["slug"])
    return {
        "anahtar": f"ozellik:{anahtar}",
        "konu": f"Site Mucidi özelliği: {ad}",
        "anahtar_kelime": "web sitesi özellikleri",
        "olgular": [f"Özellik: {ad} — {ne}", f"Esnafın derdi: {dert}", f"Örnek tema: {tema['name']} ({', '.join(tema.get('sectors', [])[:2])})",
                    "Özellikler sihirbazda tek tıkla açılır/kapanır.", "Site oluşturmak ücretsiz; kaydedince 7 gün denenir."],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "telefon": True, "sure": 3.0, "gorsel": kapak, "etiket": ad, "baslik": dert, "alt": f"Sitenize {ad} ekleyin."},
            {"tur": "sayfa", "url": f"{SITE}/temalar/{tema['slug']}/onizleme", "kaydir": True, "sure": 7, "kaydir_px": 3600, "ust_yazi": f"{ad}: tek tıkla açılır"},
            {"tur": "kart", "tip": "liste", "sure": 4.6, "gorsel": kapak, "etiket": "Nasıl açılır?", "baslik": f"{ad} 3 adımda",
             "maddeler": ["Temanızı seçin", "Özellikler sekmesinden açın", "Önizlemede hemen görün"]},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Siz de deneyin", "alt": "Site oluşturmak ücretsiz, 7 gün deneme."},
        ],
        "hikaye": {"telefon": True, "gorsel": kapak, "etiket": "İpucu", "baslik": dert, "alt": f"Çözüm: {ad}"},
    }


YZ_ACILAR = [
    ("Müşteriler artık Google'dan önce yapay zekâya soruyor", "Sakarya'da güvenilir bir oto servis önerir misin?"),
    ("Yapay zekâ önerdiği işletmeyi nereden biliyor?", "Adapazarı'nda çocuk diş hekimi var mı?"),
    ("Siteniz yoksa yapay zekâ sizi önermez", "Serdivan'da düğün salonu tavsiye eder misin?"),
    ("ChatGPT'ye işletmenizi sorsalar ne cevap verir?", "Yakınımda iyi bir kuaför hangisi?"),
]


def yz_arama(ctx) -> dict | None:
    kalan = [i for i in range(len(YZ_ACILAR)) if f"yz:{i}" not in ctx["kullanilan"]] or list(range(len(YZ_ACILAR)))
    i = ctx["rnd"].choice(kalan)
    kanca, soru = YZ_ACILAR[i]
    tema = _tema_sec(ctx, "yz") or temalar()[0]
    kapak = _kapak_gorseli(ctx, tema["slug"])
    return {
        "anahtar": f"yz:{i}",
        "konu": "Yapay zekâ aramaları ve web sitesinin önemi",
        "anahtar_kelime": "yapay zekâda görünmek",
        "olgular": [
            "İnsanlar işletme önerisini giderek ChatGPT, Gemini gibi yapay zekâ asistanlarına soruyor.",
            "Bu asistanlar cevabı web sitelerinden, Google İşletme profillerinden ve yorumlardan derler.",
            "Hizmetleri, adresi, telefonu ve SSS'si net yazılmış site yapay zekânın okuyabileceği kaynaktır.",
            "Site Mucidi'nin Gelişmiş SEO paketi yerel işletme yapılandırılmış verisi ve SSS işaretlemesi ekler.",
            f"Örnek soru: {soru}",
        ],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "telefon": True, "sure": 3.0, "gorsel": kapak, "etiket": "Yapay zekâ", "baslik": kanca, "alt": f"“{soru}”"},
            {"tur": "kart", "tip": "liste", "sure": 5.2, "gorsel": kapak, "etiket": "Yapay zekâ neye bakar?", "baslik": "Cevabı buralardan derler",
             "maddeler": ["İşletmenin web sitesi", "Google İşletme profili ve yorumlar", "Net yazılmış hizmet, adres ve telefon"]},
            {"tur": "sayfa", "url": f"{SITE}/temalar/{tema['slug']}/onizleme", "kaydir": True, "sure": 6.5, "kaydir_px": 3000,
             "ust_yazi": "Hizmet, adres, SSS: düzenli ve okunur"},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Sitesi olmayan önerilmez", "alt": "3 dakikada ücretsiz oluşturun, 7 gün deneyin."},
        ],
        "hikaye": {"telefon": True, "gorsel": kapak, "etiket": "Biliyor muydunuz?", "baslik": "Müşteriler artık yapay zekâya soruyor", "alt": "Siteniz yoksa cevapta yoksunuz"},
    }


def tema_paket(ctx) -> dict | None:
    aileler = sorted({_ana_tema(t["slug"]) for t in temalar() if t["slug"].endswith("-vizyon")})
    kalan = [a for a in aileler if f"paket:{a}" not in ctx["kullanilan"]] or aileler
    if not kalan:
        return None
    aile = ctx["rnd"].choice(kalan)
    adlar = {t["slug"]: t for t in temalar()}
    paketler = [(f"{aile}-yalin", "Yalın"), (f"{aile}-vizyon", "Vizyon"), (aile, "Premium")]
    sahneler, gorseller = [], []
    for slug, paket in paketler:
        if slug not in adlar:
            continue
        yol = ctx["klasor"] / f"paket-{slug}.png"
        ekran_goruntusu(ctx["tarayici"], f"{SITE}/temalar/{slug}/onizleme", yol, yukseklik=1500)
        gorseller.append(yol.as_uri())
        sahneler.append({"tur": "kart", "tip": "telefon", "sure": 3.0, "gorsel": yol.as_uri(), "baslik": f"{paket} paket"})
    if len(sahneler) < 2:
        return None
    ad = adlar[aile]["name"] if aile in adlar else aile.title()
    return {
        "anahtar": f"paket:{aile}",
        "konu": f"{ad} teması üç pakette",
        "anahtar_kelime": "hazır web sitesi",
        "olgular": [f"{ad} temasının Yalın, Vizyon ve Premium paketleri var; paket yükseldikçe hareket ve ek bölümler artar.",
                    "Önizlemeler sitedeki gerçek tema önizlemesidir.", "Site oluşturmak ücretsiz; kaydedince 7 gün denenir."],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "telefon": True, "sure": 3.0, "gorsel": gorseller[-1], "etiket": "Aynı tema, 3 paket", "baslik": "Hangisi sizin işletmenize uyar?", "alt": f"{ad} teması"},
            *sahneler,
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": "Yorumlara tercihinizi yazın", "alt": "Ücretsiz oluşturun, 7 gün deneyin."},
        ],
        "hikaye": {"telefon": True, "gorsel": gorseller[0], "etiket": "Anket", "baslik": "Yalın mı, Premium mu?", "alt": "Videoda üçünü karşılaştırdık"},
    }


FORMATLAR = {"sektor_demo": sektor_demo, "ozellik": ozellik, "yz_arama": yz_arama, "tema_paket": tema_paket}
