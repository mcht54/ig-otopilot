"""Panel 'Düzelt': bağlantı raporu genel sınıflarla (anahtar/kimlik yok), kesin hata yeniden gönderilir, belirsiz ASLA; insan adımı bağlantıyla."""
import datetime as dt

from otopilot import duzelt


def test_hata_siniflari_anahtar_icermez():
    assert duzelt._sinif('{"error":{"message":"Error validating access token: Session has expired","code":190}}') == "Meta anahtarı geçersiz ya da süresi dolmuş"
    assert duzelt._sinif("invalid_grant: Token has been expired or revoked.") == "Yetki iptal edilmiş ya da süresi dolmuş"
    assert "EAAB" not in duzelt._sinif("EAABxyz gizli anahtar bir şey")


def _kur(monkeypatch, tmp_path, once, sonra, bg):
    monkeypatch.setattr(duzelt, "DOSYA", tmp_path / "baglanti.json")
    monkeypatch.setattr(duzelt, "baglanti", lambda kod: bg)
    monkeypatch.setattr(duzelt, "simdi", lambda: dt.datetime(2026, 11, 26, 21, 0))
    durum = {"k": {"tarih": "2026-11-26", "tur": "reels", "durum": "yayinlandi", "platformlar": once}}
    monkeypatch.setattr(duzelt, "gecmis", lambda kod: [durum["k"]])
    from otopilot import calistir
    cagri = []

    def eksik(kodlar, elle=False):
        cagri.append((kodlar, elle))
        durum["k"] = {**durum["k"], "platformlar": sonra}
    monkeypatch.setattr(calistir, "eksik", eksik)
    return cagri


def test_kesin_hata_yeniden_gonderilir_rapor_tamam(monkeypatch, tmp_path):
    bg = {"instagram": {"durum": "tamam", "mesaj": "ok"}, "facebook": {"durum": "tamam", "mesaj": "ok"}}
    cagri = _kur(monkeypatch, tmp_path, {"instagram": "https://ig", "facebook": "HATA: 500"}, {"instagram": "https://ig", "facebook": "https://fb"}, bg)
    r = duzelt.rapor("sgb")
    assert cagri == [(["sgb"], True)]
    assert r["durum"] == "tamam" and any(a["ad"] == "Facebook Reels yeniden gönderildi" for a in r["adimlar"])


def test_belirsiz_ve_kopuk_anahtar_sorun_ve_eylem(monkeypatch, tmp_path):
    bg = {"instagram": {"durum": "hata", "mesaj": "Meta anahtarı geçersiz ya da süresi dolmuş"}, "facebook": {"durum": "tamam", "mesaj": "ok"}}
    _kur(monkeypatch, tmp_path, {"instagram": "BELIRSIZ: zaman aşımı"}, {"instagram": "BELIRSIZ: zaman aşımı"}, bg)
    r = duzelt.rapor("sgb")
    assert r["durum"] == "sorun"
    assert any(a["durum"] == "uyari" and "belirsiz" in a["ad"] for a in r["adimlar"])
    assert r["eylemler"] and r["eylemler"][0]["link"].startswith("https://business.facebook.com/")
