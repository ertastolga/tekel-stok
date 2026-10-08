"""F3 Fiyat Gör (V1.2 M3d).

Korunan sözler:
  * okutma YALNIZCA fiyat gösterir: satış, stok, sepet ve müşteri ekranı
    değişmez; sarı "FİYAT KONTROL — SATIŞ YAPILMAZ" şeridi görünür,
  * koli/paket barkodu toplam ve adet fiyatıyla gösterilir; tanınmayan barkod
    ürün tanımlama penceresi AÇMAZ,
  * okutma işleyicisi sayfa değiştirmez; "Satışa dön" / Esc geldiği Kasa
    sayfasına döndürür ve o sayfanın sepeti olduğu gibi durur,
  * son 5 kontrol listelenir; F11 kısayolu vardır.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QDialog  # noqa: E402

from app.core.models import BarcodeType  # noqa: E402
from app.scanner.scan_event import ScanEvent  # noqa: E402
from app.ui import shortcuts  # noqa: E402
from fakes import SiraliSahteEkran  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403

BIRA = "8690504001492"
KOLI = "8690504001508"


@pytest.fixture
def fiyat(window, qapp):
    window.go_to("sepetli_satis")
    window.pages["sepetli_satis"].handle_scan(ScanEvent(code=BIRA))   # eldeki sepet
    window.go_to("fiyat_kontrol")
    qapp.processEvents()
    return window.pages["fiyat_kontrol"]


def test_okutma_yalnizca_fiyat_gosterir(fiyat, window, qapp, services, bira):
    ekran = SiraliSahteEkran()
    services.display.set_display(ekran)
    once_stok = services.products.get(bira)["current_stock"]

    window.router.dispatch(ScanEvent(code=BIRA))
    qapp.processEvents()

    assert fiyat.price_label.text() == "80 TL"
    assert fiyat.name_label.text() == "Tuborg Gold 50 cl Kutu"
    assert fiyat.mode_banner.text() == "FİYAT KONTROL — SATIŞ YAPILMAZ"
    assert fiyat.mode_banner.isVisibleTo(fiyat)
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    assert services.products.get(bira)["current_stock"] == once_stok
    assert ekran.cagrilar == [], "müşteri ekranına dokunulmadı"
    assert window._current_key == "fiyat_kontrol", "okutma sayfa değiştirmez"
    assert window.pages["sepetli_satis"].cart.item_count == 1, "sepet değişmedi"


def test_koli_barkodu_toplam_ve_adet_fiyati(fiyat, services, bira):
    services.barcodes.add_barcode(bira, KOLI, BarcodeType.CASE, 24)
    fiyat.show_price_for(KOLI)
    assert fiyat.price_label.text() == "1.920 TL"
    assert "24 adetlik" in fiyat.detail_label.text()
    assert "80 TL" in fiyat.detail_label.text()


def test_taninmayan_barkod_tanimlama_penceresi_acmaz(fiyat, services, monkeypatch):
    acilan = []
    monkeypatch.setattr(QDialog, "exec", lambda self: acilan.append(self) or 0)
    urun_sayisi = services.db.scalar("SELECT COUNT(*) FROM products")
    fiyat.show_price_for("2999999999999")
    assert fiyat.name_label.text() == "Ürün tanınmadı."
    assert acilan == []
    assert services.db.scalar("SELECT COUNT(*) FROM products") == urun_sayisi


def test_pasif_ve_fiyatsiz_urun(fiyat, services, bira):
    services.products.quick_create("Fiyatsız Ürün", None, barcode="8690000000029")
    fiyat.show_price_for("8690000000029")
    assert "fiyatı girilmemiş" in fiyat.name_label.text()
    # Barkodu etkin, ürünü pasif kayıt (V1.0 verisi gibi). Pasife alınan ürünün
    # barkodunun "sahibi pasif" olarak tanınması M4b'de (D-08) eklenir.
    services.db.execute("UPDATE products SET is_active = 0 WHERE id = ?", (bira,))
    fiyat.show_price_for(BIRA)
    assert "kullanımdan kaldırılmış" in fiyat.name_label.text()
    assert fiyat.price_label.text() == ""
    # D-08 (M4b): Ürünler'den pasife alınan ürünün barkodu da tanınır.
    services.db.execute("UPDATE products SET is_active = 1 WHERE id = ?", (bira,))
    services.products.set_active(bira, False)
    fiyat.show_price_for(BIRA)
    assert "kullanımdan kaldırılmış" in fiyat.name_label.text()
    assert fiyat.detail_label.text() == "Tuborg Gold 50 cl Kutu"


def test_son_bes_kontrol(fiyat, services, bira):
    for i in range(6):
        services.products.quick_create(f"Ürün {i}", 1000 + i, barcode=f"86900000001{i}0")
    for i in range(6):
        fiyat.show_price_for(f"86900000001{i}0")
    metinler = [e.text() for e in fiyat.recent_labels]
    assert metinler[0].startswith("Ürün 5") and metinler[-1].startswith("Ürün 1")
    assert all(metinler)


def test_satisa_don_geldigi_sayfaya_doner(window, qapp):
    window.go_to("hizli_satis")
    window.go_to("fiyat_kontrol")
    sayfa = window.pages["fiyat_kontrol"]
    sayfa.back_button.click()
    assert window._current_key == "fiyat_kontrol", "dönüş bir sonraki turda"
    qapp.processEvents()
    assert window._current_key == "hizli_satis"

    window.go_to("fiyat_kontrol")
    window._go_back()                                   # Esc
    qapp.processEvents()
    assert window._current_key == "hizli_satis"


def test_kasa_disindan_gelince_sepetli_satisa_doner(window, qapp):
    window.go_to("urunler")
    window.go_to("fiyat_kontrol")
    window.pages["fiyat_kontrol"].return_to_sale()
    qapp.processEvents()
    assert window._current_key == "sepetli_satis"


def test_f11_kisayolu_ve_kasa_dugmeleri(window, qapp):
    assert shortcuts.by_action("goto:fiyat_kontrol").key == "F11"
    window.go_to("sepetli_satis")
    window.pages["sepetli_satis"].price_check_button.click()
    assert window._current_key == "fiyat_kontrol"
    window.go_to("hizli_satis")
    window.pages["hizli_satis"].price_check_button.click()
    assert window._current_key == "fiyat_kontrol"
