"""Günlük yedek fırsatları (V1.2 M10b, plan §5.11 düzeltme 6).

Korunan sözler:
  * açılışta, boştayken (5 dakikada bir denetim; 60 sn etkinlik yoksa) ve
    temiz kapanışta günlük yedek fırsatı vardır; aynı güne ikinci kuşak yok,
  * yoğun bir gün hiç boşta kalınmasa da günlük yedek KAPANIŞTA alınır,
  * boşta yedek; etkinlik varken, açık işlemde, ödeme/katman açıkken ya da
    yeniden başlatılırken ALINMAZ — satış asla beklemez,
  * yedek hatası uygulamayı durdurmaz; kaydedilir ve durum çubuğunda kalıcı
    uyarı görünür, sonraki başarılı yedekte kalkar.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest  # noqa: E402

from app.core import clock  # noqa: E402
from app.main import yedek_firsati  # noqa: E402
from app.services import backup_service as bs  # noqa: E402
from app.ui import main_window as mw  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403


def _gunluk_sayisi(services) -> int:
    return [b.kind for b in services.backup.list_backups()].count(bs.GUNLUK)


@pytest.fixture
def pencere(duvar_saati, services, bira, qapp):
    duvar_saati.git(2026, 10, 5, 10)
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)
    win = mw.MainWindow(services)
    win.show()
    qapp.processEvents()
    yield win
    close_window(win, qapp)


def _bosta_yap(win, saat):
    saat.ilerle(mw.BOSTA_SANIYE + 5)
    assert clock.monotonic() - win._son_etkinlik >= mw.BOSTA_SANIYE


def test_acilis_firsati_ve_ayni_gun_tekrar_yok(duvar_saati, services, bira):
    duvar_saati.git(2026, 10, 5, 9)
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)
    alinan = yedek_firsati(services, "açılış")
    assert any(y.name.startswith("gunluk_") for y in alinan)
    assert not any(y.name.startswith("gunluk_") for y in yedek_firsati(services, "açılış"))
    assert _gunluk_sayisi(services) == 1


def test_bosta_yedek_alinir(pencere, duvar_saati, services):
    assert pencere._yedek_zamanlayici.interval() == 5 * 60 * 1000
    _bosta_yap(pencere, duvar_saati)
    assert pencere.bosta_yedek_dene() == "GUNLUK"
    assert pencere.bosta_yedek_dene() is None, "aynı güne ikinci kuşak yok"


def test_etkinlik_varken_bosta_yedek_yok(pencere, duvar_saati, services, qapp):
    _bosta_yap(pencere, duvar_saati)
    QTest.keyClick(pencere, "a")                      # kullanıcı az önce dokundu
    assert pencere.bosta_yedek_dene() is None
    assert _gunluk_sayisi(services) == 0


def test_odeme_katman_islem_ve_yeniden_baslatma_engeller(pencere, duvar_saati, services,
                                                        qapp):
    pencere.go_to("sepetli_satis")
    qapp.processEvents()
    kasa = pencere.pages["sepetli_satis"]
    _bosta_yap(pencere, duvar_saati)
    kasa._checkout_busy = True
    assert pencere.bosta_yedek_dene() is None, "ödeme sürüyor"
    kasa._checkout_busy = False
    kasa._overlay_state = "ARA"
    assert pencere.bosta_yedek_dene() is None, "katman açık"
    kasa._overlay_state = None
    with services.db.transaction():
        assert pencere.bosta_yedek_dene() is None, "açık işlem"
    pencere.restarting = True
    assert pencere.bosta_yedek_dene() is None
    pencere.restarting = False
    assert pencere.bosta_yedek_dene() == "GUNLUK"


def test_yogun_gun_gunluk_yedegi_kapanista_alinir(pencere, duvar_saati, services, bira,
                                                 qapp):
    for _ in range(6):                                  # gün boyu hiç boşta kalınmadı
        duvar_saati.ilerle(30)
        services.sales.quick_sale(bira)
        QTest.keyClick(pencere, "a")
        assert pencere.bosta_yedek_dene() is None
    assert _gunluk_sayisi(services) == 0
    assert any(y.name.startswith("gunluk_") for y in yedek_firsati(services, "kapanış"))


def test_hata_uyarisi_ve_basarida_kalkmasi(pencere, duvar_saati, services, monkeypatch):
    gercek = bs.shutil.disk_usage
    monkeypatch.setattr(bs.shutil, "disk_usage",
                        lambda yol: type("D", (), {"free": 1})())
    _bosta_yap(pencere, duvar_saati)
    assert pencere.bosta_yedek_dene() is None, "hata uygulamayı durdurmaz"
    assert not pencere.backup_warning.isHidden()
    monkeypatch.setattr(bs.shutil, "disk_usage", gercek)
    duvar_saati.ilerle(1)
    assert pencere.bosta_yedek_dene() == "GUNLUK"
    assert pencere.backup_warning.isHidden()
