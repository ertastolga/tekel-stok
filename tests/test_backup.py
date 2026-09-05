"""Yedekleme ve geri yükleme.

Korunan söz: geri yükleme BAŞARISIZ OLSA BİLE kullanıcı verisi kaybolmaz.
"""
from __future__ import annotations

import sqlite3

import pytest

from app import config
from app.core.errors import YedekHatasi, YedekOkunamadi


@pytest.fixture
def dolu(services, bira, cips_urunu):
    """Yedeklenecek gerçekçi bir veri kümesi."""
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)
    services.sales.quick_sale(bira)
    return services


# ===================== Yedek alma ========================================
def test_calisir_veritabaninda_yedek_alinir(dolu):
    """Uygulama açık ve yazılabilir durumdayken yedek alınabilmelidir."""
    yol = dolu.backup.create_manual()

    assert yol.exists() and yol.stat().st_size > 0
    bilgi = dolu.backup.inspect(yol)
    assert bilgi.product_count == 2
    assert bilgi.sale_count == 1

    dolu.sales.quick_sale(dolu.products.by_name("Tuborg Gold 50 cl Kutu")["id"])
    assert dolu.db.scalar("SELECT COUNT(*) FROM sales") == 2, "yedekten sonra çalışmaya devam"


def test_elle_yedek_belgeler_altina_yazilir(dolu):
    yol = dolu.backup.create_manual()
    assert yol.name.startswith(config.MANUAL_BACKUP_PREFIX)
    assert yol.parent == dolu.backup.manual_dir()


def test_yedek_gecerli_sqlite_dosyasidir(dolu):
    yol = dolu.backup.create_manual()
    kopya = sqlite3.connect(f"file:{yol}?mode=ro", uri=True)
    try:
        assert kopya.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert kopya.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 2
    finally:
        kopya.close()


# ===================== Otomatik yedek ====================================
def test_otomatik_yedek_veri_degismediyse_alinmaz(dolu):
    dolu.backup.create_auto()
    assert dolu.backup.auto_backup_due() is False
    assert dolu.backup.maybe_auto_backup() is None


def test_veri_degisince_otomatik_yedek_gerekir(dolu, bira):
    dolu.backup.create_auto()
    dolu.settings.set("auto_backup_interval_minutes", 5)
    dolu.sales.quick_sale(bira)

    dolu.settings.set_many_quiet({"last_backup_at_utc": 0})
    assert dolu.backup.auto_backup_due() is True


def test_saklama_siniri_eski_otomatik_yedekleri_siler(dolu, bira):
    dolu.settings.set("auto_backup_retention", 3)
    for _ in range(5):
        dolu.sales.quick_sale(bira)
        dolu.backup.create_auto()

    otomatik = [b for b in dolu.backup.list_backups() if b.is_auto]
    assert len(otomatik) == 3


def test_elle_yedekler_asla_otomatik_silinmez(dolu, bira):
    dolu.settings.set("auto_backup_retention", 1)
    elle = [dolu.backup.create_manual() for _ in range(3)]
    for _ in range(3):
        dolu.sales.quick_sale(bira)
        dolu.backup.create_auto()

    dolu.backup.cleanup_auto_backups()
    assert all(y.exists() for y in elle), "elle alınan yedekler korunur"


# ===================== Doğrulama =========================================
def test_bozuk_dosya_reddedilir(dolu, tmp_path):
    sahte = tmp_path / "bozuk.db"
    sahte.write_bytes(b"bu bir veritabani degil")
    with pytest.raises(YedekOkunamadi):
        dolu.backup.inspect(sahte)


def test_olmayan_dosya_reddedilir(dolu, tmp_path):
    with pytest.raises(YedekOkunamadi):
        dolu.backup.inspect(tmp_path / "yok.db")


def test_ilgisiz_sqlite_dosyasi_reddedilir(dolu, tmp_path):
    yabanci = tmp_path / "baska.db"
    conn = sqlite3.connect(yabanci)
    conn.execute("CREATE TABLE t(x)")
    conn.commit()
    conn.close()
    with pytest.raises(YedekOkunamadi):
        dolu.backup.inspect(yabanci)


def test_daha_yeni_surumlu_yedek_reddedilir(dolu, tmp_path):
    yol = dolu.backup.create_manual()
    conn = sqlite3.connect(yol)
    conn.execute("UPDATE schema_meta SET value = '999' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    with pytest.raises(YedekOkunamadi):
        dolu.backup.inspect(yol)


# ===================== Geri yükleme ======================================
def test_geri_yukleme_veriyi_o_ana_dondurur(dolu, bira):
    yedek = dolu.backup.create_manual()
    stok_yedekte = dolu.products.get(bira)["current_stock"]

    for _ in range(5):
        dolu.sales.quick_sale(bira)
    assert dolu.products.get(bira)["current_stock"] == stok_yedekte - 5

    dolu.backup.restore(yedek)

    assert dolu.products.get(bira)["current_stock"] == stok_yedekte
    assert dolu.db.scalar("SELECT COUNT(*) FROM sales WHERE entry_type='SALE'") == 1
    assert dolu.db.check_invariants(deep=True) == []


def test_geri_yukleme_oncesi_guvenlik_kopyasi_alinir(dolu, bira):
    yedek = dolu.backup.create_manual()
    for _ in range(3):
        dolu.sales.quick_sale(bira)
    satis_sayisi = dolu.db.scalar("SELECT COUNT(*) FROM sales WHERE entry_type='SALE'")

    guvenlik = dolu.backup.restore(yedek)

    assert guvenlik.exists()
    assert guvenlik.name.startswith(config.PRE_RESTORE_PREFIX)
    bilgi = dolu.backup.inspect(guvenlik)
    assert bilgi.sale_count == satis_sayisi, (
        "güvenlik kopyası geri yükleme ÖNCESİNDEKİ hâli taşır"
    )


def test_basarisiz_geri_yukleme_mevcut_veriyi_korur(dolu, bira, tmp_path, monkeypatch):
    """En kritik söz: geri yükleme patlarsa çalışan veritabanı geri gelir."""
    yedek = dolu.backup.create_manual()
    for _ in range(3):
        dolu.sales.quick_sale(bira)
    onceki_stok = dolu.products.get(bira)["current_stock"]
    onceki_satis = dolu.db.scalar("SELECT COUNT(*) FROM sales WHERE entry_type='SALE'")

    def patlayan(*args, **kwargs):
        raise OSError("disk hatası")

    monkeypatch.setattr("app.services.backup_service.shutil.copyfile", patlayan)

    with pytest.raises(YedekHatasi):
        dolu.backup.restore(yedek)

    assert dolu.db.is_open, "veritabanı yeniden açıldı"
    assert dolu.products.get(bira)["current_stock"] == onceki_stok
    assert dolu.db.scalar("SELECT COUNT(*) FROM sales WHERE entry_type='SALE'") == onceki_satis
    assert dolu.db.check_invariants(deep=True) == []


def test_geri_yukleme_sonrasi_calismaya_devam_edilir(dolu, bira):
    yedek = dolu.backup.create_manual()
    dolu.sales.quick_sale(bira)
    dolu.backup.restore(yedek)

    sonuc = dolu.sales.quick_sale(bira)
    assert sonuc.total_amount == 8000
    assert dolu.db.check_invariants(deep=True) == []


def test_geri_yukleme_ayarlari_da_dondurur(dolu):
    dolu.settings.set("duplicate_scan_ms", 120)
    yedek = dolu.backup.create_manual()
    dolu.settings.set("duplicate_scan_ms", 900)
    assert dolu.settings.duplicate_scan_ms() == 900

    dolu.backup.restore(yedek)
    assert dolu.settings.duplicate_scan_ms() == 120, (
        "ayarlar veritabanında tutulur, yedekle birlikte döner"
    )


def test_yedek_listesi_yeniden_eskiye(dolu, bira):
    ilk = dolu.backup.create_manual()
    dolu.sales.quick_sale(bira)
    ikinci = dolu.backup.create_manual()

    liste = dolu.backup.list_backups()
    yollar = [b.path for b in liste]
    assert ikinci in yollar and ilk in yollar
    assert liste == sorted(liste, key=lambda b: b.created_at, reverse=True)


def test_testler_gercek_belgeler_klasorune_dokunmaz(dolu, tmp_path):
    """TEKEL_DATA_DIR ayarlıysa Belgeler'e ASLA yazılmaz."""
    assert str(tmp_path) in str(dolu.backup.manual_dir())
    assert "Documents" not in str(dolu.backup.manual_dir())
