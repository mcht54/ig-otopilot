"""Yorum/DM yanıtlama: yalnız yeni olanlara taslak, onaylananlar gönderilir, içerik loga yazılmaz (depo herkese açık)."""
from otopilot import etkilesim, panel


def test_akis_ve_gizlilik(monkeypatch, capsys):
    monkeypatch.setattr(etkilesim, "marka_kodlari", lambda: ["davetiyeler"])
    class IG:
        hazir = True
        def __init__(self, kod): pass
    monkeypatch.setattr(etkilesim, "Instagram", IG)
    aday = [{"id": "ig-yorum:1", "kod": "davetiyeler", "tur": "yorum", "hedef": "1", "kullanici": "ayse.gizli", "metin": "Fiyat nedir GIZLIMETIN",
             "zaman": "2026-11-23T10:00:00+0000", "link": "https://www.instagram.com/p/x/", "baglam": ""},
            {"id": "ig-yorum:2", "kod": "davetiyeler", "tur": "yorum", "hedef": "2", "kullanici": "eski", "metin": "eski yorum",
             "zaman": "2026-11-23T09:00:00+0000", "link": None, "baglam": ""}]
    monkeypatch.setattr(etkilesim, "yorumlar", lambda kod, ig, sinir: aday)
    monkeypatch.setattr(etkilesim, "mesajlar", lambda kod, sinir: (_ for _ in ()).throw(RuntimeError("DM izni yok")))
    monkeypatch.setattr(etkilesim, "taslak", lambda oge, m: {"taslak": "Merhaba, fiyat için sitemize bakın", "not": "", "oncelik": "yuksek"})
    gonderilen = []
    monkeypatch.setattr(etkilesim, "gonder", lambda g: gonderilen.append(g["id"]) if g["id"] != "ig-yorum:9" else (_ for _ in ()).throw(RuntimeError("izin")))
    cagrilar = []
    def kopru(yuk):
        cagrilar.append(yuk)
        if "adaylar" in yuk:
            return {"bilinmeyen": ["ig-yorum:1"], "gonderilecek": [{"id": "ig-yorum:5", "kod": "davetiyeler", "tur": "yorum", "hedef": "5", "metin": "Teşekkürler"},
                                                                {"id": "ig-yorum:9", "kod": "davetiyeler", "tur": "yorum", "hedef": "9", "metin": "x"}]}
        return {}
    monkeypatch.setattr(panel, "etkilesim", kopru)
    etkilesim.calistir()
    ilk, ikinci = cagrilar
    assert ilk["adaylar"] == ["ig-yorum:1", "ig-yorum:2"] and ilk["durumlar"]["davetiyeler"]["dm"].startswith("hata")
    assert [y["id"] for y in ikinci["yeni"]] == ["ig-yorum:1"] and ikinci["yeni"][0]["taslak"].startswith("Merhaba")
    assert gonderilen == ["ig-yorum:5"]
    assert ikinci["sonuc"] == [{"id": "ig-yorum:5", "durum": "gonderildi"}, {"id": "ig-yorum:9", "durum": "hata", "neden": "izin"}]
    cikti = capsys.readouterr().out
    assert "GIZLIMETIN" not in cikti and "ayse.gizli" not in cikti and "1 yeni" in cikti


def test_panel_yoksa_bozulmaz(monkeypatch):
    monkeypatch.setattr(etkilesim, "marka_kodlari", lambda: [])
    monkeypatch.setattr(panel, "etkilesim", lambda yuk: None)
    assert etkilesim.calistir() == 0


def test_taslak_sinif_ve_musteri(monkeypatch):
    """Sınıf geçersizse None; satın alma/şikâyet her zaman yüksek öncelik; boş müşteri alanı atılır (uydurma yok)."""
    from otopilot import etkilesim
    m = {"ad": "Site Mucidi", "site_kisa": "sitemucidi.com.tr", "deger_onerisi": ["x"], "strateji": {}}
    oge = {"tur": "dm", "metin": "Site yaptırmak istiyorum", "baglam": ""}
    monkeypatch.setattr(etkilesim.llm, "json_sor", lambda s, i: {"taslak": "Merhaba", "oncelik": "normal", "sinif": "satin_alma", "konu": " Fiyat ",
                                                                  "musteri": {"ad": "Ali", "telefon": "", "ihtiyac": "kuaför sitesi"}})
    t = etkilesim.taslak(oge, m)
    assert t["sinif"] == "satin_alma" and t["oncelik"] == "yuksek" and t["konu"] == "fiyat"
    assert t["musteri"] == {"ad": "Ali", "ihtiyac": "kuaför sitesi"}
    monkeypatch.setattr(etkilesim.llm, "json_sor", lambda s, i: {"taslak": "", "sinif": "uydurma", "musteri": {"ad": ""}})
    t = etkilesim.taslak(oge, m)
    assert t["sinif"] is None and t["musteri"] is None and t["oncelik"] == "normal"
