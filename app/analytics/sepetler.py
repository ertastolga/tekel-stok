"""Sepet analizleri (G4): birlikte satılan ürün ve kategori çiftleri.

YALNIZCA kesin sepetler (Sepetli Satış, geri alınmamış) sayılır. Bir sepette
aynı ürün birden çok satırda olsa da bir kez sayılır. "X alanların %n'i Y de
aldı" oranı = (X ve Y birlikte geçen sepet) / (X geçen sepet).

Bu gerçek sepetlerin sayımıdır, tahmin değildir. Az sayıda sepete dayanan
çiftler gösterilmez (en az destek).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analytics.donemler import Donem

ACIKLAMA = "Bu gerçek sepetlerin sayımıdır, tahmin değildir."
VARSAYILAN_EN_AZ_DESTEK = 3

_SEPET_URUNLERI = (
    "SELECT DISTINCT i.sale_id AS sepet, i.product_id AS urun FROM sale_items i "
    "  JOIN sales s ON s.id = i.sale_id "
    " WHERE s.entry_type = 'SALE' AND s.sale_mode = 'SEPET' AND s.is_reversed = 0 "
    "   AND s.business_date BETWEEN ? AND ?"
)
_SEPET_KATEGORILERI = (
    "SELECT DISTINCT i.sale_id AS sepet, "
    "       COALESCE(c.parent_id, c.id, 0) AS urun FROM sale_items i "
    "  JOIN sales s ON s.id = i.sale_id JOIN products p ON p.id = i.product_id "
    "  LEFT JOIN categories c ON c.id = p.category_id "
    " WHERE s.entry_type = 'SALE' AND s.sale_mode = 'SEPET' AND s.is_reversed = 0 "
    "   AND s.business_date BETWEEN ? AND ?"
)


@dataclass(frozen=True, slots=True)
class Cift:
    a_id: int
    a_ad: str
    b_id: int
    b_ad: str
    birlikte: int
    a_sepet: int
    b_sepet: int
    toplam_sepet: int

    @property
    def a_alanlarin_b_orani(self) -> float:
        return self.birlikte * 100.0 / self.a_sepet if self.a_sepet else 0.0

    @property
    def b_alanlarin_a_orani(self) -> float:
        return self.birlikte * 100.0 / self.b_sepet if self.b_sepet else 0.0

    def cumle(self) -> str:
        """En güçlü yönde: "X alanların %n'i Y de aldı (k sepet)"."""
        if self.a_alanlarin_b_orani >= self.b_alanlarin_a_orani:
            x, y, oran, n = self.a_ad, self.b_ad, self.a_alanlarin_b_orani, self.a_sepet
        else:
            x, y, oran, n = self.b_ad, self.a_ad, self.b_alanlarin_a_orani, self.b_sepet
        return (f"{x} alanların %{oran:.0f}'i {y} de aldı "
                f"({self.birlikte} / {n} sepet).")


def _ciftler(db, kaynak: str, adlar_sql: str, donem: Donem, en_az: int,
             limit: int) -> list[Cift]:
    parametre = (donem.baslangic, donem.bitis)
    toplam = db.scalar(
        "SELECT COUNT(*) FROM sales WHERE entry_type = 'SALE' AND sale_mode = 'SEPET' "
        "   AND is_reversed = 0 AND business_date BETWEEN ? AND ?", parametre, default=0)
    satirlar = db.query(
        f"WITH s AS ({kaynak}), n AS (SELECT urun, COUNT(*) AS c FROM s GROUP BY urun) "
        "SELECT a.urun AS a, b.urun AS b, COUNT(*) AS birlikte, na.c AS ca, nb.c AS cb "
        "  FROM s a JOIN s b ON a.sepet = b.sepet AND a.urun < b.urun "
        "  JOIN n na ON na.urun = a.urun JOIN n nb ON nb.urun = b.urun "
        " GROUP BY a.urun, b.urun HAVING birlikte >= ? "
        " ORDER BY birlikte DESC, a.urun, b.urun LIMIT ?",
        (*parametre, max(1, en_az), max(1, limit)),
    )
    kimlikler = {s["a"] for s in satirlar} | {s["b"] for s in satirlar}
    adlar = {}
    if kimlikler:
        yer = ",".join("?" * len(kimlikler))
        adlar = {r["id"]: r["name"] for r in db.query(adlar_sql.format(yer=yer),
                                                       list(kimlikler))}
    return [
        Cift(s["a"], adlar.get(s["a"], "Kategorisiz"), s["b"],
             adlar.get(s["b"], "Kategorisiz"), s["birlikte"], s["ca"], s["cb"], toplam)
        for s in satirlar
    ]


def urun_ciftleri(db, donem: Donem, en_az_destek: int = VARSAYILAN_EN_AZ_DESTEK,
                  limit: int = 30) -> list[Cift]:
    return _ciftler(db, _SEPET_URUNLERI, "SELECT id, name FROM products WHERE id IN ({yer})",
                    donem, en_az_destek, limit)


def kategori_ciftleri(db, donem: Donem, en_az_destek: int = VARSAYILAN_EN_AZ_DESTEK,
                      limit: int = 30) -> list[Cift]:
    """Üst kategori düzeyinde (alt kategoriler üstüne toplanır; 0 = kategorisiz)."""
    return _ciftler(db, _SEPET_KATEGORILERI,
                    "SELECT id, name FROM categories WHERE id IN ({yer})",
                    donem, en_az_destek, limit)
