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
* Ekranda görünen = ödemesi alınan = kaydedilen tutar: ödeme onayından HEMEN
  önce sepet güncel fiyatlarla doğrulanır; fiyatı değişen satır işaretlenir ve
  "Güncel fiyatları uygula" ya da satırı çıkarmadan ödeme yapılamaz.
* Sepet her değiştiğinde kısa bir gecikmeyle diske yazılır (elektrik kesintisi,
  kapanış); boşalan sepetin taslağı iptal edilir.
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
from app.services.cart_service import (
    SORUN_FIYAT_DEGISTI,
    TASLAK_BEKLEYEN,
    TASLAK_OTOMATIK,
    LineIssue,
)
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
    ResultBanner,
    SaleFlash,
    make_label,
)
from app.ui.widgets.kasa import KasaToolbar, SonucSeridi
from app.ui.widgets.kasa_overlays import (
    BekleyenlerPanel,
    KatmanSahibi,
    TenderPanel,
    UrunAraPanel,
)

log = logging.getLogger(__name__)

#: Son okutulan satırın vurgulu kalma süresi.
HIGHLIGHT_MS = 900

#: Sepet değiştikten sonra taslağın diske yazılma gecikmesi. Okutma akışını
#: yavaşlatmayacak kadar uzun, elektrik kesintisinde en fazla bu kadarlık
#: değişikliği kaybettirecek kadar kısa.
AUTOSAVE_MS = 750

#: Kasa sayfasının dikey kenar boşluğu ve öğeler arası boşluk (bütçe §5.2).
KASA_DIKEY_KENAR = 10
KASA_ARALIK = 8

#: Sonuç şeridinde gösterilebilecek EN UZUN iletiler; şerit yüksekliği bunlarla
#: ölçülür. Yeni bir uzun ileti eklenirse buraya da eklenir (test denetler).
SERIT_ORNEKLERI = (
    ("flash", "✓ SATIŞ TAMAMLANDI", "12.345,50 TL",
     "128 ürün · NAKİT · stok kontrolü gerekli", "Para üstü: 7.654,50 TL"),
    ("banner", "Sepet dolu olduğu için geri alma kapalı.",
     "Bu eylem ÖNCEKİ satışı iptal eder. Önce bu sepeti tamamlayın ya da "
     "boşaltın; dilediğiniz satışı Geçmiş ekranından da geri alabilirsiniz.", ""),
    ("banner", "Ödeme alınmadı: sepette değişen ürün var.",
     "İşaretli satırlar için \"Güncel fiyatları uygula\"ya dokunun ya da ürünü "
     "sepetten çıkarın.", ""),
    ("banner", "Satış kaydedilemedi.",
     "Ödeme alındıysa lütfen kontrol edin. Satış KAYDEDİLMEDİ; sepet olduğu gibi "
     "duruyor.", ""),
)

#: Katman durumları. Okutmayı KABUL ETMEYEN katmanlar burada listelenir.
KATMAN_BEKLEYENLER = "BEKLEYENLER"
KATMAN_ARA = "ARA"
KATMAN_PARA_USTU = "PARA_USTU"
OKUTMA_KAPALI_KATMANLAR = {KATMAN_BEKLEYENLER, KATMAN_PARA_USTU}

#: Ayar okunamazsa kullanılan ekran bekletme süresi.
#: ``schema.DEFAULT_SETTINGS["customer_display_hold_ms"]`` ile aynı değer.
FALLBACK_DISPLAY_HOLD_MS = 4000


class CartSalePage(KatmanSahibi, Page):
    nav_title = "🛒  Sepetli Satış"
    nav_key = "sepetli_satis"
    nav_group = "kasa"
    accepts_scans = True
    kasa_sayfasi = True
    # completes_with_shortcut TANIMLANMAZ: taban sınıftan False gelir.
    # Satış yalnızca açık NAKİT/KART eylemiyle tamamlanır.

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.cart = services.cart.new_cart()
        self._rows: dict[int, CartLineRow] = {}
        self._issues: dict[int, LineIssue] = {}
        self._checkout_busy = False
        self._display_hold = False
        #: Katman durum makinesi (plan §5.2): aynı anda en fazla bir katman.
        self._katman_baslat()
        self._parked_panel: BekleyenlerPanel | None = None
        self._search_panel: UrunAraPanel | None = None
        self._tender_panel: TenderPanel | None = None

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        # Kasa sayfasında sayfa başlığı YOKTUR (yerleşim bütçesi, plan §5.2).
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, KASA_DIKEY_KENAR,
            metrics.PAGE_MARGIN_H, KASA_DIKEY_KENAR,
        )
        duzen.setSpacing(KASA_ARALIK)

        duzen.addWidget(self._build_toolbar())
        duzen.addWidget(self._build_result_surface())
        duzen.addWidget(self._build_list(), 1)
        duzen.addWidget(self._build_payment_bar())

        self.root.addWidget(govde, 1)
        self.focus_keeper = FocusKeeper(self.barcode)

        self._highlight_timer = QTimer(self)
        self._highlight_timer.setSingleShot(True)
        self._highlight_timer.timeout.connect(self._clear_highlight)
        self._highlighted: CartLineRow | None = None

        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._autosave_now)

        self._render()
        self._show_ready()
        self.apply_settings()

    def apply_settings(self) -> None:
        """Hızlı Satış kapalıysa ona giden düğme de görünmez."""
        try:
            self.mode_button.setVisible(self.services.settings.show_quick_sale())
            # NAKİT daima vardır; KART gizlenebilir (VERESİYE / DİĞER sunulmaz).
            self.card_button.setVisible(self.services.settings.show_card_button())
        except Exception:
            log.exception("Kasa ayarları uygulanamadı")

    # ===================== Kurulum =======================================
    def _build_toolbar(self) -> QWidget:
        """Tek satır: barkod alanı + dokunma düğmeleri + "⋯" menüsü."""
        self.toolbar = KasaToolbar()
        self.barcode = BarcodeInput("sale")
        # Kısa yer tutucu: sonuç şeridi zaten "BARKOD BEKLENİYOR" der; uzun
        # metin kompakt alanda kırpılıyordu (M12b).
        self.barcode.setPlaceholderText("Barkodu okutun…")
        self.barcode.submitted.connect(self._add_by_code)
        self.toolbar.add_field(self.barcode)
        self.search_button = self.toolbar.add_tool(
            "🔍 Ürün Ara", self.open_search, "Barkodu okunmayan ürünü ada göre bul (Ctrl+F)"
        )
        self.park_button = self.toolbar.add_tool(
            "Beklet", self.park_current, "Sepeti beklet, yeni müşteriye başla"
        )
        self.parked_button = self.toolbar.add_tool(
            "Bekleyenler (0)", self.show_parked, "Bekleyen sepetleri göster"
        )
        self.price_check_button = self.toolbar.add_tool(
            "🏷 Fiyat Gör", lambda: self.main_window.go_to("fiyat_kontrol"),
            "Okutulan ürünün fiyatını göster, satış yapma (F11)",
            collapsible=True,                 # dar pencerede "⋯" menüsünde
        )
        self.toolbar.finish()
        # "⋯" menüsü: seyrek kullanılan eylemler. Öznitelik adları V1.1 ile
        # aynıdır (``undo_button``, ``clear_button``, ``mode_button``).
        self.undo_button = self.toolbar.add_menu_action(
            shortcuts.label_with_key("geri_al", "Son Satışı Geri Al"), self.undo_last
        )
        self.clear_button = self.toolbar.add_menu_action("Sepeti Boşalt", self._clear_cart)
        self.mode_button = self.toolbar.add_menu_action(
            "⚡  Hızlı Satış", lambda: self.main_window.go_to("hizli_satis")
        )
        return self.toolbar

    def _build_result_surface(self) -> QWidget:
        # Kanıtlanmış desen (bkz. quick_sale.py): şerit ve onay kartı TEK bir
        # yığında durur, böylece yüzey değişimi düzeni zıplatmaz.
        self.banner = ResultBanner()
        self.flash = SaleFlash()
        self.result_stack = SonucSeridi(self.banner, self.flash, SERIT_ORNEKLERI)
        self.flash.expired.connect(self._show_banner)
        self.banner.shown.connect(self._on_banner_shown)
        return self.result_stack

    def _build_list(self) -> QWidget:
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        # Sepet listesi ekranin ASIL alanidir: en az iki satır her zaman görünür.
        self.scroll.setMinimumHeight(metrics.CART_ROW_HEIGHT * 2 + 8 + 4)
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
        """TEK satır: toplam + NAKİT + KART (düğmeler ≥ 88 px)."""
        kart = Card()
        kart.body.setContentsMargins(14, 8, 14, 8)
        kart.body.setSpacing(0)

        satir = QHBoxLayout()
        satir.setSpacing(12)
        toplam = QVBoxLayout()
        toplam.setSpacing(0)
        self.total_caption = make_label("TOPLAM", "cartGrandLabel")
        toplam.addWidget(self.total_caption)
        self.total_label = make_label("0 TL", "cartGrandTotal")
        toplam.addWidget(self.total_label)
        satir.addLayout(toplam)
        # Yalnızca fiyatı değişen satır varken görünür: fiyat ASLA sessizce
        # düzeltilmez, kasiyer açıkça onaylar.
        self.apply_prices_button = QPushButton("Güncel fiyatları uygula")
        self.apply_prices_button.setObjectName("primary")
        self.apply_prices_button.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
        self.apply_prices_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.apply_prices_button.clicked.connect(self.apply_current_prices)
        self.apply_prices_button.setVisible(False)
        satir.addWidget(self.apply_prices_button)

        self.cash_button = QPushButton("NAKİT")
        self.cash_button.setObjectName("cashButton")
        self.cash_button.setMinimumHeight(metrics.PAYMENT_BUTTON_HEIGHT)
        self.cash_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cash_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cash_button.clicked.connect(self.cash_pressed)
        satir.addWidget(self.cash_button, 1)

        self.card_button = QPushButton("KART")
        self.card_button.setObjectName("cardButton")
        self.card_button.setMinimumHeight(metrics.PAYMENT_BUTTON_HEIGHT)
        self.card_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.card_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.card_button.clicked.connect(
            lambda: self.complete(PaymentMethod.CARD)
        )
        satir.addWidget(self.card_button, 1)
        kart.body.addLayout(satir)
        return kart

    # ===================== Yaşam döngüsü =================================
    def on_activated(self) -> None:
        self.focus_keeper.start()
        self.barcode.setFocus()
        self._offer_draft_recovery()
        self._render()
        self._refresh_parked_count()
        self._show_ready()

    def yedek_icin_uygun(self) -> bool:
        return not self._checkout_busy and self._overlay_state is None

    def on_deactivated(self) -> None:
        # Açık katman "vazgeç" anlamıyla kapanır ve okutma askısını bırakır;
        # bağlam ANCAK bundan sonra değişir.
        self.close_overlay()
        self.focus_keeper.stop()
        # Ekrandan çıkarken sepet KAYBOLMAZ: taslak HEMEN diske yazılır.
        self._autosave_now()

    def on_app_closing(self) -> None:
        """Uygulama kapanıyor: bekleyen taslak yazımı hemen yapılır.

        Geri yükleme sonrası yeniden başlatmada YAPILMAZ: eski sepet, yeni
        (geri yüklenmiş) veriye yazılmamalıdır.
        """
        self._autosave_timer.stop()
        if getattr(self.main_window, "restarting", False):
            return
        self._autosave_now()

    def refresh(self) -> None:
        self._render()

    # ===================== Taslak kalıcılığı =============================
    def _schedule_autosave(self) -> None:
        """Sepet değişti: kısa gecikmeyle diske yaz (art arda okutmalar birleşir)."""
        if getattr(self.main_window, "restarting", False):
            return
        self._autosave_timer.start(AUTOSAVE_MS)

    def _autosave_now(self) -> None:
        self._autosave_timer.stop()
        if getattr(self.main_window, "restarting", False):
            return
        if self._checkout_busy:
            # Ödeme sürerken sepet değişmez; bitince yeniden denenir.
            self._autosave_timer.start(AUTOSAVE_MS)
            return
        try:
            self.services.cart.autosave(self.cart)
        except Exception:
            # Taslak yazılamaması satışı ENGELLEMEZ; yalnızca iz bırakılır.
            log.exception("Sepet taslağı kaydedilemedi")

    def _offer_draft_recovery(self) -> None:
        """Yarım kalmış sepet KENDİLİĞİNDEN tamamlanmaz; kullanıcı karar verir."""
        if not self.cart.is_empty:
            return
        # Yalnızca otomatik kayıt kurtarılır; bekletilen sepetler "Bekleyenler"de.
        taslaklar = self.services.cart.open_drafts(kind=TASLAK_OTOMATIK)
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
        if self._issues:
            # Bekleyen sepet ASLA sessizce onarılmaz: sorunlu satırlar
            # işaretlidir, kasiyer karar verir.
            sound.error()
            self.banner.show_error(
                "Sepetteki bazı ürünlerde değişiklik var.",
                "İşaretli satırları kontrol edin.",
            )

    # ===================== Okutma ========================================
    def handle_scan(self, event) -> None:
        self._add_by_code(event.code)

    def _add_by_code(self, raw: str) -> None:
        """Okutmanın ve elle girişin TEK girişi (yönlendirici + barkod alanı)."""
        if self._checkout_busy:
            return
        if self._overlay_state in OKUTMA_KAPALI_KATMANLAR:
            self._overlay.notify_blocked()
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

        def engellendi(event):
            # Pencere açıkken okutma: barkod alanı etkinse oraya yazılır.
            if pencere is not None:
                pencere.notify_blocked(event)

        with scanning_suspended(self.main_window.router, engellendi):
            pencere = UnknownBarcodeDialog(raw, self.services, self)
            kabul = pencere.exec()
            urun_id = pencere.product_id if kabul else None
        if urun_id is None:
            return
        # Barkod YENİDEN çözülür: koli barkoduyla tanımlanan ürün, kolideki
        # adet kadar eklenir (paket onayı dahil). Barkod ürüne bağlanmadıysa
        # (ör. alan boşaltıldı) ürün 1 adet eklenir.
        if self.services.barcodes.resolve(raw) is not None:
            self._add_by_code(raw)
        else:
            self._add_product(urun_id, 1, None, 1)

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

        sound.scan()
        self._render()
        self._schedule_autosave()
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
        self._schedule_autosave()
        if self.cart.find(product_id) is not None:
            self._highlight(product_id)

    def _on_remove_requested(self, product_id: int) -> None:
        self.cart.remove(product_id)
        self._render()
        self._schedule_autosave()

    def apply_current_prices(self) -> None:
        """Kasiyerin AÇIK kararı: fiyatı değişen satırlara güncel fiyat yazılır."""
        degisen = self.services.cart.apply_current_prices(self.cart)
        self._render()
        self._schedule_autosave()
        if degisen:
            self.banner.show_warning(
                "Güncel fiyatlar uygulandı.",
                f"Yeni toplam: {format_tl(self.cart.total)}",
            )

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
        self._autosave_timer.stop()
        if self.cart.draft_id is not None:
            self.services.cart.discard_draft(self.cart.draft_id)
        self.cart = self.services.cart.new_cart()
        self._rebuild_rows()
        self._render()
        self._show_ready()

    # ===================== Ödeme =========================================
    # ===================== Para Üstü (F4) ================================
    def cash_pressed(self) -> None:
        """NAKİT: ayar kapalıysa tek dokunuş (V1.1); açıksa Para Üstü paneli."""
        if not self.services.settings.cash_change_calculator():
            self.complete(PaymentMethod.CASH)
            return
        if self._checkout_busy or self.cart.is_empty:
            return
        self._refresh_issues()
        if self._issues:
            self.complete(PaymentMethod.CASH)       # aynı ret iletisi
            return
        if self._tender_panel is None:
            self._tender_panel = TenderPanel(self)
            self._tender_panel.hide()
            self._tender_panel.confirmed.connect(self._tender_confirmed)
            self._tender_panel.cancelled.connect(self.close_overlay)
        self._tender_panel.prepare(self.cart.total)
        self._open_overlay(KATMAN_PARA_USTU, self._tender_panel, block_scans=True)

    def _tender_confirmed(self, tendered: int) -> None:
        # Askı jetonu katman kapanırken (finally) bırakılır; satış SONRA yazılır.
        self.close_overlay()
        self.complete(PaymentMethod.CASH, tendered=tendered)

    def complete(self, payment_method: str = PaymentMethod.CASH,
                 tendered: int | None = None) -> bool:
        """Sepeti ÖDEMEYLE tamamlar; satış YAZILDIYSA ``True`` döner.

        Varsayılan NAKİT'tir; NAKİT düğmesi ve testler bunu argümansız çağırır.
        ``tendered``: NAKİT'te alınan tutar (yalnızca para üstü için; kaydedilmez)
        — GÜNCEL toplamdan az olamaz.
        Genel F10 kısayolu bu metoda ULAŞMAZ (``completes_with_shortcut`` False).
        """
        if self._checkout_busy or self.cart.is_empty:
            return False
        if tendered is not None and tendered < self.cart.total:
            sound.error()
            self.banner.show_error(
                "Alınan tutar toplamdan az.",
                f"Toplam {format_tl(self.cart.total)}, alınan {format_tl(tendered)}.",
            )
            return False

        # Ödeme onayından HEMEN ÖNCE: sepet güncel fiyatlarla aynı mı?
        self._refresh_issues()
        if self._issues:
            self._render()
            sound.error()
            self.banner.show_error(
                "Ödeme alınmadı: sepette değişen ürün var.",
                "İşaretli satırlar için \"Güncel fiyatları uygula\"ya dokunun "
                "ya da ürünü sepetten çıkarın.",
            )
            return False

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
                    return False

                # 2) SONRA satış.
                try:
                    sonuc = self.services.cart.checkout(
                        self.cart, payment_method=payment_method
                    )
                except Exception as hata:
                    # Ödeme onaylandı ama satış yazılamadı (iş kuralı ya da
                    # beklenmeyen hata — fark etmez). V1.1/V1.2 manuel
                    # adaptörlerinde iptal edilecek elektronik işlem YOKTUR;
                    # yine de iz bırakılır ve kullanıcı açıkça uyarılır.
                    log.critical(
                        "Ödeme onaylandı ama satış yazılamadı: %s %s ref=%s",
                        payment_method, son_tutar, odeme.reference, exc_info=True,
                    )
                    sound.error()
                    neden = (
                        hata.message if isinstance(hata, DomainError)
                        else "Satış kaydedilemedi."
                    )
                    self.banner.show_error(
                        neden,
                        "Ödeme alındıysa lütfen kontrol edin. Satış KAYDEDİLMEDİ; "
                        "sepet olduğu gibi duruyor.",
                    )
                    return False
                basarili = True
        finally:
            self._checkout_busy = False
            self._set_payment_enabled(True)
            if not basarili:
                # Başarısızlıkta sepet ve ekran DEĞİŞMEDEN kalır.
                self._display_hold = False
                self._publish_display()
                self._render()

        self._finish_success(sonuc, payment_method, son_tutar, tendered)
        return True

    def _finish_success(self, sonuc, payment_method: str, son_tutar: int,
                        tendered: int | None = None) -> None:
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

        para_ustu = (
            f"Para üstü: {format_tl(tendered - son_tutar)}"
            if tendered is not None else ""
        )
        self.flash.flash("✓ SATIŞ TAMAMLANDI", format_tl(son_tutar), ayrinti,
                         extra=para_ustu)
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
        acik = enabled and not self.cart.is_empty and not self._issues
        self.cash_button.setEnabled(acik)
        self.card_button.setEnabled(acik)

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
        if not self._gecmis_gun_kapisi(son):
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

    def _gecmis_gun_kapisi(self, satis) -> bool:
        """Aynı iş gününün son satışı Kasa'da PIN'siz geri alınır; ÖNCEKİ bir
        güne ait satışı geri almak geçmiş satış işlemidir (PIN gerekebilir)."""
        from app.services.security_service import ProtectedAction

        bugun = self.services.settings.calendar().today()
        if satis["business_date"] == bugun:
            return True
        return self.guard_require(ProtectedAction.GECMIS_SATIS_GERI_AL)

    # ===================== Katmanlar =====================================
    def _set_controls_enabled(self, enabled: bool) -> None:
        """Katman açıkken sepet, araç çubuğu ve ödeme denetimleri kapalıdır."""
        for dugme in self.toolbar.tools:
            dugme.setEnabled(enabled)
        self.toolbar.more_button.setEnabled(enabled)
        self.scroll.setEnabled(enabled)
        self.apply_prices_button.setEnabled(enabled)
        if enabled:
            self._set_payment_enabled(not self._checkout_busy)
        else:
            self.cash_button.setEnabled(False)
            self.card_button.setEnabled(False)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._katman_boyutla()

    # ===================== Ürün Ara (F2) =================================
    def focus_search(self) -> None:
        """Ctrl+F ve "Ürün Ara" düğmesi."""
        self.open_search()

    def open_search(self) -> None:
        if self._checkout_busy:
            return
        panel = self._search_panel_for_mode()
        panel.reset()
        self._open_overlay(KATMAN_ARA, panel, block_scans=False)
        self._search_feedback("idle")

    def _search_panel_for_mode(self) -> UrunAraPanel:
        dokunmatik = self.services.settings.ekran_klavyesi()
        if self._search_panel is None or self._search_panel.touch_keyboard != dokunmatik:
            if self._search_panel is not None:
                self._search_panel.deleteLater()
            self._search_panel = UrunAraPanel(
                self.services.products, touch_keyboard=dokunmatik,
                scanner=getattr(self.main_window, "scanner", None), parent=self,
            )
            self._search_panel.hide()
            self._search_panel.close_requested.connect(self.close_overlay)
            self._search_panel.product_chosen.connect(self._on_search_chosen)
        return self._search_panel

    def _on_search_chosen(self, product_id: int) -> None:
        """Sonuca dokunmak 1 adet ekler; panel açık kalır."""
        self._add_product(product_id, 1, None, 1)

    def _search_feedback(self, kind: str) -> None:
        if self._overlay_state != KATMAN_ARA:
            return
        if kind == "idle":
            metin = ""
        else:
            metin = self.banner.headline.text()
            if self.banner.detail.text():
                metin += f"  ·  {self.banner.detail.text()}"
        sepet = (f"Sepet: {self.cart.item_count} ürün · {format_tl(self.cart.total)}"
                 if not self.cart.is_empty else "Sepet boş")
        self._overlay.show_feedback(kind, f"{metin}    —    {sepet}" if metin else sepet)

    # ===================== Bekleyen sepetler (F1) ========================
    def _refresh_parked_count(self) -> None:
        try:
            adet = self.services.cart.parked_count()
        except Exception:
            log.exception("Bekleyen sepet sayısı okunamadı")
            return
        self.parked_button.setText(f"Bekleyenler ({adet})")

    def park_current(self) -> None:
        """Beklet: sepet "Müşteri n · ss:dd" adıyla saklanır, yeni sepet açılır."""
        if self._checkout_busy:
            return
        if self.cart.is_empty:
            sound.error()
            self.banner.show_error("Sepet boş.", "Bekletilecek ürün yok.")
            return
        self._autosave_timer.stop()
        try:
            draft_id = self.services.cart.park(self.cart)
        except DomainError as hata:
            sound.error()
            self.banner.show_error(hata.message)
            return
        etiket = next(
            (r["label"] for r in self.services.cart.parked_carts() if r["id"] == draft_id),
            "Bekleyen sepet",
        )
        self.cart = self.services.cart.new_cart()
        self._rebuild_rows()
        self._render()
        self._refresh_parked_count()
        sound.success()
        self.banner.show_success(
            f"⏸ Sepet bekletildi: {etiket}", "Yeni müşteriye başlayabilirsiniz."
        )

    def show_parked(self) -> None:
        if self._checkout_busy:
            return
        if self._parked_panel is None:
            self._parked_panel = BekleyenlerPanel(self)
            self._parked_panel.close_requested.connect(self.close_overlay)
            self._parked_panel.resume_requested.connect(self._on_resume_requested)
            self._parked_panel.swap_confirmed.connect(self._swap_with_parked)
            self._parked_panel.delete_confirmed.connect(self._delete_parked)
            self._parked_panel.hide()
        self._parked_panel.set_items(self.services.cart.parked_carts())
        self._open_overlay(KATMAN_BEKLEYENLER, self._parked_panel, block_scans=True)

    def _on_resume_requested(self, draft_id: int) -> None:
        if not self.cart.is_empty:
            ozet = f"{self.cart.item_count} ürün · {format_tl(self.cart.total)}"
            self._parked_panel.ask_swap(draft_id, ozet)
            return
        self._resume_parked(draft_id)

    def _resume_parked(self, draft_id: int) -> None:
        try:
            yeni, sorunlar = self.services.cart.resume_parked(draft_id)
        except DomainError as hata:
            self._parked_panel.set_items(self.services.cart.parked_carts())
            self.banner.show_error(hata.message)
            return
        if self.cart.draft_id is not None and self.cart.is_empty:
            self.services.cart.discard_draft(self.cart.draft_id)
        self._load_resumed(yeni, sorunlar)

    def _swap_with_parked(self, draft_id: int) -> None:
        """Eldeki sepet bekletilir, seçilen açılır (sınır aşılmaz)."""
        eski = self.cart
        self._autosave_timer.stop()
        try:
            yeni, sorunlar = self.services.cart.resume_parked(draft_id)
        except DomainError as hata:
            self.banner.show_error(hata.message)
            return
        try:
            self.services.cart.park(eski)
        except DomainError as hata:
            # Geri al: seçilen sepet yeniden bekler, eldeki sepet korunur.
            self.services.cart.save_draft(yeni, kind=TASLAK_BEKLEYEN)
            sound.error()
            self.banner.show_error(hata.message)
            return
        self._load_resumed(yeni, sorunlar)

    def _load_resumed(self, yeni, sorunlar) -> None:
        self.close_overlay()
        self.cart = yeni
        self._rebuild_rows()
        self._render()
        self._refresh_parked_count()
        if sorunlar:
            # Bekleyen sepet ASLA sessizce onarılmaz: satırlar işaretlidir.
            sound.error()
            self.banner.show_error(
                "Bekleyen sepette değişen ürün var.",
                "İşaretli satırları kontrol edin: güncel fiyatı uygulayın ya da "
                "ürünü çıkarın.",
            )
        else:
            sound.success()
            self.banner.show_success("▶ Bekleyen sepet açıldı.",
                                     f"{self.cart.item_count} ürün · "
                                     f"{format_tl(self.cart.total)}")

    def _delete_parked(self, draft_id: int) -> None:
        self.services.cart.discard_draft(draft_id)
        self._parked_panel.set_items(self.services.cart.parked_carts())
        self._refresh_parked_count()

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
            # deleteLater bir sonraki olay turunu bekler; o ana dek eski satır
            # ekranda kalmasın (satış sonrası "0 TL" ile eski sepet görünüyordu).
            satir.hide()
            satir.deleteLater()
        self._rows.clear()
        self._highlighted = None

    def _render(self) -> None:
        """Satırları ARTIMLI günceller.

        Yüzlerce okutmada tüm liste yeniden kurulmaz: var olan satır yerinde
        tazelenir, yalnızca yeni ürün için gereç oluşturulur.
        """
        mevcut = {line.product_id: line for line in self.cart.lines}
        self._refresh_issues()

        for product_id in list(self._rows):
            if product_id not in mevcut:
                satir = self._rows.pop(product_id)
                self.rows_layout.removeWidget(satir)
                satir.hide()
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
            sorun = self._issues.get(line.product_id)
            satir.set_issue(sorun.message if sorun else None)

        self.apply_prices_button.setVisible(
            any(s.kind == SORUN_FIYAT_DEGISTI for s in self._issues.values())
        )
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
        self.total_caption.setText(
            f"TOPLAM · {self.cart.item_count} ürün" if dolu else "TOPLAM"
        )
        self._publish_display()

    def _refresh_issues(self) -> None:
        """Sepeti güncel ürün kayıtlarıyla karşılaştırır (tek, hızlı sorgu)."""
        if self.cart.is_empty:
            self._issues = {}
            return
        try:
            sorunlar = self.services.cart.validate(self.cart)
        except Exception:
            log.exception("Sepet doğrulanamadı")
            return
        self._issues = {s.product_id: s for s in sorunlar}

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
        # Ürün Ara açıksa sonuç, panelin kendi satırında da görünür.
        self._search_feedback(kind)
