"""Stok sayımı: fiziksel alanlara göre, kısmi sayımdan korunarak.

Neden konum bir FİLTREDİR, yetki değil
--------------------------------------
V1'de stok ürün TOPLAMI düzeyinde tutulur, ama bir ürün aynı anda birden fazla
yerde bulunabilir. Coca-Cola hem Meşrubat Dolabı'nda hem Depo'da ise, yalnızca
dolabı sayıp bulunan 12 adedi toplam sistem stoğu 40 ile karşılaştırmak
**-28'lik sahte bir düzeltme** üretir. Bu, V1'in en tehlikeli veri kaybı
senaryosudur.

Kural: bir ürünün stoğu ancak **aktif konumlarının tamamı aynı oturumda
sayıldığında** (``coverage_state='FULL'``) düzeltilir. Aksi hâlde satır bilgi
amaçlıdır ve HİÇBİR stok hareketi üretilmez.

Konum başına alt toplam tutulur (``count_line_locations``), böylece aynı ürün
iki konumda sayıldığında değerler TOPLANIR, birbirinin üzerine yazılmaz — ne
çift sayım olur ne de kayıp sayım.

Sayım sürerken ürün satılırsa
-----------------------------
Onaylama anında sistem stoğu YENİDEN okunur. Oturum başındakinden farklıysa o
satır atlanır ve işaretlenir; yoksa satış sırasında oluşan fark, sayım farkı
sanılıp "hayalet düzeltme" yazılırdı.
"""
from __future__ import annotations

import logging
import sqlite3

from app.core import costing
from app.core.clock import now_utc
from app.core.db import Database
from app.core.errors import AcikSayimVar, SayimBulunamadi, SayimZatenTamamlanmis
from app.core.models import CountCommitResult, CoverageState, MovementType, RefType

log = logging.getLogger(__name__)


class CountService:
    def __init__(self, db: Database, settings, inventory, catalog, audit) -> None:
        self.db = db
        self.settings = settings
        self.inventory = inventory
        self.catalog = catalog
        self.audit = audit

    # ===================== Oturum ========================================
    def open_session(self) -> sqlite3.Row | None:
        """Tamamlanmamış sayım. Aynı anda YALNIZCA BİR tane olabilir."""
        return self.db.query_one(
            "SELECT * FROM count_sessions WHERE status = 'DRAFT' LIMIT 1"
        )

    def start(
        self,
        location_ids: list[int] | None = None,
        scope: str = "LOCATION",
        blind: bool = False,
        category_id: int | None = None,
        note: str | None = None,
    ) -> int:
        """Yeni sayım başlatır ve sayılacak ürünlerin sistem stoğunu dondurur."""
        if self.open_session() is not None:
            raise AcikSayimVar()
        if scope == "LOCATION" and not location_ids:
            raise SayimBulunamadi()

        now = now_utc()
        with self.db.transaction() as conn:
            session_id = conn.execute(
                "INSERT INTO count_sessions(status, scope, category_id, blind, "
                "  created_at_utc, note) VALUES('DRAFT',?,?,?,?,?)",
                (scope, category_id, int(bool(blind)), now, note),
            ).lastrowid

            for location_id in location_ids or []:
                conn.execute(
                    "INSERT INTO count_session_locations(session_id, location_id) "
                    "VALUES(?,?)",
                    (session_id, location_id),
                )

            for product_id in self._products_in_scope(conn, scope, location_ids, category_id):
                urun = self.inventory.product_row(product_id, conn)
                conn.execute(
                    "INSERT INTO count_lines(session_id, product_id, system_qty_at_entry) "
                    "VALUES(?,?,?)",
                    (session_id, product_id, urun["current_stock"]),
                )
            return session_id

    def add_location(self, session_id: int, location_id: int) -> None:
        """Açık sayıma bir konum daha ekler ("Depo'yu da Say").

        Kapsamı genişletir; böylece birden fazla yerde bulunan ürünler
        ``FULL`` hâle gelip düzeltilebilir olur.
        """
        with self.db.transaction() as conn:
            self._require_draft(conn, session_id)
            conn.execute(
                "INSERT INTO count_session_locations(session_id, location_id) "
                "VALUES(?,?) ON CONFLICT DO NOTHING",
                (session_id, location_id),
            )
            mevcut = {
                row["product_id"]
                for row in conn.execute(
                    "SELECT product_id FROM count_lines WHERE session_id = ?",
                    (session_id,),
                ).fetchall()
            }
            for product_id in self.catalog.products_in_locations([location_id]):
                if product_id in mevcut:
                    continue
                urun = self.inventory.product_row(product_id, conn)
                conn.execute(
                    "INSERT INTO count_lines(session_id, product_id, system_qty_at_entry) "
                    "VALUES(?,?,?)",
                    (session_id, product_id, urun["current_stock"]),
                )

    def session_locations(self, session_id: int) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT l.* FROM count_session_locations sl "
            "  JOIN locations l ON l.id = sl.location_id "
            " WHERE sl.session_id = ? ORDER BY l.sort_order, l.name_norm",
            (session_id,),
        )

    def _products_in_scope(
        self,
        conn: sqlite3.Connection,
        scope: str,
        location_ids: list[int] | None,
        category_id: int | None,
    ) -> list[int]:
        if scope == "ALL":
            sql = "SELECT id FROM products WHERE is_active = 1"
            params: list = []
            if category_id is not None:
                ids = self.catalog.descendant_category_ids(category_id)
                sql += f" AND category_id IN ({','.join('?' * len(ids))})"
                params.extend(ids)
            return [row["id"] for row in conn.execute(sql, params).fetchall()]

        yer = ",".join("?" * len(location_ids or []))
        rows = conn.execute(
            f"SELECT DISTINCT pl.product_id FROM product_locations pl "
            f"  JOIN products p ON p.id = pl.product_id "
            f" WHERE pl.active = 1 AND p.is_active = 1 AND pl.location_id IN ({yer})",
            location_ids or [],
        ).fetchall()
        return [row["product_id"] for row in rows]

    # ===================== Sayma =========================================
    def count_scan(self, session_id: int, product_id: int, location_id: int) -> int:
        """Barkodla sayım: bir okutma = o konumda +1 adet."""
        return self._add_count(session_id, product_id, location_id, delta=1)

    def set_counted(
        self, session_id: int, product_id: int, location_id: int, quantity: int
    ) -> int:
        """Listeden sayım: o konumdaki adet doğrudan yazılır."""
        return self._add_count(session_id, product_id, location_id, absolute=quantity)

    def _add_count(
        self,
        session_id: int,
        product_id: int,
        location_id: int,
        delta: int | None = None,
        absolute: int | None = None,
    ) -> int:
        now = now_utc()
        with self.db.transaction() as conn:
            self._require_draft(conn, session_id)

            # Ürün sayım listesinde yoksa (yanlış rafa konmuş olabilir) eklenir:
            # okutulan hiçbir ürün sessizce kaybolmaz.
            conn.execute(
                "INSERT INTO count_lines(session_id, product_id, system_qty_at_entry) "
                "SELECT ?, ?, current_stock FROM products WHERE id = ? "
                "  AND NOT EXISTS (SELECT 1 FROM count_lines "
                "                   WHERE session_id = ? AND product_id = ?)",
                (session_id, product_id, product_id, session_id, product_id),
            )

            if absolute is not None:
                conn.execute(
                    "INSERT INTO count_line_locations(session_id, product_id, "
                    "  location_id, counted_qty, counted_at_utc) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(session_id, product_id, location_id) DO UPDATE SET "
                    "  counted_qty = excluded.counted_qty, "
                    "  counted_at_utc = excluded.counted_at_utc",
                    (session_id, product_id, location_id, max(0, absolute), now),
                )
            else:
                conn.execute(
                    "INSERT INTO count_line_locations(session_id, product_id, "
                    "  location_id, counted_qty, counted_at_utc) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(session_id, product_id, location_id) DO UPDATE SET "
                    "  counted_qty = counted_qty + excluded.counted_qty, "
                    "  counted_at_utc = excluded.counted_at_utc",
                    (session_id, product_id, location_id, delta or 0, now),
                )

            # Satır toplamı DAİMA konum alt toplamlarının toplamıdır (I30).
            toplam = self._sync_line_total(conn, session_id, product_id, now)
            return toplam

    def _sync_line_total(
        self, conn: sqlite3.Connection, session_id: int, product_id: int, now: int
    ) -> int:
        toplam = conn.execute(
            "SELECT COALESCE(SUM(counted_qty), 0) FROM count_line_locations "
            " WHERE session_id = ? AND product_id = ?",
            (session_id, product_id),
        ).fetchone()[0]
        conn.execute(
            "UPDATE count_lines SET counted_qty = ? "
            " WHERE session_id = ? AND product_id = ?",
            (toplam, session_id, product_id),
        )
        return toplam

    def lines(self, session_id: int, only_counted: bool = False) -> list[sqlite3.Row]:
        sql = (
            "SELECT cl.*, p.name, p.current_stock, p.unit_label "
            "  FROM count_lines cl JOIN products p ON p.id = cl.product_id "
            " WHERE cl.session_id = ?"
        )
        if only_counted:
            sql += " AND cl.counted_qty IS NOT NULL"
        sql += " ORDER BY p.name_norm"
        return self.db.query(sql, (session_id,))

    def line_locations(self, session_id: int, product_id: int) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT ll.*, l.name FROM count_line_locations ll "
            "  JOIN locations l ON l.id = ll.location_id "
            " WHERE ll.session_id = ? AND ll.product_id = ? ORDER BY l.sort_order",
            (session_id, product_id),
        )

    # ===================== Kapsam ========================================
    def coverage_of(
        self, conn: sqlite3.Connection, session_id: int, product_id: int, scope: str
    ) -> tuple[str, list[str]]:
        """(kapsam durumu, sayılmayan konum adları).

        Kapsam ONAY ANINDA yeniden hesaplanır; oturum sürerken ürünün konumları
        değiştiyse bu kendiliğinden yakalanır ve satır ``PARTIAL``a düşer.
        """
        if scope == "ALL":
            return CoverageState.FULL, []

        aktif = self.catalog.active_location_ids(product_id, conn)
        sayilan = {
            row["location_id"]
            for row in conn.execute(
                "SELECT location_id FROM count_session_locations WHERE session_id = ?",
                (session_id,),
            ).fetchall()
        }
        eksik = aktif - sayilan
        if not aktif:
            # Hiç rafı olmayan ürün ancak "Tüm Dükkân" sayımında düzeltilebilir.
            return CoverageState.PARTIAL, []
        if eksik:
            adlar = [
                row["name"]
                for row in conn.execute(
                    f"SELECT name FROM locations WHERE id IN ({','.join('?' * len(eksik))})",
                    list(eksik),
                ).fetchall()
            ]
            return CoverageState.PARTIAL, adlar
        return CoverageState.FULL, []

    def coverage_report(self, session_id: int) -> list[tuple[str, list[str]]]:
        """Onaylamadan ÖNCE gösterilir: hangi ürünler neden düzeltilemeyecek."""
        oturum = self._session(session_id)
        rapor: list[tuple[str, list[str]]] = []
        with self.db.transaction(mutating=False) as conn:
            for satir in self.lines(session_id, only_counted=True):
                durum, eksik = self.coverage_of(
                    conn, session_id, satir["product_id"], oturum["scope"]
                )
                if durum == CoverageState.PARTIAL:
                    rapor.append((satir["name"], eksik))
        return rapor

    # ===================== Onay ==========================================
    def commit(self, session_id: int) -> CountCommitResult:
        """Sayımı ATOMİK olarak işler.

        Sayılan her satır için sırayla:
          1. Kapsam yeniden hesaplanır — PARTIAL ise ATLANIR (hareket YOK).
          2. Sistem stoğu yeniden okunur — oturum başındakinden farklıysa
             ATLANIR (hayalet düzeltme yazılmaz).
          3. Fark sıfır değilse ``COUNT_ADJUSTMENT`` yazılır.

        İlk sayım (ürün daha önce hiç sayılmamışsa) ``is_baseline`` ile
        işaretlenir: düzeltme yine O ANKİ sistem stoğuna göre hesaplanır —
        çünkü başlatmadan önce yapılan satışlar gerçekten raftan çıkmıştır.
        """
        stamp = self.settings.calendar().stamp()
        with self.db.transaction() as conn:
            oturum = self._require_draft(conn, session_id)
            scope = oturum["scope"]

            uygulanan: list[tuple[str, int]] = []
            kismi: list[tuple[str, list[str]]] = []
            degisen: list[str] = []
            sayilmayan: list[str] = []
            temel_sayisi = 0
            toplam_fark = 0
            toplam_deger = 0

            satirlar = conn.execute(
                "SELECT cl.*, p.name, p.current_stock, p.stock_initialized_at_utc "
                "  FROM count_lines cl JOIN products p ON p.id = cl.product_id "
                " WHERE cl.session_id = ? ORDER BY p.name_norm",
                (session_id,),
            ).fetchall()

            for satir in satirlar:
                if satir["counted_qty"] is None:
                    sayilmayan.append(satir["name"])
                    conn.execute(
                        "UPDATE count_lines SET coverage_state = 'UNCOUNTED' "
                        " WHERE id = ?", (satir["id"],)
                    )
                    continue

                durum, eksik = self.coverage_of(
                    conn, session_id, satir["product_id"], scope
                )
                aktif_sayi = len(
                    self.catalog.active_location_ids(satir["product_id"], conn)
                )
                conn.execute(
                    "UPDATE count_lines SET coverage_state = ?, "
                    "  active_location_count_at_commit = ? WHERE id = ?",
                    (durum, aktif_sayi, satir["id"]),
                )

                if durum == CoverageState.PARTIAL:
                    # Ürün birden fazla yerde; hepsi sayılmadı. Stok BİLEREK
                    # değiştirilmez — kısmi sayım sahte fark üretir.
                    kismi.append((satir["name"], eksik))
                    continue

                guncel = self.inventory.product_row(satir["product_id"], conn)
                sistem_son = guncel["current_stock"]
                if sistem_son != satir["system_qty_at_entry"]:
                    degisen.append(satir["name"])
                    conn.execute(
                        "UPDATE count_lines SET system_qty_final = ?, reason = ? "
                        " WHERE id = ?",
                        (sistem_son, "SAYIM_SIRASINDA_DEGISTI", satir["id"]),
                    )
                    continue

                fark = satir["counted_qty"] - sistem_son
                temel = satir["stock_initialized_at_utc"] is None
                if temel:
                    temel_sayisi += 1

                hareket_id = None
                birim_maliyet = None
                deger_farki = 0
                if fark != 0:
                    temel_maliyet = costing.cost_basis(
                        guncel["current_stock"], guncel["stock_value"],
                        guncel["last_avg_cost"], guncel["last_purchase_cost"],
                    )
                    hareket = self.inventory.apply_movement(
                        conn, satir["product_id"], MovementType.COUNT_ADJUSTMENT,
                        fark, stamp, ref_type=RefType.COUNT, ref_id=session_id,
                        ref_line_id=satir["id"], fallback_basis=temel_maliyet,
                        note="İlk sayım" if temel else "Sayım farkı",
                    )
                    hareket_id = hareket.movement_id
                    birim_maliyet = temel_maliyet.unit_cost
                    deger_farki = hareket.value_delta
                    uygulanan.append((satir["name"], fark))
                    toplam_fark += fark
                    toplam_deger += deger_farki

                if temel:
                    conn.execute(
                        "UPDATE products SET stock_initialized_at_utc = ?, "
                        "  stock_initialized_by = 'COUNT' WHERE id = ?",
                        (stamp.created_at_utc, satir["product_id"]),
                    )

                conn.execute(
                    "UPDATE count_lines SET system_qty_final = ?, difference = ?, "
                    "  adjustment_movement_id = ?, unit_cost_at_commit = ?, "
                    "  value_difference = ?, is_baseline = ? WHERE id = ?",
                    (sistem_son, fark, hareket_id, birim_maliyet, deger_farki,
                     int(temel), satir["id"]),
                )

            conn.execute(
                "UPDATE count_sessions SET status = 'COMMITTED', committed_at_utc = ?, "
                "  total_diff_qty = ?, total_diff_value = ? WHERE id = ?",
                (stamp.created_at_utc, toplam_fark, toplam_deger, session_id),
            )
            self.audit.record(
                "SAYIM",
                f"Sayım tamamlandı: {len(uygulanan)} üründe düzeltme, "
                f"{len(kismi)} ürün kısmi kapsam nedeniyle değiştirilmedi.",
                "count", session_id, conn=conn,
            )

            return CountCommitResult(
                session_id=session_id,
                applied=uygulanan,
                skipped_partial=kismi,
                skipped_changed=degisen,
                uncounted=sayilmayan,
                baseline_count=temel_sayisi,
                total_diff_qty=toplam_fark,
                total_diff_value=toplam_deger,
            )

    def cancel(self, session_id: int) -> None:
        with self.db.transaction() as conn:
            self._require_draft(conn, session_id)
            conn.execute(
                "UPDATE count_sessions SET status = 'CANCELLED' WHERE id = ?",
                (session_id,),
            )

    # ===================== Uyarılar ======================================
    def large_differences(self, session_id: int) -> list[tuple[str, int]]:
        """Onaydan önce dikkat isteyen büyük farklar.

        Her 1 adetlik fark için uyarı GÖSTERİLMEZ — onay yorgunluğu yaratır.
        İlk kez sayılan ürünler de uyarı üretmez: orada fark beklenen şeydir.
        """
        esik = self.settings.large_count_diff_threshold()
        rows = self.db.query(
            "SELECT p.name, cl.counted_qty - p.current_stock AS fark "
            "  FROM count_lines cl JOIN products p ON p.id = cl.product_id "
            " WHERE cl.session_id = ? AND cl.counted_qty IS NOT NULL "
            "   AND p.stock_initialized_at_utc IS NOT NULL "
            "   AND ABS(cl.counted_qty - p.current_stock) >= ?",
            (session_id, esik),
        )
        return [(row["name"], row["fark"]) for row in rows]

    # ===================== Geçmiş ========================================
    def history(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM count_sessions WHERE status <> 'DRAFT' "
            " ORDER BY id DESC LIMIT ?",
            (max(1, min(200, limit)),),
        )

    def _session(self, session_id: int) -> sqlite3.Row:
        row = self.db.query_one(
            "SELECT * FROM count_sessions WHERE id = ?", (session_id,)
        )
        if row is None:
            raise SayimBulunamadi()
        return row

    def _require_draft(self, conn: sqlite3.Connection, session_id: int) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM count_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise SayimBulunamadi()
        if row["status"] != "DRAFT":
            raise SayimZatenTamamlanmis()
        return row
