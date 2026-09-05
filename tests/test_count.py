"""Stok sayımı: kısmi konum kapsamı, alt toplamlar, temel (ilk) sayım.

Bu modülün koruduğu en tehlikeli senaryo: bir ürün iki yerde bulunurken tek
konumun sayılması. Toplam stokla karşılaştırılırsa devasa bir SAHTE fark
üretir ve stoğu bozar. Kural: kapsam tam değilse hiçbir hareket yazılmaz.
"""
from __future__ import annotations

import pytest

from app.core.errors import AcikSayimVar, SayimZatenTamamlanmis
from app.core.models import CoverageState, StockState

BIRA_DOLABI = 1
MESRUBAT_DOLABI = 2
KASA_ONU = 5
DEPO = 8


@pytest.fixture
def kola(services):
    """Coca-Cola: hem Meşrubat Dolabı'nda hem Depo'da, toplam 40 adet."""
    pid = services.products.quick_create(
        "Coca-Cola 330 ml Kutu", sale_price=3000, initial_stock=40,
        purchase_cost=2000, location_id=MESRUBAT_DOLABI,
    )
    services.catalog.add_product_location(pid, DEPO)
    return pid


@pytest.fixture
def tek_yerli(services):
    """Yalnızca Bira Dolabı'nda bulunan ürün — yaygın ve basit hâl."""
    return services.products.quick_create(
        "Efes Malt 50 cl", sale_price=7000, initial_stock=34,
        purchase_cost=4500, location_id=BIRA_DOLABI,
    )


# ===================== Kısmi kapsam koruması =============================
def test_iki_yerli_urun_tek_konum_sayilinca_duzeltilmez(services, kola):
    """EN KRİTİK TEST: 12 adet bulundu ama toplam 40; -28 SAHTE fark yazılmamalı."""
    oturum = services.counts.start([MESRUBAT_DOLABI])
    services.counts.set_counted(oturum, kola, MESRUBAT_DOLABI, 12)

    sonuc = services.counts.commit(oturum)

    assert sonuc.applied == [], "hiçbir düzeltme uygulanmadı"
    assert [ad for ad, _ in sonuc.skipped_partial] == ["Coca-Cola 330 ml Kutu"]
    assert sonuc.skipped_partial[0][1] == ["Depo"], "hangi yer eksik, söylenir"
    assert services.products.get(kola)["current_stock"] == 40, "stok BİT DÜZEYİNDE aynı"
    assert services.db.scalar(
        "SELECT COUNT(*) FROM stock_movements WHERE movement_type = 'COUNT_ADJUSTMENT'"
    ) == 0
    assert services.db.check_invariants(deep=True) == []


def test_ikinci_konum_da_sayilinca_duzeltme_uygulanir(services, kola):
    """'Depo'yu da Say' → kapsam tamamlanır → düzeltme yapılabilir."""
    oturum = services.counts.start([MESRUBAT_DOLABI])
    services.counts.set_counted(oturum, kola, MESRUBAT_DOLABI, 12)

    services.counts.add_location(oturum, DEPO)
    services.counts.set_counted(oturum, kola, DEPO, 25)

    sonuc = services.counts.commit(oturum)

    assert sonuc.skipped_partial == []
    assert sonuc.applied == [("Coca-Cola 330 ml Kutu", -3)], "12 + 25 = 37, fark -3"
    assert services.products.get(kola)["current_stock"] == 37
    assert services.db.check_invariants(deep=True) == []


def test_konum_alt_toplamlari_toplanir_uzerine_yazilmaz(services, kola):
    oturum = services.counts.start([MESRUBAT_DOLABI, DEPO])
    services.counts.set_counted(oturum, kola, MESRUBAT_DOLABI, 12)
    services.counts.set_counted(oturum, kola, DEPO, 25)

    satir = services.counts.lines(oturum)[0]
    assert satir["counted_qty"] == 37, "alt toplamlar TOPLANIR"
    yerler = {r["name"]: r["counted_qty"] for r in
              services.counts.line_locations(oturum, kola)}
    assert yerler == {"Meşrubat Dolabı": 12, "Depo": 25}


def test_barkodla_sayim_konum_bazinda_birer_birer_artar(services, kola):
    oturum = services.counts.start([MESRUBAT_DOLABI, DEPO])
    for _ in range(12):
        services.counts.count_scan(oturum, kola, MESRUBAT_DOLABI)
    for _ in range(25):
        services.counts.count_scan(oturum, kola, DEPO)

    assert services.counts.lines(oturum)[0]["counted_qty"] == 37


def test_tek_yerli_urun_normal_sayilir(services, tek_yerli):
    """Yaygın hâl bozulmadı: tek konumlu ürün tek konum sayımıyla düzeltilir."""
    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 31)

    sonuc = services.counts.commit(oturum)
    assert sonuc.applied == [("Efes Malt 50 cl", -3)]
    assert services.products.get(tek_yerli)["current_stock"] == 31
    assert services.db.check_invariants(deep=True) == []


def test_tum_dukkan_sayiminda_her_urun_kapsam_icindedir(services, kola, tek_yerli):
    oturum = services.counts.start(scope="ALL")
    services.counts.set_counted(oturum, kola, MESRUBAT_DOLABI, 37)
    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 34)

    sonuc = services.counts.commit(oturum)
    assert sonuc.skipped_partial == []
    assert ("Coca-Cola 330 ml Kutu", -3) in sonuc.applied
    assert services.products.get(kola)["current_stock"] == 37


def test_rafsiz_urun_konum_sayiminda_duzeltilmez(services):
    """Hiç konumu olmayan ürün yalnızca 'Tüm Dükkân' sayımında düzeltilebilir."""
    pid = services.products.quick_create("Rafsız", 1000, initial_stock=10)
    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, pid, BIRA_DOLABI, 7)

    sonuc = services.counts.commit(oturum)
    assert sonuc.applied == []
    assert [ad for ad, _ in sonuc.skipped_partial] == ["Rafsız"]
    assert services.products.get(pid)["current_stock"] == 10


def test_oturum_sirasinda_konum_eklenirse_kapsam_dusurulur(services, tek_yerli):
    """Sayım sürerken ürün başka bir rafa da konursa kapsam artık tam değildir."""
    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 34)
    services.catalog.add_product_location(tek_yerli, DEPO)

    sonuc = services.counts.commit(oturum)
    assert sonuc.applied == []
    assert [ad for ad, _ in sonuc.skipped_partial] == ["Efes Malt 50 cl"]


def test_kapsam_raporu_onay_oncesi_uyarir(services, kola):
    oturum = services.counts.start([MESRUBAT_DOLABI])
    services.counts.set_counted(oturum, kola, MESRUBAT_DOLABI, 12)

    rapor = services.counts.coverage_report(oturum)
    assert rapor == [("Coca-Cola 330 ml Kutu", ["Depo"])]


# ===================== Sayım sırasında stok değişimi =====================
def test_sayim_sirasinda_satilan_urun_atlanir(services, tek_yerli):
    """Hayalet düzeltme koruması: satıştan doğan fark, sayım farkı sanılmamalı."""
    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 34)

    services.sales.quick_sale(tek_yerli)          # sayım sürerken satış

    sonuc = services.counts.commit(oturum)
    assert sonuc.applied == []
    assert sonuc.skipped_changed == ["Efes Malt 50 cl"]
    assert services.products.get(tek_yerli)["current_stock"] == 33, (
        "satışın etkisi duruyor, üstüne sahte düzeltme yazılmadı"
    )
    assert services.db.check_invariants(deep=True) == []


# ===================== Düzeltme kayıtları ================================
def test_fark_gecmisi_uzerine_yazmaz_hareket_uretir(services, tek_yerli):
    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 31)
    services.counts.commit(oturum)

    hareket = services.inventory.ledger(tek_yerli)[0]
    assert hareket["movement_type"] == "COUNT_ADJUSTMENT"
    assert hareket["quantity_delta"] == -3
    assert hareket["balance_after"] == 31

    satir = services.counts.lines(oturum)[0]
    assert satir["system_qty_at_entry"] == 34
    assert satir["system_qty_final"] == 34
    assert satir["counted_qty"] == 31
    assert satir["difference"] == -3
    assert satir["adjustment_movement_id"] == hareket["id"]
    assert satir["coverage_state"] == CoverageState.FULL


def test_sayim_ortalamayi_korur(services, tek_yerli):
    """Sayım MİKTARI düzeltir; birim maliyeti değiştirmemelidir."""
    onceki = services.inventory.average_cost(tek_yerli)
    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 40)   # +6
    services.counts.commit(oturum)

    assert services.inventory.average_cost(tek_yerli) == onceki == 4500
    assert services.products.get(tek_yerli)["stock_value"] == 40 * 4500


def test_sifir_fark_hareket_uretmez(services, tek_yerli):
    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 34)
    sonuc = services.counts.commit(oturum)

    assert sonuc.applied == []
    assert services.db.scalar(
        "SELECT COUNT(*) FROM stock_movements WHERE movement_type = 'COUNT_ADJUSTMENT'"
    ) == 0
    assert services.counts.lines(oturum)[0]["difference"] == 0


def test_sayilmayan_urunler_bildirilir(services, tek_yerli):
    services.products.quick_create(
        "Sayılmayan Bira", 7000, initial_stock=5, location_id=BIRA_DOLABI
    )
    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 34)

    sonuc = services.counts.commit(oturum)
    assert sonuc.uncounted == ["Sayılmayan Bira"]
    assert services.products.get(tek_yerli)["current_stock"] == 34


def test_buyuk_fark_onceden_uyarir_kucuk_fark_uyarmaz(services, tek_yerli):
    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 33)   # -1
    assert services.counts.large_differences(oturum) == []

    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 4)    # -30
    assert services.counts.large_differences(oturum) == [("Efes Malt 50 cl", -30)]


# ===================== Temel (ilk) sayım =================================
def test_ilk_sayim_urunu_baslatir_ve_uyari_uretmez(services):
    """Sayılmamış üründe fark beklenen şeydir; büyük fark uyarısı çıkmaz."""
    pid = services.products.quick_create(
        "Hiç Sayılmamış", 5000, initial_stock=None, location_id=BIRA_DOLABI
    )
    assert services.products.get(pid)["stock_state"] == StockState.NOT_COUNTED

    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, pid, BIRA_DOLABI, 30)
    assert services.counts.large_differences(oturum) == [], (
        "ilk sayım büyük fark uyarısı üretmez"
    )

    sonuc = services.counts.commit(oturum)
    urun = services.products.get(pid)
    assert sonuc.baseline_count == 1
    assert urun["current_stock"] == 30
    assert urun["stock_initialized_at_utc"] is not None
    assert urun["stock_initialized_by"] == "COUNT"
    assert urun["stock_state"] == StockState.NORMAL
    assert services.counts.lines(oturum)[0]["is_baseline"] == 1
    assert services.db.check_invariants(deep=True) == []


def test_maliyeti_bilinmeyen_urun_hata_degil_uyaridir(services):
    """Hiç alış fişi görmemiş, sayımla stoğa alınmış ürünün maliyeti bilinmez.

    Bu bir veri BOZULMASI değildir; ``check_invariants`` temiz kalmalı, uyarı
    ``advisories()`` altında iş diliyle çıkmalıdır.
    """
    pid = services.products.quick_create(
        "Maliyeti Bilinmeyen", 5000, initial_stock=None, location_id=BIRA_DOLABI
    )
    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, pid, BIRA_DOLABI, 30)
    services.counts.commit(oturum)

    urun = services.products.get(pid)
    assert urun["current_stock"] == 30 and urun["stock_value"] == 0
    assert services.db.check_invariants(deep=True) == [], "bozulma yok"

    uyarilar = services.db.advisories()
    assert any("alış fiyatı hiç girilmemiş" in u for u in uyarilar)


def test_baslatmadan_once_satilan_urun_ilk_sayimda_dogru_duzelir(services):
    """Sistem -4, sayılan 30 → düzeltme +34 (sıfıra göre değil, sisteme göre)."""
    pid = services.products.quick_create(
        "Önce Satıldı", 5000, initial_stock=None, location_id=BIRA_DOLABI
    )
    for _ in range(4):
        services.sales.quick_sale(pid)
    assert services.products.get(pid)["current_stock"] == -4

    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, pid, BIRA_DOLABI, 30)
    sonuc = services.counts.commit(oturum)

    assert sonuc.applied == [("Önce Satıldı", 34)], "o satışlar gerçekten raftan çıktı"
    urun = services.products.get(pid)
    assert urun["current_stock"] == 30
    assert services.counts.lines(oturum)[0]["is_baseline"] == 1

    hareket = services.db.query_one(
        "SELECT * FROM stock_movements WHERE product_id = ? "
        " AND movement_type = 'COUNT_ADJUSTMENT'", (pid,)
    )
    assert hareket["fill_quantity"] == 4, "açığı kapatan 4 adet değere girmez"
    assert services.db.check_invariants(deep=True) == []


# ===================== Oturum kuralları ==================================
def test_ayni_anda_tek_sayim_olabilir(services, tek_yerli):
    services.counts.start([BIRA_DOLABI])
    with pytest.raises(AcikSayimVar):
        services.counts.start([DEPO])


def test_iptal_edilen_sayim_stogu_etkilemez(services, tek_yerli):
    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 5)
    services.counts.cancel(oturum)

    assert services.products.get(tek_yerli)["current_stock"] == 34
    assert services.counts.open_session() is None
    assert services.db.check_invariants(deep=True) == []


def test_tamamlanmis_sayim_yeniden_onaylanamaz(services, tek_yerli):
    oturum = services.counts.start([BIRA_DOLABI])
    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 31)
    services.counts.commit(oturum)

    with pytest.raises(SayimZatenTamamlanmis):
        services.counts.commit(oturum)
    assert services.products.get(tek_yerli)["current_stock"] == 31


def test_sayim_taslagi_yeniden_baslatmaya_dayanir(services, tek_yerli, reopen):
    oturum = services.counts.start([BIRA_DOLABI], blind=True)
    services.counts.set_counted(oturum, tek_yerli, BIRA_DOLABI, 31)

    yeni = reopen(services)
    try:
        acik = yeni.counts.open_session()
        assert acik is not None and acik["id"] == oturum
        assert acik["blind"] == 1
        assert yeni.counts.lines(oturum)[0]["counted_qty"] == 31
        assert yeni.products.get(tek_yerli)["current_stock"] == 34, (
            "taslak sayım KENDİLİĞİNDEN uygulanmaz"
        )
        yeni.counts.commit(oturum)
        assert yeni.products.get(tek_yerli)["current_stock"] == 31
    finally:
        yeni.close()
