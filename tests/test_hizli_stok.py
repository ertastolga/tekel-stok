"""📥 Hızlı Stok Girişi (V1.2 M6b, D1).

Korunan sözler:
  * okut → adet → Kaydet tek satırlık, tedarikçisiz bir fişi TEK işlemde
    stoğa işler; hata olursa yarım taslak kalmaz,
  * koli barkodu okutulunca birim "Koli × 24" seçili gelir; adet × çarpan,
  * alış fiyatı isteğe bağlı: bilinen son alış ön doldurulur, "Bilmiyorum" ile
    maliyet tahmini olur ve son alış fiyatı DEĞİŞMEZ,
  * aynı ürün yeniden okutulursa adet artar; başka ürün okutulursa bekleyen
    ürün sessizce değişmez,
  * bugünkü girişler listelenir; kanıtlanabilir giriş geri alınır (PIN varsa
    ister), sonrasında hareket gören giriş geri alınmaz,
  * sayfa dokunmatiktir ve 1000×600'e sığar.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QPushButton  # noqa: E402

from app.core.errors import GecersizMiktar  # noqa: E402
from app.core.models import BarcodeType  # noqa: E402
from app.services.purchase_service import HIZLI_STOK_NOTU  # noqa: E402
from app.ui import metrics  # noqa: E402
from app.ui.dialogs import pin_dialog as pd  # noqa: E402

from conftest import BIRA_BARKOD  # noqa: E402
from ui_support import *  # noqa: E402,F401,F403

KOLI = "8690000000999"


def _stok(services, pid):
    return services.products.get(pid)["current_stock"]


# ===================== Servis ==============================================
def test_hizli_giris_tek_islemde_tek_satirlik_fis(services, bira):
    once = _stok(services, bira)
    fis = services.purchases.quick_receive(bira, 24, 5000, BIRA_BARKOD)
    assert _stok(services, bira) == once + 24
    kayit = services.purchases.receipt(fis)
    assert (kayit["status"], kayit["supplier_id"], kayit["note"]) == (
        "COMMITTED", None, HIZLI_STOK_NOTU)
    assert len(services.purchases.lines(fis)) == 1
    girisler = services.purchases.quick_entries()
    assert [(g["id"], g["quantity"], g["geri_alindi"]) for g in girisler] == [(fis, 24, 0)]


def test_hatali_giris_yarim_taslak_birakmaz(services, bira):
    with pytest.raises(GecersizMiktar):
        services.purchases.quick_receive(bira, 0, 5000)
    with pytest.raises(Exception):
        services.purchases.quick_receive(99999, 5, 5000)       # olmayan ürün
    assert services.db.scalar("SELECT COUNT(*) FROM purchase_receipts") == 0
    assert services.purchases.open_drafts() == []


def test_maliyetsiz_hizli_giris_tahminidir(services, bira):
    services.purchases.quick_receive(bira, 10, 5000)
    fis = services.purchases.quick_receive(bira, 10, None)
    assert services.purchases.lines(fis)[0]["cost_is_estimated"] == 1
    assert services.products.get(bira)["last_purchase_cost"] == 5000
    assert services.db.check_invariants(deep=True) == []


# ===================== Sayfa ===============================================
@pytest.fixture
def hizli(window, qapp, services, bira):
    services.barcodes.add_barcode(bira, KOLI, BarcodeType.CASE, 24)
    window.go_to("hizli_stok")
    qapp.processEvents()
    return window.pages["hizli_stok"]


def _tus(sayfa, metin):
    for karakter in metin:
        sayfa.numpad.keys[karakter].click()


def test_okut_adet_kaydet(hizli, services, bira):
    services.purchases.quick_receive(bira, 6, 5200)            # bilinen alış
    hizli.refresh()
    once = _stok(services, bira)
    hizli.scan_code(BIRA_BARKOD)
    assert hizli.product_id == bira and hizli.qty_display.value() == "1"
    assert hizli.cost_display.value() == "52" and "önceki alıştan" in hizli.cost_hint.text()
    hizli.plus_button.click()
    hizli.plus_button.click()
    assert hizli.total_label.text() == "3 adet"
    assert hizli.save()
    assert _stok(services, bira) == once + 3
    assert hizli.product_id is None, "sıradaki ürüne hazır"
    assert hizli.entries_list.count() == 2
    assert "+3" in hizli.entries_list.item(0).text()


def test_koli_barkodu_koli_birimini_secer(hizli, services, bira):
    once = _stok(services, bira)
    hizli.scan_code(KOLI)
    assert hizli.multiplier == 24 and hizli._unit_buttons[24].isChecked()
    assert hizli.total_label.text() == "= 24 adet"
    hizli.set_unit(1)
    hizli.qty_display.set_value("2")
    hizli.set_unit(24)
    assert hizli.units() == 48
    hizli.save()
    assert _stok(services, bira) == once + 48


def test_tus_takimiyla_adet_ve_maliyet(hizli, services, bira):
    hizli.scan_code(BIRA_BARKOD)
    hizli.numpad.clear_key.click()
    _tus(hizli, "12")
    assert hizli.qty_display.value() == "12"
    assert not hizli.numpad.keys[","].isEnabled(), "adette virgül yok"
    hizli.cost_display.clicked.emit()
    hizli.numpad.clear_key.click()
    _tus(hizli, "47,5")
    assert hizli.unit_cost() == 4750
    hizli.save()
    assert services.products.get(bira)["last_purchase_cost"] == 4750


def test_bilmiyorum_maliyeti_tahmini_yapar(hizli, services, bira):
    services.purchases.quick_receive(bira, 6, 5000)
    hizli.scan_code(BIRA_BARKOD)
    hizli.unknown_cost_button.click()
    assert hizli.unit_cost() is None
    hizli.save()
    satir = services.purchases.lines(services.purchases.quick_entries()[0]["id"])[0]
    assert satir["cost_is_estimated"] == 1
    assert services.products.get(bira)["last_purchase_cost"] == 5000, "son alış değişmedi"
    assert "maliyet bilinmiyor" in hizli.entries_list.item(0).text()


def test_ayni_urun_artar_baska_urun_bekleyeni_degistirmez(hizli, services, bira,
                                                          cips_urunu):
    services.barcodes.add_barcode(cips_urunu, "8690000000012")
    hizli.scan_code(BIRA_BARKOD)
    hizli.scan_code(BIRA_BARKOD)
    assert hizli.qty_display.value() == "2"
    hizli.scan_code("8690000000012")
    assert hizli.product_id == bira, "bekleyen ürün sessizce değişmedi"
    assert services.db.scalar("SELECT COUNT(*) FROM purchase_receipts") == 0
    hizli.cancel()
    hizli.scan_code("8690000000012")
    assert hizli.product_id == cips_urunu


def test_giris_geri_alinir_sonrasinda_hareket_varsa_alinmaz(hizli, services, bira, onay):
    once = _stok(services, bira)
    hizli.scan_code(BIRA_BARKOD)
    hizli.qty_display.set_value("5")
    hizli.save()
    hizli.entries_list.setCurrentRow(0)
    assert hizli.undo_button.isEnabled()
    assert hizli.undo_selected()
    assert _stok(services, bira) == once
    assert "geri alındı" in hizli.entries_list.item(0).text()
    hizli.entries_list.setCurrentRow(0)
    assert not hizli.undo_button.isEnabled()

    hizli.scan_code(BIRA_BARKOD)
    hizli.save()
    services.inventory.manual_adjustment(bira, -1, 5000, "fire")
    hizli.refresh()
    hizli.entries_list.setCurrentRow(0)
    sonra = _stok(services, bira)
    assert not hizli.undo_selected(), "sonrasında hareket gören giriş geri alınmaz"
    assert _stok(services, bira) == sonra


def test_geri_alma_pin_ister(hizli, services, bira, onay, monkeypatch):
    services.security.set_pin("4826")
    sorulan = []

    def ask(parent, security, action_label=""):
        sorulan.append(action_label)
        return pd.VAZGECILDI

    monkeypatch.setattr(pd.PinDialog, "ask", staticmethod(ask))
    hizli.scan_code(BIRA_BARKOD)
    hizli.save()
    hizli.entries_list.setCurrentRow(0)
    once = _stok(services, bira)
    assert not hizli.undo_selected()
    assert sorulan and _stok(services, bira) == once


def test_esc_bekleyen_urunu_birakir(hizli, bira):
    hizli.scan_code(BIRA_BARKOD)
    assert hizli.handle_back() and hizli.product_id is None
    assert not hizli.handle_back()


def test_dokunmatik_ve_1000x600e_sigar(window, qapp, hizli):
    window.resize(1000, 600)
    qapp.processEvents()
    hizli.scan_code(BIRA_BARKOD)
    qapp.processEvents()
    assert hizli.minimumSizeHint().height() <= window.stack.height(), (
        hizli.minimumSizeHint().height(), window.stack.height())
    for dugme in hizli.findChildren(QPushButton):
        if dugme.isVisibleTo(hizli):
            assert dugme.minimumHeight() >= metrics.TOUCH_TARGET_MIN, dugme.text()


def test_bugunku_girisler_gorunumu(hizli, services, bira):
    services.purchases.quick_receive(bira, 3, 5000)
    hizli.entries_button.click()
    assert hizli.stack.currentIndex() == 1 and hizli.entries_list.count() == 1
    assert hizli.entries_button.text() == "Bugünkü girişler (1)"
    assert hizli.handle_back() and hizli.stack.currentIndex() == 0
    hizli.entries_button.click()
    hizli.scan_code(BIRA_BARKOD)
    assert hizli.stack.currentIndex() == 0 and hizli.product_id == bira, \
        "okutma giriş formuna döner"
