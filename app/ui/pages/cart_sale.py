"""Sepetli Satış: önce sepete ekle, sonra tek seferde tamamla.

Sepette ürün varken stok ve ciro DEĞİŞMEZ; hiçbir şey satılmış sayılmaz.
Yalnızca "Satışı Tamamla" tek bir işlemde her şeyi yazar.

Aynı ürünü tekrar okutmak yeni satır açmaz, MEVCUT satırın adedini artırır:
dükkân sahibi tek şişeyi 10 kez okutabilir.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import DomainError
from app.core.money import format_tl
from app.ui import metrics, shortcuts, sound, theme
from app.ui.dialogs.common_dialogs import (
    PackConfirmDialog,
    ask_confirm,
    scanning_suspended,
)
from app.ui.dialogs.unknown_barcode import UnknownBarcodeDialog
from app.ui.pages.base import Page
from app.ui.widgets.barcode_input import BarcodeInput, FocusKeeper
from app.ui.widgets.common import (
    Card,
    EmptyState,
    PageHeader,
    ResultBanner,
    make_label,
    setup_table,
    stretch_column,
)
from app.services.cart_service import Cart

log = logging.getLogger(__name__)


class CartSalePage(Page):
    nav_title = "🛒  Sepetli Satış"
    nav_key = "sepetli_satis"
    nav_group = "gunluk"
    accepts_scans = True

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.cart = Cart()

        self.header = PageHeader(
            "🛒 Sepetli Satış", "Ürünleri okutun, sonunda satışı tamamlayın."
        )
        self.mode_button = QPushButton("⚡  Hızlı Satışa Geç")
        self.mode_button.clicked.connect(lambda: self.main_window.go_to("hizli_satis"))
        self.header.add_action(self.mode_button)
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
        )
        duzen.setSpacing(metrics.PAGE_SPACING)

        kart = Card()
        kart.body.addWidget(make_label("BARKOD BEKLENİYOR", "cardTitle"))
        self.barcode = BarcodeInput("sale")
        self.barcode.submitted.connect(self._add_by_code)
        kart.body.addWidget(self.barcode)
        duzen.addWidget(kart)

        self.banner = ResultBanner()
        duzen.addWidget(self.banner)

        self.table = QTableWidget(0, 4)
        setup_table(self.table, ["Ürün", "Adet", "Birim Fiyat", "Tutar"])
        stretch_column(self.table, "Ürün")
        duzen.addWidget(self.table, 1)

        self.empty = EmptyState(
            "Sepet boş",
            "Satmak istediğiniz ürünlerin barkodunu okutun.",
        )
        duzen.addWidget(self.empty, 1)

        alt = QHBoxLayout()
        alt.setSpacing(10)
        self.total_label = make_label("Toplam: 0 TL", "cardValue")
        alt.addWidget(self.total_label)
        alt.addStretch(1)

        self.remove_button = QPushButton("Seçili Satırı Çıkar")
        self.remove_button.clicked.connect(self._remove_selected)
        alt.addWidget(self.remove_button)

        self.clear_button = QPushButton("Sepeti Boşalt")
        self.clear_button.clicked.connect(self._clear_cart)
        alt.addWidget(self.clear_button)

        self.checkout_button = QPushButton(
            shortcuts.label_with_key("tamamla", "SATIŞI TAMAMLA")
        )
        self.checkout_button.setObjectName("primary")
        self.checkout_button.setProperty("class", "bigAction")
        self.checkout_button.setMinimumHeight(metrics.BIG_BUTTON_HEIGHT)
        self.checkout_button.clicked.connect(self.complete)
        alt.addWidget(self.checkout_button)
        duzen.addLayout(alt)

        self.root.addWidget(govde, 1)
        self.focus_keeper = FocusKeeper(self.barcode)
        self._render()

    # ===================== Yaşam döngüsü =================================
    def on_activated(self) -> None:
        self.focus_keeper.start()
        self.barcode.setFocus()
        self._offer_draft_recovery()
        self._render()

    def on_deactivated(self) -> None:
        self.focus_keeper.stop()
        # Ekrandan çıkarken sepet KAYBOLMAZ: taslak olarak diske yazılır.
        if not self.cart.is_empty:
            try:
                self.services.cart.save_draft(self.cart)
            except Exception:
                log.exception("Sepet taslağı kaydedilemedi")

    def refresh(self) -> None:
        self._render()

    def _offer_draft_recovery(self) -> None:
        """Yarım kalmış sepet KENDİLİĞİNDEN tamamlanmaz; kullanıcı karar verir."""
        if not self.cart.is_empty:
            return
        taslaklar = self.services.cart.open_drafts()
        if not taslaklar:
            return
        taslak = taslaklar[0]
        if not taslak["satir_sayisi"]:
            return

        with scanning_suspended(self.main_window.router):
            devam = ask_confirm(
                self,
                "Tamamlanmamış bir sepet bulundu.",
                f"{taslak['satir_sayisi']} kalem. Devam etmek ister misiniz?",
                accept_text="Devam Et",
                reject_text="Sepeti Sil",
            )
        if devam:
            self.cart = self.services.cart.load_draft(taslak["id"])
        else:
            self.services.cart.discard_draft(taslak["id"])
        self._render()

    # ===================== Okutma ========================================
    def handle_scan(self, event) -> None:
        self._add_by_code(event.code)

    def _add_by_code(self, raw: str) -> None:
        eslesme = self.services.barcodes.resolve(raw)
        if eslesme is None:
            sound.error()
            self.banner.show_error("Ürün tanınmadı.", f"Barkod: {raw}")

            pencere = None

            def engellendi(_event):
                if pencere is not None:
                    pencere.notify_blocked()

            with scanning_suspended(self.main_window.router, engellendi):
                pencere = UnknownBarcodeDialog(raw, self.services, self)
                kabul = pencere.exec()
                urun_id = pencere.product_id if kabul else None
            if urun_id is None:
                return
            self._add_product(urun_id, 1, raw, 1)
            return

        adet = eslesme.quantity
        if eslesme.needs_pack_confirm and self.services.settings.pack_confirm_in_sale():
            with scanning_suspended(self.main_window.router):
                onay = PackConfirmDialog.confirm(
                    eslesme.product_name, adet, "adet", self
                )
            if not onay:
                return
        self._add_product(eslesme.product_id, adet, eslesme.barcode, eslesme.multiplier)

    def _add_product(self, product_id: int, quantity: int, barcode: str,
                     multiplier: int) -> None:
        try:
            satir = self.services.cart.add_product(
                self.cart, product_id, quantity, barcode, multiplier
            )
        except DomainError as hata:
            sound.error()
            self.banner.show_error(hata.message)
            return
        sound.success()
        self.banner.show_success(
            "SEPETE EKLENDİ",
            f"{satir.product_name} × {satir.quantity}",
            f"Sepet toplamı: {format_tl(self.cart.total)}",
        )
        self._render()

    # ===================== Sepet işlemleri ===============================
    def _selected_product_id(self) -> int | None:
        satir = self.table.currentRow()
        if satir < 0 or satir >= len(self.cart.lines):
            return None
        return self.cart.lines[satir].product_id

    def _remove_selected(self) -> None:
        urun_id = self._selected_product_id()
        if urun_id is None:
            self.banner.show_warning("Önce listeden bir satır seçin.")
            return
        self.cart.remove(urun_id)
        self._render()

    def _clear_cart(self) -> None:
        if self.cart.is_empty:
            return
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, "Sepet boşaltılsın mı?",
                "Sepetteki ürünler silinir. Hiçbir satış yapılmaz.",
                accept_text="Evet, boşalt", danger=True,
            )
        if not onay:
            return
        if self.cart.draft_id is not None:
            self.services.cart.discard_draft(self.cart.draft_id)
        self.cart = Cart()
        self._render()

    def complete(self) -> None:
        """F10 / SATIŞI TAMAMLA — tek atomik işlem."""
        if self.cart.is_empty:
            sound.error()
            self.banner.show_error("Sepet boş.", "Önce ürün okutun.")
            return
        try:
            sonuc = self.services.cart.checkout(self.cart)
        except DomainError as hata:
            sound.error()
            self.banner.show_error(hata.message)
            return
        except Exception:
            log.exception("Sepet ödemesi tamamlanamadı")
            sound.error()
            self.banner.show_error(
                "İşlem tamamlanamadı. Stok ve satış bilgileri değiştirilmedi."
            )
            return

        sound.success()
        uyari = " · stok kontrolü gerekli" if sonuc.warnings else ""
        self.banner.show_success(
            "✓ SATIŞ TAMAMLANDI",
            f"{sonuc.item_count} ürün · {format_tl(sonuc.total_amount)}{uyari}",
        )
        self._render()
        self.main_window.refresh_today()

    # ===================== Çizim =========================================
    def _render(self) -> None:
        dolu = not self.cart.is_empty
        self.table.setVisible(dolu)
        self.empty.setVisible(not dolu)
        self.checkout_button.setEnabled(dolu)
        self.remove_button.setEnabled(dolu)
        self.clear_button.setEnabled(dolu)

        self.table.setRowCount(len(self.cart.lines))
        for satir, kalem in enumerate(self.cart.lines):
            ad = QTableWidgetItem(kalem.product_name)
            adet = QTableWidgetItem(str(kalem.quantity))
            adet.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            birim = QTableWidgetItem(format_tl(kalem.unit_price))
            birim.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            tutar = QTableWidgetItem(format_tl(kalem.line_total))
            tutar.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            for sutun, hucre in enumerate((ad, adet, birim, tutar)):
                self.table.setItem(satir, sutun, hucre)

        self.total_label.setText(f"Toplam: {format_tl(self.cart.total)}")
        self.total_label.setStyleSheet(
            f"color: {theme.PRIMARY_DARK};" if dolu else ""
        )
