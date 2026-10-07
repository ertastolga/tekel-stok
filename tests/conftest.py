"""Test altyapısı.

Testler GERÇEK dosya tabanlı bir SQLite veritabanı kullanır (``:memory:``
DEĞİL), çünkü WAL davranışı, kapat-aç kalıcılığı ve yedekleme de sınanmaktadır.

``TEKEL_DATA_DIR`` her testte geçici bir klasöre yönlendirilir; böylece hiçbir
test kullanıcının gerçek verisine, log'una ya da Belgeler klasörüne dokunamaz.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core import clock  # noqa: E402
from app.core.db import Database, open_database  # noqa: E402
from app.services.container import Services, build_services  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch):
    """Her test kendi veri klasöründe çalışır."""
    monkeypatch.setenv("TEKEL_DATA_DIR", str(tmp_path / "veri"))
    return tmp_path / "veri"


@pytest.fixture(autouse=True)
def gercek_saate_don():
    """Hiçbir test sabitlenmiş bir saati sonraki teste sızdıramaz."""
    yield
    clock.reset_clock()


@pytest.fixture
def duvar_saati():
    """Sabit, ilerletilebilir saat; test boyunca TÜM servisler onu görür."""
    from fakes import SabitDuvarSaati

    saat = SabitDuvarSaati()
    with clock.use_clock(yerel=saat, tekduze=saat.tekduze):
        yield saat


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return tmp_path / "test_tekelstok.db"


@pytest.fixture(scope="session")
def _sablon_db(tmp_path_factory) -> Path:
    """Göçleri uygulanmış, tohumlanmış BOŞ veritabanı — oturumda bir kez.

    ``db`` ve ``services`` bunu kendi dosyalarına KOPYALAR: her testte v1
    şemasını ve tohumlamayı (fsync'li) yeniden çalıştırmak süiti yavaşlatır.
    Göç testleri ``db_file`` ile TAZE dosya kullanmaya devam eder.
    """
    yol = tmp_path_factory.mktemp("sablon") / "sablon.db"
    open_database(yol).close()
    for son_ek in ("-wal", "-shm"):
        assert not Path(str(yol) + son_ek).exists()
    return yol


def _sablondan(db_file: Path, sablon: Path) -> Path:
    if not db_file.exists():
        shutil.copyfile(sablon, db_file)
    return db_file


@pytest.fixture
def db(db_file: Path, _sablon_db: Path):
    """Açık, göçleri uygulanmış bir veritabanı."""
    database = open_database(_sablondan(db_file, _sablon_db))
    yield database
    if database.is_open:
        database.close()


@pytest.fixture
def services(db_file: Path, _sablon_db: Path):
    """Tam servis kabı, kendi geçici veritabanıyla."""
    svc = build_services(open_database(_sablondan(db_file, _sablon_db)))
    yield svc
    svc.close()


FIXTURES = ROOT / "tests" / "fixtures"

#: ``-m perf`` veri şablonlarının önbelleği (sentetik veri; anahtar üretici
#: kaynağını, parametreleri ve şema sürümünü içerir — değişince yeniden üretilir).
PERF_ONBELLEK = Path(tempfile.gettempdir()) / "tekelstok_perf_onbellek"


@pytest.fixture(scope="session")
def perf_sablonu():
    """Hazır büyük veri şablonunun (``10k`` / ``100k``) SALT OKUNUR yolunu döner.

    Testler şablonu değiştirmemelidir; değiştirecekse ``perf_kopya`` kullanır.
    """
    from app.tools import perf_dataset

    def _sablon(ad: str) -> Path:
        parametreler = perf_dataset.HAZIR[ad]
        yol = PERF_ONBELLEK / f"{ad}_{parametreler.anahtar()}.db"
        if not yol.exists():
            gecici = PERF_ONBELLEK / f"{ad}_{parametreler.anahtar()}.uretiliyor.db"
            for artik in (gecici, Path(str(gecici) + ".meta.json")):
                artik.unlink(missing_ok=True)
            with pytest.MonkeyPatch.context() as mp:
                mp.setenv("TEKEL_DATA_DIR", str(PERF_ONBELLEK))
                perf_dataset.uret(parametreler, gecici)
            Path(str(gecici) + ".meta.json").replace(Path(str(yol) + ".meta.json"))
            gecici.replace(yol)
        return yol

    return _sablon


@pytest.fixture
def perf_kopya(perf_sablonu, tmp_path):
    """Şablonun bu teste ait, değiştirilebilir KOPYASI."""

    def _kopya(ad: str) -> Path:
        hedef = tmp_path / f"perf_{ad}.db"
        shutil.copyfile(perf_sablonu(ad), hedef)
        return hedef

    return _kopya


@pytest.fixture
def v1_1_kopya(tmp_path: Path) -> Path:
    """Gerçek V1.1 örnek veritabanının KOPYASI (örnek dosya asla yerinde açılmaz)."""
    hedef = tmp_path / "v1_1_kopya.db"
    shutil.copyfile(FIXTURES / "v1_1_ornek.db", hedef)
    return hedef


@pytest.fixture
def v1_0_kopya(tmp_path: Path) -> Path:
    """Gerçek V1.0 örnek veritabanının KOPYASI."""
    hedef = tmp_path / "v1_0_kopya.db"
    shutil.copyfile(FIXTURES / "v1_0_ornek.db", hedef)
    return hedef


@pytest.fixture
def reopen(db_file: Path):
    """Bağlantıyı tamamen kapatıp diskten yeniden açar (kalıcılık testleri)."""

    def _reopen(target: Database | Services):
        if isinstance(target, Services):
            target.close()
            return build_services(open_database(db_file))
        if target.is_open:
            target.close()
        return open_database(db_file)

    return _reopen


# --- Ortak test verisi ----------------------------------------------------
BIRA_BARKOD = "8690504001492"        # geçerli EAN-13 (kontrol hanesi doğru)
KOLI_BARKOD = "8690504001508"        # geçerli EAN-13


@pytest.fixture
def cips_urunu(services):
    """Ruffles — ikinci bir ürün gerektiren senaryolar için."""
    return services.products.quick_create(
        name="Ruffles Original 105 g",
        sale_price=5000,
        initial_stock=0,
        location_id=6,                # Cips Standı
    )


@pytest.fixture
def bira(services):
    """Tuborg Gold 50 cl — tekli barkod, 80 TL, sayılmış 0 stok."""
    pid = services.products.quick_create(
        name="Tuborg Gold 50 cl Kutu",
        sale_price=8000,
        barcode=BIRA_BARKOD,
        initial_stock=0,
        brand_name="Tuborg",
        location_id=1,                # Bira Dolabı
    )
    return pid


def qapp_available() -> bool:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


def set_offscreen() -> None:
    """Qt testleri için başsız platform eklentisi."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
