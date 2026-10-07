"""Geri alma doğruluğu (V1.2 M1e): D-04, D-05, D-07, D-13, D-17, D-18, D-21.

Korunan sözler:
  * bir geri alma, dönem ölçülerine ORİJİNAL satışın gününde yansır; ödeme
    kovaları her gün ciroyla birebir uyuşur; o gün yapılan iadeler ayrıca
    görülür (kasa sayımı),
  * I23 iki yönlü ve maliyetli, I34 günlük özetin tüm alanlarını denetler —
    yanlış alarm vermez, gerçek bozulmayı yakalar,
  * geri alınmış satışlar saat/gün/sepet sayılarına girmez,
  * önbellek onarımı son satış damgasını geri alınmamış satışlardan kurar,
  * fiş geri alması: kendi satırları engel sayılmaz, ters sırayla çözülür,
    sonrasındaki satışlar yanlış alarm üretmez, ters fiş / taslak / tekrar
    geri alma reddedilir, tamamlanmış fişin satırı düzenlenemez.
"""
from __future__ import annotations

import random
from datetime import datetime

import pytest

from app.core.errors import FisGeriAlinamaz, FisZatenTamamlanmis
from app.core.models import MovementType, PaymentMethod, RefType
from app.services.cart_service import Cart


def _sepet_sat(services, urun, adet=1, yontem=PaymentMethod.CARD):
    sepet = Cart()
    services.cart.add_product(sepet, urun, quantity=adet)
    return services.cart.checkout(sepet, payment_method=yontem)


def _kova_toplami(kova) -> int:
    return kova.nakit + kova.kart + kova.veresiye + kova.diger + kova.kaydedilmemis


# ===================== D-04 / D-05: günler arası geri alma ==================
def test_gunler_arasi_kartli_geri_alma_orijinal_gunde_netlesir(
    duvar_saati, services, bira
):
    services.inventory.set_initial_stock(bira, 10, unit_cost=5000)
    duvar_saati.git(2026, 10, 5, 15)
    satis = _sepet_sat(services, bira, 2, PaymentMethod.CARD)
    duvar_saati.git(2026, 10, 6, 10)
    services.sales.reverse_sale(satis.sale_id)

    a = services.analytics
    for gun in ("2026-10-05", "2026-10-06"):
        assert a.summary(gun, gun).revenue == 0
        odeme = a.payment_breakdown(gun, gun)
        assert odeme.kart == 0, f"{gun}: V1.1 +160 / −160 gösteriyordu"
        assert _kova_toplami(odeme) == 0
    assert a.refunds("2026-10-06", "2026-10-06").kart == 16000, "kasadan iade"
    assert a.refunds("2026-10-05", "2026-10-05").kart == 0
    assert services.db.check_invariants(deep=True) == [], "I23 yanlış alarmı yok"


def test_gecmis_saat_gun_ve_sepet_sayilari_geri_alinani_saymaz(
    duvar_saati, services, bira
):
    services.inventory.set_initial_stock(bira, 10, unit_cost=5000)
    duvar_saati.git(2026, 10, 5, 15)
    kalan = _sepet_sat(services, bira)
    geri = _sepet_sat(services, bira)
    services.sales.reverse_sale(geri.sale_id)

    a = services.analytics
    saatler = dict((saat, (ciro, islem)) for saat, ciro, islem in a.by_hour(
        "2026-10-05", "2026-10-05"))
    assert saatler[15] == (8000, 1)
    gunler = {gun: (ciro, islem) for gun, ciro, islem in a.by_weekday(
        "2026-10-05", "2026-10-05")}
    assert gunler[datetime(2026, 10, 5).weekday()] == (8000, 1)
    assert a.exact_basket_count("2026-10-05", "2026-10-05") == 1
    assert a.basket_summary("2026-10-05", "2026-10-05").basket_count == 1
    assert kalan.total_amount == 8000


def test_rastgele_satis_ve_geri_almalarda_kovalar_her_gun_ciroyla_uyusur(
    duvar_saati, services, bira, cips_urunu
):
    rng = random.Random(20261007)
    services.inventory.set_initial_stock(bira, 500, unit_cost=5000)
    services.inventory.set_initial_stock(cips_urunu, 500, unit_cost=3000)
    gunler = [f"2026-10-{g:02d}" for g in range(1, 7)]
    satislar: list[int] = []
    iade_toplami = 0
    for gun_no, gun in enumerate(gunler, start=1):
        for adim in range(12):
            duvar_saati.git(2026, 10, gun_no, 9 + adim)
            if satislar and rng.random() < 0.3:
                hedef = satislar.pop(rng.randrange(len(satislar)))
                sonuc = services.sales.reverse_sale(hedef)
                iade_toplami += -sonuc.total_amount
                continue
            urun = rng.choice([bira, cips_urunu])
            if rng.random() < 0.4:
                satis = services.sales.quick_sale(urun, rng.randint(1, 3))
            else:
                yontem = rng.choice([PaymentMethod.CASH, PaymentMethod.CARD])
                satis = _sepet_sat(services, urun, rng.randint(1, 3), yontem)
            satislar.append(satis.sale_id)

    a = services.analytics
    for gun in gunler:
        ozet = a.summary(gun, gun)
        assert _kova_toplami(a.payment_breakdown(gun, gun)) == ozet.revenue, gun
        assert ozet.sale_count == services.db.scalar(
            "SELECT COUNT(*) FROM sales WHERE entry_type='SALE' AND is_reversed=0 "
            "  AND business_date = ?", (gun,)
        )
    assert _kova_toplami(a.refunds(gunler[0], gunler[-1])) == iade_toplami
    assert services.db.check_invariants(deep=True) == []


# ===================== I23 / I34 gerçek bozulmayı yakalar ==================
def _gunluk_satisli(duvar_saati, services, bira):
    services.inventory.set_initial_stock(bira, 10, unit_cost=5000)
    duvar_saati.git(2026, 10, 5, 15)
    _sepet_sat(services, bira, 2, PaymentMethod.CASH)
    assert services.db.check_invariants(deep=True) == []


@pytest.mark.parametrize(
    "bozma",
    [
        "DELETE FROM product_daily_sales",
        "UPDATE product_daily_sales SET cost = cost + 1",
        "INSERT INTO product_daily_sales(business_date, product_id, quantity, amount, "
        "  cost, sale_count) VALUES('2026-01-01', 1, 1, 100, 50, 1)",
    ],
    ids=["ozet_eksik", "maliyet", "satissiz_ozet"],
)
def test_I23_iki_yonlu_ve_maliyetli(duvar_saati, services, bira, bozma):
    _gunluk_satisli(duvar_saati, services, bira)
    services.db.execute(bozma)
    sorunlar = services.db.check_invariants(deep=True)
    assert any(s.startswith("I23") for s in sorunlar), sorunlar


@pytest.mark.parametrize(
    "alan", ["sale_count", "total_amount", "total_cost", "item_count",
             "cash_amount", "card_amount"],
)
def test_I34_gunluk_ozetin_her_alanini_denetler(duvar_saati, services, bira, alan):
    _gunluk_satisli(duvar_saati, services, bira)
    services.db.execute(f"UPDATE daily_sales_rollup SET {alan} = {alan} + 1")
    sorunlar = services.db.check_invariants(deep=True)
    assert any(s.startswith("I34") for s in sorunlar), sorunlar


# ===================== D-13: önbellek onarımı =============================
def test_onarim_son_satis_damgasini_geri_alinmamislardan_kurar(
    duvar_saati, services, bira, cips_urunu
):
    services.inventory.set_initial_stock(bira, 10, unit_cost=5000)
    services.inventory.set_initial_stock(cips_urunu, 10, unit_cost=3000)
    duvar_saati.git(2026, 10, 5, 10)
    ilk = services.sales.quick_sale(bira)
    duvar_saati.git(2026, 10, 5, 12)
    son = services.sales.quick_sale(bira)
    tek = services.sales.quick_sale(cips_urunu)
    services.sales.reverse_sale(son.sale_id)
    services.sales.reverse_sale(tek.sale_id)

    services.db.execute("UPDATE products SET last_sale_at_utc = 999")
    services.db.recompute_caches()

    beklenen = int(datetime(2026, 10, 5, 10).timestamp())
    assert services.products.get(bira)["last_sale_at_utc"] == beklenen
    assert services.products.get(cips_urunu)["last_sale_at_utc"] is None, "NULL olur"
    assert ilk.total_amount == 8000


# ===================== Fiş geri alma: D-17, D-18, D-07, D-21 ===============
def _fis(services, satirlar):
    fis = services.purchases.start_draft()
    for urun, adet, maliyet in satirlar:
        services.purchases.add_line(fis, urun, adet, unit_cost=maliyet)
    services.purchases.commit(fis)
    return fis


def test_geri_alinan_fisten_sonraki_satis_I31_yanlis_alarmi_vermez(services, bira):
    services.inventory.set_initial_stock(bira, 5, unit_cost=5000)
    fis = _fis(services, [(bira, 10, 6000)])
    services.purchases.reverse(fis)
    services.sales.quick_sale(bira)                  # geri almadan SONRA
    assert services.db.check_invariants() == [], "sığ denetim temiz (V1.1: I31)"
    assert services.db.check_invariants(deep=True) == []


def test_I31_kanitsiz_ters_kaydi_hala_yakalar(services, bira):
    services.inventory.set_initial_stock(bira, 5, unit_cost=5000)
    fis = _fis(services, [(bira, 10, 6000)])
    services.sales.quick_sale(bira)                  # fişten sonra satış
    orijinal = services.db.scalar(
        "SELECT id FROM stock_movements WHERE ref_type='RECEIPT' AND ref_id = ?", (fis,)
    )
    stamp = services.settings.calendar().stamp()
    with services.db.transaction() as conn:           # servis korumasını atlayan kayıt
        services.inventory.apply_movement(
            conn, bira, MovementType.PURCHASE_REVERSAL, -10, stamp,
            ref_type=RefType.RECEIPT, ref_id=fis, reverses_movement_id=orijinal,
        )
    assert any(s.startswith("I31") for s in services.db.check_invariants())


def test_ayni_urunun_iki_satirli_fisi_geri_alinir_ve_tam_doner(services, bira):
    services.inventory.set_initial_stock(bira, 4, unit_cost=5000)
    once = services.products.get(bira)
    fis = _fis(services, [(bira, 10, 6000), (bira, 5, 7000)])
    assert len(services.purchases.lines(fis)) == 2

    onizleme = services.purchases.reversal_preview(fis)
    assert onizleme.allowed, "V1.1: kendi satırı engelliyordu"
    ters = services.purchases.reverse(fis)

    sonra = services.products.get(bira)
    assert sonra["current_stock"] == once["current_stock"]
    assert sonra["stock_value"] == once["stock_value"]
    ters_hareketler = services.db.query(
        "SELECT reverses_movement_id FROM stock_movements "
        " WHERE ref_type='RECEIPT' AND ref_id = ? ORDER BY id", (ters,)
    )
    orijinaller = [
        r["id"] for r in services.db.query(
            "SELECT id FROM stock_movements WHERE ref_type='RECEIPT' AND ref_id = ? "
            " ORDER BY id", (fis,)
        )
    ]
    assert [r["reverses_movement_id"] for r in ters_hareketler] == orijinaller[::-1], (
        "ters sırayla (LIFO) çözüldü"
    )
    assert services.db.check_invariants(deep=True) == []


def test_ters_fis_ve_tekrar_geri_alma_reddedilir_hicbir_sey_yazilmaz(services, bira):
    services.inventory.set_initial_stock(bira, 5, unit_cost=5000)
    fis = _fis(services, [(bira, 10, 6000)])
    ters = services.purchases.reverse(fis)
    fis_sayisi = services.db.scalar("SELECT COUNT(*) FROM purchase_receipts")
    satir_sayisi = services.db.scalar("SELECT COUNT(*) FROM purchase_receipt_lines")

    onizleme = services.purchases.reversal_preview(ters)
    assert not onizleme.allowed and "geri almadır" in onizleme.reason
    with pytest.raises(FisGeriAlinamaz):
        services.purchases.reverse(ters)
    with pytest.raises(FisGeriAlinamaz) as bilgi:
        services.purchases.reverse(fis)
    assert "daha önce" in bilgi.value.message
    assert not services.purchases.reversal_preview(fis).allowed

    assert services.db.scalar("SELECT COUNT(*) FROM purchase_receipts") == fis_sayisi
    assert services.db.scalar("SELECT COUNT(*) FROM purchase_receipt_lines") == satir_sayisi
    assert services.db.check_invariants(deep=True) == []


def test_onizleme_atlansa_bile_satirlar_ilgisiz_fise_baglanmaz(
    services, bira, cips_urunu, monkeypatch
):
    """V1.1: 0 satırlık INSERT...SELECT önceki ``lastrowid``'i taşıyordu."""
    from app.core.models import ReversalPreview

    services.inventory.set_initial_stock(bira, 5, unit_cost=5000)
    fis = _fis(services, [(bira, 10, 6000)])
    ters = services.purchases.reverse(fis)
    ilgisiz = _fis(services, [(cips_urunu, 3, 2000)])     # son eklenen fiş
    satir_sayisi = services.db.scalar("SELECT COUNT(*) FROM purchase_receipt_lines")

    monkeypatch.setattr(
        services.purchases, "reversal_preview",
        lambda rid: ReversalPreview(allowed=True, receipt_id=rid),
    )
    with pytest.raises(FisGeriAlinamaz):
        services.purchases.reverse(ters)
    assert services.db.scalar(
        "SELECT COUNT(*) FROM purchase_receipt_lines WHERE receipt_id = ?", (ilgisiz,)
    ) == 1
    assert services.db.scalar("SELECT COUNT(*) FROM purchase_receipt_lines") == satir_sayisi


def test_taslak_fis_onizlemesi_nedenini_soyler(services, bira):
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 3, unit_cost=5000)
    onizleme = services.purchases.reversal_preview(fis)
    assert not onizleme.allowed and "Taslak" in onizleme.reason


def test_tamamlanmis_fisin_satiri_duzenlenemez(services, bira):
    fis = _fis(services, [(bira, 10, 6000)])
    satir = services.purchases.lines(fis)[0]
    with pytest.raises(FisZatenTamamlanmis):
        services.purchases.set_line_quantity(satir["id"], 99)
    with pytest.raises(FisZatenTamamlanmis):
        services.purchases.set_line_cost(satir["id"], 1)
    sonra = services.purchases.lines(fis)[0]
    assert (sonra["quantity"], sonra["unit_cost"]) == (10, 6000)
    assert services.db.check_invariants(deep=True) == []


# ===================== V1.1 örnek verisi ===================================
@pytest.mark.parametrize("fikstur", ["v1_1_kopya", "v1_0_kopya"])
def test_eski_surum_ornek_verisi_derin_denetimde_temiz(fikstur, request):
    """V1.1 örnek verisi I23 ve I31 yanlış alarmlarını TAŞIYORDU (M0a kanıtı)."""
    from app.core.db import open_database
    from app.services.container import build_services

    svc = build_services(open_database(request.getfixturevalue(fikstur)))
    try:
        assert svc.db.check_invariants() == []
        assert svc.db.check_invariants(deep=True) == []
        a = svc.analytics
        for gun in ("2026-09-01", "2026-09-02", "2026-09-03"):
            assert _kova_toplami(a.payment_breakdown(gun, gun)) == a.summary(gun, gun).revenue
    finally:
        svc.close()
