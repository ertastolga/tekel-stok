"""SQLite bağlantısı, işlemler (transaction), göçler ve tutarlılık denetimi.

Tasarım kararları
-----------------
* ``isolation_level=None`` — işlemleri Python'un örtük mantığı değil, BİZ
  yönetiriz. Her iş kuralı açıkça ``BEGIN IMMEDIATE`` ile başlar.
* Tek bağlantı + ``RLock`` — uygulama tek kullanıcılıdır ve tüm işlemler
  milisaniye ölçeğindedir; işçi iş parçacığı yoktur, her şey arayüz
  parçacığında çalışır.
* ``synchronous=FULL`` — hız yerine elektrik kesintisi güvenliği seçilmiştir.
  Bir kasa uygulamasında yarım yazılmış satış kabul edilemez.
* Göç sırasında ``foreign_keys=OFF``, sonrasında ``ON``; her göçün sonunda
  ``PRAGMA foreign_key_check`` çalıştırılır ki bozuk bir dönüşüm sessizce
  işlenmesin.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

from app.core import schema as schema_mod
from app.core.clock import local_now, now_utc
from app.core.errors import VeritabaniHatasi
from app.core.quantity import V1_BASE_UNIT, V1_MEASURE_KIND, V1_PRICING_BASIS
from app.core.schema import SCHEMA_VERSION
from app.core.tr import DATE_FORMAT

log = logging.getLogger(__name__)

#: Sığ denetimin baktığı geçmiş pencere (gün). Veri yıllar içinde milyonlarca
#: satıra çıkacağı için açılışta tüm tarih taranmaz.
SHALLOW_WINDOW_DAYS = 30


class Database:
    """Tek bir SQLite dosyasının sahibi."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._depth = 0
        self._changes_at_begin = 0

    # -- Yaşam döngüsü ----------------------------------------------------
    @property
    def is_open(self) -> bool:
        return self._conn is not None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise VeritabaniHatasi(detail="Bağlantı kapalı.")
        return self._conn

    def connect(self) -> "Database":
        if self._conn is not None:
            return self
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(
                str(self.path),
                check_same_thread=False,
                isolation_level=None,      # işlemleri biz yönetiyoruz
                timeout=10.0,
            )
        except sqlite3.Error as exc:
            raise VeritabaniHatasi(detail=str(exc)) from exc
        conn.row_factory = sqlite3.Row
        self._conn = conn
        self._apply_pragmas(foreign_keys=False)
        self.migrate()
        self.conn.execute("PRAGMA foreign_keys = ON")
        return self

    def _apply_pragmas(self, foreign_keys: bool = True) -> None:
        cur = self.conn
        cur.execute("PRAGMA journal_mode = WAL")
        cur.execute("PRAGMA synchronous = FULL")
        cur.execute("PRAGMA busy_timeout = 5000")
        cur.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")

    def close(self) -> None:
        if self._conn is None:
            return
        with self._lock:
            try:
                self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                self._conn.execute("PRAGMA optimize")
            except sqlite3.Error:
                log.warning("Kapanış bakımı yapılamadı", exc_info=True)
            try:
                self._conn.close()
            finally:
                self._conn = None
                self._depth = 0

    def checkpoint(self) -> None:
        with self._lock:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def integrity_check(self) -> str:
        row = self.query_one("PRAGMA integrity_check")
        return "" if row is None else str(row[0])

    # -- İşlemler ---------------------------------------------------------
    @contextmanager
    def transaction(self, mutating: bool = True) -> Iterator[sqlite3.Connection]:
        """Atomik işlem. İç içe çağrılarda yalnızca EN DIŞTAKİ commit eder.

        ``mutating=False`` yalnızca defter tutma yazıları içindir (yedek
        damgası gibi): böyle bir yazı veritabanını "değişti" saymaz, yoksa
        yedek almak yeni bir yedeği tetiklerdi.
        """
        with self._lock:
            outermost = self._depth == 0
            if outermost:
                self.conn.execute("BEGIN IMMEDIATE")
                self._changes_at_begin = self.conn.total_changes
            self._depth += 1
            try:
                yield self.conn
            except BaseException:
                self._depth -= 1
                if outermost:
                    try:
                        self.conn.execute("ROLLBACK")
                    except sqlite3.Error:
                        log.exception("Geri alma (rollback) başarısız")
                raise
            else:
                self._depth -= 1
                if outermost:
                    wrote = self.conn.total_changes > self._changes_at_begin
                    if wrote and mutating:
                        self._bump(self.conn, "data_version")
                    self.conn.execute("COMMIT")

    def _bump(self, conn: sqlite3.Connection, key: str) -> None:
        conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES(?, '1') "
            "ON CONFLICT(key) DO UPDATE SET value = CAST(value AS INTEGER) + 1",
            (key,),
        )

    def data_version(self) -> int:
        return int(self.meta("data_version", "0") or 0)

    # -- Sorgu yardımcıları ------------------------------------------------
    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.execute(sql, params)

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
        with self._lock:
            return self.conn.executemany(sql, seq)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = None) -> Any:
        row = self.query_one(sql, params)
        if row is None:
            return default
        value = row[0]
        return default if value is None else value

    # -- schema_meta -------------------------------------------------------
    def meta(self, key: str, default: str | None = None) -> str | None:
        if not self._table_exists("schema_meta"):
            return default
        row = self.query_one("SELECT value FROM schema_meta WHERE key = ?", (key,))
        return default if row is None else row["value"]

    def set_meta(self, key: str, value: str, mutating: bool = False) -> None:
        with self.transaction(mutating=mutating) as conn:
            conn.execute(
                "INSERT INTO schema_meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def _table_exists(self, name: str) -> bool:
        row = self.query_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        )
        return row is not None

    # -- Göçler ------------------------------------------------------------
    def schema_version(self) -> int:
        if not self._table_exists("schema_meta"):
            return 0
        row = self.query_one("SELECT value FROM schema_meta WHERE key='schema_version'")
        if not row:
            return 0
        try:
            return int(row["value"])
        except (TypeError, ValueError):
            return 0

    def migrate(self) -> int:
        """Bekleyen göçleri uygular. Kullanıcıya asla "veritabanını sil" denmez."""
        current = self.schema_version()
        applied = 0
        for version, statements in schema_mod.MIGRATIONS:
            if version <= current:
                continue
            with self.transaction(mutating=False) as conn:
                for statement in statements:
                    # Bir göç adımı ya SQL metnidir ya da veri dönüştüren bir
                    # fonksiyondur (yeni sütunun geçmiş satırlar için
                    # doldurulması gibi). İkisi de AYNI işlem içinde çalışır.
                    if callable(statement):
                        statement(conn)
                    else:
                        conn.execute(statement)

                # Tablo yeniden inşası yapan bir göç, yabancı anahtarları
                # sessizce koparabilir; commit'ten ÖNCE denetlenir.
                broken = conn.execute("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise VeritabaniHatasi(
                        "Veritabanı güncellemesi tamamlanamadı.",
                        f"foreign_key_check: {broken[:5]}",
                    )

                conn.execute(
                    "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(version),),
                )
            applied += 1
            log.info("Şema %s sürümüne yükseltildi", version)
        return applied

    def seed_settings(self) -> None:
        """Yeni sürümde eklenen ayar anahtarlarını tamamlar."""
        with self.transaction(mutating=False) as conn:
            schema_mod.seed_settings(conn)

    # -- Saat geri alınmış mı? --------------------------------------------
    def check_clock(self) -> str | None:
        """Makine saati geriye alınmışsa uyarı metni döner.

        Sıralama her yerde ``id`` ile yapılır (bkz. modül notları), ama yine de
        kullanıcıyı bilgilendirmek gerekir: yanlış saatle girilen satışlar
        yanlış güne yazılır.
        """
        last_seen = int(self.meta("last_seen_clock_utc", "0") or 0)
        now = now_utc()
        if last_seen and now < last_seen - 3600:
            return (
                "Bilgisayarın saati geri alınmış olabilir. "
                "Satışların doğru güne yazılması için saati kontrol edin."
            )
        return None

    def stamp_clock(self) -> None:
        self.set_meta("last_seen_clock_utc", str(now_utc()), mutating=False)

    # -- Yedekleme ---------------------------------------------------------
    def backup_to(self, destination: str | Path) -> Path:
        """SQLite yedekleme API'si ile tutarlı kopya alır.

        Çalışan bir veritabanının dosyasını kopyalamak WAL yüzünden bozuk yedek
        üretebilir; bu yüzden ``Connection.backup()`` kullanılır. Yazma önce
        ``.tmp`` dosyasına yapılır, sonra atomik olarak yerine konur — yarım
        yazılmış bir yedek dosyası hiçbir zaman ortada kalmaz.
        """
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_suffix(destination.suffix + ".tmp")
        with self._lock:
            target = sqlite3.connect(str(temp))
            try:
                self.conn.backup(target)
                target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                target.close()
        temp.replace(destination)
        return destination

    # -- Önbellek yeniden hesaplama ---------------------------------------
    def recompute_caches(self) -> None:
        """``current_stock`` / ``stock_value`` / damgaları DEFTERDEN yeniden kurar.

        Bu ancak ``value_delta`` zaten SINIRLANMIŞ olarak yazıldığı için
        mümkündür (bkz. ``app/core/costing.py``): stok değeri, defterin basit
        bir toplamıdır. Sınırlama toplamadan SONRA uygulansaydı bu onarım
        imkânsız olurdu.
        """
        with self.transaction() as conn:
            conn.execute(
                """
                UPDATE products AS p
                   SET current_stock = COALESCE(a.qty, 0),
                       stock_value   = MAX(COALESCE(a.val, 0), 0)
                  FROM (SELECT product_id,
                               SUM(quantity_delta) AS qty,
                               SUM(value_delta)    AS val
                          FROM stock_movements
                         GROUP BY product_id) AS a
                 WHERE a.product_id = p.id
                """
            )
            conn.execute(
                "UPDATE products SET current_stock = 0, stock_value = 0 "
                " WHERE id NOT IN (SELECT product_id FROM stock_movements)"
            )
            conn.execute(
                """
                UPDATE products AS p
                   SET last_sale_at_utc = a.ts
                  FROM (SELECT si.product_id, MAX(s.created_at_utc) AS ts
                          FROM sale_items si
                          JOIN sales s ON s.id = si.sale_id
                         WHERE s.entry_type = 'SALE'
                         GROUP BY si.product_id) AS a
                 WHERE a.product_id = p.id
                """
            )
            conn.execute(
                """
                UPDATE stock_movements AS m
                   SET balance_after = w.running
                  FROM (SELECT id,
                               SUM(quantity_delta) OVER (PARTITION BY product_id
                                                         ORDER BY id
                                                         ROWS UNBOUNDED PRECEDING) AS running
                          FROM stock_movements) AS w
                 WHERE w.id = m.id
                """
            )
        log.info("Stok önbellekleri defterden yeniden hesaplandı")

    # -- Tutarlılık denetimi -----------------------------------------------
    def check_invariants(self, deep: bool = False) -> list[str]:
        """Değişmezleri denetler. Boş liste = her şey tutarlı.

        Sığ kip açılışta çalışır: ürün sayısıyla orantılı denetimler artı son
        30 günün satış/alış/sayım denetimleri. ``deep=True`` tüm geçmişi tarar
        ve yalnızca Bakım ekranından çağrılır.

        Sonuçlar kullanıcıya GÖSTERİLMEZ; log'a yazılır ve Bakım ekranında
        "Yeniden Hesapla" ile onarılabilir.
        """
        problems: list[str] = []
        cutoff = (local_now() - timedelta(days=SHALLOW_WINDOW_DAYS)).strftime(DATE_FORMAT)
        window = "" if deep else " AND s.business_date >= :cutoff"
        params = {"cutoff": cutoff}

        def check(sql: str, message: str, args: dict | None = None) -> None:
            count = self.scalar(sql, args or {}, default=0)
            if count:
                problems.append(message.format(n=count))

        # --- Ürün önbelleği ↔ defter -------------------------------------
        check(
            "SELECT COUNT(*) FROM products p "
            "LEFT JOIN (SELECT product_id, SUM(quantity_delta) q FROM stock_movements "
            "           GROUP BY product_id) m ON m.product_id = p.id "
            "WHERE p.current_stock <> COALESCE(m.q, 0)",
            "I1: {n} üründe stok önbelleği defterle uyuşmuyor.",
        )
        check(
            "SELECT COUNT(*) FROM products p "
            "LEFT JOIN (SELECT product_id, SUM(value_delta) v FROM stock_movements "
            "           GROUP BY product_id) m ON m.product_id = p.id "
            "WHERE p.stock_value <> MAX(COALESCE(m.v, 0), 0)",
            "I2: {n} üründe stok değeri defterle uyuşmuyor.",
        )
        check(
            "SELECT COUNT(*) FROM products WHERE stock_value < 0",
            "I3: {n} üründe stok değeri negatif.",
        )
        check(
            "SELECT COUNT(*) FROM products WHERE current_stock <= 0 AND stock_value <> 0",
            "I4: {n} üründe stok yokken değer görünüyor.",
        )
        check(
            "SELECT COUNT(*) FROM products "
            "WHERE current_stock > 0 AND stock_value = 0 "
            "  AND last_avg_cost IS NULL AND last_purchase_cost IS NULL",
            "I5: {n} ürünün maliyet temeli yok.",
        )

        # --- Barkod / konum ----------------------------------------------
        check(
            "SELECT COUNT(*) FROM product_barcodes b "
            "LEFT JOIN products p ON p.id = b.product_id "
            "WHERE b.active = 1 AND (p.id IS NULL OR p.is_active = 0)",
            "I19: {n} etkin barkod pasif ya da silinmiş ürüne bağlı.",
        )
        check(
            "SELECT COUNT(*) FROM (SELECT product_id FROM product_locations "
            " WHERE is_primary = 1 AND active = 1 GROUP BY product_id HAVING COUNT(*) > 1)",
            "I20: {n} üründe birden fazla esas raf tanımlı.",
        )
        check(
            "SELECT COUNT(*) FROM (SELECT gtin14 FROM product_barcodes "
            " WHERE active = 1 AND gtin14 IS NOT NULL "
            " GROUP BY gtin14 HAVING COUNT(DISTINCT product_id) > 1)",
            "I32: {n} barkod birden fazla ürüne çözülüyor.",
        )

        # --- Zaman damgaları / hareket türü ------------------------------
        check(
            "SELECT COUNT(*) FROM sales "
            "WHERE local_hour NOT BETWEEN 0 AND 23 OR local_dow NOT BETWEEN 0 AND 6",
            "I21: {n} satışta geçersiz saat/gün bilgisi.",
        )
        check(
            "SELECT COUNT(*) FROM stock_movements "
            "WHERE (movement_type IN ('PURCHASE','INITIAL_STOCK') AND value_delta < 0) "
            "   OR (movement_type = 'SALE' AND value_delta > 0)",
            "I22: {n} hareket, türüyle çelişen bir değer taşıyor.",
        )

        # --- Giren malın değer formülü (delik kapatma) -------------------
        check(
            "SELECT COUNT(*) FROM stock_movements "
            "WHERE movement_type IN ('INITIAL_STOCK','PURCHASE') "
            "  AND unit_cost IS NOT NULL "
            "  AND value_delta <> (quantity_delta - fill_quantity) * unit_cost",
            "I25: {n} mal girişinde değer hesabı hatalı.",
        )
        check(
            "SELECT COUNT(*) FROM stock_movements "
            "WHERE fill_quantity < 0 "
            "   OR fill_quantity > MAX(0, -(balance_after - quantity_delta)) "
            "   OR fill_quantity > ABS(quantity_delta)",
            "I26: {n} harekette açık kapatma miktarı tutarsız.",
        )

        # --- Başlangıç stoğu ----------------------------------------------
        check(
            "SELECT COUNT(*) FROM products p "
            "WHERE p.stock_initialized_at_utc IS NOT NULL "
            "  AND NOT EXISTS (SELECT 1 FROM stock_movements m "
            "                   WHERE m.product_id = p.id AND m.movement_type = 'INITIAL_STOCK') "
            "  AND NOT EXISTS (SELECT 1 FROM count_lines cl JOIN count_sessions cs "
            "                       ON cs.id = cl.session_id "
            "                   WHERE cl.product_id = p.id AND cl.is_baseline = 1 "
            "                     AND cs.status = 'COMMITTED')",
            "I27: {n} ürün sayılmış görünüyor ama başlangıç kaydı yok.",
        )
        check(
            "SELECT COUNT(*) FROM (SELECT product_id FROM stock_movements "
            " WHERE movement_type = 'INITIAL_STOCK' GROUP BY product_id HAVING COUNT(*) > 1)",
            "I28: {n} ürüne birden fazla başlangıç stoğu girilmiş.",
        )

        # --- V1 katılığı: yalnızca sayılabilir ürün ----------------------
        check(
            "SELECT COUNT(*) FROM products "
            f"WHERE measure_kind <> '{V1_MEASURE_KIND}' "
            f"   OR base_unit <> '{V1_BASE_UNIT}' "
            f"   OR pricing_basis <> '{V1_PRICING_BASIS}'",
            "I33: {n} ürün bu sürümün desteklemediği bir ölçü türünde.",
        )

        # --- Satışlar (sığ kipte son 30 gün) -----------------------------
        check(
            "SELECT COUNT(*) FROM sales s WHERE s.total_amount <> "
            "  (SELECT COALESCE(SUM(i.line_total), 0) FROM sale_items i WHERE i.sale_id = s.id) "
            "  - s.discount_total + s.rounding_adjustment" + window,
            "I6: {n} satışın toplamı satırlarıyla uyuşmuyor.",
            params,
        )
        check(
            "SELECT COUNT(*) FROM sales s WHERE s.total_cost <> "
            "  (SELECT COALESCE(SUM(i.cost_total), 0) FROM sale_items i WHERE i.sale_id = s.id)"
            + window,
            "I7: {n} satışın maliyet toplamı uyuşmuyor.",
            params,
        )
        check(
            "SELECT COUNT(*) FROM sales s WHERE s.item_count <> "
            "  (SELECT COALESCE(SUM(i.quantity), 0) FROM sale_items i WHERE i.sale_id = s.id)"
            + window,
            "I8: {n} satışın kalem adedi uyuşmuyor.",
            params,
        )
        check(
            "SELECT COUNT(*) FROM sales s WHERE "
            "  (SELECT COUNT(*) FROM sale_items i WHERE i.sale_id = s.id) <> "
            "  (SELECT COUNT(*) FROM stock_movements m "
            "    WHERE m.ref_type = 'SALE' AND m.ref_id = s.id)" + window,
            "I9: {n} satışın stok hareketi eksik.",
            params,
        )
        check(
            "SELECT COUNT(*) FROM sales s LEFT JOIN sales o ON o.id = s.reverses_sale_id "
            "WHERE s.reverses_sale_id IS NOT NULL "
            "  AND (o.id IS NULL OR o.entry_type <> 'SALE')" + window,
            "I10: {n} geri alma satırı geçersiz satışa bağlı.",
            params,
        )
        check(
            "SELECT COUNT(*) FROM (SELECT reverses_sale_id FROM sales "
            " WHERE reverses_sale_id IS NOT NULL GROUP BY reverses_sale_id HAVING COUNT(*) > 1)",
            "I11: {n} satış birden fazla kez geri alınmış.",
        )
        check(
            "SELECT COUNT(*) FROM sales s WHERE s.entry_type = 'SALE' AND s.is_reversed <> "
            "  (CASE WHEN EXISTS (SELECT 1 FROM sales r WHERE r.reverses_sale_id = s.id) "
            "        THEN 1 ELSE 0 END)" + window,
            "I12: {n} satışın geri alma damgası tutarsız.",
            params,
        )
        check(
            "SELECT COUNT(*) FROM sales s "
            "WHERE s.entry_type = 'SALE_REVERSAL' AND s.total_amount > 0" + window,
            "I13: {n} geri alma satırı pozitif tutar taşıyor.",
            params,
        )

        # --- Alış fişleri -------------------------------------------------
        check(
            "SELECT COUNT(*) FROM purchase_receipts r WHERE r.status = 'COMMITTED' AND "
            "  (SELECT COUNT(*) FROM purchase_receipt_lines l WHERE l.receipt_id = r.id) <> "
            "  (SELECT COUNT(*) FROM stock_movements m "
            "    WHERE m.ref_type = 'RECEIPT' AND m.ref_id = r.id)",
            "I14: {n} alış fişinin stok hareketi eksik.",
        )
        check(
            "SELECT COUNT(*) FROM purchase_receipts r WHERE r.status = 'DRAFT' AND EXISTS "
            "  (SELECT 1 FROM stock_movements m WHERE m.ref_type = 'RECEIPT' AND m.ref_id = r.id)",
            "I15: {n} taslak fiş stoğu etkilemiş.",
        )
        check(
            "SELECT COUNT(*) FROM purchase_receipts r WHERE r.total_cost <> "
            "  (SELECT COALESCE(SUM(l.line_total), 0) FROM purchase_receipt_lines l "
            "    WHERE l.receipt_id = r.id)",
            "I16: {n} alış fişinin toplamı satırlarıyla uyuşmuyor.",
        )
        check(
            "SELECT COUNT(*) FROM stock_movements r "
            "JOIN stock_movements o ON o.id = r.reverses_movement_id "
            "WHERE r.movement_type = 'PURCHASE_REVERSAL' AND EXISTS "
            "  (SELECT 1 FROM stock_movements x WHERE x.product_id = o.product_id "
            "     AND x.id > o.id AND x.id <> r.id)",
            "I31: {n} fiş geri alması kanıtlanabilir değil.",
        )

        # --- Sayım ---------------------------------------------------------
        check(
            "SELECT COUNT(*) FROM count_lines cl JOIN count_sessions cs ON cs.id = cl.session_id "
            "WHERE cs.status = 'COMMITTED' AND cl.coverage_state = 'FULL' "
            "  AND cl.counted_qty IS NOT NULL "
            "  AND cl.difference <> cl.counted_qty - cl.system_qty_final",
            "I17: {n} sayım satırının farkı hatalı.",
        )
        check(
            "SELECT COUNT(*) FROM count_lines cl JOIN count_sessions cs ON cs.id = cl.session_id "
            "WHERE cs.status = 'COMMITTED' AND cl.coverage_state = 'FULL' "
            "  AND cl.difference IS NOT NULL AND cl.difference <> 0 "
            "  AND cl.adjustment_movement_id IS NULL",
            "I18: {n} sayım farkı stoğa yansımamış.",
        )
        check(
            "SELECT COUNT(*) FROM count_lines "
            "WHERE coverage_state = 'PARTIAL' AND adjustment_movement_id IS NOT NULL",
            "I29: {n} kısmi sayım satırı stoğu değiştirmiş.",
        )
        check(
            "SELECT COUNT(*) FROM count_lines cl WHERE cl.counted_qty IS NOT NULL "
            "  AND cl.counted_qty <> (SELECT COALESCE(SUM(ll.counted_qty), 0) "
            "                           FROM count_line_locations ll "
            "                          WHERE ll.session_id = cl.session_id "
            "                            AND ll.product_id = cl.product_id)",
            "I30: {n} sayım satırının konum toplamları uyuşmuyor.",
        )

        if deep:
            check(
                "SELECT COUNT(*) FROM ("
                "  SELECT d.business_date, d.product_id FROM product_daily_sales d "
                "  LEFT JOIN (SELECT s.business_date bd, i.product_id pid, "
                "                    SUM(i.quantity) q, SUM(i.line_total) amt "
                "               FROM sale_items i JOIN sales s ON s.id = i.sale_id "
                "              GROUP BY s.business_date, i.product_id) a "
                "    ON a.bd = d.business_date AND a.pid = d.product_id "
                "  WHERE d.quantity <> COALESCE(a.q, 0) OR d.amount <> COALESCE(a.amt, 0))",
                "I23: {n} günlük özet satırı satışlarla uyuşmuyor.",
            )
            check(
                "SELECT COUNT(*) FROM stock_movements m JOIN "
                "  (SELECT id, SUM(quantity_delta) OVER (PARTITION BY product_id "
                "          ORDER BY id ROWS UNBOUNDED PRECEDING) AS running "
                "     FROM stock_movements) w ON w.id = m.id "
                "WHERE m.balance_after <> w.running",
                "I24: {n} hareket satırında bakiye izi hatalı.",
            )

        return problems


def open_database(path: str | Path) -> Database:
    """Veritabanını açar, göçleri uygular ve eksik ayarları tamamlar."""
    db = Database(path).connect()
    db.seed_settings()
    return db
