"""Ödeme adaptörü sözleşmesi.

Sıralama kuralı (mimarinin temeli)
----------------------------------
Ödeme onayı HER ZAMAN veritabanı işleminden ÖNCE ve ONUN DIŞINDA alınır::

    authorize()  →  (onaylandıysa)  →  cart.checkout()

Böylece ileride bir kart terminali yanıt beklerken **SQLite işlemi açık
kalmaz**. Açık kalsaydı, terminal 30 saniye düşündüğünde veritabanı o süre
boyunca kilitli olurdu.

İptal (void) için açık kapı
---------------------------
Fiziksel bir terminal ödemeyi onaylayıp ardından satış yazılamazsa para
alınmış ama satış kaydedilmemiş olur. V1.1 bu akışı ÇÖZMEZ — ama imkânsız da
kılmaz: ``PaymentResult.reference`` taşınır ve ``PaymentAdapter.void()``
sözleşmede tanımlıdır. Manuel adaptörlerde iptal edilecek elektronik bir işlem
yoktur (``supports_void = False``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class FailureKind:
    """Ödeme neden alınamadı? Kullanıcıya gösterilecek mesajı belirler."""

    NONE = ""
    DECLINED = "RED"            # kart reddedildi / müşteri vazgeçti
    TIMEOUT = "ZAMAN_ASIMI"     # terminal yanıt vermedi
    DEVICE_ERROR = "CIHAZ_HATASI"  # bağlantı koptu, istisna, bilinmeyen hata
    NOT_SUPPORTED = "DESTEKLENMIYOR"


@dataclass(frozen=True, slots=True)
class PaymentRequest:
    """Bir ödeme isteği. Tutar DAİMA tam sayı kuruştur."""

    amount: int
    method: str
    #: V1.1'de manuel adaptörler anında yanıt verdiği için kullanılmaz.
    #: Gelecekteki terminal adaptörü bu süreyi dikkate alır; süre aşılırsa
    #: ``FailureKind.TIMEOUT`` ile denetimli başarısızlık döner.
    timeout_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class PaymentResult:
    """Ödeme girişiminin sonucu. İSTİSNA DEĞİL, sonuç döner."""

    approved: bool
    method: str
    amount: int
    #: Terminal işlem numarası. İleride iptal (void) için GEREKLİDİR;
    #: manuel adaptörlerde ``None``.
    reference: str | None = None
    #: Kullanıcıya gösterilecek sade Türkçe. Teknik ayrıntı ASLA buraya girmez.
    message: str = ""
    failure_kind: str = FailureKind.NONE

    @property
    def is_device_problem(self) -> bool:
        return self.failure_kind in (FailureKind.TIMEOUT, FailureKind.DEVICE_ERROR)


@runtime_checkable
class PaymentAdapter(Protocol):
    """Bir ödeme yöntemini gerçekleştiren bileşen."""

    name: str
    #: Bu adaptör alınmış bir ödemeyi geri alabilir mi? Manuel (nakit / elle
    #: onaylanan kart) adaptörlerde ``False``: ortada iptal edilecek
    #: elektronik bir işlem yoktur.
    supports_void: bool

    def authorize(self, request: PaymentRequest) -> PaymentResult:
        """Ödemeyi onaylat. İstisna fırlatabilir; servis bunu yakalar."""
        ...

    def void(self, reference: str) -> PaymentResult:
        """Onaylanmış bir ödemeyi geri al. V1.1'de hiçbir adaptör uygulamaz."""
        ...


class BaseAdapter:
    """Ortak varsayılanlar. Adaptörler bundan türeyebilir (zorunlu değil)."""

    name = "temel"
    supports_void = False

    def authorize(self, request: PaymentRequest) -> PaymentResult:  # pragma: no cover
        raise NotImplementedError

    def void(self, reference: str) -> PaymentResult:
        """Varsayılan: desteklenmiyor.

        Gelecekteki terminal adaptörü bunu GERÇEKTEN uygular; o zamana kadar
        çağıran taraf ``supports_void`` ile zaten kontrol eder.
        """
        return PaymentResult(
            approved=False,
            method=getattr(self, "name", ""),
            amount=0,
            reference=reference,
            message="Bu ödeme yöntemi geri alma desteklemiyor.",
            failure_kind=FailureKind.NOT_SUPPORTED,
        )
