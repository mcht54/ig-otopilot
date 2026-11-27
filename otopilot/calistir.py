"""Komut satırı:
  python -m otopilot.calistir otomatik            # saati gelmiş ve bugün yapılmamış markalar
  python -m otopilot.calistir uret --marka sgb    # tek marka, şimdi (YAYIN=acik değilse yalnız önizleme)
  python -m otopilot.calistir olc                 # tüm markaların ölçümlerini güncelle

YAYIN=acik ortam değişkeni yoksa hiçbir şey paylaşılmaz, yalnız cikti/ altına önizleme üretilir.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
import shutil
import statistics
import subprocess
import sys
import traceback
from pathlib import Path

from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright

from . import beyin, dagitim
from .film import film_yap, kapak_kare
from .instagram import Instagram, InstagramHatasi
from .ortak import (CIKTI, TR, BelirsizYayin, bugun, gizle, gecmis, gecmis_guncelle, gecmis_yaz, json_kaydet, log, marka,
                    marka_kodlari, simdi)

# Bugünün kaydı bu durumlardaysa marka yeniden üretilmez. 'belirsiz' (paylaşım gitmiş olabilir) hiçbir zaman kendiliğinden
# yeniden paylaşılmaz; 'ertelendi' (geçerli anlatım sesi yok) aynı gün sonraki çalıştırmada yeniden denenir.
TAMAM_DURUMLAR = ("yayinlandi", "onizleme", "belirsiz")
# Sürmekte olan kayıtlar (marka → {"kayit", "yayin_basladi"}): main() hata yakalayıcısı yayımlanmış Reels'i boş 'hata' ile ezmesin
_SUREN: dict[str, dict] = {}


class SesYok(RuntimeError):
    """Geçerli anlatım sesi üretilemedi: kural gereği anlatımsız (yalnız müzikli) video yayınlanmaz."""


# ---------------- video kalite denetimi ----------------

def video_denetle(yol: Path, en_az: float = 5, en_cok: float = 90) -> list[str]:
    h = []
    c = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration,size",
                        "-of", "json", str(yol)], capture_output=True, text=True)
    if c.returncode:
        return ["ffprobe okuyamadı"]
    bilgi = json.loads(c.stdout)
    akis, bicim = bilgi["streams"][0], bilgi["format"]
    if (akis["width"], akis["height"]) != (1080, 1920):
        h.append(f"boyut {akis['width']}x{akis['height']}")
    sure = float(bicim["duration"])
    if not en_az <= sure <= en_cok:
        h.append(f"süre {sure:.1f}s")
    if int(bicim["size"]) > 250 * 1024 * 1024:
        h.append("dosya çok büyük")
    # boş/tek renk kare (yüklenemeyen sayfa) var mı?
    tmp = yol.with_suffix(".kare.jpg")
    for oran in (0.1, 0.35, 0.6, 0.85):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{sure * oran:.2f}", "-i", str(yol), "-frames:v", "1", str(tmp)], check=False)
        if tmp.exists():
            sapma = statistics.mean(ImageStat.Stat(Image.open(tmp).convert("L")).stddev)
            if sapma < 6:
                h.append(f"%{int(oran*100)} noktasında boş kare")
            tmp.unlink()
    # ses: sessiz video yayınlanmaz (müzik/anlatım duyulmalı)
    v = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(yol), "-af", "volumedetect", "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", v.stderr)
    if not m or float(m.group(1)) < -40:
        h.append(f"ses yok/çok kısık ({m.group(1) if m else '?'} dB)")
    return h


# ---------------- üretim ----------------

def hikaye_sahnesi(senaryo: dict, kapak_uri: str) -> dict:
    h = senaryo.get("hikaye", {})
    if h.get("kayit_url"):
        return {"tur": "sayfa", "url": h["kayit_url"], "sure": 7.0, "ust_yazi": h.get("baslik"),
                "eylemler": [{"t": 1.4, "tikla": "davetiyeyi aç"}]}
    # Görselsiz hikâyede Reels kapağı (üzerinde yazı var) zemin yapılmaz: yazılar üst üste biniyordu; telefon çerçevesinde kullanılabilir
    gorsel = h.get("gorsel") or (kapak_uri if h.get("telefon") else None)
    return {"tur": "kart", "tip": "hikaye", "sure": 6.0, "gorsel": gorsel, "telefon": h.get("telefon"),
            "etiket": h.get("etiket"), "baslik": h.get("baslik") or senaryo["konu"], "alt": h.get("alt")}



# Bu markaların hikâyesini Mac'teki Hikâye Robotu atar (Reels'i "hikâyene ekle" ile, tıklanabilir + çıkartmalı).
# Ayrı video hikâyesi bu markalarda ATILMAZ (2026-11-27 kullanıcı kararı). Robotta oturumu olmayan marka listeye girmez.
ROBOT_HIKAYE = {x.strip() for x in os.environ.get("ROBOT_HIKAYE", "sitemucidi,sgb,markakarnem").split(",") if x.strip()}

def aciklama_denetle(aciklama: str, kod: str = "") -> str:
    """Ortak açıklama denetçisi (2026-11-27): TDK yazım + kesik satır + soru işareti + 3-5 hashtag. Hata yayını durdurmaz."""
    try:
        from . import aciklama_denetim as ad
        from . import llm

        def sor(istem: str) -> str:
            y = llm._gemini("Sen titiz bir Türkçe editörsün. Yalnız istenen JSON'u döndür.", istem)
            if not y:
                raise RuntimeError("gemini yok")
            return y

        r = ad.denetle(aciklama, "instagram", llm=sor if llm.izin("gemini") else None)
        if r["duzeltmeler"] or r["hatalar"]:
            log(f"açıklama denetimi [{kod}]: düzeltme={r['duzeltmeler'][:6]} uyarı={r['hatalar'][:3]}")
        return r["metin"] or aciklama
    except Exception as e:  # noqa: BLE001
        log(f"açıklama denetimi çalışmadı: {type(e).__name__}")
        return aciklama


def _uret_bir(kod: str, m: dict, tarayici, klasor: Path, senaryo: dict, aciklama: str, kaynak: str, anlatim: list[str] | None = None,
              hazir_parcalar: list | None = None) -> dict:
    from . import ses
    if hazir_parcalar and anlatim and len(anlatim) == len(hazir_parcalar) == len(senaryo["sahneler"]):
        anlatim_kaynagi = senaryo.get("anlatim_kaynagi") or "plan"  # ses günler önce üretildi ve denetlendi: metne dokunulmaz
    elif anlatim and len(anlatim) == len(senaryo["sahneler"]):
        hazir_parcalar = None
        anlatim_kaynagi = senaryo.get("anlatim_kaynagi") or "plan"
        if anlatim_kaynagi == "kural":  # planda kota doluyken kalıp metin yazıldıysa paylaşım günü yapay zekâyla yeniden dene
            yeni, yeni_kaynak = ses.anlatim_yaz(senaryo, m)
            if yeni_kaynak != "kural":
                anlatim, anlatim_kaynagi = yeni, yeni_kaynak
        anlatim = [ses.konusma_metni(a, m) for a in anlatim]  # eski planlarda rakam/işaret kalmasın
    else:
        hazir_parcalar = None
        anlatim, anlatim_kaynagi = ses.anlatim_yaz(senaryo, m)
    reel, ses_kaynagi = film_yap(tarayici, senaryo["sahneler"], m, klasor, "reel", senaryo["tohum"], anlatim=anlatim,
                                 hazir_parcalar=hazir_parcalar)
    senaryo.update(anlatim=anlatim, anlatim_kaynagi=anlatim_kaynagi, ses_kaynagi=ses_kaynagi)
    log(f"anlatım ({anlatim_kaynagi}, ses: {ses_kaynagi}): {' / '.join(anlatim)}")
    if ses_kaynagi == "yok":
        raise SesYok("geçerli anlatım sesi üretilemedi (Gemini sesi yok/denetimden geçmedi); anlatımsız video yayınlanmaz")
    vh = video_denetle(reel)
    if vh:
        raise RuntimeError(f"video kalite: {vh}")
    kapak = kapak_kare(reel, klasor / "kapak.jpg", 1.2)
    hikaye, _ = film_yap(tarayici, [hikaye_sahnesi(senaryo, kapak.as_uri())], m, klasor, "hikaye", senaryo["tohum"] + "h")
    hh = video_denetle(hikaye, en_az=3, en_cok=15)
    if hh:
        raise RuntimeError(f"hikâye kalite: {hh}")
    senaryo["metin_kaynagi"] = kaynak
    aciklama = aciklama_denetle(aciklama, kod)
    (klasor / "aciklama.txt").write_text(aciklama, encoding="utf-8")
    json_kaydet(klasor / "senaryo.json", senaryo)
    return {"senaryo": senaryo, "aciklama": aciklama, "reel": reel, "hikaye": hikaye, "kapak": kapak}


def uret(kod: str, tarayici, klasor: Path, hazir: dict | None = None) -> dict:
    """hazir: bugünün plan öğesi (panelde görülen/düzenlenen içerik). Üretilemezse içerik baştan kurulur."""
    m = beyin.guncel_marka(kod)
    if hazir:
        try:
            s = beyin.iddia_kontrol(kod, hazir["senaryo"])  # plan günler önce kuruldu: kampanya/deneme hâlâ geçerli mi
            log(f"{kod}: bugünün planı kullanılıyor ({hazir['format']}: {hazir['konu']})")
            s["anlatim_kaynagi"] = hazir.get("anlatim_kaynagi") or "plan"
            from . import plan
            parcalar = plan.hazir_ses(hazir, klasor)
            log(f"{kod}: {'önceden hazırlanmış ve denetlenmiş ses kullanılıyor' if parcalar else 'hazır ses yok; ses şimdi üretilecek'}")
            return _uret_bir(kod, m, tarayici, klasor, s, hazir["aciklama"], s.get("metin_kaynagi", "plan"), hazir.get("anlatim"),
                             hazir_parcalar=parcalar)
        except SesYok:
            raise  # başka formatla denemek de aynı ses servisine düşer (kota yakar); içerik ertelenir
        except Exception as e:
            log(f"{kod}: plan üretilemedi ({e}); içerik baştan kuruluyor")
            log(traceback.format_exc())
    atla: set[str] = set()
    son_hata = None
    for deneme in range(len(m["formatlar"]) + 2):  # her format bir kez + ağsız yedek
        senaryo = beyin.planla(kod, m, tarayici, klasor, atla=atla)
        rnd = random.Random(senaryo["tohum"])
        senaryo, aciklama, kaynak = beyin.parlat(senaryo, m, kod, rnd)
        hatalar = beyin.metin_denetle(senaryo, aciklama, m)
        if hatalar:
            log(f"{senaryo['format']} metin kalite hatası: {hatalar}; başka format deneniyor")
            son_hata = hatalar
            atla.add(senaryo["format"])
            continue
        try:
            return _uret_bir(kod, m, tarayici, klasor, senaryo, aciklama, kaynak)
        except SesYok:
            raise
        except Exception as e:
            son_hata = e
            log(f"{senaryo['format']} üretilemedi ({e}); başka format deneniyor")
            log(traceback.format_exc())
            atla.add(senaryo["format"])
            continue
    raise RuntimeError(f"hiçbir formatla içerik üretilemedi: {son_hata}")


def bugun_paylasildi_mi(ig: Instagram, kod: str) -> bool | None:
    """Hesapta bugün (TR) tarihli gönderi var mı? Liste okunamazsa None. Yalnız paylaşımı ENGELLEMEK için kullanılır:
    listede olmaması paylaşım olmadığının kanıtı değildir (belirsiz kayıt bununla yeniden paylaşılmaz)."""
    try:
        medya = ig.son_medyalar(10)
    except Exception as e:
        log(f"{kod}: hesaptaki son gönderiler okunamadı ({str(e)[:160]})")
        return None
    for md in medya:
        try:
            z = dt.datetime.fromisoformat(str(md.get("timestamp", "")).replace("+0000", "+00:00"))
        except ValueError:
            continue
        if z.tzinfo and z.astimezone(TR).date().isoformat() == bugun():
            return True
    return False


def _bugunku_kayit(kod: str, tarih: str) -> dict | None:
    return next((k for k in gecmis(kod) if k.get("tarih") == tarih and k.get("tur") == "reels"), None)


def gunluk(kod: str, zorla: bool = False) -> dict:
    tarih = bugun()
    yayin_acik = os.environ.get("YAYIN") == "acik"
    onceki = _bugunku_kayit(kod, tarih)
    if onceki and onceki.get("durum") in TAMAM_DURUMLAR and not zorla:
        if not (yayin_acik and onceki["durum"] == "onizleme"):
            if onceki["durum"] == "belirsiz":
                log(f"{kod}: bugünkü paylaşım belirsiz — elle kontrol edin; otomatik yeniden paylaşılmaz ({onceki.get('not_') or onceki.get('hata') or ''})")
            else:
                log(f"{kod}: bugün zaten yapıldı ({onceki['durum']})")
            return {**onceki, "atlandi": True}
    from . import plan
    ig = Instagram(kod)
    if ig.hazir:
        try:
            olc(kod, ig)
            plan.hesap_kaydet(kod, ig.hesap())
        except Exception as e:
            log(f"{kod} ölçüm hatası: {e}")
    if yayin_acik and ig.hazir and not zorla and bugun_paylasildi_mi(ig, kod):
        # geçmişte kayıt yok/hata ama hesapta bugünkü gönderi var (ör. yanıt alınamayan yayın): ikinci kez paylaşılmaz
        kayit = {"format": "?", "anahtar": "", **(onceki or {}), "tarih": tarih, "tur": "reels", "durum": "belirsiz",
                 "not_": "bugün hesapta paylaşım var, elle kontrol"}
        gecmis_guncelle(kod, kayit)
        log(f"{kod}: bugün hesapta paylaşım var → yeniden paylaşılmadı (belirsiz, elle kontrol)")
        return kayit
    klasor = CIKTI / tarih / kod
    try:
        hazir = plan.bugunku(kod, klasor)
    except Exception as e:
        log(f"{kod}: plan okunamadı ({e})")
        hazir = None
    try:
        with sync_playwright() as p:
            tarayici = p.chromium.launch(args=["--disable-gpu", "--font-render-hinting=none"])
            try:
                sonuc = uret(kod, tarayici, klasor, hazir)
            finally:
                tarayici.close()
    except SesYok as e:
        kayit = {"tarih": tarih, "tur": "reels", "durum": "ertelendi", "hata": str(e)[:300], "format": "?", "anahtar": "",
                 "not_": "geçerli anlatım sesi yok; bu çalıştırmada hiçbir platforma paylaşılmadı, sonraki çalıştırmada yeniden denenir"}
        gecmis_guncelle(kod, kayit)
        log(f"{kod}: ertelendi — {e}")
        return kayit
    s = sonuc["senaryo"]
    kayit = {
        "tarih": tarih, "tur": "reels", "format": s["format"], "anahtar": s["anahtar"], "ek_anahtarlar": s.get("ek_anahtarlar", []),
        "konu": s["konu"], "baslik": next((x.get("baslik") for x in s["sahneler"] if x.get("baslik")), s["konu"]),
        "metin_kaynagi": s["metin_kaynagi"], "durum": "onizleme", "klasor": str(klasor.relative_to(CIKTI.parent)),
        "anlatim": s.get("anlatim"), "ses_kaynagi": s.get("ses_kaynagi"), "aciklama": sonuc["aciklama"],
    }
    _SUREN[kod] = {"kayit": kayit, "yayin_basladi": False}
    try:  # video yedeği: bir platform hata verirse sonradan yalnız o platforma gönderilebilsin (eksik komutu)
        yedek = CIKTI / f"{tarih}-{kod}-reel.mp4"
        shutil.copyfile(sonuc["reel"], yedek)
        if plan.yukle(yedek):
            kayit["video_yedek"] = yedek.name
    except Exception as e:
        log(f"video yedeği yüklenemedi: {e}")
    try:  # panelde geçmiş içeriğin kapağı görünsün (GitHub sürüm dosyası; sunucuya yük yok)
        on = CIKTI / f"{tarih}-{kod}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(sonuc["kapak"]), "-vf", "scale=360:-2", "-q:v", "5", str(on)], check=True)
        if plan.yukle(on):
            kayit["gorsel"] = plan.gorsel_url(on.name, "y")
    except Exception as e:
        log(f"kapak panele yüklenemedi: {e}")
    if yayin_acik:
        if not ig.hazir:
            kayit["hata"] = f"Instagram anahtarı yok (IG_{kod.upper()}_ID/TOKEN ya da IG_TOKEN + META_{kod.upper()}_IG_ID)"
            kayit["durum"] = "hata"
            log(kayit["hata"])
        else:
            _SUREN[kod]["yayin_basladi"] = True
            try:
                b = ig.reels(sonuc["reel"], sonuc["aciklama"])
                kayit.update(durum="yayinlandi", medya_id=b["id"], link=b.get("permalink"), yayin_zamani=simdi().isoformat())
            except InstagramHatasi as e:  # yayından önce kesin hata (kapsayıcı/yükleme/işleme): yayımlanmadı
                kayit.update(durum="hata", hata=str(e)[:300])
                log(f"Reels paylaşılamadı: {e}")
            except Exception as e:  # BelirsizYayin ya da beklenmeyen hata: gönderi gitmiş olabilir
                kayit.update(durum="belirsiz", hata=f"{type(e).__name__}: {str(e)[:280]}",
                             not_="Reels gönderildi ama sonucu alınamadı; elle kontrol, otomatik yeniden paylaşılmaz")
                log(f"Reels BELİRSİZ ({type(e).__name__}): {e} — hikâye ve diğer platformlar bu çalıştırmada atlandı")
            if kayit["durum"] in ("yayinlandi", "belirsiz"):
                gecmis_guncelle(kod, kayit)  # sonraki adımlar çökse/iş kesilse de kimlik ve durum kalsın
            if kayit["durum"] == "yayinlandi" and kod in ROBOT_HIKAYE:
                kayit["hikaye_robot"] = True
            elif kayit["durum"] == "yayinlandi":
                try:
                    h = ig.hikaye(sonuc["hikaye"])
                    kayit["hikaye_id"] = h["id"]
                except Exception as e:  # ağ hatası dahil: hikâye düşerse Reels kaydı bozulmaz
                    kayit["hikaye_hata"] = f"{'BELIRSIZ: ' if isinstance(e, BelirsizYayin) else ''}{str(e)[:280]}"
                    log(f"hikâye paylaşılamadı: {e}")
        if kayit["durum"] == "belirsiz":
            kayit["platformlar"] = {"instagram": f"BELIRSIZ: {kayit.get('hata', '')[:200]}"}
            gecmis_guncelle(kod, kayit)
            _SUREN.pop(kod, None)
            log(f"{kod}: belirsiz — {kayit['format']} — {kayit['baslik']}")
            return kayit
        # Diğer platformlar (Facebook, YouTube Shorts, TikTok) Instagram'dan bağımsız denenir
        etiketler = re.findall(r"#\w+", sonuc["aciklama"])
        kayit["platformlar"] = dagitim.dagit(kod, sonuc["reel"], sonuc["aciklama"], etiketler)
        kayit["platformlar"]["instagram"] = kayit.get("link") or (
            f"http-ig-medya:{kayit['medya_id']}" if kayit.get("medya_id") else
            (f"HATA: {kayit['hata']}" if kayit.get("hata") else "atlandı: anahtar yok"))
        kayit["platformlar"]["instagram_hikaye"] = "robot: Hikâye Robotu paylaşır" if kayit.get("hikaye_robot") else ("http-ig-hikaye:" + kayit["hikaye_id"]) if kayit.get("hikaye_id") else (
            f"HATA: {kayit['hikaye_hata']}" if kayit.get("hikaye_hata") else "atlandı")
        degerler = [str(v) for v in kayit["platformlar"].values()]
        if any(v.startswith(("http", "tiktok-taslak")) for v in degerler):
            kayit["durum"] = "yayinlandi"
        elif all(v.startswith("atlandı") for v in degerler if v) and not ig.hazir:
            # bu markanın hiçbir hesabı henüz bağlı değil: hata sayma, önizleme olarak kalsın
            kayit.update(durum="onizleme", hata=None, not_="hiçbir platform anahtarı yok")
    gecmis_guncelle(kod, kayit)
    _SUREN.pop(kod, None)
    log(f"{kod}: {kayit['durum']} — {kayit['format']} — {kayit['baslik']}")
    return kayit


def _ig_tamamla(kod: str, k: dict, pl: dict, video: Path, aciklama: str, ig_tekrar: bool, hikaye_tekrar: bool) -> int:
    """Instagram Reels'i (kesin hata almışsa) ve hikâyeyi tamamlar. Hikâyede Reels videosu kullanılır (≤60 sn).
    Her denemeden önce sayaç kaydedilir; yanıt alınamazsa BELIRSIZ yazılır ve bir daha denenmez."""
    ig, tamam = Instagram(kod), 0
    if not ig.hazir:
        return 0
    if ig_tekrar:
        k["ig_tekrar"] = k.get("ig_tekrar", 0) + 1
        gecmis_guncelle(kod, k)
        log(f"{kod}: Instagram Reels yeniden deneniyor ({k['ig_tekrar']}. tekrar)")
        try:
            b = ig.reels(video, aciklama)
            k.update(medya_id=b["id"], link=b.get("permalink"), yayin_zamani=simdi().isoformat(), hata=None)
            pl["instagram"] = b.get("permalink") or f"http-ig-medya:{b['id']}"
            tamam += 1
        except InstagramHatasi as e:
            pl["instagram"] = f"HATA: {str(e)[:290]}"
        except Exception as e:
            pl["instagram"] = f"BELIRSIZ: {type(e).__name__}: {str(e)[:250]}"
            k["not_"] = "Reels yeniden gönderildi ama sonucu alınamadı; elle kontrol, otomatik yeniden paylaşılmaz"
        k["platformlar"] = pl
        gecmis_guncelle(kod, k)
    if hikaye_tekrar and str(pl.get("instagram", "")).startswith("http"):
        k["hikaye_tekrar"] = k.get("hikaye_tekrar", 0) + 1
        gecmis_guncelle(kod, k)
        try:
            h = ig.hikaye(video)
            k["hikaye_id"], k["hikaye_hata"] = h["id"], None
            pl["instagram_hikaye"] = "http-ig-hikaye:" + h["id"]
            tamam += 1
        except Exception as e:
            k["hikaye_hata"] = f"{'BELIRSIZ: ' if isinstance(e, BelirsizYayin) else ''}{str(e)[:280]}"
            pl["instagram_hikaye"] = f"HATA: {k['hikaye_hata']}"
            log(f"{kod}: hikâye yine paylaşılamadı: {e}")
        k["platformlar"] = pl
        gecmis_guncelle(kod, k)
    return tamam


def eksik(kodlar: list[str] | None = None, elle: bool = False) -> int:
    """Bugün yayınlanmış ama bir platforma (Facebook vb.) gidememiş içeriği yalnız o platforma gönderir.
    Instagram'a yalnız kesin hata (medya kimliği yok) almışsa en çok 3 kez yeniden gönderir; hikâyesi eksikse tamamlar.
    Video: sürüm yedeği, yoksa Instagram'daki yayından.
    elle=True (panel "Düzelt"): otomatik deneme sayısı (3) dolmuş olsa da bir kez daha dener; BELIRSIZ yine ASLA yeniden gönderilmez."""
    sinir = 99 if elle else 3
    import requests
    from . import plan
    tarih, tamam = bugun(), 0
    for kod in kodlar or marka_kodlari():
        k = next((x for x in gecmis(kod) if x.get("tarih") == tarih and x.get("tur") == "reels"), None)
        pl = (k or {}).get("platformlar") or {}
        hatali = [p for p, v in pl.items() if str(v).startswith("HATA") and p not in ("instagram", "instagram_hikaye")]  # BELIRSIZ değil
        hatali += [p for p in dagitim.PLATFORMLAR if pl and p not in pl]  # sonradan eklenen platform (ör. Facebook hikâye)
        # anahtarı sonradan eklenen platform (ör. YouTube): bugünkü içerik de oraya gitsin
        hatali += [p for p, (hazir, _) in dagitim.PLATFORMLAR.items()
                   if str(pl.get(p, "")).startswith("atlandı: anahtar") and hazir(kod) and p not in hatali]
        # Instagram yalnız KESİN hata ise (yayından önce düştü, medya kimliği yok) yeniden denenir; BELIRSIZ asla
        ig_tekrar = bool(k) and str(pl.get("instagram", "")).startswith("HATA") and not k.get("medya_id") \
            and k.get("ig_tekrar", 0) < sinir
        hk = str(pl.get("instagram_hikaye", "atlandı"))
        hikaye_tekrar = bool(k) and kod not in ROBOT_HIKAYE and "BELIRSIZ" not in hk and hk.startswith(("HATA", "atlandı")) \
            and not hk.startswith("atlandı: anahtar") and k.get("hikaye_tekrar", 0) < sinir \
            and (ig_tekrar or str(pl.get("instagram", "")).startswith("http"))
        if not k or k.get("durum") != "yayinlandi" or not (hatali or ig_tekrar or hikaye_tekrar):
            continue
        klasor = CIKTI / "eksik" / kod
        klasor.mkdir(parents=True, exist_ok=True)
        video = plan.indir(k["video_yedek"], klasor) if k.get("video_yedek") else None
        aciklama = k.get("aciklama") or ""
        try:
            if (not video or not aciklama) and k.get("medya_id"):
                md = Instagram(kod)._istek("GET", k["medya_id"], fields="media_url,caption")
                aciklama = aciklama or md.get("caption", "")
                if not video and md.get("media_url"):
                    video = klasor / "reel.mp4"
                    r = requests.get(md["media_url"], timeout=300)
                    r.raise_for_status()
                    video.write_bytes(r.content)
        except Exception as e:
            log(f"{kod}: eksik platform için video alınamadı: {gizle(str(e))[:160]}")
            continue
        if not video or not aciklama:
            log(f"{kod}: eksik platform için video/açıklama yok")
            continue
        if ig_tekrar or hikaye_tekrar:
            tamam += _ig_tamamla(kod, k, pl, video, aciklama, ig_tekrar, hikaye_tekrar)
        if hatali:
            log(f"{kod}: eksik platformlar tamamlanıyor: {', '.join(hatali)}")
            k["platformlar"] = dagitim.dagit(kod, video, aciklama, re.findall(r"#\w+", aciklama), onceki=pl)
            gecmis_guncelle(kod, k)
            tamam += sum(1 for p in hatali if str(k["platformlar"].get(p, "")).startswith("http"))
    log(f"eksik: {tamam} platform tamamlandı")
    return 0


# ---------------- ölçüm ve öğrenme ----------------

def olc(kod: str, ig: Instagram | None = None) -> None:
    ig = ig or Instagram(kod)
    if not ig.hazir:
        return
    ks = gecmis(kod)
    sinir_eski = (simdi() - dt.timedelta(days=21)).isoformat()
    sinir_yeni = (simdi() - dt.timedelta(hours=24)).isoformat()
    for k in ks:
        if k.get("medya_id") and sinir_eski <= k.get("yayin_zamani", "") <= sinir_yeni:
            try:
                k["olcum"] = ig.olcumler(k["medya_id"])
                k["olcum_zamani"] = simdi().isoformat()
            except InstagramHatasi as e:
                log(f"ölçüm alınamadı {k['medya_id']}: {e}")
    olculen = [k for k in ks if k.get("olcum")]
    if olculen:
        erisim = [max(1, k["olcum"].get("reach") or 0) for k in olculen]
        oran = [((k["olcum"].get("likes") or 0) + 2 * (k["olcum"].get("comments") or 0) + 3 * (k["olcum"].get("saved") or 0)
                 + 4 * (k["olcum"].get("shares") or 0)) / max(1, k["olcum"].get("reach") or 0) for k in olculen]
        me, mo = statistics.median(erisim) or 1, statistics.median(oran) or 1e-6
        for k, e, o in zip(olculen, erisim, oran):
            k["skor"] = round(0.5 * e / me + 0.5 * o / mo, 3)
    gecmis_yaz(kod, ks)


# ---------------- rapor ve anahtar yenileme ----------------

def rapor(tarih: str | None = None) -> str:
    """Bugünün içerikleri için Markdown özet (önizleme e-postası / hata bildirimi)."""
    tarih = tarih or bugun()
    satir = [f"## {tarih} içerikleri", ""]
    for kod in marka_kodlari():
        k = next((x for x in gecmis(kod) if x.get("tarih") == tarih and x.get("tur") == "reels"), None)
        if not k:
            continue
        m = marka(kod)
        satir.append(f"### {m['ad']} — {k.get('durum')}")
        satir.append(f"- Format: `{k.get('format')}` · Konu: {k.get('konu', '')} · Metin: {k.get('metin_kaynagi', '-')}")
        if k.get("link"):
            satir.append(f"- Instagram: {k['link']}")
        if k.get("hata"):
            satir.append(f"- **Hata:** {k['hata']}")
        if k.get("hikaye_hata"):
            satir.append(f"- **Hikâye hatası:** {k['hikaye_hata']}")
        if k.get("not_"):
            satir.append(f"- Not: {k['not_']}")
        yol = CIKTI.parent / k.get("klasor", "") / "aciklama.txt"
        if k.get("klasor") and yol.exists():
            satir += ["", "<details><summary>Açıklama metni</summary>", "", "```", yol.read_text(encoding="utf-8"), "```", "</details>"]
        satir.append("")
    return "\n".join(satir)


def sayfa_sitesi(sayfa: str, t: str, m: dict) -> str:
    """Facebook sayfasının 'web sitesi' alanı markanın sitesini göstermiyorsa yazar (sayfa ↔ site kimlik bağı, SEO)."""
    import requests
    from .dagitim import GRAPH
    site = m.get("site", "")
    try:
        w = requests.get(f"{GRAPH}/{sayfa}", params={"fields": "website", "access_token": t}, timeout=30).json().get("website", "") or ""
        if m.get("site_kisa", "~") in w:
            return "site ✓"
        r = requests.post(f"{GRAPH}/{sayfa}", data={"website": site, "access_token": t}, timeout=30)
        return "site yazıldı ✓" if r.ok else f"site yazılamadı ({r.status_code}: {r.text[:120]})"
    except Exception as e:
        return f"site ? {type(e).__name__}"


def kontrol() -> int:
    """Bağlantı denemesi: her markanın Instagram hesabını ve Facebook sayfa erişimini okur (paylaşım yapmaz, anahtar yazdırmaz)."""
    import requests
    from .dagitim import GRAPH, _sayfa_anahtari
    hata = 0
    if os.environ.get("IG_TOKEN"):  # anahtarın izinleri (anahtarın kendisi yazılmaz): hangi izin hangi hesaplar için verilmiş
        try:
            j = requests.get(f"{GRAPH}/debug_token", params={"input_token": os.environ["IG_TOKEN"], "access_token": os.environ["IG_TOKEN"]},
                             timeout=30).json()
            if "error" in j:
                log(f"anahtar izinleri: {j['error'].get('message', '')[:200]}")
            d = j.get("data", {})
            pr = requests.get(f"{GRAPH}/me/permissions", params={"access_token": os.environ["IG_TOKEN"]}, timeout=30).json()
            if "data" in pr:  # depo herkese açık: izin adları/hedef kimlikleri loga yazılmaz, yalnız sayılar
                durumlar = [x.get("status") for x in pr["data"]]
                log(f"  verilen izinler: {durumlar.count('granted')} verildi, {len(durumlar) - durumlar.count('granted')} verilmedi")
            else:
                log(f"  izin listesi okunamadı: {pr.get('error', {}).get('message', '')[:160]}")
            if d.get("scopes"):
                log(f"  izin sayısı: {len(d['scopes'])}")
            log(f"anahtar geçerli={d.get('is_valid')} bitiş={d.get('expires_at')}")
            for g in d.get("granular_scopes", []):
                hedef = g.get("target_ids")
                log(f"  ayrıntılı izin: {f'{len(hedef)} hedef' if hedef else 'tümü'}")
        except Exception as e:
            log(f"anahtar izinleri okunamadı: {type(e).__name__}")
    for kod in marka_kodlari():
        ig = Instagram(kod)
        satir = [f"{kod:12}"]
        if ig.hazir:
            try:
                h = ig.hesap()
                satir.append(f"IG ✓ @{h.get('username')} ({h.get('followers_count')} takipçi) kimlik={ig.kimlik}")
            except InstagramHatasi as e:
                hata = 1
                satir.append(f"IG ✗ {str(e)[:120]}")
        else:
            satir.append("IG – anahtar/kimlik yok")
        if os.environ.get(f"META_{kod.upper()}_PAGE_ID"):
            try:
                sayfa, t = _sayfa_anahtari(kod)
                g = requests.get(f"{GRAPH}/me/accounts", params={"fields": "id,tasks", "limit": 50, "access_token": os.environ["IG_TOKEN"]}, timeout=30)
                gorev = next((a.get("tasks") for a in (g.json() or {}).get("data", []) if a.get("id") == sayfa), "sayfa listede yok") if g.ok else None
                b = requests.get(f"{GRAPH}/{sayfa}", params={"fields": "instagram_business_account,connected_instagram_account", "access_token": t}, timeout=30).json()
                bagli = (b.get("instagram_business_account") or b.get("connected_instagram_account") or {}).get("id")
                ib = (b.get("instagram_business_account") or {}).get("id")
                cb = (b.get("connected_instagram_account") or {}).get("id")
                kim = getattr(ig, "kimlik", None)
                satir.append(f"IG↔sayfa işletme={'✓' if ib == kim else ('başka' if ib else 'yok')} bağlı={'✓' if cb == kim else ('başka' if cb else 'yok')}")
                satir.append(f"FB sayfa ✓ {sayfa} görevler={gorev}" if g.ok else f"FB sayfa ? ({g.status_code}: {g.text[:160]})")
                satir.append(sayfa_sitesi(sayfa, t, marka(kod)))
            except Exception as e:
                hata = 1
                satir.append(f"FB sayfa ✗ {str(e)[:120]}")
        else:
            satir.append("FB sayfa – kimlik yok")
        print(gizle("  ".join(satir)), flush=True)
    return hata


def anahtar_yenile() -> None:
    """Instagram ile Giriş anahtarlarını uzatır ve GitHub sırrına yazar (GH_PAT gerekir). Anahtar yazdırılmaz."""
    pat, depo = os.environ.get("GH_PAT"), os.environ.get("GITHUB_REPOSITORY")
    for kod in marka_kodlari():
        ig = Instagram(kod)
        if not ig.hazir:
            continue
        yeni = ig.anahtar_yenile()
        if not yeni:
            continue
        if not (pat and depo):
            log(f"{kod}: anahtar yenilendi ama GH_PAT yok, sırra yazılamadı")
            continue
        r = subprocess.run(["gh", "secret", "set", f"IG_{kod.upper()}_TOKEN", "-R", depo], input=yeni, text=True,
                           env={**os.environ, "GH_TOKEN": pat}, capture_output=True)
        log(f"{kod}: anahtar {'güncellendi' if r.returncode == 0 else 'GÜNCELLENEMEDİ: ' + r.stderr[:200]}")


def plan_komutu() -> int:
    """Gün içinde birkaç kez: panel isteklerini işler, 7 günlük planı tamamlar, takipçi sayılarını kaydeder, panele bildirir."""
    from . import panel, plan
    for kod in marka_kodlari():
        ig = Instagram(kod)
        if ig.hazir:
            try:
                plan.hesap_kaydet(kod, ig.hesap())
            except Exception as e:
                log(f"{kod} hesap bilgisi alınamadı: {e}")
    from . import strateji
    for kod in marka_kodlari():  # haftalık araştırma (tutan içerikler, rakipler, sorular, mevsim); eskiyse yenilenir
        strateji.arastir(kod, beyin.guncel_marka(kod))
    yanit = panel.gonder(donus=True) or {}
    with sync_playwright() as p:
        tarayici = p.chromium.launch(args=["--disable-gpu", "--font-render-hinting=none"])
        try:
            sonuc = plan.panel_isle(yanit, tarayici)
            yeni = plan.hafta_plani(tarayici)
        finally:
            tarayici.close()
    try:
        sesli = plan.ses_hazirla()
        log(f"ses hazırlama: {sesli} plan gününe denetlenmiş ses eklendi")
    except Exception as e:
        log(f"ses hazırlama çalışmadı: {type(e).__name__}: {str(e)[:160]}")
    panel.onay(sonuc)
    panel.gonder()
    tut = set()
    for kod in marka_kodlari():
        tut |= {f"{g}-{kod}{u}" for g in plan.oku(kod) for u in (".jpg", ".zip", "-ses.npz")}
        tut |= {f"{k['tarih']}-{kod}.jpg" for k in gecmis(kod) if k.get("tarih", "") >= (simdi().date() - dt.timedelta(days=15)).isoformat()}
        tut |= {k["video_yedek"] for k in gecmis(kod) if k.get("video_yedek") and k.get("tarih", "") >= (simdi().date() - dt.timedelta(days=3)).isoformat()}
    plan.temizle(tut)
    log(f"plan: {yeni} yeni gün, panel: {len(sonuc['uygulanan'])} uygulandı, {len(sonuc['reddedilen'])} reddedildi, {len(sonuc['tanitim'])} tanıtım")
    return 0


def nabiz_tarihi() -> str:
    """Varsayılan denetim günü: TR saati 12:00'den önceyse dün, değilse bugün.
    GitHub zamanlayıcısı 22:00 nabzını ertesi sabaha (ör. 07:09) kaydırabiliyor; günün ilk Reels'i 12:30'da
    olduğundan öğleden önce 'bugün' denetlenirse her marka yanlışlıkla 'hiç üretim yapılmadı' görünür."""
    s = simdi()
    return (s.date() - dt.timedelta(days=1)).isoformat() if s.hour < 12 else s.date().isoformat()


def nabiz(tarih: str | None = None) -> int:
    """Gün sonu (22:00) denetimi: o gün Instagram'a paylaşılamayan marka varsa listeler ve 1 döner (akış e-posta bildirimi açar)."""
    tarih = tarih or nabiz_tarihi()
    sorun = []
    for kod in marka_kodlari():
        k = next((x for x in gecmis(kod) if x.get("tarih") == tarih and x.get("tur") == "reels"), None)
        if not k:
            sorun.append(f"- **{marka(kod)['ad']}**: {tarih} günü hiç üretim yapılmadı")
        elif k.get("durum") != "yayinlandi":
            sorun.append(f"- **{marka(kod)['ad']}**: {k.get('durum')} — {str(k.get('hata') or k.get('not_') or '')[:300]}")
    if sorun:
        print(f"{tarih} günü paylaşılamayan markalar (yarın sistem kendisi yeniden dener; 'belirsiz' olanlar elle kontrol edilmeli):\n")
        print(gizle("\n".join(sorun)))
        return 1
    print(f"{tarih}: dört markanın paylaşımı da tamam.")
    return 0


# ---------------- zamanlama ----------------

def zamani_gelenler() -> list[str]:
    s = simdi()
    sonuc = []
    for kod in marka_kodlari():
        saat = marka(kod)["saat"]["reels"]
        hh, mm = map(int, saat.split(":"))
        if s.hour * 60 + s.minute >= hh * 60 + mm - 30:  # GitHub zamanlayıcısı gecikebilir
            sonuc.append(kod)
    return sonuc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("komut", choices=["otomatik", "uret", "olc", "rapor", "yenile", "kontrol", "nabiz", "plan", "etkilesim", "eksik"])
    ap.add_argument("--marka", action="append")
    ap.add_argument("--zorla", action="store_true")
    ap.add_argument("--format", help="deneme için formatı zorla")
    ap.add_argument("--tarih", help="nabiz: denetlenecek gün (YYYY-AA-GG); boşsa 12:00'den önce dün, sonra bugün")
    a = ap.parse_args(argv)
    if a.format:
        os.environ["OTOPILOT_FORMAT"] = a.format
    if a.komut == "rapor":
        print(rapor())
        return 0
    if a.komut == "yenile":
        anahtar_yenile()
        return 0
    if a.komut == "kontrol":
        return kontrol()
    if a.komut == "nabiz":
        return nabiz(a.tarih)
    if a.komut == "plan":
        return plan_komutu()
    if a.komut == "etkilesim":
        from . import etkilesim
        return etkilesim.calistir()
    if a.komut == "eksik":
        return eksik(a.marka)
    kodlar = a.marka or (zamani_gelenler() if a.komut == "otomatik" else marka_kodlari())
    hata = 0
    for kod in kodlar:
        try:
            if a.komut == "olc":
                olc(kod)
            else:
                k = gunluk(kod, zorla=a.zorla)
                if k.get("durum") in ("hata", "belirsiz") and not k.get("atlandi"):
                    hata = 1
        except Exception as e:
            hata = 1
            log(f"{kod} HATA: {e}")
            log(traceback.format_exc())
            gecmis_guncelle(kod, hata_kaydi(kod, e))
    return hata


def hata_kaydi(kod: str, e: Exception) -> dict:
    """Beklenmeyen hatada yazılacak kayıt. Reels yayımlandıysa kayıt (medya_id ile) korunur; yayın denemesi başlamış ama
    sonucu bilinmiyorsa 'belirsiz' (yeniden paylaşılmaz); hiç başlamadıysa 'hata' (sonraki çalıştırma yeniden dener)."""
    suren = _SUREN.pop(kod, None)
    if suren and suren["kayit"].get("medya_id"):
        return {**suren["kayit"], "durum": "yayinlandi", "not_": f"Reels yayında; sonraki adımda hata: {str(e)[:250]}"}
    if suren and (suren["yayin_basladi"] or suren["kayit"].get("durum") == "belirsiz"):
        return {**suren["kayit"], "durum": "belirsiz", "hata": str(e)[:300],
                "not_": "yayın denemesi sırasında beklenmeyen hata; elle kontrol, otomatik yeniden paylaşılmaz"}
    return {"tarih": bugun(), "tur": "reels", "durum": "hata", "hata": str(e)[:300], "format": "?", "anahtar": ""}


if __name__ == "__main__":
    sys.exit(main())
