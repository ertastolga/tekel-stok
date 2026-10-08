"""V1.2 mimari ve veri güvenliği korumaları.

``test_migrations.py`` içindeki V1 kuralları aynen durur; bu dosya V1.2 ile
GENİŞLEYEN kapsamı ekler:

* Qt'suz olması gereken her paket (ödeme, donanım, okuyucu yönlendiricisi,
  araç güvenliği) AST ile denetlenir; ayrıca servis kabının dolaylı yoldan
  PySide6 YÜKLEMEDİĞİ ayrı bir süreçte kanıtlanır,
* Kasa modüllerinde iç içe olay döngüsü (``QEventLoop``) yasaktır,
* V1.0/V1.1 örnek veritabanları işlendikleri hâlleriyle kalır,
* geliştirici araçları sahibin gerçek veri klasörüyle çalışmayı reddeder.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.tools import veri_guvenligi

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

#: Qt içermemesi gereken V1.2 kapsamı (V1'in core/services/analytics'i ayrıca
#: test_migrations.py tarafından denetlenir). Yeni Qt'suz paketler buraya eklenir.
QT_SUZ = [
    "app/payments",
    "app/hardware",
    "app/scanner/scan_router.py",
    "app/scanner/scan_event.py",
    "app/tools/veri_guvenligi.py",
    "app/tools/perf_dataset.py",
    "app/importers",
]

#: Kasa sayfaları: iç içe olay döngüsü kullanmaz (kaplamalar sinyalle çalışır).
KASA_MODULLERI = [
    "app/ui/pages/cart_sale.py",
    "app/ui/pages/quick_sale.py",
    "app/ui/pages/price_check.py",
    "app/ui/widgets/kasa_overlays.py",
]


def _py_dosyalari(goreli: str) -> list[Path]:
    yol = ROOT / goreli
    return sorted(yol.rglob("*.py")) if yol.is_dir() else [yol]


def test_qt_suz_paketler_pyside6_icermez():
    ihlaller = []
    for goreli in QT_SUZ:
        dosyalar = _py_dosyalari(goreli)
        assert dosyalar and all(d.exists() for d in dosyalar), goreli
        for yol in dosyalar:
            agac = ast.parse(yol.read_text(encoding="utf-8"), filename=str(yol))
            for dugum in ast.walk(agac):
                if isinstance(dugum, ast.Import):
                    adlar = [a.name for a in dugum.names]
                elif isinstance(dugum, ast.ImportFrom):
                    adlar = [dugum.module or ""]
                else:
                    continue
                if any(ad.startswith(("PySide6", "shiboken6")) for ad in adlar):
                    ihlaller.append(f"{yol.relative_to(ROOT)}:{dugum.lineno}")
    assert ihlaller == [], f"Qt bağımlılığı sızmış: {ihlaller}"


def test_servis_kabi_dolayli_yoldan_bile_qt_yuklemez(tmp_path):
    """AST denetimi doğrudan içe aktarmayı yakalar; bu test DOLAYLI olanı."""
    betik = (
        "import sys; import app.services.container, app.payments.service, "
        "app.hardware.customer_display, app.scanner.scan_router; "
        "print([m for m in sys.modules if m.split('.')[0] in ('PySide6','shiboken6')])"
    )
    ortam = dict(os.environ, TEKEL_DATA_DIR=str(tmp_path / "veri"))
    sonuc = subprocess.run(
        [sys.executable, "-c", betik], cwd=ROOT, env=ortam,
        capture_output=True, text=True, timeout=120,
    )
    assert sonuc.returncode == 0, sonuc.stderr
    assert sonuc.stdout.strip() == "[]", sonuc.stdout


def test_kasa_modullerinde_ic_ice_olay_dongusu_yok():
    ihlaller = []
    for goreli in KASA_MODULLERI:
        yol = ROOT / goreli
        if not yol.exists():          # henüz oluşturulmamış Kasa modülü
            continue
        metin = yol.read_text(encoding="utf-8")
        if "QEventLoop" in metin:
            ihlaller.append(goreli)
        # Katmanlar hiçbir şeyi ``exec`` ile açmaz (V1.2 M3b).
        if goreli.endswith("kasa_overlays.py") and ".exec(" in metin:
            ihlaller.append(f"{goreli}: exec")
    assert ihlaller == [], f"Kasa'da iç içe olay döngüsü: {ihlaller}"


@pytest.mark.parametrize("ad", ["v1_1_ornek", "v1_0_ornek"])
def test_ornek_veritabani_islendigi_gibi_kalir(ad, tmp_path):
    meta = json.loads((FIXTURES / f"{ad}.meta.json").read_text(encoding="utf-8"))
    veri = (FIXTURES / f"{ad}.db").read_bytes()
    assert hashlib.sha256(veri).hexdigest() == meta["sha256"]
    for son_ek in ("-wal", "-shm"):
        assert not (FIXTURES / f"{ad}.db{son_ek}").exists()

    kopya = tmp_path / "kopya.db"          # örnek dosya ASLA yerinde açılmaz
    shutil.copyfile(FIXTURES / f"{ad}.db", kopya)
    baglanti = sqlite3.connect(kopya)
    try:
        surum = baglanti.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()[0]
        assert int(surum) == 1
        for tablo, adet in meta["satir_sayilari"].items():
            assert baglanti.execute(f"SELECT COUNT(*) FROM {tablo}").fetchone()[0] == adet
    finally:
        baglanti.close()


def test_v1_1_kopya_duzenegi_ornegi_kopyalar(v1_1_kopya):
    assert v1_1_kopya.exists() and v1_1_kopya.parent != FIXTURES


# ===================== Araçların veri güvenliği ==========================
def test_arac_karalama_klasoru_olmadan_calismaz(monkeypatch):
    monkeypatch.delenv("TEKEL_DATA_DIR", raising=False)
    with pytest.raises(veri_guvenligi.GercekVeriKlasoruHatasi):
        veri_guvenligi.karalama_klasoru()


def test_arac_gercek_veri_klasorunu_reddeder(monkeypatch, tmp_path):
    sahte_yerel = tmp_path / "Yerel"
    monkeypatch.setenv("LOCALAPPDATA", str(sahte_yerel))
    for hedef in (sahte_yerel / "TekelStok", sahte_yerel / "TekelStok" / "alt"):
        monkeypatch.setenv("TEKEL_DATA_DIR", str(hedef))
        with pytest.raises(veri_guvenligi.GercekVeriKlasoruHatasi):
            veri_guvenligi.karalama_klasoru()


def test_arac_karalama_klasorunu_kabul_eder(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Yerel"))
    monkeypatch.setenv("TEKEL_DATA_DIR", str(tmp_path / "karalama"))
    assert veri_guvenligi.karalama_klasoru() == (tmp_path / "karalama").resolve()


@pytest.mark.parametrize("gercegi_goster", [False, True])
def test_ornek_ureteci_guvensiz_klasorde_calismaz(gercegi_goster, tmp_path):
    ortam = {k: v for k, v in os.environ.items() if k != "TEKEL_DATA_DIR"}
    ortam["LOCALAPPDATA"] = str(tmp_path / "Yerel")
    if gercegi_goster:
        ortam["TEKEL_DATA_DIR"] = str(tmp_path / "Yerel" / "TekelStok")
    cikti = tmp_path / "olmamali.db"
    sonuc = subprocess.run(
        [sys.executable, str(FIXTURES / "make_v1_1_fixture.py"), "--surum", "1.1",
         "--kok", str(ROOT), "--cikti", str(cikti)],
        cwd=ROOT, env=ortam, capture_output=True, text=True, timeout=120,
    )
    assert sonuc.returncode != 0
    assert "REDDEDILDI" in (sonuc.stdout + sonuc.stderr)
    assert not cikti.exists()
    assert not (tmp_path / "Yerel").exists()


# ===================== Dağıtılmış V1.1'in korunması =======================
def test_derleme_dagitilmis_v1_1_klasorune_yazmayi_reddeder(monkeypatch):
    """V1.2 derlemesi sahibin kullandığı dist/TekelStok'u asla ezmez (plan §2)."""
    import build_exe

    for korunan in ("TekelStok", "TekelStok_tasinabilir.zip", "TekelStok.exe"):
        assert build_exe.korumali_mi(build_exe.DIST / korunan)
    assert not build_exe.korumali_mi(build_exe.DIST / "TekelStok-1.2.0b1")
    assert build_exe.varsayilan_cikti_adi().startswith("TekelStok-")

    monkeypatch.setattr(sys, "argv", ["build_exe.py", "--out", "TekelStok", "--skip-tests"])
    cagrildi = []
    monkeypatch.setattr(build_exe, "run_pyinstaller", lambda *a, **k: cagrildi.append(a))
    assert build_exe.main() == 2
    assert cagrildi == [], "reddedilen hedef için derleme başlamamalı"
