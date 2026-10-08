"""Fiyat hesapları — tam sayı KURUŞ ve BAZ PUAN (1 % = 100 bp); float YOK.

Kurallar (plan §7 M5a):
  * Yuvarlama YÖNÜ KORUR: artışlar yukarı, düşüşler aşağı yuvarlanır; "fiyatı X
    yap" tam X'tir. Böylece "%5 artır" hiçbir ürünü ucuzlatamaz.
  * Sonucu değişmeyen ya da beklenen yönün tersine giden satırlar işaretlenir;
    bunlar varsayılan olarak uygulanmaz.
  * Marj, satış fiyatına göre brüt marjdır: (satış − alış) / satış. Analiz
    ekranındaki "kâr oranı" ile aynı tanım.

Bu modül Qt ve veritabanı bilmez; her şey saf tam sayı aritmetiğidir.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core.errors import GecersizFiyat
from app.core.money import MAX_TL

#: Tek fiyatın üst sınırı (kuruş) — ``tl_to_kurus`` ile aynı.
EN_YUKSEK_FIYAT = int(MAX_TL * 100)
#: %100 = 10 000 baz puan.
TAM = 10_000

# ----- İşlem türleri (Türkçe tanımlayıcılar) -----------------------------
YUZDE_ARTIR = "YUZDE_ARTIR"
YUZDE_AZALT = "YUZDE_AZALT"
TUTAR_ARTIR = "TUTAR_ARTIR"
TUTAR_AZALT = "TUTAR_AZALT"
SABIT = "SABIT"
MARJ = "MARJ"
ISLEM_ADLARI: dict[str, str] = {
    YUZDE_ARTIR: "Yüzde artır",
    YUZDE_AZALT: "Yüzde azalt",
    TUTAR_ARTIR: "Tutar ekle (TL)",
    TUTAR_AZALT: "Tutar düş (TL)",
    SABIT: "Fiyatı şu yap (TL)",
    MARJ: "Hedef marja göre (alış fiyatı bilinenler)",
}
#: Değeri baz puan olan işlemler (geri kalanlar kuruş).
YUZDELI = frozenset({YUZDE_ARTIR, YUZDE_AZALT, MARJ})

# ----- Yön -----------------------------------------------------------------
YUKARI = "YUKARI"
ASAGI = "ASAGI"
YONSUZ = "YONSUZ"
_BEKLENEN_YON = {
    YUZDE_ARTIR: YUKARI, TUTAR_ARTIR: YUKARI, MARJ: YUKARI,
    YUZDE_AZALT: ASAGI, TUTAR_AZALT: ASAGI, SABIT: YONSUZ,
}

# ----- Satır durumları ------------------------------------------------------
DEGISIR = "DEGISIR"
AYNI = "AYNI"
TERS_YON = "TERS_YON"
FIYATSIZ = "FIYATSIZ"
MALIYETSIZ = "MALIYETSIZ"
GECERSIZ = "GECERSIZ"
DURUM_ADLARI: dict[str, str] = {
    DEGISIR: "Değişecek",
    AYNI: "Değişmiyor",
    TERS_YON: "Ters yönde (ör. hedef marj fiyatı düşürüyor)",
    FIYATSIZ: "Satış fiyatı yok",
    MALIYETSIZ: "Alış fiyatı bilinmiyor",
    GECERSIZ: "Geçersiz sonuç (0 ya da çok yüksek)",
}

#: Ayarlardaki yuvarlama adımları (kuruş) ve adları.
YUVARLAMA_ADIMLARI: dict[int, str] = {
    1: "Yuvarlama yok (kuruşuna kadar)",
    50: "50 kuruşa",
    100: "1 TL'ye",
    500: "5 TL'ye",
}
VARSAYILAN_ADIM = 100


@dataclass(frozen=True, slots=True)
class FiyatIslemi:
    """Toplu fiyat işlemi. ``deger``: yüzdeli işlemlerde baz puan, diğerlerinde kuruş."""

    tur: str
    deger: int
    adim: int = VARSAYILAN_ADIM

    def __post_init__(self) -> None:
        if self.tur not in _BEKLENEN_YON:
            raise ValueError(f"bilinmeyen işlem: {self.tur}")
        if self.deger < 0:
            raise GecersizFiyat("Değer eksi olamaz.")
        if self.adim not in YUVARLAMA_ADIMLARI:
            raise ValueError(f"bilinmeyen yuvarlama adımı: {self.adim}")
        if self.tur == MARJ and self.deger >= TAM:
            raise GecersizFiyat("Marj %100 ya da üstü olamaz.")


@dataclass(frozen=True, slots=True)
class Sonuc:
    yeni: int | None
    durum: str

    @property
    def varsayilan_secili(self) -> bool:
        return self.durum == DEGISIR


# ===================== Temel aritmetik =====================================
def _tavan_bolme(pay: int, payda: int) -> int:
    return -(-pay // payda)


def adima_yuvarla(kurus: int, adim: int, yon: str) -> int:
    """``yon`` YUKARI → tavan, ASAGI → taban, YONSUZ → dokunmaz."""
    if adim <= 1 or yon == YONSUZ:
        return kurus
    if yon == YUKARI:
        return _tavan_bolme(kurus, adim) * adim
    return (kurus // adim) * adim


def yuzde_metninden_bp(metin: str) -> int:
    """"12,5" / "12.5" / "%12,5" → 1250 baz puan (en çok iki ondalık)."""
    ham = (metin or "").replace("%", "").replace(" ", "").replace(",", ".")
    try:
        deger = Decimal(ham)
    except InvalidOperation:
        raise GecersizFiyat("Geçerli bir yüzde girin. Örnek: 5 ya da 7,5") from None
    if not deger.is_finite() or deger < 0:
        raise GecersizFiyat("Yüzde eksi olamaz.")
    if deger > 1000:
        raise GecersizFiyat("Yüzde çok büyük görünüyor. Lütfen kontrol edin.")
    bp = deger * 100
    if bp != bp.to_integral_value():
        raise GecersizFiyat("Yüzde en çok iki ondalık olabilir.")
    return int(bp)


def bp_metni(bp: int) -> str:
    """1250 → "%12,5" ; -300 → "−%3"."""
    isaret = "−" if bp < 0 else ""
    tam, kalan = divmod(abs(bp), 100)
    govde = f"{tam}" if not kalan else f"{tam},{kalan:02d}".rstrip("0")
    return f"{isaret}%{govde}"


def marj_bp(satis: int | None, maliyet: int | None) -> int | None:
    """(satış − alış) / satış, baz puan, sıfıra doğru. Bilinmiyorsa ``None``."""
    if not satis or satis <= 0 or not maliyet or maliyet <= 0:
        return None
    fark = (satis - maliyet) * TAM
    return fark // satis if fark >= 0 else -((-fark) // satis)


def degisim_bp(eski: int | None, yeni: int | None) -> int | None:
    """Yüzde değişim (baz puan, sıfıra doğru); eski bilinmiyorsa ``None``."""
    if not eski or eski <= 0 or yeni is None:
        return None
    fark = (yeni - eski) * TAM
    return fark // eski if fark >= 0 else -((-fark) // eski)


def marj_fiyati(maliyet: int, hedef_bp: int, adim: int = 1) -> int:
    """Hedef marjı en az sağlayan fiyat (yukarı yuvarlanır)."""
    if hedef_bp >= TAM:
        raise GecersizFiyat("Marj %100 ya da üstü olamaz.")
    ham = _tavan_bolme(maliyet * TAM, TAM - hedef_bp)
    return adima_yuvarla(ham, adim, YUKARI)


def marji_koruyan_fiyat(
    eski_fiyat: int, eski_maliyet: int, yeni_maliyet: int, adim: int = 1
) -> int:
    """Alış değişince ORANI koruyan fiyat: eski_fiyat × yeni_alış / eski_alış.

    Alış arttıysa yukarı, azaldıysa aşağı yuvarlanır (yön korunur).
    """
    pay = eski_fiyat * yeni_maliyet
    if yeni_maliyet >= eski_maliyet:
        return adima_yuvarla(_tavan_bolme(pay, eski_maliyet), adim, YUKARI)
    return adima_yuvarla(pay // eski_maliyet, adim, ASAGI)


# ===================== İşlem ===============================================
def hesapla(islem: FiyatIslemi, eski: int | None, maliyet: int | None = None) -> Sonuc:
    """Bir ürün için yeni fiyatı ve satırın durumunu hesaplar."""
    tur, deger, adim = islem.tur, islem.deger, islem.adim
    if tur == MARJ:
        if not maliyet or maliyet <= 0:
            return Sonuc(None, MALIYETSIZ)
        yeni = marj_fiyati(maliyet, deger, adim)
    elif tur == SABIT:
        yeni = deger
    elif eski is None or eski <= 0:
        return Sonuc(None, FIYATSIZ)
    elif tur == YUZDE_ARTIR:
        yeni = adima_yuvarla(_tavan_bolme(eski * (TAM + deger), TAM), adim, YUKARI)
    elif tur == YUZDE_AZALT:
        if deger >= TAM:
            return Sonuc(None, GECERSIZ)
        yeni = adima_yuvarla(eski * (TAM - deger) // TAM, adim, ASAGI)
    elif tur == TUTAR_ARTIR:
        yeni = adima_yuvarla(eski + deger, adim, YUKARI)
    else:  # TUTAR_AZALT
        yeni = adima_yuvarla(eski - deger, adim, ASAGI)

    if yeni <= 0 or yeni > EN_YUKSEK_FIYAT:
        return Sonuc(None, GECERSIZ)
    if yeni == eski:
        return Sonuc(yeni, AYNI)
    beklenen = _BEKLENEN_YON[tur]
    if eski is not None and (
        (beklenen == YUKARI and yeni < eski) or (beklenen == ASAGI and yeni > eski)
    ):
        return Sonuc(yeni, TERS_YON)
    return Sonuc(yeni, DEGISIR)
