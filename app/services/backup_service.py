"""Yedekleme ve geri yükleme (V1.2 M10a: yedek motoru, plan §5.11).

Çalışan bir SQLite dosyasını kopyalamak WAL yüzünden BOZUK yedek üretebilir;
bu yüzden her yedek SQLite yedekleme API'si ile, AYRI ve salt okunur bir
bağlantıdan alınır (``Database.backup_to``). Açık bir işlem varken yedek
alınmaz; yedekleme hiçbir zaman satışı engellemez.

Yedek türleri dosya adından KESİN olarak tanınır (tanınmayan ``.db`` dosyası
listelenmez ve ASLA silinmez):

=====================  ======================================  ===========================
Tür                    Ad                                      Otomatik silinir mi?
=====================  ======================================  ===========================
OTOMATIK               otomatik_<kurulum>_YYYYaaGG_SSddss.db   EVET — en yeni N kuşak kalır
GUNLUK                 gunluk_<kurulum>_<iş günü>.db           EVET — en yeni N gün kalır
ICE_AKTARMA_ONCESI     ice_aktarma_oncesi_…                    EVET — en yeni 10 kalır
GUNCELLEME_ONCESI      guncelleme_oncesi_vA_vB_…               HAYIR
PIN_SIFIRLAMA_ONCESI   pin_sifirlama_oncesi_…                  HAYIR
GERI_YUKLEME_ONCESI    geri_yukleme_oncesi_…                   HAYIR
GERI_DONUS_ONCESI      geri_donus_oncesi_…                     HAYIR
ELLE                   yedek_…                                 HAYIR
=====================  ======================================  ===========================

Silme kuralları (temkinli):
  * yalnızca BU kurulumun yazdığı ve klasördeki ``.tekelstok_yedekler.json``
    listesinde (ad + boyut) kayıtlı, düzenli dosyalar silinir; V1.1'in kurulum
    kimliksiz ``otomatik_…`` dosyaları yalnızca varsayılan klasörde bizim
    sayılır,
  * sıralama dosya ADINDAKİ zamana göredir (değiştirilme zamanına değil);
    adı 1 günden fazla gelecekte görünen dosyalar sıralamaya ve silmeye girmez,
  * en yeni N asla silinmez ve N'den az dosya varken hiçbir şey silinmez.

Otomatik yedek klasörü değiştirilebilir; klasör yoksa ya da yazılamıyorsa
varsayılana dönülür ve hata kaydedilir (``last_backup_error*``). Yedek almadan
önce disk alanı denetlenir. Elle alınan yedekler ASLA otomatik silinmez.

Geri yükleme 8 adımlı ve geri dönülebilirdir: başarısız olursa çalışan
veritabanı yerine konur, yani kullanıcı verisini kaybetme riski yoktur.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from app import config
from app.core.clock import local_now, now_utc
from app.core.db import GOC_ONCESI_ONEKI, Database, hedef_sema_surumu, salt_okunur_uri
from app.core.errors import YedekHatasi, YedekOkunamadi

log = logging.getLogger(__name__)

#: Yedeğin geçerli sayılması için bulunması gereken tablolar.
_REQUIRED_TABLES = ("products", "sales", "stock_movements", "settings", "schema_meta")

_SQLITE_HEADER = b"SQLite format 3\x00"

# ----- Yedek türleri --------------------------------------------------------
OTOMATIK = "OTOMATIK"
GUNLUK = "GUNLUK"
GUNCELLEME_ONCESI = "GUNCELLEME_ONCESI"
ICE_AKTARMA_ONCESI = "ICE_AKTARMA_ONCESI"
PIN_SIFIRLAMA_ONCESI = "PIN_SIFIRLAMA_ONCESI"
GERI_YUKLEME_ONCESI = "GERI_YUKLEME_ONCESI"
GERI_DONUS_ONCESI = "GERI_DONUS_ONCESI"
ELLE = "ELLE"
TUR_ADLARI: dict[str, str] = {
    OTOMATIK: "Otomatik",
    GUNLUK: "Günlük",
    GUNCELLEME_ONCESI: "Güncelleme öncesi",
    ICE_AKTARMA_ONCESI: "İçe aktarma öncesi",
    PIN_SIFIRLAMA_ONCESI: "PIN sıfırlama öncesi",
    GERI_YUKLEME_ONCESI: "Geri yükleme öncesi",
    GERI_DONUS_ONCESI: "Sürüm geri dönüşü öncesi",
    ELLE: "Elle",
}
GUNLUK_ONEKI = "gunluk_"
ICE_AKTARMA_ONEKI = "ice_aktarma_oncesi_"
GERI_DONUS_ONEKI = "geri_donus_oncesi_"
#: İçe aktarma öncesi yedeklerden saklanan en çok sayı.
ICE_AKTARMA_SAKLAMA = 10
MANIFEST = ".tekelstok_yedekler.json"
#: Yedek için gereken boş alan: (veritabanı + WAL) × 1,2 + 50 MB.
_EK_ALAN = 50 * 2**20
#: Bu kadar eski ``.db.tmp`` artıkları yarım kalmış yedektir; temizlenir.
_YETIM_TMP_SANIYE = 10 * 60

_DAMGA = r"(?P<damga>\d{8}_\d{6})(?:_(?P<sira>\d+))?"
_KIMLIK = r"(?P<kimlik>[0-9a-f]{8})"
_TUR_DESENLERI: list[tuple[str, re.Pattern]] = [
    (OTOMATIK, re.compile(rf"^{config.AUTO_BACKUP_PREFIX}(?:{_KIMLIK}_)?{_DAMGA}\.db$")),
    (GUNLUK, re.compile(
        rf"^{GUNLUK_ONEKI}{_KIMLIK}_(?P<gun>\d{{4}}-\d{{2}}-\d{{2}})(?:_(?P<sira>\d+))?\.db$")),
    (GUNCELLEME_ONCESI, re.compile(rf"^{GOC_ONCESI_ONEKI}v\d+_v\d+_{_DAMGA}\.db$")),
    (ICE_AKTARMA_ONCESI, re.compile(rf"^{ICE_AKTARMA_ONEKI}{_DAMGA}\.db$")),
    (PIN_SIFIRLAMA_ONCESI, re.compile(rf"^{config.PRE_PIN_RESET_PREFIX}{_DAMGA}\.db$")),
    (GERI_YUKLEME_ONCESI, re.compile(rf"^{config.PRE_RESTORE_PREFIX}{_DAMGA}\.db$")),
    (GERI_DONUS_ONCESI, re.compile(rf"^{GERI_DONUS_ONEKI}{_DAMGA}\.db$")),
    (ELLE, re.compile(rf"^{config.MANUAL_BACKUP_PREFIX}{_DAMGA}\.db$")),
]


def yedek_turu(ad: str) -> tuple[str, re.Match] | None:
    """Dosya adından yedek türü (kesin desen); tanınmayan ad → ``None``."""
    for tur, desen in _TUR_DESENLERI:
        eslesme = desen.match(ad)
        if eslesme:
            return tur, eslesme
    return None


def _ad_zamani(eslesme: re.Match) -> tuple[datetime, int] | None:
    """Addaki zaman (sıralama anahtarı) ve aynı saniyedeki sıra numarası."""
    try:
        if "gun" in eslesme.groupdict() and eslesme.group("gun"):
            zaman = datetime.strptime(eslesme.group("gun"), "%Y-%m-%d")
        else:
            zaman = datetime.strptime(eslesme.group("damga"), "%Y%m%d_%H%M%S")
    except (ValueError, IndexError):
        return None
    return zaman, int(eslesme.group("sira") or 0)


@dataclass(frozen=True, slots=True)
class BackupInfo:
    """Bir yedek dosyasının kullanıcıya gösterilecek özeti."""

    path: Path
    created_at: datetime
    size_bytes: int
    kind: str = ELLE
    product_count: int = 0
    sale_count: int = 0
    schema_version: int = 0

    @property
    def is_auto(self) -> bool:
        """Yalnızca kayan otomatik yedekler (saklama sınırıyla silinenler)."""
        return self.kind == OTOMATIK

    @property
    def display_name(self) -> str:
        return f"{TUR_ADLARI.get(self.kind, 'Yedek')} · {self.created_at.strftime('%d.%m.%Y %H:%M')}"


class BackupService:
    def __init__(self, db: Database, settings) -> None:
        self.db = db
        self.settings = settings
        #: Bu süreçte oluşturulan dosyalar (silme adayı olmaz).
        self._bu_surecte: set[Path] = set()

    # ===================== Kurulum kimliği ===============================
    def install_id(self) -> str:
        """Bu kuruluma özgü 8 haneli kimlik (yönetilen yedek adlarında)."""
        kimlik = self.db.meta("install_id")
        if not kimlik:
            kimlik = uuid.uuid4().hex
            self.db.set_meta("install_id", kimlik)
        return kimlik[:8]

    # ===================== Klasörler =====================================
    @staticmethod
    def default_auto_dir() -> Path:
        return config.auto_backup_dir()

    def auto_dir_problem(self, yol: str | Path) -> str | None:
        """Otomatik yedek klasörü olarak kullanılabilir mi? Değilse neden."""
        hedef = Path(yol).resolve()
        veri = config.data_dir().resolve()
        if hedef == veri or veri.is_relative_to(hedef):
            return "Veri klasörünün kendisi ya da onu içeren bir klasör seçilemez."
        if hedef == self.manual_dir().resolve():
            return "Elle alınan yedeklerin klasöründen farklı bir klasör seçin."
        try:
            hedef.mkdir(parents=True, exist_ok=True)
            deneme = hedef / f".yazma_denemesi_{uuid.uuid4().hex[:6]}"
            deneme.write_bytes(b"")
            deneme.unlink()
        except OSError as hata:
            return f"Klasöre yazılamıyor: {hata}"
        return None

    def auto_dir(self) -> Path:
        """Otomatik/günlük yedek klasörü; ayar kullanılamıyorsa varsayılan."""
        ozel = (self.settings.get("auto_backup_dir", "") or "").strip()
        if not ozel:
            return self.default_auto_dir()
        sorun = self.auto_dir_problem(ozel)
        if sorun is None:
            return Path(ozel)
        self._hata_kaydet(f"Otomatik yedek klasörü kullanılamadı ({ozel}): {sorun} "
                          "Varsayılan klasör kullanıldı.")
        return self.default_auto_dir()

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

        Alınamazsa ``YedekHatasi`` yükselir ve çağıran işlemi YAPMAZ. İçe
        aktarma öncesi yedeklerden en yeni 10 tanesi saklanır; diğer güvenlik
        yedekleri ASLA otomatik silinmez.
        """
        klasor = self.manual_dir()
        hedef = self._new_path(klasor, prefix)
        yol = self._backup_to(hedef, manifest=prefix == ICE_AKTARMA_ONEKI)
        if prefix == ICE_AKTARMA_ONEKI:
            self._sakla(klasor, ICE_AKTARMA_ONCESI, ICE_AKTARMA_SAKLAMA, varsayilan=False)
        return yol

    def create_auto(self) -> Path:
        klasor = self.auto_dir()
        hedef = self._new_path(klasor, f"{config.AUTO_BACKUP_PREFIX}{self.install_id()}_")
        yol = self._backup_to(hedef, manifest=True)
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

    def _gerekli_alan(self) -> int:
        boyut = 0
        for yol in (Path(self.db.path), Path(str(self.db.path) + "-wal")):
            try:
                boyut += yol.stat().st_size
            except OSError:
                pass
        return int(boyut * 1.2) + _EK_ALAN

    def _backup_to(self, hedef: Path, manifest: bool = False) -> Path:
        gerekli = self._gerekli_alan()
        try:
            hedef.parent.mkdir(parents=True, exist_ok=True)
            bos = shutil.disk_usage(hedef.parent).free
        except OSError as exc:
            self._hata_kaydet(f"Yedek klasörüne ulaşılamadı: {hedef.parent}")
            raise YedekHatasi("Yedek alınamadı. Yedek klasörüne ulaşılamıyor.",
                              str(exc)) from exc
        if bos < gerekli:
            mesaj = (f"Yedek için diskte yeterli yer yok: yaklaşık {gerekli // 2**20} MB "
                     f"gerekli, {bos // 2**20} MB boş ({hedef.parent}).")
            self._hata_kaydet(mesaj)
            raise YedekHatasi(mesaj)
        try:
            yol = self.db.backup_to(hedef)
        except (sqlite3.Error, OSError) as exc:
            log.exception("Yedek alınamadı: %s", hedef)
            self._hata_kaydet(f"Yedek alınamadı ({hedef.name}): {exc}")
            raise YedekHatasi(
                "Yedek alınamadı. Yedek klasörüne yazma izni olmayabilir.", str(exc)
            ) from exc

        self._bu_surecte.add(yol.resolve())
        if manifest:
            self._manifest_ekle(yol)
        # Damga defter tutma yazısıdır: veritabanını "değişti" saymamalı,
        # yoksa yedek almak hemen yeni bir yedeği tetiklerdi. Sürüm, ÜRETİLEN
        # dosyadan okunur: yedek o anın TAMAMLANMIŞ verisini taşır.
        self.settings.set_many_quiet(
            {
                "last_backup_at_utc": now_utc(),
                "last_backup_data_version": self._dosya_veri_surumu(yol),
            }
        )
        log.info("Yedek alındı: %s", yol)
        return yol

    def _dosya_veri_surumu(self, yol: Path) -> int:
        try:
            baglanti = sqlite3.connect(salt_okunur_uri(yol), uri=True)
            try:
                satir = baglanti.execute(
                    "SELECT value FROM schema_meta WHERE key = 'data_version'").fetchone()
            finally:
                baglanti.close()
            return int(satir[0]) if satir and satir[0] is not None else 0
        except (sqlite3.Error, ValueError):
            return self.db.data_version()

    def _hata_kaydet(self, mesaj: str) -> None:
        """Son yedek hatası (Sistem Durumu ve durum çubuğu için); asla patlamaz."""
        log.warning("Yedek hatası: %s", mesaj)
        try:
            self.settings.set_many_quiet({"last_backup_error_utc": now_utc(),
                                          "last_backup_error": mesaj[:500]})
        except Exception:
            log.exception("Yedek hatası kaydedilemedi")

    def last_error(self) -> tuple[int, str] | None:
        zaman = self.settings.get_int("last_backup_error_utc", 0)
        return (zaman, self.settings.get("last_backup_error", "") or "") if zaman else None

    # ===================== Manifest ======================================
    @staticmethod
    def _manifest_oku(klasor: Path) -> dict[str, int]:
        try:
            veri = json.loads((klasor / MANIFEST).read_text(encoding="utf-8"))
            return {str(k): int(v) for k, v in veri.get("dosyalar", {}).items()}
        except (OSError, ValueError, AttributeError, TypeError):
            return {}

    def _manifest_yaz(self, klasor: Path, dosyalar: dict[str, int]) -> None:
        yol = klasor / MANIFEST
        gecici = yol.with_suffix(".tmp")
        try:
            gecici.write_text(json.dumps({"surum": 1, "dosyalar": dosyalar},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(gecici, yol)
        except OSError:
            log.warning("Yedek listesi yazılamadı: %s", yol)

    def _manifest_ekle(self, yol: Path) -> None:
        dosyalar = self._manifest_oku(yol.parent)
        try:
            dosyalar[yol.name] = yol.stat().st_size
        except OSError:
            return
        self._manifest_yaz(yol.parent, dosyalar)

    # ===================== Saklama =======================================
    def _yonetilen(self, klasor: Path, tur: str, varsayilan: bool) -> list[tuple]:
        """Silinebilecek adaylar: ((zaman, sıra), yol) — yeniden eskiye."""
        if not klasor.exists():
            return []
        kimlik = self.install_id()
        liste = self._manifest_oku(klasor)
        sinir = local_now() + timedelta(days=1)          # saat dikişi (adlar da ondan)
        adaylar = []
        for yol in klasor.iterdir():
            bilgi = yedek_turu(yol.name)
            if bilgi is None or bilgi[0] != tur:
                continue
            eslesme = bilgi[1]
            try:
                if yol.is_symlink() or not yol.is_file():
                    continue
                boyut = yol.stat().st_size
            except OSError:
                continue
            ad_kimligi = eslesme.groupdict().get("kimlik")
            if ad_kimligi:
                if ad_kimligi != kimlik or liste.get(yol.name) != boyut:
                    continue                      # başka kurulumun ya da kayıtsız
            elif tur == OTOMATIK:
                if not varsayilan:
                    continue                      # V1.1 dosyası yalnızca varsayılan klasörde
            elif liste.get(yol.name) != boyut:
                continue
            zaman = _ad_zamani(eslesme)
            if zaman is None or zaman[0] > sinir:
                continue                          # gelecekte görünen ad: dokunma
            adaylar.append((zaman, yol))
        return sorted(adaylar, key=lambda a: a[0], reverse=True)

    def _sakla(self, klasor: Path, tur: str, sinir: int, varsayilan: bool) -> int:
        """En yeni ``sinir`` kuşak kalır; daha azı varken hiçbir şey silinmez."""
        adaylar = self._yonetilen(klasor, tur, varsayilan)
        if len(adaylar) <= max(1, sinir):
            return 0
        silinen = 0
        liste = self._manifest_oku(klasor)
        for _zaman, yol in adaylar[max(1, sinir):]:
            if yol.resolve() in self._bu_surecte and yol == adaylar[0][1]:
                continue
            try:
                yol.unlink()
                liste.pop(yol.name, None)
                silinen += 1
            except OSError:
                log.warning("Eski yedek silinemedi: %s", yol)
        self._manifest_yaz(klasor, liste)
        return silinen

    def cleanup_auto_backups(self) -> int:
        """Saklama sınırını aşan KAYAN otomatik yedekleri siler (bkz. modül notu)."""
        klasor = self.auto_dir()
        self._yetim_gecicileri_sil(klasor)
        varsayilan = klasor.resolve() == self.default_auto_dir().resolve()
        return self._sakla(klasor, OTOMATIK, self.settings.auto_backup_retention(),
                           varsayilan)

    def _yetim_gecicileri_sil(self, klasor: Path) -> int:
        """Yarım kalmış yedek artıkları (``*.db.tmp``) — yeterince eskiyse."""
        if not klasor.exists():
            return 0
        simdi = datetime.now().timestamp()
        silinen = 0
        for yol in klasor.glob(f"*{config.BACKUP_SUFFIX}.tmp*"):
            try:
                if yol.is_file() and simdi - yol.stat().st_mtime > _YETIM_TMP_SANIYE:
                    yol.unlink()
                    silinen += 1
            except OSError:
                log.warning("Yarım yedek artığı silinemedi: %s", yol)
        return silinen

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
        if not self.auto_backup_due() or self.db.in_transaction:
            return None
        try:
            return self.create_auto()
        except YedekHatasi:
            return None

    # ===================== Günlük yedek ==================================
    def daily_path(self, is_gunu: str | None = None) -> Path:
        gun = is_gunu or self.settings.calendar().today()
        return self.auto_dir() / f"{GUNLUK_ONEKI}{self.install_id()}_{gun}{config.BACKUP_SUFFIX}"

    def daily_backup_required(self) -> bool:
        """Bugünün günlük yedeği gerekli mi? (bugün yok VE son günlükten beri
        veri değişti). Aynı güne ikinci kuşak üretilmez."""
        if self.daily_path().exists():
            return False
        return self.db.data_version() > self.settings.get_int("last_backup_daily_version", -1)

    def create_daily(self) -> Path | None:
        """Gerekliyse bugünün günlük yedeğini alır; değilse ``None``."""
        if not self.daily_backup_required() or self.db.in_transaction:
            return None
        yol = self._backup_to(self.daily_path(), manifest=True)
        self.settings.set_many_quiet(
            {"last_backup_daily_version": self._dosya_veri_surumu(yol)})
        klasor = yol.parent
        varsayilan = klasor.resolve() == self.default_auto_dir().resolve()
        self._sakla(klasor, GUNLUK, self.settings.daily_backup_retention_days(), varsayilan)
        return yol

    # ===================== Listeleme =====================================
    def _list(self, folder: Path, prefix: str = "") -> list[Path]:
        """Klasördeki TANINAN yedekler (en yeni başta, ada göre)."""
        if not folder.exists():
            return []
        dosyalar = []
        for p in folder.glob(f"{prefix}*{config.BACKUP_SUFFIX}"):
            bilgi = yedek_turu(p.name)
            if bilgi is not None and p.is_file():
                dosyalar.append(p)
        return sorted(dosyalar, key=lambda p: p.stat().st_mtime, reverse=True)

    def list_backups(self) -> list[BackupInfo]:
        """Tüm tanınan yedekler, en yenisi başta (tanınmayan .db listelenmez)."""
        sonuc: list[BackupInfo] = []
        klasorler = []
        for klasor in (self.auto_dir(), self.default_auto_dir(), self.manual_dir()):
            if klasor.resolve() not in {k.resolve() for k in klasorler}:
                klasorler.append(klasor)
        for folder in klasorler:
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
                        kind=yedek_turu(dosya.name)[0],
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
            kind=(yedek_turu(kaynak.name) or (ELLE,))[0],
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
        """Ayarlar ve Sistem Durumu ekranında gösterilen yedek durumu."""
        son = self.settings.get_int("last_backup_at_utc", 0)
        yedekler = self.list_backups()

        def bos(klasor: Path) -> int | None:
            try:
                return shutil.disk_usage(_var_olan(klasor)).free
            except OSError:
                return None

        return {
            "son_yedek_utc": son or None,
            "otomatik_sayisi": sum(1 for b in yedekler if b.kind == OTOMATIK),
            "gunluk_sayisi": sum(1 for b in yedekler if b.kind == GUNLUK),
            "elle_sayisi": sum(1 for b in yedekler if not b.is_auto),
            "toplam_boyut": sum(b.size_bytes for b in yedekler),
            "otomatik_klasor": str(self.auto_dir()),
            "elle_klasor": str(self.manual_dir()),
            "bos_alan_veri": bos(config.data_dir()),
            "bos_alan_yedek": bos(self.auto_dir()),
            "son_hata": self.last_error(),
        }


def _var_olan(yol: Path) -> Path:
    while not yol.exists() and yol.parent != yol:
        yol = yol.parent
    return yol
