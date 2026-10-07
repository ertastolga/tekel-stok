"""V1.2 göç motoru güvenliği (M1b).

V1.2, sahadaki veritabanlarında İLK gerçek göçü çalıştıracak. Korunan sözler:

  * daha YENİ bir sürümün verisi açılmaz (ve dosya kilitli kalmaz),
  * göçten ÖNCE doğrulanmış bir yedek alınır; alınamazsa göç YAPILMAZ,
  * bekleyen TÜM sürümler TEK işlemde uygulanır; hata olursa dosya başlangıç
    sürümünde kalır, bağlantı kapanır, dosya yeniden adlandırılabilir,
  * göçten önce var olan yabancı anahtar ihlalleri açılışı engellemez; YENİ
    ihlaller engeller,
  * ``backup_to`` başarısız olursa diskte ``.tmp`` artığı kalmaz,
  * eski şemalı bir yedekten geri yükleme kopyayı günceller, seçilen dosya
    değişmez,
  * ``--surum-geri-donus`` veriyi açmadan / güncellemeden eski yedeği koyar.
"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
from collections import namedtuple
from pathlib import Path

import pytest

from app.core import schema as schema_mod
from app.core.db import Database, hedef_sema_surumu, open_database
from app.core.errors import (
    GocBasarisiz,
    GocOncesiYedekAlinamadi,
    VeritabaniHatasi,
    YedekHatasi,
    YedekOkunamadi,
    YeniSurumVeritabani,
)
from app.services.container import build_services


def _sha(yol: Path) -> str:
    return hashlib.sha256(Path(yol).read_bytes()).hexdigest()


def _ham_surum(yol: Path) -> int:
    """Şema sürümünü uygulama kodunu KULLANMADAN okur (göç tetiklemez)."""
    conn = sqlite3.connect(str(yol))
    try:
        return int(
            conn.execute(
                "SELECT value FROM schema_meta WHERE key='schema_version'"
            ).fetchone()[0]
        )
    finally:
        conn.close()


def _kilitsiz_mi(yol: Path) -> bool:
    """Windows'ta açık bir bağlantı dosyanın adının değiştirilmesini engeller."""
    gecici = yol.with_name(yol.name + ".tasindi")
    yol.rename(gecici)
    gecici.rename(yol)
    return True


def _sutunlar(yol: Path, tablo: str) -> set[str]:
    conn = sqlite3.connect(str(yol))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({tablo})")}
    finally:
        conn.close()


def _tablolar(yol: Path) -> set[str]:
    conn = sqlite3.connect(str(yol))
    try:
        return {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()


@pytest.fixture
def ek_goc(monkeypatch):
    """Güncel göç listesine sahte sürümler ekler (çağrı anında okunur)."""

    def _ekle(*adimlar_listesi):
        son = hedef_sema_surumu()
        yeni = [
            (son + i + 1, list(adimlar)) for i, adimlar in enumerate(adimlar_listesi)
        ]
        monkeypatch.setattr(schema_mod, "MIGRATIONS", [*schema_mod.MIGRATIONS, *yeni])
        monkeypatch.setattr(schema_mod, "SCHEMA_VERSION", yeni[-1][0])
        return [v for v, _ in yeni]

    return _ekle


@pytest.fixture
def guncel_db(db_file: Path) -> Path:
    """Güncel şemada, içinde bir ürün olan kapalı veritabanı."""
    svc = build_services(open_database(db_file))
    svc.products.quick_create("Tuborg Gold 50 cl", sale_price=8000, initial_stock=5,
                              purchase_cost=5000)
    svc.close()
    return db_file


# ===================== Sürüm tutarlılığı ===================================
def test_sema_surumu_sabiti_son_goce_esittir():
    assert schema_mod.SCHEMA_VERSION == schema_mod.MIGRATIONS[-1][0]
    assert hedef_sema_surumu() == schema_mod.SCHEMA_VERSION
    surumler = [v for v, _ in schema_mod.MIGRATIONS]
    assert surumler == list(range(1, len(surumler) + 1)), "sürümler 1'den ardışık"


def test_cekirdek_sema_surumunu_adla_ice_aktarmaz():
    """Testler göç listesini yamalayabilsin diye sürüm ÇAĞRI ANINDA okunur."""
    kok = Path(__file__).resolve().parent.parent
    for dosya in ("app/core/db.py", "app/services/backup_service.py"):
        metin = (kok / dosya).read_text(encoding="utf-8")
        assert "import SCHEMA_VERSION" not in metin, dosya


# ===================== Yeni sürüm koruması =================================
def test_daha_yeni_sema_acilmaz_ve_dosya_kilitli_kalmaz(guncel_db):
    conn = sqlite3.connect(str(guncel_db))
    conn.execute(
        "UPDATE schema_meta SET value = ? WHERE key='schema_version'",
        (str(hedef_sema_surumu() + 1),),
    )
    conn.commit()
    conn.close()
    once = _sha(guncel_db)

    db = Database(guncel_db)
    with pytest.raises(YeniSurumVeritabani) as bilgi:
        db.connect()
    assert "daha yeni" in bilgi.value.message
    assert "Ayarlar" not in bilgi.value.message
    assert not db.is_open
    assert _kilitsiz_mi(guncel_db)
    assert _sha(guncel_db) == once, "dosyaya dokunulmadı"
    assert not (guncel_db.parent / "backups").exists(), "yedek bile alınmadı"


# ===================== Güncelleme öncesi yedek =============================
def test_goc_oncesi_yedek_alinir_ve_dogrulanir(guncel_db, ek_goc):
    eski = hedef_sema_surumu()
    (hedef,) = ek_goc(["ALTER TABLE products ADD COLUMN raf_notu TEXT"])

    db = open_database(guncel_db)
    try:
        yedek = db.last_migration_backup
        assert yedek is not None and yedek.exists()
        assert yedek.parent == guncel_db.parent / "backups"
        assert yedek.name.startswith(f"guncelleme_oncesi_v{eski}_v{hedef}_")
        assert db.schema_version() == hedef
        svc = build_services(db)
        bilgi = svc.backup.inspect(yedek)
        assert bilgi.schema_version == eski, "yedek GÖÇTEN ÖNCEKİ hâl"
        assert bilgi.product_count == 1
        assert "raf_notu" not in _sutunlar(yedek, "products")
        assert not list(yedek.parent.glob("*.tmp"))
    finally:
        db.close()


def test_guncel_surumde_acilista_yedek_alinmaz(guncel_db):
    db = open_database(guncel_db)
    try:
        assert db.last_migration_backup is None
    finally:
        db.close()
    assert not (guncel_db.parent / "backups").exists()


def test_bos_yeni_veritabaninda_goc_oncesi_yedek_alinmaz(db_file):
    db = open_database(db_file)
    try:
        assert db.last_migration_backup is None
        assert db.schema_version() == hedef_sema_surumu()
    finally:
        db.close()


def test_ilk_yedek_klasoru_yazilamazsa_sonrakine_yazilir(guncel_db, ek_goc, tmp_path):
    engel = tmp_path / "dosya_klasor_degil"
    engel.write_text("bu bir dosya")              # altına klasör açılamaz
    yedek_yeri = tmp_path / "Belgeler" / "Tekel Stok Yedekleri"
    ek_goc(["ALTER TABLE products ADD COLUMN raf_notu TEXT"])

    db = open_database(guncel_db, pre_migration_backup_dirs=[engel / "alt", yedek_yeri])
    try:
        assert db.last_migration_backup is not None
        assert db.last_migration_backup.parent == yedek_yeri
    finally:
        db.close()


def test_yedek_alinamazsa_goc_yapilmaz(guncel_db, ek_goc, tmp_path):
    engel = tmp_path / "dosya_klasor_degil"
    engel.write_text("x")
    eski = hedef_sema_surumu()
    ek_goc(["ALTER TABLE products ADD COLUMN raf_notu TEXT"])
    once = _sha(guncel_db)

    db = Database(guncel_db, pre_migration_backup_dirs=[engel / "a", engel / "b"])
    with pytest.raises(GocOncesiYedekAlinamadi) as bilgi:
        db.connect()
    mesaj = bilgi.value.message
    assert "güncellenmedi" in mesaj and "değiştirilmedi" in mesaj
    assert "MB" in mesaj
    assert "Ayarlar" not in mesaj
    assert not db.is_open
    assert _kilitsiz_mi(guncel_db)
    assert _ham_surum(guncel_db) == eski
    assert "raf_notu" not in _sutunlar(guncel_db, "products")
    assert _sha(guncel_db) == once


def test_bos_alan_yetersizse_goc_yapilmaz(guncel_db, ek_goc, monkeypatch):
    import app.core.db as db_mod

    Kullanim = namedtuple("Kullanim", "total used free")
    monkeypatch.setattr(
        db_mod.shutil, "disk_usage", lambda yol: Kullanim(10**9, 10**9 - 1024, 1024)
    )
    eski = hedef_sema_surumu()
    ek_goc(["ALTER TABLE products ADD COLUMN raf_notu TEXT"])

    db = Database(guncel_db)
    with pytest.raises(GocOncesiYedekAlinamadi) as bilgi:
        db.connect()
    assert "boş alan" in bilgi.value.message
    assert "(şu an 0 MB)" in bilgi.value.message
    assert not db.is_open
    assert _ham_surum(guncel_db) == eski
    assert not list(guncel_db.parent.glob("backups/*.db"))


# ===================== Tek işlemde çok sürüm ===============================
def test_cok_surumlu_goc_tek_islemde_tamamen_geri_alinir(guncel_db, ek_goc):
    eski = hedef_sema_surumu()

    def patlayan(conn: sqlite3.Connection) -> None:
        raise sqlite3.OperationalError("son adımda hata")

    ek_goc(
        ["ALTER TABLE products ADD COLUMN raf_notu TEXT"],
        ["CREATE TABLE deneme_tablosu(id INTEGER PRIMARY KEY)"],
        ["ALTER TABLE products ADD COLUMN ucuncu TEXT", patlayan],
    )

    db = Database(guncel_db)
    with pytest.raises(GocBasarisiz) as bilgi:
        db.connect()
    assert isinstance(bilgi.value, VeritabaniHatasi)
    assert isinstance(bilgi.value.__cause__, sqlite3.OperationalError)
    assert bilgi.value.yedek_yolu is not None, "kullanıcıya yedeğin yeri söylenir"
    assert bilgi.value.yedek_yolu in bilgi.value.message
    assert "Ayarlar" not in bilgi.value.message
    assert not db.is_open
    assert _kilitsiz_mi(guncel_db)
    assert _ham_surum(guncel_db) == eski, "ara sürümler bile damgalanmadı"
    assert {"raf_notu", "ucuncu"}.isdisjoint(_sutunlar(guncel_db, "products"))
    assert "deneme_tablosu" not in _tablolar(guncel_db)

    # Hata giderildikten sonra (yeni sürümde) aynı dosya sorunsuz açılır.
    schema_mod.MIGRATIONS[-1] = (
        schema_mod.MIGRATIONS[-1][0], ["ALTER TABLE products ADD COLUMN ucuncu TEXT"]
    )
    yeniden = open_database(guncel_db)
    try:
        assert yeniden.schema_version() == eski + 3
        assert yeniden.check_invariants(deep=True) == []
    finally:
        yeniden.close()


def test_onceden_var_olan_yabanci_anahtar_ihlali_acilisi_engellemez(guncel_db, ek_goc):
    conn = sqlite3.connect(str(guncel_db))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO product_barcodes(product_id, barcode, barcode_norm, created_at_utc) "
        "VALUES(9999, 'ESKI', 'ESKI', 0)"
    )
    conn.commit()
    conn.close()
    (hedef,) = ek_goc(["ALTER TABLE products ADD COLUMN raf_notu TEXT"])

    db = open_database(guncel_db)
    try:
        assert db.schema_version() == hedef
        assert db.preexisting_fk_violations, "eski ihlal bildirildi"
        assert db.preexisting_fk_violations[0][0] == "product_barcodes"
    finally:
        db.close()


def test_gocun_yarattigi_yeni_ihlal_yine_durdurur(guncel_db, ek_goc):
    conn = sqlite3.connect(str(guncel_db))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute(
        "INSERT INTO product_barcodes(product_id, barcode, barcode_norm, created_at_utc) "
        "VALUES(9999, 'ESKI', 'ESKI', 0)"
    )
    conn.commit()
    conn.close()
    eski = hedef_sema_surumu()

    def bozan(c: sqlite3.Connection) -> None:
        c.execute(
            "INSERT INTO product_barcodes(product_id, barcode, barcode_norm, "
            "created_at_utc) VALUES(8888, 'YENI', 'YENI', 0)"
        )

    ek_goc([bozan])
    with pytest.raises(GocBasarisiz):
        open_database(guncel_db)
    assert _ham_surum(guncel_db) == eski
    assert _kilitsiz_mi(guncel_db)


# ===================== backup_to artığı ====================================
def test_backup_to_basarisiz_olursa_tmp_birakmaz(db, tmp_path, monkeypatch):
    hedef = tmp_path / "yedekler" / "deneme.db"

    def kilitli(self, *a, **k):
        raise PermissionError("hedef dosya kilitli")

    with monkeypatch.context() as m:
        m.setattr(Path, "replace", kilitli)
        with pytest.raises(PermissionError):
            db.backup_to(hedef)
    assert not hedef.exists()
    assert list(hedef.parent.iterdir()) == [], "yarım .tmp dosyası kalmadı"


# ===================== Eski yedekten geri yükleme ==========================
def test_eski_semali_yedek_geri_yuklenince_guncellenir_kaynak_degismez(
    services, bira, ek_goc
):
    eski = hedef_sema_surumu()
    yedek = services.backup.create_manual()
    kaynak_ozeti = _sha(yedek)
    (hedef,) = ek_goc(["ALTER TABLE products ADD COLUMN raf_notu TEXT"])

    services.backup.restore(yedek)

    assert services.db.schema_version() == hedef
    assert "raf_notu" in _sutunlar(Path(services.db.path), "products")
    assert _sha(yedek) == kaynak_ozeti, "kullanıcının seçtiği yedek değişmedi"
    goc_yedegi = services.db.last_migration_backup
    assert goc_yedegi is not None and goc_yedegi.exists()
    assert _ham_surum(goc_yedegi) == eski
    assert services.products.get(bira)["name"] == "Tuborg Gold 50 cl Kutu"
    assert services.db.check_invariants(deep=True) == []


# ===================== Örnek V1.0 / V1.1 verisi ============================
@pytest.mark.parametrize("fikstur", ["v1_0_kopya", "v1_1_kopya"])
def test_gercek_eski_surum_verisi_guncel_kodla_acilir(fikstur, request):
    yol: Path = request.getfixturevalue(fikstur)
    eski = _ham_surum(yol)
    db = open_database(yol)
    try:
        assert db.schema_version() == hedef_sema_surumu()
        assert db.integrity_check() == "ok"
        if hedef_sema_surumu() > eski:
            assert db.last_migration_backup is not None
            assert _ham_surum(db.last_migration_backup) == eski
        else:
            assert db.last_migration_backup is None
    finally:
        db.close()


# ===================== Sürüm geri dönüşü ===================================
def test_surum_geri_donus_eski_yedegi_acmadan_yerine_koyar(guncel_db, ek_goc, tmp_path):
    from app.services.geri_donus import GERI_DONUS_ONEKI, surum_geri_donus

    eski = hedef_sema_surumu()
    (hedef,) = ek_goc(["ALTER TABLE products ADD COLUMN raf_notu TEXT"])
    svc = build_services(open_database(guncel_db))
    goc_yedegi = svc.db.last_migration_backup
    svc.products.quick_create("Yükseltme sonrası ürün", sale_price=1000)
    svc.close()
    yedek_ozeti = _sha(goc_yedegi)

    klasor = tmp_path / "geri_donus_yedekleri"
    sonuc = surum_geri_donus(goc_yedegi, guncel_db, klasor)

    assert sonuc.yedek_semasi == eski
    assert _sha(guncel_db) == yedek_ozeti, "veri yedeğin BİREBİR kopyası (açılmadı)"
    assert _ham_surum(guncel_db) == eski, "güncellenmedi"
    assert _sha(goc_yedegi) == yedek_ozeti, "seçilen yedek değişmedi"
    for ek in ("-wal", "-shm"):
        assert not Path(str(guncel_db) + ek).exists()
    kopya = sonuc.onceki_veri_kopyasi
    assert kopya is not None and kopya.parent == klasor
    assert kopya.name.startswith(GERI_DONUS_ONEKI)
    assert _ham_surum(kopya) == hedef
    conn = sqlite3.connect(str(kopya))
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM products WHERE name = 'Yükseltme sonrası ürün'"
        ).fetchone()[0] == 1, "geri dönüş öncesi veri kaybolmadı"
    finally:
        conn.close()
    assert not list(klasor.glob("*.tmp"))


def test_surum_geri_donus_guncel_semali_yedegi_reddeder(guncel_db, tmp_path):
    from app.services.geri_donus import surum_geri_donus

    yedek = tmp_path / "guncel_yedek.db"
    shutil.copyfile(guncel_db, yedek)
    once = _sha(guncel_db)
    with pytest.raises(YedekHatasi) as bilgi:
        surum_geri_donus(yedek, guncel_db, tmp_path / "k")
    assert "değiştirilmedi" in bilgi.value.message
    assert _sha(guncel_db) == once
    assert not (tmp_path / "k").exists()


def test_surum_geri_donus_bozuk_dosyayi_reddeder(guncel_db, tmp_path):
    from app.services.geri_donus import surum_geri_donus

    bozuk = tmp_path / "bozuk.db"
    bozuk.write_bytes(b"bu bir veritabani degil" * 100)
    once = _sha(guncel_db)
    with pytest.raises(YedekOkunamadi):
        surum_geri_donus(bozuk, guncel_db, tmp_path / "k")
    assert _sha(guncel_db) == once


def test_salt_okunur_uri_ozel_karakterli_klasorde_calisir(db, tmp_path):
    klasor = tmp_path / "Yedek #1 %20 çğüş"
    hedef = db.backup_to(klasor / "deneme.db")
    svc = build_services(db)
    assert svc.backup.inspect(hedef).schema_version == hedef_sema_surumu()


# ===================== Açılış mesajları ====================================
def test_surum_geri_donus_bayragi_ayristirilir():
    from app.main import parse_args

    args = parse_args(["--surum-geri-donus", r"C:\yedek.db"])
    assert args.surum_geri_donus == r"C:\yedek.db"
    assert parse_args([]).surum_geri_donus is None


@pytest.mark.parametrize(
    "hata",
    [
        YeniSurumVeritabani(),
        GocOncesiYedekAlinamadi("yer yok"),
        GocBasarisiz("C:/yedek.db"),
        VeritabaniHatasi(),
    ],
    ids=["yeni", "yedek_yok", "goc", "genel"],
)
def test_acilis_hatasi_ulasilamayan_ayarlar_sayfasini_onermez(hata):
    from app import config
    from app.main import baslangic_hata_ayrintisi

    metin = baslangic_hata_ayrintisi(hata)
    assert "Ayarlar" not in metin and "Ayarlar" not in hata.message
    assert str(config.data_dir()) in metin
    assert str(config.log_file_path()) in metin
