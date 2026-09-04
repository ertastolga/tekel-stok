"""Yerel log dosyası kurulumu.

Loglar teknik ayrıntı içindir ve dükkân sahibine ASLA gösterilmez. Hata
pencerelerinde yalnızca sade Türkçe mesaj görünür; izler (traceback) buraya
yazılır.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app import config

_configured = False

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_MAX_BYTES = 1_000_000
_BACKUPS = 5


def setup_logging(level: int = logging.INFO) -> None:
    """Kök logger'ı bir kez kurar. Yeniden çağrılması zararsızdır."""
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(level)

    try:
        config.logs_dir().mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            config.log_file_path(),
            maxBytes=_MAX_BYTES,
            backupCount=_BACKUPS,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(handler)
    except OSError:
        # Log yazılamıyorsa bile uygulama açılmalıdır: kasa çalışmaya devam eder.
        pass

    # Donmuş (paketlenmiş) pencereli çalışmada stderr None'dur; StreamHandler
    # eklemek orada çökme sebebidir.
    if not config.is_frozen() and sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter(_FORMAT))
        root.addHandler(stream)

    _configured = True


def reset_for_tests() -> None:
    """Testlerin log kurulumunu yeniden yapabilmesi için."""
    global _configured
    _configured = False
