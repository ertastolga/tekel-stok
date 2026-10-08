"""Eğilimler (G2): saatlik, haftanın günü, günlük, haftalık, aylık.

Günlük/haftalık/aylık seriler ``daily_sales_rollup``'tan gelir (orijinal güne
yazılmış, net); saat ve gün kırılımı ``sales`` tablosundan (geri alınmamış
satışlar). Boş günler sıfırla doldurulur ki grafikte delik olmasın.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from app.analytics.donemler import Donem

AY_ADLARI = ("Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki",
             "Kas", "Ara")
GUN_ADLARI = ("Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz")


@dataclass(frozen=True, slots=True)
class Nokta:
    etiket: str
    anahtar: str
    ciro: int
    islem: int
    adet: int = 0


def saatlik(db, donem: Donem, gun_baslangic_saati: int = 0) -> list[Nokta]:
    """24 saat, iş günü başlangıcından itibaren sıralı (gece satışları sonda)."""
    satirlar = db.query(
        "SELECT local_hour AS h, COALESCE(SUM(total_amount), 0) AS ciro, COUNT(*) AS n, "
        "       COALESCE(SUM(item_count), 0) AS adet "
        "  FROM sales WHERE entry_type = 'SALE' AND is_reversed = 0 "
        "   AND business_date BETWEEN ? AND ? GROUP BY local_hour",
        (donem.baslangic, donem.bitis),
    )
    veri = {s["h"]: s for s in satirlar}
    sonuc = []
    for i in range(24):
        saat = (gun_baslangic_saati + i) % 24
        s = veri.get(saat)
        sonuc.append(Nokta(f"{saat:02d}", str(saat), s["ciro"] if s else 0,
                           s["n"] if s else 0, s["adet"] if s else 0))
    return sonuc


def haftanin_gunu(db, donem: Donem) -> list[Nokta]:
    satirlar = db.query(
        "SELECT local_dow AS g, COALESCE(SUM(total_amount), 0) AS ciro, COUNT(*) AS n, "
        "       COALESCE(SUM(item_count), 0) AS adet "
        "  FROM sales WHERE entry_type = 'SALE' AND is_reversed = 0 "
        "   AND business_date BETWEEN ? AND ? GROUP BY local_dow",
        (donem.baslangic, donem.bitis),
    )
    veri = {s["g"]: s for s in satirlar}
    return [Nokta(GUN_ADLARI[g], str(g), veri[g]["ciro"] if g in veri else 0,
                  veri[g]["n"] if g in veri else 0, veri[g]["adet"] if g in veri else 0)
            for g in range(7)]


def _gunluk_veri(db, donem: Donem) -> dict[str, tuple[int, int, int]]:
    return {
        s["business_date"]: (s["total_amount"], s["sale_count"], s["item_count"])
        for s in db.query(
            "SELECT business_date, total_amount, sale_count, item_count "
            "  FROM daily_sales_rollup WHERE business_date BETWEEN ? AND ?",
            (donem.baslangic, donem.bitis))
    }


def gunluk(db, donem: Donem) -> list[Nokta]:
    veri = _gunluk_veri(db, donem)
    sonuc = []
    for gun in donem.gunler():
        ciro, n, adet = veri.get(gun, (0, 0, 0))
        g = date.fromisoformat(gun)
        sonuc.append(Nokta(f"{g.day:02d}.{g.month:02d}", gun, ciro, n, adet))
    return sonuc


def haftalik(db, donem: Donem) -> list[Nokta]:
    """Pazartesi başlayan haftalar; dönem dışındaki günler sayılmaz."""
    veri = _gunluk_veri(db, donem)
    haftalar: dict[str, list[int]] = {}
    for gun in donem.gunler():
        g = date.fromisoformat(gun)
        pzt = (g - timedelta(days=g.weekday())).isoformat()
        toplam = haftalar.setdefault(pzt, [0, 0, 0])
        for i, deger in enumerate(veri.get(gun, (0, 0, 0))):
            toplam[i] += deger
    return [Nokta(f"{date.fromisoformat(k):%d.%m}", k, *v) for k, v in haftalar.items()]


def aylik(db, donem: Donem) -> list[Nokta]:
    veri = _gunluk_veri(db, donem)
    aylar: dict[str, list[int]] = {}
    for gun in donem.gunler():
        toplam = aylar.setdefault(gun[:7], [0, 0, 0])
        for i, deger in enumerate(veri.get(gun, (0, 0, 0))):
            toplam[i] += deger
    return [Nokta(f"{AY_ADLARI[int(k[5:7]) - 1]} {k[:4]}", k, *v) for k, v in aylar.items()]
