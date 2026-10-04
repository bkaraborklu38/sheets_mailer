# Sheets Mailer

Google Sheets'teki firma listesinden, her takım üyesinin kendi adıyla kişiselleştirilmiş sponsorluk / iş birliği maili gönderen küçük bir araç. Yerelde veya GitHub Actions üzerinde çalışır.

Sheets'te her üyenin bir sekmesi vardır. Üye, firmanın mail adresini yazıp durumu **Hazır** yaptığında script o satırı alır, firmanın sektörüne uygun şablonu seçer, maili üyenin adıyla gönderir ve satırı **Gönderildi** olarak işaretler. Spam filtrelerine takılmamak için mailler arasında rastgele süre bekler.

## Klasör yapısı

```
├── mailer.py                  # Ana script
├── config.yaml                # Takım bilgileri, üyeler, sütunlar, şablon eşlemesi
├── templates/                 # Mail şablonları (HTML)
│   ├── _layout.html           # Tüm maillerin ortak çerçevesi (selamlama + imza yeri)
│   ├── _imza.html             # İmza bloğu
│   ├── genel.html             # Varsayılan şablon
│   └── teknik.html, imalat.html, marka.html
├── attachments/               # Maillere eklenecek dosya (ör. sponsorluk PDF'i)
├── .env.example               # Yerel çalıştırma için ortam değişkenleri örneği
└── .github/workflows/send_mail.yml   # GitHub Actions iş akışı
```

Gizli bilgiler (şifreler, API anahtarları, Sheets ID, servis hesabı) **hiçbir zaman koda veya config.yaml'a yazılmaz.** Yerelde `.env` dosyasında, GitHub'da ise Secrets'ta durur. İkisi de `.gitignore`'dadır.

---

## Kurulum

### 1. SMTP hesabı (Brevo)

Varsayılan ayarlar [Brevo](https://www.brevo.com) içindir (ücretsiz planda günlük 300 mail). Başka bir SMTP servisi de kullanılabilir; sadece `SMTP_HOST` ve `SMTP_PORT` değişir.

1. Brevo'da hesap açın ve gönderici adresinizi (takım mailiniz) doğrulayın.
2. **SMTP & API → SMTP** sekmesinden **Login** değerini (`SMTP_USER`) ve bir **SMTP anahtarı** (`SMTP_PASS`) alın.
3. Spam klasörüne düşmemek için mümkünse Brevo'da alan adı doğrulaması (SPF/DKIM) yapın.

### 2. Google Sheets ve servis hesabı

1. [console.cloud.google.com](https://console.cloud.google.com) → yeni proje oluşturun.
2. **APIs & Services → Library** üzerinden **Google Sheets API** ve **Google Drive API**'yi etkinleştirin.
3. **Credentials → Create Credentials → Service account** ile bir servis hesabı oluşturun.
4. Servis hesabına tıklayın → **Keys → Add Key → Create new key → JSON**. İnen dosyanın adını `service_account.json` yapın.
5. Tablonuzu Google Sheets'te açın ve **Paylaş** butonundan servis hesabının mailini (JSON içindeki `client_email`, `...@...iam.gserviceaccount.com`) **Düzenleyici** olarak ekleyin. "Kişilere bildir" kutusunu kaldırabilirsiniz.
6. Sheets ID'yi URL'den alın: `docs.google.com/spreadsheets/d/`**`BU_KISIM`**`/edit`

> Excel dosyası yüklediyseniz önce **Google E-Tablolar ile aç** deyin; aksi halde URL'deki kod Drive dosya ID'si olur ve çalışmaz.

### 3. Tablo yapısı

Her üye için bir sekme açın (sekme adı `config.yaml`'daki `sekme` değeriyle aynı olmalı). Varsayılan sütun düzeni:

| A | B | C | D | E | F | G | H |
|---|---|---|---|---|---|---|---|
| (boş) | # | Şirket | Mail | Sektör | Durum | Özel Not | Tarih |

- **Durum** sütununa `Hazır` yazılan ve mail adresi dolu satırlar gönderilir. Script gönderince `Gönderildi`, hata olursa `Hata` yazar ve **Tarih** sütununu doldurur.
- **Sektör** metni şablon seçiminde kullanılır (ör. "Savunma Sanayii" → `teknik` şablonu).
- **Özel Not** doluysa maile ayrı bir paragraf olarak eklenir (firmaya özel bir cümle için).
- Düzeniniz farklıysa `config.yaml → sheets.sutunlar` kısmından harfleri değiştirin.
- Özet, Taslak gibi taranmaması gereken sekmeleri `atlanan_sekmeler` listesine ekleyin.

### 4. config.yaml

Dosyadaki örnek değerleri kendi takımınıza göre düzenleyin:

- **takim:** Takım adı, kurum, yarışma, proje adı. `logo_url` ve `dokuman_url` boş bırakılırsa ilgili kısımlar mailde hiç görünmez.
- **gonderim:** Limit, bekleme süreleri ve ek dosya.
- **uyeler:** Her üye için sekme adı, maillerde görünecek ad ve cevapların gideceği `reply_to` adresi. Gmail kullanıyorsanız `takim+isim@gmail.com` şeklinde alias verirseniz tüm cevaplar takım mailine düşer ama kime geldiği ayırt edilebilir. Alias'larda Türkçe karakter kullanmayın.
- **sablonlar:** Sektör anahtar kelimesi → şablon eşlemesi.

### 5. Şablonlar

> **Önemli:** Hazır şablonlar, araç geliştiren bir yarışma takımı (ör. TEKNOFEST İKA) örnek alınarak yazılmıştır; "araç üzeri logo", "şasi imalatı" gibi ifadeler içerir. Göndermeden önce `templates/` içindeki metinleri kendi projenize, sunduğunuz sponsorluk karşılıklarına ve takımınızın üslubuna göre mutlaka düzenleyin. Bunun için kod bilgisi gerekmez; dosyaları herhangi bir metin editörüyle açıp cümleleri değiştirmeniz yeterlidir. Sonucu `--dry-run` ile önizleyebilirsiniz.

Şablonlar `templates/` klasöründeki HTML dosyalarıdır. İlk satır konu, `---` satırından sonrası mail gövdesidir:

```html
konu: {{takim_ad}} — {{yarisma}} Sponsorluk Teklifi
---
<p>{{sirket}} ile tanışmak istiyoruz...</p>
{{ozel_not_paragraf}}
{{dokuman_satiri}}
```

Kullanılabilecek alanlar:

| Alan | Açıklama |
|---|---|
| `{{sirket}}`, `{{sektor}}`, `{{ozel_not}}` | Tablodaki satırdan |
| `{{gonderen_ad}}`, `{{gonderen_ilk_ad}}` | Sekmenin sahibi olan üye |
| `{{takim_ad}}`, `{{kurum}}`, `{{yarisma}}`, `{{proje}}` | config.yaml → takim |
| `{{takim_mail}}` | `SENDER_EMAIL` |
| `{{logo_url}}`, `{{dokuman_url}}` | config.yaml → takim |
| `{{ozel_not_paragraf}}` | Özel not doluysa `<p>` içinde, boşsa hiçbir şey |
| `{{dokuman_satiri}}` | Doküman linki satırı, `dokuman_url` boşsa hiçbir şey |

Yeni şablon eklemek için `templates/` içine yeni bir `.html` dosyası koyun ve `config.yaml → sablonlar.kategoriler` altına anahtar kelimelerini yazın. Selamlama ve imza her maile `_layout.html` ve `_imza.html` üzerinden otomatik eklenir.

### 6. Ek dosya

Sponsorluk dosyanızı `attachments/` klasörüne koyun ve yolunu `config.yaml → gonderim.ek_dosya` satırına yazın. Ek istemiyorsanız boş bırakın.

> Repo public ise eklediğiniz dosya herkes tarafından görülebilir. Paylaşmak istemediğiniz bir dosyaysa repoyu private tutun.

---

## Yerelde çalıştırma

```bash
pip install -r requirements.txt
cp .env.example .env          # sonra .env'i düzenleyin
# service_account.json dosyasını proje klasörüne koyun

python mailer.py --dry-run    # mail atmaz, onizleme/ klasörüne HTML önizlemeler üretir
python mailer.py --limit 1 --uye AYSE   # tek mail ile gerçek deneme
python mailer.py              # normal çalıştırma
```

İlk denemede tabloya kendi mail adresinizi yazıp `--limit 1` ile göndermeniz önerilir.

## GitHub Actions ile çalıştırma

### Secrets

Repo → **Settings → Secrets and variables → Actions → New repository secret** ile şunları ekleyin:

| Secret | Değer | Zorunlu |
|---|---|---|
| `SMTP_USER` | SMTP kullanıcı adı (Brevo SMTP Login) | Evet |
| `SMTP_PASS` | SMTP anahtarı / şifresi | Evet |
| `SENDER_EMAIL` | Gönderici adres (SMTP servisinde doğrulanmış) | Evet |
| `SHEETS_ID` | Sheets URL'sindeki kod | Evet |
| `SERVICE_ACCOUNT_JSON` | `service_account.json` dosyasının **tüm içeriği** (aç, kopyala, yapıştır) | Evet |
| `SMTP_HOST` | Brevo dışında bir servis kullanıyorsanız | Hayır |
| `SMTP_PORT` | Varsayılan 587 | Hayır |
| `GMAIL_APP_PASSWORD` | Gönderilen maillerin kopyasını takım Gmail'ine atmak için Gmail uygulama şifresi | Hayır |

### Çalıştırma

**Actions → Sheets Mailer → Run workflow** butonuyla:

- **uye:** Sekme adı (ör. `AYSE`). Boş bırakılırsa tüm üye sekmeleri sırayla taranır.
- **limit:** Bu çalışmada gönderilecek en fazla mail.
- **dry_run:** İşaretlenirse mail gönderilmez; log ve önizlemeler iş bittiğinde **Artifacts** kısmından indirilebilir.

Otomatik zamanlama için `send_mail.yml` içindeki `schedule` satırlarının başındaki `#` işaretlerini kaldırın. Cron saatleri UTC'dir (Türkiye = UTC+3).

> Mailler arası bekleme nedeniyle iş uzun sürebilir: 50 mail × ortalama 5 dk ≈ 4 saat. GitHub Actions bir işi en fazla 6 saat çalıştırır; limiti buna göre seçin.

---

## Sorun giderme

| Hata | Çözüm |
|---|---|
| `Eksik ayar: ...` | Belirtilen değişkeni `.env` dosyasına veya GitHub Secrets'a ekleyin |
| `SMTPAuthenticationError` | `SMTP_USER` / `SMTP_PASS` yanlış ya da gönderici adres doğrulanmamış |
| `SpreadsheetNotFound` | `SHEETS_ID` yanlış veya tablo servis hesabıyla paylaşılmamış |
| `APIError: ... has not been used in project` | Google Cloud'da Sheets / Drive API etkin değil |
| `'X' sekmesi config.yaml'daki üyeler listesinde yok` | Sekme adını `uyeler` listesine ekleyin veya `atlanan_sekmeler`'e yazın |
| Hiç satır gönderilmiyor | Durum sütununda tam olarak `Hazır` yazdığından ve sütun harflerinin doğru olduğundan emin olun |
| Mailler spam'e düşüyor | Alan adı doğrulaması (SPF/DKIM) yapın, bekleme süresini artırın, günlük limiti düşürün |
