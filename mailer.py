"""
Sheets Mailer — Google Sheets'ten kişiselleştirilmiş toplu mail gönderici
==========================================================================
Nasıl çalışır:
  1. config.yaml'dan takım bilgilerini, üyeleri ve şablon eşlemelerini okur
  2. Google Sheets'teki her üye sekmesini tarar, Durum = "Hazır" ve mail
     adresi dolu satırları seçer
  3. Satırın sektörüne göre templates/ klasöründen uygun şablonu seçer,
     sekmenin sahibi olan üyenin adıyla SMTP üzerinden gönderir
  4. Gönderilen satırın durumunu "Gönderildi" yapar ve tarih yazar
  5. Limit dolunca durur; mailler arasında rastgele süre bekler

Kullanım:
  python mailer.py                      → Normal çalıştır
  python mailer.py --dry-run            → Mail atmadan test et (önizleme üretir)
  python mailer.py --limit 10           → Bu çalışmada en fazla 10 mail
  python mailer.py --uye AYSE           → Sadece bu sekmeyi çalıştır
  python mailer.py --config baska.yaml  → Farklı bir config dosyası kullan
"""

import argparse
import logging
import os
import random
import re
import smtplib
import sys
import time
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "mailer.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ── Ortam değişkenleri (gizli bilgiler burada, koda yazılmaz) ─────
SMTP_HOST = os.getenv("SMTP_HOST", "smtp-relay.brevo.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
SHEETS_ID = os.getenv("SHEETS_ID", "")
SERVICE_ACCT_FILE = os.getenv("SERVICE_ACCT_FILE", "service_account.json")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")


# ── Yardımcılar ───────────────────────────────────────────────────
def tr_lower(metin: str) -> str:
    """Türkçe karakterlere duyarlı küçük harfe çevirme (İ→i, I→ı)."""
    return metin.strip().replace("İ", "i").replace("I", "ı").lower()


def sutun_index(harf: str) -> int:
    """'A' → 0, 'C' → 2, 'AA' → 26."""
    idx = 0
    for ch in harf.strip().upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def doldur(metin: str, degerler: dict) -> str:
    """{{alan}} yer tutucularını doldurur; bilinmeyen alanları boş bırakır."""
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", lambda m: str(degerler.get(m.group(1), "")), metin)


# ── Config ────────────────────────────────────────────────────────
def config_yukle(yol: Path) -> dict:
    if not yol.exists():
        log.error(f"Config dosyası bulunamadı: {yol}")
        sys.exit(1)
    with open(yol, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    sh = cfg["sheets"]
    sh["_idx"] = {ad: sutun_index(harf) for ad, harf in sh["sutunlar"].items()}
    sh["_atlanan"] = {tr_lower(s) for s in sh.get("atlanan_sekmeler", [])}
    cfg["_uyeler"] = {tr_lower(u["sekme"]): u for u in cfg.get("uyeler", [])}
    return cfg


def env_kontrol(dry_run: bool):
    eksik = []
    if not SHEETS_ID:
        eksik.append("SHEETS_ID")
    if not Path(SERVICE_ACCT_FILE).exists():
        eksik.append(f"{SERVICE_ACCT_FILE} (dosya)")
    if not dry_run:
        for ad, deger in [("SMTP_USER", SMTP_USER), ("SMTP_PASS", SMTP_PASS), ("SENDER_EMAIL", SENDER_EMAIL)]:
            if not deger:
                eksik.append(ad)
    if eksik:
        log.error("Eksik ayar: " + ", ".join(eksik) + " — README'deki kurulum adımlarına bakın.")
        sys.exit(1)


# ── Şablonlar ─────────────────────────────────────────────────────
class Sablonlar:
    """templates/ klasöründeki şablonları okur ve sektöre göre seçer."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.klasor = BASE_DIR / "templates"
        self.layout = (self.klasor / "_layout.html").read_text(encoding="utf-8")
        self.imza = (self.klasor / "_imza.html").read_text(encoding="utf-8")
        self.varsayilan = cfg["sablonlar"].get("varsayilan", "genel")
        self.kurallar = cfg["sablonlar"].get("kategoriler", [])

    def sec(self, sektor: str) -> str:
        s = tr_lower(sektor)
        for kural in self.kurallar:
            if any(tr_lower(a) in s for a in kural["anahtarlar"]):
                return kural["sablon"]
        return self.varsayilan

    def oku(self, ad: str) -> tuple[str, str]:
        """Şablon dosyası: ilk satır 'konu: ...', ardından '---', sonra HTML gövde."""
        yol = self.klasor / f"{ad}.html"
        if not yol.exists():
            log.warning(f"Şablon bulunamadı: {yol.name}, varsayılan kullanılıyor.")
            yol = self.klasor / f"{self.varsayilan}.html"
        ham = yol.read_text(encoding="utf-8")
        ust, _, govde = ham.partition("\n---\n")
        konu = ust.split(":", 1)[1].strip() if ust.lower().startswith("konu:") else ""
        return konu, govde.strip()

    def olustur(self, kayit: dict, uye: dict) -> tuple[str, str]:
        takim = self.cfg["takim"]
        degerler = {
            "sirket": kayit["sirket"],
            "sektor": kayit["sektor"],
            "ozel_not": kayit["ozel_not"],
            "gonderen_ad": uye["ad"],
            "gonderen_ilk_ad": uye["ad"].split()[0],
            "takim_ad": takim.get("ad", ""),
            "kurum": takim.get("kurum", ""),
            "yarisma": takim.get("yarisma", ""),
            "proje": takim.get("proje", ""),
            "logo_url": takim.get("logo_url", ""),
            "dokuman_url": takim.get("dokuman_url", ""),
            "takim_mail": SENDER_EMAIL or takim.get("iletisim_mail", ""),
        }
        # Boş bırakılan alanlar maile hiç yansımasın diye hazır HTML parçaları
        degerler["dokuman_satiri"] = (
            f'<p style="font-size:13px;color:#555">📎 Teknik detaylar için dokümanımıza '
            f'<a href="{degerler["dokuman_url"]}" style="color:#2E75B6">buradan</a> ulaşabilirsiniz.</p>'
            if degerler["dokuman_url"] else ""
        )
        degerler["logo_html"] = (
            f'<td style="padding-right:14px;vertical-align:middle"><img src="{degerler["logo_url"]}" '
            f'width="64" height="64" alt="{degerler["takim_ad"]}" style="border-radius:50%"/></td>'
            if degerler["logo_url"] else ""
        )
        degerler["ozel_not_paragraf"] = f"<p>{degerler['ozel_not']}</p>" if degerler["ozel_not"] else ""

        konu_ham, govde_ham = self.oku(self.sec(kayit["sektor"]))
        konu = doldur(konu_ham, degerler)
        if self.cfg["gonderim"].get("konu_onek_uye_adi", False):
            konu = f"[{tr_lower(uye['ad'].split()[0]).upper()}] {konu}"

        degerler["govde"] = doldur(govde_ham, degerler)
        degerler["imza"] = doldur(self.imza, degerler)
        return konu, doldur(self.layout, degerler)


# ── Google Sheets ─────────────────────────────────────────────────
def sheets_baglan():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(SERVICE_ACCT_FILE, scopes=scopes)
    sh = gspread.authorize(creds).open_by_key(SHEETS_ID)
    log.info(f"Sheets bağlandı: {sh.title}")
    return sh


def hazir_satirlar(sheet, cfg: dict) -> list:
    sh_cfg = cfg["sheets"]
    idx = sh_cfg["_idx"]
    en_genis = max(idx.values()) + 1
    hazir = tr_lower(sh_cfg["durum_hazir"])
    baslik_satiri = sh_cfg.get("baslik_satiri", 1)

    sonuc = []
    for i, row in enumerate(sheet.get_all_values()):
        if i < baslik_satiri:
            continue
        row = row + [""] * (en_genis - len(row))
        sirket = row[idx["sirket"]].strip()
        mail = row[idx["mail"]].strip()
        durum = row[idx["durum"]].strip()
        if sirket and mail and tr_lower(durum) == hazir:
            sonuc.append({
                "row_idx": i + 1,
                "sirket": sirket,
                "mail": mail,
                "sektor": row[idx["sektor"]].strip() if "sektor" in idx else "",
                "ozel_not": row[idx["ozel_not"]].strip() if "ozel_not" in idx else "",
                "sekme": sheet.title,
            })
    return sonuc


def durum_guncelle(sheet, row_idx: int, durum_metni: str, renk: dict | None, cfg: dict):
    sh_cfg = cfg["sheets"]
    durum_col = sh_cfg["sutunlar"]["durum"]
    tarih_col = sh_cfg["sutunlar"]["tarih"]
    tarih = datetime.now().strftime("%d.%m.%Y %H:%M")
    sheet.batch_update([
        {"range": f"{durum_col}{row_idx}", "values": [[durum_metni]]},
        {"range": f"{tarih_col}{row_idx}", "values": [[tarih]]},
    ])
    if renk and sh_cfg.get("renklendir", True):
        sutunlar = sh_cfg["_idx"].values()
        try:
            sheet.spreadsheet.batch_update({"requests": [{"repeatCell": {
                "range": {
                    "sheetId": sheet.id,
                    "startRowIndex": row_idx - 1, "endRowIndex": row_idx,
                    "startColumnIndex": min(sutunlar), "endColumnIndex": max(sutunlar) + 1,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": renk}},
                "fields": "userEnteredFormat.backgroundColor",
            }}]})
        except Exception as e:
            log.warning(f"  Satır renklendirilemedi: {e}")


# ── Mail gönderimi ────────────────────────────────────────────────
def ek_yukle(cfg: dict):
    g = cfg["gonderim"]
    yol = g.get("ek_dosya")
    if not yol:
        return None
    tam_yol = BASE_DIR / yol
    if not tam_yol.exists():
        log.warning(f"Ek dosya bulunamadı ({tam_yol}), mailler eksiz gönderilecek.")
        return None
    return tam_yol.read_bytes(), g.get("ek_dosya_adi") or tam_yol.name


def mail_gonder(kayit: dict, uye: dict, sablonlar: Sablonlar, ek, cfg: dict, dry_run: bool) -> bool:
    konu, govde = sablonlar.olustur(kayit, uye)

    if dry_run:
        onizleme = BASE_DIR / "onizleme"
        onizleme.mkdir(exist_ok=True)
        dosya = onizleme / f"{kayit['sekme']}_{kayit['row_idx']}.html"
        dosya.write_text(f"<!-- Konu: {konu} | Alıcı: {kayit['mail']} -->\n{govde}", encoding="utf-8")
        log.info(f"[DRY-RUN] {uye['ad']} → {kayit['mail']} | {kayit['sirket']} | önizleme: {dosya.name}")
        return True

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = konu
        msg["From"] = f"{uye['ad']} <{SENDER_EMAIL}>"
        msg["To"] = kayit["mail"]
        msg["Reply-To"] = uye.get("reply_to") or SENDER_EMAIL
        kampanya = cfg["takim"].get("kampanya")
        if kampanya:  # Brevo panelinde takip için etiketler
            msg["X-Mailin-Tag"] = f"{kampanya},{kayit['sekme']},{kayit['sektor'] or 'genel'}"
            msg["X-Mailin-Campaign"] = kampanya

        alt = MIMEMultipart("alternative")
        alt.attach(MIMEText(govde, "html", "utf-8"))
        msg.attach(alt)

        if ek:
            veri, ad = ek
            parca = MIMEApplication(veri, _subtype="pdf" if ad.lower().endswith(".pdf") else "octet-stream")
            parca.add_header("Content-Disposition", "attachment", filename=ad)
            msg.attach(parca)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SENDER_EMAIL, kayit["mail"], msg.as_string())
        log.info(f"✓ {uye['ad']} → {kayit['mail']} | {kayit['sirket']}")
    except Exception as e:
        log.error(f"✗ Hata → {kayit['mail']} | {e}")
        return False

    if GMAIL_APP_PASSWORD:
        gmail_kopya_gonder(konu, govde, uye)
    return True


def gmail_kopya_gonder(konu: str, govde: str, uye: dict):
    """Opsiyonel: Gönderilen mailin bir kopyasını takım Gmail'ine atar,
    böylece Gmail'de kimin neyi gönderdiği takip edilebilir."""
    try:
        kopya = MIMEMultipart("mixed")
        kopya["Subject"] = f"[KOPYA][{uye.get('no', '--')}] {konu}"
        kopya["From"] = f"{uye['ad']} <{SENDER_EMAIL}>"
        kopya["To"] = SENDER_EMAIL
        kopya.attach(MIMEText(govde, "html", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as gm:
            gm.login(SENDER_EMAIL, GMAIL_APP_PASSWORD)
            gm.sendmail(SENDER_EMAIL, SENDER_EMAIL, kopya.as_string())
        log.info("  → Gmail'e kopya gönderildi")
    except Exception as e:
        log.warning(f"  → Gmail kopyası gönderilemedi: {e}")


# ── Ana döngü ─────────────────────────────────────────────────────
YESIL = {"red": 0.85, "green": 0.96, "blue": 0.85}
KIRMIZI = {"red": 0.96, "green": 0.85, "blue": 0.85}


def calistir(cfg: dict, dry_run=False, limit=None, sadece_uye=None):
    g = cfg["gonderim"]
    limit = limit or g.get("gunluk_limit", 60)
    log.info(f"=== Mailer | limit={limit} | dry_run={dry_run} | uye={sadece_uye or 'hepsi'} ===")

    env_kontrol(dry_run)
    sablonlar = Sablonlar(cfg)
    ek = ek_yukle(cfg)
    sh = sheets_baglan()

    gonderilen = hatali = 0
    for sekme in sh.worksheets():
        if gonderilen >= limit:
            log.info(f"Limit doldu ({limit}), duruluyor.")
            break

        anahtar = tr_lower(sekme.title)
        if anahtar in cfg["sheets"]["_atlanan"]:
            continue
        if sadece_uye and anahtar != tr_lower(sadece_uye):
            continue

        uye = cfg["_uyeler"].get(anahtar)
        if not uye:
            log.warning(f"--- '{sekme.title}' sekmesi config.yaml'daki üyeler listesinde yok, atlanıyor ---")
            continue

        kayitlar = hazir_satirlar(sekme, cfg)
        log.info(f"--- {sekme.title} → gönderici: {uye['ad']} | hazır: {len(kayitlar)} ---")

        for k in kayitlar:
            if gonderilen >= limit:
                break
            if mail_gonder(k, uye, sablonlar, ek, cfg, dry_run):
                gonderilen += 1
                if not dry_run:
                    durum_guncelle(sekme, k["row_idx"], cfg["sheets"]["durum_gonderildi"], YESIL, cfg)
                    if gonderilen < limit:
                        bekleme = random.randint(g.get("bekleme_min_sn", 180), g.get("bekleme_max_sn", 420))
                        log.info(f"  Bekleniyor: {bekleme // 60}:{bekleme % 60:02d} dk")
                        time.sleep(bekleme)
            else:
                hatali += 1
                durum_guncelle(sekme, k["row_idx"], cfg["sheets"]["durum_hata"], KIRMIZI, cfg)

    log.info(f"=== Bitti | Gönderilen: {gonderilen} | Hatalı: {hatali} ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Google Sheets tabanlı toplu mail gönderici")
    parser.add_argument("--dry-run", action="store_true", help="Mail atmadan test et, onizleme/ klasörüne HTML üret")
    parser.add_argument("--limit", type=int, default=None, help="Bu çalışmada gönderilecek en fazla mail")
    parser.add_argument("--uye", type=str, default=None, help="Sadece bu sekmeyi çalıştır (örn: AYSE)")
    parser.add_argument("--config", type=str, default="config.yaml", help="Config dosyasının yolu")
    args = parser.parse_args()

    calistir(config_yukle(BASE_DIR / args.config), dry_run=args.dry_run, limit=args.limit, sadece_uye=args.uye)
