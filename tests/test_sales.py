"""Satış, geri alma ve atomiklik.

Şartname §57'deki zorunlu regresyonların satış bölümü burada korunur.
"""
from __future__ import annotations

import sqlite3

import pytest

from app.core.errors import BosSepet, FiyatiYokUrun, PasifUrun, ZatenGeriAlinmis
from app.core.models import StockState
from app.services.cart_service import Cart
from app.services.sale_service import SaleLineSpec

BIRA = "8690504001492"


@pytest.fixture
def stoklu_bira(services, bira):
    """48 adet, birim maliyet 50 TL, satış 80 TL."""
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)
    return bira


@pytest.fixture
def cips(services):
    pid = services.products.quick_create(
        "Ruffles Original 105 g", sale_price=5000, initial_stock=20, purchase_cost=3000
    )
    return pid


# ===================== Hızlı Satış =======================================
def test_hizli_satis_aninda_islenir(services, stoklu_bira):
    sonuc = services.sales.quick_sale(stoklu_bira)

    assert sonuc.total_amount == 8000
    assert sonuc.total_cost == 5000
    assert sonuc.gross_profit == 3000
    assert sonuc.item_count == 1
    assert services.products.get(stoklu_bira)["current_stock"] == 47
    assert services.db.check_invariants(deep=True) == []


def test_ayni_barkod_on_kez_okutulur(services, stoklu_bira):
    """Müşteri 10 bira alıyorsa aynı şişe 10 kez okutulur; '10' yazılmaz."""
    for _ in range(10):
        services.sales.quick_sale(stoklu_bira)

    assert services.products.get(stoklu_bira)["current_stock"] == 38
    assert services.db.scalar(
        "SELECT COUNT(*) FROM sales WHERE entry_type = 'SALE'"
    ) == 10, "her okutma AYRI ve değiştirilemez bir satış olayıdır"
    assert services.db.scalar(
        "SELECT SUM(total_amount) FROM sales"
    ) == 10 * 8000
    assert services.db.check_invariants(deep=True) == []


def test_satis_fiyat_ve_maliyet_kopyasi_saklar(services, stoklu_bira):
    sonuc = services.sales.quick_sale(stoklu_bira)
    kalem = services.sales.items(sonuc.sale_id)[0]
    assert kalem["unit_price"] == 8000
    assert kalem["cost_total"] == 5000
    assert kalem["product_name_snapshot"] == "Tuborg Gold 50 cl Kutu"


def test_fiyatsiz_urun_satilamaz(services):
    pid = services.products.create("Fiyatsız Ürün")
    with pytest.raises(FiyatiYokUrun):
        services.sales.quick_sale(pid)
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert services.db.scalar("SELECT COUNT(*) FROM stock_movements") == 0


def test_pasif_urun_satilamaz(services, stoklu_bira):
    services.products.set_active(stoklu_bira, False)
    with pytest.raises(PasifUrun):
        services.sales.quick_sale(stoklu_bira)
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0


def test_taninmayan_barkod_satis_olusturmaz(services, stoklu_bira):
    """Bilinmeyen barkod çözülemez; satış hattına HİÇ ulaşmaz."""
    assert services.barcodes.resolve("0000000000000") is None
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0


def test_stok_yoksa_satis_engellenmez_uyarilir(services, bira):
    """Kasa durmaz: sistemin stoğu yanlış olabilir, müşteri elinde ürünle bekliyor."""
    sonuc = services.sales.quick_sale(bira)

    assert sonuc.total_amount == 8000, "satış GERÇEKLEŞTİ"
    assert sonuc.warnings, "ama sessiz kalınmadı"
    urun = services.products.get(bira)
    assert urun["current_stock"] == -1
    assert urun["stock_state"] == StockState.NEEDS_CHECK
    assert urun["stock_value"] == 0, "stok değeri asla negatife itilmez"
    assert services.db.check_invariants(deep=True) == []


def test_stoksuz_satis_maliyeti_tahmini_isaretlenir(services, bira):
    services.inventory.set_initial_stock(bira, 1, unit_cost=5000)
    services.sales.quick_sale(bira)             # havuzdan
    sonuc = services.sales.quick_sale(bira)     # havuz boş

    kalem = services.sales.items(sonuc.sale_id)[0]
    assert kalem["is_estimated_cost"] == 1
    assert kalem["cost_total"] == 5000, "son bilinen ortalamadan tahmin edilir"


# ===================== Sepetli Satış =====================================
def test_sepet_tamamlanana_kadar_hicbir_sey_degismez(services, stoklu_bira, cips):
    sepet = Cart()
    for _ in range(4):
        services.cart.add_product(sepet, stoklu_bira)
    services.cart.add_product(sepet, cips, quantity=2)

    assert sepet.total == 4 * 8000 + 2 * 5000
    assert services.products.get(stoklu_bira)["current_stock"] == 48, "stok DEĞİŞMEDİ"
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0, "ciro DEĞİŞMEDİ"

    sonuc = services.cart.checkout(sepet)

    assert sonuc.item_count == 6
    assert sonuc.total_amount == 42000
    assert services.products.get(stoklu_bira)["current_stock"] == 44
    assert services.products.get(cips)["current_stock"] == 18
    assert sepet.is_empty
    assert services.db.check_invariants(deep=True) == []


def test_ayni_urun_tekrar_okutulunca_satir_adedi_artar(services, stoklu_bira):
    """Sepette 10 ayrı satır değil, tek satırda 10 adet görünür."""
    sepet = Cart()
    for _ in range(10):
        services.cart.add_product(sepet, stoklu_bira)

    assert len(sepet.lines) == 1
    assert sepet.lines[0].quantity == 10
    assert sepet.item_count == 10

    services.cart.checkout(sepet)
    assert services.products.get(stoklu_bira)["current_stock"] == 38


def test_bos_sepet_tamamlanamaz(services):
    with pytest.raises(BosSepet):
        services.cart.checkout(Cart())


def test_sepet_taslagi_yeniden_baslatmaya_dayanir(services, stoklu_bira, cips, reopen):
    sepet = Cart()
    services.cart.add_product(sepet, stoklu_bira, quantity=3)
    services.cart.add_product(sepet, cips)
    services.cart.save_draft(sepet, label="Masa 1")

    yeni = reopen(services)
    try:
        taslaklar = yeni.cart.open_drafts()
        assert len(taslaklar) == 1
        assert taslaklar[0]["label"] == "Masa 1"

        kurtarilan = yeni.cart.load_draft(taslaklar[0]["id"])
        assert kurtarilan.item_count == 4
        assert yeni.products.get(stoklu_bira)["current_stock"] == 48, (
            "taslak KENDİLİĞİNDEN tamamlanmaz"
        )
        assert yeni.db.scalar("SELECT COUNT(*) FROM sales") == 0

        sonuc = yeni.cart.checkout(kurtarilan)
        assert sonuc.item_count == 4
        assert yeni.products.get(stoklu_bira)["current_stock"] == 45
    finally:
        yeni.close()


def test_taslak_silinince_stok_etkilenmez(services, stoklu_bira):
    sepet = Cart()
    services.cart.add_product(sepet, stoklu_bira, quantity=5)
    draft_id = services.cart.save_draft(sepet)
    services.cart.discard_draft(draft_id)

    assert services.cart.open_drafts() == []
    assert services.products.get(stoklu_bira)["current_stock"] == 48


def test_ayni_urun_iki_satirda_havuzu_sirayla_tuketir(services, bira):
    """Aynı üründen iki satır: ikincisi sıfırı geçse bile maliyet doğru olmalı."""
    services.inventory.set_initial_stock(bira, 3, unit_cost=5000)
    sonuc = services.sales.commit_sale(
        [SaleLineSpec(bira, 2), SaleLineSpec(bira, 3)]
    )
    assert sonuc.item_count == 5
    assert services.products.get(bira)["current_stock"] == -2
    assert services.products.get(bira)["stock_value"] == 0
    assert sonuc.total_cost == 5 * 5000
    assert services.db.check_invariants(deep=True) == []


# ===================== Atomiklik =========================================
def test_sepet_odemesi_atomiktir(services, stoklu_bira, cips, monkeypatch):
    """Ortada patlarsa hiçbir satır kalmamalı: ne satış, ne stok, ne özet."""
    sepet = Cart()
    services.cart.add_product(sepet, stoklu_bira, quantity=2)
    services.cart.add_product(sepet, cips, quantity=1)

    gercek = services.inventory.apply_movement
    cagri = {"sayi": 0}

    def patlayan(*args, **kwargs):
        cagri["sayi"] += 1
        if cagri["sayi"] == 2:
            raise sqlite3.OperationalError("disk dolu")
        return gercek(*args, **kwargs)

    monkeypatch.setattr(services.inventory, "apply_movement", patlayan)

    with pytest.raises(sqlite3.OperationalError):
        services.cart.checkout(sepet)

    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert services.db.scalar("SELECT COUNT(*) FROM sale_items") == 0
    assert services.db.scalar("SELECT COUNT(*) FROM product_daily_sales") == 0
    assert services.products.get(stoklu_bira)["current_stock"] == 48
    assert services.products.get(cips)["current_stock"] == 20
    assert services.db.check_invariants(deep=True) == []


def test_hizli_satis_atomiktir(services, stoklu_bira, monkeypatch):
    def patlayan(*args, **kwargs):
        raise sqlite3.OperationalError("bağlantı koptu")

    monkeypatch.setattr(services.inventory, "apply_movement", patlayan)
    with pytest.raises(sqlite3.OperationalError):
        services.sales.quick_sale(stoklu_bira)

    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert services.products.get(stoklu_bira)["current_stock"] == 48


# ===================== Geri alma =========================================
def test_geri_alma_stogu_iade_eder_ciroyu_siler(services, stoklu_bira):
    satis = services.sales.quick_sale(stoklu_bira)
    assert services.products.get(stoklu_bira)["current_stock"] == 47

    services.sales.reverse_sale(satis.sale_id)

    urun = services.products.get(stoklu_bira)
    assert urun["current_stock"] == 48, "stok iade edildi"
    assert urun["stock_value"] == 48 * 5000, "değer de tam olarak geri geldi"
    assert services.db.scalar("SELECT SUM(total_amount) FROM sales") == 0, (
        "ters kayıt negatif tutar taşır, ciro filtresiz doğru olur"
    )
    assert services.db.check_invariants(deep=True) == []


def test_orijinal_kayit_silinmez(services, stoklu_bira):
    satis = services.sales.quick_sale(stoklu_bira)
    services.sales.reverse_sale(satis.sale_id)

    orijinal = services.sales.sale(satis.sale_id)
    assert orijinal is not None, "finansal geçmiş FİZİKSEL OLARAK silinmez"
    assert orijinal["is_reversed"] == 1
    assert orijinal["total_amount"] == 8000
    assert services.db.scalar(
        "SELECT COUNT(*) FROM sales WHERE entry_type = 'SALE_REVERSAL'"
    ) == 1


def test_ayni_satis_iki_kez_geri_alinamaz(services, stoklu_bira):
    satis = services.sales.quick_sale(stoklu_bira)
    services.sales.reverse_sale(satis.sale_id)

    with pytest.raises(ZatenGeriAlinmis):
        services.sales.reverse_sale(satis.sale_id)

    assert services.products.get(stoklu_bira)["current_stock"] == 48
    assert services.db.scalar(
        "SELECT COUNT(*) FROM sales WHERE entry_type = 'SALE_REVERSAL'"
    ) == 1


def test_son_satisi_geri_al(services, stoklu_bira, cips):
    services.sales.quick_sale(stoklu_bira)
    son = services.sales.quick_sale(cips)

    services.sales.reverse_last_sale()

    assert services.sales.sale(son.sale_id)["is_reversed"] == 1
    assert services.products.get(cips)["current_stock"] == 20
    assert services.products.get(stoklu_bira)["current_stock"] == 47


def test_son_satis_zaten_geri_alinmissa_bir_oncekine_gecmez(services, stoklu_bira):
    """Yanlışlıkla iki kez F8'e basmak ikinci satışı silmemeli."""
    services.sales.quick_sale(stoklu_bira)
    services.sales.quick_sale(stoklu_bira)
    services.sales.reverse_last_sale()

    with pytest.raises(ZatenGeriAlinmis):
        services.sales.reverse_last_sale()
    assert services.products.get(stoklu_bira)["current_stock"] == 47


def test_geri_alma_ozeti_orijinal_gunde_duser(services, stoklu_bira):
    satis = services.sales.quick_sale(stoklu_bira)
    gun = satis.business_date

    with services.db.transaction() as conn:
        conn.execute(
            "UPDATE sales SET business_date = '2026-01-15' WHERE id = ?", (satis.sale_id,)
        )
        conn.execute(
            "UPDATE daily_sales_rollup SET business_date = '2026-01-15' "
            " WHERE business_date = ?", (gun,)
        )
        conn.execute(
            "UPDATE product_daily_sales SET business_date = '2026-01-15' "
            " WHERE business_date = ?", (gun,)
        )

    services.sales.reverse_sale(satis.sale_id)

    ocak = services.db.query_one(
        "SELECT * FROM daily_sales_rollup WHERE business_date = '2026-01-15'"
    )
    assert ocak["total_amount"] == 0, "eksiltme ORİJİNAL güne yazıldı"
    bugun = services.db.query_one(
        "SELECT * FROM daily_sales_rollup WHERE business_date = ?", (gun,)
    )
    assert bugun is None, "bugünde hayalet eksi oluşmadı"


def test_geri_alma_son_satis_damgasini_tazeler(services, stoklu_bira):
    satis = services.sales.quick_sale(stoklu_bira)
    assert services.products.get(stoklu_bira)["last_sale_at_utc"] is not None

    services.sales.reverse_sale(satis.sale_id)
    assert services.products.get(stoklu_bira)["last_sale_at_utc"] is None


def test_geri_alma_atomiktir(services, stoklu_bira, cips, monkeypatch):
    sepet = Cart()
    services.cart.add_product(sepet, stoklu_bira, quantity=2)
    services.cart.add_product(sepet, cips)
    satis = services.cart.checkout(sepet)

    gercek = services.inventory.apply_movement
    cagri = {"sayi": 0}

    def patlayan(*args, **kwargs):
        cagri["sayi"] += 1
        if cagri["sayi"] == 2:
            raise sqlite3.OperationalError("kesinti")
        return gercek(*args, **kwargs)

    monkeypatch.setattr(services.inventory, "apply_movement", patlayan)
    with pytest.raises(sqlite3.OperationalError):
        services.sales.reverse_sale(satis.sale_id)

    assert services.sales.sale(satis.sale_id)["is_reversed"] == 0
    assert services.products.get(stoklu_bira)["current_stock"] == 46
    assert services.db.scalar(
        "SELECT COUNT(*) FROM sales WHERE entry_type = 'SALE_REVERSAL'"
    ) == 0
    assert services.db.check_invariants(deep=True) == []


# ===================== Fiyat ve maliyet geçmişi ==========================
def test_fiyat_degisikligi_eski_satisi_degistirmez(services, stoklu_bira):
    eski = services.sales.quick_sale(stoklu_bira)
    services.products.set_price(stoklu_bira, 9000)
    yeni = services.sales.quick_sale(stoklu_bira)

    assert services.sales.items(eski.sale_id)[0]["unit_price"] == 8000
    assert services.sales.items(yeni.sale_id)[0]["unit_price"] == 9000
    assert services.sales.sale(eski.sale_id)["total_amount"] == 8000


def test_yeni_alis_maliyeti_gecmis_kari_degistirmez(services, stoklu_bira):
    eski = services.sales.quick_sale(stoklu_bira)
    assert eski.gross_profit == 3000

    # Daha pahalı yeni parti gelir
    from app.core.models import MovementType, RefType

    stamp = services.settings.calendar().stamp()
    with services.db.transaction() as conn:
        services.inventory.apply_movement(
            conn, stoklu_bira, MovementType.PURCHASE, 48, stamp,
            unit_cost=7000, ref_type=RefType.RECEIPT, ref_id=1,
        )

    assert services.sales.items(eski.sale_id)[0]["cost_total"] == 5000, (
        "geçmiş maliyet kopyası DEĞİŞMEZ"
    )
    assert services.sales.sale(eski.sale_id)["total_cost"] == 5000


# ===================== Kalıcılık =========================================
def test_satislar_kapat_ac_sonrasi_durur(services, stoklu_bira, reopen):
    for _ in range(10):
        services.sales.quick_sale(stoklu_bira)
    services.sales.reverse_last_sale()

    yeni = reopen(services)
    try:
        assert yeni.products.get(stoklu_bira)["current_stock"] == 39
        assert yeni.db.scalar("SELECT SUM(total_amount) FROM sales") == 9 * 8000
        assert yeni.db.check_invariants(deep=True) == []
    finally:
        yeni.close()
