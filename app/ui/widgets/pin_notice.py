"""PIN sıfırlama bildirimi: kırmızı, KALICI şerit.

``--yonetici-pin-sifirla`` ile PIN sıfırlandıysa; yeni PIN ve yeni kurtarma
kodu kurulup sahibi bildirimi AÇIKÇA onaylayana dek her Yönetim sayfasında ve
Ana Ekran'da görünür (yeniden başlatmadan etkilenmez). Kasa sayfalarında
gösterilmez: satış akışını bölmez.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget

from app.ui import metrics, theme
from app.ui.widgets.common import make_label


class PinResetNotice(QFrame):
    setup_requested = Signal()
    acknowledge_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pinResetNotice")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#pinResetNotice {{ background: {theme.DANGER_LIGHT}; "
            f"border-bottom: 2px solid {theme.DANGER}; }}"
        )
        duzen = QHBoxLayout(self)
        duzen.setContentsMargins(16, 8, 16, 8)
        duzen.setSpacing(10)
        self.text_label = make_label("", wrap=True)
        self.text_label.setStyleSheet(f"color: {theme.DANGER}; font-weight: 600;")
        duzen.addWidget(self.text_label, 1)
        self.setup_button = QPushButton("Yeni PIN belirle")
        self.setup_button.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
        self.setup_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setup_button.clicked.connect(self.setup_requested.emit)
        duzen.addWidget(self.setup_button)
        self.ack_button = QPushButton("Bildirimi onayla")
        self.ack_button.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
        self.ack_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ack_button.clicked.connect(self.acknowledge_requested.emit)
        duzen.addWidget(self.ack_button)
        self.setVisible(False)

    def update_state(self, security, on_kasa_page: bool) -> None:
        aktif = security.reset_notice_active()
        self.setVisible(aktif and not on_kasa_page)
        if not aktif:
            return
        zaman = security.reset_time_utc()
        tarih = datetime.fromtimestamp(zaman).strftime("%d.%m.%Y %H:%M") if zaman else ""
        onaylanabilir = security.reset_notice_ackable()
        self.text_label.setText(
            f"⚠ Yönetici PIN'i {tarih} tarihinde başlangıç seçeneğiyle SIFIRLANDI. "
            + (
                "Yeni PIN ve kurtarma kodu kuruldu; bu bildirimi onaylayabilirsiniz."
                if onaylanabilir else
                "Yeni bir PIN ve kurtarma kodu belirleyin, sonra bu bildirimi onaylayın."
            )
        )
        self.setup_button.setVisible(not onaylanabilir)
        self.ack_button.setEnabled(onaylanabilir)
