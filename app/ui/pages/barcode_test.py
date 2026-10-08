"""Barkod Testi (F12): okuyucu gerçekten ne gönderiyor?

Bu ekran HİÇBİR KAYIT OLUŞTURMAZ — ne satış, ne stok. Yalnızca okuyucunun
gönderdiği ham veriyi ve zamanlamasını gösterir.

Bir okuyucu beklenmedik davrandığında (baştan karakter ekliyor, sonuna Tab
gönderiyor, aynı okutmayı iki kez yolluyor) sorunu burada görüp Ayarlar'dan
düzeltmek mümkündür.

V1.2 (M9c): her okutma için yönlendirme sonucu (işlendi / engellendi / çift
okuma…), tuş sayısı, ortalama ve en uzun tuş arası, sonlandırıcı (Enter, Tab ya
da yok), ön/son ek kırpmasının etkisi ve GTIN değerlendirmesi gösterilir.
Başka bir ekrandayken engellenen ya da çift sayılan okutmalar da listelenir.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import barcode_text as bt
from app.scanner.scan_router import ScanOutcome
from app.ui import metrics
from app.ui.pages.base import Page
from app.ui.widgets.barcode_input import BarcodeInput, FocusKeeper
from app.ui.widgets.common import (
    Card,
    PageHeader,
    ResultBanner,
    make_label,
    setup_table,
    stretch_column,
)

SUTUNLAR = ["Okunan Değer", "Tuş", "Tuş arası (ort. / en uzun)", "Sonlandırıcı",
            "Yönlendirme", "Değerlendirme", "Ürün"]
SONLANDIRICI_ADLARI = {"ENTER": "Enter", "TAB": "Tab", "YOK": "yok (bekleme ile)",
                       "": "elle"}

SONUC_ETIKETLERI = {
    ScanOutcome.HANDLED: "İşlendi",
    ScanOutcome.QUEUED: "Sıraya alındı",
    ScanOutcome.BLOCKED: "Engellendi (pencere açıktı)",
    ScanOutcome.DUPLICATE: "Çift okuma sayıldı",
    ScanOutcome.NO_HANDLER: "İşleyen ekran yok",
}


class BarcodeTestPage(Page):
    nav_title = "🔎  Barkod Testi"
    nav_key = "barkod_testi"
    nav_group = "yonetim"
    accepts_scans = True

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self._events: list = []

        self.header = PageHeader(
            "🔎 Barkod Testi",
            "Okuyucunuzu deneyin. Bu ekranda hiçbir satış ya da stok kaydı oluşmaz.",
        )
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
        )
        duzen.setSpacing(metrics.PAGE_SPACING)

        kart = Card()
        kart.body.addWidget(make_label("BARKOD OKUTUN", "cardTitle"))
        self.barcode = BarcodeInput("sale")
        self.barcode.submitted.connect(self._manual)
        kart.body.addWidget(self.barcode)
        duzen.addWidget(kart)

        self.banner = ResultBanner()
        self.banner.show_idle(
            "Hazır", "Elinizdeki bir ürünü okutun; sonuç aşağıda görünecek."
        )
        duzen.addWidget(self.banner)

        self.table = QTableWidget(0, len(SUTUNLAR))
        setup_table(self.table, SUTUNLAR)
        stretch_column(self.table, "Değerlendirme")
        duzen.addWidget(self.table, 1)

        alt = QHBoxLayout()
        self.suggestion_label = make_label("", "cardHint", wrap=True)
        alt.addWidget(self.suggestion_label, 1)
        temizle = QPushButton("Listeyi Temizle")
        temizle.clicked.connect(self._clear)
        alt.addWidget(temizle)
        duzen.addLayout(alt)

        self.root.addWidget(govde, 1)
        self.focus_keeper = FocusKeeper(self.barcode)

    # ===================== Yaşam döngüsü =================================
    def on_activated(self) -> None:
        self.focus_keeper.start()
        self.barcode.setFocus()

    def on_deactivated(self) -> None:
        self.focus_keeper.stop()

    def refresh(self) -> None:
        self._render()

    # ===================== Okutma ========================================
    def handle_scan(self, event) -> None:
        self._record(event)

    def _manual(self, text: str) -> None:
        from app.scanner.scan_event import ScanEvent

        self._record(ScanEvent(code=text, key_count=len(text), avg_gap_ms=200.0,
                               source="ELLE"))

    def _record(self, event) -> None:
        self._events.insert(0, event)
        del self._events[50:]

        eslesme = self.services.barcodes.resolve(event.code)
        if eslesme is None:
            self.banner.show_warning(
                "Okundu — ürün tanınmadı",
                bt.describe(event.code),
                "Bu ekranda kayıt oluşturulmaz.",
            )
        else:
            self.banner.show_success(
                "Okundu", eslesme.product_name,
                f"{bt.describe(event.code)} · {eslesme.quantity} adet",
            )
        self._render()

    def _clear(self) -> None:
        self._events.clear()
        self.main_window.router.clear_diagnostics()
        self._render()

    # ===================== Çizim =========================================
    def rows(self) -> list[tuple]:
        """(olay, yönlendirme etiketi) — bu ekranın işledikleri + başka ekranlarda
        engellenen / çift sayılan / işleyeni olmayan okutmalar (yeniden eskiye)."""
        benim = {olay.scan_id for olay in self._events}
        satirlar = [(olay, "Bu ekranda işlendi" if olay.source != "ELLE" else "Elle yazıldı")
                    for olay in self._events]
        for olay, sonuc in self.main_window.router.diagnostics(50):
            if olay.scan_id not in benim and sonuc != ScanOutcome.HANDLED:
                satirlar.append((olay, SONUC_ETIKETLERI.get(sonuc, sonuc.value)))
        satirlar.sort(key=lambda s: -s[0].scan_id)
        return satirlar[:50]

    def _degerlendirme(self, kod: str) -> str:
        """Kırpma etkisi + GTIN açıklaması."""
        ham = bt.clean(kod)
        try:
            normal = self.services.barcodes.normalize(kod)
        except Exception:
            normal = ham
        kirpma = f"kırpıldı: {ham} → {normal} · " if normal != ham else ""
        return kirpma + bt.describe(normal)

    def _render(self) -> None:
        satirlar = self.rows()
        self.table.setRowCount(len(satirlar))
        en_hizli = None
        for satir, (olay, yonlendirme) in enumerate(satirlar):
            eslesme = self.services.barcodes.resolve(olay.code)
            hiz = (f"{olay.avg_gap_ms:.0f} / {olay.max_gap_ms:.0f} ms"
                   if olay.key_count > 1 and olay.source != "ELLE" else "-")
            if olay.key_count > 1 and olay.source != "ELLE" and (
                    en_hizli is None or olay.avg_gap_ms < en_hizli):
                en_hizli = olay.avg_gap_ms

            hucreler = (
                QTableWidgetItem(olay.code),
                QTableWidgetItem(str(olay.key_count or len(olay.code))),
                QTableWidgetItem(hiz),
                QTableWidgetItem(SONLANDIRICI_ADLARI.get(olay.terminator, olay.terminator)),
                QTableWidgetItem(yonlendirme),
                QTableWidgetItem(self._degerlendirme(olay.code)),
                QTableWidgetItem(eslesme.product_name if eslesme else "tanınmadı"),
            )
            for sutun, hucre in enumerate(hucreler):
                self.table.setItem(satir, sutun, hucre)

        if en_hizli is not None:
            onerilen = max(60, min(400, int(en_hizli * 8)))
            self.suggestion_label.setText(
                f"En hızlı okuma: {en_hizli:.0f} ms/tuş. "
                f"Çift okuma engeli için önerilen değer: {onerilen} ms "
                f"(şu an {self.services.settings.duplicate_scan_ms()} ms)."
            )
        else:
            self.suggestion_label.setText(
                "Barkod okutunca okuyucunuzun hızı burada görünecek."
            )
