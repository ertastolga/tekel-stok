"""Ayar anahtarı → Ayarlar bölümü eşlemesi (plan §6.6) — TEK kaynak.

Kullanıcıya açık her ayar TAM OLARAK bir bölümde görünür; iç ayarlar (pencere
konumu, yedek damgaları, menü durumu, güvenlik kayıtları…) hiçbir bölümde
görünmez. ``tests/test_ayarlar.py`` bunu ``DEFAULT_SETTINGS`` ile denetler:
yeni bir ayar eklenince bu tabloya da eklenmek ZORUNDADIR.
"""
from __future__ import annotations

#: Bölümler, ekrandaki sırayla.
BOLUMLER: tuple[tuple[str, str], ...] = (
    ("kasa", "Kasa"),
    ("gorunum", "Görünüm"),
    ("ses", "Ses"),
    ("barkod", "Barkod Okuyucu"),
    ("isletme", "İşletme"),
    ("stok", "Stok"),
    ("yedekleme", "Yedekleme"),
    ("donanim", "Donanım"),
    ("guvenlik", "Güvenlik"),
)

#: Kullanıcıya açık ayarlar ve bölümleri.
AYAR_BOLUMU: dict[str, str] = {
    # Kasa
    "operating_mode": "kasa",
    "default_sale_mode": "kasa",
    "show_quick_sale": "kasa",
    "pack_confirm_in_sale": "kasa",
    "customer_display_hold_ms": "kasa",
    # V1.1'de kullanıcıya açıktı; kaldırılmadı (Kasa > Gelişmiş).
    "smart_grouping_enabled": "kasa",
    # Ses
    "sound_enabled": "ses",
    # Barkod Okuyucu
    "duplicate_scan_ms": "barkod",
    "barcode_trim_prefix": "barkod",
    "barcode_trim_suffix": "barkod",
    # İşletme (gün başlangıcı kuralı ayrı tabloda tutulur)
    "prices_include_vat": "isletme",
    "default_vat_rate": "isletme",
    # Stok
    "default_min_stock": "stok",
    "default_critical_stock": "stok",
    "slow_moving_days": "stok",
    "large_count_diff_threshold": "stok",
    # Yedekleme
    "auto_backup_interval_minutes": "yedekleme",
    "auto_backup_retention": "yedekleme",
    "manual_backup_dir": "yedekleme",
}

#: Ekranda GÖSTERİLMEYEN iç ayarlar.
IC_AYARLAR: frozenset[str] = frozenset({
    "last_backup_at_utc",
    "last_backup_data_version",
    "window_geometry",
    "window_maximized",
    "last_seen_clock_utc",
    "nav_collapsed_groups",
    "smart_grouping_threshold_seconds",
    "ask_payment_method",
})

#: Bu öneklerle başlayan her anahtar içtir (destek paketinden de çıkarılır).
IC_ONEKLER: tuple[str, ...] = ("guvenlik_", "last_backup_")


def ic_mi(anahtar: str) -> bool:
    return anahtar in IC_AYARLAR or anahtar.startswith(IC_ONEKLER)
