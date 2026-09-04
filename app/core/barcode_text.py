"""Barkod metni: kimliği KORUYARAK normalleştirme.

İki ayrı değer üretilir ve ikisi de saklanır:

``barcode_norm`` — **muhafazakâr** normalleştirme. Yalnızca görünmez farkları
    siler: baştaki/sondaki boşluk, ayraçlar, yazdırılamaz karakterler; sonra
    **ASCII** büyütme. **Baştaki sıfırlar KORUNUR.** ``00123`` ile ``123``
    farklı barkodlardır ve farklı ürünlere ait olabilir.

``gtin14`` — **yalnızca kanıtlanmışsa** doldurulan kanonik biçim. Değer
    (a) tamamen rakam, (b) uzunluğu 8/12/13/14 ve (c) GS1 kontrol hanesi
    doğru ise 14 haneye sola sıfır doldurulur. Aksi hâlde ``None`` kalır ve
    barkod tamamen opak kabul edilir.

Neden körü körüne sıfır atılmaz? Dükkânda üretilen dahili kodlar (raf etiketi,
elle yazılmış kodlar) baştaki sıfırı anlamlı biçimde taşıyabilir. Sıfırları
atmak iki ayrı ürünü sessizce birleştirir — geri dönüşü olmayan bir veri
hatasıdır. Buna karşılık UPC-A ``012345678905`` ile onun EAN-13 yazımı
``0012345678905`` GERÇEKTEN aynı üründür ve kontrol hanesi bunu KANITLAR.

Türkçe büyütme burada ASLA kullanılmaz: barkodlar ASCII'dir, ``"i"`` -> ``"I"``
olmalıdır, ``"İ"`` değil.
"""
from __future__ import annotations

from app.core.errors import BosBarkod

#: Okuyucuların araya serpiştirebildiği ayraçlar.
_SEPARATORS = " -_.\t\r\n\\/|:;,"

#: Kontrol hanesi doğrulanabilen GTIN uzunlukları (GTIN-8/12/13/14).
_GTIN_LENGTHS = (8, 12, 13, 14)

MAX_BARCODE_LENGTH = 64


def clean(raw: str | None, trim_prefix: str = "", trim_suffix: str = "") -> str:
    """Ham okuyucu çıktısını temizler; KİMLİĞİ DEĞİŞTİRMEZ.

    ``trim_prefix``/``trim_suffix`` bazı okuyucuların eklediği sabit karakterleri
    atmak içindir. Varsayılan olarak boştur (kapalı) ve Barkod Testi ekranından
    ayarlanır — kör bir varsayım yapılmaz.
    """
    text = (raw or "").strip()
    if trim_prefix and text.startswith(trim_prefix):
        text = text[len(trim_prefix):]
    if trim_suffix and text.endswith(trim_suffix):
        text = text[: -len(trim_suffix)]

    out = []
    for ch in text:
        if ch in _SEPARATORS:
            continue
        if not ch.isprintable():
            continue
        out.append(ch)
    # ASCII büyütme — Türkçe kuralları BİLEREK kullanılmaz.
    return "".join(out).upper()


def normalize(raw: str | None, trim_prefix: str = "", trim_suffix: str = "") -> str:
    """Veritabanına yazılacak ``barcode_norm`` değeri."""
    value = clean(raw, trim_prefix, trim_suffix)
    if not value:
        raise BosBarkod()
    if len(value) > MAX_BARCODE_LENGTH:
        value = value[:MAX_BARCODE_LENGTH]
    return value


def gtin_check_digit(digits: str) -> int:
    """GS1 kontrol hanesi (son hane hariç verilen gövde için).

    Sağdan sola 3-1-3-1... ağırlıklandırma, GTIN-8/12/13/14 için ortaktır.
    """
    total = 0
    for index, ch in enumerate(reversed(digits)):
        weight = 3 if index % 2 == 0 else 1
        total += int(ch) * weight
    return (10 - (total % 10)) % 10


def is_valid_gtin(value: str) -> bool:
    """Değer, kontrol hanesi doğrulanmış bir GTIN mi?"""
    if not value or not value.isdigit():
        return False
    if len(value) not in _GTIN_LENGTHS:
        return False
    body, last = value[:-1], value[-1]
    return gtin_check_digit(body) == int(last)


def to_gtin14(raw: str | None, trim_prefix: str = "", trim_suffix: str = "") -> str | None:
    """Kanonik 14 haneli GTIN — yalnızca KANITLANABİLİYORSA.

    Doğrulanamayan her değer için ``None`` döner; o barkod opak kimliğiyle
    (``barcode_norm``) tekil kalır.
    """
    value = clean(raw, trim_prefix, trim_suffix)
    if not is_valid_gtin(value):
        return None
    return value.zfill(14)


def describe(raw: str | None) -> str:
    """Barkod Testi ekranı için insan okuyabilir özet."""
    value = clean(raw)
    if not value:
        return "boş"
    canonical = to_gtin14(value)
    if canonical:
        return f"{len(value)} hane · geçerli GTIN · kanonik {canonical}"
    if value.isdigit():
        return f"{len(value)} hane · rakam · GTIN değil (opak kimlik)"
    return f"{len(value)} karakter · harf içeriyor · opak kimlik"
