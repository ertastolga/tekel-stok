"""Sepet bütünlüğü (V1.2 M1d): fiyat kayması (D-02) ve taslak dayanıklılığı (D-03).

Korunan sözler:
  * ekranda görünen = ödemesi alınan = kaydedilen tutar; fiyat sepete
    eklendikten sonra değişirse satış YAZILMAZ ve hiçbir şey yarım kalmaz,
  * fiyat ASLA sessizce düzeltilmez (``apply_current_prices`` açık eylemdir),
  * taslak yazısı veriyi "değişti" saymaz (otomatik yedeği tetiklemez),
  * kapanmış taslağa yazılmaz; boşalan sepetin taslağı iptal edilir,
  * yedek geri yüklendikten sonra ESKİ sepet yeni veriye yazılamaz.
"""
from __future__ import annotations

import pytest

from app.core.errors import EskiOturumSepeti, FiyatDegisti
from app.core.models import PaymentMethod
from app.services.cart_service import (
    SORUN_FIYAT_DEGISTI,
    SORUN_FIYATSIZ,
    SORUN_PASIF,
    Cart,
)


def _satis_sayisi(services) -> int:
    return services.db.scalar("SELECT COUNT(*) FROM sales")


# ===================== D-02: fiyat kayması =================================
def test_fiyat_degisince_dogrulama_bildirir_ama_DUZELTMEZ(services, bira):
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira, quantity=2)
    assert services.cart.validate(sepet) == []

    services.products.set_price(bira, 8500)
    sorunlar = services.cart.validate(sepet)
    assert len(sorunlar) == 1
    sorun = sorunlar[0]
    assert sorun.kind == SORUN_FIYAT_DEGISTI
    assert (sorun.cart_price, sorun.current_price) == (8000, 8500)
    assert sorun.message == "Fiyat değişti: 80 TL → 85 TL"
    assert sepet.total == 16000, "sepet kendiliğinden değişmedi"


def test_fiyat_degistiyse_checkout_HICBIR_SEY_yazmaz(services, bira):
    services.inventory.set_initial_stock(bira, 10, unit_cost=5000)
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira, quantity=2)
    taslak = services.cart.save_draft(sepet)
    services.products.set_price(bira, 8500)

    with pytest.raises(FiyatDegisti) as bilgi:
        services.cart.checkout(sepet, payment_method=PaymentMethod.CASH)
    assert bilgi.value.sorunlar[0].current_price == 8500
    assert _satis_sayisi(services) == 0
    assert services.products.get(bira)["current_stock"] == 10
    assert services.db.scalar(
        "SELECT status FROM cart_drafts WHERE id = ?", (taslak,)
    ) == "OPEN", "taslak açık kaldı"
    assert sepet.item_count == 2 and sepet.draft_id == taslak
    assert services.db.check_invariants(deep=True) == []


def test_guncel_fiyat_acikca_uygulaninca_kaydedilen_gorunenle_ayni(services, bira):
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira, quantity=2)
    services.products.set_price(bira, 8500)

    assert services.cart.apply_current_prices(sepet) == 1
    assert sepet.total == 17000
    sonuc = services.cart.checkout(sepet, payment_method=PaymentMethod.CARD)
    assert sonuc.total_amount == 17000
    assert services.db.scalar(
        "SELECT total_amount FROM sales WHERE id = ?", (sonuc.sale_id,)
    ) == 17000


def test_ayni_urun_fiyat_degisince_tekrar_okutulursa_satir_isaretlenir(services, bira):
    """Birleştirilen satır eski fiyatı taşır; sessiz karışım yerine işaretlenir."""
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira)
    services.products.set_price(bira, 8500)
    services.cart.add_product(sepet, bira)
    assert sepet.find(bira).quantity == 2
    assert [s.kind for s in services.cart.validate(sepet)] == [SORUN_FIYAT_DEGISTI]
    with pytest.raises(FiyatDegisti):
        services.cart.checkout(sepet)


def test_pasif_ve_fiyatsiz_urun_bildirilir_fiyat_uygulama_onlara_dokunmaz(
    services, bira, cips_urunu
):
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira)
    services.cart.add_product(sepet, cips_urunu)
    services.products.set_active(bira, False)
    services.db.execute("UPDATE products SET sale_price = NULL WHERE id = ?", (cips_urunu,))

    turler = {s.product_id: s.kind for s in services.cart.validate(sepet)}
    assert turler == {bira: SORUN_PASIF, cips_urunu: SORUN_FIYATSIZ}
    assert services.cart.apply_current_prices(sepet) == 0
    assert sepet.total == 8000 + 5000


# ===================== D-03: taslak dayanıklılığı ==========================
def test_taslak_yazisi_veriyi_degismis_saymaz(services, bira):
    once = services.db.data_version()
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira)
    services.cart.save_draft(sepet)
    services.cart.add_product(sepet, bira)
    services.cart.save_draft(sepet)
    services.cart.autosave(Cart())
    services.cart.discard_draft(sepet.draft_id)
    assert services.db.data_version() == once, "otomatik yedek tetiklenmez"


def test_bosalan_sepetin_taslagi_iptal_edilir(services, bira):
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira)
    taslak = services.cart.autosave(sepet)
    assert services.cart.open_drafts()[0]["id"] == taslak

    sepet.remove(bira)
    assert services.cart.autosave(sepet) is None
    assert sepet.draft_id is None
    assert services.cart.open_drafts() == [], "hayalet taslak kalmadı"
    assert services.db.scalar(
        "SELECT status FROM cart_drafts WHERE id = ?", (taslak,)
    ) == "CANCELLED"


def test_kapanmis_taslaga_yazilmaz_yenisi_acilir(services, bira):
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira)
    eski = services.cart.save_draft(sepet)
    services.db.execute(
        "UPDATE cart_drafts SET status = 'CANCELLED' WHERE id = ?", (eski,)
    )
    yeni = services.cart.save_draft(sepet)
    assert yeni != eski
    assert services.db.scalar(
        "SELECT status FROM cart_drafts WHERE id = ?", (eski,)
    ) == "CANCELLED", "kapanmış taslak yeniden açılmadı"
    assert services.db.scalar(
        "SELECT COUNT(*) FROM cart_draft_lines WHERE draft_id = ?", (yeni,)
    ) == 1
    assert [t["id"] for t in services.cart.open_drafts()] == [yeni]


def test_satisa_donusmus_taslak_iptal_edilemez(services, bira):
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira)
    taslak = services.cart.save_draft(sepet)
    services.cart.checkout(sepet)
    services.cart.discard_draft(taslak)
    assert services.db.scalar(
        "SELECT status FROM cart_drafts WHERE id = ?", (taslak,)
    ) == "CHECKED_OUT"


def test_yeniden_acilan_veritabanina_ESKI_sepet_yazilamaz(services, bira):
    """Geri yükleme bağlantıyı kapatıp açar; eski sepet yeni veriye karışmaz."""
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira)
    services.cart.save_draft(sepet)
    once = services.db.scalar("SELECT COUNT(*) FROM cart_drafts")

    services.db.close()
    services.db.connect()                      # restore() ile aynı yol

    with pytest.raises(EskiOturumSepeti):
        services.cart.save_draft(sepet)
    with pytest.raises(EskiOturumSepeti):
        services.cart.autosave(sepet)
    assert services.db.scalar("SELECT COUNT(*) FROM cart_drafts") == once

    taze = services.cart.new_cart()
    services.cart.add_product(taze, bira)
    assert services.cart.save_draft(taze) is not None


def test_okutmayla_baslayan_sepet_acilisa_baglanir(services, bira):
    sepet = Cart()                              # eski çağrı biçimi
    services.cart.add_product(sepet, bira)
    assert sepet.generation == services.db.generation


def test_geri_yuklenen_taslak_guncel_acilisa_aittir(services, bira, reopen):
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira)
    taslak = services.cart.save_draft(sepet)
    yeni = reopen(services)
    try:
        kurtarilan = yeni.cart.load_draft(taslak)
        assert kurtarilan.generation == yeni.db.generation
        yeni.cart.add_product(kurtarilan, bira)
        assert yeni.cart.save_draft(kurtarilan) == taslak
    finally:
        yeni.close()
