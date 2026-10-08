"""Yeniden kullanılan arayüz parçaları.

Buradaki gereçler yalnızca ÇİZER: iş kuralı işletmez, SQL çalıştırmaz, kuruş
biçimlemez (bunun için ``app.core.money`` vardır).
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
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
        duzen.setContentsMargins(18, 10, 18, 10)
        duzen.setSpacing(2)
        self.headline = make_label("", "resultHeadline", wrap=True)
        self.detail = make_label("", "resultDetail", wrap=True)
        self.extra = make_label("", "resultDetail", wrap=True)
        # Şerit yüksekliği en uzun iletiye göre sabittir (Kasa bütçesi); kısa
        # ileti dikeyde ORTALANIR, satırların arasına boşluk dağılmaz (M12b).
        duzen.addStretch(1)
        duzen.addWidget(self.headline)
        duzen.addWidget(self.detail)
        duzen.addWidget(self.extra)
        duzen.addStretch(1)

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
        duzen.setContentsMargins(18, 10, 18, 10)
        duzen.setSpacing(0)
        self.title = make_label("", "flashLine")
        self.name = make_label("", "flashName", wrap=True)
        self.line = make_label("", "flashLine")
        #: İsteğe bağlı ek satır (ör. "Para üstü: 50 TL"); boşsa yer kaplamaz.
        self.extra = make_label("", "flashLine")
        self.extra.setVisible(False)
        duzen.addStretch(1)
        duzen.addWidget(self.title)
        duzen.addWidget(self.name)
        duzen.addWidget(self.line)
        duzen.addWidget(self.extra)
        duzen.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._finish)

    def flash(
        self,
        title: str,
        name: str,
        line: str = "",
        border: str | None = None,
        background: str | None = None,
        duration_ms: int | None = None,
        extra: str = "",
    ) -> None:
        # Varsayılanlar ÇAĞRI ANINDA okunur: açılışta seçilen tema/ölçü geçerli olsun.
        border = border or theme.PRIMARY
        background = background or theme.PRIMARY_LIGHT
        duration_ms = metrics.SALE_FLASH_MS if duration_ms is None else duration_ms
        self.setStyleSheet(
            f"#saleFlash {{ border: 2px solid {border}; background: {background}; }}"
            f"#flashName {{ color: {border}; }}"
        )
        self.set_texts(title, name, line, extra)
        self._timer.start(duration_ms)

    def set_texts(self, title: str, name: str, line: str = "", extra: str = "") -> None:
        self.title.setText(title)
        self.name.setText(name)
        self.line.setText(line)
        self.line.setVisible(bool(line))
        self.extra.setText(extra)
        self.extra.setVisible(bool(extra))

    def _finish(self) -> None:
        self.expired.emit()


class EmptyState(QWidget):
    """Boş liste açıklaması: kullanıcıya NE YAPACAĞINI sade Türkçe anlatır."""

    def __init__(self, title: str, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        duzen = QVBoxLayout(self)
        duzen.setSpacing(8)
        # Düzen ORTALANMAZ: ortalanınca sarılan ipucu dar bir genişliğe
        # sıkışıp yüksekliği eksik hesaplanıyor ve kırpılıyordu (M12b ekran
        # incelemesi). Etiketler tam genişlikte, metin ortalı; blok dikeyde ortalı.
        duzen.addStretch(1)
        self.title = make_label(title, "sectionTitle", wrap=True,
                                align=Qt.AlignmentFlag.AlignCenter)
        self.hint = make_label(hint, "cardHint", wrap=True,
                               align=Qt.AlignmentFlag.AlignCenter)
        self.hint.setVisible(bool(hint))
        duzen.addWidget(self.title)
        duzen.addWidget(self.hint)
        duzen.addStretch(1)

    def set_text(self, title: str, hint: str = "") -> None:
        self.title.setText(title)
        self.hint.setText(hint)
        self.hint.setVisible(bool(hint))


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
        # Metin sütunu boş alanı ALIR: araya esneme konunca sarılan alt başlık
        # dar kalıp 2–4 satıra bölünüyordu (M12b ekran incelemesi).
        duzen.addLayout(metin, 1)

        # Eylemler sağa yaslı AKIŞ düzenindedir: dar pencerede alt satıra iner,
        # başlık ve sayfa yatay taşmaz (M12b; Kategoriler 888 px istiyordu).
        self._eylem_kabi = QWidget()
        self.actions = FlowLayout(self._eylem_kabi, spacing=8, sag=True)
        duzen.addWidget(self._eylem_kabi)

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

        # Yazı boyutu stil sayfasındaki #actionTitle / #actionHint kurallarından
        # gelir: uygulama stil sayfasının "*" kuralı setFont'u EZER (M12b).
        self.title_label = make_label(f"{icon}  {title}", "actionTitle")
        duzen.addWidget(self.title_label)

        if hint:
            ipucu = make_label(hint, "actionHint", wrap=True)
            duzen.addWidget(ipucu)
        duzen.addStretch(1)


class FlowLayout(QLayout):
    """Satıra sığmayan öğeleri bir ALT satıra geçiren düzen.

    YÖNETİM sayfalarındaki süzgeç ve düğme dizileri 1000×600 pencerede (ya da
    %130 yazıda) tek satıra sığmıyor, sayfayı yatay taşırıyordu (M12b ekran
    incelemesi). Öğeler kendi ``sizeHint`` boyutlarındadır; satır içinde
    dikeyde ortalanır; gizli öğeler yer kaplamaz. ``sag=True``: satırlar sağa
    yaslanır (eylem düğmeleri için).
    """

    def __init__(self, parent: QWidget | None = None, spacing: int = 8,
                 sag: bool = False) -> None:
        super().__init__(parent)
        self._ogeler = []
        self._bosluk = spacing
        self._sag = sag
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._ogeler.append(item)

    def count(self) -> int:
        return len(self._ogeler)

    def itemAt(self, index: int):  # noqa: N802
        return self._ogeler[index] if 0 <= index < len(self._ogeler) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._ogeler.pop(index) if 0 <= index < len(self._ogeler) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._yerlestir(QRect(0, 0, width, 0), olc=True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._yerlestir(rect, olc=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        """Tercih: hepsi tek satırda."""
        gorunen = [o for o in self._ogeler if not o.isEmpty()]
        m = self.contentsMargins()
        if not gorunen:
            return QSize(m.left() + m.right(), m.top() + m.bottom())
        genislik = sum(o.sizeHint().width() for o in gorunen) + self._bosluk * (len(gorunen) - 1)
        yukseklik = max(o.sizeHint().height() for o in gorunen)
        return QSize(genislik + m.left() + m.right(), yukseklik + m.top() + m.bottom())

    def minimumSize(self) -> QSize:  # noqa: N802
        """En dar: en geniş TEK öğe (gerisi alt satırlara iner)."""
        boyut = QSize()
        for oge in self._ogeler:
            if not oge.isEmpty():
                boyut = boyut.expandedTo(oge.minimumSize()).expandedTo(
                    QSize(oge.sizeHint().width(), 0))
        m = self.contentsMargins()
        return boyut + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _yerlestir(self, rect: QRect, olc: bool) -> int:
        m = self.contentsMargins()
        alan = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        satirlar: list[list] = [[]]
        genislik = 0
        for oge in self._ogeler:
            if oge.isEmpty():
                continue
            boy = oge.sizeHint()
            gerek = boy.width() if not satirlar[-1] else genislik + self._bosluk + boy.width()
            if satirlar[-1] and gerek > alan.width():
                satirlar.append([])
                gerek = boy.width()
            satirlar[-1].append((oge, boy))
            genislik = gerek
        y = alan.y()
        for satir in satirlar:
            if not satir:
                continue
            yukseklik = max(boy.height() for _o, boy in satir)
            toplam = sum(boy.width() for _o, boy in satir) + self._bosluk * (len(satir) - 1)
            x = alan.x() + (max(0, alan.width() - toplam) if self._sag else 0)
            for oge, boy in satir:
                if not olc:
                    oge.setGeometry(QRect(QPoint(x, y + (yukseklik - boy.height()) // 2),
                                          QSize(min(boy.width(), alan.width()), boy.height())))
                x += boy.width() + self._bosluk
            y += yukseklik + self._bosluk
        return max(0, y - self._bosluk - rect.y()) + m.bottom()


class CardGrid(QWidget):
    """Kartları eşit sütunlara dizer; dar pencerede sütun sayısı azalır.

    Beş özet kartı (Stok Durumu) 1000×600'de tek satıra sığmıyor, sayfayı
    yatay taşırıyordu (M12b). Kartlar her satırda eşit genişliktedir.
    """

    def __init__(self, kartlar, spacing: int = 16, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kartlar = list(kartlar)
        self._izgara = QGridLayout(self)
        self._izgara.setContentsMargins(0, 0, 0, 0)
        self._izgara.setSpacing(spacing)
        # En küçük boyutu düzen değil bu sınıf bildirir (sütun sayısına göre).
        self._izgara.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._sutun = 0
        self._diz(len(self._kartlar))

    @property
    def columns(self) -> int:
        return self._sutun

    def _en_genis(self) -> int:
        return max(k.minimumSizeHint().width() for k in self._kartlar)

    def _diz(self, sutun: int) -> None:
        sutun = max(1, min(sutun, len(self._kartlar)))
        if sutun == self._sutun:
            return
        self._sutun = sutun
        for kart in self._kartlar:
            self._izgara.removeWidget(kart)
        for sira, kart in enumerate(self._kartlar):
            self._izgara.addWidget(kart, sira // sutun, sira % sutun)
        for c in range(len(self._kartlar)):
            self._izgara.setColumnStretch(c, 1 if c < sutun else 0)
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        satir = -(-len(self._kartlar) // self._sutun)
        yukseklik = max(k.minimumSizeHint().height() for k in self._kartlar)
        aralik = self._izgara.spacing()
        return QSize(self._en_genis(), satir * yukseklik + (satir - 1) * aralik)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSizeHint()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        aralik = self._izgara.spacing()
        self._diz((event.size().width() + aralik) // (self._en_genis() + aralik))


def flow_row(*parcalar, spacing: int = 8, sag: bool = False) -> QWidget:
    """``FlowLayout``'lu bir satır gereci; parçalar sırayla eklenir."""
    satir = QWidget()
    duzen = FlowLayout(satir, spacing=spacing, sag=sag)
    for parca in parcalar:
        duzen.addWidget(parca)
    return satir


def labeled(etiket: str, gerec: QWidget, object_name: str = "cardHint") -> QWidget:
    """Etiket + denetim çiftini tek parça yapar (akışta birlikte kalsın)."""
    kap = QWidget()
    duzen = QHBoxLayout(kap)
    duzen.setContentsMargins(0, 0, 0, 0)
    duzen.setSpacing(6)
    duzen.addWidget(make_label(etiket, object_name))
    duzen.addWidget(gerec)
    return kap


def wrap_path(yol) -> str:
    """Klasör yolunu sarılabilir yapar: ayraçlardan sonra görünmez kırılma
    noktası eklenir (boşluksuz uzun yol etiketi yatay kaydırma açtırmasın)."""
    return str(yol).replace("\\", "\\\u200b").replace("/", "/\u200b")


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
