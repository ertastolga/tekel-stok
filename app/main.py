"""Uygulama giriş noktası.

Açılış sırası bilinçlidir:
  1. Yüksek DPI politikası — ``QApplication``'dan ÖNCE olmak ZORUNDA
  2. QApplication + tema (görünüm ayarları veritabanına SALT OKUNUR bakışla,
     göçten ve pencerelerden ÖNCE okunur; okunamazsa Açık / %100 / Normal)
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
    ayristirici.add_argument(
        "--yonetici-pin-sifirla", action="store_true",
        help="Son çare: önce güvenlik yedeği alır, sonra yönetici PIN'ini siler.",
    )
    ayristirici.add_argument(
        "--surum-geri-donus", metavar="YEDEK",
        help="Önceki sürüme dönmek için veriyi güncelleme öncesi yedekle "
        "değiştirir (veri açılmaz ve güncellenmez).",
    )
    return ayristirici.parse_args(argv)


def baslangic_hata_ayrintisi(hata) -> str:
    """Açılış hatası için kullanıcıya gösterilecek YARDIMCI metin.

    Uygulama açılamadığı için "Ayarlar" sayfasına ulaşılamaz; bu yüzden metin
    ASLA uygulama içi bir menüye yönlendirmez. Yalnızca klasör yollarını ve
    güvenli bir sonraki adımı söyler.
    """
    from app.core.errors import GocBasarisiz, GocOncesiYedekAlinamadi, YeniSurumVeritabani

    satirlar: list[str] = []
    if isinstance(hata, YeniSurumVeritabani):
        satirlar.append("Güncel TekelStok sürümünü bu veri klasörüyle başlatın.")
    elif isinstance(hata, GocOncesiYedekAlinamadi):
        satirlar.append(
            "Diskte yer açıp uygulamayı yeniden başlatın. Bu sırada önceki "
            "sürümü kullanmaya devam edebilirsiniz."
        )
    elif isinstance(hata, GocBasarisiz):
        satirlar.append(
            "Lütfen kayıt dosyasını destek için saklayın. Önceki sürüm aynı "
            "veriyle çalışmaya devam eder."
        )
    else:
        satirlar.append(
            "Başka bir TekelStok penceresi açıksa kapatıp yeniden deneyin. "
            "Sorun sürerse yedek klasöründeki son yedeği saklayın ve destek isteyin."
        )
    satirlar.append(f"Veri klasörü: {config.data_dir()}")
    satirlar.append(f"Yedek klasörü: {config.auto_backup_dir()}")
    satirlar.append(f"Kayıt dosyası: {config.log_file_path()}")
    return "\n".join(satirlar)


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
    from app.core import gorunum

    secim = gorunum.oku(config.db_path())
    theme.gorunumu_uygula(secim.tema, secim.olcek, secim.yogunluk)
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

    if args.surum_geri_donus:
        try:
            return _surum_geri_donus_calistir(args.surum_geri_donus)
        finally:
            tek.release()

    try:
        services = create_services()
    except VeritabaniHatasi as hata:
        log.exception("Veritabanı açılamadı")
        tek.release()
        _show_startup_error(hata.message, baslangic_hata_ayrintisi(hata))
        return 1
    except Exception:
        log.exception("Başlatma hatası")
        tek.release()
        _show_startup_error(
            "Uygulama başlatılamadı.",
            f"Veri klasörü: {config.data_dir()}\n"
            f"Kayıt dosyası: {config.log_file_path()}",
        )
        return 1

    if args.yonetici_pin_sifirla and not _pin_sifirla_calistir(services):
        services.close()
        tek.release()
        return 1

    if args.reset_window:
        services.settings.set_many_quiet(
            {"window_geometry": "", "window_maximized": 0}
        )

    acik, seviye, turler = services.settings.ses_ayarlari()
    sound.yapilandir(acik, seviye, turler, config.data_dir() / "sounds")

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

    # Açılış: günlük yedek fırsatı (göçten sonra, pencereden önce).
    yedek_firsati(services, "açılış")

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

    cikis = app.exec()

    # --- Kapanış ---
    # Gün boyu hiç boşta kalınmadıysa günlük yedek burada alınır. Geri yükleme
    # ya da görünüm için yeniden başlatılıyorsa alınmaz (açılışta alınır).
    if not pencere.restarting:
        yedek_firsati(services, "kapanış")
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


def yedek_firsati(services, asama: str) -> list:
    """Açılış/kapanış yedek fırsatı: gerekiyorsa günlük, zamanı geldiyse otomatik.

    Hiçbir hata uygulamayı durdurmaz; yedek servisi hatayı kaydeder ve durum
    çubuğunda uyarı görünür (M10b).
    """
    alinanlar = []
    for ad, islem in (("günlük", services.backup.create_daily),
                      ("otomatik", services.backup.maybe_auto_backup)):
        try:
            yol = islem()
        except Exception:
            log.exception("%s yedeği (%s) alınamadı", ad.capitalize(), asama)
            continue
        if yol is not None:
            log.info("%s yedek alındı (%s): %s", ad.capitalize(), asama, yol)
            alinanlar.append(yol)
    return alinanlar


def _pin_sifirla_calistir(services) -> bool:
    """``--yonetici-pin-sifirla``: "SIFIRLA" yazılarak onay → yedek → PIN silinir.

    Başarılıysa uygulama normal açılır; kırmızı bildirim, yeni PIN ve kurtarma
    kodu belirlenip sahibi onaylayana dek Yönetim ekranlarında kalır.
    """
    from PySide6.QtWidgets import QDialog, QLabel, QMessageBox

    from app.core.errors import DomainError
    from app.services.security_service import ONAY_METNI
    from app.ui.widgets.touch_input import TouchTextDialog

    pencere = TouchTextDialog("Yönetici PIN'ini sıfırla", placeholder=ONAY_METNI)
    aciklama = QLabel(
        "Yönetici PIN'i ve kurtarma kodu silinecek. Önce otomatik bir güvenlik "
        f"yedeği alınır. Onaylamak için {ONAY_METNI} yazın."
    )
    aciklama.setWordWrap(True)
    pencere.root.insertWidget(0, aciklama)
    if pencere.exec() != QDialog.DialogCode.Accepted:
        log.info("PIN sıfırlama vazgeçildi")
        return False
    try:
        yol = services.security.reset_with_backup(services.backup, pencere.value())
    except DomainError as hata:
        log.warning("PIN sıfırlanamadı: %s (%s)", hata.message, hata.detail)
        _show_startup_error(hata.message, f"Kayıt dosyası: {config.log_file_path()}")
        return False

    bilgi = QMessageBox()
    bilgi.setIcon(QMessageBox.Icon.Information)
    bilgi.setWindowTitle(config.APP_NAME)
    bilgi.setText("Yönetici PIN'i sıfırlandı.")
    bilgi.setInformativeText(
        f"Güvenlik yedeği: {yol}\nUygulama açılınca yeni bir PIN belirleyin."
    )
    bilgi.setStandardButtons(QMessageBox.StandardButton.Ok)
    bilgi.button(QMessageBox.StandardButton.Ok).setText("Tamam")
    bilgi.exec()
    return True


def _surum_geri_donus_calistir(yedek: str) -> int:
    """``--surum-geri-donus``: onay al, veriyi değiştir, sonucu söyle.

    Veritabanı bu yolda HİÇ açılmaz (dolayısıyla güncellenmez de).
    """
    from PySide6.QtWidgets import QMessageBox

    from app.core.errors import DomainError
    from app.services.geri_donus import surum_geri_donus, yedek_semasini_dogrula

    try:
        yedek_semasini_dogrula(yedek)
    except DomainError as hata:
        log.warning("Sürüm geri dönüşü reddedildi: %s (%s)", hata.message, hata.detail)
        _show_startup_error(hata.message, f"Seçilen dosya: {yedek}")
        return 1

    kutu = QMessageBox()
    kutu.setIcon(QMessageBox.Icon.Warning)
    kutu.setWindowTitle(config.APP_NAME)
    kutu.setText(
        "Mevcut veri, seçilen ESKİ sürüm yedeğiyle değiştirilecek.\n"
        "Yedekten sonra yapılan satış ve stok kayıtları bu veride olmayacak."
    )
    kutu.setInformativeText(
        f"Yedek: {yedek}\nVeri klasörü: {config.data_dir()}\n"
        "Mevcut veri önce bir kopyaya alınır."
    )
    devam = kutu.addButton("Geri Dön", QMessageBox.ButtonRole.AcceptRole)
    vazgec = kutu.addButton("Vazgeç", QMessageBox.ButtonRole.RejectRole)
    kutu.setDefaultButton(vazgec)
    kutu.exec()
    if kutu.clickedButton() is not devam:
        log.info("Sürüm geri dönüşü kullanıcı tarafından iptal edildi")
        return 1

    try:
        sonuc = surum_geri_donus(yedek, config.db_path(), config.auto_backup_dir())
    except DomainError:
        log.exception("Sürüm geri dönüşü başarısız")
        _show_startup_error(
            "Geri dönüş tamamlanamadı. Verileriniz değiştirilmedi.",
            f"Kayıt dosyası: {config.log_file_path()}",
        )
        return 1

    bilgi = QMessageBox()
    bilgi.setIcon(QMessageBox.Icon.Information)
    bilgi.setWindowTitle(config.APP_NAME)
    bilgi.setText("Geri dönüş tamamlandı. Şimdi önceki sürümü (V1.1) başlatın.")
    bilgi.setInformativeText(
        "Bu sürümü aynı veriyle yeniden açarsanız veri yeniden güncellenir.\n"
        f"Geri dönüş öncesi verinin kopyası: {sonuc.onceki_veri_kopyasi or '-'}"
    )
    bilgi.setStandardButtons(QMessageBox.StandardButton.Ok)
    bilgi.button(QMessageBox.StandardButton.Ok).setText("Tamam")
    bilgi.exec()
    return 0


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
