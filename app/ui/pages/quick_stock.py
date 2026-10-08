"""📥 Hızlı Stok Girişi (STOK, D1): okut → adet → Kaydet → sonraki ürün.

Gelen malı fatura/tedarikçi olmadan, dokunarak hızlıca stoğa almak için:
  * Barkod okutulur; ürün büyük yazılır. Koli barkodu okutulduysa birim
    kendiliğinden "Koli × 24" seçilir.
  * Adet büyük − / + düğmeleri ya da ekrandaki tuş takımıyla girilir; birim
    Adet / Paket / Koli arasında değiştirilebilir (ürünün paket/koli barkodu
    varsa).
  * Alış fiyatı İSTEĞE BAĞLIDIR: bilinen son alış ön doldurulur ("önceki
    alıştan"); "Bilmiyorum" ile boşaltılırsa maliyet tahmini kuralla değerlenir
    ve son alış fiyatı DEĞİŞMEZ (plan §5.8).
  * "Kaydet" tek satırlık, tedarikçisiz bir fişi TEK işlemde stoğa işler.
  * Bugünün girişleri listelenir; bir giriş, ürün o arada satılmadıysa /
    sayılmadıysa (kanıtlanabilir) geri alınabilir (PIN varsa ister).
  * Kaydedilmemiş bir ürün varken BAŞKA bir ürün okutulursa sessizce
    değiştirilmez: önce Kaydet ya da Vazgeç istenir. Aynı ürün yeniden
    okutulursa adet bir artar.

Yerleşim dokunmatik kasa ekranına (1000×600) sığar: sayfa başlığı yoktur
(menüde adı yazar), bugünkü girişler ayrı bir görünümde açılır.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.clock import utc_to_local
from app.core.errors import DomainError
from app.core.models import BarcodeType
from app.core.money import format_tl, kurus_to_tl_text, tl_to_kurus
from app.core.tr import fmt_time
from app.services.security_service import ProtectedAction
from app.ui import metrics, sound, theme
from app.ui.dialogs.common_dialogs import ask_confirm, scanning_suspended, show_error
from app.ui.dialogs.unknown_barcode import UnknownBarcodeDialog
from app.ui.pages.base import Page
from app.ui.widgets.barcode_input import BarcodeInput, FocusKeeper
from app.ui.widgets.common import Card, ResultBanner, make_label
from app.ui.widgets.touch_input import TouchDisplay, TouchNumpad

log = logging.getLogger(__name__)

KIMLIK_ROLU = int(Qt.ItemDataRole.UserRole)
#: Tek girişte en çok birim (yanlış yazımı yakalar).
EN_COK_ADET = 9999
ADET = "ADET"
MALIYET = "MALIYET"
#: Adet gösteriminin yazı boyutu (pt): karşıdan okunur.
ADET_PT = 26.0


class DokunmaGosterimi(TouchDisplay):
    """Dokununca tuş takımının hedefi olan gösterim."""

    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)

    def set_active(self, active: bool) -> None:
        self.setStyleSheet(
            f"#touchDisplay {{ border: 3px solid {theme.STOCK}; }}" if active else ""
        )


class QuickStockPage(Page):
    nav_title = "📥  Hızlı Stok Girişi"
    nav_key = "hizli_stok"
    nav_group = "stok"
    accepts_scans = True

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.product_id: int | None = None
        self.multiplier = 1
        self.barcode_used: str | None = None
        self._unit_buttons: dict[int, QPushButton] = {}
        self._hedef = ADET

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(metrics.PAGE_MARGIN_H, 8, metrics.PAGE_MARGIN_H, 8)
        duzen.setSpacing(8)

        ust = QHBoxLayout()
        ust.setSpacing(8)
        self.barcode = BarcodeInput("stock")
        self.barcode.set_compact(True)
        self.barcode.setPlaceholderText("Gelen ürünün barkodunu okutun…")
        self.barcode.submitted.connect(self.scan_code)
        ust.addWidget(self.barcode, 1)
        self.entries_button = self._touch_button("Bugünkü girişler", genis=True)
        self.entries_button.setCheckable(True)
        self.entries_button.toggled.connect(self.show_entries)
        ust.addWidget(self.entries_button)
        duzen.addLayout(ust)
        self.banner = ResultBanner()
        duzen.addWidget(self.banner)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_entry())
        self.stack.addWidget(self._build_entries())
        duzen.addWidget(self.stack, 1)
        self.root.addWidget(govde, 1)

        self.focus_keeper = FocusKeeper(self.barcode)
        self._temizle()

    # ===================== Kurulum =======================================
    def _build_entry(self) -> QWidget:
        kart = Card()
        satir = QHBoxLayout()
        satir.setSpacing(metrics.PAGE_SPACING)
        sol = QVBoxLayout()
        sol.setSpacing(6)
        self.name_label = make_label("", "sectionTitle", wrap=True)
        sol.addWidget(self.name_label)
        self.stock_label = make_label("", "cardHint")
        sol.addWidget(self.stock_label)

        self.unit_row = QHBoxLayout()
        self.unit_row.setSpacing(6)
        self.unit_group = QButtonGroup(self)
        self.unit_group.setExclusive(True)
        sol.addLayout(self.unit_row)

        adet_satiri = QHBoxLayout()
        self.minus_button = self._touch_button("−")
        self.minus_button.clicked.connect(lambda: self._adet_ekle(-1))
        adet_satiri.addWidget(self.minus_button)
        self.qty_display = DokunmaGosterimi("0", max_length=4)
        self.qty_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qty_display.setFont(theme.base_font(ADET_PT, bold=True))
        self.qty_display.clicked.connect(lambda: self._hedefle(ADET))
        self.qty_display.changed.connect(lambda _m: self._ozet())
        adet_satiri.addWidget(self.qty_display, 1)
        self.plus_button = self._touch_button("+")
        self.plus_button.clicked.connect(lambda: self._adet_ekle(1))
        adet_satiri.addWidget(self.plus_button)
        self.total_label = make_label("", "cardTitle")
        self.total_label.setMinimumWidth(90)
        adet_satiri.addWidget(self.total_label)
        sol.addLayout(adet_satiri)

        maliyet_satiri = QHBoxLayout()
        maliyet_satiri.addWidget(make_label("Alış (1 adet):", "cardHint"))
        self.cost_display = DokunmaGosterimi("bilinmiyor", max_length=12)
        self.cost_display.clicked.connect(lambda: self._hedefle(MALIYET))
        self.cost_display.changed.connect(lambda _m: self._ozet())
        maliyet_satiri.addWidget(self.cost_display, 1)
        self.unknown_cost_button = self._touch_button("Bilmiyorum", genis=True)
        self.unknown_cost_button.clicked.connect(self.clear_cost)
        maliyet_satiri.addWidget(self.unknown_cost_button)
        sol.addLayout(maliyet_satiri)
        self.cost_hint = make_label("", "cardHint", wrap=True)
        sol.addWidget(self.cost_hint)
        sol.addStretch(1)
        satir.addLayout(sol, 1)

        sag = QVBoxLayout()
        sag.setSpacing(8)
        self.numpad = TouchNumpad(allow_decimal=True, allow_double_zero=True)
        self.numpad.key_pressed.connect(lambda m: self._aktif().insert(m))
        self.numpad.backspace_pressed.connect(lambda: self._aktif().backspace())
        self.numpad.clear_pressed.connect(lambda: self._aktif().clear_value())
        sag.addWidget(self.numpad)
        dugmeler = QHBoxLayout()
        self.cancel_button = self._touch_button("Vazgeç", genis=True)
        self.cancel_button.clicked.connect(self.cancel)
        dugmeler.addWidget(self.cancel_button)
        self.save_button = self._touch_button("✓  Kaydet", genis=True)
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        dugmeler.addWidget(self.save_button, 1)
        sag.addLayout(dugmeler)
        sag.addStretch(1)
        satir.addLayout(sag)
        kart.body.addLayout(satir, 1)
        return kart

    def _build_entries(self) -> QWidget:
        kart = Card()
        kart.body.addWidget(make_label("Bugünkü hızlı girişler", "cardTitle"))
        self.entries_list = QListWidget()
        self.entries_list.currentRowChanged.connect(lambda _r: self._secim())
        kart.body.addWidget(self.entries_list, 1)
        dugmeler = QHBoxLayout()
        geri = self._touch_button("◀  Girişe dön", genis=True)
        geri.clicked.connect(lambda: self.entries_button.setChecked(False))
        dugmeler.addWidget(geri)
        dugmeler.addStretch(1)
        self.undo_button = self._touch_button("Seçili girişi geri al", genis=True)
        self.undo_button.clicked.connect(self.undo_selected)
        dugmeler.addWidget(self.undo_button)
        kart.body.addLayout(dugmeler)
        return kart

    def show_entries(self, acik: bool = True) -> None:
        """Bugünkü girişler görünümü ↔ giriş formu."""
        if self.entries_button.isChecked() != acik:
            self.entries_button.setChecked(acik)
            return
        self.stack.setCurrentIndex(1 if acik else 0)
        if acik:
            self.refresh()

    @staticmethod
    def _touch_button(metin: str, genis: bool = False) -> QPushButton:
        dugme = QPushButton(metin)
        dugme.setProperty("dokunma", "evet")
        dugme.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        dugme.setAutoDefault(False)
        dugme.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
        dugme.setMinimumWidth(metrics.TOUCH_TARGET_MIN * (2 if genis else 1))
        return dugme

    # ===================== Yaşam döngüsü =================================
    def on_activated(self) -> None:
        self.refresh()
        self.focus_keeper.start()
        self.barcode.setFocus()

    def on_deactivated(self) -> None:
        self.focus_keeper.stop()

    def handle_back(self) -> bool:
        if self.stack.currentIndex() == 1:
            self.show_entries(False)
            return True
        if self.product_id is not None:
            self.cancel()
            return True
        return False

    def refresh(self) -> None:
        try:
            girisler = self.services.purchases.quick_entries()
        except Exception:
            log.exception("Hızlı girişler okunamadı")
            return
        self.entries_button.setText(f"Bugünkü girişler ({len(girisler)})")
        self.entries_list.clear()
        for g in girisler:
            zaman = fmt_time(utc_to_local(g["committed_at_utc"]))
            maliyet = ("maliyet bilinmiyor" if g["cost_is_estimated"]
                       else format_tl(g["unit_cost"]))
            metin = f"{zaman} · {g['name']}  +{g['quantity']}  ({maliyet})"
            if g["geri_alindi"]:
                metin += " — geri alındı"
            oge = QListWidgetItem(metin)
            oge.setData(KIMLIK_ROLU, None if g["geri_alindi"] else g["id"])
            self.entries_list.addItem(oge)
        self._secim()

    # ===================== Okutma ========================================
    def handle_scan(self, event) -> None:
        self.scan_code(event.code)

    def scan_code(self, raw: str) -> None:
        eslesme = self.services.barcodes.resolve(raw)
        if eslesme is None:
            eslesme = self._bilinmeyen(raw)
            if eslesme is None:
                return
        if not eslesme.is_active:
            sound.error()
            self.banner.show_error("Bu ürün kullanımdan kaldırılmış.", eslesme.product_name)
            return
        if self.product_id is not None:
            if eslesme.product_id == self.product_id:
                # Aynı ürün yeniden okutuldu: okutulan birimde bir artır.
                if eslesme.multiplier != self.multiplier:
                    self.set_unit(eslesme.multiplier)
                self._adet_ekle(1)
                sound.success()
                return
            sound.error()
            self.banner.show_warning(
                "Önce bu ürünü kaydedin ya da vazgeçin.",
                f"Bekleyen: {self.name_label.text()}",
            )
            return
        self.show_entries(False)
        self.load_product(eslesme.product_id, eslesme.multiplier, eslesme.barcode)

    def _bilinmeyen(self, raw: str):
        sound.error()
        pencere = None

        def engellendi(event):
            if pencere is not None:
                pencere.notify_blocked(event)

        with scanning_suspended(self.main_window.router, engellendi):
            pencere = UnknownBarcodeDialog(raw, self.services, self, context="STOK")
            kabul = pencere.exec()
            urun_id = pencere.product_id if kabul else None
        if urun_id is None:
            self.banner.show_error("Ürün tanınmadı.", f"Barkod: {raw}")
            return None
        eslesme = self.services.barcodes.resolve(raw)
        if eslesme is None:                       # barkodsuz bağlandıysa
            self.load_product(urun_id, 1, None)
        return eslesme

    def load_product(self, product_id: int, multiplier: int = 1,
                     barcode: str | None = None) -> None:
        urun = self.services.products.get(product_id)
        if urun is None:
            return
        self.product_id = product_id
        self.barcode_used = barcode
        self.name_label.setText(urun["name"])
        self.stock_label.setText(f"Şu an stokta: {urun['current_stock']} adet")
        self._birimleri_kur(product_id)
        self.set_unit(multiplier if multiplier in self._unit_buttons else 1)
        self.qty_display.set_value("1")
        bilinen = self.services.purchases.last_purchase_cost(product_id)
        self.cost_display.set_value(kurus_to_tl_text(bilinen) if bilinen else "")
        self.cost_hint.setText("önceki alıştan" if bilinen else
                               "Bilinmiyorsa boş bırakın; stok değeri tahmini hesaplanır.")
        self._hedefle(ADET)
        self._etkin(True)
        sound.success()
        self.banner.show_idle("Adedi girin ve Kaydet'e dokunun.", urun["name"])

    def _birimleri_kur(self, product_id: int) -> None:
        for dugme in self._unit_buttons.values():
            self.unit_group.removeButton(dugme)
            dugme.deleteLater()
        self._unit_buttons = {}
        secenekler = {1: "Adet"}
        for b in self.services.barcodes.barcodes_of(product_id):
            if b["barcode_type"] in (BarcodeType.PACK, BarcodeType.CASE) \
                    and b["quantity_multiplier"] > 1:
                ad = "Koli" if b["barcode_type"] == BarcodeType.CASE else "Paket"
                secenekler.setdefault(b["quantity_multiplier"],
                                      f"{ad} × {b['quantity_multiplier']}")
        for carpan, ad in sorted(secenekler.items()):
            dugme = self._touch_button(ad, genis=carpan > 1)
            dugme.setCheckable(True)
            dugme.clicked.connect(lambda _=False, c=carpan: self.set_unit(c))
            self.unit_group.addButton(dugme)
            self.unit_row.addWidget(dugme)
            self._unit_buttons[carpan] = dugme

    def set_unit(self, multiplier: int) -> None:
        if multiplier not in self._unit_buttons:
            return
        self.multiplier = multiplier
        self._unit_buttons[multiplier].setChecked(True)
        self._ozet()

    # ===================== Adet / maliyet ================================
    def _aktif(self) -> TouchDisplay:
        return self.cost_display if self._hedef == MALIYET else self.qty_display

    def _hedefle(self, hedef: str) -> None:
        self._hedef = hedef
        self.qty_display.set_active(hedef == ADET)
        self.cost_display.set_active(hedef == MALIYET)
        self.numpad.keys[","].setEnabled(hedef == MALIYET)

    def _adet(self) -> int:
        metin = self.qty_display.value().strip()
        return int(metin) if metin.isdigit() else 0

    def _adet_ekle(self, fark: int) -> None:
        if self.product_id is None:
            return
        yeni = min(EN_COK_ADET, max(1, self._adet() + fark))
        self.qty_display.set_value(str(yeni))

    def clear_cost(self) -> None:
        self.cost_display.clear_value()
        self.cost_hint.setText("Maliyet bilinmiyor: stok değeri tahmini hesaplanır, "
                               "son alış fiyatı değişmez.")

    def unit_cost(self) -> int | None:
        """Girilen alış fiyatı (kuruş) ya da ``None`` (bilinmiyor)."""
        metin = self.cost_display.value().strip()
        return tl_to_kurus(metin) if metin else None

    def units(self) -> int:
        return self._adet() * self.multiplier

    def _ozet(self) -> None:
        if self.product_id is None:
            self.total_label.setText("")
            return
        adet = self._adet()
        metin = f"= {adet * self.multiplier} adet" if self.multiplier > 1 else f"{adet} adet"
        self.total_label.setText(metin)
        self.save_button.setEnabled(adet > 0)

    # ===================== Kaydet / vazgeç ===============================
    def save(self) -> bool:
        if self.product_id is None:
            return False
        adet = self.units()
        if adet <= 0 or self._adet() > EN_COK_ADET:
            sound.error()
            self.banner.show_error("Geçerli bir adet girin.")
            return False
        try:
            maliyet = self.unit_cost()
            self.services.purchases.quick_receive(
                self.product_id, adet, maliyet, self.barcode_used, self.multiplier
            )
        except DomainError as hata:
            sound.error()
            self.banner.show_error(hata.message)
            return False
        except Exception:
            log.exception("Hızlı stok girişi kaydedilemedi")
            sound.error()
            self.banner.show_error("Kaydedilemedi. Stok değişmedi.")
            return False
        urun = self.services.products.get(self.product_id)
        sound.success()
        self.banner.show_stock(
            f"✓ {urun['name']}  +{adet}",
            f"Stok şimdi: {urun['current_stock']} adet",
            "" if maliyet is not None else "Maliyet bilinmiyor (tahmini).",
        )
        self._temizle()
        self.refresh()
        self.data_changed()
        return True

    def cancel(self) -> None:
        if self.product_id is not None:
            self.banner.show_idle("Vazgeçildi. Sıradaki ürünü okutun.")
        self._temizle()

    def _temizle(self) -> None:
        self.product_id = None
        self.barcode_used = None
        self.multiplier = 1
        self.name_label.setText("Ürün okutun.")
        self.stock_label.setText("")
        self.qty_display.set_value("")
        self.cost_display.set_value("")
        self.cost_hint.setText("")
        for dugme in self._unit_buttons.values():
            self.unit_group.removeButton(dugme)
            dugme.deleteLater()
        self._unit_buttons = {}
        self._etkin(False)

    def _etkin(self, acik: bool) -> None:
        for gerec in (self.minus_button, self.plus_button, self.save_button,
                      self.cancel_button, self.unknown_cost_button, self.numpad):
            gerec.setEnabled(acik)
        self._ozet()

    # ===================== Geri alma =====================================
    def _secim(self) -> None:
        oge = self.entries_list.currentItem()
        self.undo_button.setEnabled(oge is not None and oge.data(KIMLIK_ROLU) is not None)

    def undo_selected(self) -> bool:
        oge = self.entries_list.currentItem()
        fis = oge.data(KIMLIK_ROLU) if oge is not None else None
        if fis is None:
            return False
        onizleme = self.services.purchases.reversal_preview(fis)
        if onizleme.reason or not onizleme.allowed:
            show_error(
                self, onizleme.reason or
                "Bu girişten sonra ürün satıldı, sayıldı ya da yeniden girildi; "
                "giriş geri alınamaz. Gerekirse Stok Sayımı ile düzeltin."
            )
            return False
        if not self.guard_require(ProtectedAction.FIS_GERI_AL):
            return False
        metin = oge.text()
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(self, "Bu giriş geri alınsın mı?", metin,
                               accept_text="Geri al", danger=True)
        if not onay:
            return False
        try:
            self.services.purchases.reverse(fis, note="Hızlı Stok Girişi geri alındı")
        except DomainError as hata:
            show_error(self, hata.message)
            return False
        self.refresh()
        self.data_changed()
        self.banner.show_warning("Giriş geri alındı.", metin)
        return True
