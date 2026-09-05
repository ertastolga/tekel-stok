"""Stok defteri: her stok değişiminin TEK kapısı.

``apply_movement()`` şu üç sütunun **tek yazarıdır**::

    products.current_stock
    products.stock_value
    stock_movements.balance_after

Hiçbir başka servis bunlara dokunmaz. Bunun sebebi tek bir cümlede özetlenir:
``stock_value`` defterin (``SUM(value_delta)``) basit bir katlamasıdır ve öyle
kalmalıdır, aksi hâlde bozulduğunda defterden onarılamaz.

Bu yüzden değer sınırlaması (``clamp``) DAİMA ``value_delta`` üretilirken
uygulanır — asla toplandıktan sonra değil.
"""
from __future__ import annotations

import logging
import sqlite3

from app.core import costing
from app.core.clock import BusinessCalendar, TimeStamp
from app.core.costing import CostBasis
from app.core.db import Database
from app.core.models import MovementResult, MovementType, RefType

log = logging.getLogger(__name__)

#: Bu türlerde birim maliyet ZORUNLUDUR — "sihirli" bir maliyet uydurulmaz.
_REQUIRES_UNIT_COST = frozenset(
    {MovementType.INITIAL_STOCK, MovementType.PURCHASE, MovementType.MANUAL_ADJUSTMENT}
)


class InventoryService:
    def __init__(self, db: Database, settings) -> None:
        self.db = db
        self.settings = settings

    # -- Okuma -------------------------------------------------------------
    def product_row(self, product_id: int, conn: sqlite3.Connection | None = None):
        """Ürünün stok/maliyet durumu — DAİMA işlem içinde okunmalıdır.

        Arayüzün önbelleklediği eski satır kullanılırsa, başka bir pencerede
        yapılan fiyat/stok değişikliğiyle yarış oluşur.
        """
        sql = (
            "SELECT id, name, current_stock, stock_value, last_avg_cost, "
            "       last_purchase_cost, stock_initialized_at_utc, is_active, sale_price "
            "  FROM products WHERE id = ?"
        )
        if conn is not None:
            return conn.execute(sql, (product_id,)).fetchone()
        return self.db.query_one(sql, (product_id,))

    def cost_basis(self, product_id: int, conn: sqlite3.Connection | None = None) -> CostBasis:
        """Ürünün o anki birim maliyet temeli.

        Arayüz ASLA ``stock_value / current_stock`` bölmesi yapmaz; bu değeri
        buradan alır ve ``is_estimated`` bayrağını dürüstçe gösterir.
        """
        row = self.product_row(product_id, conn)
        if row is None:
            return costing.cost_basis(0, 0)
        return costing.cost_basis(
            row["current_stock"],
            row["stock_value"],
            row["last_avg_cost"],
            row["last_purchase_cost"],
        )

    def average_cost(self, product_id: int) -> int | None:
        row = self.product_row(product_id)
        if row is None:
            return None
        return costing.average_cost(row["current_stock"], row["stock_value"])

    def ledger(self, product_id: int, limit: int = 50, offset: int = 0) -> list[sqlite3.Row]:
        """Ürünün stok hareketleri — SAYFALI.

        Yılların geçmişi asla tek seferde belleğe alınmaz. Sıralama ``id``
        iledir, zaman damgasıyla değil (makine saati geri alınmış olabilir).
        """
        return self.db.query(
            "SELECT * FROM stock_movements WHERE product_id = ? "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            (product_id, max(1, min(500, limit)), max(0, offset)),
        )

    def movement(self, movement_id: int, conn: sqlite3.Connection | None = None):
        sql = "SELECT * FROM stock_movements WHERE id = ?"
        if conn is not None:
            return conn.execute(sql, (movement_id,)).fetchone()
        return self.db.query_one(sql, (movement_id,))

    # -- Yazma: TEK KAPI ---------------------------------------------------
    def apply_movement(
        self,
        conn: sqlite3.Connection,
        product_id: int,
        movement_type: str,
        quantity_delta: int,
        stamp: TimeStamp,
        *,
        unit_cost: int | None = None,
        ref_type: str = RefType.MANUAL,
        ref_id: int | None = None,
        ref_line_id: int | None = None,
        reverses_movement_id: int | None = None,
        note: str | None = None,
        fallback_basis: CostBasis | None = None,
    ) -> MovementResult:
        """Bir stok hareketi yazar ve önbellekleri günceller.

        ÇAĞIRAN bir işlem (``BEGIN IMMEDIATE``) içinde olmak zorundadır: bu
        metot kendi işlemini AÇMAZ, çünkü satış/alış/sayım gibi çok adımlı
        işlemlerin parçasıdır ve onlarla birlikte geri alınabilmelidir.

        ``quantity_delta`` işaretlidir: giren mal artı, çıkan mal eksi.
        """
        if quantity_delta == 0:
            raise ValueError("apply_movement sıfır miktarla çağrılamaz")

        row = self.product_row(product_id, conn)
        if row is None:
            raise ValueError(f"Ürün bulunamadı: {product_id}")

        stock = int(row["current_stock"])
        value = int(row["stock_value"])
        quantity = abs(quantity_delta)

        if reverses_movement_id is not None:
            # Ters kayıt: orijinalin TAM SİMETRİĞİ. "+SUM(cost_total)" değil —
            # yalnızca defter simetrisi, her şeyi geri aldığınızda stok
            # değerinin başlangıç sayısına dönmesini garanti eder.
            original = self.movement(reverses_movement_id, conn)
            if original is None:
                raise ValueError(f"Ters alınacak hareket yok: {reverses_movement_id}")
            value_delta = costing.reversal_value(original["value_delta"])
            cost_total = abs(value_delta)
            fill = 0
            resolved_unit_cost = original["unit_cost"]
            estimated = bool(original["is_estimated_cost"])

        elif quantity_delta > 0:
            if unit_cost is None:
                if movement_type in _REQUIRES_UNIT_COST:
                    raise ValueError(f"{movement_type} için birim maliyet zorunludur")
                basis = fallback_basis or costing.cost_basis(
                    stock, value, row["last_avg_cost"], row["last_purchase_cost"]
                )
                unit_cost = basis.unit_cost
                estimated = basis.is_estimated
            else:
                estimated = False
            outcome = costing.inbound_value(quantity, stock, unit_cost, estimated)
            value_delta = outcome.value_delta
            cost_total = outcome.cost_total
            fill = outcome.fill_quantity
            resolved_unit_cost = outcome.unit_cost
            estimated = outcome.is_estimated

        else:
            basis = fallback_basis or costing.cost_basis(
                stock, value, row["last_avg_cost"], row["last_purchase_cost"]
            )
            if unit_cost is not None:
                basis = CostBasis(unit_cost, False, basis.source)
            outcome = costing.outbound_value(quantity, stock, value, basis)
            value_delta = outcome.value_delta
            cost_total = outcome.cost_total
            fill = outcome.fill_quantity
            resolved_unit_cost = outcome.unit_cost
            estimated = outcome.is_estimated

        balance_after = stock + quantity_delta
        new_value = value + value_delta

        # Savunma amaçlı son sınırlama. DEĞİŞMEZ: stok tükendiğinde değer de
        # tükenir. Düzeltme value_delta'nın KENDİSİNE yazılır ki defter ile
        # önbellek arasındaki eşitlik (I2) bozulmasın.
        if balance_after <= 0 and new_value != 0:
            value_delta -= new_value
            new_value = 0
        elif new_value < 0:
            value_delta -= new_value
            new_value = 0

        cursor = conn.execute(
            "INSERT INTO stock_movements("
            "  product_id, movement_type, quantity_delta, value_delta, unit_cost, "
            "  fill_quantity, is_estimated_cost, balance_after, ref_type, ref_id, "
            "  ref_line_id, reverses_movement_id, created_at_utc, business_date, note) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                product_id, movement_type, quantity_delta, value_delta,
                resolved_unit_cost, fill, int(bool(estimated)), balance_after,
                ref_type, ref_id, ref_line_id, reverses_movement_id,
                stamp.created_at_utc, stamp.business_date, note,
            ),
        )
        movement_id = cursor.lastrowid

        conn.execute(
            "UPDATE products SET current_stock = ?, stock_value = ?, updated_at_utc = ? "
            " WHERE id = ?",
            (balance_after, new_value, stamp.created_at_utc, product_id),
        )

        self._update_stamps(
            conn, product_id, movement_type, balance_after, new_value,
            resolved_unit_cost, stamp,
        )

        return MovementResult(
            movement_id=movement_id,
            product_id=product_id,
            quantity_delta=quantity_delta,
            value_delta=value_delta,
            balance_after=balance_after,
            cost_total=cost_total,
            unit_cost=resolved_unit_cost or 0,
            is_estimated_cost=bool(estimated),
            fill_quantity=fill,
        )

    def _update_stamps(
        self,
        conn: sqlite3.Connection,
        product_id: int,
        movement_type: str,
        balance_after: int,
        new_value: int,
        unit_cost: int | None,
        stamp: TimeStamp,
    ) -> None:
        """Analitik damgaları ve maliyet temeli yedeklerini günceller."""
        if movement_type in (MovementType.PURCHASE, MovementType.INITIAL_STOCK):
            average = costing.average_cost(balance_after, new_value)
            conn.execute(
                "UPDATE products SET last_purchase_cost = ?, "
                "  last_avg_cost = COALESCE(?, last_avg_cost), "
                "  last_purchase_at_utc = ?, "
                "  first_stocked_at_utc = COALESCE(first_stocked_at_utc, ?) "
                " WHERE id = ?",
                (unit_cost, average, stamp.created_at_utc,
                 stamp.created_at_utc, product_id),
            )

        if movement_type == MovementType.INITIAL_STOCK:
            # Başlangıç stoğu ürünü "sayılmış" yapar: artık 0 adet, gerçekten
            # sıfır demektir; "henüz sayılmadı" değil.
            conn.execute(
                "UPDATE products SET "
                "  stock_initialized_at_utc = COALESCE(stock_initialized_at_utc, ?), "
                "  stock_initialized_by = COALESCE(stock_initialized_by, 'INITIAL_STOCK') "
                " WHERE id = ?",
                (stamp.created_at_utc, product_id),
            )

        if movement_type == MovementType.SALE:
            conn.execute(
                "UPDATE products SET last_sale_at_utc = ? WHERE id = ?",
                (stamp.created_at_utc, product_id),
            )

    # -- Başlangıç stoğu ---------------------------------------------------
    def set_initial_stock(
        self,
        product_id: int,
        quantity: int,
        unit_cost: int,
        note: str | None = None,
    ) -> MovementResult | None:
        """Ürünün ilk (sayılmış) stoğunu kurar.

        ``quantity=0`` da geçerlidir ve anlamlıdır: "saydım, gerçekten sıfır".
        Bu durumda hareket yazılmaz ama ürün SAYILMIŞ olarak damgalanır — böylece
        "Henüz Sayılmadı" rozeti kalkar ve ürün Kritik listesine girer.
        """
        stamp = self.settings.calendar().stamp()
        with self.db.transaction() as conn:
            if quantity == 0:
                self.declare_zero_stock(conn, product_id, stamp.created_at_utc)
                return None
            return self.apply_movement(
                conn,
                product_id,
                MovementType.INITIAL_STOCK,
                quantity,
                stamp,
                unit_cost=unit_cost,
                ref_type=RefType.INITIAL,
                note=note or "Başlangıç stoğu",
            )

    @staticmethod
    def declare_zero_stock(
        conn: sqlite3.Connection, product_id: int, at_utc: int
    ) -> None:
        """"Saydım, gerçekten sıfır" — ürünü hareket üretmeden sayılmış yapar.

        Sıfır miktarlı bir stok hareketi yazılmaz (anlamsız olur ve şema da
        buna izin vermez); bu yüzden başlangıcın GEREKÇESİ sütunda saklanır,
        yoksa I27 denetimi haklı olarak "kaydı yok" derdi.
        """
        conn.execute(
            "UPDATE products SET "
            "  stock_initialized_at_utc = COALESCE(stock_initialized_at_utc, ?), "
            "  stock_initialized_by = COALESCE(stock_initialized_by, 'DECLARED_ZERO') "
            " WHERE id = ?",
            (at_utc, product_id),
        )

    def manual_adjustment(
        self,
        product_id: int,
        quantity_delta: int,
        unit_cost: int,
        reason: str,
    ) -> MovementResult:
        """Belgeli düzeltme — sahte bir geri alma yerine kullanılır.

        Birim maliyet çağırandan ZORUNLUDUR: kullanıcı ne çıkardığını ve hangi
        maliyetle çıkardığını açıkça söyler, sistem tahmin yürütmez.
        """
        stamp = self.settings.calendar().stamp()
        with self.db.transaction() as conn:
            return self.apply_movement(
                conn,
                product_id,
                MovementType.MANUAL_ADJUSTMENT,
                quantity_delta,
                stamp,
                unit_cost=unit_cost,
                ref_type=RefType.MANUAL,
                note=reason,
            )

    # -- Bakım -------------------------------------------------------------
    def recompute(self) -> None:
        self.db.recompute_caches()

    def stock_value_total(self) -> int:
        return int(self.db.scalar("SELECT COALESCE(SUM(stock_value), 0) FROM products", default=0))
