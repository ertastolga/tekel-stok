"""Maliyet motoru: hareketli ağırlıklı ortalama, tam sayı kuruş, sürüklenmesiz.

Ürün başına ``avg_cost`` SAKLANMAZ. Bunun yerine iki tam sayı tutulur:

    S = current_stock   (temel birim adedi)
    V = stock_value     (elde kalan malın toplam maliyeti, kuruş)

Ortalama daima ``V / S`` olarak TÜRETİLİR. Yuvarlanmış bir ortalamayı saklamak,
her satışta birkaç kuruşluk artık bırakır ve zamanla stok bittiği hâlde değer
kalmasına yol açar.

İki kural bu modülün tamamını açıklar
-------------------------------------

1) **Oransal tam sayı çekimi.** Çıkan mal, birim başına çarpma ile değil,
   havuzdan oransal olarak düşülür::

       cost = (2*q*V + S) // (2*S)          # yarım-yukarı yuvarlama

   ``q == S`` iken sonuç TAM OLARAK ``V``'dir; yani stok bittiğinde değer
   kalıntısız sıfırlanır. (``q * round(V/S)`` bunu sağlamaz: V=1000, S=3, q=3
   için 999 verir ve 1 kuruş hayalet değer bırakır.)

2) **Delik kapatma.** Stok negatifken gelen mal önce açığı kapatır ve o birimler
   stok değerine GİRMEZ; çünkü maliyetleri, açığı yaratan satışlarda zaten
   (tahmini olarak) gider yazılmıştır ve geçmiş dondurulmuştur::

       q_fill      = min(q, max(0, -S))
       value_delta = (q - q_fill) * unit_cost

   Örnek: S=-5, V=0 iken 10 adet x 50 TL alış -> S=5 ve V=250 TL (500 TL değil),
   ortalama 50 TL. ``S >= 0`` iken ``q_fill = 0`` olur, kural tek biçimlidir.

Değişmez
--------
``stock_value >= 0`` ve ``current_stock <= 0 => stock_value = 0``.
Sınırlama, ``value_delta`` ÜRETİLİRKEN uygulanır — asla toplandıktan sonra
değil. Aksi hâlde ``stock_value`` defterin katlaması olmaktan çıkar ve
``SUM(value_delta)`` ile yeniden hesaplama imkânsızlaşır.
"""
from __future__ import annotations

from dataclasses import dataclass

# Maliyet temelinin nereden geldiği — kullanıcıya "tahmini" demek için gerekir.
SOURCE_POOL = "ORTALAMA"          # eldeki maldan türetildi (kesin)
SOURCE_LAST_AVG = "SON_ORTALAMA"  # stok yok; son bilinen ortalama
SOURCE_LAST_PURCHASE = "SON_ALIS"  # stok yok; son alış fiyatı
SOURCE_NONE = "YOK"               # hiçbir maliyet bilgisi yok


@dataclass(frozen=True, slots=True)
class CostBasis:
    """Bir ürünün o andaki birim maliyet temeli."""

    unit_cost: int
    is_estimated: bool
    source: str

    @property
    def is_known(self) -> bool:
        return self.source != SOURCE_NONE


@dataclass(frozen=True, slots=True)
class MovementValue:
    """Bir stok hareketinin değer sonuçları.

    ``value_delta``  -> ``stock_value``'ya eklenecek işaretli tutar (defter).
    ``cost_total``   -> o hareketin EKONOMİK maliyeti (satışta COGS).
    ``fill_quantity``-> negatif stok deliğini kapatan birim sayısı.

    Negatif stokta bu iki sayı BİLEREK ayrışır: satılan malın bir maliyeti
    vardır (kâr raporu için), ama çıkarılacak bir değer kalmamıştır (defter için).
    """

    value_delta: int
    cost_total: int
    fill_quantity: int
    unit_cost: int
    is_estimated: bool


def average_cost(current_stock: int, stock_value: int) -> int | None:
    """Eldeki malın birim ortalama maliyeti (kuruş). Stok yoksa ``None``."""
    if current_stock > 0 and stock_value > 0:
        return (2 * stock_value + current_stock) // (2 * current_stock)
    return None


def cost_basis(
    current_stock: int,
    stock_value: int,
    last_avg_cost: int | None = None,
    last_purchase_cost: int | None = None,
) -> CostBasis:
    """Ürünün o anki birim maliyet temeli ve güvenilirliği.

    Sıra: eldeki havuz -> son bilinen ortalama -> son alış fiyatı -> bilinmiyor.
    İlk seçenek dışındakiler TAHMİNİDİR ve rapor bunu dürüstçe söyler.
    """
    pooled = average_cost(current_stock, stock_value)
    if pooled is not None:
        return CostBasis(pooled, False, SOURCE_POOL)
    if last_avg_cost is not None and last_avg_cost > 0:
        return CostBasis(int(last_avg_cost), True, SOURCE_LAST_AVG)
    if last_purchase_cost is not None and last_purchase_cost > 0:
        return CostBasis(int(last_purchase_cost), True, SOURCE_LAST_PURCHASE)
    return CostBasis(0, True, SOURCE_NONE)


def withdrawal_cost(quantity: int, current_stock: int, stock_value: int) -> int:
    """Havuzdan ``quantity`` birim çıkarmanın maliyeti (oransal, tam sayı).

    ``quantity`` en fazla ``current_stock`` kadar olabilir; çağıran bunu
    sağlar. ``quantity == current_stock`` iken sonuç tam olarak ``stock_value``
    olur — kalıntı bırakmaz.
    """
    if quantity <= 0 or current_stock <= 0 or stock_value <= 0:
        return 0
    if quantity >= current_stock:
        return stock_value
    return (2 * quantity * stock_value + current_stock) // (2 * current_stock)


def inbound_value(
    quantity: int,
    current_stock: int,
    unit_cost: int,
    is_estimated: bool = False,
) -> MovementValue:
    """Giren mal: önce negatif açığı kapatır, kalanı değere eklenir.

    ``INITIAL_STOCK``, ``PURCHASE``, pozitif ``COUNT_ADJUSTMENT``, ``RETURN`` ve
    pozitif ``MANUAL_ADJUSTMENT`` için TEK kural budur.
    """
    if quantity <= 0:
        raise ValueError("inbound_value pozitif miktar bekler")
    unit_cost = max(0, int(unit_cost))
    fill = min(quantity, max(0, -current_stock))
    valued = quantity - fill
    delta = valued * unit_cost
    return MovementValue(
        value_delta=delta,
        cost_total=delta,
        fill_quantity=fill,
        unit_cost=unit_cost,
        is_estimated=is_estimated,
    )


def outbound_value(
    quantity: int,
    current_stock: int,
    stock_value: int,
    fallback: CostBasis,
) -> MovementValue:
    """Çıkan mal: havuzdan oransal düşülür, havuzu aşan kısım tahmini maliyetlenir.

    ``SALE``, ``WASTE``, negatif ``COUNT_ADJUSTMENT`` ve negatif
    ``MANUAL_ADJUSTMENT`` için TEK kural budur.

    Havuz tükendiğinde (sıfır ya da negatif stokta satış) defterden düşülecek
    değer kalmaz — ``value_delta`` sıfırlanır — ama satışın ekonomik maliyeti
    ``cost_total`` içinde tahmini olarak korunur. Bu ayrım, negatif stokta bile
    ``stock_value >= 0`` değişmezini bozmadan kâr raporu üretebilmeyi sağlar.
    """
    if quantity <= 0:
        raise ValueError("outbound_value pozitif miktar bekler")

    from_pool = min(quantity, max(0, current_stock)) if stock_value > 0 else 0
    pool_cost = withdrawal_cost(from_pool, current_stock, stock_value)
    pool_cost = min(pool_cost, max(0, stock_value))

    beyond = quantity - from_pool
    beyond_cost = beyond * fallback.unit_cost

    covered_cost = pool_cost + beyond_cost
    unit = covered_cost // quantity if quantity else 0
    return MovementValue(
        value_delta=-pool_cost,
        cost_total=covered_cost,
        fill_quantity=0,
        unit_cost=unit,
        is_estimated=bool(beyond) or (from_pool == 0 and fallback.is_estimated),
    )


def reversal_value(original_value_delta: int) -> int:
    """Ters kaydın değer etkisi: orijinalin tam simetriği.

    Neden ``+SUM(cost_total)`` değil? Orijinal hareket sıfır stokta sınırlanmış
    olabilir; yalnızca defter simetrisi, her şeyi geri aldığınızda
    ``stock_value``'nun başlangıç değerine dönmesini garanti eder.
    """
    return -int(original_value_delta)
