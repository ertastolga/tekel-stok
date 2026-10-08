"""Fiyat Yönetimi sayfası (V1.2 M5b).

Korunan sözler:
  * liste bilinen alış ile referans (katalog) alışı ayrı gösterir; marj yalnızca
    bilinen alışla hesaplanır,
  * toplu değişiklik önce önizlenir; yalnızca "Değişecek" satırlar seçili gelir,
    kullanıcının işaretini kaldırdığı satır uygulanmaz,
  * uygulama ve geri alma PIN ister (PIN varsa); reddedilince hiçbir şey olmaz,
  * önizlemeden sonra fiyat değişirse hiçbir şey yazılmaz,
  * geri alma sonradan değişen ürüne dokunmayacağını önceden söyler,
  * tek ürün seçilince fiyat geçmişi görünür ("ilk fiyat (kayıt yok)" dahil).
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, Qt  # noqa: E402

from app.core import pricing_math as pm  # noqa: E402
from app.ui.dialogs import pin_dialog as pd  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403


@pytest.fixture
def fiyatlar(window, qapp, cips_urunu):
    window.go_to("fiyatlar")
    qapp.processEvents()
    return window.pages["fiyatlar"]


@pytest.fixture
def pin_cevabi(monkeypatch):
    kayit = {"cevap": pd.DOGRULANDI, "cagri": 0}

    def ask(parent, security, action_label=""):
        kayit["cagri"] += 1
        kayit["etiket"] = action_label
        return kayit["cevap"]

    monkeypatch.setattr(pd.PinDialog, "ask", staticmethod(ask))
    return kayit


def _satir(sayfa, pid):
    return [s.product_id for s in sayfa._satirlar].index(pid)


def _sec(sayfa, *kimlikler):
    secim = sayfa.table.selectionModel()
    secim.clearSelection()
    for pid in kimlikler:
        secim.select(
            sayfa.table.model().index(_satir(sayfa, pid), 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )


def _islem(sayfa, tur, deger, adim=100):
    sayfa.operation_combo.setCurrentIndex(sayfa.operation_combo.findData(tur))
    sayfa.value_edit.setText(deger)
    sayfa.rounding_combo.setCurrentIndex(sayfa.rounding_combo.findData(adim))


def _hucre(sayfa, pid, baslik):
    from app.ui.pages.prices import LISTE_SUTUNLARI

    return sayfa.table.item(_satir(sayfa, pid), LISTE_SUTUNLARI.index(baslik)).text()


def test_liste_bilinen_ve_referans_alisi_ayirir(fiyatlar, services, bira, cips_urunu):
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 24, 5000)
    services.purchases.commit(fis)
    services.products.set_reference_cost(cips_urunu, 3100)
    fiyatlar.refresh()
    assert _hucre(fiyatlar, bira, "Son alış") == "50 TL"
    assert _hucre(fiyatlar, bira, "Marj") == "%37,5"
    assert _hucre(fiyatlar, bira, "Marka") == "Tuborg"
    assert _hucre(fiyatlar, cips_urunu, "Son alış") == "bilinmiyor"
    assert _hucre(fiyatlar, cips_urunu, "Marj") == "—", "referans alışla marj yok"
    assert _hucre(fiyatlar, cips_urunu, "Referans alış (katalog)") == "31 TL"


def test_onizle_isaret_kaldir_uygula(fiyatlar, services, bira, cips_urunu, onay):
    assert not fiyatlar.preview_button.isEnabled()
    _sec(fiyatlar, bira, cips_urunu)
    assert fiyatlar.preview_button.text() == "Önizle (2 ürün)"
    _islem(fiyatlar, pm.YUZDE_ARTIR, "10")
    fiyatlar.preview_selected()
    assert fiyatlar.stack.currentIndex() == 1
    assert {s.product_id for s in fiyatlar.preview_checked()} == {bira, cips_urunu}
    fiyatlar.set_preview_checked(cips_urunu, False)
    assert fiyatlar.apply_button.text() == "Uygula (1)"

    assert fiyatlar.apply_preview()
    assert "1 ürünün fiyatı değişsin mi?" in onay.sorular[-1]
    assert services.products.get(bira)["sale_price"] == 8800
    assert services.products.get(cips_urunu)["sale_price"] == 5000, "işareti kaldırılan"
    assert fiyatlar.stack.currentIndex() == 0
    assert fiyatlar.batch_list.count() == 1
    assert "1 ürün" in fiyatlar.batch_list.item(0).text()


def test_degismeyen_ve_maliyetsiz_satirlar_secili_gelmez(fiyatlar, services, bira, cips_urunu):
    _sec(fiyatlar, bira, cips_urunu)
    _islem(fiyatlar, pm.SABIT, "80")
    fiyatlar.preview_selected()
    assert [s.product_id for s in fiyatlar.preview_checked()] == [cips_urunu]
    bira_satiri = [s.product_id for s in fiyatlar._onizleme].index(bira)
    durum_sutunu = 6
    assert fiyatlar.preview_table.item(bira_satiri, durum_sutunu).text() == \
        pm.DURUM_ADLARI[pm.AYNI]

    fiyatlar.close_preview()
    _islem(fiyatlar, pm.MARJ, "30")
    fiyatlar.preview_selected()
    assert fiyatlar.preview_checked() == [], "alış fiyatı bilinmiyor"
    assert not fiyatlar.apply_button.isEnabled()


def test_gecersiz_deger_onizleme_acmaz(fiyatlar, bira):
    _sec(fiyatlar, bira)
    _islem(fiyatlar, pm.YUZDE_ARTIR, "on")
    fiyatlar.preview_selected()
    assert fiyatlar.stack.currentIndex() == 0


def test_uygulama_pin_ister(fiyatlar, services, bira, onay, pin_cevabi):
    services.security.set_pin("4826")
    _sec(fiyatlar, bira)
    _islem(fiyatlar, pm.TUTAR_ARTIR, "5")
    fiyatlar.preview_selected()
    pin_cevabi["cevap"] = pd.VAZGECILDI
    assert not fiyatlar.apply_preview()
    assert services.products.get(bira)["sale_price"] == 8000
    assert pin_cevabi["cagri"] == 1
    pin_cevabi["cevap"] = pd.DOGRULANDI
    assert fiyatlar.apply_preview()
    assert services.products.get(bira)["sale_price"] == 8500


def test_onizlemeden_sonra_degisen_fiyat(fiyatlar, services, bira, cips_urunu, onay):
    _sec(fiyatlar, bira, cips_urunu)
    _islem(fiyatlar, pm.YUZDE_AZALT, "10")
    fiyatlar.preview_selected()
    services.products.set_price(cips_urunu, 5100)
    assert not fiyatlar.apply_preview()
    assert services.products.get(bira)["sale_price"] == 8000
    assert fiyatlar.stack.currentIndex() == 0, "kullanıcı yeniden önizler"


def test_geri_alma_dokunulmayacaklari_soyler(fiyatlar, services, bira, cips_urunu, onay):
    _sec(fiyatlar, bira, cips_urunu)
    _islem(fiyatlar, pm.YUZDE_ARTIR, "10")
    fiyatlar.preview_selected()
    fiyatlar.apply_preview()
    services.products.set_price(cips_urunu, 6000)
    fiyatlar.refresh()
    fiyatlar.batch_list.setCurrentRow(0)
    assert fiyatlar.undo_selected_batch()
    assert onay.sorular[-1] == "Toplu değişiklik geri alınsın mı?"
    assert onay.ayrintilar[-1] == ("1 ürün eski fiyatına döner. 1 ürünün fiyatı sonradan "
                                   "değiştiği için dokunulmayacak.")
    assert services.products.get(bira)["sale_price"] == 8000
    assert services.products.get(cips_urunu)["sale_price"] == 6000
    assert "geri alındı" in fiyatlar.batch_list.item(1).text()
    fiyatlar.batch_list.setCurrentRow(1)
    assert not fiyatlar.undo_selected_batch(), "ikinci kez geri alınmaz"


def test_tek_urun_secilince_fiyat_gecmisi(fiyatlar, services, bira):
    services.products.set_price(bira, 8500)
    fiyatlar.refresh()
    _sec(fiyatlar, bira)
    metinler = [fiyatlar.timeline_list.item(i).text()
                for i in range(fiyatlar.timeline_list.count())]
    assert metinler[0].endswith("Elle: 80 TL → 85 TL")
    assert metinler[-1].startswith("ilk fiyat (kayıt yok): 80 TL")


def test_esc_onizlemeyi_kapatir(fiyatlar, bira):
    _sec(fiyatlar, bira)
    _islem(fiyatlar, pm.YUZDE_ARTIR, "5")
    fiyatlar.preview_selected()
    assert fiyatlar.handle_back() and fiyatlar.stack.currentIndex() == 0
    assert not fiyatlar.handle_back()
