"""Hızlı Ürün Ekle penceresi (V1.2 M4b).

Korunan sözler:
  * form dokunuşla doldurulur (klavye / tuş takımı); kategori ZORUNLU, son
    kullanılan kategoriler tek dokunuş, arama ve yerinde oluşturma,
  * pencere açıkken okutulan barkod, barkod alanı etkinse o alana yazılır,
  * koli barkoduyla tanımlanan ürün sepete kolideki adet kadar girer
    (barkod yeniden çözülür); mevcut ürüne bağlama da aynı,
  * kullanımdan kaldırılmış ürünün barkodu okutulunca o ürün geri alınır
    (D-08), yeni ürün açtırılmaz,
  * Mal Kabul bağlamında başlangıç stoğu sorulmaz.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QDialog  # noqa: E402

from app.core.models import BarcodeType  # noqa: E402
from app.scanner.scan_event import ScanEvent  # noqa: E402
from app.ui.dialogs import unknown_barcode as ub  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403

YENI = "8690000000999"
BIRA = "8690504001492"


def _dokun(pencere, alan, metin):
    pencere.activate(alan)
    for karakter in metin:
        if alan.kind == ub.METIN:
            if karakter == " ":
                pencere.keyboard.space_key.click()
            else:
                pencere.keyboard.key(karakter).click()
        else:
            pencere.numpad.keys[karakter].click()


def _kategori(services, ad):
    return services.db.scalar("SELECT id FROM categories WHERE name = ?", (ad,))


@pytest.fixture
def pencere(qapp, services):
    p = ub.UnknownBarcodeDialog(YENI, services)
    yield p
    p.deleteLater()


def test_dokunusla_yeni_urun(pencere, services):
    assert not pencere.reactivate_button.isVisibleTo(pencere)
    pencere.define_button.click()
    assert pencere.display is pencere.name_field and pencere.keyboard.isVisibleTo(pencere)
    _dokun(pencere, pencere.name_field, "efes pilsen")
    _dokun(pencere, pencere.price_field, "75")
    assert pencere.numpad.isVisibleTo(pencere) and not pencere.keyboard.isVisibleTo(pencere)
    pencere.choose_category_button.click()
    _dokun(pencere, pencere.picker_field, "bira")
    pencere.refresh_picker()
    hedef = next(d for d in pencere.picker_buttons
                 if d.property("category_id") == _kategori(services, "Bira"))
    hedef.click()
    assert pencere.stages.currentWidget() is pencere.form
    pencere.save_button.click()
    assert pencere.result() == QDialog.DialogCode.Accepted
    assert pencere.result_kind == ub.SONUC_YENI
    urun = services.products.get(pencere.product_id)
    assert (urun["name"], urun["sale_price"]) == ("efes pilsen", 7500)
    assert services.barcodes.resolve(YENI).product_id == pencere.product_id


def test_kategori_zorunlu(pencere, services):
    pencere.define_button.click()
    pencere.name_field.set_value("Kategorisiz")
    pencere.price_field.set_value("10")
    pencere.save_button.click()
    assert pencere.result() == 0
    assert "Kategori seçin" in pencere.message_label.text()
    assert services.db.scalar("SELECT COUNT(*) FROM products WHERE name='Kategorisiz'") == 0


def test_son_kullanilan_kategori_cipleri_ve_yerinde_olusturma(qapp, services):
    from app.services.product_service import YeniUrun

    services.products.add_product(YeniUrun("Rakı 70 cl", 50000, _kategori(services, "Rakı")))
    p = ub.UnknownBarcodeDialog(YENI, services)
    try:
        assert p.category_chips[0].text() == "Alkollü İçecekler > Rakı"
        p.category_chips[0].click()
        assert p.category_id == _kategori(services, "Rakı")
        p.show_stage(p.picker)
        p.picker_field.set_value("Fıçı Bira")
        p.refresh_picker()
        olustur = next(d for d in p.picker_buttons
                       if d.property("create_parent") == _kategori(services, "Alkollü İçecekler"))
        olustur.click()
        assert services.categories.path(p.category_id) == "Alkollü İçecekler > Fıçı Bira"
    finally:
        p.deleteLater()


def test_okutma_etkin_barkod_alanina_yazilir(pencere):
    pencere.define_button.click()
    pencere.advanced_button.click()
    pencere.activate(pencere.extra_field)
    pencere.notify_blocked(ScanEvent(code="8690000000005"))
    assert pencere.extra_field.value() == "8690000000005"
    pencere.add_extra_barcode()
    assert pencere.extra_barcodes == [("8690000000005", BarcodeType.ALTERNATE, 1)]
    pencere.activate(pencere.name_field)
    pencere.notify_blocked(ScanEvent(code="8690000000012"))
    assert pencere.name_field.value() == "", "ad alanına barkod yazılmaz"


def test_mal_kabulde_baslangic_stogu_sorulmaz(qapp, services):
    p = ub.UnknownBarcodeDialog(YENI, services, context=ub.BAGLAM_STOK)
    try:
        assert p.stock_field.isHidden()
    finally:
        p.deleteLater()


def test_pencere_ekrana_sigar(pencere):
    pencere.define_button.click()
    pencere.advanced_button.click()
    assert pencere.minimumSizeHint().height() <= 740
    assert pencere.minimumSizeHint().width() <= 1000


# ===================== Kasa bütünleşmesi ===================================
def _sepet(window, qapp):
    window.go_to("sepetli_satis")
    qapp.processEvents()
    return window.pages["sepetli_satis"]


def test_koli_olarak_tanimlanan_urun_koli_adedi_kadar_eklenir(
    window, qapp, services, monkeypatch, onay
):
    services.settings.set("pack_confirm_in_sale", 0)      # koli sorusu ayrı testte

    def exec_(self):
        self.define_button.click()
        self.name_field.set_value("Su 0,5 L (24'lü koli)")
        self.price_field.set_value("10")
        self.set_category(_kategori(services, "Su"))
        self.barcode_type_combo.setCurrentIndex(
            self.barcode_type_combo.findData(BarcodeType.CASE))
        self.multiplier_field.set_value("24")
        self.save()
        return self.result()

    monkeypatch.setattr(ub.UnknownBarcodeDialog, "exec", exec_)
    kasa = _sepet(window, qapp)
    kasa.handle_scan(ScanEvent(code=YENI))
    qapp.processEvents()
    assert kasa.cart.item_count == 24, "barkod yeniden çözüldü: koli × 24"


def test_mevcut_urune_baglama(window, qapp, services, bira, monkeypatch):
    services.settings.set("pack_confirm_in_sale", 0)

    def exec_(self):
        self.attach_button.click()
        self.attach_field.set_value("tuborg")
        self.refresh_attach()
        self.attach_buttons[0].click()
        self.set_attach_type(BarcodeType.CASE)
        self.attach_multiplier_field.set_value("12")
        self.save()
        return self.result()

    monkeypatch.setattr(ub.UnknownBarcodeDialog, "exec", exec_)
    kasa = _sepet(window, qapp)
    kasa.handle_scan(ScanEvent(code=YENI))
    qapp.processEvents()
    assert services.barcodes.resolve(YENI).product_id == bira
    assert kasa.cart.find(bira).quantity == 12


def test_pasif_urunun_barkodu_urunu_geri_alir(window, qapp, services, bira, monkeypatch):
    services.products.set_active(bira, False)
    acilan = []

    def exec_(self):
        acilan.append(self.reactivate_button.isVisibleTo(self))
        self.reactivate_button.click()
        return self.result()

    monkeypatch.setattr(ub.UnknownBarcodeDialog, "exec", exec_)
    once = services.db.scalar("SELECT COUNT(*) FROM products")
    kasa = _sepet(window, qapp)
    kasa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    assert acilan == [True], "geri alma önerildi"
    assert services.products.get(bira)["is_active"] == 1
    assert services.db.scalar("SELECT COUNT(*) FROM products") == once, "çift ürün yok"
    assert kasa.cart.find(bira).quantity == 1


def test_mal_kabulde_koli_barkodu_adet_olarak_eklenir(window, qapp, services, monkeypatch):
    def exec_(self):
        assert self.context == ub.BAGLAM_STOK
        self.define_button.click()
        self.name_field.set_value("Kola 330 ml")
        self.price_field.set_value("30")
        self.set_category(_kategori(services, "Kola"))
        self.barcode_type_combo.setCurrentIndex(
            self.barcode_type_combo.findData(BarcodeType.CASE))
        self.multiplier_field.set_value("24")
        self.save()
        return self.result()

    monkeypatch.setattr(ub.UnknownBarcodeDialog, "exec", exec_)
    window.go_to("stok_girisi")
    sayfa = window.pages["stok_girisi"]
    sayfa.handle_scan(ScanEvent(code=YENI))
    qapp.processEvents()
    satirlar = services.purchases.lines(sayfa.receipt_id)
    assert [s["quantity"] for s in satirlar] == [24]
