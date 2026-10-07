"""Arayüz testleri: her ekran açılıyor mu, akışlar bozulmuş mu?

Testler başsız (offscreen) çalışır. Kip pencereleri (``exec``) otomatik olarak
etkisizleştirilir, aksi hâlde süit kilitlenirdi.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from app.core.models import StockState  # noqa: E402
from app.scanner.scan_event import ScanEvent  # noqa: E402
from app.ui import theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

BIRA = "8690504001492"
KOLI = "8690504001508"


from ui_support import *  # noqa: E402,F401,F403


# ===================== Açılış ============================================
def test_tum_sayfalar_acilir(window, qapp):
    for anahtar in list(window.pages):
        window.go_to(anahtar)
        qapp.processEvents()
        assert window.stack.currentWidget() is window.pages[anahtar]


def test_sales_first_sepetli_satisa_acilir(window):
    """Dokunmatik POS: uygulama açılır açılmaz satış ekranı gelir."""
    assert window._current_key == "sepetli_satis"


def test_inventory_tracked_ana_ekrana_acilir(qapp, services, bira):
    """Envanter kipinde V1 davranışı korunur."""
    from app.core.models import OperatingMode

    services.settings.set("operating_mode", OperatingMode.INVENTORY_TRACKED)
    win = MainWindow(services)
    try:
        assert win._current_key == "ana_ekran"
    finally:
        close_window(win, qapp)


def test_hizli_satis_erisilebilir_kalir(window, qapp):
    """Sepetli Satış birincil oldu ama Hızlı Satış SİLİNMEDİ."""
    assert "hizli_satis" in window.pages
    assert "hizli_satis" in window.nav_buttons
    window.go_to("hizli_satis")
    qapp.processEvents()
    assert window._current_key == "hizli_satis"


def test_gezinme_dugmeleri_sayfalarla_eslesir(window):
    for anahtar in window.nav_buttons:
        assert anahtar in window.pages


def test_tema_aydinliktir(qapp):
    """Windows koyu temada bile uygulama aydınlık kalmalıdır."""
    palet = qapp.palette()
    zemin = palet.window().color()
    assert zemin.lightness() > 200, "pencere zemini açık olmalı"
    yazi = palet.windowText().color()
    assert yazi.lightness() < 80, "yazı koyu olmalı"


def test_yasli_kullanici_icin_yazi_buyuk(qapp):
    from app.ui import metrics

    assert metrics.FONT_BASE_PT >= 12.0
    assert metrics.INPUT_HEIGHT >= 44
    assert metrics.TABLE_ROW_HEIGHT >= 40


# ===================== Hızlı Satış =======================================
def test_hizli_satis_okutmasi_satis_yapar(window, qapp, services, bira):
    window.go_to("hizli_satis")
    sayfa = window.pages["hizli_satis"]
    sayfa.handle_scan(ScanEvent(code=BIRA, key_count=13, avg_gap_ms=8.0))
    qapp.processEvents()

    assert services.products.get(bira)["current_stock"] == 47
    assert "SATILDI" in sayfa.flash.title.text()
    assert sayfa.flash.name.text() == "Tuborg Gold 50 cl Kutu"


def test_on_okutma_on_satis_yapar(window, qapp, services, bira):
    window.go_to("hizli_satis")
    sayfa = window.pages["hizli_satis"]
    for _ in range(10):
        sayfa.handle_scan(ScanEvent(code=BIRA, key_count=13, avg_gap_ms=8.0))
    qapp.processEvents()
    assert services.products.get(bira)["current_stock"] == 38


def test_taninmayan_barkod_tanimlama_penceresi_acar_satis_yapmaz(
    window, qapp, services, monkeypatch
):
    """Tanınmayan barkod sessizce yok sayılmaz; tanımlama penceresi açılır.

    Pencere testte 'Vazgeç' ile kapanır; o zaman ekran hazır duruma döner ve
    HİÇBİR satış oluşmaz.
    """
    from app.ui.dialogs import unknown_barcode

    acildi = {"sayi": 0}
    monkeypatch.setattr(
        unknown_barcode.UnknownBarcodeDialog, "exec",
        lambda self: acildi.__setitem__("sayi", acildi["sayi"] + 1) or 0,
    )

    window.go_to("hizli_satis")
    sayfa = window.pages["hizli_satis"]
    sayfa.handle_scan(ScanEvent(code="0000000000000"))
    qapp.processEvents()

    assert acildi["sayi"] == 1, "ürün tanımlama penceresi açıldı"
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert services.db.scalar("SELECT COUNT(*) FROM products WHERE name = ''") == 0, (
        "adsız sahte ürün ASLA oluşturulmaz"
    )
    # Vazgeçildikten sonra ekran bir sonraki okutmaya hazır olmalı.
    assert sayfa.banner.headline.text() == "BARKOD BEKLENİYOR"


def test_fiyatsiz_urun_satilmaz(window, qapp, services):
    pid = services.products.create("Fiyatsız")
    services.barcodes.add_barcode(pid, "1234567890128")
    window.go_to("hizli_satis")
    sayfa = window.pages["hizli_satis"]
    sayfa.handle_scan(ScanEvent(code="1234567890128"))
    qapp.processEvents()

    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    # NOT: Python'un lower() metodu Türkçe 'İ' harfini bozar; bu yüzden
    # karşılaştırmalarda tr_lower kullanılır.
    from app.core.tr import tr_lower

    assert "fiyat" in tr_lower(sayfa.banner.headline.text())


def test_satis_onayi_modal_pencere_acmaz(window, qapp, services, bira, monkeypatch):
    """Başarılı satıştan sonra 'Tamam' sorulmaz."""
    cagrildi = {"sayi": 0}
    monkeypatch.setattr(
        QMessageBox, "exec",
        lambda self: cagrildi.__setitem__("sayi", cagrildi["sayi"] + 1),
    )
    window.go_to("hizli_satis")
    window.pages["hizli_satis"].handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    assert cagrildi["sayi"] == 0


# ===================== Sepetli Satış =====================================
def test_sepete_ekleme_ve_tamamlama(window, qapp, services, bira):
    window.go_to("sepetli_satis")
    sayfa = window.pages["sepetli_satis"]
    for _ in range(4):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    assert sayfa.cart.item_count == 4
    assert len(sayfa.cart.lines) == 1, "aynı ürün tek satırda toplanır"
    assert services.products.get(bira)["current_stock"] == 48, "henüz satılmadı"

    sayfa.complete()
    qapp.processEvents()
    assert services.products.get(bira)["current_stock"] == 44
    assert sayfa.cart.is_empty


def test_bos_sepet_tamamlanamaz(window, qapp, services):
    window.go_to("sepetli_satis")
    sayfa = window.pages["sepetli_satis"]
    sayfa.complete()
    qapp.processEvents()
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0


# ===================== Okutma yönlendirmesi ==============================
def test_okutma_yalnizca_etkin_sayfaya_gider(window, qapp, services, bira):
    window.go_to("hizli_satis")
    assert window.router.context == "hizli_satis"

    window.go_to("urunler")
    assert window.router.context is None, "satış yapmayan sayfa okutma almaz"

    window.router.dispatch(ScanEvent(code=BIRA))
    qapp.processEvents()
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0


def test_karar_penceresi_acikken_satis_olmaz(window, qapp, services, bira):
    window.go_to("hizli_satis")
    window.router.suspend("test penceresi")

    for _ in range(5):
        window.router.dispatch(ScanEvent(code=BIRA))
    qapp.processEvents()

    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0

    window.router.resume()
    qapp.processEvents()
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0, (
        "pencere kapanınca GECİKMİŞ satış oluşmaz"
    )


def test_sayfa_degisince_cift_okuma_korumasi_sifirlanir(window, qapp, services, bira):
    window.go_to("hizli_satis")
    window.router.dispatch(ScanEvent(code=BIRA))
    qapp.processEvents()
    window.go_to("ana_ekran")
    window.go_to("hizli_satis")
    window.router.dispatch(ScanEvent(code=BIRA))
    qapp.processEvents()
    assert services.db.scalar("SELECT COUNT(*) FROM sales WHERE entry_type='SALE'") == 2


# ===================== Stok girişi =======================================
def test_stok_girisi_taslakta_stogu_degistirmez(window, qapp, services, bira):
    window.go_to("stok_girisi")
    sayfa = window.pages["stok_girisi"]
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    assert services.products.get(bira)["current_stock"] == 48
    assert sayfa.receipt_id is not None


def test_koli_barkodu_stok_girisinde_dogrudan_eklenir(window, qapp, services, bira):
    services.barcodes.add_barcode(bira, KOLI, "CASE", 24)
    window.go_to("stok_girisi")
    sayfa = window.pages["stok_girisi"]
    sayfa.handle_scan(ScanEvent(code=KOLI))
    qapp.processEvents()

    satirlar = services.purchases.lines(sayfa.receipt_id)
    assert satirlar[0]["quantity"] == 24, "koli satışta sorulur, girişte sorulmaz"


# ===================== Sayım =============================================
def test_sayim_baslatilmadan_okutma_uyarir(window, qapp, services, bira):
    window.go_to("stok_sayimi")
    sayfa = window.pages["stok_sayimi"]
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    from app.core.tr import tr_lower
    assert "başlat" in tr_lower(sayfa.banner.headline.text())


def test_sayim_akisi(window, qapp, services, bira):
    window.go_to("stok_sayimi")
    sayfa = window.pages["stok_sayimi"]
    index = sayfa.location_combo.findData(1)          # Bira Dolabı
    sayfa.location_combo.setCurrentIndex(index)
    sayfa._start()
    qapp.processEvents()

    assert sayfa.session_id is not None
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    assert services.counts.lines(sayfa.session_id)[0]["counted_qty"] == 1


# ===================== Panel =============================================
def test_panel_bugunu_gosterir(window, qapp, services, bira):
    services.sales.quick_sale(bira)
    window.go_to("panel")
    qapp.processEvents()
    sayfa = window.pages["panel"]
    assert "80" in sayfa.revenue_card.value_label.text()


def test_sayilmamis_urun_panelde_kritik_gorunmez(window, qapp, services):
    services.products.quick_create("Sayılmamış", 1000, initial_stock=None)
    window.go_to("panel")
    qapp.processEvents()
    dikkat = services.products.attention_counts()
    assert dikkat["henuz_sayilmadi"] >= 1
    assert dikkat["kritik"] == 0


# ===================== Ürünler ===========================================
def test_urun_listesi_dolar(window, qapp, services, bira):
    window.go_to("urunler")
    qapp.processEvents()
    sayfa = window.pages["urunler"]
    assert sayfa.table.rowCount() >= 1


def test_urun_aramasi_turkce_duyarsiz(window, qapp, services):
    services.products.quick_create("Çaykur Rize Çayı", 5000)
    window.go_to("urunler")
    sayfa = window.pages["urunler"]
    sayfa.search_edit.setText("caykur")
    qapp.processEvents()
    assert sayfa.table.rowCount() == 1


# ===================== Ayarlar ===========================================
def test_ayarlar_yuklenir_ve_kaydeder(window, qapp, services):
    window.go_to("ayarlar")
    qapp.processEvents()
    sayfa = window.pages["ayarlar"]
    assert sayfa.dup_spin.value() == 120

    sayfa.dup_spin.setValue(200)
    qapp.processEvents()
    assert services.settings.duplicate_scan_ms() == 200
    assert window.scan_guard.window_ms == 200


# ===================== Barkod testi ======================================
def test_barkod_testi_kayit_olusturmaz(window, qapp, services, bira):
    window.go_to("barkod_testi")
    sayfa = window.pages["barkod_testi"]
    for _ in range(3):
        sayfa.handle_scan(ScanEvent(code=BIRA, key_count=13, avg_gap_ms=8.0))
    qapp.processEvents()

    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert services.db.scalar("SELECT COUNT(*) FROM stock_movements") == 1  # sadece başlangıç
    assert sayfa.table.rowCount() == 3


# ===================== Yerleşim ==========================================
@pytest.mark.parametrize(
    "genislik, yukseklik",
    [(1366, 768), (1092, 614), (1536, 864), (1920, 1080), (1000, 600)],
)
def test_yerlesim_kucuk_ekranlarda_tasmaz(window, qapp, genislik, yukseklik):
    """%125 ölçeklemede 1366x768 ekran uygulamaya ~1092x614 bırakır."""
    window.resize(genislik, yukseklik)
    qapp.processEvents()
    for anahtar in ("ana_ekran", "hizli_satis", "sepetli_satis", "panel"):
        window.go_to(anahtar)
        qapp.processEvents()
        sayfa = window.pages[anahtar]
        assert sayfa.width() <= window.width()
