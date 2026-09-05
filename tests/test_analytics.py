"""Analiz, panel ve akıllı gruplama.

Korunan ayrım: KESİN sepet verisi (Sepetli Satış) ile TAHMİNİ gruplar
(Hızlı Satıştan türetilen) birbirine ASLA karışmaz.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def dukkan(services, bira, cips_urunu):
    """Gerçekçi bir gün: bira 48 adet 50 TL, cips 20 adet 30 TL maliyetli."""
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)
    services.inventory.set_initial_stock(cips_urunu, 20, unit_cost=3000)
    return services


def _bugun(services) -> str:
    return services.settings.calendar().today()


# ===================== Dönem özetleri ====================================
def test_bugun_ozeti_ciro_ve_kar(dukkan, bira, cips_urunu):
    for _ in range(3):
        dukkan.sales.quick_sale(bira)          # 80 TL satış, 50 TL maliyet
    dukkan.sales.quick_sale(cips_urunu)        # 50 TL satış, 30 TL maliyet

    ozet = dukkan.analytics.today()
    assert ozet.revenue == 3 * 8000 + 5000
    assert ozet.cost == 3 * 5000 + 3000
    assert ozet.gross_profit == 29000 - 18000
    assert ozet.item_count == 4
    assert ozet.sale_count == 4
    assert round(ozet.margin_percent, 1) == 37.9


def test_geri_alinan_satis_ciroyu_dusurur(dukkan, bira):
    satis = dukkan.sales.quick_sale(bira)
    dukkan.sales.quick_sale(bira)
    dukkan.sales.reverse_sale(satis.sale_id)

    ozet = dukkan.analytics.today()
    assert ozet.revenue == 8000, "geri alınan satış ciroda görünmez"
    assert ozet.item_count == 1
    assert ozet.sale_count == 1


def test_ozet_satis_gecmisiyle_birebir_uyusur(dukkan, bira, cips_urunu):
    """Panel toplamları HAM işlem geçmişiyle aynı olmalıdır."""
    for _ in range(7):
        dukkan.sales.quick_sale(bira)
    dukkan.sales.quick_sale(cips_urunu)
    dukkan.sales.reverse_last_sale()

    ozet = dukkan.analytics.today()
    ham = dukkan.db.query_one(
        "SELECT COALESCE(SUM(total_amount),0) AS ciro, "
        "       COALESCE(SUM(total_cost),0) AS maliyet, "
        "       COALESCE(SUM(item_count),0) AS adet FROM sales"
    )
    assert ozet.revenue == ham["ciro"]
    assert ozet.cost == ham["maliyet"]
    assert ozet.item_count == ham["adet"]
    assert dukkan.db.check_invariants(deep=True) == []


def test_bos_gun_sifir_doner(dukkan):
    ozet = dukkan.analytics.today()
    assert (ozet.revenue, ozet.cost, ozet.item_count) == (0, 0, 0)
    assert ozet.margin_percent == 0.0


# ===================== Kırılımlar ========================================
def test_en_cok_satanlar(dukkan, bira, cips_urunu):
    for _ in range(5):
        dukkan.sales.quick_sale(bira)
    dukkan.sales.quick_sale(cips_urunu)

    gun = _bugun(dukkan)
    top = dukkan.analytics.top_products(gun, gun)
    assert [t["name"] for t in top] == [
        "Tuborg Gold 50 cl Kutu", "Ruffles Original 105 g",
    ]
    assert top[0]["adet"] == 5
    assert top[0]["kar"] == 5 * 3000


def test_kategori_kirilimi(dukkan, bira):
    bira_kat = dukkan.db.scalar("SELECT id FROM categories WHERE name = 'Bira'")
    dukkan.products.update(bira, category_id=bira_kat)
    dukkan.sales.quick_sale(bira)

    gun = _bugun(dukkan)
    kirilim = dukkan.analytics.by_group(gun, gun, "category")
    assert [(k["name"], k["ciro"]) for k in kirilim] == [("Bira", 8000)]


def test_marka_kirilimi(dukkan, bira):
    dukkan.sales.quick_sale(bira)
    gun = _bugun(dukkan)
    kirilim = dukkan.analytics.by_group(gun, gun, "brand")
    assert [k["name"] for k in kirilim] == ["Tuborg"]


def test_bilinmeyen_gruplama_reddedilir(dukkan):
    gun = _bugun(dukkan)
    with pytest.raises(ValueError):
        dukkan.analytics.by_group(gun, gun, "renk")


def test_saat_kirilimi_gun_baslangicindan_baslar(dukkan, bira):
    dukkan.sales.quick_sale(bira)
    gun = _bugun(dukkan)
    saatler = dukkan.analytics.by_hour(gun, gun)

    assert len(saatler) == 24
    assert saatler[0][0] == 0, "varsayılan gün başlangıcı gece yarısıdır"
    assert sum(ciro for _, ciro, _ in saatler) == 8000


def test_haftanin_gunu_kirilimi(dukkan, bira):
    dukkan.sales.quick_sale(bira)
    gun = _bugun(dukkan)
    gunler = dukkan.analytics.by_weekday(gun, gun)
    assert len(gunler) == 7
    assert sum(ciro for _, ciro, _ in gunler) == 8000


# ===================== Stok analizleri ===================================
def test_stok_degeri_bagli_sermayeyi_verir(dukkan, bira, cips_urunu):
    assert dukkan.analytics.stock_value() == 48 * 5000 + 20 * 3000


def test_yavas_hareket_eden_urunler(dukkan, bira, cips_urunu):
    """Uzun süredir satılmayan, stoğu olan ürünler bağlı sermayeyle listelenir."""
    from app.core.clock import now_utc

    # İki ürün de 60 gün önce stoğa girmiş sayılsın.
    eski = now_utc() - 60 * 86400
    with dukkan.db.transaction() as conn:
        conn.execute("UPDATE products SET first_stocked_at_utc = ?", (eski,))

    dukkan.sales.quick_sale(bira)          # bira BUGÜN satıldı

    yavaslar = dukkan.analytics.slow_movers(days=45)
    adlar = [y["name"] for y in yavaslar]
    assert "Ruffles Original 105 g" in adlar, "45 gündür satılmadı"
    assert "Tuborg Gold 50 cl Kutu" not in adlar, "bugün satıldı, yavaş değil"
    assert dukkan.analytics.dead_capital(days=45) == 20 * 3000


def test_yeni_tanimlanan_urun_yavas_sayilmaz(dukkan, cips_urunu):
    """Dün tanımlanmış bir ürün, 45 gündür satılmıyor diye suçlanmamalı."""
    yavaslar = dukkan.analytics.slow_movers(days=45)
    assert [y["name"] for y in yavaslar] == []


def test_urun_performansi_ve_stok_gunu(dukkan, bira):
    for _ in range(30):
        dukkan.sales.quick_sale(bira)

    performans = dukkan.analytics.product_performance(bira, days=30)
    assert performans["adet"] == 30
    assert performans["gunluk_ortalama"] == 1.0
    assert dukkan.analytics.days_of_stock(bira, days=30) == 18.0


def test_hic_satilmayan_urunun_stok_gunu_bilinmez(dukkan, cips_urunu):
    assert dukkan.analytics.days_of_stock(cips_urunu) is None


# ===================== Panel =============================================
def test_panel_tek_cagrida_her_seyi_verir(dukkan, bira):
    dukkan.sales.quick_sale(bira)
    panel = dukkan.analytics.dashboard()

    assert panel.today.revenue == 8000
    assert panel.stock_value > 0
    assert panel.attention["kritik"] >= 0
    assert [t["name"] for t in panel.top_products] == ["Tuborg Gold 50 cl Kutu"]


def test_panelde_sayilmamis_urun_kritik_sayilmaz(services):
    services.products.quick_create("Sayılmamış", 1000, initial_stock=None)
    panel = services.analytics.dashboard()
    assert panel.attention["henuz_sayilmadi"] == 1
    assert panel.attention["kritik"] == 0
    assert any("henüz sayılmadı" in u for u in panel.advisories)


# ===================== Akıllı gruplama (TAHMİNİ) =========================
def test_gruplama_ham_satislari_degistirmez(dukkan, bira):
    for _ in range(4):
        dukkan.sales.quick_sale(bira)
    onceki = dukkan.db.query("SELECT * FROM sales ORDER BY id")

    dukkan.grouping.rebuild_for_day(_bugun(dukkan))

    sonraki = dukkan.db.query("SELECT * FROM sales ORDER BY id")
    assert [dict(r) for r in onceki] == [dict(r) for r in sonraki], (
        "gruplama HAM satışlara tek bir yazma bile yapmaz"
    )


def test_hizli_ardisik_satislar_tek_gruba_dusar(dukkan, bira, cips_urunu):
    for _ in range(3):
        dukkan.sales.quick_sale(bira)
    dukkan.sales.quick_sale(cips_urunu)

    grup_sayisi = dukkan.grouping.rebuild_for_day(_bugun(dukkan))
    assert grup_sayisi == 1

    gruplar = dukkan.grouping.groups_for_day(_bugun(dukkan))
    assert gruplar[0]["sale_count"] == 4
    assert gruplar[0]["kind"] == "ESTIMATED", "asla EXACT değil"
    assert gruplar[0]["algorithm_version"] == "esik-v1"


def test_uzun_ara_yeni_grup_baslatir(dukkan, bira):
    dukkan.sales.quick_sale(bira)
    dukkan.sales.quick_sale(bira)
    # İkinci satışı 5 dakika ileri al: eşik 20 saniyedir.
    son = dukkan.sales.last_sale()
    with dukkan.db.transaction() as conn:
        conn.execute(
            "UPDATE sales SET created_at_utc = created_at_utc + 300 WHERE id = ?",
            (son["id"],),
        )

    assert dukkan.grouping.rebuild_for_day(_bugun(dukkan)) == 2


def test_f4_kesin_sinir_koyar(dukkan, bira, cips_urunu):
    dukkan.sales.quick_sale(bira)
    dukkan.grouping.mark_new_customer()          # F4
    dukkan.sales.quick_sale(cips_urunu)

    assert dukkan.grouping.rebuild_for_day(_bugun(dukkan)) == 2
    gruplar = dukkan.grouping.groups_for_day(_bugun(dukkan))
    assert gruplar[1]["manual_boundary"] == 1


def test_gruplama_yeniden_calistirilabilir(dukkan, bira):
    for _ in range(3):
        dukkan.sales.quick_sale(bira)
    gun = _bugun(dukkan)

    dukkan.grouping.rebuild_for_day(gun)
    ilk = len(dukkan.grouping.groups_for_day(gun))
    dukkan.grouping.rebuild_for_day(gun)
    assert len(dukkan.grouping.groups_for_day(gun)) == ilk, "gruplar çoğalmaz"


def test_grup_urunleri_toplanmis_gosterilir(dukkan, bira):
    for _ in range(3):
        dukkan.sales.quick_sale(bira)
    gun = _bugun(dukkan)
    dukkan.grouping.rebuild_for_day(gun)

    grup = dukkan.grouping.groups_for_day(gun)[0]
    urunler = dukkan.grouping.group_items(grup["id"])
    assert [(u["name"], u["adet"]) for u in urunler] == [
        ("Tuborg Gold 50 cl Kutu", 3),
    ]


def test_grup_istatistikleri_tahmini_olarak_isaretlidir(dukkan, bira):
    dukkan.sales.quick_sale(bira)
    gun = _bugun(dukkan)
    dukkan.grouping.rebuild_for_day(gun)

    istatistik = dukkan.grouping.stats_for_day(gun)
    assert istatistik["tahmini"] is True, "arayüz bunu AÇIKÇA söylemek zorunda"
    assert istatistik["grup_sayisi"] == 1


def test_kesin_sepet_sayisi_yalnizca_sepetli_satisi_sayar(dukkan, bira):
    from app.services.cart_service import Cart

    dukkan.sales.quick_sale(bira)                # hızlı satış — TAHMİNİ
    sepet = Cart()
    dukkan.cart.add_product(sepet, bira, quantity=2)
    dukkan.cart.checkout(sepet)                  # sepetli satış — KESİN

    gun = _bugun(dukkan)
    assert dukkan.analytics.exact_basket_count(gun, gun) == 1, (
        "hızlı satışlar kesin sepet sayılmaz"
    )
