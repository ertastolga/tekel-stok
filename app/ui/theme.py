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
    #: Menüde başlık ve seçili/üzerine gelinen öğe yazısı (iki temada da açık).
    nav_strong: str
    #: Seçili menü öğesinin zemini (nav_strong ile ≥ 4,5:1 kontrast).
    nav_selected: str
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
    nav_strong="#FFFFFF",
    nav_selected="#1F6FC5",
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

#: Koyu tema (V1.2 M9a). Vurgu renkleri hem ZEMİN (üzerinde koyu yazıyla) hem
#: koyu yüzey üzerinde YAZI olarak kullanılır; ikisinde de en az 4,5:1 kontrast
#: sağlanır (test_gorunum.py ölçer). Renk yine tek başına anlam taşımaz.
DARK = ThemeTokens(
    ad="DARK",
    bg="#11161C",
    surface="#1A2129",
    surface_alt="#212A34",
    border="#3A4756",
    text="#E7EDF3",
    text_muted="#A3B0BD",
    on_accent="#0B1015",
    primary="#2E9D62",
    primary_dark="#3DB574",
    primary_light="#17392A",
    primary_light_hover="#1D4734",
    primary_pressed="#258050",
    stock="#D08A33",
    stock_dark="#E29D48",
    stock_light="#3A2A14",
    count="#9B7BEA",
    count_dark="#B096F0",
    count_light="#2A2142",
    cart="#3A8CD6",
    cart_dark="#5AA2E3",
    cart_light="#162F45",
    cart_pressed="#2C71AF",
    nav_bg="#0B1015",
    nav_text="#C8D3E0",
    nav_active="#3A8CD6",
    nav_group="#8A99AB",
    nav_hover="rgba(255,255,255,0.08)",
    nav_strong="#FFFFFF",
    nav_selected="#24507A",
    danger="#EB5F57",
    danger_light="#3D1B1B",
    danger_border="#F07A73",
    danger_pressed_light="#4A2222",
    warning="#D9A030",
    warning_light="#3A2E12",
    critical="#E07A3A",
    critical_light="#3B2416",
    info="#4FA3E3",
    info_light="#162F45",
    disabled_bg="#252E39",
    disabled_fg="#6B7785",
    disabled_border="#2E3946",
    step_hover="#273240",
    step_pressed="#2F3B4B",
    chart=(
        "#4FA3E3", "#2E9D62", "#D08A33", "#9B7BEA", "#EB5F57",
        "#2BB3A3", "#E07A3A", "#7C8BD6", "#D9A030", "#5B8DEF",
    ),
)
TEMALAR: dict[str, ThemeTokens] = {"LIGHT": LIGHT, "DARK": DARK}

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


def gorunumu_uygula(tema: str = "LIGHT", olcek: int = 100, yogunluk: str = "NORMAL") -> None:
    """Tema + yazı ölçeği + yoğunluk — açılışta, pencerelerden ÖNCE (M9a)."""
    metrics.uygula(olcek, yogunluk)
    set_tokens(TEMALAR.get(tema, LIGHT))


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
QLineEdit#barcodeInput[kompakt="evet"] {{
    font-size: {metrics.FONT_KASA_BARCODE_PT}pt; padding: 4px 10px;
    min-height: {max(text_height(metrics.FONT_KASA_BARCODE_PT) + 6,
                     metrics.KASA_BARCODE_MIN_HEIGHT)}px;
}}
/* M12d: düğmenin min-height'i açık en küçük yüksekliğidir; yer daralınca
   (kaydırılan menü, yan panel) yerleşim düğmeyi ona kadar SIKIŞTIRIR. İçerik
   alanı yazı satırından kısa kalırsa g/y/ç/ş'nin alt kısmı kesilir. En küçük
   içerik yüksekliği bu yüzden ÖLÇÜLEN yazı satırıdır (yazı ölçeğiyle büyür). */
QPushButton {{
    min-height: {max(metrics.BUTTON_HEIGHT - 20, text_height(metrics.FONT_BASE_PT))}px;
}}
QPushButton#navButton {{ min-height: {text_height(metrics.FONT_BASE_PT)}px; }}
QPushButton#navGroupHeader {{
    min-height: {max(28, text_height(metrics.FONT_SMALL_PT))}px;
}}
QPushButton#kasaMore {{
    min-height: {max(metrics.TOUCH_TARGET_MIN - 20, text_height(metrics.FONT_CART_QTY_PT))}px;
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
#navContent {{ background: {t.nav_bg}; }}
#navTitle {{
    color: {t.nav_strong}; font-size: {m.FONT_SECTION_PT}pt; font-weight: 600;
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
QPushButton#navGroupHeader:hover {{ color: {t.nav_strong}; }}
#navButton {{
    background: transparent; color: {t.nav_text}; border: none;
    text-align: left; padding: 11px 14px; border-radius: 6px;
    margin: 1px 8px;
}}
#navButton:hover {{ background: {t.nav_hover}; color: {t.nav_strong}; }}
/* Seçili sayfa AÇIKÇA vurgulanır (M12b: zemin, içerik gerecinin kapsamsız stil
   sayfasınca eziliyordu; koyu temada yazı zeminle aynı renkteydi). */
#navButton:checked {{ background: {t.nav_selected}; color: {t.nav_strong}; font-weight: 600; }}
#navFooter {{ color: {t.nav_group}; font-size: {m.FONT_SMALL_PT}pt; padding: 10px 14px; }}
/* Menü kaydırma çubuğu koyu zeminde göze batmaz (M12b). */
#navRail QScrollBar:vertical {{ background: transparent; width: 8px; }}
#navRail QScrollBar::handle:vertical {{ background: {t.nav_hover}; border-radius: 4px; }}

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
/* Yazı boyutları ADLA verilir: "*" kuralı koddaki setFont'u ezer (M12b). */
#actionTitle {{ font-size: {m.FONT_ACTION_TITLE_PT}pt; font-weight: 700; }}
#actionHint {{ font-size: {m.FONT_ACTION_HINT_PT}pt; color: {t.text_muted}; }}
#priceCheckName {{ font-size: {m.FONT_PAGE_TITLE_PT}pt; font-weight: 600; }}
#priceCheckPrice {{ font-size: {m.FONT_PRICE_CHECK_PT}pt; font-weight: 700; color: {t.text}; }}
#packQuestion {{ font-size: {m.FONT_SECTION_PT}pt; font-weight: 700; }}
#kpiValue {{ font-size: {m.FONT_CARD_VALUE_PT}pt; font-weight: 700; }}
#profitHeadline {{ font-size: {m.FONT_PAGE_TITLE_PT}pt; font-weight: 600; }}

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

/* ---- Kasa araç çubuğu ---- */
QPushButton#kasaTool {{
    min-height: {m.TOUCH_TARGET_MIN - 20}px; padding: 9px 14px; font-weight: 600;
    border-radius: 10px;
}}
QPushButton#kasaMore {{
    min-height: {m.TOUCH_TARGET_MIN - 20}px; padding: 9px 6px; border-radius: 10px;
    font-size: {m.FONT_CART_QTY_PT}pt; font-weight: 700;
}}
QMenu#kasaMenu {{ background: {t.surface}; border: 1px solid {t.border}; }}
QMenu#kasaMenu::item {{ padding: 16px 28px; font-size: {m.FONT_SECTION_PT}pt; }}
QMenu#kasaMenu::item:selected {{ background: {t.cart_light}; color: {t.text}; }}
QMenu#kasaMenu::item:disabled {{ color: {t.disabled_fg}; }}

/* ---- Ayarlar bölüm düğmeleri ---- */
/* 56 px dokunma hedefi; liste sığmazsa kendi içinde kaydırılır (M12b). */
QPushButton#sectionNav {{
    text-align: left; padding: 8px 14px; font-weight: 600;
    min-height: {m.SECTION_NAV_HEIGHT - 18}px;
}}
QPushButton#sectionNav:checked {{
    background: {t.cart_light}; border: 2px solid {t.cart}; color: {t.text};
}}
/* Seçmeli düğme dizisi (Analiz dönemleri vb.): seçili olan AÇIKÇA görünür. */
QPushButton#segment {{ padding: 8px 14px; }}
QPushButton#segment:checked {{
    background: {t.cart}; color: {t.on_accent}; border-color: {t.cart_dark}; font-weight: 600;
}}

/* ---- Dokunmatik giriş takımı ---- */
/* Stil sayfasındaki min-height, koddaki setFixedSize / setMinimumHeight'i
   cilalamada EZER; dokunma hedefleri bu yüzden burada da 56 px'e sabitlenir.
   [dokunma="evet"]: varsayılan dolgu (9 px) + kenar (1 px) ile toplam 56 px. */
QPushButton[dokunma="evet"] {{ min-height: {m.TOUCH_TARGET_MIN - 20}px; }}
QPushButton#touchKey {{
    background: {t.surface_alt}; border: 2px solid {t.border}; border-radius: 10px;
    font-size: {m.FONT_SECTION_PT}pt; font-weight: 600; padding: 0px;
    min-height: {m.TOUCH_TARGET_MIN - 4}px;
}}
QPushButton#searchResult {{ text-align: left; padding: 9px 14px; }}
#searchName {{ font-size: {m.FONT_CART_PRICE_PT}pt; }}
#searchPrice {{ font-size: {m.FONT_CART_NAME_PT}pt; font-weight: 700; }}
/* Dokunmatik pencerelerde birincil düğme de dokunma yazı boyutundadır
   (M12b: "Onayla" komşusu "Vazgeç"ten küçük görünüyordu). */
QPushButton#primary[dokunma="evet"] {{
    font-size: {m.FONT_SECTION_PT}pt; font-weight: 600; border-radius: 10px;
}}
QPushButton[tutarDugmesi="evet"] {{ font-size: {m.FONT_PAYMENT_PT}pt; font-weight: 700; }}
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
#touchDisplay[buyuk="evet"] {{ font-size: {m.FONT_TOUCH_QTY_PT}pt; font-weight: 700; }}

/* ---- Diğer ---- */
QScrollArea {{ border: none; background: transparent; }}
/* Sayfa kabı: içerik pencereye sığmazsa üst üste binmez, kaydırılır (M12b). */
QScrollArea#pageScroll, QScrollArea#pageScroll > QWidget > QWidget {{ background: {t.bg}; }}
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
/* Gösterge TAM çizilir: yalnızca boyut verilince yerleşik kutu kayboluyor,
   işaretsiz onay kutusu hiç görünmüyordu (M12b ekran incelemesi). */
QCheckBox::indicator, QRadioButton::indicator {{
    width: 20px; height: 20px; border: 2px solid {t.text_muted};
    border-radius: 5px; background: {t.surface};
}}
QRadioButton::indicator {{ border-radius: 12px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t.nav_active}; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {t.primary}; border-color: {t.primary_dark};
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    background: {t.disabled_bg}; border-color: {t.disabled_border};
}}
QCheckBox {{ spacing: 10px; }}
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
