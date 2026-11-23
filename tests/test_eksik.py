from otopilot import calistir


def test_eksik_yalniz_hatali_platformu_gonderir(tmp_path, monkeypatch):
    kayit = {"tarih": "2026-11-23", "tur": "reels", "durum": "yayinlandi", "medya_id": "m1", "aciklama": "Metin #etiket",
             "video_yedek": "2026-11-23-sgb-reel.mp4",
             "platformlar": {"instagram": "https://ig/x", "facebook": "HATA: 403", "youtube": "atlandı: anahtar yok"}}
    yazilan, gonderilen = {}, []
    monkeypatch.setattr(calistir, "bugun", lambda: "2026-11-23")
    monkeypatch.setattr(calistir, "gecmis", lambda kod: [dict(kayit)])
    monkeypatch.setattr(calistir, "gecmis_guncelle", lambda kod, k: yazilan.update({kod: k}))
    monkeypatch.setattr(calistir, "CIKTI", tmp_path)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    from otopilot import plan
    monkeypatch.setattr(plan, "indir", lambda ad, hedef: v)

    def dagit(kod, video, aciklama, etiketler, onceki=None):
        gonderilen.append((kod, aciklama, etiketler))
        return {**onceki, "facebook": "https://fb/reel/1"}
    monkeypatch.setattr(calistir.dagitim, "dagit", dagit)
    calistir.eksik(["sgb"])
    assert gonderilen == [("sgb", "Metin #etiket", ["#etiket"])]
    assert yazilan["sgb"]["platformlar"]["facebook"].startswith("https") and yazilan["sgb"]["platformlar"]["instagram"] == "https://ig/x"


def test_hatasiz_kayitta_bir_sey_gonderilmez(monkeypatch):
    monkeypatch.setattr(calistir, "bugun", lambda: "2026-11-23")
    monkeypatch.setattr(calistir, "gecmis", lambda kod: [{"tarih": "2026-11-23", "tur": "reels", "durum": "yayinlandi",
                                                          "platformlar": {"facebook": "https://fb"}}])
    monkeypatch.setattr(calistir.dagitim, "dagit", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gönderilmemeli")))
    calistir.eksik(["sgb"])
