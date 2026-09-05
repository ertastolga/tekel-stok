"""Katalog: kategoriler, markalar, ürün aileleri, etiketler ve konumlar.

Bunlar ürünü SINIFLANDIRAN yapılardır; hiçbiri stok taşımaz.

Özellikle konumlar: bir ürün aynı anda birden fazla yerde bulunabilir
(yazın dolapta, kışın rafta, ayrıca depoda). Konum "nerede bulunur"
bilgisidir — konum değiştirmek stok hareketi DEĞİLDİR.
"""
from __future__ import annotations

import sqlite3

from app.core.clock import now_utc
from app.core.db import Database
from app.core.tr import normalize_name, tr_sort_key


class CatalogService:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ===================== Kategoriler ===================================
    def categories(self, only_active: bool = True) -> list[sqlite3.Row]:
        sql = "SELECT * FROM categories"
        if only_active:
            sql += " WHERE active = 1"
        sql += " ORDER BY IFNULL(parent_id, 0), sort_order, name_norm"
        return self.db.query(sql)

    def category_tree(self) -> list[tuple[sqlite3.Row, list[sqlite3.Row]]]:
        """(üst kategori, alt kategoriler) — arayüzün ağaç çizimi için."""
        rows = self.categories()
        parents = [r for r in rows if r["parent_id"] is None]
        children: dict[int, list[sqlite3.Row]] = {}
        for row in rows:
            if row["parent_id"] is not None:
                children.setdefault(row["parent_id"], []).append(row)
        return [(p, children.get(p["id"], [])) for p in parents]

    def category_path(self, category_id: int | None) -> str:
        """'Alkollü İçecekler > Bira' — ürün detayında gösterilir."""
        if category_id is None:
            return ""
        row = self.db.query_one("SELECT * FROM categories WHERE id = ?", (category_id,))
        if row is None:
            return ""
        if row["parent_id"] is None:
            return row["name"]
        parent = self.db.query_one(
            "SELECT name FROM categories WHERE id = ?", (row["parent_id"],)
        )
        return f"{parent['name']} > {row['name']}" if parent else row["name"]

    def descendant_category_ids(self, category_id: int) -> list[int]:
        """Kategori ve tüm alt kategorileri — filtreleme için."""
        rows = self.db.query(
            "SELECT id FROM categories WHERE id = ? OR parent_id = ?",
            (category_id, category_id),
        )
        return [row["id"] for row in rows]

    def add_category(self, name: str, parent_id: int | None = None) -> int:
        return self._insert_named("categories", name, extra={"parent_id": parent_id})

    def rename_category(self, category_id: int, name: str) -> None:
        self._rename("categories", category_id, name)

    # ===================== Markalar / aileler / etiketler =================
    def brands(self, only_active: bool = True) -> list[sqlite3.Row]:
        return self._named_rows("brands", only_active)

    def add_brand(self, name: str) -> int:
        return self._insert_named("brands", name)

    def families(self, only_active: bool = True) -> list[sqlite3.Row]:
        return self._named_rows("product_families", only_active)

    def add_family(self, name: str, brand_id: int | None = None) -> int:
        return self._insert_named("product_families", name, extra={"brand_id": brand_id})

    def tags(self, only_active: bool = True) -> list[sqlite3.Row]:
        return self._named_rows("tags", only_active)

    def add_tag(self, name: str) -> int:
        return self._insert_named("tags", name)

    def ensure_brand(self, name: str | None) -> int | None:
        """Marka adı verilirse bulur ya da oluşturur. Boşsa ``None``."""
        return self._ensure("brands", name)

    def ensure_family(self, name: str | None) -> int | None:
        return self._ensure("product_families", name)

    def ensure_tag(self, name: str | None) -> int | None:
        return self._ensure("tags", name)

    def tags_of(self, product_id: int) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT t.* FROM tags t JOIN product_tags pt ON pt.tag_id = t.id "
            "WHERE pt.product_id = ? ORDER BY t.name_norm",
            (product_id,),
        )

    def set_tags(self, product_id: int, tag_ids: list[int]) -> None:
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM product_tags WHERE product_id = ?", (product_id,))
            conn.executemany(
                "INSERT INTO product_tags(product_id, tag_id) VALUES(?,?)",
                [(product_id, tag_id) for tag_id in dict.fromkeys(tag_ids)],
            )

    # ===================== Konumlar ======================================
    def locations(self, only_active: bool = True) -> list[sqlite3.Row]:
        sql = "SELECT * FROM locations"
        if only_active:
            sql += " WHERE active = 1"
        sql += " ORDER BY sort_order, name_norm"
        return self.db.query(sql)

    def location(self, location_id: int) -> sqlite3.Row | None:
        return self.db.query_one("SELECT * FROM locations WHERE id = ?", (location_id,))

    def add_location(self, name: str, kind: str = "DIGER", is_cooled: bool = False) -> int:
        now = now_utc()
        with self.db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO locations(name, name_norm, type, is_cooled, sort_order, "
                "created_at_utc) VALUES(?,?,?,?,"
                "  (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM locations), ?)",
                (name.strip(), normalize_name(name), kind, int(bool(is_cooled)), now),
            )
            return cursor.lastrowid

    def rename_location(self, location_id: int, name: str) -> None:
        self._rename("locations", location_id, name)

    def deactivate_location(self, location_id: int) -> None:
        """Konumu kullanımdan kaldırır ve oradaki yerleşimleri de kapatır.

        Stok DEĞİŞMEZ — yalnızca "burada bulunur" bilgisi silinir.
        """
        now = now_utc()
        with self.db.transaction() as conn:
            conn.execute("UPDATE locations SET active = 0 WHERE id = ?", (location_id,))
            conn.execute(
                "UPDATE product_locations SET active = 0, is_primary = 0, "
                "  deactivated_at_utc = ? WHERE location_id = ? AND active = 1",
                (now, location_id),
            )

    # --- Ürün yerleşimleri (ÇOKTAN ÇOĞA) ---------------------------------
    def locations_of(self, product_id: int) -> list[sqlite3.Row]:
        """Ürünün şu an bulunduğu yerler; esas raf başta."""
        return self.db.query(
            "SELECT l.*, pl.is_primary FROM product_locations pl "
            "  JOIN locations l ON l.id = pl.location_id "
            " WHERE pl.product_id = ? AND pl.active = 1 "
            " ORDER BY pl.is_primary DESC, l.sort_order, l.name_norm",
            (product_id,),
        )

    def active_location_ids(
        self, product_id: int, conn: sqlite3.Connection | None = None
    ) -> set[int]:
        """Sayım kapsam hesabının temel girdisi."""
        sql = (
            "SELECT location_id FROM product_locations "
            " WHERE product_id = ? AND active = 1"
        )
        rows = (
            conn.execute(sql, (product_id,)).fetchall()
            if conn is not None
            else self.db.query(sql, (product_id,))
        )
        return {row["location_id"] for row in rows}

    def products_in_locations(self, location_ids: list[int]) -> list[int]:
        if not location_ids:
            return []
        yer = ",".join("?" * len(location_ids))
        rows = self.db.query(
            f"SELECT DISTINCT product_id FROM product_locations "
            f" WHERE active = 1 AND location_id IN ({yer})",
            location_ids,
        )
        return [row["product_id"] for row in rows]

    def add_product_location(
        self, product_id: int, location_id: int, is_primary: bool = False
    ) -> None:
        """Ürüne bir bulunma yeri ekler. TOPLAM STOK DEĞİŞMEZ."""
        now = now_utc()
        with self.db.transaction() as conn:
            self._add_product_location(conn, product_id, location_id, is_primary, now)

    def _add_product_location(
        self,
        conn: sqlite3.Connection,
        product_id: int,
        location_id: int,
        is_primary: bool,
        now: int,
    ) -> None:
        if is_primary:
            conn.execute(
                "UPDATE product_locations SET is_primary = 0 "
                " WHERE product_id = ? AND active = 1",
                (product_id,),
            )
        existing = conn.execute(
            "SELECT id FROM product_locations "
            " WHERE product_id = ? AND location_id = ? AND active = 1",
            (product_id, location_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE product_locations SET is_primary = ? WHERE id = ?",
                (int(bool(is_primary)), existing["id"]),
            )
            return
        conn.execute(
            "INSERT INTO product_locations(product_id, location_id, is_primary, "
            "  active_from_utc) VALUES(?,?,?,?)",
            (product_id, location_id, int(bool(is_primary)), now),
        )

    def remove_product_location(self, product_id: int, location_id: int) -> None:
        """Yerleşimi kapatır. TOPLAM STOK DEĞİŞMEZ — bu bir stok hareketi değildir."""
        now = now_utc()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE product_locations SET active = 0, is_primary = 0, "
                "  deactivated_at_utc = ? "
                " WHERE product_id = ? AND location_id = ? AND active = 1",
                (now, product_id, location_id),
            )

    def set_primary_location(self, product_id: int, location_id: int | None) -> None:
        now = now_utc()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE product_locations SET is_primary = 0 "
                " WHERE product_id = ? AND active = 1",
                (product_id,),
            )
            if location_id is not None:
                self._add_product_location(conn, product_id, location_id, True, now)

    def bulk_move(
        self,
        product_ids: list[int],
        add_location_ids: list[int] | None = None,
        remove_location_ids: list[int] | None = None,
    ) -> int:
        """Toplu yerleşim düzenleme — 20 ürünü tek tek açmaya gerek yok.

        Yine hiçbir stok hareketi üretmez.
        """
        now = now_utc()
        touched = 0
        with self.db.transaction() as conn:
            for product_id in product_ids:
                for location_id in remove_location_ids or []:
                    conn.execute(
                        "UPDATE product_locations SET active = 0, is_primary = 0, "
                        "  deactivated_at_utc = ? "
                        " WHERE product_id = ? AND location_id = ? AND active = 1",
                        (now, product_id, location_id),
                    )
                for location_id in add_location_ids or []:
                    self._add_product_location(conn, product_id, location_id, False, now)
                touched += 1
        return touched

    # ===================== Ortak yardımcılar =============================
    def _named_rows(self, table: str, only_active: bool) -> list[sqlite3.Row]:
        sql = f"SELECT * FROM {table}"
        if only_active:
            sql += " WHERE active = 1"
        rows = self.db.query(sql)
        return sorted(rows, key=lambda r: tr_sort_key(r["name"]))

    def _insert_named(self, table: str, name: str, extra: dict | None = None) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError(f"{table}: ad boş olamaz")
        fields = {"name": name, "name_norm": normalize_name(name),
                  "created_at_utc": now_utc()}
        fields.update({k: v for k, v in (extra or {}).items()})
        columns = ", ".join(fields)
        holders = ", ".join("?" * len(fields))
        with self.db.transaction() as conn:
            cursor = conn.execute(
                f"INSERT INTO {table}({columns}) VALUES({holders})", list(fields.values())
            )
            return cursor.lastrowid

    def _rename(self, table: str, row_id: int, name: str) -> None:
        name = (name or "").strip()
        if not name:
            raise ValueError("Ad boş olamaz")
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE {table} SET name = ?, name_norm = ? WHERE id = ?",
                (name, normalize_name(name), row_id),
            )

    def _ensure(self, table: str, name: str | None) -> int | None:
        name = (name or "").strip()
        if not name:
            return None
        norm = normalize_name(name)
        row = self.db.query_one(f"SELECT id FROM {table} WHERE name_norm = ?", (norm,))
        if row:
            return row["id"]
        return self._insert_named(table, name)
