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
import re

from . import llm
from .ortak import DURUM, gecmis, json_kaydet, log, simdi

ARASTIRMA_GUN = 7
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


def arastir(kod: str, m: dict, zorla: bool = False) -> dict:
    """Haftada bir (Google Arama destekli). Başarısızsa eski araştırma kalır."""
    eski = arastirma(kod)
    if not zorla and eski.get("tarih") and (simdi().date() - dt.date.fromisoformat(eski["tarih"])).days < ARASTIRMA_GUN:
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
             'Yalnız JSON döndür: {"trendler": [""], "kancalar": [""], "rakip_dersleri": [""], "sorular": [""], "mevsim": [""], "kacinilacak": [""]}')
    try:
        sonuc = llm.ara(istem)
    except Exception as e:
        log(f"{kod} araştırma yapılamadı: {e}")
        return eski
    veri = _json_bul((sonuc or {}).get("metin", ""))
    if not veri:
        log(f"{kod} araştırma yanıtı çözülemedi; eski araştırma kullanılıyor")
        return eski
    temiz = {k: [str(x)[:220] for x in (veri.get(k) or [])][:8] for k in ("trendler", "kancalar", "rakip_dersleri", "sorular", "mevsim", "kacinilacak")}
    temiz.update(tarih=simdi().date().isoformat(), kaynaklar=[k for k in (sonuc.get("kaynaklar") or [])][:12])
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
                                ("RAKİPLERDEN DERSLER", "rakip_dersleri"), ("İNSANLARIN SORDUĞU SORULAR", "sorular"),
                                ("MEVSİM/GÜNDEM", "mevsim"), ("İZLEYİCİYİ KAÇIRAN HATALAR", "kacinilacak")):
            if a.get(anahtar):
                parcalar.append(f"{baslik}: " + " | ".join(a[anahtar][:6]))
    son = son_konular(kod)
    if son:
        parcalar.append("SON İÇERİKLER (aynı konuyu/kancayı TEKRAR ETME, farklı açı bul): " + " | ".join(son[-20:]))
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
