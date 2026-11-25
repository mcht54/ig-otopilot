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


def _hazirla(tmp_path, monkeypatch, kayit):
    yazilan = {}
    monkeypatch.setattr(calistir, "bugun", lambda: "2026-11-25")
    monkeypatch.setattr(calistir, "gecmis", lambda kod: [kayit])
    monkeypatch.setattr(calistir, "gecmis_guncelle", lambda kod, k: yazilan.update({kod: dict(k)}))
    monkeypatch.setattr(calistir, "CIKTI", tmp_path)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    from otopilot import plan
    monkeypatch.setattr(plan, "indir", lambda ad, hedef: v)
    monkeypatch.setattr(calistir.dagitim, "dagit", lambda *a, **k: (_ for _ in ()).throw(AssertionError("dagit çağrılmamalı")))
    monkeypatch.setattr(calistir.dagitim, "PLATFORMLAR", {"facebook": (lambda k: False, None), "facebook_hikaye": (lambda k: False, None)})
    return yazilan


class _IG:
    hazir = True
    def __init__(self, kod, reels_hata=None):
        self.cagri = []
    def reels(self, video, aciklama):
        self.cagri.append("reels")
        return {"id": "m9", "permalink": "https://ig/reel/9"}
    def hikaye(self, video):
        self.cagri.append("hikaye")
        return {"id": "h9"}


def test_kesin_ig_hatasi_reels_ve_hikaye_tamamlanir(tmp_path, monkeypatch):
    kayit = {"tarih": "2026-11-25", "tur": "reels", "durum": "yayinlandi", "aciklama": "Metin", "video_yedek": "x.mp4",
             "hata": "yükleme 400: ProcessingFailedError",
             "platformlar": {"instagram": "HATA: yükleme 400", "instagram_hikaye": "atlandı",
                             "facebook": "https://fb/1", "facebook_hikaye": "http-fb-hikaye:2"}}
    yazilan = _hazirla(tmp_path, monkeypatch, kayit)
    ig = _IG("sgb")
    monkeypatch.setattr(calistir, "Instagram", lambda kod: ig)
    calistir.eksik(["sgb"])
    assert ig.cagri == ["reels", "hikaye"]
    son = yazilan["sgb"]
    assert son["medya_id"] == "m9" and son["platformlar"]["instagram"] == "https://ig/reel/9"
    assert son["platformlar"]["instagram_hikaye"] == "http-ig-hikaye:h9" and son["ig_tekrar"] == 1


def test_belirsiz_ve_medyali_ig_yeniden_gonderilmez(tmp_path, monkeypatch):
    for pl, ek in (({"instagram": "BELIRSIZ: x", "instagram_hikaye": "atlandı", "facebook": "https://fb"}, {}),
                   ({"instagram": "HATA: x", "instagram_hikaye": "http-ig-hikaye:1", "facebook": "https://fb"}, {"medya_id": "m1"}),
                   ({"instagram": "HATA: x", "instagram_hikaye": "atlandı", "facebook": "https://fb"}, {"ig_tekrar": 3}),
                   ({"instagram": "https://ig/1", "instagram_hikaye": "HATA: BELIRSIZ: y", "facebook": "https://fb"}, {"medya_id": "m1"})):
        kayit = {"tarih": "2026-11-25", "tur": "reels", "durum": "yayinlandi", "aciklama": "M", "video_yedek": "x.mp4",
                 "platformlar": dict(pl), **ek}
        _hazirla(tmp_path, monkeypatch, kayit)
        monkeypatch.setattr(calistir, "Instagram", lambda kod: (_ for _ in ()).throw(AssertionError(f"denenmemeli: {pl}")))
        monkeypatch.setattr(calistir.dagitim, "PLATFORMLAR", {"facebook": (lambda k: False, None)})
        calistir.eksik(["sgb"])


def test_youtube_metni_profil_linkini_ve_basligi_uyarlar():
    baslik, acik = calistir.dagitim.youtube_meta(
        "Gece gelen teklif\n\n👉 Profildeki linkten ücretsiz dene: sitemucidi.com.tr\n\n#websitesi", ["#websitesi"], "sitemucidi")
    assert baslik.startswith("Site Mucidi | ") and baslik.endswith("#shorts")
    assert "Açıklamadaki linkten" in acik and "rofildeki" not in acik
    assert acik.index("https://www.sitemucidi.com.tr") < acik.index("#websitesi")


def test_anahtari_sonradan_eklenen_platform_bugune_gider(tmp_path, monkeypatch):
    kayit = {"tarih": "2026-11-25", "tur": "reels", "durum": "yayinlandi", "aciklama": "M", "video_yedek": "x.mp4",
             "medya_id": "m1", "platformlar": {"instagram": "https://ig/1", "instagram_hikaye": "http-ig-hikaye:1",
                                               "youtube": "atlandı: anahtar yok"}}
    _hazirla(tmp_path, monkeypatch, kayit)
    giden = []
    monkeypatch.setattr(calistir.dagitim, "PLATFORMLAR", {"youtube": (lambda k: True, None)})
    monkeypatch.setattr(calistir.dagitim, "dagit", lambda kod, v, a, e, onceki=None: giden.append(kod) or {**onceki, "youtube": "https://yt/1"})
    calistir.eksik(["sitemucidi"])
    assert giden == ["sitemucidi"]
