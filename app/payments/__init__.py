"""Ödeme adaptörleri.

Amaç: ileride fiziksel bir POS terminali eklendiğinde satış ekranına
dokunmamak. Arayüz yalnızca ``PaymentService.authorize()`` çağırır; hangi
adaptörün çalıştığını bilmez.

Qt'suzdur ve veritabanı bilmez — tamamen başsız test edilebilir.
"""
from app.payments.base import (
    PaymentAdapter,
    PaymentRequest,
    PaymentResult,
    FailureKind,
)
from app.payments.manual import ManualCardAdapter, ManualCashAdapter
from app.payments.service import PaymentService

__all__ = [
    "PaymentAdapter",
    "PaymentRequest",
    "PaymentResult",
    "FailureKind",
    "ManualCashAdapter",
    "ManualCardAdapter",
    "PaymentService",
]
