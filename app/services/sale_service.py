"""Satış çekirdeği: Hızlı Satış, Sepetli Satış ve geri alma.

İki satış kipi de AYNI çekirdeği kullanır; fark yalnızca ne zaman
işlendiğidir:

* **Hızlı Satış** — her okutma ANINDA ve atomik olarak işlenir. Sepet yok,
  tamamla düğmesi yok. Müşteri 10 bira alıyorsa aynı şişe 10 kez okutulur.
* **Sepetli Satış** — satırlar taslakta birikir; stok ve ciro yalnızca
  "Satışı Tamamla" ile, tek bir işlemde değişir.

Geri alma FİZİKSEL SİLME DEĞİLDİR: ters kayıt (contra) satırı yazılır.
Ters kayıt NEGATİF tutar taşır, böylece ``SUM(total_amount)`` hiçbir filtre
gerektirmeden doğrudur.

Atomiklik: bir satış ya tamamen olur ya hiç olmaz. "Ciro arttı ama stok
düşmedi" ya da "stok düştü ama satış kaydı yok" durumu MÜMKÜN DEĞİLDİR.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

from app.core.clock import TimeStamp
from app.core.db import Database
from app.core.errors import (
    BosSepet,
    FiyatiYokUrun,
    PasifUrun,
    SatisBulunamadi,
    ZatenGeriAlinmis,
)
from app.core.models import (
    EntryType,
    MovementType,
    PaymentMethod,
    RefType,
    SaleLineResult,
    SaleMode,
    SaleResult,
)
from app.core.money import format_tl

log = logging.getLogger(__name__)


@dataclass(slots=True)
class SaleLineSpec:
    """Satılacak tek satır. ``quantity`` DAİMA temel birimdedir."""

    product_id: int
    quantity: int = 1
    barcode_used: str | None = None
    multiplier: int = 1
    line_discount: int = 0


class SaleService:
    def __init__(self, db: Database, settings, inventory, audit) -> None:
        self.db = db
        self.settings = settings
        self.inventory = inventory
        self.audit = audit

    # ===================== Satış =========================================
    def quick_sale(
        self,
        product_id: int,
        quantity: int = 1,
        barcode_used: str | None = None,
        multiplier: int = 1,
    ) -> SaleResult:
        """Hızlı Satış: okut → satıldı. Tek işlemde tamamlanır."""
        return self.commit_sale(
            [SaleLineSpec(product_id, quantity, barcode_used, multiplier)],
            mode=SaleMode.QUICK,
        )

    def commit_sale(
        self,
        lines: list[SaleLineSpec],
        mode: str = SaleMode.CART,
        payment_method: str | None = None,
        discount_total: int = 0,
        rounding_adjustment: int = 0,
        note: str | None = None,
    ) -> SaleResult:
        """Satışı ATOMİK olarak kaydeder.

        Adım sırası bilinçlidir: önce ``sales`` satırı (yabancı anahtar
        ebeveyni), sonra satırlar ve stok hareketleri, sonra toplamlar, sonra
        özet tabloları. Herhangi bir adım patlarsa hiçbiri kalmaz.
        """
        if not lines:
            raise BosSepet()

        stamp = self.settings.calendar().stamp()
        with self.db.transaction() as conn:
            sale_id = self._insert_sale_header(conn, mode, stamp, payment_method, note)

            toplam_tutar = 0
            toplam_maliyet = 0
            toplam_adet = 0
            sonuclar: list[SaleLineResult] = []
            uyarilar: list[str] = []

            for sira, line in enumerate(lines, start=1):
                # Ürün satırı HER SATIR İÇİN işlem içinde yeniden okunur:
                # aynı üründen iki satır varsa havuzu sırayla tüketmelidirler,
                # yoksa sıfırı geçen ikinci satırın maliyeti yanlış çıkar.
                urun = self.inventory.product_row(line.product_id, conn)
                if urun is None:
                    raise SatisBulunamadi()
                if not urun["is_active"]:
                    raise PasifUrun(urun["name"])
                if urun["sale_price"] is None:
                    raise FiyatiYokUrun(urun["name"])

                adet = int(line.quantity)
                birim_fiyat = int(urun["sale_price"])
                satir_tutar = birim_fiyat * adet - int(line.line_discount)

                hareket = self.inventory.apply_movement(
                    conn,
                    line.product_id,
                    MovementType.SALE,
                    -adet,
                    stamp,
                    ref_type=RefType.SALE,
                    ref_id=sale_id,
                )

                kalem_id = conn.execute(
                    "INSERT INTO sale_items(sale_id, line_no, product_id, "
                    "  product_name_snapshot, quantity, unit_price, line_discount, "
                    "  line_total, cost_total, unit_cost, is_estimated_cost, vat_rate, "
                    "  barcode_used, barcode_multiplier) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        sale_id, sira, line.product_id, urun["name"], adet,
                        birim_fiyat, int(line.line_discount), satir_tutar,
                        hareket.cost_total, hareket.unit_cost,
                        int(hareket.is_estimated_cost),
                        self._vat_rate(conn, line.product_id),
                        line.barcode_used, max(1, int(line.multiplier)),
                    ),
                ).lastrowid

                conn.execute(
                    "UPDATE stock_movements SET ref_line_id = ? WHERE id = ?",
                    (kalem_id, hareket.movement_id),
                )

                toplam_tutar += satir_tutar
                toplam_maliyet += hareket.cost_total
                toplam_adet += adet
                sonuclar.append(
                    SaleLineResult(
                        product_id=line.product_id,
                        product_name=urun["name"],
                        quantity=adet,
                        unit_price=birim_fiyat,
                        line_total=satir_tutar,
                        cost_total=hareket.cost_total,
                        is_estimated_cost=hareket.is_estimated_cost,
                        stock_after=hareket.balance_after,
                    )
                )

                # Stok tutmuyorsa satış ENGELLENMEZ — kasa durmaz. Uyarı verilir
                # ve ürün "Stok Kontrolü Gerekli" listesine kendiliğinden düşer.
                if hareket.balance_after < 0:
                    uyarilar.append(
                        f"{urun['name']}: stok {hareket.balance_after} görünüyor, "
                        "sayım gerekebilir."
                    )

            toplam_tutar = toplam_tutar - int(discount_total) + int(rounding_adjustment)
            conn.execute(
                "UPDATE sales SET total_amount = ?, total_cost = ?, item_count = ?, "
                "  discount_total = ?, rounding_adjustment = ? WHERE id = ?",
                (toplam_tutar, toplam_maliyet, toplam_adet,
                 int(discount_total), int(rounding_adjustment), sale_id),
            )

            self._apply_rollups(
                conn, stamp.business_date, sonuclar, toplam_tutar, toplam_maliyet,
                toplam_adet, payment_method, sale_count_delta=1,
            )

            self.audit.record(
                "SATIS",
                f"{toplam_adet} adet ürün satıldı, toplam {format_tl(toplam_tutar)}.",
                "sale", sale_id, conn=conn,
            )

            return SaleResult(
                sale_id=sale_id,
                sale_mode=mode,
                total_amount=toplam_tutar,
                total_cost=toplam_maliyet,
                item_count=toplam_adet,
                business_date=stamp.business_date,
                lines=sonuclar,
                warnings=uyarilar,
            )

    def _insert_sale_header(
        self,
        conn: sqlite3.Connection,
        mode: str,
        stamp: TimeStamp,
        payment_method: str | None,
        note: str | None,
    ) -> int:
        return conn.execute(
            "INSERT INTO sales(entry_type, sale_mode, created_at_utc, local_date, "
            "  local_hour, local_dow, business_date, payment_method, note) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (
                EntryType.SALE, mode, stamp.created_at_utc, stamp.local_date,
                stamp.local_hour, stamp.local_dow, stamp.business_date,
                payment_method, note,
            ),
        ).lastrowid

    def _vat_rate(self, conn: sqlite3.Connection, product_id: int) -> int | None:
        row = conn.execute(
            "SELECT vat_rate FROM products WHERE id = ?", (product_id,)
        ).fetchone()
        return None if row is None else row["vat_rate"]

    # ===================== Geri alma =====================================
    def reverse_sale(self, sale_id: int, note: str | None = None) -> SaleResult:
        """Satışı TERS KAYITLA geri alır. Orijinal kayıt silinmez.

        "İki kez geri alınamaz" garantisi koddan değil veritabanından gelir:
        ``ux_sales_one_reversal`` kısmi tekil indeksi ikinci denemeyi reddeder.
        Burada koşullu INSERT kullanılır, böylece önce-SELECT-sonra-INSERT
        yarışı da oluşmaz.
        """
        stamp = self.settings.calendar().stamp()
        with self.db.transaction() as conn:
            orijinal = conn.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            ).fetchone()
            if orijinal is None:
                raise SatisBulunamadi()
            if orijinal["entry_type"] != EntryType.SALE:
                raise SatisBulunamadi()

            try:
                cursor = conn.execute(
                    "INSERT INTO sales(entry_type, sale_mode, created_at_utc, local_date, "
                    "  local_hour, local_dow, business_date, total_amount, total_cost, "
                    "  item_count, discount_total, rounding_adjustment, payment_method, "
                    "  reverses_sale_id, note) "
                    "SELECT 'SALE_REVERSAL', o.sale_mode, ?, ?, ?, ?, ?, "
                    "       -o.total_amount, -o.total_cost, -o.item_count, "
                    "       -o.discount_total, -o.rounding_adjustment, o.payment_method, "
                    "       o.id, ? "
                    "  FROM sales o WHERE o.id = ? AND o.entry_type = 'SALE'",
                    (
                        stamp.created_at_utc, stamp.local_date, stamp.local_hour,
                        stamp.local_dow, stamp.business_date, note, sale_id,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ZatenGeriAlinmis() from exc
            if cursor.rowcount == 0:
                raise SatisBulunamadi()
            ters_id = cursor.lastrowid

            kalemler = conn.execute(
                "SELECT * FROM sale_items WHERE sale_id = ? ORDER BY line_no", (sale_id,)
            ).fetchall()
            sonuclar: list[SaleLineResult] = []

            for kalem in kalemler:
                orijinal_hareket = conn.execute(
                    "SELECT id FROM stock_movements "
                    " WHERE ref_type = 'SALE' AND ref_id = ? AND ref_line_id = ?",
                    (sale_id, kalem["id"]),
                ).fetchone()

                hareket = self.inventory.apply_movement(
                    conn,
                    kalem["product_id"],
                    MovementType.SALE_REVERSAL,
                    kalem["quantity"],
                    stamp,
                    ref_type=RefType.SALE,
                    ref_id=ters_id,
                    reverses_movement_id=(
                        orijinal_hareket["id"] if orijinal_hareket else None
                    ),
                )

                ters_kalem_id = conn.execute(
                    "INSERT INTO sale_items(sale_id, line_no, product_id, "
                    "  product_name_snapshot, quantity, unit_price, line_discount, "
                    "  line_total, cost_total, unit_cost, is_estimated_cost, vat_rate, "
                    "  barcode_used, barcode_multiplier) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        ters_id, kalem["line_no"], kalem["product_id"],
                        kalem["product_name_snapshot"], -kalem["quantity"],
                        kalem["unit_price"], -kalem["line_discount"],
                        -kalem["line_total"], -kalem["cost_total"], kalem["unit_cost"],
                        kalem["is_estimated_cost"], kalem["vat_rate"],
                        kalem["barcode_used"], kalem["barcode_multiplier"],
                    ),
                ).lastrowid
                conn.execute(
                    "UPDATE stock_movements SET ref_line_id = ? WHERE id = ?",
                    (ters_kalem_id, hareket.movement_id),
                )

                sonuclar.append(
                    SaleLineResult(
                        product_id=kalem["product_id"],
                        product_name=kalem["product_name_snapshot"],
                        quantity=-kalem["quantity"],
                        unit_price=kalem["unit_price"],
                        line_total=-kalem["line_total"],
                        cost_total=-kalem["cost_total"],
                        is_estimated_cost=bool(kalem["is_estimated_cost"]),
                        stock_after=hareket.balance_after,
                    )
                )

            conn.execute("UPDATE sales SET is_reversed = 1 WHERE id = ?", (sale_id,))

            # Özet tabloları ORİJİNAL satışın iş gününde düşülür, BUGÜNDE DEĞİL.
            # Aksi hâlde o gün şişkin kalır ve bugün hayalet bir eksi görünür.
            self._apply_rollups(
                conn, orijinal["business_date"], sonuclar,
                -orijinal["total_amount"], -orijinal["total_cost"],
                -orijinal["item_count"], orijinal["payment_method"],
                sale_count_delta=-1,
            )
            self._refresh_last_sale(conn, [k["product_id"] for k in kalemler])

            self.audit.record(
                "SATIS_GERI_ALMA",
                f"{format_tl(orijinal['total_amount'])} tutarındaki satış geri alındı.",
                "sale", sale_id, conn=conn,
            )

            return SaleResult(
                sale_id=ters_id,
                sale_mode=orijinal["sale_mode"],
                total_amount=-orijinal["total_amount"],
                total_cost=-orijinal["total_cost"],
                item_count=-orijinal["item_count"],
                business_date=orijinal["business_date"],
                lines=sonuclar,
            )

    def reverse_last_sale(self) -> SaleResult:
        """F8: son satışı geri al. Zaten geri alınmışsa bir öncekine GEÇMEZ."""
        row = self.db.query_one(
            "SELECT id, is_reversed FROM sales WHERE entry_type = 'SALE' "
            " ORDER BY id DESC LIMIT 1"
        )
        if row is None:
            raise SatisBulunamadi()
        if row["is_reversed"]:
            raise ZatenGeriAlinmis()
        return self.reverse_sale(row["id"])

    def _refresh_last_sale(self, conn: sqlite3.Connection, product_ids: list[int]) -> None:
        """Geri alınan satış o ürünün SON satışı olabilir; damga tazelenir."""
        for product_id in dict.fromkeys(product_ids):
            conn.execute(
                "UPDATE products SET last_sale_at_utc = ("
                "  SELECT MAX(s.created_at_utc) FROM sale_items i "
                "    JOIN sales s ON s.id = i.sale_id "
                "   WHERE i.product_id = ? AND s.entry_type = 'SALE' "
                "     AND s.is_reversed = 0) WHERE id = ?",
                (product_id, product_id),
            )

    # ===================== Özet tabloları ================================
    def _apply_rollups(
        self,
        conn: sqlite3.Connection,
        business_date: str,
        lines: list[SaleLineResult],
        total_amount: int,
        total_cost: int,
        item_count: int,
        payment_method: str | None,
        sale_count_delta: int,
    ) -> None:
        """Günlük özetleri satışla AYNI işlemde günceller.

        Panel ve analiz bu tablolar sayesinde milyonlarca satırı taramaz.
        """
        for line in lines:
            conn.execute(
                "INSERT INTO product_daily_sales(business_date, product_id, quantity, "
                "  amount, cost, sale_count) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(business_date, product_id) DO UPDATE SET "
                "  quantity = quantity + excluded.quantity, "
                "  amount = amount + excluded.amount, "
                "  cost = cost + excluded.cost, "
                "  sale_count = sale_count + excluded.sale_count",
                (
                    business_date, line.product_id, line.quantity,
                    line.line_total, line.cost_total,
                    1 if sale_count_delta > 0 else -1,
                ),
            )

        nakit = total_amount if payment_method == PaymentMethod.CASH else 0
        kart = total_amount if payment_method == PaymentMethod.CARD else 0
        conn.execute(
            "INSERT INTO daily_sales_rollup(business_date, sale_count, total_amount, "
            "  total_cost, item_count, cash_amount, card_amount) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(business_date) DO UPDATE SET "
            "  sale_count = sale_count + excluded.sale_count, "
            "  total_amount = total_amount + excluded.total_amount, "
            "  total_cost = total_cost + excluded.total_cost, "
            "  item_count = item_count + excluded.item_count, "
            "  cash_amount = cash_amount + excluded.cash_amount, "
            "  card_amount = card_amount + excluded.card_amount",
            (business_date, sale_count_delta, total_amount, total_cost,
             item_count, nakit, kart),
        )

    # ===================== Okuma =========================================
    def recent(self, limit: int = 20) -> list[sqlite3.Row]:
        """Hızlı Satış ekranındaki son satışlar listesi — SAYFALI."""
        return self.db.query(
            "SELECT s.*, ("
            "  SELECT i.product_name_snapshot FROM sale_items i "
            "   WHERE i.sale_id = s.id ORDER BY i.line_no LIMIT 1) AS ilk_urun "
            "  FROM sales s WHERE s.entry_type = 'SALE' "
            " ORDER BY s.id DESC LIMIT ?",
            (max(1, min(200, limit)),),
        )

    def sale(self, sale_id: int) -> sqlite3.Row | None:
        return self.db.query_one("SELECT * FROM sales WHERE id = ?", (sale_id,))

    def items(self, sale_id: int) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM sale_items WHERE sale_id = ? ORDER BY line_no", (sale_id,)
        )

    def last_sale(self) -> sqlite3.Row | None:
        return self.db.query_one(
            "SELECT * FROM sales WHERE entry_type = 'SALE' ORDER BY id DESC LIMIT 1"
        )
