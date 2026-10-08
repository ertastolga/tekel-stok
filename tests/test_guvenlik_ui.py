"""Yönetici PIN'i arayüzü (V1.2 M2c).

Korunan sözler:
  * PIN penceresinde okuyucu dizisi + Enter HİÇBİR deneme saymaz,
  * kilit ve kalan hak pencerede görünür; kurtarma kodu yeni PIN'e götürür,
  * kapı: PIN yoksa sormaz; doğru PIN 5 dk'lık oturum açar; Kasa sayfası
    gösterilince ya da etkileşimsiz 5 dk sonra oturum kapanır,
  * korunan eylemler (ürün pasif, geçmiş satış / fiş geri alma, stok yeniden
    hesaplama, geri yükleme) PIN olmadan yapılamaz; Kasa'da aynı günün son
    satışı PIN'siz geri alınır, önceki günün satışı alınamaz,
  * sıfırlama bildirimi Yönetim'de görünür, Kasa'da görünmez; yeni PIN + kod
    kurulmadan onaylanamaz.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QDialog  # noqa: E402

from app.core import clock  # noqa: E402
from app.scanner.scan_event import ScanEvent  # noqa: E402
from app.services import security_service as g  # noqa: E402
from app.ui.dialogs import pin_dialog as pd  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from fakes import SahteSaat  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403

PIN = "4826"
BIRA = "8690504001492"


def _tikla(numpad, metin):
    for rakam in metin:
        numpad.keys[rakam].click()


@pytest.fixture
def saat():
    s = SahteSaat()
    with clock.use_clock(tekduze=s):
        yield s


@pytest.fixture
def pin_kurulu(services):
    return services.security.set_pin(PIN)


@pytest.fixture
def pin_cevabi(monkeypatch):
    """``PinDialog.ask``'ı yamalar; çağrıları sayar."""
    kayit = {"cevap": pd.DOGRULANDI, "cagri": 0}

    def ask(parent, security, action_label=""):
        kayit["cagri"] += 1
        kayit["etiket"] = action_label
        return kayit["cevap"]

    monkeypatch.setattr(pd.PinDialog, "ask", staticmethod(ask))
    return kayit


# ===================== PIN penceresi =======================================
def test_pin_penceresi_dogru_ve_yanlis_pin(qapp, services, pin_kurulu):
    pencere = pd.PinDialog(services.security, "Ayarlar")
    _tikla(pencere.numpad, "1357")
    pencere.accept_button.click()
    assert pencere.result() == 0 and pencere.sonuc == pd.VAZGECILDI
    assert "4 deneme" in pencere.message_label.text()
    assert pencere.display.value() == ""
    _tikla(pencere.numpad, PIN)
    pencere.accept_button.click()
    assert pencere.sonuc == pd.DOGRULANDI and pencere.result() == QDialog.DialogCode.Accepted


def test_pin_penceresine_okutma_ve_enter_deneme_sayilmaz(qapp, services, pin_kurulu, saat):
    pencere = pd.PinDialog(services.security)
    pencere.show()
    saat.advance(2000)
    for karakter in "8690504001492":
        QTest.keyClicks(pencere, karakter)
        saat.advance(5)
    QTest.keyClick(pencere, Qt.Key.Key_Return)
    QTest.keyClick(pencere, Qt.Key.Key_Enter)
    assert services.settings.get_int(g.HATALI_DENEME) == 0, "hiç deneme yok"
    assert pencere.display.value() == ""
    assert pencere.result() == 0 and pencere.isVisible()
    pencere.deleteLater()


def test_kilitliyken_onay_kapali_ve_sure_gorunur(qapp, services, pin_kurulu):
    for _ in range(5):
        services.security.verify("0000")
    pencere = pd.PinDialog(services.security)
    assert not pencere.accept_button.isEnabled()
    assert "sonra tekrar deneyin" in pencere.message_label.text()


def test_kurtarma_kodu_yeni_pin_akisina_gider(qapp, services, pin_kurulu):
    pencere = pd.PinDialog(services.security)
    pencere.forgot_button.click()
    _tikla(pencere.numpad, pin_kurulu.replace("-", ""))
    pencere.accept_button.click()
    assert pencere.sonuc == pd.KURTARILDI


def test_pin_kurma_penceresi(qapp, services):
    pencere = pd.PinSetupDialog(services.security)
    _tikla(pencere.numpad, "1111")
    pencere.accept_button.click()
    assert "tekrar" in pencere.message_label.text()
    assert not services.security.has_pin()
    _tikla(pencere.numpad, "73915")
    pencere.accept_button.click()
    _tikla(pencere.numpad, "73916")                        # uyuşmuyor
    pencere.accept_button.click()
    assert "aynı değil" in pencere.message_label.text()
    _tikla(pencere.numpad, "73915")
    pencere.accept_button.click()
    _tikla(pencere.numpad, "73915")
    pencere.accept_button.click()
    assert services.security.verify("73915").dogru
    assert pencere.code_label.text() == pencere.recovery_code
    assert pencere.accept_button.text() == "Kodu not aldım"
    pencere.accept_button.click()
    assert pencere.result() == QDialog.DialogCode.Accepted


# ===================== Kapı ve oturum ======================================
def test_pin_yoksa_kapi_sormaz(window, pin_cevabi):
    from app.services.security_service import ProtectedAction

    assert window.guard.require(ProtectedAction.AYARLAR)
    assert pin_cevabi["cagri"] == 0


def test_dogru_pin_oturum_acar_kasa_sayfasi_kapatir(
    window, qapp, pin_kurulu, pin_cevabi, saat
):
    from app.services.security_service import ProtectedAction

    window.go_to("urunler")
    assert window.guard.require(ProtectedAction.URUN_PASIF)
    assert pin_cevabi["etiket"] == "Ürünü kullanımdan kaldırma"
    assert window.guard.require(ProtectedAction.FIS_GERI_AL)
    assert pin_cevabi["cagri"] == 1, "oturum açıkken tekrar sorulmaz"

    window.go_to("sepetli_satis")                          # Kasa
    window.go_to("urunler")
    assert window.guard.require(ProtectedAction.URUN_PASIF)
    assert pin_cevabi["cagri"] == 2, "Kasa sayfası oturumu kapattı"

    saat.advance((300 + 1) * 1000)                         # 5 dk etkileşimsiz
    assert window.guard.require(ProtectedAction.URUN_PASIF)
    assert pin_cevabi["cagri"] == 3


def test_etkilesim_oturumu_canli_tutar(window, qapp, pin_kurulu, pin_cevabi, saat):
    from app.services.security_service import ProtectedAction

    window.go_to("urunler")
    window.guard.require(ProtectedAction.URUN_PASIF)
    for _ in range(4):
        saat.advance(200 * 1000)
        QTest.mouseClick(window.pages["urunler"], Qt.MouseButton.LeftButton)
    assert window.guard.is_unlocked()
    assert pin_cevabi["cagri"] == 1


def test_vazgecilen_pin_korunan_eylemi_yaptirmaz(
    window, qapp, services, bira, pin_kurulu, pin_cevabi, monkeypatch, onay
):
    pin_cevabi["cevap"] = pd.VAZGECILDI
    onay.cevap = True

    # Ürün pasife alma
    window.go_to("urunler")
    urunler = window.pages["urunler"]
    urunler.refresh()
    monkeypatch.setattr(urunler, "_selected", lambda: services.products.get(bira))
    urunler._toggle_active()
    assert services.products.get(bira)["is_active"] == 1

    # Stok yeniden hesaplama
    cagri = []
    monkeypatch.setattr(services.inventory, "recompute", lambda: cagri.append(1))
    window.go_to("stok_durumu")
    window.pages["stok_durumu"]._recompute()
    assert cagri == []

    # Geri yükleme
    geri = []
    monkeypatch.setattr(services.backup, "restore", lambda yol: geri.append(yol))
    window.go_to("ayarlar")                                # M2d: giriş kapısı
    assert window._current_key == "stok_durumu", "PIN'siz Ayarlar'a girilmedi"
    window.pages["ayarlar"]._restore()
    assert geri == []
    assert onay.sorular == [], "PIN'siz hiçbir onay sorusuna bile gelinmedi"
    assert pin_cevabi["cagri"] == 4, "3 eylem + Ayarlar giriş kapısı"


def test_gecmis_satis_geri_alma_pin_ister(window, qapp, services, bira, pin_kurulu, pin_cevabi, onay):
    services.sales.quick_sale(bira)
    pin_cevabi["cevap"] = pd.VAZGECILDI
    onay.cevap = True
    window.go_to("gecmis")
    sayfa = window.pages["gecmis"]
    sayfa.refresh()
    sayfa.sales_table.setCurrentCell(0, 0)
    sayfa._reverse_sale()
    assert services.sales.last_sale()["is_reversed"] == 0
    pin_cevabi["cevap"] = pd.DOGRULANDI
    sayfa._reverse_sale()
    assert services.sales.last_sale()["is_reversed"] == 1


def test_kasada_ayni_gunun_son_satisi_pinsiz_onceki_gun_pinli(
    duvar_saati, window, qapp, services, bira, pin_kurulu, pin_cevabi, onay
):
    onay.cevap = True
    window.go_to("sepetli_satis")
    sayfa = window.pages["sepetli_satis"]
    duvar_saati.git(2026, 10, 5, 14)
    sayfa.handle_scan(ScanEvent(code=BIRA))
    assert sayfa.complete() is True
    sayfa.undo_last()
    assert services.sales.last_sale()["is_reversed"] == 1
    assert pin_cevabi["cagri"] == 0, "aynı gün: PIN sorulmadı"

    sayfa.handle_scan(ScanEvent(code=BIRA))
    assert sayfa.complete() is True
    duvar_saati.git(2026, 10, 6, 9)                         # ertesi iş günü
    pin_cevabi["cevap"] = pd.VAZGECILDI
    sayfa.undo_last()
    assert services.sales.last_sale()["is_reversed"] == 0
    assert pin_cevabi["cagri"] == 1

    window.go_to("hizli_satis")
    window.pages["hizli_satis"].undo_last()
    assert services.sales.last_sale()["is_reversed"] == 0
    assert pin_cevabi["cagri"] == 2


# ===================== Sıfırlama bildirimi =================================
def test_sifirlama_bildirimi_yonetimde_gorunur_kasada_gorunmez(qapp, services, bira):
    services.security.set_pin(PIN)
    services.security.reset_with_backup(services.backup, "SIFIRLA")
    win = MainWindow(services)
    try:
        win.show()
        win.go_to("ana_ekran")
        assert win.pin_notice.isVisible()
        assert not win.pin_notice.ack_button.isEnabled()
        assert "SIFIRLANDI" in win.pin_notice.text_label.text()
        win.go_to("sepetli_satis")
        assert not win.pin_notice.isVisible(), "Kasa akışı bölünmez"
        win.go_to("urunler")
        assert win.pin_notice.isVisible()

        services.security.set_pin("73915")
        win.refresh_pin_notice()
        assert win.pin_notice.ack_button.isEnabled()
        win.pin_notice.ack_button.click()
        assert not win.pin_notice.isVisible()
        assert not services.security.reset_notice_active()
    finally:
        close_window(win, qapp)


def test_baslangic_sifirlama_akisi(qapp, services, monkeypatch):
    from app import main as ana
    from app.ui.widgets import touch_input

    services.security.set_pin(PIN)
    yazilan = {"metin": "SIFIRLA"}

    def exec_(self):
        self.display.set_value(yazilan["metin"])
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(touch_input.TouchTextDialog, "exec", exec_)
    yazilan["metin"] = "hayir"
    assert ana._pin_sifirla_calistir(services) is False
    assert services.security.has_pin()

    yazilan["metin"] = "SIFIRLA"
    assert ana._pin_sifirla_calistir(services) is True
    assert not services.security.has_pin()
    assert services.security.reset_notice_active()
    assert list(services.backup.manual_dir().glob("pin_sifirlama_oncesi_*.db"))


# ===================== Günlük satış ASLA PIN istemez =======================
def test_pin_kuruluyken_satis_bekletme_ve_ayni_gun_geri_alma_pin_istemez(
    window, qapp, services, bira, pin_kurulu, pin_cevabi, onay
):
    onay.cevap = True
    window.go_to("sepetli_satis")
    sayfa = window.pages["sepetli_satis"]
    sayfa.handle_scan(ScanEvent(code=BIRA))
    sayfa.cash_button.click()
    window.go_to("hizli_satis")
    window.pages["hizli_satis"].handle_scan(ScanEvent(code=BIRA))
    window.pages["hizli_satis"].undo_last()
    assert services.db.scalar("SELECT COUNT(*) FROM sales WHERE entry_type='SALE'") == 2
    assert pin_cevabi["cagri"] == 0


def test_kasa_modulleri_yalnizca_gecmis_gun_geri_almayi_korur():
    """Kasa kodunda korunan eylem olarak YALNIZCA önceki günün satışını geri alma geçer."""
    import ast
    from pathlib import Path

    kok = Path(__file__).resolve().parent.parent
    bulunan = set()
    for dosya in ("app/ui/pages/cart_sale.py", "app/ui/pages/quick_sale.py"):
        agac = ast.parse((kok / dosya).read_text(encoding="utf-8"))
        for dugum in ast.walk(agac):
            if (
                isinstance(dugum, ast.Attribute)
                and isinstance(dugum.value, ast.Name)
                and dugum.value.id == "ProtectedAction"
            ):
                bulunan.add(dugum.attr)
    assert bulunan == {"GECMIS_SATIS_GERI_AL"}
