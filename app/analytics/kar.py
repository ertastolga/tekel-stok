"""Kâr ve Maliyet Kapsamı (G6, plan §5.9, D-19): defterden maliyet katmanları.

Bir satış satırı yalnızca şu durumda **"Güvenilir maliyet"**tir:
  * satırın maliyeti tahmini değil (``is_estimated_cost = 0``) ve sıfırdan büyük,
  * ürünün havuzu, satıştan önceki SON sıfırlanmadan (``balance_after <= 0``)
    bu satışa kadar "kirli" bir girişle karışmamış: değerlenen birimi olan
    (``quantity_delta > fill_quantity``) ve maliyeti tahmini ya da 0/NULL olan
    bir giriş (sayımla bilinmeyen maliyetle gelen stok, maliyetsiz alış…).
Aksi hâlde maliyet > 0 ise **"Tahmini maliyet"**, 0 ise **"Maliyeti bilinmiyor"**.

Başlıktaki brüt kâr YALNIZCA güvenilir ciro toplam cironun en az %95'i ise
gösterilir; değilse kâr "kapsanan kısım için" söylenir. Katmanlar sorgu anında
defterden hesaplanır (saklanmaz).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analytics.donemler import Donem

GUVENILIR = "GUVENILIR"
TAHMINI = "TAHMINI"
BILINMIYOR = "BILINMIYOR"
KATMAN_ADLARI = {
    GUVENILIR: "Güvenilir maliyet",
    TAHMINI: "Tahmini maliyet",
    BILINMIYOR: "Maliyeti bilinmiyor",
}
#: Brüt kâr başlığı için gereken güvenilir ciro payı.
BASLIK_ESIGI = 0.95

_KATMAN_SQL = """
WITH urunler AS (
    SELECT DISTINCT i.product_id FROM sale_items i JOIN sales s ON s.id = i.sale_id
     WHERE s.entry_type = 'SALE' AND s.is_reversed = 0 AND s.business_date BETWEEN ? AND ?
), mv AS (
    SELECT m.id, m.product_id, m.ref_type, m.ref_id, m.ref_line_id,
           COALESCE(SUM(CASE WHEN m.balance_after <= 0 THEN 1 ELSE 0 END) OVER (
               PARTITION BY m.product_id ORDER BY m.id
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS grup,
           CASE WHEN m.quantity_delta > m.fill_quantity
                 AND (m.is_estimated_cost = 1 OR COALESCE(m.unit_cost, 0) = 0)
                THEN 1 ELSE 0 END AS kirli
      FROM stock_movements m JOIN urunler u ON u.product_id = m.product_id
), gk AS (
    SELECT id, ref_type, ref_id, ref_line_id,
           COALESCE(MAX(kirli) OVER (
               PARTITION BY product_id, grup ORDER BY id
               ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0) AS once_kirli
      FROM mv
)
SELECT CASE
         WHEN i.is_estimated_cost = 0 AND i.cost_total > 0
              AND COALESCE(gk.once_kirli, 0) = 0 THEN 'GUVENILIR'
         WHEN i.cost_total > 0 THEN 'TAHMINI'
         ELSE 'BILINMIYOR' END AS katman,
       SUM(i.line_total) AS ciro, SUM(i.cost_total) AS maliyet, COUNT(*) AS satir
  FROM sale_items i JOIN sales s ON s.id = i.sale_id
  LEFT JOIN gk ON gk.ref_type = 'SALE' AND gk.ref_id = s.id AND gk.ref_line_id = i.id
 WHERE s.entry_type = 'SALE' AND s.is_reversed = 0 AND s.business_date BETWEEN ? AND ?
 GROUP BY katman
"""


@dataclass(frozen=True, slots=True)
class Katman:
    ciro: int = 0
    maliyet: int = 0
    satir: int = 0

    @property
    def kar(self) -> int:
        return self.ciro - self.maliyet


@dataclass(frozen=True, slots=True)
class MaliyetKapsami:
    donem: Donem
    guvenilir: Katman
    tahmini: Katman
    bilinmiyor: Katman

    @property
    def toplam_ciro(self) -> int:
        return self.guvenilir.ciro + self.tahmini.ciro + self.bilinmiyor.ciro

    @property
    def guvenilir_oran(self) -> float:
        """Güvenilir cironun payı (0–1); ciro yoksa 1."""
        return self.guvenilir.ciro / self.toplam_ciro if self.toplam_ciro else 1.0

    @property
    def baslik_kari(self) -> int | None:
        """Brüt kâr — yalnızca güvenilir pay en az %95 ise; değilse ``None``."""
        if not self.toplam_ciro or self.guvenilir_oran < BASLIK_ESIGI:
            return None
        return self.toplam_ciro - (self.guvenilir.maliyet + self.tahmini.maliyet
                                   + self.bilinmiyor.maliyet)

    def katmanlar(self) -> list[tuple[str, Katman]]:
        return [(KATMAN_ADLARI[GUVENILIR], self.guvenilir),
                (KATMAN_ADLARI[TAHMINI], self.tahmini),
                (KATMAN_ADLARI[BILINMIYOR], self.bilinmiyor)]


def maliyet_kapsami(db, donem: Donem) -> MaliyetKapsami:
    parametre = (donem.baslangic, donem.bitis)
    satirlar = {s["katman"]: Katman(s["ciro"], s["maliyet"], s["satir"])
                for s in db.query(_KATMAN_SQL, (*parametre, *parametre))}
    return MaliyetKapsami(donem, satirlar.get(GUVENILIR, Katman()),
                          satirlar.get(TAHMINI, Katman()), satirlar.get(BILINMIYOR, Katman()))
