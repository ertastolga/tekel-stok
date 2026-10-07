"""Sürüm geri dönüşü: yükseltilmiş veriyi ESKİ sürümün yedeğiyle değiştirir.

``TekelStok.exe --surum-geri-donus <yedek.db>`` ile çalışır. Amaç, yeni sürüme
geçtikten sonra önceki sürüme (ör. V1.1) dönmek isteyen dükkân sahibine güvenli
bir yol vermektir: V1.1, daha yeni bir şemayı tanıyıp reddedemez; bu yüzden eski
exe ASLA yükseltilmiş bir veritabanıyla çalıştırılmamalıdır.

Sıra bilinçlidir ve her adım geri dönülebilirdir:
  1. Seçilen yedek SALT OKUNUR doğrulanır: SQLite, bütünlük, gerekli tablolar,
     ``1 <= şema < güncel`` (yalnızca daha ESKİ bir sürümün yedeği kabul edilir).
  2. Mevcut veritabanı SQLite yedekleme API'siyle ``geri_donus_oncesi_*.db``
     olarak kopyalanır ve doğrulanır (ham dosya kopyası DEĞİL: WAL içeriği dahil).
  3. Yedek geçici dosyaya kopyalanır ve atomik olarak yerine konur.
  4. Eskimiş ``-wal``/``-shm`` yan dosyaları silinir.

Veritabanı bu araçla AÇILMAZ ve GÜNCELLENMEZ: sonuç dosyası, seçilen yedeğin
birebir kopyasıdır. Kaynak yedek dosyası hiç değiştirilmez.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from app.core.clock import local_now
from app.core.db import hedef_sema_surumu, salt_okunur_uri
from app.core.errors import YedekHatasi, YedekOkunamadi

log = logging.getLogger(__name__)

GERI_DONUS_ONEKI = "geri_donus_oncesi_"

_SQLITE_HEADER = b"SQLite format 3\x00"
_GEREKLI_TABLOLAR = ("products", "sales", "stock_movements", "settings", "schema_meta")


@dataclass(frozen=True, slots=True)
class GeriDonusSonucu:
    """Tamamlanan geri dönüşün özeti (kullanıcıya gösterilir)."""

    yedek_semasi: int
    onceki_veri_kopyasi: Path | None


def yedek_semasini_dogrula(yedek: str | Path) -> int:
    """Yedeği salt okunur doğrular ve şema sürümünü döner.

    Yalnızca DAHA ESKİ bir sürümün yedeği kabul edilir: güncel sürümün yedeği
    için normal "Yedekten geri yükle" kullanılır.
    """
    kaynak = Path(yedek)
    if not kaynak.is_file():
        raise YedekOkunamadi(f"dosya yok: {kaynak}")
    try:
        with kaynak.open("rb") as f:
            if f.read(16) != _SQLITE_HEADER:
                raise YedekOkunamadi("SQLite başlığı yok")
    except OSError as exc:
        raise YedekOkunamadi(str(exc)) from exc

    conn = None
    try:
        conn = sqlite3.connect(salt_okunur_uri(kaynak), uri=True)
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise YedekOkunamadi("bütünlük denetimi başarısız")
        tablolar = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        eksik = set(_GEREKLI_TABLOLAR) - tablolar
        if eksik:
            raise YedekOkunamadi(f"eksik tablolar: {sorted(eksik)}")
        satir = conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        surum = int(satir[0]) if satir else 0
    except sqlite3.Error as exc:
        raise YedekOkunamadi(str(exc)) from exc
    finally:
        if conn is not None:
            conn.close()

    guncel = hedef_sema_surumu()
    if not 1 <= surum < guncel:
        raise YedekHatasi(
            "Bu yedek önceki bir sürüme ait değil. Sürüm geri dönüşü yalnızca "
            "güncellemeden ÖNCE alınmış bir yedekle yapılabilir "
            "(adı genellikle 'guncelleme_oncesi_' ile başlar). "
            "Verileriniz değiştirilmedi.",
            f"yedek şeması {surum}, güncel {guncel}",
        )
    return surum


def _yedekleme_api_ile_kopyala(kaynak: Path, hedef: Path) -> None:
    hedef.parent.mkdir(parents=True, exist_ok=True)
    gecici = hedef.with_suffix(hedef.suffix + ".tmp")
    try:
        kaynak_baglanti = sqlite3.connect(str(kaynak))
        try:
            hedef_baglanti = sqlite3.connect(str(gecici))
            try:
                kaynak_baglanti.backup(hedef_baglanti)
                if hedef_baglanti.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise YedekHatasi(detail="geri dönüş öncesi kopya doğrulanamadı")
            finally:
                hedef_baglanti.close()
        finally:
            kaynak_baglanti.close()
        os.replace(gecici, hedef)
    except BaseException:
        gecici.unlink(missing_ok=True)
        raise


def _yan_dosyalari_sil(yol: Path) -> None:
    for ek in ("-wal", "-shm"):
        yan = Path(str(yol) + ek)
        if yan.exists():
            yan.unlink()


def surum_geri_donus(
    yedek: str | Path, canli: str | Path, yedek_klasoru: str | Path
) -> GeriDonusSonucu:
    """Canlı veriyi ESKİ sürümün yedeğiyle değiştirir (bkz. modül açıklaması).

    Uygulamanın kapalı olduğu varsayılır (çağıran tek örnek korumasından sonra
    çağırır). Herhangi bir hata kullanıcı verisini DEĞİŞTİRMEDEN yükseltilir.
    """
    kaynak = Path(yedek)
    canli = Path(canli)
    surum = yedek_semasini_dogrula(kaynak)                      # 1
    if kaynak.resolve() == canli.resolve():
        raise YedekHatasi("Seçilen dosya zaten kullanılan veritabanı.")

    kopya: Path | None = None
    if canli.exists():                                          # 2
        damga = local_now().strftime("%Y%m%d_%H%M%S")
        kopya = Path(yedek_klasoru) / f"{GERI_DONUS_ONEKI}{damga}.db"
        try:
            _yedekleme_api_ile_kopyala(canli, kopya)
        except YedekHatasi:
            raise
        except Exception as exc:
            raise YedekHatasi(
                "Mevcut verinin kopyası alınamadığı için geri dönüş yapılmadı. "
                "Verileriniz değiştirilmedi.",
                str(exc),
            ) from exc

    gecici = canli.with_suffix(canli.suffix + ".geri_donus")
    try:                                                        # 3
        canli.parent.mkdir(parents=True, exist_ok=True)
        with kaynak.open("rb") as oku, gecici.open("wb") as yaz:
            while parca := oku.read(1024 * 1024):
                yaz.write(parca)
            yaz.flush()
            os.fsync(yaz.fileno())
        os.replace(gecici, canli)
    except Exception as exc:
        gecici.unlink(missing_ok=True)
        raise YedekHatasi(
            "Geri dönüş tamamlanamadı. Verileriniz değiştirilmedi.", str(exc)
        ) from exc
    _yan_dosyalari_sil(canli)                                   # 4

    log.warning(
        "Sürüm geri dönüşü: %s → %s (şema %s); önceki veri: %s",
        kaynak, canli, surum, kopya,
    )
    return GeriDonusSonucu(yedek_semasi=surum, onceki_veri_kopyasi=kopya)
