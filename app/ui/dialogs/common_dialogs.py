"""Karar pencereleri.

Modal pencere YALNIZCA gerçek bir karar gerektiğinde açılır. Başarılı bir
işlemden sonra "Tamam" sorulmaz — bu, onay yorgunluğu yaratır ve kasa akışını
bozar.

Bir karar penceresi açıkken barkod okutma ASKIYA ALINIR: gelen okutmalar
kuyruğa alınmaz, sonradan oynatılmaz; anında duyulur biçimde reddedilir.
Aksi hâlde pencere kapandığında kullanıcının istemediği satışlar oluşurdu.
"""
from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui import theme


@contextmanager
def scanning_suspended(router, on_blocked=None, reason: str = "karar penceresi"):
    """Karar penceresi süresince okutmayı askıya alır.

    Kendi JETONUNU alır ve yalnızca onu bırakır: iç içe pencerelerde içteki
    kapanınca okutma açılmaz, dıştaki hâlâ açıktır. Son askı kalkınca kuyruk
    BOŞTUR: gecikmiş sürpriz satış oluşmaz.
    """
    if router is None:
        yield
        return
    jeton = router.suspend(reason, on_blocked)
    try:
        yield
    finally:
        router.resume(jeton)


def _yonlendirici(parent: QWidget | None):
    """Ebeveyn zincirinde okutma yönlendiricisi olan pencereyi bulur."""
    gerec = parent
    while gerec is not None:
        yonlendirici = getattr(gerec, "router", None)
        if yonlendirici is not None:
            return yonlendirici
        try:
            gerec = gerec.parentWidget()
        except RuntimeError:            # gereç bu arada silinmiş olabilir
            return None
    return None


def _askida_calistir(parent: QWidget | None, pencere) -> int:
    """Modal pencereyi okutma ASKIDAYKEN çalıştırır.

    Modal bir ileti açıkken gelen okutma arkadaki sayfaya gidip satış ya da
    stok kaydı oluşturamaz; anında "engellendi" olarak bildirilir. Çağıran
    zaten askıya aldıysa jetonlar iç içe güvenle birikir.
    """
    with scanning_suspended(_yonlendirici(parent), reason="ileti penceresi"):
        return pencere.exec()


def show_error(parent: QWidget | None, message: str, detail: str = "") -> None:
    """Sade Türkçe hata. Teknik ayrıntı KULLANICIYA gösterilmez, log'a gider."""
    kutu = QMessageBox(parent)
    kutu.setIcon(QMessageBox.Icon.Warning)
    kutu.setWindowTitle("Bir sorun var")
    kutu.setText(message)
    if detail:
        kutu.setInformativeText(detail)
    kutu.setStandardButtons(QMessageBox.StandardButton.Ok)
    kutu.button(QMessageBox.StandardButton.Ok).setText("Tamam")
    _askida_calistir(parent, kutu)


def show_info(parent: QWidget | None, title: str, message: str) -> None:
    kutu = QMessageBox(parent)
    kutu.setIcon(QMessageBox.Icon.Information)
    kutu.setWindowTitle(title)
    kutu.setText(message)
    kutu.setStandardButtons(QMessageBox.StandardButton.Ok)
    kutu.button(QMessageBox.StandardButton.Ok).setText("Tamam")
    _askida_calistir(parent, kutu)


def ask_confirm(
    parent: QWidget | None,
    message: str,
    detail: str = "",
    accept_text: str = "Evet",
    reject_text: str = "Vazgeç",
    danger: bool = False,
) -> bool:
    """Onay sorusu.

    Yalnızca kullanıcı gerçekten zarar verebilecekse sorulur. Tehlikeli
    işlemlerde varsayılan odak VAZGEÇ'tedir: yanlışlıkla Enter'a basmak
    silme yapmaz.
    """
    kutu = QMessageBox(parent)
    kutu.setIcon(QMessageBox.Icon.Question)
    kutu.setWindowTitle("Onay")
    kutu.setText(message)
    if detail:
        kutu.setInformativeText(detail)
    evet = kutu.addButton(accept_text, QMessageBox.ButtonRole.AcceptRole)
    hayir = kutu.addButton(reject_text, QMessageBox.ButtonRole.RejectRole)
    if danger:
        evet.setObjectName("danger")
        evet.setStyleSheet(
            f"background: {theme.DANGER}; color: #FFFFFF; font-weight: 600;"
        )
        kutu.setDefaultButton(hayir)
    else:
        kutu.setDefaultButton(evet)
    _askida_calistir(parent, kutu)
    return kutu.clickedButton() is evet


class PackConfirmDialog(QDialog):
    """Koli/paket barkodu satışta onay ister.

    Tek bir okutmayla 24 adet satmak, yanlışlıkla yapıldığında düzeltmesi zor
    bir hatadır. Soru kısa ve tek cümledir; tekli barkodlarda HİÇ sorulmaz.
    """

    def __init__(self, product_name: str, quantity: int, unit_label: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Koli satışı")
        self.setModal(True)

        duzen = QVBoxLayout(self)
        duzen.setContentsMargins(24, 20, 24, 20)
        duzen.setSpacing(14)

        soru = QLabel(f"1 koli {product_name} = {quantity} {unit_label.lower()}.")
        soru.setFont(theme.base_font(15, bold=True))
        soru.setWordWrap(True)
        duzen.addWidget(soru)
        duzen.addWidget(QLabel("Bu şekilde satılsın mı?"))

        dugmeler = QHBoxLayout()
        dugmeler.addStretch(1)
        vazgec = QPushButton("Vazgeç")
        vazgec.clicked.connect(self.reject)
        sat = QPushButton(f"Evet, {quantity} adet sat")
        sat.setObjectName("primary")
        sat.setDefault(True)
        sat.clicked.connect(self.accept)
        dugmeler.addWidget(vazgec)
        dugmeler.addWidget(sat)
        duzen.addLayout(dugmeler)

    @staticmethod
    def confirm(product_name: str, quantity: int, unit_label: str,
                parent: QWidget | None = None) -> bool:
        pencere = PackConfirmDialog(product_name, quantity, unit_label, parent)
        return pencere.exec() == QDialog.DialogCode.Accepted


class BlockedScanNotice(QLabel):
    """Karar penceresi içinde gösterilen 'okutma işlenmedi' şeridi.

    Pencere ÜSTÜNE yeni bir pencere açmak yerine, kullanıcıya aynı pencerenin
    içinde anında geri bildirim verilir.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background: {theme.WARNING_LIGHT}; color: {theme.WARNING}; "
            f"border: 1px solid {theme.WARNING}; border-radius: 6px; padding: 8px;"
        )
        self.setVisible(False)

    def show_blocked(self) -> None:
        self.setText("Önce ekrandaki soruyu yanıtlayın. Okutulan barkod işlenmedi.")
        self.setVisible(True)


def button_box(accept_text: str = "Kaydet", reject_text: str = "Vazgeç") -> QDialogButtonBox:
    kutu = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    kutu.button(QDialogButtonBox.StandardButton.Save).setText(accept_text)
    kutu.button(QDialogButtonBox.StandardButton.Save).setObjectName("primary")
    kutu.button(QDialogButtonBox.StandardButton.Cancel).setText(reject_text)
    return kutu
