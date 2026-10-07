"""Uygulama kimliği ve dosya yolları.

Yol çözümlemesinin TEK kaynağı burasıdır. Testler ve ``--self-test`` yalnızca
``TEKEL_DATA_DIR`` ortam değişkenini ayarlayarak tüm veriyi geçici bir klasöre
yönlendirebilir; böylece hiçbir test kullanıcının gerçek verisine dokunamaz.

Klasör adı bilerek ASCII'dir (``TekelStok``): görünen ad Türkçe olsa da diskteki
yol, kodlama sorunu çıkarabilecek karakterler içermez.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Tekel Stok"
APP_VERSION = "1.2.0.dev0"
APP_DIR_NAME = "TekelStok"          # diskteki klasör adı — ASCII kalmalı
DB_FILE_NAME = "tekelstok.db"

#: Veri klasörünü değiştiren ortam değişkeni (testler, self-test, taşınabilir kip).
ENV_DATA_DIR = "TEKEL_DATA_DIR"

# --- Yedek dosya adı önekleri --------------------------------------------
# Önek, yedeğin hangi havuza ait olduğunu belirler. Yalnızca ``otomatik_``
# önekli dosyalar saklama sınırına göre silinir; diğerleri ASLA otomatik
# silinmez.
AUTO_BACKUP_PREFIX = "otomatik_"
MANUAL_BACKUP_PREFIX = "yedek_"
PRE_RESTORE_PREFIX = "geri_yukleme_oncesi_"
PRE_RESET_PREFIX = "sifirlama_oncesi_"
#: ``--yonetici-pin-sifirla`` öncesi zorunlu yedek (ASLA otomatik silinmez).
PRE_PIN_RESET_PREFIX = "pin_sifirlama_oncesi_"
BACKUP_SUFFIX = ".db"

MANUAL_BACKUP_DIR_NAME = "Tekel Stok Yedekleri"


def is_frozen() -> bool:
    """PyInstaller ile paketlenmiş hâlde mi çalışıyoruz?"""
    return bool(getattr(sys, "frozen", False))


def app_base_dir() -> Path:
    """Çalıştırılabilir dosyanın (veya proje kökünün) bulunduğu klasör.

    Bilerek ``sys._MEIPASS`` KULLANILMAZ: onefile kipinde orası her açılışta
    silinen geçici bir klasördür ve oraya veri yazmak veri kaybı demektir.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    """Paketle birlikte gelen SALT OKUNUR varlıkların yolu (ikon vb.)."""
    if is_frozen():
        base = Path(getattr(sys, "_MEIPASS", app_base_dir()))
    else:
        base = app_base_dir()
    return base.joinpath(*parts)


def base_root() -> Path:
    """Tüm yazılabilir verinin kökü.

    Öncelik sırası:
      1. ``TEKEL_DATA_DIR`` ortam değişkeni  (testler / self-test)
      2. exe yanında ``portable.txt`` varsa  ``<exe klasörü>/veri``
      3. ``%LOCALAPPDATA%/TekelStok``
    """
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        return Path(override).expanduser()

    if is_frozen() and (app_base_dir() / "portable.txt").exists():
        return app_base_dir() / "veri"

    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_DIR_NAME
    return Path.home() / "AppData" / "Local" / APP_DIR_NAME


def data_dir() -> Path:
    return base_root()


def db_path() -> Path:
    return data_dir() / DB_FILE_NAME


def logs_dir() -> Path:
    return data_dir() / "logs"


def log_file_path() -> Path:
    return logs_dir() / "app.log"


def auto_backup_dir() -> Path:
    return data_dir() / "backups"


def default_manual_backup_dir() -> Path:
    """Elle alınan yedeklerin varsayılan klasörü: Belgeler altında.

    ``TEKEL_DATA_DIR`` ayarlıysa (test/self-test) Belgeler'e ASLA dokunulmaz;
    yedekler de o geçici kökün altında kalır.
    """
    if os.environ.get(ENV_DATA_DIR):
        return base_root() / MANUAL_BACKUP_DIR_NAME

    profile = os.environ.get("USERPROFILE")
    home = Path(profile) if profile else Path.home()
    for name in ("Documents", "Belgeler"):
        candidate = home / name
        if candidate.exists():
            return candidate / MANUAL_BACKUP_DIR_NAME
    return home / "Documents" / MANUAL_BACKUP_DIR_NAME
