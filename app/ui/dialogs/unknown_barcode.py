"""Hızlı Ürün Ekle — tanınmayan barkod akışı (V1.2 M4b).

Kurallar (V1.1 şartname §16 + plan §7 M4b):
  * Tanınmayan barkod ASLA sessizce yok sayılmaz; adsız sahte ürün ASLA
    oluşturulmaz; satış, ürün açıkça KAYDEDİLENE ve fiyatı OLANA kadar olmaz.
  * Barkod daha önce kullanımdan kaldırılmış bir ürüne aitse ÖNCE o önerilir
    (yeniden kullanıma al) — çift ürün açtırılmaz (V1.1 kusuru D-08).
  * "Mevcut ürüne bağla": yeni ambalajın barkodu var olan ürüne alternatif /
    paket / koli barkodu olarak eklenir.
  * Form: barkod (okutarak doldurulabilir), ad, satış fiyatı ve ZORUNLU
    kategori (son kullanılanlar tek dokunuşla, arama, yerinde oluşturma).
    "Gelişmiş": marka, aile, etiketler, tedarikçi, KDV, barkod türü ve çarpanı,
    ek barkodlar, alış fiyatı, başlangıç stoğu (Mal Kabul'de gizli), konum.
  * Klavyesiz kasa: her alan dokunmatik klavye / tuş takımıyla doldurulur;
    klavyeli bilgisayarda fiziksel tuşlar da çalışır. Enter hiçbir şeyi
    onaylamaz; okuyucu hızındaki tuşlar alana yazılmaz.
  * Kaydedince çağıran ekran barkodu YENİDEN çözer: koli barkodu olarak
    tanımlanan ürün, kolideki adet kadar eklenir.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import DomainError
from app.core.models import BarcodeType
from app.core.money import format_tl, tl_to_kurus
from app.services.product_service import YeniUrun
from app.ui import metrics, sound, theme
from app.ui.dialogs.common_dialogs import BlockedScanNotice
from app.ui.widgets.common import make_label
from app.ui.widgets.touch_input import (
    TouchDialog,
    TouchDisplay,
    TouchKey,
    TouchKeyboard,
    TouchNumpad,
)

log = logging.getLogger(__name__)

#: Alan türleri: hangi tuş takımı gösterilir, hangi fiziksel tuş kabul edilir.
METIN, SAYI, TUTAR, BARKOD = "METIN", "SAYI", "TUTAR", "BARKOD"

#: Sonuç türleri.
SONUC_YENI = "YENI"
SONUC_BAGLANDI = "BAGLANDI"
SONUC_ACILDI = "ACILDI"

BAGLAM_SATIS = "SATIS"
BAGLAM_STOK = "STOK"


class TouchField(TouchDisplay):
    """Dokununca etkin olan değer alanı."""

    clicked = Signal()

    def __init__(self, kind: str, placeholder: str = "", max_length: int = 80) -> None:
        super().__init__(placeholder, max_length=max_length)
        self.kind = kind
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_active(False)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)

    def set_active(self, active: bool) -> None:
        self.setStyleSheet(
            f"#touchDisplay {{ border: 3px solid {theme.CART}; }}" if active else ""
        )


class UnknownBarcodeDialog(TouchDialog):
    """Tanınmayan barkod: yeniden kullanıma al / yeni ürün / mevcut ürüne bağla."""

    def __init__(self, barcode: str, services, parent: QWidget | None = None,
                 context: str = BAGLAM_SATIS) -> None:
        super().__init__("Ürün tanınmadı", parent)
        self.services = services
        self.barcode = barcode
        self.context = context
        self.product_id: int | None = None
        self.result_kind: str | None = None
        self.category_id: int | None = None
        self.extra_barcodes: list[tuple[str, str, int]] = []
        self._attach_product: int | None = None
        self._fields: list[TouchField] = []
        self.setMinimumWidth(min(940, metrics.MIN_WINDOW_WIDTH - 40))

        baslik = make_label("Ürün tanınmadı.", "sectionTitle")
        self.root.addWidget(baslik)
        self.barcode_label = make_label(f"Okutulan barkod: {barcode}", "cardHint")
        self.root.addWidget(self.barcode_label)
        self.blocked_notice = BlockedScanNotice(self)
        self.root.addWidget(self.blocked_notice)
        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet(f"color: {theme.DANGER}; font-weight: 600;")
        self.message_label.setVisible(False)
        self.root.addWidget(self.message_label)

        self.stages = QStackedWidget()
        self.root.addWidget(self.stages, 1)
        self.intro = self._build_intro()
        self.form = self._build_form()
        self.picker = self._build_picker()
        self.attach = self._build_attach()
        for sahne in (self.intro, self.form, self.picker, self.attach):
            self.stages.addWidget(sahne)

        self.keyboard = TouchKeyboard()
        self.numpad = TouchNumpad(allow_decimal=True, allow_double_zero=True)
        tus_alani = QHBoxLayout()
        tus_alani.addWidget(self.keyboard)
        tus_alani.addWidget(self.numpad)
        tus_alani.addStretch(1)
        self.keyboard.key_pressed.connect(self._ekle)
        self.keyboard.backspace_pressed.connect(self._sil)
        self.numpad.key_pressed.connect(self._ekle)
        self.numpad.backspace_pressed.connect(self._sil)
        self.numpad.clear_pressed.connect(self._temizle)
        self.root.addLayout(tus_alani)

        alt = QHBoxLayout()
        self.cancel_button = TouchKey("Vazgeç", width=160)
        self.cancel_button.clicked.connect(self.reject)
        alt.addWidget(self.cancel_button)
        alt.addStretch(1)
        self.save_button = TouchKey("Kaydet", width=220)
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self.save)
        alt.addWidget(self.save_button)
        self.root.addLayout(alt)
        self.show_stage(self.intro)

    # ===================== Ortak ==========================================
    def _alan(self, kind: str, placeholder: str, max_length: int = 80) -> TouchField:
        alan = TouchField(kind, placeholder, max_length)
        alan.clicked.connect(lambda a=alan: self.activate(a))
        self._fields.append(alan)
        return alan

    def activate(self, alan: TouchField | None) -> None:
        for diger in self._fields:
            diger.set_active(diger is alan)
        self.display = alan
        metin = alan is not None and alan.kind == METIN
        sayi = alan is not None and alan.kind in (SAYI, TUTAR, BARKOD)
        self.keyboard.setVisible(metin)
        self.numpad.setVisible(sayi)
        if alan is not None and alan.kind in (SAYI, TUTAR, BARKOD):
            self.numpad.keys[","].setVisible(alan.kind == TUTAR)
            self.numpad.keys["00"].setVisible(alan.kind != BARKOD)

    def _ekle(self, metin: str) -> None:
        if self.display is not None:
            self.display.insert(metin)

    def _sil(self) -> None:
        if self.display is not None:
            self.display.backspace()

    def _temizle(self) -> None:
        if self.display is not None:
            self.display.clear_value()

    def accepts_physical(self, metin: str) -> bool:
        alan = self.display
        if alan is None:
            return False
        if alan.kind == METIN:
            return True
        if alan.kind == TUTAR:
            return metin.isdigit() or metin in ",."
        return metin.isdigit() if alan.kind == SAYI else metin.isalnum()

    def show_stage(self, sahne: QWidget) -> None:
        self.stages.setCurrentWidget(sahne)
        self.save_button.setVisible(sahne in (self.form, self.attach))
        self.save_button.setText("Bağla" if sahne is self.attach else "Kaydet")
        ilk = {
            self.form: self.name_field, self.picker: self.picker_field,
            self.attach: self.attach_field,
        }.get(sahne)
        self.activate(ilk)

    def notify_blocked(self, event=None) -> None:
        """Pencere açıkken okutma: barkod alanı etkinse oraya YAZILIR."""
        if event is not None and self.display is not None and self.display.kind == BARKOD:
            self.display.set_value(event.code)
            sound.scan()
            return
        self.blocked_notice.show_blocked()

    def _hata(self, metin: str) -> None:
        sound.error()
        self.message_label.setText(metin)
        self.message_label.setVisible(True)

    # ===================== Giriş ==========================================
    def _build_intro(self) -> QWidget:
        sahne = QWidget()
        duzen = QVBoxLayout(sahne)
        self.owner = self.services.barcodes.inactive_owner(self.barcode)
        self.reactivate_button = TouchKey("", width=520)
        self.reactivate_button.setObjectName("primary")
        self.reactivate_button.clicked.connect(self.reactivate_owner)
        if self.owner is not None:
            duzen.addWidget(make_label(
                f"Bu barkod kullanımdan kaldırılmış \"{self.owner['name']}\" ürününe ait. "
                "Yeni ürün açmak yerine o ürünü yeniden kullanıma alabilirsiniz.",
                wrap=True,
            ))
            self.reactivate_button.setText(f"\"{self.owner['name']}\" ürününü geri al")
            duzen.addWidget(self.reactivate_button)
        else:
            self.reactivate_button.setVisible(False)
        dugmeler = QHBoxLayout()
        self.define_button = TouchKey("Yeni ürün tanımla", width=260)
        self.define_button.setObjectName("primary" if self.owner is None else "touchKey")
        self.define_button.clicked.connect(lambda: self.show_stage(self.form))
        dugmeler.addWidget(self.define_button)
        self.attach_button = TouchKey("Mevcut ürüne bağla", width=260)
        self.attach_button.clicked.connect(lambda: self.show_stage(self.attach))
        dugmeler.addWidget(self.attach_button)
        dugmeler.addStretch(1)
        duzen.addLayout(dugmeler)
        duzen.addStretch(1)
        return sahne

    def reactivate_owner(self) -> None:
        if self.owner is None:
            return
        try:
            sonuc = self.services.products.reactivate(self.owner["product_id"])
        except DomainError as hata:
            self._hata(hata.message)
            return
        if sonuc.acilamayan_barkodlar:
            log.info("Geri açılamayan barkodlar: %s", sonuc.acilamayan_barkodlar)
        self.product_id = int(self.owner["product_id"])
        self.result_kind = SONUC_ACILDI
        self.accept()

    # ===================== Form ===========================================
    def _satir(self, izgara: QGridLayout, sira: int, etiket: str, gerec: QWidget) -> None:
        izgara.addWidget(make_label(etiket), sira, 0)
        izgara.addWidget(gerec, sira, 1)

    def _build_form(self) -> QWidget:
        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        icerik = QWidget()
        dikey = QVBoxLayout(icerik)
        izgara = QGridLayout()
        izgara.setColumnStretch(1, 1)
        self.barcode_field = self._alan(BARKOD, "Barkodu okutun ya da yazın", 32)
        self.barcode_field.set_value(self.barcode or "")
        self.name_field = self._alan(METIN, "Örnek: Tuborg Gold 50 cl Kutu", 120)
        self.price_field = self._alan(TUTAR, "Örnek: 80", 12)
        self._satir(izgara, 0, "Barkod", self.barcode_field)
        self._satir(izgara, 1, "Ürün adı", self.name_field)
        self._satir(izgara, 2, "Satış fiyatı (TL)", self.price_field)
        dikey.addLayout(izgara)

        dikey.addWidget(make_label("Kategori (zorunlu)", "cardTitle"))
        cipler = QHBoxLayout()
        self.category_chips: list[QPushButton] = []
        for satir in self.services.categories.recent_for_products(5):
            cip = TouchKey(self.services.categories.path(satir["id"]), width=200)
            cip.setCheckable(True)
            cip.setProperty("category_id", int(satir["id"]))
            cip.clicked.connect(lambda _=False, k=int(satir["id"]): self.set_category(k))
            cipler.addWidget(cip)
            self.category_chips.append(cip)
        self.choose_category_button = TouchKey("Kategori seç…", width=200)
        self.choose_category_button.clicked.connect(lambda: self.show_stage(self.picker))
        cipler.addWidget(self.choose_category_button)
        cipler.addStretch(1)
        dikey.addLayout(cipler)
        self.category_label = make_label("Kategori seçilmedi.", "cardHint")
        dikey.addWidget(self.category_label)

        self.advanced_button = TouchKey("Gelişmiş ▸", width=200)
        self.advanced_button.setCheckable(True)
        self.advanced_button.toggled.connect(self._gelismis_ac)
        dikey.addWidget(self.advanced_button)
        self.advanced = QFrame()
        gizli = QGridLayout(self.advanced)
        gizli.setColumnStretch(1, 1)
        self.brand_field = self._alan(METIN, "Örnek: Tuborg", 60)
        self.family_field = self._alan(METIN, "Örnek: Gold", 60)
        self.tags_field = self._alan(METIN, "virgülle ayırın: soğuk, kutu", 120)
        self.supplier_combo = QComboBox()
        self.supplier_combo.addItem("Seçilmedi", None)
        for tedarikci in self.services.suppliers.all():
            self.supplier_combo.addItem(tedarikci["name"], tedarikci["id"])
        self.vat_field = self._alan(SAYI, "Örnek: 20", 3)
        self.barcode_type_combo = QComboBox()
        for etiket, deger in (("Adet barkodu", BarcodeType.UNIT),
                              ("Paket barkodu", BarcodeType.PACK),
                              ("Koli barkodu", BarcodeType.CASE)):
            self.barcode_type_combo.addItem(etiket, deger)
        self.multiplier_field = self._alan(SAYI, "Paket/koli içi adet", 4)
        self.extra_field = self._alan(BARKOD, "Ek (alternatif) barkod", 32)
        self.extra_add_button = TouchKey("Ekle", width=110)
        self.extra_add_button.clicked.connect(self.add_extra_barcode)
        ek = QHBoxLayout()
        ek.addWidget(self.extra_field, 1)
        ek.addWidget(self.extra_add_button)
        ek_kap = QWidget()
        ek_kap.setLayout(ek)
        self.extra_list_label = make_label("", "cardHint", wrap=True)
        self.cost_field = self._alan(TUTAR, "Alış fiyatı (biliniyorsa)", 12)
        self.stock_field = self._alan(SAYI, "Boş bırakılırsa 'henüz sayılmadı'", 6)
        self.location_combo = QComboBox()
        self.location_combo.addItem("Seçilmedi", None)
        for konum in self.services.catalog.locations():
            self.location_combo.addItem(konum["name"], konum["id"])
        satirlar = [
            ("Marka", self.brand_field), ("Ürün ailesi", self.family_field),
            ("Etiketler", self.tags_field), ("Tedarikçi", self.supplier_combo),
            ("KDV (%)", self.vat_field), ("Okutulan barkod türü", self.barcode_type_combo),
            ("Paket/koli adedi", self.multiplier_field), ("Ek barkod", ek_kap),
            ("", self.extra_list_label), ("Alış fiyatı (TL)", self.cost_field),
            ("Başlangıç stoğu", self.stock_field), ("Konum", self.location_combo),
        ]
        for sira, (etiket, gerec) in enumerate(satirlar):
            self._satir(gizli, sira, etiket, gerec)
        if self.context == BAGLAM_STOK:
            # Mal Kabul / Hızlı Stok'ta stok girişin kendisiyle gelir.
            self.stock_field.setVisible(False)
            gizli.itemAtPosition(10, 0).widget().setVisible(False)
        self.advanced.setVisible(False)
        dikey.addWidget(self.advanced)
        dikey.addStretch(1)
        kaydirma.setWidget(icerik)
        return kaydirma

    def _gelismis_ac(self, acik: bool) -> None:
        self.advanced.setVisible(acik)
        self.advanced_button.setText("Gelişmiş ▾" if acik else "Gelişmiş ▸")

    def set_category(self, category_id: int) -> None:
        self.category_id = category_id
        for cip in self.category_chips:
            cip.setChecked(cip.property("category_id") == category_id)
        self.category_label.setText(
            f"Kategori: {self.services.categories.path(category_id)}"
        )
        self.category_label.setStyleSheet("")

    def add_extra_barcode(self) -> None:
        deger = self.extra_field.value().strip()
        if not deger:
            return
        self.extra_barcodes.append((deger, BarcodeType.ALTERNATE, 1))
        self.extra_field.clear_value()
        self.extra_list_label.setText(
            "Ek barkodlar: " + ", ".join(b for b, _, _ in self.extra_barcodes)
        )

    # ===================== Kategori seçici ================================
    def _build_picker(self) -> QWidget:
        sahne = QWidget()
        duzen = QVBoxLayout(sahne)
        ust = QHBoxLayout()
        self.picker_field = self._alan(METIN, "Kategori ara ya da yeni ad yazın", 60)
        self.picker_field.changed.connect(lambda _m: self.refresh_picker())
        ust.addWidget(self.picker_field, 1)
        geri = TouchKey("◀ Forma dön", width=170)
        geri.clicked.connect(lambda: self.show_stage(self.form))
        ust.addWidget(geri)
        duzen.addLayout(ust)
        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        icerik = QWidget()
        self.picker_layout = QVBoxLayout(icerik)
        self.picker_layout.setSpacing(6)
        self.picker_layout.addStretch(1)
        kaydirma.setWidget(icerik)
        duzen.addWidget(kaydirma, 1)
        self.picker_buttons: list[QPushButton] = []
        self.refresh_picker()
        return sahne

    def refresh_picker(self) -> None:
        for dugme in self.picker_buttons:
            self.picker_layout.removeWidget(dugme)
            dugme.deleteLater()
        self.picker_buttons = []
        metin = self.picker_field.value().strip()
        if metin:
            sonuclar = self.services.categories.search(metin)
        else:
            sonuclar = [
                (alt.row, f"{d.name} > {alt.name}")
                for d in self.services.categories.tree() for alt in d.altlar
            ]
        for sira, (satir, yol) in enumerate(sonuclar[:40]):
            dugme = TouchKey(yol, width=520)
            dugme.setProperty("category_id", int(satir["id"]))
            dugme.clicked.connect(lambda _=False, k=int(satir["id"]): self._kategori_secildi(k))
            self.picker_layout.insertWidget(sira, dugme)
            self.picker_buttons.append(dugme)
        if metin:
            for ust in self.services.categories.tree():
                dugme = TouchKey(f"＋ \"{metin}\" kategorisini {ust.name} altında oluştur",
                                 width=520)
                dugme.setProperty("create_parent", ust.id)
                dugme.clicked.connect(
                    lambda _=False, u=ust.id, a=metin: self.create_category(a, u)
                )
                self.picker_layout.insertWidget(len(self.picker_buttons), dugme)
                self.picker_buttons.append(dugme)

    def _kategori_secildi(self, category_id: int) -> None:
        self.set_category(category_id)
        self.show_stage(self.form)

    def create_category(self, ad: str, parent_id: int | None) -> None:
        uyarilar = self.services.categories.similar_names(ad, parent_id)
        try:
            kimlik = self.services.categories.create(ad, parent_id)
        except DomainError as hata:
            self._hata(hata.message)
            return
        if uyarilar:
            log.info("Benzer kategori uyarısıyla oluşturuldu: %s — %s", ad, uyarilar)
        self._kategori_secildi(kimlik)

    # ===================== Mevcut ürüne bağla ==============================
    def _build_attach(self) -> QWidget:
        sahne = QWidget()
        duzen = QVBoxLayout(sahne)
        ust = QHBoxLayout()
        self.attach_field = self._alan(METIN, "Bağlanacak ürünü arayın", 60)
        self.attach_field.changed.connect(lambda _m: self.refresh_attach())
        ust.addWidget(self.attach_field, 1)
        geri = TouchKey("◀ Geri", width=140)
        geri.clicked.connect(lambda: self.show_stage(self.intro))
        ust.addWidget(geri)
        duzen.addLayout(ust)
        self.attach_selected_label = make_label("Ürün seçilmedi.", "cardHint")
        duzen.addWidget(self.attach_selected_label)
        turler = QHBoxLayout()
        self.attach_type_buttons: dict[str, QPushButton] = {}
        for etiket, deger in (("Alternatif barkod", BarcodeType.ALTERNATE),
                              ("Paket", BarcodeType.PACK), ("Koli", BarcodeType.CASE)):
            dugme = TouchKey(etiket, width=190)
            dugme.setCheckable(True)
            dugme.clicked.connect(lambda _=False, d=deger: self.set_attach_type(d))
            turler.addWidget(dugme)
            self.attach_type_buttons[deger] = dugme
        self.attach_multiplier_field = self._alan(SAYI, "Adet", 4)
        turler.addWidget(self.attach_multiplier_field)
        duzen.addLayout(turler)
        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        icerik = QWidget()
        self.attach_layout = QVBoxLayout(icerik)
        self.attach_layout.addStretch(1)
        kaydirma.setWidget(icerik)
        duzen.addWidget(kaydirma, 1)
        self.attach_buttons: list[QPushButton] = []
        self.set_attach_type(BarcodeType.ALTERNATE)
        return sahne

    def set_attach_type(self, deger: str) -> None:
        self.attach_type = deger
        for anahtar, dugme in self.attach_type_buttons.items():
            dugme.setChecked(anahtar == deger)
        self.attach_multiplier_field.setVisible(deger != BarcodeType.ALTERNATE)

    def refresh_attach(self) -> None:
        for dugme in self.attach_buttons:
            self.attach_layout.removeWidget(dugme)
            dugme.deleteLater()
        self.attach_buttons = []
        metin = self.attach_field.value().strip()
        if not metin:
            return
        for sira, satir in enumerate(self.services.products.search(metin, limit=20)):
            fiyat = format_tl(satir["sale_price"]) if satir["sale_price"] is not None else "-"
            dugme = TouchKey(f"{satir['name']}    {fiyat}", width=560)
            dugme.setProperty("product_id", int(satir["id"]))
            dugme.clicked.connect(lambda _=False, k=int(satir["id"]): self.select_attach(k))
            self.attach_layout.insertWidget(sira, dugme)
            self.attach_buttons.append(dugme)

    def select_attach(self, product_id: int) -> None:
        self._attach_product = product_id
        self.attach_selected_label.setText(
            f"Seçilen ürün: {self.services.products.get(product_id)['name']}"
        )

    # ===================== Kaydet =========================================
    def save(self) -> None:
        if self.stages.currentWidget() is self.attach:
            self._bagla()
        else:
            self._kaydet()

    @staticmethod
    def _tam_sayi(alan: TouchField, ad: str) -> int | None:
        metin = alan.value().strip()
        if not metin:
            return None
        if not metin.isdigit():
            raise DomainError(f"{ad} bir sayı olmalıdır.")
        return int(metin)

    def _kaydet(self) -> None:
        self.message_label.setVisible(False)
        try:
            fiyat_metni = self.price_field.value().strip()
            if not fiyat_metni:
                raise DomainError("Satış fiyatını girin.")
            fiyat = tl_to_kurus(fiyat_metni)
            maliyet = (tl_to_kurus(self.cost_field.value())
                       if self.cost_field.value().strip() else None)
            stok = self._tam_sayi(self.stock_field, "Başlangıç stoğu")
            kdv = self._tam_sayi(self.vat_field, "KDV")
            tur = self.barcode_type_combo.currentData()
            carpan = self._tam_sayi(self.multiplier_field, "Paket/koli adedi") or 1
            if tur != BarcodeType.UNIT and carpan < 2:
                raise DomainError("Paket/koli barkodu için içindeki adedi girin (en az 2).")
            if self.context == BAGLAM_STOK:
                stok = None
            taslak = YeniUrun(
                name=self.name_field.value(),
                sale_price=fiyat,
                category_id=self.category_id,
                barcode=self.barcode_field.value().strip() or None,
                barcode_type=tur,
                multiplier=carpan if tur != BarcodeType.UNIT else 1,
                extra_barcodes=list(self.extra_barcodes),
                brand_name=self.brand_field.value().strip() or None,
                family_name=self.family_field.value().strip() or None,
                tags=[t.strip() for t in self.tags_field.value().split(",") if t.strip()],
                supplier_id=self.supplier_combo.currentData(),
                vat_rate=kdv,
                initial_stock=stok,
                initial_cost=maliyet,
                location_id=self.location_combo.currentData(),
            )
            self.product_id = self.services.products.add_product(taslak)
        except DomainError as hata:
            if hata.detail:
                log.info("Ürün kaydedilemedi: %s | %s", hata.message, hata.detail)
            self._hata(hata.message)
            if self.category_id is None:
                self.category_label.setStyleSheet(f"color: {theme.DANGER};")
            return
        self.result_kind = SONUC_YENI
        self.accept()

    def _bagla(self) -> None:
        self.message_label.setVisible(False)
        if self._attach_product is None:
            self._hata("Önce barkodun bağlanacağı ürünü seçin.")
            return
        try:
            carpan = 1
            if self.attach_type != BarcodeType.ALTERNATE:
                carpan = self._tam_sayi(self.attach_multiplier_field, "Adet") or 0
                if carpan < 2:
                    raise DomainError("Paket/koli içindeki adedi girin (en az 2).")
            self.services.barcodes.add_barcode(
                self._attach_product, self.barcode, self.attach_type, carpan
            )
        except DomainError as hata:
            self._hata(hata.message)
            return
        self.product_id = self._attach_product
        self.result_kind = SONUC_BAGLANDI
        self.accept()

    @staticmethod
    def run(barcode: str, services, parent: QWidget | None = None) -> int | None:
        """Ürün tanımlandıysa / bağlandıysa / geri açıldıysa kimliğini döner."""
        pencere = UnknownBarcodeDialog(barcode, services, parent)
        if pencere.exec() == QDialog.DialogCode.Accepted:
            return pencere.product_id
        return None
