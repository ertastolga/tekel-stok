"""Merkezi barkod okuyucu servisi (uygulama düzeyi olay süzgeci).

USB barkod okuyucular klavye gibi davranır ama ÇOK hızlı yazar ve genellikle
sonunda Enter gönderir. Bu servis, uygulamanın TAMAMINDA tek bir yerden bu
diziyi yakalar; her ekranın kendi kırılgan klavye kodunu yazmasına gerek
kalmaz.

Kullanıcının ASLA yapmak zorunda kalmadığı şey
----------------------------------------------
Barkod kutusuna tıklayarak odağı geri getirmek. Kullanıcı bir tabloya, bir
düğmeye tıklamış olsa bile okutma yakalanır ve doğru ekrana gider.

Nasıl ayırt ediliyor?
---------------------
Okuyucu tuş başına 30 ms'den hızlı yazar; insan yazamaz. Eşik uydurma
değildir: kardeş uygulamanın Barkod Testi ekranından toplanan gerçek
ölçümlerden gelir ve Ayarlar'dan görülebilir.

İnsan yazımı yutulmaz
---------------------
Metin alanına yazan bir insanın tuşları normal akışına devam eder; yalnızca
makine hızındaki bir dizi + sonlandırıcı yakalanır. Ayrıca elle yazım
gereken alanlar ``scannerExempt`` özelliğiyle tamamen muaf tutulabilir.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
)

from app.scanner.scan_event import ScanEvent

log = logging.getLogger(__name__)

#: Bu süreden kısa aralıklarla gelen tuşlar OKUYUCU dizisi sayılır.
BURST_KEY_MS = 30
#: Kutuda metin varken bu süreden uzun bir aradan sonra gelen karakter yeni
#: bir okutmayı başlatıyor olabilir (bayat önek temizliği).
STALE_GAP_MS = 300
#: Sonlandırıcı gelmezse tamponu boşaltma süresi.
IDLE_FLUSH_MS = 400
#: Bu uzunluğun altındaki diziler sonlandırıcısız kabul EDİLMEZ.
MIN_AUTO_FLUSH_LENGTH = 6

#: Elle yazım yapılan alanlar bu özellikle tamamen muaf tutulur.
EXEMPT_PROPERTY = "scannerExempt"

_TEXT_WIDGETS = (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)


class ScannerService(QObject):
    """Klavye olaylarını dinler ve tamamlanan okutmaları yayınlar."""

    scanned = Signal(object)          # ScanEvent

    def __init__(self, parent: QObject | None = None, clock=time.monotonic) -> None:
        super().__init__(parent)
        self._clock = clock
        self._buffer: list[str] = []
        self._first_ms: float | None = None
        self._last_ms: float | None = None
        self._gaps: list[float] = []
        self._installed = False

        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(IDLE_FLUSH_MS)
        self._idle.timeout.connect(self._flush_idle)

    # ===================== Yaşam döngüsü =================================
    def start(self) -> None:
        app = QApplication.instance()
        if app is not None and not self._installed:
            app.installEventFilter(self)
            self._installed = True

    def stop(self) -> None:
        app = QApplication.instance()
        if app is not None and self._installed:
            app.removeEventFilter(self)
        self._installed = False
        self._reset()

    # ===================== Olay süzgeci ==================================
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Type.KeyPress:
            return False

        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # Sonlandırıcı: elimizde makine hızında bir dizi varsa bu bir
            # okutmadır ve Enter'ın odaktaki düğmeyi tetiklemesini ENGELLERİZ.
            if self._is_machine_burst():
                self._emit()
                return True
            self._reset()
            return False

        if key == Qt.Key.Key_Escape:
            self._reset()
            return False

        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        ):
            # Ctrl/Alt kısayolları okutma sayılmaz.
            self._reset()
            return False

        text = event.text()
        if not text or not text.isprintable() or not text.strip():
            return False

        if self._is_exempt(QApplication.focusWidget()):
            return False

        self._ingest(text)
        return False        # tuş normal akışına devam eder: insan yazımı bozulmaz

    @staticmethod
    def _is_exempt(widget) -> bool:
        """Elle yazım için ayrılmış alanlar hiç dinlenmez."""
        if widget is None:
            return False
        if widget.property(EXEMPT_PROPERTY):
            return True
        if isinstance(widget, QComboBox) and widget.isEditable():
            return True
        return False

    # ===================== Tampon ========================================
    def _ingest(self, text: str) -> None:
        now = self._now_ms()
        gap = float("inf") if self._last_ms is None else now - self._last_ms

        if self._buffer and gap > STALE_GAP_MS:
            # Uzun aradan sonra gelen karakter yeni bir okutmanın başıdır;
            # yarım kalmış eski dizi atılır (bayat önek hatası).
            self._reset()
            gap = float("inf")

        if self._first_ms is None:
            self._first_ms = now
        else:
            self._gaps.append(gap)

        self._buffer.append(text)
        self._last_ms = now
        self._idle.start()

    def _is_machine_burst(self) -> bool:
        if len(self._buffer) < 2:
            return False
        return self._avg_gap() < BURST_KEY_MS

    def _avg_gap(self) -> float:
        if not self._gaps:
            return float("inf")
        return sum(self._gaps) / len(self._gaps)

    def _flush_idle(self) -> None:
        """Sonlandırıcı göndermeyen okuyucular için güvenlik ağı.

        Yalnızca yeterince uzun VE makine hızındaki diziler yayınlanır; aksi
        hâlde insanın yazdığı birkaç harf yanlışlıkla barkod sanılırdı.
        """
        if len(self._buffer) >= MIN_AUTO_FLUSH_LENGTH and self._is_machine_burst():
            self._emit()
        else:
            self._reset()

    def _emit(self) -> None:
        code = "".join(self._buffer)
        event = ScanEvent(
            code=code,
            at_ms=self._last_ms or self._now_ms(),
            key_count=len(self._buffer),
            avg_gap_ms=0.0 if self._avg_gap() == float("inf") else self._avg_gap(),
        )
        self._reset()
        if code.strip():
            self.scanned.emit(event)

    def _reset(self) -> None:
        self._buffer.clear()
        self._gaps.clear()
        self._first_ms = None
        self._last_ms = None
        self._idle.stop()

    def _now_ms(self) -> float:
        return self._clock() * 1000.0

    # ===================== Test / tanılama ===============================
    def feed(self, text: str, interval_ms: float = 5.0, terminate: bool = True) -> None:
        """Test koşumu: bir okutmayı gerçek zamanlama ile taklit eder.

        Testler ve Barkod Testi ekranı gerçek donanım olmadan tüm akışı
        deneyebilsin diye vardır; ``clock`` enjekte edilebildiği için
        testlerde hiç beklenmez.
        """
        for ch in text:
            self._ingest(ch)
            if hasattr(self._clock, "advance"):
                self._clock.advance(interval_ms)
        if terminate:
            if self._is_machine_burst() or len(text) == 1:
                self._emit()
            else:
                self._reset()
