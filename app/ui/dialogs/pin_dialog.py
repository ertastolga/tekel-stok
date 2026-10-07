"""Yönetici PIN'i pencereleri: doğrulama, kurtarma ve kurma/değiştirme.

Hepsi ``TouchDialog`` tabanlıdır: varsayılan düğme yok, Enter onaylamaz,
okuyucu hızında gelen fiziksel rakamlar (ör. kazara okutulan bir barkod)
PIN'e YAZILMAZ ve dolayısıyla hiçbir deneme sayılmaz. Doğrulama pencerenin
İÇİNDE yapılır; pencere yalnızca doğru PIN (ya da kurtarma kodu) ile kabul
edilerek kapanır.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QWidget

from app.services.security_service import (
    KURTARMA_HANE,
    PIN_EN_UZUN,
    GecersizPin,
)
from app.ui import theme
from app.ui.widgets.common import make_label
from app.ui.widgets.touch_input import TouchDialog, TouchDisplay, TouchKey, TouchNumpad

#: ``PinDialog`` sonuçları.
VAZGECILDI = "VAZGECILDI"
DOGRULANDI = "DOGRULANDI"
KURTARILDI = "KURTARILDI"


class PinDialog(TouchDialog):
    """Yönetici PIN'ini sorar ve doğrular (kilit ve kurtarma dahil)."""

    def __init__(self, security, action_label: str = "", parent: QWidget | None = None):
        super().__init__("Yönetici PIN'i", parent)
        self.security = security
        self.sonuc = VAZGECILDI
        self._kurtarma = False

        self.title_label = make_label("Yönetici PIN'i gerekli", "sectionTitle")
        self.root.addWidget(self.title_label)
        self.action_label = make_label(
            f"İşlem: {action_label}" if action_label else "", "cardHint", wrap=True
        )
        self.root.addWidget(self.action_label)

        self.display = TouchDisplay("PIN", max_length=PIN_EN_UZUN, masked=True)
        self.root.addWidget(self.display)
        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet(f"color: {theme.DANGER}; font-weight: 600;")
        self.root.addWidget(self.message_label)

        self.numpad = TouchNumpad(allow_decimal=False, allow_double_zero=False)
        self.numpad.bind(self.display)
        self.root.addWidget(self.numpad)

        self.forgot_button = TouchKey("PIN'imi unuttum", width=220)
        self.forgot_button.clicked.connect(self._kurtarma_kipi)
        self.root.addWidget(self.forgot_button)
        self.add_buttons(accept_text="Onayla", on_accept=self._onayla)

        self._kilit_zamanlayici = QTimer(self)
        self._kilit_zamanlayici.setInterval(1000)
        self._kilit_zamanlayici.timeout.connect(self._kilidi_goster)
        self._kilidi_goster()

    def accepts_physical(self, metin: str) -> bool:
        return metin.isdigit()

    def _kurtarma_kipi(self) -> None:
        self._kurtarma = True
        self.title_label.setText("Kurtarma kodu")
        self.action_label.setText(
            "PIN kurulurken gösterilen 12 haneli kurtarma kodunu girin. "
            "Doğruysa yeni bir PIN belirleyeceksiniz."
        )
        self.display = self._yeni_gosterim()
        self.forgot_button.setVisible(False)

    def _yeni_gosterim(self) -> TouchDisplay:
        eski = self.display
        yeni = TouchDisplay("Kurtarma kodu", max_length=KURTARMA_HANE)
        self.root.replaceWidget(eski, yeni)
        eski.deleteLater()
        try:
            self.numpad.key_pressed.disconnect()
            self.numpad.backspace_pressed.disconnect()
            self.numpad.clear_pressed.disconnect()
        except (RuntimeError, TypeError):
            pass
        self.numpad.bind(yeni)
        return yeni

    def _kilidi_goster(self) -> None:
        kalan = self.security.lock_remaining()
        if kalan:
            from app.services.security_service import PinSonucu

            self.message_label.setText(PinSonucu(False, 0, kalan).mesaj)
            self.accept_button.setEnabled(False)
            if not self._kilit_zamanlayici.isActive():
                self._kilit_zamanlayici.start()
        else:
            if self._kilit_zamanlayici.isActive():
                self._kilit_zamanlayici.stop()
                self.message_label.setText("")
            self.accept_button.setEnabled(True)

    def _onayla(self) -> None:
        deger = self.display.value()
        if not deger:
            return
        if self._kurtarma:
            sonuc = self.security.verify_recovery(deger)
        else:
            sonuc = self.security.verify(deger)
        if sonuc.dogru:
            self.sonuc = KURTARILDI if self._kurtarma else DOGRULANDI
            self.accept()
            return
        self.display.clear_value()
        self.message_label.setText(sonuc.mesaj)
        self._kilidi_goster()

    @classmethod
    def ask(cls, parent, security, action_label: str = "") -> str:
        pencere = cls(security, action_label, parent)
        pencere.exec()
        return pencere.sonuc


class PinSetupDialog(TouchDialog):
    """Yeni PIN: iki kez girilir; sonra kurtarma kodu BİR KEZ gösterilir."""

    def __init__(self, security, parent: QWidget | None = None):
        super().__init__("Yönetici PIN'i belirle", parent)
        self.security = security
        self.recovery_code: str | None = None
        self._ilk: str | None = None

        self.step_label = make_label("Yeni PIN (4–8 hane)", "sectionTitle")
        self.root.addWidget(self.step_label)
        self.display = TouchDisplay("PIN", max_length=PIN_EN_UZUN, masked=True)
        self.root.addWidget(self.display)
        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet(f"color: {theme.DANGER}; font-weight: 600;")
        self.root.addWidget(self.message_label)
        self.numpad = TouchNumpad(allow_decimal=False, allow_double_zero=False)
        self.numpad.bind(self.display)
        self.root.addWidget(self.numpad)

        self.code_label = make_label("", "cardValue")
        self.code_label.setVisible(False)
        self.root.addWidget(self.code_label)
        self.code_hint = make_label(
            "Bu kurtarma kodunu yazıp güvenli bir yerde saklayın. Bir daha "
            "GÖSTERİLMEYECEK. PIN'i unutursanız bu kodla yeni PIN belirlersiniz.",
            "cardHint", wrap=True,
        )
        self.code_hint.setVisible(False)
        self.root.addWidget(self.code_hint)
        self.add_buttons(accept_text="İleri", on_accept=self._ileri)

    def accepts_physical(self, metin: str) -> bool:
        return self.recovery_code is None and metin.isdigit()

    def _ileri(self) -> None:
        if self.recovery_code is not None:
            self.accept()                       # "Kodu not aldım"
            return
        deger = self.display.value()
        if self._ilk is None:
            try:
                from app.services.security_service import pin_kurallari

                pin_kurallari(deger)
            except GecersizPin as hata:
                self.message_label.setText(hata.message)
                self.display.clear_value()
                return
            self._ilk = deger
            self.display.clear_value()
            self.message_label.setText("")
            self.step_label.setText("Yeni PIN'i tekrar girin")
            return
        if deger != self._ilk:
            self._ilk = None
            self.display.clear_value()
            self.step_label.setText("Yeni PIN (4–8 hane)")
            self.message_label.setText("PIN'ler aynı değil. Baştan girin.")
            return
        self.recovery_code = self.security.set_pin(deger)
        self._kod_goster()

    def _kod_goster(self) -> None:
        self.step_label.setText("PIN kuruldu. Kurtarma kodunuz:")
        self.display.setVisible(False)
        self.numpad.setVisible(False)
        self.message_label.setText("")
        self.code_label.setText(self.recovery_code or "")
        self.code_label.setVisible(True)
        self.code_hint.setVisible(True)
        self.reject_button.setVisible(False)
        self.accept_button.setText("Kodu not aldım")

    @classmethod
    def run(cls, parent, security) -> bool:
        pencere = cls(security, parent)
        pencere.exec()
        return pencere.recovery_code is not None
