"""Ana pencere: gezinme, kısayollar ve merkezi okuyucu bağlantısı.

Gezinme SIĞ ve TAHMİN EDİLEBİLİRDİR: üç başlıklı sol menü (KASA / STOK /
YÖNETİM) ve bir ``QStackedWidget``. Menü de ana ekran da AYNI sayfalara gider;
menü çubuğu ve iç içe menü YOKTUR. Grup başlıkları açılıp kapanabilir (durum
sessizce saklanır); gösterilen sayfanın grubu daima açıktır. Menü düğmeleri
DAİMA kurulur, yalnızca görünürlükleri değişir.

Girişte PIN isteyen sayfa (``gate_action``) için kapı, mevcut sayfa
KAPATILMADAN önce denetlenir; ret hâlinde hiçbir şey değişmez.

Okuyucu tek bir yerden bağlanır:
    ScannerService (olay süzgeci) -> ScanRouter -> etkin sayfa
"""
from __future__ import annotations

import base64
import logging
from collections.abc import Mapping

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.core.money import format_tl
from app.scanner.scan_router import ScanRouter
from app.scanner.scanner_service import ScannerService
from app.services.scan_guard import ScanGuard
from app.ui import metrics, shortcuts, sound, theme
from app.ui.widgets.common import make_label

log = logging.getLogger(__name__)

class TembelSayfalar(Mapping):
    """Sayfalar İLK gösterildiklerinde kurulur (açılış süresi ve bellek).

    Menü düğmeleri sınıf özniteliklerinden (``nav_key``, ``nav_title``,
    ``nav_group``) kurulur; sayfanın kendisi ``pages[key]`` ile ilk kez
    istendiğinde oluşturulur. ``hazir()`` yalnızca kurulmuş sayfaları verir
    (ayar uygulama, kapanış hazırlığı gibi işler kurulmamış sayfayı
    gereksiz yere kurmasın).
    """

    def __init__(self, kurucu, siniflar: dict[str, type]) -> None:
        self._kurucu = kurucu
        self._siniflar = siniflar
        self._hazir: dict[str, object] = {}

    def __getitem__(self, anahtar: str):
        if anahtar not in self._hazir:
            sinif = self._siniflar[anahtar]          # KeyError: bilinmeyen sayfa
            self._hazir[anahtar] = self._kurucu(sinif)
        return self._hazir[anahtar]

    def __iter__(self):
        return iter(self._siniflar)

    def __len__(self) -> int:
        return len(self._siniflar)

    def __contains__(self, anahtar) -> bool:
        return anahtar in self._siniflar

    def hazir(self) -> dict[str, object]:
        return dict(self._hazir)

    def sinif(self, anahtar: str) -> type:
        return self._siniflar[anahtar]


NAV_GROUPS = (
    ("kasa", "KASA"),
    ("stok", "STOK"),
    ("yonetim", "YÖNETİM"),
)


class MainWindow(QMainWindow):
    def __init__(self, services, restart_callback=None) -> None:
        super().__init__()
        self.services = services
        self.restart_callback = restart_callback
        #: Geri yükleme sonrası yeniden başlatma istendi: sayfalar artık eski
        #: veriye ait hiçbir şeyi (ör. sepet taslağı) diske yazmaz.
        self.restarting = False
        self._status_timer = None
        self._status_message = ""

        self.setWindowTitle(f"{config.APP_NAME} {config.APP_VERSION}")
        self.setMinimumSize(metrics.MIN_WINDOW_WIDTH, metrics.MIN_WINDOW_HEIGHT)

        # --- Merkezi okuyucu ---
        self.scan_guard = ScanGuard(services.settings.duplicate_scan_ms())
        self.router = ScanRouter(guard=self.scan_guard)
        self.router.on_blocked = self._on_scan_blocked
        self.router.on_duplicate = self._on_scan_duplicate
        self.scanner = ScannerService(self)
        self.scanner.scanned.connect(self.router.dispatch)

        from app.ui.manager_guard import ManagerGuard

        #: PIN gerektiren eylemlerin tek kapısı (PIN kurulu değilse sormaz).
        self.guard = ManagerGuard(services, self)

        self._build_ui()
        self._build_pages()
        self._build_shortcuts()
        self._restore_geometry()

        self.scanner.start()
        self.guard.start()
        self.go_to(self._landing_key())

    # ===================== Kurulum =======================================
    def _build_ui(self) -> None:
        govde = QWidget()
        yatay = QHBoxLayout(govde)
        yatay.setContentsMargins(0, 0, 0, 0)
        yatay.setSpacing(0)

        yatay.addWidget(self._build_nav())

        from app.ui.widgets.pin_notice import PinResetNotice

        icerik = QWidget()
        dikey = QVBoxLayout(icerik)
        dikey.setContentsMargins(0, 0, 0, 0)
        dikey.setSpacing(0)
        self.pin_notice = PinResetNotice()
        self.pin_notice.setup_requested.connect(self._pin_setup_from_notice)
        self.pin_notice.acknowledge_requested.connect(self._acknowledge_pin_notice)
        dikey.addWidget(self.pin_notice)
        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")
        dikey.addWidget(self.stack, 1)
        yatay.addWidget(icerik, 1)

        self.setCentralWidget(govde)

        self.setStatusBar(QStatusBar())
        self.status_label = QLabel("")
        self.statusBar().addWidget(self.status_label, 1)
        self.today_label = QLabel("")
        self.statusBar().addPermanentWidget(self.today_label)

    def _build_nav(self) -> QWidget:
        rail = QWidget()
        rail.setObjectName("navRail")
        rail.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        rail.setFixedWidth(metrics.NAV_WIDTH)

        duzen = QVBoxLayout(rail)
        duzen.setContentsMargins(0, 0, 0, 0)
        duzen.setSpacing(0)

        duzen.addWidget(make_label(config.APP_NAME, "navTitle"))
        duzen.addWidget(make_label("Barkodlu stok ve satış", "navSubtitle", wrap=True))

        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        kaydirma.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        icerik = QWidget()
        icerik.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        icerik.setStyleSheet(f"background: {theme.NAV_BG};")
        self.nav_layout = QVBoxLayout(icerik)
        self.nav_layout.setContentsMargins(0, 0, 0, 8)
        self.nav_layout.setSpacing(0)
        kaydirma.setWidget(icerik)
        duzen.addWidget(kaydirma, 1)

        self.nav_footer = make_label(
            f"Sürüm {config.APP_VERSION}\n{shortcuts.FOOTER_HINT}",
            "navFooter", wrap=True,
        )
        duzen.addWidget(self.nav_footer)

        self.nav_buttons: dict[str, QPushButton] = {}
        self.nav_headers: dict[str, QPushButton] = {}
        self.nav_page_group: dict[str, str] = {}
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        return rail

    def _update_footer(self) -> None:
        try:
            satis_once = self.services.settings.is_sales_first()
        except Exception:
            satis_once = False
        self.nav_footer.setText(
            f"Sürüm {config.APP_VERSION}\n{shortcuts.footer_hint(satis_once)}"
        )

    def _build_pages(self) -> None:
        from app.ui.pages.barcode_test import BarcodeTestPage
        from app.ui.pages.cart_sale import CartSalePage
        from app.ui.pages.categories import CategoriesPage
        from app.ui.pages.dashboard import DashboardPage
        from app.ui.pages.history import HistoryPage
        from app.ui.pages.home import HomePage
        from app.ui.pages.import_page import ImportPage
        from app.ui.pages.price_check import PriceCheckPage
        from app.ui.pages.prices import PricesPage
        from app.ui.pages.products import ProductsPage
        from app.ui.pages.quick_sale import QuickSalePage
        from app.ui.pages.quick_stock import QuickStockPage
        from app.ui.pages.settings import SettingsPage
        from app.ui.pages.stock_count import StockCountPage
        from app.ui.pages.stock_entry import StockEntryPage
        from app.ui.pages.stock_status import StockStatusPage
        from app.ui.pages.suppliers import SuppliersPage

        # Menüdeki sıra bu listedir (grup içinde).
        sinifler = [
            HomePage,
            # KASA — Sepetli Satış BİRİNCİL iş akışıdır; menüde de önce gelir.
            CartSalePage, QuickSalePage, PriceCheckPage,
            # STOK
            QuickStockPage, StockEntryPage, StockCountPage, StockStatusPage,
            # YÖNETİM
            DashboardPage, ProductsPage, CategoriesPage, PricesPage, ImportPage,
            SuppliersPage, HistoryPage, SettingsPage, BarcodeTestPage,
        ]

        self.pages = TembelSayfalar(
            self._build_page, {sinif.nav_key: sinif for sinif in sinifler}
        )
        self._current_key: str | None = None
        #: Bir önceki sayfa (Fiyat Gör'ün dönüş hedefi için).
        self.previous_key: str | None = None
        gruplar: dict[str, list] = {anahtar: [] for anahtar, _ in NAV_GROUPS}
        for sinif in sinifler:
            if sinif.nav_group in gruplar:
                gruplar[sinif.nav_group].append(sinif)

        # Ana ekran her zaman en üstte, grupsuz.
        self._add_nav_button("ana_ekran", "🏠  Ana Ekran")
        for anahtar, baslik in NAV_GROUPS:
            if not gruplar[anahtar]:
                continue
            baslik_dugmesi = QPushButton(baslik)
            baslik_dugmesi.setObjectName("navGroupHeader")
            baslik_dugmesi.setCursor(Qt.CursorShape.PointingHandCursor)
            baslik_dugmesi.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            baslik_dugmesi.clicked.connect(
                lambda _=False, g=anahtar: self.toggle_nav_group(g)
            )
            self.nav_layout.addWidget(baslik_dugmesi)
            self.nav_headers[anahtar] = baslik_dugmesi
            for sayfa in gruplar[anahtar]:
                self._add_nav_button(sayfa.nav_key, sayfa.nav_title)
                self.nav_page_group[sayfa.nav_key] = anahtar
        self.nav_layout.addStretch(1)
        self.apply_nav_visibility()
        self._update_footer()

    def _build_page(self, sinif):
        """Sayfayı ilk istendiğinde kurar, yığına ve yönlendiriciye ekler."""
        sayfa = sinif(self.services, self)
        self.stack.addWidget(sayfa)
        if sayfa.accepts_scans:
            self.router.register(sayfa.nav_key, sayfa.handle_scan)
        return sayfa

    def _add_nav_button(self, key: str, title: str) -> None:
        dugme = QPushButton(title)
        dugme.setObjectName("navButton")
        dugme.setCheckable(True)
        dugme.setCursor(Qt.CursorShape.PointingHandCursor)
        dugme.clicked.connect(lambda _=False, k=key: self.go_to(k))
        self.nav_layout.addWidget(dugme)
        self.nav_buttons[key] = dugme
        self.nav_group.addButton(dugme)

    def _build_shortcuts(self) -> None:
        """Kısayollar TEK yerde tanımlıdır (``app/ui/shortcuts.py``).

        Yalnızca F-tuşları ve Ctrl'lü kısayollar kullanılır: çıplak harf
        kısayolu olsaydı, okutulan barkodun içindeki harf ekranı değiştirirdi.
        """
        eylemler = {
            "yenile": self.data_changed,
            "geri_al": self._undo_last,
            "tamamla": self._complete_current,
            "yeni_musteri": self._mark_new_customer,
            "geri": self._go_back,
            "ara": self._focus_search,
        }
        for kisayol in shortcuts.SHORTCUTS:
            qs = QShortcut(QKeySequence(kisayol.key), self)
            if kisayol.action.startswith("goto:"):
                hedef = kisayol.action.split(":", 1)[1]
                qs.activated.connect(lambda k=hedef: self.go_to(k))
            elif kisayol.action in eylemler:
                qs.activated.connect(eylemler[kisayol.action])

    # ===================== Gezinme =======================================
    def _landing_key(self) -> str:
        """Uygulama açılınca hangi ekran gelsin?

        SALES_FIRST: doğrudan Sepetli Satış — dükkân sahibi uygulama açılır
        açılmaz satmaya başlayabilir.
        INVENTORY_TRACKED: V1 davranışı korunur (Ana Ekran).
        """
        try:
            secim = self.services.settings.startup_page()
            if secim != "AUTO":
                # Gizlenmiş Hızlı Satış açılış ekranı olamaz: birincil kasaya düş.
                return "sepetli_satis" if secim in self._hidden_pages() else secim
            if self.services.settings.is_sales_first():
                return "sepetli_satis"
            if self.services.settings.default_sale_mode() == "SEPET":
                return "sepetli_satis"
        except Exception:
            log.exception("Acilis sayfasi belirlenemedi")
        return "ana_ekran"

    # ===================== Menü görünürlüğü ============================
    def _collapsed_groups(self) -> set[str]:
        try:
            return self.services.settings.nav_collapsed_groups()
        except Exception:
            log.exception("Menü durumu okunamadı")
            return set()

    def apply_nav_visibility(self) -> None:
        """Grup açık/kapalı durumu ve gizlenebilir sayfalar.

        Gösterilen sayfanın grubu her zaman açıktır (kullanıcı nerede
        olduğunu görür); bu, kayıtlı durumu DEĞİŞTİRMEZ.
        """
        kapali = self._collapsed_groups()
        etkin_grup = self.nav_page_group.get(self._current_key or "")
        gizli = self._hidden_pages()
        for grup, baslik_dugmesi in self.nav_headers.items():
            acik = grup not in kapali or grup == etkin_grup
            ad = dict(NAV_GROUPS)[grup]
            baslik_dugmesi.setText(f"{'▾' if acik else '▸'}  {ad}")
            baslik_dugmesi.setProperty("acik", "evet" if acik else "hayir")
            for anahtar, sayfa_grubu in self.nav_page_group.items():
                if sayfa_grubu == grup:
                    self.nav_buttons[anahtar].setVisible(acik and anahtar not in gizli)

    def _hidden_pages(self) -> set[str]:
        try:
            return set() if self.services.settings.show_quick_sale() else {"hizli_satis"}
        except Exception:
            return set()

    def toggle_nav_group(self, group: str) -> None:
        kapali = set(self._collapsed_groups())
        if group in kapali:
            kapali.discard(group)
        else:
            kapali.add(group)
        try:
            self.services.settings.set_nav_collapsed_groups(kapali)
        except Exception:
            log.exception("Menü durumu yazılamadı")
        self.apply_nav_visibility()

    def _check_nav(self, key: str | None) -> None:
        dugme = self.nav_buttons.get(key or "")
        if dugme is not None:
            dugme.setChecked(True)
        elif self.nav_group.checkedButton() is not None:
            self.nav_group.setExclusive(False)
            self.nav_group.checkedButton().setChecked(False)
            self.nav_group.setExclusive(True)

    def go_to(self, key: str) -> None:
        if key not in self.pages:
            return
        sayfa = self.pages[key]
        if self._current_key == key:
            sayfa.on_activated()
            return
        if key in self._hidden_pages():
            # Gizlenmiş sayfa (ör. Hızlı Satış kapalı): kısayol sessizce
            # boşa gitmez, ne olduğu söylenir.
            self._check_nav(self._current_key)
            self.show_status(
                "Hızlı Satış kapalı. Açmak için: Ayarlar > Kasa.", 5
            )
            return

        # PIN isteyen sayfa: kapı, mevcut sayfa KAPATILMADAN ÖNCE denetlenir
        # (PIN penceresi okutma askısında açılır). Ret: hiçbir şey değişmez.
        if getattr(sayfa, "gate_action", None) and not self.guard.require(
            sayfa.gate_action, self
        ):
            self._check_nav(self._current_key)
            return

        if self._current_key is not None:
            try:
                self.pages[self._current_key].on_deactivated()
            except Exception:
                log.exception("Sayfa kapatılırken hata: %s", self._current_key)

        self.stack.setCurrentWidget(sayfa)
        self.previous_key = self._current_key
        self._current_key = key
        self._check_nav(key)
        self.apply_nav_visibility()

        # Kasa sayfası gösterilince yönetici kilidi kapanır.
        if getattr(sayfa, "kasa_sayfasi", False):
            self.guard.lock()
        self.refresh_pin_notice()

        # Okutmalar yalnızca ETKİN sayfaya gider.
        self.router.set_context(key if sayfa.accepts_scans else None)
        self.clear_status()
        try:
            sayfa.on_activated()
        except Exception:
            log.exception("Sayfa açılırken hata: %s", key)

    # ===================== PIN sıfırlama bildirimi =======================
    def refresh_pin_notice(self) -> None:
        sayfa = self.current_page()
        try:
            self.pin_notice.update_state(
                self.services.security, bool(getattr(sayfa, "kasa_sayfasi", False))
            )
        except Exception:
            log.exception("PIN bildirimi güncellenemedi")

    def _pin_setup_from_notice(self) -> None:
        self.guard.setup_or_change_pin(self)
        self.refresh_pin_notice()

    def _acknowledge_pin_notice(self) -> None:
        if self.services.security.acknowledge_reset_notice():
            self.show_status("PIN sıfırlama bildirimi onaylandı.", 4)
        self.refresh_pin_notice()

    def current_page(self):
        if self._current_key is None:
            return None
        return self.pages[self._current_key]

    def _go_back(self) -> None:
        """Esc: önce açık katmanı kapatır; yoksa ana ekrana döner."""
        sayfa = self.current_page()
        if sayfa is not None and hasattr(sayfa, "close_overlay") and sayfa.close_overlay():
            return
        if sayfa is not None and hasattr(sayfa, "handle_back") and sayfa.handle_back():
            return
        if self._current_key != "ana_ekran":
            self.go_to("ana_ekran")

    # ===================== Kısayol eylemleri =============================
    def _undo_last(self) -> None:
        sayfa = self.current_page()
        if sayfa is not None and hasattr(sayfa, "undo_last"):
            sayfa.undo_last()

    def _complete_current(self) -> None:
        """F10 — yalnızca AÇIKÇA katılan sayfaları tamamlar.

        Varsayılan KAPALIDIR: ileride ``complete()`` metodu olan yeni bir sayfa
        eklendiğinde bu kısayolu KAZARA devralmasın. Sepetli Satış bu bayrağı
        açmaz; bir satış yalnızca açık bir ödeme eylemiyle (NAKİT / KART)
        tamamlanır.
        """
        sayfa = self.current_page()
        if sayfa is None:
            return
        if not getattr(sayfa, "completes_with_shortcut", False):
            return
        if hasattr(sayfa, "complete"):
            sayfa.complete()

    def _mark_new_customer(self) -> None:
        if not self.services.settings.smart_grouping_enabled():
            self.show_status(
                "Müşteri ayırma kapalı. Ayarlar'dan açabilirsiniz.", 5
            )
            return
        self.services.grouping.mark_new_customer()
        self.show_status("Yeni müşteri işaretlendi.", 3)

    def _focus_search(self) -> None:
        sayfa = self.current_page()
        if sayfa is not None and hasattr(sayfa, "focus_search"):
            sayfa.focus_search()

    # ===================== Okutma geri bildirimi =========================
    def _on_scan_blocked(self, event) -> None:
        """Karar penceresi açıkken okutma geldi: ANINDA duyulur ret."""
        sound.blocked()
        self.show_status(
            "Önce ekrandaki soruyu yanıtlayın. Okutulan barkod işlenmedi.", 4
        )
        pencere = self.window().focusWidget()
        sahip = pencere.window() if pencere is not None else None
        if sahip is not None and hasattr(sahip, "notify_blocked"):
            sahip.notify_blocked()

    def _on_scan_duplicate(self, event) -> None:
        """Donanım çift-tetiklemesi: sessizce düşürülmez, kısaca bildirilir."""
        self.show_status("Aynı barkod çok hızlı iki kez okundu; biri sayıldı.", 3)

    # ===================== Durum çubuğu ==================================
    def show_status(self, message: str, seconds: int = 4) -> None:
        """Durum çubuğu iletisi; ``seconds`` sonra (hâlâ aynıysa) silinir.

        Tek, pencereye bağlı (parent'lı) bir zamanlayıcı kullanılır: pencere
        kapanınca zamanlayıcı da yok olur, bağlamsız bir lambda silinmiş bir
        gerece dokunmaz; art arda iletiler zamanlayıcı biriktirmez.
        """
        self.status_label.setText(message)
        if self._status_timer is None:
            from PySide6.QtCore import QTimer

            self._status_timer = QTimer(self)
            self._status_timer.setSingleShot(True)
            self._status_timer.timeout.connect(self._expire_status)
        self._status_message = message
        if seconds > 0:
            self._status_timer.start(seconds * 1000)
        else:
            self._status_timer.stop()

    def _expire_status(self) -> None:
        if self.status_label.text() == self._status_message:
            self.status_label.setText("")

    def clear_status(self) -> None:
        self.status_label.setText("")

    def refresh_today(self) -> None:
        try:
            ozet = self.services.analytics.today()
            self.today_label.setText(
                f"Bugün: {format_tl(ozet.revenue)} · {ozet.item_count} ürün"
            )
        except Exception:
            log.exception("Bugün özeti okunamadı")

    # ===================== Veri değişimi =================================
    def data_changed(self) -> None:
        """Yalnızca GÖRÜNEN sayfayı tazeler; hepsini yenilemek gereksizdir."""
        self.refresh_today()
        sayfa = self.current_page()
        if sayfa is not None:
            try:
                sayfa.refresh()
            except Exception:
                log.exception("Sayfa tazelenemedi: %s", self._current_key)

    def apply_settings(self) -> None:
        """Ayar değişikliklerini çalışan uygulamaya uygular."""
        acik, seviye, turler = self.services.settings.ses_ayarlari()
        sound.yapilandir(acik, seviye, turler, config.data_dir() / "sounds")
        self.scan_guard.set_window(self.services.settings.duplicate_scan_ms())
        self.scanner.set_burst_key_ms(
            self.services.settings.get_int("scanner_burst_key_ms", 30))
        self.scanner.set_min_length(self.services.settings.get_int("scanner_min_length", 6))
        self.apply_nav_visibility()
        self._update_footer()
        for sayfa in self.pages.hazir().values():
            if hasattr(sayfa, "apply_settings"):
                try:
                    sayfa.apply_settings()
                except Exception:
                    log.exception("Sayfa ayarları uygulanamadı: %s", sayfa.nav_key)

    def request_restart(self) -> None:
        self.restarting = True
        if self.restart_callback is not None:
            self.restart_callback()

    # ===================== Pencere konumu ================================
    def _restore_geometry(self) -> None:
        """Pencere boyutu ayarlarda (veritabanında) tutulur; QSettings yok."""
        try:
            kodlu = self.services.settings.get("window_geometry", "")
            if kodlu:
                self.restoreGeometry(base64.b64decode(kodlu))
            else:
                self.resize(metrics.DEFAULT_WINDOW_WIDTH, metrics.DEFAULT_WINDOW_HEIGHT)
            if self.services.settings.get_bool("window_maximized", False):
                self.showMaximized()
        except Exception:
            log.exception("Pencere konumu geri yüklenemedi")
            self.resize(metrics.DEFAULT_WINDOW_WIDTH, metrics.DEFAULT_WINDOW_HEIGHT)

    def _save_geometry(self) -> None:
        try:
            self.services.settings.set_many_quiet(
                {
                    "window_geometry": base64.b64encode(
                        bytes(self.saveGeometry())
                    ).decode("ascii"),
                    "window_maximized": 1 if self.isMaximized() else 0,
                }
            )
        except Exception:
            log.exception("Pencere konumu kaydedilemedi")

    def closeEvent(self, event) -> None:  # noqa: N802
        # Sayfalar bekleyen işlerini (ör. sepet taslağı) diske yazar.
        for anahtar, sayfa in self.pages.hazir().items():
            try:
                sayfa.on_app_closing()
            except Exception:
                log.exception("Sayfa kapanış hazırlığında hata: %s", anahtar)
        self._save_geometry()
        self.scanner.stop()
        self.guard.stop()
        super().closeEvent(event)
