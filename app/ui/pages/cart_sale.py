"""Sepetli Satış — dokunmatik POS ekranı.

Hedef cihaz **klavyesiz 15,6" AVAPOS** dokunmatik terminaldir. Günlük akış:

    barkodu okut → sepet dolar → NAKİT ya da KART'a dokun → bitti

Sepette ürün varken stok ve ciro DEĞİŞMEZ; hiçbir şey satılmış sayılmaz.
Yalnızca ödeme eylemi tek bir işlemde her şeyi yazar.

Tasarım kuralları
-----------------
* Barkod okutmak, denetimlere dokunmaktan DAİMA hızlıdır: aynı ürün tekrar
  okutulursa mevcut satırın adedi artar.
* Miktar mantığı burada DEĞİLDİR: ``+``/``−`` yalnızca
  ``Cart.set_quantity()`` çağırır (``cart_service.py``).
* **F10 bu ekranı tamamlayamaz** (``completes_with_shortcut`` taban sınıftan
  ``False`` devralınır). Satış YALNIZCA açık bir ödeme eylemiyle oluşur;
  sessizce nakit kaydeden genel bir kısayol yoktur.
* Ödeme onayı veritabanı işleminin DIŞINDA ve ÖNCE alınır.
* Başarı geri bildirimi ASLA modal değildir.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QScroller,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import DomainError
from app.core.models import PaymentMethod
from app.core.money import format_tl
from app.services.cart_service import Cart
from app.ui import metrics, shortcuts, sound, theme
from app.ui.dialogs.common_dialogs import (
    PackConfirmDialog,
    ask_confirm,
    scanning_suspended,
)
from app.ui.dialogs.unknown_barcode import UnknownBarcodeDialog
from app.ui.pages.base import Page
from app.ui.widgets.barcode_input import BarcodeInput, FocusKeeper
from app.ui.widgets.cart_row import CartLineRow
from app.ui.widgets.common import (
    Card,
    EmptyState,
    PageHeader,
    ResultBanner,
    SaleFlash,
    make_label,
)

log = logging.getLogger(__name__)

#: Son okutulan satırın vurgulu kalma süresi.
HIGHLIGHT_MS = 900

#: Ayar okunamazsa kullanılan ekran bekletme süresi.
#: ``schema.DEFAULT_SETTINGS["customer_display_hold_ms"]`` ile aynı değer.
FALLBACK_DISPLAY_HOLD_MS = 4000


class CartSalePage(Page):
    nav_title = "🛒  Sepetli Satış"
    nav_key = "sepetli_satis"
    nav_group = "gunluk"
    accepts_scans = True
    # completes_with_shortcut TANIMLANMAZ: taban sınıftan False gelir.
    # Satış yalnızca açık NAKİT/KART eylemiyle tamamlanır.

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.cart = Cart()
        self._rows: dict[int, CartLineRow] = {}
        self._checkout_busy = False
        self._display_hold = False

        self.header = PageHeader("🛒 Sepetli Satış", "Barkodu okutun.")
        self.undo_button = QPushButton(
            shortcuts.label_with_key("geri_al", "Son Satışı Geri Al")
        )
        self.undo_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.undo_button.clicked.connect(self.undo_last)
        self.header.add_action(self.undo_button)

        self.clear_button = QPushButton("Sepeti Boşalt")
        self.clear_button.setObjectName("danger")
        self.clear_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.clear_button.clicked.connect(self._clear_cart)
        self.header.add_action(self.clear_button)

        self.mode_button = QPushButton("⚡  Hızlı Satış")
        self.mode_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.mode_button.clicked.connect(lambda: self.main_window.go_to("hizli_satis"))
        self.header.add_action(self.mode_button)
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
        )
        duzen.setSpacing(12)

        duzen.addWidget(self._build_scan_card())
        duzen.addWidget(self._build_result_surface())
        duzen.addWidget(self._build_list(), 1)
        duzen.addWidget(self._build_payment_bar())

        self.root.addWidget(govde, 1)
        self.focus_keeper = FocusKeeper(self.barcode)

        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self._clear_highlight)
        self._highlighted: CartLineRow | None = None

        self._render()
        self._show_ready()

    # ===================== Kurulum =======================================
    def _build_scan_card(self) -> QWidget:
        kart = Card()
        kart.body.setContentsMargins(12, 8, 12, 8)
        kart.body.setSpacing(4)
        kart.body.addWidget(make_label("BARKOD BEKLENİYOR", "cardTitle"))
        self.barcode = BarcodeInput("sale")
        self.barcode.submitted.connect(self._add_by_code)
        kart.body.addWidget(self.barcode)
        return kart

    def _build_result_surface(self) -> QWidget:
        # Kanıtlanmış desen (bkz. quick_sale.py): şerit ve onay kartı TEK bir
        # yığında durur, böylece yüzey değişimi düzeni zıplatmaz.
        self.result_stack = QStackedWidget()
        self.banner = ResultBanner()
        self.flash = SaleFlash()
        self.result_stack.addWidget(self.banner)
        self.result_stack.addWidget(self.flash)
        # Serit sabit ve SINIRLI yukseklikte kalir: ekranin asil alani sepet
        # listesidir, geri bildirim onu bastirmamali.
        self.result_stack.setFixedHeight(96)
        self.flash.expired.connect(self._show_banner)
        self.banner.shown.connect(self._on_banner_shown)
        return self.result_stack

    def _build_list(self) -> QWidget:
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        # Sepet listesi ekranin ASIL alanidir: kasiyer ne sattigini gormeli.
        self.scroll.setMinimumHeight(metrics.CART_ROW_HEIGHT * 3)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        icerik = QWidget()
        self.rows_layout = QVBoxLayout(icerik)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)

        self.empty = EmptyState(
            "Sepet boş",
            "Satmak istediğiniz ürünlerin barkodunu okutun.",
        )
        self.rows_layout.addWidget(self.empty)
        self.rows_layout.addStretch(1)
        self.scroll.setWidget(icerik)

        # Parmakla kinetik kaydırma: dokunmatik ekranda sürükleyerek gezinmek.
        QScroller.grabGesture(
            self.scroll.viewport(), QScroller.ScrollerGestureType.LeftMouseButtonGesture
        )
        return self.scroll

    def _build_payment_bar(self) -> QWidget:
        kart = Card()
        kart.body.setContentsMargins(14, 10, 14, 10)
        kart.body.setSpacing(8)

        ust = QHBoxLayout()
        ust.addWidget(make_label("TOPLAM", "cartGrandLabel"))
        ust.addStretch(1)
        self.total_label = make_label("0 TL", "cartGrandTotal")
        ust.addWidget(self.total_label)
        kart.body.addLayout(ust)

        dugmeler = QHBoxLayout()
        dugmeler.setSpacing(12)

        self.cash_button = QPushButton("NAKİT")
        self.cash_button.setObjectName("cashButton")
        self.cash_button.setMinimumHeight(metrics.PAYMENT_BUTTON_HEIGHT)
        self.cash_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cash_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cash_button.clicked.connect(
            lambda: self.complete(PaymentMethod.CASH)
        )
        dugmeler.addWidget(self.cash_button, 1)

        self.card_button = QPushButton("KART")
        self.card_button.setObjectName("cardButton")
        self.card_button.setMinimumHeight(metrics.PAYMENT_BUTTON_HEIGHT)
        self.card_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.card_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.card_button.clicked.connect(
            lambda: self.complete(PaymentMethod.CARD)
        )
        dugmeler.addWidget(self.card_button, 1)
        kart.body.addLayout(dugmeler)
        return kart

    # ===================== Yaşam döngüsü =================================
    def on_activated(self) -> None:
        self.focus_keeper.start()
        self.barcode.setFocus()
        self._offer_draft_recovery()
        self._render()
        self._show_ready()

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
        self._rebuild_rows()
        self._render()

    # ===================== Okutma ========================================
    def handle_scan(self, event) -> None:
        self._add_by_code(event.code)

    def _add_by_code(self, raw: str) -> None:
        if self._checkout_busy:
            return
        eslesme = self.services.barcodes.resolve(raw)
        if eslesme is None:
            self._handle_unknown(raw)
            return

        adet = eslesme.quantity
        if eslesme.needs_pack_confirm and self.services.settings.pack_confirm_in_sale():
            with scanning_suspended(self.main_window.router):
                onay = PackConfirmDialog.confirm(
                    eslesme.product_name, adet, "adet", self
                )
            if not onay:
                return
        self._add_product(
            eslesme.product_id, adet, eslesme.barcode, eslesme.multiplier
        )

    def _handle_unknown(self, raw: str) -> None:
        """Tanınmayan barkod ASLA sessizce yok sayılmaz."""
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

    def _add_product(self, product_id: int, quantity: int, barcode: str | None,
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
        self._render()
        self._highlight(product_id)
        self.banner.show_success(
            f"✓ {satir.product_name}",
            f"{satir.quantity} adet · {format_tl(satir.line_total)}",
        )

    # ===================== Miktar denetimleri ============================
    def _on_quantity_changed(self, product_id: int, new_quantity: int) -> None:
        """``+`` / ``−`` — miktar kuralı SERVİSTEDİR, burada kopyalanmaz.

        ``set_quantity`` 0 ve altında satırı kendisi siler; "1'deyken eksiye
        basmak" bu yüzden doğal olarak ürünü sepetten çıkarır.
        """
        self.cart.set_quantity(product_id, new_quantity)
        self._render()
        if self.cart.find(product_id) is not None:
            self._highlight(product_id)

    def _on_remove_requested(self, product_id: int) -> None:
        self.cart.remove(product_id)
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
        self._rebuild_rows()
        self._render()
        self._show_ready()

    # ===================== Ödeme =========================================
    def complete(self, payment_method: str = PaymentMethod.CASH) -> None:
        """Sepeti ÖDEMEYLE tamamlar.

        Varsayılan NAKİT'tir; NAKİT düğmesi ve testler bunu argümansız çağırır.
        Genel F10 kısayolu bu metoda ULAŞMAZ (``completes_with_shortcut`` False).
        """
        if self._checkout_busy or self.cart.is_empty:
            return

        self._checkout_busy = True
        self._set_payment_enabled(False)
        son_tutar = self.cart.total          # ekran için checkout'tan ÖNCE yakala
        self._display_hold = True
        basarili = False
        try:
            with scanning_suspended(self.main_window.router):
                # 1) ÖNCE ödeme — veritabanı işlemi AÇILMADAN.
                odeme = self.services.payments.authorize(payment_method, son_tutar)
                if not odeme.approved:
                    sound.error()
                    self.banner.show_error(
                        odeme.message or "Ödeme tamamlanmadı.",
                        "Sepetiniz olduğu gibi duruyor.",
                    )
                    return

                # 2) SONRA satış.
                try:
                    sonuc = self.services.cart.checkout(
                        self.cart, payment_method=payment_method
                    )
                except DomainError as hata:
                    sound.error()
                    self.banner.show_error(hata.message)
                    return
                except Exception:
                    # Ödeme onaylandı ama satış yazılamadı. V1.1'de manuel
                    # adaptörlerde iptal edilecek elektronik işlem YOKTUR;
                    # yine de iz bırakılır ve kullanıcı açıkça uyarılır.
                    log.critical(
                        "Ödeme onaylandı ama satış yazılamadı: %s %s ref=%s",
                        payment_method, son_tutar, odeme.reference, exc_info=True,
                    )
                    sound.error()
                    self.banner.show_error(
                        "Satış kaydedilemedi.",
                        "Ödeme alındıysa lütfen kontrol edin. "
                        "Sepet olduğu gibi duruyor.",
                    )
                    return
                basarili = True
        finally:
            self._checkout_busy = False
            self._set_payment_enabled(True)
            if not basarili:
                # Başarısızlıkta sepet ve ekran DEĞİŞMEDEN kalır.
                self._display_hold = False
                self._publish_display()
                self._render()

        self._finish_success(sonuc, payment_method, son_tutar)

    def _finish_success(self, sonuc, payment_method: str, son_tutar: int) -> None:
        # Müşteri ekranı EN BAŞTA işlenir ve serbest bırakma zamanlayıcısı
        # hemen kurulur. Aşağıdaki arayüz adımlarından biri hata verse bile
        # ``_display_hold`` MUTLAKA çözülür; aksi hâlde bayrak True kalır,
        # ``_publish_display`` kalıcı olarak susar ve ekran o tutarda donardı.
        self.services.display.show_total(son_tutar)
        QTimer.singleShot(self._display_hold_ms(), self._release_display_hold)

        sound.success()
        self._rebuild_rows()
        self._render()

        etiket = "NAKİT" if payment_method == PaymentMethod.CASH else "KART"
        ayrinti = f"{sonuc.item_count} ürün · {etiket}"
        # Stok uyarısı SALES_FIRST kipinde kasada gösterilmez; envanter
        # kipinde eskisi gibi görünür.
        if sonuc.warnings and not self.services.settings.is_sales_first():
            ayrinti += " · stok kontrolü gerekli"

        self.flash.flash("✓ SATIŞ TAMAMLANDI", format_tl(son_tutar), ayrinti)
        self.result_stack.setCurrentWidget(self.flash)

        self.barcode.setFocus()
        self.main_window.refresh_today()

    def _display_hold_ms(self) -> int:
        """Son tutarın müşteri ekranında kalma süresi.

        Ayar okunamasa bile DAİMA bir süre döner: bu değer bekletmeyi çözen
        zamanlayıcıyı kurar, dolayısıyla burada istisna sızması ekranı
        kalıcı olarak dondururdu.
        """
        try:
            return self.services.settings.customer_display_hold_ms()
        except Exception:
            log.warning("Ekran bekletme süresi okunamadı", exc_info=True)
            return FALLBACK_DISPLAY_HOLD_MS

    def _set_payment_enabled(self, enabled: bool) -> None:
        self.cash_button.setEnabled(enabled and not self.cart.is_empty)
        self.card_button.setEnabled(enabled and not self.cart.is_empty)

    # ===================== Geri alma =====================================
    def undo_last(self) -> None:
        """ÖNCEKİ müşterinin satışını iptal eder — eldeki sepeti DEĞİL.

        Sepette ürün varken kapalıdır. Kasada iki ayrı şey aynı anda
        duruyorsa (yarım sepet + bitmiş bir satış) "geri al" iki anlama
        gelebilir; acele eden bir kasiyer yanlışını anlamadan önceki
        müşterinin satışını iptal edebilir.

        Kapı düğmede DEĞİL burada durur: F8 bu metoda düğmenin etkin olup
        olmadığına bakmadan ulaşır (``main_window._undo_last``).
        """
        if not self.cart.is_empty:
            sound.error()
            self.banner.show_error(
                "Sepet dolu olduğu için geri alma kapalı.",
                "Bu eylem ÖNCEKİ satışı iptal eder. Önce bu sepeti tamamlayın "
                "ya da boşaltın; dilediğiniz satışı Geçmiş ekranından da geri "
                "alabilirsiniz.",
            )
            return

        son = self.services.sales.last_sale()
        if son is None:
            self.banner.show_error("Geri alınacak satış bulunamadı.")
            return
        if son["is_reversed"]:
            self.banner.show_error("Bu satış daha önce geri alınmış.")
            return

        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self,
                f"{format_tl(son['total_amount'])} tutarındaki son satış "
                "geri alınsın mı?",
                "Ürünler stoğa geri eklenir. Kayıt silinmez, geri alındı olarak "
                "işaretlenir.",
                accept_text="Evet, geri al",
            )
        if not onay:
            return
        try:
            self.services.sales.reverse_sale(son["id"])
        except DomainError as hata:
            self.banner.show_error(hata.message)
            return
        sound.success()
        self.banner.show_warning("↩ SATIŞ GERİ ALINDI", "Ürünler stoğa geri eklendi.")
        self.main_window.refresh_today()

    # ===================== Müşteri ekranı ================================
    def _publish_display(self) -> None:
        """Sepet değiştiğinde müşteri ekranını günceller.

        Tamamlama sırasında BASTIRILIR: ``checkout()`` sepeti boşalttığı için
        aksi hâlde ekran anında 0.00'a düşer ve müşteri son tutarı göremezdi.
        """
        if self._display_hold:
            return
        try:
            if self.cart.is_empty:
                self.services.display.show_idle()
            else:
                self.services.display.show_total(self.cart.total)
        except Exception:
            # CustomerDisplayService zaten yutar; bu yalnızca ek güvence.
            log.warning("Müşteri ekranı güncellenemedi", exc_info=True)

    def _release_display_hold(self) -> None:
        """Bekletme süresi doldu: ekran 0.00'a döner.

        Ayrı bir metottur ki test, zamanlayıcı beklemeden çağırıp sıralamayı
        kesin olarak doğrulayabilsin.
        """
        self._display_hold = False
        self._publish_display()

    # ===================== Çizim =========================================
    def _rebuild_rows(self) -> None:
        """Tüm satırları sıfırdan kurar (taslak yükleme / sepet boşaltma)."""
        for satir in self._rows.values():
            self.rows_layout.removeWidget(satir)
            satir.deleteLater()
        self._rows.clear()
        self._highlighted = None

    def _render(self) -> None:
        """Satırları ARTIMLI günceller.

        Yüzlerce okutmada tüm liste yeniden kurulmaz: var olan satır yerinde
        tazelenir, yalnızca yeni ürün için gereç oluşturulur.
        """
        mevcut = {line.product_id: line for line in self.cart.lines}

        for product_id in list(self._rows):
            if product_id not in mevcut:
                satir = self._rows.pop(product_id)
                self.rows_layout.removeWidget(satir)
                satir.deleteLater()
                if self._highlighted is satir:
                    self._highlighted = None

        for index, line in enumerate(self.cart.lines):
            satir = self._rows.get(line.product_id)
            if satir is None:
                satir = CartLineRow(line)
                satir.quantity_changed.connect(self._on_quantity_changed)
                satir.remove_requested.connect(self._on_remove_requested)
                self._rows[line.product_id] = satir
                # stretch'ten önce ekle (son eleman stretch'tir)
                self.rows_layout.insertWidget(index, satir)
            else:
                satir.update_line(line)

        dolu = not self.cart.is_empty
        self.empty.setVisible(not dolu)
        self.clear_button.setEnabled(dolu)
        self._set_payment_enabled(not self._checkout_busy)

        # Geri alma ÖNCEKİ satışa aittir; eldeki sepetle karışmasın diye
        # sepet doluyken kapatılır (asıl kapı ``undo_last`` içindedir).
        self.undo_button.setEnabled(not dolu)
        self.undo_button.setToolTip(
            "Önceki satışı iptal eder. Sepet boşaltılınca kullanılabilir."
            if dolu else "Önceki satışı iptal eder."
        )

        self.total_label.setText(format_tl(self.cart.total))
        self.cash_button.setText(
            f"NAKİT  {format_tl(self.cart.total)}" if dolu else "NAKİT"
        )
        self.card_button.setText(
            f"KART  {format_tl(self.cart.total)}" if dolu else "KART"
        )
        self.header.set_subtitle(
            f"{self.cart.item_count} ürün · {format_tl(self.cart.total)}"
            if dolu else "Barkodu okutun."
        )
        self._publish_display()

    def _highlight(self, product_id: int) -> None:
        """Son okutulan satırı vurgular ve görünür alana kaydırır."""
        satir = self._rows.get(product_id)
        if satir is None:
            return
        self._clear_highlight()
        satir.set_highlighted(True)
        self._highlighted = satir
        self._highlight_timer.start(HIGHLIGHT_MS)
        self.scroll.ensureWidgetVisible(satir, 0, 20)

    def _clear_highlight(self) -> None:
        if self._highlighted is not None:
            try:
                self._highlighted.set_highlighted(False)
            except RuntimeError:
                pass          # gereç bu arada silinmiş olabilir
            self._highlighted = None

    # ===================== Yüzey yönetimi ================================
    def _show_ready(self) -> None:
        self.banner.show_idle(
            "BARKOD BEKLENİYOR", "Ürünleri okutun, sonra NAKİT ya da KART'a dokunun."
        )
        self._show_banner()

    def _show_banner(self) -> None:
        self.result_stack.setCurrentWidget(self.banner)

    def _on_banner_shown(self, kind: str) -> None:
        """Başarı dışı her gösterim eski onay kartını ANINDA düşürür."""
        if kind != "success":
            self._show_banner()
