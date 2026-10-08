"""Sorgu planları (V1.2 M11, plan §9): sıcak işlemler büyük tabloları taramaz.

Duvar saati ölçümleri ``-m perf`` altındadır; varsayılan süit bunun
BELİRLENİMCİ vekilini korur: her sıcak işlemin çalıştırdığı GERÇEK SQL
(``set_trace_callback`` ile yakalanır) ``EXPLAIN QUERY PLAN`` ile incelenir ve
büyüyen bir tabloyu indekssiz tarayan (``SCAN <tablo>``) ifade bulunursa test
düşer. Bilinçli istisnalar aşağıda GEREKÇESİYLE listelenir.

Ayrıca maliyet katmanı sorgusunun şema v6 kısmi indekslerini kullandığı ve
açılıştaki sığ denetimin geçmişi yalnızca bilinçli (sıralı) taramalarla
okuduğu doğrulanır.
"""
from __future__ import annotations

import re

import pytest

from app.analytics import donemler as dn
from app.analytics import kar
from app.core.models import PaymentMethod
from app.services.analytics_service import AYLIK, GUNLUK, HAFTALIK, HAFTANIN_GUNU, SAATLIK
from app.services.cart_service import Cart
from conftest import BIRA_BARKOD

#: Satışla, okutmayla ya da satır sayısıyla BÜYÜYEN tablolar: bunlarda
#: indekssiz tarama, yıllar içinde yavaşlayan bir ekran demektir. (Ürünler ve
#: kategoriler dükkânın büyüklüğüyle sınırlıdır — Ürün Ara'nın çok sözcüklü
#: araması onları bilerek tarar; alış fişleri, sayım oturumları ve toplu fiyat
#: grupları yılda yüzlerce büyür ve satır başına indeksli alt sorgularla okunur.)
BUYUYEN_TABLOLAR = frozenset({
    "sales", "sale_items", "stock_movements", "price_history", "product_daily_sales",
    "purchase_receipt_lines", "audit_log", "count_lines", "count_line_locations",
    "cart_drafts", "cart_draft_lines",
})

#: (işlem, SQL parçası) → gerekçe. Parça, ifadenin metninde aynen geçmelidir.
ISTISNALAR = {
    ("gecmis", "ORDER BY s.id DESC LIMIT"):
        "Son satışlar: rowid üzerinde GERİYE tarama, LIMIT kadar satırda durur "
        "(100k veride 0,5 ms).",
    ("son_satisi_geri_al", "ORDER BY id DESC LIMIT 1"):
        "Son satış: rowid üzerinde GERİYE tarama, ilk SATIŞ satırında durur.",
    ("sig_denetim", "r.movement_type = 'PURCHASE_REVERSAL'"):
        "I31: yalnızca TERS kayıtları taşıyan kısmi benzersiz indeksin geçişi "
        "(satışların ~%1'i; 100k veride 2 856 kayıt, ~5 ms).",
    ("sig_denetim", "NOT INDEXED"):
        "Ürün önbelleği ↔ defter toplamları (I1, I2, I28): bilinçli SIRALI tarama; "
        "indeks sırasıyla gezmekten ~9 kat hızlı (100k veride 0,13 s).",
}

_TABLO_ADI = re.compile(r"\b(?:FROM|JOIN|UPDATE|INTO)\s+(\w+)(?:\s+(?:AS\s+)?(\w+))?", re.I)
_DENETLENEN = ("SELECT", "WITH", "UPDATE", "DELETE", "INSERT")


def _taramalar(db, sql: str) -> list[str]:
    """``sql`` planındaki büyüyen tablo taramaları (takma adlar çözülür).

    INSERT planında görünen ve ifadede ADI GEÇMEYEN tablo taramaları, üst
    tabloya satır eklenince ertelenmiş yabancı anahtar sayacını düşürmek
    içindir; SQLite bunları sayaç sıfırken (her zaman) atlar (``OP_FkIfZero``).
    """
    ekleme = sql.lstrip().upper().startswith("INSERT")
    takma = {}
    for tablo, ad in _TABLO_ADI.findall(sql):
        takma[tablo.lower()] = tablo.lower()
        if ad:
            takma.setdefault(ad.lower(), tablo.lower())
    bulunan = []
    for satir in db.conn.execute("EXPLAIN QUERY PLAN " + sql).fetchall():
        ayrinti = satir[3]
        # "SCAN t", "SCAN t USING INDEX i" ve "SCAN t USING COVERING INDEX i"
        # hepsi TAM geçiştir (tablo ya da indeks); yalnızca SEARCH aralıklıdır.
        if not ayrinti.startswith("SCAN "):
            continue
        ad = ayrinti.split()[1].lower()
        if ekleme and ad not in takma:
            continue
        tablo = takma.get(ad, ad)
        if tablo in BUYUYEN_TABLOLAR:
            bulunan.append(f"{ayrinti} [{tablo}]")
    return bulunan


def _calistir_ve_incele(services, ad: str, islev) -> list[str]:
    kayit: list[str] = []
    services.db.conn.set_trace_callback(kayit.append)
    try:
        islev()
    finally:
        services.db.conn.set_trace_callback(None)
    sorunlar = []
    for sql in kayit:
        if not sql.lstrip().upper().startswith(_DENETLENEN):
            continue
        if any(i == ad and parca in sql for (i, parca) in ISTISNALAR):
            continue
        for tarama in _taramalar(services.db, sql):
            sorunlar.append(f"{tarama} :: {' '.join(sql.split())[:200]}")
    return sorunlar


@pytest.fixture
def veri(duvar_saati, services, bira, cips_urunu):
    """Her yolun gerçekten çalışacağı kadar veri: alış, sepet, hızlı satış, iade."""
    duvar_saati.git(2026, 10, 5, 10)
    for pid in (bira, cips_urunu):
        fis = services.purchases.start_draft()
        services.purchases.add_line(fis, pid, 20, 4000)
        services.purchases.commit(fis)
    for yontem in (PaymentMethod.CASH, PaymentMethod.CARD):
        sepet = Cart()
        services.cart.add_product(sepet, bira, quantity=2)
        services.cart.add_product(sepet, cips_urunu)
        services.cart.checkout(sepet, payment_method=yontem)
    services.sales.quick_sale(bira)
    duvar_saati.git(2026, 10, 6, 11)
    services.sales.reverse_sale(services.sales.recent(1)[0]["id"])
    return {"bira": bira, "cips": cips_urunu,
            "gun": dn.ozel("2026-10-05", "2026-10-06"),
            "yil": dn.ozel("2025-10-07", "2026-10-06")}


def _gecmis(services, v):
    """Geçmiş ekranı (M12a): tarihsiz, tarihli, ödeme süzgeçli, sonraki sayfa,
    tarihli özet ve ayrıntı."""
    from app.services.sale_service import SatisFiltresi

    gunluk = SatisFiltresi(baslangic=v["gun"].baslangic, bitis=v["gun"].bitis)
    ilk = services.sales.history()
    return (services.sales.recent(100), ilk, services.sales.history(gunluk),
            services.sales.history(SatisFiltresi(odeme=PaymentMethod.CARD)),
            services.sales.history(once_id=ilk[0]["id"]),
            services.sales.history_summary(gunluk), services.sales.detail(ilk[0]["id"]))


def _islemler(services, v) -> dict:
    a = services.analytics
    d, yil = v["gun"], v["yil"]

    def odeme():
        sepet = Cart()
        services.cart.add_product(sepet, v["bira"])
        services.cart.autosave(sepet)                 # Sepetli Satış böyle saklar
        services.cart.checkout(sepet, payment_method=PaymentMethod.CASH)

    def bekletme():
        sepet = Cart()
        services.cart.add_product(sepet, v["cips"])
        services.cart.resume_parked(services.cart.park(sepet))

    return {
        # KASA
        "barkod_cozumle": lambda: services.barcodes.resolve(BIRA_BARKOD),
        "urun_ara": lambda: services.products.search_for_sale("tuborg kutu"),
        "sepete_ekle": lambda: services.cart.add_product(Cart(), v["bira"]),
        "odeme": odeme,
        "hizli_satis": lambda: services.sales.quick_sale(v["cips"]),
        "son_satisi_geri_al": lambda: (services.sales.quick_sale(v["cips"]),
                                       services.sales.reverse_last_sale()),
        "bekletme": bekletme,
        # YÖNETİM
        "urun_listesi": lambda: (services.products.search(limit=100),
                                 services.products.search(text="tuborg", limit=100)),
        "fiyat_listesi": lambda: services.pricing.listele(limit=500),
        "kategori_agaci": lambda: services.categories.tree(),
        "gecmis": lambda: _gecmis(services, v),
        # ANALİZ (önbellek her testte boş: sorgular gerçekten çalışır)
        "analiz_genel": lambda: (a.genel(d), a.genel(yil)),
        "analiz_egilim": lambda: [a.egilim(t, yil) for t in
                                  (SAATLIK, HAFTANIN_GUNU, GUNLUK, HAFTALIK, AYLIK)],
        "analiz_urunler": lambda: (a.en_cok_satanlar(yil), a.en_cok_satanlar(yil, True),
                                   a.az_satanlar(yil), a.kategori_kirilimi(yil),
                                   a.marka_kirilimi(yil), a.urun_egilimi(v["bira"], yil)),
        "analiz_sepet": lambda: (a.urun_ciftleri(yil, 1), a.kategori_ciftleri(yil, 1)),
        "analiz_odeme": lambda: (a.payment_breakdown(d.baslangic, d.bitis),
                                 a.refunds(d.baslangic, d.bitis),
                                 a.basket_summary(d.baslangic, d.bitis)),
        "analiz_kar": lambda: a.maliyet_kapsami(yil),
        # Açılış
        "sig_denetim": lambda: services.db.check_invariants(),
    }


ISLEM_ADLARI = ["barkod_cozumle", "urun_ara", "sepete_ekle", "odeme", "hizli_satis",
                "son_satisi_geri_al", "bekletme", "urun_listesi", "fiyat_listesi",
                "kategori_agaci", "gecmis", "analiz_genel", "analiz_egilim", "analiz_urunler",
                "analiz_sepet", "analiz_odeme", "analiz_kar", "sig_denetim"]


def test_islem_listesi_eksiksiz(services, veri):
    assert sorted(_islemler(services, veri)) == sorted(ISLEM_ADLARI)


#: 100k satışlık ölçüm verisinde ``PRAGMA optimize``'ın yazdığı GERÇEK
#: planlayıcı istatistikleri (M11). Dükkânda da tablolar böyle çarpıktır:
#: taslakların neredeyse hepsi CHECKED_OUT, hareketlerin çoğu sıfırlanma.
URETIM_ISTATISTIGI = [
    ("cart_draft_lines", "ix_cart_draft_lines_draft", "11 1"),
    ("cart_draft_lines", "sqlite_autoindex_cart_draft_lines_1", "11 1 1"),
    ("cart_drafts", "ix_cart_drafts_open", "59462 59462 59462"),
    ("cart_drafts", "ix_cart_drafts_parked", "1168 1"),
    ("count_line_locations", "ix_count_line_locations_session", "240 20 1"),
    ("count_line_locations", "sqlite_autoindex_count_line_locations_1", "240 20 1 1"),
    ("count_lines", "ix_count_lines_product", "15006 2"),
    ("count_lines", "ix_count_lines_session", "15006 1251"),
    ("count_lines", "sqlite_autoindex_count_lines_1", "15006 1251 1"),
    ("count_session_locations", "sqlite_autoindex_count_session_locations_1", "12 1 1"),
    ("price_history", "ix_price_history_batch", "10000 10000"),
    ("price_history", "ix_price_history_product", "10180 1 1 1"),
    ("product_barcodes", "ix_barcodes_product", "10496 1 1"),
    ("product_barcodes", "ux_barcode_active", "10496 1"),
    ("product_barcodes", "ux_barcode_gtin_active", "10496 1"),
    ("product_daily_sales", "ix_pds_product", "251018 26 1"),
    ("product_daily_sales", "product_daily_sales", "251018 230 1"),
    ("product_locations", "ix_product_locations_loc", "10000 1250 1250"),
    ("product_locations", "ux_product_location_active", "10000 1 1"),
    ("product_locations", "ux_product_primary_location", "10000 1"),
    ("products", "ix_products_brand", "10000 250 250 1"),
    ("products", "ix_products_cat", "10000 295 295 1"),
    ("products", "ix_products_last_sale", "10000 2"),
    ("products", "ix_products_name_norm", "10000 1"),
    ("products", "ix_products_stock_state", "10000 2500 1"),
    ("purchase_receipt_lines", "ix_rlines_product", "2344 2 1"),
    ("purchase_receipt_lines", "ix_rlines_receipt", "2344 15"),
    ("purchase_receipt_lines", "sqlite_autoindex_purchase_receipt_lines_1", "2344 15 1"),
    ("sale_items", "ix_sale_items_product", "298634 30 1"),
    ("sale_items", "ix_sale_items_sale", "298634 3"),
    ("sale_items", "sqlite_autoindex_sale_items_1", "298634 3 1"),
    ("sales", "ix_sales_bdate", "100203 92 1"),
    ("sales", "ix_sales_created", "100203 1"),
    ("sales", "ix_sales_dow_hour", "99216 14174 1013"),
    ("sales", "ux_sales_one_reversal", "987 1"),
    ("stock_movements", "ix_moves_bdate", "311052 285"),
    ("stock_movements", "ix_moves_pool_reset", "181561 45 1"),
    ("stock_movements", "ix_moves_product", "311052 32 1"),
    ("stock_movements", "ix_moves_ref", "311052 77763 4"),
    ("stock_movements", "ix_moves_tainting", "1730 3 1"),
    ("stock_movements", "ux_moves_one_reversal", "2856 1"),
]


def _uretim_istatistigini_yukle(db) -> None:
    """Planlayıcıya büyük dükkân verisinin istatistiklerini verir (SQLite bu
    tablonun elle yazılmasını destekler; ``ANALYZE sqlite_schema`` yeniden okutur)."""
    conn = db.conn
    conn.execute("ANALYZE")                         # sqlite_stat1 oluşsun
    conn.execute("DELETE FROM sqlite_stat1")
    indeksler = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    conn.executemany("INSERT INTO sqlite_stat1(tbl, idx, stat) VALUES(?, ?, ?)",
                     [s for s in URETIM_ISTATISTIGI if s[1] in indeksler])
    conn.commit()
    conn.execute("ANALYZE sqlite_schema")


@pytest.mark.parametrize("istatistik", ["yok", "uretim"])
@pytest.mark.parametrize("ad", ISLEM_ADLARI)
def test_sicak_islem_buyuyen_tabloyu_taramaz(services, veri, ad, istatistik):
    """Yeni kurulum (istatistik yok) ve yıllanmış dükkân (gerçek istatistik)."""
    if istatistik == "uretim":
        _uretim_istatistigini_yukle(services.db)
    sorunlar = _calistir_ve_incele(services, ad, _islemler(services, veri)[ad])
    assert sorunlar == [], "\n".join(sorunlar)


def test_istisnalar_gercekten_kullaniliyor(services, veri):
    """Ölü istisna kalmasın: her istisna ilgili işlemde gerçekten bir SQL'e uyar."""
    islemler = _islemler(services, veri)
    for (ad, parca) in ISTISNALAR:
        kayit: list[str] = []
        services.db.conn.set_trace_callback(kayit.append)
        try:
            islemler[ad]()
        finally:
            services.db.conn.set_trace_callback(None)
        assert any(parca in sql for sql in kayit), (ad, parca)


def test_tarama_dedektoru_gercek_taramayi_yakalar(services, veri):
    """Dedektörün kendisi: indekssiz bir sorgu ve takma ad yakalanır."""
    assert _taramalar(services.db, "SELECT * FROM sale_items i WHERE i.unit_price > 0")
    assert _taramalar(services.db, "SELECT COUNT(*) FROM stock_movements NOT INDEXED")
    assert not _taramalar(services.db, "SELECT * FROM sales WHERE id = 1")
    assert not _taramalar(services.db, "SELECT * FROM products")      # katalog tablosu
    assert _taramalar(services.db, "SELECT parked_at_utc FROM cart_drafts WHERE kind = "
                                   "'PARKED' ORDER BY id DESC LIMIT 200"), "V1.2 M3b sorgusu"


@pytest.mark.parametrize("istatistik", [False, True])
def test_maliyet_katmani_kismi_indeksleri_kullanir(services, veri, istatistik):
    """İstatistik yazıldıktan sonra da (``PRAGMA optimize`` / ANALYZE): 100k
    veride istatistikle planlayıcı genel indekse kayıyor ve 10 kat yavaşlıyordu."""
    if istatistik:
        services.db.conn.execute("ANALYZE")
    plan = " | ".join(r[3] for r in services.db.conn.execute(
        "EXPLAIN QUERY PLAN " + kar._KATMAN_SQL, ("2026-10-01", "2026-10-06")))
    assert "SEARCH r USING INDEX ix_moves_pool_reset" in plan, plan
    assert "SEARCH x USING INDEX ix_moves_tainting" in plan, plan
    assert "ix_sales_bdate" in plan, plan


V6_INDEKSLERI = {"ix_moves_pool_reset", "ix_moves_tainting", "ix_cart_drafts_acik",
                 "ix_cart_drafts_parked", "ix_cart_draft_lines_draft", "ix_count_lines_product"}


def _indeksler(db) -> set[str]:
    return {r[0] for r in db.query("SELECT name FROM sqlite_master WHERE type = 'index'")}


def test_v6_indeksleri_yeni_kurulumda_ve_v1_1_guncellemesinde(services, v1_1_kopya):
    from app.core.db import open_database

    assert V6_INDEKSLERI <= _indeksler(services.db)
    db = open_database(v1_1_kopya)
    try:
        assert V6_INDEKSLERI <= _indeksler(db)
        assert db.check_invariants(deep=True) == []
    finally:
        db.close()


def test_bekletme_sirasi_ve_sayim_denetimi_indeks_kullanir(services):
    """İstatistiksiz (yeni kurulum) veride de: bekletme sırası kısmi indeksle,
    I27'nin temel sayım araması ürün indeksiyle yapılır."""
    plan = " | ".join(r[3] for r in services.db.conn.execute(
        "EXPLAIN QUERY PLAN SELECT parked_at_utc FROM cart_drafts WHERE kind = 'PARKED' "
        "AND parked_at_utc IS NOT NULL AND parked_at_utc >= 0 "
        "ORDER BY parked_at_utc DESC LIMIT 200"))
    assert "ix_cart_drafts_parked" in plan, plan
    plan = " | ".join(r[3] for r in services.db.conn.execute(
        "EXPLAIN QUERY PLAN SELECT 1 FROM count_lines cl WHERE cl.product_id = 7 "
        "AND cl.is_baseline = 1"))
    assert "ix_count_lines_product" in plan, plan
