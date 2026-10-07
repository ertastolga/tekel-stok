"""Yönetici koruması: PIN gerektiren eylemlerin TEK kapısı.

* PIN kurulmamışsa hiçbir şey sorulmaz (PIN isteğe bağlıdır).
* Doğru PIN bir "kilit açık" oturumu başlatır. Oturum bir Kasa sayfası
  gösterilince ya da 5 dakika etkileşimsiz kalınınca KAPANIR.
* PIN penceresi açıkken okutma askıdadır; okutulan barkod PIN'e yazılmaz.
* Kasa işleri (satış, aynı günün son satışını geri alma, bekletme, fiyat
  görme, arama, hızlı ürün ekleme, gezinme) bu kapıdan GEÇMEZ.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from app.core import clock
from app.services.security_service import ProtectedAction

log = logging.getLogger(__name__)

#: Etkileşimsiz geçen bu süreden sonra kilit yeniden kapanır (sn).
OTURUM_SN = 300

_ETKILESIM = (
    QEvent.Type.MouseButtonPress,
    QEvent.Type.KeyPress,
    QEvent.Type.TouchBegin,
)


class ManagerGuard(QObject):
    def __init__(self, services, main_window) -> None:
        super().__init__(main_window)
        self.services = services
        self.main_window = main_window
        self._acik = False
        self._son = 0.0
        self._kurulu = False

    # ===================== Yaşam döngüsü =================================
    def start(self) -> None:
        app = QApplication.instance()
        if app is not None and not self._kurulu:
            app.installEventFilter(self)
            self._kurulu = True

    def stop(self) -> None:
        app = QApplication.instance()
        if app is not None and self._kurulu:
            app.removeEventFilter(self)
        self._kurulu = False
        self.lock()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if self._acik and event.type() in _ETKILESIM:
            self._son = clock.monotonic()
        return False

    # ===================== Oturum ========================================
    def is_unlocked(self) -> bool:
        if not self._acik:
            return False
        if clock.monotonic() - self._son > OTURUM_SN:
            self._acik = False
            log.info("Yönetici oturumu süre dolduğu için kapandı")
            return False
        return True

    def lock(self) -> None:
        self._acik = False

    def _ac(self) -> None:
        self._acik = True
        self._son = clock.monotonic()

    # ===================== Kapı ==========================================
    def require(self, action: str, parent=None) -> bool:
        """Eylem yapılabilir mi? Gerekirse PIN sorar; ``True`` = devam."""
        guvenlik = self.services.security
        if not guvenlik.has_pin():
            return True
        if self.is_unlocked():
            self._son = clock.monotonic()
            return True
        from app.ui.dialogs.common_dialogs import scanning_suspended
        from app.ui.dialogs.pin_dialog import DOGRULANDI, KURTARILDI, PinDialog, PinSetupDialog

        etiket = ProtectedAction.ETIKETLER.get(action, action)
        with scanning_suspended(
            getattr(self.main_window, "router", None), reason="yönetici PIN'i"
        ):
            sonuc = PinDialog.ask(parent or self.main_window, guvenlik, etiket)
            if sonuc == KURTARILDI:
                # Kurtarma kodu doğru: sahibi HEMEN yeni PIN (ve yeni kod) belirler.
                if not PinSetupDialog.run(parent or self.main_window, guvenlik):
                    return False
                sonuc = DOGRULANDI
        if sonuc == DOGRULANDI:
            self._ac()
            return True
        return False

    def setup_or_change_pin(self, parent=None) -> bool:
        """PIN kurar ya da (mevcut PIN'le) değiştirir."""
        guvenlik = self.services.security
        if guvenlik.has_pin() and not self.require(ProtectedAction.PIN_DEGISTIR, parent):
            return False
        from app.ui.dialogs.common_dialogs import scanning_suspended
        from app.ui.dialogs.pin_dialog import PinSetupDialog

        with scanning_suspended(
            getattr(self.main_window, "router", None), reason="yönetici PIN'i"
        ):
            kuruldu = PinSetupDialog.run(parent or self.main_window, guvenlik)
        if kuruldu:
            self._ac()
        return kuruldu
