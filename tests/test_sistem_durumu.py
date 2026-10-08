"""🩺 Sistem Durumu (V1.2 M10c, plan §6.5).

Korunan sözler:
  * §6.5'teki her öğe listelenir; durum metinle yazılır,
  * hızlı bütünlük denetimi açılışta; tam + derin tutarlılık denetimi istek
    üzerine ve bulunan sorunu gösterir,
  * göçten önce de var olan ilişki ihlalleri uyarı olarak görünür,
  * son yedek hatası "SON DENEME BAŞARISIZ" diye görünür,
  * donanım satırları dürüsttür; okutma yoksa "bu oturumda okutma yok".
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.services import system_status as sd  # noqa: E402
from app.services.backup_service import YedekHatasi  # noqa: E402

from ui_support import *  # noqa: E402,F401,F403


def _satirlar(services) -> dict[str, sd.DurumSatiri]:
    return {s.baslik: s for s in services.system_status.satirlar("Qt test")}


def test_her_oge_listelenir(services):
    satirlar = _satirlar(services)
    for baslik in ("Sürüm", "Veri şeması", "Veri klasörü", "Hızlı bütünlük denetimi",
                   "Son yedek", "Yedekler", "Boş disk (veri)", "Boş disk (yedek)",
                   "Son okutma", "Barkod okuyucu", "Müşteri ekranı", "Banka POS cihazı",
                   "Python", "Qt / PySide6", "SQLite", "İşletim sistemi", "Paketli uygulama"):
        assert baslik in satirlar, baslik
    assert satirlar["Hızlı bütünlük denetimi"].durum == sd.IYI
    assert satirlar["Veri şeması"].durum == sd.IYI
    assert satirlar["Son okutma"].deger == "bu oturumda okutma yok"
    assert satirlar["Qt / PySide6"].deger == "Qt test"
    assert satirlar["Son yedek"].durum == sd.UYARI, "hiç yedek yok"


def test_yedek_hatasi_gorunur(services, monkeypatch):
    services.backup.create_manual()
    assert _satirlar(services)["Son yedek"].durum == sd.IYI
    monkeypatch.setattr("app.services.backup_service.shutil.disk_usage",
                        lambda yol: type("D", (), {"free": 1})())
    with pytest.raises(YedekHatasi):
        services.backup.create_manual()
    monkeypatch.undo()
    son = _satirlar(services)["Son yedek"]
    assert son.durum == sd.HATA and "SON DENEME BAŞARISIZ" in son.deger


def test_derin_denetim_ve_onceden_var_olan_ihlal(services, bira):
    assert services.system_status.derin_denetim() == []
    with services.db.transaction() as conn:
        conn.execute("UPDATE products SET current_stock = current_stock + 3 WHERE id = ?",
                     (bira,))
    assert services.system_status.derin_denetim(), "tutarsızlık bulunur"
    services.db.preexisting_fk_violations = [("sale_items", 7, "sales", 0)]
    assert any("ilişki ihlali" in u for u in services.system_status.uyarilar())


def test_boyut_metni():
    assert sd.boyut_metni(None) == "bilinmiyor"
    assert sd.boyut_metni(512) == "512 B"
    assert sd.boyut_metni(3 * 2**20) == "3,0 MB"


def test_sayfa(window, qapp, services, bira):
    window.go_to("sistem_durumu")
    qapp.processEvents()
    sayfa = window.pages["sistem_durumu"]
    assert sayfa.table.rowCount() >= 17
    durumlar = {sayfa.table.item(i, 2).text() for i in range(sayfa.table.rowCount())}
    assert durumlar <= set(sd.DURUMLAR.values())
    assert sayfa.run_deep_check() == []
    assert sayfa.deep_result.text() == "Tam denetim: sorun bulunmadı."
