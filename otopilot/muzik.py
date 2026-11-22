"""Telifsiz fon müziği: tamamen kodla sentezlenir (lisans/indirme yok, her gün tohumla farklı varyasyon).
Marka havası `markalar/<kod>.yaml` → `muzik: {tempo, ton, hava}`. Çıktı: 44,1 kHz stereo float32 dizi.

hava: "enerjik" (dört vuruş, parlak arpej), "sicak" (yumuşak davul, piyano benzeri tını), "sakin" (hafif ritim, geniş pad).
Kendi parçanızı kullanmak isterseniz `muzik/<marka>/*.mp3` (ya da `muzik/*.mp3`) koyun; sentez yerine o çalınır.
"""
from __future__ import annotations

import hashlib

import numpy as np

SR = 44100
NOTALAR = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
# Pop akor dizileri (majör ton derecesi: kök yarım ses ofseti, minör mü)
DIZILER = [
    [(0, False), (7, False), (9, True), (5, False)],   # I  V  vi IV
    [(9, True), (5, False), (0, False), (7, False)],   # vi IV I  V
    [(0, False), (9, True), (5, False), (7, False)],   # I  vi IV V
    [(5, False), (0, False), (7, False), (9, True)],   # IV I  V  vi
]


def _hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def _t(d: float) -> np.ndarray:
    return np.arange(int(d * SR)) / SR


def _lp(x: np.ndarray, w: int) -> np.ndarray:
    return np.convolve(x, np.ones(w) / w, mode="same") if w > 1 else x


def _yerlestir(buf: np.ndarray, sig: np.ndarray, an: float, pan: float = 0.0) -> None:
    i = int(an * SR)
    if i >= len(buf):
        return
    sig = sig[: len(buf) - i]
    sol, sag = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:i + len(sig), 0] += sig * sol * 1.414
    buf[i:i + len(sig), 1] += sig * sag * 1.414


def _testere(f: float, d: float, harmonik: int = 18) -> np.ndarray:
    t = _t(d)
    s = np.zeros_like(t)
    for n in range(1, harmonik + 1):
        if f * n > 12000:
            break
        s += np.sin(2 * np.pi * f * n * t) / n
    return s


def _zarf(n: int, a: float, r: float) -> np.ndarray:
    e = np.ones(n)
    na, nr = min(int(a * SR), n), min(int(r * SR), n)
    if na:
        e[:na] = np.linspace(0, 1, na)
    if nr:
        e[-nr:] *= np.linspace(1, 0, nr)
    return e


def _kick(rnd) -> np.ndarray:
    t = _t(0.35)
    f = 48 + 110 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def _clap(rnd) -> np.ndarray:
    t = _t(0.22)
    n = np.diff(rnd.standard_normal(len(t) + 1)) * 0.35
    return n * (np.exp(-t * 24) + 0.6 * np.exp(-np.maximum(t - 0.012, 0) * 200) * (t >= 0.012))


def _hat(rnd, uzun: bool = False) -> np.ndarray:
    t = _t(0.18 if uzun else 0.05)
    n = np.diff(np.diff(rnd.standard_normal(len(t) + 2)))
    return n * np.exp(-t * (18 if uzun else 90)) * 0.18


def _pluck(f: float, d: float, parlak: float) -> np.ndarray:
    t = _t(d)
    s = sum(np.sin(2 * np.pi * f * k * t) * np.exp(-t * (3 + k * (6 - 4 * parlak))) / k for k in range(1, 7))
    return s * _zarf(len(t), 0.003, 0.05)


def uret(sure: float, marka: dict, tohum: str) -> np.ndarray:
    ayar = marka.get("muzik") or {}
    hava = ayar.get("hava", "enerjik")
    rnd = np.random.default_rng(int(hashlib.sha256(tohum.encode()).hexdigest()[:8], 16))  # tekrarlanabilir
    tempo = float(ayar.get("tempo", 118)) + rnd.integers(-3, 4)
    vurus = 60 / tempo
    olcu = vurus * 4
    kok = 48 + NOTALAR.get(str(ayar.get("ton", "C")), 0)  # C3 tabanı
    dizi = DIZILER[int(rnd.integers(len(DIZILER)))]
    toplam = sure + 1.0
    buf = np.zeros((int(toplam * SR), 2))

    olcu_sayisi = int(np.ceil(toplam / olcu))
    for o in range(olcu_sayisi):
        bas = o * olcu
        ofset, minor = dizi[o % len(dizi)]
        akor = [kok + ofset, kok + ofset + (3 if minor else 4), kok + ofset + 7]
        # pad: geniş, yumuşak (iki sese hafif detune)
        pad_d = olcu + 0.25
        pad = sum(_testere(_hz(n + 12), pad_d) + _testere(_hz(n + 12) * 1.004, pad_d) for n in akor)
        pad = _lp(pad, 28 if hava != "enerjik" else 16) * _zarf(len(pad), 0.35 if hava == "sakin" else 0.08, 0.3) * 0.035
        _yerlestir(buf, pad, bas, -0.2)
        _yerlestir(buf, pad * 0.9, bas + 0.012, 0.2)
        # bas: sekizlik (enerjik) ya da dörtlük
        adim = vurus / 2 if hava == "enerjik" else vurus
        for k in range(int(olcu / adim)):
            f = _hz(akor[0] - 12)
            d = adim * 0.9
            b = _testere(f, d, 6) * _zarf(int(d * SR), 0.005, 0.06) * (0.10 if hava == "enerjik" else 0.08)
            _yerlestir(buf, _lp(b, 6), bas + k * adim)
        # arpej / piyano benzeri melodi
        parlak = 0.9 if hava == "enerjik" else 0.4
        arp_adim = vurus / (4 if hava == "enerjik" else 2)
        notalar = akor + [akor[0] + 12]
        for k in range(int(olcu / arp_adim)):
            if hava == "sakin" and k % 2:
                continue
            n = notalar[int(rnd.integers(len(notalar)))] + 24
            _yerlestir(buf, _pluck(_hz(n), 0.45, parlak) * 0.045, bas + k * arp_adim, float(rnd.uniform(-0.5, 0.5)))
        # davul
        for v in range(4):
            an = bas + v * vurus
            if hava == "enerjik" or v in (0, 2):
                _yerlestir(buf, _kick(rnd) * (0.32 if hava == "enerjik" else 0.22), an)
            if v in (1, 3) and hava != "sakin":
                _yerlestir(buf, _clap(rnd) * (0.16 if hava == "enerjik" else 0.10), an, 0.1)
            for yarim in (0, 0.5):
                if hava == "sakin" and yarim:
                    continue
                _yerlestir(buf, _hat(rnd, uzun=(yarim == 0.5 and hava == "enerjik")), an + yarim * vurus, -0.3)

    buf = buf[: int(sure * SR)]
    # yumuşak giriş/çıkış + tepe normalizasyonu
    n = len(buf)
    zarf = np.ones(n)
    gi, ci = min(int(0.6 * SR), n), min(int(1.5 * SR), n)
    zarf[:gi] = np.linspace(0, 1, gi)
    zarf[-ci:] *= np.linspace(1, 0, ci)
    buf *= zarf[:, None]
    tepe = np.max(np.abs(buf)) or 1.0
    return (buf / tepe * 0.8).astype(np.float32)
