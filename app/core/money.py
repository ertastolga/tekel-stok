"""Para birimi: her yerde tam sayı KURUŞ kullanılır, float ASLA kullanılmaz.

1 TL = 100 kuruş. Kayan noktalı sayı kullanılsaydı 0,1 + 0,2 gibi toplamlar
zamanla kuruş kaybettirir ve ciro ile satış satırları birbirini tutmazdı.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.core.errors import GecersizFiyat

#: Tek bir fiyat için üst sınır — yanlış yazımı (fazladan sıfır) yakalar.
MAX_TL = Decimal("1000000")


def tl_to_kurus(text: str | int | float | Decimal) -> int:
    """Kullanıcı girdisini kuruşa çevirir. 80 / 80,50 / 1.250,50 kabul edilir."""
    if isinstance(text, bool):
        raise GecersizFiyat()
    if isinstance(text, int):
        value = Decimal(text)
    elif isinstance(text, Decimal):
        value = text
    elif isinstance(text, float):
        value = Decimal(str(text))
    else:
        raw = (text or "").strip()
        raw = raw.replace("TL", "").replace("tl", "").replace("₺", "").strip()
        if not raw:
            raise GecersizFiyat("Fiyat boş olamaz.")
        # 1.250,50 -> 1250.50 ; 80,50 -> 80.50 ; 1.250 -> 1250 ; 80.50 -> 80.50
        if "," in raw:
            raw = raw.replace(".", "").replace(",", ".")
        elif raw.count(".") > 1:
            raw = raw.replace(".", "")
        elif "." in raw:
            # Tek nokta belirsizdir. Türkçe yazımda noktadan sonra TAM ÜÇ hane
            # varsa bu binlik ayıracıdır: 1.250 -> 1250. Aksi hâlde ondalık
            # ayıracı kabul edilir: 80.50 -> 80,50.
            whole, _, fraction = raw.partition(".")
            if len(fraction) == 3 and fraction.isdigit() and whole.isdigit():
                raw = whole + fraction
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise GecersizFiyat("Geçerli bir fiyat giriniz. Örnek: 80") from None

    if not value.is_finite():
        raise GecersizFiyat()
    if value < 0:
        raise GecersizFiyat("Fiyat negatif olamaz.")
    if value > MAX_TL:
        raise GecersizFiyat("Fiyat çok yüksek görünüyor. Lütfen kontrol edin.")

    return int((value * 100).quantize(Decimal("1")))


def format_tl(kurus: int | None, suffix: str = " TL") -> str:
    """8000 -> '80 TL' ; 8050 -> '80,50 TL' ; 125000 -> '1.250 TL'"""
    if kurus is None:
        return "-"
    negative = kurus < 0
    kurus = abs(int(kurus))
    lira, kalan = divmod(kurus, 100)
    text = f"{lira:,}".replace(",", ".")
    if kalan:
        text = f"{text},{kalan:02d}"
    if negative:
        text = "-" + text
    return text + suffix


def format_tl_plain(kurus: int | None) -> str:
    """CSV için: binlik ayıracı yok, ondalık virgül (Excel TR uyumlu)."""
    if kurus is None:
        return ""
    negative = kurus < 0
    lira, kalan = divmod(abs(int(kurus)), 100)
    text = f"{lira},{kalan:02d}"
    return "-" + text if negative else text


def kurus_to_tl_text(kurus: int | None) -> str:
    """Düzenleme alanları için: 8000 -> '80' ; 8050 -> '80,50'"""
    if kurus is None:
        return ""
    negative = kurus < 0
    lira, kalan = divmod(abs(int(kurus)), 100)
    text = f"{lira}" if kalan == 0 else f"{lira},{kalan:02d}"
    return "-" + text if negative else text


def vat_amount(line_total: int, vat_rate: int | None, prices_include_vat: bool) -> int:
    """Satır tutarındaki KDV payı (kuruş).

    Türkiye perakendesinde raf fiyatı KDV DAHİLDİR; bu yüzden varsayılan
    hesap ``tutar * oran / (100 + oran)`` şeklindedir. Yanlış formül her kâr
    marjını sessizce bozacağı için burada tek yerde tutulur.
    """
    if not vat_rate:
        return 0
    rate = int(vat_rate)
    if prices_include_vat:
        return round(line_total * rate / (100 + rate))
    return round(line_total * rate / 100)


def net_amount(line_total: int, vat_rate: int | None, prices_include_vat: bool) -> int:
    """KDV hariç tutar (kuruş)."""
    if not prices_include_vat:
        return line_total
    return line_total - vat_amount(line_total, vat_rate, True)
