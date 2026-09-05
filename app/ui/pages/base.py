"""Sayfa taban sınıfı — ekranların tek sözleşmesi.

Her sayfa ``nav_key`` ve ``nav_title`` bildirir; ana pencere bunları okuyup
menüyü ve yığını kendisi kurar. Sayfalar birbirini TANIMAZ; gezinme daima
``main_window.go_to()`` üzerinden olur.

Sayfalar iş kuralı SQL'i çalıştırmaz: her şey ``self.services`` üzerinden gider.
"""
from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget


class Page(QWidget):
    #: Menüde görünen ad.
    nav_title = ""
    #: Gezinme anahtarı (``go_to`` bunu kullanır).
    nav_key = ""
    #: Menüde hangi grupta görünecek: "gunluk" | "yonetim" | "" (gizli).
    nav_group = "yonetim"
    #: Bu sayfa barkod okutma kabul ediyor mu?
    accepts_scans = False

    def __init__(self, services, main_window) -> None:
        super().__init__()
        self.services = services
        self.main_window = main_window
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)

    # -- Yaşam döngüsü ----------------------------------------------------
    def on_activated(self) -> None:
        """Sayfa görünür oldu. Varsayılan davranış: verileri tazele."""
        self.refresh()

    def on_deactivated(self) -> None:
        """Sayfa gizlendi. Zamanlayıcılar burada durdurulur."""

    def refresh(self) -> None:
        """Verileri yeniden yükle. Alt sınıflar doldurur."""

    # -- Okutma -----------------------------------------------------------
    def handle_scan(self, event) -> None:
        """Merkezi yönlendiriciden gelen okutma. ``accepts_scans`` ile açılır."""

    # -- Kolaylıklar ------------------------------------------------------
    def notify(self, message: str, seconds: int = 4) -> None:
        self.main_window.show_status(message, seconds)

    def data_changed(self) -> None:
        """Veri değişti: görünen sayfa kendini tazelesin."""
        self.main_window.data_changed()
