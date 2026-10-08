"""Analiz dönemleri ve karşılaştırma dönemleri (plan §6.3).

Bütün tarihler İŞ GÜNÜDÜR (``business_date``, "YYYY-MM-DD"). Haftalar
Pazartesi başlar.

Hazır dönemler: Bugün, Dün, Son 7 Gün, Bu Hafta, Geçen Hafta, Bu Ay, Geçen Ay,
Özel.

Karşılaştırma kuralları:
  * tek gün ↔ önceki gün VE geçen haftanın aynı günü,
  * N günlük dönem (Son 7 Gün, haftalar, Özel) ↔ hemen önceki eşit uzunlukta
    dönem,
  * Bu Ay (ayın bugüne kadarki kısmı) ↔ geçen ayın AYNI aralığı (ay kısaysa
    ayın sonuna kadar),
  * Geçen Ay ↔ ondan önceki ayın tamamı,
  * 366 günden uzun dönemlerde karşılaştırma yapılmaz (ileti gösterilir).
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from app.core.tr import DATE_FORMAT

BUGUN = "BUGUN"
DUN = "DUN"
SON_7 = "SON_7"
BU_HAFTA = "BU_HAFTA"
GECEN_HAFTA = "GECEN_HAFTA"
BU_AY = "BU_AY"
GECEN_AY = "GECEN_AY"
OZEL = "OZEL"
DONEM_ADLARI: dict[str, str] = {
    BUGUN: "Bugün",
    DUN: "Dün",
    SON_7: "Son 7 Gün",
    BU_HAFTA: "Bu Hafta",
    GECEN_HAFTA: "Geçen Hafta",
    BU_AY: "Bu Ay",
    GECEN_AY: "Geçen Ay",
    OZEL: "Özel",
}
#: Bu uzunluktan (gün) büyük dönemlerde karşılaştırma yapılmaz.
EN_UZUN_KARSILASTIRMA = 366
KARSILASTIRMA_YOK = ("Bu uzunlukta bir dönem için karşılaştırma yapılmaz "
                     "(en çok 366 gün).")


@dataclass(frozen=True, slots=True)
class Donem:
    baslangic: str
    bitis: str
    ad: str = ""
    tur: str = OZEL

    @property
    def gun_sayisi(self) -> int:
        return (_g(self.bitis) - _g(self.baslangic)).days + 1

    def gunler(self) -> list[str]:
        bas = _g(self.baslangic)
        return [_s(bas + timedelta(days=i)) for i in range(self.gun_sayisi)]


def _g(gun: str) -> date:
    return date.fromisoformat(gun)


def _s(gun: date) -> str:
    return gun.strftime(DATE_FORMAT)


def _pazartesi(gun: date) -> date:
    return gun - timedelta(days=gun.weekday())


def hazir(tur: str, bugun: str) -> Donem:
    """Hazır dönem; ``bugun`` geçerli iş günüdür."""
    g = _g(bugun)
    ad = DONEM_ADLARI[tur]
    if tur == BUGUN:
        return Donem(bugun, bugun, ad, tur)
    if tur == DUN:
        dun = _s(g - timedelta(days=1))
        return Donem(dun, dun, ad, tur)
    if tur == SON_7:
        return Donem(_s(g - timedelta(days=6)), bugun, ad, tur)
    if tur == BU_HAFTA:
        return Donem(_s(_pazartesi(g)), bugun, ad, tur)
    if tur == GECEN_HAFTA:
        pzt = _pazartesi(g) - timedelta(days=7)
        return Donem(_s(pzt), _s(pzt + timedelta(days=6)), ad, tur)
    if tur == BU_AY:
        return Donem(_s(g.replace(day=1)), bugun, ad, tur)
    if tur == GECEN_AY:
        son = g.replace(day=1) - timedelta(days=1)
        return Donem(_s(son.replace(day=1)), _s(son), ad, tur)
    raise ValueError(f"hazır dönem değil: {tur}")


def ozel(baslangic: str, bitis: str) -> Donem:
    if _g(bitis) < _g(baslangic):
        baslangic, bitis = bitis, baslangic
    return Donem(baslangic, bitis, f"{_g(baslangic):%d.%m.%Y} – {_g(bitis):%d.%m.%Y}", OZEL)


def _ay_kaydir(gun: date, ay: int) -> date:
    """Ay kaydırma; hedef ay kısaysa ayın son gününe sabitlenir."""
    yil, kalan = divmod(gun.month - 1 + ay, 12)
    yil += gun.year
    ay_no = kalan + 1
    son_gun = calendar.monthrange(yil, ay_no)[1]
    return date(yil, ay_no, min(gun.day, son_gun))


def karsilastirmalar(donem: Donem) -> list[Donem]:
    """Dönemin karşılaştırma dönemleri; çok uzunsa boş liste."""
    if donem.gun_sayisi > EN_UZUN_KARSILASTIRMA:
        return []
    bas, bit = _g(donem.baslangic), _g(donem.bitis)
    if donem.gun_sayisi == 1:
        return [
            Donem(_s(bas - timedelta(days=1)), _s(bas - timedelta(days=1)), "Önceki gün"),
            Donem(_s(bas - timedelta(days=7)), _s(bas - timedelta(days=7)),
                  "Geçen haftanın aynı günü"),
        ]
    if donem.tur == BU_AY:
        onceki_bas = _ay_kaydir(bas, -1)
        onceki_bit = _ay_kaydir(bit, -1)
        return [Donem(_s(onceki_bas), _s(onceki_bit), "Geçen ayın aynı günleri")]
    if donem.tur == GECEN_AY:
        onceki_son = bas - timedelta(days=1)
        return [Donem(_s(onceki_son.replace(day=1)), _s(onceki_son), "Önceki ay")]
    uzunluk = donem.gun_sayisi
    return [Donem(_s(bas - timedelta(days=uzunluk)), _s(bas - timedelta(days=1)),
                  f"Önceki {uzunluk} gün")]


def degisim_yuzdesi(simdi: int, once: int) -> float | None:
    """Yüzde değişim; önceki 0 ise ``None`` (anlamsız)."""
    if not once:
        return None
    return (simdi - once) * 100.0 / abs(once)
