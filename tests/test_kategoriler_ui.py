"""Kategoriler sayfası (V1.2 M4a).

Korunan sözler:
  * ağaç ürün sayılarını ve kategorisiz ürün sayısını gösterir; arama süzer,
  * benzer ad eklemeden önce SORULUR, aynı yerde aynı ad hatayla reddedilir,
  * kaldırma ve birleştirme yönetici PIN'i ister (PIN kuruluysa),
  * şablon önizlemesinde isteğe bağlı adımlar kendiliğinden seçili değildir.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.services.category_service import ADIM_YENIDEN_ADLANDIR  # noqa: E402
from app.ui.dialogs import pin_dialog as pd  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403


@pytest.fixture
def sayfa(window, qapp):
    window.go_to("kategoriler")
    qapp.processEvents()
    return window.pages["kategoriler"]


def _kimlik(services, ad):
    return services.db.scalar("SELECT id FROM categories WHERE name = ?", (ad,))


def test_agac_sayilar_ve_kategorisiz(sayfa, services):
    bira = _kimlik(services, "Bira")
    services.products.quick_create("Efes", 7000, category_id=bira)
    sayfa.refresh()
    ust = next(sayfa.tree.topLevelItem(i) for i in range(sayfa.tree.topLevelItemCount())
               if sayfa.tree.topLevelItem(i).text(0) == "Alkollü İçecekler")
    assert ust.text(1) == "1"
    assert "Kategorisiz ürün: 1" in sayfa.uncategorized_label.text()   # "bira" fikstürü
    sayfa.search_edit.setText("sigar")
    gorunen = [o.text(0) for o in sayfa._tum_ogeler() if not o.isHidden()]
    assert set(gorunen) == {"Tütün", "Sigara", "Puro / Sigarillo"}


def test_benzer_ad_sorulur_ayni_ad_reddedilir(sayfa, services, monkeypatch, onay):
    sayfa.select_id(_kimlik(services, "Alkollü İçecekler"))
    monkeypatch.setattr(sayfa, "_ad_iste", lambda *a, **k: "Biralar")
    onay.cevap = False
    assert sayfa.add_category(alt=True) is None
    assert any("Benzer bir kategori" in s for s in onay.sorular)
    assert _kimlik(services, "Biralar") is None
    onay.cevap = True
    kimlik = sayfa.add_category(alt=True)
    assert services.categories.path(kimlik) == "Alkollü İçecekler > Biralar"

    hatalar = []
    monkeypatch.setattr(sayfa, "_hata", lambda h: hatalar.append(h.message))
    monkeypatch.setattr(sayfa, "_ad_iste", lambda *a, **k: "BİRA")
    sayfa.select_id(_kimlik(services, "Alkollü İçecekler"))
    sayfa.add_category(alt=True)
    assert hatalar and "zaten var" in hatalar[0]


def test_alt_secili_iken_alt_ekleme_kardes_ekler(sayfa, services, monkeypatch):
    sayfa.select_id(_kimlik(services, "Bira"))
    monkeypatch.setattr(sayfa, "_ad_iste", lambda *a, **k: "Fıçı Bira")
    kimlik = sayfa.add_category(alt=True)
    assert services.categories.path(kimlik) == "Alkollü İçecekler > Fıçı Bira"


def test_kaldirma_ve_birlestirme_pin_ister(window, sayfa, services, monkeypatch, onay):
    services.security.set_pin("4826")
    window.guard.lock()
    cevap = {"deger": pd.VAZGECILDI}
    monkeypatch.setattr(pd.PinDialog, "ask", staticmethod(lambda *a, **k: cevap["deger"]))
    onay.cevap = True
    sakiz = _kimlik(services, "Sakız")
    sayfa.refresh()
    sayfa.select_id(sakiz)
    sayfa.deactivate_selected()
    assert services.categories.get(sakiz)["active"] == 1
    assert onay.sorular == [], "PIN'siz onay sorusuna bile gelinmedi"

    cevap["deger"] = pd.DOGRULANDI
    sayfa.deactivate_selected()
    assert services.categories.get(sakiz)["active"] == 0

    kola, gazoz = _kimlik(services, "Kola"), _kimlik(services, "Gazoz")
    urun = services.products.quick_create("Kola 1 L", 4000, category_id=kola)
    sayfa.select_id(kola)
    monkeypatch.setattr(sayfa, "_hedef_sec", lambda *a, **k: gazoz)
    sayfa.merge_selected()
    assert services.products.get(urun)["category_id"] == gazoz


def test_tasi_ve_yeniden_adlandir(sayfa, services, monkeypatch):
    buz = _kimlik(services, "Buz")
    sayfa.select_id(buz)
    monkeypatch.setattr(sayfa, "_hedef_sec", lambda *a, **k: _kimlik(services, "Soğuk İçecek"))
    sayfa.move_selected()
    assert services.categories.path(buz) == "Soğuk İçecek > Buz"
    monkeypatch.setattr(sayfa, "_ad_iste", lambda *a, **k: "Buz Torbası")
    sayfa.select_id(buz)
    sayfa.rename_selected()
    assert services.categories.get(buz)["name"] == "Buz Torbası"


def test_sablon_onizlemesi_istege_bagliyi_secmez(sayfa, services, monkeypatch):
    services.categories.rename(_kimlik(services, "Soğuk İçecek"), "İçecekler")
    services.db.execute("DELETE FROM categories WHERE name = 'Soda'")
    gorulen = []

    def sec(adimlar):
        gorulen.extend((a.tur, a.secili) for a in adimlar)
        return adimlar

    monkeypatch.setattr(sayfa, "_adimlari_sec", sec)
    assert sayfa.apply_template() == 1, "yalnızca Soda eklendi"
    assert (ADIM_YENIDEN_ADLANDIR, False) in gorulen
    assert _kimlik(services, "Soğuk İçecek") is None, "yeniden adlandırma seçilmedi"
    assert _kimlik(services, "Soda") is not None
