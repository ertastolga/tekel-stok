"""Genel Bakış (G1): ciro, işlem, adet, kesin sepetler, ödeme kovaları, iadeler."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.analytics.donemler import Donem


@dataclass(frozen=True, slots=True)
class OdemeKovalari:
    nakit: int = 0
    kart: int = 0
    veresiye: int = 0
    diger: int = 0
    kaydedilmemis: int = 0

    @property
    def toplam(self) -> int:
        return self.nakit + self.kart + self.veresiye + self.diger + self.kaydedilmemis

    def satirlar(self) -> list[tuple[str, int]]:
        """Gösterim sırası; boş VERESİYE/DİĞER kovaları gizlenir."""
        satirlar = [("NAKİT", self.nakit), ("KART", self.kart)]
        if self.veresiye:
            satirlar.append(("VERESİYE", self.veresiye))
        if self.diger:
            satirlar.append(("DİĞER", self.diger))
        if self.kaydedilmemis:
            satirlar.append(("Kaydedilmemiş", self.kaydedilmemis))
        return satirlar


@dataclass(frozen=True, slots=True)
class GenelBakis:
    donem: Donem
    ciro: int
    maliyet: int
    islem: int
    adet: int
    sepet_sayisi: int
    sepet_cirosu: int
    sepet_kalemi: int
    odemeler: OdemeKovalari = field(default_factory=OdemeKovalari)
    iadeler: OdemeKovalari = field(default_factory=OdemeKovalari)

    @property
    def ortalama_sepet(self) -> int:
        """Kesin sepetlerin ortalama tutarı (kuruş, yarım yukarı)."""
        if not self.sepet_sayisi:
            return 0
        return (2 * self.sepet_cirosu + self.sepet_sayisi) // (2 * self.sepet_sayisi)

    @property
    def sepet_basina_urun(self) -> float:
        return self.sepet_kalemi / self.sepet_sayisi if self.sepet_sayisi else 0.0


_KOVA_SQL = (
    "SELECT "
    "  COALESCE(SUM(CASE WHEN payment_method = 'NAKIT' THEN total_amount END), 0) AS nakit, "
    "  COALESCE(SUM(CASE WHEN payment_method = 'KART' THEN total_amount END), 0) AS kart, "
    "  COALESCE(SUM(CASE WHEN payment_method = 'VERESIYE' THEN total_amount END), 0) "
    "    AS veresiye, "
    "  COALESCE(SUM(CASE WHEN payment_method = 'DIGER' THEN total_amount END), 0) AS diger, "
    "  COALESCE(SUM(CASE WHEN payment_method IS NULL THEN total_amount END), 0) "
    "    AS kaydedilmemis "
    "  FROM sales WHERE {kosul} AND business_date BETWEEN ? AND ?"
)


def odeme_kovalari(db, donem: Donem) -> OdemeKovalari:
    """Ödeme yöntemine göre ciro (geri alınmamış satışlar; orijinal güne)."""
    r = db.query_one(_KOVA_SQL.format(kosul="entry_type = 'SALE' AND is_reversed = 0"),
                     (donem.baslangic, donem.bitis))
    return OdemeKovalari(r["nakit"], r["kart"], r["veresiye"], r["diger"], r["kaydedilmemis"])


def iadeler(db, donem: Donem) -> OdemeKovalari:
    """Bu dönemde YAPILAN iadeler (geri alma gününe göre, pozitif tutar) — kasa sayımı."""
    r = db.query_one(_KOVA_SQL.format(kosul="entry_type = 'SALE_REVERSAL'"),
                     (donem.baslangic, donem.bitis))
    return OdemeKovalari(-r["nakit"], -r["kart"], -r["veresiye"], -r["diger"],
                         -r["kaydedilmemis"])


def genel_bakis(db, donem: Donem) -> GenelBakis:
    toplam = db.query_one(
        "SELECT COALESCE(SUM(total_amount), 0) AS ciro, COALESCE(SUM(total_cost), 0) AS mal, "
        "       COALESCE(SUM(sale_count), 0) AS islem, COALESCE(SUM(item_count), 0) AS adet "
        "  FROM daily_sales_rollup WHERE business_date BETWEEN ? AND ?",
        (donem.baslangic, donem.bitis),
    )
    sepet = db.query_one(
        "SELECT COUNT(*) AS n, COALESCE(SUM(total_amount), 0) AS ciro, "
        "       COALESCE(SUM(item_count), 0) AS kalem FROM sales "
        " WHERE entry_type = 'SALE' AND sale_mode = 'SEPET' AND is_reversed = 0 "
        "   AND business_date BETWEEN ? AND ?",
        (donem.baslangic, donem.bitis),
    )
    return GenelBakis(
        donem=donem, ciro=toplam["ciro"], maliyet=toplam["mal"], islem=toplam["islem"],
        adet=toplam["adet"], sepet_sayisi=sepet["n"], sepet_cirosu=sepet["ciro"],
        sepet_kalemi=sepet["kalem"], odemeler=odeme_kovalari(db, donem),
        iadeler=iadeler(db, donem),
    )
