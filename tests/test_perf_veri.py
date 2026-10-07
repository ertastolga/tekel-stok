"""Başarım veri üretici (V1.2 M1f).

Varsayılan süitte KÜÇÜK bir "doğruluk ikizi" çalışır: üretici gerçek
servislerle her kayıt türünü yazar, veri derin denetimde temizdir, aynı tohum
aynı veriyi verir ve araç gerçek veri klasörüyle çalışmayı reddeder.

Büyük şablonlar (``10k`` / ``100k``) yalnızca ``-m perf`` ile üretilir ve
oturumlar arasında önbelleklenir.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.db import open_database
from app.tools import perf_dataset, veri_guvenligi

KUCUK = perf_dataset.VeriParametreleri(urun=30, gun=10, satis=200, geri_alma_orani=0.08)


@pytest.fixture
def karalama(tmp_path, monkeypatch):
    klasor = tmp_path / "karalama"
    monkeypatch.setenv("TEKEL_DATA_DIR", str(klasor))
    return klasor


def test_kucuk_veri_her_kayit_turunu_icerir_ve_tutarlidir(karalama):
    sonuc = perf_dataset.uret(KUCUK, karalama / "kucuk.db")
    db = open_database(sonuc.yol)
    try:
        assert db.check_invariants(deep=True) == []
        modlar = {r[0] for r in db.query("SELECT DISTINCT sale_mode FROM sales")}
        assert modlar == {"SEPET", "HIZLI"}
        yontemler = {r[0] for r in db.query("SELECT DISTINCT payment_method FROM sales")}
        assert yontemler == {"NAKIT", "KART", None}
        assert sonuc.sayimlar["geri_alma"] > 0
        assert sonuc.sayimlar["gunler_arasi_geri_alma"] > 0
        assert sonuc.sayimlar["purchase_receipts"] > 0
        assert sonuc.sayimlar["count_sessions"] > 0
        assert sonuc.sayimlar["price_history"] > 0
        assert db.scalar("SELECT COUNT(DISTINCT business_date) FROM sales") == KUCUK.gun
        assert db.scalar("SELECT MAX(business_date) FROM sales") == "2026-09-30"
    finally:
        db.close()
    for ek in ("-wal", "-shm"):
        assert not Path(str(sonuc.yol) + ek).exists(), "yan dosya kalmadı"
    meta = json.loads(Path(str(sonuc.yol) + ".meta.json").read_text(encoding="utf-8"))
    assert meta["parametreler"]["satis"] == KUCUK.satis
    assert meta["sayimlar"]["sales"] == KUCUK.satis


def test_ayni_tohum_ayni_veri_farkli_tohum_farkli_veri(karalama):
    a = perf_dataset.uret(KUCUK, karalama / "a.db")
    b = perf_dataset.uret(KUCUK, karalama / "b.db")
    from dataclasses import replace

    c = perf_dataset.uret(replace(KUCUK, tohum=7), karalama / "c.db")
    assert perf_dataset.parmak_izi(a.yol) == perf_dataset.parmak_izi(b.yol)
    assert perf_dataset.parmak_izi(a.yol) != perf_dataset.parmak_izi(c.yol)


def test_uretici_gercek_saati_ve_saat_saglayicisini_geride_birakmaz(karalama):
    from datetime import datetime

    from app.core import clock

    perf_dataset.uret(KUCUK, karalama / "s.db")
    assert abs((clock.local_now() - datetime.now()).total_seconds()) < 5


def test_karalama_klasoru_olmadan_calismaz(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TEKEL_DATA_DIR", raising=False)
    assert perf_dataset.main(["--hazir", "kucuk", "--cikti", str(tmp_path / "x.db")]) == 2
    assert "REDDEDİLDİ" in capsys.readouterr().err
    assert not (tmp_path / "x.db").exists()
    with pytest.raises(veri_guvenligi.GercekVeriKlasoruHatasi):
        perf_dataset.uret(KUCUK, tmp_path / "y.db")


def test_gercek_veri_klasorune_yazmayi_reddeder(monkeypatch, tmp_path):
    sahte_yerel = tmp_path / "LocalAppData"
    monkeypatch.setenv("LOCALAPPDATA", str(sahte_yerel))
    monkeypatch.setenv("TEKEL_DATA_DIR", str(tmp_path / "karalama"))
    gercek = sahte_yerel / "TekelStok" / "perf.db"
    with pytest.raises(veri_guvenligi.GercekVeriKlasoruHatasi):
        perf_dataset.uret(KUCUK, gercek)
    assert not gercek.exists()

    monkeypatch.setenv("TEKEL_DATA_DIR", str(sahte_yerel / "TekelStok"))
    assert perf_dataset.main(["--hazir", "kucuk"]) == 2


def test_var_olan_dosyanin_ustune_yazmaz(karalama):
    hedef = karalama / "var.db"
    hedef.parent.mkdir(parents=True)
    hedef.write_bytes(b"dokunma")
    with pytest.raises(FileExistsError):
        perf_dataset.uret(KUCUK, hedef)
    assert hedef.read_bytes() == b"dokunma"


def test_onbellek_anahtari_parametreye_ve_kaynaga_baglidir():
    from dataclasses import replace

    a = perf_dataset.HAZIR["10k"]
    assert a.anahtar() == perf_dataset.HAZIR["10k"].anahtar()
    assert a.anahtar() != replace(a, tohum=1).anahtar()
    assert a.anahtar() != perf_dataset.HAZIR["100k"].anahtar()


# ===================== Büyük şablonlar (yalnızca -m perf) ==================
@pytest.mark.perf
@pytest.mark.parametrize("ad", ["10k", "100k"])
def test_buyuk_sablon_uretilir_ve_tutarlidir(perf_sablonu, perf_kopya, ad):
    sablon = perf_sablonu(ad)
    beklenen = perf_dataset.HAZIR[ad]
    meta = json.loads(Path(str(sablon) + ".meta.json").read_text(encoding="utf-8"))
    assert meta["sayimlar"]["sales"] == beklenen.satis
    assert meta["sayimlar"]["products"] == beklenen.urun
    conn_db = open_database(perf_kopya(ad))
    try:
        assert conn_db.integrity_check() == "ok"
        assert conn_db.check_invariants(deep=True) == []
    finally:
        conn_db.close()
