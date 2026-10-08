"""Veritabanı şeması ve göçler (migrations).

Şema sürümü ``schema_meta`` tablosunda ``schema_version`` anahtarında tutulur.
Her göç ya bir SQL metni ya da ``conn`` alan bir fonksiyondur; bir göçün tüm
adımları ve sürüm damgası TEK bir işlemde uygulanır (bkz. ``Database.migrate``).

Uygulama yıllarca yaşayacağı için kullanıcıya ASLA "veritabanını silin"
denmez; her şema değişikliği yeni bir göç olarak eklenir.

Para birimi: tüm ``*_kurus`` anlamındaki sütunlar tam sayı kuruştur.
Miktarlar: tüm miktar sütunları tam sayıdır ve ürünün TEMEL BİRİMİNDEDİR
(bkz. ``app/core/quantity.py``).
"""
from __future__ import annotations

import sqlite3

from app.core.clock import BEGINNING_OF_TIME, DEFAULT_BUSINESS_DAY_START_HOUR
from app.core.tr import normalize_name

SCHEMA_VERSION = 4


# =========================================================================
# Sürüm 1 — ilk şema
# =========================================================================
_V1_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS schema_meta (
        key   TEXT PRIMARY KEY,
        value TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key            TEXT PRIMARY KEY,
        value          TEXT,
        updated_at_utc INTEGER
    )
    """,
    # --- İş günü kuralı: GEÇERLİLİK TARİHLİ ------------------------------
    # Gün başlangıcı değiştiğinde geçmiş raporlar YENİDEN YAZILMAZ; yeni kural
    # yalnızca kendi effective_from tarihinden sonraki kayıtlara uygulanır.
    # Kayıtların business_date sütunu zaten yazma anında dondurulmuştur.
    """
    CREATE TABLE IF NOT EXISTS business_day_rules (
        id             INTEGER PRIMARY KEY,
        effective_from TEXT    NOT NULL UNIQUE,          -- 'YYYY-MM-DD'
        start_hour     INTEGER NOT NULL CHECK (start_hour BETWEEN 0 AND 23),
        created_at_utc INTEGER NOT NULL,
        note           TEXT
    )
    """,
    # --- Katalog ---------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS categories (
        id             INTEGER PRIMARY KEY,
        parent_id      INTEGER REFERENCES categories(id),
        name           TEXT    NOT NULL,
        name_norm      TEXT    NOT NULL,
        sort_order     INTEGER NOT NULL DEFAULT 0,
        active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        created_at_utc INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS brands (
        id             INTEGER PRIMARY KEY,
        name           TEXT    NOT NULL,
        name_norm      TEXT    NOT NULL UNIQUE,
        active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        created_at_utc INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS product_families (
        id             INTEGER PRIMARY KEY,
        name           TEXT    NOT NULL,
        name_norm      TEXT    NOT NULL UNIQUE,
        brand_id       INTEGER REFERENCES brands(id),
        active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        created_at_utc INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tags (
        id             INTEGER PRIMARY KEY,
        name           TEXT    NOT NULL,
        name_norm      TEXT    NOT NULL UNIQUE,
        active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        created_at_utc INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS locations (
        id             INTEGER PRIMARY KEY,
        name           TEXT    NOT NULL,
        name_norm      TEXT    NOT NULL UNIQUE,
        type           TEXT    NOT NULL DEFAULT 'DIGER'
                       CHECK (type IN ('DOLAP','RAF','STAND','KASA_ONU','DEPO','DIGER')),
        is_cooled      INTEGER NOT NULL DEFAULT 0 CHECK (is_cooled IN (0, 1)),
        sort_order     INTEGER NOT NULL DEFAULT 0,
        active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        created_at_utc INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS suppliers (
        id             INTEGER PRIMARY KEY,
        name           TEXT    NOT NULL,
        name_norm      TEXT    NOT NULL UNIQUE,
        phone          TEXT,
        contact        TEXT,
        notes          TEXT,
        active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        created_at_utc INTEGER NOT NULL,
        updated_at_utc INTEGER NOT NULL
    )
    """,
    # --- Ürün ------------------------------------------------------------
    # stock_state ÜRETİLMİŞ (STORED) sütundur ve v1 CREATE içinde olmak
    # ZORUNDADIR: SQLite ALTER TABLE ile STORED üretilmiş sütun EKLEYEMEZ ve
    # ifadesini değiştirmek tam tablo yeniden inşası gerektirir.
    #
    # Neden gerekli: "current_stock <= min_stock" bir sütun-sütun
    # karşılaştırmasıdır ve indeks kullanamaz; bu sütun olmadan "Kritik Stok"
    # ekranı her açılışta tüm ürünleri tarardı.
    #
    # SIRA ÖNEMLİ: hiç sayılmamış bir ürün ASLA "Kritik"/"Düşük" gösterilmez —
    # bilinmeyen stok, az stok değildir. Yalnızca NEGATİF stok bunun önüne
    # geçer, çünkü o sayımdan bağımsız olarak gerçek bir uyarıdır.
    """
    CREATE TABLE IF NOT EXISTS products (
        id             INTEGER PRIMARY KEY,
        name           TEXT    NOT NULL,
        name_norm      TEXT    NOT NULL,
        brand_id       INTEGER REFERENCES brands(id),
        category_id    INTEGER REFERENCES categories(id),
        family_id      INTEGER REFERENCES product_families(id),
        size_value     REAL,
        size_unit      TEXT,
        package_type   TEXT,
        unit_label     TEXT    NOT NULL DEFAULT 'Adet'
                       CHECK (unit_label IN ('Adet','Paket','Koli')),

        -- Ölçüm üstverisi. CHECK listeleri bilerek geniştir (ileride tablo
        -- yeniden inşası gerekmesin); V1 katılığı servis katmanında ve I33
        -- değişmezinde sağlanır: yalnızca COUNT/ADET/PER_UNIT kabul edilir.
        measure_kind   TEXT    NOT NULL DEFAULT 'COUNT'
                       CHECK (measure_kind IN ('COUNT','WEIGHT','VOLUME')),
        base_unit      TEXT    NOT NULL DEFAULT 'ADET'
                       CHECK (base_unit IN ('ADET','GRAM','MILILITRE')),
        pricing_basis  TEXT    NOT NULL DEFAULT 'PER_UNIT'
                       CHECK (pricing_basis IN ('PER_UNIT','PER_1000_BASE')),

        sale_price     INTEGER CHECK (sale_price IS NULL OR sale_price >= 0),
        vat_rate       INTEGER CHECK (vat_rate IS NULL OR vat_rate BETWEEN 0 AND 100),

        -- Eşikler ürün oluşturulurken ayarlardan doldurulur: üretilmiş sütun
        -- settings tablosunu okuyamaz, ayrıca NULL mantığı her sorgudan kalkar.
        min_stock      INTEGER NOT NULL DEFAULT 0 CHECK (min_stock >= 0),
        critical_stock INTEGER NOT NULL DEFAULT 0 CHECK (critical_stock >= 0),

        -- Önbellek: YALNIZCA InventoryService.apply_movement() yazar.
        -- Defterden (stock_movements) yeniden hesaplanabilir olmak zorundadır.
        current_stock  INTEGER NOT NULL DEFAULT 0,
        stock_value    INTEGER NOT NULL DEFAULT 0 CHECK (stock_value >= 0),
        last_avg_cost      INTEGER,
        last_purchase_cost INTEGER,

        -- NULL = henüz sayılmadı. Nasıl sayıldığı da saklanır, çünkü
        -- "saydım, gerçekten sıfır" hâli geçerli bir başlangıçtır ama ortada
        -- bir stok hareketi bırakmaz (sıfır miktarlı hareket yazılmaz).
        stock_initialized_at_utc INTEGER,
        stock_initialized_by     TEXT CHECK (stock_initialized_by IS NULL OR
                                 stock_initialized_by IN ('INITIAL_STOCK','COUNT','DECLARED_ZERO')),
        last_sale_at_utc         INTEGER,
        last_purchase_at_utc     INTEGER,
        first_stocked_at_utc     INTEGER,

        default_supplier_id INTEGER REFERENCES suppliers(id),
        notes          TEXT,
        is_active      INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
        created_at_utc INTEGER NOT NULL,
        updated_at_utc INTEGER NOT NULL,

        stock_state INTEGER GENERATED ALWAYS AS (
            CASE WHEN stock_initialized_at_utc IS NULL
                      AND current_stock >= 0          THEN 4   -- Henüz Sayılmadı
                 WHEN current_stock <  0              THEN 3   -- Stok Kontrolü Gerekli
                 WHEN current_stock <= critical_stock THEN 2   -- Kritik
                 WHEN current_stock <= min_stock      THEN 1   -- Düşük
                 ELSE 0 END) STORED                            -- 0 = Normal
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS product_tags (
        product_id INTEGER NOT NULL REFERENCES products(id),
        tag_id     INTEGER NOT NULL REFERENCES tags(id),
        PRIMARY KEY (product_id, tag_id)
    )
    """,
    # --- Barkodlar -------------------------------------------------------
    # barcode      : okuyucudan geldiği gibi (ham)
    # barcode_norm : muhafazakâr normalleştirme — BAŞTAKİ SIFIRLAR KORUNUR
    # gtin14       : yalnızca kontrol hanesi DOĞRULANMIŞSA kanonik 14 hane
    """
    CREATE TABLE IF NOT EXISTS product_barcodes (
        id             INTEGER PRIMARY KEY,
        product_id     INTEGER NOT NULL REFERENCES products(id),
        barcode        TEXT    NOT NULL,
        barcode_norm   TEXT    NOT NULL,
        gtin14         TEXT,
        barcode_type   TEXT    NOT NULL DEFAULT 'UNIT'
                       CHECK (barcode_type IN ('UNIT','PACK','CASE','ALTERNATE')),
        quantity_multiplier INTEGER NOT NULL DEFAULT 1
                       CHECK (quantity_multiplier >= 1),
        active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        created_at_utc     INTEGER NOT NULL,
        deactivated_at_utc INTEGER
    )
    """,
    # --- Ürün konumları (ÇOKTAN ÇOĞA) ------------------------------------
    # Konum "nerede bulunur" bilgisidir. Konum değiştirmek stok hareketi
    # DEĞİLDİR ve toplam stoğu ASLA etkilemez.
    """
    CREATE TABLE IF NOT EXISTS product_locations (
        id             INTEGER PRIMARY KEY,
        product_id     INTEGER NOT NULL REFERENCES products(id),
        location_id    INTEGER NOT NULL REFERENCES locations(id),
        is_primary     INTEGER NOT NULL DEFAULT 0 CHECK (is_primary IN (0, 1)),
        active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
        active_from_utc    INTEGER NOT NULL,
        deactivated_at_utc INTEGER
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS price_history (
        id             INTEGER PRIMARY KEY,
        product_id     INTEGER NOT NULL REFERENCES products(id),
        old_price      INTEGER,
        new_price      INTEGER,
        changed_at_utc INTEGER NOT NULL,
        source         TEXT    NOT NULL DEFAULT 'MANUAL'
                       CHECK (source IN ('MANUAL','BULK')),
        reason         TEXT
    )
    """,
    # --- Satışlar (ters kayıt / contra modeli) ---------------------------
    # Geri alma satırı NEGATİF tutar taşır. Böylece SUM(total_amount) hiçbir
    # filtre gerektirmeden doğrudur; unutulacak bir "AND is_reversed=0" kalmaz.
    """
    CREATE TABLE IF NOT EXISTS sales (
        id             INTEGER PRIMARY KEY,
        entry_type     TEXT    NOT NULL CHECK (entry_type IN ('SALE','SALE_REVERSAL')),
        sale_mode      TEXT    NOT NULL CHECK (sale_mode IN ('HIZLI','SEPET')),

        created_at_utc INTEGER NOT NULL,
        local_date     TEXT    NOT NULL,
        local_hour     INTEGER NOT NULL CHECK (local_hour BETWEEN 0 AND 23),
        local_dow      INTEGER NOT NULL CHECK (local_dow BETWEEN 0 AND 6),
        business_date  TEXT    NOT NULL,

        total_amount   INTEGER NOT NULL DEFAULT 0,
        total_cost     INTEGER NOT NULL DEFAULT 0,
        item_count     INTEGER NOT NULL DEFAULT 0,
        discount_total INTEGER NOT NULL DEFAULT 0,
        rounding_adjustment INTEGER NOT NULL DEFAULT 0,

        payment_method TEXT CHECK (payment_method IS NULL OR
                       payment_method IN ('NAKIT','KART','VERESIYE','DIGER')),

        reverses_sale_id INTEGER REFERENCES sales(id),
        is_reversed    INTEGER NOT NULL DEFAULT 0 CHECK (is_reversed IN (0, 1)),
        note           TEXT,

        CHECK ((entry_type = 'SALE_REVERSAL') = (reverses_sale_id IS NOT NULL)),
        CHECK ((entry_type = 'SALE'          AND total_amount >= 0 AND item_count >= 0)
            OR (entry_type = 'SALE_REVERSAL' AND total_amount <= 0 AND item_count <= 0))
    )
    """,
    # cost_total GERÇEKTİR; unit_cost yalnızca gösterimdir.
    # (Oransal çekim yüzünden q * unit_cost != cost_total olabilir.)
    # quantity DAİMA temel birimdedir; çarpan yalnızca denetim izidir.
    """
    CREATE TABLE IF NOT EXISTS sale_items (
        id             INTEGER PRIMARY KEY,
        sale_id        INTEGER NOT NULL REFERENCES sales(id),
        line_no        INTEGER NOT NULL,
        product_id     INTEGER NOT NULL REFERENCES products(id),
        product_name_snapshot TEXT NOT NULL,
        quantity       INTEGER NOT NULL CHECK (quantity <> 0),
        unit_price     INTEGER NOT NULL,
        line_discount  INTEGER NOT NULL DEFAULT 0,
        line_total     INTEGER NOT NULL,
        cost_total     INTEGER NOT NULL,
        unit_cost      INTEGER NOT NULL DEFAULT 0,
        is_estimated_cost INTEGER NOT NULL DEFAULT 0
                       CHECK (is_estimated_cost IN (0, 1)),
        vat_rate       INTEGER,
        barcode_used   TEXT,
        barcode_multiplier INTEGER NOT NULL DEFAULT 1,
        UNIQUE (sale_id, line_no)
    )
    """,
    # --- Akıllı gruplama (TAHMİNİ) ---------------------------------------
    # Ham satışlar bu tablolar yüzünden ASLA değişmez; üyelik ayrı tablodadır.
    """
    CREATE TABLE IF NOT EXISTS sale_sessions (
        id             INTEGER PRIMARY KEY,
        kind           TEXT    NOT NULL DEFAULT 'ESTIMATED'
                       CHECK (kind IN ('ESTIMATED','EXACT')),
        started_at_utc INTEGER NOT NULL,
        ended_at_utc   INTEGER NOT NULL,
        business_date  TEXT    NOT NULL,
        algorithm_version  TEXT NOT NULL,
        threshold_seconds  INTEGER NOT NULL,
        confidence     REAL,
        manual_boundary INTEGER NOT NULL DEFAULT 0
                       CHECK (manual_boundary IN (0, 1)),
        sale_count     INTEGER NOT NULL DEFAULT 0,
        total_amount   INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sale_session_members (
        session_id INTEGER NOT NULL REFERENCES sale_sessions(id),
        sale_id    INTEGER NOT NULL REFERENCES sales(id),
        PRIMARY KEY (session_id, sale_id)
    )
    """,
    # --- Stok hareketleri: TEK DOĞRULUK KAYNAĞI --------------------------
    # TRANSFER TÜRÜ YOKTUR: V1'de stok ürün düzeyindedir, konum yalnızca
    # "nerede bulunur" bilgisidir; bir transfer hareketi ya sıfır etkilidir ya
    # da anlamsızdır. RETURN/WASTE listede durur ama V1'de ekranı yoktur.
    #
    # fill_quantity: negatif stok deliğini kapatan birim sayısı. Bu birimler
    # değere GİRMEZ, çünkü maliyetleri geçmiş satışlarda zaten donmuştur.
    """
    CREATE TABLE IF NOT EXISTS stock_movements (
        id             INTEGER PRIMARY KEY,
        product_id     INTEGER NOT NULL REFERENCES products(id),
        movement_type  TEXT    NOT NULL CHECK (movement_type IN (
                           'INITIAL_STOCK','PURCHASE','PURCHASE_REVERSAL',
                           'SALE','SALE_REVERSAL','COUNT_ADJUSTMENT',
                           'MANUAL_ADJUSTMENT','RETURN','WASTE')),
        quantity_delta INTEGER NOT NULL CHECK (quantity_delta <> 0),
        value_delta    INTEGER NOT NULL DEFAULT 0,
        unit_cost      INTEGER,
        fill_quantity  INTEGER NOT NULL DEFAULT 0 CHECK (fill_quantity >= 0),
        is_estimated_cost INTEGER NOT NULL DEFAULT 0
                       CHECK (is_estimated_cost IN (0, 1)),
        balance_after  INTEGER NOT NULL,
        ref_type       TEXT    NOT NULL DEFAULT 'MANUAL'
                       CHECK (ref_type IN ('SALE','RECEIPT','COUNT','MANUAL','INITIAL')),
        ref_id         INTEGER,
        ref_line_id    INTEGER,
        reverses_movement_id INTEGER REFERENCES stock_movements(id),
        created_at_utc INTEGER NOT NULL,
        business_date  TEXT    NOT NULL,
        note           TEXT
    )
    """,
    # --- Alış fişleri ----------------------------------------------------
    # Geri alma bir CONTRA satırdır (durum geçişi DEĞİL): satışlarla aynı
    # desen, ve kısmi tekil indeks sayesinde "iki kez geri alınamaz" garantisi
    # veritabanı düzeyindedir.
    """
    CREATE TABLE IF NOT EXISTS purchase_receipts (
        id             INTEGER PRIMARY KEY,
        status         TEXT    NOT NULL DEFAULT 'DRAFT'
                       CHECK (status IN ('DRAFT','COMMITTED')),
        supplier_id    INTEGER REFERENCES suppliers(id),
        invoice_no     TEXT,
        receipt_date   TEXT    NOT NULL,
        created_at_utc INTEGER NOT NULL,
        committed_at_utc INTEGER,
        reverses_receipt_id INTEGER REFERENCES purchase_receipts(id),
        total_cost     INTEGER NOT NULL DEFAULT 0,
        line_count     INTEGER NOT NULL DEFAULT 0,
        note           TEXT,
        CHECK (reverses_receipt_id IS NULL OR status = 'COMMITTED'),
        CHECK (reverses_receipt_id IS NULL OR total_cost <= 0)
    )
    """,
    # UNIQUE(receipt_id, product_id) DEĞİL: gerçek bir irsaliyede aynı ürün iki
    # farklı alış fiyatıyla iki satırda gelebilir. Aynı barkodun tekrar
    # okutulması mevcut satırı artırır — bu ARAYÜZ davranışıdır, şema kısıtı değil.
    """
    CREATE TABLE IF NOT EXISTS purchase_receipt_lines (
        id             INTEGER PRIMARY KEY,
        receipt_id     INTEGER NOT NULL REFERENCES purchase_receipts(id),
        line_no        INTEGER NOT NULL,
        product_id     INTEGER NOT NULL REFERENCES products(id),
        quantity       INTEGER NOT NULL CHECK (quantity <> 0),
        unit_cost      INTEGER NOT NULL CHECK (unit_cost >= 0),
        line_total     INTEGER NOT NULL,
        previous_unit_cost INTEGER,
        barcode_used   TEXT,
        barcode_multiplier INTEGER NOT NULL DEFAULT 1,
        UNIQUE (receipt_id, line_no)
    )
    """,
    # --- Sayım -----------------------------------------------------------
    # Kısmi konum sayımı stoğu ASLA düzeltmez: bir ürünün stoğu ancak AKTİF
    # KONUMLARININ TAMAMI aynı oturumda sayıldığında (coverage_state='FULL')
    # düzeltilir. Aksi hâlde satır bilgi amaçlıdır.
    """
    CREATE TABLE IF NOT EXISTS count_sessions (
        id             INTEGER PRIMARY KEY,
        status         TEXT    NOT NULL DEFAULT 'DRAFT'
                       CHECK (status IN ('DRAFT','COMMITTED','CANCELLED')),
        scope          TEXT    NOT NULL DEFAULT 'LOCATION'
                       CHECK (scope IN ('LOCATION','ALL')),
        category_id    INTEGER REFERENCES categories(id),
        blind          INTEGER NOT NULL DEFAULT 0 CHECK (blind IN (0, 1)),
        created_at_utc INTEGER NOT NULL,
        committed_at_utc INTEGER,
        total_diff_qty   INTEGER NOT NULL DEFAULT 0,
        total_diff_value INTEGER NOT NULL DEFAULT 0,
        note           TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS count_session_locations (
        session_id  INTEGER NOT NULL REFERENCES count_sessions(id),
        location_id INTEGER NOT NULL REFERENCES locations(id),
        PRIMARY KEY (session_id, location_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS count_lines (
        id             INTEGER PRIMARY KEY,
        session_id     INTEGER NOT NULL REFERENCES count_sessions(id),
        product_id     INTEGER NOT NULL REFERENCES products(id),
        system_qty_at_entry INTEGER NOT NULL,
        system_qty_final    INTEGER,
        counted_qty    INTEGER,
        coverage_state TEXT    NOT NULL DEFAULT 'UNCOUNTED'
                       CHECK (coverage_state IN ('FULL','PARTIAL','UNCOUNTED')),
        active_location_count_at_commit INTEGER,
        is_baseline    INTEGER NOT NULL DEFAULT 0 CHECK (is_baseline IN (0, 1)),
        difference     INTEGER,
        unit_cost_at_commit INTEGER,
        value_difference    INTEGER,
        adjustment_movement_id INTEGER REFERENCES stock_movements(id),
        reason         TEXT,
        UNIQUE (session_id, product_id)
    )
    """,
    # Konum başına ALT TOPLAM. Aynı ürün iki konumda sayılırsa değerler
    # TOPLANIR, birbirinin üzerine YAZILMAZ → ne çift sayım ne kayıp sayım.
    """
    CREATE TABLE IF NOT EXISTS count_line_locations (
        id             INTEGER PRIMARY KEY,
        session_id     INTEGER NOT NULL REFERENCES count_sessions(id),
        product_id     INTEGER NOT NULL REFERENCES products(id),
        location_id    INTEGER NOT NULL REFERENCES locations(id),
        counted_qty    INTEGER NOT NULL DEFAULT 0,
        counted_at_utc INTEGER NOT NULL,
        UNIQUE (session_id, product_id, location_id)
    )
    """,
    # --- Sepet taslakları ------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS cart_drafts (
        id             INTEGER PRIMARY KEY,
        label          TEXT,
        status         TEXT    NOT NULL DEFAULT 'OPEN'
                       CHECK (status IN ('OPEN','CHECKED_OUT','CANCELLED')),
        created_at_utc INTEGER NOT NULL,
        updated_at_utc INTEGER NOT NULL,
        checked_out_sale_id INTEGER REFERENCES sales(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cart_draft_lines (
        id             INTEGER PRIMARY KEY,
        draft_id       INTEGER NOT NULL REFERENCES cart_drafts(id),
        line_no        INTEGER NOT NULL,
        product_id     INTEGER NOT NULL REFERENCES products(id),
        quantity       INTEGER NOT NULL CHECK (quantity > 0),
        unit_price     INTEGER NOT NULL,
        UNIQUE (draft_id, line_no)
    )
    """,
    # --- Özet tabloları --------------------------------------------------
    # Panel ve analiz sorgularını milyonlarca satır taramaktan kurtarır.
    # Satış işlemiyle AYNI transaction içinde güncellenir; geri alma bu
    # tabloları ORİJİNAL satışın business_date'inde düşer, bugünde değil.
    """
    CREATE TABLE IF NOT EXISTS product_daily_sales (
        business_date TEXT    NOT NULL,
        product_id    INTEGER NOT NULL REFERENCES products(id),
        quantity      INTEGER NOT NULL DEFAULT 0,
        amount        INTEGER NOT NULL DEFAULT 0,
        cost          INTEGER NOT NULL DEFAULT 0,
        sale_count    INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (business_date, product_id)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_sales_rollup (
        business_date TEXT    PRIMARY KEY,
        sale_count    INTEGER NOT NULL DEFAULT 0,
        total_amount  INTEGER NOT NULL DEFAULT 0,
        total_cost    INTEGER NOT NULL DEFAULT 0,
        item_count    INTEGER NOT NULL DEFAULT 0,
        cash_amount   INTEGER NOT NULL DEFAULT 0,
        card_amount   INTEGER NOT NULL DEFAULT 0
    ) WITHOUT ROWID
    """,
    # --- Denetim ---------------------------------------------------------
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id             INTEGER PRIMARY KEY,
        created_at_utc INTEGER NOT NULL,
        actor          TEXT    NOT NULL DEFAULT 'USER'
                       CHECK (actor IN ('USER','SYSTEM','MIGRATION')),
        action         TEXT    NOT NULL,
        entity_type    TEXT,
        entity_id      INTEGER,
        summary_tr     TEXT    NOT NULL,
        details_json   TEXT
    )
    """,
]


_V1_INDEXES = [
    # --- Barkod okutma: en sıcak sorgu -----------------------------------
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_barcode_active "
    "  ON product_barcodes(barcode_norm) WHERE active = 1",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_barcode_gtin_active "
    "  ON product_barcodes(gtin14) WHERE active = 1 AND gtin14 IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_barcodes_product "
    "  ON product_barcodes(product_id, active)",

    # --- Katalog tekillikleri --------------------------------------------
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_categories_parent_name "
    "  ON categories(IFNULL(parent_id, 0), name_norm)",

    # --- Ürün arama / listeleme / gruplama -------------------------------
    "CREATE INDEX IF NOT EXISTS ix_products_name_norm ON products(name_norm)",
    "CREATE INDEX IF NOT EXISTS ix_products_cat "
    "  ON products(category_id, is_active, name_norm)",
    "CREATE INDEX IF NOT EXISTS ix_products_brand "
    "  ON products(brand_id, is_active, name_norm)",
    "CREATE INDEX IF NOT EXISTS ix_products_family "
    "  ON products(family_id) WHERE family_id IS NOT NULL",

    # --- Dikkat listeleri (üretilmiş sütun sayesinde indeksli) -----------
    "CREATE INDEX IF NOT EXISTS ix_products_stock_state "
    "  ON products(stock_state, name_norm) WHERE is_active = 1",
    "CREATE INDEX IF NOT EXISTS ix_products_last_sale "
    "  ON products(last_sale_at_utc) WHERE is_active = 1",

    # --- Ürün konumları ---------------------------------------------------
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_product_location_active "
    "  ON product_locations(product_id, location_id) WHERE active = 1",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_product_primary_location "
    "  ON product_locations(product_id) WHERE is_primary = 1 AND active = 1",
    "CREATE INDEX IF NOT EXISTS ix_product_locations_loc "
    "  ON product_locations(location_id, active)",

    # --- Satışlar ---------------------------------------------------------
    "CREATE INDEX IF NOT EXISTS ix_sales_bdate ON sales(business_date, id)",
    "CREATE INDEX IF NOT EXISTS ix_sales_created ON sales(created_at_utc)",
    "CREATE INDEX IF NOT EXISTS ix_sales_dow_hour "
    "  ON sales(local_dow, local_hour) WHERE entry_type = 'SALE'",
    # "İki kez geri alınamaz" GARANTİSİ — kod değil, veritabanı sağlar.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_sales_one_reversal "
    "  ON sales(reverses_sale_id) WHERE reverses_sale_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_sale_items_sale ON sale_items(sale_id)",
    "CREATE INDEX IF NOT EXISTS ix_sale_items_product "
    "  ON sale_items(product_id, sale_id)",

    # --- Hareket defteri --------------------------------------------------
    "CREATE INDEX IF NOT EXISTS ix_moves_product ON stock_movements(product_id, id)",
    "CREATE INDEX IF NOT EXISTS ix_moves_bdate ON stock_movements(business_date)",
    "CREATE INDEX IF NOT EXISTS ix_moves_ref ON stock_movements(ref_type, ref_id)",
    # Çifte geri alma DEFTER düzeyinde imkânsız — hangi serviste hata olursa olsun.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_moves_one_reversal "
    "  ON stock_movements(reverses_movement_id) WHERE reverses_movement_id IS NOT NULL",

    # --- Alış -------------------------------------------------------------
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_receipts_one_reversal "
    "  ON purchase_receipts(reverses_receipt_id) WHERE reverses_receipt_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_receipts_supplier "
    "  ON purchase_receipts(supplier_id, receipt_date) WHERE status = 'COMMITTED'",
    "CREATE INDEX IF NOT EXISTS ix_rlines_product "
    "  ON purchase_receipt_lines(product_id, receipt_id)",
    "CREATE INDEX IF NOT EXISTS ix_rlines_receipt ON purchase_receipt_lines(receipt_id)",

    # --- Sayım ------------------------------------------------------------
    "CREATE INDEX IF NOT EXISTS ix_count_lines_session ON count_lines(session_id)",
    "CREATE INDEX IF NOT EXISTS ix_count_line_locations_session "
    "  ON count_line_locations(session_id, product_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_one_draft_count "
    "  ON count_sessions(status) WHERE status = 'DRAFT'",

    # --- Özet / denetim ---------------------------------------------------
    "CREATE INDEX IF NOT EXISTS ix_pds_product "
    "  ON product_daily_sales(product_id, business_date)",
    "CREATE INDEX IF NOT EXISTS ix_audit_entity "
    "  ON audit_log(entity_type, entity_id, id)",
    "CREATE INDEX IF NOT EXISTS ix_audit_created ON audit_log(created_at_utc)",
    "CREATE INDEX IF NOT EXISTS ix_sale_sessions_bdate "
    "  ON sale_sessions(business_date, id)",
]


# --- Başlangıç verisi ------------------------------------------------------
#: Kategori ağacı: (üst kategori, [alt kategoriler])
#: Kategori şablonu (plan §6.1): 5 üst + 29 alt = 34 kategori. YENİ kurulumlar
#: bununla başlar. Mevcut kurulumlar kendiliğinden DEĞİŞMEZ; Kategoriler
#: ekranındaki "Şablondan eksikleri ekle" önizlemeyle uygular.
#: (V1.0/V1.1 kurulumları 20 kategorilik eski ağaçla başlamıştı.)
KATEGORI_SABLONU: list[tuple[str, list[str]]] = [
    ("Alkollü İçecekler", ["Bira", "Rakı", "Viski", "Votka", "Şarap", "Cin", "Tekila",
                           "Likör"]),
    ("Tütün", ["Sigara", "Puro / Sigarillo", "Tütün", "Tütün Aksesuarı"]),
    ("Soğuk İçecek", ["Kola", "Gazoz", "Enerji İçeceği", "Meyve Suyu", "Su", "Soda"]),
    ("Atıştırmalık", ["Cips", "Kuruyemiş", "Çikolata", "Bisküvi", "Kraker", "Şekerleme",
                      "Sakız"]),
    ("Diğer", ["Çakmak", "Pil", "Buz", "Diğer"]),
]
#: Yeni kurulum tohumu (v1 göçünün veri adımı) şablonu kullanır.
DEFAULT_CATEGORIES = KATEGORI_SABLONU

#: (ad, tür, soğutmalı mı)
DEFAULT_LOCATIONS: list[tuple[str, str, int]] = [
    ("Bira Dolabı", "DOLAP", 1),
    ("Meşrubat Dolabı", "DOLAP", 1),
    ("Alkol Rafı", "RAF", 0),
    ("Sigara Rafı", "RAF", 0),
    ("Kasa Önü", "KASA_ONU", 0),
    ("Cips Standı", "STAND", 0),
    ("Kuruyemiş Bölümü", "RAF", 0),
    ("Depo", "DEPO", 0),
]

DEFAULT_SETTINGS: dict[str, str] = {
    # --- Çalışma kipi ---
    # SALES_FIRST: dokunmatik POS akışı (varsayılan).
    # INVENTORY_TRACKED: V1'in envanter odaklı davranışı.
    # YALNIZCA sunum/iş akışını etkiler; defteri ve değişmezleri ETKİLEMEZ.
    "operating_mode": "SALES_FIRST",
    # Satıştan sonra son tutarın müşteri ekranında kalma süresi.
    "customer_display_hold_ms": "4000",
    # --- Satış ---
    "default_sale_mode": "HIZLI",
    "smart_grouping_enabled": "0",
    "smart_grouping_threshold_seconds": "20",
    "pack_confirm_in_sale": "1",
    "ask_payment_method": "0",
    # --- Barkod ---
    # 120 ms: okuyucu çift-tetiklemesi (~10-30 ms) yakalanır, ama aynı ürünü
    # arka arkaya okutmak (>=250 ms) ENGELLENMEZ. Bu uygulamada tekrar okutmak
    # birincil miktar giriş yöntemidir; pencere geniş olursa gerçek satış düşer.
    "duplicate_scan_ms": "120",
    "barcode_trim_prefix": "",
    "barcode_trim_suffix": "",
    # --- Fiyat / vergi ---
    "prices_include_vat": "1",
    "default_vat_rate": "20",
    # --- Stok eşikleri (YENİ ÜRÜN varsayılanı) ---
    "default_min_stock": "6",
    "default_critical_stock": "2",
    "slow_moving_days": "45",
    "large_count_diff_threshold": "20",
    # Toplu fiyat değişikliğinde yuvarlama adımı (kuruş): 1 | 50 | 100 | 500.
    # Artışlar yukarı, düşüşler aşağı yuvarlanır (yön korunur).
    "price_rounding": "100",
    # --- Yedekleme ---
    "auto_backup_interval_minutes": "120",
    "auto_backup_retention": "10",
    "manual_backup_dir": "",
    "last_backup_at_utc": "0",
    "last_backup_data_version": "0",
    # --- Kasa (V1.2) ---
    # Hızlı Satış gizlenebilir (menü, Ana Ekran kartı, F1).
    "show_quick_sale": "1",
    # Açılış ekranı: AUTO (kipe göre) | sepetli_satis | hizli_satis | ana_ekran.
    "startup_page": "AUTO",
    # KART düğmesi gizlenebilir (yalnızca nakit çalışan dükkân); NAKİT daima var.
    "show_card_button": "1",
    # NAKİT'te para üstü hesaplayıcısı (F4). Kapalıyken NAKİT tek dokunuştur.
    "cash_change_calculator": "0",
    # --- Arayüz ---
    # Kapalı menü grupları (iç ayar). "VARSAYILAN": kipe göre (SALES_FIRST'te
    # STOK kapalı başlar); kullanıcı açıp kapatınca virgüllü liste yazılır.
    "nav_collapsed_groups": "VARSAYILAN",
    # Ürün Ara vb. alanlarda ekran klavyesi (klavyesiz dokunmatik kasa).
    "ekran_klavyesi": "1",
    "sound_enabled": "1",
    "window_geometry": "",
    "window_maximized": "0",
    # --- Bakım ---
    "last_seen_clock_utc": "0",
}


def _v1_seed(conn: sqlite3.Connection) -> None:
    """Kategori ağacı, konumlar, iş günü kuralı ve varsayılan ayarlar."""
    now = _now()

    conn.execute(
        "INSERT INTO business_day_rules(effective_from, start_hour, created_at_utc, note) "
        "VALUES(?, ?, ?, ?)",
        (
            BEGINNING_OF_TIME,
            DEFAULT_BUSINESS_DAY_START_HOUR,
            now,
            "Varsayılan: takvim günü (gece 00:00'da yeni gün başlar).",
        ),
    )

    for order, (parent_name, children) in enumerate(DEFAULT_CATEGORIES):
        cursor = conn.execute(
            "INSERT INTO categories(parent_id, name, name_norm, sort_order, created_at_utc) "
            "VALUES(NULL, ?, ?, ?, ?)",
            (parent_name, normalize_name(parent_name), order, now),
        )
        parent_id = cursor.lastrowid
        for child_order, child in enumerate(children):
            conn.execute(
                "INSERT INTO categories(parent_id, name, name_norm, sort_order, created_at_utc) "
                "VALUES(?, ?, ?, ?, ?)",
                (parent_id, child, normalize_name(child), child_order, now),
            )

    for order, (name, kind, cooled) in enumerate(DEFAULT_LOCATIONS):
        conn.execute(
            "INSERT INTO locations(name, name_norm, type, is_cooled, sort_order, created_at_utc) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (name, normalize_name(name), kind, cooled, order, now),
        )

    seed_settings(conn)


def seed_settings(conn: sqlite3.Connection) -> None:
    """Eksik ayar anahtarlarını tamamlar; mevcut değerleri DEĞİŞTİRMEZ.

    Her açılışta çağrılır, böylece yeni sürümde eklenen bir ayar eski
    veritabanlarında da kendiliğinden belirir.
    """
    now = _now()
    conn.executemany(
        "INSERT INTO settings(key, value, updated_at_utc) VALUES(?, ?, ?) "
        "ON CONFLICT(key) DO NOTHING",
        [(key, value, now) for key, value in DEFAULT_SETTINGS.items()],
    )


def _now() -> int:
    from app.core.clock import now_utc

    return now_utc()


#: v2 (V1.2 M3b) — Bekleyen sepetler ve taslak satırı kopyaları. YALNIZCA
#: ekleme: mevcut AÇIK taslaklar ``AUTOSAVE`` olur (V1.1 kurtarma anlamı).
_V2_BEKLEYEN_SEPETLER = [
    "ALTER TABLE cart_drafts ADD COLUMN kind TEXT NOT NULL DEFAULT 'AUTOSAVE' "
    "CHECK (kind IN ('AUTOSAVE','PARKED'))",
    "ALTER TABLE cart_drafts ADD COLUMN parked_at_utc INTEGER",
    "ALTER TABLE cart_draft_lines ADD COLUMN product_name_snapshot TEXT",
    "ALTER TABLE cart_draft_lines ADD COLUMN barcode_used TEXT",
    "ALTER TABLE cart_draft_lines ADD COLUMN barcode_multiplier INTEGER NOT NULL "
    "DEFAULT 1 CHECK (barcode_multiplier >= 1)",
    "CREATE INDEX IF NOT EXISTS ix_cart_drafts_open ON cart_drafts(status, kind)",
]

#: v3 (V1.2 M4b) — Referans (katalog) alış fiyatı. Gerçek alış geçmişi
#: (``last_purchase_cost``) DEĞİLDİR: stok değerine, havuza ve maliyet
#: kapsamına ASLA girmez. Mevcut ürünlerde NULL.
_V3_REFERANS_MALIYET = [
    "ALTER TABLE products ADD COLUMN reference_cost INTEGER "
    "CHECK (reference_cost IS NULL OR reference_cost >= 0)",
    "ALTER TABLE products ADD COLUMN reference_cost_updated_at_utc INTEGER",
]

#: v4 (V1.2 M5a) — Toplu fiyat değişikliği grupları. Fiyat geçmişi satırı
#: hangi toplu işlemle yazıldığını taşır; bir grup YALNIZCA BİR KEZ geri
#: alınabilir (benzersiz kısmi indeks). Mevcut geçmiş satırları: NULL (elle).
_V4_FIYAT_GRUPLARI = [
    """
    CREATE TABLE IF NOT EXISTS price_change_batches (
        id                INTEGER PRIMARY KEY,
        created_at_utc    INTEGER NOT NULL,
        kind              TEXT    NOT NULL
                          CHECK (kind IN ('TOPLU','ICE_AKTARMA','GERI_ALMA','MAL_KABUL')),
        description       TEXT,
        product_count     INTEGER NOT NULL DEFAULT 0 CHECK (product_count >= 0),
        reverses_batch_id INTEGER REFERENCES price_change_batches(id)
    )
    """,
    "ALTER TABLE price_history ADD COLUMN batch_id INTEGER "
    "REFERENCES price_change_batches(id)",
    "CREATE INDEX IF NOT EXISTS ix_price_history_product "
    "ON price_history(product_id, changed_at_utc, id)",
    "CREATE INDEX IF NOT EXISTS ix_price_history_batch "
    "ON price_history(batch_id) WHERE batch_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_price_batches_one_reversal "
    "ON price_change_batches(reverses_batch_id) WHERE reverses_batch_id IS NOT NULL",
]

#: Her göç ya SQL metni ya da ``conn`` alan bir fonksiyondur. Göçler bir kez
#: işlendikten sonra DEĞİŞTİRİLMEZ; yalnızca yeni sürüm eklenir.
MIGRATIONS: list[tuple[int, list]] = [
    (1, [*_V1_TABLES, *_V1_INDEXES, _v1_seed]),
    (2, _V2_BEKLEYEN_SEPETLER),
    (3, _V3_REFERANS_MALIYET),
    (4, _V4_FIYAT_GRUPLARI),
]
