"""Instagram Graph API: Reels + video hikâye yayını (dosya doğrudan yüklenir, barındırma gerekmez)
ve gönderi ölçümleri. Ücretsizdir; yalnız Profesyonel (İşletme/İçerik üreticisi) hesapta çalışır.

Ortam değişkenleri (marka kodu büyük harfle, ör. SITEMUCIDI):
  IG_<KOD>_ID     Instagram hesap kimliği (ig-user-id)
  IG_<KOD>_TOKEN  Erişim anahtarı
  IG_API          "instagram" (Instagram ile Giriş, graph.instagram.com) ya da "facebook" (graph.facebook.com)
  ya da: IG_TOKEN (Meta sistem kullanıcısı, süresiz) + META_<KOD>_IG_ID → graph.facebook.com
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import requests

from .ortak import log

SURUM = os.environ.get("IG_GRAPH_SURUM", "v25.0")


class InstagramHatasi(RuntimeError):
    pass


class Instagram:
    def __init__(self, kod: str):
        k = kod.upper()
        # 1) Markaya özel anahtar (Instagram ile Giriş) ya da 2) Meta sistem kullanıcısı (süresiz, sayfaya bağlı hesap)
        self.kimlik = os.environ.get(f"IG_{k}_ID") or os.environ.get(f"META_{k}_IG_ID", "")
        ozel = os.environ.get(f"IG_{k}_TOKEN", "")
        self.anahtar = ozel or os.environ.get("IG_TOKEN", "")
        api = os.environ.get(f"IG_{k}_API") or (os.environ.get("IG_API", "instagram") if ozel else "facebook")
        self.kok = f"https://graph.{'instagram' if api == 'instagram' else 'facebook'}.com/{SURUM}"

    @property
    def hazir(self) -> bool:
        return bool(self.kimlik and self.anahtar)

    def _istek(self, yontem: str, yol: str, **params) -> dict:
        params["access_token"] = self.anahtar
        r = requests.request(yontem, f"{self.kok}/{yol}", params=params if yontem == "GET" else None,
                             data=params if yontem != "GET" else None, timeout=120)
        veri = r.json() if r.headers.get("content-type", "").startswith(("application/json", "text/javascript")) else {"ham": r.text[:300]}
        if r.status_code >= 400 or "error" in veri:
            hata = veri.get("error", veri)
            raise InstagramHatasi(f"{yol}: {hata.get('message', hata) if isinstance(hata, dict) else hata}")
        return veri

    def hesap(self) -> dict:
        return self._istek("GET", self.kimlik, fields="id,username,followers_count,media_count")

    def _yukle(self, video: Path, **alanlar) -> str:
        """Resumable upload: kapsayıcı oluştur → baytları rupload'a gönder → işlenmesini bekle."""
        kap = self._istek("POST", f"{self.kimlik}/media", upload_type="resumable", **alanlar)
        boyut = video.stat().st_size
        with open(video, "rb") as f:
            r = requests.post(kap["uri"], data=f, timeout=600, headers={
                "Authorization": f"OAuth {self.anahtar}", "offset": "0", "file_size": str(boyut)})
        if r.status_code >= 400:
            raise InstagramHatasi(f"yükleme {r.status_code}: {r.text[:300]}")
        kimlik = kap["id"]
        for _ in range(60):  # en çok ~10 dk
            d = self._istek("GET", kimlik, fields="status_code,status")
            if d.get("status_code") == "FINISHED":
                return kimlik
            if d.get("status_code") in ("ERROR", "EXPIRED"):
                raise InstagramHatasi(f"işleme hatası: {d.get('status')}")
            time.sleep(10)
        raise InstagramHatasi("işleme zaman aşımı")

    def _yayinla(self, kapsayici: str) -> dict:
        for deneme in range(5):
            try:
                m = self._istek("POST", f"{self.kimlik}/media_publish", creation_id=kapsayici)
                break
            except InstagramHatasi as e:
                if "not ready" in str(e).lower() and deneme < 4:
                    time.sleep(15)
                    continue
                raise
        bilgi = self._istek("GET", m["id"], fields="id,permalink,timestamp")
        return bilgi

    def reels(self, video: Path, aciklama: str, kapak_ms: int = 1200) -> dict:
        kap = self._yukle(video, media_type="REELS", caption=aciklama, share_to_feed="true", thumb_offset=str(kapak_ms))
        b = self._yayinla(kap)
        log(f"Reels yayında: {b.get('permalink')}")
        return b

    def hikaye(self, video: Path) -> dict:
        kap = self._yukle(video, media_type="STORIES")
        b = self._yayinla(kap)
        log(f"Hikâye yayında: {b.get('id')}")
        return b

    def olcumler(self, medya_id: str) -> dict:
        tam = ["reach", "views", "likes", "comments", "saved", "shares", "total_interactions", "ig_reels_avg_watch_time"]
        try:
            d = self._istek("GET", f"{medya_id}/insights", metric=",".join(tam))
        except InstagramHatasi:
            d = {"data": []}
            for m in tam:  # desteklenmeyen ölçüyü atla
                try:
                    d["data"] += self._istek("GET", f"{medya_id}/insights", metric=m)["data"]
                except InstagramHatasi:
                    pass
        sonuc = {}
        for x in d.get("data", []):
            v = x.get("values", [{}])[0].get("value", x.get("total_value", {}).get("value"))
            sonuc[x["name"]] = v
        return sonuc

    def anahtar_yenile(self) -> str | None:
        """Instagram ile Giriş anahtarları 60 gün geçerlidir; süresi dolmadan uzatılır."""
        if "graph.instagram.com" not in self.kok:
            return None
        r = requests.get("https://graph.instagram.com/refresh_access_token",
                         params={"grant_type": "ig_refresh_token", "access_token": self.anahtar}, timeout=60)
        if r.ok:
            return r.json().get("access_token")
        log(f"anahtar yenilenemedi: {r.text[:200]}")
        return None
