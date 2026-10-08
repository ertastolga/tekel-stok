"""İçe aktarma alanları, eş anlamlı başlıklar ve hücre dönüşümü.

Hücre kuralları:
  * Barkod METİN olarak alınır ve ASLA kendiliğinden düzeltilmez. Sayı hücresi
    olarak gelen barkod işaretlenir (Excel baştaki sıfırı silmiş olabilir);
    sıfırla tamamlanınca geçerli GTIN oluyorsa bu yalnızca ÖNERİ olarak sunulur.
    Bilimsel gösterim (8,69E+12) geçersizdir.
  * Fiyatlar tam sayı kuruşa çevrilir (float yok): "80", "80,50", "1.250,50",
    sayı hücresi 80.5 → 8050.
  * Boş hücre "bilgi yok" demektir; güncellemede ASLA üzerine yazmaz.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.core import barcode_text as bt
from app.core.errors import DomainError, GecersizFiyat
from app.core.money import tl_to_kurus
from app.core.tr import normalize_name

# ----- Alanlar (Türkçe tanımlayıcılar) -------------------------------------
BARKOD = "BARKOD"
AD = "AD"
SATIS = "SATIS"
KATEGORI = "KATEGORI"
MARKA = "MARKA"
AILE = "AILE"
TEDARIKCI = "TEDARIKCI"
ALIS = "ALIS"
KDV = "KDV"

ALAN_ADLARI: dict[str, str] = {
    BARKOD: "Barkod",
    AD: "Ürün adı",
    SATIS: "Satış fiyatı",
    KATEGORI: "Kategori",
    MARKA: "Marka",
    AILE: "Aile",
    TEDARIKCI: "Tedarikçi",
    ALIS: "Alış fiyatı (katalog)",
    KDV: "KDV %",
}
#: Yeni ürün için zorunlu alanlar (kategori varsayılanla da gelebilir).
ZORUNLU = (BARKOD, AD, SATIS)

#: Başlık eş anlamlıları (``normalize_name`` sonrası karşılaştırılır).
ES_ANLAMLILAR: dict[str, tuple[str, ...]] = {
    BARKOD: ("barkod", "barkodu", "barkod no", "barkod numarasi", "urun barkodu",
             "ean", "ean13", "ean 13", "gtin", "barcode"),
    AD: ("urun adi", "urun", "ad", "adi", "isim", "urun ismi", "stok adi",
         "aciklama", "urun aciklamasi", "product", "product name", "name"),
    SATIS: ("satis fiyati", "satis", "fiyat", "fiyati", "perakende fiyat",
            "perakende satis fiyati", "etiket fiyati", "psf", "price", "sale price"),
    KATEGORI: ("kategori", "kategorisi", "grup", "urun grubu", "reyon", "category"),
    MARKA: ("marka", "markasi", "uretici", "brand"),
    AILE: ("aile", "urun ailesi", "seri", "family"),
    TEDARIKCI: ("tedarikci", "toptanci", "firma", "dagitici", "supplier"),
    ALIS: ("alis fiyati", "alis", "maliyet", "gelis fiyati", "liste fiyati",
           "cost", "purchase price"),
    KDV: ("kdv", "kdv orani", "kdv %", "vergi", "vat", "tax"),
}


def otomatik_esle(basliklar: list[str]) -> dict[str, int]:
    """Başlıkları alanlara eşler (her alan en çok bir sütun; ilk eşleşen kazanır)."""
    esleme: dict[str, int] = {}
    kullanilan: set[int] = set()
    normal = [normalize_name(b or "").replace("_", " ").strip() for b in basliklar]
    for alan, adlar in ES_ANLAMLILAR.items():
        for i, baslik in enumerate(normal):
            if i not in kullanilan and baslik in adlar:
                esleme[alan] = i
                kullanilan.add(i)
                break
    return esleme


# ===================== Hücre dönüşümü ======================================
@dataclass(frozen=True, slots=True)
class BarkodHucresi:
    metin: str | None
    sayisal: bool = False
    oneri: str | None = None
    hata: str | None = None


def barkod_hucresi(deger) -> BarkodHucresi:
    """Barkod hücresi → metin; kendiliğinden düzeltme YOK."""
    if deger is None or deger == "":
        return BarkodHucresi(None)
    sayisal = False
    if isinstance(deger, bool):
        return BarkodHucresi(None, hata="geçersiz barkod")
    if isinstance(deger, int):
        metin, sayisal = str(deger), True
    elif isinstance(deger, float):
        if not deger.is_integer():
            return BarkodHucresi(None, True, hata="geçersiz barkod (ondalıklı sayı)")
        metin, sayisal = str(int(deger)), True
    else:
        metin = str(deger).strip()
        if "E+" in metin.upper() and metin.replace(",", ".").upper().replace("E+", "") \
                .replace(".", "").isdigit():
            return BarkodHucresi(None, hata="geçersiz barkod (bilimsel gösterim: "
                                            "sütunu Excel'de METİN olarak kaydedin)")
    temiz = bt.clean(metin)
    if not temiz:
        return BarkodHucresi(None, sayisal, hata="geçersiz barkod")
    if len(temiz) > bt.MAX_BARCODE_LENGTH:
        return BarkodHucresi(None, sayisal, hata="geçersiz barkod (çok uzun)")
    oneri = None
    if temiz.isdigit() and not bt.is_valid_gtin(temiz):
        # Kısa kodda EAN-8, diğerlerinde EAN-13 önce (Türkiye'de yaygın olan).
        for uzunluk in ((8, 13) if len(temiz) < 8 else (13, 12, 14)):
            if len(temiz) < uzunluk and bt.is_valid_gtin(temiz.zfill(uzunluk)):
                oneri = temiz.zfill(uzunluk)
                break
    return BarkodHucresi(temiz, sayisal, oneri)


def metin_hucresi(deger) -> str | None:
    if deger is None:
        return None
    if isinstance(deger, float) and deger.is_integer():
        deger = int(deger)
    metin = " ".join(str(deger).split())
    return metin or None


def fiyat_hucresi(deger) -> int | None:
    """TL → kuruş; boş → ``None``; geçersiz → ``GecersizFiyat``."""
    if deger is None or deger == "":
        return None
    if isinstance(deger, bool):
        raise GecersizFiyat()
    if isinstance(deger, (int, float)):
        try:
            return tl_to_kurus(Decimal(str(deger)))
        except InvalidOperation:
            raise GecersizFiyat() from None
    return tl_to_kurus(str(deger))


def kdv_hucresi(deger) -> int | None:
    """"20", "%20", 20, 0.2 (yüzde biçimli hücre) → 20."""
    if deger is None or deger == "":
        return None
    if isinstance(deger, (int, float)) and not isinstance(deger, bool):
        sayi = Decimal(str(deger))
        if 0 < sayi < 1:
            sayi *= 100
    else:
        try:
            sayi = Decimal(str(deger).replace("%", "").replace(",", ".").strip())
        except InvalidOperation:
            raise DomainError("geçersiz KDV oranı") from None
    if sayi != sayi.to_integral_value() or not 0 <= sayi <= 100:
        raise DomainError("geçersiz KDV oranı")
    return int(sayi)
