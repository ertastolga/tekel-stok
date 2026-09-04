"""Test altyapısı.

Testler GERÇEK dosya tabanlı bir SQLite veritabanı kullanır (``:memory:``
DEĞİL), çünkü WAL davranışı, kapat-aç kalıcılığı ve yedekleme de sınanmaktadır.

``TEKEL_DATA_DIR`` her testte geçici bir klasöre yönlendirilir; böylece hiçbir
test kullanıcının gerçek verisine, log'una ya da Belgeler klasörüne dokunamaz.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.db import Database, open_database  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch):
    """Her test kendi veri klasöründe çalışır."""
    monkeypatch.setenv("TEKEL_DATA_DIR", str(tmp_path / "veri"))
    return tmp_path / "veri"


@pytest.fixture
def db_file(tmp_path: Path) -> Path:
    return tmp_path / "test_tekelstok.db"


@pytest.fixture
def db(db_file: Path):
    """Açık, göçleri uygulanmış bir veritabanı."""
    database = open_database(db_file)
    yield database
    if database.is_open:
        database.close()


@pytest.fixture
def reopen(db_file: Path):
    """Bağlantıyı tamamen kapatıp diskten yeniden açar (kalıcılık testleri)."""

    def _reopen(database: Database) -> Database:
        if database.is_open:
            database.close()
        return open_database(db_file)

    return _reopen


def qapp_available() -> bool:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


def set_offscreen() -> None:
    """Qt testleri için başsız platform eklentisi."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
