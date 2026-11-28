"""İçerik zekâsı: gerçek bir sosyal medya yöneticisi gibi düşünmek için bağlam + araştırma + editör denetimi.

- Strateji bilgisi (markalar/<kod>.yaml → strateji): kitlenin derdi, en çok dikkat ettiği şeyler, itirazlar, ürünün
  gerçek özellikleri, içerik sütunları, kanca kalıpları, kaçınılacaklar.
- Haftalık araştırma (Gemini + Google Arama, ücretsiz katman): Türkiye'de bu alanda tutan Reels/TikTok içerik türleri,
  kancalar, rakip hesapların ne yaptığı, insanların sorduğu sorular, mevsim/gündem. durum/<kod>/arastirma.json.
- Tekrar freni: son 30 içeriğin konusu/kancası her istemde "tekrar etme" olarak verilir.
- Editör: yazılan içerik bir kontrol listesiyle puanlanır (kanca, kitle dili, tek mesaj, değer, CTA, hata, tekrar);
  zayıfsa editör önerisi denetimden geçerse uygulanır. Hiçbir adım paylaşımı durdurmaz.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import os
import re

from . import llm
from .ortak import DURUM, gecmis, json_kaydet, log, simdi

ARASTIRMA_GUN = 7
# Rakip / sektörde güçlü hesaplar (2026-11-26 API ile okunabildiği doğrulandı). Gerçek, herkese açık paylaşım verisi araştırmaya girer.
YT_SORGU = {"sitemucidi": ["esnaf web sitesi", "web sitesi kurma", "google haritalar işletme"], "davetiyeler": ["dijital davetiye", "düğün davetiyesi fikir"],
            "sgb": ["sapanca bungalov", "bungalov tatil", "hafta sonu kaçamak"], "markakarnem": ["işletme instagram hataları", "küçük işletme pazarlama"]}
RAKIP = {"sitemucidi": ["syncoretr", "ikas", "ideasoft", "ticimax"], "davetiyeler": ["davetiyeci", "davetiyem"],
         "sgb": ["sapancabungalov", "sapancatatil", "sapancaevleri"], "markakarnem": ["eleganzaajans", "sovaajans"]}


def _rakip_verisi(kod: str) -> str:
    """Rakiplerin son 60 günde en çok tutan paylaşımları (radar). Okunamazsa boş; araştırma yine yapılır."""
    try:
        from . import radar
        from .instagram import Instagram
        ig = Instagram(kod)
        hs = [h for h in (radar.hesap_oku(ig.kimlik, ig.anahtar, u) for u in RAKIP.get(kod, [])) if h] if ig.hazir else []
        t = radar.tutanlar(hs, en_cok=8)
        e = radar.yt_erisim(os.environ.get("YT_CLIENT_ID", ""), os.environ.get("YT_CLIENT_SECRET", ""),
                            os.environ.get(f"YT_{kod.upper()}_REFRESH_TOKEN") or os.environ.get("YT_SITEMUCIDI_REFRESH_TOKEN", ""))
        t += radar.yt_trend(e, YT_SORGU.get(kod, []), en_cok=6)
        if t:
            log(f"{kod} rakip radarı: {len(hs)} hesap, {len(t)} tutan paylaşım")
        return json.dumps([{k: x.get(k) for k in ("tur", "izlenme", "begeni", "yorum", "kat", "aciklama")} for x in t], ensure_ascii=False)[:6000] if t else ""
    except Exception as e:  # noqa: BLE001
        log(f"{kod} rakip radarı okunamadı: {type(e).__name__}")
        return ""
BASARISIZ_SAAT = 6  # (2026-11-26: 24 → 6) başarısız araştırma her plan çalıştırmasında yeniden denenip kota yakmasın
NIS = {
    "sitemucidi": "esnaf ve küçük işletmeler için web sitesi kurma, Google'da ve yapay zekâ aramasında görünme",
    "davetiyeler": "düğün, nişan, kına ve sünnet davetiyesi; dijital davetiye; düğün hazırlığı",
    "sgb": "Sapanca bungalov tatili, kapora dolandırıcılığı, bungalov işletmeciliği ve doğrudan misafir bulma",
    "markakarnem": "küçük işletmeler için yerel SEO, Google İşletme Profili, Google Haritalar ve Instagram büyümesi",
}


# ---------------- araştırma ----------------

def _yol(kod: str):
    return DURUM / kod / "arastirma.json"


def arastirma(kod: str) -> dict:
    p = _yol(kod)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _json_bul(metin: str) -> dict | None:
    m = re.search(r"\{.*\}", metin or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _deneme_yeni(eski: dict) -> bool:
    """Son deneme başarısızsa ve üzerinden BASARISIZ_SAAT geçmediyse True."""
    if eski.get("durum") != "basarisiz" or not eski.get("son_deneme"):
        return False
    try:
        return simdi() - dt.datetime.fromisoformat(eski["son_deneme"]) < dt.timedelta(hours=BASARISIZ_SAAT)
    except (TypeError, ValueError):
        return False


def _basarisiz(kod: str, eski: dict, neden: str) -> dict:
    """Deneme zamanı ve durumu kaydedilir; önceki başarılı bulgular (ve 'tarih') korunur."""
    kayit = {**eski, "son_deneme": simdi().isoformat(), "durum": "basarisiz", "neden": neden[:160]}
    json_kaydet(_yol(kod), kayit)
    return kayit


def arastir(kod: str, m: dict, zorla: bool = False) -> dict:
    """Haftada bir (Google Arama destekli). Başarısızsa eski araştırma kalır ve 24 saat yeniden denenmez."""
    eski = arastirma(kod)
    if not zorla and eski.get("tarih") and (simdi().date() - dt.date.fromisoformat(eski["tarih"])).days < ARASTIRMA_GUN:
        return eski
    if not zorla and _deneme_yeni(eski):
        return eski
    ay = simdi().strftime("%B %Y")
    istem = (f"Türkiye'de Instagram Reels ve TikTok'ta şu alanı araştır: {NIS.get(kod, m['ad'])}. Hedef kitle: {m['hedef_kitle'].strip()}\n"
             f"Bugün {simdi().date().isoformat()} ({ay}). Şunları bul ve somut yaz:\n"
             "1) Son dönemde bu alanda en çok izlenen/kaydedilen/paylaşılan kısa video türleri ve neden tuttukları\n"
             "2) Çok tutan açılış kancaları (ilk 1-2 saniyede söylenen cümle kalıpları)\n"
             "3) Bu alandaki rakip ya da benzer Türk hesapların hangi içerikleri iyi gidiyor (hesap adlarıyla, kopyalamadan ders çıkar)\n"
             "4) İnsanların bu konuda en çok sorduğu sorular ve en büyük endişeleri\n"
             "5) Bu ay ve önümüzdeki haftalar için mevsim/gündem fırsatları\n"
             "6) Bu alanda izleyiciyi kaçıran, kaçınılması gereken hatalar\n"
             'Yalnız JSON döndür: {"trendler": [""], "kancalar": [""], "rakip_dersleri": [""], "sorular": [""], "mevsim": [""], "kacinilacak": [""], "farklilasma": [""]}')
    rv = _rakip_verisi(kod)
    if rv:
        istem += ("\n\nRAKİPLERİN GERÇEK VERİSİ (Instagram, son 60 gün, en çok tutan paylaşımlar; kat = hesabın kendi ortalamasının kaç katı): " + rv +
                  "\nBunlardan rakip_dersleri'ni ÇIKAR (neden tuttu?) ve 'farklilasma'ya rakiplerin yapmadığı, bizim öne çıkacağımız açıları yaz. "
                  "Rakip adını ve metnini içeriğe KOPYALAMA. Argo, bahis/kumar, alkol, +18 fikir verme.")
    try:  # ücretsiz katmanda Google araması sürekli 429 (2026-11-26 ölçüldü): rakip verisi varsa arama denenmez, doğrudan veriden çıkarılır
        sonuc = None if rv else llm.ara(istem)
    except Exception as e:
        log(f"{kod} araştırma yapılamadı: {e}")
        return _basarisiz(kod, eski, f"{type(e).__name__}")
    veri = _json_bul((sonuc or {}).get("metin", ""))
    if not veri and rv:  # arama kotası (429) düştüyse: rakiplerin GERÇEK verisinden aramasız çıkarım (Gemini/Groq) — boş kalmasın
        try:
            v2 = llm.json_sor("Sen deneyimli bir sosyal medya stratejistisin. Web araması yapamıyorsun; YALNIZ verilen rakip verisinden "
                              "çıkarım yap, olmayan trend/rakam uydurma. Yalnız JSON döndür.", istem.split("Şunları bul", 1)[0] +
                              "\nGörev: aşağıdaki gerçek rakip verisinden trendler (tutan video türleri), kancalar, rakip_dersleri, "
                              "kacinilacak ve farklilasma çıkar; sorular ve mevsim boş kalabilir.\n" + istem.split("RAKİPLERİN GERÇEK VERİSİ", 1)[-1] +
                              '\nJSON: {"trendler": [""], "kancalar": [""], "rakip_dersleri": [""], "sorular": [], "mevsim": [], "kacinilacak": [""], "farklilasma": [""]}')
            if isinstance(v2, dict) and any(v2.get(k) for k in ("trendler", "rakip_dersleri", "kancalar")):
                veri, sonuc = v2, {"kaynaklar": [f"instagram.com/{u}" for u in RAKIP.get(kod, [])]}
                log(f"{kod} arama yok; araştırma rakip verisinden çıkarıldı")
        except Exception as e:  # noqa: BLE001
            log(f"{kod} rakip verisinden çıkarım yapılamadı: {type(e).__name__}")
    if not veri:
        log(f"{kod} araştırma yanıtı {'alınamadı' if not sonuc else 'çözülemedi'}; eski araştırma kullanılıyor, {BASARISIZ_SAAT} saat yeniden denenmeyecek")
        return _basarisiz(kod, eski, "yanıt yok" if not sonuc else "yanıt çözülemedi")
    from .guvenlik import uygunsuz
    temiz = {k: [str(x)[:220] for x in (veri.get(k) or []) if not uygunsuz(str(x))][:8]
             for k in ("trendler", "kancalar", "rakip_dersleri", "sorular", "mevsim", "kacinilacak", "farklilasma")}
    temiz.update(tarih=simdi().date().isoformat(), son_deneme=simdi().isoformat(), durum="basarili", kaynaklar=[k for k in (sonuc.get("kaynaklar") or [])][:12])
    json_kaydet(_yol(kod), temiz)
    log(f"{kod} araştırma güncellendi: {len(temiz['trendler'])} trend, {len(temiz['kancalar'])} kanca, {len(temiz['sorular'])} soru")
    return temiz


# ---------------- bağlam ----------------

def son_konular(kod: str, n: int = 30) -> list[str]:
    from . import plan
    ks = [f"{k.get('baslik') or k.get('konu')}" for k in gecmis(kod) if k.get("tur") == "reels"][-n:]
    ks += [f"{o.get('konu')}" for o in plan.oku(kod).values()]
    return [k for k in ks if k and k != "None"][-n:]


def baglam(kod: str, m: dict) -> str:
    """Her metin yazımında sistem istemine eklenen düşünme çerçevesi."""
    s = m.get("strateji") or {}
    a = arastirma(kod)
    parcalar = [
        "DÜŞÜNME BİÇİMİN: Gerçek bir insan, bu kitlenin içinden biri gibi düşün. İzleyici kaydırırken neden durur, neyi merak eder, "
        "neye güvenir, neyi kaydedip arkadaşına gönderir? Tek videoda tek net mesaj. Kitlenin en çok dikkat ettiği şeyi öne çıkar. "
        "Ekran yazısı 1 saniyede okunur olsun; yazım ve dil hatası yapma.",
    ]
    if m.get("asama") == "kurulus":
        parcalar.append("AŞAMA: Sitede henüz listelenen tesis yok. Tesis sahiplerine hitap et; misafire 'listede tesis var' izlenimi verme.")
    for baslik, anahtar in (("KİTLE İÇGÖRÜSÜ", "kitle_icgorusu"), ("EN ÇOK DİKKAT ETTİKLERİ", "dikkat_ettikleri"), ("İTİRAZLARI", "itirazlar"),
                            ("ÜRÜNÜN GERÇEK ÖZELLİKLERİ (yalnız bunları söyle)", "ozellikler"), ("İÇERİK SÜTUNLARI", "icerik_sutunlari"),
                            ("KANCA KALIPLARI (ilham, birebir kopyalama)", "kanca_kaliplari"), ("KAÇIN", "kacinilacaklar")):
        if s.get(anahtar):
            parcalar.append(f"{baslik}: " + " | ".join(map(str, s[anahtar])))
    if a:
        for baslik, anahtar in (("BU HAFTA TUTAN İÇERİKLER (araştırma)", "trendler"), ("TUTAN KANCALAR (araştırma)", "kancalar"),
                                ("RAKİPLERDEN DERSLER (gerçek veriden)", "rakip_dersleri"), ("RAKİPLERDEN FARKIMIZ", "farklilasma"),
                                ("İNSANLARIN SORDUĞU SORULAR", "sorular"),
                                ("MEVSİM/GÜNDEM", "mevsim"), ("İZLEYİCİYİ KAÇIRAN HATALAR", "kacinilacak")):
            if a.get(anahtar):
                parcalar.append(f"{baslik}: " + " | ".join(a[anahtar][:6]))
    son = son_konular(kod)
    if son:
        parcalar.append("SON İÇERİKLER (aynı konuyu/kancayı TEKRAR ETME, farklı açı bul): " + " | ".join(son[-20:]))
    from .gundem_notu import metin as _gundem  # doğrulanmış, tarihli gündem (2026-11-27): haftada 3 gün, süresi geçen düşer
    g = _gundem(pathlib.Path(__file__).parent / "gundem" / f"{kod}.json")
    if g:
        parcalar.append(g)
    ogr = pathlib.Path(__file__).parent / "ogrenme" / f"{kod}.md"   # öğrenme döngüsü (2026-11-28): sunucu Pzt/Per yazar
    if ogr.exists():
        parcalar.append("KENDİ ÖLÇÜMÜMÜZDEN DERSLER (bu hesabın gerçek izlenme verisi; marka kurallarıyla çelişirse marka kuralları geçerli):\n"
                        + ogr.read_text(encoding="utf-8")[:3000])
    return "\n".join(parcalar)


# ---------------- editör ----------------

ESIK = 7.0


def editor(senaryo: dict, aciklama: str, m: dict, kod: str, slotlar_f, slot_yaz_f, slot_sinir_f, denetle_f) -> tuple[dict, str, dict]:
    """Kıdemli editör gibi puanlar; ortalama < ESIK ise önerdiği düzeltmeyi (denetimden geçerse) uygular.
    Dönen: (senaryo, aciklama, rapor)."""
    d = slotlar_f(senaryo)
    istem = json.dumps({
        "gorev": ("Bu Instagram Reels taslağını yayından önce kıdemli bir sosyal medya editörü gibi değerlendir. Her ölçüte 1-10 puan ver. "
                  "Ortalama 7'nin altındaysa, ya da yazım/dil hatası varsa slotları düzelt (anahtarları AYNEN koru, sınırlara uy, "
                  "OLGULAR dışında bilgi ekleme)."),
        "olcutler": ["kanca: ilk saniyede durdurur mu", "kitle: hedef kitlenin dilinde ve derdinde mi", "tek_mesaj: tek net fikir mi",
                     "deger: kaydetmeye/paylaşmaya değer bilgi var mı", "cta: ne yapacağı net mi", "hata: yazım/dil/anlam hatası yok mu (10=hiç yok)",
                     "ozgunluk: son içeriklerden farklı mı"],
        "OLGULAR": senaryo.get("olgular", []),
        "slotlar": {k: {"metin": v, "en_fazla": slot_sinir_f(k)} for k, v in d.items()},
        "aciklama": aciklama,
        "cikti_bicimi": {"puanlar": {"kanca": 0, "kitle": 0, "tek_mesaj": 0, "deger": 0, "cta": 0, "hata": 0, "ozgunluk": 0},
                         "notlar": "<kısa>", "slotlar": {"<yalnız değişen anahtar>": "<yeni metin>"}, "aciklama": "<gerekirse yeni caption, yoksa boş>"},
    }, ensure_ascii=False)
    sistem = f"Sen {m['ad']} için çalışan titiz bir içerik editörüsün.\n" + baglam(kod, m)
    rapor: dict = {"puan": None, "uygulandi": False}
    try:
        y = llm.json_sor(sistem, istem)
    except Exception as e:
        log(f"editör çalışmadı: {e}")
        return senaryo, aciklama, rapor
    if not y or not isinstance(y.get("puanlar"), dict):
        return senaryo, aciklama, rapor
    puanlar = [float(v) for v in y["puanlar"].values() if isinstance(v, (int, float))]
    ort = round(sum(puanlar) / len(puanlar), 1) if puanlar else None
    rapor.update(puan=ort, puanlar=y["puanlar"], notlar=str(y.get("notlar", ""))[:300])
    hata_puani = y["puanlar"].get("hata", 10)
    if ort is not None and (ort < ESIK or (isinstance(hata_puani, (int, float)) and hata_puani < 8)):
        degisen = {k: str(v).strip() for k, v in (y.get("slotlar") or {}).items() if k in d and str(v).strip()}
        yeni_ac = str(y.get("aciklama") or "").strip() or aciklama
        if degisen or yeni_ac != aciklama:
            aday = slot_yaz_f(senaryo, degisen)
            hatalar = denetle_f(aday, yeni_ac, m, referans=senaryo)
            if not hatalar:
                rapor["uygulandi"] = True
                log(f"editör: {ort}/10 → düzeltildi ({rapor['notlar'][:120]})")
                return aday, yeni_ac, rapor
            log(f"editör önerisi denetimden geçmedi: {hatalar[:3]}")
    log(f"editör puanı: {ort}/10")
    return senaryo, aciklama, rapor
