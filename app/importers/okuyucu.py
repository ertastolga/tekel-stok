"""CSV ve XLSX okuyucu.

* CSV: kodlama sırayla ``utf-8-sig`` → ``utf-8`` → ``cp1254`` (Türkçe Windows
  Excel'i) denenir; ayırıcı ``; , TAB |`` arasından koklanır. Bütün hücreler
  METİN kalır — baştaki sıfırlar asla kaybolmaz.
* XLSX: yalnızca ``openpyxl`` ile, salt okunur ve formül SONUÇLARIYLA okunur
  (kendi XLSX ayrıştırıcımız YOKTUR). Sayı hücreleri sayı olarak gelir; barkod
  sütununda bunlar ayrıca işaretlenir (baştaki sıfır kaybolmuş olabilir).
  ``openpyxl`` yoksa XLSX "geçici olarak kullanılamıyor" der, CSV çalışır.
* İlk boş olmayan satır başlıktır; tamamen boş satırlar atlanır.
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import DomainError

try:  # pragma: no cover - ortama bağlı
    import openpyxl

    XLSX_KULLANILABILIR = True
except ImportError:  # pragma: no cover - ortama bağlı
    openpyxl = None
    XLSX_KULLANILABILIR = False

#: Okunan en çok veri satırı (yanlış dosya seçimini yakalar).
EN_COK_SATIR = 20_000
#: En büyük dosya (bayt).
EN_BUYUK_DOSYA = 25 * 1024 * 1024
KODLAMALAR = ("utf-8-sig", "utf-8", "cp1254")
AYIRICILAR = ";,\t|"


class DosyaOkunamadi(DomainError):
    """Dosya okunamadı — mesaj kullanıcıya gösterilir."""


@dataclass
class Tablo:
    """Okunan dosya: başlıklar ve ham hücreler (``str | int | float | None`` …)."""

    basliklar: list[str]
    satirlar: list[list]
    bicim: str
    kodlama: str | None = None
    ayirici: str | None = None
    sayfa: str | None = None
    sayfalar: list[str] = field(default_factory=list)

    def hucre(self, satir: list, sutun: int | None):
        if sutun is None or sutun >= len(satir):
            return None
        return satir[sutun]


def dosya_ozeti(yol: str | Path) -> tuple[str, int]:
    """(SHA-256, bayt) — denetim kaydına yazılır."""
    ozet = hashlib.sha256()
    boyut = 0
    with open(yol, "rb") as dosya:
        for parca in iter(lambda: dosya.read(1 << 16), b""):
            ozet.update(parca)
            boyut += len(parca)
    return ozet.hexdigest(), boyut


def oku(yol: str | Path, sayfa: str | None = None) -> Tablo:
    yol = Path(yol)
    try:
        boyut = yol.stat().st_size
    except OSError as hata:
        raise DosyaOkunamadi("Dosya açılamadı.", str(hata)) from None
    if boyut > EN_BUYUK_DOSYA:
        raise DosyaOkunamadi("Dosya çok büyük (en çok 25 MB).")
    uzanti = yol.suffix.lower()
    if uzanti in (".xlsx", ".xlsm"):
        return _xlsx(yol, sayfa)
    if uzanti in (".csv", ".txt"):
        return _csv(yol)
    if uzanti == ".xls":
        raise DosyaOkunamadi(
            "Eski Excel (.xls) biçimi okunamaz. Dosyayı Excel'de 'Excel Çalışma Kitabı "
            "(.xlsx)' ya da 'CSV (noktalı virgülle ayrılmış)' olarak kaydedin.")
    raise DosyaOkunamadi("Yalnızca .xlsx ve .csv dosyaları içe aktarılabilir.")


# ===================== CSV =================================================
def _coz(ham: bytes) -> tuple[str, str]:
    for kodlama in KODLAMALAR:
        try:
            return ham.decode(kodlama), kodlama
        except UnicodeDecodeError:
            continue
    raise DosyaOkunamadi("Dosyanın karakter kodlaması tanınmadı.")


def _ayirici(metin: str) -> str:
    ornek = "\n".join(metin.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(ornek, delimiters=AYIRICILAR).delimiter
    except csv.Error:
        sayilar = {a: ornek.count(a) for a in AYIRICILAR}
        en_cok = max(sayilar, key=sayilar.get)
        return en_cok if sayilar[en_cok] else ";"


def _csv(yol: Path) -> Tablo:
    metin, kodlama = _coz(yol.read_bytes())
    ayirici = _ayirici(metin)
    okuyucu = csv.reader(io.StringIO(metin, newline=""), delimiter=ayirici)
    basliklar, satirlar = _ayikla(
        [[(h.strip() if h.strip() else None) for h in s] for s in okuyucu])
    return Tablo(basliklar, satirlar, "CSV", kodlama=kodlama, ayirici=ayirici)


# ===================== XLSX ================================================
def _xlsx(yol: Path, sayfa: str | None) -> Tablo:
    if not XLSX_KULLANILABILIR:
        raise DosyaOkunamadi(
            "Excel (.xlsx) okuma geçici olarak kullanılamıyor. Dosyayı Excel'de "
            "'CSV (noktalı virgülle ayrılmış)' olarak kaydedip onu seçin.")
    try:
        kitap = openpyxl.load_workbook(yol, read_only=True, data_only=True)
    except Exception as hata:            # bozuk / şifreli / yanlış uzantı
        raise DosyaOkunamadi("Excel dosyası okunamadı.", repr(hata)) from None
    try:
        adlar = list(kitap.sheetnames)
        if sayfa is not None and sayfa not in adlar:
            raise DosyaOkunamadi(f"'{sayfa}' adlı sayfa yok.")
        calisma = kitap[sayfa] if sayfa else kitap.worksheets[0]
        ham = []
        for satir in calisma.iter_rows(values_only=True):
            ham.append([(h.strip() or None) if isinstance(h, str) else h for h in satir])
            if len(ham) > EN_COK_SATIR + 50:
                break
        basliklar, satirlar = _ayikla(ham)
        return Tablo(basliklar, satirlar, "XLSX", sayfa=calisma.title, sayfalar=adlar)
    finally:
        kitap.close()


# ===================== Ortak ===============================================
def _ayikla(ham: list[list]) -> tuple[list[str], list[list]]:
    dolu = [s for s in ham if any(h is not None and h != "" for h in s)]
    if not dolu:
        raise DosyaOkunamadi("Dosya boş görünüyor.")
    baslik = dolu[0]
    basliklar = [str(h).strip() if h is not None else "" for h in baslik]
    while basliklar and not basliklar[-1]:
        basliklar.pop()
    if not any(basliklar):
        raise DosyaOkunamadi("İlk satırda sütun başlıkları bulunamadı.")
    satirlar = [list(s[: len(basliklar)]) + [None] * (len(basliklar) - len(s))
                for s in dolu[1:]]
    if len(satirlar) > EN_COK_SATIR:
        raise DosyaOkunamadi(f"Dosyada {EN_COK_SATIR:,} satırdan fazlası var. "
                             "Lütfen dosyayı bölün.".replace(",", "."))
    return basliklar, satirlar
