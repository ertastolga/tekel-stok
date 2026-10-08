"""📄 Ürün İçe Aktar sihirbazı (V1.2 M7b).

Korunan sözler:
  * dosya → sütunlar (otomatik eşleme, düzeltilebilir) → önizleme → sonuç;
    önizleme hiçbir şey yazmaz,
  * aynı sütun iki bilgiye eşlenemez,
  * durum süzgeci, satır satır değişiklik/sorun, güncellenecek alanlar tek tek
    seçilir (varsayılan satış + alış), sıfır önerisi yalnızca seçilen satırda,
  * hata raporu ve örnek şablon CSV olarak kaydedilir (şablon tekrar okunur),
  * İçe Aktar PIN ister (PIN varsa) ve onaydan sonra tek işlemde yazar.
"""
from __future__ import annotations

import csv
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core import barcode_text as bt  # noqa: E402
from app.importers import alanlar as al  # noqa: E402
from app.importers.okuyucu import oku  # noqa: E402
from app.services import import_service as ims  # noqa: E402
from app.ui.dialogs import pin_dialog as pd  # noqa: E402
from app.ui.pages import import_page as ip  # noqa: E402

from conftest import BIRA_BARKOD  # noqa: E402
from ui_support import *  # noqa: E402,F401,F403


def _gtin13(govde12: str) -> str:
    return govde12 + str(bt.gtin_check_digit(govde12))


@pytest.fixture
def sayfa(window, qapp):
    window.go_to("ice_aktar")
    qapp.processEvents()
    return window.pages["ice_aktar"]


@pytest.fixture
def liste(tmp_path):
    yol = tmp_path / "toptanci.csv"
    eksik = _gtin13("001234567890")[2:]
    satirlar = [
        "Barkod;Ürün adı;Satış fiyatı;Kategori;Alış fiyatı;Not",
        f"{_gtin13('869000000201')};Yeni Soda 200 ml;12,50;Soda;8;",
        f"{BIRA_BARKOD};Tuborg Gold 50 cl;85;;55;fiyat zammı",
        f"{eksik};Kısa Barkod;10;Su;;",
        "8,69E+12;Bozuk;10;Su;;",
    ]
    yol.write_bytes(("\r\n".join(satirlar) + "\r\n").encode("utf-8-sig"))
    return yol


def test_sihirbaz_akisi(sayfa, services, bira, liste, onay):
    assert sayfa.stack.currentIndex() == ip.DOSYA
    assert sayfa.load_file(liste)
    assert sayfa.stack.currentIndex() == ip.SUTUNLAR
    assert sayfa.mapping() == {al.BARKOD: 0, al.AD: 1, al.SATIS: 2, al.KATEGORI: 3,
                               al.ALIS: 4}
    once = services.db.scalar("SELECT COUNT(*) FROM products")
    assert sayfa.preview()
    assert services.db.scalar("SELECT COUNT(*) FROM products") == once, "önizleme yazmaz"
    assert sayfa.stack.currentIndex() == ip.ONIZLEME
    assert "Geçerli yeni ürün: 2" in sayfa.counts_label.text()
    assert "Geçersiz barkod: 1" in sayfa.counts_label.text()
    assert sayfa.apply_button.text() == "İçe Aktar (2 yeni, 1 güncelleme)"
    guncel = next(i for i in range(sayfa.preview_table.rowCount())
                  if sayfa.preview_table.item(i, 2).text() == BIRA_BARKOD)
    assert sayfa.preview_table.item(guncel, 4).text() == (
        "Ürün adı: Tuborg Gold 50 cl Kutu → Tuborg Gold 50 cl; "
        "Satış fiyatı: 80 TL → 85 TL; Alış fiyatı (katalog): — → 55 TL"), \
        "bütün farklar gösterilir; yalnızca seçilen bilgiler yazılır"

    assert sayfa.apply()
    assert "2 yeni ürün eklenecek, 1 ürün güncellenecek" in onay.ayrintilar[-1]
    assert sayfa.stack.currentIndex() == ip.SONUC
    assert services.products.get(bira)["sale_price"] == 8500
    assert services.barcodes.resolve(_gtin13("869000000201")) is not None
    assert "geri alınabilir" in sayfa.result_hint.text()


def test_ayni_sutun_iki_bilgiye_eslenemez(sayfa, liste):
    sayfa.load_file(liste)
    sayfa.mapping_combos[al.MARKA].setCurrentIndex(
        sayfa.mapping_combos[al.MARKA].findData(1))            # "Ürün adı" sütunu
    assert not sayfa.preview()
    assert sayfa.stack.currentIndex() == ip.SUTUNLAR


def test_durum_suzgeci_ve_alan_secimi(sayfa, services, bira, liste):
    sayfa.load_file(liste)
    sayfa.preview()
    sayfa.status_filter.setCurrentIndex(sayfa.status_filter.findData(ims.GECERSIZ))
    assert sayfa.preview_table.rowCount() == 1
    assert "bilimsel" in sayfa.preview_table.item(0, 4).text()
    sayfa.field_checks[al.SATIS].setChecked(False)
    sayfa.field_checks[al.ALIS].setChecked(False)
    assert sayfa.apply_button.text() == "İçe Aktar (2 yeni, 0 güncelleme)"
    assert sayfa.selected_fields() == frozenset()


def test_sifir_onerisi_secilen_satirda(sayfa, services, liste, onay):
    sayfa.load_file(liste)
    sayfa.preview()
    kisa = next(s for s in sayfa.plan.satirlar if s.sifir_onerisi)
    sayfa.accept_zero_suggestions([kisa.satir_no])
    satir = next(s for s in sayfa.plan.satirlar if s.satir_no == kisa.satir_no)
    assert satir.barkod == _gtin13("001234567890") and satir.sifir_onerisi is None
    sayfa.apply()
    assert services.barcodes.resolve(_gtin13("001234567890")) is not None


def test_hata_raporu_ve_sablon(sayfa, liste, tmp_path):
    sayfa.load_file(liste)
    sayfa.preview()
    rapor = tmp_path / "hatalar.csv"
    assert sayfa.save_error_report(rapor) == 2                 # bilimsel + öneri uyarısı
    with open(rapor, encoding="utf-8-sig", newline="") as dosya:
        satirlar = list(csv.reader(dosya, delimiter=";"))
    assert satirlar[0] == ["Satır", "Durum", "Barkod", "Ürün adı", "Neden"]

    sablon = tmp_path / "sablon.csv"
    ip.ImportPage.save_template(sablon)
    tablo = oku(sablon)
    assert set(al.otomatik_esle(tablo.basliklar)) == set(al.ALAN_ADLARI), \
        "şablonun her sütunu kendiliğinden eşlenir"


def test_ice_aktarma_pin_ister(sayfa, services, bira, liste, onay, monkeypatch):
    services.security.set_pin("4826")
    sorulan = []

    def ask(parent, security, action_label=""):
        sorulan.append(action_label)
        return pd.VAZGECILDI

    monkeypatch.setattr(pd.PinDialog, "ask", staticmethod(ask))
    sayfa.load_file(liste)
    sayfa.preview()
    assert not sayfa.apply()
    assert sorulan and services.products.get(bira)["sale_price"] == 8000


def test_okunamayan_dosya_adimi_degistirmez(sayfa, tmp_path):
    (tmp_path / "eski.xls").write_bytes(b"\xd0\xcf")
    assert not sayfa.load_file(tmp_path / "eski.xls")
    assert sayfa.stack.currentIndex() == ip.DOSYA
    assert not sayfa.handle_back()


def test_geri_tusu_adimlarda_geri_gider(sayfa, liste):
    sayfa.load_file(liste)
    sayfa.preview()
    assert sayfa.handle_back() and sayfa.stack.currentIndex() == ip.SUTUNLAR
    assert sayfa.handle_back() and sayfa.stack.currentIndex() == ip.DOSYA


def test_secilmeyen_ad_yazilmaz(sayfa, services, bira, liste, onay):
    sayfa.load_file(liste)
    sayfa.preview()
    sayfa.apply()
    assert services.products.get(bira)["name"] == "Tuborg Gold 50 cl Kutu"
