"""Bugün / Panel: günün özeti tek bakışta.

Grafik duvarı YOKTUR. Dükkân sahibi ekranı birkaç saniyede anlamalıdır:
ne kazandım, neye dikkat etmeliyim, ne satıyor.
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
from app.core.tr import fmt_percent
from app.ui import metrics, theme
from app.ui.pages.base import Page
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
        self.profit_card = StatCard("BRÜT KÂR", "-")
        self.items_card = StatCard("SATILAN ÜRÜN", "-")
        self.stock_card = StatCard("STOK DEĞERİ", "-", "Eldeki malın maliyeti")
        for kart in (self.revenue_card, self.profit_card, self.items_card, self.stock_card):
            ozet.addWidget(kart)
        duzen.addLayout(ozet)

        # --- Dikkat ---
        dikkat_kart = Card()
        dikkat_kart.body.addWidget(make_label("Dikkat", "sectionTitle"))
        self.attention_grid = QGridLayout()
        self.attention_grid.setSpacing(8)
        dikkat_kart.body.addLayout(self.attention_grid)
        self.advisory_label = make_label("", "cardHint", wrap=True)
        dikkat_kart.body.addWidget(self.advisory_label)
        duzen.addWidget(dikkat_kart)

        # --- En çok satanlar ---
        top_kart = Card()
        top_kart.body.addWidget(make_label("Bugün En Çok Satanlar", "sectionTitle"))
        self.top_table = QTableWidget(0, 4)
        setup_table(self.top_table, ["Ürün", "Adet", "Ciro", "Kâr"])
        stretch_column(self.top_table, "Ürün")
        self.top_table.setMaximumHeight(metrics.TABLE_ROW_HEIGHT * 7)
        top_kart.body.addWidget(self.top_table)
        self.top_empty = EmptyState(
            "Bugün henüz satış yok",
            "Hızlı Satış ekranından ürün okutunca burada görünür.",
        )
        top_kart.body.addWidget(self.top_empty)
        duzen.addWidget(top_kart)

        # --- Yavaş hareket edenler ---
        yavas_kart = Card()
        yavas_kart.body.addWidget(
            make_label("Uzun Süredir Satılmayanlar", "sectionTitle")
        )
        self.slow_hint = make_label("", "cardHint", wrap=True)
        yavas_kart.body.addWidget(self.slow_hint)
        self.slow_table = QTableWidget(0, 3)
        setup_table(self.slow_table, ["Ürün", "Stok", "Bağlı Para"])
        stretch_column(self.slow_table, "Ürün")
        self.slow_table.setMaximumHeight(metrics.TABLE_ROW_HEIGHT * 7)
        yavas_kart.body.addWidget(self.slow_table)
        duzen.addWidget(yavas_kart)

        duzen.addStretch(1)
        kaydirma.setWidget(icerik)
        self.root.addWidget(kaydirma, 1)

    # ===================== Tazeleme ======================================
    def refresh(self) -> None:
        try:
            panel = self.services.analytics.dashboard()
        except Exception:
            log.exception("Panel verisi okunamadı")
            return

        bugun = panel.today
        self.header.set_subtitle(
            f"{self.services.settings.calendar().today()} · {bugun.sale_count} işlem"
        )
        self.revenue_card.set_value(format_tl(bugun.revenue))
        self.profit_card.set_value(
            format_tl(bugun.gross_profit),
            f"Marj {fmt_percent(bugun.margin_percent)}" if bugun.revenue else "",
        )
        self.items_card.set_value(f"{bugun.item_count}")
        self.stock_card.set_value(format_tl(panel.stock_value))

        self._fill_attention(panel.attention, panel.advisories)
        self._fill_top(panel.top_products)
        self._fill_slow()

    def _fill_attention(self, dikkat: dict, uyarilar: list[str]) -> None:
        while self.attention_grid.count():
            oge = self.attention_grid.takeAt(0)
            if oge.widget() is not None:
                oge.widget().deleteLater()

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
            rozet.setCursor(Qt.CursorShape.PointingHandCursor)
            self.attention_grid.addWidget(rozet, 0, sutun)
            sutun += 1

        if sutun == 0:
            self.attention_grid.addWidget(
                make_label("Şu an dikkat gerektiren bir durum yok.", "cardHint"), 0, 0
            )
        self.advisory_label.setText(" ".join(uyarilar))
        self.advisory_label.setVisible(bool(uyarilar))

    def _fill_top(self, urunler) -> None:
        self.top_table.setVisible(bool(urunler))
        self.top_empty.setVisible(not urunler)
        self.top_table.setRowCount(len(urunler))
        for satir, urun in enumerate(urunler):
            hucreler = (
                QTableWidgetItem(urun["name"]),
                QTableWidgetItem(str(urun["adet"])),
                QTableWidgetItem(format_tl(urun["ciro"])),
                QTableWidgetItem(format_tl(urun["kar"])),
            )
            for hucre in hucreler[1:]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(hucreler):
                self.top_table.setItem(satir, sutun, hucre)

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
