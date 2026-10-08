"""Kasa sayfalarının ortak parçaları: araç çubuğu ve ölçülü sonuç şeridi.

Yerleşim bütçesi (plan §5.2): 1000×600 pencerede içerik yığınına ~576 px
kalır. Kasa sayfalarında sayfa başlığı YOKTUR; üstte tek bir ≤ 64 px araç
çubuğu (barkod alanı + 56 px dokunma düğmeleri + "⋯" menüsü) durur. Sonuç
şeridinin yüksekliği sabit bir sayı DEĞİLDİR: gösterilebilecek en uzun ileti
(satış onayı, para üstü, geri alma kapısı açıklaması…) gerçek yazı tipiyle,
en dar içerik genişliğinde ölçülür; böylece hiçbir ileti kırpılmaz ve şerit
gereğinden büyük olup sepet listesini ezmez.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QWidget,
)

from app.ui import metrics

#: Araç çubuğunun en büyük yüksekliği.
ARAC_CUBUGU_YUKSEKLIGI = 64
#: Barkod alanının okunur kalacağı en az genişlik; altına inilecekse
#: "katlanır" araçlar "⋯" menüsüne taşınır (M12b: 1000×600'de alan "Bar…"
#: diye ezilmişti).
BARKOD_ALANI_EN_AZ = 260

#: En dar Kasa içerik genişliği: en küçük pencere − menü − sayfa kenar boşlukları.
def en_dar_icerik_genisligi() -> int:
    return metrics.MIN_WINDOW_WIDTH - metrics.nav_genisligi() - 2 * metrics.PAGE_MARGIN_H


class KasaToolbar(QWidget):
    """Tek satırlık Kasa araç çubuğu; sağ uçta "⋯" (diğer eylemler) menüsü."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("kasaToolbar")
        self.setFixedHeight(ARAC_CUBUGU_YUKSEKLIGI)
        self._duzen = QHBoxLayout(self)
        self._duzen.setContentsMargins(0, 0, 0, 0)
        self._duzen.setSpacing(8)
        self.tools: list[QPushButton] = []
        #: Dar pencerede menüye taşınan araçlar: (düğme, menü eylemi).
        self._katlanirlar: list[tuple[QPushButton, QAction]] = []
        self._alan: QWidget | None = None

        self.more_menu = QMenu(self)
        self.more_menu.setObjectName("kasaMenu")
        self.more_button = QPushButton("⋯")
        # Kendi biçemi: aynı 56 px hedef, okunur büyüklükte simge (M12b).
        self.more_button.setObjectName("kasaMore")
        self.more_button.setToolTip("Diğer işlemler")
        self.more_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.more_button.setFixedWidth(metrics.TOUCH_TARGET_MIN)
        self.more_button.clicked.connect(self.open_more_menu)
        self._sona = self.more_button

    def add_field(self, widget: QWidget) -> None:
        """Barkod alanı: kalan genişliği alır, kompakt biçimde."""
        if hasattr(widget, "set_compact"):
            widget.set_compact(True)
        # Araç çubuğu yüksekliğini doldurur: içerik hiçbir ölçekte kırpılmaz.
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._duzen.addWidget(widget, 1)
        self._alan = widget

    def add_tool(self, text: str, slot, tooltip: str = "",
                 collapsible: bool = False) -> QPushButton:
        """``collapsible``: yer kalmazsa düğme gizlenir, eylemi "⋯" menüsünde
        görünür (metin değişmez; kısayolu ve menü yolu aynı kalır)."""
        dugme = QPushButton(text)
        dugme.setObjectName("kasaTool")
        dugme.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if tooltip:
            dugme.setToolTip(tooltip)
        dugme.clicked.connect(slot)
        self._duzen.addWidget(dugme)
        self.tools.append(dugme)
        if collapsible:
            eylem = QAction(text, self)
            eylem.triggered.connect(slot)
            eylem.setVisible(False)
            self._katlanirlar.append((dugme, eylem))
        return dugme

    def collapsed(self) -> bool:
        """Katlanır araçlar şu an menüde mi?"""
        return any(not d.isVisibleTo(self) for d, _e in self._katlanirlar)

    def _katla(self, genislik: int) -> None:
        if not self._katlanirlar:
            return
        aralik = self._duzen.spacing()
        gereken = BARKOD_ALANI_EN_AZ
        for dugme in self.tools:
            gereken += dugme.sizeHint().width() + aralik
        if self.more_button.parent() is self and self.more_button.isVisibleTo(self):
            gereken += self.more_button.sizeHint().width() + aralik
        katli = genislik < gereken
        for dugme, eylem in self._katlanirlar:
            dugme.setVisible(not katli)
            eylem.setVisible(katli)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._katla(event.size().width())

    def finish(self, with_menu: bool = True) -> None:
        """Araçlar eklendikten sonra "⋯" en sağa konur (menüsüz sayfada yok)."""
        if with_menu:
            self._duzen.addWidget(self.more_button)
            for _dugme, eylem in self._katlanirlar:
                self.more_menu.addAction(eylem)
        else:
            self.more_button.setParent(self)
            self.more_button.setVisible(False)

    def add_menu_action(self, text: str, slot) -> QAction:
        eylem = QAction(text, self)
        eylem.triggered.connect(slot)
        self.more_menu.addAction(eylem)
        return eylem

    def open_more_menu(self) -> None:
        """Menü ENGELLEMEDEN açılır (``popup``): iç içe olay döngüsü yoktur."""
        self.more_menu.popup(self.more_button.mapToGlobal(
            QPoint(0, self.more_button.height())
        ))


def sonuc_seridi_yuksekligi(ornekler, genislik: int | None = None,
                            olcum_gerecleri=None) -> int:
    """Örnek iletilerin hiçbiri kırpılmayacak en küçük şerit yüksekliği.

    ``ornekler``: ``("banner", başlık, ayrıntı, ek)`` ya da
    ``("flash", başlık, ad, satır, ek)`` demetleri. Ölçüm, ekrana HİÇ
    konmayan karalama gereçleriyle yapılır (gösterilen ileti bozulmaz);
    gerçek yazı tipi ve stil sayfası kullanılır.
    """
    from app.ui.widgets.common import ResultBanner, SaleFlash

    genislik = genislik or en_dar_icerik_genisligi()
    banner, flash = olcum_gerecleri or (ResultBanner(), SaleFlash())
    en_buyuk = 0
    for ornek in ornekler:
        if ornek[0] == "banner":
            _, baslik, ayrinti, ek = ornek
            banner.show_idle(baslik, ayrinti)
            banner.extra.setText(ek)
            banner.extra.setVisible(bool(ek))
            gerec = banner
        else:
            _, baslik, ad, satir, ek = ornek
            flash.set_texts(baslik, ad, satir, ek)
            gerec = flash
        gerec.ensurePolished()
        for cocuk in gerec.findChildren(QWidget):
            cocuk.ensurePolished()
        gerec.layout().activate()
        yukseklik = gerec.layout().totalHeightForWidth(genislik)
        en_buyuk = max(en_buyuk, yukseklik, gerec.minimumSizeHint().height())
    return en_buyuk


class SonucSeridi(QStackedWidget):
    """Şerit + satış onayı yığını; yüksekliği GERÇEK genişliğinde ölçülür.

    Genişlik değiştikçe (pencere boyutu, ölçek) en uzun örnek iletinin
    gerektirdiği yükseklik yeniden hesaplanır. Böylece dar bir sütunda bile
    hiçbir ileti kırpılmaz.
    """

    def __init__(self, banner, flash, ornekler, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from app.ui.widgets.common import ResultBanner, SaleFlash

        self.addWidget(banner)
        self.addWidget(flash)
        self._ornekler = ornekler
        self._olcum = (ResultBanner(), SaleFlash())
        self._olculen = -1
        self._ayarla(en_dar_icerik_genisligi())

    def _ayarla(self, genislik: int) -> None:
        if genislik <= 0 or genislik == self._olculen:
            return
        self._olculen = genislik
        yukseklik = sonuc_seridi_yuksekligi(self._ornekler, genislik, self._olcum)
        if yukseklik != self.height() or self.minimumHeight() != yukseklik:
            self.setFixedHeight(yukseklik)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._ayarla(event.size().width())
