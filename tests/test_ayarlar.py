"""Ayarlar kabuğu (V1.2 M2e).

Korunan sözler:
  * kullanıcıya açık her ayar TAM OLARAK bir bölümde, iç ayarlar hiçbirinde
    (``keys.py`` ↔ ``DEFAULT_SETTINGS``) ve her ayarın denetimi kendi bölümünde,
  * her denetim değiştiği anda YALNIZCA kendi anahtarını kaydeder,
  * "Gelişmiş" ayarlar "Varsayılana dön" ile fabrika değerine döner,
  * PIN kurulmamışsa öneri şeridi zorlamadan görünür ve kapatılabilir; PIN'i
    kaldırmak PIN ister,
  * hata iletisi teknik ayrıntıyı kullanıcıya göstermez.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from app.core import schema as schema_mod  # noqa: E402
from app.core.errors import YedekOkunamadi  # noqa: E402
from app.ui import metrics  # noqa: E402
from app.ui.dialogs import pin_dialog as pd  # noqa: E402
from app.ui.pages.settings.keys import AYAR_BOLUMU, BOLUMLER, IC_AYARLAR, ic_mi  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403


@pytest.fixture
def ayarlar(window, qapp):
    window.go_to("ayarlar")
    qapp.processEvents()
    return window.pages["ayarlar"]


# ===================== Anahtar ↔ bölüm tablosu =============================
def test_her_ayar_ya_tam_bir_bolumde_ya_ic():
    bolum_kimlikleri = {k for k, _ in BOLUMLER}
    for anahtar in schema_mod.DEFAULT_SETTINGS:
        if ic_mi(anahtar):
            assert anahtar not in AYAR_BOLUMU, f"{anahtar} hem iç hem bölümde"
        else:
            assert anahtar in AYAR_BOLUMU, f"{anahtar} hiçbir bölümde değil"
    for anahtar, bolum in AYAR_BOLUMU.items():
        assert anahtar in schema_mod.DEFAULT_SETTINGS, anahtar
        assert bolum in bolum_kimlikleri
    assert not (set(AYAR_BOLUMU) & IC_AYARLAR)


def test_her_ayarin_denetimi_kendi_bolumunde(ayarlar):
    for anahtar, bolum in AYAR_BOLUMU.items():
        denetim = ayarlar.kontroller.get(anahtar)
        assert denetim is not None, f"{anahtar} için denetim yok"
        assert ayarlar.bolumler[bolum].isAncestorOf(denetim), anahtar
    for anahtar in schema_mod.DEFAULT_SETTINGS:
        if ic_mi(anahtar):
            assert anahtar not in ayarlar.kontroller


def test_bolumler_sirali_ve_dokunma_boyutunda(ayarlar):
    sira = [k for k, _ in BOLUMLER if k in ayarlar.bolumler]
    assert sira == ["kasa", "ses", "barkod", "isletme", "stok", "yedekleme", "guvenlik"]
    for kimlik, dugme in ayarlar.section_buttons.items():
        assert dugme.minimumHeight() >= metrics.TOUCH_TARGET_MIN
        dugme.click()
        assert ayarlar.current_section() == kimlik


# ===================== Kaydetme =============================================
def test_denetim_yalnizca_kendi_anahtarini_kaydeder(ayarlar, services):
    once = {k: services.settings.get(k) for k in AYAR_BOLUMU}
    ayarlar.hold_spin.setValue(6500)
    ayarlar.vat_spin.setValue(10)
    ayarlar.quick_sale_check.setChecked(False)
    sonra = {k: services.settings.get(k) for k in AYAR_BOLUMU}
    degisen = {k for k in AYAR_BOLUMU if once[k] != sonra[k]}
    assert degisen == {"customer_display_hold_ms", "default_vat_rate", "show_quick_sale"}
    assert services.settings.customer_display_hold_ms() == 6500
    assert services.settings.default_vat_rate() == 10


def test_hizli_satis_kapatilinca_menuden_hemen_kalkar(window, ayarlar):
    ayarlar.quick_sale_check.setChecked(False)
    assert not window.nav_buttons["hizli_satis"].isVisibleTo(window)
    ayarlar.quick_sale_check.setChecked(True)
    assert window.nav_buttons["hizli_satis"].isVisibleTo(window)


def test_on_ek_ve_son_ek_kaydedilir(ayarlar, services):
    ayarlar.prefix_edit.setText("]C1")
    ayarlar.prefix_edit.editingFinished.emit()
    assert services.settings.barcode_trim_prefix() == "]C1"


def test_gelismis_ayar_varsayilana_doner(ayarlar, services):
    ayarlar.hold_spin.setValue(9000)
    ayarlar.reset_to_default("customer_display_hold_ms")
    assert services.settings.get("customer_display_hold_ms") == (
        schema_mod.DEFAULT_SETTINGS["customer_display_hold_ms"]
    )
    assert ayarlar.hold_spin.value() == 4000
    dugme = ayarlar.findChild(type(ayarlar.day_button), "varsayilan_barcode_trim_suffix")
    assert dugme is not None
    ayarlar.suffix_edit.setText("X")
    ayarlar.suffix_edit.editingFinished.emit()
    dugme.click()
    assert services.settings.barcode_trim_suffix() == ""


# ===================== Güvenlik bölümü =====================================
def test_pin_onerisi_zorlamadan_gorunur_ve_kapatilir(window, qapp, services, ayarlar):
    assert ayarlar.pin_hint.isVisibleTo(ayarlar)
    assert "kurulmamış" in ayarlar.pin_status.text()
    ayarlar.pin_hint_dismiss.click()
    assert not ayarlar.pin_hint.isVisibleTo(ayarlar)
    ayarlar.refresh()
    assert not ayarlar.pin_hint.isVisibleTo(ayarlar), "kalıcı"


def test_pin_kaldirmak_pin_ister(window, qapp, services, ayarlar, monkeypatch, onay):
    services.security.set_pin("4826")
    window.guard.lock()
    ayarlar.refresh()
    assert not ayarlar.pin_remove_button.isHidden()
    assert ayarlar.pin_set_button.text() == "PIN'i değiştir"
    cevap = {"deger": pd.VAZGECILDI}
    monkeypatch.setattr(pd.PinDialog, "ask", staticmethod(lambda *a, **k: cevap["deger"]))
    onay.cevap = True
    ayarlar._pin_kaldir()
    assert services.security.has_pin()
    cevap["deger"] = pd.DOGRULANDI
    ayarlar._pin_kaldir()
    assert not services.security.has_pin()
    assert "kurulmamış" in ayarlar.pin_status.text()


# ===================== Hata iletileri ======================================
def test_geri_yukleme_hatasi_teknik_ayrintiyi_gostermez(
    ayarlar, services, monkeypatch, tmp_path
):
    gorulen = []

    def exec_(kutu):
        gorulen.append((kutu.text(), kutu.informativeText()))
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", exec_)

    def bozuk(yol):
        raise YedekOkunamadi("sqlite3.DatabaseError: file is not a database")

    monkeypatch.setattr(services.backup, "inspect", bozuk)
    from PySide6.QtWidgets import QListWidgetItem

    oge = QListWidgetItem("x")
    oge.setData(32, str(tmp_path / "x.db"))
    ayarlar.backup_list.addItem(oge)
    ayarlar.backup_list.setCurrentItem(oge)
    ayarlar._restore()
    assert gorulen and "sqlite3" not in "".join(f"{a} {b}" for a, b in gorulen)
