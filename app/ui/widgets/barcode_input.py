"""Barkod alanı: tarama ekranlarındaki görünür odak noktası.

Merkezi ``ScannerService`` okutmayı zaten yakalar; bu alan iki iş yapar:
  1. Kullanıcıya "sistem barkod bekliyor" duygusunu verir,
  2. Elle barkod yazmak isteyene bir kapı açar (okuyucu bozulursa).

Odak, ekran etkin olduğu sürece burada TUTULUR. Kullanıcı bir tabloya ya da
düğmeye tıkladıktan sonra barkod kutusuna geri tıklamak ZORUNDA DEĞİLDİR.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QLineEdit, QWidget

from app.ui import metrics


class BarcodeInput(QLineEdit):
    """Sonlandırıcıyla (Enter/Tab) gönderim yapan barkod alanı."""

    submitted = Signal(str)

    def __init__(self, mode: str = "sale", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("barcodeInput")
        self.setProperty("mode", mode)
        self.setPlaceholderText("Barkodu okutun…")
        self.setClearButtonEnabled(False)
        self.setMinimumHeight(metrics.BARCODE_INPUT_HEIGHT)

        #: Uzun süre dokunulmazsa yarım kalmış metin temizlenir; ertesi
        #: okutmanın başına eski karakterler yapışmasın.
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(3000)
        self._idle.timeout.connect(self.clear)
        self.textEdited.connect(lambda _: self._idle.start())

    def event(self, event):
        # Tab, odak zincirine gitmeden ÖNCE yakalanır: bazı okuyucular
        # sonlandırıcı olarak Enter yerine Tab gönderir.
        if event.type() == event.Type.KeyPress and event.key() in (
            Qt.Key.Key_Tab, Qt.Key.Key_Backtab
        ):
            if self.text().strip():
                self._submit()
                return True
        return super().event(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._submit()
            return
        if key == Qt.Key.Key_Escape:
            self.clear()
            return
        super().keyPressEvent(event)

    def _submit(self) -> None:
        text = self.text()
        self.clear()                     # her okutmadan sonra alan temizlenir
        self._idle.stop()
        if text.strip():
            self.submitted.emit(text)

    def set_compact(self, compact: bool = True) -> None:
        """Kasa araç çubuğu için alçak biçim (yerleşim bütçesi)."""
        self.setProperty("kompakt", "evet" if compact else "hayir")
        self.setMinimumHeight(0 if compact else metrics.BARCODE_INPUT_HEIGHT)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_mode(self, mode: str) -> None:
        """Ekrana göre odak rengi: satış yeşil, stok turuncu, sayım mor."""
        self.setProperty("mode", mode)
        self.style().unpolish(self)
        self.style().polish(self)


class FocusKeeper:
    """Barkod alanının odağını nazikçe geri getirir.

    Kullanıcı bir düğmeye ya da tabloya tıkladıktan sonra okuyucuyu kullanmaya
    devam edebilmelidir. Odak, yalnızca BAŞKA bir yazı alanına geçilmediyse
    geri alınır — yoksa kullanıcının yazdığı ad/fiyat alanı elinden alınırdı.
    """

    def __init__(self, target: BarcodeInput, interval_ms: int = 400) -> None:
        self.target = target
        self._timer = QTimer(target)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        self._timer.start()
        self.target.setFocus()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        from PySide6.QtWidgets import (
            QAbstractSpinBox,
            QApplication,
            QComboBox,
            QLineEdit,
            QPlainTextEdit,
            QTextEdit,
        )

        if not self.target.isVisible() or not self.target.isEnabled():
            return
        app = QApplication.instance()
        if app is None:
            return
        pencere = self.target.window()
        if pencere is None or not pencere.isActiveWindow():
            return
        if app.activeModalWidget() is not None:
            return                       # karar penceresi açık: karışma
        odak = app.focusWidget()
        if odak is self.target:
            return
        if isinstance(odak, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
            return                       # kullanıcı yazıyor: elinden alma
        if isinstance(odak, QComboBox) and odak.isEditable():
            return
        self.target.setFocus()
