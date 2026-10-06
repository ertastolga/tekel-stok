"""Bugün / Panel — çalışma kipine göre iki yüzü vardır.

**SALES_FIRST:** satış odaklı. Ciro, müşteri (sepet) sayısı, satılan adet,
ortalama sepet, sepet başına ürün, nakit/kart kırılımı, en çok satanlar,
saatlik satış ve gün karşılaştırması.

Kâr ve maliyet BİLEREK GÖSTERİLMEZ: stoksuz satış serbest olduğu için birçok
satışın maliyeti tahminidir ve panelde kesin bir kâr rakamı göstermek
yanıltıcı olurdu. Kâr, Yönetim ekranlarında ve INVENTORY_TRACKED kipinde durur.
Stok uyarıları da burada yoktur; yerleri Stok Durumu ekranıdır.

**INVENTORY_TRACKED:** V1 davranışı — brüt kâr, stok değeri, Dikkat bölümü ve
uzun süredir satılmayanlar.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.models import STOCK_STATE_LABELS, StockState
from app.core.money import format_tl
from app.core.tr import fmt_decimal_trim, fmt_percent
from app.ui import metrics, theme
from app.ui.pages.base import Page
from app.ui.widgets.charts import SimpleBarChart
from app.ui.widgets.common import (
    Badge,
    Card,
    EmptyState,
    PageHeader,
    StatCard,
    make_label,
    setup_table,
    stretch_column,
)

log = logging.getLogger(__name__)

GUN_KISA = ("Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz")


class DashboardPage(Page):
    nav_title = "📊  Bugün"
    nav_key = "panel"
    nav_group = "yonetim"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)

        self.header = PageHeader("📊 Bugün", "")
        self.root.addWidget(self.header)

        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        icerik = QWidget()
        duzen = QVBoxLayout(icerik)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
        )
        duzen.setSpacing(metrics.PAGE_SPACING)

        # --- Günün sayıları ---
        ozet = QHBoxLayout()
        ozet.setSpacing(metrics.PAGE_SPACING)
        self.revenue_card = StatCard("CİRO", "-")
        self.customers_card = StatCard("MÜŞTERİ", "-", "Tamamlanan sepet")
        self.items_card = StatCard("SATILAN ÜRÜN", "-")
        self.avg_card = StatCard("ORTALAMA SEPET", "-")
        self.profit_card = StatCard("BRÜT KÂR", "-")
        self.stock_card = StatCard("STOK DEĞERİ", "-", "Eldeki malın maliyeti")
        for kart in (
            self.revenue_card, self.customers_card, self.items_card,
            self.avg_card, self.profit_card, self.stock_card,
        ):
            ozet.addWidget(kart)
        duzen.addLayout(ozet)

        # --- Ödeme kırılımı (SALES_FIRST) ---
        self.payment_card = Card()
        self.payment_card.body.addWidget(make_label("Ödeme", "sectionTitle"))
        self.payment_grid = QGridLayout()
        self.payment_grid.setSpacing(8)
        self.payment_card.body.addLayout(self.payment_grid)
        self.payment_hint = make_label("", "cardHint", wrap=True)
        self.payment_card.body.addWidget(self.payment_hint)
        duzen.addWidget(self.payment_card)

        # --- Dikkat (INVENTORY_TRACKED) ---
        self.attention_card = Card()
        self.attention_card.body.addWidget(make_label("Dikkat", "sectionTitle"))
        self.attention_grid = QGridLayout()
        self.attention_grid.setSpacing(8)
        self.attention_card.body.addLayout(self.attention_grid)
        self.advisory_label = make_label("", "cardHint", wrap=True)
        self.attention_card.body.addWidget(self.advisory_label)
        duzen.addWidget(self.attention_card)

        # --- Saatlik satış (SALES_FIRST) ---
        self.hourly_card = Card()
        self.hourly_card.body.addWidget(make_label("Saatlik Satış", "sectionTitle"))
        self.hourly_chart = SimpleBarChart()
        self.hourly_card.body.addWidget(self.hourly_chart)
        duzen.addWidget(self.hourly_card)

        # --- Gün karşılaştırması (SALES_FIRST) ---
        self.compare_card = Card()
        self.compare_card.body.addWidget(make_label("Karşılaştırma", "sectionTitle"))
        self.compare_table = QTableWidget(0, 3)
        setup_table(self.compare_table, ["Dönem", "Ciro", "Satılan"])
        stretch_column(self.compare_table, "Dönem")
        self.compare_table.setMaximumHeight(metrics.TABLE_ROW_HEIGHT * 5)
        self.compare_card.body.addWidget(self.compare_table)
        duzen.addWidget(self.compare_card)

        # --- En çok satanlar ---
        self.top_card = Card()
        self.top_card.body.addWidget(
            make_label("Bugün En Çok Satanlar", "sectionTitle")
        )
        self.top_table = QTableWidget(0, 4)
        setup_table(self.top_table, ["Ürün", "Adet", "Ciro", "Kâr"])
        stretch_column(self.top_table, "Ürün")
        self.top_table.setMaximumHeight(metrics.TABLE_ROW_HEIGHT * 7)
        self.top_card.body.addWidget(self.top_table)
        self.top_empty = EmptyState(
            "Bugün henüz satış yok",
            "Satış ekranından ürün okutunca burada görünür.",
        )
        self.top_card.body.addWidget(self.top_empty)
        duzen.addWidget(self.top_card)

        # --- Yavaş hareket edenler (INVENTORY_TRACKED) ---
        self.slow_card = Card()
        self.slow_card.body.addWidget(
            make_label("Uzun Süredir Satılmayanlar", "sectionTitle")
        )
        self.slow_hint = make_label("", "cardHint", wrap=True)
        self.slow_card.body.addWidget(self.slow_hint)
        self.slow_table = QTableWidget(0, 3)
        setup_table(self.slow_table, ["Ürün", "Stok", "Bağlı Para"])
        stretch_column(self.slow_table, "Ürün")
        self.slow_table.setMaximumHeight(metrics.TABLE_ROW_HEIGHT * 7)
        self.slow_card.body.addWidget(self.slow_table)
        duzen.addWidget(self.slow_card)

        duzen.addStretch(1)
        kaydirma.setWidget(icerik)
        self.root.addWidget(kaydirma, 1)

    # ===================== Tazeleme ======================================
    def refresh(self) -> None:
        try:
            if self.services.settings.is_sales_first():
                self._refresh_sales_first()
            else:
                self._refresh_inventory()
        except Exception:
            log.exception("Panel verisi okunamadı")

    def _set_mode_visibility(self, sales_first: bool) -> None:
        # SALES_FIRST'te kâr, stok değeri, dikkat ve ölü stok GÖSTERİLMEZ.
        self.profit_card.setVisible(not sales_first)
        self.stock_card.setVisible(not sales_first)
        self.attention_card.setVisible(not sales_first)
        self.slow_card.setVisible(not sales_first)

        self.customers_card.setVisible(sales_first)
        self.avg_card.setVisible(sales_first)
        self.payment_card.setVisible(sales_first)
        self.hourly_card.setVisible(sales_first)
        self.compare_card.setVisible(sales_first)

        # "Kâr" sütunu yalnızca envanter kipinde anlamlıdır.
        kar_sutunu = self.top_table.columnCount() - 1
        self.top_table.setColumnHidden(kar_sutunu, sales_first)

    # ===================== SALES_FIRST ===================================
    def _refresh_sales_first(self) -> None:
        self._set_mode_visibility(True)
        panel = self.services.analytics.sales_first_dashboard()

        self.header.set_subtitle(
            f"{panel.business_date} · {panel.sale_count} işlem"
        )
        self.revenue_card.set_value(format_tl(panel.revenue))
        self.customers_card.set_value(
            str(panel.basket.basket_count), "Tamamlanan sepet"
        )
        self.items_card.set_value(str(panel.item_count))
        self.avg_card.set_value(
            format_tl(panel.basket.avg_basket_value),
            f"Sepet başına {fmt_decimal_trim(panel.basket.avg_items_per_basket)} ürün"
            if panel.basket.basket_count else "",
        )

        self._fill_payments(panel.payments)
        self._fill_top(panel.top_products, show_profit=False)
        self.hourly_chart.set_data(
            [(f"{saat:02d}", ciro) for saat, ciro, _ in panel.hourly]
        )
        self._fill_comparison(panel.comparison)

    def _fill_payments(self, kirilim) -> None:
        self._clear_grid(self.payment_grid)
        kovalar = kirilim.buckets()
        if not kovalar:
            self.payment_grid.addWidget(
                make_label("Bugün henüz satış yok.", "cardHint"), 0, 0
            )
            self.payment_hint.setVisible(False)
            return

        renkler = {"Nakit": theme.PRIMARY, "Kart": theme.CART}
        for sutun, (ad, tutar, yuzde) in enumerate(kovalar):
            rozet = Badge()
            renk = renkler.get(ad, theme.TEXT_MUTED)
            rozet.set_state(
                f"{ad}  {format_tl(tutar)}  ({fmt_percent(yuzde)})",
                renk, theme.SURFACE_ALT,
            )
            self.payment_grid.addWidget(rozet, 0, sutun)

        # Ödeme seçimi eklenmeden önceki satışlar asla nakit/kart sayılmaz.
        self.payment_hint.setText(
            "\"Kaydedilmemiş\", ödeme yöntemi seçilmeden önce yapılmış "
            "satışlardır; nakit ya da kart sayılmaz."
            if kirilim.kaydedilmemis else ""
        )
        self.payment_hint.setVisible(bool(kirilim.kaydedilmemis))

    def _fill_comparison(self, kiyas) -> None:
        self.compare_table.setRowCount(len(kiyas))
        for satir, (ad, ozet) in enumerate(kiyas):
            hucreler = (
                QTableWidgetItem(ad),
                QTableWidgetItem(format_tl(ozet.revenue)),
                QTableWidgetItem(str(ozet.item_count)),
            )
            for hucre in hucreler[1:]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(hucreler):
                self.compare_table.setItem(satir, sutun, hucre)

    # ===================== INVENTORY_TRACKED =============================
    def _refresh_inventory(self) -> None:
        self._set_mode_visibility(False)
        panel = self.services.analytics.dashboard()
        bugun = panel.today

        self.header.set_subtitle(
            f"{self.services.settings.calendar().today()} · {bugun.sale_count} işlem"
        )
        self.revenue_card.set_value(format_tl(bugun.revenue))
        self.profit_card.set_value(
            format_tl(bugun.gross_profit),
            f"Marj {fmt_percent(bugun.margin_percent)}" if bugun.revenue else "",
        )
        self.items_card.set_value(str(bugun.item_count))
        self.stock_card.set_value(format_tl(panel.stock_value))

        self._fill_attention(panel.attention, panel.advisories)
        self._fill_top(panel.top_products, show_profit=True)
        self._fill_slow()

    def _fill_attention(self, dikkat: dict, uyarilar: list[str]) -> None:
        self._clear_grid(self.attention_grid)
        kovalar = (
            ("kontrol_gerekli", StockState.NEEDS_CHECK),
            ("kritik", StockState.CRITICAL),
            ("dusuk", StockState.LOW),
            ("henuz_sayilmadi", StockState.NOT_COUNTED),
        )
        sutun = 0
        for anahtar, durum in kovalar:
            adet = dikkat.get(anahtar, 0)
            if not adet:
                continue
            on, arka = theme.level_colors(int(durum))
            rozet = Badge()
            rozet.set_state(f"{adet} ürün — {STOCK_STATE_LABELS[durum]}", on, arka)
            self.attention_grid.addWidget(rozet, 0, sutun)
            sutun += 1

        if sutun == 0:
            self.attention_grid.addWidget(
                make_label("Şu an dikkat gerektiren bir durum yok.", "cardHint"), 0, 0
            )
        self.advisory_label.setText(" ".join(uyarilar))
        self.advisory_label.setVisible(bool(uyarilar))

    def _fill_slow(self) -> None:
        gun = self.services.settings.slow_moving_days()
        try:
            yavaslar = self.services.analytics.slow_movers(limit=10)
            bagli = self.services.analytics.dead_capital()
        except Exception:
            log.exception("Yavaş hareket eden ürünler okunamadı")
            return

        self.slow_hint.setText(
            f"Son {gun} gündür satılmayan ürünler · toplam bağlı para: {format_tl(bagli)}"
            if yavaslar else f"Son {gun} gündür satılmayan ürün yok."
        )
        self.slow_table.setVisible(bool(yavaslar))
        self.slow_table.setRowCount(len(yavaslar))
        for satir, urun in enumerate(yavaslar):
            hucreler = (
                QTableWidgetItem(urun["name"]),
                QTableWidgetItem(str(urun["current_stock"])),
                QTableWidgetItem(format_tl(urun["stock_value"])),
            )
            for hucre in hucreler[1:]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(hucreler):
                self.slow_table.setItem(satir, sutun, hucre)

    # ===================== Ortak =========================================
    def _fill_top(self, urunler, show_profit: bool) -> None:
        self.top_table.setVisible(bool(urunler))
        self.top_empty.setVisible(not urunler)
        self.top_table.setRowCount(len(urunler))
        for satir, urun in enumerate(urunler):
            hucreler = [
                QTableWidgetItem(urun["name"]),
                QTableWidgetItem(str(urun["adet"])),
                QTableWidgetItem(format_tl(urun["ciro"])),
                QTableWidgetItem(format_tl(urun["kar"]) if show_profit else ""),
            ]
            for hucre in hucreler[1:]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(hucreler):
                self.top_table.setItem(satir, sutun, hucre)

    @staticmethod
    def _clear_grid(grid: QGridLayout) -> None:
        while grid.count():
            oge = grid.takeAt(0)
            if oge.widget() is not None:
                oge.widget().deleteLater()
