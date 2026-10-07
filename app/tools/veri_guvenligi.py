"""Geliştirici araçları için veri güvenliği kapısı.

Ekran görüntüsü, sentetik veri ve ölçüm araçları GERÇEK dükkân verisine asla
dokunmamalıdır. Bu araçlar çalışmaya başlamadan önce ``karalama_klasoru()``
çağırır; ``TEKEL_DATA_DIR`` ayarlı değilse ya da sahibin gerçek veri klasörünü
(``%LOCALAPPDATA%\\TekelStok``) gösteriyorsa çalışmayı REDDEDER.

Bu modül ürün davranışını değiştirmez; yalnızca araçlar tarafından kullanılır.
"""
from __future__ import annotations

import os
from pathlib import Path

from app import config


class GercekVeriKlasoruHatasi(RuntimeError):
    """Araç gerçek veri klasörüyle çalıştırılmak istendi."""


def gercek_veri_klasoru() -> Path | None:
    """Sahibin varsayılan (gerçek) veri klasörü; belirlenemiyorsa ``None``."""
    yerel = os.environ.get("LOCALAPPDATA")
    if not yerel:
        return None
    return (Path(yerel) / config.APP_DIR_NAME).resolve()


def karalama_klasoru() -> Path:
    """Doğrulanmış karalama veri klasörünü döner; aksi hâlde hata verir."""
    deger = os.environ.get(config.ENV_DATA_DIR, "").strip()
    if not deger:
        raise GercekVeriKlasoruHatasi(
            f"{config.ENV_DATA_DIR} bir karalama klasörüne ayarlanmalı; "
            "araçlar gerçek veri klasörüyle çalışmaz."
        )
    yol = Path(deger).expanduser().resolve()
    gercek = gercek_veri_klasoru()
    if gercek is not None and (yol == gercek or gercek in yol.parents):
        raise GercekVeriKlasoruHatasi(
            "Bu araç sahibin gerçek veri klasörüyle çalıştırılamaz."
        )
    return yol
