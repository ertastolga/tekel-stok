"""🩺 Sistem Durumu (YÖNETİM): uygulamanın sağlığı tek bakışta (§6.5).

Hızlı denetimler açılışta; tam bütünlük ve derin tutarlılık denetimi "Tam
denetim yap" ile istek üzerine (büyük veride birkaç saniye sürebilir). Her
satırın durumu metinle de yazılır. Destek paketi buradan oluşturulur (M10d).
"""
from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.clock import local_now
from app.services.system_status import DURUMLAR
from app.ui import metrics
from app.ui.dialogs.common_dialogs import (
    bekleme_imleci,
    scanning_suspended,
    show_error,
    show_info,
)
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
        # Durum tablosu sayfanın ASIL içeriğidir: kalan alanın hepsini alır
        # (M12b: uyarı kutusu yüzünden 1,5 satıra sıkışıyordu).
        self.table.setMinimumHeight(240)
        duzen.addWidget(self.table, 1)

        kart = Card()
        kart.body.addWidget(make_label("Uyarılar", "cardTitle"))
        self.advisory_list = QListWidget()
        self.advisory_list.setMaximumHeight(96)
        kart.body.addWidget(self.advisory_list)
        satir = QHBoxLayout()
        self.deep_button = QPushButton("Tam denetim yap")
        self.deep_button.clicked.connect(self.run_deep_check)
        satir.addWidget(self.deep_button)
        self.deep_result = make_label("", "cardHint", wrap=True)
        satir.addWidget(self.deep_result, 1)
        kart.body.addLayout(satir)
        destek = QHBoxLayout()
        self.include_db_check = QCheckBox("Veritabanı kopyası ekle (önerilmez)")
        self.include_db_check.setToolTip(
            "Yalnızca destek açıkça isterse. PIN bilgileri silinir, kişisel klasör yolları "
            "gizlenir; yine de satış ve ürün verilerinizi içerir.")
        destek.addWidget(self.include_db_check)
        destek.addStretch(1)
        self.support_button = QPushButton("Destek paketi oluştur…")
        self.support_button.clicked.connect(self._destek_paketi)
        destek.addWidget(self.support_button)
        kart.body.addLayout(destek)
        kart.body.addWidget(make_label(
            "Destek paketi; sistem bilgisi, ayarlar (PIN hariç), kayıt dosyaları ve "
            "sınama raporunu tek ZIP dosyasında toplar. Kişisel klasör yolları gizlenir. "
            "Veritabanı varsayılan olarak EKLENMEZ.", "cardHint", wrap=True))
        duzen.addWidget(kart)
        self.root.addWidget(govde, 1)

    def on_activated(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        try:
            with bekleme_imleci():                  # hızlı denetim büyük veride ~1 s
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
            with bekleme_imleci():
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
        varsayilan = f"tekelstok_destek_{local_now():%Y%m%d_%H%M}.zip"
        with scanning_suspended(self.main_window.router):
            yol, _ = QFileDialog.getSaveFileName(
                self, "Destek paketini kaydet",
                str(self.services.backup.manual_dir() / varsayilan), "ZIP (*.zip)")
        if yol:
            self.create_support_package(yol, self.include_db_check.isChecked())

    def create_support_package(self, yol, veritabani_ekle: bool = False):
        tanilama = [
            {"kod": olay.code, "sonuc": sonuc.value, "tus": olay.key_count,
             "ort_ara_ms": round(olay.avg_gap_ms, 1), "en_uzun_ara_ms": round(olay.max_gap_ms, 1),
             "sonlandirici": olay.terminator, "kaynak": olay.source}
            for olay, sonuc in self.main_window.router.diagnostics(200)
        ]
        try:
            with bekleme_imleci():
                hedef = self.services.support.olustur(
                    yol, veritabani_ekle=veritabani_ekle, tanilama=tanilama,
                    qt_surumu=qt_surumu())
        except Exception as hata:
            log.exception("Destek paketi oluşturulamadı")
            show_error(self, "Destek paketi oluşturulamadı.", str(hata))
            return None
        with scanning_suspended(self.main_window.router):
            show_info(self, "Destek paketi hazır", f"Kaydedildi: {hedef}")
        return hedef
