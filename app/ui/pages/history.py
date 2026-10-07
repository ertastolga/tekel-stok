"""Geçmiş: satışlar, stok girişleri, sayımlar ve işlem günlüğü.

Normal kullanıcı günlük işinde buraya BAKMAZ. Bir şey ters gittiğinde ya da
"dün ne olmuştu?" diye merak edildiğinde açılır.

Listeler DAİMA sayfalıdır: yılların geçmişi tek seferde belleğe alınmaz.
"""
from __future__ import annotations

import datetime
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import DomainError
from app.core.money import format_tl
from app.core.tr import fmt_date, fmt_datetime
from app.ui import metrics
from app.ui.dialogs.common_dialogs import ask_confirm, scanning_suspended, show_error, show_info
from app.ui.pages.base import Page
from app.ui.widgets.common import PageHeader, setup_table, stretch_column

log = logging.getLogger(__name__)

PAGE_SIZE = 100


class HistoryPage(Page):
    nav_title = "🕘  Geçmiş"
    nav_key = "gecmis"
    nav_group = "yonetim"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.sale_offset = 0

        self.header = PageHeader("🕘 Geçmiş", "Yapılan işlemlerin kaydı.")
        self.root.addWidget(self.header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_sales_tab(), "Satışlar")
        self.tabs.addTab(self._build_receipts_tab(), "Stok Girişleri")
        self.tabs.addTab(self._build_counts_tab(), "Sayımlar")
        self.tabs.addTab(self._build_audit_tab(), "İşlem Günlüğü")
        self.tabs.currentChanged.connect(lambda _: self.refresh())
        self.root.addWidget(self.tabs, 1)

    # ===================== Sekmeler ======================================
    def _build_sales_tab(self) -> QWidget:
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        duzen.setContentsMargins(12, 12, 12, 12)
        duzen.setSpacing(10)

        self.sales_table = QTableWidget(0, 6)
        setup_table(
            self.sales_table,
            ["Zaman", "Kip", "Ürün", "Adet", "Tutar", "Durum"],
        )
        stretch_column(self.sales_table, "Ürün")
        duzen.addWidget(self.sales_table, 1)

        alt = QHBoxLayout()
        alt.addStretch(1)
        onceki = QPushButton("‹ Önceki")
        onceki.clicked.connect(lambda: self._page_sales(-1))
        alt.addWidget(onceki)
        sonraki = QPushButton("Sonraki ›")
        sonraki.clicked.connect(lambda: self._page_sales(1))
        alt.addWidget(sonraki)

        self.reverse_button = QPushButton("Seçili Satışı Geri Al")
        self.reverse_button.clicked.connect(self._reverse_sale)
        alt.addWidget(self.reverse_button)
        duzen.addLayout(alt)
        return sayfa

    def _build_receipts_tab(self) -> QWidget:
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        duzen.setContentsMargins(12, 12, 12, 12)
        duzen.setSpacing(10)

        self.receipts_table = QTableWidget(0, 5)
        setup_table(
            self.receipts_table,
            ["Tarih", "Tedarikçi", "İrsaliye", "Kalem", "Tutar"],
        )
        stretch_column(self.receipts_table, "Tedarikçi")
        duzen.addWidget(self.receipts_table, 1)

        alt = QHBoxLayout()
        alt.addStretch(1)
        self.reverse_receipt_button = QPushButton("Seçili Girişi Geri Al")
        self.reverse_receipt_button.clicked.connect(self._reverse_receipt)
        alt.addWidget(self.reverse_receipt_button)
        duzen.addLayout(alt)
        return sayfa

    def _build_counts_tab(self) -> QWidget:
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        duzen.setContentsMargins(12, 12, 12, 12)
        self.counts_table = QTableWidget(0, 5)
        setup_table(
            self.counts_table,
            ["Tarih", "Kapsam", "Durum", "Adet Farkı", "Değer Farkı"],
        )
        duzen.addWidget(self.counts_table, 1)
        return sayfa

    def _build_audit_tab(self) -> QWidget:
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        duzen.setContentsMargins(12, 12, 12, 12)
        self.audit_table = QTableWidget(0, 2)
        setup_table(self.audit_table, ["Zaman", "İşlem"])
        stretch_column(self.audit_table, "İşlem")
        duzen.addWidget(self.audit_table, 1)
        return sayfa

    # ===================== Veri ==========================================
    def refresh(self) -> None:
        try:
            index = self.tabs.currentIndex()
            if index == 0:
                self._fill_sales()
            elif index == 1:
                self._fill_receipts()
            elif index == 2:
                self._fill_counts()
            else:
                self._fill_audit()
        except Exception:
            log.exception("Geçmiş okunamadı")

    def _page_sales(self, direction: int) -> None:
        self.sale_offset = max(0, self.sale_offset + direction * PAGE_SIZE)
        self._fill_sales()

    def _fill_sales(self) -> None:
        satislar = self.services.db.query(
            "SELECT s.*, (SELECT i.product_name_snapshot FROM sale_items i "
            "               WHERE i.sale_id = s.id ORDER BY i.line_no LIMIT 1) AS ilk "
            "  FROM sales s WHERE s.entry_type = 'SALE' "
            " ORDER BY s.id DESC LIMIT ? OFFSET ?",
            (PAGE_SIZE, self.sale_offset),
        )
        self._sales = satislar
        self.sales_table.setRowCount(len(satislar))
        for satir, satis in enumerate(satislar):
            zaman = fmt_datetime(
                datetime.datetime.fromtimestamp(satis["created_at_utc"])
            )
            kip = "Hızlı" if satis["sale_mode"] == "HIZLI" else "Sepetli"
            urun = satis["ilk"] or "-"
            if satis["item_count"] > 1:
                urun += f"  (+{satis['item_count'] - 1} kalem)"
            durum = "Geri alındı" if satis["is_reversed"] else "Tamam"

            hucreler = (
                QTableWidgetItem(zaman),
                QTableWidgetItem(kip),
                QTableWidgetItem(urun),
                QTableWidgetItem(str(satis["item_count"])),
                QTableWidgetItem(format_tl(satis["total_amount"])),
                QTableWidgetItem(durum),
            )
            for hucre in hucreler[3:5]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            if satis["is_reversed"]:
                for hucre in hucreler:
                    hucre.setForeground(Qt.GlobalColor.gray)
            for sutun, hucre in enumerate(hucreler):
                self.sales_table.setItem(satir, sutun, hucre)

    def _fill_receipts(self) -> None:
        fisler = self.services.purchases.history(limit=PAGE_SIZE)
        self._receipts = fisler
        self.receipts_table.setRowCount(len(fisler))
        for satir, fis in enumerate(fisler):
            geri_alindi = self.services.purchases.is_reversed(fis["id"])
            ad = fis["tedarikci"] or "-"
            if fis["reverses_receipt_id"]:
                ad += "  (geri alma kaydı)"
            elif geri_alindi:
                ad += "  (geri alındı)"
            hucreler = (
                QTableWidgetItem(fmt_date(fis["receipt_date"])),
                QTableWidgetItem(ad),
                QTableWidgetItem(fis["invoice_no"] or "-"),
                QTableWidgetItem(str(fis["line_count"])),
                QTableWidgetItem(format_tl(fis["total_cost"])),
            )
            for hucre in hucreler[3:]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(hucreler):
                self.receipts_table.setItem(satir, sutun, hucre)

    def _fill_counts(self) -> None:
        sayimlar = self.services.counts.history(limit=PAGE_SIZE)
        self.counts_table.setRowCount(len(sayimlar))
        for satir, sayim in enumerate(sayimlar):
            zaman = fmt_datetime(
                datetime.datetime.fromtimestamp(sayim["created_at_utc"])
            )
            durum = {
                "COMMITTED": "Tamamlandı",
                "CANCELLED": "İptal edildi",
                "DRAFT": "Sürüyor",
            }.get(sayim["status"], sayim["status"])
            hucreler = (
                QTableWidgetItem(zaman),
                QTableWidgetItem("Tüm Dükkân" if sayim["scope"] == "ALL" else "Bölüm"),
                QTableWidgetItem(durum),
                QTableWidgetItem(f"{sayim['total_diff_qty']:+d}"),
                QTableWidgetItem(format_tl(sayim["total_diff_value"])),
            )
            for hucre in hucreler[3:]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(hucreler):
                self.counts_table.setItem(satir, sutun, hucre)

    def _fill_audit(self) -> None:
        kayitlar = self.services.audit.recent(limit=PAGE_SIZE)
        self.audit_table.setRowCount(len(kayitlar))
        for satir, kayit in enumerate(kayitlar):
            zaman = fmt_datetime(
                datetime.datetime.fromtimestamp(kayit["created_at_utc"])
            )
            self.audit_table.setItem(satir, 0, QTableWidgetItem(zaman))
            self.audit_table.setItem(satir, 1, QTableWidgetItem(kayit["summary_tr"]))

    # ===================== Eylemler ======================================
    def _reverse_sale(self) -> None:
        index = self.sales_table.currentRow()
        if index < 0 or index >= len(getattr(self, "_sales", [])):
            return
        satis = self._sales[index]
        if satis["is_reversed"]:
            show_error(self, "Bu satış daha önce geri alınmış.")
            return

        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self,
                f"{format_tl(satis['total_amount'])} tutarındaki satış geri alınsın mı?",
                "Ürünler stoğa geri eklenir. Kayıt silinmez, geri alındı olarak işaretlenir.",
                accept_text="Evet, geri al",
            )
        if not onay:
            return
        try:
            self.services.sales.reverse_sale(satis["id"])
        except DomainError as hata:
            show_error(self, hata.message)
            return
        self.refresh()
        self.main_window.refresh_today()

    def _reverse_receipt(self) -> None:
        index = self.receipts_table.currentRow()
        if index < 0 or index >= len(getattr(self, "_receipts", [])):
            return
        fis = self._receipts[index]

        # Servis KARAR VERİR, pencere yalnızca çizer.
        onizleme = self.services.purchases.reversal_preview(fis["id"])
        if onizleme.reason:
            with scanning_suspended(self.main_window.router):
                show_info(self, "Bu giriş geri alınamıyor", onizleme.reason)
            return
        if not onizleme.allowed:
            adlar = ", ".join(onizleme.blocking_names[:5])
            with scanning_suspended(self.main_window.router):
                show_info(
                    self, "Bu giriş geri alınamıyor",
                    "Bu üründen sonra satış ya da yeni giriş yapılmış: "
                    f"{adlar}.\n\nStok değerinin bozulmaması için otomatik geri alma "
                    "yapılmaz. Bunun yerine Stok Durumu ekranından düzeltme "
                    "girişi yapabilirsiniz.",
                )
            return

        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, "Bu stok girişi geri alınsın mı?",
                f"{format_tl(fis['total_cost'])} tutarındaki giriş stoktan düşülür.",
                accept_text="Evet, geri al", danger=True,
            )
        if not onay:
            return
        try:
            self.services.purchases.reverse(fis["id"])
        except DomainError as hata:
            show_error(self, hata.message)
            return
        self.refresh()
