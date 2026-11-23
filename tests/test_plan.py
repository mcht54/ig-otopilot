"""İleri tarihli plan + panel istekleri (ağ/tarayıcı olmadan)."""
import datetime as dt
import json

import pytest

from otopilot import ortak, panel, plan


@pytest.fixture
def durum(tmp_path, monkeypatch):
    monkeypatch.setattr(ortak, "DURUM", tmp_path)
    monkeypatch.setattr(plan, "DURUM", tmp_path)
    monkeypatch.setattr(plan, "CIKTI", tmp_path / "cikti")
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    return tmp_path


def _oge(kod, gun, kaynak="otomatik"):
    s = {"format": "rehber", "konu": "Kapora", "anahtar": f"r:{gun}", "olgular": [], "tohum": f"{kod}:{gun}",
         "sahneler": [{"tur": "kart", "tip": "kapak", "baslik": "Eski başlık", "alt": "Alt", "gorsel": "file://{{KLASOR}}/a.png"},
                      {"tur": "kart", "tip": "cta", "baslik": "Son"}], "hikaye": {}}
    return {"id": f"{gun}-{kod}", "gun": gun, "kod": kod, "format": "rehber", "konu": "Kapora", "anahtar": s["anahtar"],
            "senaryo": s, "aciklama": "a", "anlatim": ["Bir!", "İki."], "kaynak": kaynak, "varlik": False, "gorsel": None}


def test_yer_tutucu_gidis_donus(tmp_path):
    k = tmp_path / "k"
    s = {"a": str(k / "x.html"), "b": (k / "y.png").as_uri()}
    t = plan._yer_tut(s, k)
    assert "{{KLASOR}}" in json.dumps(t) and str(tmp_path) not in json.dumps(t)
    yeni = tmp_path / "baska"
    assert plan._yer_ac(t, yeni) == {"a": str(yeni / "x.html"), "b": (yeni / "y.png").as_uri()}


def test_duzenleme_uygulanir_gecmis_gun_reddedilir(durum):
    yarin = (ortak.simdi().date() + dt.timedelta(days=1)).isoformat()
    bugun = ortak.simdi().date().isoformat()
    plan.yaz("sgb", {yarin: _oge("sgb", yarin), bugun: _oge("sgb", bugun)})
    sonuc = plan.panel_isle({"duzenlemeler": [
        {"id": "d1", "bolum_id": f"{yarin}-sgb", "satirlar": {"k.baslik": "Yeni  başlık", "a1": "%20 indirim yok"}},
        {"id": "d2", "bolum_id": f"{bugun}-sgb", "satirlar": {"a0": "x"}}]}, None)
    assert sonuc["uygulanan"] == ["d1"] and sonuc["reddedilen"][0]["id"] == "d2"
    o = plan.oku("sgb")[yarin]
    assert o["senaryo"]["sahneler"][0]["baslik"] == "Yeni başlık" and o["anlatim"][1] == "yüzde 20 indirim yok"


def test_tanitim_ilk_otomatik_gune_yerlesir(durum, monkeypatch):
    g1 = (ortak.simdi().date() + dt.timedelta(days=1)).isoformat()
    g2 = (ortak.simdi().date() + dt.timedelta(days=2)).isoformat()
    plan.yaz("davetiyeler", {g1: _oge("davetiyeler", g1, kaynak="istek"), g2: _oge("davetiyeler", g2)})
    monkeypatch.setattr(plan, "ozel_icerik", lambda kod, m, metin, t, k, g: {"senaryo": _oge(kod, g.isoformat())["senaryo"], "aciklama": "x",
                                                                            "kaynak": "istek", "neden": "Nişan sezonu için kanca"})
    monkeypatch.setattr(plan, "_tamamla", lambda kod, m, oge, g, t, k: {**_oge(kod, g.isoformat(), oge["kaynak"]), "neden": oge["neden"],
                                                                       "tanitim_id": oge.get("tanitim_id")})
    sonuc = plan.panel_isle({"tanitimlar": [{"id": "t1", "metin": "Nişan davetiyelerini öne çıkar", "urun": "davetiyeler"},
                                             {"id": "t2", "metin": "x", "urun": None}]}, None)
    assert sonuc["tanitim"][0] == {"id": "t1", "durum": "planlandi", "gun": g2, "aciklama": "Nişan sezonu için kanca"}
    assert sonuc["tanitim"][1]["durum"] == "reddedildi"
    assert plan.oku("davetiyeler")[g2]["kaynak"] == "tanitim"


def test_uygunsuz_istek_nedeniyle_reddedilir(durum, monkeypatch):
    g = (ortak.simdi().date() + dt.timedelta(days=3)).isoformat()
    def red(*a):
        raise ValueError("Markayla ilgisiz")
    monkeypatch.setattr(plan, "ozel_icerik", red)
    sonuc = plan.panel_isle({"istekler": [{"id": "i1", "gun": g, "urun": "sgb", "istek": "kripto anlat"}]}, None)
    assert sonuc["reddedilen"] == [{"id": "i1", "neden": "Markayla ilgisiz"}]


def test_gecici_hata_istegi_bekletir(durum, monkeypatch):
    g = (ortak.simdi().date() + dt.timedelta(days=3)).isoformat()
    def gecici(*a):
        raise RuntimeError("yapay zekâ yanıt vermedi")
    monkeypatch.setattr(plan, "ozel_icerik", gecici)
    sonuc = plan.panel_isle({"istekler": [{"id": "i1", "gun": g, "urun": "sgb", "istek": "x"}]}, None)
    assert sonuc == {"uygulanan": [], "reddedilen": [], "tanitim": []}  # panelde bekler, sonra yeniden denenir


def test_bugunku_varliksiz_plan_yolu_acilir(durum, tmp_path):
    bugun = ortak.simdi().date().isoformat()
    o = _oge("sgb", bugun)
    o["senaryo"]["sahneler"][0]["gorsel"] = None
    plan.yaz("sgb", {bugun: o})
    h = plan.bugunku("sgb", tmp_path / "k")
    assert h["senaryo"]["sahneler"][0]["baslik"] == "Eski başlık"
    o2 = _oge("sgb", bugun)  # yer tutuculu ama varlık paketi yok → baştan kur
    plan.yaz("sgb", {bugun: o2})
    assert plan.bugunku("sgb", tmp_path / "k") is None


def test_buyume_ve_panel_ozeti(durum):
    bugun = ortak.simdi().date()
    seri = [{"gun": (bugun - dt.timedelta(days=d)).isoformat(), "takipci": 100 + (10 - d) * 5, "gonderi": 1} for d in range(10, -1, -1)]
    (durum / "sgb").mkdir(parents=True, exist_ok=True)
    (durum / "sgb" / "hesap.json").write_text(json.dumps(seri))
    b = plan.buyume("sgb")
    assert b["takipci"] == 150 and b["degisim_7g"] == 35 and b["yuzde_7g"] == pytest.approx(30.4, 0.1)
    yarin = (bugun + dt.timedelta(days=1)).isoformat()
    plan.yaz("sgb", {yarin: _oge("sgb", yarin)})
    oz = [x for x in panel.ozet() if x["sektor"] == "sgb"]
    assert oz[-1]["durum"] == "senaryo" and oz[-1]["duzenlenebilir"] and [s["id"] for s in oz[-1]["satirlar"]] == ["k.baslik", "k.alt", "a0", "a1"]
    e = panel.ekler()
    assert {u["anahtar"] for u in e["urunler"]} == set(ortak.marka_kodlari()) and e["markalar"]["sgb"]["takipci"] == 150
