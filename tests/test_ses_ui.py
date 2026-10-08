"""Ses ayarları ve ekranlardaki ses türleri (V1.2 M9b).

Korunan sözler:
  * Ayarlar › Ses: seviye ve tür başına açık/kapalı kaydedilir ve hemen
    uygulanır; "Dinle" o türü çalar,
  * ses dosyaları veri klasörünün ``sounds`` alt klasörüne üretilir,
  * Kasa'da okutma "okutma", satışın tamamlanması "başarı" sesidir.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import config  # noqa: E402
from app.scanner.scan_event import ScanEvent  # noqa: E402
from app.ui import sound  # noqa: E402

from conftest import BIRA_BARKOD  # noqa: E402
from ui_support import *  # noqa: E402,F401,F403


@pytest.fixture
def calinan(monkeypatch):
    kayit = []
    gercek = sound.cal

    def kaydet(ad):
        kayit.append(ad)
        gercek(ad)

    monkeypatch.setattr(sound, "cal", kaydet)
    return kayit


@pytest.fixture
def ayarlar(window, qapp):
    window.go_to("ayarlar")
    qapp.processEvents()
    return window.pages["ayarlar"]


def test_ses_ayarlari_kaydedilir_ve_uygulanir(ayarlar, services, calinan):
    ayarlar.volume_combo.setCurrentIndex(ayarlar.volume_combo.findData(3))
    assert services.settings.ses_ayarlari()[1] == 3
    assert (config.data_dir() / "sounds" / "scan_3.wav").exists()
    ayarlar.sound_type_checks["scan"].setChecked(False)
    assert services.settings.get_bool("sound_scan") is False
    assert not sound.tur_acik_mi("scan") and sound.tur_acik_mi("success")
    dinle = [d for d in ayarlar.findChildren(type(ayarlar.appearance_button))
             if d.text() == "Dinle"]
    assert len(dinle) == 4
    dinle[1].click()
    assert calinan[-1] == "success"


def test_kasada_okutma_ve_satis_sesleri(window, qapp, sayfa, services, bira, calinan):
    sayfa.handle_scan(ScanEvent(code=BIRA_BARKOD))
    qapp.processEvents()
    assert calinan[-1] == "scan"
    sayfa.cash_button.click()
    qapp.processEvents()
    assert calinan[-1] == "success"
