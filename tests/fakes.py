"""Testlerde paylaşılan sahte nesneler.

V1.1'de bu sınıflar ayrı test dosyalarında tanımlıydı; V1.2'de çok sayıda yeni
test dosyası aynılarına ihtiyaç duyduğu için buraya TAŞINDILAR (davranış
değişmedi). Hiçbiri ürün koduna dahil değildir.
"""
from __future__ import annotations

from app.payments.base import FailureKind, PaymentRequest, PaymentResult


# --- Saat ----------------------------------------------------------------
class SahteSaat:
    """İlerletilebilir tekdüze saat (saniye cinsinden)."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, ms: float) -> None:
        self.now += ms / 1000.0


# --- Ödeme adaptörleri ----------------------------------------------------
class PatlayanAdaptor:
    name = "patlak"
    supports_void = False

    def authorize(self, request: PaymentRequest) -> PaymentResult:
        raise RuntimeError("terminal kablosu çıktı")

    def void(self, reference: str) -> PaymentResult:  # pragma: no cover
        raise RuntimeError("olmaz")


class ZamanAsimiAdaptor:
    name = "yavas"
    supports_void = False

    def authorize(self, request: PaymentRequest) -> PaymentResult:
        raise TimeoutError("terminal yanıt vermedi")

    def void(self, reference: str) -> PaymentResult:  # pragma: no cover
        raise RuntimeError("olmaz")


class RedAdaptor:
    name = "red"
    supports_void = False

    def authorize(self, request: PaymentRequest) -> PaymentResult:
        return PaymentResult(
            approved=False, method=request.method, amount=request.amount,
            message="Kart reddedildi.", failure_kind=FailureKind.DECLINED,
        )

    def void(self, reference: str) -> PaymentResult:  # pragma: no cover
        raise RuntimeError("olmaz")


# --- Müşteri ekranı -------------------------------------------------------
class SahteEkran:
    """Çağrıları SIRAYLA kaydeden sahte ekran."""

    def __init__(self, patlasin: bool = False) -> None:
        self.cagrilar: list[tuple[str, int | None]] = []
        self.patlasin = patlasin

    def show_total(self, kurus: int) -> None:
        self.cagrilar.append(("total", kurus))
        if self.patlasin:
            raise OSError("COM portu yok")

    def show_idle(self) -> None:
        self.cagrilar.append(("idle", None))
        if self.patlasin:
            raise OSError("COM portu yok")

    def close(self) -> None:
        self.cagrilar.append(("close", None))


class SiraliSahteEkran:
    """Çağrıları SIRAYLA kaydeden sahte ekran."""

    def __init__(self) -> None:
        self.cagrilar: list[tuple[str, int | None]] = []

    def show_total(self, kurus: int) -> None:
        self.cagrilar.append(("total", kurus))

    def show_idle(self) -> None:
        self.cagrilar.append(("idle", None))

    def close(self) -> None:
        pass


class SabitDuvarSaati:
    """İlerletilebilir yerel duvar saati (``app.core.clock.use_clock`` için).

    ``saat()`` çağrılabilir nesnesi sağlayıcı olarak verilir; ``git``/``ilerle``
    ile zaman ileri alınır. Tekdüze saat de aynı nesneden türetilebilir.
    """

    def __init__(self, an=None) -> None:
        from datetime import datetime

        self.an = an or datetime(2026, 9, 1, 9, 0, 0)

    def __call__(self):
        return self.an

    def git(self, yil, ay, gun, saat=12, dakika=0, saniye=0) -> None:
        from datetime import datetime

        self.an = datetime(yil, ay, gun, saat, dakika, saniye)

    def ilerle(self, saniye: float = 1.0) -> None:
        from datetime import timedelta

        self.an = self.an + timedelta(seconds=saniye)

    def tekduze(self) -> float:
        return self.an.timestamp()
