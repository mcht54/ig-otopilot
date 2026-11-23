"""İleri tarihli plan (önümüzdeki 7 gün) ve panel istekleri.

- Her marka için yarından itibaren 7 günün içeriği önceden kurulur: format, konu, ekran metinleri, açıklama, anlatım ve
  kapak önizlemesi. Panelde (İçerik takvimi → marka sekmesi) görünür; ekran başlığı ve anlatım satırları düzenlenebilir.
- Panelden "Konuyu değiştir" (o günün içeriği) ve "Ne paylaşılsın?" (serbest metin) gelir: yapay zekâ isteği yorumlar,
  markanın kitlesine göre açı/kanca seçer ve yalnız doğrulanabilir bilgiyle içeriği kurar; uygun değilse nedenini yazar.
- Ağır iş (tarayıcı, görsel) GitHub Actions'ta yapılır; panel yalnız küçük JSON tutar, görseller GitHub sürüm
  dosyasından (release "plan") gösterilir. Sunucuya yük binmez.
- Plan varlıkları (ekran görüntüleri, önizleme HTML'i) zip olarak aynı sürüme yüklenir; üretim günü indirilir.
  İndirilemezse o günün içeriği baştan kurulur — paylaşım durmaz.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

from . import beyin, llm, ses
from .kaynak import ekran_goruntusu, getir, temiz
from .ortak import CIKTI, DURUM, json_kaydet, log, marka, marka_kodlari, simdi

PLAN_GUN = 7
EN_COK_YENI = 8  # çalıştırma başına kurulan en çok yeni gün (çalıştırma kısa kalsın; günde 5 çalıştırmada hafta dolar)
SURUM = "plan"
YER = "{{KLASOR}}"


# ---------------- depolama ----------------

def _yol(kod: str) -> Path:
    return DURUM / kod / "plan.json"


def oku(kod: str) -> dict[str, dict]:
    p = _yol(kod)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def yaz(kod: str, plan: dict[str, dict]) -> None:
    json_kaydet(_yol(kod), dict(sorted(plan.items())))


def _yer_tut(veri, klasor: Path):
    m = json.dumps(veri, ensure_ascii=False)
    return json.loads(m.replace(klasor.as_uri(), "file://" + YER).replace(str(klasor), YER))


def _yer_ac(veri, klasor: Path):
    m = json.dumps(veri, ensure_ascii=False)
    return json.loads(m.replace("file://" + YER, klasor.as_uri()).replace(YER, str(klasor)))


# ---------------- GitHub sürüm dosyaları (varlıklar + önizleme) ----------------

def _depo() -> str | None:
    return os.environ.get("GITHUB_REPOSITORY")


def _gh(*a: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *a, "-R", _depo()], capture_output=True, text=True, check=check, timeout=300)


def _surum_hazir() -> bool:
    if not _depo():
        return False
    if _gh("release", "view", SURUM, check=False).returncode:
        _gh("release", "create", SURUM, "--prerelease", "--title", "Plan varlıkları (otomatik)",
            "--notes", "İleri tarihli plan kapak önizlemeleri ve varlık paketleri. Otomasyon yönetir; elle değiştirmeyin.", check=False)
    return True


def gorsel_url(ad: str, surum: str = "") -> str | None:
    return f"https://github.com/{_depo()}/releases/download/{SURUM}/{ad}" + (f"?v={surum}" if surum else "") if _depo() else None


def yukle(*dosyalar: Path) -> bool:
    if not _surum_hazir():
        return False
    r = _gh("release", "upload", SURUM, *map(str, dosyalar), "--clobber", check=False)
    if r.returncode:
        log(f"plan varlığı yüklenemedi: {r.stderr[:200]}")
    return r.returncode == 0


def indir(ad: str, hedef: Path) -> Path | None:
    if not _depo():
        return None
    hedef.mkdir(parents=True, exist_ok=True)
    r = _gh("release", "download", SURUM, "-p", ad, "-D", str(hedef), "--clobber", check=False)
    return hedef / ad if r.returncode == 0 and (hedef / ad).exists() else None


def temizle(tut: set[str]) -> None:
    """Planda/son 14 günde olmayan eski sürüm dosyalarını siler (depo/sürüm şişmesin)."""
    if not _surum_hazir():
        return
    r = _gh("release", "view", SURUM, "--json", "assets", "-q", ".assets[].name", check=False)
    for ad in (r.stdout or "").split():
        if ad not in tut:
            _gh("release", "delete-asset", SURUM, ad, "-y", check=False)


# ---------------- önizleme ----------------

def kapak_onizleme(tarayici, senaryo: dict, m: dict, klasor: Path, cikti: Path) -> Path | None:
    """İlk sahnenin karesi (360 px genişlik, küçük jpg)."""
    from .film import kapak_kare, klip_uret
    try:
        ilk = dict(senaryo["sahneler"][0])
        if ilk.get("tur") == "kart":
            ilk["sure"] = 2.6
            klip = klip_uret(tarayici, ilk, m, klasor / "onizleme-ilk.mp4")
            ham = kapak_kare(klip, klasor / "onizleme-ham.jpg", 2.2)
            klip.unlink(missing_ok=True)
        else:
            ham = ekran_goruntusu(tarayici, ilk.get("url") or Path(ilk["html_yol"]).as_uri(), klasor / "onizleme-ham.png")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(ham), "-vf", "scale=360:-2", "-q:v", "5", str(cikti)], check=True)
        return cikti
    except Exception as e:
        log(f"önizleme üretilemedi: {e}")
        return None


def _paketle(klasor: Path, cikti: Path) -> Path:
    with zipfile.ZipFile(cikti, "w", zipfile.ZIP_DEFLATED) as z:
        for f in klasor.iterdir():
            if f.is_file() and f.suffix in (".png", ".jpg", ".jpeg", ".html", ".webp", ".svg"):
                z.write(f, f.name)
    return cikti


# ---------------- içerik kurma ----------------

def _kur_otomatik(kod: str, m: dict, tarayici, klasor: Path, gun: dt.date, ek: set[str], onceki: str | None) -> dict:
    atla: set[str] = set()
    for _ in range(len(m["formatlar"]) + 2):
        s = beyin.planla(kod, m, tarayici, klasor, atla=atla, gun=gun, ek_kullanilan=ek, onceki_format=onceki)
        s, aciklama, kaynak = beyin.parlat(s, m, kod, random.Random(s["tohum"]))
        hatalar = beyin.metin_denetle(s, aciklama, m)
        if hatalar:
            atla.add(s["format"])
            continue
        s["metin_kaynagi"] = kaynak
        return {"senaryo": s, "aciklama": aciklama, "kaynak": "otomatik",
                "neden": f"Otomatik plan: {s['format']} formatı (performansa göre ağırlıklı seçim)"}
    raise RuntimeError("plan kurulamadı")


def _site_olgulari(m: dict) -> list[str]:
    try:
        t = temiz(getir(m["site"]).text)
        return [t[i:i + 300] for i in range(0, min(len(t), 1800), 300)]
    except Exception:
        return []


def ozel_icerik(kod: str, m: dict, istek: str, tarayici, klasor: Path, gun: dt.date) -> dict:
    """Panelden gelen serbest istekten içerik: yapay zekâ isteği yorumlar, kitlenin derdine göre açı ve kanca seçer,
    yalnız istek metni + marka profili + sitedeki gerçek bilgiyle yazar. Uygun değilse ValueError(neden)."""
    olgular = [f"Panelden istek: {istek}", *m["deger_onerisi"], *_site_olgulari(m)]
    sistem = (f"Sen {m['ad']} markasının deneyimli sosyal medya yöneticisisin; insan gibi düşünürsün.\n"
              f"Hedef kitle: {m['hedef_kitle'].strip()}\nSes tonu: {m['ses_tonu'].strip()}\n"
              "Önce isteği yorumla: ne tanıtılmak isteniyor, kitlenin bu konudaki derdi/merakı ne, hangi açı ve kanca en çok "
              "durdurur ve kaydettirir. Sonra Instagram Reels ekran metinlerini yaz.\n"
              "KURALLAR: Yalnız OLGULAR'daki bilgiye dayan; olmayan rakam, fiyat, süre, kampanya, garanti UYDURMA. "
              f"Yasak ifadeler: {', '.join(m.get('yasak_ifadeler', []) + beyin.GENEL_YASAK)}. Ekran metinlerinde emoji yok. "
              "İstek markayla ilgisizse, yanıltıcıysa ya da yasal/etik sorun taşıyorsa uygun=false ve red_nedeni yaz.")
    istem = ("OLGULAR:\n- " + "\n- ".join(olgular) + "\n\nJSON döndür: {\"uygun\": true, \"red_nedeni\": \"\", "
             "\"anlasilan\": \"isteği bir cümleyle nasıl anladın\", \"neden\": \"seçtiğin açı ve kanca neden işe yarar (1-2 cümle)\", "
             "\"konu\": \"\", \"anahtar_kelime\": \"Instagram aramasında aranacak 2-4 kelime\", "
             "\"kapak\": {\"etiket\": \"≤26 karakter\", \"baslik\": \"≤62 karakter kanca\", \"alt\": \"≤84\"}, "
             "\"liste\": {\"etiket\": \"≤26\", \"baslik\": \"≤62\", \"maddeler\": [\"3 madde, her biri ≤54 karakter\"]}, "
             "\"cta\": {\"baslik\": \"≤62\", \"alt\": \"≤84\"}, \"hikaye\": {\"etiket\": \"≤26\", \"baslik\": \"≤62\", \"alt\": \"≤84\"}}")
    from . import strateji
    v = llm.json_sor(sistem + "\n" + strateji.baglam(kod, m), istem)
    if not v:
        raise RuntimeError("yapay zekâ şu an yanıt vermedi")
    if not v.get("uygun", True):
        raise ValueError(str(v.get("red_nedeni") or "İstek bu markanın içeriğine uygun bulunmadı.")[:300])
    k, li, c, h = (v.get(a) or {} for a in ("kapak", "liste", "cta", "hikaye"))
    arka = klasor / "ozel-arka.png"
    try:
        ekran_goruntusu(tarayici, m["site"], arka, once_tikla=["Kabul", "Tamam"])
        gorsel = arka.as_uri()
    except Exception:
        gorsel = None
    s = {
        "format": "ozel", "anahtar": f"ozel:{gun.isoformat()}:{hashlib.sha1(istek.encode()).hexdigest()[:8]}",
        "konu": str(v.get("konu") or istek)[:120], "anahtar_kelime": str(v.get("anahtar_kelime") or "")[:60], "olgular": olgular,
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 2.8, "gorsel": gorsel, "etiket": k.get("etiket"), "baslik": k.get("baslik") or istek[:60], "alt": k.get("alt")},
            {"tur": "sayfa", "url": m["site"], "sure": 5.5, "once_tikla": ["Kabul", "Tamam"], "kaydir": True, "kaydir_px": 1600,
             "ust_yazi": (li.get("baslik") or "")[:46] or None},
            {"tur": "kart", "tip": "liste", "sure": 5.0, "gorsel": gorsel, "etiket": li.get("etiket"), "baslik": li.get("baslik") or "",
             "maddeler": [str(x) for x in (li.get("maddeler") or [])][:3] or list(m["deger_onerisi"])[:3]},
            {"tur": "kart", "tip": "cta", "sure": 3.2, "baslik": c.get("baslik") or m["cta"], "alt": c.get("alt")},
        ],
        "hikaye": {"gorsel": gorsel, "etiket": h.get("etiket"), "baslik": h.get("baslik") or k.get("baslik"), "alt": h.get("alt")},
    }
    s = beyin.slot_yaz(s, {kk: beyin._kisalt(vv, beyin.slot_sinir(kk)) for kk, vv in beyin.slotlar(s).items()})
    s["tohum"] = f"{kod}:{gun.isoformat()}:ozel"
    aciklama = beyin.kural_aciklama(s, m, random.Random(s["tohum"]))
    hatalar = beyin.metin_denetle(s, aciklama, m)
    if hatalar:
        raise ValueError(f"Yazılan metin kalite denetiminden geçmedi ({'; '.join(map(str, hatalar))[:200]}); farklı ifadeyle tekrar deneyin.")
    s["metin_kaynagi"] = v.get("_saglayici", "llm")
    return {"senaryo": s, "aciklama": aciklama, "kaynak": "istek",
            "neden": f"{v.get('anlasilan', '')} {v.get('neden', '')}".strip()[:300] or "Panelden istendi"}


def _tamamla(kod: str, m: dict, oge: dict, gun: dt.date, tarayici, klasor: Path) -> dict:
    """Anlatım + önizleme + varlık paketi; plan öğesini kalıcı biçime getirir."""
    s = oge["senaryo"]
    anlatim, ak = ses.anlatim_yaz(s, m)
    ad = f"{gun.isoformat()}-{kod}"
    surum = hashlib.sha1(json.dumps([s["sahneler"], anlatim], ensure_ascii=False).encode()).hexdigest()[:8]
    on = kapak_onizleme(tarayici, s, m, klasor, klasor.parent / f"{ad}.jpg")
    paket = _paketle(klasor, klasor.parent / f"{ad}.zip")
    yuklendi = yukle(*(x for x in (on, paket) if x))
    return {"id": ad, "gun": gun.isoformat(), "kod": kod, "format": s["format"], "konu": s["konu"], "anahtar": s["anahtar"],
            "ek_anahtarlar": s.get("ek_anahtarlar", []), "senaryo": _yer_tut(s, klasor), "aciklama": oge["aciklama"],
            "anlatim": anlatim, "anlatim_kaynagi": ak, "kaynak": oge["kaynak"], "neden": oge.get("neden", ""),
            "tanitim_id": oge.get("tanitim_id"), "varlik": bool(yuklendi), "gorsel": gorsel_url(f"{ad}.jpg", surum) if on and yuklendi else None,
            "olusturma": simdi().isoformat(timespec="seconds")}


def _klasor(kod: str, gun: dt.date) -> Path:
    k = CIKTI / "plan" / f"{gun.isoformat()}-{kod}"
    shutil.rmtree(k, ignore_errors=True)
    k.mkdir(parents=True, exist_ok=True)
    return k


def hafta_plani(tarayici, kodlar: list[str] | None = None, en_cok: int | None = None) -> int:
    """Eksik günleri doldurur (var olanlara dokunmaz); geçmiş günleri plandan çıkarır. Önce en yakın gün: tüm markaların
    yarını, sonra öbür günü... Çalıştırma başına en çok EN_COK_YENI öğe (kalan uzak günler sonraki çalıştırmaya)."""
    bugun = simdi().date()
    kodlar = kodlar or marka_kodlari()
    sinir = EN_COK_YENI if en_cok is None else en_cok
    planlar = {kod: {g: x for g, x in oku(kod).items() if g >= bugun.isoformat()} for kod in kodlar}
    for kod in kodlar:
        yaz(kod, planlar[kod])  # geçmiş günler temizlenir
    markalar: dict[str, dict] = {}
    yeni = 0
    for i in range(1, PLAN_GUN + 1):
        gun = bugun + dt.timedelta(days=i)
        for kod in kodlar:
            p = planlar[kod]
            if gun.isoformat() in p:
                continue
            if yeni >= sinir:
                return yeni
            m = markalar.setdefault(kod, beyin.guncel_marka(kod))
            ek = {x["anahtar"] for x in p.values()} | {a for x in p.values() for a in x.get("ek_anahtarlar", [])}
            onceki = (p.get((gun - dt.timedelta(days=1)).isoformat()) or {}).get("format")
            try:
                k = _klasor(kod, gun)
                p[gun.isoformat()] = _tamamla(kod, m, _kur_otomatik(kod, m, tarayici, k, gun, ek, onceki), gun, tarayici, k)
                yeni += 1
                log(f"plan: {kod} {gun} → {p[gun.isoformat()]['format']}: {p[gun.isoformat()]['konu']}")
            except Exception as e:
                log(f"plan: {kod} {gun} kurulamadı: {e}")
            yaz(kod, p)
    return yeni


# ---------------- üretim günü ----------------

def bugunku(kod: str, klasor: Path) -> dict | None:
    """Bugünün plan öğesi (varlıkları indirilmiş, yolları bu klasöre açılmış). Yoksa/indirilemezse None."""
    oge = oku(kod).get(simdi().date().isoformat())
    if not oge:
        return None
    klasor.mkdir(parents=True, exist_ok=True)
    if oge.get("varlik"):
        z = indir(f"{oge['id']}.zip", klasor.parent / "_indir")
        if not z:
            log(f"{kod}: plan varlıkları indirilemedi; içerik baştan kurulacak")
            return None
        with zipfile.ZipFile(z) as f:
            f.extractall(klasor)
    elif "{{KLASOR}}" in json.dumps(oge["senaryo"]):
        return None
    s = _yer_ac(oge["senaryo"], klasor)
    s["tohum"] = s.get("tohum") or f"{kod}:{oge['gun']}"
    return {**oge, "senaryo": s}


# ---------------- panel istekleri ----------------

def _duzenleme_uygula(oge: dict, satirlar: dict[str, str]) -> None:
    s = oge["senaryo"]
    kapak = next((i for i, sh in enumerate(s["sahneler"]) if sh.get("tip") == "kapak"), 0)
    for k, v in satirlar.items():
        v = " ".join(str(v).split())
        if k in ("k.baslik", "k.alt"):
            s["sahneler"][kapak][k[2:]] = v[: beyin.SINIR[k[2:]]]
        elif re.fullmatch(r"a\d+", k) and int(k[1:]) < len(oge["anlatim"]):
            oge["anlatim"][int(k[1:])] = ses.konusma_metni(v, marka(oge["kod"]))


def panel_isle(yanit: dict, tarayici) -> dict:
    """Panelin döndürdüğü düzenleme/istek/tanıtımları uygular; onay yükünü döndürür."""
    uygulanan, reddedilen, tanitim = [], [], []
    bugun = simdi().date()
    for d in yanit.get("duzenlemeler", []):
        kod = d["bolum_id"].rsplit("-", 1)[-1] if "-" in d["bolum_id"] else ""
        p = oku(kod) if kod in marka_kodlari() else {}
        oge = next((x for x in p.values() if x["id"] == d["bolum_id"]), None)
        if not oge or oge["gun"] <= bugun.isoformat():
            reddedilen.append({"id": d["id"], "neden": "Bu içerik artık düzenlenemez (yayın günü geldi ya da plan değişti)."})
            continue
        _duzenleme_uygula(oge, d.get("satirlar", {}))
        if oge.get("varlik") and tarayici is not None:  # kapak başlığı değiştiyse önizlemeyi tazele
            k = _klasor(oge["kod"], dt.date.fromisoformat(oge["gun"]))
            z = indir(f"{oge['id']}.zip", k.parent / "_indir")
            if z:
                with zipfile.ZipFile(z) as f:
                    f.extractall(k)
                s = _yer_ac(oge["senaryo"], k)
                on = kapak_onizleme(tarayici, s, marka(oge["kod"]), k, k.parent / f"{oge['id']}.jpg")
                if on and yukle(on):
                    oge["gorsel"] = gorsel_url(on.name, hashlib.sha1(json.dumps(s["sahneler"][0], ensure_ascii=False).encode()).hexdigest()[:8])
        yaz(kod, p)
        uygulanan.append(d["id"])
    for d in yanit.get("istekler", []):
        kod, gun = d.get("urun"), d.get("gun", "")
        if kod not in marka_kodlari() or gun <= bugun.isoformat():
            reddedilen.append({"id": d["id"], "neden": "Gün ya da marka geçersiz."})
            continue
        try:
            g = dt.date.fromisoformat(gun)
            k = _klasor(kod, g)
            p = oku(kod)
            p[gun] = _tamamla(kod, marka(kod), ozel_icerik(kod, beyin.guncel_marka(kod), d["istek"], tarayici, k, g), g, tarayici, k)
            yaz(kod, p)
            uygulanan.append(d["id"])
        except ValueError as e:
            reddedilen.append({"id": d["id"], "neden": str(e)[:300]})
        except Exception as e:  # geçici (yapay zekâ/ağ): istek panelde bekler, sonraki çalışmada yeniden denenir
            log(f"istek {d['id']} ertelendi: {e}")
    for t in yanit.get("tanitimlar", []):
        kod = t.get("urun")
        if kod not in marka_kodlari():
            tanitim.append({"id": t["id"], "durum": "reddedildi", "neden": "Marka seçilmemiş."})
            continue
        p = oku(kod)
        bos = [bugun + dt.timedelta(days=i) for i in range(1, PLAN_GUN + 1)
               if (p.get((bugun + dt.timedelta(days=i)).isoformat()) or {}).get("kaynak", "otomatik") == "otomatik"]
        if not bos:
            continue  # 7 gün de panel istekleriyle dolu; bekler
        g = bos[0]
        try:
            k = _klasor(kod, g)
            oge = ozel_icerik(kod, beyin.guncel_marka(kod), t["metin"], tarayici, k, g)
            oge["kaynak"], oge["tanitim_id"] = "tanitim", t["id"]
            p[g.isoformat()] = _tamamla(kod, marka(kod), oge, g, tarayici, k)
            yaz(kod, p)
            tanitim.append({"id": t["id"], "durum": "planlandi", "gun": g.isoformat(), "aciklama": p[g.isoformat()]["neden"]})
        except ValueError as e:
            tanitim.append({"id": t["id"], "durum": "reddedildi", "neden": str(e)[:300]})
        except Exception as e:
            log(f"tanıtım {t['id']} ertelendi: {e}")
    return {"uygulanan": uygulanan, "reddedilen": reddedilen, "tanitim": tanitim}


# ---------------- büyüme ----------------

def hesap_kaydet(kod: str, bilgi: dict) -> None:
    yol = DURUM / kod / "hesap.json"
    seri = json.loads(yol.read_text(encoding="utf-8")) if yol.exists() else []
    gun = simdi().date().isoformat()
    seri = [x for x in seri if x["gun"] != gun] + [{"gun": gun, "takipci": bilgi.get("followers_count"), "gonderi": bilgi.get("media_count")}]
    json_kaydet(yol, sorted(seri, key=lambda x: x["gun"])[-400:])


def buyume(kod: str) -> dict:
    from .ortak import gecmis
    yol = DURUM / kod / "hesap.json"
    seri = [x for x in (json.loads(yol.read_text(encoding="utf-8")) if yol.exists() else []) if x.get("takipci") is not None]
    out: dict = {"seri": [{"gun": x["gun"], "takipci": x["takipci"]} for x in seri[-60:]]}
    if seri:
        son = seri[-1]["takipci"]
        out["takipci"] = son
        for gun_sayi, ad in ((7, "7g"), (30, "30g")):
            sinir = (simdi().date() - dt.timedelta(days=gun_sayi)).isoformat()
            eski = next((x["takipci"] for x in seri if x["gun"] >= sinir), None)
            if eski is not None:
                out[f"degisim_{ad}"] = son - eski
                out[f"yuzde_{ad}"] = round((son - eski) / eski * 100, 1) if eski else None
    sinir7 = (simdi().date() - dt.timedelta(days=7)).isoformat()
    son7 = [k for k in gecmis(kod) if k.get("tur") == "reels" and k.get("tarih", "") >= sinir7 and k.get("durum") == "yayinlandi"]
    out["gonderi_7g"] = len(son7)
    out["erisim_7g"] = sum(int((k.get("olcum") or {}).get("reach") or 0) for k in son7)
    out["etkilesim_7g"] = sum(int((k.get("olcum") or {}).get("total_interactions") or 0) for k in son7)
    puanlar: dict[str, list[float]] = {}
    for k in gecmis(kod):
        if k.get("skor") is not None:
            puanlar.setdefault(k["format"], []).append(k["skor"])
    if puanlar:
        out["en_iyi_format"] = max(puanlar, key=lambda f: sum(puanlar[f]) / len(puanlar[f]))
    return out
