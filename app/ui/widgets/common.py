"""Yeniden kullanılan arayüz parçaları.

Buradaki gereçler yalnızca ÇİZER: iş kuralı işletmez, SQL çalıştırmaz, kuruş
biçimlemez (bunun için ``app.core.money`` vardır).
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.tr import tr_sort_key
from app.ui import metrics, theme


def make_label(
    text: str = "",
    object_name: str = "",
    wrap: bool = False,
    align=None,
) -> QLabel:
    """Etiket üreticisi. ``objectName`` stil kancasıdır."""
    label = QLabel(text)
    if object_name:
        label.setObjectName(object_name)
    label.setWordWrap(wrap)
    if align is not None:
        label.setAlignment(align)
    return label


class Card(QFrame):
    """Beyaz, kenarlıklı kutu. İçerik ``self.body`` düzenine eklenir."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        # Düz QWidget/QFrame alt sınıfları, bu bayrak olmadan QSS arka planını
        # ÇİZMEZ; kutular şeffaf görünür.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(
            metrics.CARD_PADDING, metrics.CARD_PADDING,
            metrics.CARD_PADDING, metrics.CARD_PADDING,
        )
        self.body.setSpacing(metrics.CARD_SPACING)


class StatCard(Card):
    """Panel kutucuğu: başlık, büyük değer, küçük ipucu."""

    def __init__(self, title: str, value: str = "-", hint: str = "") -> None:
        super().__init__()
        self.title_label = make_label(title, "cardTitle")
        self.value_label = make_label(value, "cardValue")
        self.hint_label = make_label(hint, "cardHint", wrap=True)
        self.body.addWidget(self.title_label)
        self.body.addWidget(self.value_label)
        self.body.addWidget(self.hint_label)
        # Ipucu satiri BOS OLSA DA yer kaplar: yan yana duran kartlarin
        # buyuk rakamlari ayni hizada dursun diye. Gizlenirse o kart kayar.
        self.hint_label.setMinimumHeight(
            theme.text_height(metrics.FONT_SMALL_PT)
        )

    def set_value(self, value: str, hint: str = "") -> None:
        self.value_label.setText(value)
        self.hint_label.setText(hint)

    def set_accent(self, color: str) -> None:
        self.value_label.setStyleSheet(f"color: {color};")


class ResultBanner(QFrame):
    """Büyük, MODAL OLMAYAN geri bildirim şeridi.

    Başarılı işlemler için pencere AÇILMAZ: kullanıcı her satıştan sonra
    "Tamam"a basmak zorunda kalmamalıdır. Şerit yalnızca bilgi verir ve bir
    sonraki okutmayı engellemez.
    """

    shown = Signal(str)          # kind

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("resultBanner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        duzen = QVBoxLayout(self)
        duzen.setContentsMargins(18, 14, 18, 14)
        duzen.setSpacing(4)
        self.headline = make_label("", "resultHeadline", wrap=True)
        self.detail = make_label("", "resultDetail", wrap=True)
        self.extra = make_label("", "resultDetail", wrap=True)
        duzen.addWidget(self.headline)
        duzen.addWidget(self.detail)
        duzen.addWidget(self.extra)

    def _set(self, kind: str, border: str, background: str,
             headline: str, detail: str = "", extra: str = "") -> None:
        self.setStyleSheet(
            f"#resultBanner {{ border: 2px solid {border}; background: {background}; }}"
        )
        self.headline.setText(headline)
        self.detail.setText(detail)
        self.extra.setText(extra)
        self.detail.setVisible(bool(detail))
        self.extra.setVisible(bool(extra))
        self.shown.emit(kind)

    def show_idle(self, headline: str, detail: str = "") -> None:
        self._set("idle", theme.BORDER, theme.SURFACE, headline, detail)

    def show_success(self, headline: str, detail: str = "", extra: str = "") -> None:
        self._set("success", theme.PRIMARY, theme.PRIMARY_LIGHT, headline, detail, extra)

    def show_stock(self, headline: str, detail: str = "", extra: str = "") -> None:
        self._set("stock", theme.STOCK, theme.STOCK_LIGHT, headline, detail, extra)

    def show_warning(self, headline: str, detail: str = "", extra: str = "") -> None:
        self._set("warning", theme.WARNING, theme.WARNING_LIGHT, headline, detail, extra)

    def show_error(self, headline: str, detail: str = "", extra: str = "") -> None:
        self._set("error", theme.DANGER, theme.DANGER_LIGHT, headline, detail, extra)


class SaleFlash(QFrame):
    """Satış onayı: kısa süre görünen büyük kart.

    Kurallar (bilerek katı):
      * ASLA ``QMessageBox`` / ``exec()`` kullanılmaz,
      * ASLA odak almaz — bir sonraki okutma anında işlenir,
      * TEK gereç ve TEK zamanlayıcı vardır; hızlı okutmalar kart yığmaz.
    """

    expired = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("saleFlash")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        duzen = QVBoxLayout(self)
        duzen.setContentsMargins(18, 14, 18, 14)
        duzen.setSpacing(2)
        self.title = make_label("", "flashLine")
        self.name = make_label("", "flashName", wrap=True)
        self.line = make_label("", "flashLine")
        duzen.addWidget(self.title)
        duzen.addWidget(self.name)
        duzen.addWidget(self.line)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._finish)

    def flash(
        self,
        title: str,
        name: str,
        line: str = "",
        border: str = theme.PRIMARY,
        background: str = theme.PRIMARY_LIGHT,
        duration_ms: int = metrics.SALE_FLASH_MS,
    ) -> None:
        self.setStyleSheet(
            f"#saleFlash {{ border: 2px solid {border}; background: {background}; }}"
            f"#flashName {{ color: {border}; }}"
        )
        self.title.setText(title)
        self.name.setText(name)
        self.line.setText(line)
        self.line.setVisible(bool(line))
        self._timer.start(duration_ms)

    def _finish(self) -> None:
        self.expired.emit()


class EmptyState(QWidget):
    """Boş liste açıklaması: kullanıcıya NE YAPACAĞINI sade Türkçe anlatır."""

    def __init__(self, title: str, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        duzen = QVBoxLayout(self)
        duzen.setAlignment(Qt.AlignmentFlag.AlignCenter)
        duzen.setSpacing(8)
        self.title = make_label(title, "sectionTitle", align=Qt.AlignmentFlag.AlignCenter)
        self.hint = make_label(hint, "cardHint", wrap=True,
                               align=Qt.AlignmentFlag.AlignCenter)
        duzen.addWidget(self.title)
        duzen.addWidget(self.hint)

    def set_text(self, title: str, hint: str = "") -> None:
        self.title.setText(title)
        self.hint.setText(hint)


class Badge(QLabel):
    """Durum rozeti. Renk TEK BAŞINA anlam taşımaz; metin daima yazılır."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("badge")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_state(self, text: str, foreground: str, background: str) -> None:
        self.setText(text)
        self.setStyleSheet(
            f"#badge {{ color: {foreground}; background: {background}; "
            f"border: 1px solid {foreground}; }}"
        )


class PageHeader(QWidget):
    """Sayfa başlığı: nerede olduğumuz her zaman açıkça yazar."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        duzen = QHBoxLayout(self)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, 14, metrics.PAGE_MARGIN_H, 14
        )
        metin = QVBoxLayout()
        metin.setSpacing(2)
        self.title = make_label(title, "pageTitle")
        self.subtitle = make_label(subtitle, "pageSubtitle", wrap=True)
        self.subtitle.setVisible(bool(subtitle))
        metin.addWidget(self.title)
        metin.addWidget(self.subtitle)
        duzen.addLayout(metin)
        duzen.addStretch(1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        duzen.addLayout(self.actions)

    def set_subtitle(self, text: str) -> None:
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)


class ActionCard(QPushButton):
    """Ana ekrandaki büyük eylem kartı.

    Fare hassasiyeti gerektirmeyecek kadar büyüktür ve DAİMA Türkçe metin
    taşır — yalnızca simge KULLANILMAZ.
    """

    def __init__(
        self,
        icon: str,
        title: str,
        hint: str = "",
        primary: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("actionCardPrimary" if primary else "actionCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        duzen = QVBoxLayout(self)
        duzen.setContentsMargins(18, 16, 18, 16)
        duzen.setSpacing(6)

        baslik = make_label(f"{icon}  {title}")
        baslik.setFont(theme.base_font(metrics.FONT_ACTION_TITLE_PT, bold=True))
        duzen.addWidget(baslik)

        if hint:
            ipucu = make_label(hint, wrap=True)
            ipucu.setFont(theme.base_font(metrics.FONT_ACTION_HINT_PT))
            ipucu.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            duzen.addWidget(ipucu)
        duzen.addStretch(1)


# ===================== Tablo yardımcıları ================================
def setup_table(table: QTableWidget, headers: list[str]) -> None:
    """Tabloyu okunur ve tutarlı hâle getirir."""
    table.setColumnCount(len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(metrics.TABLE_ROW_HEIGHT)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents
    )


def column_index(table: QTableWidget, header: str) -> int:
    """Sütuna BAŞLIK METNİYLE erişir; sütun sırası değişince kod bozulmaz."""
    for i in range(table.columnCount()):
        item = table.horizontalHeaderItem(i)
        if item is not None and item.text() == header:
            return i
    return -1


def stretch_column(table: QTableWidget, header: str) -> None:
    """Bu sutunu genislet, digerlerini iceriklerine gore sikistir.

    ``setStretchLastSection`` kapatilir: acik kalirsa SON sutun butun bos alani
    alir ve asil genisletilmek istenen sutun (genelde urun adi) kirpilir.
    """
    index = column_index(table, header)
    if index < 0:
        return
    baslik = table.horizontalHeader()
    baslik.setStretchLastSection(False)
    baslik.setSectionResizeMode(index, QHeaderView.ResizeMode.Stretch)


class TextItem(QTableWidgetItem):
    """Türkçe alfabetik sıralanan hücre."""

    def __lt__(self, other) -> bool:
        return tr_sort_key(self.text()) < tr_sort_key(other.text())


class NumericItem(QTableWidgetItem):
    """Sayısal sıralanan hücre: '1.250 TL' metni doğru sıralanır."""

    def __init__(self, text: str, value: float) -> None:
        super().__init__(text)
        self._value = value
        self.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

    def __lt__(self, other) -> bool:
        if isinstance(other, NumericItem):
            return self._value < other._value
        return super().__lt__(other)
