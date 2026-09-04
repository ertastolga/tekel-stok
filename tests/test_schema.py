"""Şema, göç ve kalıcılık davranışı.

Korunan değişmezler: göç bir kez uygulanır, yeniden açmak veriyi bozmaz,
üretilmiş ``stock_state`` sütunu doğru sıralar, kısmi tekil indeksler
gerçekten kısıtlar.
"""
from __future__ import annotations

import sqlite3

import pytest

from app.core.clock import now_utc
from app.core.schema import SCHEMA_VERSION


def _urun(db, ad="Test Ürün", **alanlar) -> int:
    now = now_utc()
    veri = {
        "name": ad,
        "name_norm": ad.lower(),
        "min_stock": 6,
        "critical_stock": 2,
        "created_at_utc": now,
        "updated_at_utc": now,
    }
    veri.update(alanlar)
    sutunlar = ", ".join(veri)
    yer = ", ".join("?" * len(veri))
    with db.transaction() as conn:
        cur = conn.execute(
            f"INSERT INTO products({sutunlar}) VALUES({yer})", list(veri.values())
        )
        return cur.lastrowid


# --- Göç -------------------------------------------------------------------
def test_gocler_uygulandi(db):
    assert db.schema_version() == SCHEMA_VERSION


def test_goc_ikinci_kez_calismaz(db):
    assert db.migrate() == 0, "Bekleyen göç kalmamalı"


def test_baslangic_verisi_yuklendi(db):
    # 5 üst kategori + 15 alt kategori
    assert db.scalar("SELECT COUNT(*) FROM categories") == 20
    assert db.scalar("SELECT COUNT(*) FROM categories WHERE parent_id IS NULL") == 5
    assert db.scalar("SELECT COUNT(*) FROM locations") == 8
    assert db.scalar("SELECT COUNT(*) FROM business_day_rules") == 1
    assert db.scalar("SELECT start_hour FROM business_day_rules") == 0
    bira = db.query_one("SELECT * FROM categories WHERE name = 'Bira'")
    assert bira is not None and bira["parent_id"] is not None


def test_pragmalar(db):
    assert str(db.scalar("PRAGMA journal_mode")).lower() == "wal"
    assert db.scalar("PRAGMA foreign_keys") == 1


def test_kapat_ac_veriyi_korur(db, reopen):
    _urun(db, "Tuborg Gold 50 cl")
    yeni = reopen(db)
    try:
        assert yeni.scalar("SELECT COUNT(*) FROM products") == 1
        assert yeni.scalar("SELECT name FROM products") == "Tuborg Gold 50 cl"
        assert yeni.schema_version() == SCHEMA_VERSION
    finally:
        yeni.close()


def test_turkce_karakterler_korunur(db, reopen):
    ad = "Çaykur Rize Çayı 1 kg — ıspanaklı şöğüş ĞÜİÖŞ"
    _urun(db, ad)
    yeni = reopen(db)
    try:
        assert yeni.scalar("SELECT name FROM products") == ad
    finally:
        yeni.close()


# --- Üretilmiş stock_state sütunu -----------------------------------------
def test_sayilmamis_urun_kritik_gostermez(db):
    """Bilinmeyen stok, AZ stok değildir: 'Henüz Sayılmadı' (4) gösterilir."""
    pid = _urun(db, "Yeni Ürün")           # stock_initialized_at_utc = NULL
    assert db.scalar("SELECT current_stock FROM products WHERE id=?", (pid,)) == 0
    assert db.scalar("SELECT stock_state FROM products WHERE id=?", (pid,)) == 4


def test_sayilmis_sifir_stok_kritiktir(db):
    pid = _urun(db, "Sayılmış Ürün", stock_initialized_at_utc=now_utc())
    assert db.scalar("SELECT stock_state FROM products WHERE id=?", (pid,)) == 2


@pytest.mark.parametrize(
    "stok, beklenen",
    [(-1, 3), (0, 2), (2, 2), (3, 1), (6, 1), (7, 0)],
)
def test_stock_state_siralamasi(db, stok, beklenen):
    pid = _urun(db, f"Ürün {stok}", stock_initialized_at_utc=now_utc())
    with db.transaction() as conn:
        conn.execute("UPDATE products SET current_stock=? WHERE id=?", (stok, pid))
    assert db.scalar("SELECT stock_state FROM products WHERE id=?", (pid,)) == beklenen


def test_negatif_stok_sayilmamis_urunde_bile_gorunur(db):
    """Sayılmamış olsa da negatif stok gerçek bir uyarıdır (3), gizlenmez."""
    pid = _urun(db, "Eksiye Düşen")
    with db.transaction() as conn:
        conn.execute("UPDATE products SET current_stock=-4 WHERE id=?", (pid,))
    assert db.scalar("SELECT stock_state FROM products WHERE id=?", (pid,)) == 3


# --- Kısıtlar ve kısmi tekil indeksler ------------------------------------
def test_ayni_barkod_iki_urune_verilemez(db):
    a = _urun(db, "A")
    b = _urun(db, "B")
    now = now_utc()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO product_barcodes(product_id, barcode, barcode_norm, created_at_utc) "
            "VALUES(?,?,?,?)",
            (a, "8690000000001", "8690000000001", now),
        )
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO product_barcodes(product_id, barcode, barcode_norm, created_at_utc) "
                "VALUES(?,?,?,?)",
                (b, "8690000000001", "8690000000001", now),
            )


def test_pasif_barkod_ayni_degeri_engellemez(db):
    """Eski barkod pasife alınırsa aynı değer yeni bir ürüne verilebilir."""
    a = _urun(db, "A")
    b = _urun(db, "B")
    now = now_utc()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO product_barcodes(product_id, barcode, barcode_norm, active, "
            "created_at_utc) VALUES(?,?,?,0,?)",
            (a, "8690000000001", "8690000000001", now),
        )
        conn.execute(
            "INSERT INTO product_barcodes(product_id, barcode, barcode_norm, active, "
            "created_at_utc) VALUES(?,?,?,1,?)",
            (b, "8690000000001", "8690000000001", now),
        )
    assert db.scalar("SELECT COUNT(*) FROM product_barcodes") == 2


def test_tek_esas_raf(db):
    pid = _urun(db, "A")
    now = now_utc()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO product_locations(product_id, location_id, is_primary, active_from_utc) "
            "VALUES(?,1,1,?)",
            (pid, now),
        )
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO product_locations(product_id, location_id, is_primary, "
                "active_from_utc) VALUES(?,2,1,?)",
                (pid, now),
            )


def test_esas_raf_olmadan_birden_cok_konum_olabilir(db):
    pid = _urun(db, "A")
    now = now_utc()
    with db.transaction() as conn:
        for loc in (1, 2, 8):
            conn.execute(
                "INSERT INTO product_locations(product_id, location_id, is_primary, "
                "active_from_utc) VALUES(?,?,0,?)",
                (pid, loc, now),
            )
    assert db.scalar(
        "SELECT COUNT(*) FROM product_locations WHERE product_id=? AND active=1", (pid,)
    ) == 3


def test_tek_taslak_sayim(db):
    now = now_utc()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO count_sessions(status, scope, created_at_utc) VALUES('DRAFT','ALL',?)",
            (now,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO count_sessions(status, scope, created_at_utc) "
                "VALUES('DRAFT','ALL',?)",
                (now,),
            )


def test_negatif_stok_degeri_reddedilir(db):
    pid = _urun(db, "A")
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute("UPDATE products SET stock_value = -1 WHERE id = ?", (pid,))


def test_satis_geri_alma_isaret_kisiti(db):
    """Geri alma satırı NEGATİF tutar taşımalıdır."""
    with db.transaction() as conn:
        cur = conn.execute(
            "INSERT INTO sales(entry_type, sale_mode, created_at_utc, local_date, "
            "local_hour, local_dow, business_date, total_amount, item_count) "
            "VALUES('SALE','HIZLI',?, '2026-09-05', 20, 5, '2026-09-05', 8000, 1)",
            (now_utc(),),
        )
        satis_id = cur.lastrowid

    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO sales(entry_type, sale_mode, created_at_utc, local_date, "
                "local_hour, local_dow, business_date, total_amount, item_count, "
                "reverses_sale_id) "
                "VALUES('SALE_REVERSAL','HIZLI',?, '2026-09-05', 20, 5, '2026-09-05', "
                "8000, 1, ?)",
                (now_utc(), satis_id),
            )


def test_ayni_satis_iki_kez_geri_alinamaz(db):
    """Garanti KOD'da değil, veritabanı indeksindedir."""
    with db.transaction() as conn:
        cur = conn.execute(
            "INSERT INTO sales(entry_type, sale_mode, created_at_utc, local_date, "
            "local_hour, local_dow, business_date, total_amount, item_count) "
            "VALUES('SALE','HIZLI',?, '2026-09-05', 20, 5, '2026-09-05', 8000, 1)",
            (now_utc(),),
        )
        satis_id = cur.lastrowid

    def geri_al():
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO sales(entry_type, sale_mode, created_at_utc, local_date, "
                "local_hour, local_dow, business_date, total_amount, item_count, "
                "reverses_sale_id) "
                "VALUES('SALE_REVERSAL','HIZLI',?, '2026-09-05', 20, 5, '2026-09-05', "
                "-8000, -1, ?)",
                (now_utc(), satis_id),
            )

    geri_al()
    with pytest.raises(sqlite3.IntegrityError):
        geri_al()


def test_transfer_hareket_turu_yok(db):
    """V1'de stok ürün düzeyindedir; TRANSFER anlamsız olurdu."""
    pid = _urun(db, "A")
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO stock_movements(product_id, movement_type, quantity_delta, "
                "balance_after, created_at_utc, business_date) "
                "VALUES(?, 'TRANSFER', 1, 1, ?, '2026-09-05')",
                (pid, now_utc()),
            )


# --- İşlem atomikliği ------------------------------------------------------
def test_hata_durumunda_tam_geri_alma(db):
    _urun(db, "Önce")
    onceki = db.scalar("SELECT COUNT(*) FROM products")

    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO products(name, name_norm, created_at_utc, updated_at_utc) "
                "VALUES('Yarım','yarim',?,?)",
                (now_utc(), now_utc()),
            )
            raise RuntimeError("iş kuralı patladı")

    assert db.scalar("SELECT COUNT(*) FROM products") == onceki


def test_ic_ice_islem_tek_commit(db):
    with db.transaction() as dis:
        dis.execute(
            "INSERT INTO products(name, name_norm, created_at_utc, updated_at_utc) "
            "VALUES('Dış','dis',?,?)",
            (now_utc(), now_utc()),
        )
        with db.transaction() as ic:
            ic.execute(
                "INSERT INTO products(name, name_norm, created_at_utc, updated_at_utc) "
                "VALUES('İç','ic',?,?)",
                (now_utc(), now_utc()),
            )
    assert db.scalar("SELECT COUNT(*) FROM products") == 2


def test_ic_islem_hatasi_dis_islemi_de_geri_alir(db):
    with pytest.raises(RuntimeError):
        with db.transaction() as dis:
            dis.execute(
                "INSERT INTO products(name, name_norm, created_at_utc, updated_at_utc) "
                "VALUES('Dış','dis',?,?)",
                (now_utc(), now_utc()),
            )
            with db.transaction():
                raise RuntimeError("iç hata")
    assert db.scalar("SELECT COUNT(*) FROM products") == 0


# --- Denetim ---------------------------------------------------------------
def test_temiz_veritabani_tutarlidir(db):
    assert db.check_invariants(deep=True) == []


def test_bozuk_onbellek_yakalanir_ve_onarilir(db):
    pid = _urun(db, "A", stock_initialized_at_utc=now_utc())
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO stock_movements(product_id, movement_type, quantity_delta, "
            "value_delta, unit_cost, balance_after, ref_type, created_at_utc, business_date) "
            "VALUES(?, 'INITIAL_STOCK', 10, 50000, 5000, 10, 'INITIAL', ?, '2026-09-05')",
            (pid, now_utc()),
        )
        conn.execute("UPDATE products SET current_stock=99 WHERE id=?", (pid,))

    sorunlar = db.check_invariants()
    assert any(s.startswith("I1:") for s in sorunlar)

    db.recompute_caches()
    assert db.scalar("SELECT current_stock FROM products WHERE id=?", (pid,)) == 10
    assert db.scalar("SELECT stock_value FROM products WHERE id=?", (pid,)) == 50000
    assert [s for s in db.check_invariants() if s.startswith(("I1:", "I2:"))] == []


def test_yedek_alinabilir_ve_okunabilir(db, tmp_path):
    _urun(db, "Tuborg Gold 50 cl")
    hedef = tmp_path / "yedek.db"
    db.backup_to(hedef)

    assert hedef.exists() and hedef.stat().st_size > 0
    kopya = sqlite3.connect(f"file:{hedef}?mode=ro", uri=True)
    try:
        assert kopya.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert kopya.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 1
    finally:
        kopya.close()


def test_yedek_calisir_veritabaninda_alinabilir(db, tmp_path):
    """Yedek, veritabanı açık ve yazılabilir durumdayken alınabilmelidir."""
    _urun(db, "A")
    db.backup_to(tmp_path / "y1.db")
    _urun(db, "B")          # yedekten sonra yazmaya devam
    assert db.scalar("SELECT COUNT(*) FROM products") == 2
