"""Müşteriye bakan tutar ekranı (AVAPOS LED).

Kasanın müşteri tarafında rakam gösteren küçük bir ekran vardır. İstenen
davranış:

    boş sepet          → 0.00
    sepet değişti      → güncel toplam
    satış tamamlandı   → son tutar kısa süre kalır
    süre dolunca       → 0.00

**En önemli kural: bu ekran bir satışı ASLA engelleyemez.**
Kablosu çıkmış, portu yanlış, cihaz bozuk olabilir — hiçbiri kasayı
durdurmamalıdır. Bu yüzden ``CustomerDisplayService`` her çağrıyı yutar.

V1.1 durumu
-----------
Gerçek AVAPOS protokolü, COM portu ve baud hızı HENÜZ BİLİNMİYOR. Bu yüzden
hiçbir seri komut tahmin edilmez ve ``pyserial`` bağımlılığı EKLENMEZ.
Yalnızca sözleşme ve ``NullCustomerDisplay`` vardır; protokol ölçülüp
doğrulandığında ``SerialCustomerDisplay`` doldurulur ve başka hiçbir yere
dokunulmaz.
"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

log = logging.getLogger(__name__)


@runtime_checkable
class CustomerDisplay(Protocol):
    """Müşteri ekranı sözleşmesi. Tutarlar tam sayı kuruştur."""

    def show_total(self, kurus: int) -> None: ...
    def show_idle(self) -> None: ...
    def close(self) -> None: ...


class NullCustomerDisplay:
    """Cihaz yokken kullanılan sessiz uygulama — V1.1 varsayılanı.

    Hiçbir şey yapmaz ve hiçbir zaman hata vermez.
    """

    name = "yok"

    def show_total(self, kurus: int) -> None:
        return None

    def show_idle(self) -> None:
        return None

    def close(self) -> None:
        return None


class SerialCustomerDisplay:
    """Seri port üzerinden çalışan gerçek ekran — HENÜZ UYGULANMADI.

    Doldurulmadan önce yapılacaklar:

    1. Cihazın hangi COM portunda göründüğünü belirle (Aygıt Yöneticisi).
    2. Baud hızını, veri bitlerini, pariteyi ve stop bitini ölç.
    3. Protokolü doğrula: çoğu LED müşteri ekranı ya ESC/POS benzeri bir komut
       seti ya da düz ASCII + CR kullanır. TAHMİN EDİLMEZ, ölçülür.
    4. ``requirements.txt``'e ``pyserial`` eklenir ve
       ``TekelStok.spec`` içindeki ``PySide6.QtSerialPort`` dışlaması gözden
       geçirilir (not: ``QtSerialPort`` PySide6-Essentials'ta YOKTUR).
    5. Yazma işlemleri kısa zaman aşımıyla yapılır; ekran asla kasayı bekletmez.

    O zamana kadar bu sınıf bilerek çalışmaz: yanlış bayt göndermek, hiç
    göndermemekten daha kötüdür.
    """

    name = "seri"

    def __init__(self, port: str = "", baud: int = 9600) -> None:
        self.port = port
        self.baud = baud

    def _not_ready(self) -> None:
        raise NotImplementedError(
            "AVAPOS müşteri ekranı protokolü henüz doğrulanmadı. "
            "Gerçek port/baud/komut seti ölçülmeden seri komut gönderilmez."
        )

    def show_total(self, kurus: int) -> None:
        self._not_ready()

    def show_idle(self) -> None:
        self._not_ready()

    def close(self) -> None:
        return None


class CustomerDisplayService:
    """Ekran çağrılarını GÜVENLİ hâle getiren sarmalayıcı.

    Her çağrı ``try/except`` içindedir. Bir cihaz hatası log'a yazılır ve
    yutulur; çağıran taraf hiçbir şey fark etmez. Bu, "ekran arızası satışı
    bozamaz" garantisinin tek uygulandığı yerdir.

    Arka arkaya aynı tutar gönderilmez (``_last``): gereksiz seri trafiği
    önlenir ve ileride yavaş bir cihaz kasayı yavaşlatmaz.
    """

    def __init__(self, display: CustomerDisplay | None = None) -> None:
        self._display: CustomerDisplay = display or NullCustomerDisplay()
        self._last: int | None = None

    def set_display(self, display: CustomerDisplay) -> None:
        self._display = display or NullCustomerDisplay()
        self._last = None

    @property
    def display(self) -> CustomerDisplay:
        return self._display

    def show_total(self, kurus: int) -> None:
        kurus = int(kurus)
        if kurus == self._last:
            return
        self._last = kurus
        try:
            self._display.show_total(kurus)
        except Exception:
            log.warning("Müşteri ekranına tutar yazılamadı", exc_info=True)

    def show_idle(self) -> None:
        if self._last == 0:
            return
        self._last = 0
        try:
            self._display.show_idle()
        except Exception:
            log.warning("Müşteri ekranı sıfırlanamadı", exc_info=True)

    def close(self) -> None:
        try:
            self._display.close()
        except Exception:
            log.warning("Müşteri ekranı kapatılamadı", exc_info=True)
