"""Yedek motoru (V1.2 M10a, plan §5.11, D-11).

Korunan sözler:
  * yedek türü dosya adından KESİN tanınır; tanınmayan .db listelenmez ve
    ASLA silinmez (V1.1 klasördeki her .db'yi listeliyordu),
  * yönetilen adlar kuruluma özgüdür; yalnızca bu kurulumun yazdığı ve
    listede (ad + boyut) kayıtlı dosyalar silinir; V1.1'in kimliksiz
    otomatik dosyaları yalnızca varsayılan klasörde bizimdir,
  * sıralama ADDAKİ zamana göredir; gelecekte görünen ada dokunulmaz; en yeni
    N asla silinmez, N'den az varken hiçbir şey silinmez,
  * günlük yedek: iş günü başına en çok bir kuşak, veri değişmediyse yok,
    en yeni N gün saklanır; içe aktarma öncesi yedeklerden en yeni 10'u kalır;
    diğer güvenlik yedekleri asla silinmez,
  * yarım kalmış .db.tmp artıkları temizlenir (V1.1 hiç silmiyordu),
  * açık işlem varken yedek alınmaz; disk alanı önceden denetlenir; hata
    kaydedilir; otomatik yedek klasörü kullanılamıyorsa varsayılana dönülür.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import config
from app.core.errors import YedekHatasi
from app.services import backup_service as bs
from app.services.import_service import ICE_AKTARMA_YEDEK_ONEKI


@pytest.fixture
def yedek(services, bira):
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)
    return services.backup


def _degistir(services, bira):
    services.sales.quick_sale(bira)


def _bos_db(yol: Path) -> Path:
    yol.parent.mkdir(parents=True, exist_ok=True)
    yol.write_bytes(b"SQLite format 3\x00" + b"\x00" * 100)
    return yol


# ===================== Tür tanıma ==========================================
@pytest.mark.parametrize("ad,tur", [
    ("otomatik_20261005_101500.db", bs.OTOMATIK),
    ("otomatik_1a2b3c4d_20261005_101500_2.db", bs.OTOMATIK),
    ("gunluk_1a2b3c4d_2026-10-05.db", bs.GUNLUK),
    ("guncelleme_oncesi_v1_v5_20261005_101500.db", bs.GUNCELLEME_ONCESI),
    ("ice_aktarma_oncesi_20261005_101500.db", bs.ICE_AKTARMA_ONCESI),
    ("pin_sifirlama_oncesi_20261005_101500.db", bs.PIN_SIFIRLAMA_ONCESI),
    ("geri_yukleme_oncesi_20261005_101500.db", bs.GERI_YUKLEME_ONCESI),
    ("geri_donus_oncesi_20261005_101500.db", bs.GERI_DONUS_ONCESI),
    ("yedek_20261005_101500.db", bs.ELLE),
])
def test_tur_adlardan_kesin_taninir(ad, tur):
    assert bs.yedek_turu(ad)[0] == tur


@pytest.mark.parametrize("ad", ["tekelstok.db", "otomatik_kopya.db", "yedek_eski.db",
                                "gunluk_2026-10-05.db", "otomatik_20261005_101500.db.tmp"])
def test_taninmayan_ad(ad):
    assert bs.yedek_turu(ad) is None


def test_taninmayan_db_listelenmez(yedek):
    """V1.1 kanıtı (D-11): yedek klasöründeki HER .db listeleniyordu."""
    yedek.create_auto()
    yabanci = _bos_db(yedek.auto_dir() / "tekelstok_kopyasi.db")
    yollar = [b.path for b in yedek.list_backups()]
    assert yabanci not in yollar
    assert all(b.kind in bs.TUR_ADLARI for b in yedek.list_backups())


# ===================== Kurulum kimliği ve liste ============================
def test_kurulum_kimligi_ve_manifest(yedek):
    kimlik = yedek.install_id()
    assert len(kimlik) == 8 and yedek.install_id() == kimlik
    yol = yedek.create_auto()
    assert yol.name.startswith(f"otomatik_{kimlik}_")
    liste = yedek._manifest_oku(yol.parent)
    assert liste == {yol.name: yol.stat().st_size}


def test_saklama_yalnizca_bizim_ve_kayitli_dosyalari_siler(yedek, services, bira):
    services.settings.set("auto_backup_retention", 2)
    klasor = yedek.auto_dir()
    baska = _bos_db(klasor / "otomatik_ffffffff_20200101_000000.db")     # başka kurulum
    yabanci = _bos_db(klasor / "notlar.db")
    eski_v11 = _bos_db(klasor / "otomatik_20200101_000000.db")           # V1.1, bizim
    uretilen = []
    for _ in range(3):
        _degistir(services, bira)
        uretilen.append(yedek.create_auto())
    # Kayıtlı ama boyutu değişmiş (elle kurcalanmış) dosya silinmez.
    with open(uretilen[0], "ab") as dosya:
        dosya.write(b"x")
    _degistir(services, bira)
    uretilen.append(yedek.create_auto())
    assert baska.exists() and yabanci.exists(), "başkasının dosyasına dokunulmaz"
    assert not eski_v11.exists(), "varsayılan klasördeki V1.1 dosyası sıralamaya girer"
    assert uretilen[0].exists(), "boyutu tutmayan kayıt silinmez"
    assert [y.exists() for y in uretilen[1:]] == [False, True, True]


def test_siralama_addaki_zamana_gore_ve_gelecek_ad_korunur(yedek, services):
    services.settings.set("auto_backup_retention", 2)
    klasor = yedek.auto_dir()
    kimlik = yedek.install_id()
    adlar = {
        "eski": f"otomatik_{kimlik}_20200101_000000.db",
        "orta": f"otomatik_{kimlik}_20210101_000000.db",
        "yeni": f"otomatik_{kimlik}_20220101_000000.db",
        "gelecek": f"otomatik_{kimlik}_{(datetime.now() + timedelta(days=30)):%Y%m%d_%H%M%S}.db",
    }
    for i, ad in enumerate(adlar.values()):
        yol = _bos_db(klasor / ad)
        os.utime(yol, (time.time() - i * 1000, time.time() - i * 1000))  # ters mtime
        yedek._manifest_ekle(yol)
    yedek.cleanup_auto_backups()
    assert not (klasor / adlar["eski"]).exists()
    assert (klasor / adlar["orta"]).exists() and (klasor / adlar["yeni"]).exists()
    assert (klasor / adlar["gelecek"]).exists(), "gelecekte görünen ada dokunulmaz"


def test_n_den_az_varken_silinmez(yedek, services, bira):
    services.settings.set("auto_backup_retention", 5)
    for _ in range(3):
        _degistir(services, bira)
        yedek.create_auto()
    assert len([b for b in yedek.list_backups() if b.is_auto]) == 3


# ===================== Günlük yedek ========================================
def test_gunluk_yedek_gun_basina_bir_kusak(duvar_saati, services, bira):
    yedek = services.backup
    duvar_saati.git(2026, 10, 5, 12)
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)
    yol = yedek.create_daily()
    assert yol.name == f"gunluk_{yedek.install_id()}_2026-10-05.db"
    assert yedek.create_daily() is None, "aynı güne ikinci kuşak yok"
    duvar_saati.git(2026, 10, 6, 12)
    assert yedek.daily_backup_required() is False, "veri değişmedi: yeni gün yedeği yok"
    _degistir(services, bira)
    assert yedek.create_daily().name.endswith("2026-10-06.db")
    _degistir(services, bira)
    assert yedek.create_daily() is None, "veri değişse de aynı güne ikinci kuşak yok"
    duvar_saati.git(2026, 10, 7, 12)
    assert yedek.daily_backup_required(), "dünkü yedekten sonra değişti"
    assert [b.kind for b in yedek.list_backups()].count(bs.GUNLUK) == 2


def test_gunluk_saklama(duvar_saati, services, bira):
    yedek = services.backup
    services.settings.set("daily_backup_retention_days", 7)
    for gun in range(1, 11):
        duvar_saati.git(2026, 10, gun, 12)
        _degistir(services, bira)
        yedek.create_daily()
    gunler = sorted(b.path.name[-13:-3] for b in yedek.list_backups() if b.kind == bs.GUNLUK)
    assert gunler == [f"2026-10-{g:02d}" for g in range(4, 11)]


def test_ice_aktarma_oncesi_en_yeni_10_kalir(yedek):
    for _ in range(12):
        yedek.create_safety_backup(ICE_AKTARMA_YEDEK_ONEKI)
    pin = yedek.create_safety_backup(config.PRE_PIN_RESET_PREFIX)
    turler = [b.kind for b in yedek.list_backups()]
    assert turler.count(bs.ICE_AKTARMA_ONCESI) == 10
    assert pin.exists()


# ===================== Güvenlik ===========================================
def test_yetim_gecici_dosya_temizlenir(yedek):
    """V1.1 kanıtı (D-11): yarım kalmış .db.tmp hiç silinmiyordu."""
    klasor = yedek.auto_dir()
    eski = _bos_db(klasor / "otomatik_20200101_000000.db.tmp")
    os.utime(eski, (time.time() - 3600, time.time() - 3600))
    taze = _bos_db(klasor / "otomatik_20200101_000001.db.tmp")
    yedek.cleanup_auto_backups()
    assert not eski.exists() and taze.exists(), "yazılmakta olabilecek dosyaya dokunulmaz"


def test_islem_surerken_yedek_alinmaz(yedek, services, bira):
    with services.db.transaction():
        with pytest.raises(YedekHatasi):
            yedek.create_manual()
        _degistir(services, bira)
        assert yedek.maybe_auto_backup() is None
        assert yedek.create_daily() is None


def test_veri_surumu_uretilen_dosyadan_damgalanir(yedek, services, bira):
    _degistir(services, bira)
    yol = yedek.create_manual()
    assert services.settings.get_int("last_backup_data_version") == \
        yedek._dosya_veri_surumu(yol) == services.db.data_version()


def test_disk_alani_onceden_denetlenir(yedek, monkeypatch):
    monkeypatch.setattr(bs.shutil, "disk_usage",
                        lambda yol: type("D", (), {"free": 10 * 2**20})())
    with pytest.raises(YedekHatasi, match="MB gerekli"):
        yedek.create_manual()
    zaman, mesaj = yedek.last_error()
    assert zaman and "yeterli yer yok" in mesaj


def test_otomatik_yedek_klasoru_ve_yedege_donus(yedek, services, bira, tmp_path):
    ozel = tmp_path / "ozel_yedekler"
    services.settings.set("auto_backup_dir", str(ozel))
    assert yedek.auto_dir() == ozel
    assert yedek.create_auto().parent == ozel
    engel = tmp_path / "dosya"
    engel.write_text("klasör değil")
    services.settings.set("auto_backup_dir", str(engel / "alt"))
    _degistir(services, bira)
    assert yedek.create_auto().parent == yedek.default_auto_dir(), "varsayılana dönüş"
    assert "kullanılamadı" in yedek.last_error()[1]
    assert yedek.auto_dir_problem(config.data_dir())
    assert yedek.auto_dir_problem(config.data_dir().parent), "veri klasörünü içeren"
    assert yedek.auto_dir_problem(yedek.manual_dir())


def test_durum_ozeti(yedek, services, bira):
    yedek.create_auto()
    yedek.create_manual()
    durum = yedek.status()
    assert durum["otomatik_sayisi"] == 1 and durum["elle_sayisi"] == 1
    assert durum["toplam_boyut"] > 0 and durum["bos_alan_veri"] and durum["bos_alan_yedek"]
    assert durum["son_hata"] is None
