"""Senaryodaki sahneleri tek tek kaydedip geçişlerle Reels videosuna birleştirir.

Sahne türleri:
  kart     — kendi şablonumuz (sablon/kart.html): kapak, liste, izgara, urun, rakam, telefon, cta, hikaye
  sayfa    — gerçek bir web sayfası (url ya da yerel html) + isteğe bağlı eylemler, üst yazı, kaydırma
"""
from __future__ import annotations

import base64
import functools
import json
import random
import subprocess
from pathlib import Path

from .kayit import kaydet, tikla, yeni_sayfa
from .ortak import FONT, KOK, SABLON, log

GECIS = 0.35  # saniye, sahneler arası çapraz geçiş


@functools.cache
def _font_b64() -> str:
    return base64.b64encode((FONT / "Montserrat.ttf").read_bytes()).decode()


def _marka_js(marka: dict) -> dict:
    alan = ("ad", "site_kisa", "cta", "renk")
    m = {k: marka[k] for k in alan}
    m["logo_yol"] = Path(marka["logo_yol"]).as_uri()
    m["maskot_yol"] = Path(marka["maskot_yol"]).as_uri() if marka.get("maskot_yol") else ""
    return m


def kart_klip(tarayici, sahne: dict, marka: dict, cikti: Path) -> Path:
    sablon = (SABLON / "kart.html").read_text(encoding="utf-8")
    enjekte = f"<script>window.SAHNE={json.dumps(sahne, ensure_ascii=False)};window.MARKA={json.dumps(_marka_js(marka), ensure_ascii=False)};</script>"
    html = sablon.replace('<div id="kok"></div>', '<div id="kok"></div>' + enjekte)
    gecici = SABLON / f".sahne-{cikti.stem}.html"  # göreli font yolu için şablon klasöründe
    gecici.write_text(html, encoding="utf-8")
    sayfa = yeni_sayfa(tarayici)
    try:
        sayfa.goto(gecici.as_uri(), wait_until="load")
        sayfa.evaluate("document.fonts.ready")
        sayfa.wait_for_function("[...document.images].every(i => i.complete)", timeout=30000)
        return kaydet(sayfa, cikti, sahne.get("sure", 3), sifirdan=True)
    finally:
        sayfa.context.close()
        gecici.unlink(missing_ok=True)


UST_YAZI_JS = """
([metin, ana, font, konum]) => {
  if (!document.getElementById('__otf')) {
    try {  // CSP font-src'ye takılmamak için yazı tipini bellekten yükle
      const b = Uint8Array.from(atob(font), c => c.charCodeAt(0));
      const ff = new FontFace('OTM', b.buffer, { weight: '100 900' }); document.fonts.add(ff); ff.load();
    } catch (e) {}
    const st = document.createElement('style'); st.id = '__otf';
    st.textContent = `
    .__ust{position:fixed;left:18px;right:18px;z-index:2147483647;display:flex;justify-content:center;pointer-events:none}
    .__ust span{font-family:OTM,sans-serif;font-weight:800;font-size:19px;line-height:1.2;color:#fff;background:${ana};padding:10px 15px;border-radius:14px;
      box-shadow:0 10px 30px rgba(0,0,0,.35);text-align:center;text-wrap:balance;animation:__g .5s cubic-bezier(.2,.8,.2,1) both}
    @keyframes __g{from{opacity:0;transform:translateY(-14px) scale(.96)}to{opacity:1;transform:none}}`;
    document.head.appendChild(st);
  }
  document.querySelectorAll('.__ust').forEach(e => e.remove());
  if (!metin) return;
  const d = document.createElement('div'); d.className = '__ust';
  d.style[konum === 'alt' ? 'bottom' : 'top'] = konum === 'alt' ? '170px' : '92px';
  const s = document.createElement('span'); s.textContent = metin; d.appendChild(s);
  document.body.appendChild(d);
}
"""


def ust_yazi(sayfa, metin: str | None, marka: dict, konum: str = "ust") -> None:
    sayfa.evaluate(UST_YAZI_JS, [metin or "", marka["renk"]["ana"], _font_b64(), konum])


def _eylem(e: dict, marka: dict):
    """Senaryodaki eylem sözlüğünü sayfa fonksiyonuna çevirir."""
    if "tikla" in e:
        return lambda s: tikla(s, e["tikla"])
    if "odak" in e:
        return lambda s: s.get_by_label(e["odak"]).first.evaluate("el => { el.focus(); el.select && el.select(); }")
    if "tus" in e:
        return lambda s: s.keyboard.type(e["tus"])
    if "sil" in e:
        return lambda s: s.keyboard.press("Backspace")
    if "ust_yazi" in e:
        return lambda s: ust_yazi(s, e["ust_yazi"], marka, e.get("konum", "ust"))
    if "js" in e:
        return lambda s: s.evaluate(e["js"])
    raise ValueError(f"bilinmeyen eylem: {e}")


def yazma_eylemleri(baslangic: float, alan: str, metin: str, hiz: float = 0.07) -> list[dict]:
    """Bir form alanını temizleyip metni harf harf yazan eylem listesi."""
    ey = [{"t": baslangic, "odak": alan}, {"t": baslangic + 0.02, "js": "document.execCommand && document.execCommand('delete')"}]
    for i, h in enumerate(metin):
        ey.append({"t": baslangic + 0.1 + i * hiz, "tus": h})
    return ey


def sayfa_klip(tarayici, sahne: dict, marka: dict, cikti: Path) -> Path:
    sayfa = yeni_sayfa(tarayici)
    try:
        if sahne.get("html_yol"):
            sayfa.goto(Path(sahne["html_yol"]).as_uri(), wait_until="load")
        else:
            yanit = sayfa.goto(sahne["url"], wait_until="networkidle", timeout=60000)
            if yanit and yanit.status >= 400:
                raise RuntimeError(f"sayfa {yanit.status}: {sahne['url']}")
        for metin in sahne.get("once_tikla", []):
            tikla(sayfa, metin)
            sayfa.wait_for_timeout(400)
        for js in sahne.get("once_js", []):
            sayfa.evaluate(js)
        if sahne.get("kaydir"):
            sayfa.evaluate("document.documentElement.style.scrollBehavior='auto'; document.body.style.scrollBehavior='auto'")
            sayfa.wait_for_timeout(300)
        sayfa.wait_for_timeout(int(sahne.get("bekle", 0.6) * 1000))
        if sahne.get("ust_yazi"):
            ust_yazi(sayfa, sahne["ust_yazi"], marka, sahne.get("ust_konum", "ust"))
        eylemler = {}
        for i, e in enumerate(sahne.get("eylemler", [])):
            eylemler[e["t"] + i * 1e-6] = _eylem(e, marka)
        her_kare = None
        if sahne.get("kaydir"):
            sure = sahne["sure"]
            en_cok = sayfa.evaluate("document.documentElement.scrollHeight - innerHeight")
            hedef = min(en_cok * sahne.get("kaydir_oran", 0.7), sahne.get("kaydir_px", 2600))
            bas = sahne.get("kaydir_bas", 0.6)

            def her_kare(t, sayfa=sayfa):
                x = min(1, max(0, (t - bas) / max(0.1, sure - bas - 0.4)))
                y = hedef * (x * x * (3 - 2 * x))  # yumuşak başla/bitir
                sayfa.evaluate("y => window.scrollTo(0, y)", y)
        return kaydet(sayfa, cikti, sahne.get("sure", 4), eylemler=eylemler, her_kare=her_kare)
    finally:
        sayfa.context.close()


def _sure(yol: Path) -> float:
    c = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(yol)],
                       capture_output=True, text=True, check=True)
    return float(c.stdout.strip())


def muzik_sec(tohum: str) -> Path | None:
    parcalar = sorted((KOK / "muzik").glob("*.mp3")) if (KOK / "muzik").exists() else []
    if not parcalar:
        return None
    return random.Random(tohum).choice(parcalar)


def birlestir(klipler: list[Path], cikti: Path, muzik: Path | None = None, hazir_ses: Path | None = None) -> Path:
    sureler = [_sure(k) for k in klipler]
    girdiler = []
    for k in klipler:
        girdiler += ["-i", str(k)]
    filtre, onceki, ofset = [], "[0:v]", 0.0
    for i in range(1, len(klipler)):
        ofset += sureler[i - 1] - GECIS
        etiket = f"[v{i}]"
        filtre.append(f"{onceki}[{i}:v]xfade=transition=fade:duration={GECIS}:offset={ofset:.3f}{etiket}")
        onceki = etiket
    toplam = sum(sureler) - GECIS * (len(klipler) - 1)
    if not filtre:
        filtre.append("[0:v]null[v0]")
        onceki = "[v0]"
    si = len(klipler)
    if hazir_ses:  # seslendirme + müzik miksi hazır (ses.miks): seviyesine dokunulmaz
        ses_girdi = ["-i", str(hazir_ses)]
        filtre.append(f"[{si}:a]atrim=0:{toplam:.3f},afade=t=out:st={max(0, toplam - 0.6):.3f}:d=0.6[a]")
    else:
        ses_girdi = ["-i", str(muzik)] if muzik else ["-f", "lavfi", "-t", f"{toplam:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
        filtre.append(f"[{si}:a]atrim=0:{toplam:.3f},afade=t=in:d=0.4,afade=t=out:st={max(0, toplam - 1.2):.3f}:d=1.2,volume=0.6[a]")
    komut = ["ffmpeg", "-y", "-loglevel", "error", *girdiler, *ses_girdi,
             "-filter_complex", ";".join(filtre), "-map", onceki, "-map", "[a]",
             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-r", "30",
             "-profile:v", "high", "-level", "4.1", "-maxrate", "8M", "-bufsize", "16M",
             "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-t", f"{toplam:.3f}", "-movflags", "+faststart", str(cikti)]
    subprocess.run(komut, check=True)
    log(f"film: {cikti} {toplam:.1f}s")
    return cikti


def klip_uret(tarayici, sahne: dict, marka: dict, cikti: Path) -> Path:
    if sahne["tur"] == "kart":
        return kart_klip(tarayici, sahne, marka, cikti)
    return sayfa_klip(tarayici, sahne, marka, cikti)


SES_ONCE = 0.25   # sahne açıldıktan sonra konuşmanın başlama payı (sn)
SES_SONRA = 0.45  # konuşma bittikten sonra sahnenin kalma payı (sn)
EN_UZUN_SAHNE = 8.0


def film_yap(tarayici, sahneler: list[dict], marka: dict, klasor: Path, ad: str, tohum: str,
             anlatim: list[str] | None = None) -> tuple[Path, str]:
    """Videoyu üretir; (yol, ses_kaynagi) döner. Anlatım varsa sahne süreleri konuşmaya göre uzar ve her satır
    kendi sahnesinin başında başlar; her durumda fon müziği çalar (ses: gemini | edge | yok)."""
    from . import ses
    klasor.mkdir(parents=True, exist_ok=True)
    sahneler = [dict(s) for s in sahneler]
    parcalar, kaynak = (ses.seslendir(anlatim, marka) if anlatim else (None, "yok"))
    if parcalar:
        for sh, p in zip(sahneler, parcalar):
            gerek = SES_ONCE + len(p) / ses.SR + SES_SONRA + GECIS
            sh["sure"] = round(min(max(sh.get("sure", 3.0), gerek), EN_UZUN_SAHNE), 2)
    klipler = []
    for i, sahne in enumerate(sahneler):
        klipler.append(klip_uret(tarayici, sahne, marka, klasor / f"{ad}-s{i:02d}.mp4"))
    sureler = [_sure(k) for k in klipler]
    toplam = sum(sureler) - GECIS * (len(klipler) - 1)
    konusmalar, an = [], 0.0
    for i, d in enumerate(sureler):
        if parcalar:
            konusmalar.append((an + (0.12 if i == 0 else SES_ONCE), parcalar[i]))
        an += d - GECIS
    miks = ses.miks(toplam, konusmalar, marka, tohum, klasor / f"{ad}-ses.wav")
    son = birlestir(klipler, klasor / f"{ad}.mp4", hazir_ses=miks)
    for k in [*klipler, miks]:
        k.unlink(missing_ok=True)
    return son, kaynak


def kapak_kare(video: Path, cikti: Path, saniye: float = 1.2) -> Path:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{saniye}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(cikti)], check=True)
    return cikti
