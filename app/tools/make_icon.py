"""Uygulama ikonunu üretir (harici kütüphane olmadan, Qt ile).

Basit ama tanınabilir bir simge: yeşil zemin üzerine barkod çizgileri.
"""
from __future__ import annotations

import sys
from pathlib import Path

BOYUTLAR = (16, 24, 32, 48, 64, 128, 256)


def make_icon(hedef: Path | None = None) -> Path:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        QApplication([])

    kok = Path(__file__).resolve().parent.parent.parent
    hedef = hedef or (kok / "resources" / "icon.ico")
    hedef.parent.mkdir(parents=True, exist_ok=True)

    ikon = QIcon()
    for boyut in BOYUTLAR:
        resim = QPixmap(boyut, boyut)
        resim.fill(QColor("#1B7F4C"))
        boyaci = QPainter(resim)
        boyaci.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        boyaci.setPen(Qt.PenStyle.NoPen)
        boyaci.setBrush(QColor("#FFFFFF"))

        # Barkod çizgileri: kalınlıkları değişken, gerçek bir barkoda benzesin.
        kenar = max(2, boyut // 8)
        alan = boyut - 2 * kenar
        desen = (2, 1, 1, 3, 1, 2, 1, 1)
        toplam = sum(desen) + len(desen)          # çubuklar + aralar
        birim = max(1, alan // toplam)
        x = kenar
        for genislik in desen:
            boyaci.drawRect(x, kenar, birim * genislik, alan)
            x += birim * genislik + birim
        boyaci.end()
        ikon.addPixmap(resim)

    # QIcon doğrudan .ico yazamaz; en büyük boyut PNG olarak da saklanır.
    en_buyuk = ikon.pixmap(256, 256)
    en_buyuk.save(str(hedef.with_suffix(".png")), "PNG")
    if not en_buyuk.save(str(hedef), "ICO"):
        # Bazı Qt derlemelerinde ICO eklentisi yoktur; PNG yeterlidir.
        print("ICO yazılamadı, PNG üretildi:", hedef.with_suffix(".png"))
        return hedef.with_suffix(".png")
    print("İkon üretildi:", hedef)
    return hedef


if __name__ == "__main__":
    make_icon()
    sys.exit(0)
