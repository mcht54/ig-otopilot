import numpy as np

from otopilot import ses

SR = ses.SR


def _konusma(sn, f0=180.0, tohum=0):
    """Konuşmaya benzer: düşük frekanslı harmonikler, hece zarfı."""
    t = np.arange(int(sn * SR)) / SR
    x = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 8))
    return (x * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t) ** 2) * 0.3).astype(np.float32)


def _tislama(sn, tohum=1):
    n = np.random.default_rng(tohum).standard_normal(int(sn * SR) + 2)
    return (np.diff(np.diff(n)) * 0.5).astype(np.float32)


def _bos(sn):
    return np.zeros(int(sn * SR), np.float32)


def test_sondaki_parazit_atilir():
    k = _konusma(2.0)
    x = np.concatenate([k, _bos(0.15), _tislama(0.2)])
    y = ses.parazit_temizle(x)
    assert len(y) < len(k) + int(0.1 * SR)
    assert ses._merkez(y[-int(0.1 * SR):]) < ses.PARAZIT_HZ


def test_bastaki_parazit_atilir():
    x = np.concatenate([_tislama(0.15), _bos(0.1), _konusma(1.5)])
    y = ses.parazit_temizle(x)
    assert len(y) < int(1.5 * SR) + int(0.1 * SR)


def test_konusma_ve_uzun_ses_korunur():
    x = np.concatenate([_konusma(1.0), _bos(0.2), _konusma(1.0, 220)])
    assert len(ses.parazit_temizle(x)) >= int(2.1 * SR)
    # uzun (0,4 sn üstü) yüksek frekanslı bölüm parazit sayılmaz
    x2 = np.concatenate([_konusma(1.0), _bos(0.2), _tislama(0.6)])
    assert len(ses.parazit_temizle(x2)) >= int(1.7 * SR)


def test_bol_parcalarda_parazit_kalmaz():
    x = np.concatenate([_konusma(1.2), _bos(0.4), _konusma(1.2, 220), _bos(0.15), _tislama(0.2)])
    p = ses.bol(x, 2, ["birinci satır burada", "ikinci satır burada"])
    assert len(p) == 2 and ses._merkez(p[1][-int(0.1 * SR):]) < ses.PARAZIT_HZ


def test_kural_sayfa_satiri_numara_okumaz_tekrar_etmez():
    m = {"cta": "Hemen deneyin", "site_kisa": "x.com", "ad": "X"}
    sen = {"sahneler": [{"tip": "kapak", "baslik": "Başlık"},
                        {"tur": "sayfa", "eylemler": [{"ust_yazi": "1. Tasarımınızı seçin"}]},
                        {"tur": "sayfa", "ust_yazi": "2. Bilgilerinizi yazın"}]}
    a = ses.kural_anlatim(sen, m)
    assert "bir." not in a[1].lower() and "Tasarımınızı seçin" in a[1]
    assert "bakalım" not in a[2] and "iki" not in a[2].lower()
