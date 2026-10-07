"""Göç (migration) motoru ve mimari kurallar.

Uygulama yıllarca yaşayacak. Kullanıcıya ASLA "veritabanını silin" denmez;
her şema değişikliği bir göç olarak eklenir ve mevcut veri korunur.
"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.core import schema as schema_mod
from app.core.clock import now_utc
from app.core.db import Database, open_database
from app.core.schema import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parent.parent


# ===================== Göç motoru =======================================
def test_bos_dosyada_tum_gocler_uygulanir(db_file):
    assert not db_file.exists()
    db = Database(db_file).connect()
    try:
        assert db.schema_version() == SCHEMA_VERSION
        assert db.scalar("SELECT COUNT(*) FROM categories") == 20
    finally:
        db.close()


def test_goc_ikinci_acilista_tekrar_calismaz(db, reopen):
    yeni = reopen(db)
    try:
        assert yeni.migrate() == 0
    finally:
        yeni.close()


def test_yeni_goc_eski_veritabanini_yukseltir_ve_VERIYI_KORUR(
    db_file, monkeypatch
):
    """Güncel şemadaki veri, bir SONRAKİ göçten sonra OLDUĞU GİBİ durmalıdır.

    (V1.1'de bu test sabit "v2" kullanıyordu; V1.2 gerçek göçler eklediği için
    hedef artık ``SCHEMA_VERSION + 1``'dir — koruma aynı, ek olarak güncelleme
    öncesi yedek de doğrulanır.)
    """
    sonraki = SCHEMA_VERSION + 1
    db = open_database(db_file)
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO products(name, name_norm, sale_price, min_stock, "
            "  critical_stock, created_at_utc, updated_at_utc) "
            "VALUES('Tuborg Gold 50 cl', 'tuborg gold 50 cl', 8000, 6, 2, ?, ?)",
            (now_utc(), now_utc()),
        )
    urun_id = db.scalar("SELECT id FROM products")
    db.close()

    # Gelecekteki bir sürümü taklit et: hem SQL hem de veri dönüştüren adım.
    def v2_backfill(conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE products SET raf_notu = 'aktarildi'")

    monkeypatch.setattr(
        schema_mod, "MIGRATIONS",
        [
            *schema_mod.MIGRATIONS,
            (sonraki, ["ALTER TABLE products ADD COLUMN raf_notu TEXT", v2_backfill]),
        ],
    )
    monkeypatch.setattr(schema_mod, "SCHEMA_VERSION", sonraki)

    yeni = open_database(db_file)
    try:
        assert yeni.schema_version() == sonraki
        assert yeni.last_migration_backup is not None, "güncelleme öncesi yedek"
        satir = yeni.query_one("SELECT * FROM products WHERE id = ?", (urun_id,))
        assert satir["name"] == "Tuborg Gold 50 cl", "eski veri KORUNDU"
        assert satir["sale_price"] == 8000
        assert satir["raf_notu"] == "aktarildi", "geriye dönük doldurma çalıştı"
        assert yeni.check_invariants() == []
    finally:
        yeni.close()


def test_basarisiz_goc_semayi_yarim_birakmaz(db_file, monkeypatch):
    """Göç ortada patlarsa sürüm damgası ilerlemez; veritabanı tutarlı kalır.

    V1.2'de daha GÜÇLÜ: ham ``sqlite3`` hatası kullanıcıya sızmaz (sebep olarak
    zincirlenir), bağlantı kapanır ve dosya kilitli kalmaz.
    """
    from app.core.errors import VeritabaniHatasi

    open_database(db_file).close()

    def patlayan(conn: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("göç ortasında hata")

    monkeypatch.setattr(
        schema_mod, "MIGRATIONS",
        [
            *schema_mod.MIGRATIONS,
            (SCHEMA_VERSION + 1,
             ["ALTER TABLE products ADD COLUMN yeni_sutun TEXT", patlayan]),
        ],
    )

    acilan = Database(db_file)
    with pytest.raises(VeritabaniHatasi) as bilgi:
        acilan.connect()
    assert isinstance(bilgi.value.__cause__, sqlite3.OperationalError)
    assert not acilan.is_open, "bağlantı kapatıldı"
    tasinan = db_file.with_name("tasindi.db")
    db_file.rename(tasinan)                      # Windows: açık dosya taşınamaz
    tasinan.rename(db_file)

    db = Database(db_file)
    db._conn = sqlite3.connect(str(db_file))
    db._conn.row_factory = sqlite3.Row
    try:
        assert db.schema_version() == SCHEMA_VERSION, "sürüm damgası ilerlemedi"
        sutunlar = {
            satir["name"]
            for satir in db.query("PRAGMA table_info(products)")
        }
        assert "yeni_sutun" not in sutunlar, "yarım kalan değişiklik geri alındı"
    finally:
        db.close()


def test_yabanci_anahtar_denetimi_gocte_calisir(db_file, monkeypatch):
    """Bozuk bir dönüşüm sessizce işlenmemeli."""
    open_database(db_file).close()

    def bozan(conn: sqlite3.Connection) -> None:
        # Var olmayan ürüne bağlı barkod: yabancı anahtar ihlali.
        conn.execute(
            "INSERT INTO product_barcodes(product_id, barcode, barcode_norm, "
            "  created_at_utc) VALUES(9999, 'X', 'X', 0)"
        )

    monkeypatch.setattr(
        schema_mod, "MIGRATIONS",
        [*schema_mod.MIGRATIONS, (SCHEMA_VERSION + 1, [bozan])],
    )
    from app.core.errors import VeritabaniHatasi

    with pytest.raises(VeritabaniHatasi):
        open_database(db_file)


def test_yeni_ayar_anahtari_eski_veritabaninda_belirir(db, reopen, monkeypatch):
    """Sürümle gelen yeni ayar, mevcut veritabanlarında kendiliğinden oluşur."""
    monkeypatch.setitem(schema_mod.DEFAULT_SETTINGS, "yeni_ayar", "42")
    yeni = reopen(db)
    try:
        assert yeni.scalar(
            "SELECT value FROM settings WHERE key = 'yeni_ayar'"
        ) == "42"
    finally:
        yeni.close()


def test_mevcut_ayar_degeri_ezilmez(db, reopen):
    db.execute("UPDATE settings SET value = '999' WHERE key = 'duplicate_scan_ms'")
    yeni = reopen(db)
    try:
        assert yeni.scalar(
            "SELECT value FROM settings WHERE key = 'duplicate_scan_ms'"
        ) == "999"
    finally:
        yeni.close()


# ===================== Mimari kurallar ==================================
def test_cekirdek_ve_servisler_qt_icermez():
    """``app/core`` ve ``app/services`` PySide6 içe aktarmaz.

    Bu kural iş kurallarının başsız test edilebilir kalmasını sağlar; bozulursa
    servisler arayüze bağımlı hâle gelir ve testler yavaşlar.
    """
    import ast

    ihlaller = []
    for klasor in ("app/core", "app/services", "app/analytics"):
        for yol in (ROOT / klasor).rglob("*.py"):
            agac = ast.parse(yol.read_text(encoding="utf-8"), filename=str(yol))
            for dugum in ast.walk(agac):
                if isinstance(dugum, ast.Import):
                    adlar = [a.name for a in dugum.names]
                elif isinstance(dugum, ast.ImportFrom):
                    adlar = [dugum.module or ""]
                else:
                    continue
                if any(ad.startswith("PySide6") for ad in adlar):
                    ihlaller.append(f"{yol.relative_to(ROOT)}:{dugum.lineno}")
    assert ihlaller == [], f"Qt bağımlılığı sızmış: {ihlaller}"


def test_arayuz_is_kurali_sql_calistirmaz():
    """Sayfalar INSERT/UPDATE/DELETE yazmaz; her yazma servisten geçer.

    Okuma amaçlı SELECT'e izin verilir (liste doldurmak için), ama veri
    DEĞİŞTİREN SQL arayüzde bulunmamalıdır.
    """
    yasakli = ("INSERT INTO", "UPDATE ", "DELETE FROM")
    ihlaller = []
    for yol in (ROOT / "app/ui").rglob("*.py"):
        metin = yol.read_text(encoding="utf-8").upper()
        for kalip in yasakli:
            if kalip in metin:
                ihlaller.append(f"{yol.relative_to(ROOT)}: {kalip.strip()}")
    assert ihlaller == [], f"Arayüzde iş kuralı SQL'i: {ihlaller}"


def test_insert_or_replace_kullanilmaz():
    """``INSERT OR REPLACE`` proje genelinde YASAK.

    Çakışan satırı SİLER; ``ON DELETE CASCADE`` ile birlikte sessiz veri
    kaybına yol açar. Yerine ``ON CONFLICT ... DO UPDATE`` kullanılır.
    """
    ihlaller = []
    for yol in (ROOT / "app").rglob("*.py"):
        metin = yol.read_text(encoding="utf-8").upper()
        if "INSERT OR REPLACE" in metin:
            ihlaller.append(str(yol.relative_to(ROOT)))
    assert ihlaller == [], f"INSERT OR REPLACE bulundu: {ihlaller}"


def test_miktar_mantigi_merkezidir():
    """"adet" kelimesi miktar mantığında dağınık biçimde geçmemeli.

    Tek sahibi ``app/core/quantity.py``'dir; ileride tartılı ürün eklendiğinde
    değişecek yer orasıdır.
    """
    # ``schema.py`` muaftir: temel birimi TANIMLAYAN yer orasidir (CHECK + DEFAULT).
    muaf = {"quantity.py", "errors.py", "schema.py"}
    ihlaller = []
    for klasor in ("app/core", "app/services"):
        for yol in (ROOT / klasor).rglob("*.py"):
            if yol.name in muaf:
                continue
            for satir_no, satir in enumerate(
                yol.read_text(encoding="utf-8").splitlines(), start=1
            ):
                kod = satir.split("#")[0]
                # BUYUK harfli sabit aranir; kucuk harfli "adet" bir SQL takma
                # adi ya da Turkce metin olabilir ve kurali ihlal etmez.
                if '"ADET"' in kod or "'ADET'" in kod:
                    ihlaller.append(f"{yol.relative_to(ROOT)}:{satir_no}")
    assert ihlaller == [], (
        f"Temel birim sabiti koda gömülmüş; quantity.V1_BASE_UNIT kullanın: {ihlaller}"
    )


def test_kendi_kendini_sinama_gecer(tmp_path):
    """``--self-test`` donmuş kod yollarını da doğrular; burada kaynaktan."""
    rapor = tmp_path / "rapor.txt"
    sonuc = subprocess.run(
        [sys.executable, "-m", "app.main", "--self-test", str(rapor)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=180,
    )
    assert sonuc.returncode == 0, sonuc.stdout + sonuc.stderr
    assert rapor.exists()
    icerik = rapor.read_text(encoding="utf-8")
    assert "BASARISIZ" not in icerik, icerik
