"""Sanal saatli sayfa kaydedici.

Sayfanın zamanını (setTimeout, requestAnimationFrame, Date, performance.now ve CSS/WAAPI
animasyonları) biz ilerletiriz; her karede ekran görüntüsü alınıp ffmpeg'e borulanır.
Böylece yavaş bir makinede (GitHub Actions) bile akıcı, takılmasız 30 kare/sn video çıkar.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from .ortak import log

GENISLIK, YUKSEKLIK = 1080, 1920
VIEWPORT = {"width": 405, "height": 720}
OLCEK = GENISLIK / VIEWPORT["width"]  # 2.666…

SANAL_SAAT_JS = r"""
(() => {
  if (window.__ss) return;
  const gercekNow = performance.now.bind(performance);
  const t0Gercek = gercekNow(), d0 = Date.now();
  const S = window.__ss = { t: 0, sira: 1, zam: new Map(), raf: new Map(), dogum: new WeakMap(), canli: true };
  const _raf = window.requestAnimationFrame.bind(window);
  window.setTimeout = (fn, ms = 0, ...a) => { const id = S.sira++; S.zam.set(id, { fn, a, at: S.t + Math.max(0, +ms || 0), aralik: 0 }); return id; };
  window.setInterval = (fn, ms = 0, ...a) => { const id = S.sira++; const m = Math.max(10, +ms || 0); S.zam.set(id, { fn, a, at: S.t + m, aralik: m }); return id; };
  window.clearTimeout = window.clearInterval = (id) => { S.zam.delete(id); };
  window.requestAnimationFrame = (fn) => { const id = S.sira++; S.raf.set(id, fn); return id; };
  window.cancelAnimationFrame = (id) => { S.raf.delete(id); };
  performance.now = () => S.t;
  const _Date = Date;
  function SDate(...a) { if (!(this instanceof SDate)) return new _Date(d0 + S.t).toString(); return a.length ? new _Date(...a) : new _Date(d0 + S.t); }
  SDate.prototype = _Date.prototype; SDate.now = () => d0 + S.t; SDate.parse = _Date.parse; SDate.UTC = _Date.UTC;
  window.Date = SDate;
  S.ilerle = (ms) => {
    const hedef = S.t + ms;
    for (let guvenlik = 0; guvenlik < 5000; guvenlik++) {
      let enYakin = null;
      for (const [id, z] of S.zam) if (z.at <= hedef && (!enYakin || z.at < enYakin[1].at)) enYakin = [id, z];
      if (!enYakin) break;
      const [id, z] = enYakin;
      S.t = Math.max(S.t, z.at);
      if (z.aralik) z.at += z.aralik; else S.zam.delete(id);
      try { typeof z.fn === "function" ? z.fn(...z.a) : eval(z.fn); } catch (e) { console.error(e); }
    }
    S.t = hedef;
    const r = [...S.raf]; S.raf.clear();
    for (const [, fn] of r) { try { fn(S.t); } catch (e) { console.error(e); } }
    if (S.canli) return;  // canlı modda animasyonlar tarayıcının kendi saatinde akar
    for (const an of document.getAnimations()) {
      if (!S.dogum.has(an)) {
        // Sanal saatten önce başlamış animasyonun geçen süresini koru
        const gecen = S.sifirdan ? 0 : (an.currentTime || 0);
        S.dogum.set(an, S.t - gecen);
      }
      try { an.pause(); an.currentTime = Math.max(0, S.t - S.dogum.get(an)); } catch (e) {}
    }
    for (const v of document.querySelectorAll("video")) { try { v.pause(); v.currentTime = S.t / 1000 % (v.duration || 1e9); } catch (e) {} }
  };
  // Kayıt başlayana kadar sanal saat gerçek zamanı izler (sayfa normal yüklensin)
  const pompa = () => { if (!S.canli) return; S.ilerle(Math.max(0, gercekNow() - t0Gercek - S.t)); _raf(pompa); };
  _raf(pompa);
})();
"""


def ffmpeg_yazici(cikti: Path, fps: int = 30) -> subprocess.Popen:
    cikti.parent.mkdir(parents=True, exist_ok=True)
    komut = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
        "-vf", f"scale={GENISLIK}:{YUKSEKLIK}:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(fps),
        "-movflags", "+faststart", str(cikti),
    ]
    return subprocess.Popen(komut, stdin=subprocess.PIPE)


def kaydet(
    sayfa,
    cikti: Path,
    sure: float,
    fps: int = 30,
    eylemler: dict[float, Callable] | None = None,
    her_kare: Callable[[float], None] | None = None,
    sifirdan: bool = False,
) -> Path:
    """Sayfanın şu anki hâlinden itibaren `sure` saniyelik video kaydeder.

    eylemler: {saniye: fonksiyon(sayfa)} — o anda tıklama/yazma gibi işlemler.
    her_kare: fonksiyon(saniye) — her kareden önce (örn. kaydırma konumu) çağrılır.
    """
    sayfa.evaluate(SANAL_SAAT_JS)  # init script yoksa (eski sayfa) şimdi kur
    sayfa.evaluate("v => { window.__ss.sifirdan = v; window.__ss.canli = false; }", sifirdan)
    bekleyen = sorted((eylemler or {}).items())
    kare_ms = 1000 / fps
    toplam = int(round(sure * fps))
    yazici = ffmpeg_yazici(cikti, fps)
    try:
        for i in range(toplam):
            t = i / fps
            while bekleyen and bekleyen[0][0] <= t:
                _, f = bekleyen.pop(0)
                f(sayfa)
            if her_kare:
                her_kare(t)
            sayfa.evaluate("ms => window.__ss.ilerle(ms)", kare_ms if i else 0)
            yazici.stdin.write(sayfa.screenshot(type="jpeg", quality=92, animations="allow", caret="hide"))
    finally:
        yazici.stdin.close()
        yazici.wait()
    if yazici.returncode:
        raise RuntimeError(f"ffmpeg kayıt hatası: {cikti}")
    log(f"kayıt: {cikti.name} {sure:.1f}s")
    return cikti


def yeni_sayfa(tarayici, viewport: dict | None = None):
    baglam = tarayici.new_context(
        viewport=viewport or VIEWPORT,
        device_scale_factor=OLCEK,
        locale="tr-TR",
        timezone_id="Europe/Istanbul",
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
        is_mobile=True,
        has_touch=True,
    )
    baglam.add_init_script(SANAL_SAAT_JS)
    return baglam.new_page()


def tikla(sayfa, metin: str, secici: str = "button, a, [role=button]") -> bool:
    """Görünür ögeyi metnine göre (büyük/küçük harf duyarsız) JS ile tıklar."""
    return sayfa.evaluate(
        """([metin, secici]) => {
          const k = s => (s || '').toLocaleLowerCase('tr').replace(/\\s+/g, ' ').trim();
          const el = [...document.querySelectorAll(secici)].find(e => k(e.innerText || e.getAttribute('aria-label')).includes(k(metin)) && e.offsetParent !== null);
          if (!el) return false; el.click(); return true;
        }""",
        [metin, secici],
    )
