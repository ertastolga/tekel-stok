"""Dokunmatik giriş takımı (V1.2 M2b).

Korunan sözler:
  * klavyesiz kasada ad, fiyat, tutar ve arama metni YALNIZCA ekran tuşlarıyla
    eksiksiz girilebilir (Türkçe harfler, büyük İ/I, sembol katmanı),
  * tuşlar en az 56 px'tir ve odak ALMAZ; klavye 736 px'e sığar,
  * dokunmatik pencerede varsayılan düğme yoktur; Enter hiçbir şeyi onaylamaz,
  * makine hızında (okuyucu) gelen fiziksel tuşlar değere yazılmaz,
  * fiziksel klavye alanına (ScanSafeLineEdit) düşen okutma geri alınır; insan
    yazımı bozulmaz.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget  # noqa: E402

from app.core import clock  # noqa: E402
from app.scanner.scanner_service import ScannerService  # noqa: E402
from app.ui import metrics  # noqa: E402
from app.ui.widgets.touch_input import (  # noqa: E402
    KLAVYE_AZAMI_GENISLIK,
    ScanSafeLineEdit,
    TouchAmountDialog,
    TouchDisplay,
    TouchKeyboard,
    TouchNumpad,
    TouchTextDialog,
)
from fakes import SahteSaat  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403


@pytest.fixture
def saat():
    """Tek sahte saat: hem okuyucu servisi hem saat dikişi aynı zamanı görür."""
    s = SahteSaat()
    with clock.use_clock(tekduze=s):
        yield s


def _yaz(klavye: TouchKeyboard, metin: str) -> None:
    """Metni YALNIZCA dokunuşla yazar (büyük harf ve sembol katmanı dahil)."""
    from app.core.tr import tr_lower

    for karakter in metin:
        if karakter == " ":
            klavye.space_key.click()
            continue
        try:
            klavye.key(karakter)
            buyuk = False
        except KeyError:
            buyuk = True
        if buyuk:
            kucuk = tr_lower(karakter)
            try:
                klavye.key(kucuk)
            except KeyError:
                kucuk = None
        if buyuk and kucuk is not None:
            klavye.shift_key.setChecked(True)
            klavye.key(kucuk).click()
            klavye.shift_key.setChecked(False)
        elif buyuk:                                     # sembol
            klavye.symbol_key.setChecked(True)
            klavye.key(karakter).click()
            klavye.symbol_key.setChecked(False)
        else:
            klavye.key(karakter).click()


# ===================== Klavye ve tuş takımı =================================
@pytest.mark.parametrize(
    "metin", ["Puro/Sigarillo", "Coca-Cola", "Jack Daniel's", "İÇİ", "ışık Iğdır iİıI"]
)
def test_turkce_klavye_metni_birebir_yazar(qapp, metin):
    klavye = TouchKeyboard()
    gosterim = TouchDisplay()
    klavye.bind(gosterim)
    _yaz(klavye, metin)
    assert gosterim.value() == metin


def test_buyuk_harf_turkce_kurala_uyar(qapp):
    klavye = TouchKeyboard()
    klavye.shift_key.setChecked(True)
    assert klavye.key("i").text() == "İ"
    assert klavye.key("ı").text() == "I"
    assert klavye.key("ş").text() == "Ş"
    klavye.shift_key.setChecked(False)
    assert klavye.key("i").text() == "i"


def test_tuslar_dokunma_boyutunda_ve_odak_almaz(qapp):
    for gerec in (TouchKeyboard(), TouchNumpad()):
        # Gösterilip stil sayfasıyla CİLALANDIKTAN sonra ölçülür (V1.2 M3c:
        # cilalanmamış ölçüm, stil sayfasının 28 px'e indirdiği tuşları kaçırdı).
        gerec.resize(gerec.minimumSizeHint())
        gerec.show()
        qapp.processEvents()
        dugmeler = gerec.findChildren(QPushButton)
        assert dugmeler
        for dugme in dugmeler:
            assert dugme.width() >= metrics.TOUCH_TARGET_MIN, dugme.text()
            assert dugme.height() >= metrics.TOUCH_TARGET_MIN, dugme.text()
            assert dugme.focusPolicy() == Qt.FocusPolicy.NoFocus
            assert not dugme.autoDefault() and not dugme.isDefault()
    assert TouchKeyboard().minimumSizeHint().width() <= KLAVYE_AZAMI_GENISLIK
    assert TouchDisplay().focusPolicy() == Qt.FocusPolicy.NoFocus


def test_sayi_tus_takimi(qapp):
    tuslar = TouchNumpad()
    gosterim = TouchDisplay()
    tuslar.bind(gosterim)
    for metin in ("1", "2", "00", ",", "5"):
        tuslar.keys[metin].click()
    assert gosterim.value() == "1200,5"
    tuslar.backspace_key.click()
    assert gosterim.value() == "1200,"
    tuslar.clear_key.click()
    assert gosterim.value() == ""
    tamsayi = TouchNumpad(allow_decimal=False)
    assert tamsayi.keys[","].isHidden()


def test_gosterim_azami_uzunluk_ve_maske(qapp):
    gosterim = TouchDisplay(max_length=4, masked=True)
    for _ in range(6):
        gosterim.insert("7")
    assert gosterim.value() == "7777"
    assert gosterim.text() == "●●●●"


# ===================== Dokunmatik pencere ==================================
def test_enter_dokunmatik_pencereyi_ONAYLAMAZ(qapp, saat):
    pencere = TouchAmountDialog("Tutar")
    pencere.show()
    for dugme in pencere.findChildren(QPushButton):
        assert not dugme.isDefault() and not dugme.autoDefault()
    saat.advance(1000)
    QTest.keyClick(pencere, Qt.Key.Key_5)
    QTest.keyClick(pencere, Qt.Key.Key_Return)
    QTest.keyClick(pencere, Qt.Key.Key_Enter)
    assert pencere.isVisible() and pencere.result() == 0, "onaylanmadı"
    assert pencere.value() == "5"
    pencere.accept_button.click()
    assert pencere.result() == 1
    pencere.deleteLater()


def test_okuyucu_hizindaki_fiziksel_tuslar_degere_yazilmaz(qapp, saat):
    pencere = TouchAmountDialog("Tutar")
    pencere.show()
    saat.advance(1000)
    QTest.keyClick(pencere, Qt.Key.Key_4)                # insan: kabul
    saat.advance(800)
    for karakter in "8690504001492":                     # okuyucu dizisi
        QTest.keyClicks(pencere, karakter)
        saat.advance(5)
    QTest.keyClick(pencere, Qt.Key.Key_Return)
    assert pencere.value() == "4", "dizinin İLK karakteri dahil geri alındı"
    assert pencere.result() == 0
    saat.advance(900)
    QTest.keyClick(pencere, Qt.Key.Key_2)
    assert pencere.value() == "42", "sonraki insan yazımı yine kabul"
    pencere.deleteLater()


def test_tutar_penceresi_yalnizca_rakam_kabul_eder(qapp, saat):
    pencere = TouchAmountDialog("Adet", allow_decimal=False)
    pencere.show()
    for karakter in "1a,2":
        saat.advance(500)
        QTest.keyClicks(pencere, karakter)
    assert pencere.value() == "12"
    pencere.deleteLater()


def test_metin_penceresi_dokunusla_doldurulur(qapp):
    pencere = TouchTextDialog("Ürün adı", initial="Efes")
    _yaz(pencere.keyboard, " Pilsen")
    assert pencere.value() == "Efes Pilsen"
    pencere.deleteLater()


# ===================== ScanSafeLineEdit ====================================
@pytest.fixture
def alan_ve_okuyucu(qapp, saat):
    okuyucu = ScannerService(clock=saat)
    okuyucu.start()
    kap = QWidget()
    duzen = QVBoxLayout(kap)
    alan = ScanSafeLineEdit(scanner=okuyucu)
    duzen.addWidget(alan)
    kap.show()
    kap.activateWindow()
    qapp.processEvents()
    alan.setFocus()
    qapp.processEvents()
    okutmalar = []
    okuyucu.scanned.connect(okutmalar.append)
    yield alan, okutmalar
    okuyucu.stop()
    close_window(kap, qapp)


def _insan(alan, saat, metin):
    for karakter in metin:
        saat.advance(250)
        QTest.keyClicks(alan, karakter)


def _okut(alan, saat, kod):
    saat.advance(900)
    for karakter in kod:
        QTest.keyClicks(alan, karakter)
        saat.advance(6)
    QTest.keyClick(alan, Qt.Key.Key_Return)


def test_odaktaki_alana_dusen_okutma_geri_alinir(alan_ve_okuyucu, saat):
    alan, okutmalar = alan_ve_okuyucu
    assert alan.hasFocus()
    _insan(alan, saat, "Bira")
    alan.setCursorPosition(2)
    _okut(alan, saat, "8690504001492")
    assert len(okutmalar) == 1 and okutmalar[0].code == "8690504001492"
    assert alan.text() == "Bira", "okutmanın karakterleri geri alındı"
    assert alan.cursorPosition() == 2
    _insan(alan, saat, "!")
    assert alan.text() == "Bi!ra"


def test_insan_yazimi_okutma_olmadan_bozulmaz(alan_ve_okuyucu, saat):
    alan, okutmalar = alan_ve_okuyucu
    _insan(alan, saat, "Coca-Cola 1 lt")
    assert alan.text() == "Coca-Cola 1 lt"
    assert okutmalar == []


def test_odakta_degilken_okutma_alani_degistirmez(qapp, saat):
    okuyucu = ScannerService(clock=saat)
    alan = ScanSafeLineEdit(scanner=okuyucu)
    alan.setText("Ruffles")
    okuyucu.feed("8690504001492")
    assert alan.text() == "Ruffles"
