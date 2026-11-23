import numpy as np

from otopilot import calistir, plan, ses


def test_ses_paketi_gidip_gelir(tmp_path, monkeypatch):
    parcalar = [np.random.default_rng(i).standard_normal(4410).astype(np.float32) * 0.1 for i in range(3)]
    oge = {"id": "2026-11-24-sgb", "anlatim": ["bir", "iki", "üç"]}
    f = tmp_path / "_indir" / f"{oge['id']}-ses.npz"
    f.parent.mkdir()
    np.savez_compressed(f, *parcalar)
    monkeypatch.setattr(plan, "indir", lambda ad, hedef: f if ad.endswith("-ses.npz") else None)
    assert plan.hazir_ses(oge, tmp_path / "k") is None  # imza yok → hazır sayılmaz
    oge["ses"] = plan.ses_imza(oge["anlatim"])
    geri = plan.hazir_ses(oge, tmp_path / "k")
    assert geri and all(np.array_equal(a, b) for a, b in zip(geri, parcalar))
    oge["anlatim"][1] = "değişti"  # panelden düzenlendi → eski ses kullanılmaz
    assert plan.hazir_ses(oge, tmp_path / "k") is None


def test_gunduz_ses_hazirlanmaz(monkeypatch):
    import datetime as dt
    monkeypatch.setattr(plan, "simdi", lambda: dt.datetime(2026, 11, 23, 14, 0))
    assert plan.ses_hazirla(["sgb"]) == 0


def test_uret_plan_modulunu_bulur():
    import inspect
    assert "from . import plan" in inspect.getsource(calistir.uret)


def test_son_sonus_yumusak(tmp_path):
    m = {"muzik": {"hava": "sakin"}}
    import wave
    out = ses.miks(6.0, [], m, "t", tmp_path / "m.wav")
    with wave.open(str(out)) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2)[:, 0].astype(float)
    n = int(6.0 * ses.SR)
    pen = lambda t: np.sqrt(np.mean(a[int(t * ses.SR):int((t + 0.2) * ses.SR)] ** 2))
    assert pen(5.0) < pen(4.0) and pen(5.6) < pen(5.0) and pen(5.8) < 0.1 * pen(4.0)
