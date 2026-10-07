"""Zaman damgalama ve iş günü hesabı.

İKİ AYRI KAVRAM vardır ve karıştırılmamalıdır:

* **Gerçek zaman** (``created_at_utc``, ``local_date``, ``local_hour``) — olayın
  gerçekte yaşandığı andır. ASLA değiştirilmez, hiçbir gruplama uğruna
  kaydırılmaz.
* **İş günü** (``business_date``) — raporlamanın gruplama anahtarıdır. Yazma
  anında damgalanır ve BİR DAHA hesaplanmaz. Bu sayede dükkân sahibi ileride
  "gün başlangıcı" ayarını değiştirse bile geçmiş günlük raporlar aynı kalır.

İş günü sınırı GEÇERLİLİK TARİHLİDİR (``business_day_rules``): yeni bir kural
yalnızca kendi ``effective_from`` tarihinden sonraki satışlara uygulanır.

Neden yerel saat sütunları veritabanına yazılıyor?
``strftime('%H', ..., 'localtime')`` SQLite'ta deterministik DEĞİLDİR: sorgu
anındaki işletim sistemi saat dilimi kurallarını uygular. Bu yüzden indeks veya
üretilmiş sütun içinde kullanılamaz ve saat dilimi kuralları değişirse geçmişi
sessizce yeniden yazar. Damgayı yazma anında dondurmak doğru olandır.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from app.core.tr import DATE_FORMAT, TS_FORMAT

#: ``business_day_rules`` tablosundaki ilk (varsayılan) kuralın tarihi.
BEGINNING_OF_TIME = "0001-01-01"
DEFAULT_BUSINESS_DAY_START_HOUR = 0

# --- Saat dikişi (clock seam) ---------------------------------------------
# Üretimde HİÇ kullanılmaz: ikisi de ``None`` kalır ve gerçek saat okunur.
# Testler ve sentetik veri üreteci, servisleri değiştirmeden zamanı
# yönetebilsin diye sağlayıcı BURADA, işlevlerin İÇİNDE okunur; böylece
# ``from app.core.clock import now_utc`` diye adla içe aktaran her modül de
# otomatik olarak aynı saati görür.
_yerel_saat: Callable[[], datetime] | None = None
_tekduze_saat: Callable[[], float] | None = None


def now_utc() -> int:
    """Epoch saniyesi (UTC). Sıralama için ASLA kullanılmaz — bkz. modül notu."""
    if _yerel_saat is not None:
        return int(_yerel_saat().timestamp())
    return int(time.time())


def local_now() -> datetime:
    if _yerel_saat is not None:
        return _yerel_saat()
    return datetime.now()


def monotonic() -> float:
    """Süre ölçümü için tekdüze saat (saniye). Duvar saatinden bağımsızdır.

    ``time.perf_counter`` kullanılır: Python 3.12'de Windows'ta
    ``time.monotonic`` ~15,6 ms adımla ilerler.
    """
    if _tekduze_saat is not None:
        return _tekduze_saat()
    return time.perf_counter()


@contextmanager
def use_clock(
    yerel: Callable[[], datetime] | None = None,
    tekduze: Callable[[], float] | None = None,
) -> Iterator[None]:
    """Blok boyunca saati verilen sağlayıcılara bağlar; çıkışta geri alır."""
    global _yerel_saat, _tekduze_saat
    onceki = (_yerel_saat, _tekduze_saat)
    if yerel is not None:
        _yerel_saat = yerel
    if tekduze is not None:
        _tekduze_saat = tekduze
    try:
        yield
    finally:
        _yerel_saat, _tekduze_saat = onceki


def reset_clock() -> None:
    """Gerçek saate döner (testler arası güvence)."""
    global _yerel_saat, _tekduze_saat
    _yerel_saat = None
    _tekduze_saat = None


@dataclass(frozen=True, slots=True)
class TimeStamp:
    """Bir olayın tüm zaman sütunları — tek yerden üretilir."""

    created_at_utc: int
    local_date: str        # 'YYYY-MM-DD' — gerçek takvim günü
    local_hour: int        # 0-23 — gerçek saat
    local_dow: int         # 0=Pazartesi — İŞ GÜNÜNDEN türetilir
    business_date: str     # 'YYYY-MM-DD' — raporlama günü, donmuş

    def as_dict(self) -> dict:
        return {
            "created_at_utc": self.created_at_utc,
            "local_date": self.local_date,
            "local_hour": self.local_hour,
            "local_dow": self.local_dow,
            "business_date": self.business_date,
        }


class BusinessCalendar:
    """Geçerlilik tarihli iş günü kurallarını çözer.

    ``rules`` = ``[(effective_from 'YYYY-MM-DD', start_hour 0-23), ...]``.
    Veritabanından okunur, bellekte tutulur (tablo çok küçüktür); kural
    değiştiğinde servis ``reload()`` çağırır.
    """

    __slots__ = ("_rules",)

    def __init__(self, rules: list[tuple[str, int]] | None = None) -> None:
        self._rules: list[tuple[str, int]] = []
        self.reload(rules)

    def reload(self, rules: list[tuple[str, int]] | None) -> None:
        cleaned = [(str(d), int(h)) for d, h in (rules or []) if d]
        cleaned.sort(key=lambda item: item[0])
        if not cleaned or cleaned[0][0] > BEGINNING_OF_TIME:
            cleaned.insert(0, (BEGINNING_OF_TIME, DEFAULT_BUSINESS_DAY_START_HOUR))
        self._rules = cleaned

    @property
    def rules(self) -> list[tuple[str, int]]:
        return list(self._rules)

    def start_hour_for(self, local_day: str) -> int:
        """O takvim gününde geçerli olan gün başlangıç saati."""
        chosen = DEFAULT_BUSINESS_DAY_START_HOUR
        for effective_from, start_hour in self._rules:
            if effective_from <= local_day:
                chosen = start_hour
            else:
                break
        return chosen

    def business_date_for(self, moment: datetime) -> str:
        """Gerçek yerel ana karşılık gelen iş günü.

        Gün başlangıcı 04:00 ise, 01:30'daki bir satış BİR ÖNCEKİ iş gününe
        yazılır. Varsayılan 00:00'da takvim günüyle birebir aynıdır.
        """
        local_day = moment.strftime(DATE_FORMAT)
        start_hour = self.start_hour_for(local_day)
        if start_hour and moment.hour < start_hour:
            return (moment.date() - timedelta(days=1)).strftime(DATE_FORMAT)
        return local_day

    def stamp(self, moment: datetime | None = None) -> TimeStamp:
        """Bir olayın tüm zaman sütunlarını üretir."""
        moment = moment or local_now()
        business_date = self.business_date_for(moment)
        # Haftanın günü İŞ GÜNÜNDEN türetilir: aksi hâlde cumartesi gecesi
        # yapılan satışlar pazara düşer ve "en yoğun gün" analizi tam da en
        # önemli saatlerde yanlış sonuç verir.
        business_day = datetime.strptime(business_date, DATE_FORMAT).date()
        return TimeStamp(
            created_at_utc=int(moment.timestamp()),
            local_date=moment.strftime(DATE_FORMAT),
            local_hour=moment.hour,
            local_dow=business_day.weekday(),
            business_date=business_date,
        )

    def today(self) -> str:
        """Şu anda hangi iş günündeyiz? Panel 'Bugün' bunu kullanır."""
        return self.business_date_for(local_now())


def utc_to_local(epoch: int | None) -> datetime | None:
    if epoch is None:
        return None
    return datetime.fromtimestamp(int(epoch))


def format_utc(epoch: int | None, fmt: str = TS_FORMAT) -> str:
    moment = utc_to_local(epoch)
    return "" if moment is None else moment.strftime(fmt)


def day_str(value: date | datetime) -> str:
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime(DATE_FORMAT)


def shift_days(day: str, delta: int) -> str:
    parsed = datetime.strptime(day, DATE_FORMAT).date()
    return (parsed + timedelta(days=delta)).strftime(DATE_FORMAT)
