"""Sitelerden canlı veri okuma yardımcıları (yalnız herkese açık sayfalar/API'ler)."""
from __future__ import annotations

import html as _html
import re
from html.parser import HTMLParser
from pathlib import Path

import requests

from ..kayit import VIEWPORT, tikla, yeni_sayfa
from ..ortak import UA

_oturum = requests.Session()
_oturum.headers.update({"User-Agent": UA, "Accept-Language": "tr-TR,tr;q=0.9"})


def getir(url: str, **kw) -> requests.Response:
    r = _oturum.get(url, timeout=30, **kw)
    r.raise_for_status()
    return r


def temiz(s: str) -> str:
    s = _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()


class _Makale(HTMLParser):
    """h1/h2/h3/p/li metinlerini sırasıyla toplar; nav/footer/script atlanır."""

    ATLA = {"script", "style", "nav", "footer", "noscript", "svg", "form"}

    def __init__(self):
        super().__init__()
        self.bloklar: list[tuple[str, str]] = []
        self._yigin: list[str] = []
        self._atla = 0
        self._tampon: list[str] = []
        self._etiket = None

    def handle_starttag(self, tag, attrs):
        if tag in self.ATLA:
            self._atla += 1
        if self._atla:
            return
        if tag in ("h1", "h2", "h3", "p", "li"):
            self._etiket, self._tampon = tag, []

    def handle_endtag(self, tag):
        if tag in self.ATLA and self._atla:
            self._atla -= 1
            return
        if self._atla:
            return
        if tag == self._etiket:
            metin = re.sub(r"\s+", " ", "".join(self._tampon)).strip()
            if metin:
                self.bloklar.append((tag, metin))
            self._etiket = None

    def handle_data(self, data):
        if self._etiket and not self._atla:
            self._tampon.append(data)


def makale(url: str) -> dict:
    """Sayfanın başlık, alt başlık ve paragraflarını döndürür."""
    t = getir(url).text
    ana = re.search(r"<main.*?</main>", t, re.S)
    p = _Makale()
    p.feed(ana.group(0) if ana else t)
    og = re.search(r'property="og:image" content="([^"]+)"', t)
    aciklama = re.search(r'name="description" content="([^"]+)"', t)
    baslik = next((m for e, m in p.bloklar if e == "h1"), "")
    if not baslik:
        ogt = re.search(r'property="og:title" content="([^"]+)"', t)
        baslik = re.split(r"\s[|–-]\s", ogt.group(1))[0] if ogt else ""
    bolumler, simdiki = [], None
    for e, m in p.bloklar:
        if e in ("h2", "h3"):
            simdiki = {"baslik": m, "metin": []}
            bolumler.append(simdiki)
        elif simdiki is not None and e in ("p", "li") and len(simdiki["metin"]) < 4:
            simdiki["metin"].append(m)
    # makale gövdesi "Kaynaklar"/"Diğer yazılar" gibi yan bloklarda biter
    for i, b in enumerate(bolumler):
        if re.match(r"(kaynaklar|diğer rehber|ilgili yazı|benzer yazı)", b["baslik"], re.I):
            bolumler = bolumler[:i]
            break
    return {
        "url": url,
        "baslik": _html.unescape(baslik),
        "aciklama": _html.unescape(aciklama.group(1)) if aciklama else "",
        "gorsel": og.group(1) if og else None,
        "bolumler": bolumler,
        "duz_metin": " ".join(m for _, m in p.bloklar)[:6000],
    }


def sitemap(url: str) -> list[str]:
    return re.findall(r"<loc>([^<]+)</loc>", getir(url).text)


def ekran_goruntusu(tarayici, url: str, yol: Path, tam: bool = False, yukseklik: int | None = None,
                    once_tikla: list[str] | None = None, js: str | None = None, viewport: dict | None = None) -> Path:
    """Telefon görünümünde ekran görüntüsü (1080 piksel genişlik)."""
    yol.parent.mkdir(parents=True, exist_ok=True)
    sayfa = yeni_sayfa(tarayici, viewport or VIEWPORT)
    try:
        if url.startswith("file:") or url.startswith("http"):
            sayfa.goto(url, wait_until="networkidle", timeout=60000)
        for m in once_tikla or []:
            tikla(sayfa, m)
            sayfa.wait_for_timeout(400)
        if js:
            sayfa.evaluate(js)
        sayfa.wait_for_timeout(800)
        if tam or yukseklik:
            # tembel yüklenen görselleri tetiklemek için sayfayı gez
            sayfa.evaluate("""async () => { for (let y = 0; y < document.body.scrollHeight; y += 500) { scrollTo(0, y); await new Promise(r => setTimeout(r, 60)); } scrollTo(0, 0); }""")
            sayfa.wait_for_timeout(800)
        if yukseklik:
            sayfa.screenshot(path=str(yol), clip={"x": 0, "y": 0, "width": sayfa.viewport_size["width"], "height": yukseklik}, full_page=True)
        else:
            sayfa.screenshot(path=str(yol), full_page=tam)
        return yol
    finally:
        sayfa.context.close()
