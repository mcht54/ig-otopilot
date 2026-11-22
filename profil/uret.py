"""Sayfa/kanal profil ve kapak görselleri: python profil/uret.py"""
import sys; sys.path.insert(0, ".")
from pathlib import Path
from playwright.sync_api import sync_playwright
from otopilot.ortak import marka, marka_kodlari, FONT
SLOGAN = {"sitemucidi": "3 dakikada web siteniz hazır", "davetiyeler": "Düğün · Nişan · Kına · Sünnet davetiyeleri",
          "sgb": "Yalnız Bakanlık belgeli bungalovlar", "markakarnem": "İşletmenizin ücretsiz dijital karnesi"}
O = Path("profil").resolve()
MASKOT = "/Users/mucahit/Documents/markakarnem/apps/karne/public/maskot/"

def maskotlar(kod, olc):
    if kod != "markakarnem":
        return ""
    return "<div style='display:flex;align-items:flex-end;gap:0'>" + "".join(
        f"<img src='{Path(MASKOT + a).as_uri()}' style='height:{int(h*olc)}px;margin-left:-{int(30*olc)}px'>"
        for a, h in (("inceliyor.webp", 250), ("kutluyor.webp", 310), ("sunuyor.webp", 250))) + "</div>"


def ac(s, html):
    t = O / ".gecici.html"; t.write_text("<meta charset=utf-8>" + html, encoding="utf-8"); s.goto(t.as_uri())
with sync_playwright() as p:
    b = p.chromium.launch()
    for kod in marka_kodlari():
        m = marka(kod); r = m["renk"]; logo = Path(m["logo_yol"]).as_uri(); font = (FONT / "Montserrat.ttf").as_uri()
        css = f"@font-face{{font-family:M;src:url('{font}')}}*{{margin:0}}body{{font-family:M;}}"
        s = b.new_page(viewport={"width": 1024, "height": 1024})
        ac(s, f"<style>{css}body{{width:1024px;height:1024px;display:grid;place-items:center;background:#fff}}img{{width:78%;height:78%;object-fit:contain}}</style><img src='{logo}'>")
        s.wait_for_timeout(400); s.screenshot(path=str(O / f"{kod}-profil.png"))
        for ad, w, h in (("kapak-fb", 1640, 856), ("kapak-yt", 2560, 1440)):
            s.set_viewport_size({"width": w, "height": h})
            olc = w / 1640
            ac(s, f"""<style>{css}body{{width:{w}px;height:{h}px;background:radial-gradient(120% 90% at 85% 0%,{r['ana']} 0%,transparent 60%),{r['koyu']};
              color:#fff;display:flex;align-items:center;justify-content:center;gap:{60*olc}px}}
              .l{{background:#fff;border-radius:{40*olc}px;padding:{28*olc}px;box-shadow:0 20px 60px rgba(0,0,0,.35)}}.l img{{height:{170*olc}px;max-width:{420*olc}px;object-fit:contain;display:block}}
              h1{{font-size:{92*olc}px;font-weight:900;letter-spacing:-.02em}}p{{font-size:{44*olc}px;font-weight:600;opacity:.9;margin-top:{12*olc}px}}
              .u{{display:inline-block;margin-top:{28*olc}px;background:#fff;color:{r['koyu']};font-weight:800;font-size:{36*olc}px;padding:{14*olc}px {28*olc}px;border-radius:999px}}</style>
              {maskotlar(kod, olc) or f"<div class=l><img src='{logo}'></div>"}<div style="max-width:{1000*olc}px"><h1>{m['ad']}</h1><p>{SLOGAN[kod]}</p><span class=u>{m['site_kisa']}</span></div>""")
            s.wait_for_timeout(400); s.screenshot(path=str(O / f"{kod}-{ad}.png"))
        s.close()
    b.close()
