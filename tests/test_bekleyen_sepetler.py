"""F1 Bekleyen Sepetler + şema v2 + Kasa katman sözleşmesi (V1.2 M3b).

Korunan sözler:
  * "Beklet" sepeti anında "Müşteri n · ss:dd" adıyla saklar; en çok 9 sepet;
    yeniden başlatmaya dayanır; açılış kurtarması yalnızca otomatik kaydı sorar,
  * bekleyen sepet açılınca saklanan fiyatlar korunur, değişiklik İŞARETLENİR,
    ASLA kendiliğinden onarılmaz; doluyken açmak "değiştir" onayı ister ve
    sınırı aşmaz,
  * katman açıkken okutma ve elle giriş reddedilir (katmanın içinde bildirilir),
    sepet/ödeme denetimleri kapalıdır; Esc ve sayfa değişimi katmanı kapatıp
    okutma askısını bırakır,
  * v2 göçü yalnızca ekler; V1.1'in açık taslakları AUTOSAVE olur.
"""
from __future__ import annotations

import os
import sqlite3

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.db import open_database  # noqa: E402
from app.core.errors import BekletmeSiniri, BosSepet  # noqa: E402
from app.scanner.scan_event import ScanEvent  # noqa: E402
from app.services.cart_service import (  # noqa: E402
    BEKLETME_SINIRI,
    SORUN_FIYAT_DEGISTI,
    TASLAK_OTOMATIK,
)
from app.ui.main_window import MainWindow  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403

BIRA = "8690504001492"


def _sepet(services, *urunler, adet=1):
    sepet = services.cart.new_cart()
    for urun in urunler:
        services.cart.add_product(sepet, urun, quantity=adet)
    return sepet


# ===================== Servis ==============================================
def test_beklet_etiketler_ve_satir_kopyalarini_saklar(duvar_saati, services, bira):
    duvar_saati.git(2026, 10, 8, 14, 32)
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira, quantity=2, barcode_used=BIRA, multiplier=1)
    ilk = services.cart.park(sepet)
    duvar_saati.git(2026, 10, 8, 14, 40)
    ikinci = services.cart.park(_sepet(services, bira))

    bekleyen = services.cart.parked_carts()
    assert [r["id"] for r in bekleyen] == [ilk, ikinci]
    assert [r["label"] for r in bekleyen] == ["Müşteri 1 · 14:32", "Müşteri 2 · 14:40"]
    assert bekleyen[0]["urun_adedi"] == 2 and bekleyen[0]["toplam"] == 16000
    satir = services.db.query_one(
        "SELECT * FROM cart_draft_lines WHERE draft_id = ?", (ilk,)
    )
    assert satir["product_name_snapshot"] == "Tuborg Gold 50 cl Kutu"
    assert satir["barcode_used"] == BIRA and satir["barcode_multiplier"] == 1
    assert services.cart.open_drafts(kind=TASLAK_OTOMATIK) == [], "kurtarmaya girmez"

    duvar_saati.git(2026, 10, 9, 10, 0)                     # ertesi iş günü
    ucuncu = services.cart.park(_sepet(services, bira))
    assert services.db.scalar(
        "SELECT label FROM cart_drafts WHERE id = ?", (ucuncu,)
    ) == "Müşteri 1 · 10:00"


def test_bos_sepet_bekletilmez_ve_sinir_dokuzdur(services, bira):
    with pytest.raises(BosSepet):
        services.cart.park(services.cart.new_cart())
    for _ in range(BEKLETME_SINIRI):
        services.cart.park(_sepet(services, bira))
    with pytest.raises(BekletmeSiniri):
        services.cart.park(_sepet(services, bira))
    assert services.cart.parked_count() == 9


def test_bekleyen_acilinca_fiyat_korunur_degisiklik_isaretlenir(services, bira, cips_urunu):
    kimlik = services.cart.park(_sepet(services, bira, cips_urunu))
    services.products.set_price(bira, 8500)
    services.products.set_active(cips_urunu, False)

    sepet, sorunlar = services.cart.resume_parked(kimlik)
    assert sepet.find(bira).unit_price == 8000, "saklanan fiyat korundu"
    assert {s.product_id: s.kind for s in sorunlar} == {
        bira: SORUN_FIYAT_DEGISTI, cips_urunu: "PASIF",
    }
    assert services.cart.parked_count() == 0
    assert services.db.scalar(
        "SELECT kind FROM cart_drafts WHERE id = ?", (kimlik,)
    ) == "AUTOSAVE", "artık üzerinde çalışılan sepet"
    with pytest.raises(BosSepet):
        services.cart.resume_parked(kimlik)


def test_bekleyen_sepet_yeniden_baslatmaya_dayanir(services, bira, reopen):
    kimlik = services.cart.park(_sepet(services, bira, adet=3))
    yeni = reopen(services)
    try:
        assert [r["id"] for r in yeni.cart.parked_carts()] == [kimlik]
        sepet, sorunlar = yeni.cart.resume_parked(kimlik)
        assert sepet.item_count == 3 and sorunlar == []
        assert sepet.generation == yeni.db.generation
        sonuc = yeni.cart.checkout(sepet)
        assert sonuc.total_amount == 24000
    finally:
        yeni.close()


def test_bekletme_veriyi_degismis_saymaz(services, bira):
    once = services.db.data_version()
    kimlik = services.cart.park(_sepet(services, bira))
    services.cart.resume_parked(kimlik)
    assert services.db.data_version() == once


def test_v2_gocu_eski_acik_taslagi_otomatik_yapar(v1_1_kopya):
    db = open_database(v1_1_kopya)
    try:
        assert db.schema_version() >= 2
        satirlar = db.query("SELECT kind, status FROM cart_drafts")
        assert satirlar and all(r["kind"] == "AUTOSAVE" for r in satirlar)
        assert db.scalar(
            "SELECT COUNT(*) FROM cart_draft_lines WHERE barcode_multiplier <> 1"
        ) == 0
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE cart_drafts SET kind = 'BASKA' WHERE id = ?",
                (satirlar and db.scalar("SELECT id FROM cart_drafts"),),
            )
        assert db.check_invariants(deep=True) == []
    finally:
        db.close()


# ===================== Arayüz ==============================================
@pytest.fixture
def kasa(window, qapp):
    window.go_to("sepetli_satis")
    qapp.processEvents()
    return window.pages["sepetli_satis"]


def test_beklet_sepeti_kaldirir_ve_yeni_musteriye_hazirlar(kasa, qapp, services, bira):
    kasa.handle_scan(ScanEvent(code=BIRA))
    kasa.park_button.click()
    qapp.processEvents()
    assert kasa.cart.is_empty
    assert kasa.parked_button.text() == "Bekleyenler (1)"
    assert "bekletildi" in kasa.banner.headline.text()
    kasa.handle_scan(ScanEvent(code=BIRA))
    assert kasa.cart.item_count == 1, "yeni sepet"
    assert services.cart.parked_count() == 1


def test_katman_acikken_okutma_ve_denetimler_kapali(kasa, window, qapp, services, bira):
    kasa.handle_scan(ScanEvent(code=BIRA))
    kasa.park_button.click()
    kasa.handle_scan(ScanEvent(code=BIRA))
    kasa.show_parked()
    qapp.processEvents()
    panel = kasa._parked_panel
    assert kasa.overlay_state == "BEKLEYENLER"
    assert panel.isVisible() and panel.geometry() == kasa.rect()
    assert window.router.is_suspended
    assert not kasa.cash_button.isEnabled() and not kasa.park_button.isEnabled()

    window.router.dispatch(ScanEvent(code=BIRA))           # yönlendirici yolu
    kasa.barcode.submitted.emit(BIRA)                       # elle giriş yolu
    assert kasa.cart.item_count == 1, "katman açıkken hiçbir şey eklenmedi"
    assert panel.notice_label.isVisibleTo(panel)

    window._go_back()                                       # Esc: önce katman
    assert kasa.overlay_state is None and window._current_key == "sepetli_satis"
    assert not window.router.is_suspended
    assert kasa.cash_button.isEnabled()


def test_bos_sepette_ac_dolu_sepette_degistir(kasa, qapp, services, bira, cips_urunu):
    kasa.handle_scan(ScanEvent(code=BIRA))
    kasa.park_button.click()
    kasa.show_parked()
    kimlik = next(iter(kasa._parked_panel.rows))
    kasa._parked_panel.rows[kimlik].open_button.click()
    qapp.processEvents()
    assert kasa.overlay_state is None
    assert kasa.cart.item_count == 1 and kasa.cart.find(services.products.by_name(
        "Tuborg Gold 50 cl Kutu")["id"]) is not None
    assert kasa.parked_button.text() == "Bekleyenler (0)"

    kasa.park_button.click()                                # tekrar beklet
    kasa._add_product(cips_urunu, 2, None, 1)               # yeni müşteri
    kasa.show_parked()
    kimlik = next(iter(kasa._parked_panel.rows))
    kasa._parked_panel.rows[kimlik].open_button.click()
    assert kasa._parked_panel.swap_frame.isVisibleTo(kasa._parked_panel)
    kasa._parked_panel.swap_yes_button.click()
    qapp.processEvents()
    assert kasa.cart.find(cips_urunu) is None, "bekleyen açıldı"
    assert [r["urun_adedi"] for r in services.cart.parked_carts()] == [2], "eldeki bekletildi"


def test_sinirdayken_degistirme_siniri_asmaz(kasa, qapp, services, bira, cips_urunu):
    for _ in range(BEKLETME_SINIRI):
        services.cart.park(_sepet(services, bira))
    kasa._add_product(cips_urunu, 1, None, 1)
    kasa.park_button.click()
    assert "En fazla 9" in kasa.banner.headline.text()
    kasa.show_parked()
    kimlik = next(iter(kasa._parked_panel.rows))
    kasa._on_resume_requested(kimlik)
    kasa._parked_panel.swap_yes_button.click()
    assert services.cart.parked_count() == 9
    assert kasa.cart.find(cips_urunu) is None


def test_sil_satir_ici_onayla(kasa, qapp, services, bira):
    services.cart.park(_sepet(services, bira))
    kasa.show_parked()
    satir = next(iter(kasa._parked_panel.rows.values()))
    satir.delete_button.click()
    assert satir.confirm_delete_button.isVisibleTo(satir)
    satir.confirm_delete_button.click()
    assert services.cart.parked_count() == 0
    assert kasa._parked_panel.empty.isVisibleTo(kasa._parked_panel)


def test_acilan_bekleyende_degisen_fiyat_isaretli_odeme_kapali(kasa, qapp, services, bira):
    services.cart.park(_sepet(services, bira))
    services.products.set_price(bira, 9000)
    kasa.show_parked()
    kasa._resume_parked(next(iter(kasa._parked_panel.rows)))
    qapp.processEvents()
    assert kasa._rows[bira].issue_text == "Fiyat değişti: 80 TL → 90 TL"
    assert not kasa.cash_button.isEnabled()
    assert "değişen ürün" in kasa.banner.headline.text()


def test_sayfa_degisince_katman_kapanir_aski_birakilir(kasa, window, qapp, services, bira):
    services.cart.park(_sepet(services, bira))
    kasa.show_parked()
    window.go_to("urunler")
    assert kasa.overlay_state is None and not window.router.is_suspended


def test_yeniden_acilista_bekleyen_kurtarma_sorusu_sormaz(qapp, services, bira, onay):
    services.cart.park(_sepet(services, bira))
    win = MainWindow(services)
    try:
        win.show()
        win.go_to("sepetli_satis")
        qapp.processEvents()
        assert onay.sorular == [], "bekleyen sepet 'devam et?' sorusuna dönüşmez"
        assert win.pages["sepetli_satis"].parked_button.text() == "Bekleyenler (1)"
    finally:
        close_window(win, qapp)
