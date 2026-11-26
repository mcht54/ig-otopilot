from otopilot import aciklama_denetim as ad


def test_bilinen_hatalar_duzelir():
    metin = ("tadilat firması programı\nDijital davetiye modeli: Cerceve\n"
             "💬 Sen gecikmeleri nasıl önlüyorsun Yorumlara yaz 👇\n"
             "👉 Tesisinizi ekleyin: başvuru profildeki linkte: site.com.tr\n"
             "✔️ Kayıttaki adı, belge türünü ve ilçeyi…\n\n#a1b2 #sapanca #Sapanca #bungalov #tatil #sakarya #gezi")
    r = ad.denetle(metin)
    t = r["metin"]
    assert t.startswith("Tadilat")
    assert "Çerçeve" in t
    assert "önlüyorsun? Yorumlara yaz" in t
    assert t.count(": ") == 2  # çift iki nokta tek
    assert "…" not in t
    assert len([w for w in t.split() if w.startswith("#")]) == 5
    assert t.lower().count("#sapanca") == 1


def test_llm_rakam_degistirirse_reddedilir():
    metin = "Sipariş onayında ₺650 değerinde dijital davetiye hediye.\n\n#davetiye #düğün #nikah"
    r = ad.denetle(metin, llm=lambda istem: '{"metin": "Sipariş onayında ₺700 değerinde dijital davetiye hediye.\\n\\n#davetiye #düğün #nikah", "degisiklikler": []}')
    assert "₺650" in r["metin"]
