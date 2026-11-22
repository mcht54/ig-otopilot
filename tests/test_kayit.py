"""Sanal saatli kayıt: ağsız, yerel sayfa ile uçtan uca (Chromium gerekir)."""
import subprocess

import pytest
from playwright.sync_api import sync_playwright

from otopilot.calistir import video_denetle
from otopilot.kayit import kaydet, yeni_sayfa

SAYFA = """<!doctype html><meta name=viewport content="width=device-width">
<style>body{margin:0;background:#123}#k{width:100px;height:100px;background:#f80;animation:a 1s linear both}
@keyframes a{from{transform:translateX(0)}to{transform:translateX(300px)}}</style>
<div id=k></div><p id=t style="color:#fff;font:40px sans-serif">0</p>
<script>let n=0;setInterval(()=>{document.getElementById('t').textContent=++n},100)</script>"""


@pytest.fixture(scope="module")
def tarayici():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


def test_sanal_saat_animasyon_ve_zamanlayici(tarayici, tmp_path):
    s = yeni_sayfa(tarayici)
    s.set_content(SAYFA)
    konumlar = []
    kaydet(s, tmp_path / "v.mp4", 1.0, fps=10, sifirdan=True,
           her_kare=lambda t: konumlar.append(s.evaluate("document.getElementById('t').textContent")))
    # 10 kare × 100 ms: setInterval tam olarak sanal saate göre işler (gerçek süreden bağımsız)
    assert s.evaluate("document.getElementById('t').textContent") == "9"
    x = s.evaluate("new DOMMatrix(getComputedStyle(document.getElementById('k')).transform).m41")
    assert 260 <= x <= 300
    c = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", str(tmp_path / "v.mp4")],
                       capture_output=True, text=True)
    assert c.stdout.strip() == "1080,1920"
    s.context.close()


def test_bos_kare_yakalanir(tarayici, tmp_path):
    s = yeni_sayfa(tarayici)
    s.set_content("<body style='margin:0;background:#fff'></body>")
    kaydet(s, tmp_path / "bos.mp4", 6, fps=5)
    assert any("boş kare" in h for h in video_denetle(tmp_path / "bos.mp4"))
    s.context.close()
