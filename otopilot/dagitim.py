"""Aynı Reels'i markanın diğer platformlarına dağıtır (Dijital Çırak'taki yapı): Facebook sayfası Reels,
YouTube Shorts, TikTok. Bir platformun anahtarı yoksa atlanır, biri düşerse diğerleri yine denenir.
Anahtarlar yalnız ortamdan okunur; hiçbir yere yazılmaz, loglanmaz.

  Facebook : IG_TOKEN (Meta sistem kullanıcısı, süresiz; sayfa varlığı atanmış) + META_<KOD>_PAGE_ID
             (ya da doğrudan META_<KOD>_PAGE_TOKEN)
  YouTube  : YT_CLIENT_ID, YT_CLIENT_SECRET (ortak) + YT_<KOD>_REFRESH_TOKEN (markanın kendi kanalı)
  TikTok   : TT_CLIENT_KEY, TT_CLIENT_SECRET (ortak) + TT_<KOD>_REFRESH_TOKEN; denetimsiz uygulamada taslak
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

import requests

from .ortak import BelirsizYayin, log

GRAPH = "https://graph.facebook.com/v25.0"
TT_API = "https://open.tiktokapis.com/v2"
PLATFORM_AD = {"instagram": "Instagram Reels", "instagram_hikaye": "Instagram hikâye", "facebook": "Facebook Reels",
               "facebook_hikaye": "Facebook hikâye", "youtube": "YouTube Shorts", "tiktok": "TikTok"}


def _e(ad: str, kod: str) -> str:
    return os.environ.get(ad.replace("<KOD>", kod.upper()), "")


# ---------------- Facebook sayfası Reels
def _sayfa_anahtari(kod: str) -> tuple[str, str]:
    sayfa = _e("META_<KOD>_PAGE_ID", kod)
    dogrudan = _e("META_<KOD>_PAGE_TOKEN", kod)
    if dogrudan:
        return sayfa, dogrudan
    r = requests.get(f"{GRAPH}/{sayfa}", params={"fields": "access_token", "access_token": os.environ["IG_TOKEN"]}, timeout=30)
    if not r.ok or "access_token" not in r.json():
        raise RuntimeError(f"sayfa anahtarı alınamadı ({r.status_code}): {r.text[:200]}")
    return sayfa, r.json()["access_token"]


def facebook(kod: str, video: Path, aciklama: str) -> str:
    sayfa, t = _sayfa_anahtari(kod)
    r = requests.post(f"{GRAPH}/{sayfa}/video_reels", data={"upload_phase": "start", "access_token": t}, timeout=60)
    if not r.ok:
        raise RuntimeError(f"facebook başlatma {r.status_code}: {r.text[:300]}")
    vid = r.json()["video_id"]
    veri = video.read_bytes()
    u = requests.post(f"https://rupload.facebook.com/video-upload/v25.0/{vid}", data=veri, timeout=900,
                      headers={"Authorization": f"OAuth {t}", "offset": "0", "file_size": str(len(veri))})
    if not u.ok:
        raise RuntimeError(f"facebook yükleme {u.status_code}: {u.text[:300]}")
    try:  # finish = yayımla: yanıt alınamazsa Reels yayımlanmış olabilir → yeniden denenmez
        s = requests.post(f"{GRAPH}/{sayfa}/video_reels", timeout=60, data={
            "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED", "description": aciklama, "access_token": t})
    except requests.RequestException as e:
        raise BelirsizYayin(f"facebook finish yanıtı alınamadı ({type(e).__name__}); video {vid}") from e
    if not s.ok:  # Meta'nın açıkça döndürdüğü hata: yayımlanmadı, yeniden denenebilir
        raise RuntimeError(f"facebook {s.status_code}: {s.text[:300]}")
    try:
        basari = s.json().get("success")
    except ValueError as e:
        raise BelirsizYayin(f"facebook finish yanıtı okunamadı; video {vid}") from e
    if basari is not True:
        raise RuntimeError(f"facebook finish başarısız: {s.text[:300]}")
    return f"https://www.facebook.com/reel/{vid}"


def facebook_hikaye(kod: str, video: Path) -> str:
    """Aynı Reels videosu sayfanın Facebook hikâyesine (Muhit'teki yol; hikâye en çok 60 sn)."""
    sayfa, t = _sayfa_anahtari(kod)
    r = requests.post(f"{GRAPH}/{sayfa}/video_stories", data={"upload_phase": "start", "access_token": t}, timeout=60)
    if not r.ok or "video_id" not in r.json():
        raise RuntimeError(f"facebook hikâye başlatma {r.status_code}: {r.text[:300]}")
    vid = r.json()["video_id"]
    yukle = r.json().get("upload_url") or f"https://rupload.facebook.com/video-upload/v25.0/{vid}"
    veri = video.read_bytes()
    u = requests.post(yukle, data=veri, timeout=900,
                      headers={"Authorization": f"OAuth {t}", "offset": "0", "file_size": str(len(veri))})
    if not u.ok:
        raise RuntimeError(f"facebook hikâye yükleme {u.status_code}: {u.text[:300]}")
    try:  # finish = yayımla: yanıt alınamazsa hikâye gitmiş olabilir → yeniden denenmez
        s = requests.post(f"{GRAPH}/{sayfa}/video_stories", timeout=120,
                          data={"upload_phase": "finish", "video_id": vid, "access_token": t})
    except requests.RequestException as e:
        raise BelirsizYayin(f"facebook hikâye finish yanıtı alınamadı ({type(e).__name__}); video {vid}") from e
    if not s.ok:
        raise RuntimeError(f"facebook hikâye {s.status_code}: {s.text[:300]}")
    try:
        j = s.json()
    except ValueError as e:
        raise BelirsizYayin(f"facebook hikâye finish yanıtı okunamadı; video {vid}") from e
    if j.get("success") is not True and "post_id" not in j:
        raise RuntimeError(f"facebook hikâye finish başarısız: {s.text[:300]}")
    return f"http-fb-hikaye:{j.get('post_id') or vid}"


# ---------------- YouTube Shorts (markanın kendi kanalı)
def youtube_meta(aciklama: str, etiketler: list[str]) -> tuple[str, str]:
    ilk = aciklama.strip().splitlines()[0] if aciklama.strip() else "Yeni video"
    baslik = ilk[:88].rstrip(" .") + " #shorts"
    return baslik[:100], aciklama[:4900]


def youtube(kod: str, video: Path, aciklama: str, etiketler: list[str]) -> str:
    r = requests.post("https://oauth2.googleapis.com/token", timeout=30, data={
        "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": _e("YT_<KOD>_REFRESH_TOKEN", kod), "grant_type": "refresh_token"})
    r.raise_for_status()
    a = r.json()["access_token"]
    baslik, acik = youtube_meta(aciklama, etiketler)
    govde = {"snippet": {"title": baslik, "description": acik, "tags": [e.lstrip("#") for e in etiketler][:15],
                         "categoryId": "22", "defaultLanguage": "tr", "defaultAudioLanguage": "tr"},
             "status": {"privacyStatus": os.environ.get("YT_GIZLILIK", "public"), "selfDeclaredMadeForKids": False}}
    b = requests.post("https://www.googleapis.com/upload/youtube/v3/videos", params={"uploadType": "resumable", "part": "snippet,status"},
                      headers={"Authorization": f"Bearer {a}", "X-Upload-Content-Type": "video/mp4",
                               "X-Upload-Content-Length": str(video.stat().st_size)}, json=govde, timeout=60)
    b.raise_for_status()
    with open(video, "rb") as f:
        y = requests.put(b.headers["Location"], data=f, headers={"Content-Type": "video/mp4"}, timeout=900)
    y.raise_for_status()
    return "https://youtube.com/shorts/" + y.json()["id"]


# ---------------- TikTok (inceleme yokken gelen kutusuna taslak)
def tiktok(kod: str, video: Path, aciklama: str) -> str:
    r = requests.post(f"{TT_API}/oauth/token/", timeout=30, data={
        "client_key": os.environ["TT_CLIENT_KEY"], "client_secret": os.environ["TT_CLIENT_SECRET"],
        "grant_type": "refresh_token", "refresh_token": _e("TT_<KOD>_REFRESH_TOKEN", kod)})
    if "access_token" not in r.json():
        raise RuntimeError(f"tiktok anahtar yenilenemedi: {str(r.json())[:200]}")
    b = {"Authorization": f"Bearer {r.json()['access_token']}", "Content-Type": "application/json; charset=UTF-8"}
    boyut = video.stat().st_size
    parca = min(boyut, 10_000_000)
    adet = max(1, math.floor(boyut / parca))
    v = requests.post(f"{TT_API}/post/publish/inbox/video/init/", headers=b, timeout=60, data=json.dumps({
        "source_info": {"source": "FILE_UPLOAD", "video_size": boyut, "chunk_size": parca, "total_chunk_count": adet}})).json()
    if v.get("error", {}).get("code") not in (None, "ok"):
        raise RuntimeError(f"tiktok başlatma: {v['error']}")
    yid, url = v["data"]["publish_id"], v["data"]["upload_url"]
    with open(video, "rb") as f:
        for i in range(adet):
            bas = i * parca
            son = boyut - 1 if i == adet - 1 else bas + parca - 1
            f.seek(bas)
            veri = f.read(son - bas + 1)
            u = requests.put(url, data=veri, timeout=600, headers={"Content-Type": "video/mp4", "Content-Length": str(len(veri)),
                                                                     "Content-Range": f"bytes {bas}-{son}/{boyut}"})
            if u.status_code not in (200, 201, 206):
                raise RuntimeError(f"tiktok yükleme {u.status_code}: {u.text[:200]}")
    for _ in range(30):
        d = requests.post(f"{TT_API}/post/publish/status/fetch/", headers=b, timeout=30, data=json.dumps({"publish_id": yid})).json().get("data", {})
        if d.get("status") in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            return f"tiktok-taslak:{d['status']}:{yid}"
        if d.get("status") == "FAILED":
            raise RuntimeError(f"tiktok hatası: {d.get('fail_reason')}")
        time.sleep(10)
    return f"tiktok-taslak:BEKLIYOR:{yid}"


# platform → (gerekli ortam değişkenleri, gönderim)
PLATFORMLAR = {
    "facebook": (lambda k: _e("META_<KOD>_PAGE_ID", k) and (os.environ.get("IG_TOKEN") or _e("META_<KOD>_PAGE_TOKEN", k)),
                 lambda k, v, a, e: facebook(k, v, a)),
    "facebook_hikaye": (lambda k: _e("META_<KOD>_PAGE_ID", k) and (os.environ.get("IG_TOKEN") or _e("META_<KOD>_PAGE_TOKEN", k)),
                        lambda k, v, a, e: facebook_hikaye(k, v)),
    "youtube": (lambda k: os.environ.get("YT_CLIENT_ID") and _e("YT_<KOD>_REFRESH_TOKEN", k),
                lambda k, v, a, e: youtube(k, v, a, e)),
    "tiktok": (lambda k: os.environ.get("TT_CLIENT_KEY") and _e("TT_<KOD>_REFRESH_TOKEN", k),
               lambda k, v, a, e: tiktok(k, v, a)),
}


def tiktok_metni(aciklama: str) -> str:
    """TikTok'ta telefon/WhatsApp satırı dağıtımı düşürebiliyor (Dijital Çırak teşhisi) → bağlantı satırı sadeleşir."""
    return "\n".join(s for s in aciklama.splitlines() if "wa.me" not in s and "WhatsApp" not in s)


def dagit(kod: str, video: Path, aciklama: str, etiketler: list[str], onceki: dict | None = None) -> dict[str, str]:
    sonuc = dict(onceki or {})
    for p, (hazir, gonder) in PLATFORMLAR.items():
        if str(sonuc.get(p, "")).startswith(("http", "tiktok-taslak", "BELIRSIZ")):  # belirsiz: elle kontrol, tekrar gönderilmez
            continue
        if not hazir(kod):
            sonuc[p] = "atlandı: anahtar yok"
            continue
        metin = tiktok_metni(aciklama) if p == "tiktok" else aciklama
        for deneme in range(2):
            try:
                sonuc[p] = gonder(kod, video, metin, etiketler)
                break
            except BelirsizYayin as e:  # yayımlanmış olabilir: ikinci deneme çift paylaşım yapar
                sonuc[p] = f"BELIRSIZ: {str(e)[:300]}"
                break
            except Exception as e:  # bir platform düşerse diğerleri yine denensin
                sonuc[p] = f"HATA: {str(e)[:300]}"
                time.sleep(20)
        log(f"{kod} {p} → {sonuc[p][:120]}")
    return sonuc
