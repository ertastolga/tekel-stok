"""Sesli geri bildirim.

Dükkân sahibi ekrana sürekli bakmak zorunda kalmamalıdır: okutmanın tuttuğunu
kulağıyla da anlamalıdır.

``winsound`` kullanılır — ses dosyası yoktur ve ``QtMultimedia`` gerekmez, bu
sayede paketleme küçük kalır. Sesler kısa ve ayırt edicidir; rahatsız edici
değildir ve Ayarlar'dan tamamen kapatılabilir.
"""
from __future__ import annotations

import logging
import sys

log = logging.getLogger(__name__)

try:
    if sys.platform == "win32":
        import winsound
    else:                                          # pragma: no cover
        winsound = None
except ImportError:                                # pragma: no cover
    winsound = None

_ENABLED = True


def set_enabled(enabled: bool) -> None:
    global _ENABLED
    _ENABLED = bool(enabled)


def is_enabled() -> bool:
    return _ENABLED


def _beep(frequency: int, duration_ms: int) -> None:
    if not _ENABLED or winsound is None:
        return
    try:
        winsound.Beep(frequency, duration_ms)
    except Exception:                              # pragma: no cover
        pass


def _message(kind: int) -> None:
    if not _ENABLED or winsound is None:
        return
    try:
        winsound.MessageBeep(kind)
    except Exception:                              # pragma: no cover
        pass


def success() -> None:
    """Okutma tuttu: kısa ve tiz — akışı kesmez."""
    _beep(1200, 40)


def warning() -> None:
    """Dikkat: satış oldu ama bir not var (örn. stok eksiye düştü)."""
    _message(getattr(winsound, "MB_ICONEXCLAMATION", 48) if winsound else 48)


def error() -> None:
    """Tanınmayan barkod ya da yapılamayan işlem."""
    _message(getattr(winsound, "MB_ICONHAND", 16) if winsound else 16)


def blocked() -> None:
    """Karar penceresi açıkken okutma yapıldı: alçak ve kısa iki ton.

    Bilerek 'başarı' sesinden AÇIKÇA farklıdır; kullanıcı ekrana bakmadan da
    okutmanın işlenmediğini anlar.
    """
    _beep(380, 70)
    _beep(300, 70)


def price_check() -> None:
    """Fiyat Gör: satıştan AYIRT EDİLEBİLEN iki kısa tiz ses (satış yapılmadı)."""
    _beep(1600, 30)
    _beep(1600, 30)
