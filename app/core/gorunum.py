"""Görünüm ayarları (tema, yazı ölçeği, yoğunluk) — açılışta ÖNCEDEN okunur.

Tema ve ölçüler pencereler kurulmadan ÖNCE bilinmelidir; bu yüzden ayarlar,
veritabanı açılıp göç yapılmadan, dosyaya SALT OKUNUR bir bakışla okunur.
Okunamazsa (dosya yok, eski/bozuk veri, kilit) sessizce varsayılana dönülür:
Açık tema, %100, Normal. Değişiklikler yeniden başlatınca uygulanır.

Bu modül Qt bilmez.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

ACIK = "LIGHT"
KOYU = "DARK"
TEMALAR: dict[str, str] = {ACIK: "Açık", KOYU: "Koyu"}
OLCEKLER: tuple[int, ...] = (100, 110, 120, 130)
NORMAL = "NORMAL"
RAHAT = "RAHAT"
YOGUNLUKLAR: dict[str, str] = {NORMAL: "Normal", RAHAT: "Rahat (daha geniş aralıklar)"}
ANAHTARLAR = ("theme", "font_scale", "density")


@dataclass(frozen=True, slots=True)
class Gorunum:
    tema: str = ACIK
    olcek: int = 100
    yogunluk: str = NORMAL


def dogrula(tema, olcek, yogunluk) -> Gorunum:
    """Bilinmeyen değerler varsayılana döner (bozuk ayar uygulamayı açtırmaz)."""
    try:
        olcek_sayi = int(olcek)
    except (TypeError, ValueError):
        olcek_sayi = 100
    return Gorunum(
        tema if tema in TEMALAR else ACIK,
        olcek_sayi if olcek_sayi in OLCEKLER else 100,
        yogunluk if yogunluk in YOGUNLUKLAR else NORMAL,
    )


def oku(db_yolu: str | Path) -> Gorunum:
    """Veritabanından SALT OKUNUR bakış; hiçbir şey yazmaz, göç yapmaz."""
    from app.core.db import salt_okunur_uri

    yol = Path(db_yolu)
    if not yol.exists():
        return Gorunum()
    try:
        baglanti = sqlite3.connect(salt_okunur_uri(yol), uri=True, timeout=1.0)
        try:
            satirlar = dict(baglanti.execute(
                "SELECT key, value FROM settings WHERE key IN (?,?,?)", ANAHTARLAR
            ).fetchall())
        finally:
            baglanti.close()
    except sqlite3.Error:
        return Gorunum()
    return dogrula(satirlar.get("theme", ACIK), satirlar.get("font_scale", 100),
                   satirlar.get("density", NORMAL))
