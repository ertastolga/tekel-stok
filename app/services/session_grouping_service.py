"""Akıllı Hızlı Satış: satışları OLASI müşteri gruplarına ayırma.

Bu, Hızlı Satış'ın ÜZERİNE eklenen isteğe bağlı bir katmandır. Dükkân sahibi
için hiçbir şey değişmez: okut → satıldı; sepet yok, tamamla düğmesi yok.

Kritik ayrım
------------
* **KESİN** sepet verisi yalnızca Sepetli Satış'tan gelir.
* Buradaki gruplar **TAHMİNİDİR** ve asla gerçek müşteri sepeti gibi
  sunulmaz.

Ham satışlar bu işlemden ETKİLENMEZ: gruplama ayrı tablolarda
(``sale_sessions`` + ``sale_session_members``) tutulur, yeniden
hesaplanabilir ve silinse bile tek bir satış kaydı bile değişmez.

V1'de karmaşık bir algoritma YOKTUR: yalnızca ayarlanabilir bir hareketsizlik
eşiği ve kullanıcının F4 ile koyduğu kesin sınırlar. Amaç, ileride daha akıllı
analiz yapılabilsin diye HAM VERİYİ doğru saklamaktır.
"""
from __future__ import annotations

import logging
import sqlite3

from app.core.db import Database

log = logging.getLogger(__name__)

#: Algoritma sürümü kaydedilir; ileride değişirse eski gruplar ayırt edilebilir.
ALGORITHM_VERSION = "esik-v1"


class SessionGroupingService:
    def __init__(self, db: Database, settings, audit) -> None:
        self.db = db
        self.settings = settings
        self.audit = audit
        #: F4 ile konan kesin sınırlar (satış id'leri): bu satışlar YENİ bir
        #: grubun ilk üyesidir.
        self._manual_boundaries: set[int] = set()

    # ===================== Sınır işareti ==================================
    def mark_new_customer(self) -> int | None:
        """F4: 'Yeni Müşteri'.

        Yalnızca gruplama için kesin bir sınır koyar. Satışlar ZATEN anında
        işlenmiştir; bu işaret hiçbir finansal kaydı değiştirmez.
        """
        son = self.db.query_one(
            "SELECT id FROM sales WHERE entry_type = 'SALE' ORDER BY id DESC LIMIT 1"
        )
        sinir = (son["id"] + 1) if son else 1
        self._manual_boundaries.add(sinir)
        return sinir

    def pending_boundaries(self) -> set[int]:
        return set(self._manual_boundaries)

    # ===================== Gruplama =======================================
    def rebuild_for_day(self, business_date: str) -> int:
        """Bir günün Hızlı Satışlarını olası gruplara ayırır.

        Yeniden çalıştırılabilir: önce o günün TAHMİNİ grupları silinir, sonra
        yeniden kurulur. Ham satışlara tek bir yazma bile yapılmaz.
        """
        esik = self.settings.smart_grouping_threshold_seconds()
        satislar = self.db.query(
            "SELECT id, created_at_utc, total_amount FROM sales "
            " WHERE entry_type = 'SALE' AND sale_mode = 'HIZLI' "
            "   AND business_date = ? AND is_reversed = 0 "
            " ORDER BY id",
            (business_date,),
        )

        with self.db.transaction() as conn:
            self._clear_day(conn, business_date)
            if not satislar:
                return 0

            gruplar: list[list[sqlite3.Row]] = []
            mevcut: list[sqlite3.Row] = []
            onceki_zaman: int | None = None

            for satis in satislar:
                elle_sinir = satis["id"] in self._manual_boundaries
                bosluk = (
                    None if onceki_zaman is None
                    else satis["created_at_utc"] - onceki_zaman
                )
                yeni_grup = (
                    not mevcut
                    or elle_sinir
                    or (bosluk is not None and bosluk > esik)
                )
                if yeni_grup and mevcut:
                    gruplar.append(mevcut)
                    mevcut = []
                mevcut.append(satis)
                onceki_zaman = satis["created_at_utc"]

            if mevcut:
                gruplar.append(mevcut)

            for grup in gruplar:
                self._insert_group(conn, business_date, grup, esik)
            return len(gruplar)

    def _clear_day(self, conn: sqlite3.Connection, business_date: str) -> None:
        conn.execute(
            "DELETE FROM sale_session_members WHERE session_id IN "
            "  (SELECT id FROM sale_sessions WHERE business_date = ? AND kind = 'ESTIMATED')",
            (business_date,),
        )
        conn.execute(
            "DELETE FROM sale_sessions WHERE business_date = ? AND kind = 'ESTIMATED'",
            (business_date,),
        )

    def _insert_group(
        self,
        conn: sqlite3.Connection,
        business_date: str,
        grup: list[sqlite3.Row],
        esik: int,
    ) -> int:
        elle = any(s["id"] in self._manual_boundaries for s in grup)
        session_id = conn.execute(
            "INSERT INTO sale_sessions(kind, started_at_utc, ended_at_utc, business_date, "
            "  algorithm_version, threshold_seconds, confidence, manual_boundary, "
            "  sale_count, total_amount) VALUES('ESTIMATED',?,?,?,?,?,?,?,?,?)",
            (
                grup[0]["created_at_utc"], grup[-1]["created_at_utc"], business_date,
                ALGORITHM_VERSION, esik, self._confidence(grup, esik),
                int(elle), len(grup), sum(s["total_amount"] for s in grup),
            ),
        ).lastrowid
        conn.executemany(
            "INSERT INTO sale_session_members(session_id, sale_id) VALUES(?,?)",
            [(session_id, s["id"]) for s in grup],
        )
        return session_id

    @staticmethod
    def _confidence(grup: list[sqlite3.Row], esik: int) -> float:
        """Kaba bir güven ölçüsü: okutmalar ne kadar sıkışıksa o kadar yüksek.

        Bu bir OLASILIK DEĞİLDİR, yalnızca sıralama için kullanılan bir
        göstergedir ve kullanıcıya sayı olarak GÖSTERİLMEZ.
        """
        if len(grup) < 2:
            return 0.5
        sure = grup[-1]["created_at_utc"] - grup[0]["created_at_utc"]
        ortalama = sure / (len(grup) - 1)
        return round(max(0.0, min(1.0, 1.0 - (ortalama / esik))), 2)

    # ===================== Okuma ==========================================
    def groups_for_day(self, business_date: str) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM sale_sessions WHERE business_date = ? ORDER BY started_at_utc",
            (business_date,),
        )

    def group_items(self, session_id: int) -> list[sqlite3.Row]:
        """Gruptaki ürünler, adetleri toplanmış hâlde."""
        return self.db.query(
            "SELECT i.product_id, i.product_name_snapshot AS name, "
            "       SUM(i.quantity) AS adet, SUM(i.line_total) AS tutar "
            "  FROM sale_session_members m "
            "  JOIN sale_items i ON i.sale_id = m.sale_id "
            " WHERE m.session_id = ? GROUP BY i.product_id ORDER BY adet DESC",
            (session_id,),
        )

    def stats_for_day(self, business_date: str) -> dict:
        row = self.db.query_one(
            "SELECT COUNT(*) AS grup, COALESCE(AVG(sale_count), 0) AS ort_kalem, "
            "       COALESCE(AVG(total_amount), 0) AS ort_tutar "
            "  FROM sale_sessions WHERE business_date = ? AND kind = 'ESTIMATED'",
            (business_date,),
        )
        return {
            "grup_sayisi": row["grup"],
            "ortalama_kalem": round(row["ort_kalem"], 1),
            "ortalama_tutar": int(row["ort_tutar"]),
            "tahmini": True,          # arayüz bunu AÇIKÇA belirtmek zorundadır
        }
