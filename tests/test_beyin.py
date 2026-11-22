import json
import random

import pytest

from otopilot import beyin, calistir, ortak
from otopilot.kaynak.davetiyeler import kisa_ad


@pytest.fixture
def gecici_durum(tmp_path, monkeypatch):
    monkeypatch.setattr(ortak, "DURUM", tmp_path)
    return tmp_path


def ornek_senaryo():
    return {
        "format": "rehber", "konu": "Kapora dolandırıcılığı", "anahtar": "rehber:x", "anahtar_kelime": "sapanca bungalov",
        "olgular": ["Sapanca'da 374 belgeli tesis var."],
        "sahneler": [
            {"tur": "kart", "tip": "kapak", "sure": 3, "etiket": "Güvenli tatil", "baslik": "Kapora göndermeden 3 kontrol", "alt": "Kaydedin"},
            {"tur": "kart", "tip": "liste", "sure": 5, "baslik": "Bilmeniz gerekenler", "maddeler": ["Belgeyi sorun", "IBAN adını kontrol edin"]},
            {"tur": "sayfa", "url": "https://x", "sure": 5, "eylemler": [{"t": 1, "ust_yazi": "Rehber sitede"}]},
        ],
        "hikaye": {"etiket": "İpucu", "baslik": "Belgeyi sorun", "alt": "Profilde"},
    }


def test_slot_gidis_donus():
    s = ornek_senaryo()
    d = beyin.slotlar(s)
    assert d["s1.madde1"] == "IBAN adını kontrol edin" and d["s2.eylem0"] == "Rehber sitede" and d["h.baslik"] == "Belgeyi sorun"
    assert beyin.slot_yaz(s, d) == s
    yeni = beyin.slot_yaz(s, {"s1.madde0": "Yeni madde", "s2.eylem0": "Yeni yazı"})
    assert yeni["sahneler"][1]["maddeler"][0] == "Yeni madde" and yeni["sahneler"][2]["eylemler"][0]["ust_yazi"] == "Yeni yazı"
    assert s["sahneler"][1]["maddeler"][0] == "Belgeyi sorun"  # orijinal bozulmaz


def test_denetim_uydurma_rakam_ve_yasak_ifade():
    m = ortak.marka("sgb")
    s = ornek_senaryo()
    assert beyin.metin_denetle(s, "", m) == []
    kotu = beyin.slot_yaz(s, {"s0.baslik": "500 tesisten en iyi bungalov"})
    h = beyin.metin_denetle(kotu, "", m, referans=s)
    assert any("kaynaksız rakam" in x for x in h) and any("yasak" in x for x in h)
    uzun = beyin.slot_yaz(s, {"s0.etiket": "Ç" * 40})
    assert any("uzun" in x for x in beyin.metin_denetle(uzun, "", m))
    assert any("site adresi" in x for x in beyin.metin_denetle(s, "Merhaba #sapanca", m))


def test_parlat_bozuk_yanitta_kurala_duser(monkeypatch, gecici_durum):
    m = ortak.marka("sgb")
    monkeypatch.setattr(beyin.llm, "var_mi", lambda: True)
    monkeypatch.setattr(beyin.llm, "json_sor", lambda *a: {"slotlar": {"s0.baslik": "1000 kişi bu bungalovu seçti"}, "aciklama": "x", "_saglayici": "gemini"})
    s, aciklama, kaynak = beyin.parlat(ornek_senaryo(), m, "sgb", random.Random(1))
    assert kaynak == "kural" and s["sahneler"][0]["baslik"] == "Kapora göndermeden 3 kontrol"
    assert m["site_kisa"] in aciklama


def test_parlat_iyi_yaniti_kullanir(monkeypatch, gecici_durum):
    m = ortak.marka("sgb")
    monkeypatch.setattr(beyin.llm, "var_mi", lambda: True)
    iyi = {"slotlar": {"s0.baslik": "Kapora atmadan önce bunu yapın"},
           "aciklama": f"Sapanca bungalov kiralarken kapora tuzağına düşmeyin\n\nBelgeyi sorun.\n\n{m['cta']}: {m['site_kisa']}\n\n#sapanca #bungalov",
           "_saglayici": "gemini"}
    monkeypatch.setattr(beyin.llm, "json_sor", lambda *a: iyi)
    s, aciklama, kaynak = beyin.parlat(ornek_senaryo(), m, "sgb", random.Random(1))
    assert kaynak == "gemini" and s["sahneler"][0]["baslik"] == "Kapora atmadan önce bunu yapın"
    assert s["sahneler"][1]["maddeler"] == ["Belgeyi sorun", "IBAN adını kontrol edin"]  # dokunulmayan slot korunur


def test_kural_aciklama_seo_ve_etiket():
    m = ortak.marka("davetiyeler")
    a = beyin.kural_aciklama(ornek_senaryo(), m, random.Random(3))
    assert a.splitlines()[0] == "Kapora göndermeden 3 kontrol"
    assert m["site_kisa"] in a and "Sapanca bungalov" in a
    assert 3 <= len([w for w in a.split() if w.startswith("#")]) <= 5


def test_format_ogrenme(gecici_durum, monkeypatch):
    monkeypatch.setenv("OTOPILOT_SAAT", "2026-11-22T12:00")
    kayitlar = [{"tarih": f"2026-11-0{i}", "tur": "reels", "format": f, "skor": sk}
                for i, (f, sk) in enumerate([("a", 2.0), ("a", 1.8), ("b", 0.4), ("b", 0.6)], start=1)]
    ortak.gecmis_yaz("deneme", kayitlar)
    c = beyin.format_carpani("deneme")
    assert c["a"] > 1.4 and c["b"] < 0.6
    # dün paylaşılan format sıranın başına nadiren gelir
    ortak.gecmis_yaz("deneme", [{"tarih": "2026-11-21", "tur": "reels", "format": "x"}])
    m = {"formatlar": {"x": 1, "y": 1}}
    ilk = [beyin.format_sirasi("deneme", m, random.Random(i))[0] for i in range(200)]
    assert ilk.count("y") > ilk.count("x") * 2


def test_kisa_ad():
    assert kisa_ad("Şeffaf Kare Düğün Davetiyesi – Model 7171", 40) == "Şeffaf Kare Düğün – Model 7171"
    assert "si" not in kisa_ad("Lüks Kare Düğün Davetiyesi").split()


def test_zamanlama(monkeypatch):
    monkeypatch.setenv("OTOPILOT_SAAT", "2026-11-22T12:05")
    assert "sitemucidi" in calistir.zamani_gelenler() and "sgb" not in calistir.zamani_gelenler()
    monkeypatch.setenv("OTOPILOT_SAAT", "2026-11-22T19:35")
    assert set(calistir.zamani_gelenler()) == {"sitemucidi", "sgb", "davetiyeler", "markakarnem"}


def test_dagitim_anahtarsiz_platformu_atlar_ve_dusen_digerini_durdurmaz(monkeypatch, tmp_path):
    from otopilot import dagitim
    for k in list(__import__("os").environ):
        if k.startswith(("YT_", "TT_", "META_", "IG_")):
            monkeypatch.delenv(k)
    monkeypatch.setenv("YT_CLIENT_ID", "x"); monkeypatch.setenv("YT_SGB_REFRESH_TOKEN", "x")
    monkeypatch.setenv("TT_CLIENT_KEY", "x"); monkeypatch.setenv("TT_SGB_REFRESH_TOKEN", "x")
    monkeypatch.setattr(dagitim.time, "sleep", lambda s: None)
    monkeypatch.setitem(dagitim.PLATFORMLAR, "youtube", (dagitim.PLATFORMLAR["youtube"][0], lambda *a: (_ for _ in ()).throw(RuntimeError("kota"))))
    monkeypatch.setitem(dagitim.PLATFORMLAR, "tiktok", (dagitim.PLATFORMLAR["tiktok"][0], lambda *a: "tiktok-taslak:SEND_TO_USER_INBOX:1"))
    s = dagitim.dagit("sgb", tmp_path / "v.mp4", "Başlık\n📞 wa.me/905", [])
    assert s["facebook"].startswith("atlandı") and s["youtube"].startswith("HATA") and s["tiktok"].startswith("tiktok-taslak")
    assert "wa.me" not in dagitim.tiktok_metni("a\nwa.me/1\nb")


def test_instagram_sistem_anahtari(monkeypatch):
    from otopilot.instagram import Instagram
    for k in ("IG_SGB_ID", "IG_SGB_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("IG_TOKEN", "sistem"); monkeypatch.setenv("META_SGB_IG_ID", "178")
    ig = Instagram("sgb")
    assert ig.hazir and ig.kimlik == "178" and "graph.facebook.com" in ig.kok
