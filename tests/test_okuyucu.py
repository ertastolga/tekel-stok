"""ScannerService: gerçek tuş olaylarıyla okuyucu davranışı (V1.2 M9c, D-22).

Korunan sözler:
  * saat ``time.perf_counter``'dır (D-22),
  * Enter ya da Tab ile biten makine hızındaki dizi TEK okutmadır; sonlandırıcı
    yutulur (Tab ile gönderen barkod alanı ikinci kez işlemez),
  * okuyucunun odaktaki alana yazdığı karakterler okutmadan sonra silinir
    (arka arkaya okutmalar alanda birleşmez),
  * insan yazımı (yavaş) okutma sayılmaz; Enter/Tab normal çalışır,
  * sonlandırıcısız okuyucu bekleme ile yakalanır (en kısa uzunluk ayarlı),
  * eşikler ayarlanabilir ama güvenli sınırlar dışına çıkamaz,
  * muaf alanlar ve Ctrl kısayolları okutma sayılmaz,
  * Barkod Testi sonlandırıcıyı, tuş aralarını ve başka ekranda engellenen
    okutmaları gösterir.
"""
from __future__ import annotations

import os
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget  # noqa: E402

from app.scanner import scanner_service as ss  # noqa: E402
from app.scanner.scanner_service import ScannerService  # noqa: E402
from app.ui.widgets.barcode_input import BarcodeInput  # noqa: E402

from conftest import BIRA_BARKOD  # noqa: E402
from ui_support import *  # noqa: E402,F401,F403


class Saat:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, ms: float) -> None:
        self.t += ms / 1000


@pytest.fixture
def duzenek(qapp):
    saat = Saat()
    okuyucu = ScannerService(clock=saat)
    okuyucu.start()
    kap = QWidget()
    duzen = QVBoxLayout(kap)
    alan = BarcodeInput("sale")
    diger = QLineEdit()
    duzen.addWidget(alan)
    duzen.addWidget(diger)
    kap.show()
    alan.setFocus()
    qapp.processEvents()
    okunan, gonderilen = [], []
    okuyucu.scanned.connect(okunan.append)
    alan.submitted.connect(gonderilen.append)
    yield okuyucu, saat, alan, diger, okunan, gonderilen
    okuyucu.stop()
    close_window(kap, qapp)


def _yaz(alan, saat, metin, ara_ms):
    for ch in metin:
        QTest.keyClick(alan, ch)
        saat.advance(ara_ms)


def test_varsayilan_saat_perf_counter():
    """D-22: Windows'ta monotonic ~15,6 ms adımlıdır; 30 ms eşik güvenilmez ölçülür."""
    assert ScannerService().__dict__["_clock"] is time.perf_counter


def test_enter_ile_tek_okutma_ve_alan_temizlenir(duzenek):
    okuyucu, saat, alan, _d, okunan, gonderilen = duzenek
    for _ in range(2):
        _yaz(alan, saat, BIRA_BARKOD, 8)
        QTest.keyClick(alan, Qt.Key.Key_Return)
        saat.advance(400)
    assert [o.code for o in okunan] == [BIRA_BARKOD, BIRA_BARKOD]
    assert gonderilen == [], "Enter yutuldu: alan ayrıca göndermedi"
    assert alan.text() == "", "V1.1: alanda kalıyor, okutmalar birleşiyordu"
    assert (okunan[0].terminator, okunan[0].key_count) == ("ENTER", 13)
    assert okunan[0].avg_gap_ms == pytest.approx(8.0)
    assert okunan[0].max_gap_ms == pytest.approx(8.0)


def test_tab_ile_biten_okutma_bir_kez_islenir(duzenek, qapp):
    okuyucu, saat, alan, _d, okunan, gonderilen = duzenek
    _yaz(alan, saat, BIRA_BARKOD, 8)
    QTest.keyClick(alan, Qt.Key.Key_Tab)
    QTest.qWait(ss.IDLE_FLUSH_MS + 100)
    assert [o.code for o in okunan] == [BIRA_BARKOD]
    assert gonderilen == [], "V1.1: alan Tab ile ayrıca gönderiyordu (çift işleme)"
    assert okunan[0].terminator == "TAB" and alan.hasFocus()


def test_insan_yazimi_okutma_sayilmaz(duzenek, qapp):
    okuyucu, saat, alan, diger, okunan, gonderilen = duzenek
    _yaz(alan, saat, "1234", 250)
    QTest.keyClick(alan, Qt.Key.Key_Return)
    assert okunan == [] and gonderilen == ["1234"], "elle yazılan normal gönderilir"
    _yaz(alan, saat, "12", 250)
    QTest.keyClick(alan, Qt.Key.Key_Tab)
    qapp.processEvents()
    assert okunan == [], "insanın Tab'ı okutma değil"


def test_sonlandiricisiz_okuyucu_ve_en_kisa_uzunluk(duzenek):
    okuyucu, saat, alan, _d, okunan, _g = duzenek
    _yaz(alan, saat, "12345", 8)
    QTest.qWait(ss.IDLE_FLUSH_MS + 100)
    assert okunan == [], "6'dan kısa sonlandırıcısız dizi kabul edilmez"
    okuyucu.set_min_length(4)
    saat.advance(1000)
    _yaz(alan, saat, "12345", 8)
    QTest.qWait(ss.IDLE_FLUSH_MS + 100)
    assert [(o.code, o.terminator) for o in okunan] == [("12345", "YOK")]


def test_esik_ayarlanir_ve_sinirlanir(duzenek):
    okuyucu, saat, alan, _d, okunan, _g = duzenek
    _yaz(alan, saat, BIRA_BARKOD, 40)
    QTest.keyClick(alan, Qt.Key.Key_Return)
    assert okunan == [], "40 ms/tuş varsayılan eşikte insan sayılır"
    okuyucu.set_burst_key_ms(45)
    saat.advance(1000)
    alan.clear()
    _yaz(alan, saat, BIRA_BARKOD, 40)
    QTest.keyClick(alan, Qt.Key.Key_Return)
    assert [o.code for o in okunan] == [BIRA_BARKOD]
    okuyucu.set_burst_key_ms(5)
    okuyucu.set_min_length(99)
    assert (okuyucu.burst_key_ms, okuyucu.min_length) == (15.0, 14)


def test_muaf_alan_ve_ctrl_kisayolu(duzenek, qapp):
    okuyucu, saat, alan, diger, okunan, _g = duzenek
    diger.setProperty(ss.EXEMPT_PROPERTY, True)
    diger.setFocus()
    qapp.processEvents()
    _yaz(diger, saat, BIRA_BARKOD, 8)
    QTest.keyClick(diger, Qt.Key.Key_Return)
    assert okunan == [] and diger.text() == BIRA_BARKOD, "muaf alana yazılan kalır"
    alan.setFocus()
    qapp.processEvents()
    _yaz(alan, saat, "869050", 8)
    QTest.keyClick(alan, "c", Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(alan, Qt.Key.Key_Return)
    assert okunan == []


# ===================== Uygulamada =========================================
def test_ayarlar_okuyucuya_uygulanir(window, qapp, services):
    window.go_to("ayarlar")
    qapp.processEvents()
    ayarlar = window.pages["ayarlar"]
    ayarlar.burst_spin.setValue(42)
    ayarlar.min_length_spin.setValue(8)
    assert (window.scanner.burst_key_ms, window.scanner.min_length) == (42.0, 8)


def test_barkod_testi_ayrintilari(window, qapp, services, bira):
    window.go_to("barkod_testi")
    qapp.processEvents()
    sayfa = window.pages["barkod_testi"]
    from app.scanner.scan_event import ScanEvent

    window.router.dispatch(ScanEvent(code=BIRA_BARKOD, key_count=13, avg_gap_ms=7.6,
                                     max_gap_ms=12.0, terminator="TAB"))
    tok = window.router.suspend("deneme")
    window.router.dispatch(ScanEvent(code="8690000000012", key_count=13, avg_gap_ms=8,
                                     terminator="ENTER"))
    window.router.resume(tok)
    sayfa.refresh()
    satirlar = sayfa.rows()
    assert [y for _o, y in satirlar] == ["Engellendi (pencere açıktı)", "Bu ekranda işlendi"]
    from app.ui.pages.barcode_test import SUTUNLAR

    def hucre(satir, baslik):
        return sayfa.table.item(satir, SUTUNLAR.index(baslik)).text()

    assert hucre(1, "Sonlandırıcı") == "Tab"
    assert hucre(1, "Tuş arası (ort. / en uzun)") == "8 / 12 ms"
    assert "geçerli GTIN" in hucre(1, "Değerlendirme")
    services.settings.set("barcode_trim_prefix", "]C1")
    window.apply_settings()
    assert "kırpıldı" in sayfa._degerlendirme("]C1" + BIRA_BARKOD)
