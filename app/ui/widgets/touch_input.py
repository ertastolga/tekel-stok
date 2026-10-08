"""Dokunmatik giriş takımı: sayı tuş takımı, Türkçe Q klavye, güvenli alanlar.

Hedef cihaz KLAVYESİZ bir dokunmatik terminaldir (AVAPOS 15,6"): kasiyer ürün
adı, fiyat, PIN, tutar ya da arama metnini yalnızca ekrandaki tuşlarla
girebilir. Windows dokunmatik klavyesine güvenilmez (doğrulanamaz).

Kurallar
--------
* Tüm tuşlar en az ``metrics.TOUCH_TARGET_MIN`` (56 px) ve ODAK ALMAZ: barkod
  okuyucunun hedefi değişmez, tuşa dokunmak bir alanın odağını çalmaz.
* Değer gösterimi (``TouchDisplay``) odak almaz; yazı yalnızca tuşlardan ya da
  pencerenin süzdüğü fiziksel tuşlardan gelir.
* Dokunmatik pencerelerde (``TouchDialog``) varsayılan düğme YOKTUR ve
  Enter/Return yutulur: bir barkod okuyucunun sonlandırıcısı (Enter) ya da
  kazara bir tuş bir şeyi ONAYLAYAMAZ. Onay yalnızca açık dokunuşla olur.
* Makine hızında (okuyucu) gelen fiziksel tuşlar değere YAZILMAZ: dizinin
  ilk karakteri dahil geri alınır.
* ``ScanSafeLineEdit``: fiziksel klavyeyle yazılan alanlar için. Odaktayken bir
  okutma gelirse, okutmanın alana düşen karakterleri geri alınır.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core import clock
from app.core.tr import tr_upper
from app.scanner import scanner_service
from app.ui import metrics

#: Tuşlar arası boşluk (px). 12 tuşluk satır: 12×56 + 11×4 = 716 px ≤ 736.
TUS_ARALIGI = 4
#: Klavyenin en geniş satırının sığması gereken genişlik (1000 px pencerede
#: menü ve kenar boşlukları düşüldükten sonra kalan alan).
KLAVYE_AZAMI_GENISLIK = 736

HARF_SATIRLARI = ("1234567890", "qwertyuıopğü", "asdfghjklşi", "zxcvbnmöç.")
SEMBOL_SATIRI = ("-", "/", "'", ",", "%", "&", "+", "(", ")", "*", ":")


def _burst_esigi_ms() -> float:
    """Okuyucu dizisi eşiği — ÇAĞRI ANINDA okunur (M9c ayarı değiştirebilir)."""
    return float(scanner_service.BURST_KEY_MS)


class TouchKey(QPushButton):
    """Odak almayan, varsayılan olamayan, en az 56 px'lik tuş."""

    def __init__(self, text: str, parent: QWidget | None = None, width: int | None = None):
        super().__init__(text, parent)
        self.setObjectName("touchKey")
        self.setProperty("dokunma", "evet")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoDefault(False)
        self.setDefault(False)
        self.setMinimumSize(width or metrics.TOUCH_TARGET_MIN, metrics.TOUCH_TARGET_MIN)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(width or metrics.TOUCH_TARGET_MIN, metrics.TOUCH_TARGET_MIN)


class TouchDisplay(QLabel):
    """Girilen değerin odak almayan, büyük gösterimi."""

    changed = Signal(str)

    def __init__(
        self,
        placeholder: str = "",
        max_length: int = 64,
        masked: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("touchDisplay")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
        self.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._value = ""
        self._placeholder = placeholder
        self._max = max_length
        self._masked = masked
        self._render()

    # -- Değer --------------------------------------------------------------
    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        self._value = (value or "")[: self._max]
        self._render()
        self.changed.emit(self._value)

    def insert(self, text: str) -> None:
        if len(self._value) + len(text) > self._max:
            return
        self.set_value(self._value + text)

    def backspace(self) -> None:
        if self._value:
            self.set_value(self._value[:-1])

    def clear_value(self) -> None:
        self.set_value("")

    def _render(self) -> None:
        if not self._value:
            self.setText(self._placeholder)
            self.setProperty("bos", "evet")
        else:
            self.setText("●" * len(self._value) if self._masked else self._value)
            self.setProperty("bos", "hayir")


class TouchNumpad(QWidget):
    """0–9, 00, virgül, ⌫ ve Temizle."""

    key_pressed = Signal(str)
    backspace_pressed = Signal()
    clear_pressed = Signal()

    def __init__(
        self,
        allow_decimal: bool = True,
        allow_double_zero: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("touchNumpad")
        izgara = QGridLayout(self)
        izgara.setContentsMargins(0, 0, 0, 0)
        izgara.setSpacing(TUS_ARALIGI)
        self.keys: dict[str, TouchKey] = {}

        duzen = [
            ("7", 0, 0), ("8", 0, 1), ("9", 0, 2),
            ("4", 1, 0), ("5", 1, 1), ("6", 1, 2),
            ("1", 2, 0), ("2", 2, 1), ("3", 2, 2),
            ("00", 3, 0), ("0", 3, 1), (",", 3, 2),
        ]
        for metin, satir, sutun in duzen:
            tus = TouchKey(metin)
            tus.clicked.connect(lambda _=False, m=metin: self.key_pressed.emit(m))
            izgara.addWidget(tus, satir, sutun)
            self.keys[metin] = tus
        self.keys["00"].setVisible(allow_double_zero)
        self.keys[","].setVisible(allow_decimal)

        self.backspace_key = TouchKey("⌫")
        self.backspace_key.clicked.connect(self.backspace_pressed.emit)
        izgara.addWidget(self.backspace_key, 0, 3)
        self.clear_key = TouchKey("Temizle", width=metrics.TOUCH_TARGET_MIN + 40)
        self.clear_key.clicked.connect(self.clear_pressed.emit)
        izgara.addWidget(self.clear_key, 1, 3)

    def bind(self, display: TouchDisplay) -> None:
        """Tuş takımını bir gösterime bağlar."""
        self.key_pressed.connect(display.insert)
        self.backspace_pressed.connect(display.backspace)
        self.clear_pressed.connect(display.clear_value)


class TouchKeyboard(QWidget):
    """Türkçe Q dokunmatik klavye (+ sembol katmanı, büyük harf, boşluk)."""

    key_pressed = Signal(str)
    backspace_pressed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("touchKeyboard")
        self._buyuk = False
        self._sembol = False
        dikey = QVBoxLayout(self)
        dikey.setContentsMargins(0, 0, 0, 0)
        dikey.setSpacing(TUS_ARALIGI)

        self.letter_keys: list[TouchKey] = []
        self._harf_satirlari: list[QWidget] = []
        for satir_metni in HARF_SATIRLARI:
            satir = self._satir([c for c in satir_metni])
            dikey.addWidget(satir)
            if satir_metni != HARF_SATIRLARI[0]:
                self._harf_satirlari.append(satir)

        self.symbol_row = self._satir(list(SEMBOL_SATIRI))
        self.symbol_row.setVisible(False)
        dikey.addWidget(self.symbol_row)

        alt = QWidget()
        yatay = QHBoxLayout(alt)
        yatay.setContentsMargins(0, 0, 0, 0)
        yatay.setSpacing(TUS_ARALIGI)
        self.shift_key = TouchKey("Büyük harf", width=150)
        self.shift_key.setCheckable(True)
        self.shift_key.toggled.connect(self._set_buyuk)
        self.symbol_key = TouchKey("Sembol", width=110)
        self.symbol_key.setCheckable(True)
        self.symbol_key.toggled.connect(self._set_sembol)
        self.space_key = TouchKey("Boşluk", width=300)
        self.space_key.clicked.connect(lambda: self.key_pressed.emit(" "))
        self.backspace_key = TouchKey("⌫", width=110)
        self.backspace_key.clicked.connect(self.backspace_pressed.emit)
        for tus in (self.shift_key, self.symbol_key, self.space_key, self.backspace_key):
            yatay.addWidget(tus)
        yatay.addStretch(1)
        dikey.addWidget(alt)

    def _satir(self, karakterler: list[str]) -> QWidget:
        satir = QWidget()
        yatay = QHBoxLayout(satir)
        yatay.setContentsMargins(0, 0, 0, 0)
        yatay.setSpacing(TUS_ARALIGI)
        for karakter in karakterler:
            tus = TouchKey(karakter)
            tus.setProperty("karakter", karakter)
            tus.clicked.connect(lambda _=False, t=tus: self._bas(t))
            yatay.addWidget(tus)
            self.letter_keys.append(tus)
        yatay.addStretch(1)
        return satir

    def _bas(self, tus: TouchKey) -> None:
        self.key_pressed.emit(tus.text())

    def _set_buyuk(self, acik: bool) -> None:
        self._buyuk = acik
        for tus in self.letter_keys:
            karakter = tus.property("karakter")
            # Türkçe büyük harf: i → İ, ı → I (``tr_upper``).
            tus.setText(tr_upper(karakter) if acik else karakter)

    def _set_sembol(self, acik: bool) -> None:
        self._sembol = acik
        for satir in self._harf_satirlari:
            satir.setVisible(not acik)
        self.symbol_row.setVisible(acik)

    def key(self, karakter: str) -> TouchKey:
        """Testler ve yardım için: küçük harf karakterinin tuşu."""
        for tus in self.letter_keys:
            if tus.property("karakter") == karakter:
                return tus
        raise KeyError(karakter)

    def bind(self, display: TouchDisplay) -> None:
        self.key_pressed.connect(display.insert)
        self.backspace_pressed.connect(display.backspace)


class _BurstSuzgeci:
    """Fiziksel tuş akışında okuyucu (makine hızı) dizisini ayırt eder.

    Yavaş bir aradan sonra gelen her tuştan ÖNCE değerin anlık görüntüsü
    alınır. Ardından eşikten hızlı bir tuş gelirse bu bir okuyucu dizisidir:
    değer o anlık görüntüye döner ve dizi bitene kadar tuşlar yok sayılır.
    """

    def __init__(self) -> None:
        self._son_ms: float | None = None
        self._goruntu = None
        self.burst = False

    def tus_oncesi(self, goruntu) -> bool:
        """Tuş işlenmeden ÖNCE çağrılır; ``False`` = tuşu yok say."""
        simdi = clock.monotonic() * 1000.0
        aralik = float("inf") if self._son_ms is None else simdi - self._son_ms
        self._son_ms = simdi
        if aralik <= _burst_esigi_ms():
            self.burst = True
            return False
        self.burst = False
        self._goruntu = goruntu
        return True

    def geri_alinacak(self):
        """Dizi başladıysa dönülecek anlık görüntü (yoksa ``None``)."""
        return self._goruntu if self.burst else None


class TouchDialog(QDialog):
    """Dokunmatik pencere tabanı: varsayılan düğme yok, Enter onaylamaz.

    Alt sınıflar ``display`` (``TouchDisplay``) ve tuş takımını kurar; onay
    yalnızca ``accept_button`` dokunuşuyla olur.
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setObjectName("touchDialog")
        self.display: TouchDisplay | None = None
        self._suzgec = _BurstSuzgeci()
        self.root = QVBoxLayout(self)
        self.root.setSpacing(10)

    def add_buttons(
        self, accept_text: str = "Tamam", reject_text: str = "Vazgeç", on_accept=None
    ) -> None:
        """Vazgeç / onay düğmeleri. ``on_accept`` verilirse onay düğmesi pencereyi
        doğrudan kabul etmez; doğrulamayı yapan o işlev kabul eder."""
        satir = QHBoxLayout()
        self.reject_button = TouchKey(reject_text, width=160)
        self.reject_button.clicked.connect(self.reject)
        self.accept_button = TouchKey(accept_text, width=200)
        self.accept_button.setObjectName("primary")
        self.accept_button.clicked.connect(on_accept or self.accept)
        satir.addWidget(self.reject_button)
        satir.addStretch(1)
        satir.addWidget(self.accept_button)
        self.root.addLayout(satir)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        anahtar = event.key()
        if anahtar in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            event.accept()                 # okuyucu sonlandırıcısı / kaza: YUTULUR
            return
        if anahtar == Qt.Key.Key_Escape:
            super().keyPressEvent(event)
            return
        if self.display is None:
            event.accept()
            return
        if anahtar == Qt.Key.Key_Backspace:
            self.display.backspace()
            event.accept()
            return
        metin = event.text()
        if metin and metin.isprintable() and self.accepts_physical(metin):
            if self._suzgec.tus_oncesi(self.display.value()):
                self.display.insert(metin)
            else:
                geri = self._suzgec.geri_alinacak()
                if geri is not None and self.display.value() != geri:
                    self.display.set_value(geri)
        event.accept()

    def accepts_physical(self, metin: str) -> bool:
        """Fiziksel klavyeden hangi karakterler kabul edilir (alt sınıf daraltır)."""
        return True

    def value(self) -> str:
        return self.display.value() if self.display is not None else ""


class TouchTextDialog(TouchDialog):
    """Dokunmatik metin girişi (ürün adı, arama...)."""

    def __init__(
        self,
        title: str,
        initial: str = "",
        placeholder: str = "",
        max_length: int = 120,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, parent)
        self.display = TouchDisplay(placeholder, max_length=max_length)
        self.display.set_value(initial)
        self.root.addWidget(self.display)
        self.keyboard = TouchKeyboard()
        self.keyboard.bind(self.display)
        self.root.addWidget(self.keyboard)
        self.add_buttons()


class TouchAmountDialog(TouchDialog):
    """Dokunmatik tutar / sayı girişi."""

    def __init__(
        self,
        title: str,
        initial: str = "",
        allow_decimal: bool = True,
        max_length: int = 12,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, parent)
        self._ondalik = allow_decimal
        self.display = TouchDisplay("0", max_length=max_length)
        self.display.set_value(initial)
        self.root.addWidget(self.display)
        self.numpad = TouchNumpad(allow_decimal=allow_decimal)
        self.numpad.bind(self.display)
        self.root.addWidget(self.numpad)
        self.add_buttons()

    def accepts_physical(self, metin: str) -> bool:
        return metin.isdigit() or (self._ondalik and metin in ",.")


class ScanSafeLineEdit(QLineEdit):
    """Fiziksel klavye alanı: odaktayken gelen okutma metni BOZMAZ.

    Okuyucu klavye gibi yazar; odaktaki bir arama/ad alanına barkod
    karakterleri düşer (sonlandırıcıyı ``ScannerService`` yutar ve okutmayı
    ayrıca yayınlar). Bu alan, yavaş bir aradan sonra gelen her tuştan önce
    metnin anlık görüntüsünü alır; odaktayken bir okutma yayınlanırsa ve
    alana makine hızında karakter düştüyse görüntüye döner.
    """

    #: Bir okutma alanın metnini geri aldığında yayınlanır (bilgi amaçlı).
    scan_reverted = Signal(object)

    def __init__(self, parent: QWidget | None = None, scanner=None) -> None:
        super().__init__(parent)
        self._suzgec = _BurstSuzgeci()
        self._scanner = None
        if scanner is not None:
            self.attach_scanner(scanner)

    def attach_scanner(self, scanner) -> None:
        if self._scanner is scanner:
            return
        if self._scanner is not None:
            try:
                self._scanner.scanned.disconnect(self._okutma_geldi)
            except (RuntimeError, TypeError):
                pass
        self._scanner = scanner
        scanner.scanned.connect(self._okutma_geldi)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        metin = event.text()
        if metin and metin.isprintable():
            if not self._suzgec.tus_oncesi((self.text(), self.cursorPosition())):
                # Makine hızındaki karakter de alana yazılır (okuyucu Enter
                # göndermezse insan yazımı olabilir); okutma yayınlanırsa geri
                # alınır.
                pass
        super().keyPressEvent(event)

    def _okutma_geldi(self, event) -> None:
        if not self.hasFocus():
            return
        geri = self._suzgec.geri_alinacak()
        if geri is None:
            return
        metin, imlec = geri
        self.setText(metin)
        self.setCursorPosition(imlec)
        self._suzgec.burst = False
        self.scan_reverted.emit(event)
