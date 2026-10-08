"""📦 Mal Kabul (V1.2 M6c, D2).

Korunan sözler:
  * başlık düzenlenebilir: tedarikçi (listeden ya da yeni ad), fatura no,
    fatura tarihi; yalnızca taslakta,
  * satırlar Önceki alış / Yeni alış / Değişim % / Satış / Tahmini marj
    gösterir; marj yalnızca bilinen alışla,
  * satır adedi −/+/adet girişi/koli ile değişir, satır silinir,
  * 0 TL alış "bedelsiz" demektir ve ayrıca sorulur; bilinmeyen alış
    "bilinmiyor" kalır,
  * alış fiyatı eşikten fazla değişen ürünler fiyat incelemesine düşer; satış
    fiyatı YALNIZCA açık "Fiyatı Güncelle" ile değişir ve "Mal kabul" grubu
    olarak fiyat geçmişine yazılır (toplu güncelleme PIN ister),
  * F10 (Girişi Tamamla) korunur (test_pos_ui).
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate  # noqa: E402

from app.core.errors import FisZatenTamamlanmis  # noqa: E402
from app.core.models import BarcodeType  # noqa: E402
from app.scanner.scan_event import ScanEvent  # noqa: E402
from app.services.pricing_service import MAL_KABUL  # noqa: E402
from app.ui.dialogs import pin_dialog as pd  # noqa: E402
from app.ui.pages.stock_entry import SATIR_SUTUNLARI  # noqa: E402

from conftest import BIRA_BARKOD  # noqa: E402
from ui_support import *  # noqa: E402,F401,F403

KOLI = "8690000000999"
CIPS = "8690000000012"


def _alis(services, pid, adet, maliyet):
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, pid, adet, maliyet)
    services.purchases.commit(fis)
    return fis


# ===================== Servis ==============================================
def test_baslik_yalnizca_taslakta_duzenlenir(services, bira):
    tedarikci = services.suppliers.create("Anadolu Dağıtım")
    fis = services.purchases.start_draft()
    services.purchases.set_header(fis, tedarikci, " F-123 ", "2026-09-30")
    kayit = services.purchases.receipt(fis)
    assert (kayit["supplier_id"], kayit["invoice_no"], kayit["receipt_date"]) == (
        tedarikci, "F-123", "2026-09-30")
    services.purchases.add_line(fis, bira, 1, 5000)
    services.purchases.commit(fis)
    with pytest.raises(FisZatenTamamlanmis):
        services.purchases.set_header(fis, None, "X")


def test_fiyat_onerileri(services, bira, cips_urunu):
    _alis(services, bira, 10, 5000)
    _alis(services, cips_urunu, 10, 3000)
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 5, 5300)
    services.purchases.add_line(fis, bira, 5, 5600)        # son satır geçerli
    services.purchases.add_line(fis, cips_urunu, 5, 3090)  # %3: eşiğin altında
    oneriler = services.pricing.mal_kabul_onerileri(fis, 500, 100)
    assert [(o.product_id, o.onceki_alis, o.yeni_alis) for o in oneriler] == [
        (bira, 5000, 5600)]
    assert oneriler[0].degisim_bp == 1200
    assert oneriler[0].onerilen == 9000              # 80 × 56/50 = 89,6 → 90 TL
    assert oneriler[0].onerilen_marj_bp >= oneriler[0].simdiki_marj_bp
    assert services.pricing.mal_kabul_onerileri(fis, 1300, 100) == []
    services.products.set_price(bira, 8800)                 # incelendi: elle değişti
    assert services.pricing.mal_kabul_onerileri(fis, 500, 100) == []


def test_tahmini_ve_bedelsiz_satir_oneri_uretmez(services, bira):
    _alis(services, bira, 10, 5000)
    fis = services.purchases.start_draft()
    services.purchases.add_line(fis, bira, 5, None)
    services.purchases.add_line(fis, bira, 5, 0)
    assert services.pricing.mal_kabul_onerileri(fis, 1, 100) == []


# ===================== Sayfa ===============================================
@pytest.fixture
def kabul(window, qapp, services, bira):
    services.barcodes.add_barcode(bira, KOLI, BarcodeType.CASE, 24)
    window.go_to("stok_girisi")
    qapp.processEvents()
    return window.pages["stok_girisi"]


def _hucre(sayfa, satir, baslik):
    return sayfa.table.item(satir, SATIR_SUTUNLARI.index(baslik)).text()


def test_yeni_tedarikci_fatura_ve_tarih(kabul, services, bira):
    kabul.supplier_combo.setCurrentText("Yeni Toptancı")
    kabul.invoice_edit.setText("İRS-77")
    kabul.date_edit.setDate(QDate(2026, 9, 30))
    kabul.handle_scan(ScanEvent(code=BIRA_BARKOD))
    fis = services.purchases.receipt(kabul.receipt_id)
    tedarikci = services.suppliers.get(fis["supplier_id"])
    assert tedarikci["name"] == "Yeni Toptancı"
    assert (fis["invoice_no"], fis["receipt_date"]) == ("İRS-77", "2026-09-30")

    kabul.invoice_edit.setText("İRS-78")
    kabul.invoice_edit.editingFinished.emit()
    assert services.purchases.receipt(kabul.receipt_id)["invoice_no"] == "İRS-78"
    assert services.db.scalar("SELECT COUNT(*) FROM suppliers") == 1, "çift tedarikçi yok"


def test_satir_sutunlari_ve_marj(kabul, services, bira):
    _alis(services, bira, 10, 5000)
    kabul.handle_scan(ScanEvent(code=BIRA_BARKOD))
    kabul.select_line(0)
    assert kabul.set_selected_cost(5500)
    assert _hucre(kabul, 0, "Önceki alış") == "50 TL"
    assert _hucre(kabul, 0, "Yeni alış") == "55 TL"
    assert _hucre(kabul, 0, "Değişim") == "%10"
    assert _hucre(kabul, 0, "Satış") == "80 TL"
    assert _hucre(kabul, 0, "Tahmini marj") == "%31,25"


def test_bilinmeyen_alis_ve_bedelsiz(kabul, services, cips_urunu, onay):
    services.barcodes.add_barcode(cips_urunu, CIPS)          # alışı hiç bilinmiyor
    kabul.handle_scan(ScanEvent(code=CIPS))
    assert _hucre(kabul, 0, "Yeni alış") == "bilinmiyor"
    assert _hucre(kabul, 0, "Tahmini marj") == "—"
    assert "fiyatı bilinmiyor" in kabul.total_label.text()
    kabul.select_line(0)
    onay.cevap = False
    assert not kabul.set_selected_cost(0)
    assert _hucre(kabul, 0, "Yeni alış") == "bilinmiyor"
    onay.cevap = True
    assert kabul.set_selected_cost(0)
    assert "bedelsiz mi geldi?" in onay.sorular[-1]
    assert _hucre(kabul, 0, "Yeni alış") == "bedelsiz"


def test_satir_adedi_koli_ve_silme(kabul, services, bira):
    kabul.handle_scan(ScanEvent(code=BIRA_BARKOD))
    kabul.select_line(0)
    kabul.plus_button.click()
    kabul.plus_button.click()
    assert services.purchases.lines(kabul.receipt_id)[0]["quantity"] == 3
    kabul.minus_button.click()
    assert services.purchases.lines(kabul.receipt_id)[0]["quantity"] == 2
    assert kabul.case_button.isVisibleTo(kabul) and kabul.case_button.text() == "+1 koli (×24)"
    kabul.case_button.click()
    assert services.purchases.lines(kabul.receipt_id)[0]["quantity"] == 26
    kabul.set_selected_quantity(7)
    assert services.purchases.lines(kabul.receipt_id)[0]["quantity"] == 7
    kabul.remove_button.click()
    assert services.purchases.lines(kabul.receipt_id) == []


def test_fiyat_incelemesi_onaysiz_fiyat_degistirmez(kabul, services, bira, onay):
    _alis(services, bira, 10, 5000)
    kabul.handle_scan(ScanEvent(code=BIRA_BARKOD))
    kabul.select_line(0)
    kabul.set_selected_cost(5600)
    assert [o.product_id for o in kabul.review_rows()] == [bira]
    assert kabul.review_card.isVisibleTo(kabul)
    kabul.complete()
    assert services.products.get(bira)["sale_price"] == 8000, "açık onay olmadan değişmez"
    assert kabul.receipt_id is None and kabul.review_rows(), "inceleme tamamlanınca da durur"
    assert "fiyat incelemesine" in kabul.banner.extra.text()

    assert kabul.apply_price_updates([bira]) == 1
    assert services.products.get(bira)["sale_price"] == 9000
    grup = services.db.query_one("SELECT * FROM price_change_batches")
    assert grup["kind"] == MAL_KABUL
    assert kabul.review_rows() == [], "fiyatı güncellenen ürün incelemeden düşer"


def test_toplu_fiyat_guncelleme_pin_ister(kabul, services, bira, cips_urunu, onay,
                                         monkeypatch):
    services.barcodes.add_barcode(cips_urunu, CIPS)
    _alis(services, bira, 10, 5000)
    _alis(services, cips_urunu, 10, 3000)
    services.security.set_pin("4826")
    monkeypatch.setattr(pd.PinDialog, "ask",
                        staticmethod(lambda parent, security, action_label="": pd.VAZGECILDI))
    for kod, maliyet in ((BIRA_BARKOD, 6000), (CIPS, 3600)):
        kabul.handle_scan(ScanEvent(code=kod))
    for i in range(2):
        kabul.select_line(i)
        kabul.set_selected_cost(6000 if i == 0 else 3600)
    assert len(kabul.review_rows()) == 2
    assert kabul.apply_price_updates([bira, cips_urunu]) == 0
    assert services.products.get(bira)["sale_price"] == 8000
    assert kabul.apply_price_updates([bira]) == 1, "tek ürün tek fiyat düzenlemesidir"


def test_esik_ayari(kabul, services, bira):
    _alis(services, bira, 10, 5000)
    services.settings.set("cost_change_alert_percent", 20)
    kabul.handle_scan(ScanEvent(code=BIRA_BARKOD))
    kabul.select_line(0)
    kabul.set_selected_cost(5600)
    assert kabul.review_rows() == [] and not kabul.review_card.isVisibleTo(kabul)


def test_kurtarilan_taslak_basligi_yuklenir(window, qapp, services, bira, onay):
    tedarikci = services.suppliers.create("Kuzey Gıda")
    fis = services.purchases.start_draft(tedarikci, "F-9", "2026-09-28")
    services.purchases.add_line(fis, bira, 3, 5000)
    window.go_to("stok_girisi")
    qapp.processEvents()
    sayfa = window.pages["stok_girisi"]
    assert sayfa.receipt_id == fis
    assert sayfa.supplier_combo.currentText() == "Kuzey Gıda"
    assert sayfa.invoice_edit.text() == "F-9"
    assert sayfa.receipt_date() == "2026-09-28"
