"""Barkod çözümleme ve yönetimi.

Temel ilke: **barkod ürünü tanımlar, stoğu değil.** Bir ürünün birden çok
barkodu olabilir (tekli, paket, koli, eski ambalaj); ama bir barkod aynı anda
iki ürüne ait OLAMAZ.

Arayüz ham okuyucu metnini verir ve ``BarcodeMatch`` alır. Çarpanı
(``quantity_multiplier``) arayüz ASLA kendisi uygulamaz: dönen ``quantity``
zaten temel birimdedir.
"""
from __future__ import annotations

import logging
import sqlite3

from app.core import barcode_text as bt
from app.core.clock import now_utc
from app.core.db import Database
from app.core.errors import GecersizCarpan, MukerrerBarkod
from app.core.models import BarcodeMatch, BarcodeType

log = logging.getLogger(__name__)


class BarcodeService:
    def __init__(self, db: Database, settings) -> None:
        self.db = db
        self.settings = settings

    # -- Normalleştirme ----------------------------------------------------
    def _trims(self) -> tuple[str, str]:
        return (
            self.settings.barcode_trim_prefix(),
            self.settings.barcode_trim_suffix(),
        )

    def normalize(self, raw: str) -> str:
        prefix, suffix = self._trims()
        return bt.normalize(raw, prefix, suffix)

    def canonical(self, raw: str) -> str | None:
        prefix, suffix = self._trims()
        return bt.to_gtin14(raw, prefix, suffix)

    # -- Çözümleme ---------------------------------------------------------
    def resolve(
        self, raw: str, conn: sqlite3.Connection | None = None
    ) -> BarcodeMatch | None:
        """Okutulan barkodu ürüne çözer. Bulunamazsa ``None``.

        Arama sırası bilinçlidir:
          1. Birebir ``barcode_norm`` — barkodun KİMLİĞİ budur.
          2. Yalnızca değer kontrol hanesi doğrulanmış bir GTIN ise ``gtin14``.

        Bu sıra sayesinde UPC-A ile onun EAN-13 yazımı aynı ürüne çözülür, ama
        dahili ``00123`` kodu ``123``e karışmaz.
        """
        norm = self.normalize(raw)
        row = self._lookup("barcode_norm", norm, conn)
        if row is None:
            gtin = self.canonical(raw)
            if gtin:
                row = self._lookup("gtin14", gtin, conn)
        if row is None:
            return None

        multiplier = max(1, int(row["quantity_multiplier"]))
        return BarcodeMatch(
            product_id=row["product_id"],
            product_name=row["name"],
            quantity=multiplier,          # DAİMA temel birim
            barcode=row["barcode_norm"],
            barcode_type=row["barcode_type"],
            multiplier=multiplier,
            sale_price=row["sale_price"],
            is_active=bool(row["is_active"]),
        )

    def _lookup(
        self, column: str, value: str, conn: sqlite3.Connection | None
    ) -> sqlite3.Row | None:
        sql = (
            "SELECT b.*, p.name, p.sale_price, p.is_active "
            "  FROM product_barcodes b JOIN products p ON p.id = b.product_id "
            f" WHERE b.active = 1 AND b.{column} = ?"
        )
        if conn is not None:
            return conn.execute(sql, (value,)).fetchone()
        return self.db.query_one(sql, (value,))

    def owner_of(self, raw: str) -> sqlite3.Row | None:
        """Bu barkod kimde? Mükerrer barkod hatasında ürün adını göstermek için."""
        norm = self.normalize(raw)
        row = self._lookup("barcode_norm", norm, None)
        if row is None:
            gtin = self.canonical(raw)
            if gtin:
                row = self._lookup("gtin14", gtin, None)
        return row

    def inactive_owner(self, raw: str) -> sqlite3.Row | None:
        """Barkod ETKİN bir üründe değilse, kullanımdan kaldırılmış bir ürüne mi ait?

        Pasife alınan ürünün barkodları da kapatılır; okutulduğunda "ürün
        tanınmadı" deyip yeni (çift) ürün açtırmak yerine o ürün önerilir
        (V1.1 kusuru D-08).
        """
        if self.owner_of(raw) is not None:
            return None
        norm = self.normalize(raw)
        gtin = self.canonical(raw)
        return self.db.query_one(
            "SELECT p.id AS product_id, p.name, b.id AS barcode_id "
            "  FROM product_barcodes b JOIN products p ON p.id = b.product_id "
            " WHERE b.active = 0 AND p.is_active = 0 "
            "   AND (b.barcode_norm = ? OR (? IS NOT NULL AND b.gtin14 = ?)) "
            " ORDER BY COALESCE(b.deactivated_at_utc, 0) DESC, b.id DESC LIMIT 1",
            (norm, gtin, gtin),
        )

    # -- Yönetim -----------------------------------------------------------
    def barcodes_of(self, product_id: int, include_inactive: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM product_barcodes WHERE product_id = ?"
        if not include_inactive:
            sql += " AND active = 1"
        sql += " ORDER BY active DESC, quantity_multiplier, id"
        return self.db.query(sql, (product_id,))

    def add_barcode(
        self,
        product_id: int,
        raw: str,
        barcode_type: str = BarcodeType.UNIT,
        multiplier: int = 1,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """Ürüne barkod ekler.

        Aynı barkod başka bir üründe etkinse anlaşılır bir Türkçe hata verilir
        (ham ``IntegrityError`` kullanıcıya ASLA ulaşmaz).
        """
        multiplier = int(multiplier)
        if multiplier < 1:
            raise GecersizCarpan()

        norm = self.normalize(raw)
        gtin = self.canonical(raw)

        def _insert(c: sqlite3.Connection) -> int:
            existing = self._lookup("barcode_norm", norm, c)
            if existing is None and gtin:
                existing = self._lookup("gtin14", gtin, c)
            if existing is not None:
                if existing["product_id"] == product_id:
                    raise MukerrerBarkod(
                        existing["name"],
                        detail=f"aynı üründe zaten kayıtlı: {norm}",
                    )
                raise MukerrerBarkod(existing["name"], detail=f"barkod={norm}")
            cursor = c.execute(
                "INSERT INTO product_barcodes(product_id, barcode, barcode_norm, gtin14, "
                "  barcode_type, quantity_multiplier, created_at_utc) VALUES(?,?,?,?,?,?,?)",
                (product_id, (raw or "").strip(), norm, gtin, barcode_type,
                 multiplier, now_utc()),
            )
            return cursor.lastrowid

        if conn is not None:
            return _insert(conn)
        with self.db.transaction() as own:
            return _insert(own)

    def deactivate_barcode(self, barcode_id: int) -> None:
        """Barkodu pasife alır — FİZİKSEL OLARAK SİLMEZ.

        Ambalaj değişince eski barkod tarihsel olarak bilinir kalmalıdır; ayrıca
        aynı değer ileride başka bir ürüne verilebilsin diye etkin tekillik
        kısıtından çıkar.
        """
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE product_barcodes SET active = 0, deactivated_at_utc = ? "
                " WHERE id = ? AND active = 1",
                (now_utc(), barcode_id),
            )

    def update_barcode(
        self, barcode_id: int, barcode_type: str, multiplier: int
    ) -> None:
        multiplier = int(multiplier)
        if multiplier < 1:
            raise GecersizCarpan()
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE product_barcodes SET barcode_type = ?, quantity_multiplier = ? "
                " WHERE id = ?",
                (barcode_type, multiplier, barcode_id),
            )
