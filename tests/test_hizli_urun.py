"""Hızlı Ürün Ekle servisi, şema v3 ve D-08 (V1.2 M4b).

Korunan sözler:
  * form TEK işlemde kaydedilir; herhangi bir hata (ör. çakışan ek barkod)
    hiçbir şey bırakmaz; kategori zorunlu, fiyat > 0,
  * stoksuz girilen alış fiyatı yalnızca REFERANS fiyattır: stok değerine,
    "son alış"a, havuza ve maliyet kapsamına ASLA girmez,
  * pasife alınan ürün yeniden açılınca kapatılan barkodları (başka üründe
    etkin değilse) geri gelir; pasif ürünün barkodu okutulunca o ürün bulunur
    (V1.1 kusuru D-08).
"""
from __future__ import annotations

import pytest

from app.core.db import open_database
from app.core.errors import GecersizFiyat, GecersizUrunAdi, KategoriGerekli, MukerrerBarkod
from app.core.models import BarcodeType
from app.services.product_service import YeniUrun

BIRA = "8690504001492"
KOLI = "8690504001508"


def _kategori(services, ad="Bira"):
    return services.db.scalar("SELECT id FROM categories WHERE name = ?", (ad,))


def _taslak(services, **ek):
    alanlar = dict(name="Efes Pilsen 50 cl", sale_price=7000,
                   category_id=_kategori(services), barcode="8690000000111")
    alanlar.update(ek)
    return YeniUrun(**alanlar)


# ===================== Şema v3 =============================================
def test_v3_referans_maliyet_sutunlari(services, bira):
    sutunlar = {r[1] for r in services.db.query("PRAGMA table_info(products)")}
    assert {"reference_cost", "reference_cost_updated_at_utc"} <= sutunlar
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        services.db.execute("UPDATE products SET reference_cost = -1")


def test_v11_verisi_v3e_yukselir_referans_bos(v1_1_kopya):
    db = open_database(v1_1_kopya)
    try:
        assert db.schema_version() >= 3
        assert db.scalar("SELECT COUNT(*) FROM products WHERE reference_cost IS NOT NULL") == 0
        assert db.check_invariants(deep=True) == []
    finally:
        db.close()


# ===================== Atomik ekleme =======================================
def test_tam_form_tek_islemde_kaydedilir(services):
    tedarikci = services.suppliers.create("Toptancı A")
    pid = services.products.add_product(_taslak(
        services,
        extra_barcodes=[("8690000000128", BarcodeType.ALTERNATE, 1), (KOLI, BarcodeType.CASE, 24)],
        brand_name="Efes", family_name="Pilsen", tags=["soğuk", "kutu"],
        supplier_id=tedarikci, vat_rate=20, reference_cost=5200, location_id=1,
    ))
    urun = services.products.get(pid)
    assert urun["category_id"] == _kategori(services)
    assert urun["default_supplier_id"] == tedarikci and urun["vat_rate"] == 20
    assert urun["reference_cost"] == 5200 and urun["reference_cost_updated_at_utc"]
    assert services.barcodes.resolve(KOLI).quantity == 24
    assert services.barcodes.resolve("8690000000128").product_id == pid
    assert {t["name"] for t in services.catalog.tags_of(pid)} == {"soğuk", "kutu"}
    assert services.catalog.locations_of(pid)[0]["id"] == 1


def test_hata_hicbir_sey_birakmaz(services, bira):
    once = services.db.scalar("SELECT COUNT(*) FROM products")
    with pytest.raises(MukerrerBarkod):
        services.products.add_product(_taslak(
            services, extra_barcodes=[(BIRA, BarcodeType.ALTERNATE, 1)],   # bira'da kayıtlı
        ))
    assert services.db.scalar("SELECT COUNT(*) FROM products") == once
    assert services.barcodes.resolve("8690000000111") is None


@pytest.mark.parametrize(
    "ek,hata",
    [
        ({"name": "  "}, GecersizUrunAdi),
        ({"sale_price": 0}, GecersizFiyat),
        ({"category_id": None}, KategoriGerekli),
    ],
)
def test_zorunlu_alanlar(services, ek, hata):
    with pytest.raises(hata):
        services.products.add_product(_taslak(services, **ek))


def test_pasif_kategoriye_eklenmez(services):
    kategori = _kategori(services, "Sakız")
    services.categories.deactivate(kategori)
    with pytest.raises(KategoriGerekli):
        services.products.add_product(_taslak(services, category_id=kategori))


# ===================== Referans maliyet "asla" kuralları ===================
def test_stoksuz_alis_fiyati_yalnizca_referanstir(services):
    pid = services.products.add_product(_taslak(services, initial_cost=5500))
    urun = services.products.get(pid)
    assert urun["reference_cost"] == 5500
    assert urun["last_purchase_cost"] is None, "son alış DEĞİLDİR"
    assert urun["stock_value"] == 0 and urun["current_stock"] == 0
    assert services.db.scalar(
        "SELECT COUNT(*) FROM stock_movements WHERE product_id = ?", (pid,)) == 0


def test_referans_maliyet_satis_maliyetine_girmez(services):
    pid = services.products.add_product(_taslak(services, reference_cost=5000))
    sonuc = services.sales.quick_sale(pid)
    satir = services.db.query_one("SELECT * FROM sale_items WHERE sale_id = ?", (sonuc.sale_id,))
    assert satir["cost_total"] == 0, "referans maliyet havuza / satış maliyetine girmez"
    assert services.products.get(pid)["last_purchase_cost"] is None
    services.products.set_reference_cost(pid, 6000)
    assert services.products.get(pid)["last_purchase_cost"] is None
    assert services.db.check_invariants(deep=True) == []


def test_stoklu_alis_fiyati_acilis_maliyetidir(services):
    pid = services.products.add_product(_taslak(services, initial_stock=10, initial_cost=5000))
    urun = services.products.get(pid)
    assert urun["current_stock"] == 10 and urun["stock_value"] == 50000
    assert urun["reference_cost"] is None


# ===================== D-08 ================================================
def test_yeniden_acilan_urunun_barkodlari_geri_gelir(services, bira):
    services.barcodes.add_barcode(bira, KOLI, BarcodeType.CASE, 24)
    services.products.set_active(bira, False)
    assert services.barcodes.resolve(BIRA) is None
    sonuc = services.products.set_active(bira, True)
    assert sorted(sonuc.acilan_barkodlar) == sorted([BIRA, KOLI])
    assert services.barcodes.resolve(BIRA).product_id == bira
    assert services.barcodes.resolve(KOLI).quantity == 24


def test_elle_kapatilmis_barkod_geri_gelmez_cakisan_acilmaz(services, bira):
    eski = services.barcodes.add_barcode(bira, "8690000000135")
    services.barcodes.deactivate_barcode(eski)                  # elle, ÖNCE kapatıldı
    services.products.set_active(bira, False)
    yeni = services.products.quick_create("Başka ürün", 1000)
    services.barcodes.add_barcode(yeni, BIRA)                   # barkod başkasına verildi
    sonuc = services.products.reactivate(bira)
    assert sonuc.acilan_barkodlar == [] and sonuc.acilamayan_barkodlar == [BIRA]
    assert services.barcodes.resolve(BIRA).product_id == yeni
    assert services.barcodes.resolve("8690000000135") is None


def test_pasif_urunun_barkodu_sahibini_bulur(services, bira):
    assert services.barcodes.inactive_owner(BIRA) is None, "etkin sahibi var"
    services.products.set_active(bira, False)
    sahip = services.barcodes.inactive_owner(BIRA)
    assert sahip["product_id"] == bira and sahip["name"] == "Tuborg Gold 50 cl Kutu"
    assert services.barcodes.inactive_owner("2999999999999") is None


def test_v11_tarzi_pasiflestirme_de_geri_acilir(services, bira):
    """Denetim ayrıntısı olmayan (V1.1) kayıtta aynı anda kapanan grup açılır."""
    services.db.execute("UPDATE products SET is_active = 0 WHERE id = ?", (bira,))
    services.db.execute(
        "UPDATE product_barcodes SET active = 0, deactivated_at_utc = 1000 WHERE product_id = ?",
        (bira,),
    )
    sonuc = services.products.reactivate(bira)
    assert sonuc.acilan_barkodlar == [BIRA]


def test_son_kullanilan_kategoriler(services):
    for ad in ("Bira", "Cips", "Bira", "Sigara"):
        services.products.add_product(_taslak(
            services, name=f"Ürün {ad} {services.db.scalar('SELECT COUNT(*) FROM products')}",
            category_id=_kategori(services, ad), barcode=None))
    assert [r["name"] for r in services.categories.recent_for_products()] == [
        "Sigara", "Bira", "Cips"]
