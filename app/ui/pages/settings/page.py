"""Ayarlar: bölümlere ayrılmış, sade Türkçeyle anlatılmış tercihler.

Bölümler (plan §5.5): Kasa, Görünüm, Ses, Barkod Okuyucu, İşletme, Stok,
Yedekleme, Donanım, Güvenlik. Henüz denetimi olmayan bölüm listede görünmez.
Hangi ayarın hangi bölümde olduğu ``keys.py`` tablosundadır; her denetim
``kontroller`` kaydına kendi anahtarıyla yazılır (test bunu doğrular).

* Her denetim değiştiği anda KENDİ anahtarını kaydeder (ayrı "Kaydet" yok).
* Az kullanılan ayarlar her bölümün "Gelişmiş" kutusundadır; her birinin
  sınırları vardır ve "Varsayılana dön" ile fabrika değerine döner.
* Ayarlar'a giriş, PIN kuruluysa yönetici PIN'i ister (``gate_action``).
* V1.1 testlerinin kullandığı denetim adları (``dup_spin``, ``mode_combo``…)
  sayfanın öznitelikleri olarak KORUNUR.
"""
from __future__ import annotations

import datetime
import logging
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core import schema as schema_mod
from app.core.clock import shift_days
from app.core.errors import DomainError
from app.core import gorunum as gorunum_mod
from app.core.pricing_math import YUVARLAMA_ADIMLARI
from app.core.tr import fmt_datetime
from app.services.security_service import ProtectedAction
from app.ui import metrics, sound, theme
from app.ui.dialogs.common_dialogs import ask_confirm, scanning_suspended, show_error, show_info
from app.ui.pages.base import Page
from app.ui.pages.settings.keys import BOLUMLER
from app.ui.widgets.common import PageHeader, make_label

log = logging.getLogger(__name__)

#: Bölüm düğmelerinin sütun genişliği.
BOLUM_SUTUNU = 190


class SettingsPage(Page):
    nav_title = "⚙️  Ayarlar"
    nav_key = "ayarlar"
    nav_group = "yonetim"
    #: Ayarlar'a girmek yönetici PIN'i ister (PIN kuruluysa).
    gate_action = ProtectedAction.AYARLAR

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self._loading = False
        #: Ayar anahtarı → denetim (bölüm tablosu testleri için).
        self.kontroller: dict[str, QWidget] = {}
        #: Bölüm kimliği → bölüm gereci.
        self.bolumler: dict[str, QWidget] = {}
        self._yukleyiciler: list[Callable[[], None]] = []

        self.header = PageHeader("⚙️ Ayarlar", "Uygulamanın çalışma tercihleri.")
        self.root.addWidget(self.header)
        self.root.addWidget(self._build_pin_hint())

        govde = QWidget()
        yatay = QHBoxLayout(govde)
        yatay.setContentsMargins(metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
                                 metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V)
        yatay.setSpacing(metrics.PAGE_SPACING)

        sutun = QWidget()
        sutun.setFixedWidth(BOLUM_SUTUNU)
        self._bolum_duzeni = QVBoxLayout(sutun)
        self._bolum_duzeni.setContentsMargins(0, 0, 0, 0)
        self._bolum_duzeni.setSpacing(6)
        yatay.addWidget(sutun)

        self.section_stack = QStackedWidget()
        yatay.addWidget(self.section_stack, 1)
        self.root.addWidget(govde, 1)

        self.section_buttons: dict[str, QPushButton] = {}
        self._bolum_grubu = QButtonGroup(self)
        self._bolum_grubu.setExclusive(True)

        kurucular = {
            "kasa": self._build_kasa,
            "gorunum": self._build_gorunum,
            "ses": self._build_ses,
            "barkod": self._build_barkod,
            "isletme": self._build_isletme,
            "stok": self._build_stok,
            "yedekleme": self._build_yedekleme,
            "guvenlik": self._build_guvenlik,
        }
        for kimlik, baslik in BOLUMLER:
            kurucu = kurucular.get(kimlik)
            if kurucu is None:
                continue                      # bu bölümün denetimleri sonraki taşlarda
            self._bolum_ekle(kimlik, baslik, kurucu())
        self._bolum_duzeni.addStretch(1)
        self.show_section("kasa")

    # ===================== İskelet =======================================
    def _bolum_ekle(self, kimlik: str, baslik: str, icerik: QWidget) -> None:
        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        kaydirma.setWidget(icerik)
        self.section_stack.addWidget(kaydirma)
        self.bolumler[kimlik] = icerik

        dugme = QPushButton(baslik)
        dugme.setObjectName("sectionNav")
        dugme.setCheckable(True)
        dugme.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
        dugme.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        dugme.clicked.connect(lambda _=False, k=kimlik: self.show_section(k))
        self._bolum_duzeni.addWidget(dugme)
        self._bolum_grubu.addButton(dugme)
        self.section_buttons[kimlik] = dugme

    def show_section(self, kimlik: str) -> None:
        icerik = self.bolumler.get(kimlik)
        if icerik is None:
            return
        self.section_stack.setCurrentWidget(icerik.parentWidget().parentWidget())
        self.section_buttons[kimlik].setChecked(True)

    def current_section(self) -> str:
        for kimlik, icerik in self.bolumler.items():
            if self.section_stack.currentWidget() is icerik.parentWidget().parentWidget():
                return kimlik
        return ""

    @staticmethod
    def _bolum_kutusu() -> tuple[QWidget, QVBoxLayout]:
        icerik = QWidget()
        duzen = QVBoxLayout(icerik)
        duzen.setContentsMargins(0, 0, 0, 0)
        duzen.setSpacing(metrics.PAGE_SPACING)
        return icerik, duzen

    def _hint(self, text: str) -> QLabel:
        etiket = QLabel(text)
        etiket.setWordWrap(True)
        etiket.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        return etiket

    def _kaydet(self, anahtar: str, deger, uygula: bool = True) -> None:
        if self._loading:
            return
        self.services.settings.set(anahtar, deger)
        if uygula:
            self.main_window.apply_settings()

    def _kayit(self, anahtar: str, gerec: QWidget, yukle: Callable[[], None]) -> None:
        self.kontroller[anahtar] = gerec
        self._yukleyiciler.append(yukle)

    def _spin(self, anahtar: str, enaz: int, encok: int, adim: int = 1,
              sonek: str = "") -> QSpinBox:
        kutucuk = QSpinBox()
        kutucuk.setRange(enaz, encok)
        kutucuk.setSingleStep(adim)
        if sonek:
            kutucuk.setSuffix(sonek)
        kutucuk.setProperty("scannerExempt", True)
        kutucuk.valueChanged.connect(lambda deger, k=anahtar: self._kaydet(k, deger))
        self._kayit(
            anahtar, kutucuk,
            lambda k=anahtar, g=kutucuk: g.setValue(self.services.settings.get_int(k)),
        )
        return kutucuk

    def _check(self, anahtar: str, metin: str) -> QCheckBox:
        kutu = QCheckBox(metin)
        kutu.stateChanged.connect(
            lambda _=0, k=anahtar, g=kutu: self._kaydet(k, int(g.isChecked()))
        )
        self._kayit(
            anahtar, kutu,
            lambda k=anahtar, g=kutu: g.setChecked(self.services.settings.get_bool(k)),
        )
        return kutu

    def _gelismis(self, duzen: QVBoxLayout) -> QVBoxLayout:
        """Bölümün "Gelişmiş" kutusu (sınırlı, varsayılana dönebilen ayarlar)."""
        kutu = QGroupBox("Gelişmiş")
        kutu.setObjectName("advancedGroup")
        ic = QVBoxLayout(kutu)
        ic.setSpacing(10)
        duzen.addWidget(kutu)
        return ic

    def _varsayilan_dugmesi(self, anahtar: str, gerec: QWidget) -> QPushButton:
        dugme = QPushButton("Varsayılana dön")
        dugme.setObjectName(f"varsayilan_{anahtar}")
        dugme.clicked.connect(lambda: self.reset_to_default(anahtar))
        return dugme

    def reset_to_default(self, anahtar: str) -> None:
        """Gelişmiş bir ayarı fabrika değerine döndürür ve ekranı tazeler."""
        varsayilan = schema_mod.DEFAULT_SETTINGS.get(anahtar)
        if varsayilan is None:
            return
        self.services.settings.set(anahtar, varsayilan)
        self.main_window.apply_settings()
        self.refresh()

    def _satir(self, etiket: str, *gerecler: QWidget) -> QHBoxLayout:
        satir = QHBoxLayout()
        satir.addWidget(make_label(etiket))
        for gerec in gerecler:
            satir.addWidget(gerec)
        satir.addStretch(1)
        return satir

    # ===================== PIN önerisi ===================================
    def _build_pin_hint(self) -> QWidget:
        """PIN kurulmamışsa NON-MODAL bir öneri şeridi (zorlamaz)."""
        self.pin_hint = QFrame()
        self.pin_hint.setObjectName("pinHint")
        self.pin_hint.setStyleSheet(
            f"#pinHint {{ background: {theme.INFO_LIGHT}; border-bottom: 1px solid {theme.BORDER}; }}"
        )
        duzen = QHBoxLayout(self.pin_hint)
        duzen.setContentsMargins(metrics.PAGE_MARGIN_H, 8, metrics.PAGE_MARGIN_H, 8)
        duzen.addWidget(make_label(
            "Yönetici PIN'i kurulmamış: Ayarlar, geri yükleme ve geçmiş işlemler "
            "herkese açık. İsterseniz bir PIN belirleyin.", wrap=True), 1)
        self.pin_hint_button = QPushButton("PIN belirle")
        self.pin_hint_button.clicked.connect(self._pin_kur)
        duzen.addWidget(self.pin_hint_button)
        self.pin_hint_dismiss = QPushButton("Şimdi değil")
        self.pin_hint_dismiss.clicked.connect(self._pin_onerisini_kapat)
        duzen.addWidget(self.pin_hint_dismiss)
        return self.pin_hint

    def _pin_onerisini_kapat(self) -> None:
        self.services.settings.set_many_quiet({"guvenlik_oneri_kapali": 1})
        self._guvenlik_tazele()

    # ===================== Kasa ==========================================
    def _build_kasa(self) -> QWidget:
        icerik, duzen = self._bolum_kutusu()

        kip = QGroupBox("Çalışma kipi")
        k = QVBoxLayout(kip)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Satış Önceliği (dokunmatik kasa)", "SALES_FIRST")
        self.mode_combo.addItem("Stok Takibi (ayrıntılı envanter)", "INVENTORY_TRACKED")
        self.mode_combo.currentIndexChanged.connect(self._save_mode)
        self._kayit("operating_mode", self.mode_combo, lambda: self._combo_yukle(
            self.mode_combo, self.services.settings.operating_mode()))
        k.addLayout(self._satir("Uygulama nasıl çalışsın", self.mode_combo))
        k.addWidget(self._hint(
            "Satış Önceliği: uygulama doğrudan satış ekranına açılır. Stok "
            "bilgisi eksik ya da eksi olsa bile satış hiç durmaz ve kasada "
            "stok uyarısı çıkmaz. Stok ekranları STOK menüsünde aynen durur."
        ))
        k.addWidget(self._hint(
            "Stok Takibi: uygulama ana ekrana açılır, satış sonrası stok "
            "uyarıları gösterilir. Bu ayar yalnızca ekranları ve uyarıları "
            "değiştirir; stok hareketleri, maliyetler ve geçmiş kayıtlar HER İKİ "
            "kipte de aynı şekilde tutulur."
        ))
        duzen.addWidget(kip)

        satis = QGroupBox("Satış ekranları")
        s = QVBoxLayout(satis)
        self.sale_mode_combo = QComboBox()
        self.sale_mode_combo.addItem("⚡ Hızlı Satış", "HIZLI")
        self.sale_mode_combo.addItem("🛒 Sepetli Satış", "SEPET")
        self.sale_mode_combo.currentIndexChanged.connect(
            lambda _=0: self._kaydet("default_sale_mode", self.sale_mode_combo.currentData())
        )
        self._kayit("default_sale_mode", self.sale_mode_combo, lambda: self._combo_yukle(
            self.sale_mode_combo, self.services.settings.default_sale_mode()))
        s.addLayout(self._satir("Stok Takibi kipinde açılan satış ekranı",
                                self.sale_mode_combo))
        self.startup_combo = QComboBox()
        for etiket, deger in (
            ("Otomatik (çalışma kipine göre)", "AUTO"),
            ("🛒 Sepetli Satış", "sepetli_satis"),
            ("⚡ Hızlı Satış", "hizli_satis"),
            ("🏠 Ana Ekran", "ana_ekran"),
        ):
            self.startup_combo.addItem(etiket, deger)
        self.startup_combo.currentIndexChanged.connect(
            lambda _=0: self._kaydet("startup_page", self.startup_combo.currentData(),
                                     uygula=False)
        )
        self._kayit("startup_page", self.startup_combo, lambda: self._combo_yukle(
            self.startup_combo, self.services.settings.startup_page()))
        s.addLayout(self._satir("Uygulama açılınca gelen ekran", self.startup_combo))
        self.card_check = self._check(
            "show_card_button", "KART düğmesini göster (NAKİT her zaman görünür)"
        )
        s.addWidget(self.card_check)
        self.quick_sale_check = self._check(
            "show_quick_sale", "Hızlı Satış ekranını göster (menü, Ana Ekran, F1)"
        )
        s.addWidget(self.quick_sale_check)
        self.change_check = self._check(
            "cash_change_calculator", "NAKİT'te para üstünü hesapla (alınan tutarı sor)"
        )
        s.addWidget(self.change_check)
        s.addWidget(self._hint(
            "Kapalıyken NAKİT tek dokunuşla satışı tamamlar. Açıkken alınan tutar "
            "seçilir ve para üstü ekranda büyük yazılır (tutar kaydedilmez)."
        ))
        self.pack_check = self._check(
            "pack_confirm_in_sale", "Koli barkodu okutulduğunda satıştan önce sor"
        )
        s.addWidget(self.pack_check)
        s.addWidget(self._hint(
            "Kapatırsanız 1 koli okutmak doğrudan kolideki adet kadar satar. "
            "Yanlışlıkla okutmaya karşı açık kalması önerilir."
        ))
        duzen.addWidget(satis)

        ileri = self._gelismis(duzen)
        self.hold_spin = self._spin("customer_display_hold_ms", 0, 30000, 500, " ms")
        ileri.addLayout(self._satir(
            "Satıştan sonra son tutar müşteri ekranında ne kadar kalsın",
            self.hold_spin, self._varsayilan_dugmesi("customer_display_hold_ms",
                                                     self.hold_spin),
        ))
        self.group_check = self._check(
            "smart_grouping_enabled", "Hızlı satışları olası müşteri gruplarına ayır"
        )
        ileri.addWidget(self.group_check)
        ileri.addWidget(self._hint(
            "Arka arkaya yapılan satışlar aynı müşteriye ait SAYILABİLİR. Bu bir "
            "tahmindir; kesin sepet bilgisi yalnızca Sepetli Satıştan gelir."
        ))
        duzen.addStretch(1)
        return icerik

    @staticmethod
    def _combo_yukle(kutu: QComboBox, deger) -> None:
        index = kutu.findData(deger)
        if index >= 0:
            kutu.setCurrentIndex(index)

    # ===================== Görünüm =======================================
    def _build_gorunum(self) -> QWidget:
        icerik, duzen = self._bolum_kutusu()
        kutu = QGroupBox("Giriş")
        k = QVBoxLayout(kutu)
        self.keyboard_check = self._check(
            "ekran_klavyesi", "Kasa'da arama için ekran klavyesini kullan"
        )
        k.addWidget(self.keyboard_check)
        k.addWidget(self._hint(
            "Klavyesiz dokunmatik kasada açık kalmalıdır. Klavyeli bir "
            "bilgisayarda kapatırsanız arama alanına klavyeyle yazılır; okutulan "
            "bir barkod yazdığınız metni bozmaz."
        ))
        duzen.addWidget(kutu)

        gorunus = QGroupBox("Tema ve yazı boyutu")
        g = QVBoxLayout(gorunus)
        self.theme_combo = QComboBox()
        for kimlik, ad in gorunum_mod.TEMALAR.items():
            self.theme_combo.addItem(ad, kimlik)
        self.font_scale_combo = QComboBox()
        for olcek in gorunum_mod.OLCEKLER:
            self.font_scale_combo.addItem(f"%{olcek}", olcek)
        self.density_combo = QComboBox()
        for kimlik, ad in gorunum_mod.YOGUNLUKLAR.items():
            self.density_combo.addItem(ad, kimlik)
        for anahtar, kutu_, adi, alan in (
            ("theme", self.theme_combo, "Tema", "tema"),
            ("font_scale", self.font_scale_combo, "Yazı boyutu", "olcek"),
            ("density", self.density_combo, "Yoğunluk", "yogunluk"),
        ):
            self._kayit(anahtar, kutu_, lambda k_=kutu_, a=alan: self._combo_yukle(
                k_, getattr(self.services.settings.gorunum(), a)))
            kutu_.currentIndexChanged.connect(lambda _i: self._gorunum_degisti())
            g.addLayout(self._satir(adi, kutu_))
        self.appearance_warning = self._hint("")
        g.addWidget(self.appearance_warning)
        self.appearance_button = QPushButton("Kaydet ve yeniden başlat")
        self.appearance_button.setObjectName("primary")
        self.appearance_button.clicked.connect(self.save_appearance_and_restart)
        g.addWidget(self.appearance_button)
        g.addWidget(self._hint(
            "Tema, yazı boyutu ve yoğunluk uygulama yeniden başlayınca geçerli olur. "
            "Açık sepet ve bekleyen sepetler kaybolmaz."
        ))
        duzen.addWidget(gorunus)
        duzen.addStretch(1)
        return icerik

    def appearance_choice(self) -> tuple[str, int, str]:
        return (self.theme_combo.currentData(), self.font_scale_combo.currentData(),
                self.density_combo.currentData())

    def _gorunum_degisti(self) -> None:
        if self._loading:
            return
        kayitli = self.services.settings.gorunum()
        secim = self.appearance_choice()
        self.appearance_button.setEnabled(
            secim != (kayitli.tema, kayitli.olcek, kayitli.yogunluk))
        self.appearance_warning.setText(
            "Bu yazı boyutu 1366×768 ve daha büyük ekranlar içindir; 1000×600 ekranda "
            "bazı sayfalar sığmayabilir." if secim[1] > 100 else "")
        self.appearance_warning.setVisible(secim[1] > 100)

    def save_appearance_and_restart(self) -> None:
        tema, olcek, yogunluk = self.appearance_choice()
        self.services.settings.set("theme", tema)
        self.services.settings.set("font_scale", olcek)
        self.services.settings.set("density", yogunluk)
        self.appearance_button.setEnabled(False)
        self.main_window.request_restart()

    # ===================== Ses ===========================================
    def _build_ses(self) -> QWidget:
        icerik, duzen = self._bolum_kutusu()
        kutu = QGroupBox("Sesler")
        k = QVBoxLayout(kutu)
        self.sound_check = self._check("sound_enabled", "Okutma ve satış seslerini çal")
        k.addWidget(self.sound_check)
        self.volume_combo = QComboBox()
        for seviye, ad in sound.SEVIYELER.items():
            self.volume_combo.addItem(ad, seviye)
        self.volume_combo.currentIndexChanged.connect(
            lambda _i: self._kaydet("sound_volume", self.volume_combo.currentData()))
        self._kayit("sound_volume", self.volume_combo, lambda: self._combo_yukle(
            self.volume_combo, self.services.settings.ses_ayarlari()[1]))
        k.addLayout(self._satir("Ses seviyesi", self.volume_combo))
        self.sound_type_checks = {}
        for tur, aciklama in sound.TURLER.items():
            kutucuk = self._check(f"sound_{tur}", aciklama)
            self.sound_type_checks[tur] = kutucuk
            dinle = QPushButton("Dinle")
            dinle.clicked.connect(lambda _=False, t=tur: sound.cal(t))
            k.addLayout(self._satir("", kutucuk, dinle))
        k.addWidget(self._hint(
            "Sesler kasiyerin ekrana bakmadan okutmanın başarılı olduğunu "
            "anlamasını sağlar. Kapatırsanız uyarılar yalnızca ekranda görünür."
        ))
        duzen.addWidget(kutu)
        duzen.addStretch(1)
        return icerik

    # ===================== Barkod Okuyucu ================================
    def _build_barkod(self) -> QWidget:
        icerik, duzen = self._bolum_kutusu()
        kutu = QGroupBox("Çift okuma koruması")
        k = QVBoxLayout(kutu)
        self.dup_spin = self._spin("duplicate_scan_ms", 0, 1000, 10, " ms")
        k.addLayout(self._satir("Aynı barkodun iki kez okunmasını engelle",
                                self.dup_spin))
        k.addWidget(self._hint(
            "Bazı okuyucular tek okutmada barkodu iki kez gönderir. Bu süre "
            "içindeki ikinci okuma sayılmaz. Aynı ürünü arka arkaya satmanızı "
            "engellemeyecek kadar kısa tutulmalıdır (önerilen: 120 ms)."
        ))
        duzen.addWidget(kutu)

        ileri = self._gelismis(duzen)
        for anahtar, etiket, ad in (
            ("barcode_trim_prefix", "Okuyucunun barkodun BAŞINA eklediği karakterler",
             "prefix_edit"),
            ("barcode_trim_suffix", "Okuyucunun barkodun SONUNA eklediği karakterler",
             "suffix_edit"),
        ):
            alan = QLineEdit()
            alan.setMaxLength(8)
            alan.setMaximumWidth(140)
            alan.setProperty("scannerExempt", True)
            alan.editingFinished.connect(
                lambda k=anahtar, a=alan: self._kaydet(k, a.text())
            )
            self._kayit(anahtar, alan,
                        lambda k=anahtar, a=alan: a.setText(self.services.settings.get(k, "")))
            setattr(self, ad, alan)
            ileri.addLayout(self._satir(etiket, alan, self._varsayilan_dugmesi(anahtar, alan)))
        ileri.addWidget(self._hint(
            "Yalnızca okuyucunuz barkoda fazladan karakter ekliyorsa doldurun; "
            "bu karakterler okutulan koddan silinir."
        ))
        self.burst_spin = self._spin("scanner_burst_key_ms", 15, 60, 1, " ms")
        ileri.addLayout(self._satir(
            "Tuş başına en fazla süre (bu kadar hızlı yazılan okutmadır)", self.burst_spin,
            self._varsayilan_dugmesi("scanner_burst_key_ms", self.burst_spin)))
        self.min_length_spin = self._spin("scanner_min_length", 4, 14, 1, " karakter")
        ileri.addLayout(self._satir(
            "Sonlandırıcı göndermeyen okuyucuda en kısa barkod", self.min_length_spin,
            self._varsayilan_dugmesi("scanner_min_length", self.min_length_spin)))
        ileri.addWidget(self._hint(
            "Varsayılanlar çoğu okuyucuda doğrudur. Barkod Testi ekranında okuyucunuzun "
            "tuş arası ve sonlandırıcısı görünür; yalnızca orada sorun görürseniz "
            "değiştirin."
        ))
        duzen.addStretch(1)
        return icerik

    # ===================== İşletme =======================================
    def _build_isletme(self) -> QWidget:
        icerik, duzen = self._bolum_kutusu()

        gun = QGroupBox("Gün başlangıcı")
        g = QVBoxLayout(gun)
        self.day_spin = QSpinBox()
        self.day_spin.setRange(0, 23)
        self.day_spin.setSuffix(":00")
        self.day_spin.setProperty("scannerExempt", True)
        self.day_button = QPushButton("Uygula")
        self.day_button.clicked.connect(self._save_business_day)
        self._yukleyiciler.append(lambda: self.day_spin.setValue(
            self.services.settings.current_business_day_start_hour()))
        g.addLayout(self._satir("Yeni gün saat kaçta başlasın", self.day_spin,
                                self.day_button))
        g.addWidget(self._hint(
            "Gece geç saate kadar açıksanız 04:00 seçebilirsiniz: gece yarısından "
            "sonraki satışlar bir önceki güne yazılır.\nBu değişiklik YARINDAN "
            "itibaren geçerli olur ve GEÇMİŞ RAPORLARI DEĞİŞTİRMEZ."
        ))
        duzen.addWidget(gun)

        vergi = QGroupBox("KDV")
        v = QVBoxLayout(vergi)
        self.vat_check = self._check("prices_include_vat", "Satış fiyatları KDV dahildir")
        v.addWidget(self.vat_check)
        self.vat_spin = self._spin("default_vat_rate", 0, 100, 1, " %")
        v.addLayout(self._satir("Yeni ürünlerde varsayılan KDV oranı", self.vat_spin))
        duzen.addWidget(vergi)
        duzen.addStretch(1)
        return icerik

    # ===================== Stok ==========================================
    def _build_stok(self) -> QWidget:
        icerik, duzen = self._bolum_kutusu()
        kutu = QGroupBox("Yeni ürün varsayılanları ve uyarılar")
        k = QVBoxLayout(kutu)
        for etiket, anahtar, alan, ipucu in (
            ("Yeni üründe az stok sınırı", "default_min_stock", "min", None),
            ("Yeni üründe kritik stok sınırı", "default_critical_stock", "critical", None),
            ("Kaç gündür satılmayan ürün 'yavaş' sayılsın", "slow_moving_days", "slow",
             None),
            ("Bu adetten büyük sayım farkında uyar", "large_count_diff_threshold", "diff",
             "Küçük farklar için soru sorulmaz; onay yorgunluğu yaratır."),
        ):
            kutucuk = self._spin(anahtar, 0, 100000)
            setattr(self, f"{alan}_spin", kutucuk)
            k.addLayout(self._satir(etiket, kutucuk))
            if ipucu:
                k.addWidget(self._hint(ipucu))
        k.addWidget(self._hint(
            "Bu sınırlar YENİ tanımlanan ürünler için varsayılandır; mevcut "
            "ürünlerin sınırları ürün ekranından değiştirilir."
        ))
        duzen.addWidget(kutu)

        fiyat = QGroupBox("Fiyat")
        f = QVBoxLayout(fiyat)
        self.rounding_combo = QComboBox()
        for adim, etiket in YUVARLAMA_ADIMLARI.items():
            self.rounding_combo.addItem(etiket, adim)
        self.rounding_combo.currentIndexChanged.connect(
            lambda _=0: self._kaydet("price_rounding", self.rounding_combo.currentData(),
                                     uygula=False)
        )
        self._kayit("price_rounding", self.rounding_combo, lambda: self._combo_yukle(
            self.rounding_combo, self.services.settings.price_rounding()))
        f.addLayout(self._satir("Toplu fiyat değişikliğinde yuvarla", self.rounding_combo))
        self.cost_alert_spin = self._spin("cost_change_alert_percent", 1, 100, 1, " %")
        f.addLayout(self._satir("Mal kabulde alış fiyatı şu kadar değişirse fiyatı "
                                "incelemeye al", self.cost_alert_spin))
        f.addWidget(self._hint(
            "Artışlar yukarı, düşüşler aşağı yuvarlanır: %5 artış hiçbir ürünü "
            "ucuzlatmaz. \"Fiyatı şu yap\" yazdığınız tutarı aynen kullanır."
        ))
        duzen.addWidget(fiyat)
        duzen.addStretch(1)
        return icerik

    # ===================== Yedekleme =====================================
    def _build_yedekleme(self) -> QWidget:
        icerik, duzen = self._bolum_kutusu()
        kutu = QGroupBox("Yedekler")
        k = QVBoxLayout(kutu)
        k.setSpacing(10)

        self.backup_status = make_label("", "cardHint", wrap=True)
        k.addWidget(self.backup_status)

        self.interval_spin = self._spin("auto_backup_interval_minutes", 5, 1440, 5,
                                        " dakika")
        self.retention_spin = self._spin("auto_backup_retention", 1, 100)
        k.addLayout(self._satir("Kaç dakikada bir otomatik yedek", self.interval_spin))
        k.addLayout(self._satir("Kaç otomatik yedek saklansın", self.retention_spin))
        k.addWidget(self._hint(
            "Elle aldığınız yedekler bu sayıdan etkilenmez; asla kendiliğinden silinmez."
        ))

        dugmeler = QHBoxLayout()
        self.backup_now_button = QPushButton("Şimdi Yedek Al")
        self.backup_now_button.setObjectName("primary")
        self.backup_now_button.clicked.connect(self._backup_now)
        dugmeler.addWidget(self.backup_now_button)
        self.restore_button = QPushButton("Yedekten Geri Yükle")
        self.restore_button.clicked.connect(self._restore)
        dugmeler.addWidget(self.restore_button)
        self.folder_button = QPushButton("Yedek Klasörünü Seç")
        self.folder_button.clicked.connect(self._choose_folder)
        dugmeler.addWidget(self.folder_button)
        dugmeler.addStretch(1)
        k.addLayout(dugmeler)
        self.kontroller["manual_backup_dir"] = self.folder_button

        k.addWidget(make_label("Mevcut yedekler", "sectionTitle"))
        self.backup_list = QListWidget()
        self.backup_list.setMaximumHeight(200)
        k.addWidget(self.backup_list)
        duzen.addWidget(kutu)
        duzen.addStretch(1)
        return icerik

    # ===================== Güvenlik ======================================
    def _build_guvenlik(self) -> QWidget:
        icerik, duzen = self._bolum_kutusu()
        kutu = QGroupBox("Yönetici PIN'i")
        k = QVBoxLayout(kutu)
        self.pin_status = make_label("", "sectionTitle", wrap=True)
        k.addWidget(self.pin_status)
        dugmeler = QHBoxLayout()
        self.pin_set_button = QPushButton("PIN belirle")
        self.pin_set_button.setObjectName("primary")
        self.pin_set_button.clicked.connect(self._pin_kur)
        dugmeler.addWidget(self.pin_set_button)
        self.pin_remove_button = QPushButton("PIN korumasını kaldır")
        self.pin_remove_button.clicked.connect(self._pin_kaldir)
        dugmeler.addWidget(self.pin_remove_button)
        dugmeler.addStretch(1)
        k.addLayout(dugmeler)
        k.addWidget(self._hint(
            "PIN kuruluysa Ayarlar, yedekten geri yükleme, ürün kaldırma, geçmiş "
            "satış ya da stok girişini geri alma ve stok yeniden hesaplama PIN "
            "ister. Satış, aynı günün son satışını geri alma, fiyat görme ve arama "
            "ASLA PIN istemez. Doğru PIN 5 dakika geçerlidir; Kasa ekranına "
            "dönünce kilit yeniden kapanır."
        ))
        k.addWidget(self._hint(
            "Bu koruma dükkânda yanlışlıkla yapılan değişiklikleri önlemek içindir; "
            "bilgisayara ya da veri dosyasına erişebilen birine karşı bir güvenlik "
            "önlemi DEĞİLDİR. Yedekler PIN'in özetini içerir: eski bir yedeği geri "
            "yüklemek o yedeğin PIN durumunu geri getirir. PIN'i ve kurtarma "
            "kodunu unutursanız uygulamayı --yonetici-pin-sifirla ile başlatın."
        ))
        duzen.addWidget(kutu)
        duzen.addStretch(1)
        return icerik

    def _guvenlik_tazele(self) -> None:
        guv = self.services.security
        var = guv.has_pin()
        self.pin_status.setText(
            "PIN kurulu. Hassas işlemler korunuyor." if var
            else "PIN kurulmamış. Hassas işlemler herkese açık."
        )
        self.pin_set_button.setText("PIN'i değiştir" if var else "PIN belirle")
        self.pin_remove_button.setVisible(var)
        kapali = self.services.settings.get_bool("guvenlik_oneri_kapali", False)
        self.pin_hint.setVisible(not var and not kapali)

    def _pin_kur(self) -> None:
        guard = getattr(self.main_window, "guard", None)
        if guard is not None and guard.setup_or_change_pin(self):
            self.main_window.refresh_pin_notice()
        self._guvenlik_tazele()

    def _pin_kaldir(self) -> None:
        if not self.guard_require(ProtectedAction.PIN_DEGISTIR):
            return
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, "PIN koruması kaldırılsın mı?",
                "Ayarlar ve hassas işlemler PIN istemeden açılır.",
                accept_text="Evet, kaldır", danger=True,
            )
        if not onay:
            return
        self.services.security.remove_pin()
        self._guvenlik_tazele()

    # ===================== Yükleme =======================================
    def refresh(self) -> None:
        self._loading = True
        try:
            for yukle in self._yukleyiciler:
                yukle()
            self._fill_backups()
            self._guvenlik_tazele()
        finally:
            self._loading = False
        self._gorunum_degisti()

    def _save_mode(self) -> None:
        if self._loading:
            return
        self.services.settings.set("operating_mode", self.mode_combo.currentData())
        self.main_window.apply_settings()
        with scanning_suspended(self.main_window.router):
            show_info(
                self, "Çalışma kipi",
                "Kip değiştirildi. Ekranların tamamen güncellenmesi için "
                "uygulamayı kapatıp açabilirsiniz.",
            )

    def _save_business_day(self) -> None:
        """Kural GEÇERLİLİK TARİHLİDİR; geçmiş raporlar değişmez."""
        yarin = shift_days(self.services.settings.calendar().today(), 1)
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self,
                f"Yeni gün {self.day_spin.value():02d}:00'da başlasın mı?",
                f"Bu kural {yarin} tarihinden itibaren geçerli olur.\n"
                "Geçmiş günlerin raporları DEĞİŞMEZ.",
                accept_text="Evet, uygula",
            )
        if not onay:
            return
        self.services.settings.set_business_day_start_hour(self.day_spin.value(), yarin)
        with scanning_suspended(self.main_window.router):
            show_info(self, "Gün başlangıcı", f"{yarin} tarihinden itibaren geçerli.")

    # ===================== Yedekleme işlemleri ===========================
    def _fill_backups(self) -> None:
        self.backup_list.clear()
        try:
            durum = self.services.backup.status()
            yedekler = self.services.backup.list_backups()
        except Exception:
            log.exception("Yedekler listelenemedi")
            return

        son = durum["son_yedek_utc"]
        self.backup_status.setText(
            (f"Son yedek: {fmt_datetime(datetime.datetime.fromtimestamp(son))}"
             if son else "Henüz yedek alınmadı.")
            + f"\nOtomatik: {durum['otomatik_klasor']}"
            + f"\nElle: {durum['elle_klasor']}"
        )
        for yedek in yedekler[:50]:
            boyut = yedek.size_bytes / 1024 / 1024
            oge = QListWidgetItem(f"{yedek.display_name}  ·  {boyut:.1f} MB")
            oge.setData(32, str(yedek.path))
            self.backup_list.addItem(oge)

    def _hata(self, hata: DomainError) -> None:
        """Teknik ayrıntı kullanıcıya değil, log'a."""
        if hata.detail:
            log.warning("%s | %s", hata.message, hata.detail)
        show_error(self, hata.message)

    def _backup_now(self) -> None:
        try:
            yol = self.services.backup.create_manual()
        except DomainError as hata:
            self._hata(hata)
            return
        sound.success()
        with scanning_suspended(self.main_window.router):
            show_info(self, "Yedek alındı", f"Yedek kaydedildi:\n{yol}")
        self._fill_backups()

    def _restore(self) -> None:
        if not self.guard_require(ProtectedAction.GERI_YUKLE):
            return
        oge = self.backup_list.currentItem()
        yol = oge.data(32) if oge is not None else None
        if yol is None:
            with scanning_suspended(self.main_window.router):
                yol, _ = QFileDialog.getOpenFileName(
                    self, "Yedek seçin",
                    str(self.services.backup.manual_dir()),
                    "Yedek dosyaları (*.db)",
                )
            if not yol:
                return

        try:
            bilgi = self.services.backup.inspect(yol)
        except DomainError as hata:
            self._hata(hata)
            return

        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, "Bu yedek geri yüklensin mi?",
                f"{bilgi.display_name}\n"
                f"{bilgi.product_count} ürün · {bilgi.sale_count} satış\n\n"
                "Şu anki veriler bu yedekle DEĞİŞTİRİLİR. İşlemden önce mevcut "
                "verilerin bir güvenlik kopyası otomatik alınır.",
                accept_text="Evet, geri yükle", danger=True,
            )
        if not onay:
            return

        try:
            guvenlik = self.services.backup.restore(yol)
        except DomainError as hata:
            self._hata(hata)
            return

        with scanning_suspended(self.main_window.router):
            show_info(
                self, "Geri yüklendi",
                "Yedek geri yüklendi.\n\n"
                f"Önceki verilerinizin kopyası:\n{guvenlik}\n\n"
                "Uygulama şimdi yeniden başlatılacak.",
            )
        self.main_window.request_restart()

    def _choose_folder(self) -> None:
        with scanning_suspended(self.main_window.router):
            klasor = QFileDialog.getExistingDirectory(
                self, "Yedek klasörü seçin", str(self.services.backup.manual_dir())
            )
        if not klasor:
            return
        self.services.settings.set("manual_backup_dir", klasor)
        self._fill_backups()
