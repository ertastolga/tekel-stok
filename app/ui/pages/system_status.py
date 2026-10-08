"""🩺 Sistem Durumu (YÖNETİM): uygulamanın sağlığı tek bakışta (§6.5).

Hızlı denetimler açılışta; tam bütünlük ve derin tutarlılık denetimi "Tam
denetim yap" ile istek üzerine (büyük veride birkaç saniye sürebilir). Her
satırın durumu metinle de yazılır. Destek paketi buradan oluşturulur (M10d).
"""
from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.services.system_status import DURUMLAR
from app.ui import metrics
from app.ui.pages.base import Page
from app.ui.widgets.common import Card, PageHeader, make_label, setup_table, stretch_column

log = logging.getLogger(__name__)


def qt_surumu() -> str:
    import PySide6
    from PySide6.QtCore import qVersion

    return f"Qt {qVersion()} · PySide6 {PySide6.__version__}"


class SystemStatusPage(Page):
    nav_title = "🩺  Sistem Durumu"
    nav_key = "sistem_durumu"
    nav_group = "yonetim"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.header = PageHeader("🩺 Sistem Durumu",
                                 "Uygulamanın, verinin, yedeklerin ve cihazların durumu.")
        self.refresh_button = QPushButton("Yenile")
        self.refresh_button.clicked.connect(self.refresh)
        self.header.add_action(self.refresh_button)
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
                                 metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V)
        duzen.setSpacing(metrics.PAGE_SPACING)

        self.table = QTableWidget(0, 3)
        setup_table(self.table, ["Öğe", "Değer", "Durum"])
        stretch_column(self.table, "Değer")
        duzen.addWidget(self.table, 2)

        kart = Card()
        kart.body.addWidget(make_label("Uyarılar", "cardTitle"))
        self.advisory_list = QListWidget()
        self.advisory_list.setMaximumHeight(120)
        kart.body.addWidget(self.advisory_list)
        satir = QHBoxLayout()
        self.deep_button = QPushButton("Tam denetim yap")
        self.deep_button.clicked.connect(self.run_deep_check)
        satir.addWidget(self.deep_button)
        self.deep_result = make_label("", "cardHint", wrap=True)
        satir.addWidget(self.deep_result, 1)
        self.support_button = QPushButton("Destek paketi oluştur…")
        self.support_button.clicked.connect(self._destek_paketi)
        satir.addWidget(self.support_button)
        kart.body.addLayout(satir)
        duzen.addWidget(kart, 1)
        self.root.addWidget(govde, 1)

    def on_activated(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        try:
            satirlar = self.services.system_status.satirlar(qt_surumu())
            uyarilar = self.services.system_status.uyarilar()
        except Exception:
            log.exception("Sistem durumu okunamadı")
            return
        self.table.setRowCount(len(satirlar))
        for i, s in enumerate(satirlar):
            for j, metin in enumerate((s.baslik, s.deger, DURUMLAR[s.durum])):
                self.table.setItem(i, j, QTableWidgetItem(metin))
        self.advisory_list.clear()
        for uyari in uyarilar or ["Uyarı yok."]:
            self.advisory_list.addItem(uyari)

    def run_deep_check(self) -> list[str]:
        """Tam bütünlük + derin tutarlılık denetimi (istek üzerine)."""
        try:
            sorunlar = self.services.system_status.derin_denetim()
        except Exception:
            log.exception("Tam denetim yapılamadı")
            self.deep_result.setText("Denetim yapılamadı; kayıt dosyasına yazıldı.")
            return ["denetim yapılamadı"]
        self.deep_result.setText(
            "Tam denetim: sorun bulunmadı." if not sorunlar else
            f"Tam denetim: {len(sorunlar)} sorun bulundu — " + "; ".join(sorunlar[:3])
            + (" … (tamamı destek paketinde)" if len(sorunlar) > 3 else ""))
        return sorunlar

    def _destek_paketi(self) -> None:
        """M10d'de doldurulur."""
        self.notify("Destek paketi henüz hazır değil.")
