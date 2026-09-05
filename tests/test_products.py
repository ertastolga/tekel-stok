"""Ürün, barkod, konum ve stok defteri davranışı.

Korunan değişmezler (şartname §61):
  * barkod ürünü tanımlar, stoğu değil,
  * bir ürünün birden çok barkodu olabilir,
  * bir barkod iki ürüne ait olamaz,
  * ürün birden çok yerde bulunabilir ve konum değişimi stoğu DEĞİŞTİRMEZ,
  * pasife alma geçmişi yok etmez.
"""
from __future__ import annotations

import pytest

from app.core.errors import DesteklenmeyenOlcuTuru, GecersizUrunAdi, MukerrerBarkod
from app.core.models import BarcodeType, MovementType, RefType, StockState

BIRA = "8690504001492"
KOLI = "8690504001508"
PAKET = "8690504001515"


# ===================== Ürün ve barkod ====================================
def test_urun_ve_barkod_olusturulur(services, bira):
    urun = services.products.get(bira)
    assert urun["name"] == "Tuborg Gold 50 cl Kutu"
    assert urun["sale_price"] == 8000
    eslesme = services.barcodes.resolve(BIRA)
    assert eslesme is not None
    assert eslesme.product_id == bira
    assert eslesme.quantity == 1


def test_ayni_barkod_iki_urune_verilemez(services, bira):
    diger = services.products.create("Efes Malt 50 cl")
    with pytest.raises(MukerrerBarkod) as hata:
        services.barcodes.add_barcode(diger, BIRA)
    assert "Tuborg Gold 50 cl Kutu" in hata.value.message
    assert services.barcodes.resolve(BIRA).product_id == bira


def test_bir_urun_birden_cok_barkod_tasiyabilir(services, bira):
    services.barcodes.add_barcode(bira, PAKET, BarcodeType.PACK, 6)
    services.barcodes.add_barcode(bira, KOLI, BarcodeType.CASE, 24)

    assert services.barcodes.resolve(BIRA).quantity == 1
    assert services.barcodes.resolve(PAKET).quantity == 6
    assert services.barcodes.resolve(KOLI).quantity == 24
    assert all(b.product_id == bira for b in
               (services.barcodes.resolve(x) for x in (BIRA, PAKET, KOLI)))
    assert len(services.barcodes.barcodes_of(bira)) == 3


def test_koli_barkodu_onay_ister_tekli_istemez(services, bira):
    services.barcodes.add_barcode(bira, KOLI, BarcodeType.CASE, 24)
    assert services.barcodes.resolve(BIRA).needs_pack_confirm is False
    assert services.barcodes.resolve(KOLI).needs_pack_confirm is True


def test_tanınmayan_barkod_none_doner(services, bira):
    assert services.barcodes.resolve("9999999999999") is None


def test_pasife_alinan_barkod_okunmaz_ama_silinmez(services, bira):
    barkod_id = services.barcodes.barcodes_of(bira)[0]["id"]
    services.barcodes.deactivate_barcode(barkod_id)
    assert services.barcodes.resolve(BIRA) is None
    assert len(services.barcodes.barcodes_of(bira, include_inactive=True)) == 1


def test_eski_barkod_pasifken_yeni_urune_verilebilir(services, bira):
    """Ambalaj değişince eski barkod başka ürüne geçebilir."""
    services.barcodes.deactivate_barcode(services.barcodes.barcodes_of(bira)[0]["id"])
    yeni = services.products.create("Tuborg Gold 50 cl Yeni Ambalaj")
    services.barcodes.add_barcode(yeni, BIRA)
    assert services.barcodes.resolve(BIRA).product_id == yeni


def test_upc_ve_ean_yazimi_ayni_urune_cozulur(services):
    pid = services.products.create("Test GTIN")
    services.barcodes.add_barcode(pid, "012345678905")       # UPC-A
    assert services.barcodes.resolve("0012345678905").product_id == pid  # EAN-13
    assert services.barcodes.resolve("012345678905").product_id == pid


def test_gtin_olmayan_kodlarda_sifir_onemlidir(services):
    """00123 ve 123 FARKLI ürünlere verilebilir; çakışma olmamalı."""
    a = services.products.create("Dahili A")
    b = services.products.create("Dahili B")
    services.barcodes.add_barcode(a, "00123")
    services.barcodes.add_barcode(b, "123")
    assert services.barcodes.resolve("00123").product_id == a
    assert services.barcodes.resolve("123").product_id == b


def test_ayni_gtin_farkli_yazimla_bile_ikinci_urune_verilemez(services):
    a = services.products.create("A")
    b = services.products.create("B")
    services.barcodes.add_barcode(a, "012345678905")
    with pytest.raises(MukerrerBarkod):
        services.barcodes.add_barcode(b, "0012345678905")


def test_bos_urun_adi_reddedilir(services):
    with pytest.raises(GecersizUrunAdi):
        services.products.create("   ")


def test_v1_yalnizca_sayilabilir_urunu_kabul_eder(services):
    """Şema daha geniştir (ileride tablo yeniden inşası gerekmesin diye);
    katılık servis katmanındadır."""
    from app.core import quantity as qty

    with pytest.raises(DesteklenmeyenOlcuTuru):
        qty.ensure_v1_supported("WEIGHT", "GRAM", "PER_1000_BASE")
    assert services.db.check_invariants() == []


# ===================== Benzer üründen oluştur ============================
def test_benzer_urunden_olustur_siniflandirmayi_kopyalar(services, bira):
    services.catalog.set_tags(bira, [services.catalog.ensure_tag("soğuk")])
    services.catalog.add_product_location(bira, 8)          # Depo

    yeni = services.products.create_from_similar(
        bira, "Tuborg Gold 33 cl Kutu", sale_price=6500
    )
    kaynak = services.products.get(bira)
    kopya = services.products.get(yeni)

    assert kopya["brand_id"] == kaynak["brand_id"]
    assert kopya["unit_label"] == kaynak["unit_label"]
    assert kopya["sale_price"] == 6500, "fiyat kopyalanmaz, verilen kullanılır"
    assert {t["name"] for t in services.catalog.tags_of(yeni)} == {"soğuk"}
    assert {l["id"] for l in services.catalog.locations_of(yeni)} == {1, 8}
    assert services.barcodes.barcodes_of(yeni) == [], "barkod ASLA kopyalanmaz"


# ===================== Konumlar ==========================================
def test_urun_birden_cok_yerde_bulunabilir(services, bira):
    services.catalog.add_product_location(bira, 8)          # Depo
    yerler = {l["name"] for l in services.catalog.locations_of(bira)}
    assert yerler == {"Bira Dolabı", "Depo"}


def test_konum_degisikligi_stogu_degistirmez(services, bira):
    services.inventory.set_initial_stock(bira, 40, unit_cost=5000)
    onceki = services.products.get(bira)
    hareket_sayisi = services.db.scalar(
        "SELECT COUNT(*) FROM stock_movements WHERE product_id = ?", (bira,)
    )

    services.catalog.add_product_location(bira, 2)           # Meşrubat Dolabı
    services.catalog.remove_product_location(bira, 1)        # Bira Dolabı'ndan çıkar
    services.catalog.set_primary_location(bira, 2)

    sonraki = services.products.get(bira)
    assert sonraki["current_stock"] == onceki["current_stock"] == 40
    assert sonraki["stock_value"] == onceki["stock_value"]
    assert services.db.scalar(
        "SELECT COUNT(*) FROM stock_movements WHERE product_id = ?", (bira,)
    ) == hareket_sayisi, "konum değişimi stok hareketi ÜRETMEZ"


def test_tek_esas_raf_kurali(services, bira):
    services.catalog.add_product_location(bira, 8)
    services.catalog.set_primary_location(bira, 8)
    esas = [l for l in services.catalog.locations_of(bira) if l["is_primary"]]
    assert len(esas) == 1 and esas[0]["name"] == "Depo"


def test_toplu_konum_duzenleme(services):
    ids = [services.products.create(f"Enerji {i}") for i in range(5)]
    for pid in ids:
        services.catalog.add_product_location(pid, 5)        # Kasa Önü

    services.catalog.bulk_move(ids, add_location_ids=[2], remove_location_ids=[5])
    for pid in ids:
        yerler = {l["name"] for l in services.catalog.locations_of(pid)}
        assert yerler == {"Meşrubat Dolabı"}


# ===================== Stok defteri ======================================
def test_baslangic_stogu_defter_ve_onbellegi_kurar(services, bira):
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)
    urun = services.products.get(bira)
    assert urun["current_stock"] == 48
    assert urun["stock_value"] == 48 * 5000
    assert services.inventory.average_cost(bira) == 5000
    hareket = services.inventory.ledger(bira)[0]
    assert hareket["movement_type"] == MovementType.INITIAL_STOCK
    assert hareket["balance_after"] == 48


def test_stok_onbellegi_defterden_yeniden_uretilebilir(services, bira):
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)
    with services.db.transaction() as conn:
        conn.execute("UPDATE products SET current_stock = 999, stock_value = 7 "
                     " WHERE id = ?", (bira,))
    assert any(s.startswith("I1:") for s in services.db.check_invariants())

    services.inventory.recompute()
    urun = services.products.get(bira)
    assert (urun["current_stock"], urun["stock_value"]) == (48, 240000)
    assert services.db.check_invariants(deep=True) == []


def test_negatiften_pozitife_gecen_alis_ortalamayi_bozmaz(services, bira):
    """Kullanıcının verdiği senaryo, servis düzeyinde uçtan uca."""
    stamp = services.settings.calendar().stamp()
    with services.db.transaction() as conn:
        services.inventory.apply_movement(
            conn, bira, MovementType.SALE, -5, stamp, ref_type=RefType.MANUAL
        )
    assert services.products.get(bira)["current_stock"] == -5
    assert services.products.get(bira)["stock_value"] == 0

    with services.db.transaction() as conn:
        services.inventory.apply_movement(
            conn, bira, MovementType.PURCHASE, 10, stamp,
            unit_cost=5000, ref_type=RefType.MANUAL,
        )
    urun = services.products.get(bira)
    assert urun["current_stock"] == 5
    assert urun["stock_value"] == 25000, "delik kapatan 5 adet değere girmez"
    assert services.inventory.average_cost(bira) == 5000
    assert services.db.check_invariants(deep=True) == []


def test_delik_kapatma_hareket_uzerinde_kayitlidir(services, bira):
    stamp = services.settings.calendar().stamp()
    with services.db.transaction() as conn:
        services.inventory.apply_movement(
            conn, bira, MovementType.SALE, -5, stamp, ref_type=RefType.MANUAL
        )
        services.inventory.apply_movement(
            conn, bira, MovementType.PURCHASE, 10, stamp,
            unit_cost=5000, ref_type=RefType.MANUAL,
        )
    alis = services.inventory.ledger(bira)[0]
    assert alis["fill_quantity"] == 5
    assert alis["value_delta"] == 25000


def test_stok_bitince_deger_sifirlanir(services, bira):
    services.inventory.set_initial_stock(bira, 3, unit_cost=333)   # 999 kuruş
    stamp = services.settings.calendar().stamp()
    with services.db.transaction() as conn:
        for _ in range(3):
            services.inventory.apply_movement(
                conn, bira, MovementType.SALE, -1, stamp, ref_type=RefType.MANUAL
            )
    urun = services.products.get(bira)
    assert (urun["current_stock"], urun["stock_value"]) == (0, 0)
    assert services.db.check_invariants(deep=True) == []


def test_defter_sayfali_okunur(services, bira):
    services.inventory.set_initial_stock(bira, 100, unit_cost=5000)
    stamp = services.settings.calendar().stamp()
    with services.db.transaction() as conn:
        for _ in range(60):
            services.inventory.apply_movement(
                conn, bira, MovementType.SALE, -1, stamp, ref_type=RefType.MANUAL
            )
    assert len(services.inventory.ledger(bira, limit=50)) == 50
    assert len(services.inventory.ledger(bira, limit=50, offset=50)) == 11


# ===================== Başlatılmamış stok ================================
def test_yeni_urun_henuz_sayilmadi_durumundadir(services):
    pid = services.products.quick_create("Yeni Ürün", sale_price=1000)
    urun = services.products.get(pid)
    assert urun["stock_initialized_at_utc"] is None
    assert urun["stock_state"] == StockState.NOT_COUNTED
    assert services.products.attention_counts()["henuz_sayilmadi"] == 1
    assert services.products.attention_counts()["kritik"] == 0


def test_sifir_yazmak_sayildi_demektir(services):
    """Boş bırakmak 'bilmiyorum', 0 yazmak 'saydım, gerçekten sıfır' demektir."""
    bos = services.products.quick_create("Bilinmiyor", 1000, initial_stock=None)
    sifir = services.products.quick_create("Gerçekten Sıfır", 1000, initial_stock=0)
    assert services.products.get(bos)["stock_state"] == StockState.NOT_COUNTED
    assert services.products.get(sifir)["stock_state"] == StockState.CRITICAL


def test_alis_tek_basina_urunu_sayilmis_yapmaz(services):
    """Mal girmesi, önceden ne olduğunu bilmemizi sağlamaz."""
    pid = services.products.quick_create("Sayılmamış", 1000, initial_stock=None)
    stamp = services.settings.calendar().stamp()
    with services.db.transaction() as conn:
        services.inventory.apply_movement(
            conn, pid, MovementType.PURCHASE, 24, stamp,
            unit_cost=5000, ref_type=RefType.RECEIPT, ref_id=1,
        )
    urun = services.products.get(pid)
    assert urun["current_stock"] == 24
    assert urun["stock_initialized_at_utc"] is None
    assert urun["stock_state"] == StockState.NOT_COUNTED


def test_baslangic_stogu_urunu_sayilmis_yapar(services):
    pid = services.products.quick_create("Sayılacak", 1000, initial_stock=None)
    services.inventory.set_initial_stock(pid, 12, unit_cost=5000)
    urun = services.products.get(pid)
    assert urun["stock_initialized_at_utc"] is not None
    assert urun["stock_state"] == StockState.NORMAL


def test_sayilmamis_urunde_negatif_stok_yine_de_gorunur(services):
    pid = services.products.quick_create("Eksiye Düşen", 1000, initial_stock=None)
    stamp = services.settings.calendar().stamp()
    with services.db.transaction() as conn:
        services.inventory.apply_movement(
            conn, pid, MovementType.SALE, -4, stamp, ref_type=RefType.MANUAL
        )
    assert services.products.get(pid)["stock_state"] == StockState.NEEDS_CHECK


# ===================== Fiyat ve pasife alma ==============================
def test_fiyat_gecmisi_saklanir(services, bira):
    services.products.set_price(bira, 8500, "zam")
    services.products.set_price(bira, 9000)
    gecmis = services.products.price_history(bira)
    assert [(g["old_price"], g["new_price"]) for g in gecmis] == [
        (8500, 9000), (8000, 8500),
    ]


def test_ayni_fiyati_yazmak_gecmis_uretmez(services, bira):
    services.products.set_price(bira, 8000)
    assert services.products.price_history(bira) == []


def test_pasife_alma_gecmisi_yok_etmez(services, bira):
    services.inventory.set_initial_stock(bira, 10, unit_cost=5000)
    services.products.set_active(bira, False)

    urun = services.products.get(bira)
    assert urun is not None and urun["is_active"] == 0
    assert services.db.scalar(
        "SELECT COUNT(*) FROM stock_movements WHERE product_id = ?", (bira,)
    ) == 1
    assert services.barcodes.resolve(BIRA) is None, "pasif ürün kasada okunmaz"
    assert services.db.check_invariants() == []


def test_eksik_urun_bilgileri_listesi(services):
    pid = services.products.create("Yarım Ürün")
    eksikler = services.products.missing_fields(services.products.get(pid))
    assert "satış fiyatı" in eksikler
    assert "barkod" in eksikler
    assert "başlangıç stoğu" in eksikler
    assert pid in [r["id"] for r in services.products.incomplete()]


# ===================== Arama =============================================
def test_turkce_duyarsiz_arama(services, bira):
    services.products.create("Çaykur Rize Çayı")
    assert [r["name"] for r in services.products.search("caykur")] == ["Çaykur Rize Çayı"]
    assert [r["name"] for r in services.products.search("ÇAYKUR")] == ["Çaykur Rize Çayı"]
    assert services.products.search("tuborg")[0]["id"] == bira


def test_barkodla_arama(services, bira):
    assert services.products.search(BIRA)[0]["id"] == bira


def test_konuma_gore_filtre(services, bira):
    services.products.create("Rafta Olmayan")
    sonuc = services.products.search(location_id=1)
    assert [r["id"] for r in sonuc] == [bira]


# ===================== Kalıcılık =========================================
def test_kapat_ac_her_seyi_korur(services, bira, reopen):
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)
    services.barcodes.add_barcode(bira, KOLI, BarcodeType.CASE, 24)
    services.catalog.add_product_location(bira, 8)

    yeni = reopen(services)
    try:
        urun = yeni.products.get(bira)
        assert urun["current_stock"] == 48
        assert urun["stock_value"] == 240000
        assert yeni.barcodes.resolve(KOLI).quantity == 24
        assert len(yeni.catalog.locations_of(bira)) == 2
        assert yeni.db.check_invariants(deep=True) == []
    finally:
        yeni.close()
