"""Türkçe metin, tarih ve sayı biçimleri.

Python'un ``upper()``/``lower()`` metotları Türkçe'de yanlıştır: ``"i".upper()``
İngilizce kurala göre ``"I"`` verir, oysa Türkçe'de ``"İ"`` olmalıdır. Bu modül
doğru dönüşümü, Türkçe alfabetik sıralamayı ve aksansız arama eşleşmesini sağlar.

DİKKAT: Barkodlar bu kuralların DIŞINDADIR — onlar ASCII'dir ve
``app/core/barcode_text.py`` içinde ASCII kurallarıyla işlenir.
"""
from __future__ import annotations

from datetime import date, datetime

_TR_UPPER = str.maketrans("iı", "İI")
_TR_LOWER = str.maketrans("İI", "iı")

#: Türkçe alfabetik sıra (sayılar ve boşluk önde).
_TR_ALPHABET = "0123456789 aâbcçdefgğhıiîjklmnoöprsştuüûvyz"
_TR_ORDER = {ch: index for index, ch in enumerate(_TR_ALPHABET)}

_ASCII_FOLD = str.maketrans(
    {
        "ş": "s", "Ş": "s", "ı": "i", "İ": "i", "ğ": "g", "Ğ": "g",
        "ü": "u", "Ü": "u", "ö": "o", "Ö": "o", "ç": "c", "Ç": "c",
        "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u", "Û": "u",
    }
)

AYLAR = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]
AYLAR_KISA = ["Oca", "Şub", "Mar", "Nis", "May", "Haz",
              "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]

#: 0 = Pazartesi (Python ``date.weekday()`` ile aynı).
#: SQLite ``strftime('%w')`` 0 = Pazar'dır; ASLA onunla hesaplanmaz.
GUNLER = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
GUNLER_KISA = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]

#: Veritabanına yazılan tarih-saat biçimi.
TS_FORMAT = "%Y-%m-%d %H:%M:%S"
DATE_FORMAT = "%Y-%m-%d"


def tr_upper(text: str | None) -> str:
    return (text or "").translate(_TR_UPPER).upper()


def tr_lower(text: str | None) -> str:
    return (text or "").translate(_TR_LOWER).lower()


def tr_sort_key(text: str | None) -> tuple:
    """Türkçe alfabetik sıralama anahtarı ('ç' 'c'den sonra, 'ı' 'i'den önce)."""
    lowered = tr_lower(text or "")
    return tuple(_TR_ORDER.get(ch, 900 + (ord(ch) % 100)) for ch in lowered)


def ascii_fold(text: str | None) -> str:
    """Aksanları düşürüp küçük harfe indirger: 'Şanslı' -> 'sansli'."""
    return tr_lower(text or "").translate(_ASCII_FOLD)


def normalize_name(text: str | None) -> str:
    """Arama ve tekillik için normalleştirilmiş ad.

    Veritabanındaki ``*_norm`` sütunlarının TEK üreticisi budur. Fazla boşluklar
    tek boşluğa indirilir, aksanlar düşürülür, küçük harfe çevrilir. Böylece
    'Bira', 'bira' ve 'BİRA' aynı kategori sayılır.
    """
    folded = ascii_fold(text)
    return " ".join(folded.split())


def tr_contains(haystack: str | None, needle: str | None) -> bool:
    return tr_lower(needle) in tr_lower(haystack)


def search_matches(haystack: str | None, needle: str | None) -> bool:
    """Ürün araması: Türkçe duyarsız, ayrıca ASCII yazımı da kabul eder.

    'sans' da 'şans' da 'Şanslı' sonucunu bulur. Bulanık (fuzzy) eşleşme
    YOKTUR: yalnızca alt dizi araması yapılır, böylece sonuçlar tahmin
    edilebilir kalır — dükkân sahibi neden o ürünün çıktığını anlar.
    """
    needle = (needle or "").strip()
    if not needle:
        return True
    if tr_contains(haystack, needle):
        return True
    return ascii_fold(needle) in ascii_fold(haystack)


# --- Tarih / saat ---------------------------------------------------------
def fmt_date(value: date | datetime | str | None) -> str:
    """-> '05.09.2026'"""
    parsed = _as_date(value)
    return "" if parsed is None else parsed.strftime("%d.%m.%Y")


def fmt_date_long(value: date | datetime | str | None) -> str:
    """-> '5 Eylül 2026 Cumartesi'"""
    parsed = _as_date(value)
    if parsed is None:
        return ""
    return f"{parsed.day} {AYLAR[parsed.month - 1]} {parsed.year} {GUNLER[parsed.weekday()]}"


def fmt_time(value: datetime | str | None) -> str:
    """-> '20:14'"""
    parsed = _as_datetime(value)
    return "" if parsed is None else parsed.strftime("%H:%M")


def fmt_datetime(value: datetime | str | None) -> str:
    """-> '05.09.2026 20:14'"""
    parsed = _as_datetime(value)
    return "" if parsed is None else parsed.strftime("%d.%m.%Y %H:%M")


def _as_datetime(value: datetime | date | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    for fmt in (TS_FORMAT, "%Y-%m-%dT%H:%M:%S", DATE_FORMAT):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def _as_date(value: date | datetime | str | None) -> date | None:
    parsed = _as_datetime(value)
    return None if parsed is None else parsed.date()


# --- Sayılar --------------------------------------------------------------
def fmt_int(value: int | float | None) -> str:
    """1250 -> '1.250'"""
    if value is None:
        return ""
    return f"{int(value):,}".replace(",", ".")


def fmt_decimal(value: float | None, digits: int = 1) -> str:
    """1.5 -> '1,5'"""
    if value is None:
        return ""
    return f"{value:.{digits}f}".replace(".", ",")


def fmt_decimal_trim(value: float | None, digits: int = 1) -> str:
    """Gereksiz sıfırları atar: 2.0 -> '2' ; 2.5 -> '2,5'"""
    if value is None:
        return ""
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return (text or "0").replace(".", ",")


def fmt_percent(value: float | None, digits: int = 1) -> str:
    """12.5 -> '%12,5'"""
    if value is None:
        return ""
    return "%" + fmt_decimal(value, digits)


def fmt_signed_int(value: int | None) -> str:
    """Fark gösterimi: 3 -> '+3' ; -3 -> '-3' ; 0 -> '0'"""
    if value is None:
        return ""
    value = int(value)
    return f"+{fmt_int(value)}" if value > 0 else fmt_int(value)
