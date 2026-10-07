"""Hızlı Satış: okut → satıldı.

Uygulamanın en önemli ekranı ve en sade olanı. Sepet yok, tamamla düğmesi yok,
miktar kutusu yok, ödeme sorusu yok. Müşteri 10 bira alıyorsa dükkân sahibi tek
şişeyi 10 kez okutur.

Başarılı satış MODAL PENCERE AÇMAZ: büyük bir onay kartı 2 saniye görünür ve
ekran kendiliğinden hazır duruma döner. "Satış tamamlandı [Tamam]" sorulmaz.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import DomainError, SatisBulunamadi, ZatenGeriAlinmis
from app.core.money import format_tl
from app.core.tr import fmt_time
from app.ui import metrics, shortcuts, sound, theme
from app.ui.dialogs.common_dialogs import (
    PackConfirmDialog,
    ask_confirm,
    scanning_suspended,
    show_error,
)
from app.ui.dialogs.unknown_barcode import UnknownBarcodeDialog
from app.ui.pages.base import Page
from app.ui.widgets.barcode_input import BarcodeInput, FocusKeeper
from app.ui.widgets.common import (
    Card,
    PageHeader,
    ResultBanner,
    SaleFlash,
    StatCard,
    make_label,
    setup_table,
    stretch_column,
)

log = logging.getLogger(__name__)


class QuickSalePage(Page):
    nav_title = "⚡  Hızlı Satış"
    nav_key = "hizli_satis"
    kasa_sayfasi = True
    nav_group = "gunluk"
    accepts_scans = True

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)

        self.header = PageHeader("⚡ Hızlı Satış", "Barkodu okutun, ürün hemen satılır.")
        self.mode_button = QPushButton("🛒  Sepetli Satışa Geç")
        self.mode_button.clicked.connect(
            lambda: self.main_window.go_to("sepetli_satis")
        )
        self.header.add_action(self.mode_button)
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QHBoxLayout(govde)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
        )
        duzen.setSpacing(metrics.PAGE_SPACING)
        duzen.addWidget(self._build_left(), 3)
        duzen.addWidget(self._build_right(), 2)
        self.root.addWidget(govde, 1)

        self.focus_keeper = FocusKeeper(self.barcode)

    # ===================== Kurulum =======================================
    def _build_left(self) -> QWidget:
        sol = QWidget()
        duzen = QVBoxLayout(sol)
        duzen.setContentsMargins(0, 0, 0, 0)
        duzen.setSpacing(metrics.PAGE_SPACING)

        kart = Card()
        kart.body.addWidget(make_label("BARKOD BEKLENİYOR", "cardTitle"))
        self.barcode = BarcodeInput("sale")
        self.barcode.submitted.connect(self._on_manual_entry)
        kart.body.addWidget(self.barcode)
        duzen.addWidget(kart)

        # Sonuç yüzeyi: şerit ve onay kartı TEK bir yığında durur, böylece
        # yüzey değişimi sayfayı yeniden akıtmaz ve düzen zıplamaz.
        self.result_stack = QStackedWidget()
        self.banner = ResultBanner()
        self.flash = SaleFlash()
        self.result_stack.addWidget(self.banner)
        self.result_stack.addWidget(self.flash)
        self.flash.expired.connect(self._show_banner)
        self.banner.shown.connect(self._on_banner_shown)
        duzen.addWidget(self.result_stack)

        self.undo_button = QPushButton(
            shortcuts.label_with_key("geri_al", "Son Satışı Geri Al")
        )
        self.undo_button.setObjectName("bigAction")
        self.undo_button.clicked.connect(self.undo_last)
        duzen.addWidget(self.undo_button)

        duzen.addStretch(1)
        self._show_ready()
        return sol

    def _build_right(self) -> QWidget:
        sag = QWidget()
        duzen = QVBoxLayout(sag)
        duzen.setContentsMargins(0, 0, 0, 0)
        duzen.setSpacing(metrics.PAGE_SPACING)

        ozet = QHBoxLayout()
        ozet.setSpacing(metrics.PAGE_SPACING)
        self.revenue_card = StatCard("BUGÜN CİRO", "-")
        self.count_card = StatCard("BUGÜN SATILAN", "-")
        ozet.addWidget(self.revenue_card)
        ozet.addWidget(self.count_card)
        duzen.addLayout(ozet)

        kart = Card()
        kart.body.addWidget(make_label("Son Satışlar", "sectionTitle"))
        self.table = QTableWidget(0, 3)
        setup_table(self.table, ["Saat", "Ürün", "Tutar"])
        stretch_column(self.table, "Ürün")
        self.table.setMinimumHeight(
            metrics.TABLE_ROW_HEIGHT * metrics.RECENT_MIN_ROWS + 40
        )
        kart.body.addWidget(self.table)
        duzen.addWidget(kart, 1)
        return sag

    # ===================== Yaşam döngüsü =================================
    def on_activated(self) -> None:
        self.focus_keeper.start()
        self.barcode.setFocus()
        self._show_ready()
        self.refresh()

    def on_deactivated(self) -> None:
        self.focus_keeper.stop()

    def refresh(self) -> None:
        try:
            ozet = self.services.analytics.today()
            self.revenue_card.set_value(format_tl(ozet.revenue))
            self.count_card.set_value(f"{ozet.item_count} ürün")
            self._fill_recent()
        except Exception:
            log.exception("Hızlı satış ekranı tazelenemedi")

    def _fill_recent(self) -> None:
        satislar = self.services.sales.recent(limit=25)
        self.table.setRowCount(len(satislar))
        for satir, satis in enumerate(satislar):
            saat = QTableWidgetItem(fmt_time(
                __import__("datetime").datetime.fromtimestamp(satis["created_at_utc"])
            ))
            ad = QTableWidgetItem(satis["ilk_urun"] or "-")
            tutar = QTableWidgetItem(format_tl(satis["total_amount"]))
            tutar.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            if satis["is_reversed"]:
                # Renk TEK BAŞINA anlam taşımaz: metin de açıkça yazar.
                ad.setText(f"{ad.text()}  (geri alındı)")
                for hucre in (saat, ad, tutar):
                    hucre.setForeground(Qt.GlobalColor.gray)
            for sutun, hucre in enumerate((saat, ad, tutar)):
                self.table.setItem(satir, sutun, hucre)

    # ===================== Okutma ========================================
    def handle_scan(self, event) -> None:
        self._sell(event.code)

    def _on_manual_entry(self, text: str) -> None:
        """Elle yazılan barkod da aynı yoldan geçer."""
        self._sell(text)

    def _sell(self, raw: str) -> None:
        try:
            eslesme = self.services.barcodes.resolve(raw)
        except DomainError as hata:
            self._fail(hata.message)
            return

        if eslesme is None:
            self._handle_unknown(raw)
            return
        if not eslesme.is_active:
            self._fail("Bu ürün kullanımdan kaldırılmış.", eslesme.product_name)
            return
        if eslesme.sale_price is None:
            self._fail(
                "Bu ürünün satış fiyatı girilmemiş.",
                f"{eslesme.product_name} — önce fiyatını yazın.",
            )
            return

        adet = eslesme.quantity
        if eslesme.needs_pack_confirm and self.services.settings.pack_confirm_in_sale():
            # Tek okutmayla 24 adet satmak, yanlışlıkla yapılırsa düzeltmesi
            # zor bir hatadır; kısa ve tek soruluk onay alınır.
            with scanning_suspended(self.main_window.router):
                onay = PackConfirmDialog.confirm(
                    eslesme.product_name, adet, "adet", self
                )
            if not onay:
                self._show_ready()
                return

        self._commit(eslesme.product_id, adet, eslesme.barcode, eslesme.multiplier)

    def _handle_unknown(self, raw: str) -> None:
        """Tanınmayan barkod ASLA sessizce yok sayılmaz."""
        sound.error()
        self.banner.show_error(
            "Ürün tanınmadı.", f"Barkod: {raw}", "Tanımlamak için pencereyi kullanın."
        )
        self._show_banner()

        pencere = None

        def engellendi(_event):
            if pencere is not None:
                pencere.notify_blocked()

        with scanning_suspended(self.main_window.router, engellendi):
            pencere = UnknownBarcodeDialog(raw, self.services, self)
            sonuc = pencere.exec()
            urun_id = pencere.product_id if sonuc else None

        if urun_id is None:
            self._show_ready()
            return
        # Ürün açıkça kaydedildi: barkodu TEKRAR okutmaya gerek yok.
        self._commit(urun_id, 1, raw, 1)

    def _commit(self, product_id: int, quantity: int, barcode: str, multiplier: int) -> None:
        try:
            sonuc = self.services.sales.quick_sale(
                product_id, quantity, barcode_used=barcode, multiplier=multiplier
            )
        except DomainError as hata:
            # Teknik ayrıntı kullanıcıya GÖSTERİLMEZ ama kaybolmaz: log'a yazılır.
            log.warning("Hızlı satış reddedildi: %s | %s", hata.message, hata.detail)
            self._fail(hata.message)
            return
        except Exception:
            log.exception("Hızlı satış tamamlanamadı")
            self._fail("İşlem tamamlanamadı. Stok ve satış bilgileri değiştirilmedi.")
            return

        satir = sonuc.lines[0]
        # SALES_FIRST kipinde stok uyarisi kasada GOSTERILMEZ: stoksuz satis
        # normal bir durumdur ve her satista sari uyari akisi bozar. Uyari
        # servis katmaninda yine URETILIR; yalnizca burada gosterilmez.
        uyar = bool(sonuc.warnings) and not self.services.settings.is_sales_first()
        if uyar:
            sound.warning()
            self.flash.flash(
                "✓ SATILDI",
                satir.product_name,
                f"{format_tl(sonuc.total_amount)} · stok kontrolü gerekli",
                border=theme.WARNING,
                background=theme.WARNING_LIGHT,
            )
        else:
            sound.success()
            self.flash.flash(
                "✓ SATILDI",
                satir.product_name,
                format_tl(sonuc.total_amount)
                + (f" · {satir.quantity} adet" if satir.quantity > 1 else ""),
            )
        self.result_stack.setCurrentWidget(self.flash)
        self.refresh()
        self.main_window.refresh_today()

    # ===================== Geri alma =====================================
    def undo_last(self) -> None:
        son = self.services.sales.last_sale()
        if son is None:
            self._fail("Geri alınacak satış bulunamadı.")
            return
        if son["is_reversed"]:
            self._fail("Bu satış daha önce geri alınmış.")
            return
        if son["business_date"] != self.services.settings.calendar().today():
            # Önceki iş gününün satışı: geçmiş satış işlemi (PIN gerekebilir).
            from app.services.security_service import ProtectedAction

            if not self.guard_require(ProtectedAction.GECMIS_SATIS_GERI_AL):
                return

        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self,
                f"{format_tl(son['total_amount'])} tutarındaki son satış geri alınsın mı?",
                "Ürün stoğa geri eklenir. Kayıt silinmez, geri alındı olarak işaretlenir.",
                accept_text="Evet, geri al",
            )
        if not onay:
            self._show_ready()
            return

        try:
            self.services.sales.reverse_sale(son["id"])
        except (SatisBulunamadi, ZatenGeriAlinmis) as hata:
            self._fail(hata.message)
            return
        except Exception:
            log.exception("Satış geri alınamadı")
            self._fail("İşlem tamamlanamadı. Hiçbir bilgi değiştirilmedi.")
            return

        sound.success()
        self.banner.show_warning(
            "↩ SATIŞ GERİ ALINDI", "Ürün stoğa geri eklendi."
        )
        self._show_banner()
        self.refresh()
        self.main_window.refresh_today()

    # ===================== Yüzey yönetimi ================================
    def _show_ready(self) -> None:
        self.banner.show_idle(
            "BARKOD BEKLENİYOR", "Ürünü okutun; satış hemen kaydedilir."
        )
        self._show_banner()

    def _show_banner(self) -> None:
        self.result_stack.setCurrentWidget(self.banner)

    def _on_banner_shown(self, kind: str) -> None:
        """Başarı dışı her gösterim eski onay kartını ANINDA düşürür."""
        if kind != "success":
            self._show_banner()

    def _fail(self, message: str, detail: str = "") -> None:
        sound.error()
        self.banner.show_error(message, detail)
        self._show_banner()
