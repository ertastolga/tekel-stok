"""Küçük çubuk grafik — harici kütüphane YOK, QPainter ile çizilir.

Saatlik satış 24 satırlık bir tabloda okunmaz; dükkân sahibinin tek bakışta
"akşam yoğunuz" diyebilmesi gerekir. Grafik bilerek SADEDİR: eksen süsü,
ızgara ve animasyon yoktur.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.core.money import format_tl
from app.ui import metrics, theme


class SimpleBarChart(QWidget):
    """(etiket, değer) çiftlerini dikey çubuk olarak çizer."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: list[tuple[str, int]] = []
        self._accent = theme.PRIMARY
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(self, data: list[tuple[str, int]], accent: str | None = None) -> None:
        self._data = list(data)
        if accent:
            self._accent = accent
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        boyaci = QPainter(self)
        boyaci.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        boyaci.fillRect(self.rect(), QColor(theme.SURFACE))

        if not self._data:
            boyaci.setPen(QColor(theme.TEXT_MUTED))
            boyaci.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Henüz veri yok"
            )
            return

        en_buyuk = max((deger for _, deger in self._data), default=0)
        if en_buyuk <= 0:
            boyaci.setPen(QColor(theme.TEXT_MUTED))
            boyaci.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "Bugün henüz satış yok"
            )
            return

        etiket_yuksekligi = 18
        ust_bosluk = 6
        alan_yuksekligi = self.height() - etiket_yuksekligi - ust_bosluk
        adet = len(self._data)
        sutun_genisligi = self.width() / adet
        cubuk_genisligi = max(3.0, sutun_genisligi * 0.62)

        boyaci.setFont(theme.base_font(metrics.FONT_SMALL_PT - 1.5))
        for index, (etiket, deger) in enumerate(self._data):
            oran = max(0.0, deger / en_buyuk)
            yukseklik = alan_yuksekligi * oran
            x = index * sutun_genisligi + (sutun_genisligi - cubuk_genisligi) / 2
            y = ust_bosluk + (alan_yuksekligi - yukseklik)

            renk = QColor(self._accent)
            if deger <= 0:
                renk = QColor(theme.BORDER)
            boyaci.fillRect(
                QRectF(x, y, cubuk_genisligi, max(2.0, yukseklik)), renk
            )

            # Etiketler kalabalıklaşırsa seyreltilir (24 saatte her ikinciyi yaz).
            yaz = adet <= 12 or index % 2 == 0
            if yaz:
                boyaci.setPen(QColor(theme.TEXT_MUTED))
                boyaci.drawText(
                    QRectF(
                        index * sutun_genisligi,
                        self.height() - etiket_yuksekligi,
                        sutun_genisligi,
                        etiket_yuksekligi,
                    ),
                    Qt.AlignmentFlag.AlignCenter,
                    etiket,
                )

        # Ölçek bilgisi. En yüksek çubuk sağda olabileceği için SOL üste yazılır
        # ve altına zemin çizilir: çubuğun üstüne binip okunmaz hâle gelmesin.
        metin = f"en yüksek: {format_tl(en_buyuk)}"
        kutu = QRectF(2, 1, boyaci.fontMetrics().horizontalAdvance(metin) + 10, 16)
        boyaci.fillRect(kutu, QColor(theme.SURFACE))
        boyaci.setPen(QColor(theme.TEXT_MUTED))
        boyaci.drawText(kutu, Qt.AlignmentFlag.AlignCenter, metin)
        boyaci.end()
