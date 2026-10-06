"""Ayarlar: veritabanındaki ``settings`` tablosu üzerinde tiplenmiş erişim.

Ayarlar QSettings'te değil VERİTABANINDA tutulur; böylece yedek alındığında
tercihler de yedeğe girer ve geri yüklemede birlikte döner.

Her tiplenmiş okuyucu kendi sınırlarını uygular: bozuk ya da anlamsız bir değer
uygulamayı çökertmez, sessizce güvenli varsayılana döner.
"""
from __future__ import annotations

import logging

from app.core.clock import BusinessCalendar, now_utc
from app.core.db import Database
from app.core.schema import DEFAULT_SETTINGS

log = logging.getLogger(__name__)


class SettingsService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self._cache: dict[str, str] | None = None
        self._calendar: BusinessCalendar | None = None

    # -- Ham erişim --------------------------------------------------------
    def _load(self) -> dict[str, str]:
        if self._cache is None:
            rows = self.db.query("SELECT key, value FROM settings")
            self._cache = {row["key"]: row["value"] for row in rows}
        return self._cache

    def invalidate(self) -> None:
        self._cache = None
        self._calendar = None

    def get(self, key: str, default: str | None = None) -> str:
        value = self._load().get(key)
        if value is None or value == "":
            fallback = DEFAULT_SETTINGS.get(key, "") if default is None else default
            return "" if fallback is None else str(fallback)
        return value

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, str(default)))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        raw = self.get(key, "1" if default else "0")
        return str(raw).strip() in ("1", "true", "True", "evet")

    def set(self, key: str, value: object, mutating: bool = True) -> None:
        self.set_many({key: value}, mutating=mutating)

    def set_many(self, values: dict[str, object], mutating: bool = True) -> None:
        now = now_utc()
        with self.db.transaction(mutating=mutating) as conn:
            conn.executemany(
                "INSERT INTO settings(key, value, updated_at_utc) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "  updated_at_utc = excluded.updated_at_utc",
                [(key, "" if v is None else str(v), now) for key, v in values.items()],
            )
        self.invalidate()

    def set_many_quiet(self, values: dict[str, object]) -> None:
        """Defter tutma yazısı: veritabanını "değişti" saymaz.

        Yedek damgası böyle yazılır; aksi hâlde yedek almak yeni bir yedeği
        tetiklerdi.
        """
        self.set_many(values, mutating=False)

    # -- Çalışma kipi ------------------------------------------------------
    def operating_mode(self) -> str:
        """Günlük iş akışı kipi. Tanınmayan değerde güvenli varsayılana döner.

        Bu ayar YALNIZCA sunumu etkiler: stok defteri, maliyet hesabı ve
        değişmezler kipten tamamen bağımsızdır.
        """
        from app.core.models import OperatingMode

        mode = self.get("operating_mode", OperatingMode.SALES_FIRST)
        return mode if mode in OperatingMode.ALL else OperatingMode.SALES_FIRST

    def is_sales_first(self) -> bool:
        from app.core.models import OperatingMode

        return self.operating_mode() == OperatingMode.SALES_FIRST

    def customer_display_hold_ms(self) -> int:
        """Satıştan sonra son tutarın müşteri ekranında kalma süresi (ms)."""
        return max(0, min(30000, self.get_int("customer_display_hold_ms", 4000)))

    # -- Satış -------------------------------------------------------------
    def default_sale_mode(self) -> str:
        mode = self.get("default_sale_mode", "HIZLI")
        return mode if mode in ("HIZLI", "SEPET") else "HIZLI"

    def smart_grouping_enabled(self) -> bool:
        return self.get_bool("smart_grouping_enabled", False)

    def smart_grouping_threshold_seconds(self) -> int:
        return max(5, min(300, self.get_int("smart_grouping_threshold_seconds", 20)))

    def pack_confirm_in_sale(self) -> bool:
        """Koli/paket barkodu satışta onay ister mi? Güvenli varsayılan: evet."""
        return self.get_bool("pack_confirm_in_sale", True)

    def ask_payment_method(self) -> bool:
        return self.get_bool("ask_payment_method", False)

    # -- Barkod ------------------------------------------------------------
    def duplicate_scan_ms(self) -> int:
        """Donanım çift-tetiklemesi penceresi.

        Varsayılan 120 ms bilinçlidir: bu uygulamada aynı barkodu arka arkaya
        okutmak birincil MİKTAR GİRİŞ yöntemidir (10 bira = aynı şişeyi 10 kez
        okut). Pencere geniş olursa gerçek satışlar sessizce düşer.
        """
        return max(0, min(1000, self.get_int("duplicate_scan_ms", 120)))

    def barcode_trim_prefix(self) -> str:
        return self.get("barcode_trim_prefix", "")

    def barcode_trim_suffix(self) -> str:
        return self.get("barcode_trim_suffix", "")

    # -- Fiyat / vergi -----------------------------------------------------
    def prices_include_vat(self) -> bool:
        return self.get_bool("prices_include_vat", True)

    def default_vat_rate(self) -> int:
        return max(0, min(100, self.get_int("default_vat_rate", 20)))

    # -- Stok eşikleri (YENİ ÜRÜN varsayılanı) -----------------------------
    def default_thresholds(self) -> tuple[int, int]:
        """(min_stock, critical_stock) — kritik daima min'den küçük ya da eşittir."""
        low = max(0, self.get_int("default_min_stock", 6))
        critical = max(0, self.get_int("default_critical_stock", 2))
        if critical > low:
            low, critical = critical, low
        return low, critical

    def slow_moving_days(self) -> int:
        return max(7, min(365, self.get_int("slow_moving_days", 45)))

    def large_count_diff_threshold(self) -> int:
        """Bu adetten büyük sayım farkı onay ister. Her 1 adet için sorulmaz."""
        return max(1, self.get_int("large_count_diff_threshold", 20))

    # -- Yedekleme ---------------------------------------------------------
    def auto_backup_interval_minutes(self) -> int:
        return max(5, min(1440, self.get_int("auto_backup_interval_minutes", 120)))

    def auto_backup_retention(self) -> int:
        return max(1, self.get_int("auto_backup_retention", 10))

    def manual_backup_dir(self) -> str:
        return self.get("manual_backup_dir", "")

    # -- Arayüz ------------------------------------------------------------
    def sound_enabled(self) -> bool:
        return self.get_bool("sound_enabled", True)

    # -- İş günü -----------------------------------------------------------
    def calendar(self) -> BusinessCalendar:
        """Geçerlilik tarihli iş günü kurallarını taşıyan takvim."""
        if self._calendar is None:
            rows = self.db.query(
                "SELECT effective_from, start_hour FROM business_day_rules "
                "ORDER BY effective_from"
            )
            self._calendar = BusinessCalendar(
                [(row["effective_from"], row["start_hour"]) for row in rows]
            )
        return self._calendar

    def current_business_day_start_hour(self) -> int:
        return self.calendar().start_hour_for(self.calendar().today())

    def set_business_day_start_hour(self, start_hour: int, effective_from: str) -> None:
        """Yeni bir iş günü kuralı ekler — GEÇMİŞİ DEĞİŞTİRMEZ.

        Kayıtların ``business_date`` sütunu yazma anında dondurulduğu için
        geçmiş günlük raporlar bu değişiklikten etkilenmez. Varsayılan
        ``effective_from`` yarındır; bugünden başlatmak arayüzde ayrı bir onay
        gerektirir (bugünün yarısı eski kuralla damgalanmış olur).
        """
        start_hour = max(0, min(23, int(start_hour)))
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO business_day_rules(effective_from, start_hour, created_at_utc) "
                "VALUES(?,?,?) "
                "ON CONFLICT(effective_from) DO UPDATE SET start_hour = excluded.start_hour",
                (effective_from, start_hour, now_utc()),
            )
        self._calendar = None
        log.info("İş günü başlangıcı %s tarihinden itibaren %02d:00", effective_from, start_hour)
