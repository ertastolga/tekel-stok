"""Ürünler: arama, hızlı tanımlama, benzerden oluşturma ve düzenleme.

Liste DAİMA sayfalıdır: 5.000 ürünlük bir dükkânda bile tam liste belleğe
alınmaz. Bir sayfa için kategori yolları ve barkodlar TOPLU okunur (satır
başına sorgu yok).

Ürün silinmez, "pasife alınır": geçmiş satışlar, maliyetler ve stok hareketleri
olduğu gibi kalır. Pasif ürünler "Kullanım" süzgecinden bulunur ve yeniden
kullanıma alınabilir; pasife alınırken kapatılan barkodlar, bu arada başka
ürüne verilmemişse geri açılır.

V1.2 (D-10): düğmeler seçime göre açılır; birden çok ürün seçilip toplu
"Kategoriye Taşı" yapılabilir (önce ne olacağı gösterilir).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import DomainError
from app.core.models import STOCK_STATE_LABELS, StockState
from app.core.money import format_tl
from app.ui import metrics, theme
from app.ui.dialogs.common_dialogs import (
    ask_confirm,
    button_box,
    scanning_suspended,
    show_error,
    show_info,
)
from app.ui.dialogs.product_edit import ProductEditDialog
from app.ui.pages.base import Page
from app.ui.widgets.common import (
    Card,
    EmptyState,
    PageHeader,
    make_label,
    setup_table,
    stretch_column,
)

log = logging.getLogger(__name__)

PAGE_SIZE = 100

#: "Kullanım" süzgeci.
KULLANIMDAKILER = "AKTIF"
PASIFLER = "PASIF"
TUMU = "TUMU"
#: Toplu taşıma önizlemesinde adıyla gösterilecek en çok ürün.
ONIZLEME_AD = 5


class KategoriSecPenceresi(QDialog):
    """Toplu "Kategoriye Taşı" için hedef kategori seçimi."""

    def __init__(self, services, adet: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kategoriye Taşı")
        self.setModal(True)
        duzen = QVBoxLayout(self)
        duzen.addWidget(make_label(f"Seçili {adet} ürün hangi kategoriye taşınsın?",
                                   "cardTitle", wrap=True))
        self.combo = QComboBox()
        for ust, altlar in services.catalog.category_tree():
            self.combo.addItem(ust["name"], ust["id"])
            for alt in altlar:
                self.combo.addItem(f"   {alt['name']}", alt["id"])
        duzen.addWidget(self.combo)
        kutu = button_box("Devam", "Vazgeç")
        kutu.accepted.connect(self.accept)
        kutu.rejected.connect(self.reject)
        duzen.addWidget(kutu)

    @staticmethod
    def choose(services, adet: int, parent=None) -> int | None:
        pencere = KategoriSecPenceresi(services, adet, parent)
        return pencere.combo.currentData() if pencere.exec() else None


class ProductsPage(Page):
    nav_title = "🏷️  Ürünler"
    nav_key = "urunler"
    nav_group = "yonetim"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.offset = 0
        self._current: list = []

        self.header = PageHeader("🏷️ Ürünler", "")
        self.new_button = QPushButton("+ Yeni Ürün")
        self.new_button.setObjectName("primary")
        self.new_button.clicked.connect(self._new_product)
        self.header.add_action(self.new_button)
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
        )
        duzen.setSpacing(metrics.PAGE_SPACING)
        duzen.addWidget(self._build_filters())

        self.table = QTableWidget(0, 6)
        setup_table(
            self.table, ["Ürün", "Kategori", "Stok", "Durum", "Satış Fiyatı", "Barkod"]
        )
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        stretch_column(self.table, "Ürün")
        self.table.cellDoubleClicked.connect(lambda *_: self._edit_selected())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        duzen.addWidget(self.table, 1)

        self.empty = EmptyState(
            "Henüz ürün yok",
            "İlk ürünü tanıtmak için '+ Yeni Ürün' düğmesine basın ya da "
            "Kasa ekranında barkodu okutun.",
        )
        duzen.addWidget(self.empty, 1)
        duzen.addLayout(self._build_bottom())
        self.root.addWidget(govde, 1)
        self._update_buttons()

    # ===================== Kurulum =======================================
    def _build_filters(self) -> QWidget:
        kart = Card()
        satir = QHBoxLayout()
        satir.setSpacing(10)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Ürün adı ya da barkod ara…")
        self.search_edit.setProperty("scannerExempt", True)
        self.search_edit.textChanged.connect(self._on_filter_changed)
        satir.addWidget(self.search_edit, 2)

        self.category_combo = QComboBox()
        self.category_combo.currentIndexChanged.connect(self._on_filter_changed)
        satir.addWidget(self.category_combo, 1)

        self.state_combo = QComboBox()
        self.state_combo.addItem("Tüm durumlar", None)
        for durum in (
            StockState.NEEDS_CHECK, StockState.CRITICAL,
            StockState.LOW, StockState.NOT_COUNTED, StockState.NORMAL,
        ):
            self.state_combo.addItem(STOCK_STATE_LABELS[durum], int(durum))
        self.state_combo.currentIndexChanged.connect(self._on_filter_changed)
        satir.addWidget(self.state_combo, 1)

        self.usage_combo = QComboBox()
        self.usage_combo.addItem("Kullanımdakiler", KULLANIMDAKILER)
        self.usage_combo.addItem("Pasif ürünler", PASIFLER)
        self.usage_combo.addItem("Tümü", TUMU)
        self.usage_combo.currentIndexChanged.connect(self._on_filter_changed)
        satir.addWidget(self.usage_combo)

        self.incomplete_button = QPushButton("Eksik Bilgiler")
        self.incomplete_button.setCheckable(True)
        self.incomplete_button.clicked.connect(self._on_filter_changed)
        satir.addWidget(self.incomplete_button)

        kart.body.addLayout(satir)
        return kart

    def _build_bottom(self) -> QHBoxLayout:
        alt = QHBoxLayout()
        self.count_label = make_label("", "cardHint")
        alt.addWidget(self.count_label)
        alt.addStretch(1)

        self.prev_button = QPushButton("‹ Önceki")
        self.prev_button.clicked.connect(lambda: self._page(-1))
        alt.addWidget(self.prev_button)

        self.next_button = QPushButton("Sonraki ›")
        self.next_button.clicked.connect(lambda: self._page(1))
        alt.addWidget(self.next_button)

        self.move_button = QPushButton("Kategoriye Taşı")
        self.move_button.clicked.connect(self._move_selected)
        alt.addWidget(self.move_button)

        self.clone_button = QPushButton("Benzer Üründen Oluştur")
        self.clone_button.clicked.connect(self._clone_selected)
        alt.addWidget(self.clone_button)

        self.edit_button = QPushButton("Düzenle")
        self.edit_button.setObjectName("primary")
        self.edit_button.clicked.connect(self._edit_selected)
        alt.addWidget(self.edit_button)

        self.deactivate_button = QPushButton("Pasife Al")
        self.deactivate_button.clicked.connect(self._toggle_active)
        alt.addWidget(self.deactivate_button)
        return alt

    # ===================== Veri ==========================================
    def on_activated(self) -> None:
        self._load_categories()
        self.refresh()

    def _load_categories(self) -> None:
        secili = self.category_combo.currentData()
        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("Tüm kategoriler", None)
        for ust, altlar in self.services.catalog.category_tree():
            self.category_combo.addItem(ust["name"], ust["id"])
            for alt in altlar:
                self.category_combo.addItem(f"   {alt['name']}", alt["id"])
        if secili is not None:
            index = self.category_combo.findData(secili)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
        self.category_combo.blockSignals(False)

    def _on_filter_changed(self) -> None:
        self.offset = 0
        self.refresh()

    def _page(self, direction: int) -> None:
        self.offset = max(0, self.offset + direction * PAGE_SIZE)
        self.refresh()

    def refresh(self) -> None:
        kullanim = self.usage_combo.currentData()
        try:
            if self.incomplete_button.isChecked():
                urunler = self.services.products.incomplete(limit=PAGE_SIZE)
            else:
                urunler = self.services.products.search(
                    text=self.search_edit.text(),
                    category_id=self.category_combo.currentData(),
                    stock_state=self.state_combo.currentData(),
                    only_active=kullanim == KULLANIMDAKILER,
                    only_inactive=kullanim == PASIFLER,
                    limit=PAGE_SIZE,
                    offset=self.offset,
                )
            yollar = self.services.categories.paths()
            barkodlar = self.services.products.first_barcodes([u["id"] for u in urunler])
        except Exception:
            log.exception("Ürün listesi okunamadı")
            return

        self._current = list(urunler)
        dolu = bool(urunler)
        self.table.setVisible(dolu)
        self.empty.setVisible(not dolu)
        self.table.clearSelection()
        self.table.setRowCount(len(urunler))

        for satir, urun in enumerate(urunler):
            durum = int(urun["stock_state"])

            ad = QTableWidgetItem(urun["name"])
            if not urun["is_active"]:
                ad.setText(f"{urun['name']}  (pasif)")
                ad.setForeground(QColor(theme.TEXT_MUTED))
            kategori = QTableWidgetItem(yollar.get(urun["category_id"], ""))
            stok = QTableWidgetItem(str(urun["current_stock"]))
            durum_hucre = QTableWidgetItem(STOCK_STATE_LABELS[StockState(durum)])
            durum_hucre.setForeground(Qt.GlobalColor.black)
            fiyat = QTableWidgetItem(
                format_tl(urun["sale_price"]) if urun["sale_price"] is not None
                else "girilmedi"
            )
            barkod = QTableWidgetItem(barkodlar.get(urun["id"], "yok"))

            for hucre in (stok, fiyat):
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(
                (ad, kategori, stok, durum_hucre, fiyat, barkod)
            ):
                self.table.setItem(satir, sutun, hucre)

        self.count_label.setText(
            f"{self.offset + 1}-{self.offset + len(urunler)} arası gösteriliyor"
            if dolu else ""
        )
        self.prev_button.setEnabled(self.offset > 0)
        self.next_button.setEnabled(len(urunler) == PAGE_SIZE)
        self._update_buttons()

    # ===================== Seçim =========================================
    def selected_products(self) -> list:
        satirlar = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self._current[s] for s in satirlar if 0 <= s < len(self._current)]

    def _selected(self):
        """Tek ürün gerektiren eylemler için: tam olarak bir seçim."""
        secili = self.selected_products()
        return secili[0] if len(secili) == 1 else None

    def _update_buttons(self) -> None:
        secili = self.selected_products()
        tek = secili[0] if len(secili) == 1 else None
        for dugme in (self.edit_button, self.clone_button, self.deactivate_button):
            dugme.setEnabled(tek is not None)
        self.move_button.setEnabled(bool(secili))
        self.move_button.setText(
            f"Kategoriye Taşı ({len(secili)})" if len(secili) > 1 else "Kategoriye Taşı"
        )
        if tek is not None:
            self.deactivate_button.setText(
                "Yeniden Kullan" if not tek["is_active"] else "Pasife Al"
            )

    def focus_search(self) -> None:
        self.search_edit.setFocus()
        self.search_edit.selectAll()

    # ===================== Eylemler ======================================
    def _new_product(self) -> None:
        with scanning_suspended(self.main_window.router):
            ProductEditDialog.create(self.services, self)
        self.refresh()

    def _edit_selected(self) -> None:
        urun = self._selected()
        if urun is None:
            return
        with scanning_suspended(self.main_window.router):
            ProductEditDialog.edit(self.services, urun["id"], self)
        self.refresh()

    def _clone_selected(self) -> None:
        urun = self._selected()
        if urun is None:
            return
        with scanning_suspended(self.main_window.router):
            ProductEditDialog.clone(self.services, urun["id"], self)
        self.refresh()

    def _move_selected(self) -> None:
        secili = self.selected_products()
        if not secili:
            return
        with scanning_suspended(self.main_window.router):
            hedef = KategoriSecPenceresi.choose(self.services, len(secili), self)
        if hedef is not None:
            self.move_selected_to(hedef)

    def move_selected_to(self, category_id: int) -> int:
        """Seçili ürünleri ÖNİZLEME + onayla tek işlemde taşır; taşınan sayısı."""
        secili = self.selected_products()
        if not secili:
            return 0
        yol = self.services.categories.path(category_id)
        zaten = [u for u in secili if u["category_id"] == category_id]
        tasinacak = [u for u in secili if u["category_id"] != category_id]
        if not tasinacak:
            show_info(self, "Kategoriye Taşı", f"Seçili ürünlerin hepsi zaten {yol} içinde.")
            return 0
        adlar = ", ".join(u["name"] for u in tasinacak[:ONIZLEME_AD])
        if len(tasinacak) > ONIZLEME_AD:
            adlar += f" ve {len(tasinacak) - ONIZLEME_AD} ürün daha"
        ayrinti = f"Taşınacaklar: {adlar}."
        if zaten:
            ayrinti += f"\n{len(zaten)} ürün zaten bu kategoride, değişmeyecek."
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, f"{len(tasinacak)} ürün {yol} kategorisine taşınsın mı?",
                ayrinti + "\nSatışlar ve stok değişmez; raporlar yeni kategoriyi gösterir.",
                accept_text="Taşı",
            )
        if not onay:
            return 0
        try:
            sayi = self.services.products.move_to_category(
                [u["id"] for u in tasinacak], category_id
            )
        except DomainError as hata:
            show_error(self, hata.message)
            return 0
        self.refresh()
        self.notify(f"{sayi} ürün {yol} kategorisine taşındı.")
        return sayi

    def _toggle_active(self) -> None:
        urun = self._selected()
        if urun is None:
            return
        aktif = bool(urun["is_active"])
        if aktif:
            from app.services.security_service import ProtectedAction

            if not self.guard_require(ProtectedAction.URUN_PASIF):
                return
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self,
                f"{urun['name']} {'pasife alınsın' if aktif else 'yeniden kullanıma alınsın'} mı?",
                "Geçmiş satışlar ve stok hareketleri KORUNUR. Ürün silinmez. "
                "Barkodları kasada artık okunmaz."
                if aktif else
                "Ürün yeniden satılabilir olur. Pasife alınırken kapatılan barkodları, "
                "başka bir ürüne verilmemişse geri açılır.",
                accept_text="Evet",
                danger=aktif,
            )
        if not onay:
            return
        try:
            sonuc = self.services.products.set_active(urun["id"], not aktif)
        except DomainError as hata:
            show_error(self, hata.message)
            return
        self.refresh()
        if sonuc is not None and sonuc.acilamayan_barkodlar:
            show_info(
                self, "Ürün yeniden kullanımda",
                f"{urun['name']} yeniden satılabilir. Şu barkodlar başka bir üründe "
                f"kullanıldığı için AÇILMADI: {', '.join(sonuc.acilamayan_barkodlar)}. "
                "Gerekirse ürünü düzenleyip yeni barkod ekleyin.",
            )
        elif sonuc is not None:
            self.notify(
                f"{urun['name']} yeniden kullanımda"
                + (f"; {len(sonuc.acilan_barkodlar)} barkod geri açıldı." if
                   sonuc.acilan_barkodlar else ".")
            )
