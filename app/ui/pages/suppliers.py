"""Tedarikçiler: kim, ne getirdi, ne kadar ödendi.

Tedarikçi günlük işte ZORUNLU DEĞİLDİR; burada yönetilir, satışta hiç sorulmaz.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.money import format_tl
from app.core.tr import fmt_date
from app.ui import metrics
from app.ui.dialogs.common_dialogs import scanning_suspended, show_error
from app.ui.pages.base import Page
from app.ui.widgets.common import (
    EmptyState,
    PageHeader,
    make_label,
    setup_table,
    stretch_column,
)

log = logging.getLogger(__name__)


class SuppliersPage(Page):
    nav_title = "🚚  Tedarikçiler"
    nav_key = "tedarikciler"
    nav_group = "yonetim"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)

        self.header = PageHeader("🚚 Tedarikçiler", "Mal aldığınız firmalar.")
        self.new_button = QPushButton("+ Yeni Tedarikçi")
        self.new_button.setObjectName("primary")
        self.new_button.clicked.connect(self._new_supplier)
        self.header.add_action(self.new_button)
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
        )
        duzen.setSpacing(metrics.PAGE_SPACING)

        self.table = QTableWidget(0, 5)
        setup_table(
            self.table, ["Tedarikçi", "Telefon", "Sevkiyat", "Toplam Alış", "Son Alış"]
        )
        stretch_column(self.table, "Tedarikçi")
        self.table.currentCellChanged.connect(lambda *_: self._fill_products())
        duzen.addWidget(self.table, 1)

        self.empty = EmptyState(
            "Henüz tedarikçi yok",
            "Mal aldığınız firmaları buraya ekleyebilirsiniz. Zorunlu değildir.",
        )
        duzen.addWidget(self.empty, 1)

        duzen.addWidget(make_label("Bu Tedarikçiden Gelen Ürünler", "sectionTitle"))
        self.product_table = QTableWidget(0, 4)
        setup_table(
            self.product_table, ["Ürün", "Stok", "Son Alış Fiyatı", "Son Alış Tarihi"]
        )
        stretch_column(self.product_table, "Ürün")
        self.product_table.setMaximumHeight(metrics.TABLE_ROW_HEIGHT * 7)
        duzen.addWidget(self.product_table)

        self.root.addWidget(govde, 1)

    def refresh(self) -> None:
        try:
            self._suppliers = self.services.suppliers.all()
        except Exception:
            log.exception("Tedarikçiler okunamadı")
            return

        dolu = bool(self._suppliers)
        self.table.setVisible(dolu)
        self.empty.setVisible(not dolu)
        self.table.setRowCount(len(self._suppliers))

        for satir, tedarikci in enumerate(self._suppliers):
            ozet = self.services.suppliers.summary(tedarikci["id"])
            hucreler = (
                QTableWidgetItem(tedarikci["name"]),
                QTableWidgetItem(tedarikci["phone"] or "-"),
                QTableWidgetItem(str(ozet["fis_sayisi"])),
                QTableWidgetItem(format_tl(ozet["toplam_tutar"])),
                QTableWidgetItem(fmt_date(ozet["son_tarih"]) or "-"),
            )
            for hucre in hucreler[2:4]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(hucreler):
                self.table.setItem(satir, sutun, hucre)
        self._fill_products()

    def _fill_products(self) -> None:
        index = self.table.currentRow()
        if index < 0 or index >= len(getattr(self, "_suppliers", [])):
            self.product_table.setRowCount(0)
            return
        urunler = self.services.suppliers.products(self._suppliers[index]["id"])
        self.product_table.setRowCount(len(urunler))
        for satir, urun in enumerate(urunler):
            hucreler = (
                QTableWidgetItem(urun["name"]),
                QTableWidgetItem(str(urun["current_stock"])),
                QTableWidgetItem(format_tl(urun["last_purchase_cost"])),
                QTableWidgetItem(fmt_date(urun["son_alis"]) or "-"),
            )
            for hucre in hucreler[1:3]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(hucreler):
                self.product_table.setItem(satir, sutun, hucre)

    def _new_supplier(self) -> None:
        with scanning_suspended(self.main_window.router):
            ad, tamam = QInputDialog.getText(self, "Yeni Tedarikçi", "Firma adı:")
        if not tamam or not ad.strip():
            return
        try:
            self.services.suppliers.create(ad.strip())
        except Exception as hata:
            log.exception("Tedarikçi eklenemedi")
            show_error(self, "Tedarikçi eklenemedi.", str(hata))
            return
        self.refresh()
