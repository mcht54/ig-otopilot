"""İçerik beyni: bugünün formatını seçer, taslağı veriden kurar, metni yapay zekâyla
parlatır, kalite kapısından geçirir. Yapay zekâ yoksa/hatalıysa kural taslağı kullanılır."""
from __future__ import annotations

import copy
import datetime as dt
import json
import os
import random
import re
import statistics

from . import llm
from .kaynak import davetiyeler, markakarnem, sgb, sitemucidi
from .ortak import gecmis, kullanilan_anahtarlar, log, simdi

KAYNAKLAR = {"sitemucidi": sitemucidi, "davetiyeler": davetiyeler, "sgb": sgb, "markakarnem": markakarnem}

# Slot → en fazla karakter (videoda okunabilirlik + Instagram arayüzü)
SINIR = {"etiket": 26, "baslik": 62, "alt": 84, "ust_yazi": 46, "madde": 54}
GENEL_YASAK = ["en çok satan", "en çok bakılan", "en çok tercih", "en iyi", "en ucuz", "garanti", "1 numara", "bir numara",
               "türkiye'nin en", "sınırlı stok", "son gün", "bedava"]


# ---------------- format seçimi ve öğrenme ----------------

def format_carpani(kod: str) -> dict[str, float]:
    """Ölçülen gönderilerin skorlarından format çarpanı (0.5–2). En az 2 örnek gerekir."""
    skorlar: dict[str, list[float]] = {}
    for k in gecmis(kod):
        if k.get("tur") == "reels" and k.get("skor") is not None:
            skorlar.setdefault(k["format"], []).append(k["skor"])
    hepsi = [s for v in skorlar.values() for s in v]
    if len(hepsi) < 4:
        return {}
    ort = statistics.mean(hepsi) or 1e-9
    return {f: max(0.5, min(2.0, statistics.mean(v) / ort)) for f, v in skorlar.items() if len(v) >= 2}


def format_sirasi(kod: str, marka: dict, rnd: random.Random, gun: dt.date | None = None, onceki_format: str | None = None) -> list[str]:
    taban = dict(marka["formatlar"])
    carpan = format_carpani(kod)
    dun = ((gun or simdi().date()) - dt.timedelta(days=1)).isoformat()
    dunku = onceki_format or next((k["format"] for k in gecmis(kod) if k.get("tarih") == dun and k.get("tur") == "reels"), None)
    agirlik = {f: w * carpan.get(f, 1.0) * (0.25 if f == dunku else 1.0) for f, w in taban.items()}
    if rnd.random() < 0.15:  # keşif: arada az denenen formatı da dene
        agirlik = {f: 1.0 for f in taban}
    sira = []
    havuz = dict(agirlik)
    while havuz:
        f = rnd.choices(list(havuz), weights=list(havuz.values()))[0]
        sira.append(f)
        havuz.pop(f)
    return sira


def _kisalt(v: str, n: int) -> str:
    return v if len(v) <= n else v[: n - 1].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"


def guncel_marka(kod: str) -> dict:
    """Marka profili + o anki aşaması (ör. Bungalov'da listede tesis yokken içerik tesis sahiplerine döner)."""
    from .ortak import marka as _marka
    m = _marka(kod)
    ayar = getattr(KAYNAKLAR.get(kod), "asama_ayari", None)
    if ayar:
        try:
            ek = ayar(m)
            if ek:
                log(f"{kod}: aşama {ek.get('asama')} ({ek})")
            m.update(ek)
        except Exception as e:
            log(f"{kod}: aşama okunamadı ({e}); varsayılan")
    return m


def taslak_kur(kod: str, marka: dict, format_ad: str, ctx: dict) -> dict | None:
    f = KAYNAKLAR[kod].FORMATLAR[format_ad]
    s = f(ctx)
    if not s:
        return None
    if marka.get("asama") == "kurulus" and hasattr(KAYNAKLAR[kod], "kurulus_temizle"):
        s = KAYNAKLAR[kod].kurulus_temizle(s)
    s["format"] = format_ad
    s["olgular"] = [o for o in s.get("olgular", []) if o]
    liste = next((x for x in s["sahneler"] if x.get("tip") == "liste"), None)
    if liste:
        s["tam_maddeler"] = list(liste.get("maddeler", []))
    # kural metinleri her zaman sınır içinde kalsın (güvenlik ağı)
    return slot_yaz(s, {k: _kisalt(v, slot_sinir(k)) for k, v in slotlar(s).items()})


# ---------------- metin slotları ----------------

def slotlar(senaryo: dict) -> dict[str, str]:
    d: dict[str, str] = {}
    for i, sh in enumerate(senaryo["sahneler"]):
        for alan in ("etiket", "baslik", "alt", "ust_yazi"):
            if sh.get(alan):
                d[f"s{i}.{alan}"] = sh[alan]
        for j, m in enumerate(sh.get("maddeler", [])):
            d[f"s{i}.madde{j}"] = m
        for j, e in enumerate(sh.get("eylemler", [])):
            if "ust_yazi" in e and e["ust_yazi"]:
                d[f"s{i}.eylem{j}"] = e["ust_yazi"]
    h = senaryo.get("hikaye", {})
    for alan in ("etiket", "baslik", "alt"):
        if h.get(alan):
            d[f"h.{alan}"] = h[alan]
    return d


def slot_sinir(anahtar: str) -> int:
    alan = anahtar.split(".", 1)[1]
    if alan.startswith("madde"):
        return SINIR["madde"]
    if alan.startswith("eylem"):
        return SINIR["ust_yazi"]
    return SINIR.get(alan, 80)


def slot_yaz(senaryo: dict, d: dict[str, str]) -> dict:
    s = copy.deepcopy(senaryo)
    for k, v in d.items():
        bolum, alan = k.split(".", 1)
        hedef = s["hikaye"] if bolum == "h" else s["sahneler"][int(bolum[1:])]
        if alan.startswith("madde"):
            hedef["maddeler"][int(alan[5:])] = v
        elif alan.startswith("eylem"):
            hedef["eylemler"][int(alan[5:])]["ust_yazi"] = v
        else:
            hedef[alan] = v
    return s


# ---------------- açıklama (caption) ----------------

def etiket_sec(marka: dict, rnd: random.Random, ek: list[str] | None = None) -> list[str]:
    havuz = list(dict.fromkeys(marka["etiketler"]))
    sec = havuz[:2] + rnd.sample(havuz[2:], k=min(3, len(havuz) - 2))
    for e in ek or []:
        e = "#" + re.sub(r"[^\wçğıöşüÇĞİÖŞÜ]", "", e.lstrip("#").lower())
        if len(e) > 2 and e not in sec:
            sec.insert(2, e)
    return sec[:5]


def kural_aciklama(senaryo: dict, marka: dict, rnd: random.Random) -> str:
    sh = senaryo["sahneler"]
    kapak = next((x for x in sh if x.get("tip") == "kapak"), sh[0])
    liste = next((x for x in sh if x.get("tip") == "liste"), None)
    satirlar = [kapak.get("baslik") or senaryo["konu"]]
    if kapak.get("alt"):
        satirlar.append(kapak["alt"])
    satirlar.append("")
    if liste:
        satirlar.append(liste["baslik"])
        tam = senaryo.get("tam_maddeler") if len(senaryo.get("tam_maddeler") or []) == len(liste["maddeler"]) else None
        satirlar += [f"✔️ {m}" for m in (tam or liste["maddeler"])]
        satirlar.append("")
    ak = senaryo.get("anahtar_kelime")
    if marka.get("kaydet_satiri"):
        satirlar.append(marka["kaydet_satiri"])
    elif ak:
        satirlar.append(f"{ak[:1].upper() + ak[1:]} arıyorsanız bu videoyu kaydedin, lazım olduğunda elinizin altında olsun.")
    satirlar.append(f"👉 {marka['cta']}: {marka['site_kisa']}")
    satirlar.append("")
    satirlar.append(" ".join(etiket_sec(marka, rnd)))
    return "\n".join(satirlar)


# ---------------- yapay zekâ ile parlatma ----------------

def _sistem(marka: dict) -> str:
    return f"""Sen {marka['ad']} markasının Instagram içerik yazarısın. Türkçe yazarsın, büyüme odaklı düşünürsün:
ilk 1 saniyede merak uyandıran kanca, kaydetmeye ve paylaşmaya değer somut bilgi, net harekete çağrı.
Hedef kitle: {marka['hedef_kitle'].strip()}
Ses tonu: {marka['ses_tonu'].strip()}
Değer önerisi: {' | '.join(marka['deger_onerisi'])}
KESİN KURALLAR:
- Yalnız verilen OLGULAR'a dayan. Olgularda olmayan rakam, fiyat, süre, sıralama, "en çok/en iyi" iddiası, müşteri sayısı UYDURMA.
- Yasak ifadeler: {', '.join(marka['yasak_ifadeler'] + GENEL_YASAK)}.
- Videodaki yazılarda emoji yok. Her slotun karakter sınırına uy (verildi). Kısa, konuşur gibi cümleler.
- Açıklama (caption): ilk satır 70 karakteri geçmeyen kanca ve anahtar kelimeyi doğal biçimde içerir (Instagram araması için);
  sonra 2-4 kısa satır değer; sonra "{marka['cta']}: {marka['site_kisa']}"; en sonda 3-5 hashtag. En fazla 3 emoji.
- Hikâye yazıları videodan farklı, merak uyandıran kısa bir teaser olsun.
Yalnız JSON döndür."""


def parlat(senaryo: dict, marka: dict, kod: str, rnd: random.Random) -> tuple[dict, str, str]:
    """(senaryo, aciklama, kaynak) döndürür. kaynak: 'gemini' | 'groq' | 'kural'."""
    kural = kural_aciklama(senaryo, marka, rnd)
    if not llm.var_mi():
        return senaryo, kural, "kural"
    d = slotlar(senaryo)
    sinirli = {k: {"metin": v, "en_fazla": slot_sinir(k)} for k, v in d.items()}
    onceki = [k.get("baslik", "") for k in gecmis(kod)[-20:] if k.get("tur") == "reels"]
    iyi = sorted([k for k in gecmis(kod) if k.get("skor") is not None], key=lambda k: -k["skor"])
    istem = json.dumps({
        "gorev": "Aşağıdaki Reels taslağının yazılarını daha çekici, daha net ve büyüme odaklı yeniden yaz. Anahtarları AYNEN koru.",
        "format": senaryo["format"], "konu": senaryo["konu"], "anahtar_kelime": senaryo.get("anahtar_kelime"),
        "konum": marka.get("konum"), "OLGULAR": senaryo["olgular"],
        "slotlar": sinirli,
        "son_kancalar_tekrar_etme": onceki,
        "en_iyi_performans_kancalari": [k["baslik"] for k in iyi[:3]],
        "en_zayif_performans_kancalari": [k["baslik"] for k in iyi[-3:]] if len(iyi) > 5 else [],
        "hashtag_havuzu": marka["etiketler"],
        "cikti_bicimi": {"slotlar": {"<aynı anahtar>": "<yeni metin>"}, "aciklama": "<caption>", "neden": "<1 cümle: bu açıyı neden seçtin>"},
    }, ensure_ascii=False)
    from . import strateji
    yanit = llm.json_sor(_sistem(marka) + "\n" + strateji.baglam(kod, marka), istem)
    if not yanit or not isinstance(yanit.get("slotlar"), dict):
        log("yapay zekâ yanıtı yok → kural metni")
        return senaryo, kural, "kural"
    yeni = {k: str(yanit["slotlar"].get(k, v)).strip() for k, v in d.items()}
    aday = slot_yaz(senaryo, yeni)
    aciklama = str(yanit.get("aciklama", "")).strip()
    hatalar = metin_denetle(aday, aciklama, marka, referans=senaryo)
    if hatalar:
        log("yapay zekâ metni kaliteden geçmedi → kural metni:", "; ".join(hatalar[:4]))
        return senaryo, kural, "kural"
    log(f"metin: {yanit.get('_saglayici')} — {yanit.get('neden', '')[:120]}")
    aday, aciklama, rapor = strateji.editor(aday, aciklama, marka, kod, slotlar, slot_yaz, slot_sinir, metin_denetle)
    aday["editor"] = rapor
    return aday, aciklama, yanit.get("_saglayici", "llm")


# ---------------- kalite kapısı (metin) ----------------

def _rakamlar(s: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", s))


def metin_denetle(senaryo: dict, aciklama: str, marka: dict, referans: dict | None = None) -> list[str]:
    hatalar = []
    yasak = [y.lower() for y in marka["yasak_ifadeler"] + GENEL_YASAK]
    izinli_rakam = _rakamlar(" ".join(senaryo.get("olgular", [])) + " " + json.dumps(referans or senaryo, ensure_ascii=False))
    for k, v in slotlar(senaryo).items():
        if not v.strip():
            hatalar.append(f"{k} boş")
        if len(v) > slot_sinir(k):
            hatalar.append(f"{k} uzun ({len(v)}>{slot_sinir(k)})")
        if any(y in v.lower() for y in yasak):
            hatalar.append(f"{k} yasak ifade: {v}")
        if _rakamlar(v) - izinli_rakam:
            hatalar.append(f"{k} kaynaksız rakam: {v}")
        if re.search(r"[\U0001F300-\U0001FAFF]", v):
            hatalar.append(f"{k} emoji")
    if aciklama:
        if len(aciklama) > 2100:
            hatalar.append("açıklama çok uzun")
        if len(re.findall(r"#\w", aciklama)) > 5:
            hatalar.append("5'ten fazla hashtag")
        if any(y in aciklama.lower() for y in yasak):
            hatalar.append("açıklamada yasak ifade")
        if _rakamlar(aciklama) - izinli_rakam - {"7", "3"}:
            hatalar.append(f"açıklamada kaynaksız rakam: {_rakamlar(aciklama) - izinli_rakam}")
        if marka["site_kisa"] not in aciklama:
            hatalar.append("açıklamada site adresi yok")
    return hatalar


# ---------------- ana giriş ----------------

def planla(kod: str, marka: dict, tarayici, klasor, atla: set[str] | None = None, gun: dt.date | None = None,
           ek_kullanilan: set[str] | None = None, onceki_format: str | None = None) -> dict:
    """gun verilirse o gün için (ileri tarihli plan) kurar; ek_kullanilan: haftalık plandaki diğer günlerin anahtarları."""
    g = gun or simdi().date()
    an = simdi() if gun is None else dt.datetime.combine(g, dt.time(12, 0), tzinfo=simdi().tzinfo)
    tohum = f"{kod}:{g.isoformat()}"
    rnd = random.Random(tohum)
    ek = set(ek_kullanilan or ())
    ctx = {
        "tarayici": tarayici, "marka": marka, "klasor": klasor, "rnd": rnd, "simdi": an,
        "tarih": g.isoformat(),
        "kullanilan": kullanilan_anahtarlar(kod, 120) | {a for k in gecmis(kod) for a in k.get("ek_anahtarlar", [])} | ek,
        "kullanilan_yakin": kullanilan_anahtarlar(kod, 14) | ek,
    }
    klasor.mkdir(parents=True, exist_ok=True)
    sira = format_sirasi(kod, marka, rnd, g, onceki_format)
    zorla = os.environ.get("OTOPILOT_FORMAT")
    if zorla:
        sira = [zorla] + [f for f in sira if f != zorla]
    hatalar = []
    for tur in ("normal", "gevsek"):
        if tur == "gevsek":  # aylar içinde konu havuzu tükendiyse yalnız son 14 günü tekrar sayma
            ctx["kullanilan"] = ctx["kullanilan_yakin"]
        for f in [x for x in sira if x not in (atla or set())]:
            try:
                s = taslak_kur(kod, marka, f, ctx)
            except Exception as e:  # site geçici hata verirse sıradaki formata geç
                hatalar.append(f"{f}: {e}")
                log(f"format {f} kurulamadı: {e}")
                continue
            if s:
                s["tohum"] = tohum
                s["denenen_formatlar"] = sira
                return s
    if YEDEK not in (atla or set()):
        log(f"{kod}: hiçbir format kurulamadı ({hatalar}); ağsız yedek içerik kullanılıyor")
        s = yedek_icerik(kod, marka, ctx)
        s["tohum"] = tohum
        s["denenen_formatlar"] = sira + [YEDEK]
        return s
    raise RuntimeError(f"hiçbir format kurulamadı: {hatalar}")


YEDEK = "yedek"


def yedek_icerik(kod: str, marka: dict, ctx: dict) -> dict:
    """Site/veri kaynağı tamamen erişilemezken bile o günün paylaşımı düşmesin: yalnız marka profilindeki
    (doğrulanmış) değer önerileriyle, internete ihtiyaç duymayan kart videosu."""
    rnd = ctx["rnd"]
    ak = rnd.choice(marka["anahtar_kelimeler"])
    maddeler = list(marka["deger_onerisi"])[:4]
    basliklar = [f"{ak[:1].upper() + ak[1:]} için bilmeniz gerekenler", f"{marka['ad']} ne işe yarar?", f"Neden {marka['ad']}?"]
    baslik = rnd.choice(basliklar)
    s = {
        "format": YEDEK, "anahtar": f"yedek:{ctx['tarih']}", "konu": baslik, "anahtar_kelime": ak,
        "olgular": maddeler,
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "etiket": marka["ad"], "baslik": baslik, "alt": marka["cta"]},
            {"tur": "kart", "tip": "liste", "sure": 5.6, "etiket": "Kısaca", "baslik": f"{marka['ad']} ile", "maddeler": maddeler},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": marka["ad"]},  # şablon site ve CTA satırını kendisi ekler
        ],
        "hikaye": {"etiket": marka["ad"], "baslik": baslik, "alt": marka["cta"]},
    }
    s["tam_maddeler"] = list(maddeler)
    return slot_yaz(s, {k: _kisalt(v, slot_sinir(k)) for k, v in slotlar(s).items()})


def iddia_kontrol(kod: str, senaryo: dict) -> dict:
    """Üretim günü son kontrol (plan günler önce kurulmuş olabilir): kampanya/deneme iddiası sitede artık yoksa çıkarılır."""
    from .kaynak import iddia_temizle
    if kod == "davetiyeler":
        if not davetiyeler.hediye_suruyor():
            return iddia_temizle(senaryo, r"hediye|650\+KDV|650 değerinde", "Tüm modeller sitede")
    elif kod == "sgb":
        m = guncel_marka("sgb")
        if m.get("asama") == "kurulus":
            return sgb.kurulus_temizle(senaryo)
    elif kod == "sitemucidi":
        from .kaynak import sitede_var
        if not sitede_var(f"{sitemucidi.SITE}/", r"7 gün"):
            return iddia_temizle(senaryo, r"7 gün", "Sitenizi ücretsiz oluşturun")
    return senaryo
