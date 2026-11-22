"""Bir yıl elle müdahalesiz çalışma için güvenlik ağları: site çökerse yedek içerik, konu havuzu tükenirse tekrar,
biten kampanya/deneme iddiası videoya girmez, gün sonu nabzı."""
import random

import pytest

from otopilot import beyin, calistir, ortak
from otopilot.kaynak import iddia_temizle


@pytest.fixture
def gecici_durum(tmp_path, monkeypatch):
    monkeypatch.setattr(ortak, "DURUM", tmp_path)
    return tmp_path


@pytest.mark.parametrize("kod", ["sitemucidi", "davetiyeler", "sgb", "markakarnem"])
def test_tum_formatlar_coker_yedek_icerik(kod, gecici_durum, tmp_path, monkeypatch):
    def coker(ctx):
        raise ConnectionError("site kapalı")
    monkeypatch.setattr(beyin.KAYNAKLAR[kod], "FORMATLAR", {f: coker for f in ortak.marka(kod)["formatlar"]})
    m = ortak.marka(kod)
    s = beyin.planla(kod, m, None, tmp_path / "k")
    assert s["format"] == beyin.YEDEK and len(s["sahneler"]) == 3
    assert all(sh["tur"] == "kart" for sh in s["sahneler"])  # internete ihtiyaç yok
    assert not beyin.metin_denetle(s, beyin.kural_aciklama(s, m, random.Random(1)), m)
    with pytest.raises(RuntimeError):  # yedek de atlandıysa açık hata
        beyin.planla(kod, m, None, tmp_path / "k", atla={beyin.YEDEK})


def test_havuz_tukenince_son_14_gun_disi_tekrar_kullanilir(gecici_durum, tmp_path, monkeypatch):
    gorulen = []
    def secici(ctx):
        gorulen.append(set(ctx["kullanilan"]))
        return None if "eski" in ctx["kullanilan"] else {"anahtar": "eski", "konu": "x", "olgular": [], "sahneler": [{"tur": "kart", "tip": "kapak", "baslik": "x"}], "hikaye": {}}
    m = ortak.marka("sgb")
    monkeypatch.setattr(beyin.KAYNAKLAR["sgb"], "FORMATLAR", {f: secici for f in m["formatlar"]})
    eski = (ortak.simdi().date().replace(day=1)).isoformat()
    ortak.gecmis_guncelle("sgb", {"tarih": "2020-01-01", "tur": "reels", "anahtar": "eski", "format": "rehber"})
    ortak.gecmis_guncelle("sgb", {"tarih": eski, "tur": "reels", "anahtar": "x", "format": "rehber",
                             "ek_anahtarlar": ["eski"]})  # ek anahtarlar tüm geçmişten sayılır
    s = beyin.planla("sgb", m, None, tmp_path / "k")
    assert s["anahtar"] == "eski" and s["format"] != beyin.YEDEK


def test_biten_kampanya_videoya_girmez():
    s = {"olgular": ["Basılı davetiye alana ₺650+KDV değerinde dijital davetiye hediye.", "Adet 100-1000"],
         "sahneler": [{"tip": "cta", "baslik": "Dijital davetiye de hediye", "alt": "Basılı davetiye siparişine ₺650 değerinde"},
                      {"tip": "liste", "baslik": "Adımlar", "maddeler": ["Hediye kodunuz gelir", "Modeli seçin"]}],
         "hikaye": {"baslik": "Kampanya", "alt": "Dijital davetiye hediye"}}
    t = iddia_temizle(s, r"hediye|650\+KDV|650 değerinde", "Tüm modeller sitede")
    assert t["olgular"] == ["Adet 100-1000"]
    assert t["sahneler"][0]["baslik"] == "Tüm modeller sitede" and t["sahneler"][0]["alt"] == ""
    assert t["sahneler"][1]["maddeler"] == ["Modeli seçin"] and t["hikaye"]["alt"] == ""


def test_kampanya_formati_kampanya_bitince_kurulmaz(monkeypatch):
    from otopilot.kaynak import davetiyeler
    monkeypatch.setattr(davetiyeler, "hediye_suruyor", lambda: False)
    assert davetiyeler.kampanya({}) is None


def test_aciklama_tam_maddeler_ve_marka_kaydet_satiri():
    m = ortak.marka("markakarnem")
    s = {"konu": "x", "anahtar_kelime": "otel", "tam_maddeler": ["Uzun ve tam madde metni burada"],
         "sahneler": [{"tip": "kapak", "baslik": "Başlık"}, {"tip": "liste", "baslik": "Liste", "maddeler": ["Uzun ve tam…"]}]}
    a = beyin.kural_aciklama(s, m, random.Random(1))
    assert "✔️ Uzun ve tam madde metni burada" in a and "…" not in a
    assert m["kaydet_satiri"] in a and "otel arıyorsanız" not in a.lower()


def test_markakarnem_maskot_yolu():
    m = ortak.marka("markakarnem")
    assert m["maskot_yol"].endswith("markakarnem-maskot.png")
    assert "maskot_yol" not in ortak.marka("sgb")


def test_nabiz(gecici_durum, capsys):
    for kod in ortak.marka_kodlari():
        ortak.gecmis_guncelle(kod, {"tarih": ortak.bugun(), "tur": "reels", "durum": "yayinlandi", "anahtar": "a", "format": "f"})
    assert calistir.nabiz() == 0
    ortak.gecmis_guncelle("sgb", {"tarih": ortak.bugun(), "tur": "reels", "durum": "hata", "hata": "token", "anahtar": "a", "format": "f"})
    assert calistir.nabiz() == 1 and "Sapanca" in capsys.readouterr().out


def test_gemini_model_kesfi_en_yeni_flash_secilir():
    from otopilot.llm import model_sirala
    adlar = ["gemini-2.0-flash", "gemini-3.8-flash", "gemini-3.8-flash-lite", "gemini-3.9-flash-preview-11-2026",
             "gemini-3.8-pro", "gemini-3.8-flash-image", "gemini-3.8-flash-tts", "text-embedding-004"]
    s = model_sirala(adlar)
    assert s[:3] == ["gemini-3.8-flash", "gemini-3.8-flash-lite", "gemini-2.0-flash"] and s[3] == "gemini-3.9-flash-preview-11-2026"
    assert not any(x in " ".join(s) for x in ("pro", "image", "tts", "embedding"))
