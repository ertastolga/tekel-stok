"""Görsel tema: renkler, yazı tipleri ve stil sayfası.

Tasarım ilkeleri: yüksek kontrast, büyük düğmeler, sade tipografi, animasyon
yok. Kullanıcı teknik değildir; ekran ilk bakışta anlaşılmalıdır.

Renk ASLA tek başına anlam taşımaz: her durum renkle BİRLİKTE metin (ve
gerektiğinde simge) ile gösterilir. Kırmızı yalnızca tehlike, hata ve geri
alınamaz işlemler içindir.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontMetrics, QPalette

from app.ui import metrics

# --- Renkler --------------------------------------------------------------
BG = "#EEF1F5"
SURFACE = "#FFFFFF"
SURFACE_ALT = "#F6F8FB"
BORDER = "#D3DBE5"
TEXT = "#16202B"
TEXT_MUTED = "#65727F"

#: Satış — yeşil
PRIMARY = "#1B7F4C"
PRIMARY_DARK = "#14663C"
PRIMARY_LIGHT = "#E4F3EA"

#: Stok girişi — turuncu
STOCK = "#B4650E"
STOCK_DARK = "#8F4F09"
STOCK_LIGHT = "#FCEFDD"

#: Sayım — mor
COUNT = "#6941C6"
COUNT_DARK = "#53309E"
COUNT_LIGHT = "#EFE9FB"

#: Sepetli satış — mavi
CART = "#1F6FB2"
CART_DARK = "#17588C"
CART_LIGHT = "#E6F0F9"

NAV_BG = "#1E2A38"
NAV_TEXT = "#C8D3E0"
NAV_ACTIVE = "#2E90FA"
NAV_GROUP = "#8A99AB"

DANGER = "#C62B2B"
DANGER_LIGHT = "#FBE7E7"
WARNING = "#B77400"
WARNING_LIGHT = "#FDF2DC"
INFO = "#1F6FB2"
INFO_LIGHT = "#E6F0F9"

#: Devre dışı durum — TÜM düğme türleri için tek kaynak.
DISABLED_BG = "#E9EDF2"
DISABLED_FG = "#9AA6B3"
DISABLED_BORDER = "#DCE2EA"

#: Stok durumu renkleri. Anahtarlar ``models.StockState`` değerleridir.
#: 4 = "Henüz Sayılmadı" NÖTRDÜR: bilinmeyen stok, az stok DEĞİLDİR ve
#: kullanıcıyı boş yere telaşlandırmamalıdır.
LEVEL_COLORS = {
    0: (PRIMARY, PRIMARY_LIGHT),        # Normal
    1: (WARNING, WARNING_LIGHT),        # Düşük
    2: ("#D2691E", "#FBE6D6"),          # Kritik
    3: (DANGER, DANGER_LIGHT),          # Stok Kontrolü Gerekli
    4: (TEXT_MUTED, SURFACE_ALT),       # Henüz Sayılmadı — nötr
}

CHART_COLORS = [
    "#2E90FA", "#1B7F4C", "#B4650E", "#7A5AF8", "#C62B2B",
    "#0E9384", "#B54708", "#4E5BA6", "#CA8504", "#155EEF",
]

FONT_FAMILY = "Segoe UI"


def base_font(size: float = metrics.FONT_BASE_PT, bold: bool = False) -> QFont:
    font = QFont(FONT_FAMILY)
    font.setPointSizeF(float(size))
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


def light_palette() -> QPalette:
    """Uygulamanın TEK renk kaynağı.

    Windows koyu temadayken Qt'nin varsayılan paleti de koyu gelir; stil
    sayfası yalnızca belirli bileşenleri boyadığı için pencereler yarı koyu
    yarı açık görünür ve koyu zemin üzerinde koyu yazı OKUNMAZ hâle gelir.
    Bu palet uygulamayı işletim sistemi temasından tamamen bağımsız kılar.
    """
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(BG))
    p.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Base, QColor(SURFACE))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE_ALT))
    p.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(TEXT_MUTED))
    p.setColor(QPalette.ColorRole.Button, QColor(SURFACE))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.BrightText, QColor(DANGER))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    p.setColor(QPalette.ColorRole.Highlight, QColor(NAV_ACTIVE))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    p.setColor(QPalette.ColorRole.Link, QColor(INFO))
    p.setColor(QPalette.ColorRole.Mid, QColor(BORDER))
    p.setColor(QPalette.ColorRole.Dark, QColor(TEXT_MUTED))

    for role, color in (
        (QPalette.ColorRole.WindowText, DISABLED_FG),
        (QPalette.ColorRole.Text, DISABLED_FG),
        (QPalette.ColorRole.ButtonText, DISABLED_FG),
        (QPalette.ColorRole.Button, DISABLED_BG),
        (QPalette.ColorRole.Base, DISABLED_BG),
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, QColor(color))
    return p


STYLESHEET = f"""
* {{
    font-family: "{FONT_FAMILY}";
    font-size: {metrics.FONT_BASE_PT}pt;
}}
QWidget {{ color: {TEXT}; }}

/* Dialoglar: koyu OS temasında arka planı zorlamazsak koyu gelir. */
QDialog, QMessageBox {{ background: {BG}; }}

/* ---- Sol menü ---- */
#navRail {{ background: {NAV_BG}; }}
#navTitle {{
    color: #FFFFFF; font-size: {metrics.FONT_SECTION_PT}pt; font-weight: 600;
    padding: 16px 14px 2px 14px;
}}
#navSubtitle {{ color: {NAV_GROUP}; padding: 0 14px 12px 14px; }}
#navGroup {{
    color: {NAV_GROUP}; font-size: {metrics.FONT_SMALL_PT}pt; font-weight: 600;
    padding: 14px 14px 4px 14px;
}}
#navButton {{
    background: transparent; color: {NAV_TEXT}; border: none;
    text-align: left; padding: 11px 14px; border-radius: 6px;
    margin: 1px 8px;
}}
#navButton:hover {{ background: rgba(255,255,255,0.08); color: #FFFFFF; }}
#navButton:checked {{ background: {NAV_ACTIVE}; color: #FFFFFF; font-weight: 600; }}
#navFooter {{ color: {NAV_GROUP}; font-size: {metrics.FONT_SMALL_PT}pt; padding: 10px 14px; }}

/* ---- Sayfa ---- */
#contentArea {{ background: {BG}; }}
#pageHeader {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; }}
#pageTitle {{ font-size: {metrics.FONT_PAGE_TITLE_PT}pt; font-weight: 600; }}
#pageSubtitle {{ color: {TEXT_MUTED}; }}
#sectionTitle {{ font-size: {metrics.FONT_SECTION_PT}pt; font-weight: 600; }}

/* ---- Kartlar ---- */
#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
#cardTitle {{ color: {TEXT_MUTED}; font-size: {metrics.FONT_SMALL_PT}pt; }}
#cardValue {{ font-size: {metrics.FONT_CARD_VALUE_PT}pt; font-weight: 600; }}
#cardHint {{ color: {TEXT_MUTED}; font-size: {metrics.FONT_SMALL_PT}pt; }}

/* ---- Ana ekran eylem kartları ---- */
QPushButton#actionCard, QPushButton#actionCardPrimary {{
    background: {SURFACE}; border: 2px solid {BORDER}; border-radius: 12px;
    text-align: left; padding: 16px 18px;
}}
QPushButton#actionCard:hover, QPushButton#actionCardPrimary:hover {{
    border-color: {NAV_ACTIVE}; background: {SURFACE_ALT};
}}
QPushButton#actionCard:focus, QPushButton#actionCardPrimary:focus {{
    border: 3px solid {NAV_ACTIVE};
}}
QPushButton#actionCardPrimary {{
    background: {PRIMARY_LIGHT}; border-color: {PRIMARY};
}}
QPushButton#actionCardPrimary:hover {{ background: #D8EDE1; }}

/* ---- Düğmeler ---- */
QPushButton {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER};
    border-radius: 8px; padding: 9px 16px; min-height: {metrics.BUTTON_HEIGHT - 20}px;
}}
QPushButton:hover {{ background: {SURFACE_ALT}; }}
QPushButton:disabled {{
    background: {DISABLED_BG}; color: {DISABLED_FG}; border-color: {DISABLED_BORDER};
}}
QPushButton#primary {{
    background: {PRIMARY}; color: #FFFFFF; border-color: {PRIMARY_DARK}; font-weight: 600;
}}
QPushButton#primary:hover {{ background: {PRIMARY_DARK}; }}
QPushButton#stockAction {{
    background: {STOCK}; color: #FFFFFF; border-color: {STOCK_DARK}; font-weight: 600;
}}
QPushButton#stockAction:hover {{ background: {STOCK_DARK}; }}
QPushButton#danger {{
    background: {DANGER}; color: #FFFFFF; border-color: #A32222; font-weight: 600;
}}
QPushButton#bigAction {{
    min-height: {metrics.BIG_BUTTON_HEIGHT - 20}px;
    font-size: {metrics.FONT_SECTION_PT}pt; font-weight: 600;
}}
QPushButton#primary:disabled, QPushButton#stockAction:disabled,
QPushButton#danger:disabled, QPushButton#bigAction:disabled {{
    background: {DISABLED_BG}; color: {DISABLED_FG}; border-color: {DISABLED_BORDER};
}}

/* ---- Giriş alanları ---- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QTextEdit {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 8px 12px; min-height: {metrics.INPUT_HEIGHT - 20}px;
    selection-background-color: {NAV_ACTIVE}; selection-color: #FFFFFF;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border: 2px solid {NAV_ACTIVE}; padding: 7px 11px;
}}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled {{
    background: {DISABLED_BG}; color: {DISABLED_FG};
}}
QLineEdit#barcodeInput {{
    font-size: {metrics.FONT_BARCODE_PT}pt; font-weight: 600;
    border: 2px solid {BORDER};
}}
QLineEdit#barcodeInput[mode="sale"]:focus {{ border: 3px solid {PRIMARY}; }}
QLineEdit#barcodeInput[mode="stock"]:focus {{ border: 3px solid {STOCK}; }}
QLineEdit#barcodeInput[mode="count"]:focus {{ border: 3px solid {COUNT}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}

/* ---- Tablolar ---- */
QTableWidget, QTableView {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
    gridline-color: {BORDER}; selection-background-color: {PRIMARY_LIGHT};
    selection-color: {TEXT};
}}
QHeaderView::section {{
    background: {SURFACE_ALT}; color: {TEXT_MUTED}; border: none;
    border-bottom: 1px solid {BORDER}; padding: 10px 8px; font-weight: 600;
}}
QTableWidget::item {{ padding: 6px 8px; }}
/* QTableWidget'a stil verilince yerleşik onay kutusu çizimi bozulur. */
QTableWidget::indicator, QTableView::indicator {{
    width: 20px; height: 20px; border: 1px solid {BORDER};
    border-radius: 4px; background: {SURFACE};
}}
QTableWidget::indicator:checked, QTableView::indicator:checked {{
    background: {PRIMARY}; border-color: {PRIMARY_DARK};
}}

/* ---- Sonuç şeridi ---- */
#resultBanner {{ border-radius: 10px; border: 2px solid {BORDER}; background: {SURFACE}; }}
#resultHeadline {{ font-size: {metrics.FONT_SECTION_PT}pt; font-weight: 600; }}
#resultDetail {{ color: {TEXT_MUTED}; }}
#saleFlash {{ border-radius: 10px; border: 2px solid {PRIMARY}; background: {PRIMARY_LIGHT}; }}
#flashName {{ font-size: {metrics.FONT_FLASH_NAME_PT}pt; font-weight: 600; color: {PRIMARY_DARK}; }}
#flashLine {{ font-size: {metrics.FONT_FLASH_LINE_PT}pt; color: {TEXT}; }}

/* ---- Dokunmatik POS ---- */
/* Satış onayı ASLA kırmızı değildir; kırmızı yalnızca yıkıcı eylemlerde. */
QPushButton#cashButton {{
    background: {PRIMARY}; color: #FFFFFF; border: 2px solid {PRIMARY_DARK};
    border-radius: 10px; font-size: {metrics.FONT_PAYMENT_PT}pt; font-weight: 600;
    min-height: {metrics.PAYMENT_BUTTON_HEIGHT - 24}px; padding: 10px 16px;
}}
QPushButton#cashButton:hover  {{ background: {PRIMARY_DARK}; }}
QPushButton#cashButton:pressed {{ background: #0F5330; }}
QPushButton#cardButton {{
    background: {CART}; color: #FFFFFF; border: 2px solid {CART_DARK};
    border-radius: 10px; font-size: {metrics.FONT_PAYMENT_PT}pt; font-weight: 600;
    min-height: {metrics.PAYMENT_BUTTON_HEIGHT - 24}px; padding: 10px 16px;
}}
QPushButton#cardButton:hover  {{ background: {CART_DARK}; }}
QPushButton#cardButton:pressed {{ background: #11476F; }}
QPushButton#cashButton:disabled, QPushButton#cardButton:disabled {{
    background: {DISABLED_BG}; color: {DISABLED_FG}; border-color: {DISABLED_BORDER};
}}

/* Sepet satırı ve içindeki büyük adet düğmeleri */
#cartRow {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px;
}}
#cartRow[vurgu="evet"] {{ border: 2px solid {PRIMARY}; background: {PRIMARY_LIGHT}; }}
#cartName  {{ font-size: {metrics.FONT_CART_NAME_PT}pt; font-weight: 600; }}
#cartPrice {{ font-size: {metrics.FONT_CART_PRICE_PT}pt; color: {TEXT_MUTED}; }}
#cartQty   {{ font-size: {metrics.FONT_CART_QTY_PT}pt; font-weight: 600; }}
#cartTotal {{ font-size: {metrics.FONT_CART_NAME_PT}pt; font-weight: 600; }}
QPushButton#touchStep {{
    background: {SURFACE_ALT}; border: 2px solid {BORDER}; border-radius: 10px;
    font-size: {metrics.FONT_CART_QTY_PT}pt; font-weight: 600; padding: 0px;
}}
QPushButton#touchStep:hover   {{ background: #E7ECF3; border-color: {NAV_ACTIVE}; }}
QPushButton#touchStep:pressed {{ background: #DCE3EC; }}
QPushButton#touchRemove {{
    background: {SURFACE}; color: {DANGER}; border: 2px solid {DANGER};
    border-radius: 10px; font-size: {metrics.FONT_CART_QTY_PT}pt;
    font-weight: 600; padding: 0px;
}}
QPushButton#touchRemove:hover   {{ background: {DANGER_LIGHT}; }}
QPushButton#touchRemove:pressed {{ background: #F6D4D4; }}

/* Sepet toplamı — ekranın en belirgin rakamı */
#cartGrandTotal {{ font-size: {metrics.FONT_TOTAL_PT}pt; font-weight: 700; }}
#cartGrandLabel {{ color: {TEXT_MUTED}; font-size: {metrics.FONT_SMALL_PT}pt; }}

/* ---- Rozetler ---- */
#badge {{ border-radius: 6px; padding: 3px 10px; font-size: {metrics.FONT_SMALL_PT}pt; }}

/* ---- Diğer ---- */
QScrollArea {{ border: none; background: transparent; }}
QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; }}
QStatusBar::item {{ border: none; }}
QToolTip {{
    background: {SURFACE}; color: {TEXT}; border: 1px solid {BORDER}; padding: 6px;
}}
QGroupBox {{
    border: 1px solid {BORDER}; border-radius: 10px; margin-top: 14px;
    padding: 14px; background: {SURFACE};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 6px;
    color: {TEXT_MUTED}; font-weight: 600;
}}
QCheckBox::indicator, QRadioButton::indicator {{ width: 22px; height: 22px; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 6px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
"""


def apply_theme(app) -> None:
    """Temayı uygular. Uygulama, testler ve araçlar bunu ÇAĞIRIR."""
    app.setStyle("Fusion")          # işletim sistemi temasından bağımsız çizim
    app.setPalette(light_palette())
    app.setFont(base_font())
    app.setStyleSheet(STYLESHEET + measured_rules())


def level_colors(state: int) -> tuple[str, str]:
    return LEVEL_COLORS.get(int(state), (TEXT_MUTED, SURFACE_ALT))
