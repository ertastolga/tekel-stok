"""Dokunmatik sepet satırı.

Her satır bir ürünü ve onun miktar denetimlerini taşır. Hedef cihaz klavyesiz
bir dokunmatik terminal olduğu için tüm hedefler en az 56 px'tir ve fare
hassasiyeti gerektirmez.

Bu gereç **yalnızca çizer ve sinyal yayar**. Miktar mantığı burada DEĞİLDİR:
sayfa, sinyali alıp ``Cart.set_quantity()`` çağırır. Böylece miktar kuralı tek
yerde kalır (``cart_service.py``) ve kopyalanmaz.

Genişlik notu: satıra ``setMinimumWidth`` VERİLMEZ. Yerleşim testi sepet
ekranını 1000x600'de de sınıyor; menü düşünce ~776 px kalıyor. Ürün adı
gerekirse kısaltılır (elide), düğmeler sabit kare kalır.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.money import format_tl
from app.ui import metrics, theme
from app.ui.widgets.common import make_label


def _touch_button(text: str, object_name: str) -> QPushButton:
    """56x56 kare dokunma hedefi."""
    dugme = QPushButton(text)
    dugme.setObjectName(object_name)
    dugme.setFixedSize(metrics.TOUCH_TARGET_MIN, metrics.TOUCH_TARGET_MIN)
    dugme.setCursor(Qt.CursorShape.PointingHandCursor)
    # Odak almaz: barkod alanı odakta kalsın, okuyucu kesintisiz çalışsın.
    dugme.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return dugme


class CartLineRow(QFrame):
    """Sepetteki tek bir ürün satırı."""

    quantity_changed = Signal(int, int)      # (product_id, yeni_adet)
    remove_requested = Signal(int)           # (product_id)

    def __init__(self, line, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.product_id = int(line.product_id)
        self.setObjectName("cartRow")
        # Düz QFrame alt sınıfı bu bayrak olmadan QSS arka planını ÇİZMEZ.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(metrics.CART_ROW_HEIGHT)

        duzen = QHBoxLayout(self)
        duzen.setContentsMargins(14, 8, 14, 8)
        duzen.setSpacing(10)

        # --- Ad + birim fiyat ---
        metin = QVBoxLayout()
        metin.setSpacing(1)
        self.name_label = make_label("", "cartName")
        self.name_label.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.price_label = make_label("", "cartPrice")
        metin.addWidget(self.name_label)
        metin.addWidget(self.price_label)
        duzen.addLayout(metin, 1)

        # --- Adet denetimleri ---
        self.minus_button = _touch_button("−", "touchStep")
        self.minus_button.clicked.connect(self._on_minus)
        duzen.addWidget(self.minus_button)

        self.qty_label = make_label("", "cartQty", align=Qt.AlignmentFlag.AlignCenter)
        self.qty_label.setMinimumWidth(56)
        duzen.addWidget(self.qty_label)

        self.plus_button = _touch_button("+", "touchStep")
        self.plus_button.clicked.connect(self._on_plus)
        duzen.addWidget(self.plus_button)

        # --- Satır tutarı ---
        self.total_label = make_label(
            "", "cartTotal",
            align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        self.total_label.setMinimumWidth(110)
        duzen.addWidget(self.total_label)

        # --- Çıkar ---
        self.remove_button = _touch_button("✕", "touchRemove")
        self.remove_button.setToolTip("Bu ürünü sepetten çıkar")
        self.remove_button.clicked.connect(
            lambda: self.remove_requested.emit(self.product_id)
        )
        duzen.addWidget(self.remove_button)

        self._quantity = 0
        self._price_text = ""
        self._issue: str | None = None
        self.update_line(line)

    # ===================== Güncelleme ====================================
    def update_line(self, line) -> None:
        """Satırı yeniden kurmadan içeriğini tazeler.

        Yüzlerce okutmada tüm liste yeniden kurulmaz; yalnızca bu metot çalışır.
        """
        self._quantity = int(line.quantity)
        self._raw_name = line.product_name
        self._elide_name()
        self._price_text = f"{format_tl(line.unit_price)} / adet"
        self._refresh_price_text()
        self.qty_label.setText(str(self._quantity))
        self.total_label.setText(format_tl(line.line_total))
        # 1 adetteyken eksiye basmak satırı siler — bunu kullanıcıya söyle.
        self.minus_button.setToolTip(
            "Ürünü sepetten çıkar" if self._quantity <= 1 else "Adedi azalt"
        )

    def set_issue(self, text: str | None) -> None:
        """Ödemeden önce çözülmesi gereken sorunu satırda gösterir.

        Örnek: "Fiyat değişti: 80,00 TL → 85,00 TL". ``None`` sorunu kaldırır.
        """
        if text == self._issue:
            return
        self._issue = text
        self._refresh_price_text()

    @property
    def issue_text(self) -> str | None:
        return self._issue

    def _refresh_price_text(self) -> None:
        if self._issue:
            self.price_label.setText(f"⚠ {self._issue}")
            self.price_label.setStyleSheet(
                f"color: {theme.WARNING}; font-weight: 600;"
            )
        else:
            self.price_label.setText(self._price_text)
            self.price_label.setStyleSheet("")

    def set_highlighted(self, highlighted: bool) -> None:
        """Son okutulan satırı kısa süre vurgular."""
        self.setProperty("vurgu", "evet" if highlighted else "hayir")
        self.style().unpolish(self)
        self.style().polish(self)

    # ===================== Olaylar =======================================
    def _on_plus(self) -> None:
        self.quantity_changed.emit(self.product_id, self._quantity + 1)

    def _on_minus(self) -> None:
        # 0'a inince Cart.set_quantity satırı kendisi siler; burada ayrı bir
        # kural yazılmaz.
        self.quantity_changed.emit(self.product_id, self._quantity - 1)

    # ===================== Yerleşim ======================================
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide_name()

    def _elide_name(self) -> None:
        """Uzun ürün adını kısalt: satır asla yatay taşmaz."""
        olcum = QFontMetrics(self.name_label.font())
        genislik = max(60, self.name_label.width())
        self.name_label.setText(
            olcum.elidedText(self._raw_name, Qt.TextElideMode.ElideRight, genislik)
        )
        self.name_label.setToolTip(self._raw_name)
