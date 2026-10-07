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

Askıya alma JETONLUDUR (V1.2)
-----------------------------

``suspend()`` bir jeton döner; ``resume(jeton)`` yalnızca O jetonu bırakır.
Yönlendirici ancak HİÇ jeton kalmadığında ``ACTIVE`` olur. Böylece iç içe ya da
sırası karışık açılıp kapanan pencereler (bir karar penceresinin içinden açılan
onay, kapanan bir katman...) okutmayı erken AÇAMAZ. ``resume`` aynı jetonla
ikinci kez çağrılırsa hiçbir şey olmaz. Engellenen okutmayı EN YENİ jetonun
bildirimcisi karşılar; onun bildirimcisi yoksa varsayılan ``on_blocked``.
Jetonsuz eski çağrı (``suspend()`` / ``resume()``) çift olarak çalışmaya devam
eder: jetonsuz ``resume()`` en son alınan jetonu bırakır.
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


class SuspensionToken:
    """Bir askıya alma isteğinin kimliği (yalnızca ``resume`` için)."""

    __slots__ = ("reason", "on_blocked", "_sira")

    def __init__(self, sira: int, reason: str, on_blocked) -> None:
        self._sira = sira
        self.reason = reason
        self.on_blocked: Callable[[ScanEvent], None] | None = on_blocked

    def __repr__(self) -> str:                                   # pragma: no cover
        return f"SuspensionToken({self._sira}, {self.reason!r})"


class ScanRouter:
    def __init__(self, guard=None) -> None:
        self._handlers: dict[str, Callable[[ScanEvent], None]] = {}
        self._context: str | None = None
        self._tokens: list[SuspensionToken] = []
        self._sonraki_jeton = 0
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
        return RouterMode.SUSPENDED if self._tokens else RouterMode.ACTIVE

    # ===================== Askıya alma ===================================
    def suspend(
        self,
        reason: str = "",
        on_blocked: Callable[[ScanEvent], None] | None = None,
    ) -> SuspensionToken:
        """Karar penceresi açıldı: iş işleme durur, kuyruk BİRİKTİRMEZ.

        Dönen jeton ``resume`` ile bırakılır. ``on_blocked`` verilirse bu jeton
        en yeni jeton olduğu sürece engellenen okutmaları o karşılar.
        """
        self._sonraki_jeton += 1
        jeton = SuspensionToken(self._sonraki_jeton, reason, on_blocked)
        self._tokens.append(jeton)
        log.debug("Okutma askıya alındı: %s (%d jeton)", reason, len(self._tokens))
        return jeton

    def resume(self, token: SuspensionToken | None = None) -> None:
        """Bir askıya almayı bırakır; SON jeton bırakılınca okutma açılır.

        Açılışta kuyruk BOŞTUR — gecikmiş satış olmaz. Aynı jetonla tekrar
        çağrı etkisizdir (bir başkasının askısını bırakmaz).
        """
        if token is None:
            if not self._tokens:
                return
            self._tokens.pop()
        else:
            if token not in self._tokens:
                return
            self._tokens.remove(token)
        if self._tokens:
            return
        self._queue.clear()
        if self._guard is not None:
            self._guard.reset()

    @property
    def is_suspended(self) -> bool:
        return bool(self._tokens)

    @property
    def suspension_count(self) -> int:
        """Açık askı jetonu sayısı (tanılama ve testler için)."""
        return len(self._tokens)

    def _blocked_handler(self) -> Callable[[ScanEvent], None] | None:
        if self._tokens and self._tokens[-1].on_blocked is not None:
            return self._tokens[-1].on_blocked
        return self.on_blocked

    def _bildir_engellendi(self, event: ScanEvent) -> None:
        self._record(event, ScanOutcome.BLOCKED)
        isleyici = self._blocked_handler()
        if isleyici is not None:
            isleyici(event)

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

        if self._tokens:
            self._bildir_engellendi(event)
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
                if self._tokens:
                    # İşleyici bir karar penceresi açtı: kalanları İŞLEME,
                    # kullanıcıya sürpriz yapma.
                    bekleyenler = list(self._queue)
                    self._queue.clear()
                    for bekleyen in bekleyenler:
                        self._bildir_engellendi(bekleyen)
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
