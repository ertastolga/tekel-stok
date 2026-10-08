"""Görünüm: koyu tema, yazı ölçeği, yoğunluk (V1.2 M9a).

Korunan sözler:
  * görünüm ayarları açılışta veritabanına SALT OKUNUR bakışla okunur (dosya
    değişmez, göç yapılmaz); okunamazsa Açık / %100 / Normal,
  * koyu temada yazı/zemin ve vurgu renkleri yeterli kontrastta; stil
    sayfasındaki her renk koyu temanın jetonudur,
  * yazı ölçeği bütün yazı boyutlarını ölçekler; "Rahat" yalnızca aralıkları
    BÜYÜTÜR, dokunma hedefleri asla küçülmez,
  * Ayarlar › Görünüm seçimi "Kaydet ve yeniden başlat" ile kaydedilir;
    %100'ün üstünde 1000×600 uyarısı gösterilir,
  * %130 + Rahat'ta Kasa sayfaları 1366×768'e sığar.
"""
from __future__ import annotations

import dataclasses
import hashlib
import os
import re

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core import gorunum  # noqa: E402
from app.core.db import open_database  # noqa: E402
from app.services.container import build_services  # noqa: E402
from app.ui import metrics, theme  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403


def _parlaklik(renk: str) -> float:
    r, g, b = (int(renk.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def kontrast(a: str, b: str) -> float:
    ust, alt = sorted((_parlaklik(a), _parlaklik(b)), reverse=True)
    return (ust + 0.05) / (alt + 0.05)


@pytest.fixture
def varsayilana_don():
    yield
    metrics.sifirla()
    theme.set_tokens(theme.LIGHT)


# ===================== Salt okunur bakış ===================================
def test_gorunum_salt_okunur_okunur(tmp_path):
    yol = tmp_path / "veri.db"
    assert gorunum.oku(yol) == gorunum.Gorunum(), "dosya yok: varsayılan"
    hizmet = build_services(open_database(yol))
    hizmet.settings.set("theme", "DARK")
    hizmet.settings.set("font_scale", 120)
    hizmet.settings.set("density", "RAHAT")
    hizmet.close()
    once = hashlib.sha256(yol.read_bytes()).hexdigest()
    assert gorunum.oku(yol) == gorunum.Gorunum("DARK", 120, "RAHAT")
    assert hashlib.sha256(yol.read_bytes()).hexdigest() == once, "dosya değişmedi"


def test_bozuk_deger_ve_dosya_varsayilana_doner(tmp_path):
    assert gorunum.dogrula("MOR", "abc", "SIKISIK") == gorunum.Gorunum()
    assert gorunum.dogrula("DARK", "115", "RAHAT") == gorunum.Gorunum("DARK", 100, "RAHAT")
    bozuk = tmp_path / "bozuk.db"
    bozuk.write_bytes(b"bu bir veritabani degil" * 100)
    assert gorunum.oku(bozuk) == gorunum.Gorunum()


def test_eski_surum_veritabani_varsayilan(v1_1_kopya):
    """V1.1 verisinde bu ayarlar yok: göç yapılmadan varsayılan okunur."""
    once = hashlib.sha256(v1_1_kopya.read_bytes()).hexdigest()
    assert gorunum.oku(v1_1_kopya) == gorunum.Gorunum()
    assert hashlib.sha256(v1_1_kopya.read_bytes()).hexdigest() == once


# ===================== Koyu tema ===========================================
def test_koyu_tema_kontrasti():
    t = theme.DARK
    assert kontrast(t.text, t.bg) >= 7 and kontrast(t.text, t.surface) >= 7
    assert kontrast(t.text_muted, t.surface) >= 4.5
    assert kontrast(t.nav_text, t.nav_bg) >= 7
    for ad in ("primary", "cart", "stock", "count", "danger", "warning", "critical",
               "info"):
        vurgu = getattr(t, ad)
        assert kontrast(t.on_accent, vurgu) >= 4.5, f"{ad} zemininde yazı"
        assert kontrast(vurgu, t.surface) >= 4.5, f"{ad} yüzeyde yazı"
        assert kontrast(vurgu, getattr(t, f"{ad}_light")) >= 3, f"{ad} rozet"


def test_koyu_tema_stil_sayfasi_yalnizca_jetonlarini_kullanir():
    jetonlar = {d for a, d in dataclasses.asdict(theme.DARK).items()
                if isinstance(d, str) and a != "ad"}
    stil = theme.build_stylesheet(theme.DARK)
    bulunan = set(re.findall(r"#[0-9A-Fa-f]{6}\b|rgba?\([^)]*\)", stil))
    assert bulunan and bulunan <= jetonlar
    assert theme.LIGHT.bg not in stil
    assert {f.name for f in dataclasses.fields(theme.ThemeTokens)} == set(
        dataclasses.asdict(theme.DARK))


# ===================== Ölçek ve yoğunluk ===================================
def test_yazi_olcegi_ve_yogunluk(varsayilana_don):
    taban = (metrics.FONT_BASE_PT, metrics.FONT_TOTAL_PT, metrics.TABLE_ROW_HEIGHT,
             metrics.CARD_PADDING)
    theme.gorunumu_uygula("DARK", 130, "RAHAT")
    assert theme.tokens() is theme.DARK
    assert metrics.FONT_BASE_PT == round(taban[0] * 1.3, 1)
    assert metrics.FONT_TOTAL_PT == round(taban[1] * 1.3, 1)
    assert metrics.TABLE_ROW_HEIGHT == taban[2] + 8 and metrics.CARD_PADDING == taban[3] + 4
    assert metrics.TOUCH_TARGET_MIN == 56 and metrics.PAYMENT_BUTTON_HEIGHT == 88
    assert theme.base_font().pointSizeF() == pytest.approx(taban[0] * 1.3, abs=0.06)
    theme.gorunumu_uygula("LIGHT", 130, "NORMAL")
    assert metrics.TABLE_ROW_HEIGHT == taban[2], "tekrar çağrı tabandan hesaplar"
    metrics.sifirla()
    assert (metrics.FONT_BASE_PT, metrics.FONT_TOTAL_PT, metrics.TABLE_ROW_HEIGHT,
            metrics.CARD_PADDING) == taban


# ===================== Ayarlar › Görünüm ===================================
@pytest.fixture
def ayarlar(window, qapp):
    window.go_to("ayarlar")
    qapp.processEvents()
    return window.pages["ayarlar"]


def test_kaydet_ve_yeniden_baslat(ayarlar, window, services):
    assert ayarlar.appearance_choice() == ("LIGHT", 100, "NORMAL")
    assert not ayarlar.appearance_button.isEnabled()
    ayarlar.theme_combo.setCurrentIndex(ayarlar.theme_combo.findData("DARK"))
    ayarlar.font_scale_combo.setCurrentIndex(ayarlar.font_scale_combo.findData(120))
    assert ayarlar.appearance_button.isEnabled()
    assert "1000×600" in ayarlar.appearance_warning.text()
    assert services.settings.get("theme") == "LIGHT", "kaydetmeden yazılmaz"
    ayarlar.appearance_button.click()
    assert services.settings.gorunum() == gorunum.Gorunum("DARK", 120, "NORMAL")
    assert window.restarting, "yeniden başlatma istendi"


# ===================== %130 + Rahat yerleşimi ==============================
def test_yuzde_130_rahat_kasa_1366x768e_sigar(qapp, services, bira, varsayilana_don):
    from app.ui.main_window import MainWindow

    theme.gorunumu_uygula("DARK", 130, "RAHAT")
    theme.apply_theme(qapp)
    pencere = MainWindow(services)
    try:
        pencere.show()
        pencere.resize(1366, 768)
        qapp.processEvents()
        for anahtar in ("sepetli_satis", "hizli_satis", "fiyat_kontrol", "hizli_stok"):
            pencere.go_to(anahtar)
            qapp.processEvents()
            sayfa = pencere.pages[anahtar]
            assert sayfa.minimumSizeHint().height() <= pencere.stack.height(), (
                anahtar, sayfa.minimumSizeHint().height(), pencere.stack.height())
    finally:
        close_window(pencere, qapp)
        metrics.sifirla()
        theme.set_tokens(theme.LIGHT)
        theme.apply_theme(qapp)
