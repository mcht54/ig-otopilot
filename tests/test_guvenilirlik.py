"""Belirsiz paylaşım güvenliği (çift paylaşım yok), anlatım kuralı, araştırma kotası, nabız günü ve log gizliliği.
Gerçek API çağrısı yapılmaz: requests sahte yanıtlarla değiştirilir."""
import json

import pytest
import requests

from otopilot import calistir, dagitim, instagram, llm, ortak, panel, plan, strateji

BUGUN = "2026-11-24"
KIMLIK = "17841400000000001"


class Yanit:
    def __init__(self, veri, kod=200):
        self.status_code, self._v = kod, veri
        self.ok = kod < 400
        self.headers = {"content-type": "application/json"}
        self.text = json.dumps(veri)

    def json(self):
        return self._v


class SahteIG:
    """graph.instagram.com yerine geçer; media_publish / bağlantı / hesap listesi davranışı ayarlanır."""

    def __init__(self):
        self.yayin = {"REELS": [], "STORIES": []}   # media_publish çağrıları
        self.yayin_hatasi = {}                        # tür → yükseltilecek istisna
        self.baglanti_hatasi = False                  # yayından sonraki GET permalink düşsün mü
        self.medya = []                               # hesaptaki son gönderiler

    def request(self, yontem, url, params=None, data=None, timeout=None):
        yol = url.split("/v25.0/", 1)[1]
        p = params or data or {}
        if yontem == "POST" and yol == f"{KIMLIK}/media":
            return Yanit({"id": f"kap-{p['media_type']}", "uri": "https://rupload.example/x"})
        if yontem == "POST" and yol == f"{KIMLIK}/media_publish":
            tur = p["creation_id"].removeprefix("kap-")
            self.yayin[tur].append(1)
            if tur in self.yayin_hatasi:
                raise self.yayin_hatasi[tur]
            return Yanit({"id": f"medya-{tur}"})
        if yontem == "GET" and yol == f"{KIMLIK}/media":
            return Yanit({"data": self.medya})
        if yontem == "GET" and yol.startswith("kap-"):
            return Yanit({"status_code": "FINISHED"})
        if yontem == "GET" and yol.startswith("medya-"):
            if self.baglanti_hatasi:
                raise requests.ConnectionError("bağlantı koptu")
            return Yanit({"id": yol, "permalink": f"https://instagram.com/reel/{yol}"})
        if yontem == "GET" and yol == KIMLIK:
            return Yanit({"id": KIMLIK, "username": "sgb", "followers_count": 1, "media_count": 1})
        raise AssertionError(f"beklenmeyen istek {yontem} {yol}")


@pytest.fixture
def ortam(tmp_path, monkeypatch):
    monkeypatch.setattr(ortak, "DURUM", tmp_path / "durum")
    monkeypatch.setattr(calistir, "CIKTI", tmp_path / "cikti")
    monkeypatch.setenv("OTOPILOT_SAAT", f"{BUGUN}T19:05")
    monkeypatch.setenv("YAYIN", "acik")
    monkeypatch.setenv("IG_SGB_ID", KIMLIK)
    monkeypatch.setenv("IG_SGB_TOKEN", "test-anahtari")
    monkeypatch.delenv("IG_SGB_API", raising=False)
    ig = SahteIG()
    monkeypatch.setattr(instagram.requests, "request", ig.request)
    monkeypatch.setattr(instagram.requests, "post", lambda *a, **k: Yanit({}, 200))  # rupload
    monkeypatch.setattr(instagram.time, "sleep", lambda s: None)
    monkeypatch.setattr(calistir, "olc", lambda kod, ig=None: None)
    monkeypatch.setattr(plan, "hesap_kaydet", lambda kod, h: None)
    monkeypatch.setattr(plan, "bugunku", lambda kod, klasor: None)
    monkeypatch.setattr(plan, "yukle", lambda yol: False)
    monkeypatch.setattr(calistir.subprocess, "run", lambda *a, **k: None)

    class Tarayici:
        def close(self):
            pass

    class PW:
        chromium = type("C", (), {"launch": staticmethod(lambda **k: Tarayici())})

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(calistir, "sync_playwright", lambda: PW())
    ig.uretim = []

    def uret(kod, tarayici, klasor, hazir=None):
        ig.uretim.append(kod)
        klasor.mkdir(parents=True, exist_ok=True)
        dosya = {}
        for ad in ("reel.mp4", "hikaye.mp4", "kapak.jpg"):
            (klasor / ad).write_bytes(b"x")
            dosya[ad.split(".")[0]] = klasor / ad
        s = {"format": "rehber", "anahtar": "a1", "konu": "Konu", "sahneler": [{"baslik": "Başlık"}], "metin_kaynagi": "plan",
             "anlatim": ["Merhaba!"], "ses_kaynagi": "gemini"}
        return {"senaryo": s, "aciklama": "Metin #sapanca", **dosya}
    monkeypatch.setattr(calistir, "uret", uret)
    ig.dagit = []

    def dagit(kod, video, aciklama, etiketler, onceki=None):
        ig.dagit.append(kod)
        return {"facebook": "https://www.facebook.com/reel/1"}
    monkeypatch.setattr(calistir.dagitim, "dagit", dagit)
    calistir._SUREN.clear()
    return ig


def _kayit(kod="sgb"):
    return next(k for k in ortak.gecmis(kod) if k["tarih"] == BUGUN and k["tur"] == "reels")


# ---------------- Instagram: belirsiz yayın ----------------

def test_media_publish_zaman_asimi_belirsiz_ikinci_calistirma_paylasmaz(ortam):
    ortam.yayin_hatasi["REELS"] = requests.Timeout("okuma zaman aşımı")
    assert calistir.main(["otomatik", "--marka", "sgb"]) == 1, "belirsiz yayın çalıştırmayı başarısız gösterir"
    k = _kayit()
    assert k["durum"] == "belirsiz" and "elle kontrol" in k["not_"]
    assert ortam.yayin == {"REELS": [1], "STORIES": []}, "hikâye denenmez"
    assert ortam.dagit == [], "Facebook vb. bu çalıştırmada atlanır"
    # aynı gün ikinci çalıştırma (ör. 22:00 yeniden deneme): hiçbir yayın çağrısı yok, üretim de yok
    assert calistir.main(["otomatik", "--marka", "sgb"]) == 0
    assert ortam.yayin == {"REELS": [1], "STORIES": []} and ortam.uretim == ["sgb"]
    assert _kayit()["durum"] == "belirsiz"


def test_media_publish_5xx_de_belirsiz(ortam, monkeypatch):
    ig = instagram.Instagram("sgb")
    monkeypatch.setattr(instagram.requests, "request", lambda *a, **k: Yanit({"error": {"message": "iç hata"}}, 500))
    with pytest.raises(ortak.BelirsizYayin):
        ig._yayinla("kap-REELS")
    assert not issubclass(ortak.BelirsizYayin, instagram.InstagramHatasi)


def test_yayindan_once_ag_hatasi_normal_hata_yeniden_denenebilir(ortam, monkeypatch):
    def coker(*a, **k):
        raise requests.ConnectionError("kapsayıcı oluşturulamadı")
    monkeypatch.setattr(instagram.requests, "request", coker)
    with pytest.raises(instagram.InstagramHatasi):
        instagram.Instagram("sgb")._yukle(ortak.KOK / "requirements.txt", media_type="REELS")


def test_permalink_okunamazsa_medya_id_kalir_yeniden_paylasilmaz(ortam):
    ortam.baglanti_hatasi = True
    k = calistir.gunluk("sgb")
    assert k["durum"] == "yayinlandi" and k["medya_id"] == "medya-REELS" and k["link"] is None
    assert k["platformlar"]["instagram"] == "http-ig-medya:medya-REELS"
    assert _kayit()["medya_id"] == "medya-REELS"
    calistir.gunluk("sgb")
    assert ortam.yayin["REELS"] == [1], "ikinci çalıştırma yeniden paylaşmaz"


def test_hikaye_ag_hatasi_reels_kaydini_bozmaz(ortam):
    ortam.yayin_hatasi["STORIES"] = requests.ConnectionError("bağlantı sıfırlandı")
    k = calistir.gunluk("sgb")
    assert k["durum"] == "yayinlandi" and k["medya_id"] == "medya-REELS"
    assert k["hikaye_hata"].startswith("BELIRSIZ") and "hikaye_id" not in k
    assert ortam.dagit == ["sgb"], "Facebook yine denenir"
    assert _kayit()["durum"] == "yayinlandi"


def test_main_yakalayicisi_yayimlanmis_reelsi_bos_hata_ile_ezmez(ortam, monkeypatch):
    monkeypatch.setattr(calistir.dagitim, "dagit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("dağıtım çöktü")))
    assert calistir.main(["otomatik", "--marka", "sgb"]) == 1
    k = _kayit()
    assert k["durum"] == "yayinlandi" and k["medya_id"] == "medya-REELS" and "dağıtım çöktü" in k["not_"]
    assert k["format"] == "rehber", "boş 'hata' kaydı yazılmadı"
    calistir.main(["otomatik", "--marka", "sgb"])
    assert ortam.yayin["REELS"] == [1]


def test_hata_kaydi_yayin_basladiysa_belirsiz_baslamadiysa_hata():
    calistir._SUREN.clear()
    calistir._SUREN["sgb"] = {"kayit": {"tarih": BUGUN, "tur": "reels", "durum": "onizleme", "format": "f"}, "yayin_basladi": True}
    assert calistir.hata_kaydi("sgb", RuntimeError("x"))["durum"] == "belirsiz"
    calistir._SUREN["sgb"] = {"kayit": {"tarih": BUGUN, "tur": "reels", "durum": "onizleme", "format": "f"}, "yayin_basladi": False}
    assert calistir.hata_kaydi("sgb", RuntimeError("x"))["durum"] == "hata"
    assert calistir.hata_kaydi("sgb", RuntimeError("x"))["format"] == "?"  # sürmekte olan kayıt yoksa eski davranış


def test_reels_beklenmeyen_hata_belirsiz(ortam):
    ortam.yayin_hatasi["REELS"] = KeyError("id")
    k = calistir.gunluk("sgb")
    assert k["durum"] == "belirsiz" and ortam.dagit == []


@pytest.mark.parametrize("zaman, paylasir", [
    ("2026-11-24T08:00:00+0000", False),   # 11:00 TR, bugün
    ("2026-11-23T22:30:00+0000", False),   # 01:30 TR, bugün (UTC'ye göre dün)
    ("2026-11-23T20:30:00+0000", True),    # 23:30 TR, dün
])
def test_hesapta_bugun_gonderi_varsa_paylasilmaz(ortam, zaman, paylasir):
    ortam.medya = [{"id": "eski", "timestamp": zaman}]
    k = calistir.gunluk("sgb")
    if paylasir:
        assert k["durum"] == "yayinlandi" and ortam.yayin["REELS"] == [1]
    else:
        assert k["durum"] == "belirsiz" and k["not_"] == "bugün hesapta paylaşım var, elle kontrol"
        assert ortam.yayin["REELS"] == [] and ortam.uretim == [] and ortam.dagit == []


def test_hata_kaydi_hesapta_gonderi_varsa_belirsize_doner(ortam):
    """Eski sürümün boş 'hata' kaydı: hesapta bugünkü gönderi görülünce yeniden paylaşılmaz."""
    ortak.gecmis_guncelle("sgb", {"tarih": BUGUN, "tur": "reels", "durum": "hata", "hata": "x", "format": "?", "anahtar": ""})
    ortam.medya = [{"id": "m", "timestamp": f"{BUGUN}T10:00:00+0000"}]
    assert calistir.gunluk("sgb")["durum"] == "belirsiz" and ortam.yayin["REELS"] == []


def test_belirsiz_kayit_hesap_listesinde_yoksa_da_paylasilmaz(ortam):
    ortak.gecmis_guncelle("sgb", {"tarih": BUGUN, "tur": "reels", "durum": "belirsiz", "format": "f", "anahtar": ""})
    ortam.medya = []  # listede olmaması paylaşım olmadığının kanıtı değildir
    assert calistir.gunluk("sgb")["durum"] == "belirsiz" and ortam.yayin["REELS"] == [] and ortam.uretim == []


# ---------------- anlatım kuralı ----------------

def test_anlatim_sesi_yoksa_ertelenir_paylasim_yok_sonra_yeniden_denenir(ortam, monkeypatch):
    asil = calistir.uret

    def sessiz(*a, **k):
        raise calistir.SesYok("geçerli anlatım sesi üretilemedi")
    monkeypatch.setattr(calistir, "uret", sessiz)
    k = calistir.gunluk("sgb")
    assert k["durum"] == "ertelendi" and "anlatım" in k["hata"]
    assert ortam.yayin == {"REELS": [], "STORIES": []} and ortam.dagit == []
    assert _kayit()["durum"] == "ertelendi"
    monkeypatch.setattr(calistir, "uret", asil)  # sonraki çalıştırma (ör. 22:00) yeniden üretir
    assert calistir.gunluk("sgb")["durum"] == "yayinlandi" and ortam.yayin["REELS"] == [1]


def test_uret_ses_yokken_baska_formata_gecmez(monkeypatch):
    m = {"formatlar": ["a", "b", "c"]}
    monkeypatch.setattr(calistir.beyin, "guncel_marka", lambda kod: m)
    monkeypatch.setattr(calistir.beyin, "planla", lambda *a, **k: {"format": "a", "tohum": "t"})
    monkeypatch.setattr(calistir.beyin, "parlat", lambda s, m, kod, rnd: (s, "aç", "kural"))
    monkeypatch.setattr(calistir.beyin, "metin_denetle", lambda *a: [])
    cagri = []
    monkeypatch.setattr(calistir, "_uret_bir", lambda *a, **k: cagri.append(1) or (_ for _ in ()).throw(calistir.SesYok("yok")))
    with pytest.raises(calistir.SesYok):
        calistir.uret("sgb", None, None)
    assert cagri == [1], "ses servisi her formatta yeniden denenip kota yakmaz"


# ---------------- Facebook: finish belirsizliği ----------------

@pytest.fixture
def fb(monkeypatch, tmp_path):
    monkeypatch.setenv("META_SGB_PAGE_ID", "sayfa1")
    monkeypatch.setenv("META_SGB_PAGE_TOKEN", "sayfa-anahtari")
    for e in ("YT_CLIENT_ID", "TT_CLIENT_KEY", "YT_SGB_REFRESH_TOKEN", "TT_SGB_REFRESH_TOKEN"):
        monkeypatch.delenv(e, raising=False)
    monkeypatch.setattr(dagitim.time, "sleep", lambda s: None)
    durum = {"baslat": 0, "finish": None}

    def post(url, data=None, timeout=None, headers=None):
        if "rupload" in url:
            return Yanit({"success": True})
        if data["upload_phase"] == "start":
            durum["baslat"] += 1
            return Yanit({"video_id": "v1"})
        f = durum["finish"]
        if isinstance(f, Exception):
            raise f
        return f
    monkeypatch.setattr(dagitim.requests, "post", post)
    v = tmp_path / "v.mp4"
    v.write_bytes(b"x")
    durum["video"] = v
    return durum


def test_facebook_finish_zaman_asimi_yeniden_denenmez(fb):
    fb["finish"] = requests.Timeout("okuma zaman aşımı")
    s = dagitim.dagit("sgb", fb["video"], "Metin", [])
    assert s["facebook"].startswith("BELIRSIZ") and fb["baslat"] == 1
    # belirsiz platform sonraki dağıtımda (eksik) yeniden gönderilmez
    s2 = dagitim.dagit("sgb", fb["video"], "Metin", [], onceki=s)
    assert s2["facebook"] == s["facebook"] and fb["baslat"] == 1


def test_facebook_finish_basari_dogrulanir(fb):
    fb["finish"] = Yanit({"success": False})
    s = dagitim.dagit("sgb", fb["video"], "Metin", [])
    assert s["facebook"].startswith("HATA") and fb["baslat"] == 2, "kesin başarısızlık yeniden denenir"
    fb["finish"] = Yanit({"success": True})
    assert dagitim.dagit("sgb", fb["video"], "Metin", [])["facebook"] == "https://www.facebook.com/reel/v1"


def test_eksik_belirsiz_platformu_tekrar_gondermez(monkeypatch):
    monkeypatch.setattr(calistir, "bugun", lambda: BUGUN)
    monkeypatch.setattr(calistir, "gecmis", lambda kod: [{"tarih": BUGUN, "tur": "reels", "durum": "yayinlandi", "aciklama": "x",
                                                          "platformlar": {"instagram": "https://ig", "facebook": "BELIRSIZ: zaman aşımı"}}])
    monkeypatch.setattr(calistir.dagitim, "dagit", lambda *a, **k: pytest.fail("belirsiz platform yeniden gönderilmemeli"))
    calistir.eksik(["sgb"])
    monkeypatch.setattr(calistir, "gecmis", lambda kod: [{"tarih": BUGUN, "tur": "reels", "durum": "belirsiz", "aciklama": "x",
                                                          "platformlar": {"facebook": "HATA: 500"}}])
    calistir.eksik(["sgb"])  # Reels'i belirsiz kayıt hiç işlenmez


# ---------------- araştırma kotası ----------------

def test_arastirma_basarisizsa_24_saat_yeniden_denenmez(tmp_path, monkeypatch):
    monkeypatch.setattr(strateji, "DURUM", tmp_path)
    ortak.json_kaydet(tmp_path / "sgb" / "arastirma.json", {"tarih": "2026-11-10", "trendler": ["eski trend"]})
    cagri = []
    monkeypatch.setattr(strateji.llm, "ara", lambda istem: cagri.append(1) or None)
    m = ortak.marka("sgb")
    monkeypatch.setenv("OTOPILOT_SAAT", "2026-11-24T10:00")
    a = strateji.arastir("sgb", m)
    assert cagri == [1] and a["trendler"] == ["eski trend"] and a["durum"] == "basarisiz"
    kayit = strateji.arastirma("sgb")
    assert kayit["durum"] == "basarisiz" and kayit["tarih"] == "2026-11-10" and kayit["trendler"] == ["eski trend"]
    monkeypatch.setenv("OTOPILOT_SAAT", "2026-11-25T09:00")
    strateji.arastir("sgb", m)
    assert cagri == [1], "24 saat dolmadan yeniden denenmez"
    monkeypatch.setenv("OTOPILOT_SAAT", "2026-11-25T10:30")
    monkeypatch.setattr(strateji.llm, "ara", lambda istem: cagri.append(1) or {"metin": '{"trendler": ["yeni"]}', "kaynaklar": []})
    a = strateji.arastir("sgb", m)
    assert cagri == [1, 1] and a["trendler"] == ["yeni"] and a["durum"] == "basarili" and a["tarih"] == "2026-11-25"
    monkeypatch.setenv("OTOPILOT_SAAT", "2026-11-30T10:30")
    strateji.arastir("sgb", m)
    assert cagri == [1, 1], "başarıdan sonra 7 gün yenilenmez"


def test_gemini_429_yalniz_kota_alanlari_loglanir(monkeypatch, capsys):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setattr(llm, "_kesif", ["gemini-x-flash"])
    monkeypatch.setattr(llm, "_kota_doldu", set())
    monkeypatch.setattr(llm, "_sayac", {"istek": 0})
    govde = {"error": {"code": 429, "message": "GIZLI_GOVDE ayrıntısı", "details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "41s"}]}}
    monkeypatch.setattr(llm.requests, "post", lambda *a, **k: Yanit(govde, 429))
    assert llm.ara("istem") is None
    cikti = capsys.readouterr().out
    assert "HTTP 429" in cikti and "quotaId=GenerateRequestsPerDayPerProjectPerModel-FreeTier" in cikti and "retryDelay=41s" in cikti
    assert "GIZLI_GOVDE" not in cikti and "gemini-ara:gemini-x-flash" in llm._kota_doldu


# ---------------- nabız günü ----------------

def test_nabiz_varsayilan_gunu(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ortak, "DURUM", tmp_path)
    monkeypatch.setenv("OTOPILOT_SAAT", "2026-11-24T22:00")
    assert calistir.nabiz_tarihi() == "2026-11-24"
    monkeypatch.setenv("OTOPILOT_SAAT", "2026-11-25T00:40")  # gecikmeli 22:00 çalıştırması gece yarısını geçti
    assert calistir.nabiz_tarihi() == "2026-11-24"
    monkeypatch.setenv("OTOPILOT_SAAT", "2026-11-25T06:00")
    assert calistir.nabiz_tarihi() == "2026-11-25"
    for kod in ortak.marka_kodlari():
        ortak.gecmis_guncelle(kod, {"tarih": "2026-11-24", "tur": "reels", "durum": "yayinlandi", "anahtar": "a", "format": "f"})
    monkeypatch.setenv("OTOPILOT_SAAT", "2026-11-25T00:40")
    assert calistir.nabiz() == 0
    assert calistir.nabiz("2026-11-25") == 1
    assert calistir.main(["nabiz", "--tarih", "2026-11-24"]) == 0


# ---------------- log gizliliği ----------------

def test_panel_logu_yanit_govdesini_yazmaz(monkeypatch, capsys):
    monkeypatch.setattr(panel, "_belge", lambda: "jwt")
    monkeypatch.setattr(panel, "ozet", lambda: [])
    monkeypatch.setattr(panel, "ekler", lambda: {})
    y = Yanit({"istekler": [{"metin": "GIZLI_PANEL_ICERIGI"}, {"metin": "b"}], "tanitim": []})
    monkeypatch.setattr(panel.requests, "post", lambda *a, **k: y)
    assert panel.gonder(donus=True)["istekler"]
    panel.onay({"uygulanan": [1]})
    cikti = capsys.readouterr().out
    assert "GIZLI_PANEL_ICERIGI" not in cikti and "200" in cikti and "istekler=2" in cikti and "panel onay" in cikti


def test_kontrol_izin_listesi_ve_hedef_kimlikleri_yazilmaz(monkeypatch, capsys):
    monkeypatch.setenv("IG_TOKEN", "EAAtestanahtar")
    for kod in ortak.marka_kodlari():
        for e in (f"META_{kod.upper()}_PAGE_ID", f"IG_{kod.upper()}_ID", f"META_{kod.upper()}_IG_ID", f"IG_{kod.upper()}_TOKEN"):
            monkeypatch.delenv(e, raising=False)

    def get(url, params=None, timeout=None):
        if url.endswith("/debug_token"):
            return Yanit({"data": {"is_valid": True, "expires_at": 0, "scopes": ["instagram_basic", "pages_show_list"],
                                   "granular_scopes": [{"scope": "instagram_basic", "target_ids": ["998877665544"]}]}})
        return Yanit({"data": [{"permission": "instagram_basic", "status": "granted"}, {"permission": "ads_read", "status": "declined"}]})
    monkeypatch.setattr(requests, "get", get)
    calistir.kontrol()
    cikti = capsys.readouterr().out
    assert "998877665544" not in cikti and "instagram_basic" not in cikti and "ads_read" not in cikti
    assert "1 verildi, 1 verilmedi" in cikti and "1 hedef" in cikti


def test_gizle_yeni_anahtar_desenleri():
    metin = ("ig: IGAAKx1234567890abcdefghijKLMNOP_-x eski: IGQVJabcdefghijklmnopqrstuvwxyz12 "
             "google: 1//0gAbCdEfGhIjKlMnOpQrStUvWxYz-_12 sürüm v1//yol kalsın")
    g = ortak.gizle(metin)
    assert "IGAAKx" not in g and "IGQVJ" not in g and "1//0gAb" not in g
    assert g.count("***") == 3 and "v1//yol kalsın" in g
