"""Donanım kaynaklı çift okuma koruması.

Bazı barkod okuyucular tek tetiklemede aynı barkodu iki kez gönderir. Koruma
bilerek ÇOK DAR tutulmuştur.

Neden dar? Bu uygulamada **aynı barkodu tekrar tekrar okutmak birincil miktar
giriş yöntemidir**: müşteri 10 bira alıyorsa dükkân sahibi tek şişeyi 10 kez
okutur. Pencere geniş olursa gerçek satışlar SESSİZCE DÜŞER — bu, uygulamanın
yapabileceği en kötü hatadır.

Sayılar
-------
* Okuyucu çift-tetiklemesi: ~10-30 ms
* İnsanın şişeyi geri çevirip tekrar okutması: en az ~250 ms
* Varsayılan pencere: **120 ms** — ikisinin tam ortasında, ikisine de güvenli.

Kardeş uygulamada bu değer 450 ms'dir; orada tekrar okutma bir miktar giriş
yöntemi olmadığı için sorun çıkarmaz. Burada olurdu.

Koruma yalnızca şu üç koşul birlikte sağlandığında devreye girer:
  * barkod metni birebir aynı,
  * aynı ekran etkin,
  * bir önceki okuma kabul edilmiş.
"""
from __future__ import annotations

import time

DEFAULT_WINDOW_MS = 120


class ScanGuard:
    def __init__(
        self, window_ms: int = DEFAULT_WINDOW_MS, clock=time.monotonic
    ) -> None:
        self.window_ms = max(0, int(window_ms))
        self._clock = clock
        self._last_code: str | None = None
        self._last_context: str | None = None
        self._last_ms: float | None = None

    def _now_ms(self) -> float:
        return self._clock() * 1000.0

    def set_window(self, window_ms: int) -> None:
        self.window_ms = max(0, int(window_ms))

    def reset(self) -> None:
        """Ekran değişince çağrılır: yeni bağlamda eski okuma sayılmaz."""
        self._last_code = None
        self._last_context = None
        self._last_ms = None

    def is_duplicate(
        self, code: str, context: str, now_ms: float | None = None
    ) -> bool:
        if self.window_ms <= 0:
            return False
        if self._last_code is None or self._last_ms is None:
            return False
        if code != self._last_code or context != self._last_context:
            return False
        now_ms = self._now_ms() if now_ms is None else now_ms
        return (now_ms - self._last_ms) < self.window_ms

    def register(self, code: str, context: str, now_ms: float | None = None) -> None:
        self._last_code = code
        self._last_context = context
        self._last_ms = self._now_ms() if now_ms is None else now_ms

    def check(self, code: str, context: str, now_ms: float | None = None) -> bool:
        """True = okuma KABUL edilir (ve kaydedilir), False = çift okuma."""
        if self.is_duplicate(code, context, now_ms):
            return False
        self.register(code, context, now_ms)
        return True
