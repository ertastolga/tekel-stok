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
            services.db.scalar("SELECT COUNT(*) FROM categories") == 34,
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

        kontrol(*_yukseltme_denetimi(Path(gecici)))
        for denetim in _ice_aktarma_denetimleri(Path(gecici)):
            kontrol(*denetim)

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


def _yukseltme_denetimi(kok: Path) -> tuple[str, bool, str]:
    """En eski semadan (v1) guncel semaya yukseltme, ASCII olmayan bir klasorde.

    Derlenmis exe'nin gocleri ve guncelleme oncesi yedegi GERCEKTEN
    calistirabildigini kanitlar (yalnizca bos veritabani acmak yetmez).
    """
    from app.core import schema as schema_mod
    from app.core.db import Database, hedef_sema_surumu, open_database
    from app.services.container import build_services

    hedef = hedef_sema_surumu()
    ad = f"Surum yukseltme v1 -> v{hedef}"
    klasor = kok / "yükseltme_ğüşİöç"
    yedekler = klasor / "yedekler"
    yol = klasor / "eski.db"
    try:
        klasor.mkdir(parents=True, exist_ok=True)
        tum_gocler = schema_mod.MIGRATIONS
        schema_mod.MIGRATIONS = tum_gocler[:1]
        try:
            eski = Database(yol).connect()
            eski.seed_settings()
            eski.close()
        finally:
            schema_mod.MIGRATIONS = tum_gocler

        yeni = build_services(open_database(yol, pre_migration_backup_dirs=[yedekler]))
        try:
            surum = yeni.db.schema_version()
            sorunlar = yeni.db.check_invariants(deep=True)
            yedek = yeni.db.last_migration_backup
            if hedef > 1:
                if yedek is None or not yedek.exists():
                    return ad, False, "guncelleme oncesi yedek yok"
                bilgi = yeni.backup.inspect(yedek)
                if bilgi.schema_version != 1:
                    return ad, False, f"yedek semasi {bilgi.schema_version}"
            elif yedek is not None:
                return ad, False, "guncelleme yokken yedek alindi"
        finally:
            yeni.close()
        if surum != hedef:
            return ad, False, f"sema {surum}"
        return ad, not sorunlar, "; ".join(sorunlar)
    except Exception as hata:
        return ad, False, repr(hata)


def _ice_aktarma_denetimleri(kok: Path) -> list[tuple[str, bool, str]]:
    """Ürün listesi okuma: CSV (cp1254) ve XLSX (openpyxl) gidiş-dönüş.

    Derlenmiş exe'de openpyxl'in GERÇEKTEN paketlendiğini kanıtlar: XLSX
    açıksa bu denetim geçmek zorundadır.
    """
    from app.importers.alanlar import barkod_hucresi, fiyat_hucresi
    from app.importers.okuyucu import XLSX_KULLANILABILIR, oku

    sonuc = []
    klasor = kok / "içe_aktarma_ğüş"
    klasor.mkdir(parents=True, exist_ok=True)
    ad_tr = "Şarap Çeşit İçki"
    try:
        csv_yolu = klasor / "liste.csv"
        csv_yolu.write_bytes(f"Barkod;Ürün adı;Fiyat\r\n0012345;{ad_tr};80,50\r\n"
                             .encode("cp1254"))
        tablo = oku(csv_yolu)
        satir = tablo.satirlar[0]
        dogru = (satir[0] == "0012345" and satir[1] == ad_tr
                 and fiyat_hucresi(satir[2]) == 8050)
        sonuc.append(("CSV urun listesi okunuyor", dogru, repr(satir)))
    except Exception as hata:
        sonuc.append(("CSV urun listesi okunuyor", False, repr(hata)))
    try:
        if not XLSX_KULLANILABILIR:
            raise RuntimeError("openpyxl paketlenmemis")
        import openpyxl

        kitap = openpyxl.Workbook()
        kitap.active.append(["Barkod", "Ürün adı", "Fiyat"])
        kitap.active.append(["0012345678905", ad_tr, 80.5])
        kitap.active.append([8690504001492, "Sayı", 75])
        xlsx_yolu = klasor / "liste.xlsx"
        kitap.save(xlsx_yolu)
        tablo = oku(xlsx_yolu)
        ilk, ikinci = tablo.satirlar
        dogru = (ilk[0] == "0012345678905" and ilk[1] == ad_tr
                 and fiyat_hucresi(ilk[2]) == 8050 and barkod_hucresi(ikinci[0]).sayisal)
        sonuc.append(("Excel (.xlsx) urun listesi okunuyor", dogru, repr(tablo.satirlar)))
    except Exception as hata:
        sonuc.append(("Excel (.xlsx) urun listesi okunuyor", False, repr(hata)))
    return sonuc


def _write_report(path: str | None, satirlar: list[str]) -> None:
    if not path:
        return
    try:
        Path(path).write_text("\n".join(satirlar), encoding="utf-8")
    except OSError:
        pass
