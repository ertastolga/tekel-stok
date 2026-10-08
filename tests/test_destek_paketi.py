"""Destek Paketi (V1.2 M10d).

Korunan sözler:
  * ZIP: sistem.json, ayarlar.json, tanilama.json, self_test.txt, logs/;
    veritabanı VARSAYILAN OLARAK YOK,
  * ayarlar beyaz listedir: güvenlik ve iç ayarlar yok,
  * BAYT DÜZEYİNDE: hiçbir dosyada ``guvenlik_``, ``scrypt$``, PIN özeti/tuzu,
    kullanıcı profili yolu (8.3 kısa biçimi dahil) ve kullanıcı adı yok —
    veritabanı kopyası istendiğinde de,
  * veritabanı kopyası yedekleme API'siyle alınır, güvenlik satırları silinir,
    VACUUM'lanır; geçici dosya her durumda silinir,
  * kendi kendini sınama ayrı süreçte çalışır ve rapora girer.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

import pytest

from app import config
from app.services import support_package as sp
from app.services.import_service import ICE_AKTARMA_YEDEK_ONEKI

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui_support import *  # noqa: E402,F401,F403


def _stub_self_test():
    return "Sonuc: TUM KONTROLLER BASARILI"


def _uyelik(zip_yolu: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(zip_yolu) as paket:
        return {ad: paket.read(ad) for ad in paket.namelist()}


def _yasakli_baytlar(services) -> list[bytes]:
    yasak = [b"guvenlik_", b"scrypt$"]
    ozet = services.settings.get("guvenlik_pin_hash", "")
    for parca in ozet.split("$")[4:]:                   # tuz ve özet
        yasak.append(parca.encode())
    for ad in ("USERPROFILE", "USERNAME"):
        deger = os.environ.get(ad, "")
        if len(deger) >= 3:
            yasak += [deger.encode("utf-8"), deger.encode("utf-8").replace(b"\\", b"\\\\")]
            kisa = sp._kisa_yol(deger) if ad == "USERPROFILE" else None
            if kisa:
                yasak.append(kisa.encode("utf-8"))
    return [y for y in yasak if y]


def test_varsayilan_paket_icerigi(services, bira, tmp_path):
    hedef = services.support.olustur(tmp_path / "destek.zip", tanilama=[{"kod": "123"}],
                                     qt_surumu="Qt test", self_test=_stub_self_test)
    uyeler = _uyelik(hedef)
    assert {"sistem.json", "ayarlar.json", "tanilama.json", "self_test.txt"} <= set(uyeler)
    assert "veritabani.db" not in uyeler, "veritabanı varsayılan olarak eklenmez"
    sistem = json.loads(uyeler["sistem.json"])
    assert sistem["surum"] == config.APP_VERSION and sistem["derin_denetim"] == []
    assert sistem["tablolar"]["products"] == 1
    ayarlar = json.loads(uyeler["ayarlar.json"])
    assert "duplicate_scan_ms" in ayarlar
    assert not any(k.startswith(("guvenlik_", "last_backup_", "window_")) for k in ayarlar)
    assert json.loads(uyeler["tanilama.json"]) == [{"kod": "123"}]
    assert not list(tmp_path.glob("*.tmp")), "geçici zip kalmaz"


def test_bayt_duzeyinde_maskeleme_veritabani_dahil(services, bira, tmp_path):
    services.security.set_pin("4826")
    assert services.settings.get("guvenlik_pin_hash", "").startswith("scrypt$")
    # Denetim kaydına kişisel yol giren bir işlem (içe aktarma öncesi yedek yolu).
    yedek = services.backup.create_safety_backup(ICE_AKTARMA_YEDEK_ONEKI)
    services.audit.record("DENEME", f"yedek {yedek}", details={"yol": str(yedek)})
    log_yolu = config.log_file_path()
    log_yolu.parent.mkdir(parents=True, exist_ok=True)
    with open(log_yolu, "a", encoding="utf-8") as dosya:
        dosya.write(f"INFO veri klasörü {Path.home()}\nDEBUG guvenlik_pin_hash okundu\n")

    hedef = services.support.olustur(tmp_path / "destek.zip", veritabani_ekle=True,
                                     self_test=_stub_self_test)
    uyeler = _uyelik(hedef)
    assert "veritabani.db" in uyeler and any(a.startswith("logs/") for a in uyeler)
    for ad, icerik in uyeler.items():
        for yasak in _yasakli_baytlar(services):
            assert yasak not in icerik, (ad, yasak)
    assert sp.MASKE.encode() in uyeler["logs/app.log"]

    kopya = tmp_path / "kopya.db"
    kopya.write_bytes(uyeler["veritabani.db"])
    baglanti = sqlite3.connect(kopya)
    try:
        assert baglanti.execute("SELECT COUNT(*) FROM settings WHERE key LIKE "
                                "'guvenlik%'").fetchone()[0] == 0
        assert baglanti.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
        assert baglanti.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        baglanti.close()
    assert services.security.has_pin(), "canlı veritabanı değişmedi"


def test_gecici_veritabani_her_durumda_silinir(services, tmp_path, monkeypatch):
    oncekiler = set(Path(tempfile.gettempdir()).glob("tekelstok_destek_*.db"))

    def patla(self, hedef):
        Path(hedef).write_bytes(b"yarim")
        raise RuntimeError("disk dolu")

    monkeypatch.setattr(sp.SupportPackageService, "_veritabani_kopyasi", patla)
    with pytest.raises(RuntimeError):
        services.support.olustur(tmp_path / "destek.zip", veritabani_ekle=True,
                                 self_test=_stub_self_test)
    assert set(Path(tempfile.gettempdir()).glob("tekelstok_destek_*.db")) == oncekiler
    assert not (tmp_path / "destek.zip").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_maskele():
    profil = os.environ.get("USERPROFILE") or str(Path.home())
    metin = f"yol={profil}\\AppData yol2={profil.replace(chr(92), '/')}/x"
    sonuc = sp.maskele(metin)
    assert profil not in sonuc and profil.replace("\\", "/") not in sonuc
    assert sonuc.count(sp.MASKE) >= 2
    assert sp.gizli_satirlari_cikar("a\nguvenlik_x=1\nb\nscrypt$1$2\n") == "a\nb"


def test_kendi_kendini_sinama_ayri_surecte(services, tmp_path):
    rapor = sp._self_test_varsayilan()
    assert "TUM KONTROLLER BASARILI" in rapor, rapor[-500:]


def test_sistem_durumu_sayfasindan(window, qapp, services, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(sp, "_self_test_varsayilan", _stub_self_test)
    window.go_to("sistem_durumu")
    qapp.processEvents()
    sayfa = window.pages["sistem_durumu"]
    assert not sayfa.include_db_check.isChecked(), "veritabanı varsayılan olarak yok"
    hedef = sayfa.create_support_package(tmp_path / "paket.zip")
    assert hedef is not None and "veritabani.db" not in _uyelik(hedef)
    assert QApplication.overrideCursor() is None, "bekleme imleci geri alındı"

    def patla(*a, **k):
        raise RuntimeError("disk dolu")

    monkeypatch.setattr(services.support, "olustur", patla)
    assert sayfa.create_support_package(tmp_path / "paket2.zip") is None
    assert QApplication.overrideCursor() is None, "hata olsa da imleç geri alındı"


def test_butunluk_bir_kez_denetlenir(services, tmp_path):
    """Tam bütünlük denetimi hızlı denetimi kapsar: pakette ikisi birden
    çalışmaz (100k veride saniyeler, M11); satırda tam denetimin sonucu var."""
    kayit: list[str] = []
    services.db.conn.set_trace_callback(kayit.append)
    try:
        hedef = services.support.olustur(tmp_path / "d.zip", self_test=_stub_self_test)
    finally:
        services.db.conn.set_trace_callback(None)
    assert sum("integrity_check" in sql for sql in kayit) == 1
    assert not any("quick_check" in sql for sql in kayit)
    sistem = json.loads(_uyelik(hedef)["sistem.json"])
    satir = {s["oge"]: s for s in sistem["durum"]}["Tam bütünlük denetimi"]
    assert satir["deger"] == "sorun yok"
