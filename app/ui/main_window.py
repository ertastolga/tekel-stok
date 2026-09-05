"""Ana pencere: gezinme, kısayollar ve merkezi okuyucu bağlantısı.

Gezinme SIĞ ve TAHMİN EDİLEBİLİRDİR: iki başlıklı sol menü (Günlük İşlemler /
Yönetim) ve bir ``QStackedWidget``. Menü de ana ekran da AYNI sayfalara gider;
menü çubuğu ve iç içe menü YOKTUR.

Okuyucu tek bir yerden bağlanır:
    ScannerService (olay süzgeci) -> ScanRouter -> etkin sayfa
"""
from __future__ import annotations

import base64
import logging

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

NAV_GROUPS = (
    ("gunluk", "GÜNLÜK İŞLEMLER"),
    ("yonetim", "YÖNETİM"),
)


class MainWindow(QMainWindow):
    def __init__(self, services, restart_callback=None) -> None:
        super().__init__()
        self.services = services
        self.restart_callback = restart_callback

        self.setWindowTitle(f"{config.APP_NAME} {config.APP_VERSION}")
        self.setMinimumSize(metrics.MIN_WINDOW_WIDTH, metrics.MIN_WINDOW_HEIGHT)

        # --- Merkezi okuyucu ---
        self.scan_guard = ScanGuard(services.settings.duplicate_scan_ms())
        self.router = ScanRouter(guard=self.scan_guard)
        self.router.on_blocked = self._on_scan_blocked
        self.router.on_duplicate = self._on_scan_duplicate
        self.scanner = ScannerService(self)
        self.scanner.scanned.connect(self.router.dispatch)

        self._build_ui()
        self._build_pages()
        self._build_shortcuts()
        self._restore_geometry()

        self.scanner.start()
        self.go_to("ana_ekran")

    # ===================== Kurulum =======================================
    def _build_ui(self) -> None:
        govde = QWidget()
        yatay = QHBoxLayout(govde)
        yatay.setContentsMargins(0, 0, 0, 0)
        yatay.setSpacing(0)

        yatay.addWidget(self._build_nav())

        self.stack = QStackedWidget()
        self.stack.setObjectName("contentArea")
        yatay.addWidget(self.stack, 1)

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
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        return rail

    def _build_pages(self) -> None:
        from app.ui.pages.barcode_test import BarcodeTestPage
        from app.ui.pages.cart_sale import CartSalePage
        from app.ui.pages.dashboard import DashboardPage
        from app.ui.pages.history import HistoryPage
        from app.ui.pages.home import HomePage
        from app.ui.pages.products import ProductsPage
        from app.ui.pages.quick_sale import QuickSalePage
        from app.ui.pages.settings_page import SettingsPage
        from app.ui.pages.stock_count import StockCountPage
        from app.ui.pages.stock_entry import StockEntryPage
        from app.ui.pages.stock_status import StockStatusPage
        from app.ui.pages.suppliers import SuppliersPage

        sinifler = [
            HomePage,
            QuickSalePage, CartSalePage, StockEntryPage, StockCountPage,
            DashboardPage, ProductsPage, StockStatusPage, SuppliersPage,
            HistoryPage, SettingsPage, BarcodeTestPage,
        ]

        self.pages: dict[str, object] = {}
        self._current_key: str | None = None
        gruplar: dict[str, list] = {anahtar: [] for anahtar, _ in NAV_GROUPS}

        for sinif in sinifler:
            sayfa = sinif(self.services, self)
            self.pages[sayfa.nav_key] = sayfa
            self.stack.addWidget(sayfa)
            if sayfa.accepts_scans:
                self.router.register(sayfa.nav_key, sayfa.handle_scan)
            if sayfa.nav_group in gruplar:
                gruplar[sayfa.nav_group].append(sayfa)

        # Ana ekran her zaman en üstte, grupsuz.
        self._add_nav_button("ana_ekran", "🏠  Ana Ekran")
        for anahtar, baslik in NAV_GROUPS:
            if not gruplar[anahtar]:
                continue
            self.nav_layout.addWidget(make_label(baslik, "navGroup"))
            for sayfa in gruplar[anahtar]:
                self._add_nav_button(sayfa.nav_key, sayfa.nav_title)
        self.nav_layout.addStretch(1)

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
    def go_to(self, key: str) -> None:
        if key not in self.pages:
            return
        sayfa = self.pages[key]
        if self._current_key == key:
            sayfa.on_activated()
            return

        if self._current_key is not None:
            try:
                self.pages[self._current_key].on_deactivated()
            except Exception:
                log.exception("Sayfa kapatılırken hata: %s", self._current_key)

        self.stack.setCurrentWidget(sayfa)
        self._current_key = key
        dugme = self.nav_buttons.get(key)
        if dugme is not None:
            dugme.setChecked(True)
        elif self.nav_group.checkedButton() is not None:
            self.nav_group.setExclusive(False)
            self.nav_group.checkedButton().setChecked(False)
            self.nav_group.setExclusive(True)

        # Okutmalar yalnızca ETKİN sayfaya gider.
        self.router.set_context(key if sayfa.accepts_scans else None)
        self.clear_status()
        try:
            sayfa.on_activated()
        except Exception:
            log.exception("Sayfa açılırken hata: %s", key)

    def current_page(self):
        return self.pages.get(self._current_key or "")

    def _go_back(self) -> None:
        """Esc: ana ekrana dön. Beklenmedik bir yere düşürmez."""
        if self._current_key != "ana_ekran":
            self.go_to("ana_ekran")

    # ===================== Kısayol eylemleri =============================
    def _undo_last(self) -> None:
        sayfa = self.current_page()
        if sayfa is not None and hasattr(sayfa, "undo_last"):
            sayfa.undo_last()

    def _complete_current(self) -> None:
        sayfa = self.current_page()
        if sayfa is not None and hasattr(sayfa, "complete"):
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
        self.status_label.setText(message)
        if seconds > 0:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(
                seconds * 1000,
                lambda: self.status_label.setText("")
                if self.status_label.text() == message else None,
            )

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
        sound.set_enabled(self.services.settings.sound_enabled())
        self.scan_guard.set_window(self.services.settings.duplicate_scan_ms())

    def request_restart(self) -> None:
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
        self._save_geometry()
        self.scanner.stop()
        super().closeEvent(event)
