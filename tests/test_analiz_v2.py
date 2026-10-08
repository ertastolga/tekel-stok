"""Analiz V2 (V1.2 M8a): dönemler, genel bakış, eğilimler, ürünler, sepetler, kâr.

Korunan sözler:
  * hazır dönemler ve karşılaştırmalar plan §6.3'e uyar (Pazartesi haftası,
    ayın aynı günleri, 366 günden uzunda karşılaştırma yok),
  * dönem ölçüleri geri almayı orijinal güne yazar; iadeler geri alma gününe,
  * kesin sepet ölçüleri yalnızca Sepetli Satış'ı sayar,
  * kategori kırılımı üst kategoriye toplar ve "Kategorisiz"i gösterir,
  * ürün çiftleri gerçek sepetlerin sayımıdır (en az destek, geri alınan sepet
    ve Hızlı Satış sayılmaz),
  * maliyet katmanları defterden: kirli (maliyeti bilinmeyen) bir girişle
    karışmış havuzdan yapılan satış "güvenilir" sayılmaz (D-19); başlık kârı
    yalnızca güvenilir pay ≥ %95 iken,
  * V2 sonuçları önbelleklidir ve veri değişince yenilenir.
"""
from __future__ import annotations

import pytest

from app.analytics import donemler as dn
from app.analytics import kar
from app.analytics.urunler import KATEGORISIZ
from app.core.models import PaymentMethod
from app.services.analytics_service import GUNLUK, HAFTALIK, SAATLIK
from app.services.cart_service import Cart

BIRA_DOLABI = 1


def _sepet(services, *kalemler, yontem=PaymentMethod.CASH):
    sepet = Cart()
    for urun, adet in kalemler:
        services.cart.add_product(sepet, urun, quantity=adet)
    return services.cart.checkout(sepet, payment_method=yontem)


def _urun(services, ad, fiyat, kategori=None):
    kategori_id = (services.db.scalar("SELECT id FROM categories WHERE name = ? "
                                      "AND parent_id IS NOT NULL", (kategori,))
                   if kategori else None)
    return services.products.quick_create(ad, fiyat, location_id=BIRA_DOLABI,
                                          category_id=kategori_id)


def _alis(services, pid, adet, maliyet):
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, pid, adet, maliyet)
    services.purchases.commit(fis)


# ===================== Dönemler ============================================
def test_hazir_donemler():
    bugun = "2026-09-01"                                       # Salı
    beklenen = {
        dn.BUGUN: ("2026-09-01", "2026-09-01"),
        dn.DUN: ("2026-08-31", "2026-08-31"),
        dn.SON_7: ("2026-08-26", "2026-09-01"),
        dn.BU_HAFTA: ("2026-08-31", "2026-09-01"),
        dn.GECEN_HAFTA: ("2026-08-24", "2026-08-30"),
        dn.BU_AY: ("2026-09-01", "2026-09-01"),
        dn.GECEN_AY: ("2026-08-01", "2026-08-31"),
    }
    for tur, (bas, bit) in beklenen.items():
        donem = dn.hazir(tur, bugun)
        assert (donem.baslangic, donem.bitis) == (bas, bit), tur
    assert dn.ozel("2026-09-10", "2026-09-01").baslangic == "2026-09-01", "ters tarih düzelir"


def test_karsilastirmalar():
    gun = dn.hazir(dn.BUGUN, "2026-09-01")
    assert [(d.baslangic, d.ad) for d in dn.karsilastirmalar(gun)] == [
        ("2026-08-31", "Önceki gün"), ("2026-08-25", "Geçen haftanın aynı günü")]
    son7 = dn.hazir(dn.SON_7, "2026-09-01")
    assert [(d.baslangic, d.bitis) for d in dn.karsilastirmalar(son7)] == [
        ("2026-08-19", "2026-08-25")]
    ay = dn.hazir(dn.BU_AY, "2026-03-31")
    assert [(d.baslangic, d.bitis) for d in dn.karsilastirmalar(ay)] == [
        ("2026-02-01", "2026-02-28")], "kısa ay sonuna sabitlenir"
    gecen = dn.hazir(dn.GECEN_AY, "2026-03-15")
    assert [(d.baslangic, d.bitis) for d in dn.karsilastirmalar(gecen)] == [
        ("2026-01-01", "2026-01-31")]
    assert dn.karsilastirmalar(dn.ozel("2025-01-01", "2026-01-02")) == []
    assert dn.degisim_yuzdesi(150, 100) == 50.0 and dn.degisim_yuzdesi(5, 0) is None


# ===================== Genel bakış =========================================
def test_genel_bakis_ve_gunler_arasi_iade(duvar_saati, services, bira, cips_urunu):
    services.inventory.set_initial_stock(bira, 50, unit_cost=5000)
    duvar_saati.git(2026, 10, 5, 15)
    kart = _sepet(services, (bira, 2), yontem=PaymentMethod.CARD)       # 160 TL
    _sepet(services, (bira, 1), (cips_urunu, 2))                        # 80 + 100 nakit
    services.sales.quick_sale(bira)                                     # HIZLI 80, yöntemsiz
    duvar_saati.git(2026, 10, 6, 15)
    services.sales.reverse_sale(kart.sale_id)                           # ertesi gün iade

    a = services.analytics
    pzt = a.genel(dn.ozel("2026-10-05", "2026-10-05"))
    assert (pzt.ciro, pzt.islem, pzt.adet) == (26000, 2, 4)
    assert (pzt.sepet_sayisi, pzt.ortalama_sepet, pzt.sepet_basina_urun) == (1, 18000, 3.0)
    assert pzt.odemeler.satirlar() == [("NAKİT", 18000), ("KART", 0),
                                       ("Kaydedilmemiş", 8000)]
    sali = a.genel(dn.ozel("2026-10-06", "2026-10-06"))
    assert sali.ciro == 0, "iade orijinal güne yazılır"
    assert sali.iadeler.kart == 16000, "kasa sayımı için iade geri alma gününde"


# ===================== Eğilimler ===========================================
def test_egilimler(duvar_saati, services, bira):
    services.inventory.set_initial_stock(bira, 50, unit_cost=5000)
    for gun, saat in ((5, 10), (6, 21), (13, 21)):                      # Pzt, Sal, Sal
        duvar_saati.git(2026, 10, gun, saat)
        services.sales.quick_sale(bira)
    a = services.analytics
    donem = dn.ozel("2026-10-05", "2026-10-14")
    gunluk = a.egilim(GUNLUK, donem)
    assert len(gunluk) == 10 and [n.ciro for n in gunluk if n.ciro] == [8000, 8000, 8000]
    assert gunluk[3].ciro == 0, "boş gün sıfırla doldurulur"
    haftalik = a.egilim(HAFTALIK, donem)
    assert [(n.anahtar, n.ciro) for n in haftalik] == [("2026-10-05", 16000),
                                                       ("2026-10-12", 8000)]
    saatlik = {int(n.anahtar): n.islem for n in a.egilim(SAATLIK, donem)}
    assert (saatlik[10], saatlik[21]) == (1, 2)
    gunler = a.egilim("HAFTANIN_GUNU", donem)
    assert [(n.etiket, n.islem) for n in gunler if n.islem] == [("Pzt", 1), ("Sal", 2)]
    aylik = a.egilim("AYLIK", dn.ozel("2026-09-20", "2026-10-14"))
    assert [(n.etiket, n.ciro) for n in aylik] == [("Eyl 2026", 0), ("Eki 2026", 24000)]


# ===================== Ürünler =============================================
def test_urun_ve_kategori_kirilimi(duvar_saati, services):
    duvar_saati.git(2026, 10, 5, 15)
    bira = _urun(services, "Bira A", 1000, "Bira")
    raki = _urun(services, "Rakı A", 5000, "Rakı")
    serbest = _urun(services, "Kategorisiz Ürün", 300)
    _sepet(services, (bira, 5), (raki, 1), (serbest, 1))
    a = services.analytics
    donem = dn.ozel("2026-10-05", "2026-10-05")
    assert [u.ad for u in a.en_cok_satanlar(donem)][:1] == ["Bira A"]
    assert [u.ad for u in a.en_cok_satanlar(donem, ciroya_gore=True)][:1] == ["Bira A"]
    assert [u.ad for u in a.az_satanlar(donem)][0] in ("Rakı A", "Kategorisiz Ürün")
    kategoriler = a.kategori_kirilimi(donem)
    alkollu = next(k for k in kategoriler if k.ad == "Alkollü İçecekler")
    assert (alkollu.ciro, [c.ad for c in alkollu.alt]) == (10000, ["Bira", "Rakı"])
    assert any(k.ad == KATEGORISIZ and k.ciro == 300 for k in kategoriler)
    assert [m.ad for m in a.marka_kirilimi(donem)] == ["Markasız"]
    egilim = a.urun_egilimi(bira, dn.ozel("2026-10-04", "2026-10-05"))
    assert egilim == [("2026-10-04", 0, 0), ("2026-10-05", 5, 5000)]


# ===================== Sepetler ============================================
def test_urun_ciftleri_gercek_sepetlerden(duvar_saati, services):
    duvar_saati.git(2026, 10, 5, 15)
    bira = _urun(services, "Bira", 1000, "Bira")
    cips = _urun(services, "Cips", 500, "Cips")
    su = _urun(services, "Su", 100, "Su")
    for _ in range(3):
        _sepet(services, (bira, 1), (cips, 1), (cips, 1))
    _sepet(services, (bira, 1), (su, 1))
    geri = _sepet(services, (bira, 1), (cips, 1))
    services.sales.reverse_sale(geri.sale_id)                           # sayılmaz
    services.sales.quick_sale(bira)                                     # HIZLI: sayılmaz
    a = services.analytics
    donem = dn.ozel("2026-10-05", "2026-10-05")
    ciftler = a.urun_ciftleri(donem)
    assert [(c.a_ad, c.b_ad, c.birlikte, c.a_sepet, c.b_sepet) for c in ciftler] == [
        ("Bira", "Cips", 3, 4, 3)]
    assert ciftler[0].cumle() == "Cips alanların %100'i Bira de aldı (3 / 3 sepet)."
    assert a.urun_ciftleri(donem, en_az_destek=1)[-1].birlikte == 1
    kategoriler = a.kategori_ciftleri(donem)
    assert [({c.a_ad, c.b_ad}, c.birlikte) for c in kategoriler] == [
        ({"Alkollü İçecekler", "Atıştırmalık"}, 3)], "üst kategori düzeyinde"


# ===================== Kâr katmanları (D-19) ===============================
def test_maliyet_katmanlari(duvar_saati, services):
    duvar_saati.git(2026, 10, 5, 10)
    kirli = _urun(services, "Sayımla Gelen", 1000)
    temiz = _urun(services, "Alışla Gelen", 1000)
    bilinmez = _urun(services, "Hiç Alınmamış", 1000)
    sifirlanan = _urun(services, "Sıfırlanıp Alınan", 1000)
    for pid in (kirli, sifirlanan):
        oturum = services.counts.start([BIRA_DOLABI])
        services.counts.set_counted(oturum, pid, BIRA_DOLABI, 5)    # maliyet bilinmiyor
        services.counts.commit(oturum)
    _alis(services, kirli, 5, 500)
    _alis(services, temiz, 5, 500)
    services.sales.quick_sale(sifirlanan, 5)                        # havuz sıfırlandı
    _alis(services, sifirlanan, 5, 500)
    duvar_saati.git(2026, 10, 5, 15)
    for pid in (kirli, temiz, bilinmez, sifirlanan):
        services.sales.quick_sale(pid)

    satir = services.db.query_one(
        "SELECT is_estimated_cost, cost_total FROM sale_items WHERE product_id = ? "
        "ORDER BY id DESC LIMIT 1", (kirli,))
    assert (satir["is_estimated_cost"], satir["cost_total"]) == (0, 250), \
        "seyreltilmiş ortalama (5×0 + 5×500)/10 ama satırın kendi işareti 'kesin' der — " \
        "V1.1 yalnızca buna bakıyordu (D-19)"
    kapsam = services.analytics.maliyet_kapsami(dn.ozel("2026-10-05", "2026-10-05"))
    assert kapsam.guvenilir == kar.Katman(2000, 1000, 2), "temiz + sıfırlandıktan sonra"
    assert kapsam.tahmini.ciro == 1000, "V1.1 bunu 'kesin' sayıyordu (D-19)"
    assert kapsam.bilinmiyor.ciro == 1000 + 5000, "maliyetsiz satışlar"
    assert kapsam.guvenilir_oran < kar.BASLIK_ESIGI and kapsam.baslik_kari is None
    bos_gun = services.analytics.maliyet_kapsami(dn.ozel("2026-10-06", "2026-10-06"))
    assert bos_gun.baslik_kari is None and bos_gun.guvenilir_oran == 1.0


def test_baslik_kari_yuzde_95_ile(duvar_saati, services, bira):
    duvar_saati.git(2026, 10, 5, 10)
    _alis(services, bira, 50, 5000)
    for _ in range(3):
        services.sales.quick_sale(bira)
    kapsam = services.analytics.maliyet_kapsami(dn.ozel("2026-10-05", "2026-10-05"))
    assert kapsam.guvenilir_oran == 1.0
    assert kapsam.baslik_kari == 3 * (8000 - 5000)


# ===================== Önbellek ============================================
def test_onbellek_veri_degisince_yenilenir(duvar_saati, services, bira):
    duvar_saati.git(2026, 10, 5, 15)
    services.inventory.set_initial_stock(bira, 10, unit_cost=5000)
    donem = dn.ozel("2026-10-05", "2026-10-05")
    ilk = services.analytics.genel(donem)
    assert services.analytics.genel(donem) is ilk, "aynı veri: önbellekten"
    services.sales.quick_sale(bira)
    assert services.analytics.genel(donem).ciro == ilk.ciro + 8000


@pytest.mark.parametrize("tur", list(dn.DONEM_ADLARI))
def test_cephe_her_donemde_calisir(services, tur):
    a = services.analytics
    donem = a.donem(tur, "2026-10-01", "2026-10-05")
    assert a.genel(donem).ciro == 0
    assert a.maliyet_kapsami(donem).toplam_ciro == 0
