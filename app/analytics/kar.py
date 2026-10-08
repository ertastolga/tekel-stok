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

Sorgu (V1.2 M11): her satış satırının hareketi için iki indeks araması —
ürünün bu hareketten önceki SON sıfırlanması (``ix_moves_pool_reset``) ve o
sıfırlanmayla bu hareket arasında kirli giriş var mı (``ix_moves_tainting``).
Süre dönemdeki satır sayısıyla orantılıdır, geçmişin uzunluğuyla değil. İlk
sürümdeki pencere fonksiyonlu sorgu (satılan ürünlerin TÜM hareket geçmişini
tarar; 100k veride 30 gün 2,2 s) testlerde kâhin olarak durur ve sonuçlar
rastgele defterlerde birebir karşılaştırılır.
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

#: Kısmi indekslerin (şema v6) WHERE ifadeleriyle AYNI metin olmalı. İndeksler
#: ``INDEXED BY`` ile SABİTLENİR: ``PRAGMA optimize`` istatistik yazınca planlayıcı
#: sıfırlanma araması için genel ``(ürün, id)`` indeksini seçip geçmişte geriye
#: yürüyordu (100k veride 30 gün 18 ms → 184 ms; 1 yıl 0,25 s → 2,1 s). v6 göçü
#: indekslerin varlığını garanti eder.
_KATMAN_SQL = """
SELECT CASE
         WHEN i.is_estimated_cost = 0 AND i.cost_total > 0
              AND NOT EXISTS (
                  SELECT 1 FROM stock_movements x INDEXED BY ix_moves_tainting
                   WHERE x.product_id = m.product_id AND x.id < m.id
                     AND x.quantity_delta > x.fill_quantity
                     AND (x.is_estimated_cost = 1 OR COALESCE(x.unit_cost, 0) = 0)
                     AND x.id > COALESCE((
                         SELECT r.id FROM stock_movements r INDEXED BY ix_moves_pool_reset
                          WHERE r.product_id = m.product_id AND r.id < m.id
                            AND r.balance_after <= 0
                          ORDER BY r.id DESC LIMIT 1), 0))
              THEN 'GUVENILIR'
         WHEN i.cost_total > 0 THEN 'TAHMINI'
         ELSE 'BILINMIYOR' END AS katman,
       SUM(i.line_total) AS ciro, SUM(i.cost_total) AS maliyet, COUNT(*) AS satir
  FROM sales s JOIN sale_items i ON i.sale_id = s.id
  LEFT JOIN stock_movements m
         ON m.ref_type = 'SALE' AND m.ref_id = s.id AND m.ref_line_id = i.id
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
    satirlar = {s["katman"]: Katman(s["ciro"], s["maliyet"], s["satir"])
                for s in db.query(_KATMAN_SQL, (donem.baslangic, donem.bitis))}
    return MaliyetKapsami(donem, satirlar.get(GUVENILIR, Katman()),
                          satirlar.get(TAHMINI, Katman()), satirlar.get(BILINMIYOR, Katman()))
