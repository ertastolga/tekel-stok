"""Gezinme (V1.2 M2d): KASA / STOK / YÖNETİM, Ana Ekran, Ayarlar kapısı.

Korunan sözler:
  * grubu olan HER sayfanın menü düğmesi vardır; anahtarlar V1.1 ile aynıdır,
  * gruplar açılıp kapanır, durum sessizce saklanır ve yeniden açılışta korunur;
    SALES_FIRST'te STOK kapalı başlar; gösterilen sayfanın grubu daima açıktır,
  * Hızlı Satış kapatılınca menüden, Ana Ekran'dan ve Kasa'dan kalkar; F1
    sessizce boşa gitmez,
  * Ayarlar'ın PIN kapısı mevcut sayfa KAPATILMADAN ve okutma ASKIDAYKEN
    denetlenir; ret hâlinde hiçbir şey değişmez (önceki menü düğmesi seçili).
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.models import OperatingMode  # noqa: E402
from app.ui.dialogs import pin_dialog as pd  # noqa: E402
from app.ui.main_window import NAV_GROUPS, MainWindow  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403

BEKLENEN = {
    "kasa": ["sepetli_satis", "hizli_satis"],
    "stok": ["stok_girisi", "stok_sayimi", "stok_durumu"],
    "yonetim": ["panel", "urunler", "tedarikciler", "gecmis", "ayarlar", "barkod_testi"],
}


def _gorunur(win, anahtar) -> bool:
    return win.nav_buttons[anahtar].isVisibleTo(win)


def test_gruplar_ve_sira(window):
    assert [g for g, _ in NAV_GROUPS] == ["kasa", "stok", "yonetim"]
    for grup, anahtarlar in BEKLENEN.items():
        gercek = [k for k, g in window.nav_page_group.items() if g == grup]
        assert gercek == anahtarlar, grup
    assert window.nav_buttons["stok_girisi"].text().endswith("Mal Kabul")
    assert window.nav_buttons["panel"].text().endswith("Analiz")


def test_grubu_olan_her_sayfanin_menu_dugmesi_vardir(window):
    for anahtar, sayfa in window.pages.items():
        if sayfa.nav_group:
            assert anahtar in window.nav_buttons, anahtar
            assert window.nav_page_group[anahtar] == sayfa.nav_group
    assert "ana_ekran" in window.nav_buttons


def test_sales_first_stok_kapali_baslar_ve_gosterilen_grup_acilir(window, qapp, services):
    window.go_to("ana_ekran")
    assert not _gorunur(window, "stok_sayimi")
    assert "▸" in window.nav_headers["stok"].text()
    assert _gorunur(window, "sepetli_satis") and _gorunur(window, "urunler")

    window.go_to("stok_sayimi")
    assert _gorunur(window, "stok_sayimi"), "gösterilen sayfanın grubu açık"
    assert services.settings.get("nav_collapsed_groups") == "VARSAYILAN", "kayıt değişmedi"
    window.go_to("ana_ekran")
    assert not _gorunur(window, "stok_sayimi")


def test_envanter_kipinde_hicbir_grup_kapali_degil(qapp, services, bira):
    services.settings.set("operating_mode", OperatingMode.INVENTORY_TRACKED)
    win = MainWindow(services)
    try:
        assert all(_gorunur(win, k) for k in BEKLENEN["stok"])
    finally:
        close_window(win, qapp)


def test_grup_basligi_acar_kapatir_ve_sessizce_saklanir(window, qapp, services):
    window.go_to("ana_ekran")
    once = services.db.data_version()
    window.nav_headers["kasa"].click()
    assert not _gorunur(window, "sepetli_satis")
    window.nav_headers["stok"].click()
    assert _gorunur(window, "stok_girisi")
    assert services.settings.nav_collapsed_groups() == {"kasa"}
    assert services.db.data_version() == once, "menü durumu veri değişikliği sayılmaz"

    yeni = MainWindow(services)
    try:
        yeni.go_to("ana_ekran")
        assert not _gorunur(yeni, "sepetli_satis")
        assert _gorunur(yeni, "stok_girisi")
    finally:
        close_window(yeni, qapp)


def test_hizli_satis_kapatilinca_her_yerden_kalkar(window, qapp, services):
    services.settings.set("show_quick_sale", 0)
    window.apply_settings()
    window.go_to("ana_ekran")
    assert not _gorunur(window, "hizli_satis")
    assert not window.pages["ana_ekran"].quick_card.isVisibleTo(window)
    assert not window.pages["sepetli_satis"].mode_button.isVisibleTo(window.pages["sepetli_satis"])

    window.go_to("hizli_satis")                            # F1 de buraya gelir
    assert window._current_key == "ana_ekran"
    assert "Hızlı Satış kapalı" in window.status_label.text()
    assert window.nav_buttons["ana_ekran"].isChecked()

    services.settings.set("show_quick_sale", 1)
    window.apply_settings()
    window.pages["ana_ekran"].refresh()
    assert _gorunur(window, "hizli_satis")
    assert window.pages["ana_ekran"].quick_card.isVisibleTo(window)
    window.go_to("hizli_satis")
    assert window._current_key == "hizli_satis"


def test_ayarlar_kapisi_once_ve_askida_denetlenir_ret_hicbir_seyi_degistirmez(
    window, qapp, services, monkeypatch
):
    services.security.set_pin("4826")
    sira: list[str] = []

    def ask(parent, security, action_label=""):
        sira.append(f"pin:{window.router.is_suspended}")
        return cevap["deger"]

    cevap = {"deger": pd.VAZGECILDI}
    monkeypatch.setattr(pd.PinDialog, "ask", staticmethod(ask))
    window.go_to("urunler")
    urunler = window.pages["urunler"]
    eski_kapanis = urunler.on_deactivated
    monkeypatch.setattr(
        urunler, "on_deactivated", lambda: (sira.append("kapandi"), eski_kapanis())
    )

    window.nav_buttons["ayarlar"].click()
    assert sira == ["pin:True"], "PIN okutma askısında, sayfa kapanmadan soruldu"
    assert window._current_key == "urunler"
    assert window.nav_buttons["urunler"].isChecked()
    assert not window.nav_buttons["ayarlar"].isChecked()
    assert not window.router.is_suspended

    cevap["deger"] = pd.DOGRULANDI
    window.nav_buttons["ayarlar"].click()
    assert sira == ["pin:True", "pin:True", "kapandi"]
    assert window._current_key == "ayarlar"


def test_pin_yoksa_ayarlar_dogrudan_acilir(window, monkeypatch):
    def ask(*a, **k):                                      # pragma: no cover
        raise AssertionError("PIN sorulmamalıydı")

    monkeypatch.setattr(pd.PinDialog, "ask", staticmethod(ask))
    window.go_to("ayarlar")
    assert window._current_key == "ayarlar"


def test_ana_ekran_sepetli_satisi_birincil_gosterir(window):
    ana = window.pages["ana_ekran"]
    assert ana.cart_card.objectName() == "actionCardPrimary"
    assert ana.quick_card.objectName() == "actionCard"
    ana.entry_card.click()
    assert window._current_key == "stok_girisi"
