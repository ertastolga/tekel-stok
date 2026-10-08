"""📦 Mal Kabul: faturalı/irsaliyeli gelen malı okutup stoğa alma (D2).

Bir mal kabulü bir FİŞTİR. Operatör okuturken hiçbir şey kalıcı olmaz; fiş
taslakta birikir ve yalnızca "Girişi Tamamla" (F10) ile tek işlemde stoğa
işlenir.

* Başlık düzenlenebilir: tedarikçi (listeden seçilir ya da yeni adı yazılır),
  fatura/irsaliye no, fatura tarihi — hepsi isteğe bağlı.
* Koli barkodu burada SORULMADAN uygulanır: koli okutmak zaten "24 adet geldi"
  demektir. (Satışta ise onay istenir — orada yanlışlık pahalıdır.)
* Alış fiyatı bilinen son alışla ÖN DOLDURULUR; değişmediyse operatör hiçbir
  şey yapmaz. Bilinmiyorsa satır "bilinmiyor" görünür (tahmini değerlenir).
  0 TL girmek "bedelsiz mal" demektir ve ayrıca sorulur.
* Satırlar: Önceki alış / Yeni alış / Değişim % / Satış / Tahmini marj. Marj
  yalnızca bilinen alışla hesaplanır (KDV dahil fiyatlarla, tahmini).
* Alış fiyatı ayarlardaki eşikten fazla değişen ürünler "Fiyat incelemesi"
  bölümünde önerilen satış fiyatıyla listelenir. Satış fiyatı YALNIZCA
  "Fiyatı Güncelle" ile, açık onayla değişir.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import pricing_math as pm
from app.core.errors import DomainError
from app.core.models import BarcodeType
from app.core.money import format_tl, kurus_to_tl_text, tl_to_kurus
from app.services.pricing_service import MAL_KABUL, FiyatDegisikligi
from app.services.security_service import ProtectedAction
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
from app.ui.widgets.touch_input import TouchAmountDialog

log = logging.getLogger(__name__)

#: Hızlı adet düğmeleri — barkod okutmak birincil yol olsa da elle ekleme kolay olmalı.
QUICK_QUANTITIES = (1, 6, 12, 24, 48)
SATIR_SUTUNLARI = ["Ürün", "Adet", "Önceki alış", "Yeni alış", "Değişim", "Satış",
                   "Tahmini marj", "Tutar"]
INCELEME_SUTUNLARI = ["Ürün", "Alış", "Değişim", "Satış", "Önerilen", "Marj"]
TARIH_BICIMI = "yyyy-MM-dd"


def _sag(metin: str) -> QTableWidgetItem:
    hucre = QTableWidgetItem(metin)
    hucre.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return hucre


def _yuzde(bp: int | None) -> str:
    return pm.bp_metni(bp) if bp is not None else "—"


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
        self._satirlar: list = []
        self._secili_satir_id: int | None = None
        #: Fiyat incelemesinin baktığı fiş (taslak ya da az önce tamamlanan).
        self.review_receipt_id: int | None = None
        self._oneriler: list = []

        self.header = PageHeader(
            "📦 Mal Kabul", "Gelen ürünleri okutun, sonunda girişi tamamlayın."
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

        self.table = QTableWidget(0, len(SATIR_SUTUNLARI))
        setup_table(self.table, SATIR_SUTUNLARI)
        stretch_column(self.table, "Ürün")
        self.table.itemSelectionChanged.connect(self._secim_degisti)
        duzen.addWidget(self.table, 1)

        self.empty = EmptyState(
            "Henüz ürün eklenmedi",
            "Gelen ürünlerin barkodunu okutun. Koli barkodu okutursanız "
            "kolideki adet doğrudan eklenir.",
        )
        duzen.addWidget(self.empty, 1)

        duzen.addLayout(self._build_line_actions())
        duzen.addWidget(self._build_review())
        duzen.addLayout(self._build_bottom())
        self.root.addWidget(govde, 1)

        self.focus_keeper = FocusKeeper(self.barcode)
        self._bugune_don()
        self._render()

    # ===================== Kurulum =======================================
    def _build_top(self) -> QWidget:
        kart = Card()

        ust = QHBoxLayout()
        ust.setSpacing(10)
        ust.addWidget(make_label("Tedarikçi"))
        self.supplier_combo = QComboBox()
        self.supplier_combo.setEditable(True)
        self.supplier_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.supplier_combo.setMinimumWidth(200)
        self.supplier_combo.lineEdit().setProperty("scannerExempt", True)
        self.supplier_combo.lineEdit().setPlaceholderText("Seçin ya da yazın")
        self.supplier_combo.lineEdit().editingFinished.connect(self._baslik_yaz)
        self.supplier_combo.activated.connect(lambda _i: self._baslik_yaz())
        ust.addWidget(self.supplier_combo)

        ust.addWidget(make_label("Fatura / İrsaliye No"))
        self.invoice_edit = QLineEdit()
        self.invoice_edit.setProperty("scannerExempt", True)
        self.invoice_edit.setMaximumWidth(180)
        self.invoice_edit.editingFinished.connect(self._baslik_yaz)
        ust.addWidget(self.invoice_edit)

        ust.addWidget(make_label("Tarih"))
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        self.date_edit.setProperty("scannerExempt", True)
        self.date_edit.dateChanged.connect(lambda _d: self._baslik_yaz())
        ust.addWidget(self.date_edit)
        ust.addStretch(1)
        kart.body.addLayout(ust)

        self.barcode = BarcodeInput("stock")
        self.barcode.setPlaceholderText("Gelen ürünün barkodunu okutun…")
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

    def _dugme(self, metin: str, yuva) -> QPushButton:
        dugme = QPushButton(metin)
        dugme.setProperty("dokunma", "evet")
        dugme.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
        dugme.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        dugme.clicked.connect(yuva)
        return dugme

    def _build_line_actions(self) -> QHBoxLayout:
        satir = QHBoxLayout()
        satir.setSpacing(8)
        self.line_label = make_label("Satır seçin:", "cardHint")
        satir.addWidget(self.line_label)
        self.minus_button = self._dugme("−", lambda: self.change_quantity(-1))
        self.plus_button = self._dugme("+", lambda: self.change_quantity(1))
        self.quantity_button = self._dugme("Adet…", self._edit_quantity)
        self.case_button = self._dugme("+1 koli", self.add_case)
        self.edit_cost_button = self._dugme("Alış fiyatı…", self._edit_cost)
        self.remove_button = self._dugme("Satırı sil", self.remove_selected)
        for dugme in (self.minus_button, self.plus_button, self.quantity_button,
                      self.case_button, self.edit_cost_button, self.remove_button):
            satir.addWidget(dugme)
        satir.addStretch(1)
        return satir

    def _build_review(self) -> QWidget:
        self.review_card = Card()
        ust = QHBoxLayout()
        self.review_title = make_label("Fiyat incelemesi", "cardTitle")
        ust.addWidget(self.review_title)
        ust.addStretch(1)
        self.update_price_button = QPushButton("Seçilenlerin Fiyatını Güncelle")
        self.update_price_button.setObjectName("primary")
        self.update_price_button.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
        self.update_price_button.clicked.connect(self._fiyat_guncelle_secilen)
        ust.addWidget(self.update_price_button)
        self.review_card.body.addLayout(ust)
        self.review_card.body.addWidget(make_label(
            "Alış fiyatı belirgin değişen ürünler. Önerilen fiyat eski satış/alış "
            "oranını korur. Satış fiyatı siz onaylamadan DEĞİŞMEZ.", "cardHint", wrap=True))
        self.review_table = QTableWidget(0, len(INCELEME_SUTUNLARI))
        setup_table(self.review_table, INCELEME_SUTUNLARI)
        self.review_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.review_table.setMaximumHeight(150)
        self.review_table.itemSelectionChanged.connect(
            lambda: self.update_price_button.setEnabled(bool(self._inceleme_secili())))
        self.review_card.body.addWidget(self.review_table)
        return self.review_card

    def _build_bottom(self) -> QHBoxLayout:
        alt = QHBoxLayout()
        alt.setSpacing(10)
        self.total_label = make_label("Toplam: 0 TL", "cardValue")
        alt.addWidget(self.total_label)
        alt.addStretch(1)

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
        metin = self.supplier_combo.currentText()
        self.supplier_combo.blockSignals(True)
        self.supplier_combo.clear()
        self.supplier_combo.addItem("", None)
        for tedarikci in self.services.suppliers.all():
            self.supplier_combo.addItem(tedarikci["name"], tedarikci["id"])
        self.supplier_combo.setCurrentText(metin)
        self.supplier_combo.blockSignals(False)

    def _recover_draft(self) -> None:
        """Yarım kalmış giriş KENDİLİĞİNDEN tamamlanmaz; kullanıcı karar verir."""
        if self.receipt_id is not None:
            return
        taslaklar = self.services.purchases.open_drafts()
        if not taslaklar:
            return
        taslak = taslaklar[0]
        if not taslak["satir_sayisi"]:
            self._taslagi_al(taslak["id"])
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
            self._taslagi_al(taslak["id"])
        else:
            self.services.purchases.discard_draft(taslak["id"])

    def _taslagi_al(self, receipt_id: int) -> None:
        """Kurtarılan taslağın başlığını ekrana yükler."""
        self.receipt_id = receipt_id
        self.review_receipt_id = receipt_id
        fis = self.services.purchases.receipt(receipt_id)
        if fis is None:
            return
        for gerec in (self.supplier_combo, self.invoice_edit, self.date_edit):
            gerec.blockSignals(True)
        tedarikci = (self.services.suppliers.get(fis["supplier_id"])
                     if fis["supplier_id"] else None)
        self.supplier_combo.setCurrentText(tedarikci["name"] if tedarikci else "")
        self.invoice_edit.setText(fis["invoice_no"] or "")
        self.date_edit.setDate(QDate.fromString(fis["receipt_date"], TARIH_BICIMI))
        for gerec in (self.supplier_combo, self.invoice_edit, self.date_edit):
            gerec.blockSignals(False)

    # ===================== Başlık ========================================
    def supplier_id(self) -> int | None:
        """Yazılan/seçilen tedarikçi; yeni bir ad yazıldıysa tedarikçi oluşturulur."""
        metin = self.supplier_combo.currentText().strip()
        if not metin:
            return None
        index = self.supplier_combo.findText(metin, Qt.MatchFlag.MatchFixedString)
        if index >= 0 and self.supplier_combo.itemData(index) is not None:
            return self.supplier_combo.itemData(index)
        kimlik = self.services.suppliers.ensure(metin)
        self._load_suppliers()
        return kimlik

    def receipt_date(self) -> str:
        return self.date_edit.date().toString(TARIH_BICIMI)

    def _bugune_don(self) -> None:
        """Yeni fişin tarihi bugünün iş günüdür (fatura tarihine göre değiştirilir)."""
        self.date_edit.blockSignals(True)
        self.date_edit.setDate(QDate.fromString(
            self.services.settings.calendar().today(), TARIH_BICIMI))
        self.date_edit.blockSignals(False)

    def _baslik_yaz(self) -> None:
        if self.receipt_id is None:
            return
        try:
            self.services.purchases.set_header(
                self.receipt_id, self.supplier_id(),
                self.invoice_edit.text(), self.receipt_date(),
            )
        except DomainError as hata:
            show_error(self, hata.message)

    def _ensure_receipt(self) -> int:
        if self.receipt_id is None:
            self.receipt_id = self.services.purchases.start_draft(
                supplier_id=self.supplier_id(),
                invoice_no=self.invoice_edit.text().strip() or None,
                receipt_date=self.receipt_date(),
            )
            self.review_receipt_id = self.receipt_id
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
            # Bilinen son alış ÖN DOLDURULUR ve açıkça geçirilir; bilinmiyorsa
            # satır "maliyet bilinmiyor" (tahmini) olur — 0 yazılmaz (D-06).
            self.services.purchases.add_line(
                fis, product_id, quantity,
                unit_cost=self.services.purchases.last_purchase_cost(product_id),
                barcode_used=barcode, multiplier=multiplier,
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
        self._satiri_sec_urun(product_id)

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
        index = self.table.currentRow()
        if index < 0 or index >= len(self._satirlar):
            return None
        return self._satirlar[index]

    def select_line(self, index: int) -> None:
        self.table.selectRow(index)

    def _satiri_sec_urun(self, product_id: int) -> None:
        for i, satir in enumerate(self._satirlar):
            if satir["product_id"] == product_id:
                self.table.selectRow(i)

    def _koli_carpani(self, product_id: int) -> int:
        carpanlar = [
            b["quantity_multiplier"] for b in self.services.barcodes.barcodes_of(product_id)
            if b["barcode_type"] in (BarcodeType.CASE, BarcodeType.PACK)
            and b["quantity_multiplier"] > 1
        ]
        return max(carpanlar) if carpanlar else 0

    def _secim_degisti(self) -> None:
        satir = self._selected_line()
        self._secili_satir_id = satir["id"] if satir is not None else None
        var = satir is not None
        for dugme in (self.minus_button, self.plus_button, self.quantity_button,
                      self.edit_cost_button, self.remove_button):
            dugme.setEnabled(var)
        carpan = self._koli_carpani(satir["product_id"]) if var else 0
        self.case_button.setVisible(carpan > 1)
        self.case_button.setText(f"+1 koli (×{carpan})")
        self.line_label.setText(satir["name"] if var else "Satır seçin:")

    def set_selected_quantity(self, adet: int) -> None:
        satir = self._selected_line()
        if satir is None:
            return
        if adet <= 0:
            self.remove_selected()
            return
        try:
            self.services.purchases.set_line_quantity(satir["id"], adet)
        except DomainError as hata:
            show_error(self, hata.message)
            return
        self._render()

    def change_quantity(self, fark: int) -> None:
        satir = self._selected_line()
        if satir is not None:
            self.set_selected_quantity(satir["quantity"] + fark)

    def add_case(self) -> None:
        satir = self._selected_line()
        if satir is None:
            return
        carpan = self._koli_carpani(satir["product_id"])
        if carpan > 1:
            self.set_selected_quantity(satir["quantity"] + carpan)

    def remove_selected(self) -> None:
        satir = self._selected_line()
        if satir is None:
            return
        try:
            self.services.purchases.set_line_quantity(satir["id"], 0)
        except DomainError as hata:
            show_error(self, hata.message)
            return
        self._secili_satir_id = None
        self._render()

    def set_selected_cost(self, kurus: int) -> bool:
        """Seçili satırın alış fiyatı; 0 = bedelsiz (ayrıca sorulur)."""
        satir = self._selected_line()
        if satir is None:
            return False
        if kurus == 0:
            with scanning_suspended(self.main_window.router):
                bedelsiz = ask_confirm(
                    self, f"{satir['name']} bedelsiz mi geldi?",
                    "0 TL alış fiyatı 'ücretsiz mal' demektir: stok değeri düşer, "
                    "ürünün son alış fiyatı değişmez. Fiyatı bilmiyorsanız Vazgeç'e "
                    "dokunun; satır 'bilinmiyor' kalır.",
                    accept_text="Evet, bedelsiz",
                )
            if not bedelsiz:
                return False
        try:
            self.services.purchases.set_line_cost(satir["id"], kurus)
        except DomainError as hata:
            show_error(self, hata.message)
            return False
        self._render()
        return True

    def _sor_tutar(self, baslik: str, ilk: str, ondalik: bool) -> str | None:
        with scanning_suspended(self.main_window.router):
            pencere = TouchAmountDialog(baslik, ilk, allow_decimal=ondalik, parent=self)
            return pencere.value() if pencere.exec() else None

    def _edit_quantity(self) -> None:
        satir = self._selected_line()
        if satir is None:
            self.banner.show_warning("Önce listeden bir satır seçin.")
            return
        metin = self._sor_tutar(f"{satir['name']} — adet", str(satir["quantity"]), False)
        if metin is not None and metin.strip().isdigit():
            self.set_selected_quantity(int(metin.strip()))

    def _edit_cost(self) -> None:
        satir = self._selected_line()
        if satir is None:
            self.banner.show_warning("Önce listeden bir satır seçin.")
            return
        ilk = "" if satir["cost_is_estimated"] else kurus_to_tl_text(satir["unit_cost"])
        metin = self._sor_tutar(f"{satir['name']} — alış fiyatı (1 adet, TL)", ilk, True)
        if metin is None or not metin.strip():
            return
        try:
            kurus = tl_to_kurus(metin)
        except DomainError as hata:
            show_error(self, hata.message)
            return
        self.set_selected_cost(kurus)

    # ===================== Fiyat incelemesi ==============================
    def review_rows(self) -> list:
        return self._oneriler

    def _inceleme_yenile(self) -> None:
        fis = self.review_receipt_id
        esik = self.services.settings.cost_change_alert_percent() * 100
        adim = self.services.settings.price_rounding()
        self._oneriler = (
            self.services.pricing.mal_kabul_onerileri(fis, esik, adim) if fis else []
        )
        self.review_card.setVisible(bool(self._oneriler))
        self.review_title.setText(
            f"Fiyat incelemesi — {len(self._oneriler)} üründe alış fiyatı "
            f"%{self.services.settings.cost_change_alert_percent()}'ten fazla değişti")
        self.review_table.setRowCount(len(self._oneriler))
        for i, o in enumerate(self._oneriler):
            hucreler = (
                QTableWidgetItem(o.ad),
                _sag(f"{format_tl(o.onceki_alis)} → {format_tl(o.yeni_alis)}"),
                _sag(_yuzde(o.degisim_bp)),
                _sag(format_tl(o.satis) if o.satis is not None else "—"),
                _sag(format_tl(o.onerilen) if o.onerilen is not None else "—"),
                _sag(f"{_yuzde(o.simdiki_marj_bp)} → {_yuzde(o.onerilen_marj_bp)}"),
            )
            for sutun, hucre in enumerate(hucreler):
                self.review_table.setItem(i, sutun, hucre)
        self.update_price_button.setEnabled(bool(self._inceleme_secili()))

    def _inceleme_secili(self) -> list:
        satirlar = sorted({i.row() for i in self.review_table.selectionModel().selectedRows()})
        return [self._oneriler[s] for s in satirlar if s < len(self._oneriler)]

    def _fiyat_guncelle_secilen(self) -> None:
        self.apply_price_updates([o.product_id for o in self._inceleme_secili()])

    def apply_price_updates(self, product_ids: list[int]) -> int:
        """Seçilen ürünlerin satış fiyatını ÖNERİLEN fiyata çeker (açık onayla).

        Tek ürün tek fiyat düzenlemesidir (PIN istemez); birden çok ürün toplu
        fiyat değişikliğidir (PIN varsa ister). Fiyat geçmişine "Mal kabul"
        grubu olarak yazılır ve Fiyat Yönetimi'nden geri alınabilir.
        """
        secilen = [o for o in self._oneriler
                   if o.product_id in set(product_ids) and o.onerilen and o.onerilen != o.satis]
        if not secilen:
            return 0
        if len(secilen) > 1 and not self.guard_require(ProtectedAction.TOPLU_FIYAT):
            return 0
        ayrinti = "\n".join(
            f"{o.ad}: {format_tl(o.satis) if o.satis else '—'} → {format_tl(o.onerilen)}"
            for o in secilen[:6])
        if len(secilen) > 6:
            ayrinti += f"\n… ve {len(secilen) - 6} ürün daha"
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(self, f"{len(secilen)} ürünün satış fiyatı güncellensin mi?",
                               ayrinti, accept_text="Fiyatı Güncelle")
        if not onay:
            return 0
        try:
            self.services.pricing.uygula(
                [FiyatDegisikligi(o.product_id, o.satis, o.onerilen) for o in secilen],
                tur=MAL_KABUL, aciklama=f"Mal kabul fişi {self.review_receipt_id}",
            )
        except DomainError as hata:
            show_error(self, hata.message)
            self._render()
            return 0
        self.banner.show_success(f"{len(secilen)} ürünün satış fiyatı güncellendi.")
        self._render()
        self.data_changed()
        return len(secilen)

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
        bilinmeyen = sum(1 for s in satirlar if s["cost_is_estimated"])
        ayrinti = f"{len(satirlar)} kalem · {format_tl(self._total())}"
        if degisen:
            adlar = ", ".join(d["name"] for d in degisen[:3])
            ayrinti += f"\nAlış fiyatı değişenler: {adlar}"
        if bilinmeyen:
            ayrinti += (f"\n{bilinmeyen} kalemin alış fiyatı bilinmiyor; stok değeri "
                        "tahmini hesaplanır.")

        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, "Stok girişi tamamlansın mı?", ayrinti,
                accept_text="Evet, tamamla",
            )
        if not onay:
            return

        self._baslik_yaz()
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
        self.review_receipt_id = self.receipt_id
        self.receipt_id = None
        self._last_product_id = None
        self.invoice_edit.clear()
        self._bugune_don()
        self._render()
        ek = (f"{len(self._oneriler)} üründe alış fiyatı değişti: aşağıdaki fiyat "
              "incelemesine bakın." if self._oneriler else "")
        self.banner.show_stock("✓ STOK GİRİŞİ TAMAMLANDI", ayrinti.split("\n")[0], ek)

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
        self.review_receipt_id = None
        self._last_product_id = None
        self._bugune_don()
        self._render()

    # ===================== Çizim =========================================
    def _total(self) -> int:
        if self.receipt_id is None:
            return 0
        fis = self.services.purchases.receipt(self.receipt_id)
        return fis["total_cost"] if fis else 0

    def _render(self) -> None:
        secili = self._secili_satir_id
        self._satirlar = (
            self.services.purchases.lines(self.receipt_id)
            if self.receipt_id is not None else []
        )
        satirlar = self._satirlar
        dolu = bool(satirlar)
        self.table.setVisible(dolu)
        self.empty.setVisible(not dolu)
        self.commit_button.setEnabled(dolu)
        self.discard_button.setEnabled(self.receipt_id is not None)

        self.table.blockSignals(True)
        self.table.clearSelection()
        self.table.setRowCount(len(satirlar))
        for index, satir in enumerate(satirlar):
            tahmini = bool(satir["cost_is_estimated"])
            yeni = None if tahmini else satir["unit_cost"]
            onceki = satir["previous_unit_cost"] if satir["previous_unit_cost"] else None
            if tahmini:
                yeni_metin = "bilinmiyor"
            elif yeni == 0:
                yeni_metin = "bedelsiz"
            else:
                yeni_metin = format_tl(yeni)
            degisim = pm.degisim_bp(onceki, yeni) if yeni else None
            hucreler = (
                QTableWidgetItem(satir["name"]),
                _sag(str(satir["quantity"])),
                _sag(format_tl(onceki) if onceki else "—"),
                _sag(yeni_metin),
                _sag(_yuzde(degisim) if degisim else "—"),
                _sag(format_tl(satir["sale_price"]) if satir["sale_price"] else "—"),
                _sag(_yuzde(pm.marj_bp(satir["sale_price"], yeni)) if yeni else "—"),
                _sag("—" if tahmini else format_tl(satir["line_total"])),
            )
            # Değişen alış fiyatı görsel olarak VURGULANIR; son onay metninde de
            # adı geçer (renk tek başına anlam taşımaz).
            if degisim:
                hucreler[3].setForeground(Qt.GlobalColor.darkYellow)
                hucreler[4].setForeground(Qt.GlobalColor.darkYellow)
            for sutun, hucre in enumerate(hucreler):
                self.table.setItem(index, sutun, hucre)
        self.table.blockSignals(False)
        for index, satir in enumerate(satirlar):
            if satir["id"] == secili:
                self.table.selectRow(index)
        self._secim_degisti()

        bilinmeyen = sum(1 for s in satirlar if s["cost_is_estimated"])
        self.total_label.setText(
            f"Toplam: {format_tl(self._total())}"
            + (f"  (+{bilinmeyen} kalem fiyatı bilinmiyor)" if bilinmeyen else "")
        )
        self.total_label.setStyleSheet(
            f"color: {theme.STOCK_DARK};" if dolu else ""
        )
        self._inceleme_yenile()
