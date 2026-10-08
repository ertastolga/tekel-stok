"""Stok Girişi: gelen malı okutup stoğa ekleme.

Bir mal kabulü bir FİŞTİR. Operatör okuturken hiçbir şey kalıcı olmaz; fiş
taslakta birikir ve yalnızca "Girişi Tamamla" ile tek işlemde stoğa işlenir.

Koli barkodu burada SORULMADAN uygulanır: koli okutmak zaten "24 adet geldi"
demektir. (Satışta ise onay istenir — orada yanlışlık pahalıdır.)

Alış fiyatı son bilinen değerle ÖN DOLDURULUR; değişmediyse operatör hiçbir şey
yapmaz. Her barkoddan sonra fiyat sorulmaz, akış kesilmez.
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
from app.core.money import format_tl, kurus_to_tl_text, tl_to_kurus
from app.ui import metrics, shortcuts, sound, theme
from app.ui.dialogs.common_dialogs import ask_confirm, scanning_suspended, show_error
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

log = logging.getLogger(__name__)

#: Hızlı adet düğmeleri — barkod okutmak birincil yol olsa da elle ekleme kolay olmalı.
QUICK_QUANTITIES = (1, 6, 12, 24, 48)


class StockEntryPage(Page):
    nav_title = "📦  Mal Kabul"
    nav_key = "stok_girisi"
    nav_group = "stok"
    accepts_scans = True
    completes_with_shortcut = True     # F10 = "Girisi Tamamla" (mevcut davranis)

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.receipt_id: int | None = None
        self._last_product_id: int | None = None

        self.header = PageHeader(
            "📦 Stok Girişi", "Gelen ürünleri okutun, sonunda girişi tamamlayın."
        )
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
        )
        duzen.setSpacing(metrics.PAGE_SPACING)

        duzen.addWidget(self._build_top())

        self.banner = ResultBanner()
        duzen.addWidget(self.banner)

        self.table = QTableWidget(0, 4)
        setup_table(self.table, ["Ürün", "Adet", "Alış Fiyatı", "Tutar"])
        stretch_column(self.table, "Ürün")
        duzen.addWidget(self.table, 1)

        self.empty = EmptyState(
            "Henüz ürün eklenmedi",
            "Gelen ürünlerin barkodunu okutun. Koli barkodu okutursanız "
            "kolideki adet doğrudan eklenir.",
        )
        duzen.addWidget(self.empty, 1)

        duzen.addLayout(self._build_bottom())
        self.root.addWidget(govde, 1)

        self.focus_keeper = FocusKeeper(self.barcode)
        self._render()

    # ===================== Kurulum =======================================
    def _build_top(self) -> QWidget:
        kart = Card()

        ust = QHBoxLayout()
        ust.setSpacing(10)
        ust.addWidget(make_label("Tedarikçi (isteğe bağlı)"))
        self.supplier_combo = QComboBox()
        self.supplier_combo.setMinimumWidth(220)
        ust.addWidget(self.supplier_combo)

        ust.addWidget(make_label("İrsaliye No (isteğe bağlı)"))
        self.invoice_edit = QLineEdit()
        self.invoice_edit.setProperty("scannerExempt", True)
        self.invoice_edit.setMaximumWidth(200)
        ust.addWidget(self.invoice_edit)
        ust.addStretch(1)
        kart.body.addLayout(ust)

        kart.body.addWidget(make_label("BARKOD BEKLENİYOR", "cardTitle"))
        self.barcode = BarcodeInput("stock")
        self.barcode.submitted.connect(self._add_by_code)
        kart.body.addWidget(self.barcode)

        hizli = QHBoxLayout()
        hizli.setSpacing(8)
        hizli.addWidget(make_label("Son okutulana ekle:"))
        for adet in QUICK_QUANTITIES:
            dugme = QPushButton(f"+{adet}")
            dugme.clicked.connect(lambda _=False, a=adet: self._add_quick(a))
            hizli.addWidget(dugme)
        hizli.addStretch(1)
        kart.body.addLayout(hizli)
        return kart

    def _build_bottom(self) -> QHBoxLayout:
        alt = QHBoxLayout()
        alt.setSpacing(10)
        self.total_label = make_label("Toplam: 0 TL", "cardValue")
        alt.addWidget(self.total_label)
        alt.addStretch(1)

        self.edit_cost_button = QPushButton("Seçili Satırın Fiyatını Değiştir")
        self.edit_cost_button.clicked.connect(self._edit_cost)
        alt.addWidget(self.edit_cost_button)

        self.discard_button = QPushButton("Girişi İptal Et")
        self.discard_button.clicked.connect(self._discard)
        alt.addWidget(self.discard_button)

        self.commit_button = QPushButton(
            shortcuts.label_with_key("tamamla", "GİRİŞİ TAMAMLA")
        )
        self.commit_button.setObjectName("stockAction")
        self.commit_button.setMinimumHeight(metrics.BIG_BUTTON_HEIGHT)
        self.commit_button.clicked.connect(self.complete)
        alt.addWidget(self.commit_button)
        return alt

    # ===================== Yaşam döngüsü =================================
    def on_activated(self) -> None:
        self.focus_keeper.start()
        self.barcode.setFocus()
        self._load_suppliers()
        self._recover_draft()
        self._render()

    def on_deactivated(self) -> None:
        self.focus_keeper.stop()

    def refresh(self) -> None:
        self._render()

    def _load_suppliers(self) -> None:
        secili = self.supplier_combo.currentData()
        self.supplier_combo.clear()
        self.supplier_combo.addItem("Seçilmedi", None)
        for tedarikci in self.services.suppliers.all():
            self.supplier_combo.addItem(tedarikci["name"], tedarikci["id"])
        if secili is not None:
            index = self.supplier_combo.findData(secili)
            if index >= 0:
                self.supplier_combo.setCurrentIndex(index)

    def _recover_draft(self) -> None:
        """Yarım kalmış giriş KENDİLİĞİNDEN tamamlanmaz; kullanıcı karar verir."""
        if self.receipt_id is not None:
            return
        taslaklar = self.services.purchases.open_drafts()
        if not taslaklar:
            return
        taslak = taslaklar[0]
        if not taslak["satir_sayisi"]:
            self.receipt_id = taslak["id"]
            return

        with scanning_suspended(self.main_window.router):
            devam = ask_confirm(
                self,
                "Tamamlanmamış stok girişi bulundu.",
                f"{taslak['satir_sayisi']} kalem"
                + (f" · {taslak['tedarikci']}" if taslak["tedarikci"] else "")
                + ". Devam etmek ister misiniz?",
                accept_text="Devam Et",
                reject_text="Taslağı Sil",
            )
        if devam:
            self.receipt_id = taslak["id"]
        else:
            self.services.purchases.discard_draft(taslak["id"])

    def _ensure_receipt(self) -> int:
        if self.receipt_id is None:
            self.receipt_id = self.services.purchases.start_draft(
                supplier_id=self.supplier_combo.currentData(),
                invoice_no=self.invoice_edit.text().strip() or None,
            )
        return self.receipt_id

    # ===================== Okutma ========================================
    def handle_scan(self, event) -> None:
        self._add_by_code(event.code)

    def _add_by_code(self, raw: str) -> None:
        eslesme = self.services.barcodes.resolve(raw)
        if eslesme is None:
            sound.error()

            pencere = None

            def engellendi(event):
                if pencere is not None:
                    pencere.notify_blocked(event)

            with scanning_suspended(self.main_window.router, engellendi):
                # Mal kabulde başlangıç stoğu sorulmaz: stok girişin kendisidir.
                pencere = UnknownBarcodeDialog(raw, self.services, self, context="STOK")
                kabul = pencere.exec()
                urun_id = pencere.product_id if kabul else None
            if urun_id is None:
                self.banner.show_error("Ürün tanınmadı.", f"Barkod: {raw}")
                return
            eslesme = self.services.barcodes.resolve(raw)
            if eslesme is not None:
                self._add_line(eslesme.product_id, eslesme.quantity, eslesme.barcode,
                               eslesme.multiplier)
            else:
                self._add_line(urun_id, 1, None, 1)
            return

        # Koli/paket barkodu burada SORULMADAN uygulanır: mal kabulünde
        # "1 koli" zaten 24 adet demektir ve yanlışlık ucuzdur (satır düzeltilir).
        self._add_line(
            eslesme.product_id, eslesme.quantity, eslesme.barcode, eslesme.multiplier
        )

    def _add_quick(self, quantity: int) -> None:
        if self._last_product_id is None:
            self.banner.show_warning("Önce bir ürün okutun.")
            return
        self._add_line(self._last_product_id, quantity, None, 1)

    def _add_line(self, product_id: int, quantity: int, barcode: str | None,
                  multiplier: int) -> None:
        try:
            fis = self._ensure_receipt()
            self.services.purchases.add_line(
                fis, product_id, quantity, barcode_used=barcode, multiplier=multiplier
            )
        except DomainError as hata:
            sound.error()
            self.banner.show_error(hata.message)
            return
        except Exception:
            log.exception("Stok giriş satırı eklenemedi")
            sound.error()
            self.banner.show_error("İşlem tamamlanamadı. Hiçbir bilgi değişmedi.")
            return

        self._last_product_id = product_id
        urun = self.services.products.get(product_id)
        sound.success()
        toplam = self._line_quantity(product_id)
        self.banner.show_stock(
            "EKLENDİ",
            f"{urun['name']}  +{quantity}",
            f"Bu fişte toplam: {toplam} adet",
        )
        self._render()

    def _line_quantity(self, product_id: int) -> int:
        if self.receipt_id is None:
            return 0
        return sum(
            satir["quantity"]
            for satir in self.services.purchases.lines(self.receipt_id)
            if satir["product_id"] == product_id
        )

    # ===================== Satır düzenleme ===============================
    def _selected_line(self):
        if self.receipt_id is None:
            return None
        satirlar = self.services.purchases.lines(self.receipt_id)
        index = self.table.currentRow()
        if index < 0 or index >= len(satirlar):
            return None
        return satirlar[index]

    def _edit_cost(self) -> None:
        satir = self._selected_line()
        if satir is None:
            self.banner.show_warning("Önce listeden bir satır seçin.")
            return

        from PySide6.QtWidgets import QInputDialog

        with scanning_suspended(self.main_window.router):
            metin, tamam = QInputDialog.getText(
                self, "Alış Fiyatı",
                f"{satir['name']} için alış fiyatı (TL):",
                text=kurus_to_tl_text(satir["unit_cost"]),
            )
        if not tamam:
            return
        try:
            self.services.purchases.set_line_cost(satir["id"], tl_to_kurus(metin))
        except DomainError as hata:
            show_error(self, hata.message)
            return
        self._render()

    # ===================== Tamamlama =====================================
    def complete(self) -> None:
        if self.receipt_id is None:
            self.banner.show_error("Stok girişinde hiç ürün yok.", "Önce ürün okutun.")
            return
        satirlar = self.services.purchases.lines(self.receipt_id)
        if not satirlar:
            self.banner.show_error("Stok girişinde hiç ürün yok.", "Önce ürün okutun.")
            return

        degisen = self.services.purchases.changed_cost_lines(self.receipt_id)
        ayrinti = f"{len(satirlar)} kalem · {format_tl(self._total())}"
        if degisen:
            adlar = ", ".join(d["name"] for d in degisen[:3])
            ayrinti += f"\nAlış fiyatı değişenler: {adlar}"

        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, "Stok girişi tamamlansın mı?", ayrinti,
                accept_text="Evet, tamamla",
            )
        if not onay:
            return

        try:
            self.services.purchases.commit(self.receipt_id)
        except DomainError as hata:
            sound.error()
            self.banner.show_error(hata.message)
            return
        except Exception:
            log.exception("Stok girişi tamamlanamadı")
            sound.error()
            self.banner.show_error(
                "İşlem tamamlanamadı. Stok bilgileri değiştirilmedi."
            )
            return

        sound.success()
        self.banner.show_stock("✓ STOK GİRİŞİ TAMAMLANDI", ayrinti.split("\n")[0])
        self.receipt_id = None
        self._last_product_id = None
        self.invoice_edit.clear()
        self._render()

    def _discard(self) -> None:
        if self.receipt_id is None:
            return
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, "Bu stok girişi silinsin mi?",
                "Girilen satırlar silinir. Stok DEĞİŞMEZ.",
                accept_text="Evet, sil", danger=True,
            )
        if not onay:
            return
        try:
            self.services.purchases.discard_draft(self.receipt_id)
        except DomainError as hata:
            show_error(self, hata.message)
            return
        self.receipt_id = None
        self._last_product_id = None
        self._render()

    # ===================== Çizim =========================================
    def _total(self) -> int:
        if self.receipt_id is None:
            return 0
        fis = self.services.purchases.receipt(self.receipt_id)
        return fis["total_cost"] if fis else 0

    def _render(self) -> None:
        satirlar = (
            self.services.purchases.lines(self.receipt_id)
            if self.receipt_id is not None else []
        )
        dolu = bool(satirlar)
        self.table.setVisible(dolu)
        self.empty.setVisible(not dolu)
        self.commit_button.setEnabled(dolu)
        self.discard_button.setEnabled(self.receipt_id is not None)
        self.edit_cost_button.setEnabled(dolu)

        self.table.setRowCount(len(satirlar))
        for index, satir in enumerate(satirlar):
            ad = QTableWidgetItem(satir["name"])
            adet = QTableWidgetItem(str(satir["quantity"]))
            fiyat = QTableWidgetItem(format_tl(satir["unit_cost"]))
            tutar = QTableWidgetItem(format_tl(satir["line_total"]))
            for hucre in (adet, fiyat, tutar):
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            # Değişen alış fiyatı görsel olarak VURGULANIR; ayrıca son inceleme
            # metninde de adı geçer (renk tek başına anlam taşımaz).
            onceki = satir["previous_unit_cost"]
            if onceki is not None and onceki != satir["unit_cost"]:
                fiyat.setText(
                    f"{format_tl(satir['unit_cost'])}  (eski {format_tl(onceki)})"
                )
                fiyat.setForeground(Qt.GlobalColor.darkYellow)
            for sutun, hucre in enumerate((ad, adet, fiyat, tutar)):
                self.table.setItem(index, sutun, hucre)

        self.total_label.setText(f"Toplam: {format_tl(self._total())}")
        self.total_label.setStyleSheet(
            f"color: {theme.STOCK_DARK};" if dolu else ""
        )
