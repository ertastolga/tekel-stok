"""Ekran görüntüsü aracı (V1.2 M12b).

Korunan sözler:
  * örnek dükkân verisi gerçek servislerle üretilir ve tutarlıdır (derin
    denetim temiz; geri alma, günler arası geri alma, bekleyen sepet var),
  * araç karalama klasörü olmadan ve gerçek veri klasörüne asla çalışmaz,
  * YEREL çizimde (Windows yazı ölçüleri) 1000×600'de hiçbir sayfa yatay
    taşmaz ve Kasa sayfaları dikey bütçeye sığar — offscreen ölçüler farklı
    olduğu için bu denetim ayrı süreçte gerçek platformla yapılır.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.core.db import open_database
from app.tools import ekran_goruntusu as eg
from app.tools import veri_guvenligi

KOK = Path(__file__).resolve().parents[1]


@pytest.fixture
def karalama(tmp_path, monkeypatch):
    klasor = tmp_path / "karalama"
    monkeypatch.setenv("TEKEL_DATA_DIR", str(klasor))
    return klasor


def test_ornek_dukkan_tutarli_ve_gercekci(karalama):
    yol = eg.ornek_dukkan(karalama / "ornek.db")
    db = open_database(yol)
    try:
        assert db.check_invariants(deep=True) == []
        assert db.scalar("SELECT COUNT(*) FROM products") == len(eg.URUNLER)
        assert db.scalar("SELECT COUNT(DISTINCT business_date) FROM sales") == eg.ORNEK_GUN_SAYISI
        assert db.scalar("SELECT COUNT(*) FROM sales WHERE entry_type = 'SALE'") > 300
        assert db.scalar("SELECT COUNT(*) FROM sales r JOIN sales o ON o.id = r.reverses_sale_id "
                         "WHERE r.business_date <> o.business_date") >= 1, "günler arası iade"
        assert db.scalar("SELECT COUNT(*) FROM cart_drafts WHERE status = 'OPEN' "
                         "AND kind = 'PARKED'") == 1
        assert db.scalar("SELECT value FROM settings WHERE key = 'shop_name'") == \
            "Örnek Tekel Bayii"
    finally:
        db.close()
    for ek in ("-wal", "-shm"):
        assert not Path(str(yol) + ek).exists()


def test_karalama_klasoru_olmadan_calismaz(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TEKEL_DATA_DIR", raising=False)
    assert eg.main(["--cikti", str(tmp_path / "png")]) == 2
    assert "REDDEDİLDİ" in capsys.readouterr().err
    assert not (tmp_path / "png").exists()


def test_gercek_veri_klasorune_yazmaz(monkeypatch, tmp_path, capsys):
    sahte_yerel = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(sahte_yerel))
    monkeypatch.setenv("TEKEL_DATA_DIR", str(tmp_path / "karalama"))
    hedef = sahte_yerel / "TekelStok" / "png"
    assert eg.main(["--cikti", str(hedef)]) == 2
    assert "REDDEDİLDİ" in capsys.readouterr().err
    assert not hedef.exists()
    monkeypatch.setenv("TEKEL_DATA_DIR", str(sahte_yerel / "TekelStok"))
    with pytest.raises(veri_guvenligi.GercekVeriKlasoruHatasi):
        veri_guvenligi.karalama_klasoru()


def test_temas_sayfasi_her_profili_listeler(tmp_path):
    for ad in ("1000x600", "1366x768"):
        (tmp_path / ad).mkdir()
        (tmp_path / ad / "01_ana_ekran.png").write_bytes(b"\x89PNG")
    dizin = eg.temas_sayfasi(tmp_path, ["1000x600", "1366x768", "1920x1080"])
    metin = dizin.read_text(encoding="utf-8")
    assert "1000x600/01_ana_ekran.png" in metin and "1366x768/01_ana_ekran.png" in metin
    assert "1920x1080" not in metin, "görüntüsü olmayan profil listelenmez"


@pytest.mark.skipif(os.name != "nt", reason="yerel Windows çizimi gerekir")
def test_yerel_cizimde_1000x600_tasma_yok(tmp_path):
    """M12b: offscreen testleri geçerken gerçek Windows yazı ölçüleriyle Kasa
    1000×600'de 25 px taşıyordu; bu denetim o farkı yakalar."""
    ortam = dict(os.environ, TEKEL_DATA_DIR=str(tmp_path / "karalama"),
                 PYTHONIOENCODING="utf-8")
    ortam.pop("QT_QPA_PLATFORM", None)
    sonuc = subprocess.run(
        [sys.executable, "-m", "app.tools.ekran_goruntusu", "--cikti", str(tmp_path / "png"),
         "--profil", "1000x600", "--yalnizca-tasma"],
        cwd=str(KOK), env=ortam, capture_output=True, timeout=300)
    cikti = sonuc.stdout.decode("utf-8", "replace") + sonuc.stderr.decode("utf-8", "replace")
    assert sonuc.returncode == 0, cikti[-3000:]
    assert "taşma 0" in cikti, cikti[-3000:]
