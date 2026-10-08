"""Ürün analizleri (G3): en çok satanlar, az satanlar, kategori, marka, ürün eğilimi.

Kaynak ``product_daily_sales`` (orijinal güne yazılmış, net). Kategori kırılımı
alt kategorileri ÜST kategoriye toplar; kategorisi olmayan ürünler
"Kategorisiz" satırında görünür. Sınıflandırma ürünlerin BUGÜNKÜ kategorisidir.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.analytics.donemler import Donem

KATEGORISIZ = "Kategorisiz"
MARKASIZ = "Markasız"


@dataclass(frozen=True, slots=True)
class UrunSatiri:
    product_id: int | None
    ad: str
    adet: int
    ciro: int
    maliyet: int = 0
    alt: tuple = ()

    @property
    def kar(self) -> int:
        return self.ciro - self.maliyet


def _urun_sql(siralama: str) -> str:
    return (
        "SELECT p.id, p.name, SUM(d.quantity) AS adet, SUM(d.amount) AS ciro, "
        "       SUM(d.cost) AS mal "
        "  FROM product_daily_sales d JOIN products p ON p.id = d.product_id "
        " WHERE d.business_date BETWEEN ? AND ? "
        f" GROUP BY p.id HAVING adet > 0 ORDER BY {siralama} LIMIT ?"
    )


def _satirlar(rows) -> list[UrunSatiri]:
    return [UrunSatiri(r["id"], r["name"], r["adet"], r["ciro"], r["mal"]) for r in rows]


def en_cok_adet(db, donem: Donem, limit: int = 20) -> list[UrunSatiri]:
    return _satirlar(db.query(_urun_sql("adet DESC, ciro DESC, p.name_norm"),
                              (donem.baslangic, donem.bitis, limit)))


def en_cok_ciro(db, donem: Donem, limit: int = 20) -> list[UrunSatiri]:
    return _satirlar(db.query(_urun_sql("ciro DESC, adet DESC, p.name_norm"),
                              (donem.baslangic, donem.bitis, limit)))


def az_satanlar(db, donem: Donem, limit: int = 20) -> list[UrunSatiri]:
    """Dönemde satılmış ama en AZ satılan ürünler (hiç satılmayanlar ayrı listede)."""
    return _satirlar(db.query(_urun_sql("adet ASC, ciro ASC, p.name_norm"),
                              (donem.baslangic, donem.bitis, limit)))


def kategoriler(db, donem: Donem) -> list[UrunSatiri]:
    """Üst kategori toplamları (altlarıyla birlikte) + "Kategorisiz"."""
    satirlar = db.query(
        "SELECT COALESCE(u.id, c.id) AS ust_id, COALESCE(u.name, c.name) AS ust_ad, "
        "       CASE WHEN u.id IS NULL THEN NULL ELSE c.id END AS alt_id, "
        "       CASE WHEN u.id IS NULL THEN NULL ELSE c.name END AS alt_ad, "
        "       SUM(d.quantity) AS adet, SUM(d.amount) AS ciro, SUM(d.cost) AS mal "
        "  FROM product_daily_sales d JOIN products p ON p.id = d.product_id "
        "  LEFT JOIN categories c ON c.id = p.category_id "
        "  LEFT JOIN categories u ON u.id = c.parent_id "
        " WHERE d.business_date BETWEEN ? AND ? "
        " GROUP BY ust_id, alt_id",
        (donem.baslangic, donem.bitis),
    )
    ustler: dict = {}
    for s in satirlar:
        anahtar = s["ust_id"]
        kayit = ustler.setdefault(anahtar, {"ad": s["ust_ad"] or KATEGORISIZ, "adet": 0,
                                            "ciro": 0, "mal": 0, "alt": []})
        kayit["adet"] += s["adet"]
        kayit["ciro"] += s["ciro"]
        kayit["mal"] += s["mal"]
        if s["alt_id"] is not None:
            kayit["alt"].append(UrunSatiri(s["alt_id"], s["alt_ad"], s["adet"], s["ciro"],
                                           s["mal"]))
    sonuc = [
        UrunSatiri(k, v["ad"], v["adet"], v["ciro"], v["mal"],
                   tuple(sorted(v["alt"], key=lambda a: -a.ciro)))
        for k, v in ustler.items() if v["adet"] or v["ciro"]
    ]
    return sorted(sonuc, key=lambda s: (-s.ciro, s.ad))


def markalar(db, donem: Donem, limit: int = 30) -> list[UrunSatiri]:
    satirlar = db.query(
        "SELECT b.id, b.name, SUM(d.quantity) AS adet, SUM(d.amount) AS ciro, "
        "       SUM(d.cost) AS mal "
        "  FROM product_daily_sales d JOIN products p ON p.id = d.product_id "
        "  LEFT JOIN brands b ON b.id = p.brand_id "
        " WHERE d.business_date BETWEEN ? AND ? "
        " GROUP BY b.id HAVING adet > 0 ORDER BY ciro DESC LIMIT ?",
        (donem.baslangic, donem.bitis, limit),
    )
    return [UrunSatiri(r["id"], r["name"] or MARKASIZ, r["adet"], r["ciro"], r["mal"])
            for r in satirlar]


def urun_egilimi(db, product_id: int, donem: Donem) -> list[tuple[str, int, int]]:
    """Ürünün gün gün (adet, ciro) serisi; boş günler sıfır."""
    veri = {
        s["business_date"]: (s["quantity"], s["amount"]) for s in db.query(
            "SELECT business_date, quantity, amount FROM product_daily_sales "
            " WHERE product_id = ? AND business_date BETWEEN ? AND ?",
            (product_id, donem.baslangic, donem.bitis))
    }
    return [(gun, *veri.get(gun, (0, 0))) for gun in donem.gunler()]
