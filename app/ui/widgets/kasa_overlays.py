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
            self.body.addWidget(self.keyboard, 0, Qt.AlignmentFlag.AlignHCenter)

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
            fiyat = format_tl(satir["sale_price"])
            # Ad solda, fiyat SAĞDA ve kalın: kasiyer fiyatı tek bakışta görür
            # (M12b ekran incelemesi). Etiketler tıklamayı düğmeye bırakır.
            dugme = QPushButton()
            dugme.setAccessibleName(f"{ad} {fiyat}")
            ic = QHBoxLayout(dugme)
            ic.setContentsMargins(14, 0, 14, 0)
            for metin, ad_nesne, esnek in ((ad, "searchName", 1), (fiyat, "searchPrice", 0)):
                etiket = make_label(metin, ad_nesne)
                etiket.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                ic.addWidget(etiket, esnek)
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


class TenderPanel(KasaOverlay):
    """F4 — Para Üstü: NAKİT'te alınan tutarı seç, para üstünü gör.

    Hızlı tutara dokunmak satışı o tutarla ONAYLAR (tek dokunuş). "Özel" ile
    tutar tuş takımından girilir. Alınan tutar toplamdan az olamaz. Tutar
    kaydedilmez; yalnızca para üstünü hesaplamak içindir.
    """

    confirmed = Signal(int)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Para Üstü", parent)
        from app.ui.widgets.touch_input import TouchNumpad

        self.close_button.setText("Vazgeç")
        self.close_requested.connect(self.cancelled.emit)
        self._toplam = 0
        self.quick_buttons: list[QPushButton] = []

        self.total_label = make_label("", "cartGrandTotal")
        self.body.addWidget(self.total_label)
        # Ne yapılacağı yazılır (M12b: panel boş görünüyordu).
        self.instruction_label = make_label(
            "Müşteriden alınan tutara dokunun: satış tamamlanır, para üstü gösterilir. "
            "Başka bir tutar için \"Özel tutar\".", "cardHint", wrap=True)
        self.body.addWidget(self.instruction_label)

        self.quick_row = QHBoxLayout()
        self.quick_row.setSpacing(8)
        self.body.addLayout(self.quick_row)
        self.custom_button = _dokunma_dugmesi("Özel tutar")
        self.custom_button.clicked.connect(self._ozel_ac)
        self.quick_row.addWidget(self.custom_button)

        self.custom_frame = QFrame()
        ozel = QHBoxLayout(self.custom_frame)
        ozel.setContentsMargins(0, 0, 0, 0)
        ozel.setSpacing(12)
        sol = QVBoxLayout()
        self.display = TouchDisplay("Alınan tutar (TL)", max_length=9)
        self.display.changed.connect(self._onizle)
        sol.addWidget(self.display)
        self.change_label = make_label("", "sectionTitle", wrap=True)
        sol.addWidget(self.change_label)
        self.custom_confirm_button = _dokunma_dugmesi("Satışı tamamla", "primary")
        self.custom_confirm_button.clicked.connect(self._ozel_onayla)
        sol.addWidget(self.custom_confirm_button)
        sol.addStretch(1)
        ozel.addLayout(sol, 1)
        self.numpad = TouchNumpad(allow_decimal=True, allow_double_zero=True)
        self.numpad.bind(self.display)
        ozel.addWidget(self.numpad)
        self.custom_frame.setVisible(False)
        self.body.addWidget(self.custom_frame, 1)
        self.body.addStretch(1)

    def prepare(self, toplam: int) -> None:
        """Yeni bir tahsilat için paneli kurar (hızlı tutarlar, temiz giriş)."""
        from app.core.money import nakit_hizli_tutarlar

        self._toplam = int(toplam)
        self.total_label.setText(f"Toplam: {format_tl(self._toplam)}")
        for dugme in self.quick_buttons:
            self.quick_row.removeWidget(dugme)
            dugme.deleteLater()
        self.quick_buttons = []
        for sira, tutar in enumerate(nakit_hizli_tutarlar(self._toplam)):
            tam = tutar == self._toplam
            metin = f"Tam {format_tl(tutar)}" if tam else format_tl(tutar)
            dugme = _dokunma_dugmesi(metin, "primary" if tam else "kasaTool")
            dugme.setProperty("tutar", tutar)
            dugme.setProperty("tutarDugmesi", "evet")      # büyük yazı (tema)
            dugme.clicked.connect(lambda _=False, t=tutar: self.confirmed.emit(t))
            self.quick_row.insertWidget(sira, dugme)
            self.quick_buttons.append(dugme)
        self.display.clear_value()
        self.change_label.setText("")
        self.custom_frame.setVisible(False)
        self.notice_label.setVisible(False)

    def _ozel_ac(self) -> None:
        self.custom_frame.setVisible(True)

    def _girilen(self) -> int | None:
        from app.core.money import tl_to_kurus

        metin = self.display.value()
        if not metin:
            return None
        try:
            return tl_to_kurus(metin)
        except Exception:
            return None

    def _onizle(self, _metin: str = "") -> None:
        tutar = self._girilen()
        if tutar is None:
            self.change_label.setText("")
        elif tutar < self._toplam:
            self.change_label.setText(
                f"Eksik: {format_tl(self._toplam - tutar)} — alınan tutar toplamdan az."
            )
        else:
            self.change_label.setText(f"Para üstü: {format_tl(tutar - self._toplam)}")

    def _ozel_onayla(self) -> None:
        tutar = self._girilen()
        if tutar is None or tutar < self._toplam:
            sound.error()
            self._onizle()
            if tutar is None:
                self.change_label.setText("Alınan tutarı girin.")
            return
        self.confirmed.emit(tutar)
