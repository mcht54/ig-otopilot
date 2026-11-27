"""Panel "hesap başına platform ayarları": kapalı platform atlanır, kayda "atlandı: panelde kapalı" yazılır, eksik/Düzelt
yeniden denemez; alan/hesap/platform yoksa açık; panel ulaşılamazsa son bilinen ayar. Gerçek paylaşım/istek yok."""
import json

import pytest

from otopilot import calistir, dagitim, ortak, panel, platform_ayar
from test_guvenilirlik import BUGUN, Yanit, _kayit, ortam  # noqa: F401  (ortam: sahte Instagram + sahte dağıtım)

NOT = platform_ayar.NOT


@pytest.fixture
def durum(tmp_path, monkeypatch):
    monkeypatch.setattr(ortak, "DURUM", tmp_path)
    return tmp_path


def _ayar(hesaplar):
    platform_ayar.kaydet({"platform_ayarlari": {"hesaplar": hesaplar}})


def test_varsayilan_acik(durum):
    assert platform_ayar.acik("sgb", "facebook")  # dosya yok
    platform_ayar.kaydet({"bolumler": 3})  # panelin eski sürümü: alan yok → önbelleğe dokunulmaz
    assert not platform_ayar.dosya().exists()
    _ayar({"sgb": {"facebook": False, "youtube": True, "tiktok": "false"}})
    assert not platform_ayar.acik("sgb", "facebook")
    assert platform_ayar.acik("sgb", "youtube") and platform_ayar.acik("sgb", "tiktok"), "yalnız gerçek false kapalı"
    assert platform_ayar.acik("sgb", "instagram") and platform_ayar.acik("davetiyeler", "facebook")
    platform_ayar.dosya().write_text("{bozuk", encoding="utf-8")
    assert platform_ayar.acik("sgb", "facebook"), "bozuk önbellek → hepsi açık"


def test_instagram_kapaliysa_hikaye_de_kapali(durum):
    _ayar({"sgb": {"instagram": False, "instagram_hikaye": True}})
    assert not platform_ayar.acik("sgb", "instagram_hikaye")


def test_panel_yaniti_onbellege_yazilir_ulasilamazsa_son_ayar_kalir(durum, monkeypatch):
    monkeypatch.setattr(panel, "_belge", lambda: "belge")
    monkeypatch.setattr(panel, "ozet", lambda: [])
    monkeypatch.setattr(panel, "ekler", lambda: {})
    monkeypatch.setattr(panel.requests, "post", lambda *a, **k: Yanit({"platform_ayarlari": {"hesaplar": {"sgb": {"youtube": False}}}}))
    panel.gonder()
    assert json.loads(platform_ayar.dosya().read_text())["hesaplar"] == {"sgb": {"youtube": False}}

    def dusuk(*a, **k):
        raise ConnectionError("panel kapalı")
    monkeypatch.setattr(panel.requests, "post", dusuk)
    assert panel.gonder(donus=True) == {}
    assert not platform_ayar.acik("sgb", "youtube"), "panel ulaşılamazsa son bilinen ayar"


def test_dagit_kapali_platformu_atlar(durum, monkeypatch):
    _ayar({"sgb": {"facebook": False, "tiktok": False}})
    gonderilen = []
    monkeypatch.setattr(dagitim, "PLATFORMLAR", {p: (lambda k: True, lambda k, v, a, e, p=p: gonderilen.append(p) or f"https://{p}/1")
                                                 for p in ("facebook", "youtube", "tiktok")})
    s = dagitim.dagit("sgb", None, "metin", [])
    assert gonderilen == ["youtube"]
    assert s == {"facebook": NOT, "youtube": "https://youtube/1", "tiktok": NOT}


def _fb_anahtari(monkeypatch):
    monkeypatch.setenv("META_SGB_PAGE_ID", "1")
    monkeypatch.setenv("IG_TOKEN", "t")


def test_instagram_kapali_reels_ve_hikaye_atlanir_digerleri_gider(ortam, monkeypatch):
    _fb_anahtari(monkeypatch)
    _ayar({"sgb": {"instagram": False}})
    k = calistir.gunluk("sgb")
    assert ortam.yayin == {"REELS": [], "STORIES": []}, "Instagram'a hiçbir şey gitmez"
    assert ortam.dagit == ["sgb"]
    assert k["platformlar"]["instagram"] == NOT and k["platformlar"]["instagram_hikaye"] == NOT
    assert k["durum"] == "yayinlandi" and _kayit()["durum"] == "yayinlandi"
    calistir.gunluk("sgb")
    assert ortam.dagit == ["sgb"] and ortam.uretim == ["sgb"], "ikinci koşu yeniden paylaşmaz"


def test_yalniz_hikaye_kapali(ortam):
    _ayar({"sgb": {"instagram_hikaye": False}})
    k = calistir.gunluk("sgb")
    assert ortam.yayin == {"REELS": [1], "STORIES": []}
    assert k["platformlar"]["instagram"].startswith("https://") and k["platformlar"]["instagram_hikaye"] == NOT


def test_instagram_kapali_diger_platform_belirsizse_yeniden_paylasilmaz(ortam, monkeypatch):
    _fb_anahtari(monkeypatch)
    _ayar({"sgb": {"instagram": False}})
    monkeypatch.setattr(calistir.dagitim, "dagit", lambda *a, **k: ortam.dagit.append("sgb") or {"facebook": "BELIRSIZ: zaman aşımı"})
    assert calistir.gunluk("sgb")["durum"] == "belirsiz"
    calistir.gunluk("sgb")
    assert ortam.dagit == ["sgb"] and ortam.uretim == ["sgb"]


def test_tum_platformlar_kapaliysa_uretilmez_kayit_yazilmaz(ortam, monkeypatch, capsys):
    _ayar({"sgb": {p: False for p in ("instagram", "facebook", "facebook_hikaye", "youtube", "tiktok")}})
    k = calistir.gunluk("sgb")
    assert k["atlandi"] and ortam.uretim == [] and ortam.dagit == [] and ortam.yayin["REELS"] == []
    assert not any(x.get("tarih") == BUGUN for x in ortak.gecmis("sgb"))
    assert calistir.main(["otomatik", "--marka", "sgb"]) == 0, "atlanan hesap hata sayılmaz"
    # nabız: anahtarı olan hesap bilerek kapatıldıysa "hiç üretim yapılmadı" alarmı yok
    capsys.readouterr()
    calistir.nabiz(BUGUN)
    cikti = capsys.readouterr().out
    assert ortak.marka("sgb")["ad"] not in cikti and ortak.marka("davetiyeler")["ad"] in cikti, \
        "kapatılan hesap alarm vermez; anahtarı hiç olmayan hesap eskisi gibi alarm verir"


def test_eksik_panelde_kapaliyi_yeniden_denemez(durum, monkeypatch):
    _ayar({"sgb": {"instagram_hikaye": False, "instagram": True}})
    monkeypatch.setattr(calistir, "bugun", lambda: BUGUN)
    kayit = {"tarih": BUGUN, "tur": "reels", "durum": "yayinlandi", "aciklama": "x", "video_yedek": "v.mp4",
             "platformlar": {"instagram": "https://ig", "instagram_hikaye": NOT, "facebook": NOT, "facebook_hikaye": NOT,
                             "youtube": NOT, "tiktok": NOT}}
    monkeypatch.setattr(calistir, "gecmis", lambda kod: [kayit])
    monkeypatch.setattr(calistir.dagitim, "dagit", lambda *a, **k: pytest.fail("panelde kapalı platform yeniden gönderilmemeli"))
    monkeypatch.setattr(calistir, "_ig_tamamla", lambda *a, **k: pytest.fail("kapalı hikâye yeniden denenmemeli"))
    from otopilot import plan
    monkeypatch.setattr(plan, "indir", lambda *a, **k: pytest.fail("iş yoksa video indirilmez"))
    calistir.eksik(["sgb"])
    # Instagram Reels HATA ama panelde artık kapalı → Instagram yeniden denenmez
    _ayar({"sgb": {"instagram": False}})
    kayit["platformlar"]["instagram"] = "HATA: 500"
    calistir.eksik(["sgb"])
