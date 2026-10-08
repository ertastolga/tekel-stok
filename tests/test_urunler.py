"""Ürün düzenleme ve Ürünler sayfası (V1.2 M4c — D-09, D-10).

Korunan sözler:
  * düzenleme penceresinde yapılan her şey yalnızca "Kaydet"te ve TEK işlemde
    yazılır; "Vazgeç" (barkod ekleme/kaldırma dahil) hiçbir şeyi değiştirmez,
  * kaydetmek esas rafı SİLMEZ; kaldırılmış kategori kaydedince kaybolmaz,
  * tedarikçi, etiketler ve referans alış (katalog) fiyatı düzenlenebilir;
    referans alış stok değerine / "son alış"a GİRMEZ,
  * ``update`` yalnızca beyaz listedeki alanları yazar ve değişeni denetime
    kaydeder,
  * Ürünler sayfasında düğmeler seçime göre açılır, pasif ürünler bulunur ve
    geri alınır, çoklu seçimle önizlemeli toplu "Kategoriye Taşı" yapılır,
  * liste satır başına sorgu yapmaz.
"""
from __future__ import annotations

import json
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from app.core.errors import KategoriGerekli  # noqa: E402
from app.ui.dialogs.product_edit import MODE_EDIT, ProductEditDialog  # noqa: E402
from app.ui.pages import products as urunler_sayfasi  # noqa: E402

from conftest import BIRA_BARKOD  # noqa: E402
from ui_support import *  # noqa: E402,F401,F403

YENI_BARKOD = "8690000000999"


def _kategori(services, ad):
    return services.db.scalar("SELECT id FROM categories WHERE name = ?", (ad,))


def _esas_raf(services, pid):
    return services.db.scalar(
        "SELECT location_id FROM product_locations "
        " WHERE product_id = ? AND active = 1 AND is_primary = 1", (pid,),
    )


def _denetim(services, eylem):
    return services.db.query(
        "SELECT * FROM audit_log WHERE action = ? ORDER BY id", (eylem,)
    )


@pytest.fixture
def pencere(qapp, services, bira):
    p = ProductEditDialog(services, bira, MODE_EDIT)
    yield p
    p.deleteLater()


# ===================== Servis ==============================================
def test_update_beyaz_liste_ve_denetim_farki(services, bira):
    with pytest.raises(ValueError):
        services.products.update(bira, current_stock=999)
    with pytest.raises(ValueError):
        services.products.update(bira, is_active=0)
    assert services.products.get(bira)["current_stock"] == 0

    eski = services.products.get(bira)["min_stock"]
    services.products.update(bira, name="Tuborg Gold 50 cl Kutu", min_stock=eski + 5)
    satirlar = _denetim(services, "URUN_DUZENLE")
    assert len(satirlar) == 1
    assert json.loads(satirlar[0]["details_json"]) == {"min_stock": [eski, eski + 5]}, \
        "yalnızca DEĞİŞEN alan denetime yazılır"

    services.products.update(bira, min_stock=eski + 5)
    assert len(_denetim(services, "URUN_DUZENLE")) == 1, "değişiklik yoksa kayıt yok"


def test_set_locations_esas_rafi_korur(services, bira):
    assert _esas_raf(services, bira) == 1
    services.catalog.set_locations(bira, [1, 8])
    assert _esas_raf(services, bira) == 1
    assert services.catalog.active_location_ids(bira) == {1, 8}
    services.catalog.set_locations(bira, [8])
    assert services.catalog.active_location_ids(bira) == {8}


def test_save_edit_tek_islem_hata_olursa_hicbiri_yazilmaz(services, bira, cips_urunu):
    cips_barkod = "8690000000012"
    services.barcodes.add_barcode(cips_urunu, cips_barkod)
    with pytest.raises(Exception):
        services.products.save_edit(
            bira, {"name": "Değişmiş Ad"}, sale_price=9900,
            brand_name="Yeni Marka", tags=["soğuk"], location_ids=[1, 8],
            barcode_adds=[(cips_barkod, "UNIT", 1)],          # başka üründe!
        )
    urun = services.products.get(bira)
    assert (urun["name"], urun["sale_price"]) == ("Tuborg Gold 50 cl Kutu", 8000)
    assert services.catalog.active_location_ids(bira) == {1}
    assert services.db.scalar("SELECT COUNT(*) FROM brands WHERE name = 'Yeni Marka'") == 0
    assert services.db.scalar("SELECT COUNT(*) FROM price_history WHERE product_id = ?",
                              (bira,)) == 0


def test_referans_alis_maliyete_girmez(services, bira):
    services.products.save_edit(bira, {}, reference_cost=4200)
    urun = services.products.get(bira)
    assert urun["reference_cost"] == 4200
    assert urun["reference_cost_updated_at_utc"] is not None
    assert urun["last_purchase_cost"] in (None, 0)
    services.products.save_edit(bira, {}, reference_cost=None)
    assert services.products.get(bira)["reference_cost"] is None


def test_toplu_kategoriye_tasima(services, bira, cips_urunu):
    bira_kat = _kategori(services, "Bira")
    assert services.products.move_to_category([bira, cips_urunu, bira], bira_kat) == 2
    assert services.products.get(cips_urunu)["category_id"] == bira_kat
    assert services.products.move_to_category([bira], bira_kat) == 0
    denetim = _denetim(services, "URUN_TOPLU_KATEGORI")
    assert json.loads(denetim[0]["details_json"]) == {"urunler": [bira, cips_urunu]}

    services.categories.deactivate(_kategori(services, "Cin"))
    with pytest.raises(KategoriGerekli):
        services.products.move_to_category([bira], _kategori(services, "Cin"))


def test_pasif_arama_ve_ilk_barkodlar(services, bira, cips_urunu):
    services.products.set_active(cips_urunu, False)
    assert [u["id"] for u in services.products.search(only_inactive=True)] == [cips_urunu]
    assert bira not in [u["id"] for u in services.products.search(only_inactive=True)]
    assert services.products.first_barcodes([bira, cips_urunu]) == {bira: BIRA_BARKOD}


def test_kategori_yollari(services):
    yollar = services.categories.paths()
    assert yollar[_kategori(services, "Rakı")] == "Alkollü İçecekler > Rakı"
    assert yollar[_kategori(services, "Tütün Aksesuarı")] == "Tütün > Tütün Aksesuarı"


# ===================== Düzenleme penceresi (D-09) ==========================
def test_kaydetmek_esas_rafi_silmez(pencere, services, bira):
    pencere._save()
    assert pencere.result() == 1
    assert _esas_raf(services, bira) == 1, "V1.1: düzenleme kaydı esas rafı siliyordu"


def test_vazgec_barkod_degisikliklerini_yazmaz(pencere, services, bira, onay):
    pencere.new_barcode_edit.setText(YENI_BARKOD)
    pencere._add_barcode()
    pencere.barcode_list.setCurrentRow(0)                 # kayıtlı BIRA barkodu
    pencere._remove_barcode()
    assert services.barcodes.resolve(YENI_BARKOD) is None, "Kaydet'e kadar bekler"
    pencere.reject()
    assert services.barcodes.resolve(YENI_BARKOD) is None
    assert services.barcodes.resolve(BIRA_BARKOD).product_id == bira


def test_barkod_degisiklikleri_kaydedince_yazilir(pencere, services, bira, onay):
    pencere.new_barcode_edit.setText(YENI_BARKOD)
    pencere._add_barcode()
    pencere.barcode_list.setCurrentRow(0)
    pencere._remove_barcode()
    pencere._save()
    assert pencere.result() == 1
    assert services.barcodes.resolve(YENI_BARKOD).product_id == bira
    assert services.barcodes.resolve(BIRA_BARKOD) is None


def test_okuyucu_enteri_pencereyi_kaydetmez(pencere, services):
    pencere.show()
    pencere.tabs.setCurrentIndex(1)
    pencere.new_barcode_edit.setFocus()
    QTest.keyClicks(pencere.new_barcode_edit, YENI_BARKOD)
    QTest.keyClick(pencere.new_barcode_edit, Qt.Key.Key_Return)
    assert pencere.isVisible() and pencere.result() == 0, "Enter kaydetmedi"
    assert [b for b, _, _ in pencere.pending_barcode_adds] == [YENI_BARKOD]
    assert services.barcodes.resolve(YENI_BARKOD) is None


def test_kaldirilmis_kategori_kaydedince_kaybolmaz(qapp, services, bira):
    cin = _kategori(services, "Cin")
    services.products.update(bira, category_id=cin)
    services.categories.deactivate(cin)
    p = ProductEditDialog(services, bira, MODE_EDIT)
    try:
        assert p.category_combo.currentText() == "Alkollü İçecekler > Cin (pasif)"
        p._save()
        assert services.products.get(bira)["category_id"] == cin
    finally:
        p.deleteLater()


def test_tedarikci_etiket_ve_referans_alis(qapp, services, bira):
    tedarikci = services.suppliers.create("Anadolu Dağıtım")
    pencere = ProductEditDialog(services, bira, MODE_EDIT)
    pencere.supplier_combo.setCurrentIndex(pencere.supplier_combo.findData(tedarikci))
    pencere.tags_edit.setText("soğuk, kutu")
    pencere.reference_edit.setText("42,50")
    pencere._save()
    pencere.deleteLater()
    urun = services.products.get(bira)
    assert urun["default_supplier_id"] == tedarikci
    assert urun["reference_cost"] == 4250
    assert [t["name"] for t in services.catalog.tags_of(bira)] == ["kutu", "soğuk"]

    p = ProductEditDialog(services, bira, MODE_EDIT)
    try:
        assert p.supplier_combo.currentData() == tedarikci
        assert p.tags_edit.text() == "kutu, soğuk"
        assert p.reference_edit.text() == "42,50"
    finally:
        p.deleteLater()


def test_yarim_kayit_olmaz(pencere, services, bira, monkeypatch):
    def patla(*a, **k):
        raise RuntimeError("disk dolu")

    monkeypatch.setattr(services.catalog, "set_locations", patla)
    pencere.name_edit.setText("Yarım Kalan Ad")
    pencere.price_edit.setText("99")
    pencere._save()
    assert pencere.result() == 0
    urun = services.products.get(bira)
    assert (urun["name"], urun["sale_price"]) == ("Tuborg Gold 50 cl Kutu", 8000), \
        "V1.1: ad ve fiyat yazılıp raflar yazılamıyordu"


# ===================== Ürünler sayfası (D-10) ==============================
@pytest.fixture
def urunler(window, qapp):
    window.go_to("urunler")
    qapp.processEvents()
    return window.pages["urunler"]


def _sec(sayfa, *satirlar):
    secim = sayfa.table.selectionModel()
    secim.clearSelection()
    for satir in satirlar:
        secim.select(
            sayfa.table.model().index(satir, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )


def _satir(sayfa, pid):
    return [u["id"] for u in sayfa._current].index(pid)


def test_secim_dugmeleri_acar(urunler, bira):
    assert not urunler.edit_button.isEnabled()
    urunler.table.selectRow(_satir(urunler, bira))
    assert urunler.edit_button.isEnabled(), "V1.1: seçim düğmeleri açmıyordu"
    assert urunler.deactivate_button.isEnabled() and urunler.move_button.isEnabled()


def test_coklu_secim_ve_toplu_tasima(urunler, services, bira, cips_urunu, onay):
    urunler.refresh()
    _sec(urunler, _satir(urunler, bira), _satir(urunler, cips_urunu))
    assert not urunler.edit_button.isEnabled(), "düzenleme tek ürün ister"
    assert urunler.move_button.isEnabled()
    assert urunler.move_button.text() == "Kategoriye Taşı (2)"

    cips_kat = _kategori(services, "Cips")
    assert urunler.move_selected_to(cips_kat) == 2
    assert "2 ürün Atıştırmalık > Cips kategorisine taşınsın mı?" in onay.sorular[-1]
    assert services.products.get(bira)["category_id"] == cips_kat


def test_pasif_urun_bulunur_ve_geri_alinir(urunler, services, bira, onay):
    services.products.set_active(bira, False)
    urunler.refresh()
    assert bira not in [u["id"] for u in urunler._current]
    urunler.usage_combo.setCurrentIndex(urunler.usage_combo.findData(urunler_sayfasi.PASIFLER))
    assert [u["id"] for u in urunler._current] == [bira], "V1.1: pasifler bulunamıyordu"
    urunler.table.selectRow(0)
    # M12b terim birliği: "Yeniden Kullan" → "Yeniden Kullanıma Al" (aynı sınama).
    assert urunler.deactivate_button.text() == "Yeniden Kullanıma Al"
    urunler._toggle_active()
    assert services.products.get(bira)["is_active"] == 1
    assert services.barcodes.resolve(BIRA_BARKOD).product_id == bira, "barkod geri açıldı"


def test_liste_satir_basina_sorgu_yapmaz(urunler, services, bira, cips_urunu, monkeypatch):
    def yasak(*a, **k):
        raise AssertionError("satır başına sorgu")

    monkeypatch.setattr(services.barcodes, "barcodes_of", yasak)
    monkeypatch.setattr(services.catalog, "category_path", yasak)
    monkeypatch.setattr(services.categories, "path", yasak)
    urunler.refresh()
    assert len(urunler._current) >= 2
    satir = _satir(urunler, bira)
    assert urunler.table.item(satir, 5).text() == BIRA_BARKOD
