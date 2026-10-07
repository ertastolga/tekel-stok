"""Ürünler: arama, hızlı tanımlama, benzerden oluşturma ve düzenleme.

Liste DAİMA sayfalıdır: 5.000 ürünlük bir dükkânda bile tam liste belleğe
alınmaz.

Ürün silinmez, "pasife alınır": geçmiş satışlar, maliyetler ve stok hareketleri
olduğu gibi kalır.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
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
from app.ui.dialogs.common_dialogs import ask_confirm, scanning_suspended, show_error
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


class ProductsPage(Page):
    nav_title = "🏷️  Ürünler"
    nav_key = "urunler"
    nav_group = "yonetim"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.offset = 0

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
        stretch_column(self.table, "Ürün")
        self.table.cellDoubleClicked.connect(lambda *_: self._edit_selected())
        duzen.addWidget(self.table, 1)

        self.empty = EmptyState(
            "Henüz ürün yok",
            "İlk ürünü tanıtmak için '+ Yeni Ürün' düğmesine basın ya da "
            "Hızlı Satış ekranında barkodu okutun.",
        )
        duzen.addWidget(self.empty, 1)
        duzen.addLayout(self._build_bottom())
        self.root.addWidget(govde, 1)

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
        try:
            if self.incomplete_button.isChecked():
                urunler = self.services.products.incomplete(limit=PAGE_SIZE)
            else:
                urunler = self.services.products.search(
                    text=self.search_edit.text(),
                    category_id=self.category_combo.currentData(),
                    stock_state=self.state_combo.currentData(),
                    limit=PAGE_SIZE,
                    offset=self.offset,
                )
        except Exception:
            log.exception("Ürün listesi okunamadı")
            return

        self._current = urunler
        dolu = bool(urunler)
        self.table.setVisible(dolu)
        self.empty.setVisible(not dolu)
        self.table.setRowCount(len(urunler))

        for satir, urun in enumerate(urunler):
            durum = int(urun["stock_state"])
            on, arka = theme.level_colors(durum)

            ad = QTableWidgetItem(urun["name"])
            if not urun["is_active"]:
                ad.setText(f"{urun['name']}  (pasif)")
            kategori = QTableWidgetItem(
                self.services.catalog.category_path(urun["category_id"])
            )
            stok = QTableWidgetItem(str(urun["current_stock"]))
            durum_hucre = QTableWidgetItem(STOCK_STATE_LABELS[StockState(durum)])
            durum_hucre.setForeground(Qt.GlobalColor.black)
            fiyat = QTableWidgetItem(
                format_tl(urun["sale_price"]) if urun["sale_price"] is not None
                else "girilmedi"
            )
            barkodlar = self.services.barcodes.barcodes_of(urun["id"])
            barkod = QTableWidgetItem(
                barkodlar[0]["barcode_norm"] if barkodlar else "yok"
            )

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

    def _selected(self):
        index = self.table.currentRow()
        if index < 0 or index >= len(getattr(self, "_current", [])):
            return None
        return self._current[index]

    def _update_buttons(self) -> None:
        urun = self._selected()
        var = urun is not None
        for dugme in (self.edit_button, self.clone_button, self.deactivate_button):
            dugme.setEnabled(var)
        if var:
            self.deactivate_button.setText(
                "Yeniden Kullan" if not urun["is_active"] else "Pasife Al"
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
                "Geçmiş satışlar ve stok hareketleri KORUNUR. Ürün silinmez."
                if aktif else "Ürün yeniden satılabilir olur.",
                accept_text="Evet",
                danger=aktif,
            )
        if not onay:
            return
        try:
            self.services.products.set_active(urun["id"], not aktif)
        except DomainError as hata:
            show_error(self, hata.message)
            return
        self.refresh()
