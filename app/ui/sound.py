"""Sesli geri bildirim (V1.2 M9b: WAV ses motoru).

Dükkân sahibi ekrana sürekli bakmak zorunda kalmamalıdır: okutmanın tuttuğunu
kulağıyla da anlamalıdır.

Sesler bir kez, (tür, seviye) başına küçük WAV dosyaları olarak ÜRETİLİR
(``veri klasörü/sounds``) ve ``winsound.PlaySound(SND_FILENAME | SND_ASYNC |
SND_NODEFAULT)`` ile çalınır: çalma arayüzü BEKLETMEZ (V1.1'deki ``Beep``
çağrıları kasayı ses süresince donduruyordu). Çok tonlu sesler tek dosyaya
önceden işlenir. Dosya yazılamazsa ya da çalınamazsa ``Beep`` yedeğine
düşülür. ``QtMultimedia`` gerekmez; paket küçük kalır.

Türler Ayarlar › Ses'ten tek tek kapatılabilir; seviye Düşük / Orta / Yüksek.
"""
from __future__ import annotations

import logging
import math
import os
import struct
import sys
from pathlib import Path

log = logging.getLogger(__name__)

try:
    if sys.platform == "win32":
        import winsound
    else:                                          # pragma: no cover
        winsound = None
except ImportError:                                # pragma: no cover
    winsound = None

# ----- Ses türleri (ayar anahtarı ↔ tür) ------------------------------------
OKUTMA = "scan"
BASARI = "success"
UYARI = "warning"
HATA = "error"
TURLER: dict[str, str] = {
    OKUTMA: "Okutma (ürün eklendi, fiyat gösterildi)",
    BASARI: "Başarı (satış tamamlandı, işlem bitti)",
    UYARI: "Uyarı (dikkat, okutma işlenmedi)",
    HATA: "Hata (ürün tanınmadı, işlem yapılamadı)",
}
SEVIYELER: dict[int, str] = {1: "Düşük", 2: "Orta", 3: "Yüksek"}
_GENLIK = {1: 0.22, 2: 0.45, 3: 0.85}
ORNEKLEME = 22_050

#: İşaret adı → (tür, [(frekans Hz, süre ms), ...]); frekans 0 = sessizlik.
ISARETLER: dict[str, tuple[str, list[tuple[int, int]]]] = {
    "scan": (OKUTMA, [(1200, 45)]),
    "price_check": (OKUTMA, [(1600, 35), (0, 35), (1600, 35)]),
    "success": (BASARI, [(880, 60), (1320, 90)]),
    "warning": (UYARI, [(660, 110), (0, 30), (520, 150)]),
    "blocked": (UYARI, [(380, 70), (300, 70)]),
    "error": (HATA, [(330, 160), (0, 30), (250, 220)]),
}

_ENABLED = True
_SEVIYE = 2
_KAPALI_TURLER: set[str] = set()
_DOSYALAR: dict[str, Path] = {}
#: (işaret, seviye) → WAV baytları; süreç başına bir kez üretilir.
_WAV_ONBELLEK: dict[tuple[str, int], bytes] = {}


# ===================== Ayar ================================================
def set_enabled(enabled: bool) -> None:
    global _ENABLED
    _ENABLED = bool(enabled)


def is_enabled() -> bool:
    return _ENABLED


def yapilandir(enabled: bool, seviye: int = 2, acik_turler=None,
               klasor: str | Path | None = None) -> None:
    """Ayarları uygular; ``klasor`` verilirse WAV dosyalarını (gerekirse) üretir."""
    global _SEVIYE, _KAPALI_TURLER
    set_enabled(enabled)
    _SEVIYE = seviye if seviye in SEVIYELER else 2
    acik = set(TURLER) if acik_turler is None else set(acik_turler)
    _KAPALI_TURLER = set(TURLER) - acik
    if klasor is not None:
        _DOSYALAR.clear()
        _DOSYALAR.update(hazirla(klasor, _SEVIYE))


def tur_acik_mi(tur: str) -> bool:
    return _ENABLED and tur not in _KAPALI_TURLER


# ===================== WAV üretimi =========================================
def wav_bayt(tonlar: list[tuple[int, int]], seviye: int = 2,
             ornekleme: int = ORNEKLEME) -> bytes:
    """16 bit, tek kanal PCM. Her tonun başı/sonu yumuşatılır (tık sesi olmaz)."""
    genlik = _GENLIK.get(seviye, _GENLIK[2]) * 32767
    ornekler = bytearray()
    for frekans, sure_ms in tonlar:
        n = int(ornekleme * sure_ms / 1000)
        yumusak = max(1, min(n // 6, int(ornekleme * 0.004)))
        for i in range(n):
            if frekans <= 0:
                deger = 0
            else:
                zarf = min(1.0, i / yumusak, (n - 1 - i) / yumusak)
                deger = int(genlik * zarf * math.sin(2 * math.pi * frekans * i / ornekleme))
            ornekler += struct.pack("<h", deger)
    veri = bytes(ornekler)
    return (b"RIFF" + struct.pack("<I", 36 + len(veri)) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, ornekleme, ornekleme * 2, 2, 16)
            + b"data" + struct.pack("<I", len(veri)) + veri)


def hazirla(klasor: str | Path, seviye: int = 2) -> dict[str, Path]:
    """İşaret başına ``<ad>_<seviye>.wav``; içeriği aynıysa yeniden yazılmaz.

    Yazılamayan dosya atlanır (o işaret ``Beep`` yedeğiyle çalınır).
    """
    hedef = Path(klasor)
    sonuc: dict[str, Path] = {}
    try:
        hedef.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.warning("Ses klasörü oluşturulamadı: %s", hedef)
        return sonuc
    for ad, (_tur, tonlar) in ISARETLER.items():
        yol = hedef / f"{ad}_{seviye}.wav"
        anahtar = (ad, seviye)
        if anahtar not in _WAV_ONBELLEK:
            _WAV_ONBELLEK[anahtar] = wav_bayt(tonlar, seviye)
        icerik = _WAV_ONBELLEK[anahtar]
        try:
            if not yol.exists() or yol.read_bytes() != icerik:
                gecici = yol.with_suffix(".tmp")
                gecici.write_bytes(icerik)
                os.replace(gecici, yol)
            sonuc[ad] = yol
        except OSError:
            log.warning("Ses dosyası yazılamadı: %s", yol)
    return sonuc


# ===================== Çalma ===============================================
def _oynat(yol: Path) -> bool:
    """Eşzamansız çal (beklemez). Başarısızsa ``False``."""
    if winsound is None:
        return False
    try:
        winsound.PlaySound(
            str(yol), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        return True
    except Exception:                              # pragma: no cover
        return False


def _beep(frequency: int, duration_ms: int) -> None:
    """Yedek: dosya çalınamazsa (BEKLETİR; yalnızca son çare)."""
    if winsound is None or frequency <= 0:
        return
    try:
        winsound.Beep(frequency, duration_ms)
    except Exception:                              # pragma: no cover
        pass


def cal(ad: str) -> None:
    """Adı verilen işareti, türü açıksa çalar."""
    tur, tonlar = ISARETLER[ad]
    if not tur_acik_mi(tur):
        return
    yol = _DOSYALAR.get(ad)
    if yol is not None and _oynat(yol):
        return
    for frekans, sure in tonlar:
        _beep(frequency=frekans, duration_ms=sure)


def scan() -> None:
    """Okutma tuttu (ürün sepete/fişe/sayıma eklendi): kısa ve tiz."""
    cal("scan")


def success() -> None:
    """İşlem tamamlandı (satış, bekletme, sayım bitti…): yükselen iki ton."""
    cal("success")


def warning() -> None:
    """Dikkat: işlem oldu ama bir not var (örn. stok eksiye düştü)."""
    cal("warning")


def error() -> None:
    """Tanınmayan barkod ya da yapılamayan işlem."""
    cal("error")


def blocked() -> None:
    """Karar penceresi açıkken okutma yapıldı: alçak ve kısa iki ton.

    Bilerek 'başarı' sesinden AÇIKÇA farklıdır; kullanıcı ekrana bakmadan da
    okutmanın işlenmediğini anlar.
    """
    cal("blocked")


def price_check() -> None:
    """Fiyat Gör: satıştan AYIRT EDİLEBİLEN iki kısa tiz ses (satış yapılmadı)."""
    cal("price_check")
