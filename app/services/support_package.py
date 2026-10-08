"""Destek Paketi (V1.2 M10d): sorun bildirmek için tek ZIP dosyası.

İçerik:
  * ``sistem.json``     — sürüm, şema, ortam, Sistem Durumu satırları, uyarılar,
    derin tutarlılık denetimi sonucu, yedek özeti, tablo satır sayıları,
  * ``ayarlar.json``    — YALNIZCA kullanıcıya açık ayarlar (beyaz liste);
    ``guvenlik_*`` ve iç ayarlar ASLA,
  * ``tanilama.json``   — barkod okuyucu yönlendirme kayıtları,
  * ``self_test.txt``   — kendi kendini sınama raporu (ayrı süreçte),
  * ``logs/…``          — kayıt dosyaları,
  * ``veritabani.db``   — YALNIZCA açıkça istenirse (önerilmez): yedekleme
    API'siyle alınan anlık görüntü; ``guvenlik_*`` satırları silinir, kişisel
    yollar maskelenir, ``VACUUM`` ile silinen veri dosyadan da atılır; geçici
    dosya her durumda silinir.

Maskeleme: kullanıcı profili yolu ve kullanıcı adı ``<KULLANICI>`` olur;
``guvenlik_`` ya da ``scrypt$`` geçen kayıt satırları tamamen çıkarılır. PIN
özeti ve tuzu hiçbir dosyaya girmez (bayt düzeyinde test edilir).

Qt bilmez.
"""
from __future__ import annotations

import json
import logging
import os
import platform
import re
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path

from app import config

log = logging.getLogger(__name__)

MASKE = "<KULLANICI>"
#: Bu ifadeleri içeren kayıt satırları pakete HİÇ girmez.
_GIZLI_SATIR = re.compile(r"guvenlik_|scrypt\$", re.IGNORECASE)
SELF_TEST_ZAMAN_ASIMI = 180


def _kisa_yol(yol: str) -> str | None:
    """Windows'ta yolun 8.3 kısa biçimi (geçici klasör yolları böyle görünür)."""
    if os.name != "nt":
        return None
    try:
        import ctypes

        tampon = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(str(yol), tampon, 1024):
            return tampon.value
    except Exception:                                   # pragma: no cover
        return None
    return None


def _maskelenecekler() -> list[str]:
    adaylar = set()
    for ortam in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA"):
        deger = os.environ.get(ortam)
        if deger:
            adaylar.add(deger)
    try:
        adaylar.add(str(Path.home()))
    except RuntimeError:
        pass
    for aday in list(adaylar):
        kisa = _kisa_yol(aday)                     # Windows 8.3 biçimi: C:\Users\ADI~1
        if kisa and kisa != aday:
            adaylar.add(kisa)
            adaylar.add(Path(kisa).name if Path(kisa).parent.name.lower() == "users" else "")
    adaylar.discard("")
    kullanici = os.environ.get("USERNAME") or os.environ.get("USER")
    try:
        kullanici = kullanici or Path.home().name
    except RuntimeError:
        pass
    if kullanici and len(kullanici) >= 3:
        adaylar.add(kullanici)
    # Yol biçimleri: ters bölü, düz bölü, JSON içinde çift ters bölü.
    sonuc = set()
    for aday in adaylar:
        for bicim in (aday, aday.replace("\\", "/"), aday.replace("\\", "\\\\")):
            sonuc.add(bicim)
    # Uzun olan önce: ana yol, kullanıcı adından önce değişsin.
    return sorted(sonuc, key=len, reverse=True)


def maskele(metin: str) -> str:
    """Kullanıcı profili yolu ve kullanıcı adı → ``<KULLANICI>`` (büyük/küçük harf duyarsız)."""
    for aday in _maskelenecekler():
        metin = re.sub(re.escape(aday), MASKE, metin, flags=re.IGNORECASE)
    return metin


def gizli_satirlari_cikar(metin: str) -> str:
    return "\n".join(s for s in metin.splitlines() if not _GIZLI_SATIR.search(s))


def _self_test_varsayilan() -> str:
    """Kendi kendini sınamayı AYRI süreçte çalıştırır (kendi geçici veri klasörüyle)."""
    with tempfile.TemporaryDirectory(prefix="tekelstok_destek_") as gecici:
        rapor = Path(gecici) / "self_test.txt"
        if config.is_frozen():
            komut = [sys.executable, "--self-test", str(rapor)]
        else:
            komut = [sys.executable, "-m", "app.main", "--self-test", str(rapor)]
        ortam = dict(os.environ, TEKEL_DATA_DIR=str(Path(gecici) / "veri"),
                     QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
        try:
            sonuc = subprocess.run(
                komut, cwd=str(config.app_base_dir()), env=ortam,
                capture_output=True, timeout=SELF_TEST_ZAMAN_ASIMI,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.TimeoutExpired) as hata:
            return f"Kendi kendini sınama çalıştırılamadı: {hata}"
        if rapor.exists():
            return rapor.read_text(encoding="utf-8", errors="replace")
        return (f"Rapor üretilmedi (çıkış kodu {sonuc.returncode}).\n"
                + sonuc.stdout.decode("utf-8", "replace")[-4000:])


class SupportPackageService:
    def __init__(self, db, settings, system_status, backup) -> None:
        self.db = db
        self.settings = settings
        self.system_status = system_status
        self.backup = backup

    # ===================== İçerik =========================================
    def tablo_sayilari(self) -> dict[str, int]:
        adlar = [r[0] for r in self.db.query(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        return {ad: int(self.db.scalar(f'SELECT COUNT(*) FROM "{ad}"', default=0))
                for ad in adlar}

    def ayarlar(self) -> dict[str, str]:
        """Beyaz liste: yalnızca kullanıcıya açık ayarlar (bölüm tablosu)."""
        from app.core.ayar_bolumleri import AYAR_BOLUMU, ic_mi

        sonuc = {}
        for anahtar in sorted(AYAR_BOLUMU):
            if ic_mi(anahtar) or anahtar.startswith("guvenlik_"):
                continue
            sonuc[anahtar] = maskele(str(self.settings.get(anahtar, "") or ""))
        return sonuc

    def sistem(self, qt_surumu: str = "") -> dict:
        durum = self.backup.status()
        butunluk, derin = self.system_status.tam_denetim()
        return {
            "uygulama": config.APP_NAME,
            "surum": config.APP_VERSION,
            "sema": self.db.schema_version(),
            "paketli": config.is_frozen(),
            "python": sys.version.split()[0],
            "sqlite": sqlite3.sqlite_version,
            "isletim_sistemi": f"{platform.system()} {platform.release()} {platform.version()}",
            "durum": [{"oge": s.baslik, "deger": s.deger, "durum": s.durum}
                      for s in self.system_status.satirlar(qt_surumu, butunluk=butunluk)],
            "uyarilar": self.system_status.uyarilar(),
            "derin_denetim": derin,
            "yedek": {"otomatik": durum["otomatik_sayisi"], "gunluk": durum["gunluk_sayisi"],
                      "diger": durum["elle_sayisi"] - durum["gunluk_sayisi"],
                      "toplam_bayt": durum["toplam_boyut"], "son_yedek_utc": durum["son_yedek_utc"],
                      "son_hata": list(durum["son_hata"]) if durum["son_hata"] else None},
            "tablolar": self.tablo_sayilari(),
        }

    def _json(self, veri) -> str:
        return gizli_satirlari_cikar(maskele(json.dumps(veri, ensure_ascii=False, indent=1)))

    def _loglar(self) -> list[tuple[str, str]]:
        klasor = config.log_file_path().parent
        sonuc = []
        if klasor.exists():
            for yol in sorted(klasor.glob("*.log*")):
                try:
                    metin = yol.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                sonuc.append((f"logs/{yol.name}", gizli_satirlari_cikar(maskele(metin))))
        return sonuc

    def _veritabani_kopyasi(self, hedef: Path) -> None:
        """Anlık görüntü → güvenlik satırları silinir → yollar maskelenir → VACUUM."""
        self.db.backup_to(hedef)
        baglanti = sqlite3.connect(str(hedef))
        try:
            baglanti.execute(r"DELETE FROM settings WHERE key LIKE 'guvenlik\_%' ESCAPE '\'")
            for tablo, anahtar, sutunlar in (("settings", "key", ("value",)),
                                             ("audit_log", "id", ("summary_tr", "details_json"))):
                satirlar = baglanti.execute(
                    f"SELECT {anahtar}, {', '.join(sutunlar)} FROM {tablo}").fetchall()
                for satir in satirlar:
                    yeni = [maskele(d) if isinstance(d, str) else d for d in satir[1:]]
                    if yeni != list(satir[1:]):
                        atama = ", ".join(f"{s} = ?" for s in sutunlar)
                        baglanti.execute(f"UPDATE {tablo} SET {atama} WHERE {anahtar} = ?",
                                         (*yeni, satir[0]))
            baglanti.commit()
            baglanti.execute("VACUUM")
        finally:
            baglanti.close()

    # ===================== Paket ==========================================
    def olustur(
        self,
        hedef: str | Path,
        veritabani_ekle: bool = False,
        tanilama: list[dict] | None = None,
        qt_surumu: str = "",
        self_test: Callable[[], str] | None = None,
    ) -> Path:
        hedef = Path(hedef)
        hedef.parent.mkdir(parents=True, exist_ok=True)
        gecici_zip = hedef.with_suffix(hedef.suffix + ".tmp")
        gecici_db = None
        try:
            rapor = (self_test or _self_test_varsayilan)()
            with zipfile.ZipFile(gecici_zip, "w", zipfile.ZIP_DEFLATED) as paket:
                paket.writestr("sistem.json", self._json(self.sistem(qt_surumu)))
                paket.writestr("ayarlar.json", self._json(self.ayarlar()))
                paket.writestr("tanilama.json", self._json(tanilama or []))
                paket.writestr("self_test.txt", gizli_satirlari_cikar(maskele(rapor)))
                for ad, metin in self._loglar():
                    paket.writestr(ad, metin)
                if veritabani_ekle:
                    fd, ad = tempfile.mkstemp(prefix="tekelstok_destek_", suffix=".db")
                    os.close(fd)
                    gecici_db = Path(ad)
                    gecici_db.unlink()
                    self._veritabani_kopyasi(gecici_db)
                    paket.write(gecici_db, "veritabani.db")
            os.replace(gecici_zip, hedef)
        finally:
            for artik in (gecici_zip, gecici_db):
                if artik is not None:
                    try:
                        artik.unlink(missing_ok=True)
                    except OSError:
                        log.warning("Geçici destek dosyası silinemedi: %s", artik)
        log.info("Destek paketi oluşturuldu: %s (veritabanı: %s)", hedef,
                 "evet" if veritabani_ekle else "hayır")
        return hedef
