"""Analiz: panel özetleri ve temel raporlar.

Tüm gruplamalar ``business_date`` (donmuş iş günü) üzerinden yapılır; asla
sorgu anında yerel saate çevrilmez. Böylece "gün başlangıcı" ayarı ileride
değişse bile geçmiş raporlar OLDUĞU GİBİ kalır.

Günlük toplamlar ``daily_sales_rollup`` ve ``product_daily_sales`` özet
tablolarından okunur: milyonlarca satış satırı taranmaz.

KESİN ve TAHMİNİ veri asla karıştırılmaz: sepet satışları gerçek müşteri
sepetidir; Hızlı Satış'tan türetilen gruplar yalnızca TAHMİNDİR ve öyle
etiketlenir.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta

from app.core.clock import shift_days
from app.core.db import Database
from app.core.tr import DATE_FORMAT


@dataclass(frozen=True, slots=True)
class PeriodSummary:
    """Bir dönemin satış özeti."""

    start: str
    end: str
    revenue: int = 0
    cost: int = 0
    item_count: int = 0
    sale_count: int = 0

    @property
    def gross_profit(self) -> int:
        return self.revenue - self.cost

    @property
    def margin_percent(self) -> float:
        return (self.gross_profit / self.revenue * 100) if self.revenue else 0.0


@dataclass(frozen=True, slots=True)
class DashboardData:
    """Panelin gösterdiği her şey — arayüz yalnızca çizer."""

    today: PeriodSummary
    stock_value: int = 0
    attention: dict = field(default_factory=dict)
    top_products: list = field(default_factory=list)
    advisories: list = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PaymentBreakdown:
    """Ödeme yöntemine göre ciro kırılımı.

    Her kova AYRI sayılır. ``kaydedilmemis`` YALNIZCA ``payment_method IS NULL``
    satırlardır — ödeme seçimi eklenmeden önce yazılmış satışlar. Veresiye ve
    Diğer, "bilinmiyor" ile ASLA karıştırılmaz.
    """

    nakit: int = 0
    kart: int = 0
    veresiye: int = 0
    diger: int = 0
    kaydedilmemis: int = 0

    @property
    def total(self) -> int:
        return self.nakit + self.kart + self.veresiye + self.diger + self.kaydedilmemis

    def percent(self, amount: int) -> float:
        return (amount / self.total * 100) if self.total else 0.0

    def buckets(self) -> list[tuple[str, int, float]]:
        """(etiket, tutar, yüzde) — yalnızca DOLU kovalar, büyükten küçüğe.

        Boş kovalar gizlenir ki panel gereksiz sıfır satırıyla dolmasın; ama
        dolu olan her kova kendi adıyla görünür.
        """
        from app.core.models import PAYMENT_LABELS, PaymentMethod

        ham = [
            (PAYMENT_LABELS[PaymentMethod.CASH], self.nakit),
            (PAYMENT_LABELS[PaymentMethod.CARD], self.kart),
            (PAYMENT_LABELS[PaymentMethod.CREDIT], self.veresiye),
            (PAYMENT_LABELS[PaymentMethod.OTHER], self.diger),
            (PAYMENT_LABELS[None], self.kaydedilmemis),
        ]
        dolu = [(ad, tutar) for ad, tutar in ham if tutar]
        dolu.sort(key=lambda item: item[1], reverse=True)
        return [(ad, tutar, self.percent(tutar)) for ad, tutar in dolu]


@dataclass(frozen=True, slots=True)
class BasketSummary:
    """KESİN sepet (Sepetli Satış) özeti.

    Hızlı Satış işlemleri buraya GİRMEZ: onlar tek tek satış olaylarıdır,
    müşteri sepeti değildir.
    """

    basket_count: int = 0
    revenue: int = 0
    item_count: int = 0

    @property
    def avg_basket_value(self) -> int:
        return round(self.revenue / self.basket_count) if self.basket_count else 0

    @property
    def avg_items_per_basket(self) -> float:
        return (self.item_count / self.basket_count) if self.basket_count else 0.0


@dataclass(frozen=True, slots=True)
class SalesFirstDashboardData:
    """SALES_FIRST panelinin gösterdiği her şey.

    Kâr ve maliyet BİLEREK YOKTUR: stoksuz satış serbest olduğu için birçok
    satışın maliyeti tahminidir; panelde kesin bir kâr rakamı göstermek
    yanıltıcı olurdu. Kâr Yönetim ekranlarında kalır.
    """

    business_date: str = ""
    revenue: int = 0
    item_count: int = 0
    sale_count: int = 0
    basket: BasketSummary = field(default_factory=BasketSummary)
    payments: PaymentBreakdown = field(default_factory=PaymentBreakdown)
    top_products: list = field(default_factory=list)
    hourly: list = field(default_factory=list)
    comparison: list = field(default_factory=list)


class AnalyticsService:
    def __init__(self, db: Database, settings, inventory, products) -> None:
        self.db = db
        self.settings = settings
        self.inventory = inventory
        self.products = products

    # ===================== Dönem özetleri ================================
    def summary(self, start: str, end: str) -> PeriodSummary:
        """İki iş günü arasındaki (dâhil) satış özeti — özet tablosundan."""
        row = self.db.query_one(
            "SELECT COALESCE(SUM(total_amount), 0) AS ciro, "
            "       COALESCE(SUM(total_cost), 0)   AS maliyet, "
            "       COALESCE(SUM(item_count), 0)   AS adet, "
            "       COALESCE(SUM(sale_count), 0)   AS islem "
            "  FROM daily_sales_rollup WHERE business_date BETWEEN ? AND ?",
            (start, end),
        )
        return PeriodSummary(
            start=start, end=end,
            revenue=row["ciro"], cost=row["maliyet"],
            item_count=row["adet"], sale_count=row["islem"],
        )

    def today(self) -> PeriodSummary:
        gun = self.settings.calendar().today()
        return self.summary(gun, gun)

    def last_days(self, days: int) -> PeriodSummary:
        bugun = self.settings.calendar().today()
        return self.summary(shift_days(bugun, -(days - 1)), bugun)

    def daily_series(self, start: str, end: str) -> list[sqlite3.Row]:
        """Grafik için gün gün ciro/kâr."""
        return self.db.query(
            "SELECT business_date, total_amount, total_cost, item_count, sale_count "
            "  FROM daily_sales_rollup WHERE business_date BETWEEN ? AND ? "
            " ORDER BY business_date",
            (start, end),
        )

    # ===================== Ürün / grup kırılımları =======================
    def top_products(self, start: str, end: str, limit: int = 10) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT p.id, p.name, SUM(d.quantity) AS adet, SUM(d.amount) AS ciro, "
            "       SUM(d.amount) - SUM(d.cost) AS kar "
            "  FROM product_daily_sales d JOIN products p ON p.id = d.product_id "
            " WHERE d.business_date BETWEEN ? AND ? "
            " GROUP BY p.id HAVING adet > 0 ORDER BY adet DESC, ciro DESC LIMIT ?",
            (start, end, max(1, min(100, limit))),
        )

    def by_group(
        self, start: str, end: str, group: str = "category", limit: int = 20
    ) -> list[sqlite3.Row]:
        """Kategori / marka / ürün ailesi kırılımı."""
        eslesme = {
            "category": ("categories", "p.category_id"),
            "brand": ("brands", "p.brand_id"),
            "family": ("product_families", "p.family_id"),
        }
        if group not in eslesme:
            raise ValueError(f"bilinmeyen gruplama: {group}")
        tablo, alan = eslesme[group]
        return self.db.query(
            f"SELECT g.id, g.name, SUM(d.quantity) AS adet, SUM(d.amount) AS ciro, "
            f"       SUM(d.amount) - SUM(d.cost) AS kar "
            f"  FROM product_daily_sales d "
            f"  JOIN products p ON p.id = d.product_id "
            f"  JOIN {tablo} g ON g.id = {alan} "
            f" WHERE d.business_date BETWEEN ? AND ? "
            f" GROUP BY g.id ORDER BY ciro DESC LIMIT ?",
            (start, end, max(1, min(100, limit))),
        )

    # ===================== Zaman kırılımları =============================
    def by_hour(self, start: str, end: str) -> list[tuple[int, int, int]]:
        """(saat, ciro, işlem) — gün başlangıç saatinden itibaren sıralı.

        Saat GERÇEK saattir (``local_hour``); yalnızca gösterim sırası iş günü
        başlangıcına göre döndürülür ki gece satışları listenin sonunda görünsün.
        """
        rows = self.db.query(
            "SELECT local_hour, COALESCE(SUM(total_amount), 0) AS ciro, COUNT(*) AS islem "
            "  FROM sales WHERE entry_type = 'SALE' AND business_date BETWEEN ? AND ? "
            " GROUP BY local_hour",
            (start, end),
        )
        veri = {row["local_hour"]: (row["ciro"], row["islem"]) for row in rows}
        baslangic = self.settings.current_business_day_start_hour()
        sira = [(baslangic + i) % 24 for i in range(24)]
        return [(saat, *veri.get(saat, (0, 0))) for saat in sira]

    def by_weekday(self, start: str, end: str) -> list[tuple[int, int, int]]:
        """(gün, ciro, işlem) — 0 = Pazartesi, iş gününden türetilmiştir."""
        rows = self.db.query(
            "SELECT local_dow, COALESCE(SUM(total_amount), 0) AS ciro, COUNT(*) AS islem "
            "  FROM sales WHERE entry_type = 'SALE' AND business_date BETWEEN ? AND ? "
            " GROUP BY local_dow",
            (start, end),
        )
        veri = {row["local_dow"]: (row["ciro"], row["islem"]) for row in rows}
        return [(gun, *veri.get(gun, (0, 0))) for gun in range(7)]

    # ===================== Stok analizleri ===============================
    def stock_value(self) -> int:
        """Eldeki malın toplam maliyeti (bağlı sermaye)."""
        return self.inventory.stock_value_total()

    def slow_movers(self, days: int | None = None, limit: int = 50) -> list[sqlite3.Row]:
        """Uzun süredir satılmayan, stoğu olan ürünler ve bağlı sermaye.

        Yeni tanımlanmış ürünler haksız yere listelenmez: ilk stok girişinden
        beri en az o kadar gün geçmiş olmalıdır.
        """
        gun = days or self.settings.slow_moving_days()
        from app.core.clock import local_now

        esik = int((local_now() - timedelta(days=gun)).timestamp())
        return self.db.query(
            "SELECT id, name, current_stock, stock_value, last_sale_at_utc, "
            "       first_stocked_at_utc "
            "  FROM products "
            " WHERE is_active = 1 AND current_stock > 0 "
            "   AND (last_sale_at_utc IS NULL OR last_sale_at_utc < ?) "
            "   AND (first_stocked_at_utc IS NULL OR first_stocked_at_utc < ?) "
            " ORDER BY stock_value DESC LIMIT ?",
            (esik, esik, max(1, min(500, limit))),
        )

    def dead_capital(self, days: int | None = None) -> int:
        return sum(row["stock_value"] for row in self.slow_movers(days, limit=500))

    def product_performance(self, product_id: int, days: int = 30) -> dict:
        """Ürün detay ekranındaki 'Son 30 gün' özeti."""
        bugun = self.settings.calendar().today()
        baslangic = shift_days(bugun, -(days - 1))
        row = self.db.query_one(
            "SELECT COALESCE(SUM(quantity), 0) AS adet, "
            "       COALESCE(SUM(amount), 0)   AS ciro, "
            "       COALESCE(SUM(cost), 0)     AS maliyet "
            "  FROM product_daily_sales "
            " WHERE product_id = ? AND business_date BETWEEN ? AND ?",
            (product_id, baslangic, bugun),
        )
        adet = row["adet"]
        return {
            "gun": days,
            "adet": adet,
            "ciro": row["ciro"],
            "maliyet": row["maliyet"],
            "kar": row["ciro"] - row["maliyet"],
            "gunluk_ortalama": adet / days if days else 0.0,
        }

    def days_of_stock(self, product_id: int, days: int = 30) -> float | None:
        """Kaç günlük stok kaldı? (Sipariş planlamasının temeli.)"""
        performans = self.product_performance(product_id, days)
        hiz = performans["gunluk_ortalama"]
        if hiz <= 0:
            return None
        urun = self.products.get(product_id)
        return (urun["current_stock"] / hiz) if urun else None

    # ===================== Panel =========================================
    def dashboard(self) -> DashboardData:
        """Panelin ihtiyacı olan her şey tek çağrıda."""
        bugun = self.settings.calendar().today()
        return DashboardData(
            today=self.summary(bugun, bugun),
            stock_value=self.stock_value(),
            attention=self.products.attention_counts(),
            top_products=self.top_products(bugun, bugun, limit=5),
            advisories=self.db.advisories(),
        )

    # ===================== Ödeme kırılımı ================================
    def payment_breakdown(self, start: str, end: str) -> PaymentBreakdown:
        """Ödeme yöntemine göre ciro — her kova AÇIKÇA sayılır.

        ``toplam − nakit − kart`` gibi bir çıkarma BİLEREK kullanılmaz: bugün
        doğru görünür ama ileride bir VERESIYE ya da DIGER satışı yazıldığı an
        o tutar sessizce "Kaydedilmemiş" diye etiketlenirdi.

        ``entry_type`` filtresi yoktur: ters kayıtlar negatif tutar taşıdığı
        için kovalar kendiliğinden netleşir. ``daily_sales_rollup`` yalnızca
        nakit/kart kovası tanıdığı için bu ayrımı YAPAMAZ; yetkili kaynak
        ``sales`` tablosudur.
        """
        row = self.db.query_one(
            "SELECT "
            "  COALESCE(SUM(CASE WHEN payment_method = 'NAKIT'    "
            "            THEN total_amount ELSE 0 END), 0) AS nakit, "
            "  COALESCE(SUM(CASE WHEN payment_method = 'KART'     "
            "            THEN total_amount ELSE 0 END), 0) AS kart, "
            "  COALESCE(SUM(CASE WHEN payment_method = 'VERESIYE' "
            "            THEN total_amount ELSE 0 END), 0) AS veresiye, "
            "  COALESCE(SUM(CASE WHEN payment_method = 'DIGER'    "
            "            THEN total_amount ELSE 0 END), 0) AS diger, "
            "  COALESCE(SUM(CASE WHEN payment_method IS NULL      "
            "            THEN total_amount ELSE 0 END), 0) AS kaydedilmemis "
            "  FROM sales WHERE business_date BETWEEN ? AND ?",
            (start, end),
        )
        return PaymentBreakdown(
            nakit=row["nakit"], kart=row["kart"], veresiye=row["veresiye"],
            diger=row["diger"], kaydedilmemis=row["kaydedilmemis"],
        )

    # ===================== Sepet özeti ===================================
    def basket_summary(self, start: str, end: str) -> BasketSummary:
        """KESİN sepet istatistikleri: yalnızca Sepetli Satış, geri alınmamış."""
        row = self.db.query_one(
            "SELECT COUNT(*) AS adet, "
            "       COALESCE(SUM(total_amount), 0) AS ciro, "
            "       COALESCE(SUM(item_count), 0)   AS kalem "
            "  FROM sales "
            " WHERE entry_type = 'SALE' AND sale_mode = 'SEPET' "
            "   AND is_reversed = 0 AND business_date BETWEEN ? AND ?",
            (start, end),
        )
        return BasketSummary(
            basket_count=row["adet"], revenue=row["ciro"], item_count=row["kalem"]
        )

    def comparison(self) -> list[tuple[str, PeriodSummary]]:
        """Bugün / dün / geçen hafta aynı gün — hızlı kıyas için."""
        bugun = self.settings.calendar().today()
        return [
            ("Bugün", self.summary(bugun, bugun)),
            ("Dün", self._day(shift_days(bugun, -1))),
            ("Geçen hafta aynı gün", self._day(shift_days(bugun, -7))),
        ]

    def _day(self, gun: str) -> PeriodSummary:
        return self.summary(gun, gun)

    # ===================== SALES_FIRST paneli ============================
    def sales_first_dashboard(self) -> SalesFirstDashboardData:
        """Satış odaklı panelin ihtiyacı olan her şey tek çağrıda.

        Kâr ve maliyet BİLEREK dönülmez; bkz. ``SalesFirstDashboardData``.
        """
        gun = self.settings.calendar().today()
        ozet = self.summary(gun, gun)
        return SalesFirstDashboardData(
            business_date=gun,
            revenue=ozet.revenue,
            item_count=ozet.item_count,
            sale_count=ozet.sale_count,
            basket=self.basket_summary(gun, gun),
            payments=self.payment_breakdown(gun, gun),
            top_products=self.top_products(gun, gun, limit=5),
            hourly=self.by_hour(gun, gun),
            comparison=self.comparison(),
        )

    # ===================== Kesin sepet verisi ============================
    def exact_baskets(
        self, start: str, end: str, limit: int = 500
    ) -> list[tuple[int, list[int]]]:
        """KESİN sepet bileşimleri: ``(sale_id, [product_id, ...])``.

        Gelecekteki ürün birlikteliği analizinin VERİ TEMELİDİR. V1.1'de
        arayüzde kullanılmaz ve hiçbir istatistik üretilmez — burada yalnızca
        ham veriye erişim vardır.

        YALNIZCA Sepetli Satış sayılır: Hızlı Satış'tan türetilen gruplar
        TAHMİNİDİR ve kesin sepet verisiyle asla karıştırılmaz.
        """
        rows = self.db.query(
            "SELECT i.sale_id, i.product_id FROM sale_items i "
            "  JOIN sales s ON s.id = i.sale_id "
            " WHERE s.entry_type = 'SALE' AND s.sale_mode = 'SEPET' "
            "   AND s.is_reversed = 0 AND s.business_date BETWEEN ? AND ? "
            " ORDER BY i.sale_id, i.line_no",
            (start, end),
        )
        sepetler: dict[int, list[int]] = {}
        for row in rows:
            sepetler.setdefault(row["sale_id"], []).append(row["product_id"])
            if len(sepetler) > max(1, limit):
                break
        return list(sepetler.items())[: max(1, limit)]

    def exact_basket_count(self, start: str, end: str) -> int:
        """KESİN sepet sayısı: yalnızca Sepetli Satış işlemleri.

        Hızlı Satış'tan türetilen gruplar TAHMİNİDİR ve buraya karışmaz.
        İleride yapılacak sepet analizinin veri temeli budur.
        """
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM sales WHERE entry_type = 'SALE' "
                "  AND sale_mode = 'SEPET' AND business_date BETWEEN ? AND ?",
                (start, end), default=0,
            )
        )
