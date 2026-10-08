"""F4 Para Üstü (V1.2 M3e).

Korunan sözler:
  * ayar KAPALIYKEN (varsayılan) NAKİT V1.1'deki gibi tek dokunuştur,
  * açıkken NAKİT para üstü panelini açar; hızlı tutarlar plan §6.4'e uyar
    ("Tam" toplam, sonra 10/50/100/500/1000'e yukarı yuvarlama, en çok 4),
  * hızlı tutar tek dokunuşla satışı o tutarla tamamlar ve "Para üstü: X TL"
    satış onayında ayrı satırda görünür; alınan tutar toplamdan az olamaz,
  * panel açıkken okutma reddedilir, denetimler kapalıdır; Vazgeç / Esc /
    sayfa değişimi satış YAPMADAN kapatır ve askıyı bırakır,
  * KART bu ayardan etkilenmez; SALES_FIRST'te "F4 Yeni Müşteri" ipucu yok.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QPushButton  # noqa: E402

from app.core.models import OperatingMode  # noqa: E402
from app.core.money import nakit_hizli_tutarlar  # noqa: E402
from app.scanner.scan_event import ScanEvent  # noqa: E402
from app.ui import metrics, shortcuts  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403

BIRA = "8690504001492"


@pytest.mark.parametrize(
    "toplam,beklenen",
    [
        (34700, [35000, 40000, 50000, 100000]),
        (124000, [124000, 125000, 130000, 150000]),
        (50000, [50000, 100000]),
        (34750, [35000, 40000, 50000, 100000]),
        (0, []),
    ],
    ids=["347", "1240", "500", "347.50", "0"],
)
def test_hizli_tutarlar_plan_vektorleri(toplam, beklenen):
    assert nakit_hizli_tutarlar(toplam) == beklenen


@pytest.fixture
def kasa(window, qapp, services):
    window.resize(1000, 600)
    window.go_to("sepetli_satis")
    qapp.processEvents()
    return window.pages["sepetli_satis"]


@pytest.fixture
def acik(services):
    services.settings.set("cash_change_calculator", 1)


def test_ayar_kapaliyken_nakit_tek_dokunus(kasa, qapp, services, bira):
    kasa.handle_scan(ScanEvent(code=BIRA))
    kasa.cash_button.click()
    assert kasa.overlay_state is None
    assert services.sales.last_sale()["payment_method"] == "NAKIT"


def test_hizli_tutar_tek_dokunusla_tamamlar_ve_para_ustunu_gosterir(
    kasa, window, qapp, services, bira, acik
):
    kasa.handle_scan(ScanEvent(code=BIRA))                 # 80 TL
    kasa.cash_button.click()
    panel = kasa._tender_panel
    assert kasa.overlay_state == "PARA_USTU" and window.router.is_suspended
    assert [d.text() for d in panel.quick_buttons] == ["Tam 80 TL", "100 TL", "500 TL",
                                                      "1.000 TL"]
    assert not kasa.cash_button.isEnabled() and not kasa.card_button.isEnabled()
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0

    window.router.dispatch(ScanEvent(code=BIRA))          # panel açıkken okutma
    assert kasa.cart.item_count == 1 and panel.notice_label.isVisibleTo(panel)

    panel.quick_buttons[1].click()                         # 100 TL
    qapp.processEvents()
    satis = services.sales.last_sale()
    assert satis["total_amount"] == 8000 and satis["payment_method"] == "NAKIT"
    assert kasa.overlay_state is None and not window.router.is_suspended
    assert kasa.flash.extra.text() == "Para üstü: 20 TL"
    assert kasa.flash.extra.isVisibleTo(kasa.flash)


def test_ozel_tutar_eksikse_reddedilir_yeterliyse_tamamlar(kasa, qapp, services, bira, acik):
    kasa.handle_scan(ScanEvent(code=BIRA))
    kasa.cash_button.click()
    panel = kasa._tender_panel
    panel.custom_button.click()
    for rakam in "50":
        panel.numpad.keys[rakam].click()
    assert panel.change_label.text().startswith("Eksik: 30 TL")
    panel.custom_confirm_button.click()
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert kasa.overlay_state == "PARA_USTU"

    panel.numpad.clear_key.click()
    for rakam in "200":
        panel.numpad.keys[rakam].click()
    assert panel.change_label.text() == "Para üstü: 120 TL"
    panel.custom_confirm_button.click()
    assert services.sales.last_sale()["total_amount"] == 8000
    assert kasa.flash.extra.text() == "Para üstü: 120 TL"


@pytest.mark.parametrize("kapat", ["vazgec", "esc", "gezinme"])
def test_vazgec_esc_ve_gezinme_satis_yapmaz(kasa, window, qapp, services, bira, acik, kapat):
    kasa.handle_scan(ScanEvent(code=BIRA))
    kasa.cash_button.click()
    if kapat == "vazgec":
        kasa._tender_panel.close_button.click()
    elif kapat == "esc":
        window._go_back()
    else:
        window.go_to("urunler")
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert kasa.overlay_state is None and not window.router.is_suspended
    assert kasa.cart.item_count == 1, "sepet olduğu gibi"


def test_alinan_tutar_toplamdan_az_olamaz(kasa, services, bira):
    kasa.handle_scan(ScanEvent(code=BIRA))
    from app.core.models import PaymentMethod

    assert kasa.complete(PaymentMethod.CASH, tendered=5000) is False
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert "az" in kasa.banner.headline.text()


def test_fiyat_degistiyse_panel_acilmaz(kasa, services, bira, acik):
    kasa.handle_scan(ScanEvent(code=BIRA))
    services.products.set_price(bira, 8500)
    kasa.cash_button.click()
    assert kasa.overlay_state is None
    assert "Ödeme alınmadı" in kasa.banner.headline.text()


def test_kart_ayardan_etkilenmez(kasa, services, bira, acik):
    kasa.handle_scan(ScanEvent(code=BIRA))
    kasa.card_button.click()
    assert kasa.overlay_state is None
    assert services.sales.last_sale()["payment_method"] == "KART"


def test_panel_sigar_ve_dokunma_boyutunda(kasa, qapp, services, bira, acik):
    kasa.handle_scan(ScanEvent(code=BIRA))
    kasa.cash_button.click()
    panel = kasa._tender_panel
    panel.custom_button.click()
    qapp.processEvents()
    assert panel.minimumSizeHint().height() <= kasa.height()
    kucuk = [(d.text(), d.height()) for d in panel.findChildren(QPushButton)
             if d.isVisibleTo(panel) and d.height() < metrics.TOUCH_TARGET_MIN]
    assert kucuk == []


def test_sales_first_yeni_musteri_ipucunu_gizler(window, services):
    assert "Yeni Müşteri" not in window.nav_footer.text()
    assert "Yeni Müşteri" in shortcuts.footer_hint(sales_first=False)
    services.settings.set("operating_mode", OperatingMode.INVENTORY_TRACKED)
    window.apply_settings()
    assert "F4 Yeni Müşteri" in window.nav_footer.text()
