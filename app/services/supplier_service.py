"""Tedarikçiler.

Tedarikçi OPSİYONELDİR: günlük işi hiçbir yerde zorunlu kılmaz. Kaydedildiğinde
alış geçmişi, harcama tutarı ve son maliyetler üzerinden ileride sipariş
önerisi üretilebilir.
"""
from __future__ import annotations

import sqlite3

from app.core.clock import now_utc
from app.core.db import Database
from app.core.tr import normalize_name, tr_sort_key


class SupplierService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def all(self, only_active: bool = True) -> list[sqlite3.Row]:
        sql = "SELECT * FROM suppliers"
        if only_active:
            sql += " WHERE active = 1"
        return sorted(self.db.query(sql), key=lambda r: tr_sort_key(r["name"]))

    def get(self, supplier_id: int) -> sqlite3.Row | None:
        return self.db.query_one("SELECT * FROM suppliers WHERE id = ?", (supplier_id,))

    def create(
        self,
        name: str,
        phone: str | None = None,
        contact: str | None = None,
        notes: str | None = None,
    ) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("Tedarikçi adı boş olamaz")
        now = now_utc()
        with self.db.transaction() as conn:
            return conn.execute(
                "INSERT INTO suppliers(name, name_norm, phone, contact, notes, "
                "  created_at_utc, updated_at_utc) VALUES(?,?,?,?,?,?,?)",
                (name, normalize_name(name), phone, contact, notes, now, now),
            ).lastrowid

    def ensure(self, name: str | None) -> int | None:
        name = (name or "").strip()
        if not name:
            return None
        row = self.db.query_one(
            "SELECT id FROM suppliers WHERE name_norm = ?", (normalize_name(name),)
        )
        return row["id"] if row else self.create(name)

    def update(self, supplier_id: int, **fields) -> None:
        if not fields:
            return
        if "name" in fields:
            fields["name_norm"] = normalize_name(fields["name"])
        fields["updated_at_utc"] = now_utc()
        atama = ", ".join(f"{k} = ?" for k in fields)
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE suppliers SET {atama} WHERE id = ?",
                [*fields.values(), supplier_id],
            )

    def set_active(self, supplier_id: int, active: bool) -> None:
        self.update(supplier_id, active=int(bool(active)))

    def summary(self, supplier_id: int) -> dict:
        """Tedarikçi özeti: kaç sevkiyat, ne kadar harcama, son ne zaman."""
        row = self.db.query_one(
            "SELECT COUNT(*) AS fis_sayisi, COALESCE(SUM(total_cost), 0) AS toplam, "
            "       MAX(receipt_date) AS son_tarih "
            "  FROM purchase_receipts "
            " WHERE supplier_id = ? AND status = 'COMMITTED'",
            (supplier_id,),
        )
        return {
            "fis_sayisi": row["fis_sayisi"] if row else 0,
            "toplam_tutar": row["toplam"] if row else 0,
            "son_tarih": row["son_tarih"] if row else None,
        }

    def products(self, supplier_id: int, limit: int = 100) -> list[sqlite3.Row]:
        """Bu tedarikçiden gelen ürünler ve son alış fiyatları."""
        return self.db.query(
            "SELECT p.id, p.name, p.current_stock, p.last_purchase_cost, "
            "       MAX(r.receipt_date) AS son_alis "
            "  FROM purchase_receipt_lines l "
            "  JOIN purchase_receipts r ON r.id = l.receipt_id "
            "  JOIN products p ON p.id = l.product_id "
            " WHERE r.supplier_id = ? AND r.status = 'COMMITTED' "
            " GROUP BY p.id ORDER BY p.name_norm LIMIT ?",
            (supplier_id, max(1, min(500, limit))),
        )
