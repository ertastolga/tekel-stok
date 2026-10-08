"""📊 Analiz sayfası (V1.2 M8b).

Korunan sözler:
  * her açılışta Genel Bakış + Bugün; sekmeler ilk GÖSTERİLDİĞİNDE dolar,
  * dönem değişince kartlar/karşılaştırma o döneme göre; 366 günden uzunda
    karşılaştırma yok (ileti),
  * eğilim gösterimi dönem uzunluğuna göre seçilir; önceki dönem ikinci seri,
  * ürünler sekmesi kategori kırılımını alt kategorilerle gösterir; ürün
    seçilince günlük eğilimi çizilir,
  * sepet çiftleri gerçek sepetlerden, açıklama cümlesiyle,
  * ödemeler sekmesi iadeleri geri alma gününde gösterir,
  * Kâr ve Maliyet Kapsamı iki kipte de vardır; tek kâr rakamı yalnızca
    güvenilir pay ≥ %95 iken; SALES_FIRST Genel Bakış'ta kâr yoktur.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.analytics import donemler as dn  # noqa: E402
from app.core.models import OperatingMode, PaymentMethod  # noqa: E402
from app.services.analytics_service import GUNLUK, SAATLIK  # noqa: E402
from app.services.cart_service import Cart  # noqa: E402
from app.ui.pages import dashboard as db_sayfa  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403


def _sepet(services, *kalemler, yontem=PaymentMethod.CASH):
    sepet = Cart()
    for urun, adet in kalemler:
        services.cart.add_product(sepet, urun, quantity=adet)
    return services.cart.checkout(sepet, payment_method=yontem)


@pytest.fixture
def saat(duvar_saati):
    duvar_saati.git(2026, 10, 6, 15)                     # Salı
    return duvar_saati


@pytest.fixture
def analiz(saat, window, qapp):
    window.go_to("panel")
    qapp.processEvents()
    return window.pages["panel"]


def test_her_acilis_genel_bakis_ve_bugun(analiz, window, qapp):
    assert analiz.tabs.currentIndex() == db_sayfa.GENEL
    assert analiz.period_type == dn.BUGUN and analiz.period_buttons[dn.BUGUN].isChecked()
    assert analiz.built_tabs() == {db_sayfa.GENEL}, "yalnızca görünen sekme doldu"
    analiz.set_period(dn.SON_7)
    analiz.tabs.setCurrentIndex(db_sayfa.URUNLER)
    assert db_sayfa.URUNLER in analiz.built_tabs()
    window.go_to("urunler")
    window.go_to("panel")
    qapp.processEvents()
    assert analiz.tabs.currentIndex() == db_sayfa.GENEL
    assert analiz.period_type == dn.BUGUN


def test_donem_degisince_kartlar_ve_karsilastirma(analiz, saat, services, bira):
    services.inventory.set_initial_stock(bira, 20, unit_cost=5000)
    saat.git(2026, 10, 5, 15)
    _sepet(services, (bira, 2))                                     # dün 160 TL
    saat.git(2026, 10, 6, 15)
    _sepet(services, (bira, 1))                                     # bugün 80 TL
    analiz.refresh()
    assert "80" in analiz.revenue_card.value_label.text()
    assert analiz.compare_table.rowCount() == 3
    assert analiz.compare_table.item(1, 4).text().startswith("▼"), "dünden düşük"
    analiz.set_period(dn.DUN)
    assert "160" in analiz.revenue_card.value_label.text()
    analiz.set_period(dn.OZEL, "2025-01-01", "2026-10-06")
    assert analiz.compare_table.rowCount() == 1
    assert analiz.compare_hint.text() == dn.KARSILASTIRMA_YOK


def test_egilim_gosterimi_doneme_gore(analiz, saat, services, bira):
    services.sales.quick_sale(bira)
    analiz.tabs.setCurrentIndex(db_sayfa.EGILIM)
    assert analiz.trend_combo.currentData() == SAATLIK
    assert len(analiz.trend_chart.data()) == 24
    assert len(analiz.trend_chart.comparison()) == 24, "önceki gün ikinci seri"
    analiz.set_period(dn.SON_7)
    assert analiz.trend_combo.currentData() == GUNLUK
    assert len(analiz.trend_chart.data()) == 7
    assert sum(v for _, v in analiz.trend_chart.data()) == 8000


def test_urunler_kategori_ve_urun_egilimi(analiz, saat, services, bira, cips_urunu):
    bira_kat = services.db.scalar("SELECT id FROM categories WHERE name = 'Bira'")
    services.products.update(bira, category_id=bira_kat)
    _sepet(services, (bira, 3), (cips_urunu, 1))
    analiz.tabs.setCurrentIndex(db_sayfa.URUNLER)
    analiz.product_view.setCurrentIndex(analiz.product_view.findData("KATEGORI"))
    analiz._fill_products()
    adlar = [analiz.product_table.item(i, 0).text()
             for i in range(analiz.product_table.rowCount())]
    assert adlar == ["Alkollü İçecekler", "    Bira", "Kategorisiz"]
    analiz.product_view.setCurrentIndex(analiz.product_view.findData("ADET"))
    analiz._fill_products()
    analiz.product_table.selectRow(0)
    assert analiz.product_table.item(0, 0).text() == "Tuborg Gold 50 cl Kutu"
    assert analiz.product_trend.data() == [("06.10", 3)]


def test_sepet_ciftleri(analiz, saat, services, bira, cips_urunu):
    for _ in range(3):
        _sepet(services, (bira, 1), (cips_urunu, 1))
    analiz.tabs.setCurrentIndex(db_sayfa.SEPETLER)
    assert analiz.pairs_table.rowCount() == 1
    assert analiz.pairs_table.item(0, 1).text() == "3"
    assert "alanların %100'i" in analiz.pairs_table.item(0, 2).text()
    assert analiz.basket_summary.text().startswith("3 kesin sepet")


def test_odemeler_iadeyi_geri_alma_gununde_gosterir(analiz, saat, services, bira):
    services.inventory.set_initial_stock(bira, 20, unit_cost=5000)
    saat.git(2026, 10, 5, 15)
    kart = _sepet(services, (bira, 2), yontem=PaymentMethod.CARD)
    saat.git(2026, 10, 6, 15)
    services.sales.reverse_sale(kart.sale_id)
    analiz.refresh()
    analiz.tabs.setCurrentIndex(db_sayfa.ODEMELER)
    assert analiz.refund_table.item(0, 0).text() == "KART"
    assert "160" in analiz.refund_table.item(0, 1).text()
    assert "160" not in analiz.payment_table.item(1, 1).text(), "bugünün kart satışı yok"


def test_kar_sekmesi_iki_kipte_ve_kapsam(analiz, saat, services, bira, cips_urunu):
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 10, 5000)
    services.purchases.commit(fis)
    services.sales.quick_sale(bira)
    analiz.refresh()
    assert not analiz.profit_card.isVisible(), "SALES_FIRST Genel Bakış'ta kâr yok"
    analiz.tabs.setCurrentIndex(db_sayfa.KAR)
    assert analiz.profit_headline.text().startswith("Brüt kâr: 30 TL")
    assert "%100" in analiz.coverage_label.text()

    services.sales.quick_sale(cips_urunu)                       # maliyeti bilinmiyor
    analiz.refresh()
    assert analiz.profit_headline.text().startswith("Kâr yalnızca kapsanan kısım için")
    assert analiz.tier_table.item(2, 0).text() == "Maliyeti bilinmiyor"


def test_stok_takibi_kipinde_dusuk_kapsam_kar_kartinda(saat, window, qapp, services,
                                                     cips_urunu):
    services.settings.set("operating_mode", OperatingMode.INVENTORY_TRACKED)
    services.sales.quick_sale(cips_urunu)
    window.go_to("panel")
    qapp.processEvents()
    analiz = window.pages["panel"]
    assert analiz.profit_card.isVisible()
    assert analiz.profit_card.value_label.text() == "kapsam düşük"
