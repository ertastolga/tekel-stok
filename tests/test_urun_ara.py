"""F2 Ürün Ara (V1.2 M3c).

Korunan sözler:
  * yalnızca satılabilir ürünler (aktif, fiyatlı); çok kelimeli VE araması ad
    ya da markada; Türkçe/aksan duyarsız; rakam sorgusu barkodda da aranır
    (baştan eşleşen önce); ``%`` ``_`` jokere dönüşmez,
  * panel okutmayı ENGELLEMEZ: açıkken okutulan ürün sepete girer ve sonucu
    panelde görünür; dokunuş 1 adet ekler ve panel açık kalır,
  * Hızlı Satış'ta sonuca dokunmak ürünü satar; Ctrl+F her iki Kasa sayfasında
    paneli açar; Esc ve sayfa değişimi kapatır,
  * ekran klavyesi kapalıysa okutmaya dayanıklı yazı alanı kullanılır,
  * panel 1000×600'de sığar, tüm dokunma hedefleri 56 px'tir.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QPushButton  # noqa: E402

from app.scanner.scan_event import ScanEvent  # noqa: E402
from app.ui import metrics  # noqa: E402
from app.ui.widgets.touch_input import ScanSafeLineEdit  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403

BIRA = "8690504001492"


@pytest.fixture
def katalog(services):
    p = services.products
    return {
        "efes": p.quick_create("Efes Pilsen 50 cl Kutu", 7000, barcode="8690504009993",
                               brand_name="Efes"),
        "efes_sise": p.quick_create("Efes Malt 33 cl Şişe", 6000, brand_name="Efes"),
        "kola": p.quick_create("Şişe Kola 1 L", 4000, barcode="8690000000012"),
        "fiyatsiz": p.quick_create("Efes Fiyatsız", None, brand_name="Efes"),
        "pasif": p.quick_create("Efes Eski Seri", 5000, brand_name="Efes"),
    }


def _adlar(services, sorgu):
    return [r["name"] for r in services.products.search_for_sale(sorgu)]


# ===================== Servis ==============================================
def test_cok_kelimeli_ve_marka_aramasi(services, katalog):
    services.products.set_active(katalog["pasif"], False)
    assert _adlar(services, "efes 50") == ["Efes Pilsen 50 cl Kutu"]
    assert _adlar(services, "efes") == ["Efes Malt 33 cl Şişe", "Efes Pilsen 50 cl Kutu"]
    assert _adlar(services, "malt efes") == ["Efes Malt 33 cl Şişe"], "marka kelimesi"
    assert _adlar(services, "kola efes") == [], "VE araması"


def test_satilamayanlar_cikmaz(services, katalog):
    services.products.set_active(katalog["pasif"], False)
    adlar = _adlar(services, "efes")
    assert "Efes Fiyatsız" not in adlar and "Efes Eski Seri" not in adlar


@pytest.mark.parametrize("sorgu", ["sise", "ŞİŞE", "şişe", "SISE kola"])
def test_turkce_ve_aksan_duyarsiz(services, katalog, sorgu):
    assert "Şişe Kola 1 L" in _adlar(services, sorgu)


def test_barkod_aramasi_bastan_eslesen_once(services, katalog):
    assert _adlar(services, "869050") [0] == "Efes Pilsen 50 cl Kutu"
    assert _adlar(services, "0012") == ["Şişe Kola 1 L"]
    assert _adlar(services, "86") == [], "iki rakam barkod araması değildir"


@pytest.mark.parametrize("sorgu", ["%", "_", "100%", "e_e"])
def test_joker_karakterler_kacislanir(services, katalog, sorgu):
    assert _adlar(services, sorgu) == []


def test_sonuc_siniri(services):
    for i in range(40):
        services.products.quick_create(f"Çikolata {i:02d}", 1000)
    assert len(services.products.search_for_sale("cikolata", limit=30)) == 30
    assert services.products.search_for_sale("   ") == []


# ===================== Arayüz ==============================================
@pytest.fixture
def kasa(window, qapp):
    window.resize(1000, 600)
    window.go_to("sepetli_satis")
    qapp.processEvents()
    return window.pages["sepetli_satis"]


def _yaz(panel, metin):
    for karakter in metin:
        if karakter == " ":
            panel.keyboard.space_key.click()
        else:
            panel.keyboard.key(karakter).click()
    panel.search_now()


def test_panel_acilir_okutmayi_engellemez_ve_sigar(kasa, window, qapp, katalog):
    kasa.search_button.click()
    qapp.processEvents()
    panel = kasa._search_panel
    assert kasa.overlay_state == "ARA"
    assert not window.router.is_suspended, "okutma açık"
    assert not kasa.cash_button.isEnabled()
    assert panel.geometry() == kasa.rect()
    assert panel.minimumSizeHint().height() <= kasa.height()
    dugmeler = [d for d in panel.findChildren(QPushButton) if d.isVisibleTo(panel)]
    kucuk = [(d.text(), d.height()) for d in dugmeler if d.height() < metrics.TOUCH_TARGET_MIN]
    assert kucuk == []


def test_dokunusla_ekler_panel_acik_kalir(kasa, qapp, katalog):
    kasa.open_search()
    panel = kasa._search_panel
    _yaz(panel, "efes 50")
    assert [d.property("product_id") for d in panel.result_buttons] == [katalog["efes"]]
    panel.result_buttons[0].click()
    panel.result_buttons[0].click()
    qapp.processEvents()
    assert kasa.cart.find(katalog["efes"]).quantity == 2
    assert kasa.overlay_state == "ARA", "panel açık kaldı"
    assert "Sepet: 2 ürün" in panel.feedback_label.text()


def test_panel_acikken_okutma_sepete_girer_ve_panelde_gorunur(kasa, window, qapp, bira):
    kasa.open_search()
    window.router.dispatch(ScanEvent(code=BIRA))
    qapp.processEvents()
    assert kasa.cart.item_count == 1
    assert "Tuborg" in kasa._search_panel.feedback_label.text()


def test_ctrl_f_ve_esc(kasa, window, qapp):
    window._focus_search()
    assert kasa.overlay_state == "ARA"
    window._go_back()
    assert kasa.overlay_state is None and window._current_key == "sepetli_satis"
    kasa.open_search()
    window.go_to("urunler")
    assert kasa.overlay_state is None


def test_hizli_satista_sonuca_dokunmak_satar(window, qapp, services, katalog):
    window.go_to("hizli_satis")
    sayfa = window.pages["hizli_satis"]
    window._focus_search()
    assert sayfa.overlay_state == "ARA"
    panel = sayfa._search_panel
    _yaz(panel, "kola")
    panel.result_buttons[0].click()
    qapp.processEvents()
    satis = services.sales.last_sale()
    assert satis is not None and satis["total_amount"] == 4000
    assert "SATILDI" in panel.feedback_label.text()


def test_ekran_klavyesi_kapaliysa_okutmaya_dayanikli_alan(kasa, qapp, services, katalog):
    services.settings.set("ekran_klavyesi", 0)
    kasa.open_search()
    panel = kasa._search_panel
    assert isinstance(panel.edit, ScanSafeLineEdit)
    assert not hasattr(panel, "keyboard")
    panel.edit.setText("kola")
    panel.search_now()
    assert len(panel.result_buttons) == 1
    services.settings.set("ekran_klavyesi", 1)
    kasa.close_overlay()
    kasa.open_search()
    assert kasa._search_panel.touch_keyboard, "ayar değişince panel yeniden kurulur"
