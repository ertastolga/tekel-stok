"""Ürün yönetimi: oluşturma, düzenleme, fiyat geçmişi, arama.

İlkeler
-------
* Ürün, barkodundan bağımsız kalıcı bir kimliktir (``products.id``).
* Geçmişi olan ürün ASLA silinmez, "pasife alınır".
* Fiyat değişikliği geçmiş satışları etkilemez: satışlar fiyat kopyası tutar.
* İlk kurulumda ZORUNLU alan azdır — dükkân sahibi 800 ürünü baştan tanımlamak
  zorunda kalmamalıdır. Eksik bilgiler sonradan tamamlanır.
"""
from __future__ import annotations

import logging
import sqlite3

from app.core import quantity as qty
from app.core.clock import now_utc
from app.core.db import Database
from app.core.errors import GecersizUrunAdi
from app.core.models import BarcodeType, StockState
from app.core.tr import normalize_name, search_matches

log = logging.getLogger(__name__)

#: "Benzer Üründen Oluştur" bu alanları kopyalar. Barkod, ad, boyut ve fiyat
#: KOPYALANMAZ — onlar ürünü ayıran şeylerdir.
_CLONE_FIELDS = (
    "brand_id", "category_id", "family_id", "unit_label", "package_type",
    "size_unit", "vat_rate", "min_stock", "critical_stock", "default_supplier_id",
)


class ProductService:
    def __init__(self, db: Database, settings, catalog, barcodes, inventory, audit) -> None:
        self.db = db
        self.settings = settings
        self.catalog = catalog
        self.barcodes = barcodes
        self.inventory = inventory
        self.audit = audit

    # ===================== Okuma =========================================
    def get(self, product_id: int) -> sqlite3.Row | None:
        return self.db.query_one("SELECT * FROM products WHERE id = ?", (product_id,))

    def by_name(self, name: str) -> sqlite3.Row | None:
        return self.db.query_one(
            "SELECT * FROM products WHERE name_norm = ?", (normalize_name(name),)
        )

    def search(
        self,
        text: str = "",
        category_id: int | None = None,
        brand_id: int | None = None,
        family_id: int | None = None,
        location_id: int | None = None,
        supplier_id: int | None = None,
        stock_state: int | None = None,
        only_active: bool = True,
        limit: int = 200,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        """Filtreli ürün araması — DAİMA sayfalı.

        5.000 ürünlük bir dükkânda bile tam liste belleğe alınmaz.
        Metin araması Türkçe duyarsızdır ve aksansız yazımı da kabul eder.
        """
        where = []
        params: list = []
        if only_active:
            where.append("p.is_active = 1")
        if category_id is not None:
            ids = self.catalog.descendant_category_ids(category_id)
            where.append(f"p.category_id IN ({','.join('?' * len(ids))})")
            params.extend(ids)
        if brand_id is not None:
            where.append("p.brand_id = ?")
            params.append(brand_id)
        if family_id is not None:
            where.append("p.family_id = ?")
            params.append(family_id)
        if supplier_id is not None:
            where.append("p.default_supplier_id = ?")
            params.append(supplier_id)
        if stock_state is not None:
            where.append("p.stock_state = ?")
            params.append(int(stock_state))
        if location_id is not None:
            where.append(
                "EXISTS (SELECT 1 FROM product_locations pl WHERE pl.product_id = p.id "
                "         AND pl.active = 1 AND pl.location_id = ?)"
            )
            params.append(location_id)

        needle = (text or "").strip()
        if needle:
            # Önce indeksten hızlı bir ön eleme (ASCII katlanmış ada göre),
            # sonra Python tarafında Türkçe duyarsız kesin eşleşme.
            where.append("(p.name_norm LIKE ? OR EXISTS (SELECT 1 FROM product_barcodes b "
                         "  WHERE b.product_id = p.id AND b.active = 1 "
                         "    AND b.barcode_norm LIKE ?))")
            params.append(f"%{normalize_name(needle)}%")
            params.append(f"%{needle.upper()}%")

        sql = "SELECT p.* FROM products p"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY p.name_norm LIMIT ? OFFSET ?"
        params.extend([max(1, min(1000, limit)), max(0, offset)])
        rows = self.db.query(sql, params)

        if needle:
            rows = [r for r in rows if search_matches(r["name"], needle)] or rows
        return rows

    def incomplete(self, limit: int = 200) -> list[sqlite3.Row]:
        """"Eksik Ürün Bilgileri" — ilk kurulumdan sonra tamamlanacaklar.

        İlk kurulumda az alan zorunludur; eksikler burada toplanır ki dükkân
        sahibi boş vaktinde tamamlasın.
        """
        return self.db.query(
            "SELECT * FROM products WHERE is_active = 1 AND ("
            "     sale_price IS NULL"
            "  OR category_id IS NULL"
            "  OR brand_id IS NULL"
            "  OR stock_initialized_at_utc IS NULL"
            "  OR NOT EXISTS (SELECT 1 FROM product_barcodes b "
            "                  WHERE b.product_id = products.id AND b.active = 1)"
            "  OR NOT EXISTS (SELECT 1 FROM product_locations pl "
            "                  WHERE pl.product_id = products.id AND pl.active = 1)"
            ") ORDER BY name_norm LIMIT ?",
            (max(1, min(1000, limit)),),
        )

    def missing_fields(self, row: sqlite3.Row) -> list[str]:
        """Bir üründe eksik olanların Türkçe listesi."""
        eksik = []
        if row["sale_price"] is None:
            eksik.append("satış fiyatı")
        if row["category_id"] is None:
            eksik.append("kategori")
        if row["brand_id"] is None:
            eksik.append("marka")
        if row["stock_initialized_at_utc"] is None:
            eksik.append("başlangıç stoğu")
        if not self.barcodes.barcodes_of(row["id"]):
            eksik.append("barkod")
        if not self.catalog.locations_of(row["id"]):
            eksik.append("bulunduğu yer")
        return eksik

    # ===================== Oluşturma =====================================
    def create(
        self,
        name: str,
        sale_price: int | None = None,
        category_id: int | None = None,
        brand_id: int | None = None,
        family_id: int | None = None,
        unit_label: str = qty.DEFAULT_UNIT_LABEL,
        vat_rate: int | None = None,
        size_value: float | None = None,
        size_unit: str | None = None,
        package_type: str | None = None,
        min_stock: int | None = None,
        critical_stock: int | None = None,
        default_supplier_id: int | None = None,
        notes: str | None = None,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """Yeni ürün. Yalnızca AD zorunludur."""
        name = (name or "").strip()
        if not name:
            raise GecersizUrunAdi()

        # V1 yalnızca sayılabilir ürünü destekler; kapı burada.
        qty.ensure_v1_supported(qty.V1_MEASURE_KIND, qty.V1_BASE_UNIT, qty.V1_PRICING_BASIS)

        varsayilan_min, varsayilan_kritik = self.settings.default_thresholds()
        now = now_utc()
        veri = {
            "name": name,
            "name_norm": normalize_name(name),
            "brand_id": brand_id,
            "category_id": category_id,
            "family_id": family_id,
            "size_value": size_value,
            "size_unit": size_unit,
            "package_type": package_type,
            "unit_label": unit_label if unit_label in qty.UNIT_LABELS else qty.DEFAULT_UNIT_LABEL,
            "measure_kind": qty.V1_MEASURE_KIND,
            "base_unit": qty.V1_BASE_UNIT,
            "pricing_basis": qty.V1_PRICING_BASIS,
            "sale_price": sale_price,
            "vat_rate": self.settings.default_vat_rate() if vat_rate is None else vat_rate,
            # Eşikler NOT NULL: üretilmiş stock_state sütunu settings okuyamaz,
            # ayrıca NULL mantığı her dikkat sorgusundan böylece kalkar.
            "min_stock": varsayilan_min if min_stock is None else max(0, min_stock),
            "critical_stock": (
                varsayilan_kritik if critical_stock is None else max(0, critical_stock)
            ),
            "default_supplier_id": default_supplier_id,
            "notes": notes,
            "created_at_utc": now,
            "updated_at_utc": now,
        }
        columns = ", ".join(veri)
        holders = ", ".join("?" * len(veri))
        sql = f"INSERT INTO products({columns}) VALUES({holders})"

        def _insert(c: sqlite3.Connection) -> int:
            cursor = c.execute(sql, list(veri.values()))
            pid = cursor.lastrowid
            self.audit.record(
                "URUN_OLUSTUR", f"{name} ürünü tanımlandı.", "product", pid, conn=c
            )
            return pid

        if conn is not None:
            return _insert(conn)
        with self.db.transaction() as own:
            return _insert(own)

    def quick_create(
        self,
        name: str,
        sale_price: int | None,
        barcode: str | None = None,
        initial_stock: int | None = None,
        purchase_cost: int | None = None,
        category_id: int | None = None,
        brand_name: str | None = None,
        location_id: int | None = None,
        barcode_type: str = BarcodeType.UNIT,
        multiplier: int = 1,
        **extra,
    ) -> int:
        """Hızlı Ürün Tanımlama: barkod okut → ad → fiyat → stok → kaydet.

        Hepsi TEK işlemde olur: ürün, barkodu, yerleşimi ve başlangıç stoğu ya
        birlikte oluşur ya da hiçbiri oluşmaz. Yarım tanımlanmış ürün kalmaz.

        ``initial_stock=None`` → "bilmiyorum, boş bıraktım" → ürün SAYILMAMIŞ
        kalır ve "Henüz Sayılmadı" gösterilir.
        ``initial_stock=0``   → "saydım, gerçekten sıfır" → ürün sayılmış olur.
        """
        with self.db.transaction() as conn:
            brand_id = extra.pop("brand_id", None)
            if brand_id is None and brand_name:
                brand_id = self.catalog.ensure_brand(brand_name)

            product_id = self.create(
                name,
                sale_price=sale_price,
                category_id=category_id,
                brand_id=brand_id,
                conn=conn,
                **extra,
            )

            if barcode:
                self.barcodes.add_barcode(
                    product_id, barcode, barcode_type, multiplier, conn=conn
                )
            if location_id:
                self.catalog._add_product_location(
                    conn, product_id, location_id, True, now_utc()
                )

            if initial_stock is not None:
                stamp = self.settings.calendar().stamp()
                if initial_stock > 0:
                    from app.core.models import MovementType, RefType

                    self.inventory.apply_movement(
                        conn, product_id, MovementType.INITIAL_STOCK, initial_stock,
                        stamp, unit_cost=purchase_cost or 0,
                        ref_type=RefType.INITIAL, note="Başlangıç stoğu",
                    )
                else:
                    self.inventory.declare_zero_stock(
                        conn, product_id, stamp.created_at_utc
                    )
            return product_id

    def create_from_similar(self, source_id: int, name: str, **overrides) -> int:
        """"Benzer Üründen Oluştur" — yüzlerce akraba ürünü hızlı tanımlamak için.

        Marka, kategori, aile, birim, tedarikçi, etiketler ve bulunduğu yerler
        kopyalanır. Barkod, ad, boyut ve FİYAT kopyalanmaz — onlar ürünü ayıran
        şeylerdir.
        """
        source = self.get(source_id)
        if source is None:
            raise ValueError(f"Kaynak ürün yok: {source_id}")

        alanlar = {field: source[field] for field in _CLONE_FIELDS}
        alanlar.update(overrides)
        alanlar.pop("sale_price", None)
        sale_price = overrides.get("sale_price")

        with self.db.transaction() as conn:
            product_id = self.create(name, sale_price=sale_price, conn=conn, **alanlar)

            for tag in self.catalog.tags_of(source_id):
                conn.execute(
                    "INSERT INTO product_tags(product_id, tag_id) VALUES(?,?) "
                    "ON CONFLICT DO NOTHING",
                    (product_id, tag["id"]),
                )
            now = now_utc()
            for loc in self.catalog.locations_of(source_id):
                self.catalog._add_product_location(
                    conn, product_id, loc["id"], bool(loc["is_primary"]), now
                )
            self.audit.record(
                "URUN_KOPYALA",
                f"{name} ürünü {source['name']} ürününden oluşturuldu.",
                "product", product_id, conn=conn,
            )
            return product_id

    # ===================== Güncelleme ====================================
    def update(self, product_id: int, **fields) -> None:
        """Ürün alanlarını günceller. Fiyat için ``set_price`` kullanılır."""
        fields.pop("sale_price", None)
        if not fields:
            return
        if "name" in fields:
            name = (fields["name"] or "").strip()
            if not name:
                raise GecersizUrunAdi()
            fields["name"] = name
            fields["name_norm"] = normalize_name(name)
        fields["updated_at_utc"] = now_utc()
        atama = ", ".join(f"{k} = ?" for k in fields)
        with self.db.transaction() as conn:
            conn.execute(
                f"UPDATE products SET {atama} WHERE id = ?",
                [*fields.values(), product_id],
            )

    def set_price(self, product_id: int, new_price: int, reason: str = "") -> None:
        """Satış fiyatını değiştirir ve geçmişe kaydeder.

        Bugünkü fiyatı değiştirmek DÜNKÜ cirosu değiştirmez: her satış satırı
        kendi fiyat kopyasını taşır.
        """
        now = now_utc()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT name, sale_price FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Ürün yok: {product_id}")
            old = row["sale_price"]
            if old == new_price:
                return
            conn.execute(
                "UPDATE products SET sale_price = ?, updated_at_utc = ? WHERE id = ?",
                (new_price, now, product_id),
            )
            conn.execute(
                "INSERT INTO price_history(product_id, old_price, new_price, "
                "  changed_at_utc, source, reason) VALUES(?,?,?,?,'MANUAL',?)",
                (product_id, old, new_price, now, reason or None),
            )
            from app.core.money import format_tl

            self.audit.record(
                "FIYAT_DEGISTI",
                f"{row['name']} fiyatı {format_tl(old)} → {format_tl(new_price)} oldu.",
                "product", product_id, conn=conn,
            )

    def price_history(self, product_id: int, limit: int = 50) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM price_history WHERE product_id = ? ORDER BY id DESC LIMIT ?",
            (product_id, max(1, min(200, limit))),
        )

    def set_active(self, product_id: int, active: bool) -> None:
        """Ürünü pasife alır ya da geri açar.

        Geçmişi olan ürün SİLİNMEZ: eski satışlar, maliyetler ve stok
        hareketleri olduğu gibi durur. Pasif ürünün etkin barkodları da
        kapatılır ki kasada yanlışlıkla okunmasın.
        """
        now = now_utc()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT name FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            conn.execute(
                "UPDATE products SET is_active = ?, updated_at_utc = ? WHERE id = ?",
                (int(bool(active)), now, product_id),
            )
            if not active:
                conn.execute(
                    "UPDATE product_barcodes SET active = 0, deactivated_at_utc = ? "
                    " WHERE product_id = ? AND active = 1",
                    (now, product_id),
                )
            if row:
                self.audit.record(
                    "URUN_DURUM",
                    f"{row['name']} {'yeniden kullanıma alındı' if active else 'pasife alındı'}.",
                    "product", product_id, conn=conn,
                )

    # ===================== Dikkat listeleri ==============================
    def attention_counts(self) -> dict[str, int]:
        """Panel için tek sorguda dikkat kovaları.

        "Henüz sayılmadı" AYRI bir kovadır ve kritik/düşük sayılmaz — bilinmeyen
        stok, az stok değildir.
        """
        rows = self.db.query(
            "SELECT stock_state, COUNT(*) AS adet FROM products "
            " WHERE is_active = 1 GROUP BY stock_state"
        )
        sayim = {row["stock_state"]: row["adet"] for row in rows}
        return {
            "normal": sayim.get(StockState.NORMAL, 0),
            "dusuk": sayim.get(StockState.LOW, 0),
            "kritik": sayim.get(StockState.CRITICAL, 0),
            "kontrol_gerekli": sayim.get(StockState.NEEDS_CHECK, 0),
            "henuz_sayilmadi": sayim.get(StockState.NOT_COUNTED, 0),
        }

    def by_stock_state(self, state: int, limit: int = 200) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM products WHERE is_active = 1 AND stock_state = ? "
            " ORDER BY current_stock, name_norm LIMIT ?",
            (int(state), max(1, min(1000, limit))),
        )
