"""Görsel tema: renkler, yazı tipleri ve stil sayfası.

Tasarım ilkeleri: yüksek kontrast, büyük düğmeler, sade tipografi, animasyon
yok. Kullanıcı teknik değildir; ekran ilk bakışta anlaşılmalıdır.

Renk ASLA tek başına anlam taşımaz: her durum renkle BİRLİKTE metin (ve
gerektiğinde simge) ile gösterilir. Kırmızı yalnızca tehlike, hata ve geri
alınamaz işlemler içindir.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontMetrics, QPalette

from app.ui import metrics

# --- Renk jetonları -------------------------------------------------------
@dataclass(frozen=True)
class ThemeTokens:
    """Bir temanın TÜM renkleri. Stil sayfası ve palet yalnızca buradan okur.

    Koyu tema (M9a) yalnızca yeni bir ``ThemeTokens`` örneğidir; hiçbir
    sayfa kodu değişmez. Sayfalar renklere ``theme.DANGER`` gibi MODÜL
    ÜZERİNDEN erişir (adla içe aktarma yasaktır — bkz. test_tema.py): böylece
    açılışta ``set_tokens`` ile seçilen tema her yerde geçerli olur.
    """

    ad: str
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    text_muted: str
    #: Renkli zemin üzerindeki yazı (birincil/tehlike düğmeleri, menü).
    on_accent: str
    primary: str
    primary_dark: str
    primary_light: str
    primary_light_hover: str
    primary_pressed: str
    stock: str
    stock_dark: str
    stock_light: str
    count: str
    count_dark: str
    count_light: str
    cart: str
    cart_dark: str
    cart_light: str
    cart_pressed: str
    nav_bg: str
    nav_text: str
    nav_active: str
    nav_group: str
    nav_hover: str
    danger: str
    danger_light: str
    danger_border: str
    danger_pressed_light: str
    warning: str
    warning_light: str
    critical: str
    critical_light: str
    info: str
    info_light: str
    disabled_bg: str
    disabled_fg: str
    disabled_border: str
    step_hover: str
    step_pressed: str
    chart: tuple[str, ...]


#: V1.1'in renkleri, birebir. (Görsel değişiklik YOK.)
LIGHT = ThemeTokens(
    ad="LIGHT",
    bg="#EEF1F5",
    surface="#FFFFFF",
    surface_alt="#F6F8FB",
    border="#D3DBE5",
    text="#16202B",
    text_muted="#65727F",
    on_accent="#FFFFFF",
    # Satış — yeşil
    primary="#1B7F4C",
    primary_dark="#14663C",
    primary_light="#E4F3EA",
    primary_light_hover="#D8EDE1",
    primary_pressed="#0F5330",
    # Stok girişi — turuncu
    stock="#B4650E",
    stock_dark="#8F4F09",
    stock_light="#FCEFDD",
    # Sayım — mor
    count="#6941C6",
    count_dark="#53309E",
    count_light="#EFE9FB",
    # Sepetli satış — mavi
    cart="#1F6FB2",
    cart_dark="#17588C",
    cart_light="#E6F0F9",
    cart_pressed="#11476F",
    nav_bg="#1E2A38",
    nav_text="#C8D3E0",
    nav_active="#2E90FA",
    nav_group="#8A99AB",
    nav_hover="rgba(255,255,255,0.08)",
    danger="#C62B2B",
    danger_light="#FBE7E7",
    danger_border="#A32222",
    danger_pressed_light="#F6D4D4",
    warning="#B77400",
    warning_light="#FDF2DC",
    critical="#D2691E",
    critical_light="#FBE6D6",
    info="#1F6FB2",
    info_light="#E6F0F9",
    # Devre dışı durum — TÜM düğme türleri için tek kaynak.
    disabled_bg="#E9EDF2",
    disabled_fg="#9AA6B3",
    disabled_border="#DCE2EA",
    step_hover="#E7ECF3",
    step_pressed="#DCE3EC",
    chart=(
        "#2E90FA", "#1B7F4C", "#B4650E", "#7A5AF8", "#C62B2B",
        "#0E9384", "#B54708", "#4E5BA6", "#CA8504", "#155EEF",
    ),
)

#: Etkin tema. Açılışta (pencereler kurulmadan ÖNCE) ``set_tokens`` ile seçilir.
_aktif: ThemeTokens = LIGHT

# Modül düzeyi adlar: ``theme.DANGER`` gibi erişimler için. ``set_tokens``
# bunları yeniden bağlar; değerler daima etkin temadan gelir.
BG = SURFACE = SURFACE_ALT = BORDER = TEXT = TEXT_MUTED = ""
ON_ACCENT = ""
PRIMARY = PRIMARY_DARK = PRIMARY_LIGHT = ""
STOCK = STOCK_DARK = STOCK_LIGHT = ""
COUNT = COUNT_DARK = COUNT_LIGHT = ""
CART = CART_DARK = CART_LIGHT = ""
NAV_BG = NAV_TEXT = NAV_ACTIVE = NAV_GROUP = ""
DANGER = DANGER_LIGHT = WARNING = WARNING_LIGHT = INFO = INFO_LIGHT = ""
DISABLED_BG = DISABLED_FG = DISABLED_BORDER = ""
#: Stok durumu renkleri. Anahtarlar ``models.StockState`` değerleridir.
#: 4 = "Henüz Sayılmadı" NÖTRDÜR: bilinmeyen stok, az stok DEĞİLDİR ve
#: kullanıcıyı boş yere telaşlandırmamalıdır.
LEVEL_COLORS: dict[int, tuple[str, str]] = {}
CHART_COLORS: list[str] = []


def set_tokens(tokens: ThemeTokens) -> None:
    """Etkin temayı seçer ve modül düzeyi renk adlarını yeniden bağlar.

    Yeniden başlatmayla uygulanır (M9a): pencereler kurulduktan sonra çağrı,
    zaten çizilmiş gereçleri DEĞİŞTİRMEZ.
    """
    global _aktif, BG, SURFACE, SURFACE_ALT, BORDER, TEXT, TEXT_MUTED, ON_ACCENT
    global PRIMARY, PRIMARY_DARK, PRIMARY_LIGHT, STOCK, STOCK_DARK, STOCK_LIGHT
    global COUNT, COUNT_DARK, COUNT_LIGHT, CART, CART_DARK, CART_LIGHT
    global NAV_BG, NAV_TEXT, NAV_ACTIVE, NAV_GROUP
    global DANGER, DANGER_LIGHT, WARNING, WARNING_LIGHT, INFO, INFO_LIGHT
    global DISABLED_BG, DISABLED_FG, DISABLED_BORDER, LEVEL_COLORS, CHART_COLORS
    t = tokens
    _aktif = t
    BG, SURFACE, SURFACE_ALT, BORDER = t.bg, t.surface, t.surface_alt, t.border
    TEXT, TEXT_MUTED, ON_ACCENT = t.text, t.text_muted, t.on_accent
    PRIMARY, PRIMARY_DARK, PRIMARY_LIGHT = t.primary, t.primary_dark, t.primary_light
    STOCK, STOCK_DARK, STOCK_LIGHT = t.stock, t.stock_dark, t.stock_light
    COUNT, COUNT_DARK, COUNT_LIGHT = t.count, t.count_dark, t.count_light
    CART, CART_DARK, CART_LIGHT = t.cart, t.cart_dark, t.cart_light
    NAV_BG, NAV_TEXT, NAV_ACTIVE, NAV_GROUP = t.nav_bg, t.nav_text, t.nav_active, t.nav_group
    DANGER, DANGER_LIGHT = t.danger, t.danger_light
    WARNING, WARNING_LIGHT, INFO, INFO_LIGHT = (
        t.warning, t.warning_light, t.info, t.info_light
    )
    DISABLED_BG, DISABLED_FG, DISABLED_BORDER = (
        t.disabled_bg, t.disabled_fg, t.disabled_border
    )
    LEVEL_COLORS = {
        0: (t.primary, t.primary_light),        # Normal
        1: (t.warning, t.warning_light),        # Düşük
        2: (t.critical, t.critical_light),      # Kritik
        3: (t.danger, t.danger_light),          # Stok Kontrolü Gerekli
        4: (t.text_muted, t.surface_alt),       # Henüz Sayılmadı — nötr
    }
    CHART_COLORS = list(t.chart)


def tokens() -> ThemeTokens:
    """Etkin tema jetonları."""
    return _aktif


set_tokens(LIGHT)

FONT_FAMILY = "Segoe UI"


def base_font(size: float | None = None, bold: bool = False) -> QFont:
    """Uygulama yazı tipi. Boyut verilmezse taban boyut ÇAĞRI ANINDA okunur
    (yazı ölçeği ayarı açılışta ``metrics``'i değiştirebilir)."""
    font = QFont(FONT_FAMILY)
    font.setPointSizeF(float(metrics.FONT_BASE_PT if size is None else size))
    font.setBold(bold)
    return font


def text_height(size: float, lines: int = 1) -> int:
    """Metnin kapladığı yükseklik (mantıksal piksel).

    ``QApplication`` kurulduktan SONRA çağrılmalıdır: ölçüm o anki yazı tipi ve
    ekran ölçeklemesiyle yapılır, bu yüzden %125/%150'de kendiliğinden büyür.
    Sabit piksel kullanılmaz — aksi hâlde ölçekleme arttığında metin kutunun
    dışına taşar.
    """
    olcum = QFontMetrics(base_font(size))
    satir = max(olcum.height(), olcum.lineSpacing())
    return satir * lines


def measured_rules() -> str:
    """QFontMetrics ile ÖLÇÜLEN yükseklik kuralları.

    QSS'teki ``min-height``, koddaki ``setMinimumHeight`` çağrısını SESSİZCE
    ezer. Bu yüzden ölçülen değerler doğrudan stil sayfasına yazılır.
    """
    return f"""
QPushButton#actionCard {{
    min-height: {metrics.ACTION_CARD_MIN_HEIGHT}px;
}}
QPushButton#actionCardPrimary {{
    min-height: {metrics.ACTION_CARD_PRIMARY_MIN_HEIGHT}px;
}}
QLineEdit#barcodeInput {{
    min-height: {max(metrics.BARCODE_INPUT_HEIGHT,
                     text_height(metrics.FONT_BARCODE_PT) + 18)}px;
}}
"""


def build_palette(t: ThemeTokens | None = None) -> QPalette:
    """Uygulamanın TEK renk kaynağı.

    Windows koyu temadayken Qt'nin varsayılan paleti de koyu gelir; stil
    sayfası yalnızca belirli bileşenleri boyadığı için pencereler yarı koyu
    yarı açık görünür ve koyu zemin üzerinde koyu yazı OKUNMAZ hâle gelir.
    Bu palet uygulamayı işletim sistemi temasından tamamen bağımsız kılar.
    """
    t = t or _aktif
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(t.bg))
    p.setColor(QPalette.ColorRole.WindowText, QColor(t.text))
    p.setColor(QPalette.ColorRole.Base, QColor(t.surface))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(t.surface_alt))
    p.setColor(QPalette.ColorRole.Text, QColor(t.text))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(t.text_muted))
    p.setColor(QPalette.ColorRole.Button, QColor(t.surface))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(t.text))
    p.setColor(QPalette.ColorRole.BrightText, QColor(t.danger))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(t.surface))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(t.text))
    p.setColor(QPalette.ColorRole.Highlight, QColor(t.nav_active))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor(t.on_accent))
    p.setColor(QPalette.ColorRole.Link, QColor(t.info))
    p.setColor(QPalette.ColorRole.Mid, QColor(t.border))
    p.setColor(QPalette.ColorRole.Dark, QColor(t.text_muted))

    for role, color in (
        (QPalette.ColorRole.WindowText, t.disabled_fg),
        (QPalette.ColorRole.Text, t.disabled_fg),
        (QPalette.ColorRole.ButtonText, t.disabled_fg),
        (QPalette.ColorRole.Button, t.disabled_bg),
        (QPalette.ColorRole.Base, t.disabled_bg),
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))
    return p


def light_palette() -> QPalette:
    """Geriye uyumluluk: açık temanın paleti."""
    return build_palette(LIGHT)


def build_stylesheet(t: ThemeTokens | None = None) -> str:
    """Stil sayfası — renkler jetonlardan, ölçüler ``metrics``'ten ÇAĞRI ANINDA."""
    t = t or _aktif
    m = metrics
    return f"""
* {{
    font-family: "{FONT_FAMILY}";
    font-size: {m.FONT_BASE_PT}pt;
}}
QWidget {{ color: {t.text}; }}

/* Dialoglar: koyu OS temasında arka planı zorlamazsak koyu gelir. */
QDialog, QMessageBox {{ background: {t.bg}; }}

/* ---- Sol menü ---- */
#navRail {{ background: {t.nav_bg}; }}
#navTitle {{
    color: {t.on_accent}; font-size: {m.FONT_SECTION_PT}pt; font-weight: 600;
    padding: 16px 14px 2px 14px;
}}
#navSubtitle {{ color: {t.nav_group}; padding: 0 14px 12px 14px; }}
#navGroup {{
    color: {t.nav_group}; font-size: {m.FONT_SMALL_PT}pt; font-weight: 600;
    padding: 14px 14px 4px 14px;
}}
QPushButton#navGroupHeader {{
    background: transparent; color: {t.nav_group}; border: none;
    text-align: left; font-size: {m.FONT_SMALL_PT}pt; font-weight: 600;
    padding: 12px 14px 4px 14px; min-height: 28px;
}}
QPushButton#navGroupHeader:hover {{ color: {t.on_accent}; }}
#navButton {{
    background: transparent; color: {t.nav_text}; border: none;
    text-align: left; padding: 11px 14px; border-radius: 6px;
    margin: 1px 8px;
}}
#navButton:hover {{ background: {t.nav_hover}; color: {t.on_accent}; }}
#navButton:checked {{ background: {t.nav_active}; color: {t.on_accent}; font-weight: 600; }}
#navFooter {{ color: {t.nav_group}; font-size: {m.FONT_SMALL_PT}pt; padding: 10px 14px; }}

/* ---- Sayfa ---- */
#contentArea {{ background: {t.bg}; }}
#pageHeader {{ background: {t.surface}; border-bottom: 1px solid {t.border}; }}
#pageTitle {{ font-size: {m.FONT_PAGE_TITLE_PT}pt; font-weight: 600; }}
#pageSubtitle {{ color: {t.text_muted}; }}
#sectionTitle {{ font-size: {m.FONT_SECTION_PT}pt; font-weight: 600; }}

/* ---- Kartlar ---- */
#card {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px; }}
#cardTitle {{ color: {t.text_muted}; font-size: {m.FONT_SMALL_PT}pt; }}
#cardValue {{ font-size: {m.FONT_CARD_VALUE_PT}pt; font-weight: 600; }}
#cardHint {{ color: {t.text_muted}; font-size: {m.FONT_SMALL_PT}pt; }}

/* ---- Ana ekran eylem kartları ---- */
QPushButton#actionCard, QPushButton#actionCardPrimary {{
    background: {t.surface}; border: 2px solid {t.border}; border-radius: 12px;
    text-align: left; padding: 16px 18px;
}}
QPushButton#actionCard:hover, QPushButton#actionCardPrimary:hover {{
    border-color: {t.nav_active}; background: {t.surface_alt};
}}
QPushButton#actionCard:focus, QPushButton#actionCardPrimary:focus {{
    border: 3px solid {t.nav_active};
}}
QPushButton#actionCardPrimary {{
    background: {t.primary_light}; border-color: {t.primary};
}}
QPushButton#actionCardPrimary:hover {{ background: {t.primary_light_hover}; }}

/* ---- Düğmeler ---- */
QPushButton {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border};
    border-radius: 8px; padding: 9px 16px; min-height: {m.BUTTON_HEIGHT - 20}px;
}}
QPushButton:hover {{ background: {t.surface_alt}; }}
QPushButton:disabled {{
    background: {t.disabled_bg}; color: {t.disabled_fg}; border-color: {t.disabled_border};
}}
QPushButton#primary {{
    background: {t.primary}; color: {t.on_accent}; border-color: {t.primary_dark}; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {t.primary_dark}; }}
QPushButton#stockAction {{
    background: {t.stock}; color: {t.on_accent}; border-color: {t.stock_dark}; font-weight: 600;
}}
QPushButton#stockAction:hover {{ background: {t.stock_dark}; }}
QPushButton#danger {{
    background: {t.danger}; color: {t.on_accent}; border-color: {t.danger_border}; font-weight: 600;
}}
QPushButton#bigAction {{
    min-height: {m.BIG_BUTTON_HEIGHT - 20}px;
    font-size: {m.FONT_SECTION_PT}pt; font-weight: 600;
}}
QPushButton#primary:disabled, QPushButton#stockAction:disabled,
QPushButton#danger:disabled, QPushButton#bigAction:disabled {{
    background: {t.disabled_bg}; color: {t.disabled_fg}; border-color: {t.disabled_border};
}}

/* ---- Giriş alanları ---- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 8px;
    padding: 8px 12px; min-height: {m.INPUT_HEIGHT - 20}px;
    selection-background-color: {t.nav_active}; selection-color: {t.on_accent};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border: 2px solid {t.nav_active}; padding: 7px 11px;
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    background: {t.disabled_bg}; color: {t.disabled_fg};
}}
QLineEdit#barcodeInput {{
    font-size: {m.FONT_BARCODE_PT}pt; font-weight: 600;
    border: 2px solid {t.border};
}}
QLineEdit#barcodeInput[mode="sale"]:focus {{ border: 3px solid {t.primary}; }}
QLineEdit#barcodeInput[mode="stock"]:focus {{ border: 3px solid {t.stock}; }}
QLineEdit#barcodeInput[mode="count"]:focus {{ border: 3px solid {t.count}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}

/* ---- Tablolar ---- */
QTableWidget, QTableView {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px;
    gridline-color: {t.border}; selection-background-color: {t.primary_light};
    selection-color: {t.text};
}}
QHeaderView::section {{
    background: {t.surface_alt}; color: {t.text_muted}; border: none;
    border-bottom: 1px solid {t.border}; padding: 10px 8px; font-weight: 600;
}}
QTableWidget::item {{ padding: 6px 8px; }}
/* QTableWidget'a stil verilince yerleşik onay kutusu çizimi bozulur. */
QTableWidget::indicator, QTableView::indicator {{
    width: 20px; height: 20px; border: 1px solid {t.border};
    border-radius: 4px; background: {t.surface};
}}
QTableWidget::indicator:checked, QTableView::indicator:checked {{
    background: {t.primary}; border-color: {t.primary_dark};
}}

/* ---- Sonuç şeridi ---- */
#resultBanner {{ border-radius: 10px; border: 2px solid {t.border}; background: {t.surface}; }}
#resultHeadline {{ font-size: {m.FONT_SECTION_PT}pt; font-weight: 600; }}
#resultDetail {{ color: {t.text_muted}; }}
#saleFlash {{ border-radius: 10px; border: 2px solid {t.primary}; background: {t.primary_light}; }}
#flashName {{ font-size: {m.FONT_FLASH_NAME_PT}pt; font-weight: 600; color: {t.primary_dark}; }}
#flashLine {{ font-size: {m.FONT_FLASH_LINE_PT}pt; color: {t.text}; }}

/* ---- Dokunmatik POS ---- */
/* Satış onayı ASLA kırmızı değildir; kırmızı yalnızca yıkıcı eylemlerde. */
QPushButton#cashButton {{
    background: {t.primary}; color: {t.on_accent}; border: 2px solid {t.primary_dark};
    border-radius: 10px; font-size: {m.FONT_PAYMENT_PT}pt; font-weight: 600;
    min-height: {m.PAYMENT_BUTTON_HEIGHT - 24}px; padding: 10px 16px;
}}
QPushButton#cashButton:hover  {{ background: {t.primary_dark}; }}
QPushButton#cashButton:pressed {{ background: {t.primary_pressed}; }}
QPushButton#cardButton {{
    background: {t.cart}; color: {t.on_accent}; border: 2px solid {t.cart_dark};
    border-radius: 10px; font-size: {m.FONT_PAYMENT_PT}pt; font-weight: 600;
    min-height: {m.PAYMENT_BUTTON_HEIGHT - 24}px; padding: 10px 16px;
}}
QPushButton#cardButton:hover  {{ background: {t.cart_dark}; }}
QPushButton#cardButton:pressed {{ background: {t.cart_pressed}; }}
QPushButton#cashButton:disabled, QPushButton#cardButton:disabled {{
    background: {t.disabled_bg}; color: {t.disabled_fg}; border-color: {t.disabled_border};
}}

/* Sepet satırı ve içindeki büyük adet düğmeleri */
#cartRow {{
    background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px;
}}
#cartRow[vurgu="evet"] {{ border: 2px solid {t.primary}; background: {t.primary_light}; }}
#cartName  {{ font-size: {m.FONT_CART_NAME_PT}pt; font-weight: 600; }}
#cartPrice {{ font-size: {m.FONT_CART_PRICE_PT}pt; color: {t.text_muted}; }}
#cartQty   {{ font-size: {m.FONT_CART_QTY_PT}pt; font-weight: 600; }}
#cartTotal {{ font-size: {m.FONT_CART_NAME_PT}pt; font-weight: 600; }}
QPushButton#touchStep {{
    background: {t.surface_alt}; border: 2px solid {t.border}; border-radius: 10px;
    font-size: {m.FONT_CART_QTY_PT}pt; font-weight: 600; padding: 0px;
}}
QPushButton#touchStep:hover   {{ background: {t.step_hover}; border-color: {t.nav_active}; }}
QPushButton#touchStep:pressed {{ background: {t.step_pressed}; }}
QPushButton#touchRemove {{
    background: {t.surface}; color: {t.danger}; border: 2px solid {t.danger};
    border-radius: 10px; font-size: {m.FONT_CART_QTY_PT}pt;
    font-weight: 600; padding: 0px;
}}
QPushButton#touchRemove:hover   {{ background: {t.danger_light}; }}
QPushButton#touchRemove:pressed {{ background: {t.danger_pressed_light}; }}

/* Sepet toplamı — ekranın en belirgin rakamı */
#cartGrandTotal {{ font-size: {m.FONT_TOTAL_PT}pt; font-weight: 700; }}
#cartGrandLabel {{ color: {t.text_muted}; font-size: {m.FONT_SMALL_PT}pt; }}

/* ---- Rozetler ---- */
#badge {{ border-radius: 6px; padding: 3px 10px; font-size: {m.FONT_SMALL_PT}pt; }}

/* ---- Ayarlar bölüm düğmeleri ---- */
QPushButton#sectionNav {{
    text-align: left; padding: 8px 14px; font-weight: 600;
    min-height: {m.TOUCH_TARGET_MIN - 18}px;
}}
QPushButton#sectionNav:checked {{
    background: {t.cart_light}; border: 2px solid {t.cart}; color: {t.text};
}}

/* ---- Dokunmatik giriş takımı ---- */
QPushButton#touchKey {{
    background: {t.surface_alt}; border: 2px solid {t.border}; border-radius: 10px;
    font-size: {m.FONT_SECTION_PT}pt; font-weight: 600; padding: 0px;
}}
QPushButton#touchKey:hover   {{ background: {t.step_hover}; border-color: {t.nav_active}; }}
QPushButton#touchKey:pressed {{ background: {t.step_pressed}; }}
QPushButton#touchKey:checked {{
    background: {t.nav_active}; color: {t.on_accent}; border-color: {t.nav_active};
}}
#touchDisplay {{
    background: {t.surface}; border: 2px solid {t.border}; border-radius: 8px;
    font-size: {m.FONT_BARCODE_PT}pt; font-weight: 600; padding: 6px 12px;
}}
#touchDisplay[bos="evet"] {{ color: {t.text_muted}; font-weight: 400; }}

/* ---- Diğer ---- */
QScrollArea {{ border: none; background: transparent; }}
QStatusBar {{ background: {t.surface}; border-top: 1px solid {t.border}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {t.surface}; color: {t.text}; border: 1px solid {t.border}; padding: 6px;
}}
QGroupBox {{
    border: 1px solid {t.border}; border-radius: 10px; margin-top: 14px;
    padding: 14px; background: {t.surface};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px;
    color: {t.text_muted}; font-weight: 600;
}}
QCheckBox::indicator, QRadioButton::indicator {{ width: 22px; height: 22px; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 6px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
"""


def apply_theme(app, tokens: ThemeTokens | None = None) -> None:
    """Temayı uygular. Uygulama, testler ve araçlar bunu ÇAĞIRIR.

    ``tokens`` verilirse önce etkin tema o yapılır (açılışta, pencerelerden
    ÖNCE). Verilmezse etkin tema kullanılır.
    """
    if tokens is not None:
        set_tokens(tokens)
    app.setStyle("Fusion")          # işletim sistemi temasından bağımsız çizim
    app.setPalette(build_palette())
    app.setFont(base_font())
    app.setStyleSheet(build_stylesheet() + measured_rules())


def level_colors(state: int) -> tuple[str, str]:
    return LEVEL_COLORS.get(int(state), (TEXT_MUTED, SURFACE_ALT))
