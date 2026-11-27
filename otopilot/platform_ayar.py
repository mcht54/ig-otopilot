"""Panel "hesap başına platform ayarları" (2026-11-27): panelde bir hesabın bir platformu kapatılınca hat o platforma paylaşmaz.

Panel senkron yanıtı: {"platform_ayarlari": {"hesaplar": {"<hesap>": {"<platform>": true|false}}}}
Kural: alan yoksa / hesap ya da platform yoksa AÇIK. Yalnız açıkça false olan kapalıdır.
Panel her yanıt verdiğinde ayar durum/platform_ayarlari.json'a yazılır (akış durum/ klasörünü commitler → koşular arası kalıcı).
Panel ulaşılamazsa son bilinen ayar kullanılır; dosya yoksa/bozuksa hepsi açık.
Bu hatta hesap kodu = marka kodu (sitemucidi, davetiyeler, sgb, markakarnem).
"""
from __future__ import annotations

import json
from pathlib import Path

from . import ortak
from .ortak import json_kaydet, log, simdi

NOT = "atlandı: panelde kapalı"


def dosya() -> Path:
    return ortak.DURUM / "platform_ayarlari.json"  # her çağrıda: testler DURUM'u geçici klasöre çevirir


def kaydet(yanit) -> bool:
    """Senkron yanıtındaki platform_ayarlari'nı önbelleğe yazar. Alan yoksa (panelin eski sürümü) önbelleğe dokunmaz."""
    if not isinstance(yanit, dict):
        return False
    pa = yanit.get("platform_ayarlari")
    if not isinstance(pa, dict) or not isinstance(pa.get("hesaplar"), dict):
        return False
    hesaplar = {str(h): {str(p): bool(v) for p, v in d.items() if isinstance(v, bool)}
                for h, d in pa["hesaplar"].items() if isinstance(d, dict)}
    try:
        eski = json.loads(dosya().read_text(encoding="utf-8")).get("hesaplar") if dosya().exists() else None
    except Exception:  # noqa: BLE001
        eski = None
    if eski != hesaplar:  # değişmediyse dosyaya yazılmaz (her koşuda boş "durum" commit'i olmasın)
        json_kaydet(dosya(), {"hesaplar": hesaplar, "zaman": simdi().isoformat(timespec="seconds")})
        kapali = sorted(f"{h}/{p}" for h, d in hesaplar.items() for p, v in d.items() if v is False)
        log(f"platform ayarları güncellendi; kapalı: {', '.join(kapali) or 'yok'}")
    return True


def oku() -> dict:
    try:
        h = json.loads(dosya().read_text(encoding="utf-8")).get("hesaplar")
        return h if isinstance(h, dict) else {}
    except Exception:  # noqa: BLE001  (dosya yok/bozuk → hepsi açık)
        return {}


def acik(hesap: str, platform: str) -> bool:
    """Instagram Reels kapalıysa Instagram hikâyesi de kapalı sayılır."""
    d = oku().get(hesap)
    if not isinstance(d, dict):
        return True
    if platform == "instagram_hikaye" and d.get("instagram") is False:
        return False
    return d.get(platform) is not False
