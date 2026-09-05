"""Stok Girişi (alış fişleri): taslak oturum, atomik onay, kanıtlanabilir geri alma.

Bir mal kabulü bir FİŞTİR. Operatör ürünleri okuturken hiçbir şey kalıcı
olmaz; fiş taslakta birikir ve yalnızca "Girişi Tamamla" ile tek işlemde
stoğa işlenir. Uygulama beklenmedik biçimde kapanırsa taslak kurtarılabilir
ama KENDİLİĞİNDEN tamamlanmaz.

Geri alma kuralı (önemli)
-------------------------
Miktarın negatife düşmemesi YETMEZ. Araya giren satış ve alışlardan sonra eski
bir fişi geri almak ortalama maliyeti bozar::

    10x50 al (V=500) -> 10x70 al (V=1200, ort. 60) -> 5 sat (V=900, S=15)
    ilk fişi geri al: -500 -> V=400, S=5 -> ort. 80   (doğrusu 350 / ort. 70)

Bu yüzden otomatik geri alma yalnızca KANITLANABİLİR olduğunda yapılır: fişteki
her ürün için, o fişin hareketinden sonra başka hiçbir stok hareketi olmamalı.
Bu koşulda ters kayıt stok ve değeri fiş öncesi hâline TAM olarak döndürür.

Koşul sağlanmıyorsa geri alma REDDEDİLİR ve kullanıcıya sahte bir geri alma
yerine "Düzeltme Girişi" önerilir. ``force`` gibi bir kaçış yolu YOKTUR.
"""
from __future__ import annotations

import logging
import sqlite3

from app.core.clock import now_utc
from app.core.db import Database
from app.core.errors import (
    BosFis,
    FisBulunamadi,
    FisZatenTamamlanmis,
    GeriAlmaKanitlanamaz,
)
from app.core.models import MovementType, RefType, ReversalPreview
from app.core.money import format_tl

log = logging.getLogger(__name__)


class PurchaseService:
    def __init__(self, db: Database, settings, inventory, audit) -> None:
        self.db = db
        self.settings = settings
        self.inventory = inventory
        self.audit = audit

    # ===================== Taslak ========================================
    def start_draft(
        self,
        supplier_id: int | None = None,
        invoice_no: str | None = None,
        receipt_date: str | None = None,
        note: str | None = None,
    ) -> int:
        now = now_utc()
        tarih = receipt_date or self.settings.calendar().today()
        with self.db.transaction() as conn:
            return conn.execute(
                "INSERT INTO purchase_receipts(status, supplier_id, invoice_no, "
                "  receipt_date, created_at_utc, note) VALUES('DRAFT',?,?,?,?,?)",
                (supplier_id, invoice_no, tarih, now, note),
            ).lastrowid

    def open_drafts(self) -> list[sqlite3.Row]:
        """Kurtarılabilir taslaklar. Açılışta kullanıcıya sorulur."""
        return self.db.query(
            "SELECT r.*, s.name AS tedarikci, "
            "  (SELECT COUNT(*) FROM purchase_receipt_lines l WHERE l.receipt_id = r.id) "
            "    AS satir_sayisi "
            "  FROM purchase_receipts r LEFT JOIN suppliers s ON s.id = r.supplier_id "
            " WHERE r.status = 'DRAFT' ORDER BY r.created_at_utc DESC"
        )

    def receipt(self, receipt_id: int) -> sqlite3.Row | None:
        return self.db.query_one(
            "SELECT * FROM purchase_receipts WHERE id = ?", (receipt_id,)
        )

    def lines(self, receipt_id: int) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT l.*, p.name FROM purchase_receipt_lines l "
            "  JOIN products p ON p.id = l.product_id "
            " WHERE l.receipt_id = ? ORDER BY l.line_no",
            (receipt_id,),
        )

    def last_purchase_cost(self, product_id: int) -> int | None:
        """Son alış fiyatı — giriş ekranında ÖN DOLDURULUR.

        Fiyat değişmediyse operatörün hiçbir şey yapması gerekmez; yalnızca
        değişen maliyetler dikkat ister.
        """
        row = self.db.query_one(
            "SELECT last_purchase_cost FROM products WHERE id = ?", (product_id,)
        )
        return None if row is None else row["last_purchase_cost"]

    def add_line(
        self,
        receipt_id: int,
        product_id: int,
        quantity: int,
        unit_cost: int | None = None,
        barcode_used: str | None = None,
        multiplier: int = 1,
    ) -> None:
        """Taslağa ürün ekler; aynı ürün tekrar okutulursa MEVCUT SATIR artar.

        Bu bir ARAYÜZ kolaylığıdır, şema kısıtı değil: gerçek bir irsaliyede
        aynı ürün iki farklı fiyatla iki satırda gelebilir ve şema buna izin
        verir (``UNIQUE(receipt_id, line_no)``).
        """
        with self.db.transaction() as conn:
            fis = conn.execute(
                "SELECT status FROM purchase_receipts WHERE id = ?", (receipt_id,)
            ).fetchone()
            if fis is None:
                raise FisBulunamadi()
            if fis["status"] != "DRAFT":
                raise FisZatenTamamlanmis()

            if unit_cost is None:
                unit_cost = self.last_purchase_cost(product_id) or 0

            mevcut = conn.execute(
                "SELECT * FROM purchase_receipt_lines "
                " WHERE receipt_id = ? AND product_id = ? AND unit_cost = ? "
                " ORDER BY line_no LIMIT 1",
                (receipt_id, product_id, unit_cost),
            ).fetchone()

            if mevcut is not None:
                yeni_adet = mevcut["quantity"] + quantity
                conn.execute(
                    "UPDATE purchase_receipt_lines SET quantity = ?, line_total = ? "
                    " WHERE id = ?",
                    (yeni_adet, yeni_adet * unit_cost, mevcut["id"]),
                )
            else:
                sira = (conn.execute(
                    "SELECT COALESCE(MAX(line_no), 0) + 1 FROM purchase_receipt_lines "
                    " WHERE receipt_id = ?", (receipt_id,)
                ).fetchone()[0])
                onceki = conn.execute(
                    "SELECT last_purchase_cost FROM products WHERE id = ?", (product_id,)
                ).fetchone()
                conn.execute(
                    "INSERT INTO purchase_receipt_lines(receipt_id, line_no, product_id, "
                    "  quantity, unit_cost, line_total, previous_unit_cost, barcode_used, "
                    "  barcode_multiplier) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        receipt_id, sira, product_id, quantity, unit_cost,
                        quantity * unit_cost,
                        onceki["last_purchase_cost"] if onceki else None,
                        barcode_used, max(1, int(multiplier)),
                    ),
                )
            self._refresh_totals(conn, receipt_id)

    def set_line_quantity(self, line_id: int, quantity: int) -> None:
        with self.db.transaction() as conn:
            satir = conn.execute(
                "SELECT * FROM purchase_receipt_lines WHERE id = ?", (line_id,)
            ).fetchone()
            if satir is None:
                return
            if quantity <= 0:
                conn.execute("DELETE FROM purchase_receipt_lines WHERE id = ?", (line_id,))
            else:
                conn.execute(
                    "UPDATE purchase_receipt_lines SET quantity = ?, line_total = ? "
                    " WHERE id = ?",
                    (quantity, quantity * satir["unit_cost"], line_id),
                )
            self._refresh_totals(conn, satir["receipt_id"])

    def set_line_cost(self, line_id: int, unit_cost: int) -> None:
        with self.db.transaction() as conn:
            satir = conn.execute(
                "SELECT * FROM purchase_receipt_lines WHERE id = ?", (line_id,)
            ).fetchone()
            if satir is None:
                return
            conn.execute(
                "UPDATE purchase_receipt_lines SET unit_cost = ?, line_total = ? "
                " WHERE id = ?",
                (unit_cost, satir["quantity"] * unit_cost, line_id),
            )
            self._refresh_totals(conn, satir["receipt_id"])

    def changed_cost_lines(self, receipt_id: int) -> list[sqlite3.Row]:
        """Alış fiyatı DEĞİŞEN satırlar — son incelemede vurgulanır."""
        return self.db.query(
            "SELECT l.*, p.name FROM purchase_receipt_lines l "
            "  JOIN products p ON p.id = l.product_id "
            " WHERE l.receipt_id = ? AND l.previous_unit_cost IS NOT NULL "
            "   AND l.previous_unit_cost <> l.unit_cost ORDER BY l.line_no",
            (receipt_id,),
        )

    def discard_draft(self, receipt_id: int) -> None:
        with self.db.transaction() as conn:
            fis = conn.execute(
                "SELECT status FROM purchase_receipts WHERE id = ?", (receipt_id,)
            ).fetchone()
            if fis is None or fis["status"] != "DRAFT":
                raise FisZatenTamamlanmis()
            conn.execute(
                "DELETE FROM purchase_receipt_lines WHERE receipt_id = ?", (receipt_id,)
            )
            conn.execute("DELETE FROM purchase_receipts WHERE id = ?", (receipt_id,))

    def _refresh_totals(self, conn: sqlite3.Connection, receipt_id: int) -> None:
        conn.execute(
            "UPDATE purchase_receipts SET "
            "  total_cost = (SELECT COALESCE(SUM(line_total), 0) "
            "                  FROM purchase_receipt_lines WHERE receipt_id = ?), "
            "  line_count = (SELECT COUNT(*) FROM purchase_receipt_lines "
            "                 WHERE receipt_id = ?) WHERE id = ?",
            (receipt_id, receipt_id, receipt_id),
        )

    # ===================== Onay ==========================================
    def commit(self, receipt_id: int) -> int:
        """Fişi ATOMİK olarak stoğa işler.

        Durum geçişi ÖNCE ve KOŞULLU yapılır: ``WHERE status='DRAFT'`` ile tek
        satır güncellenmezse hiç stoğa dokunulmadan hata verilir. Bu, aynı fişin
        iki kez işlenmesini yarış olmadan engeller.
        """
        stamp = self.settings.calendar().stamp()
        with self.db.transaction() as conn:
            guncellenen = conn.execute(
                "UPDATE purchase_receipts SET status = 'COMMITTED', committed_at_utc = ? "
                " WHERE id = ? AND status = 'DRAFT'",
                (stamp.created_at_utc, receipt_id),
            ).rowcount
            if guncellenen == 0:
                if self.receipt(receipt_id) is None:
                    raise FisBulunamadi()
                raise FisZatenTamamlanmis()

            satirlar = conn.execute(
                "SELECT * FROM purchase_receipt_lines WHERE receipt_id = ? "
                " ORDER BY line_no", (receipt_id,)
            ).fetchall()
            if not satirlar:
                raise BosFis()

            for satir in satirlar:
                # Önceki maliyet hareketten ÖNCE alınır; sonra alınsaydı yeni
                # maliyeti yakalar ve "değişti mi?" karşılaştırması bozulurdu.
                onceki = conn.execute(
                    "SELECT last_purchase_cost FROM products WHERE id = ?",
                    (satir["product_id"],),
                ).fetchone()["last_purchase_cost"]

                hareket = self.inventory.apply_movement(
                    conn, satir["product_id"], MovementType.PURCHASE,
                    satir["quantity"], stamp, unit_cost=satir["unit_cost"],
                    ref_type=RefType.RECEIPT, ref_id=receipt_id,
                    ref_line_id=satir["id"],
                )
                conn.execute(
                    "UPDATE purchase_receipt_lines SET previous_unit_cost = ? "
                    " WHERE id = ?",
                    (onceki, satir["id"]),
                )
                log.debug(
                    "Fiş %s: ürün %s +%s -> bakiye %s",
                    receipt_id, satir["product_id"], satir["quantity"],
                    hareket.balance_after,
                )

            self._refresh_totals(conn, receipt_id)
            toplam = conn.execute(
                "SELECT total_cost FROM purchase_receipts WHERE id = ?", (receipt_id,)
            ).fetchone()["total_cost"]
            self.audit.record(
                "STOK_GIRISI",
                f"{len(satirlar)} kalemlik stok girişi tamamlandı, "
                f"toplam {format_tl(toplam)}.",
                "receipt", receipt_id, conn=conn,
            )
            return receipt_id

    # ===================== Geri alma =====================================
    def reversal_preview(self, receipt_id: int) -> ReversalPreview:
        """Geri alma KANITLANABİLİR mi? Pencere yalnızca bu sonucu çizer.

        Kanıt koşulu: fişteki her ürün için, o fişin hareketinden sonra başka
        hiçbir stok hareketi olmamalı. Ancak o zaman ters kayıt stok ve değeri
        fiş öncesi hâline tam olarak döndürebilir.
        """
        fis = self.receipt(receipt_id)
        if fis is None:
            raise FisBulunamadi()

        engelleyen = self.db.query(
            "SELECT p.name, COUNT(x.id) AS sonraki, MIN(x.movement_type) AS ilk_tur "
            "  FROM stock_movements m "
            "  JOIN products p ON p.id = m.product_id "
            "  JOIN stock_movements x ON x.product_id = m.product_id AND x.id > m.id "
            " WHERE m.ref_type = 'RECEIPT' AND m.ref_id = ? "
            " GROUP BY p.id ORDER BY p.name_norm",
            (receipt_id,),
        )
        return ReversalPreview(
            allowed=not engelleyen,
            receipt_id=receipt_id,
            blocking=[(r["name"], r["sonraki"], r["ilk_tur"]) for r in engelleyen],
        )

    def reverse(self, receipt_id: int, note: str | None = None) -> int:
        """Fişi ters kayıtla geri alır — yalnızca kanıtlanabiliyorsa.

        ``force`` parametresi BİLEREK YOKTUR: miktarı negatife düşürmemek,
        değerlemenin doğru kalacağı anlamına gelmez. Kanıt yoksa kullanıcı
        "Düzeltme Girişi" (``InventoryService.manual_adjustment``) yapar.
        """
        onizleme = self.reversal_preview(receipt_id)
        if not onizleme.allowed:
            raise GeriAlmaKanitlanamaz(onizleme.blocking_names)

        fis = self.receipt(receipt_id)
        if fis["status"] != "COMMITTED":
            raise FisZatenTamamlanmis()

        stamp = self.settings.calendar().stamp()
        with self.db.transaction() as conn:
            try:
                ters_id = conn.execute(
                    "INSERT INTO purchase_receipts(status, supplier_id, invoice_no, "
                    "  receipt_date, created_at_utc, committed_at_utc, "
                    "  reverses_receipt_id, note) "
                    "SELECT 'COMMITTED', o.supplier_id, o.invoice_no, ?, ?, ?, o.id, ? "
                    "  FROM purchase_receipts o "
                    " WHERE o.id = ? AND o.status = 'COMMITTED' "
                    "   AND o.reverses_receipt_id IS NULL",
                    (stamp.business_date, stamp.created_at_utc, stamp.created_at_utc,
                     note, receipt_id),
                ).lastrowid
            except sqlite3.IntegrityError as exc:
                raise FisZatenTamamlanmis() from exc

            satirlar = conn.execute(
                "SELECT * FROM purchase_receipt_lines WHERE receipt_id = ? "
                " ORDER BY line_no", (receipt_id,)
            ).fetchall()

            for satir in satirlar:
                orijinal = conn.execute(
                    "SELECT id FROM stock_movements "
                    " WHERE ref_type = 'RECEIPT' AND ref_id = ? AND ref_line_id = ?",
                    (receipt_id, satir["id"]),
                ).fetchone()

                ters_satir = conn.execute(
                    "INSERT INTO purchase_receipt_lines(receipt_id, line_no, product_id, "
                    "  quantity, unit_cost, line_total, previous_unit_cost, barcode_used, "
                    "  barcode_multiplier) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        ters_id, satir["line_no"], satir["product_id"],
                        -satir["quantity"], satir["unit_cost"], -satir["line_total"],
                        satir["previous_unit_cost"], satir["barcode_used"],
                        satir["barcode_multiplier"],
                    ),
                ).lastrowid

                self.inventory.apply_movement(
                    conn, satir["product_id"], MovementType.PURCHASE_REVERSAL,
                    -satir["quantity"], stamp, ref_type=RefType.RECEIPT,
                    ref_id=ters_id, ref_line_id=ters_satir,
                    reverses_movement_id=orijinal["id"] if orijinal else None,
                )

                # Son alış fiyatı YALNIZCA hâlâ bu fişin bıraktığı değerse
                # geri alınır; sonradan başka bir fiş değiştirmişse tarihi
                # yeniden yazmayız.
                conn.execute(
                    "UPDATE products SET last_purchase_cost = ? "
                    " WHERE id = ? AND last_purchase_cost = ?",
                    (satir["previous_unit_cost"], satir["product_id"], satir["unit_cost"]),
                )

            self._refresh_totals(conn, ters_id)
            self.audit.record(
                "STOK_GIRISI_GERI_ALMA",
                f"{format_tl(fis['total_cost'])} tutarındaki stok girişi geri alındı.",
                "receipt", receipt_id, conn=conn,
            )
            return ters_id

    def is_reversed(self, receipt_id: int) -> bool:
        return bool(
            self.db.scalar(
                "SELECT COUNT(*) FROM purchase_receipts WHERE reverses_receipt_id = ?",
                (receipt_id,), default=0,
            )
        )

    # ===================== Geçmiş ========================================
    def history(
        self, supplier_id: int | None = None, limit: int = 50, offset: int = 0
    ) -> list[sqlite3.Row]:
        sql = (
            "SELECT r.*, s.name AS tedarikci FROM purchase_receipts r "
            "  LEFT JOIN suppliers s ON s.id = r.supplier_id "
            " WHERE r.status = 'COMMITTED'"
        )
        params: list = []
        if supplier_id is not None:
            sql += " AND r.supplier_id = ?"
            params.append(supplier_id)
        sql += " ORDER BY r.id DESC LIMIT ? OFFSET ?"
        params.extend([max(1, min(200, limit)), max(0, offset)])
        return self.db.query(sql, params)

    def product_purchase_history(self, product_id: int, limit: int = 20) -> list[sqlite3.Row]:
        """Ürünün alış geçmişi — maliyetler ASLA üzerine yazılmaz, hepsi durur."""
        return self.db.query(
            "SELECT l.*, r.receipt_date, r.id AS fis_id, s.name AS tedarikci "
            "  FROM purchase_receipt_lines l "
            "  JOIN purchase_receipts r ON r.id = l.receipt_id "
            "  LEFT JOIN suppliers s ON s.id = r.supplier_id "
            " WHERE l.product_id = ? AND r.status = 'COMMITTED' "
            " ORDER BY l.id DESC LIMIT ?",
            (product_id, max(1, min(200, limit))),
        )
