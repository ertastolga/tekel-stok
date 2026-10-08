"""Küçük çubuk grafik — harici kütüphane YOK, QPainter ile çizilir.

Saatlik satış 24 satırlık bir tabloda okunmaz; dükkân sahibinin tek bakışta
"akşam yoğunuz" diyebilmesi gerekir. Grafik bilerek SADEDİR: eksen süsü,
ızgara ve animasyon yoktur.

V1.2: isteğe bağlı karşılaştırma serisi (önceki dönem, açık renkli ve dar
çubuk olarak arkada), değer biçimi (TL ya da adet), alt yazı ve döneme uygun
boş veri metni.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.core.money import format_tl
from app.ui import metrics, theme

TL = "TL"
ADET = "ADET"


def _bicimle(deger: int, bicim: str) -> str:
    return format_tl(deger) if bicim == TL else f"{deger:,}".replace(",", ".")


class SimpleBarChart(QWidget):
    """(etiket, değer) çiftlerini dikey çubuk olarak çizer."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: list[tuple[str, int]] = []
        self._comparison: list[int] = []
        self._accent = theme.PRIMARY
        self._bicim = TL
        self._caption = ""
        self._empty_text = "Bu dönemde satış yok"
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_data(
        self,
        data: list[tuple[str, int]],
        accent: str | None = None,
        comparison: list[int] | None = None,
        value_format: str = TL,
        caption: str = "",
        empty_text: str | None = None,
    ) -> None:
        self._data = list(data)
        self._comparison = list(comparison or [])
        if accent:
            self._accent = accent
        self._bicim = value_format
        self._caption = caption
        if empty_text is not None:
            self._empty_text = empty_text
        self.update()

    def data(self) -> list[tuple[str, int]]:
        return list(self._data)

    def comparison(self) -> list[int]:
        return list(self._comparison)

    def paintEvent(self, event) -> None:  # noqa: N802
        boyaci = QPainter(self)
        boyaci.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        boyaci.fillRect(self.rect(), QColor(theme.SURFACE))

        degerler = [deger for _, deger in self._data] + self._comparison
        en_buyuk = max(degerler, default=0)
        if not self._data or en_buyuk <= 0:
            boyaci.setPen(QColor(theme.TEXT_MUTED))
            boyaci.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                            self._empty_text if self._data else "Henüz veri yok")
            boyaci.end()
            return

        etiket_yuksekligi = 18
        alt_yazi = 16 if self._caption else 0
        ust_bosluk = 18
        alan_yuksekligi = self.height() - etiket_yuksekligi - ust_bosluk - alt_yazi
        adet = len(self._data)
        sutun_genisligi = self.width() / adet
        cubuk_genisligi = max(3.0, sutun_genisligi * 0.62)

        boyaci.setFont(theme.base_font(metrics.FONT_SMALL_PT - 1.5))
        seyrek = max(1, (adet + 11) // 12)
        for index, (etiket, deger) in enumerate(self._data):
            x0 = index * sutun_genisligi
            if index < len(self._comparison) and self._comparison[index] > 0:
                oran = self._comparison[index] / en_buyuk
                yukseklik = alan_yuksekligi * oran
                genislik = cubuk_genisligi * 1.25
                boyaci.fillRect(
                    QRectF(x0 + (sutun_genisligi - genislik) / 2,
                           ust_bosluk + alan_yuksekligi - yukseklik, genislik, yukseklik),
                    QColor(theme.BORDER))
            oran = max(0.0, deger / en_buyuk)
            yukseklik = alan_yuksekligi * oran
            x = x0 + (sutun_genisligi - cubuk_genisligi) / 2
            y = ust_bosluk + (alan_yuksekligi - yukseklik)
            renk = QColor(self._accent) if deger > 0 else QColor(theme.BORDER)
            boyaci.fillRect(QRectF(x, y, cubuk_genisligi, max(2.0, yukseklik)), renk)

            # Etiketler kalabalıklaşırsa seyreltilir (en çok ~12 etiket).
            if index % seyrek == 0:
                boyaci.setPen(QColor(theme.TEXT_MUTED))
                boyaci.drawText(
                    QRectF(x0, self.height() - etiket_yuksekligi - alt_yazi,
                           sutun_genisligi * seyrek, etiket_yuksekligi),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, etiket)

        # Ölçek bilgisi. En yüksek çubuk sağda olabileceği için SOL üste yazılır
        # ve altına zemin çizilir: çubuğun üstüne binip okunmaz hâle gelmesin.
        metin = f"en yüksek: {_bicimle(en_buyuk, self._bicim)}"
        if self._comparison:
            metin += "   (gri: önceki dönem)"
        kutu = QRectF(2, 1, boyaci.fontMetrics().horizontalAdvance(metin) + 10, 16)
        boyaci.fillRect(kutu, QColor(theme.SURFACE))
        boyaci.setPen(QColor(theme.TEXT_MUTED))
        boyaci.drawText(kutu, Qt.AlignmentFlag.AlignCenter, metin)
        if self._caption:
            boyaci.drawText(QRectF(0, self.height() - alt_yazi, self.width(), alt_yazi),
                            Qt.AlignmentFlag.AlignCenter, self._caption)
        boyaci.end()
