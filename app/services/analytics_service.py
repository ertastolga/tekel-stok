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

    # ===================== Kesin sepet verisi ============================
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
