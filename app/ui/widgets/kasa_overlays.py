"""Kasa katmanları: sayfanın üstünü kaplayan, ENGELLEMEYEN paneller.

Sözleşme (plan §5.2):
  1. Katman bir pencere DEĞİLDİR; Kasa sayfasının tam boy çocuğudur ve
     sinyallerle çalışır. İç içe olay döngüsü YOKTUR — mimari testi bu dosyada
     olay döngüsü sınıfını ve pencere çalıştırma çağrısını metin olarak yasaklar.
  2. Okutma, katman açıkken sayfanın tek girişinden (``_add_by_code``) geçer;
     okutmayı kabul etmeyen katman ``notify_blocked`` ile katmanın İÇİNDE
     duyulur biçimde reddeder.
  3. Katman açıkken sepet ve ödeme denetimleri kapalıdır; sayfa değişirse ya
     da Esc'e basılırsa katman "vazgeç" anlamıyla kapanır.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.money import format_tl
from app.ui import metrics, sound, theme
from app.ui.widgets.common import EmptyState, make_label
from app.ui.widgets.touch_input import ScanSafeLineEdit, TouchDisplay, TouchKeyboard

#: Engellenen okutma bildiriminin katmanda kalma süresi.
ENGEL_BILDIRIMI_MS = 2500


def _dokunma_dugmesi(metin: str, ad: str = "kasaTool") -> QPushButton:
    dugme = QPushButton(metin)
    dugme.setObjectName(ad)
    dugme.setProperty("dokunma", "evet")
    dugme.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
    dugme.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return dugme


class KasaOverlay(QFrame):
    """Katman tabanı: başlık, "Kapat", engellenen okutma bildirimi, gövde."""

    close_requested = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("kasaOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#kasaOverlay {{ background: {theme.BG}; border: 2px solid {theme.CART}; "
            "border-radius: 10px; }"
        )
        dis = QVBoxLayout(self)
        dis.setContentsMargins(metrics.PAGE_MARGIN_H, 8, metrics.PAGE_MARGIN_H, 8)
        dis.setSpacing(8)

        ust = QHBoxLayout()
        self.header_layout = ust
        self.title_label = make_label(title, "sectionTitle")
        ust.addWidget(self.title_label)
        ust.addStretch(1)
        self.close_button = _dokunma_dugmesi("Kapat")
        self.close_button.clicked.connect(self.close_requested.emit)
        ust.addWidget(self.close_button)
        dis.addLayout(ust)

        self.notice_label = QLabel("")
        self.notice_label.setWordWrap(True)
        self.notice_label.setStyleSheet(
            f"background: {theme.WARNING_LIGHT}; color: {theme.WARNING}; "
            "font-weight: 600; padding: 8px; border-radius: 6px;"
        )
        self.notice_label.setVisible(False)
        dis.addWidget(self.notice_label)

        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        dis.addLayout(self.body, 1)

        self._bildirim = QTimer(self)
        self._bildirim.setSingleShot(True)
        self._bildirim.timeout.connect(lambda: self.notice_label.setVisible(False))

    def notify_blocked(self, _event=None) -> None:
        """Bu katman açıkken okutma yapılmaz: ANINDA, duyulur ret."""
        sound.blocked()
        self.notice_label.setText(
            "Bu pencere açıkken okutulan barkod işlenmedi. Önce pencereyi kapatın."
        )
        self.notice_label.setVisible(True)
        self._bildirim.start(ENGEL_BILDIRIMI_MS)

    def cover(self, page: QWidget) -> None:
        """Sayfanın tamamını kaplar ve öne gelir."""
        self.setParent(page)
        self.setGeometry(page.rect())
        self.show()
        self.raise_()


class _BekleyenSatir(QFrame):
    """Bekleyen tek sepet: ad, özet, Aç / Sil (silmede satır içi onay)."""

    def __init__(self, satir, panel: "BekleyenlerPanel") -> None:
        super().__init__()
        self.setObjectName("cartRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.draft_id = int(satir["id"])
        duzen = QHBoxLayout(self)
        duzen.setContentsMargins(14, 8, 14, 8)
        duzen.setSpacing(10)

        metin = QVBoxLayout()
        metin.setSpacing(1)
        self.name_label = make_label(satir["label"] or "Bekleyen sepet", "cartName")
        bekletilme = (
            datetime.fromtimestamp(satir["parked_at_utc"]).strftime("%H:%M")
            if satir["parked_at_utc"] else ""
        )
        self.detail_label = make_label(
            f"{satir['urun_adedi']} ürün · {format_tl(satir['toplam'])}"
            + (f" · {bekletilme}" if bekletilme else ""),
            "cartPrice",
        )
        metin.addWidget(self.name_label)
        metin.addWidget(self.detail_label)
        duzen.addLayout(metin, 1)

        self.open_button = _dokunma_dugmesi("Aç", "primary")
        self.open_button.clicked.connect(lambda: panel.resume_requested.emit(self.draft_id))
        duzen.addWidget(self.open_button)
        self.delete_button = _dokunma_dugmesi("Sil")
        self.delete_button.clicked.connect(self._silmeyi_sor)
        duzen.addWidget(self.delete_button)
        self.confirm_delete_button = _dokunma_dugmesi("Evet, sil", "danger")
        self.confirm_delete_button.clicked.connect(
            lambda: panel.delete_confirmed.emit(self.draft_id)
        )
        self.confirm_delete_button.setVisible(False)
        duzen.addWidget(self.confirm_delete_button)
        self.cancel_delete_button = _dokunma_dugmesi("Vazgeç")
        self.cancel_delete_button.clicked.connect(self._silmeden_vazgec)
        self.cancel_delete_button.setVisible(False)
        duzen.addWidget(self.cancel_delete_button)

    def _silmeyi_sor(self) -> None:
        for dugme in (self.open_button, self.delete_button):
            dugme.setVisible(False)
        for dugme in (self.confirm_delete_button, self.cancel_delete_button):
            dugme.setVisible(True)

    def _silmeden_vazgec(self) -> None:
        for dugme in (self.open_button, self.delete_button):
            dugme.setVisible(True)
        for dugme in (self.confirm_delete_button, self.cancel_delete_button):
            dugme.setVisible(False)


class BekleyenlerPanel(KasaOverlay):
    """F1 — Bekleyen Sepetler: listele, aç (gerekirse değiştir), sil."""

    resume_requested = Signal(int)
    swap_confirmed = Signal(int)
    delete_confirmed = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Bekleyen Sepetler", parent)
        self.rows: dict[int, _BekleyenSatir] = {}

        # Eldeki sepet doluyken başka bir sepeti açmak: satır içi, modal
        # olmayan onay ("değiştir").
        self.swap_frame = QFrame()
        self.swap_frame.setObjectName("swapFrame")
        self.swap_frame.setStyleSheet(
            f"#swapFrame {{ background: {theme.INFO_LIGHT}; border-radius: 8px; }}"
        )
        takas = QHBoxLayout(self.swap_frame)
        takas.setContentsMargins(12, 8, 12, 8)
        self.swap_label = make_label("", wrap=True)
        takas.addWidget(self.swap_label, 1)
        self.swap_yes_button = _dokunma_dugmesi("Evet, değiştir", "primary")
        self.swap_yes_button.clicked.connect(self._takasi_onayla)
        takas.addWidget(self.swap_yes_button)
        self.swap_no_button = _dokunma_dugmesi("Vazgeç")
        self.swap_no_button.clicked.connect(self.cancel_swap)
        takas.addWidget(self.swap_no_button)
        self.swap_frame.setVisible(False)
        self.body.addWidget(self.swap_frame)
        self._takas_id: int | None = None

        self.empty = EmptyState(
            "Bekleyen sepet yok",
            "Bir müşteriyi bekletmek için sepetteyken \"Beklet\"e dokunun.",
        )
        self.body.addWidget(self.empty)

        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        icerik = QWidget()
        self.list_layout = QVBoxLayout(icerik)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        self.list_layout.addStretch(1)
        kaydirma.setWidget(icerik)
        self.body.addWidget(kaydirma, 1)

    def set_items(self, satirlar) -> None:
        for satir in self.rows.values():
            self.list_layout.removeWidget(satir)
            satir.deleteLater()
        self.rows.clear()
        for sira, satir in enumerate(satirlar):
            gerec = _BekleyenSatir(satir, self)
            self.list_layout.insertWidget(sira, gerec)
            self.rows[gerec.draft_id] = gerec
        self.empty.setVisible(not self.rows)
        self.cancel_swap()

    def ask_swap(self, draft_id: int, current_summary: str) -> None:
        self._takas_id = draft_id
        ad = self.rows[draft_id].name_label.text() if draft_id in self.rows else "sepet"
        self.swap_label.setText(
            f"Eldeki sepet ({current_summary}) bekletilsin ve \"{ad}\" açılsın mı?"
        )
        self.swap_frame.setVisible(True)

    def cancel_swap(self) -> None:
        self._takas_id = None
        self.swap_frame.setVisible(False)

    def _takasi_onayla(self) -> None:
        if self._takas_id is not None:
            hedef = self._takas_id
            self.cancel_swap()
            self.swap_confirmed.emit(hedef)


class UrunAraPanel(KasaOverlay):
    """F2 — Ürün Ara: barkodu okunamayan ürünü ada / markaya / barkoda göre bul.

    Bir sonuca dokunmak 1 adet ekler; panel açık kalır (birden çok ürün).
    Panel açıkken okutma ÇALIŞIR: okutulan ürün sepete eklenir ve sonucu
    panelin kendi geri bildirim satırında görünür. Klavyesiz kasada ekran
    klavyesi, klavyeli bilgisayarda okutmaya dayanıklı bir yazı alanı kullanılır.
    """

    product_chosen = Signal(int)

    #: En çok gösterilen sonuç (kasa ekranı sade kalsın).
    SONUC_SINIRI = 30

    def __init__(self, products, touch_keyboard: bool = True, scanner=None,
                 parent: QWidget | None = None) -> None:
        super().__init__("Ürün Ara", parent)
        self.products = products
        self.touch_keyboard = touch_keyboard
        self.result_buttons: list[QPushButton] = []
        self.title_label.setVisible(False)

        if touch_keyboard:
            self.display = TouchDisplay("Ürün adı, marka ya da barkod", max_length=60)
            self.display.changed.connect(lambda _m: self._zamanla())
            self.query_widget = self.display
        else:
            self.edit = ScanSafeLineEdit(scanner=scanner)
            self.edit.setPlaceholderText("Ürün adı, marka ya da barkod")
            self.edit.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
            self.edit.textChanged.connect(lambda _m: self._zamanla())
            self.query_widget = self.edit
        self.header_layout.insertWidget(0, self.query_widget, 1)

        self.feedback_label = make_label("", wrap=False)
        self.feedback_label.setMinimumHeight(22)
        self.body.addWidget(self.feedback_label)

        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        kaydirma.setMinimumHeight(2 * metrics.TOUCH_TARGET_MIN + 8)
        icerik = QWidget()
        self.results_layout = QVBoxLayout(icerik)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.results_layout.setSpacing(6)
        self.empty = make_label("Aramak için yazmaya başlayın.", "cardHint")
        self.results_layout.addWidget(self.empty)
        self.results_layout.addStretch(1)
        kaydirma.setWidget(icerik)
        self.body.addWidget(kaydirma, 1)

        if touch_keyboard:
            self.keyboard = TouchKeyboard()
            self.keyboard.bind(self.display)
            self.body.addWidget(self.keyboard)

        self._zamanlayici = QTimer(self)
        self._zamanlayici.setSingleShot(True)
        self._zamanlayici.setInterval(150)
        self._zamanlayici.timeout.connect(self.search_now)

    def query(self) -> str:
        return self.display.value() if self.touch_keyboard else self.edit.text()

    def set_query(self, metin: str) -> None:
        if self.touch_keyboard:
            self.display.set_value(metin)
        else:
            self.edit.setText(metin)

    def _zamanla(self) -> None:
        self._zamanlayici.start()

    def search_now(self) -> None:
        self._zamanlayici.stop()
        metin = self.query()
        sonuclar = self.products.search_for_sale(metin, limit=self.SONUC_SINIRI)
        for dugme in self.result_buttons:
            self.results_layout.removeWidget(dugme)
            dugme.deleteLater()
        self.result_buttons = []
        for sira, satir in enumerate(sonuclar):
            ad = satir["name"] + (f"  ·  {satir['marka']}" if satir["marka"] else "")
            dugme = QPushButton(f"{ad}    {format_tl(satir['sale_price'])}")
            dugme.setObjectName("searchResult")
            dugme.setProperty("dokunma", "evet")
            dugme.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
            dugme.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            dugme.setProperty("product_id", int(satir["id"]))
            dugme.clicked.connect(
                lambda _=False, pid=int(satir["id"]): self.product_chosen.emit(pid)
            )
            self.results_layout.insertWidget(sira, dugme)
            self.result_buttons.append(dugme)
        bos = not sonuclar
        self.empty.setVisible(bos)
        self.empty.setText(
            "Aramak için yazmaya başlayın." if not metin.strip()
            else "Bu aramayla satılabilir ürün bulunamadı."
        )

    def show_feedback(self, kind: str, text: str) -> None:
        """Sepetin / satışın son sonucu (okutma ya da dokunuş) panelin içinde."""
        renk = {
            "success": theme.PRIMARY_DARK, "error": theme.DANGER,
            "warning": theme.WARNING,
        }.get(kind, theme.TEXT_MUTED)
        self.feedback_label.setStyleSheet(f"color: {renk}; font-weight: 600;")
        self.feedback_label.setText(text)

    def reset(self) -> None:
        self.set_query("")
        self.feedback_label.setText("")
        self.search_now()


class KatmanSahibi:
    """Kasa sayfasının katman durum makinesi (aynı anda en çok bir katman).

    Sayfa ``_katman_baslat()`` çağırır ve ``_set_controls_enabled(bool)`` ile
    ``barcode`` sağlar. Okutmayı engelleyen katman bir askı JETONU tutar ve
    jeton katman kapanırken ``finally`` içinde bırakılır.
    """

    def _katman_baslat(self) -> None:
        self._overlay_state: str | None = None
        self._overlay = None
        self._overlay_token = None

    @property
    def overlay_state(self) -> str | None:
        return self._overlay_state

    def _open_overlay(self, state: str, overlay, block_scans: bool) -> None:
        self.close_overlay()
        self._overlay_state = state
        self._overlay = overlay
        if block_scans:
            self._overlay_token = self.main_window.router.suspend(
                f"kasa katmanı: {state}", overlay.notify_blocked
            )
        self._set_controls_enabled(False)
        overlay.cover(self)

    def close_overlay(self) -> bool:
        """Açık katmanı "vazgeç" anlamıyla kapatır; açık katman yoksa ``False``."""
        if self._overlay is None:
            return False
        katman = self._overlay
        try:
            katman.hide()
        finally:
            if self._overlay_token is not None:
                self.main_window.router.resume(self._overlay_token)
                self._overlay_token = None
            self._overlay = None
            self._overlay_state = None
            self._set_controls_enabled(True)
            self.barcode.setFocus()
        return True

    def _katman_boyutla(self) -> None:
        if self._overlay is not None:
            self._overlay.setGeometry(self.rect())
