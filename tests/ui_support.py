"""Arayüz testleri için ORTAK düzenek.

V1.1'de ``test_ui.py`` ve ``test_pos_ui.py`` bu düzeneği ayrı ayrı (birebir aynı)
tanımlıyordu. V1.2'de çok sayıda yeni arayüz testi geleceği için tek yere
taşındı. Kullanım (test dosyasının başında)::

    pytest.importorskip("PySide6")
    from ui_support import *  # noqa: F401,F403

``__all__`` içindeki otomatik (autouse) düzenekler içe aktarıldıkları modülde
devreye girer:

* ``kip_pencereler_kapali`` — modal pencereler testte açılmaz; varsayılan
  cevap "Vazgeç" (V1.1 davranışı, birebir korunur),
* ``sesler_kapali`` — winsound çağrıları yapılmaz. ``sound.set_enabled`` DEĞİL,
  çalma ilkelleri yamalanır; ayar kaydı ``apply_settings`` ile sesi yeniden
  açsa bile test sessiz kalır,
* ``ic_ice_olay_dongusu_yasak`` — Python'dan ``QEventLoop.exec`` çağrısı testte
  hata verir. Kasa kaplamaları eşzamansız sinyallerle çalışmalıdır; iç içe olay
  döngüsü testi sonsuza dek kilitlerdi.

``onay`` düzeneği istendiğinde HER sayfadaki ``ask_confirm`` çağrısını (adla
içe aktarılmış ya da işlev içinde içe aktarılmış olsun) aynı yerden cevaplar
ve sorulan metinleri kaydeder.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QEventLoop  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox  # noqa: E402

from app.ui import sound, theme  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

__all__ = [
    "qapp",
    "close_window",
    "kip_pencereler_kapali",
    "sesler_kapali",
    "ic_ice_olay_dongusu_yasak",
    "onay",
    "window",
    "sayfa",
]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    theme.apply_theme(app)
    yield app


def close_window(win, qapp) -> None:
    """Pencereyi GERÇEKTEN yok eder.

    ``deleteLater()`` yalnızca bir DeferredDelete olayı kuyruğa alır ve
    ``processEvents()`` bu türü İŞLEMEZ. Yüzlerce arayüz testi boyunca
    kapatılan her pencere bellekte kalır; süit giderek yavaşlar.
    """
    win.close()
    win.deleteLater()
    qapp.processEvents()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


@pytest.fixture(autouse=True)
def kip_pencereler_kapali(monkeypatch):
    """Modal pencereler testte açılmaz; varsayılan olarak 'Vazgeç' sayılır."""
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Rejected)


@pytest.fixture(autouse=True)
def sesler_kapali(monkeypatch):
    monkeypatch.setattr(sound, "_beep", lambda *args, **kwargs: None)
    monkeypatch.setattr(sound, "_message", lambda *args, **kwargs: None)


@pytest.fixture(autouse=True)
def ic_ice_olay_dongusu_yasak(monkeypatch):
    def yasak(self, *args, **kwargs):
        raise AssertionError(
            "Testte iç içe olay döngüsü (QEventLoop.exec) açıldı; "
            "Kasa kaplamaları sinyallerle çalışmalı."
        )

    monkeypatch.setattr(QEventLoop, "exec", yasak)


@dataclass
class OnayKaydi:
    """``onay`` düzeneğinin durumu: verilecek cevap ve sorulan metinler."""

    cevap: bool = True
    sorular: list[str] = field(default_factory=list)
    #: Her sorunun ayrıntı metni (``informativeText``), aynı sırayla.
    ayrintilar: list[str] = field(default_factory=list)


@pytest.fixture
def onay(monkeypatch) -> OnayKaydi:
    """Bütün onay sorularını tek noktadan cevaplar (varsayılan: Evet).

    Sayfalar ``ask_confirm``'ü adla içe aktardığı için modül başına yama
    yapmak yeni sayfaları kaçırırdı. Bunun yerine ``QMessageBox`` sınıfı
    yamalanır: ``clickedButton`` cevap Evet ise kabul rolündeki düğmeyi döner.
    """
    kayit = OnayKaydi()

    def exec_(self):
        kayit.sorular.append(self.text())
        kayit.ayrintilar.append(self.informativeText())
        return QMessageBox.StandardButton.Ok

    def clicked(self):
        if not kayit.cevap:
            return None
        for dugme in self.buttons():
            if self.buttonRole(dugme) in (
                QMessageBox.ButtonRole.AcceptRole,
                QMessageBox.ButtonRole.YesRole,
            ):
                return dugme
        return None

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    monkeypatch.setattr(QMessageBox, "clickedButton", clicked)
    return kayit


@pytest.fixture
def window(qapp, services, bira):
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)
    win = MainWindow(services)
    win.show()
    qapp.processEvents()
    yield win
    close_window(win, qapp)


@pytest.fixture
def sayfa(window, qapp):
    window.go_to("sepetli_satis")
    qapp.processEvents()
    return window.pages["sepetli_satis"]
