"""Okutmaların hangi ekrana, hangi sırayla gideceğini yöneten yönlendirici.

Qt'suzdur ve bu yüzden tamamen başsız test edilebilir; ``ScannerService``
yalnızca klavye olaylarını buraya besler.

İki kip ve aralarındaki fark BİLİNÇLİDİR
----------------------------------------

``ACTIVE``
    Normal çalışma. Okutmalar FIFO kuyruğa alınır ve SIRAYLA işlenir. Bir
    işleyici çalışırken gelen okutma kaybolmaz, arkasına dizilir. Saniyede
    birkaç okutma bu sayede güvenle işlenir.

``SUSPENDED``
    Ekranda iş açısından kritik bir KARAR penceresi açık (tanınmayan barkod,
    koli onayı, büyük sayım farkı...). Bu sırada gelen okutmalar **kuyruğa
    ALINMAZ** ve **sonradan OYNATILMAZ**; anında "engellendi" olarak geri
    bildirilir.

    Neden kuyruk değil? Pencere kapandıktan sonra biriken okutmaların
    işlenmesi **gecikmiş sürpriz satış** üretir: kullanıcının o an istemediği,
    hatta farkında olmadığı işlemler. Doğru davranış geciktirmek değil,
    HEMEN ve DUYULUR biçimde reddetmektir.

Her iki kipte de değişmez aynıdır: **hiçbir okutma sessizce kaybolmaz** — ya
işlenir, ya da kullanıcıya anında bildirilerek reddedilir.
"""
from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from enum import Enum

from app.scanner.scan_event import ScanEvent

log = logging.getLogger(__name__)


class RouterMode(Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ScanOutcome(Enum):
    HANDLED = "HANDLED"
    QUEUED = "QUEUED"
    BLOCKED = "BLOCKED"          # karar penceresi açık — anında reddedildi
    DUPLICATE = "DUPLICATE"      # donanım çift-tetiklemesi
    NO_HANDLER = "NO_HANDLER"


class ScanRouter:
    def __init__(self, guard=None) -> None:
        self._handlers: dict[str, Callable[[ScanEvent], None]] = {}
        self._context: str | None = None
        self._mode = RouterMode.ACTIVE
        self._queue: deque[ScanEvent] = deque()
        self._dispatching = False
        self._seen: set[int] = set()
        self._guard = guard
        #: Tanılama halkası: askıdayken gelen okutmalar da buraya yazılır,
        #: böylece Barkod Testi ekranında görünürler ama İŞ KUYRUĞUNA girmezler.
        self._diagnostics: deque[tuple[ScanEvent, ScanOutcome]] = deque(maxlen=200)
        self.on_blocked: Callable[[ScanEvent], None] | None = None
        self.on_duplicate: Callable[[ScanEvent], None] | None = None

    # ===================== İşleyiciler ===================================
    def register(self, context: str, handler: Callable[[ScanEvent], None]) -> None:
        self._handlers[context] = handler

    def unregister(self, context: str) -> None:
        self._handlers.pop(context, None)
        if self._context == context:
            self._context = None

    def set_context(self, context: str | None) -> None:
        """Etkin ekranı değiştirir ve çift-okuma korumasını sıfırlar."""
        if context == self._context:
            return
        self._context = context
        if self._guard is not None:
            self._guard.reset()

    @property
    def context(self) -> str | None:
        return self._context

    @property
    def mode(self) -> RouterMode:
        return self._mode

    # ===================== Askıya alma ===================================
    def suspend(self, reason: str = "") -> None:
        """Karar penceresi açıldı: iş işleme durur, kuyruk BİRİKTİRMEZ."""
        self._mode = RouterMode.SUSPENDED
        log.debug("Okutma askıya alındı: %s", reason)

    def resume(self) -> None:
        """Karar penceresi kapandı. Kuyruk BOŞTUR — gecikmiş satış olmaz."""
        self._mode = RouterMode.ACTIVE
        self._queue.clear()
        if self._guard is not None:
            self._guard.reset()

    @property
    def is_suspended(self) -> bool:
        return self._mode is RouterMode.SUSPENDED

    # ===================== Teslim ========================================
    def dispatch(self, event: ScanEvent) -> ScanOutcome:
        """Bir okutmayı etkin işleyiciye teslim eder."""
        # Aynı olayın iki kez teslimi (Qt olay tekrarı) sessizce yutulur.
        # Bu, kullanıcının aynı barkodu BİLEREK tekrar okutmasından farklıdır:
        # o durumda yeni bir olay ve yeni bir scan_id oluşur.
        if event.scan_id in self._seen:
            return ScanOutcome.DUPLICATE
        self._seen.add(event.scan_id)
        if len(self._seen) > 1000:
            self._seen = set(list(self._seen)[-500:])

        if self._mode is RouterMode.SUSPENDED:
            self._record(event, ScanOutcome.BLOCKED)
            if self.on_blocked is not None:
                self.on_blocked(event)
            return ScanOutcome.BLOCKED

        if self._context is None or self._context not in self._handlers:
            self._record(event, ScanOutcome.NO_HANDLER)
            return ScanOutcome.NO_HANDLER

        if self._guard is not None and not self._guard.check(event.code, self._context):
            self._record(event, ScanOutcome.DUPLICATE)
            if self.on_duplicate is not None:
                self.on_duplicate(event)
            return ScanOutcome.DUPLICATE

        # Bir işleyici çalışırken gelen okutma SIRAYA girer; böylece hızlı
        # ardışık okutmalar hem kaybolmaz hem de sırası bozulmaz.
        self._queue.append(event)
        if self._dispatching:
            return ScanOutcome.QUEUED

        self._drain()
        return ScanOutcome.HANDLED

    def _drain(self) -> None:
        self._dispatching = True
        try:
            while self._queue:
                if self._mode is RouterMode.SUSPENDED:
                    # İşleyici bir karar penceresi açtı: kalanları İŞLEME,
                    # kullanıcıya sürpriz yapma.
                    for bekleyen in self._queue:
                        self._record(bekleyen, ScanOutcome.BLOCKED)
                        if self.on_blocked is not None:
                            self.on_blocked(bekleyen)
                    self._queue.clear()
                    return
                event = self._queue.popleft()
                handler = self._handlers.get(self._context or "")
                if handler is None:
                    self._record(event, ScanOutcome.NO_HANDLER)
                    continue
                try:
                    handler(event)
                    self._record(event, ScanOutcome.HANDLED)
                except Exception:
                    # Bir ekranın hatası okuyucuyu kilitlememeli.
                    log.exception("Okutma işlenirken hata: %s", event.code)
                    self._record(event, ScanOutcome.NO_HANDLER)
        finally:
            self._dispatching = False

    # ===================== Tanılama ======================================
    def _record(self, event: ScanEvent, outcome: ScanOutcome) -> None:
        self._diagnostics.append((event, outcome))

    def diagnostics(self, limit: int = 20) -> list[tuple[ScanEvent, ScanOutcome]]:
        """Barkod Testi ekranı için son okutmalar (engellenenler dâhil)."""
        return list(self._diagnostics)[-limit:]

    def clear_diagnostics(self) -> None:
        self._diagnostics.clear()
