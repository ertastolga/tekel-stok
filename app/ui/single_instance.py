"""Tek örnek koruması.

Aynı veritabanına iki uygulama örneğinin yazması, kullanıcının farkında
olmadığı tuhaf durumlar üretir: bir pencerede yapılan satış diğerinde
görünmez, iki ekran farklı stok gösterir.

``QLocalServer``/``QLocalSocket`` ile çözülür: ikinci örnek açıldığında mevcut
pencereye haber verir ve kendisi sessizce kapanır. Kullanıcı yalnızca
uygulamanın öne geldiğini görür; hata mesajı almaz.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject
from PySide6.QtNetwork import QLocalServer, QLocalSocket

log = logging.getLogger(__name__)

_CONNECT_TIMEOUT_MS = 300


class SingleInstance(QObject):
    def __init__(self, key: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.key = f"{key}-single-instance"
        self._server: QLocalServer | None = None
        self._window = None
        self._running = False
        self._check()

    def _check(self) -> None:
        soket = QLocalSocket()
        soket.connectToServer(self.key)
        if soket.waitForConnected(_CONNECT_TIMEOUT_MS):
            self._running = True
            soket.disconnectFromServer()
            return

        # Uygulama çöktüyse eski soket dosyası kalmış olabilir; temizlenir.
        QLocalServer.removeServer(self.key)
        self._server = QLocalServer(self)
        if not self._server.listen(self.key):
            log.warning("Tek örnek sunucusu kurulamadı: %s", self._server.errorString())
            self._server = None
            return
        self._server.newConnection.connect(self._on_new_connection)

    def already_running(self) -> bool:
        return self._running

    def notify_existing(self) -> None:
        """Çalışan örneğe 'öne gel' der."""
        soket = QLocalSocket()
        soket.connectToServer(self.key)
        if soket.waitForConnected(_CONNECT_TIMEOUT_MS):
            soket.write(b"raise")
            soket.flush()
            soket.waitForBytesWritten(_CONNECT_TIMEOUT_MS)
            soket.disconnectFromServer()

    def set_window(self, window) -> None:
        self._window = window

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        soket = self._server.nextPendingConnection()
        if soket is not None:
            soket.readyRead.connect(lambda: self._raise_window(soket))

    def _raise_window(self, soket) -> None:
        try:
            soket.readAll()
        except Exception:
            pass
        if self._window is None:
            return
        try:
            if self._window.isMinimized():
                self._window.showNormal()
            self._window.raise_()
            self._window.activateWindow()
        except Exception:
            log.exception("Pencere öne getirilemedi")

    def release(self) -> None:
        if self._server is not None:
            self._server.close()
            QLocalServer.removeServer(self.key)
            self._server = None
