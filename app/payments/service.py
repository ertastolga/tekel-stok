"""Ödeme servisi: adaptör kaydı ve GÜVENLİ çağrı sınırı.

En önemli görevi tek cümleyle: **hiçbir adaptör istisnası dışarı sızmaz.**

Bir ödeme cihazı her şeyi yapabilir — bağlantıyı koparır, donar, beklenmedik
bir istisna fırlatır. Bunların hiçbiri satış ekranını çökertmemeli ve yarım
kalmış bir işlem bırakmamalıdır. Bu yüzden her adaptör çağrısı burada
sarmalanır ve **denetimli bir başarısızlık sonucuna** çevrilir:

    satış yazılmaz · sepet aynen durur · okutma yeniden açılır ·
    kullanıcı modal olmayan sade bir hata görür · ayrıntı yalnızca log'a gider
"""
from __future__ import annotations

import logging

from app.core.models import PaymentMethod
from app.payments.base import (
    FailureKind,
    PaymentAdapter,
    PaymentRequest,
    PaymentResult,
)
from app.payments.manual import ManualCardAdapter, ManualCashAdapter

log = logging.getLogger(__name__)


class PaymentService:
    def __init__(self, adapters: dict[str, PaymentAdapter] | None = None) -> None:
        self._adapters: dict[str, PaymentAdapter] = {
            PaymentMethod.CASH: ManualCashAdapter(),
            PaymentMethod.CARD: ManualCardAdapter(),
        }
        if adapters:
            self._adapters.update(adapters)

    def register(self, method: str, adapter: PaymentAdapter) -> None:
        """Bir yöntemin adaptörünü değiştirir.

        Fiziksel terminal geldiğinde tek yapılacak budur; satış ekranı ve
        veritabanı katmanı hiç değişmez.
        """
        self._adapters[method] = adapter

    def adapter_for(self, method: str) -> PaymentAdapter | None:
        return self._adapters.get(method)

    def supports_void(self, method: str) -> bool:
        adapter = self._adapters.get(method)
        return bool(adapter is not None and getattr(adapter, "supports_void", False))

    # ===================== Onay ==========================================
    def authorize(
        self, method: str, amount: int, timeout_seconds: float | None = None
    ) -> PaymentResult:
        """Ödemeyi onaylatır. ASLA istisna fırlatmaz, DAİMA sonuç döner.

        Çağıran taraf yalnızca ``result.approved`` değerine bakar; onaylanmadıysa
        veritabanına HİÇ dokunulmaz.
        """
        adapter = self._adapters.get(method)
        if adapter is None:
            log.error("Tanımsız ödeme yöntemi: %s", method)
            return PaymentResult(
                approved=False, method=method, amount=amount,
                message="Bu ödeme yöntemi tanımlı değil.",
                failure_kind=FailureKind.NOT_SUPPORTED,
            )

        request = PaymentRequest(
            amount=amount, method=method, timeout_seconds=timeout_seconds
        )
        try:
            result = adapter.authorize(request)
        except TimeoutError:
            log.exception("Ödeme zaman aşımına uğradı: %s %s", method, amount)
            return PaymentResult(
                approved=False, method=method, amount=amount,
                message="Ödeme cihazı yanıt vermedi. Lütfen tekrar deneyin.",
                failure_kind=FailureKind.TIMEOUT,
            )
        except Exception:
            # Cihaz ne yaparsa yapsın satış ekranı ayakta kalır.
            log.exception("Ödeme alınamadı: %s %s", method, amount)
            return PaymentResult(
                approved=False, method=method, amount=amount,
                message="Ödeme alınamadı. Lütfen tekrar deneyin.",
                failure_kind=FailureKind.DEVICE_ERROR,
            )

        if result is None:                                   # kötü yazılmış adaptör
            log.error("Adaptör sonuç döndürmedi: %s", method)
            return PaymentResult(
                approved=False, method=method, amount=amount,
                message="Ödeme alınamadı. Lütfen tekrar deneyin.",
                failure_kind=FailureKind.DEVICE_ERROR,
            )
        if not result.approved and not result.message:
            # Adaptör mesaj vermediyse kullanıcıya boş ekran göstermeyelim.
            return PaymentResult(
                approved=False, method=result.method or method,
                amount=result.amount or amount, reference=result.reference,
                message="Ödeme tamamlanmadı.",
                failure_kind=result.failure_kind or FailureKind.DECLINED,
            )
        return result

    # ===================== İptal (V1.1'de kullanılmaz) ====================
    def void(self, method: str, reference: str) -> PaymentResult:
        """Onaylanmış bir ödemeyi geri alır.

        V1.1'de hiçbir adaptör bunu desteklemez (manuel ödemede iptal edilecek
        elektronik işlem yoktur). Sözleşme, fiziksel terminal eklendiğinde
        telafi akışının yazılabilmesi için BURADA DURUR.
        """
        adapter = self._adapters.get(method)
        if adapter is None:
            return PaymentResult(
                approved=False, method=method, amount=0, reference=reference,
                message="Bu ödeme yöntemi tanımlı değil.",
                failure_kind=FailureKind.NOT_SUPPORTED,
            )
        try:
            return adapter.void(reference)
        except Exception:
            log.exception("Ödeme iptali başarısız: %s ref=%s", method, reference)
            return PaymentResult(
                approved=False, method=method, amount=0, reference=reference,
                message="Ödeme iptali yapılamadı.",
                failure_kind=FailureKind.DEVICE_ERROR,
            )
