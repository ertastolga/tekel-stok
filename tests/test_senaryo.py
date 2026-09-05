"""Gerçek dükkân senaryosu — şartname §63'ün 25 adımı, uçtan uca.

Bu test tek başına V1'in kabul ölçütüdür: geçmiyorsa V1 bitmemiştir.

Her adım gerçek servis çağrılarıyla yapılır; hiçbir yerde doğrudan SQL ile
kestirme yoktur. Sonunda panel toplamlarının HAM işlem geçmişiyle birebir
uyuştuğu doğrulanır.
"""
from __future__ import annotations

from app.core.models import BarcodeType, MovementType
from app.services.cart_service import Cart

BIRA_UNIT = "8690504001492"
BIRA_KOLI = "8690504001508"
KOLA_UNIT = "8690504003007"


def test_gercek_dukkan_senaryosu(services, reopen, db_file):
    # --- 1) Uygulama açıldı: şema hazır, tutarlı --------------------------
    assert services.db.schema_version() >= 1
    assert services.db.check_invariants(deep=True) == []

    # --- 2) Fiziksel bölümler tanımlı ------------------------------------
    konumlar = {k["name"]: k["id"] for k in services.catalog.locations()}
    assert {"Bira Dolabı", "Meşrubat Dolabı", "Depo"} <= set(konumlar)
    bira_dolabi = konumlar["Bira Dolabı"]
    mesrubat = konumlar["Meşrubat Dolabı"]
    depo = konumlar["Depo"]

    # --- 3) Bira ürünü eklendi -------------------------------------------
    bira = services.products.quick_create(
        name="Tuborg Gold 50 cl Kutu",
        sale_price=8000,                     # 80 TL
        barcode=BIRA_UNIT,
        brand_name="Tuborg",
        location_id=bira_dolabi,
        initial_stock=None,                  # stok henüz bilinmiyor
    )
    assert services.products.get(bira)["stock_state"] == 4, "Henüz Sayılmadı"

    # --- 4) Adet ve koli barkodu -----------------------------------------
    services.barcodes.add_barcode(bira, BIRA_KOLI, BarcodeType.CASE, 24)
    assert services.barcodes.resolve(BIRA_UNIT).quantity == 1
    assert services.barcodes.resolve(BIRA_KOLI).quantity == 24

    # --- 5) İkinci içecek ürünü ------------------------------------------
    kola = services.products.quick_create(
        name="Coca-Cola 330 ml Kutu",
        sale_price=3000,
        barcode=KOLA_UNIT,
        brand_name="Coca-Cola",
        location_id=mesrubat,
        initial_stock=None,
    )

    # --- 6) Başlangıç stoğu ----------------------------------------------
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)   # 50 TL
    services.inventory.set_initial_stock(kola, 60, unit_cost=2000)   # 20 TL
    assert services.products.get(bira)["current_stock"] == 48
    assert services.products.get(bira)["stock_state"] == 0, "artık sayılmış"

    # --- 7) Koli barkoduyla mal girişi -----------------------------------
    eslesme = services.barcodes.resolve(BIRA_KOLI)
    fis = services.purchases.start_draft(invoice_no="IRS-001")
    services.purchases.add_line(
        fis, eslesme.product_id, eslesme.quantity, unit_cost=5000,
        barcode_used=eslesme.barcode, multiplier=eslesme.multiplier,
    )
    assert services.products.get(bira)["current_stock"] == 48, "taslak stoğu etkilemez"
    services.purchases.commit(fis)
    assert services.products.get(bira)["current_stock"] == 72, "48 + 1 koli (24)"

    # --- 8) Aynı biradan 10 hızlı okutma ---------------------------------
    for _ in range(10):
        eslesme = services.barcodes.resolve(BIRA_UNIT)
        services.sales.quick_sale(
            eslesme.product_id, eslesme.quantity,
            barcode_used=eslesme.barcode, multiplier=eslesme.multiplier,
        )
    assert services.products.get(bira)["current_stock"] == 62
    assert services.db.scalar(
        "SELECT COUNT(*) FROM sales WHERE entry_type = 'SALE'"
    ) == 10, "her okutma AYRI bir satış olayıdır"

    # --- 9) Son satış geri alındı ----------------------------------------
    services.sales.reverse_last_sale()
    assert services.products.get(bira)["current_stock"] == 63
    ciro_9_adim = services.analytics.today().revenue
    assert ciro_9_adim == 9 * 8000

    # --- 10) Sepetli satış ------------------------------------------------
    sepet = Cart()
    services.cart.add_product(sepet, bira, quantity=2)
    services.cart.add_product(sepet, kola, quantity=3)
    assert services.products.get(bira)["current_stock"] == 63, "sepet stoğu etkilemez"
    sepet_satisi = services.cart.checkout(sepet)
    assert sepet_satisi.item_count == 5
    assert services.products.get(bira)["current_stock"] == 61
    assert services.products.get(kola)["current_stock"] == 57

    # --- 11) Bira dolaptan rafa taşındı ----------------------------------
    stok_once = services.products.get(bira)["current_stock"]
    deger_once = services.products.get(bira)["stock_value"]
    hareket_once = services.db.scalar(
        "SELECT COUNT(*) FROM stock_movements WHERE product_id = ?", (bira,)
    )
    services.catalog.add_product_location(bira, depo)
    services.catalog.remove_product_location(bira, bira_dolabi)
    services.catalog.set_primary_location(bira, depo)

    # --- 12) Konum değişikliği TOPLAM STOĞU DEĞİŞTİRMEDİ ------------------
    assert services.products.get(bira)["current_stock"] == stok_once
    assert services.products.get(bira)["stock_value"] == deger_once
    assert services.db.scalar(
        "SELECT COUNT(*) FROM stock_movements WHERE product_id = ?", (bira,)
    ) == hareket_once, "konum değişimi stok hareketi ÜRETMEZ"
    assert {k["name"] for k in services.catalog.locations_of(bira)} == {"Depo"}

    # --- 13) Fiziksel sayım ----------------------------------------------
    # Bira artık YALNIZCA Depo'da; o bölümü saymak kapsamı tamamlar.
    oturum = services.counts.start([depo])
    services.counts.set_counted(oturum, bira, depo, 58)      # rafta 58 var
    assert services.counts.coverage_report(oturum) == [], "kapsam tam"

    # --- 14) Farktan düzeltme --------------------------------------------
    sonuc = services.counts.commit(oturum)
    assert sonuc.applied == [("Tuborg Gold 50 cl Kutu", -3)]
    assert services.products.get(bira)["current_stock"] == 58
    duzeltme = services.db.query_one(
        "SELECT * FROM stock_movements WHERE product_id = ? "
        "  AND movement_type = ? ORDER BY id DESC LIMIT 1",
        (bira, MovementType.COUNT_ADJUSTMENT),
    )
    assert duzeltme["quantity_delta"] == -3, "geçmiş ÜZERİNE YAZILMADI, hareket üretildi"

    # --- 15) Satış fiyatı değişti ----------------------------------------
    eski_satis = services.db.query_one(
        "SELECT * FROM sales WHERE entry_type = 'SALE' ORDER BY id LIMIT 1"
    )
    eski_kalem = services.sales.items(eski_satis["id"])[0]
    services.products.set_price(bira, 9000)                  # 80 -> 90 TL

    # --- 16) Yeni satış ---------------------------------------------------
    yeni_satis = services.sales.quick_sale(bira)
    assert yeni_satis.total_amount == 9000

    # --- 17) Eski satış ESKİ FİYATI korudu -------------------------------
    assert services.sales.items(eski_satis["id"])[0]["unit_price"] == 8000
    assert eski_kalem["unit_price"] == 8000
    assert services.sales.sale(eski_satis["id"])["total_amount"] == 8000

    # --- 18) Yeni fişle alış maliyeti değişti ----------------------------
    eski_kar = eski_satis["total_amount"] - eski_satis["total_cost"]
    fis2 = services.purchases.start_draft(invoice_no="IRS-002")
    services.purchases.add_line(fis2, bira, 24, unit_cost=7000)   # 50 -> 70 TL
    services.purchases.commit(fis2)

    # --- 19) Geçmiş kâr DEĞİŞMEDİ ----------------------------------------
    guncel = services.sales.sale(eski_satis["id"])
    assert guncel["total_cost"] == eski_satis["total_cost"]
    assert guncel["total_amount"] - guncel["total_cost"] == eski_kar
    assert services.sales.items(eski_satis["id"])[0]["cost_total"] == 5000

    # --- 20/21/22) Kapat, aç, veri yerinde -------------------------------
    beklenen_stok = services.products.get(bira)["current_stock"]
    beklenen_deger = services.products.get(bira)["stock_value"]
    beklenen_ciro = services.analytics.today().revenue
    beklenen_kar = services.analytics.today().gross_profit

    yeniden = reopen(services)
    try:
        assert yeniden.products.get(bira)["current_stock"] == beklenen_stok
        assert yeniden.products.get(bira)["stock_value"] == beklenen_deger
        assert yeniden.analytics.today().revenue == beklenen_ciro
        assert yeniden.barcodes.resolve(BIRA_KOLI).quantity == 24
        assert {k["name"] for k in yeniden.catalog.locations_of(bira)} == {"Depo"}
        assert yeniden.db.check_invariants(deep=True) == []

        # --- 23) Yedek alındı --------------------------------------------
        yedek = yeniden.backup.create_manual()
        bilgi = yeniden.backup.inspect(yedek)
        assert bilgi.product_count == 2

        # --- 24) Geri yükleme güvenli ------------------------------------
        yeniden.sales.quick_sale(bira)                   # yedekten sonra satış
        assert yeniden.products.get(bira)["current_stock"] == beklenen_stok - 1

        guvenlik = yeniden.backup.restore(yedek)
        assert guvenlik.exists(), "geri yükleme öncesi güvenlik kopyası alındı"
        assert yeniden.products.get(bira)["current_stock"] == beklenen_stok, (
            "yedekteki hâle dönüldü"
        )
        assert yeniden.db.check_invariants(deep=True) == []

        # --- 25) Panel toplamları HAM geçmişle birebir --------------------
        panel = yeniden.analytics.dashboard()
        ham = yeniden.db.query_one(
            "SELECT COALESCE(SUM(total_amount), 0) AS ciro, "
            "       COALESCE(SUM(total_cost), 0)   AS maliyet, "
            "       COALESCE(SUM(item_count), 0)   AS adet FROM sales"
        )
        assert panel.today.revenue == ham["ciro"] == beklenen_ciro
        assert panel.today.cost == ham["maliyet"]
        assert panel.today.gross_profit == beklenen_kar

        # Stok değeri de defterden yeniden üretilebilmeli.
        defter = yeniden.db.scalar(
            "SELECT COALESCE(SUM(value_delta), 0) FROM stock_movements "
            " WHERE product_id = ?", (bira,)
        )
        assert yeniden.products.get(bira)["stock_value"] == defter
    finally:
        yeniden.close()


def test_senaryo_sonunda_hicbir_finansal_kayit_silinmemis(services):
    """Geri alınan işlemler bile geçmişte DURUR."""
    bira = services.products.quick_create(
        "Test Bira", 8000, barcode=BIRA_UNIT, initial_stock=10, purchase_cost=5000
    )
    satis = services.sales.quick_sale(bira)
    services.sales.reverse_sale(satis.sale_id)

    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 5, unit_cost=5000)
    services.purchases.commit(fis)
    services.purchases.reverse(fis)

    # Orijinal kayıtlar duruyor, ters kayıtlar eklenmiş.
    assert services.db.scalar(
        "SELECT COUNT(*) FROM sales WHERE entry_type = 'SALE'"
    ) == 1
    assert services.db.scalar(
        "SELECT COUNT(*) FROM sales WHERE entry_type = 'SALE_REVERSAL'"
    ) == 1
    assert services.db.scalar("SELECT COUNT(*) FROM purchase_receipts") == 2
    assert services.products.get(bira)["current_stock"] == 10
    assert services.db.check_invariants(deep=True) == []
