"""Maliyet motoru: oransal çekim, delik kapatma, tahmini maliyet.

Bu modülün koruduğu iki gerçek hata:
  * ``q * round(V/S)`` stok bittiğinde kuruş artığı bırakıyordu,
  * negatif stoktan pozitife geçen alış, açığı kapatan birimleri de
    değerliyor ve ortalama maliyeti iki katına çıkarıyordu.
"""
from __future__ import annotations

import pytest

from app.core.costing import (
    SOURCE_LAST_AVG,
    SOURCE_LAST_PURCHASE,
    SOURCE_NONE,
    SOURCE_POOL,
    average_cost,
    cost_basis,
    inbound_value,
    outbound_value,
    reversal_value,
    withdrawal_cost,
)

TL = 100  # 1 TL = 100 kuruş


# --- Oransal çekim: kalıntı bırakmaz --------------------------------------
def test_stok_bitince_deger_tam_sifirlanir():
    """V=1000, S=3, 3 adet satış -> 1000 (999 DEĞİL)."""
    assert withdrawal_cost(3, 3, 1000) == 1000


def test_parcali_cekim_yarim_yukari_yuvarlar():
    # 1 adet, havuz 3 adet / 1000 kuruş -> 333,33 -> 333
    assert withdrawal_cost(1, 3, 1000) == 333
    # 2 adet -> 666,67 -> 667
    assert withdrawal_cost(2, 3, 1000) == 667


def test_ardisik_cekimler_havuzu_tam_tuketir():
    """Birer birer satmak da toplu satmak da havuzu tam bitirmeli."""
    stok, deger, toplam = 3, 1000, 0
    for _ in range(3):
        maliyet = withdrawal_cost(1, stok, deger)
        toplam += maliyet
        stok -= 1
        deger -= maliyet
    assert deger == 0
    assert toplam == 1000


@pytest.mark.parametrize("stok, deger", [(7, 12345), (13, 99991), (100, 1), (2, 3)])
def test_teker_teker_satis_hicbir_zaman_artik_birakmaz(stok, deger):
    kalan_stok, kalan_deger, toplam = stok, deger, 0
    while kalan_stok > 0:
        maliyet = withdrawal_cost(1, kalan_stok, kalan_deger)
        toplam += maliyet
        kalan_stok -= 1
        kalan_deger -= maliyet
    assert kalan_deger == 0, "stok bittiğinde hayalet değer kalmamalı"
    assert toplam == deger


def test_ortalama_turetilir():
    assert average_cost(4, 20000) == 5000
    assert average_cost(0, 0) is None
    assert average_cost(-3, 0) is None


# --- Delik kapatma: negatiften pozitife geçiş -----------------------------
def test_negatif_stokta_alis_once_acigi_kapatir():
    """Kullanıcının verdiği örnek: S=-5, V=0, 10 adet x 50 TL -> S=5, V=250 TL."""
    sonuc = inbound_value(quantity=10, current_stock=-5, unit_cost=50 * TL)
    assert sonuc.fill_quantity == 5
    assert sonuc.value_delta == 250 * TL      # 500 TL DEĞİL
    yeni_stok = -5 + 10
    yeni_deger = 0 + sonuc.value_delta
    assert yeni_stok == 5
    assert average_cost(yeni_stok, yeni_deger) == 50 * TL


def test_alis_tam_acigi_kapatirsa_deger_sifir_kalir():
    sonuc = inbound_value(quantity=5, current_stock=-5, unit_cost=50 * TL)
    assert sonuc.fill_quantity == 5
    assert sonuc.value_delta == 0
    assert (-5 + 5, 0 + sonuc.value_delta) == (0, 0)


def test_alis_acigi_kapatmaya_yetmezse_stok_negatif_kalir():
    sonuc = inbound_value(quantity=3, current_stock=-5, unit_cost=50 * TL)
    assert sonuc.fill_quantity == 3
    assert sonuc.value_delta == 0
    assert -5 + 3 == -2


def test_pozitif_stokta_delik_kurali_devrede_degildir():
    sonuc = inbound_value(quantity=10, current_stock=4, unit_cost=50 * TL)
    assert sonuc.fill_quantity == 0
    assert sonuc.value_delta == 500 * TL


def test_sifir_stokta_alis_tamamen_deger_olur():
    sonuc = inbound_value(quantity=10, current_stock=0, unit_cost=50 * TL)
    assert sonuc.fill_quantity == 0
    assert sonuc.value_delta == 500 * TL


# --- Maliyet temeli --------------------------------------------------------
def test_maliyet_temeli_havuzdan_gelir_ve_kesindir():
    temel = cost_basis(current_stock=4, stock_value=20000)
    assert temel.unit_cost == 5000
    assert temel.is_estimated is False
    assert temel.source == SOURCE_POOL


def test_stok_yokken_son_ortalamaya_duser_ve_tahminidir():
    temel = cost_basis(0, 0, last_avg_cost=5300, last_purchase_cost=5600)
    assert temel.unit_cost == 5300
    assert temel.is_estimated is True
    assert temel.source == SOURCE_LAST_AVG


def test_son_ortalama_yoksa_son_alisa_duser():
    temel = cost_basis(0, 0, last_avg_cost=None, last_purchase_cost=5600)
    assert (temel.unit_cost, temel.source) == (5600, SOURCE_LAST_PURCHASE)


def test_hicbir_maliyet_bilgisi_yoksa_sifir_ve_bilinmiyor():
    temel = cost_basis(0, 0)
    assert (temel.unit_cost, temel.source, temel.is_known) == (0, SOURCE_NONE, False)


# --- Çıkan mal -------------------------------------------------------------
def test_normal_satis_havuzdan_duser():
    sonuc = outbound_value(2, current_stock=4, stock_value=20000, fallback=cost_basis(4, 20000))
    assert sonuc.value_delta == -10000
    assert sonuc.cost_total == 10000
    assert sonuc.is_estimated is False


def test_stok_bitmisken_satis_defteri_bozmaz_ama_maliyeti_korur():
    """Negatif stokta satış: çıkarılacak değer yok, ama COGS tahmini olarak durur."""
    temel = cost_basis(0, 0, last_avg_cost=5000)
    sonuc = outbound_value(3, current_stock=0, stock_value=0, fallback=temel)
    assert sonuc.value_delta == 0, "stok değeri asla negatife itilmez"
    assert sonuc.cost_total == 15000, "kâr raporu için maliyet yine de bilinir"
    assert sonuc.is_estimated is True


def test_havuzu_asan_satis_karma_maliyetlenir():
    """2 adet havuzdan, 3 adet havuzu aşarak.

    Stok pozitifken maliyet temeli HAVUZ ortalamasıdır (5.000); ``last_avg_cost``
    yalnızca havuz boşken devreye girer. Havuzu aşan 3 adet de bu ortalamayla
    maliyetlenir — eldeki en iyi tahmin odur — ama satır TAHMİNİ işaretlenir.
    """
    temel = cost_basis(2, 10000, last_avg_cost=6000)
    assert temel.unit_cost == 5000 and temel.source == SOURCE_POOL

    sonuc = outbound_value(5, current_stock=2, stock_value=10000, fallback=temel)
    assert sonuc.value_delta == -10000          # havuz tamamen boşalır
    assert sonuc.cost_total == 10000 + 3 * 5000
    assert sonuc.is_estimated is True, "stok dışı satılan adetler tahminidir"


def test_deger_asla_stok_degerini_asamaz():
    sonuc = outbound_value(100, current_stock=1, stock_value=500, fallback=cost_basis(1, 500))
    assert sonuc.value_delta == -500
    assert 500 + sonuc.value_delta == 0


# --- Ters kayıt ------------------------------------------------------------
def test_ters_kayit_tam_simetriktir():
    assert reversal_value(-2500) == 2500
    assert reversal_value(50000) == -50000


def test_satis_geri_alinca_havuz_baslangica_doner():
    """Araya yeni alış girse bile ortalama doğru kalır."""
    stok, deger = 10, 10 * 500 * 1        # 10 adet x 5,00 TL
    satis = outbound_value(5, stok, deger, cost_basis(stok, deger))
    stok, deger = stok - 5, deger + satis.value_delta

    alis = inbound_value(10, stok, 700)   # 10 adet x 7,00 TL
    stok, deger = stok + 10, deger + alis.value_delta
    assert (stok, deger) == (15, 2500 + 7000)

    stok, deger = stok + 5, deger + reversal_value(satis.value_delta)
    assert stok == 20
    assert deger == 10 * 500 + 10 * 700   # 12000 = doğru havuz
    assert average_cost(stok, deger) == 600


# --- Sınır durumları -------------------------------------------------------
def test_sifir_veya_negatif_miktar_reddedilir():
    with pytest.raises(ValueError):
        inbound_value(0, 0, 100)
    with pytest.raises(ValueError):
        outbound_value(-1, 5, 500, cost_basis(5, 500))


def test_degersiz_havuzdan_cekim_sifirdir():
    assert withdrawal_cost(2, 5, 0) == 0
    assert withdrawal_cost(2, 0, 100) == 0
