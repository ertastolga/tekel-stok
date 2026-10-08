"""Stok girişi: taslak, koli barkodu, maliyet geçmişi ve KANITLANABİLİR geri alma.

Bu modülün koruduğu en önemli kural: bir alış fişi, ancak stok ve değeri fiş
öncesi hâline TAM olarak döndürebiliyorsa otomatik geri alınır. Aksi hâlde
reddedilir — çünkü araya giren hareketlerden sonra "tam simetrik" ters kayıt
ortalama maliyeti bozar.
"""
from __future__ import annotations

import pytest

from app.core.errors import (
    BosFis,
    FisZatenTamamlanmis,
    GeriAlmaKanitlanamaz,
)
from app.core.models import BarcodeType

BIRA = "8690504001492"
KOLI = "8690504001508"


@pytest.fixture
def tedarikci(services):
    return services.suppliers.create("Anadolu Efes Dağıtım", phone="0212 000 00 00")


# ===================== Taslak ve onay ====================================
def test_taslakta_hicbir_sey_stoga_islenmez(services, bira):
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 48, unit_cost=5000)

    assert services.products.get(bira)["current_stock"] == 0, "taslak stoğu ETKİLEMEZ"
    assert services.db.scalar("SELECT COUNT(*) FROM stock_movements") == 0
    assert services.db.check_invariants() == []


def test_fis_onaylaninca_stok_artar(services, bira, tedarikci):
    fis = services.purchases.start_draft(supplier_id=tedarikci, invoice_no="A-1234")
    services.purchases.add_line(fis, bira, 48, unit_cost=5000)
    services.purchases.commit(fis)

    urun = services.products.get(bira)
    assert urun["current_stock"] == 48
    assert urun["stock_value"] == 48 * 5000
    assert urun["last_purchase_cost"] == 5000
    assert services.purchases.receipt(fis)["status"] == "COMMITTED"
    assert services.db.check_invariants(deep=True) == []


def test_bos_fis_onaylanamaz(services):
    fis = services.purchases.start_draft()
    with pytest.raises(BosFis):
        services.purchases.commit(fis)


def test_ayni_fis_iki_kez_onaylanamaz(services, bira):
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 10, unit_cost=5000)
    services.purchases.commit(fis)

    with pytest.raises(FisZatenTamamlanmis):
        services.purchases.commit(fis)
    assert services.products.get(bira)["current_stock"] == 10


def test_onaylanmis_fise_satir_eklenemez(services, bira):
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 10, unit_cost=5000)
    services.purchases.commit(fis)

    with pytest.raises(FisZatenTamamlanmis):
        services.purchases.add_line(fis, bira, 5, unit_cost=5000)


def test_taslak_yeniden_baslatmaya_dayanir(services, bira, reopen):
    fis = services.purchases.start_draft(invoice_no="B-99")
    services.purchases.add_line(fis, bira, 24, unit_cost=5200)

    yeni = reopen(services)
    try:
        taslaklar = yeni.purchases.open_drafts()
        assert len(taslaklar) == 1
        assert taslaklar[0]["invoice_no"] == "B-99"
        assert taslaklar[0]["satir_sayisi"] == 1
        assert yeni.products.get(bira)["current_stock"] == 0, (
            "taslak KENDİLİĞİNDEN tamamlanmaz"
        )
        yeni.purchases.commit(fis)
        assert yeni.products.get(bira)["current_stock"] == 24
    finally:
        yeni.close()


def test_taslak_silinince_iz_kalmaz(services, bira):
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 24, unit_cost=5000)
    services.purchases.discard_draft(fis)

    assert services.purchases.open_drafts() == []
    assert services.products.get(bira)["current_stock"] == 0
    assert services.db.check_invariants() == []


# ===================== Barkod çarpanı ====================================
def test_koli_barkodu_yirmi_dort_adet_ekler(services, bira):
    services.barcodes.add_barcode(bira, KOLI, BarcodeType.CASE, 24)
    eslesme = services.barcodes.resolve(KOLI)
    assert eslesme.quantity == 24, "çarpan servis katmanında uygulanır"

    fis = services.purchases.start_draft()
    services.purchases.add_line(
        fis, eslesme.product_id, eslesme.quantity, unit_cost=5000,
        barcode_used=eslesme.barcode, multiplier=eslesme.multiplier,
    )
    services.purchases.commit(fis)
    assert services.products.get(bira)["current_stock"] == 24


def test_ayni_barkod_tekrar_okutulunca_satir_artar(services, bira):
    """Karışık bir liste yerine tek satırda '+48' görünmeli."""
    fis = services.purchases.start_draft()
    for _ in range(2):
        services.purchases.add_line(fis, bira, 24, unit_cost=5000)

    satirlar = services.purchases.lines(fis)
    assert len(satirlar) == 1
    assert satirlar[0]["quantity"] == 48
    assert satirlar[0]["line_total"] == 48 * 5000


def test_farkli_maliyetli_ayni_urun_ayri_satir_olur(services, bira):
    """Gerçek irsaliyede aynı ürün iki fiyattan gelebilir; şema buna izin verir."""
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 24, unit_cost=5000)
    services.purchases.add_line(fis, bira, 12, unit_cost=5600)

    satirlar = services.purchases.lines(fis)
    assert len(satirlar) == 2
    services.purchases.commit(fis)
    urun = services.products.get(bira)
    assert urun["current_stock"] == 36
    assert urun["stock_value"] == 24 * 5000 + 12 * 5600


# ===================== Maliyet geçmişi ===================================
def test_son_alis_fiyati_on_doldurulur(services, bira):
    """V1.2 (plan §5.8): ön doldurma EKRANIN işidir — bilinen son alışı açıkça
    geçirir. ``add_line`` maliyetsiz çağrılırsa maliyet BİLİNMİYOR demektir
    (tahmini satır), sessizce eski fiyat ya da 0 yazılmaz."""
    for maliyet in (5000, 5400):                          # iki farklı alış
        fis1 = services.purchases.start_draft()
        services.purchases.add_line(fis1, bira, 24, unit_cost=maliyet)
        services.purchases.commit(fis1)

    assert services.purchases.last_purchase_cost(bira) == 5400

    fis2 = services.purchases.start_draft()
    services.purchases.add_line(
        fis2, bira, 24, unit_cost=services.purchases.last_purchase_cost(bira)
    )
    satir = services.purchases.lines(fis2)[0]
    assert (satir["unit_cost"], satir["cost_is_estimated"]) == (5400, 0)

    fis3 = services.purchases.start_draft()
    services.purchases.add_line(fis3, bira, 24)          # maliyet verilmedi
    satir = services.purchases.lines(fis3)[0]
    assert (satir["unit_cost"], satir["cost_is_estimated"]) == (0, 1)


def test_degisen_maliyetler_vurgulanir(services, bira, cips_urunu):
    fis1 = services.purchases.start_draft()
    services.purchases.add_line(fis1, bira, 24, unit_cost=5000)
    services.purchases.add_line(fis1, cips_urunu, 10, unit_cost=3000)
    services.purchases.commit(fis1)

    fis2 = services.purchases.start_draft()
    services.purchases.add_line(fis2, bira, 24, unit_cost=5600)      # zam
    services.purchases.add_line(fis2, cips_urunu, 10, unit_cost=3000)  # aynı

    degisen = services.purchases.changed_cost_lines(fis2)
    assert [d["name"] for d in degisen] == ["Tuborg Gold 50 cl Kutu"]


def test_alis_maliyeti_gecmisi_uzerine_yazilmaz(services, bira):
    for maliyet in (5000, 5300, 5600):
        fis = services.purchases.start_draft()
        services.purchases.add_line(fis, bira, 10, unit_cost=maliyet)
        services.purchases.commit(fis)

    gecmis = services.purchases.product_purchase_history(bira)
    assert [g["unit_cost"] for g in gecmis] == [5600, 5300, 5000]
    assert services.products.get(bira)["current_stock"] == 30
    assert services.products.get(bira)["stock_value"] == 10 * (5000 + 5300 + 5600)


def test_tedarikci_ozeti(services, bira, tedarikci):
    fis = services.purchases.start_draft(supplier_id=tedarikci)
    services.purchases.add_line(fis, bira, 24, unit_cost=5000)
    services.purchases.commit(fis)

    ozet = services.suppliers.summary(tedarikci)
    assert ozet["fis_sayisi"] == 1
    assert ozet["toplam_tutar"] == 120000
    assert [p["name"] for p in services.suppliers.products(tedarikci)] == [
        "Tuborg Gold 50 cl Kutu"
    ]


# ===================== Geri alma: kanıtlanabilirlik ======================
def test_hemen_ardindan_geri_alma_tam_geri_dondurur(services, bira):
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 48, unit_cost=5000)
    services.purchases.commit(fis)

    assert services.purchases.reversal_preview(fis).allowed is True
    services.purchases.reverse(fis)

    urun = services.products.get(bira)
    assert urun["current_stock"] == 0
    assert urun["stock_value"] == 0
    assert services.purchases.is_reversed(fis) is True
    assert services.db.check_invariants(deep=True) == []


def test_deligi_kapatmis_alisin_geri_alinmasi_da_tam_simetriktir(services, bira):
    """S=-5 iken gelen 10 adet, geri alınınca yine S=-5 ve V=0 olmalı."""
    from app.core.models import MovementType, RefType

    stamp = services.settings.calendar().stamp()
    with services.db.transaction() as conn:
        services.inventory.apply_movement(
            conn, bira, MovementType.SALE, -5, stamp, ref_type=RefType.MANUAL
        )

    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 10, unit_cost=5000)
    services.purchases.commit(fis)
    assert services.products.get(bira)["current_stock"] == 5
    assert services.products.get(bira)["stock_value"] == 25000

    services.purchases.reverse(fis)
    urun = services.products.get(bira)
    assert urun["current_stock"] == -5
    assert urun["stock_value"] == 0
    assert services.db.check_invariants(deep=True) == []


def test_araya_satis_girerse_geri_alma_reddedilir(services, bira):
    """Miktar negatife düşmese bile ortalama maliyet bozulacağı için reddedilir."""
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 48, unit_cost=5000)
    services.purchases.commit(fis)

    services.sales.quick_sale(bira)          # araya bir satış girdi

    onizleme = services.purchases.reversal_preview(fis)
    assert onizleme.allowed is False
    assert onizleme.blocking_names == ["Tuborg Gold 50 cl Kutu"]

    with pytest.raises(GeriAlmaKanitlanamaz) as hata:
        services.purchases.reverse(fis)
    assert "Tuborg Gold 50 cl Kutu" in hata.value.message

    urun = services.products.get(bira)
    assert urun["current_stock"] == 47, "hiçbir şey değişmedi"
    assert services.purchases.is_reversed(fis) is False
    assert services.db.check_invariants(deep=True) == []


def test_araya_baska_alis_girerse_de_reddedilir(services, bira):
    """Klasik tuzak: 10x50 + 10x70 sonra ilk fişi geri almak ortalamayı bozardı."""
    fis1 = services.purchases.start_draft()
    services.purchases.add_line(fis1, bira, 10, unit_cost=5000)
    services.purchases.commit(fis1)

    fis2 = services.purchases.start_draft()
    services.purchases.add_line(fis2, bira, 10, unit_cost=7000)
    services.purchases.commit(fis2)

    assert services.purchases.reversal_preview(fis1).allowed is False
    with pytest.raises(GeriAlmaKanitlanamaz):
        services.purchases.reverse(fis1)

    urun = services.products.get(bira)
    assert urun["stock_value"] == 10 * 5000 + 10 * 7000
    assert services.inventory.average_cost(bira) == 6000


def test_ikinci_fis_hala_geri_alinabilir(services, bira):
    """En son fişin arkasında hareket yoksa geri alınabilir."""
    fis1 = services.purchases.start_draft()
    services.purchases.add_line(fis1, bira, 10, unit_cost=5000)
    services.purchases.commit(fis1)

    fis2 = services.purchases.start_draft()
    services.purchases.add_line(fis2, bira, 10, unit_cost=7000)
    services.purchases.commit(fis2)

    services.purchases.reverse(fis2)
    urun = services.products.get(bira)
    assert urun["current_stock"] == 10
    assert urun["stock_value"] == 50000
    assert urun["last_purchase_cost"] == 5000, "son alış fiyatı da geri döndü"
    assert services.db.check_invariants(deep=True) == []


def test_fis_hep_ya_da_hic_geri_alinir(services, bira, cips_urunu):
    """Fişin TEK ürünü bile engelliyorsa fişin tamamı reddedilir."""
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 10, unit_cost=5000)
    services.purchases.add_line(fis, cips_urunu, 10, unit_cost=3000)
    services.purchases.commit(fis)

    services.sales.quick_sale(cips_urunu)     # yalnızca cipsi etkiledi

    with pytest.raises(GeriAlmaKanitlanamaz):
        services.purchases.reverse(fis)
    assert services.products.get(bira)["current_stock"] == 10, "bira da geri alınmadı"


def test_force_parametresi_yoktur(services):
    """Kaçış yolu bilerek kapatıldı: negatife düşmemek doğruluk garantisi değildir."""
    import inspect

    imza = inspect.signature(services.purchases.reverse)
    assert "force" not in imza.parameters


def test_duzeltme_girisi_alternatifi_calisir(services, bira):
    """Geri alınamayan durumda belgeli düzeltme yapılabilir."""
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 48, unit_cost=5000)
    services.purchases.commit(fis)
    services.sales.quick_sale(bira)

    hareket = services.inventory.manual_adjustment(
        bira, -10, unit_cost=5000, reason="Fazla girilen 10 adet düzeltildi"
    )
    assert hareket.balance_after == 37
    assert services.products.get(bira)["current_stock"] == 37
    assert services.inventory.ledger(bira)[0]["note"].startswith("Fazla girilen")
    assert services.db.check_invariants(deep=True) == []
