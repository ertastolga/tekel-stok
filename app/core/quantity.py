"""Miktar mantığının TEK sahibi.

V1 yalnızca sayılabilir (paketli) ürünleri destekler: her satılabilir kalem tam
sayı adet/paket olarak satılır. Tartılı ürün, terazi, kesirli miktar ve kilogram
fiyatı V1'de YOKTUR.

Buna rağmen "envanter ancak parça olabilir" varsayımı koda gömülmez. Miktarla
ilgili her karar bu modülden geçer; hiçbir servis, sorgu veya arayüz gereci
kendi içine "adet" yazmaz. İleride tartılı ürün eklendiğinde değişecek yer
yalnızca burasıdır.

Değişmeyen sözleşme
-------------------
Veritabanındaki TÜM miktar sütunları (``sale_items.quantity``,
``stock_movements.quantity_delta``, ``purchase_receipt_lines.quantity``,
``count_line_locations.counted_qty``) **tam sayıdır** ve **ürünün temel
biriminde** ifade edilir. Kayan noktalı sayı asla kullanılmaz.

V1'de temel birim ``ADET``'tir. İleride 350 gramlık tartılı bir ürün
``base_unit='GRAM'`` ile ``quantity=350`` olarak temsil edilebilir — şema,
defter ve maliyet motoru değişmeden çalışır.

DİKKAT: 180 g'lık paketli kuruyemiş bir ``COUNT`` ürünüdür; bir paket = 1 adet.
Gramaj yalnızca ``size_value``/``size_unit`` alanlarında bilgi olarak durur.
"""
from __future__ import annotations

from app.core.errors import DesteklenmeyenOlcuTuru, GecersizMiktar

# --- Ölçüm üstverisi ------------------------------------------------------
MEASURE_COUNT = "COUNT"
MEASURE_WEIGHT = "WEIGHT"      # V1'de KULLANILMAZ, şema yeri hazır
MEASURE_VOLUME = "VOLUME"      # V1'de KULLANILMAZ, şema yeri hazır
MEASURE_KINDS = (MEASURE_COUNT, MEASURE_WEIGHT, MEASURE_VOLUME)

BASE_UNIT_PIECE = "ADET"
BASE_UNIT_GRAM = "GRAM"        # V1'de KULLANILMAZ
BASE_UNIT_ML = "MILILITRE"     # V1'de KULLANILMAZ
BASE_UNITS = (BASE_UNIT_PIECE, BASE_UNIT_GRAM, BASE_UNIT_ML)

PRICING_PER_UNIT = "PER_UNIT"
PRICING_PER_1000_BASE = "PER_1000_BASE"    # V1'de KULLANILMAZ (kg/litre fiyatı)
PRICING_BASES = (PRICING_PER_UNIT, PRICING_PER_1000_BASE)

#: V1'in kabul ettiği TEK bileşim. Şemadaki CHECK listeleri bilerek daha
#: geniştir (SQLite'ta CHECK genişletmek tam tablo yeniden inşası gerektirir);
#: katılık burada, servis katmanında sağlanır.
V1_MEASURE_KIND = MEASURE_COUNT
V1_BASE_UNIT = BASE_UNIT_PIECE
V1_PRICING_BASIS = PRICING_PER_UNIT

#: ``products.unit_label`` — yalnızca COUNT ürünler için GÖSTERİM etiketi.
UNIT_LABELS = ("Adet", "Paket", "Koli")
DEFAULT_UNIT_LABEL = "Adet"

#: Miktar üst sınırı — yanlış yazımı (fazladan sıfır) yakalar.
MAX_QUANTITY = 1_000_000


def ensure_v1_supported(
    measure_kind: str | None,
    base_unit: str | None,
    pricing_basis: str | None,
) -> None:
    """V1 katılığı: COUNT / ADET / PER_UNIT dışında hiçbir bileşim kabul edilmez.

    Şema daha geniş değerlere izin verir ki ileride tablo yeniden inşası
    gerekmesin; bu kapı, V1'de yanlışlıkla desteklenmeyen bir ürün
    oluşturulmasını engeller. ``I33`` değişmezi de veritabanını denetler.
    """
    if (
        (measure_kind or V1_MEASURE_KIND) != V1_MEASURE_KIND
        or (base_unit or V1_BASE_UNIT) != V1_BASE_UNIT
        or (pricing_basis or V1_PRICING_BASIS) != V1_PRICING_BASIS
    ):
        raise DesteklenmeyenOlcuTuru(
            f"measure_kind={measure_kind} base_unit={base_unit} "
            f"pricing_basis={pricing_basis}"
        )


def is_integral(measure_kind: str | None) -> bool:
    """Bu ölçü türünde miktar arayüzde tam sayı olarak mı girilir?"""
    return (measure_kind or V1_MEASURE_KIND) == MEASURE_COUNT


def unit_label(product) -> str:
    """Ürünün miktar etiketi: 'Adet' / 'Paket' / 'Koli'.

    ``product`` bir dataclass, ``sqlite3.Row`` ya da sözlük olabilir.
    """
    label = _attr(product, "unit_label")
    if label in UNIT_LABELS:
        return label
    return DEFAULT_UNIT_LABEL


def parse_quantity(text: str | int | None, product=None) -> int:
    """Kullanıcı girdisini temel birim cinsinden TAM SAYIYA çevirir.

    V1'de yalnızca tam sayı kabul edilir; '2,5' gibi bir girdi açıkça reddedilir
    ki sessizce yuvarlanıp stok bozulmasın.
    """
    if isinstance(text, bool):
        raise GecersizMiktar()
    if isinstance(text, int):
        value = text
    else:
        raw = str(text or "").strip().replace(".", "")
        if not raw:
            raise GecersizMiktar("Adet boş olamaz.")
        if "," in raw:
            raise GecersizMiktar("Bu üründe yarım adet olamaz. Tam sayı yazın.")
        if raw.startswith("-"):
            body = raw[1:]
            sign = -1
        else:
            body = raw
            sign = 1
        if not body.isdigit():
            raise GecersizMiktar("Geçerli bir adet giriniz. Örnek: 6")
        value = sign * int(body)

    if abs(value) > MAX_QUANTITY:
        raise GecersizMiktar("Adet çok yüksek görünüyor. Lütfen kontrol edin.")
    return value


def parse_positive_quantity(text: str | int | None, product=None) -> int:
    value = parse_quantity(text, product)
    if value <= 0:
        raise GecersizMiktar("Adet en az 1 olmalıdır.")
    return value


def format_quantity(quantity: int | None, product=None, with_label: bool = True) -> str:
    """Miktarı kullanıcıya gösterilecek biçime çevirir: '24 Adet'."""
    if quantity is None:
        return ""
    from app.core.tr import fmt_int

    text = fmt_int(int(quantity))
    if not with_label:
        return text
    return f"{text} {unit_label(product)}"


def format_quantity_signed(quantity: int | None, product=None) -> str:
    """Stok hareketi gösterimi: '+24 Adet' / '-3 Adet'."""
    if quantity is None:
        return ""
    from app.core.tr import fmt_signed_int

    return f"{fmt_signed_int(int(quantity))} {unit_label(product)}"


def to_base_units(quantity: int, multiplier: int = 1) -> int:
    """Barkod çarpanını uygular: 1 koli x 24 -> 24 temel birim.

    Arayüz ``quantity_multiplier`` ile ASLA doğrudan çarpma yapmaz; çarpanın
    uygulandığı tek yer burasıdır.
    """
    if multiplier < 1:
        from app.core.errors import GecersizCarpan

        raise GecersizCarpan()
    return int(quantity) * int(multiplier)


def _attr(source, name: str):
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(name)
    try:
        return source[name]          # sqlite3.Row
    except (TypeError, IndexError, KeyError):
        return getattr(source, name, None)
