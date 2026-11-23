"""İçerik zekâsı: strateji bağlamı, tekrar freni, editör, Bungalov kuruluş aşaması."""
import pytest

from otopilot import beyin, ortak, strateji
from otopilot.kaynak import sgb


@pytest.fixture
def durum(tmp_path, monkeypatch):
    monkeypatch.setattr(ortak, "DURUM", tmp_path)
    monkeypatch.setattr(strateji, "DURUM", tmp_path)
    from otopilot import plan
    monkeypatch.setattr(plan, "DURUM", tmp_path)
    return tmp_path


def test_baglam_strateji_arastirma_ve_tekrar_freni(durum):
    m = ortak.marka("davetiyeler")
    ortak.gecmis_guncelle("davetiyeler", {"tarih": "2026-11-20", "tur": "reels", "baslik": "Kaç davetiye bastırmalı?", "anahtar": "a", "format": "f"})
    ortak.json_kaydet(durum / "davetiyeler" / "arastirma.json", {"tarih": "2026-11-23", "trendler": ["Zarf açılış videoları"], "sorular": ["Kaç günde hazır?"]})
    b = strateji.baglam("davetiyeler", m)
    assert "LCV" in b and "Zarf açılış videoları" in b and "Kaç günde hazır?" in b
    assert "TEKRAR ETME" in b and "Kaç davetiye bastırmalı?" in b


def test_kurulus_asamasi_baglami(durum):
    m = {**ortak.marka("sgb"), "asama": "kurulus"}
    assert "listelenen tesis yok" in strateji.baglam("sgb", m)


def _senaryo():
    return {"format": "f", "konu": "k", "olgular": ["17 işletme ölçüldü"],
            "sahneler": [{"tur": "kart", "tip": "kapak", "baslik": "Eski kanca", "alt": "alt"}, {"tur": "kart", "tip": "cta", "baslik": "Son"}], "hikaye": {}}


def test_editor_dusuk_puanda_duzeltir_yuksekte_dokunmaz(durum, monkeypatch):
    m = ortak.marka("markakarnem")
    yanitlar = iter([
        {"puanlar": {"kanca": 4, "kitle": 6, "tek_mesaj": 7, "deger": 5, "cta": 6, "hata": 9, "ozgunluk": 6}, "notlar": "kanca zayıf",
         "slotlar": {"s0.baslik": "17 işletmeyi ölçtük, sonuç şaşırtıcı"}, "aciklama": ""},
        {"puanlar": {"kanca": 9, "kitle": 9, "tek_mesaj": 9, "deger": 8, "cta": 9, "hata": 10, "ozgunluk": 9}, "slotlar": {"s0.baslik": "değişmemeli"}},
        {"puanlar": {"kanca": 3, "kitle": 3, "tek_mesaj": 3, "deger": 3, "cta": 3, "hata": 3, "ozgunluk": 3}, "slotlar": {"s0.baslik": "999 işletme garanti"}},
    ])
    monkeypatch.setattr(strateji.llm, "json_sor", lambda s, i: next(yanitlar))
    args = (m, "markakarnem", beyin.slotlar, beyin.slot_yaz, beyin.slot_sinir, beyin.metin_denetle)
    s, _, r = strateji.editor(_senaryo(), "Açıklama markakarnem.com.tr #seo", *args)
    assert r["uygulandi"] and s["sahneler"][0]["baslik"] == "17 işletmeyi ölçtük, sonuç şaşırtıcı"
    s, _, r = strateji.editor(_senaryo(), "Açıklama markakarnem.com.tr #seo", *args)
    assert not r["uygulandi"] and s["sahneler"][0]["baslik"] == "Eski kanca"
    s, _, r = strateji.editor(_senaryo(), "Açıklama markakarnem.com.tr #seo", *args)  # uydurma rakam/yasak ifade → uygulanmaz
    assert not r["uygulandi"] and s["sahneler"][0]["baslik"] == "Eski kanca"


def test_sgb_kurulus_asamasi(monkeypatch):
    m = ortak.marka("sgb")
    monkeypatch.setattr(sgb, "tesis_sayisi", lambda: 0)
    a = sgb.asama_ayari(m)
    assert a["asama"] == "kurulus" and "sahte_ilan_isletme" in a["formatlar"] and "rehber" not in a["formatlar"]
    monkeypatch.setattr(sgb, "tesis_sayisi", lambda: 12)
    assert sgb.asama_ayari(m) == {}
    monkeypatch.setattr(sgb, "tesis_sayisi", lambda: None)  # okunamazsa varsayılan
    assert sgb.asama_ayari(m) == {}
    s = {"sahneler": [{"tip": "cta", "baslik": "Yalnız Bakanlık belgeli bungalovlar", "alt": "x"}, {"tip": "cta", "baslik": "Tesisinizi ücretsiz ekleyin", "alt": "y"}]}
    t = sgb.kurulus_temizle(s)
    assert t["sahneler"][0]["baslik"] == "Kapora göndermeden önce kontrol edin" and t["sahneler"][1]["baslik"] == "Tesisinizi ücretsiz ekleyin"


def test_kurulus_formatlari_tanimli():
    m = ortak.marka("sgb")
    assert set(m["asamalar"]["kurulus"]["formatlar"]) <= set(sgb.FORMATLAR)
