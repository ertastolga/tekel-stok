"""İşletme ve Donanım ayarları (V1.2 M9d).

Korunan sözler:
  * dükkân adı kaydedilir ve pencere başlığında görünür,
  * gün başlangıcı: şu anki ve BEKLEYEN kural birlikte gösterilir; bekleyen
    kural varken yeni değer SESSİZCE üzerine yazılmaz (soru hangi bekleyen
    değişikliğin değiştirileceğini söyler); bekleyen değişiklik iptal
    edilebilir, bugünkü ve geçmiş kurallara dokunulmaz,
  * donanım durumları dürüsttür: kanıt (makine hızında gerçek okutma) yoksa
    hiçbir şey "çalışıyor" değildir; müşteri ekranı, POS, yazıcı ve çekmece
    "yok / tanımlı değil".
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.clock import shift_days  # noqa: E402
from app.hardware import durum as hd  # noqa: E402
from app.scanner.scan_event import ScanEvent  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403


@pytest.fixture
def ayarlar(window, qapp):
    window.go_to("ayarlar")
    qapp.processEvents()
    sayfa = window.pages["ayarlar"]
    sayfa.refresh()
    return sayfa


# ===================== İşletme =============================================
def test_dukkan_adi_basliga_yansir(ayarlar, window, services):
    ayarlar.shop_edit.setText("Yıldız Tekel")
    ayarlar.shop_edit.editingFinished.emit()
    assert services.settings.shop_name() == "Yıldız Tekel"
    assert window.windowTitle().endswith("— Yıldız Tekel")


def test_bekleyen_gun_kurali_gorunur_ve_sessizce_ezilmez(ayarlar, services, onay):
    ayar = services.settings
    bugun = ayar.calendar().today()
    ayarlar.day_spin.setValue(4)
    ayarlar.day_button.click()
    yarin = shift_days(bugun, 1)
    assert ayar.pending_business_day_rule() == (yarin, 4)
    assert "Bekleyen değişiklik" in ayarlar.day_status.text()
    assert not ayarlar.day_cancel_button.isHidden()

    ayarlar.day_spin.setValue(5)
    ayarlar.day_button.click()
    soru = onay.sorular.index("Yeni gün 05:00'da başlasın mı?")
    assert "Bekleyen değişiklik" in onay.ayrintilar[soru]
    assert "04:00" in onay.ayrintilar[soru], "hangi bekleyen kuralın değişeceği yazar"
    assert ayar.pending_business_day_rule() == (yarin, 5)

    ayarlar.day_cancel_button.click()
    assert ayar.pending_business_day_rule() is None
    assert ayarlar.day_cancel_button.isHidden()
    assert ayar.current_business_day_start_hour() == ayar.calendar().start_hour_for(bugun)


def test_iptal_yalnizca_gelecek_kurallari_siler(duvar_saati, services):
    # Saat SABİT (öğle): sonuç duvar saatine bağlı olmamalı. M12d son kapıda bu
    # test gerçek saatle 02:10'da çalışıp düştü (bkz. aşağıdaki gece testi).
    duvar_saati.git(2026, 10, 8, 12)
    ayar = services.settings
    bugun = ayar.calendar().today()
    assert bugun == "2026-10-08"
    ayar.set_business_day_start_hour(3, bugun)
    ayar.set_business_day_start_hour(5, shift_days(bugun, 3))
    assert ayar.cancel_pending_business_day_rules() == 1
    assert ayar.current_business_day_start_hour() == 3, "bugünkü kural kalır"


def test_gece_bugun_kurali_henuz_baslamadiysa_bekleyen_sayilir(duvar_saati, services):
    """02:10'da "bugünden itibaren gün 03:00'te başlasın" denirse yeni kurala göre
    bugünün iş günü HENÜZ başlamamıştır: an dünün iş gününe düşer. Gösterim
    (bekleyen kural) ile iptal AYNI tanımı kullanır; iptal eski kurala döndürür."""
    duvar_saati.git(2026, 10, 9, 2, 10)
    ayar = services.settings
    assert ayar.calendar().today() == "2026-10-09"           # varsayılan kural 00:00
    ayar.set_business_day_start_hour(3, "2026-10-09")
    assert ayar.calendar().today() == "2026-10-08"
    assert ayar.pending_business_day_rule() == ("2026-10-09", 3), "bekleyen gösterilir"
    ayar.set_business_day_start_hour(5, "2026-10-12")
    assert ayar.cancel_pending_business_day_rules() == 2
    assert ayar.pending_business_day_rule() is None
    assert ayar.calendar().today() == "2026-10-09", "eski kurala dönüldü"
    duvar_saati.git(2026, 10, 9, 12)
    ayar.set_business_day_start_hour(3, "2026-10-09")
    assert ayar.pending_business_day_rule() is None, "öğlen bugünün kuralı yürürlükte"


# ===================== Donanım =============================================
class _Saat:
    t = 100.0

    def __call__(self):
        return self.t


def test_kanit_yoksa_hicbir_sey_calisiyor_degil(services):
    durumlar = services.hardware.durumlar()
    assert [d.ad for d in durumlar] == ["Barkod okuyucu", "Müşteri ekranı",
                                        "Banka POS cihazı", "Fiş yazıcısı", "Para çekmecesi"]
    assert all(d.durum != hd.CALISIYOR for d in durumlar)
    assert durumlar[0].durum == hd.BILINMIYOR
    assert durumlar[1].durum == hd.YOK and durumlar[2].durum == hd.YOK
    assert "POS'a siz girersiniz" in durumlar[2].aciklama


def test_okuyucu_yalnizca_gercek_okutmayla_calisiyor(services):
    saat = _Saat()
    durumlar = hd.HardwareStatusService(services.display, services.payments, clock=saat)
    durumlar.okutma_kaydet(ScanEvent(code="123", key_count=13, avg_gap_ms=200.0))  # insan
    durumlar.okutma_kaydet(ScanEvent(code="8690504001492", key_count=13, avg_gap_ms=8.0,
                                     source="ELLE"))
    assert durumlar.durumlar()[0].durum == hd.BILINMIYOR
    durumlar.okutma_kaydet(ScanEvent(code="8690504001492", key_count=13, avg_gap_ms=8.0))
    saat.t += 42
    okuyucu = durumlar.durumlar()[0]
    assert okuyucu.durum == hd.CALISIYOR and "42 sn önce" in okuyucu.aciklama


def test_donanim_bolumu_listeler(ayarlar, window):
    assert "donanim" in ayarlar.bolumler
    assert ayarlar.hardware_table.rowCount() == 5
    assert ayarlar.hardware_table.item(0, 1).text() == "Bilinmiyor"
    window.scanner.scanned.emit(ScanEvent(code="8690504001492", key_count=13,
                                          avg_gap_ms=7.0))
    ayarlar._donanim_doldur()
    assert ayarlar.hardware_table.item(0, 1).text() == "Çalışıyor"
