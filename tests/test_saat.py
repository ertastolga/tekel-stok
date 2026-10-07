"""Saat dikişi (clock seam): servisler değişmeden zaman yönetilebilir.

Korunan sözler:
  * üretimde sağlayıcı yoktur; gerçek saat okunur,
  * ``use_clock`` bloğu boyunca adla içe aktarılmış ``now_utc``/``local_now``
    kullanan HER servis aynı saati görür,
  * blok bittiğinde (hata olsa bile) gerçek saate dönülür.
"""
from __future__ import annotations

import time
from datetime import datetime

import pytest

from app.core import clock
from app.core.models import PaymentMethod
from app.services.cart_service import Cart
from fakes import SabitDuvarSaati


def test_saglayici_yokken_gercek_saat_okunur():
    once = time.time()
    assert abs(clock.now_utc() - once) <= 2
    assert abs((clock.local_now() - datetime.now()).total_seconds()) <= 2
    a = clock.monotonic()
    assert clock.monotonic() >= a


def test_use_clock_cikista_geri_alinir_hata_olsa_bile():
    saat = SabitDuvarSaati(datetime(2030, 1, 1, 12, 0, 0))
    with pytest.raises(RuntimeError):
        with clock.use_clock(yerel=saat):
            assert clock.local_now().year == 2030
            raise RuntimeError("blok içinde hata")
    assert clock.local_now().year != 2030


def test_ic_ice_use_clock_onceki_saati_geri_yukler():
    dis = SabitDuvarSaati(datetime(2031, 5, 5, 10, 0, 0))
    ic = SabitDuvarSaati(datetime(2032, 6, 6, 11, 0, 0))
    with clock.use_clock(yerel=dis):
        with clock.use_clock(yerel=ic):
            assert clock.local_now().year == 2032
        assert clock.local_now().year == 2031


def test_tekduze_saat_saglanabilir():
    deger = [100.0]
    with clock.use_clock(tekduze=lambda: deger[0]):
        assert clock.monotonic() == 100.0
        deger[0] = 160.5
        assert clock.monotonic() == 160.5


def test_satis_geri_alma_denetim_ve_urun_damgalari_saati_izler(
    duvar_saati, services, bira
):
    duvar_saati.git(2026, 9, 1, 14, 30)
    sonuc = services.sales.quick_sale(bira)
    satis = services.sales.sale(sonuc.sale_id)
    assert satis["business_date"] == "2026-09-01"
    assert satis["local_hour"] == 14
    assert satis["created_at_utc"] == int(datetime(2026, 9, 1, 14, 30).timestamp())

    duvar_saati.git(2026, 9, 2, 9, 0)                 # ertesi gün geri alma
    services.sales.reverse_sale(sonuc.sale_id)
    ters = services.db.query_one(
        "SELECT business_date FROM sales WHERE entry_type='SALE_REVERSAL'"
    )
    assert ters["business_date"] == "2026-09-02"

    denetim = services.db.query_one(
        "SELECT created_at_utc FROM audit_log ORDER BY id DESC LIMIT 1"
    )
    assert denetim["created_at_utc"] == int(datetime(2026, 9, 2, 9, 0).timestamp())
    assert services.settings.calendar().today() == "2026-09-02"


def test_sepet_taslagi_ve_yedek_adi_saati_izler(duvar_saati, services, bira):
    duvar_saati.git(2026, 9, 3, 18, 45, 7)
    sepet = Cart()
    services.cart.add_product(sepet, bira, quantity=1)
    taslak = services.cart.save_draft(sepet)
    satir = services.db.query_one(
        "SELECT updated_at_utc FROM cart_drafts WHERE id = ?", (taslak,)
    )
    assert satir["updated_at_utc"] == int(datetime(2026, 9, 3, 18, 45, 7).timestamp())

    yol = services.backup.create_manual()
    assert "20260903_184507" in yol.name


def test_gunler_arasi_senaryo_kurulabilir(duvar_saati, services, bira):
    """M1 kusur testleri (D-04 vb.) bu yolla gerçek servislerle kurulur."""
    services.inventory.set_initial_stock(bira, 10, unit_cost=5000)
    duvar_saati.git(2026, 9, 1, 15)
    sepet = Cart()
    services.cart.add_product(sepet, bira, quantity=2)
    satis = services.cart.checkout(sepet, payment_method=PaymentMethod.CARD)
    duvar_saati.git(2026, 9, 2, 10)
    services.sales.reverse_sale(satis.sale_id)
    gunler = [
        r["business_date"]
        for r in services.db.query("SELECT business_date FROM sales ORDER BY id")
    ]
    assert gunler == ["2026-09-01", "2026-09-02"]
