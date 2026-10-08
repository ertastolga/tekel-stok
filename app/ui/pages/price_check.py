"""F3 — Fiyat Gör: barkodu okut, fiyatı gör. SATIŞ YAPILMAZ.

Kasada müşteri "bu kaç para?" diye sorduğunda kullanılır. Kurallar:
  * Sepete, satışa, stoğa ve MÜŞTERİ EKRANINA hiçbir şekilde dokunulmaz.
  * Ekranın en üstünde sarı "FİYAT KONTROL — SATIŞ YAPILMAZ" şeridi durur;
    kasiyer yanlışlıkla satış yaptığını sanmaz.
  * Kendi okutma bağlamı ve kendi barkod alanı vardır: okutma burada YALNIZCA
    fiyat gösterir. Okutma işleyicisi ASLA sayfa değiştirmez.
  * "◀ Satışa dön" (ya da Esc) geldiği Kasa sayfasına döndürür; dönüş, olay
    işleyicisinin dışında, bir sonraki olay döngüsü turunda yapılır.
  * Son 5 kontrol listelenir (aynı ürünü tekrar sormak kolay olsun).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from app.core.errors import DomainError
from app.core.money import format_tl
from app.ui import metrics, sound, theme
from app.ui.pages.base import Page
from app.ui.widgets.barcode_input import BarcodeInput, FocusKeeper
from app.ui.widgets.common import Card, make_label
from app.ui.widgets.kasa import KasaToolbar

log = logging.getLogger(__name__)

#: Fiyat Gör'e gelinebilecek Kasa sayfaları (dönüş hedefi).
KASA_KAYNAKLARI = ("sepetli_satis", "hizli_satis")
#: Kaç son kontrol listelensin.
SON_KONTROL = 5
#: Fiyatın yazı boyutu (pt): karşıdan okunabilmeli.
FIYAT_PT = 44.0


class PriceCheckPage(Page):
    nav_title = "🏷  Fiyat Gör"
    nav_key = "fiyat_kontrol"
    nav_group = "kasa"
    accepts_scans = True
    kasa_sayfasi = True

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.return_key = KASA_KAYNAKLARI[0]
        self._son: list[tuple[str, str]] = []

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(metrics.PAGE_MARGIN_H, 10, metrics.PAGE_MARGIN_H, 10)
        duzen.setSpacing(10)

        self.toolbar = KasaToolbar()
        self.barcode = BarcodeInput("sale")
        self.barcode.setPlaceholderText("Fiyatını görmek istediğiniz ürünü okutun")
        self.barcode.submitted.connect(self.show_price_for)
        self.toolbar.add_field(self.barcode)
        self.back_button = self.toolbar.add_tool("◀  Satışa dön", self.return_to_sale)
        self.toolbar.finish(with_menu=False)
        duzen.addWidget(self.toolbar)

        self.mode_banner = QLabel("FİYAT KONTROL — SATIŞ YAPILMAZ")
        self.mode_banner.setObjectName("priceCheckBanner")
        self.mode_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mode_banner.setStyleSheet(
            f"#priceCheckBanner {{ background: {theme.WARNING_LIGHT}; color: {theme.WARNING}; "
            f"border: 2px solid {theme.WARNING}; border-radius: 8px; padding: 6px; "
            f"font-size: {metrics.FONT_SECTION_PT}pt; font-weight: 700; }}"
        )
        duzen.addWidget(self.mode_banner)

        kart = Card()
        self.name_label = make_label("Ürünü okutun.", "sectionTitle", wrap=True,
                                     align=Qt.AlignmentFlag.AlignCenter)
        self.price_label = make_label("", align=Qt.AlignmentFlag.AlignCenter)
        self.price_label.setFont(theme.base_font(FIYAT_PT, bold=True))
        self.detail_label = make_label("", "cardHint", wrap=True,
                                       align=Qt.AlignmentFlag.AlignCenter)
        kart.body.addWidget(self.name_label)
        kart.body.addWidget(self.price_label)
        kart.body.addWidget(self.detail_label)
        duzen.addWidget(kart, 1)

        self.recent_frame = QFrame()
        son = QVBoxLayout(self.recent_frame)
        son.setContentsMargins(0, 0, 0, 0)
        son.setSpacing(2)
        son.addWidget(make_label("Son kontroller", "cardTitle"))
        self.recent_labels = [make_label("", "cardHint") for _ in range(SON_KONTROL)]
        for etiket in self.recent_labels:
            son.addWidget(etiket)
        duzen.addWidget(self.recent_frame)

        self.root.addWidget(govde, 1)
        self.focus_keeper = FocusKeeper(self.barcode)
        self._yenile_son()

    # ===================== Yaşam döngüsü =================================
    def on_activated(self) -> None:
        onceki = getattr(self.main_window, "previous_key", None)
        if onceki in KASA_KAYNAKLARI:
            self.return_key = onceki
        self.focus_keeper.start()
        self.barcode.setFocus()

    def on_deactivated(self) -> None:
        self.focus_keeper.stop()

    def handle_back(self) -> bool:
        """Esc: geldiği Kasa sayfasına döner (ana ekrana değil)."""
        self.return_to_sale()
        return True

    # ===================== Okutma ========================================
    def handle_scan(self, event) -> None:
        self.show_price_for(event.code)

    def show_price_for(self, raw: str) -> None:
        """Yalnızca GÖSTERİR: sepet, satış, stok ve müşteri ekranı değişmez."""
        try:
            eslesme = self.services.barcodes.resolve(raw)
        except DomainError as hata:
            self._goster_hata(hata.message, raw)
            return
        if eslesme is None:
            sahip = self.services.barcodes.inactive_owner(raw)
            if sahip is not None:
                self._goster_hata("Bu ürün kullanımdan kaldırılmış.", sahip["name"])
            else:
                self._goster_hata("Ürün tanınmadı.", f"Barkod: {raw}")
            return
        if not eslesme.is_active:
            self._goster_hata("Bu ürün kullanımdan kaldırılmış.", eslesme.product_name)
            return
        if eslesme.sale_price is None:
            self._goster_hata("Bu ürünün satış fiyatı girilmemiş.", eslesme.product_name)
            return

        sound.price_check()
        fiyat = int(eslesme.sale_price)
        self.name_label.setText(eslesme.product_name)
        self.name_label.setStyleSheet("")
        if eslesme.multiplier > 1:
            toplam = fiyat * eslesme.multiplier
            self.price_label.setText(format_tl(toplam))
            self.detail_label.setText(
                f"Bu barkod {eslesme.multiplier} adetlik paket/koli · "
                f"adet fiyatı {format_tl(fiyat)}"
            )
            ozet = f"{eslesme.product_name} ({eslesme.multiplier} adet) — {format_tl(toplam)}"
        else:
            self.price_label.setText(format_tl(fiyat))
            self.detail_label.setText("Bu ekranda satış yapılmaz.")
            ozet = f"{eslesme.product_name} — {format_tl(fiyat)}"
        self._son.insert(0, (ozet, raw))
        del self._son[SON_KONTROL:]
        self._yenile_son()

    def _goster_hata(self, baslik: str, ayrinti: str) -> None:
        sound.error()
        self.name_label.setText(baslik)
        self.name_label.setStyleSheet(f"color: {theme.DANGER};")
        self.price_label.setText("")
        self.detail_label.setText(ayrinti)

    def _yenile_son(self) -> None:
        for sira, etiket in enumerate(self.recent_labels):
            etiket.setText(self._son[sira][0] if sira < len(self._son) else "")
        self.recent_frame.setVisible(bool(self._son))

    # ===================== Dönüş =========================================
    def return_to_sale(self) -> None:
        """Dönüş olay işleyicisinin DIŞINDA, bir sonraki turda yapılır."""
        QTimer.singleShot(0, self, self._donus)

    def _donus(self) -> None:
        if self.main_window.current_page() is self:
            self.main_window.go_to(self.return_key)
