"""Kendi kendini sinama: arayuz acmadan, gercek kod yollari uzerinden.

Paketleme dogrulamasi icin vardir. "PyInstaller hata vermedi" yeterli bir
kanit DEGILDIR; derlenmis exe gercekten calisip veri yazabilmelidir.

Gecici bir veri klasoru kullanir: kullanicinin gercek verisine ASLA dokunmaz.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


def run_self_test(report_path: str | None = None) -> int:
    satirlar: list[str] = []

    def yaz(metin: str) -> None:
        satirlar.append(metin)
        print(metin)

    gecici = tempfile.mkdtemp(prefix="tekelstok_selftest_")
    os.environ["TEKEL_DATA_DIR"] = gecici

    from app import config
    from app.core.logging_setup import setup_logging

    # Log altyapisi burada da kurulur: "yazilabiliyor mu?" kontrolu ancak
    # gercekten yazmayi deneyerek anlamli olur.
    setup_logging()

    yaz(f"Surum: {config.APP_VERSION}")
    yaz(f"Donmus (frozen): {config.is_frozen()}")
    yaz(f"Veri klasoru: {config.data_dir()}")
    yaz(f"Python: {sys.version.split()[0]}")

    basarisiz = 0

    def kontrol(ad: str, kosul: bool, ayrinti: str = "") -> None:
        nonlocal basarisiz
        durum = "BASARILI" if kosul else "BASARISIZ"
        if not kosul:
            basarisiz += 1
        yaz(f"[{durum}] {ad}" + (f" - {ayrinti}" if ayrinti else ""))

    if config.is_frozen():
        kontrol(
            "Veri klasoru uygulama klasorunun disinda",
            not str(config.data_dir()).startswith(str(config.app_base_dir())),
            str(config.data_dir()),
        )

    try:
        from app.services.container import create_services

        services = create_services()
    except Exception as hata:
        kontrol("Veritabani acildi", False, str(hata))
        _write_report(report_path, satirlar)
        return 1

    try:
        kontrol("Sema surumu", services.db.schema_version() >= 1)
        kontrol(
            "Baslangic kategorileri",
            services.db.scalar("SELECT COUNT(*) FROM categories") == 20,
        )
        kontrol(
            "Baslangic konumlari",
            services.db.scalar("SELECT COUNT(*) FROM locations") == 8,
        )

        # Turkce karakterler diskte bozulmamali.
        tam_turkce = "Çaykur Rize Çayı — ıspanak şöğüş ĞÜİÖŞ"
        pid = services.products.quick_create(
            tam_turkce, sale_price=8000, barcode="8690504001492", initial_stock=10,
            purchase_cost=5000,
        )
        okunan = services.products.get(pid)["name"]
        kontrol("Turkce karakterler korunuyor", okunan == tam_turkce, okunan)

        satis = services.sales.quick_sale(pid)
        kontrol("Hizli satis calisiyor", satis.total_amount == 8000)
        kontrol(
            "Stok dustu",
            services.products.get(pid)["current_stock"] == 9,
        )

        services.sales.reverse_sale(satis.sale_id)
        kontrol(
            "Geri alma stogu iade etti",
            services.products.get(pid)["current_stock"] == 10,
        )

        sorunlar = services.db.check_invariants(deep=True)
        kontrol("Tutarlilik denetimi temiz", not sorunlar, "; ".join(sorunlar))

        yedek = services.backup.create_manual()
        kontrol("Yedek alindi", Path(yedek).exists())

        db_yolu = Path(services.db.path)
        services.close()
        kontrol("Veritabani dosyasi olustu", db_yolu.exists())

        # Kapat-ac kaliciligi.
        from app.core.db import open_database
        from app.services.container import build_services

        yeniden = build_services(open_database(db_yolu))
        try:
            kontrol(
                "Kapat-ac veriyi korudu",
                yeniden.products.get(pid)["current_stock"] == 10,
            )
        finally:
            yeniden.close()

        import logging

        logging.getLogger(__name__).info("Kendi kendini sinama tamamlandi")
        for isleyici in logging.getLogger().handlers:
            isleyici.flush()
        log_yolu = config.log_file_path()
        kontrol(
            "Log dosyasi yazilabiliyor",
            log_yolu.exists() and log_yolu.stat().st_size > 0,
            str(log_yolu),
        )
    except Exception as hata:                                  # pragma: no cover
        kontrol("Beklenmeyen hata", False, repr(hata))

    yaz("")
    yaz(f"Sonuc: {'TUM KONTROLLER BASARILI' if not basarisiz else str(basarisiz) + ' KONTROL BASARISIZ'}")
    _write_report(report_path, satirlar)
    return 0 if not basarisiz else 1


def _write_report(path: str | None, satirlar: list[str]) -> None:
    if not path:
        return
    try:
        Path(path).write_text("\n".join(satirlar), encoding="utf-8")
    except OSError:
        pass
