"""Alan modelleri: sabitler, sayılabilir türler ve veri taşıyıcıları.

Buradaki dataclass'lar servis katmanının arayüze döndürdüğü SONUÇLARDIR.
Arayüz bunları yalnızca ÇİZER: karar vermez, hesap yapmaz, SQL yazmaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


# =========================== Sabitler =====================================
class MovementType:
    INITIAL_STOCK = "INITIAL_STOCK"
    PURCHASE = "PURCHASE"
    PURCHASE_REVERSAL = "PURCHASE_REVERSAL"
    SALE = "SALE"
    SALE_REVERSAL = "SALE_REVERSAL"
    COUNT_ADJUSTMENT = "COUNT_ADJUSTMENT"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    RETURN = "RETURN"
    WASTE = "WASTE"

    #: Stoğa mal GİREN türler — delik kapatma kuralı bunlara uygulanır.
    INBOUND = frozenset(
        {INITIAL_STOCK, PURCHASE, RETURN}
    )
    #: Stoktan mal ÇIKAN türler.
    OUTBOUND = frozenset({SALE, WASTE})


class RefType:
    SALE = "SALE"
    RECEIPT = "RECEIPT"
    COUNT = "COUNT"
    MANUAL = "MANUAL"
    INITIAL = "INITIAL"


class BarcodeType:
    UNIT = "UNIT"
    PACK = "PACK"
    CASE = "CASE"
    ALTERNATE = "ALTERNATE"


BARCODE_TYPE_LABELS = {
    BarcodeType.UNIT: "Tekli",
    BarcodeType.PACK: "Paket",
    BarcodeType.CASE: "Koli",
    BarcodeType.ALTERNATE: "Diğer",
}


class SaleMode:
    QUICK = "HIZLI"
    CART = "SEPET"


class EntryType:
    SALE = "SALE"
    SALE_REVERSAL = "SALE_REVERSAL"


class PaymentMethod:
    CASH = "NAKIT"
    CARD = "KART"
    CREDIT = "VERESIYE"       # V1'de kullanılmaz; şema yeri hazır
    OTHER = "DIGER"


class CoverageState:
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    UNCOUNTED = "UNCOUNTED"


class StockState(IntEnum):
    """``products.stock_state`` üretilmiş sütununun değerleri."""

    NORMAL = 0
    LOW = 1
    CRITICAL = 2
    NEEDS_CHECK = 3        # negatif stok
    NOT_COUNTED = 4        # henüz sayılmadı — "az stok" DEĞİLDİR


STOCK_STATE_LABELS = {
    StockState.NORMAL: "Normal",
    StockState.LOW: "Düşük",
    StockState.CRITICAL: "Kritik",
    StockState.NEEDS_CHECK: "Stok Kontrolü Gerekli",
    StockState.NOT_COUNTED: "Henüz Sayılmadı",
}


# =========================== Veri taşıyıcıları ============================
@dataclass(frozen=True, slots=True)
class BarcodeMatch:
    """Okutulan barkodun çözümü.

    ``quantity`` DAİMA temel birimdedir; arayüz çarpanı kendisi uygulamaz.
    """

    product_id: int
    product_name: str
    quantity: int
    barcode: str
    barcode_type: str
    multiplier: int
    sale_price: int | None
    is_active: bool

    @property
    def needs_pack_confirm(self) -> bool:
        """Koli/paket barkodu satışta sessizce 24 adet satmamalıdır."""
        return self.multiplier > 1


@dataclass(frozen=True, slots=True)
class MovementResult:
    movement_id: int
    product_id: int
    quantity_delta: int
    value_delta: int
    balance_after: int
    cost_total: int
    unit_cost: int
    is_estimated_cost: bool
    fill_quantity: int


@dataclass(frozen=True, slots=True)
class SaleLineResult:
    product_id: int
    product_name: str
    quantity: int
    unit_price: int
    line_total: int
    cost_total: int
    is_estimated_cost: bool
    stock_after: int


@dataclass(frozen=True, slots=True)
class SaleResult:
    """Tamamlanmış bir satış — arayüzün göstereceği her şey burada."""

    sale_id: int
    sale_mode: str
    total_amount: int
    total_cost: int
    item_count: int
    business_date: str
    lines: list[SaleLineResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def gross_profit(self) -> int:
        return self.total_amount - self.total_cost

    @property
    def single_line(self) -> SaleLineResult | None:
        return self.lines[0] if len(self.lines) == 1 else None


@dataclass(frozen=True, slots=True)
class ReversalPreview:
    """Fiş geri alma denemesinin sonucu — pencere yalnızca bunu çizer."""

    allowed: bool
    receipt_id: int
    blocking: list[tuple[str, int, str]] = field(default_factory=list)

    @property
    def blocking_names(self) -> list[str]:
        return [name for name, _, _ in self.blocking]


@dataclass(frozen=True, slots=True)
class CountCommitResult:
    """Sayım onayının sonucu.

    ``skipped_partial`` — ürün birden fazla yerde bulunuyor ama hepsi
    sayılmadı; stok BİLEREK değiştirilmedi.
    ``skipped_changed`` — sayım sürerken ürünün stoğu değişti; hayalet
    düzeltme üretmemek için atlandı.
    """

    session_id: int
    applied: list[tuple[str, int]] = field(default_factory=list)
    skipped_partial: list[tuple[str, list[str]]] = field(default_factory=list)
    skipped_changed: list[str] = field(default_factory=list)
    uncounted: list[str] = field(default_factory=list)
    baseline_count: int = 0
    total_diff_qty: int = 0
    total_diff_value: int = 0

    @property
    def applied_count(self) -> int:
        return len(self.applied)
