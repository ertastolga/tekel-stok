"""Elle onaylanan ödemeler — V1.1'in tamamı.

Nakit: para kasaya girer, onay dükkân sahibinin kendisidir.
Kart: fiş bankanın kendi terminalinden çekilir; bu uygulama yalnızca hangi
yöntemle ödendiğini KAYDEDER, parayı tahsil etmez.

Her ikisi de anında onaylar. Fiziksel terminal entegrasyonu geldiğinde
``ManualCardAdapter`` yerine o adaptör kaydedilir; satış ekranı değişmez.
"""
from __future__ import annotations

from app.core.models import PaymentMethod
from app.payments.base import BaseAdapter, PaymentRequest, PaymentResult


class ManualCashAdapter(BaseAdapter):
    """Nakit: her zaman onaylanır."""

    name = PaymentMethod.CASH
    supports_void = False

    def authorize(self, request: PaymentRequest) -> PaymentResult:
        return PaymentResult(
            approved=True,
            method=PaymentMethod.CASH,
            amount=request.amount,
            reference=None,
        )


class ManualCardAdapter(BaseAdapter):
    """Kart: bankanın kendi terminalinde çekilir, burada yalnızca kaydedilir.

    V1.1'de hiçbir fiziksel cihazla konuşmaz; bu yüzden anında onaylar ve
    ``reference`` üretmez.
    """

    name = PaymentMethod.CARD
    supports_void = False

    def authorize(self, request: PaymentRequest) -> PaymentResult:
        return PaymentResult(
            approved=True,
            method=PaymentMethod.CARD,
            amount=request.amount,
            reference=None,
        )
