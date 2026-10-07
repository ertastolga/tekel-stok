"""Yedekleme ve geri yükleme.

Çalışan bir SQLite dosyasını kopyalamak WAL yüzünden BOZUK yedek üretebilir;
bu yüzden her yedek ``Connection.backup()`` (SQLite yedekleme API'si) ile
alınır.

İki ayrı havuz vardır ve dosya adı önekiyle ayrılır:

============  ================================  ==================
Önek          Yer                               Otomatik silinir mi?
============  ================================  ==================
otomatik_     %LOCALAPPDATA%/TekelStok/backups  EVET (saklama sınırı)
yedek_        Belgeler/Tekel Stok Yedekleri     HAYIR
geri_yukleme_oncesi_                      "    HAYIR
sifirlama_oncesi_                         "    HAYIR
============  ================================  ==================

Elle alınan yedekler ASLA otomatik silinmez.

Geri yükleme 8 adımlı ve geri dönülebilirdir: başarısız olursa çalışan
veritabanı yerine konur, yani kullanıcı verisini kaybetme riski yoktur.
"""
from __future__ import annotations

import logging
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app import config
from app.core.clock import local_now, now_utc
from app.core.db import Database, hedef_sema_surumu, salt_okunur_uri
from app.core.errors import YedekHatasi, YedekOkunamadi

log = logging.getLogger(__name__)

#: Yedeğin geçerli sayılması için bulunması gereken tablolar.
_REQUIRED_TABLES = ("products", "sales", "stock_movements", "settings", "schema_meta")

_SQLITE_HEADER = b"SQLite format 3\x00"


@dataclass(frozen=True, slots=True)
class BackupInfo:
    """Bir yedek dosyasının kullanıcıya gösterilecek özeti."""

    path: Path
    created_at: datetime
    size_bytes: int
    is_auto: bool
    product_count: int = 0
    sale_count: int = 0
    schema_version: int = 0

    @property
    def display_name(self) -> str:
        tur = "Otomatik" if self.is_auto else "Elle"
        return f"{tur} · {self.created_at.strftime('%d.%m.%Y %H:%M')}"


class BackupService:
    def __init__(self, db: Database, settings) -> None:
        self.db = db
        self.settings = settings

    # ===================== Klasörler =====================================
    def auto_dir(self) -> Path:
        return config.auto_backup_dir()

    def manual_dir(self) -> Path:
        özel = self.settings.manual_backup_dir()
        return Path(özel) if özel else config.default_manual_backup_dir()

    # ===================== Yedek alma ====================================
    def create_manual(self, note: str | None = None) -> Path:
        """Kullanıcının istediği yedek. Otomatik olarak ASLA silinmez."""
        hedef = self._new_path(self.manual_dir(), config.MANUAL_BACKUP_PREFIX)
        return self._backup_to(hedef)

    def create_safety_backup(self, prefix: str) -> Path:
        """Riskli bir işlemden ÖNCE zorunlu güvenlik yedeği (elle yedek klasörüne).

        Bu yedekler otomatik olarak ASLA silinmez. Alınamazsa ``YedekHatasi``
        yükselir ve çağıran işlemi YAPMAZ.
        """
        hedef = self._new_path(self.manual_dir(), prefix)
        return self._backup_to(hedef)

    def create_auto(self) -> Path:
        hedef = self._new_path(self.auto_dir(), config.AUTO_BACKUP_PREFIX)
        yol = self._backup_to(hedef)
        self.cleanup_auto_backups()
        return yol

    def _new_path(self, folder: Path, prefix: str) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        damga = local_now().strftime("%Y%m%d_%H%M%S")
        aday = folder / f"{prefix}{damga}{config.BACKUP_SUFFIX}"
        sayac = 1
        while aday.exists():
            aday = folder / f"{prefix}{damga}_{sayac}{config.BACKUP_SUFFIX}"
            sayac += 1
        return aday

    def _backup_to(self, hedef: Path) -> Path:
        try:
            yol = self.db.backup_to(hedef)
        except (sqlite3.Error, OSError) as exc:
            log.exception("Yedek alınamadı: %s", hedef)
            raise YedekHatasi(
                "Yedek alınamadı. Yedek klasörüne yazma izni olmayabilir.", str(exc)
            ) from exc

        # Damga defter tutma yazısıdır: veritabanını "değişti" saymamalı,
        # yoksa yedek almak hemen yeni bir yedeği tetiklerdi.
        self.settings.set_many_quiet(
            {
                "last_backup_at_utc": now_utc(),
                "last_backup_data_version": self.db.data_version(),
            }
        )
        log.info("Yedek alındı: %s", yol)
        return yol

    # ===================== Otomatik yedek zamanlaması ====================
    def auto_backup_due(self) -> bool:
        """Otomatik yedek zamanı geldi mi?

        İKİ koşul birden gerekir: yeterli süre geçmiş OLMALI **ve** son
        yedekten beri veri değişmiş olmalı. Böylece dükkân kapalıyken
        açılıp kapanan uygulama boş yere yedek üretmez.
        """
        son_surum = self.settings.get_int("last_backup_data_version", 0)
        if self.db.data_version() <= son_surum:
            return False
        son_zaman = self.settings.get_int("last_backup_at_utc", 0)
        if not son_zaman:
            return True
        aralik = self.settings.auto_backup_interval_minutes() * 60
        return (now_utc() - son_zaman) >= aralik

    def maybe_auto_backup(self) -> Path | None:
        """Açılışta ve kapanışta çağrılır; yalnızca gerekiyorsa yedek alır."""
        if not self.auto_backup_due():
            return None
        try:
            return self.create_auto()
        except YedekHatasi:
            return None

    def cleanup_auto_backups(self) -> int:
        """Saklama sınırını aşan OTOMATİK yedekleri siler.

        Yalnızca ``otomatik_`` önekli dosyalara dokunur; elle alınan yedekler
        ve geri-yükleme-öncesi güvenlik kopyaları ASLA silinmez.
        """
        sinir = self.settings.auto_backup_retention()
        dosyalar = self._list(self.auto_dir(), config.AUTO_BACKUP_PREFIX)
        silinen = 0
        for dosya in dosyalar[sinir:]:
            try:
                dosya.unlink()
                silinen += 1
            except OSError:
                log.warning("Eski yedek silinemedi: %s", dosya)
        return silinen

    # ===================== Listeleme =====================================
    def _list(self, folder: Path, prefix: str = "") -> list[Path]:
        if not folder.exists():
            return []
        dosyalar = [
            p for p in folder.glob(f"{prefix}*{config.BACKUP_SUFFIX}") if p.is_file()
        ]
        return sorted(dosyalar, key=lambda p: p.stat().st_mtime, reverse=True)

    def list_backups(self) -> list[BackupInfo]:
        """Tüm yedekler, en yenisi başta."""
        sonuc: list[BackupInfo] = []
        for folder, otomatik in ((self.auto_dir(), True), (self.manual_dir(), False)):
            for dosya in self._list(folder):
                try:
                    durum = dosya.stat()
                except OSError:
                    continue
                sonuc.append(
                    BackupInfo(
                        path=dosya,
                        created_at=datetime.fromtimestamp(durum.st_mtime),
                        size_bytes=durum.st_size,
                        is_auto=otomatik or dosya.name.startswith(
                            config.AUTO_BACKUP_PREFIX
                        ),
                    )
                )
        return sorted(sonuc, key=lambda b: b.created_at, reverse=True)

    # ===================== Doğrulama =====================================
    def inspect(self, path: str | Path) -> BackupInfo:
        """Yedeği SALT OKUNUR açıp gerçekten kullanılabilir olduğunu doğrular.

        Bozuk ya da yanlış bir dosya, geri yükleme başlamadan ÖNCE elenir.
        """
        kaynak = Path(path)
        if not kaynak.exists():
            raise YedekOkunamadi(f"dosya yok: {kaynak}")
        try:
            with kaynak.open("rb") as f:
                if f.read(16) != _SQLITE_HEADER:
                    raise YedekOkunamadi("SQLite başlığı yok")
        except OSError as exc:
            raise YedekOkunamadi(str(exc)) from exc

        conn = None
        try:
            # Yüzde-kodlu URI: klasör adında ?, #, % olsa da doğru dosya açılır.
            conn = sqlite3.connect(salt_okunur_uri(kaynak), uri=True)
            conn.row_factory = sqlite3.Row
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise YedekOkunamadi("bütünlük denetimi başarısız")

            mevcut = {
                row["name"]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            eksik = set(_REQUIRED_TABLES) - mevcut
            if eksik:
                raise YedekOkunamadi(f"eksik tablolar: {sorted(eksik)}")

            surum_satiri = conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()
            surum = int(surum_satiri["value"]) if surum_satiri else 0
            hedef = hedef_sema_surumu()
            if surum > hedef:
                raise YedekOkunamadi(
                    f"yedek daha yeni bir sürüme ait: {surum} > {hedef}"
                )

            urun = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
            satis = conn.execute(
                "SELECT COUNT(*) FROM sales WHERE entry_type='SALE'"
            ).fetchone()[0]
        except sqlite3.Error as exc:
            raise YedekOkunamadi(str(exc)) from exc
        finally:
            if conn is not None:
                conn.close()

        durum = kaynak.stat()
        return BackupInfo(
            path=kaynak,
            created_at=datetime.fromtimestamp(durum.st_mtime),
            size_bytes=durum.st_size,
            is_auto=kaynak.name.startswith(config.AUTO_BACKUP_PREFIX),
            product_count=urun,
            sale_count=satis,
            schema_version=surum,
        )

    # ===================== Geri yükleme ==================================
    def restore(self, path: str | Path) -> Path:
        """Yedeği geri yükler; GÜVENLİK KOPYASININ yolunu döner.

        Sıra bilinçlidir ve her adım geri dönülebilirdir:
          1. Yedeği salt okunur doğrula (bozuksa hiç başlama)
          2. MEVCUT veritabanının güvenlik kopyasını al (bağlantı hâlâ açıkken)
          3. Checkpoint + bağlantıyı kapat
          4. Geçici dosyaya kopyala, sonra atomik olarak yerine koy
          5. Eskimiş -wal/-shm yan dosyalarını sil (yenisini bozabilirler)
          6. Yeniden aç, bütünlüğü ve şema sürümünü DOĞRULA
          7. Göçleri uygula, eksik ayarları tamamla
          8. Herhangi bir adım patlarsa güvenlik kopyasını geri koy

        Bu yüzden geri yükleme başarısız olsa bile kullanıcı verisi kaybolmaz.
        """
        kaynak = Path(path)
        self.inspect(kaynak)                                   # 1

        canli = Path(self.db.path)
        guvenlik = self._new_path(self.manual_dir(), config.PRE_RESTORE_PREFIX)
        self._backup_to(guvenlik)                              # 2

        try:                                                   # 3
            self.db.checkpoint()
        except sqlite3.Error:
            log.warning("Geri yükleme öncesi checkpoint başarısız", exc_info=True)
        self.db.close()

        gecici = canli.with_suffix(canli.suffix + ".restore")
        try:
            shutil.copyfile(kaynak, gecici)                    # 4
            os.replace(gecici, canli)
            self._remove_sidecars(canli)                       # 5

            self.db.connect()                                  # 6
            if self.db.integrity_check() != "ok":
                raise YedekHatasi("Geri yüklenen veritabanı doğrulanamadı.")
            self.db.seed_settings()                            # 7
            self.settings.invalidate()
        except Exception as exc:                               # 8
            log.exception("Geri yükleme başarısız; güvenlik kopyası geri konuyor")
            self._rollback(canli, guvenlik)
            if isinstance(exc, YedekHatasi):
                raise
            raise YedekHatasi(
                "Geri yükleme tamamlanamadı. Önceki verileriniz korundu.", str(exc)
            ) from exc
        finally:
            if gecici.exists():
                try:
                    gecici.unlink()
                except OSError:
                    pass

        log.info("Yedek geri yüklendi: %s (güvenlik kopyası: %s)", kaynak, guvenlik)
        return guvenlik

    def _rollback(self, canli: Path, guvenlik: Path) -> None:
        try:
            if self.db.is_open:
                self.db.close()
        except Exception:
            log.exception("Geri alma sırasında bağlantı kapatılamadı")
        try:
            if guvenlik.exists():
                shutil.copyfile(guvenlik, canli)
                self._remove_sidecars(canli)
        except OSError:
            log.exception("Güvenlik kopyası geri konulamadı: %s", guvenlik)
        try:
            self.db.connect()
            self.settings.invalidate()
        except Exception:
            log.exception("Geri alma sonrası veritabanı açılamadı")

    @staticmethod
    def _remove_sidecars(canli: Path) -> None:
        """Eski WAL/SHM dosyaları yeni veritabanını bozabilir; silinir."""
        for son_ek in ("-wal", "-shm"):
            yan = Path(str(canli) + son_ek)
            if yan.exists():
                try:
                    yan.unlink()
                except OSError:
                    log.warning("Yan dosya silinemedi: %s", yan)

    # ===================== Özet ==========================================
    def status(self) -> dict:
        """Ayarlar ekranında gösterilen yedek durumu."""
        son = self.settings.get_int("last_backup_at_utc", 0)
        yedekler = self.list_backups()
        return {
            "son_yedek_utc": son or None,
            "otomatik_sayisi": sum(1 for b in yedekler if b.is_auto),
            "elle_sayisi": sum(1 for b in yedekler if not b.is_auto),
            "otomatik_klasor": str(self.auto_dir()),
            "elle_klasor": str(self.manual_dir()),
        }
