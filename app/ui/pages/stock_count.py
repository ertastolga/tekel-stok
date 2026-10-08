"""Stok Sayımı: gerçek fiziksel alanlara göre.

Sayım TEK BİR 800 ürünlük listeyle yapılmaz; dükkân sahibi "Bira Dolabı"nı
sayar, sonra isterse "Depo"yu ekler.

En önemli koruma: bir ürün birden fazla yerde bulunuyorsa ve hepsi sayılmadıysa
STOĞU DEĞİŞTİRİLMEZ. Sadece dolabı sayıp toplam stokla karşılaştırmak devasa
sahte farklar üretirdi. Kullanıcıya bu sade Türkçeyle anlatılır ve eksik yeri
de saymak için tek düğme sunulur.

Kör sayım: sistem adedi ÖNCE gösterilmez, böylece sayan kişi sayıya göre
kendini ayarlamaz.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import DomainError
from app.core.models import CoverageState
from app.core.money import format_tl
from app.ui import metrics, shortcuts, sound, theme
from app.ui.dialogs.common_dialogs import ask_confirm, scanning_suspended, show_info
from app.ui.pages.base import Page
from app.ui.widgets.barcode_input import BarcodeInput, FocusKeeper
from app.ui.widgets.common import (
    Card,
    EmptyState,
    FlowLayout,
    PageHeader,
    ResultBanner,
    labeled,
    make_label,
    setup_table,
    stretch_column,
)

log = logging.getLogger(__name__)


class StockCountPage(Page):
    nav_title = "📋  Stok Sayımı"
    nav_key = "stok_sayimi"
    nav_group = "stok"
    accepts_scans = True
    completes_with_shortcut = True     # F10 = "Sayimi Bitir" (mevcut davranis)

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.session_id: int | None = None

        self.header = PageHeader(
            "📋 Stok Sayımı", "Bir bölüm seçin, ürünleri okutun ya da adet yazın."
        )
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
        )
        duzen.setSpacing(metrics.PAGE_SPACING)

        duzen.addWidget(self._build_setup())
        duzen.addWidget(self._build_scan())

        self.banner = ResultBanner()
        # İlk iletiye dek gizli: boş beyaz kutu anlamsızdı (M12b).
        self.banner.setVisible(False)
        self.banner.shown.connect(lambda _tur: self.banner.setVisible(True))
        duzen.addWidget(self.banner)

        self.table = QTableWidget(0, 5)
        setup_table(self.table, ["Ürün", "Sistem", "Sayılan", "Fark", "Durum"])
        stretch_column(self.table, "Ürün")
        self.table.cellDoubleClicked.connect(self._edit_counted)
        duzen.addWidget(self.table, 1)

        self.empty = EmptyState(
            "Sayım başlatılmadı",
            "Yukarıdan bir bölüm seçip 'Sayımı Başlat' düğmesine basın.",
        )
        duzen.addWidget(self.empty, 1)

        duzen.addLayout(self._build_bottom())
        self.root.addWidget(govde, 1)

        self.focus_keeper = FocusKeeper(self.barcode)
        self._render()

    # ===================== Kurulum =======================================
    def _build_setup(self) -> QWidget:
        kart = Card()
        # Akış: dar pencerede alt satıra iner (M12b: tek satır 1097 px istiyordu).
        kap = QWidget()
        satir = FlowLayout(kap, spacing=10)

        self.location_combo = QComboBox()
        self.location_combo.setMinimumWidth(220)
        satir.addWidget(labeled("Bölüm", self.location_combo, ""))

        self.blind_check = QCheckBox("Kör sayım (sistem adedini gösterme)")
        satir.addWidget(self.blind_check)

        self.start_button = QPushButton("Sayımı Başlat")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(self._start)
        satir.addWidget(self.start_button)

        self.add_location_button = QPushButton("Bu Bölümü de Say")
        self.add_location_button.clicked.connect(self._add_location)
        satir.addWidget(self.add_location_button)
        kart.body.addWidget(kap)

        self.scope_label = make_label("", "cardHint", wrap=True)
        kart.body.addWidget(self.scope_label)
        return kart

    def _build_scan(self) -> QWidget:
        kart = Card()
        kart.body.addWidget(make_label("SAYILAN ÜRÜNÜ OKUTUN", "cardTitle"))
        self.barcode = BarcodeInput("count")
        self.barcode.submitted.connect(self._count_by_code)
        kart.body.addWidget(self.barcode)
        kart.body.addWidget(
            make_label(
                "Her okutma 1 adet sayar. Listeden bir satıra çift tıklayarak "
                "adedi doğrudan yazabilirsiniz.",
                "cardHint", wrap=True,
            )
        )
        return kart

    def _build_bottom(self) -> QHBoxLayout:
        alt = QHBoxLayout()
        alt.setSpacing(10)
        self.summary_label = make_label("", "cardHint")
        alt.addWidget(self.summary_label)
        alt.addStretch(1)

        self.cancel_button = QPushButton("Sayımı İptal Et")
        self.cancel_button.clicked.connect(self._cancel)
        alt.addWidget(self.cancel_button)

        self.commit_button = QPushButton(
            shortcuts.label_with_key("tamamla", "SAYIMI BİTİR")
        )
        self.commit_button.setObjectName("primary")
        self.commit_button.setMinimumHeight(metrics.BIG_BUTTON_HEIGHT)
        self.commit_button.clicked.connect(self.complete)
        alt.addWidget(self.commit_button)
        return alt

    # ===================== Yaşam döngüsü =================================
    def on_activated(self) -> None:
        self.focus_keeper.start()
        self._load_locations()
        acik = self.services.counts.open_session()
        self.session_id = acik["id"] if acik else None
        if self.session_id:
            self.blind_check.setChecked(bool(acik["blind"]))
        self._render()

    def on_deactivated(self) -> None:
        self.focus_keeper.stop()

    def refresh(self) -> None:
        self._render()

    def _load_locations(self) -> None:
        secili = self.location_combo.currentData()
        self.location_combo.clear()
        for konum in self.services.catalog.locations():
            self.location_combo.addItem(konum["name"], konum["id"])
        self.location_combo.addItem("Tüm Dükkân", "ALL")
        if secili is not None:
            index = self.location_combo.findData(secili)
            if index >= 0:
                self.location_combo.setCurrentIndex(index)

    # ===================== Oturum ========================================
    def _start(self) -> None:
        secim = self.location_combo.currentData()
        try:
            if secim == "ALL":
                self.session_id = self.services.counts.start(
                    scope="ALL", blind=self.blind_check.isChecked()
                )
            else:
                self.session_id = self.services.counts.start(
                    [secim], blind=self.blind_check.isChecked()
                )
        except DomainError as hata:
            self.banner.show_error(hata.message)
            return
        self.banner.show_idle("Sayım başladı.", "Ürünleri okutun ya da adet yazın.")
        self.barcode.setFocus()
        self._render()

    def _add_location(self) -> None:
        if self.session_id is None:
            self.banner.show_warning("Önce sayımı başlatın.")
            return
        secim = self.location_combo.currentData()
        if secim == "ALL":
            self.banner.show_warning("Tüm dükkân zaten her yeri kapsar.")
            return
        try:
            self.services.counts.add_location(self.session_id, secim)
        except DomainError as hata:
            self.banner.show_error(hata.message)
            return
        self.banner.show_idle(
            "Bölüm eklendi.", f"{self.location_combo.currentText()} de sayılacak."
        )
        self._render()

    def _cancel(self) -> None:
        if self.session_id is None:
            return
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, "Sayım iptal edilsin mi?",
                "Girilen sayımlar silinir. Stok DEĞİŞMEZ.",
                accept_text="Evet, iptal et", danger=True,
            )
        if not onay:
            return
        self.services.counts.cancel(self.session_id)
        self.session_id = None
        self.banner.show_idle("Sayım iptal edildi.", "Stok değişmedi.")
        self._render()

    # ===================== Sayma =========================================
    def handle_scan(self, event) -> None:
        self._count_by_code(event.code)

    def _count_by_code(self, raw: str) -> None:
        if self.session_id is None:
            sound.error()
            self.banner.show_error("Önce sayımı başlatın.")
            return
        eslesme = self.services.barcodes.resolve(raw)
        if eslesme is None:
            sound.error()
            self.banner.show_error(
                "Ürün tanınmadı.",
                f"Barkod: {raw}. Sayıma eklemek için önce ürünü tanımlayın.",
            )
            return

        konum = self._active_location_id()
        if konum is None:
            sound.error()
            self.banner.show_error("Sayılacak bölüm seçili değil.")
            return
        try:
            toplam = self.services.counts.count_scan(
                self.session_id, eslesme.product_id, konum
            )
        except DomainError as hata:
            sound.error()
            self.banner.show_error(hata.message)
            return
        sound.scan()
        self.banner.show_success(
            "SAYILDI", eslesme.product_name, f"Bu üründen toplam: {toplam} adet"
        )
        self._render()

    def _active_location_id(self) -> int | None:
        """Okutmanın hangi konuma yazılacağı: seçili bölüm."""
        secim = self.location_combo.currentData()
        if secim == "ALL":
            konumlar = self.services.counts.session_locations(self.session_id)
            return konumlar[0]["id"] if konumlar else self._first_location_id()
        return secim

    def _first_location_id(self) -> int | None:
        konumlar = self.services.catalog.locations()
        return konumlar[0]["id"] if konumlar else None

    def _edit_counted(self, row: int, _column: int) -> None:
        """Listeden sayım: adedi doğrudan yaz."""
        if self.session_id is None:
            return
        satirlar = self.services.counts.lines(self.session_id)
        if row < 0 or row >= len(satirlar):
            return
        satir = satirlar[row]
        konum = self._active_location_id()
        if konum is None:
            return

        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout

        pencere = QDialog(self)
        pencere.setWindowTitle("Sayılan adet")
        duzen = QFormLayout(pencere)
        kutu = QSpinBox()
        kutu.setRange(0, 1_000_000)
        kutu.setValue(satir["counted_qty"] or 0)
        kutu.setProperty("scannerExempt", True)
        duzen.addRow(satir["name"], kutu)
        dugmeler = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        dugmeler.button(QDialogButtonBox.StandardButton.Ok).setText("Kaydet")
        dugmeler.button(QDialogButtonBox.StandardButton.Cancel).setText("Vazgeç")
        dugmeler.accepted.connect(pencere.accept)
        dugmeler.rejected.connect(pencere.reject)
        duzen.addRow(dugmeler)

        with scanning_suspended(self.main_window.router):
            kabul = pencere.exec() == QDialog.DialogCode.Accepted
        if not kabul:
            return
        self.services.counts.set_counted(
            self.session_id, satir["product_id"], konum, kutu.value()
        )
        self._render()

    # ===================== Bitirme =======================================
    def complete(self) -> None:
        if self.session_id is None:
            return

        buyuk = self.services.counts.large_differences(self.session_id)
        kismi = self.services.counts.coverage_report(self.session_id)

        ayrinti = []
        if buyuk:
            ilk = ", ".join(f"{ad} ({fark:+d})" for ad, fark in buyuk[:3])
            ayrinti.append(f"Büyük fark var: {ilk}. Sayımı kontrol etmek ister misiniz?")
        if kismi:
            adlar = ", ".join(ad for ad, _ in kismi[:3])
            ayrinti.append(
                f"{len(kismi)} ürün birden fazla yerde bulunuyor ve hepsi "
                f"sayılmadı ({adlar}). Bu ürünlerin stoğu DEĞİŞTİRİLMEYECEK."
            )

        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, "Sayım bitirilsin mi?",
                "\n\n".join(ayrinti) if ayrinti else "Farklar stoğa işlenecek.",
                accept_text="Evet, bitir",
            )
        if not onay:
            return

        try:
            sonuc = self.services.counts.commit(self.session_id)
        except DomainError as hata:
            sound.error()
            self.banner.show_error(hata.message)
            return
        except Exception:
            log.exception("Sayım tamamlanamadı")
            sound.error()
            self.banner.show_error("İşlem tamamlanamadı. Stok değiştirilmedi.")
            return

        self.session_id = None
        self._show_result(sonuc)
        self._render()

    def _show_result(self, sonuc) -> None:
        """Sonuç sade Türkçeyle özetlenir; kural işletmez, yalnızca anlatır."""
        satirlar = [f"{sonuc.applied_count} üründe stok düzeltildi."]
        if sonuc.total_diff_value:
            satirlar.append(f"Değer farkı: {format_tl(sonuc.total_diff_value)}")
        if sonuc.baseline_count:
            satirlar.append(f"{sonuc.baseline_count} ürün ilk kez sayıldı.")

        uyari = []
        if sonuc.skipped_partial:
            adlar = ", ".join(ad for ad, _ in sonuc.skipped_partial[:5])
            eksik = sonuc.skipped_partial[0][1]
            uyari.append(
                f"{len(sonuc.skipped_partial)} ürün birden fazla yerde bulunduğu ve "
                f"hepsi sayılmadığı için değiştirilmedi: {adlar}."
                + (f" Eksik kalan yer: {', '.join(eksik)}." if eksik else "")
            )
        if sonuc.skipped_changed:
            uyari.append(
                f"{len(sonuc.skipped_changed)} ürün sayım sırasında satıldığı için "
                "atlandı: " + ", ".join(sonuc.skipped_changed[:5]) + "."
            )

        if uyari:
            sound.warning()
            self.banner.show_warning(
                "SAYIM BİTTİ", " ".join(satirlar), " ".join(uyari)
            )
            with scanning_suspended(self.main_window.router):
                show_info(self, "Sayım sonucu", " ".join(satirlar) + "\n\n" + "\n\n".join(uyari))
        else:
            sound.success()
            self.banner.show_success("✓ SAYIM BİTTİ", " ".join(satirlar))

    # ===================== Çizim =========================================
    def _render(self) -> None:
        acik = self.session_id is not None
        self.start_button.setEnabled(not acik)
        self.location_combo.setEnabled(True)
        self.blind_check.setEnabled(not acik)
        self.add_location_button.setEnabled(acik)
        self.commit_button.setEnabled(acik)
        self.cancel_button.setEnabled(acik)
        self.barcode.setEnabled(acik)
        self.table.setVisible(acik)
        self.empty.setVisible(not acik)

        if not acik:
            self.scope_label.setText("")
            self.summary_label.setText("")
            self.table.setRowCount(0)
            return

        konumlar = self.services.counts.session_locations(self.session_id)
        adlar = ", ".join(k["name"] for k in konumlar) or "Tüm Dükkân"
        self.scope_label.setText(f"Sayılan bölümler: {adlar}")

        satirlar = self.services.counts.lines(self.session_id)
        kor = self.blind_check.isChecked()
        self.table.setRowCount(len(satirlar))
        sayilan = 0

        for index, satir in enumerate(satirlar):
            ad = QTableWidgetItem(satir["name"])
            sistem_metni = "—" if kor and satir["counted_qty"] is None else str(
                satir["current_stock"]
            )
            sistem = QTableWidgetItem(sistem_metni)
            sayilan_metni = "—" if satir["counted_qty"] is None else str(
                satir["counted_qty"]
            )
            sayilan_hucre = QTableWidgetItem(sayilan_metni)

            if satir["counted_qty"] is None:
                fark_metni, durum = "—", "Sayılmadı"
            else:
                sayilan += 1
                fark = satir["counted_qty"] - satir["current_stock"]
                fark_metni = f"{fark:+d}" if fark else "0"
                durum = "Tamam" if fark == 0 else "Fark var"
            fark_hucre = QTableWidgetItem(fark_metni)
            durum_hucre = QTableWidgetItem(durum)

            for hucre in (sistem, sayilan_hucre, fark_hucre):
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(
                (ad, sistem, sayilan_hucre, fark_hucre, durum_hucre)
            ):
                self.table.setItem(index, sutun, hucre)

        self.summary_label.setText(
            f"{sayilan} / {len(satirlar)} ürün sayıldı"
        )
