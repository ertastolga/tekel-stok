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

import json
import logging
import sqlite3
from dataclasses import dataclass, field

from app.core import quantity as qty
from app.core.clock import now_utc
from app.core.db import Database
from app.core.errors import GecersizFiyat, GecersizUrunAdi, KategoriGerekli
from app.core.models import BarcodeType, StockState
from app.core.tr import normalize_name, search_matches

log = logging.getLogger(__name__)

#: ``update`` ile değiştirilebilen sütunlar (beyaz liste). Fiyat
#: ``set_price``, stok defterden, durum ``set_active`` ile değişir.
_DUZENLENEBILIR = frozenset({
    "name", "brand_id", "category_id", "family_id", "unit_label", "package_type",
    "size_value", "size_unit", "vat_rate", "min_stock", "critical_stock",
    "default_supplier_id", "notes",
})

#: "Benzer Üründen Oluştur" bu alanları kopyalar. Barkod, ad, boyut ve fiyat
#: KOPYALANMAZ — onlar ürünü ayıran şeylerdir.
_CLONE_FIELDS = (
    "brand_id", "category_id", "family_id", "unit_label", "package_type",
    "size_unit", "vat_rate", "min_stock", "critical_stock", "default_supplier_id",
)


@dataclass
class YeniUrun:
    """Hızlı Ürün Ekle formunun tamamı — TEK işlemde kaydedilir."""

    name: str
    sale_price: int
    category_id: int | None
    barcode: str | None = None
    barcode_type: str = BarcodeType.UNIT
    multiplier: int = 1
    #: Ek barkodlar: (barkod, tür, çarpan) — alternatif / paket / koli.
    extra_barcodes: list[tuple[str, str, int]] = field(default_factory=list)
    brand_name: str | None = None
    family_name: str | None = None
    tags: list[str] = field(default_factory=list)
    supplier_id: int | None = None
    vat_rate: int | None = None
    #: Katalog / referans alış fiyatı (stok değerine ASLA girmez).
    reference_cost: int | None = None
    #: Başlangıç stoğu ve (biliniyorsa) birim maliyeti.
    initial_stock: int | None = None
    initial_cost: int | None = None
    location_id: int | None = None


@dataclass(frozen=True, slots=True)
class AktiflestirmeSonucu:
    acilan_barkodlar: list[str]
    acilamayan_barkodlar: list[str]


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
        only_inactive: bool = False,
    ) -> list[sqlite3.Row]:
        """Filtreli ürün araması — DAİMA sayfalı.

        5.000 ürünlük bir dükkânda bile tam liste belleğe alınmaz.
        Metin araması Türkçe duyarsızdır ve aksansız yazımı da kabul eder.
        """
        where = []
        params: list = []
        if only_inactive:
            where.append("p.is_active = 0")
        elif only_active:
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

    def search_for_sale(self, query: str, limit: int = 30) -> list[sqlite3.Row]:
        """Kasa "Ürün Ara": barkodu okunamayan ürünü bulup sepete eklemek için.

        * Yalnızca SATILABİLİR ürünler: aktif ve fiyatı girilmiş.
        * Çok kelimeli arama: her kelime ad YA DA marka içinde geçmeli (VE);
          "efes 50" → "Efes Pilsen 50 cl". Türkçe ve aksan duyarsız.
        * Rakamlardan oluşan en az 3 karakterlik sorgu barkodda da aranır
          (önce baştan eşleşenler).
        Sonuçlar tahmin edilebilir: bulanık eşleşme YOKTUR.
        """
        metin = (query or "").strip()
        kelimeler = normalize_name(metin).split()
        if not kelimeler:
            return []

        def kacis(deger: str) -> str:
            return deger.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

        ad_kosulu = " AND ".join(
            "(p.name_norm || ' ' || COALESCE(br.name_norm, '')) LIKE ? ESCAPE '\\'"
            for _ in kelimeler
        )
        params: list = [f"%{kacis(k)}%" for k in kelimeler]
        kod = "".join(metin.split())
        barkodla = kod.isdigit() and len(kod) >= 3
        kosul = f"({ad_kosulu})"
        sira = ""
        if barkodla:
            kosul = (
                f"({kosul} OR EXISTS (SELECT 1 FROM product_barcodes b "
                "  WHERE b.product_id = p.id AND b.active = 1 "
                "    AND b.barcode_norm LIKE ? ESCAPE '\\'))"
            )
            params.append(f"%{kacis(kod)}%")
            sira = (
                "CASE WHEN EXISTS (SELECT 1 FROM product_barcodes b "
                "  WHERE b.product_id = p.id AND b.active = 1 "
                "    AND b.barcode_norm LIKE ? ESCAPE '\\') THEN 0 ELSE 1 END, "
            )
        sql = (
            "SELECT p.id, p.name, p.sale_price, p.current_stock, br.name AS marka "
            "  FROM products p LEFT JOIN brands br ON br.id = p.brand_id "
            " WHERE p.is_active = 1 AND p.sale_price IS NOT NULL AND " + kosul +
            f" ORDER BY {sira}"
            "  CASE WHEN p.name_norm LIKE ? ESCAPE '\\' THEN 0 ELSE 1 END, p.name_norm "
            " LIMIT ?"
        )
        if barkodla:
            params.append(f"{kacis(kod)}%")
        params.append(f"{kacis(kelimeler[0])}%")
        params.append(max(1, min(100, limit)))
        return self.db.query(sql, params)

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
        """Ürün alanlarını günceller (beyaz liste) ve DEĞİŞENLERİ denetime yazar.

        Fiyat için ``set_price`` kullanılır; ``sale_price`` burada yok sayılır.
        Listede olmayan bir alan ``ValueError`` verir (programcı hatası).
        """
        fields.pop("sale_price", None)
        bilinmeyen = set(fields) - _DUZENLENEBILIR
        if bilinmeyen:
            raise ValueError(f"düzenlenemeyen alan(lar): {sorted(bilinmeyen)}")
        if not fields:
            return
        if "name" in fields:
            name = (fields["name"] or "").strip()
            if not name:
                raise GecersizUrunAdi()
            fields["name"] = name
        with self.db.transaction() as conn:
            eski = conn.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            if eski is None:
                raise ValueError(f"Ürün yok: {product_id}")
            fark = {
                alan: [eski[alan], deger] for alan, deger in fields.items()
                if eski[alan] != deger
            }
            if not fark:
                return
            yazilacak = {alan: fields[alan] for alan in fark}
            if "name" in yazilacak:
                yazilacak["name_norm"] = normalize_name(yazilacak["name"])
            yazilacak["updated_at_utc"] = now_utc()
            atama = ", ".join(f"{k} = ?" for k in yazilacak)
            conn.execute(
                f"UPDATE products SET {atama} WHERE id = ?",
                [*yazilacak.values(), product_id],
            )
            self.audit.record(
                "URUN_DUZENLE", f"{fields.get('name', eski['name'])} düzenlendi "
                f"({', '.join(sorted(fark))}).",
                "product", product_id, details=fark, conn=conn,
            )

    def save_edit(
        self,
        product_id: int,
        fields: dict,
        sale_price: int | None = None,
        brand_name: str | None = None,
        family_name: str | None = None,
        tags: list[str] | None = None,
        location_ids: list[int] | None = None,
        barcode_adds: list[tuple[str, str, int]] | None = None,
        barcode_removals: list[int] | None = None,
        reference_cost: int | None | object = ...,
    ) -> None:
        """Düzenleme penceresinin TAMAMINI tek işlemde kaydeder (D-09).

        Marka/aile kaydı, alanlar, fiyat (geçmişe yazılır), etiketler,
        yerleşimler (esas raf korunur), barkod ekleme/kaldırma ve referans alış
        fiyatı ya hep birlikte olur ya hiçbiri. Pencerede "Vazgeç" hiçbir şeyi
        değiştirmez çünkü bu çağrı yapılmaz.
        """
        with self.db.transaction() as conn:
            alanlar = dict(fields)
            if brand_name is not None:
                alanlar["brand_id"] = self.catalog.ensure_brand(brand_name)
            if family_name is not None:
                alanlar["family_id"] = self.catalog.ensure_family(family_name)
            self.update(product_id, **alanlar)
            if sale_price is not None:
                self.set_price(product_id, sale_price)
            if tags is not None:
                etiket_idleri = [self.catalog.ensure_tag(t) for t in tags if t.strip()]
                conn.execute("DELETE FROM product_tags WHERE product_id = ?", (product_id,))
                conn.executemany(
                    "INSERT INTO product_tags(product_id, tag_id) VALUES(?,?)",
                    [(product_id, t) for t in dict.fromkeys(e for e in etiket_idleri if e)],
                )
            if location_ids is not None:
                self.catalog.set_locations(product_id, location_ids, conn=conn)
            for barkod_id in barcode_removals or []:
                conn.execute(
                    "UPDATE product_barcodes SET active = 0, deactivated_at_utc = ? "
                    " WHERE id = ? AND product_id = ? AND active = 1",
                    (now_utc(), barkod_id, product_id),
                )
            for barkod, tur, carpan in barcode_adds or []:
                self.barcodes.add_barcode(product_id, barkod, tur, carpan, conn=conn)
            if reference_cost is not ...:
                if reference_cost is not None and int(reference_cost) < 0:
                    raise GecersizFiyat("Alış fiyatı eksi olamaz.")
                conn.execute(
                    "UPDATE products SET reference_cost = ?, reference_cost_updated_at_utc = "
                    "  CASE WHEN ? IS NULL THEN NULL ELSE ? END WHERE id = ? "
                    "   AND IFNULL(reference_cost, -1) <> IFNULL(?, -1)",
                    (reference_cost, reference_cost, now_utc(), product_id, reference_cost),
                )

    def move_to_category(self, product_ids: list[int], category_id: int | None) -> int:
        """Toplu "Kategoriye taşı": tek işlem, tek denetim satırı."""
        kimlikler = list(dict.fromkeys(int(p) for p in product_ids))
        if not kimlikler:
            return 0
        if category_id is not None:
            kategori = self.db.query_one(
                "SELECT active FROM categories WHERE id = ?", (category_id,)
            )
            if kategori is None or not kategori["active"]:
                raise KategoriGerekli()
        yer = ",".join("?" * len(kimlikler))
        with self.db.transaction() as conn:
            sayi = conn.execute(
                f"UPDATE products SET category_id = ?, updated_at_utc = ? "
                f" WHERE id IN ({yer}) AND IFNULL(category_id, 0) <> IFNULL(?, 0)",
                [category_id, now_utc(), *kimlikler, category_id],
            ).rowcount
            self.audit.record(
                "URUN_TOPLU_KATEGORI", f"{sayi} ürünün kategorisi değiştirildi.",
                "category", category_id, details={"urunler": kimlikler}, conn=conn,
            )
            return sayi

    def first_barcodes(self, product_ids: list[int]) -> dict[int, str]:
        """Liste ekranı için her ürünün ilk etkin barkodu (TEK sorgu)."""
        if not product_ids:
            return {}
        yer = ",".join("?" * len(product_ids))
        sonuc: dict[int, str] = {}
        for satir in self.db.query(
            f"SELECT product_id, barcode_norm FROM product_barcodes "
            f" WHERE active = 1 AND product_id IN ({yer}) "
            f" ORDER BY product_id, quantity_multiplier, id",
            list(product_ids),
        ):
            sonuc.setdefault(satir["product_id"], satir["barcode_norm"])
        return sonuc

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

    def set_active(self, product_id: int, active: bool) -> AktiflestirmeSonucu | None:
        """Ürünü pasife alır ya da geri açar.

        Geçmişi olan ürün SİLİNMEZ: eski satışlar, maliyetler ve stok
        hareketleri olduğu gibi durur. Pasif ürünün etkin barkodları da
        kapatılır ki kasada yanlışlıkla okunmasın — hangi barkodların
        kapatıldığı denetim kaydına yazılır. Yeniden açılırken BU barkodlar,
        bu arada başka bir ürüne verilmemişlerse geri açılır (V1.1 kusuru D-08:
        barkodlar geri gelmiyor, okutulunca çift ürün açtırılıyordu).
        """
        if active:
            return self.reactivate(product_id)
        now = now_utc()
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT name FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            conn.execute(
                "UPDATE products SET is_active = 0, updated_at_utc = ? WHERE id = ?",
                (now, product_id),
            )
            kapatilan = [
                r["id"] for r in conn.execute(
                    "SELECT id FROM product_barcodes WHERE product_id = ? AND active = 1",
                    (product_id,),
                ).fetchall()
            ]
            conn.execute(
                "UPDATE product_barcodes SET active = 0, deactivated_at_utc = ? "
                " WHERE product_id = ? AND active = 1",
                (now, product_id),
            )
            if row:
                self.audit.record(
                    "URUN_DURUM", f"{row['name']} pasife alındı.",
                    "product", product_id, details={"barkodlar": kapatilan}, conn=conn,
                )
        return None

    def reactivate(self, product_id: int) -> AktiflestirmeSonucu:
        """Ürünü yeniden kullanıma alır; pasife alınırken kapatılan barkodları
        (başka bir üründe etkin değilse) geri açar."""
        now = now_utc()
        acilan: list[str] = []
        acilamayan: list[str] = []
        with self.db.transaction() as conn:
            row = conn.execute(
                "SELECT name FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            conn.execute(
                "UPDATE products SET is_active = 1, updated_at_utc = ? WHERE id = ?",
                (now, product_id),
            )
            for barkod in self._pasiflestirmede_kapanan(conn, product_id):
                cakisan = conn.execute(
                    "SELECT 1 FROM product_barcodes WHERE active = 1 AND ("
                    "  barcode_norm = ? OR (? IS NOT NULL AND gtin14 = ?))",
                    (barkod["barcode_norm"], barkod["gtin14"], barkod["gtin14"]),
                ).fetchone()
                if cakisan:
                    acilamayan.append(barkod["barcode"])
                    continue
                conn.execute(
                    "UPDATE product_barcodes SET active = 1, deactivated_at_utc = NULL "
                    " WHERE id = ?", (barkod["id"],),
                )
                acilan.append(barkod["barcode"])
            if row:
                self.audit.record(
                    "URUN_DURUM", f"{row['name']} yeniden kullanıma alındı.",
                    "product", product_id,
                    details={"acilan": acilan, "acilamayan": acilamayan}, conn=conn,
                )
        return AktiflestirmeSonucu(acilan, acilamayan)

    def _pasiflestirmede_kapanan(self, conn, product_id: int) -> list[sqlite3.Row]:
        """Son pasife almada kapatılan barkodlar.

        V1.2 kaydı denetim satırındaki listeyi kullanır; V1.1'den gelen kayıtta
        aynı anda (aynı saniye) kapatılan en son barkod grubu alınır.
        """
        son = conn.execute(
            "SELECT details_json FROM audit_log WHERE action = 'URUN_DURUM' "
            "   AND entity_type = 'product' AND entity_id = ? "
            " ORDER BY id DESC LIMIT 1",
            (product_id,),
        ).fetchone()
        if son is not None and son["details_json"]:
            kimlikler = json.loads(son["details_json"]).get("barkodlar")
            if kimlikler is not None:
                if not kimlikler:
                    return []
                yer = ",".join("?" * len(kimlikler))
                return conn.execute(
                    f"SELECT * FROM product_barcodes WHERE id IN ({yer}) AND active = 0",
                    kimlikler,
                ).fetchall()
        en_son = conn.execute(
            "SELECT MAX(deactivated_at_utc) FROM product_barcodes "
            " WHERE product_id = ? AND active = 0", (product_id,),
        ).fetchone()[0]
        if en_son is None:
            return []
        return conn.execute(
            "SELECT * FROM product_barcodes WHERE product_id = ? AND active = 0 "
            "   AND deactivated_at_utc = ?", (product_id, en_son),
        ).fetchall()

    # ===================== Hızlı Ürün Ekle (M4b) ==========================
    def add_product(self, taslak: YeniUrun) -> int:
        """Formun TAMAMINI tek işlemde kaydeder; herhangi bir hata hepsini geri alır.

        Kategori ZORUNLUDUR; satış fiyatı sıfırdan büyük olmalıdır. Alış
        fiyatı stokla birlikte verildiyse açılış stoğunun maliyetidir; stoksuz
        verildiyse yalnızca REFERANS (katalog) alış fiyatıdır — stok değerine,
        "son alış"a ve maliyet kapsamına ASLA girmez.
        """
        ad = (taslak.name or "").strip()
        if not ad:
            raise GecersizUrunAdi()
        if taslak.sale_price is None or int(taslak.sale_price) <= 0:
            raise GecersizFiyat("Satış fiyatı sıfırdan büyük olmalıdır.")
        if taslak.category_id is None:
            raise KategoriGerekli()
        kategori = self.db.query_one(
            "SELECT active FROM categories WHERE id = ?", (taslak.category_id,)
        )
        if kategori is None or not kategori["active"]:
            raise KategoriGerekli()
        if taslak.reference_cost is not None and taslak.reference_cost < 0:
            raise GecersizFiyat("Alış fiyatı eksi olamaz.")

        with self.db.transaction() as conn:
            stoklu = taslak.initial_stock is not None and taslak.initial_stock > 0
            extra: dict = {}
            if taslak.supplier_id is not None:
                extra["default_supplier_id"] = taslak.supplier_id
            if taslak.vat_rate is not None:
                extra["vat_rate"] = taslak.vat_rate
            aile = self.catalog.ensure_family(taslak.family_name)
            if aile is not None:
                extra["family_id"] = aile
            pid = self.quick_create(
                ad,
                sale_price=int(taslak.sale_price),
                barcode=taslak.barcode or None,
                initial_stock=taslak.initial_stock,
                purchase_cost=taslak.initial_cost if stoklu else None,
                category_id=taslak.category_id,
                brand_name=taslak.brand_name,
                location_id=taslak.location_id,
                barcode_type=taslak.barcode_type,
                multiplier=taslak.multiplier,
                **extra,
            )
            for barkod, tur, carpan in taslak.extra_barcodes:
                self.barcodes.add_barcode(pid, barkod, tur, carpan, conn=conn)
            if taslak.tags:
                etiketler = [self.catalog.ensure_tag(t) for t in taslak.tags]
                conn.executemany(
                    "INSERT INTO product_tags(product_id, tag_id) VALUES(?,?)",
                    [(pid, t) for t in dict.fromkeys(e for e in etiketler if e)],
                )
            referans = taslak.reference_cost
            if referans is None and not stoklu and taslak.initial_cost is not None:
                referans = taslak.initial_cost
            if referans is not None:
                conn.execute(
                    "UPDATE products SET reference_cost = ?, "
                    "  reference_cost_updated_at_utc = ? WHERE id = ?",
                    (int(referans), now_utc(), pid),
                )
            return pid

    def set_reference_cost(self, product_id: int, cost: int | None) -> None:
        """Referans (katalog) alış fiyatı. ``last_purchase_cost``'a DOKUNMAZ."""
        if cost is not None and cost < 0:
            raise GecersizFiyat("Alış fiyatı eksi olamaz.")
        with self.db.transaction() as conn:
            conn.execute(
                "UPDATE products SET reference_cost = ?, reference_cost_updated_at_utc = ? "
                " WHERE id = ?",
                (cost, now_utc() if cost is not None else None, product_id),
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
