"""Tek bir barkod okutma olayı.

``scan_id`` idempotans içindir: Qt aynı olayı iki kez teslim ederse ya da bir
işleyici yanlışlıkla iki kez çağrılırsa, ikinci teslim sessizce yok sayılır.
Bu, "aynı barkodu bilerek tekrar okutmak"tan FARKLIDIR — o durumda yeni bir
olay ve yeni bir ``scan_id`` oluşur.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

_counter = itertools.count(1)


def _next_id() -> int:
    return next(_counter)


@dataclass(frozen=True, slots=True)
class ScanEvent:
    """Okuyucudan gelen ham okutma.

    ``code`` HAM metindir; normalleştirme ve GTIN çözümü servis katmanının
    işidir (``BarcodeService``). Arayüz ham metni verir, ürünü servis bulur.
    """

    code: str
    at_ms: float = 0.0
    key_count: int = 0
    avg_gap_ms: float = 0.0
    source: str = "SCANNER"
    #: En uzun tuş arası (ms) ve sonlandırıcı: "ENTER", "TAB" ya da "YOK"
    #: (sonlandırıcısız okuyucu, bekleme süresiyle yakalandı) — Barkod Testi.
    max_gap_ms: float = 0.0
    terminator: str = ""
    scan_id: int = field(default_factory=_next_id)

    @property
    def looks_machine_typed(self) -> bool:
        """Tuş başına 30 ms'nin altı = okuyucu.

        Eşik, kardeş uygulamanın Barkod Testi ekranından toplanan gerçek
        ölçümlerle belirlenmiştir.
        """
        return self.key_count > 3 and self.avg_gap_ms < 30.0

    def describe(self) -> str:
        """Barkod Testi ekranı için insan okuyabilir özet."""
        hiz = (
            "barkod okuyucu (çok hızlı)"
            if self.looks_machine_typed
            else "elle yazım olabilir (yavaş)"
        )
        return (
            f"{self.code} · {self.key_count} tuş · "
            f"tuş başına {self.avg_gap_ms:.0f} ms · {hiz}"
        )
