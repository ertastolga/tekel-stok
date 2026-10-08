"""Geçmiş — Satışlar (V1.2 M12a, D-15).

Korunan sözler:
  * süzgeçler: iş günü aralığı, kip, ödeme (Kaydedilmemiş dahil), durum —
    tek tek ve birlikte,
  * sayfalama anahtar kümelidir: sayfalar örtüşmez, boşluk bırakmaz,
  * "(+N kalem)" SATIR sayısıdır, satılan adet değil (D-15),
  * ödeme sütunu; seçili satışın ayrıntısı (satırlar, geri alma zamanı ve
    iade günü); boş liste açıklaması,
  * önceki günün satışını geri alırken onay metni cironun hangi güne
    yazılacağını ve kart iadesinin POS'tan yapılacağını söyler.
"""
from __future__ import annotations

import os

import pytest

from app.core.models import PaymentMethod, SaleMode
from app.services.cart_service import Cart
from app.services.sale_service import (
    DURUM_GERI_ALINDI,
    DURUM_TAMAM,
    ODEME_KAYITSIZ,
    SatisFiltresi,
)

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui_support import *  # noqa: E402,F401,F403

from app.ui.widgets.common import column_index  # noqa: E402

GUN1, GUN2 = "2026-10-05", "2026-10-06"


def _sepet(services, *kalemler, yontem=PaymentMethod.CASH):
    sepet = Cart()
    for urun, adet in kalemler:
        services.cart.add_product(sepet, urun, quantity=adet)
    return services.cart.checkout(sepet, payment_method=yontem).sale_id


@pytest.fixture
def veri(duvar_saati, services, bira, cips_urunu):
    """1. gün: sepet/nakit (2 kalem, 5 adet), sepet/kart, hızlı (ödeme yok),
    sepet/kart. 2. gün: sepet/nakit; 1. günün ilk kart satışı 2. gün geri alındı."""
    duvar_saati.git(2026, 10, 5, 10)
    s1 = _sepet(services, (bira, 3), (cips_urunu, 2))
    duvar_saati.ilerle(60)
    s2 = _sepet(services, (bira, 1), yontem=PaymentMethod.CARD)
    duvar_saati.ilerle(60)
    s3 = services.sales.quick_sale(bira).sale_id
    duvar_saati.ilerle(60)
    s5 = _sepet(services, (cips_urunu, 1), yontem=PaymentMethod.CARD)
    duvar_saati.git(2026, 10, 6, 11)
    s4 = _sepet(services, (cips_urunu, 1))
    services.sales.reverse_sale(s2)
    duvar_saati.git(2026, 10, 6, 12)
    return {"s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5}


def _kimlikler(services, filtre=None, **kw):
    return [r["id"] for r in services.sales.history(filtre, **kw)]


# ===================== Servis ==============================================
def test_suzgecler_tek_tek_ve_birlikte(services, veri):
    v = veri
    assert _kimlikler(services) == [v["s4"], v["s5"], v["s3"], v["s2"], v["s1"]]
    assert _kimlikler(services, SatisFiltresi(baslangic=GUN1, bitis=GUN1)) == \
        [v["s5"], v["s3"], v["s2"], v["s1"]]
    assert _kimlikler(services, SatisFiltresi(baslangic=GUN2)) == [v["s4"]]
    assert _kimlikler(services, SatisFiltresi(kip=SaleMode.QUICK)) == [v["s3"]]
    assert _kimlikler(services, SatisFiltresi(odeme=PaymentMethod.CARD)) == [v["s5"], v["s2"]]
    assert _kimlikler(services, SatisFiltresi(odeme=PaymentMethod.CASH)) == [v["s4"], v["s1"]]
    assert _kimlikler(services, SatisFiltresi(odeme=ODEME_KAYITSIZ)) == [v["s3"]]
    assert _kimlikler(services, SatisFiltresi(durum=DURUM_GERI_ALINDI)) == [v["s2"]]
    assert _kimlikler(services, SatisFiltresi(durum=DURUM_TAMAM)) == \
        [v["s4"], v["s5"], v["s3"], v["s1"]]
    assert _kimlikler(services, SatisFiltresi(
        baslangic=GUN1, bitis=GUN1, kip=SaleMode.CART, odeme=PaymentMethod.CARD,
        durum=DURUM_TAMAM)) == [v["s5"]]


def test_kalem_sayisi_satir_sayisidir_adet_degil(services, veri):
    """D-15: 2 satır, 5 adet → "+1 kalem" (V1.1 "+4 kalem" yazıyordu)."""
    satir = {r["id"]: r for r in services.sales.history()}[veri["s1"]]
    assert (satir["satir_sayisi"], satir["item_count"]) == (2, 5)
    assert satir["ilk_urun"] == "Tuborg Gold 50 cl Kutu"


def test_anahtar_kumeli_sayfalama_ortusmez_bosluk_birakmaz(duvar_saati, services, bira):
    duvar_saati.git(2026, 10, 5, 10)
    hepsi = []
    for _ in range(7):
        duvar_saati.ilerle(30)
        hepsi.append(services.sales.quick_sale(bira).sale_id)
    sayfalar, sinir = [], None
    while True:
        sayfa = _kimlikler(services, limit=3, once_id=sinir)
        if not sayfa:
            break
        sayfalar.append(sayfa)
        sinir = sayfa[-1]
    assert [len(s) for s in sayfalar] == [3, 3, 1]
    assert [k for s in sayfalar for k in s] == list(reversed(hepsi))


def test_tarihli_ozet_geri_alinani_ciroya_katmaz(services, veri):
    ozet = services.sales.history_summary(SatisFiltresi(baslangic=GUN1, bitis=GUN1))
    tutarlar = {r["id"]: r["total_amount"] for r in services.sales.history()}
    assert (ozet.satis_sayisi, ozet.geri_alinan) == (4, 1)
    assert ozet.net_tutar == tutarlar[veri["s1"]] + tutarlar[veri["s3"]] + tutarlar[veri["s5"]]
    assert services.sales.history_summary(SatisFiltresi()) is None, "tarihsiz: toplanmaz"


def test_ayrinti_satirlar_ve_geri_alma_kaydi(services, veri):
    ayrinti = services.sales.detail(veri["s1"])
    assert ayrinti.satir_sayisi == 2 and ayrinti.geri_alma is None
    assert [s["quantity"] for s in ayrinti.satirlar] == [3, 2]
    geri = services.sales.detail(veri["s2"]).geri_alma
    assert geri is not None and geri["business_date"] == GUN2
    assert services.sales.detail(999_999) is None


# ===================== Arayüz ==============================================
@pytest.fixture
def gecmis(window, qapp, veri):
    window.go_to("gecmis")
    qapp.processEvents()
    sayfa = window.pages["gecmis"]
    sayfa.tabs.setCurrentIndex(0)
    sayfa.refresh()
    return sayfa


def _sutun(sayfa, baslik):
    tablo = sayfa.sales_table
    i = column_index(tablo, baslik)
    return [tablo.item(r, i).text() for r in range(tablo.rowCount())]


def test_urun_sutunu_kalem_sayisini_dogru_yazar(window, qapp, services, veri):
    """D-15 (arayüz): en eski satış 2 satır / 5 adet → "(+1 kalem)"."""
    window.go_to("gecmis")
    qapp.processEvents()
    sayfa = window.pages["gecmis"]
    sayfa.refresh()
    urunler = _sutun(sayfa, "Ürün")
    assert urunler[-1].endswith("(+1 kalem)"), urunler[-1]


def test_odeme_sutunu_ve_kip(gecmis):
    assert _sutun(gecmis, "Ödeme") == ["Nakit", "Kart", "Kaydedilmemiş", "Kart", "Nakit"]
    assert _sutun(gecmis, "Kip") == ["Sepetli", "Sepetli", "Hızlı", "Sepetli", "Sepetli"]
    assert _sutun(gecmis, "Durum")[3] == "Geri alındı"


def _sec(kutu, deger):
    kutu.setCurrentIndex(kutu.findData(deger))


def test_suzgec_degisince_liste_ve_ozet(gecmis):
    from app.analytics import donemler as dn

    assert gecmis.sales_summary.text() == "En yeni satışlar üstte."
    _sec(gecmis.payment_combo, PaymentMethod.CARD)
    assert gecmis.sales_table.rowCount() == 2
    _sec(gecmis.payment_combo, None)
    _sec(gecmis.period_combo, dn.DUN)                      # bugün 06.10 → dün 05.10
    assert gecmis.sales_table.rowCount() == 4
    assert gecmis.sales_summary.text().startswith("4 satış · 1 geri alındı · net ")
    assert not gecmis.start_edit.isVisibleTo(gecmis)
    _sec(gecmis.period_combo, dn.OZEL)
    assert gecmis.start_edit.isVisibleTo(gecmis) and gecmis.end_edit.isVisibleTo(gecmis)
    assert gecmis.sales_filter().baslangic == GUN2, "Özel bugünle başlar"


def test_bos_durum_aciklamasi(gecmis):
    from app.analytics import donemler as dn

    _sec(gecmis.period_combo, dn.BUGUN)
    _sec(gecmis.status_combo, DURUM_GERI_ALINDI)
    assert gecmis.sales_stack.currentWidget() is gecmis.sales_empty
    assert gecmis.sales_empty.title.text() == "Bu süzgeçle satış yok"
    _sec(gecmis.status_combo, None)
    assert gecmis.sales_stack.currentWidget() is gecmis.sales_table


def test_ayrinti_paneli_ve_geri_al_dugmesi(gecmis):
    assert gecmis.detail_stack.currentWidget() is gecmis.detail_empty
    assert not gecmis.reverse_button.isEnabled(), "seçim yokken geri alınamaz"
    gecmis.sales_table.selectRow(3)                         # geri alınmış kart satışı
    assert gecmis.detail_stack.currentIndex() == 1
    assert "Geri alındı: 06.10.2026" in gecmis.detail_status.text()
    assert "iş günü 06.10.2026" in gecmis.detail_status.text()
    assert "Kart" in gecmis.detail_info.text()
    assert not gecmis.reverse_button.isEnabled()
    gecmis.sales_table.selectRow(4)                         # 2 kalem, 5 adet
    assert gecmis.detail_lines.rowCount() == 2
    assert "5 adet, 2 kalem" in gecmis.detail_info.text()
    assert gecmis.detail_status.text() == "Tamamlandı"
    assert gecmis.reverse_button.isEnabled()


def test_sayfalar_arasi_gezinme(gecmis, monkeypatch):
    from app.ui.pages import history

    monkeypatch.setattr(history, "PAGE_SIZE", 2)
    gecmis.refresh()
    assert gecmis.sales_table.rowCount() == 2 and not gecmis.prev_button.isEnabled()
    gecmis.next_button.click()
    assert gecmis.page_label.text() == "Sayfa 2" and gecmis.prev_button.isEnabled()
    gecmis.next_button.click()
    assert gecmis.sales_table.rowCount() == 1 and not gecmis.next_button.isEnabled()
    gecmis.prev_button.click()
    gecmis.prev_button.click()
    assert gecmis.page_label.text() == "Sayfa 1"
    assert _sutun(gecmis, "Ödeme") == ["Nakit", "Kart"]


def test_onceki_gun_kart_satisini_geri_alma_metni(gecmis, services, veri, onay):
    gecmis.sales_table.selectRow(1)                         # 05.10 kart satışı
    gecmis._reverse_sale()
    assert "05.10.2026 tarihli" in onay.ayrintilar[-1]
    assert "banka POS" in onay.ayrintilar[-1]
    assert services.sales.sale(veri["s5"])["is_reversed"] == 1


def test_ayni_gun_nakit_geri_alma_metni(gecmis, services, veri, onay):
    gecmis.sales_table.selectRow(0)                         # bugünkü nakit satış
    gecmis._reverse_sale()
    assert "tarihli" not in onay.ayrintilar[-1]
    assert "kasadan iade" in onay.ayrintilar[-1]
    assert services.sales.sale(veri["s4"])["is_reversed"] == 1
