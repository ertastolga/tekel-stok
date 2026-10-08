"""Yerleşim ölçüleri — arayüzün TEK boyut kaynağı.

Ölçüler 1366x768 mantıksal piksele göre seçilmiştir. Windows %125 ölçeklemede
aynı ekran uygulamaya yaklaşık 1092x614 mantıksal piksel bırakır (Qt ölçek
çarpanını olduğu gibi geçirir), bu yüzden pencerenin en küçük boyutu bunun
ALTINDA olmalıdır.

Bu uygulamanın hedef kullanıcısı 55-75 yaşında ve bilgisayara mesafeli. Bu
yüzden ölçüler kardeş uygulamadan bilerek BÜYÜKTÜR: taban yazı 12 pt (10,5
değil), giriş kutuları 44 px, tablo satırları 40 px. Küçük yazı ve dar hedefler
bu kullanıcı için doğrudan hata sebebidir.
"""
from __future__ import annotations

# --- Pencere -------------------------------------------------------------
#: %125 ölçeklemede 1366x768 ekranın uygulamaya bıraktığı mantıksal alan.
SCALED_1366 = (1092, 614)
MIN_WINDOW_WIDTH = 1000
MIN_WINDOW_HEIGHT = 600
DEFAULT_WINDOW_WIDTH = 1280
DEFAULT_WINDOW_HEIGHT = 820

#: Sol menü. Etiketler büyük yazıyla sığacak kadar geniş.
NAV_WIDTH = 224

# --- Duyarlı yerleşim ----------------------------------------------------
#: Bu genişliğin altında iki sütunlu sayfalar alt alta yığılır.
TWO_COLUMN_MIN_WIDTH = 1040
STACKED_SECONDARY_MIN_HEIGHT = 280

# --- Yazı boyutları (pt) -------------------------------------------------
FONT_BASE_PT = 12.0
FONT_SMALL_PT = 10.5
FONT_SECTION_PT = 13.5
FONT_PAGE_TITLE_PT = 20.0
FONT_CARD_VALUE_PT = 26.0
#: Ana ekrandaki büyük eylem kartları.
FONT_ACTION_TITLE_PT = 19.0
FONT_ACTION_HINT_PT = 11.5
#: Barkod bekleme ve satış onayı: karşıdan okunmalı.
FONT_BARCODE_PT = 18.0
FONT_FLASH_NAME_PT = 24.0
FONT_FLASH_LINE_PT = 15.0

# --- Boşluklar -----------------------------------------------------------
PAGE_MARGIN_H = 20
PAGE_MARGIN_V = 18
PAGE_SPACING = 16
CARD_PADDING = 16
CARD_SPACING = 10

# --- Denetimler ----------------------------------------------------------
INPUT_HEIGHT = 44
BUTTON_HEIGHT = 44
BIG_BUTTON_HEIGHT = 56
#: Ana ekran eylem kartı: fare hassasiyeti gerektirmeyecek kadar büyük.
ACTION_CARD_MIN_HEIGHT = 140
ACTION_CARD_PRIMARY_MIN_HEIGHT = 180
BARCODE_INPUT_HEIGHT = 60

# --- Dokunmatik POS (AVAPOS 15,6") ---------------------------------------
# Hedef cihaz klavyesiz bir dokunmatik terminaldir. Parmak hedefi için yaygın
# öneri en az 48 px'tir; burada 56 px seçildi çünkü kullanıcı 55-75 yaş ve
# ekranda eldivenle/aceleyle dokunabiliyor.
#
# NOT: mevcut WIDGET_ROW_HEIGHT (52) BİLEREK kullanılmadı — 56 px eşiğinin
# altında kalıyor.
TOUCH_TARGET_MIN = 56
#: Sepet satırı: 56 px düğme + dikey nefes payı.
CART_ROW_HEIGHT = 84
#: NAKİT / KART düğmeleri: ekranın en büyük hedefleri.
PAYMENT_BUTTON_HEIGHT = 88
#: Kasa araç çubuğundaki kompakt barkod alanı (araç çubuğu ≤ 64 px):
#: içerik + 4 px dolgu ×2 + 3 px odak kenarı ×2 ≤ 60 px.
KASA_BARCODE_MIN_HEIGHT = 46
FONT_KASA_BARCODE_PT = 15.0
#: Sepet toplamı karşıdan okunabilmeli.
FONT_TOTAL_PT = 30.0
FONT_PAYMENT_PT = 17.0
FONT_CART_NAME_PT = 14.5
FONT_CART_QTY_PT = 18.0
FONT_CART_PRICE_PT = 11.5

# --- Tablolar ------------------------------------------------------------
TABLE_ROW_HEIGHT = 40
WIDGET_ROW_HEIGHT = 52
CELL_SPIN_HEIGHT = 38
#: Başlık metninin kırpılmaması için sütuna eklenen yastık.
HEADER_PADDING = 30

# --- Son satışlar listesi ------------------------------------------------
RECENT_MIN_ROWS = 5
RECENT_NAME_PT = 14.0
RECENT_TIME_PT = 11.0
RECENT_ROW_PADDING = 9

# --- Satış onayı ---------------------------------------------------------
#: Başarılı satıştan sonra büyük onayın ekranda kaldığı süre.
SALE_FLASH_MS = 2000
#: Engellenen okutma bildiriminin süresi (daha kısa: sadece dikkat çeker).
BLOCKED_FLASH_MS = 1400

# --- Formlar -------------------------------------------------------------
FORM_FIELD_WIDTH = 300
FORM_FIELD_MAX_WIDTH = 520

# --- Barkod okutma hijyeni ------------------------------------------------
#: Bkz. app/scanner/scanner_service.py — eşikler orada uygulanır, burada
#: yalnızca arayüzün gösterdiği bilgi için tutulur.
SCAN_BURST_KEY_MS = 30
SCAN_STALE_GAP_MS = 300
