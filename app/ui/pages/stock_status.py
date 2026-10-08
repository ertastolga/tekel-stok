"""Stok Durumu: neyin bittiğini, neyin fazla olduğunu tek ekranda görme."""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.models import STOCK_STATE_LABELS, StockState
from app.core.money import format_tl
from app.ui import metrics
from app.ui.pages.base import Page
from app.ui.widgets.common import (
    Card,
    CardGrid,
    EmptyState,
    PageHeader,
    StatCard,
    make_label,
    setup_table,
    stretch_column,
)

log = logging.getLogger(__name__)


class StockStatusPage(Page):
    nav_title = "📈  Stok Durumu"
    nav_key = "stok_durumu"
    nav_group = "stok"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)

        self.header = PageHeader("📈 Stok Durumu", "")
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
        )
        duzen.setSpacing(metrics.PAGE_SPACING)

        self.value_card = StatCard("STOK DEĞERİ", "-", "Eldeki malın maliyeti")
        self.critical_card = StatCard("KRİTİK", "-")
        self.low_card = StatCard("DÜŞÜK", "-")
        self.check_card = StatCard("KONTROL GEREKLİ", "-", "Stok eksiye düşmüş")
        self.uncounted_card = StatCard("HENÜZ SAYILMADI", "-", "Stoğu bilinmiyor")
        # Dar pencerede kartlar iki satıra iner (M12b: 1000×600'de taşıyordu).
        self.cards = CardGrid((
            self.value_card, self.critical_card, self.low_card,
            self.check_card, self.uncounted_card,
        ), spacing=metrics.PAGE_SPACING)
        duzen.addWidget(self.cards)

        filtre = Card()
        satir = QHBoxLayout()
        satir.setSpacing(10)
        satir.addWidget(make_label("Göster"))
        self.state_combo = QComboBox()
        for durum in (
            StockState.NEEDS_CHECK, StockState.CRITICAL, StockState.LOW,
            StockState.NOT_COUNTED, StockState.NORMAL,
        ):
            self.state_combo.addItem(STOCK_STATE_LABELS[durum], int(durum))
        self.state_combo.currentIndexChanged.connect(self.refresh)
        satir.addWidget(self.state_combo)

        self.recompute_button = QPushButton("Stokları Defterden Yeniden Hesapla")
        self.recompute_button.clicked.connect(self._recompute)
        satir.addStretch(1)
        satir.addWidget(self.recompute_button)
        filtre.body.addLayout(satir)
        duzen.addWidget(filtre)

        self.table = QTableWidget(0, 5)
        setup_table(self.table, ["Ürün", "Stok", "Az Sınırı", "Kritik Sınırı", "Değer"])
        stretch_column(self.table, "Ürün")
        duzen.addWidget(self.table, 1)

        self.empty = EmptyState("Bu durumda ürün yok", "")
        duzen.addWidget(self.empty, 1)
        self.root.addWidget(govde, 1)

    def refresh(self) -> None:
        try:
            dikkat = self.services.products.attention_counts()
            self.value_card.set_value(format_tl(self.services.analytics.stock_value()))
            self.critical_card.set_value(str(dikkat["kritik"]))
            self.low_card.set_value(str(dikkat["dusuk"]))
            self.check_card.set_value(str(dikkat["kontrol_gerekli"]))
            self.uncounted_card.set_value(str(dikkat["henuz_sayilmadi"]))

            urunler = self.services.products.by_stock_state(
                self.state_combo.currentData(), limit=300
            )
        except Exception:
            log.exception("Stok durumu okunamadı")
            return

        dolu = bool(urunler)
        self.table.setVisible(dolu)
        self.empty.setVisible(not dolu)
        self.empty.set_text(
            f"{self.state_combo.currentText()} durumunda ürün yok", ""
        )
        self.table.setRowCount(len(urunler))
        for satir, urun in enumerate(urunler):
            hucreler = (
                QTableWidgetItem(urun["name"]),
                QTableWidgetItem(str(urun["current_stock"])),
                QTableWidgetItem(str(urun["min_stock"])),
                QTableWidgetItem(str(urun["critical_stock"])),
                QTableWidgetItem(format_tl(urun["stock_value"])),
            )
            for hucre in hucreler[1:]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(hucreler):
                self.table.setItem(satir, sutun, hucre)

    def _recompute(self) -> None:
        """Bakım işlemi: önbellekleri defterden yeniden kurar."""
        from app.services.security_service import ProtectedAction
        from app.ui.dialogs.common_dialogs import (
            ask_confirm,
            bekleme_imleci,
            scanning_suspended,
            show_info,
        )

        if not self.guard_require(ProtectedAction.STOK_YENIDEN_HESAPLA):
            return

        with scanning_suspended(self.main_window.router):
            if not ask_confirm(
                self, "Stoklar defterden yeniden hesaplansın mı?",
                "Bu işlem stok hareketlerini baştan toplar. Veri KAYBOLMAZ.",
                accept_text="Evet, hesapla",
            ):
                return
        try:
            with bekleme_imleci():                 # 100k satışta birkaç saniye (M11)
                self.services.inventory.recompute()
                sorunlar = self.services.db.check_invariants(deep=True)
        except Exception:
            log.exception("Yeniden hesaplama başarısız")
            return
        with scanning_suspended(self.main_window.router):
            show_info(
                self, "Yeniden hesaplama",
                "Stoklar yeniden hesaplandı."
                + ("" if not sorunlar else f"\n\n{len(sorunlar)} konu incelenmeli."),
            )
        self.refresh()
