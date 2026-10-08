"""Donanım durumları (V1.2 M9d) — DÜRÜST: kanıt yoksa "bağlı" denmez.

Bu uygulama donanımla yalnızca klavye gibi davranan barkod okuyucu üzerinden
konuşur. Müşteri ekranı, banka POS'u, fiş yazıcısı ve para çekmecesi için
gerçek bir bağlantı YOKTUR; bunlar "yok / tanımlı değil" olarak gösterilir,
asla yeşil "bağlı" değil. Barkod okuyucu da ancak bu oturumda makine hızında
gerçek bir okutma geldiyse "çalışıyor" sayılır.

Qt bilmez.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

CALISIYOR = "CALISIYOR"
BILINMIYOR = "BILINMIYOR"
YOK = "YOK"
HATA = "HATA"
DURUM_ADLARI = {
    CALISIYOR: "Çalışıyor",
    BILINMIYOR: "Bilinmiyor",
    YOK: "Yok / tanımlı değil",
    HATA: "Hata",
}


@dataclass(frozen=True, slots=True)
class DonanimDurumu:
    ad: str
    durum: str
    aciklama: str


class HardwareStatusService:
    def __init__(self, display_service, payments, clock=time.monotonic) -> None:
        self.display_service = display_service
        self.payments = payments
        self._clock = clock
        self._okutma_sayisi = 0
        self._son_okutma: float | None = None
        self._son_okutma_kodu = ""

    def okutma_kaydet(self, event) -> None:
        """Okuyucudan (makine hızında) gelen okutma — kanıt."""
        if getattr(event, "source", "SCANNER") != "SCANNER":
            return
        if not getattr(event, "looks_machine_typed", False):
            return
        self._okutma_sayisi += 1
        self._son_okutma = self._clock()
        self._son_okutma_kodu = event.code

    @property
    def okutma_sayisi(self) -> int:
        return self._okutma_sayisi

    def son_okutma_saniye(self) -> float | None:
        return None if self._son_okutma is None else self._clock() - self._son_okutma

    def _okuyucu(self) -> DonanimDurumu:
        if not self._okutma_sayisi:
            return DonanimDurumu(
                "Barkod okuyucu", BILINMIYOR,
                "Bu oturumda henüz okutma gelmedi; okuyucunun bağlı olup olmadığı "
                "bilinmiyor. Barkod Testi ekranında bir ürün okutup deneyin.")
        gecen = int(self.son_okutma_saniye() or 0)
        return DonanimDurumu(
            "Barkod okuyucu", CALISIYOR,
            f"Bu oturumda {self._okutma_sayisi} okutma geldi; sonuncusu {gecen} sn önce.")

    def _musteri_ekrani(self) -> DonanimDurumu:
        ekran = self.display_service.display
        tur = type(ekran).__name__
        if tur == "NullCustomerDisplay":
            return DonanimDurumu("Müşteri ekranı", YOK,
                                 "Müşteri ekranı tanımlı değil; tutar yalnızca kasa "
                                 "ekranında görünür.")
        return DonanimDurumu("Müşteri ekranı", BILINMIYOR,
                             f"{tur}: cihazdan doğrulama alınamıyor; yazma hataları "
                             "kayıt dosyasına yazılır, satışı engellemez.")

    def _kart_pos(self) -> DonanimDurumu:
        adaptor = self.payments.adapter_for("KART")
        tur = type(adaptor).__name__ if adaptor is not None else ""
        if adaptor is None or tur == "ManualCardAdapter":
            return DonanimDurumu("Banka POS cihazı", YOK,
                                 "POS cihazıyla bağlantı yok: KART tuşu yalnızca ödeme "
                                 "yöntemini kaydeder; tutarı POS'a siz girersiniz.")
        return DonanimDurumu("Banka POS cihazı", BILINMIYOR, f"{tur} tanımlı.")

    def durumlar(self) -> list[DonanimDurumu]:
        return [
            self._okuyucu(),
            self._musteri_ekrani(),
            self._kart_pos(),
            DonanimDurumu("Fiş yazıcısı", YOK, "Fiş yazdırma bu sürümde yok."),
            DonanimDurumu("Para çekmecesi", YOK,
                          "Çekmece açma bu sürümde yok; çekmeceyi elle açın."),
        ]
