"""Uygulama giriş noktası.

Açılış sırası bilinçlidir:
  1. Yüksek DPI politikası — ``QApplication``'dan ÖNCE olmak ZORUNDA
  2. QApplication + tema
  3. Log ve hata yakalayıcı
  4. Tek örnek koruması
  5. Veritabanı (göçler burada uygulanır)
  6. Tutarlılık denetimi (sessiz; yalnızca log'a yazar)
  7. Gerekiyorsa otomatik yedek
  8. Ana pencere

Kapanışta: yedek (gerekiyorsa), saat damgası, veritabanını düzgün kapat.
"""
from __future__ import annotations

import argparse
import logging
import sys

from app import config

log = logging.getLogger(__name__)


def parse_args(argv: list[str]) -> argparse.Namespace:
    ayristirici = argparse.ArgumentParser(description=config.APP_NAME, add_help=True)
    ayristirici.add_argument(
        "--data-dir", help="Veri klasörünü değiştirir (test ve taşınabilir kip)."
    )
    ayristirici.add_argument(
        "--self-test", nargs="?", const="", metavar="RAPOR",
        help="Arayüz açmadan kendi kendini sınar ve raporu yazar.",
    )
    ayristirici.add_argument(
        "--reset-window", action="store_true",
        help="Pencere boyutu ve konumunu sıfırlar.",
    )
    return ayristirici.parse_args(argv)


def _configure_high_dpi() -> None:
    """Ölçek çarpanını olduğu gibi geçir.

    ``QApplication`` oluşturulmadan ÖNCE çağrılmak zorundadır. Sonuç olarak
    %125 ölçeklemede 1366x768 ekran uygulamaya ~1092x614 mantıksal piksel
    bırakır; en küçük pencere boyutu bunun altında tutulmuştur.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )


def _install_excepthook(app) -> None:
    """Yakalanmamış hatalar: kullanıcıya sade mesaj, log'a tam iz."""
    from PySide6.QtWidgets import QMessageBox

    def kanca(tur, deger, iz):
        if issubclass(tur, KeyboardInterrupt):
            sys.__excepthook__(tur, deger, iz)
            return
        log.critical("Beklenmeyen hata", exc_info=(tur, deger, iz))
        try:
            kutu = QMessageBox()
            kutu.setIcon(QMessageBox.Icon.Warning)
            kutu.setWindowTitle("Beklenmeyen bir durum")
            kutu.setText(
                "Uygulamada beklenmeyen bir durum oluştu.\n"
                "Verileriniz güvende; işleme kaldığınız yerden devam edebilirsiniz."
            )
            kutu.setInformativeText(f"Kayıt dosyası:\n{config.log_file_path()}")
            kutu.setStandardButtons(QMessageBox.StandardButton.Ok)
            kutu.button(QMessageBox.StandardButton.Ok).setText("Tamam")
            kutu.exec()
        except Exception:
            pass

    sys.excepthook = kanca


def _show_startup_error(message: str, detail: str = "") -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    if QApplication.instance() is None:
        QApplication(sys.argv)
    kutu = QMessageBox()
    kutu.setIcon(QMessageBox.Icon.Critical)
    kutu.setWindowTitle(config.APP_NAME)
    kutu.setText(message)
    if detail:
        kutu.setInformativeText(detail)
    kutu.setStandardButtons(QMessageBox.StandardButton.Ok)
    kutu.button(QMessageBox.StandardButton.Ok).setText("Tamam")
    kutu.exec()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(argv)

    if args.self_test is not None:
        from app.tools.self_test import run_self_test

        return run_self_test(args.self_test or None)

    if args.data_dir:
        import os

        os.environ[config.ENV_DATA_DIR] = args.data_dir

    _configure_high_dpi()

    from PySide6.QtWidgets import QApplication

    from app.core.logging_setup import setup_logging
    from app.ui import sound, theme

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationDisplayName(config.APP_NAME)
    app.setOrganizationName(config.APP_DIR_NAME)
    theme.apply_theme(app)

    setup_logging()
    _install_excepthook(app)
    log.info("%s %s başlatılıyor", config.APP_NAME, config.APP_VERSION)

    # --- Tek örnek koruması ---
    from app.ui.single_instance import SingleInstance

    tek = SingleInstance(config.APP_DIR_NAME)
    if tek.already_running():
        log.info("Uygulama zaten açık; mevcut pencere öne getiriliyor")
        tek.notify_existing()
        return 0

    # --- Veritabanı ---
    from app.core.errors import VeritabaniHatasi
    from app.services.container import create_services

    try:
        services = create_services()
    except VeritabaniHatasi as hata:
        log.exception("Veritabanı açılamadı")
        _show_startup_error(
            hata.message,
            "Ayarlar > Yedekleme bölümünden bir yedeği geri yükleyebilirsiniz.\n"
            f"Veri klasörü: {config.data_dir()}",
        )
        return 1
    except Exception as hata:
        log.exception("Başlatma hatası")
        _show_startup_error(
            "Uygulama başlatılamadı.",
            f"Veri klasörü: {config.data_dir()}\n{hata}",
        )
        return 1

    if args.reset_window:
        services.settings.set_many_quiet(
            {"window_geometry": "", "window_maximized": 0}
        )

    sound.set_enabled(services.settings.sound_enabled())

    # Tutarlılık denetimi: sorun yoksa kullanıcı HİÇBİR ŞEY görmez.
    try:
        sorunlar = services.db.check_invariants()
        if sorunlar:
            log.error("Veri tutarsızlığı: %s", "; ".join(sorunlar))
    except Exception:
        log.exception("Bütünlük kontrolü yapılamadı")

    try:
        uyari = services.db.check_clock()
        if uyari:
            log.warning(uyari)
    except Exception:
        log.exception("Saat kontrolü yapılamadı")

    try:
        alinan = services.backup.maybe_auto_backup()
        if alinan:
            log.info("Otomatik yedek alındı: %s", alinan)
    except Exception:
        log.exception("Otomatik yedek alınamadı")

    # --- Ana pencere ---
    from app.ui.main_window import MainWindow

    yeniden_baslat = {"istendi": False}

    def yeniden_baslat_iste() -> None:
        yeniden_baslat["istendi"] = True
        app.quit()

    pencere = MainWindow(services, restart_callback=yeniden_baslat_iste)
    tek.set_window(pencere)
    pencere.show()
    pencere.refresh_today()

    # Açılışta kullanıcının seçtiği satış kipine git; her açılışta sorma.
    varsayilan = services.settings.default_sale_mode()
    if varsayilan == "SEPET":
        pencere.go_to("sepetli_satis")
    else:
        pencere.go_to("ana_ekran")

    cikis = app.exec()

    # --- Kapanış ---
    try:
        services.backup.maybe_auto_backup()
    except Exception:
        log.exception("Kapanışta yedek alınamadı")
    try:
        services.db.stamp_clock()
    except Exception:
        log.exception("Saat damgası yazılamadı")
    try:
        services.close()
    except Exception:
        log.exception("Veritabanı düzgün kapatılamadı")

    tek.release()
    if yeniden_baslat["istendi"]:
        _restart_process()
    log.info("Uygulama kapatıldı (kod %s)", cikis)
    return cikis


def _restart_process() -> None:
    """Geri yükleme sonrası uygulamayı yeniden başlatır."""
    from PySide6.QtCore import QProcess

    try:
        if config.is_frozen():
            QProcess.startDetached(sys.executable, sys.argv[1:])
        else:
            QProcess.startDetached(sys.executable, ["-m", "app.main", *sys.argv[1:]])
    except Exception:                                          # pragma: no cover
        log.exception("Yeniden başlatma başarısız")


if __name__ == "__main__":
    sys.exit(main())
