"""H1 Kasa ayarları (V1.2 M3f).

Korunan sözler:
  * açılış ekranı seçilebilir (Otomatik / Sepetli / Hızlı / Ana Ekran); gizli
    Hızlı Satış açılış ekranı olamaz; tanınmayan değer Otomatik sayılır,
  * NAKİT daima görünür; KART gizlenebilir; VERESİYE / DİĞER sunulmaz,
  * Ayarlar ekranındaki denetimler anında uygulanır.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QPushButton  # noqa: E402

from app.core.models import OperatingMode  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403


def _acilis(qapp, services) -> str:
    win = MainWindow(services)
    try:
        return win._current_key
    finally:
        close_window(win, qapp)


@pytest.mark.parametrize(
    "secim,kip,beklenen",
    [
        ("AUTO", OperatingMode.SALES_FIRST, "sepetli_satis"),
        ("AUTO", OperatingMode.INVENTORY_TRACKED, "ana_ekran"),
        ("hizli_satis", OperatingMode.SALES_FIRST, "hizli_satis"),
        ("ana_ekran", OperatingMode.SALES_FIRST, "ana_ekran"),
        ("sepetli_satis", OperatingMode.INVENTORY_TRACKED, "sepetli_satis"),
        ("bilinmeyen", OperatingMode.SALES_FIRST, "sepetli_satis"),
    ],
)
def test_acilis_ekrani(qapp, services, secim, kip, beklenen):
    services.settings.set_many({"startup_page": secim, "operating_mode": kip})
    assert _acilis(qapp, services) == beklenen


def test_gizli_hizli_satis_acilis_ekrani_olamaz(qapp, services):
    services.settings.set_many({"startup_page": "hizli_satis", "show_quick_sale": 0})
    assert _acilis(qapp, services) == "sepetli_satis"


def test_kart_gizlenebilir_nakit_daima_gorunur(window, qapp, services):
    window.go_to("sepetli_satis")
    kasa = window.pages["sepetli_satis"]
    assert kasa.card_button.isVisibleTo(kasa) and kasa.cash_button.isVisibleTo(kasa)
    services.settings.set("show_card_button", 0)
    window.apply_settings()
    assert not kasa.card_button.isVisibleTo(kasa)
    assert kasa.cash_button.isVisibleTo(kasa)
    metinler = " ".join(d.text() for d in kasa.findChildren(QPushButton))
    assert "VERESİYE" not in metinler and "DİĞER" not in metinler


def test_ayarlar_denetimleri_aninda_uygulanir(window, qapp, services):
    window.go_to("ayarlar")
    ayarlar = window.pages["ayarlar"]
    ayarlar.card_check.setChecked(False)
    window.go_to("sepetli_satis")
    kasa = window.pages["sepetli_satis"]
    assert not kasa.card_button.isVisibleTo(kasa)

    window.go_to("ayarlar")
    ayarlar.startup_combo.setCurrentIndex(ayarlar.startup_combo.findData("hizli_satis"))
    assert services.settings.startup_page() == "hizli_satis"
