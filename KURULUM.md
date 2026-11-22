# IG Otopilot — kurulum ve işleyiş

Site Mucidi, Davetiyeler.TR, Sapanca Güvenilir Bungalov ve MarkaKarnem Instagram hesaplarına **her gün 1 Reels + 1 hikâye**
üretip kendiliğinden paylaşan sistem. Tamamen ücretsiz: GitHub Actions (bilgisayar kapalıyken çalışır),
Gemini/Groq ücretsiz katman (yoksa kural motoru), Instagram Graph API.

## Nasıl çalışır?

| Adım | Ne olur |
|---|---|
| 1. Veri | Her gün sitelerden **canlı** veri okunur: Site Mucidi `/api/themes` (199 tema), davetiyeler.tr WooCommerce mağaza API'si (1.700+ ürün, kategori, kampanya), bungalov sitesindeki rehberler ve Bakanlık sayısı. |
| 2. Karar | `otopilot/beyin.py` formatı seçer: marka ağırlıkları × ölçülen performans (kaydetme ×3, paylaşım ×4, yorum ×2, erişim), dün paylaşılan format geri planda, %15 keşif. 120 gün içinde kullanılan tema/ürün/rehber tekrar edilmez. |
| 3. Metin | Gemini (yoksa Groq) yalnız verilen **olgulara** dayanarak kanca, ekran yazıları, SEO'lu açıklama ve hikâye yazar. Uydurma rakam, "en iyi/en çok" iddiası, yasak ifade, uzun yazı varsa reddedilir ve kural metni kullanılır. |
| 4. Video | Robot tarayıcı **gerçek ekranları** sanal saatle kare kare kaydeder (akıcı 30 kare/sn, 1080×1920): Site Mucidi sihirbazında işletme adı yazılıp site önizlenir; dijital davetiyenin gerçek açılış animasyonu; ürün fotoğrafları; rehber sayfası kaydırma. |
| 5. Kalite | Boyut, süre, boş/tek renk kare (yüklenmeyen sayfa), metin kuralları. Geçmeyen format atlanır, sıradaki denenir (3 deneme). |
| 6. Yayın | Video Instagram'a doğrudan yüklenir (barındırma gerekmez): önce Reels (akışta da görünür), sonra hikâye. |
| 7. Öğrenme | Sonraki günlerde 24 saati geçen gönderilerin ölçümleri çekilir, skorlanır; iyi giden formatların ağırlığı artar, en iyi/zayıf kancalar yapay zekâya örnek verilir. |

**Saatler** (`markalar/*.yaml` → `saat.reels`): Site Mucidi 12:30, MarkaKarnem 13:30, Bungalov 19:00, Davetiyeler 20:00.
GitHub zamanlayıcısı 30 dk kadar gecikebilir; 22:00'deki ek çalıştırma hata vereni yeniden dener.

## Formatlar

- **Site Mucidi:** `sektor_demo` (bir sektör teması seçilir, sihirbazda adı yazılır, gerçek önizleme kaydırılır),
  `ozellik` (WhatsApp, randevu, harita… tek özellik), `yz_arama` (insanlar artık yapay zekâya soruyor, yapay zekâ
  sitelerden derler), `tema_paket` (aynı tema Yalın/Vizyon/Premium).
- **Davetiyeler.TR:** `model_vitrin` (sezona göre kategori, 4 gerçek model, "yoruma numara yazın"),
  `dijital_davetiye` (70+ canlı dijital davetiyeden biri gerçek animasyonuyla), `siparis_nasil`, `kampanya`
  (basılı davetiyeye ₺650 değerinde dijital davetiye hediye).
- **Bungalov:** `guvenlik_ipucu` / `rehber` (sitedeki rehberler), `belge_sorgula` (+ Bakanlık kaydındaki belgeli
  tesis sayısı), `isletme_davet` (tesis sahiplerine komisyonsuz listeleme). Fotoğraflar temsilidir.
- **MarkaKarnem:** `soru_cevap` (soru/sözlük/rehber sayfaları), `sektor_ipucu`, `yerel_karne` (Sakarya'da ölçülmüş
  sektör verisi: en sık eksik %, medyan Marka Skoru), `arac_demo` (etkileşim oranı aracına rakam yazılıp sonuç
  gösterilir — tarayıcıda hesaplar, API/yapay zekâ bütçesi harcamaz), `ornek_rapor`. Gerçek analiz başlatılmaz.

Yeni format eklemek: `otopilot/kaynak/<marka>.py` içine fonksiyon yazıp `FORMATLAR`'a ve `markalar/<marka>.yaml`
`formatlar` ağırlığına ekleyin.

## Yerelde deneme

```bash
cd ~/Documents/ig-otopilot
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/playwright install chromium
PYTHONPATH=. .venv/bin/python -m otopilot.calistir uret --marka sgb --zorla            # çıktı: cikti/<tarih>/sgb/
PYTHONPATH=. .venv/bin/python -m otopilot.calistir uret --marka sitemucidi --zorla --format sektor_demo
PYTHONPATH=. .venv/bin/python -m pytest -q tests
```
`YAYIN=acik` olmadan **hiçbir şey paylaşılmaz.**

## Müzik

Instagram API'si Instagram'ın müzik kütüphanesini eklemeye izin vermez. `muzik/` klasörüne telifsiz `.mp3`
koyarsanız (ör. YouTube Ses Kitaplığı "atıf gerekmez" parçaları) her videoya rastgele biri, yumuşak giriş/çıkışla eklenir.
Klasör boşsa video sessiz yüklenir.

## Bir kerelik kurulum (kullanıcı)

### 1) Instagram hesapları
Her marka için Instagram hesabı **Profesyonel** olmalı: Ayarlar → Hesap türü ve araçlar → Profesyonel hesaba geç
→ İşletme. (Facebook sayfasına bağlamak gerekmez.)

### 2) Meta uygulamasına Instagram ürünü ve test kullanıcıları
developers.facebook.com → Uygulamalarım → **Mchttasarım Marka Yönetim** →
- Ürün ekle → **Instagram** → "API setup with Instagram login".
- Uygulama rolleri → Roller → **Instagram Testers** → üç hesabın kullanıcı adını ekleyin.
- Her hesapta Instagram: Ayarlar → Web siteleri ve uygulamalar → **Test kullanıcısı davetleri** → Kabul et.
- Instagram → API setup → **Generate access tokens** → her hesap için "Add account" → izinler:
  `instagram_business_basic`, `instagram_business_content_publish`, `instagram_business_manage_insights`.
  Çıkan **erişim anahtarı** ve **Instagram hesap kimliği (user id)** not edilir.

### 3) GitHub sırları (anahtarlar ekrana yazdırılmadan girilir)
```bash
R=mcht54/ig-otopilot
gh secret set GEMINI_API_KEY -R $R        # aistudio.google.com/apikey (ücretsiz)
gh secret set GROQ_API_KEY -R $R          # isteğe bağlı yedek: console.groq.com (ücretsiz)
for K in SITEMUCIDI DAVETIYELER SGB MARKAKARNEM; do gh secret set IG_${K}_ID -R $R; gh secret set IG_${K}_TOKEN -R $R; done
gh secret set GH_PAT -R $R                # anahtar yenileme için: yalnız bu depoda "Secrets: write" izinli ince taneli token
gh variable set IG_API -R $R --body instagram
```
Eksik hesabı olan marka sırrı girilmediği sürece yalnız önizleme üretir, diğerleri paylaşır.

### 4) Önizleme → otomatik
`YAYIN` değişkeni yokken her gün videolar GitHub Release'e konur ve **"Önizleme — onay bekliyor"** başlıklı bir
issue açılır (GitHub e-posta gönderir). Beğenince:
```bash
gh variable set YAYIN -R mcht54/ig-otopilot --body acik
```
Bundan sonra paylaşım tamamen otomatik. Durdurmak için `--body kapali`. Hata olursa "⚠️ … hata verdi" issue'su gelir.

## Bilinen sınırlar
- Instagram API hikâyelere bağlantı/anket çıkartması ekleyemez; hikâyeler video kart olarak paylaşılır.
- Instagram ile Giriş anahtarları 60 gün geçerli; `anahtar.yml` her pazartesi uzatır (GH_PAT gerekir).
- Sitelerin tasarımı değişirse (ör. sihirbazdaki "Bilgiler"/"Önizleme" düğme adları) ilgili format kalite
  kapısında düşer, diğer formatlar çalışmaya devam eder; hata issue'su gelir.

## Çok platform (Dijital Çırak düzeni) ve panel takibi

Her Reels; Instagram Reels + hikâye, **Facebook sayfası Reels**, **YouTube Shorts** (markanın kendi kanalı) ve
**TikTok** (inceleme onayı yokken telefona taslak) olarak dağıtılır. Anahtarı olmayan platform atlanır.

| Sır | Ne |
|---|---|
| `IG_TOKEN` | Meta sistem kullanıcısı anahtarı (süresiz; Dijital Çırak'taki ile aynı). Sayfalar + Instagram hesapları sistem kullanıcısına atanmalı |
| `META_<KOD>_IG_ID`, `META_<KOD>_PAGE_ID` | Markanın sayfaya bağlı Instagram hesap kimliği ve Facebook sayfa kimliği |
| `YT_CLIENT_ID`, `YT_CLIENT_SECRET` | Dijital Çırak'taki YouTube OAuth istemcisi (ortak) |
| `YT_<KOD>_REFRESH_TOKEN` | Markanın kendi kanalı seçilerek alınan yenileme anahtarı |
| `TT_CLIENT_KEY`, `TT_CLIENT_SECRET`, `TT_<KOD>_REFRESH_TOKEN` | TikTok uygulaması (ortak) + markanın hesabı |

`<KOD>`: SITEMUCIDI, DAVETIYELER, SGB, MARKAKARNEM. `IG_TOKEN + META_<KOD>_IG_ID` varsa markaya özel `IG_<KOD>_TOKEN` gerekmez.

**Panel:** her çalıştırmanın sonunda `python -m otopilot.panel` son 14 günü (tarih, marka, format, konu, platform
platform durum + bağlantı, ölçüm/skor) GitHub OIDC ile `panel.mchttasarim.com.tr/api/icerik-takvimi/senkron/ig_otopilot`
ucuna gönderir; panelde anahtar tutulmaz. Panelin `KANALLAR` listesinde `ig_otopilot` tanımlı olmalı.
