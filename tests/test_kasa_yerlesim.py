"""Kasa yerleşim bütçesi (V1.2 M3a, D-16).

V1.1'de Sepetli Satış ~770 px yükseklik istiyordu; 1000×600 pencerede yalnızca
~576 px vardı (1366×768'de bile 744 px) ve alt kısım kırpılıyordu. Korunan
sözler:
  * her Kasa sayfası 1000×600 ve %125'te 1366×768 (1092×614) pencereye
    DİKEY olarak sığar; sayfa başlığı yoktur, araç çubuğu ≤ 64 px'tir,
  * sonuç şeridindeki EN UZUN ileti bile kırpılmaz,
  * sepet listesinde en az iki satır görünür; toplam + NAKİT + KART tek satırdır,
  * Kasa'daki her görünür düğme en az 56 px'tir; "⋯" menüsü engellemeden açılır.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QPushButton  # noqa: E402

from app.scanner.scan_event import ScanEvent  # noqa: E402
from app.ui import metrics, theme  # noqa: E402
from app.ui.pages import cart_sale, quick_sale  # noqa: E402
from app.ui.widgets.common import PageHeader  # noqa: E402
from app.ui.widgets.kasa import ARAC_CUBUGU_YUKSEKLIGI  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403

BIRA = "8690504001492"
KASA = ("sepetli_satis", "hizli_satis", "fiyat_kontrol")
BOYUTLAR = [(1000, 600), (1092, 614)]


def _hazirla(window, qapp, boyut, anahtar):
    window.resize(*boyut)
    qapp.processEvents()
    window.go_to(anahtar)
    qapp.processEvents()
    return window.pages[anahtar]


@pytest.mark.parametrize("boyut", BOYUTLAR, ids=["1000x600", "1092x614"])
@pytest.mark.parametrize("anahtar", KASA)
def test_kasa_sayfasi_dikey_sigar(window, qapp, boyut, anahtar):
    sayfa = _hazirla(window, qapp, boyut, anahtar)
    assert sayfa.minimumSizeHint().height() <= window.stack.height(), (
        sayfa.minimumSizeHint().height(), window.stack.height()
    )
    assert sayfa.findChildren(PageHeader) == [], "Kasa'da sayfa başlığı yok"
    assert sayfa.toolbar.height() <= ARAC_CUBUGU_YUKSEKLIGI
    assert sayfa.barcode.height() >= sayfa.barcode.minimumSizeHint().height(), "kırpılmaz"


@pytest.mark.parametrize("modul,anahtar", [(cart_sale, "sepetli_satis"),
                                           (quick_sale, "hizli_satis")])
def test_en_uzun_sonuc_iletisi_kirpilmaz(window, qapp, modul, anahtar):
    """Ölçüm şeridin GERÇEK genişliğinde (Hızlı Satış'ta dar sol sütun) yapılır."""
    for boyut in BOYUTLAR:
        sayfa = _hazirla(window, qapp, boyut, anahtar)
        serit = sayfa.result_stack.height()
        genislik = sayfa.result_stack.width()
        assert 0 < genislik
        for ornek in modul.SERIT_ORNEKLERI:
            if ornek[0] == "banner":
                sayfa.banner.show_error(ornek[1], ornek[2], ornek[3])
                gerec = sayfa.banner
            else:
                sayfa.flash.set_texts(*ornek[1:])
                gerec = sayfa.flash
            gerec.layout().activate()
            gereken = max(gerec.layout().totalHeightForWidth(genislik),
                          gerec.minimumSizeHint().height())
            assert gereken <= serit, (boyut, ornek[1], gereken, serit)
        assert sayfa.minimumSizeHint().height() <= window.stack.height()


def test_sepet_listesi_en_az_iki_satir_ve_odeme_tek_satir(window, qapp, services, bira,
                                                          cips_urunu):
    sayfa = _hazirla(window, qapp, (1000, 600), "sepetli_satis")
    sayfa.handle_scan(ScanEvent(code=BIRA))
    sayfa._add_product(cips_urunu, 1, None, 1)
    qapp.processEvents()
    # Ölçülen satır yüksekliği (%100'de CART_ROW_HEIGHT; M12d).
    assert sayfa.scroll.viewport().height() >= 2 * theme.cart_row_height()
    assert theme.cart_row_height() >= metrics.CART_ROW_HEIGHT

    def dikey_aralik(gerec):
        ust = gerec.mapTo(sayfa, QPoint(0, 0)).y()
        return ust, ust + gerec.height()

    nakit = dikey_aralik(sayfa.cash_button)
    kart = dikey_aralik(sayfa.card_button)
    toplam = dikey_aralik(sayfa.total_label)
    assert nakit == kart, "NAKİT ve KART yan yana"
    assert nakit[0] <= toplam[0] and toplam[1] <= nakit[1], "toplam aynı satırda"
    assert sayfa.cash_button.height() >= metrics.PAYMENT_BUTTON_HEIGHT


@pytest.mark.parametrize("anahtar", KASA)
def test_kasadaki_her_gorunur_dugme_dokunma_boyutunda(window, qapp, bira, anahtar):
    sayfa = _hazirla(window, qapp, (1000, 600), anahtar)
    if anahtar == "sepetli_satis":
        sayfa.handle_scan(ScanEvent(code=BIRA))
        qapp.processEvents()
    dugmeler = [d for d in sayfa.findChildren(QPushButton) if d.isVisibleTo(sayfa)]
    assert dugmeler
    for dugme in dugmeler:
        assert dugme.height() >= metrics.TOUCH_TARGET_MIN, (dugme.text(), dugme.height())


def test_diger_islemler_menusu_engellemeden_acilir(window, qapp, services, bira):
    sayfa = _hazirla(window, qapp, (1000, 600), "sepetli_satis")
    menu = sayfa.toolbar.more_menu
    metinler = [e.text() for e in menu.actions()]
    assert any("Son Satışı Geri Al" in m for m in metinler)
    assert "Sepeti Boşalt" in metinler and any("Hızlı Satış" in m for m in metinler)
    sayfa.toolbar.more_button.click()          # QEventLoop.exec yasak: popup engellemez
    qapp.processEvents()
    assert menu.isVisible()
    menu.hide()

    assert not sayfa.clear_button.isEnabled(), "boş sepet"
    sayfa.handle_scan(ScanEvent(code=BIRA))
    assert sayfa.clear_button.isEnabled() and not sayfa.undo_button.isEnabled()
    assert sayfa.total_caption.text() == "TOPLAM · 1 ürün"


def test_katmanlardaki_her_dugme_dokunma_boyutunda_ve_katman_sigar(
    window, qapp, services, bira
):
    """Katmanlar 1000×600'de sığar; içlerindeki düğmeler (klavye tuşları dahil)
    stil sayfası cilasından SONRA da en az 56 px'tir (V1.2 M3c bulgusu)."""
    sayfa = _hazirla(window, qapp, (1000, 600), "sepetli_satis")
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira)
    services.cart.park(sepet)
    for ac in (sayfa.open_search, sayfa.show_parked):
        ac()
        qapp.processEvents()
        katman = sayfa._overlay
        assert katman.minimumSizeHint().height() <= sayfa.height()
        if hasattr(katman, "keyboard"):
            katman.set_query("t")
            katman.search_now()
            qapp.processEvents()
        kucuk = [
            (d.text(), d.height()) for d in katman.findChildren(QPushButton)
            if d.isVisibleTo(katman) and d.height() < metrics.TOUCH_TARGET_MIN
        ]
        assert kucuk == []
        sayfa.close_overlay()


@pytest.mark.parametrize("boyut, katli", [((1000, 600), True), ((1920, 1080), False)])
def test_dar_pencerede_fiyat_gor_menuye_katlanir(window, qapp, boyut, katli):
    """M12b: 1000×600'de barkod alanı "Bar…" diye eziliyordu. Yer kalmazsa
    "Fiyat Gör" düğmesi "⋯" menüsüne taşınır (metin ve kısayol aynı); genişte
    düğme yerinde, menü girişi gizli. (Alanın gerçek genişliği yerel çizimli
    ekran görüntülerinde doğrulanır: offscreen yazı ölçüleri farklıdır.)"""
    sayfa = _hazirla(window, qapp, boyut, "sepetli_satis")
    menude = [e for e in sayfa.toolbar.more_menu.actions() if "Fiyat Gör" in e.text()]
    assert len(menude) == 1, "menüde tek giriş"
    assert sayfa.toolbar.collapsed() is katli
    assert sayfa.price_check_button.isVisibleTo(sayfa) is not katli
    assert menude[0].isVisible() is katli
    if katli:
        menude[0].trigger()
        qapp.processEvents()
        assert window._current_key == "fiyat_kontrol"
