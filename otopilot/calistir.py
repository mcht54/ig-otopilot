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
from .ortak import CIKTI, bugun, gizle, gecmis, gecmis_guncelle, gecmis_yaz, json_kaydet, log, marka, marka_kodlari, simdi


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


def _uret_bir(kod: str, m: dict, tarayici, klasor: Path, senaryo: dict, aciklama: str, kaynak: str, anlatim: list[str] | None = None) -> dict:
    from . import ses
    if anlatim and len(anlatim) == len(senaryo["sahneler"]):
        anlatim_kaynagi = senaryo.get("anlatim_kaynagi") or "plan"
    else:
        anlatim, anlatim_kaynagi = ses.anlatim_yaz(senaryo, m)
    reel, ses_kaynagi = film_yap(tarayici, senaryo["sahneler"], m, klasor, "reel", senaryo["tohum"], anlatim=anlatim)
    senaryo.update(anlatim=anlatim, anlatim_kaynagi=anlatim_kaynagi, ses_kaynagi=ses_kaynagi)
    log(f"anlatım ({anlatim_kaynagi}, ses: {ses_kaynagi}): {' / '.join(anlatim)}")
    vh = video_denetle(reel)
    if vh:
        raise RuntimeError(f"video kalite: {vh}")
    kapak = kapak_kare(reel, klasor / "kapak.jpg", 1.2)
    hikaye, _ = film_yap(tarayici, [hikaye_sahnesi(senaryo, kapak.as_uri())], m, klasor, "hikaye", senaryo["tohum"] + "h")
    hh = video_denetle(hikaye, en_az=3, en_cok=15)
    if hh:
        raise RuntimeError(f"hikâye kalite: {hh}")
    senaryo["metin_kaynagi"] = kaynak
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
            return _uret_bir(kod, m, tarayici, klasor, s, hazir["aciklama"], s.get("metin_kaynagi", "plan"), hazir.get("anlatim"))
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
        except Exception as e:
            son_hata = e
            log(f"{senaryo['format']} üretilemedi ({e}); başka format deneniyor")
            log(traceback.format_exc())
            atla.add(senaryo["format"])
            continue
    raise RuntimeError(f"hiçbir formatla içerik üretilemedi: {son_hata}")


def gunluk(kod: str, zorla: bool = False) -> dict:
    tarih = bugun()
    yayin_acik = os.environ.get("YAYIN") == "acik"
    onceki = next((k for k in gecmis(kod) if k.get("tarih") == tarih and k.get("tur") == "reels"), None)
    if onceki and onceki.get("durum") in ("yayinlandi", "onizleme") and not zorla:
        if not (yayin_acik and onceki["durum"] == "onizleme"):
            log(f"{kod}: bugün zaten yapıldı ({onceki['durum']})")
            return onceki
    from . import plan
    ig = Instagram(kod)
    if ig.hazir:
        try:
            olc(kod, ig)
            plan.hesap_kaydet(kod, ig.hesap())
        except Exception as e:
            log(f"{kod} ölçüm hatası: {e}")
    klasor = CIKTI / tarih / kod
    try:
        hazir = plan.bugunku(kod, klasor)
    except Exception as e:
        log(f"{kod}: plan okunamadı ({e})")
        hazir = None
    with sync_playwright() as p:
        tarayici = p.chromium.launch(args=["--disable-gpu", "--font-render-hinting=none"])
        try:
            sonuc = uret(kod, tarayici, klasor, hazir)
        finally:
            tarayici.close()
    s = sonuc["senaryo"]
    kayit = {
        "tarih": tarih, "tur": "reels", "format": s["format"], "anahtar": s["anahtar"], "ek_anahtarlar": s.get("ek_anahtarlar", []),
        "konu": s["konu"], "baslik": next((x.get("baslik") for x in s["sahneler"] if x.get("baslik")), s["konu"]),
        "metin_kaynagi": s["metin_kaynagi"], "durum": "onizleme", "klasor": str(klasor.relative_to(CIKTI.parent)),
        "anlatim": s.get("anlatim"), "ses_kaynagi": s.get("ses_kaynagi"),
    }
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
            try:
                b = ig.reels(sonuc["reel"], sonuc["aciklama"])
                kayit.update(durum="yayinlandi", medya_id=b["id"], link=b.get("permalink"), yayin_zamani=simdi().isoformat())
                try:
                    h = ig.hikaye(sonuc["hikaye"])
                    kayit["hikaye_id"] = h["id"]
                except InstagramHatasi as e:
                    kayit["hikaye_hata"] = str(e)[:300]
                    log(f"hikâye paylaşılamadı: {e}")
            except InstagramHatasi as e:
                kayit.update(durum="hata", hata=str(e)[:300])
                log(f"Reels paylaşılamadı: {e}")
        # Diğer platformlar (Facebook, YouTube Shorts, TikTok) Instagram'dan bağımsız denenir
        etiketler = re.findall(r"#\w+", sonuc["aciklama"])
        kayit["platformlar"] = dagitim.dagit(kod, sonuc["reel"], sonuc["aciklama"], etiketler)
        kayit["platformlar"]["instagram"] = kayit.get("link") or (f"HATA: {kayit['hata']}" if kayit.get("hata") else "atlandı: anahtar yok")
        kayit["platformlar"]["instagram_hikaye"] = ("http-ig-hikaye:" + kayit["hikaye_id"]) if kayit.get("hikaye_id") else (
            f"HATA: {kayit['hikaye_hata']}" if kayit.get("hikaye_hata") else "atlandı")
        degerler = [str(v) for v in kayit["platformlar"].values()]
        if any(v.startswith(("http", "tiktok-taslak")) for v in degerler):
            kayit["durum"] = "yayinlandi"
        elif all(v.startswith("atlandı") for v in degerler if v) and not ig.hazir:
            # bu markanın hiçbir hesabı henüz bağlı değil: hata sayma, önizleme olarak kalsın
            kayit.update(durum="onizleme", hata=None, not_="hiçbir platform anahtarı yok")
    gecmis_guncelle(kod, kayit)
    log(f"{kod}: {kayit['durum']} — {kayit['format']} — {kayit['baslik']}")
    return kayit


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
        yol = CIKTI.parent / k.get("klasor", "") / "aciklama.txt"
        if k.get("klasor") and yol.exists():
            satir += ["", "<details><summary>Açıklama metni</summary>", "", "```", yol.read_text(encoding="utf-8"), "```", "</details>"]
        satir.append("")
    return "\n".join(satir)


def kontrol() -> int:
    """Bağlantı denemesi: her markanın Instagram hesabını ve Facebook sayfa erişimini okur (paylaşım yapmaz, anahtar yazdırmaz)."""
    from .dagitim import _sayfa_anahtari
    hata = 0
    for kod in marka_kodlari():
        ig = Instagram(kod)
        satir = [f"{kod:12}"]
        if ig.hazir:
            try:
                h = ig.hesap()
                satir.append(f"IG ✓ @{h.get('username')} ({h.get('followers_count')} takipçi)")
            except InstagramHatasi as e:
                hata = 1
                satir.append(f"IG ✗ {str(e)[:120]}")
        else:
            satir.append("IG – anahtar/kimlik yok")
        if os.environ.get(f"META_{kod.upper()}_PAGE_ID"):
            try:
                _sayfa_anahtari(kod)
                satir.append("FB sayfa ✓")
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
    panel.onay(sonuc)
    panel.gonder()
    tut = set()
    for kod in marka_kodlari():
        tut |= {f"{g}-{kod}.{u}" for g in plan.oku(kod) for u in ("jpg", "zip")}
        tut |= {f"{k['tarih']}-{kod}.jpg" for k in gecmis(kod) if k.get("tarih", "") >= (simdi().date() - dt.timedelta(days=15)).isoformat()}
    plan.temizle(tut)
    log(f"plan: {yeni} yeni gün, panel: {len(sonuc['uygulanan'])} uygulandı, {len(sonuc['reddedilen'])} reddedildi, {len(sonuc['tanitim'])} tanıtım")
    return 0


def nabiz() -> int:
    """Gün sonu (22:00) denetimi: bugün Instagram'a paylaşılamayan marka varsa listeler ve 1 döner (akış e-posta bildirimi açar)."""
    sorun = []
    for kod in marka_kodlari():
        k = next((x for x in gecmis(kod) if x.get("tarih") == bugun() and x.get("tur") == "reels"), None)
        if not k:
            sorun.append(f"- **{marka(kod)['ad']}**: bugün hiç üretim yapılmadı")
        elif k.get("durum") != "yayinlandi":
            sorun.append(f"- **{marka(kod)['ad']}**: {k.get('durum')} — {str(k.get('hata', ''))[:300]}")
    if sorun:
        print("Bugün paylaşılamayan markalar (yarın sistem kendisi yeniden dener):\n")
        print(gizle("\n".join(sorun)))
        return 1
    print("Bugün dört markanın paylaşımı da tamam.")
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
    ap.add_argument("komut", choices=["otomatik", "uret", "olc", "rapor", "yenile", "kontrol", "nabiz", "plan", "etkilesim"])
    ap.add_argument("--marka", action="append")
    ap.add_argument("--zorla", action="store_true")
    ap.add_argument("--format", help="deneme için formatı zorla")
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
        return nabiz()
    if a.komut == "plan":
        return plan_komutu()
    if a.komut == "etkilesim":
        from . import etkilesim
        return etkilesim.calistir()
    kodlar = a.marka or (zamani_gelenler() if a.komut == "otomatik" else marka_kodlari())
    hata = 0
    for kod in kodlar:
        try:
            if a.komut == "olc":
                olc(kod)
            else:
                k = gunluk(kod, zorla=a.zorla)
                if k.get("durum") == "hata":
                    hata = 1
        except Exception as e:
            hata = 1
            log(f"{kod} HATA: {e}")
            log(traceback.format_exc())
            gecmis_guncelle(kod, {"tarih": bugun(), "tur": "reels", "durum": "hata", "hata": str(e)[:300], "format": "?", "anahtar": ""})
    return hata


if __name__ == "__main__":
    sys.exit(main())
