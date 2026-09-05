"""Ürün tanımlama / düzenleme penceresi.

İlk kurulumda ZORUNLU alan azdır: ad ve fiyat yeter. Tedarikçi, aile, etiket,
asgari stok gibi alanlar SORULMAZ; eksik kalanlar "Eksik Bilgiler" listesinde
sonradan tamamlanır.

"Benzer Üründen Oluştur" marka, kategori, birim ve rafları kopyalar; barkod,
ad ve fiyat kopyalanmaz — onlar ürünü ayıran şeylerdir.
"""
from __future__ import annotations

import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import DomainError
from app.core.models import BARCODE_TYPE_LABELS, BarcodeType
from app.core.money import kurus_to_tl_text, tl_to_kurus
from app.ui import metrics, theme
from app.ui.dialogs.common_dialogs import ask_confirm, show_error

log = logging.getLogger(__name__)

MODE_CREATE = "create"
MODE_EDIT = "edit"
MODE_CLONE = "clone"


class ProductEditDialog(QDialog):
    def __init__(self, services, product_id: int | None = None,
                 mode: str = MODE_CREATE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.mode = mode
        self.source_id = product_id if mode == MODE_CLONE else None
        self.product_id = product_id if mode == MODE_EDIT else None

        basliklar = {
            MODE_CREATE: "Yeni Ürün",
            MODE_EDIT: "Ürünü Düzenle",
            MODE_CLONE: "Benzer Üründen Oluştur",
        }
        self.setWindowTitle(basliklar[mode])
        self.setModal(True)
        self.setMinimumWidth(560)

        duzen = QVBoxLayout(self)
        duzen.setContentsMargins(20, 18, 20, 18)
        duzen.setSpacing(14)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_basic_tab(), "Temel Bilgiler")
        if mode == MODE_EDIT:
            self.tabs.addTab(self._build_barcodes_tab(), "Barkodlar")
            self.tabs.addTab(self._build_locations_tab(), "Bulunduğu Yerler")
        duzen.addWidget(self.tabs)

        dugmeler = QHBoxLayout()
        dugmeler.addStretch(1)
        vazgec = QPushButton("Vazgeç")
        vazgec.clicked.connect(self.reject)
        kaydet = QPushButton("Kaydet")
        kaydet.setObjectName("primary")
        kaydet.setDefault(True)
        kaydet.clicked.connect(self._save)
        dugmeler.addWidget(vazgec)
        dugmeler.addWidget(kaydet)
        duzen.addLayout(dugmeler)

        self._load()

    # ===================== Sekmeler ======================================
    def _build_basic_tab(self) -> QWidget:
        sayfa = QWidget()
        form = QFormLayout(sayfa)
        form.setSpacing(10)

        self.name_edit = self._text_field("Örnek: Tuborg Gold 50 cl Kutu")
        form.addRow("Ürün adı *", self.name_edit)

        self.price_edit = self._text_field("Örnek: 80")
        form.addRow("Satış fiyatı (TL) *", self.price_edit)

        self.brand_edit = self._text_field("Örnek: Tuborg")
        form.addRow("Marka", self.brand_edit)

        self.category_combo = QComboBox()
        self.category_combo.addItem("Seçilmedi", None)
        for ust, altlar in self.services.catalog.category_tree():
            self.category_combo.addItem(ust["name"], ust["id"])
            for alt in altlar:
                self.category_combo.addItem(f"   {alt['name']}", alt["id"])
        form.addRow("Kategori", self.category_combo)

        self.family_edit = self._text_field("Örnek: Coca-Cola")
        form.addRow("Ürün ailesi", self.family_edit)

        self.unit_combo = QComboBox()
        self.unit_combo.addItems(["Adet", "Paket", "Koli"])
        form.addRow("Birim", self.unit_combo)

        self.vat_spin = QSpinBox()
        self.vat_spin.setRange(0, 100)
        self.vat_spin.setValue(self.services.settings.default_vat_rate())
        self.vat_spin.setSuffix(" %")
        self.vat_spin.setProperty("scannerExempt", True)
        form.addRow("KDV oranı", self.vat_spin)

        varsayilan_min, varsayilan_kritik = self.services.settings.default_thresholds()
        self.min_spin = QSpinBox()
        self.min_spin.setRange(0, 100000)
        self.min_spin.setValue(varsayilan_min)
        self.min_spin.setProperty("scannerExempt", True)
        form.addRow("Az stok sınırı", self.min_spin)

        self.critical_spin = QSpinBox()
        self.critical_spin.setRange(0, 100000)
        self.critical_spin.setValue(varsayilan_kritik)
        self.critical_spin.setProperty("scannerExempt", True)
        form.addRow("Kritik stok sınırı", self.critical_spin)

        if self.mode != MODE_EDIT:
            self.barcode_edit = self._text_field("Barkodu okutabilirsiniz")
            form.addRow("Barkod", self.barcode_edit)

            self.location_combo = QComboBox()
            self.location_combo.addItem("Seçilmedi", None)
            for konum in self.services.catalog.locations():
                self.location_combo.addItem(konum["name"], konum["id"])
            form.addRow("Bulunduğu yer", self.location_combo)

            self.stock_edit = self._text_field("Bilmiyorsanız boş bırakın")
            form.addRow("Şu an kaç adet var?", self.stock_edit)

            self.cost_edit = self._text_field("Örnek: 50")
            form.addRow("Alış fiyatı (TL)", self.cost_edit)

            ipucu = QLabel(
                "Adet alanını boş bırakırsanız ürün \"Henüz Sayılmadı\" olarak "
                "işaretlenir. 0 yazarsanız \"saydım, gerçekten sıfır\" demektir."
            )
            ipucu.setWordWrap(True)
            ipucu.setStyleSheet(f"color: {theme.TEXT_MUTED};")
            form.addRow("", ipucu)
        return sayfa

    def _build_barcodes_tab(self) -> QWidget:
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        duzen.setSpacing(10)

        self.barcode_list = QListWidget()
        duzen.addWidget(self.barcode_list)

        ekle = QHBoxLayout()
        self.new_barcode_edit = self._text_field("Yeni barkodu okutun")
        ekle.addWidget(self.new_barcode_edit, 2)

        self.barcode_type_combo = QComboBox()
        for tur, etiket in BARCODE_TYPE_LABELS.items():
            self.barcode_type_combo.addItem(etiket, tur)
        ekle.addWidget(self.barcode_type_combo)

        self.multiplier_spin = QSpinBox()
        self.multiplier_spin.setRange(1, 10000)
        self.multiplier_spin.setPrefix("× ")
        self.multiplier_spin.setProperty("scannerExempt", True)
        ekle.addWidget(self.multiplier_spin)

        ekle_dugme = QPushButton("Ekle")
        ekle_dugme.clicked.connect(self._add_barcode)
        ekle.addWidget(ekle_dugme)
        duzen.addLayout(ekle)

        sil = QPushButton("Seçili Barkodu Kullanımdan Kaldır")
        sil.clicked.connect(self._remove_barcode)
        duzen.addWidget(sil)

        aciklama = QLabel(
            "Bir ürünün birden çok barkodu olabilir: tekli, paket, koli. "
            "Koli barkodu okutulduğunda kolideki adet kadar işlem yapılır."
        )
        aciklama.setWordWrap(True)
        aciklama.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        duzen.addWidget(aciklama)
        return sayfa

    def _build_locations_tab(self) -> QWidget:
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        duzen.setSpacing(10)

        self.location_list = QListWidget()
        duzen.addWidget(self.location_list)

        aciklama = QLabel(
            "Ürün aynı anda birden fazla yerde bulunabilir. "
            "Yerini değiştirmek TOPLAM STOĞU DEĞİŞTİRMEZ."
        )
        aciklama.setWordWrap(True)
        aciklama.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        duzen.addWidget(aciklama)
        return sayfa

    def _text_field(self, placeholder: str = "") -> QLineEdit:
        alan = QLineEdit()
        alan.setPlaceholderText(placeholder)
        # Elle yazılan alanlar okuyucu süzgecinden muaftır.
        alan.setProperty("scannerExempt", True)
        alan.setMaximumWidth(metrics.FORM_FIELD_MAX_WIDTH)
        return alan

    # ===================== Yükleme =======================================
    def _load(self) -> None:
        kaynak_id = self.product_id or self.source_id
        if kaynak_id is None:
            return
        urun = self.services.products.get(kaynak_id)
        if urun is None:
            return

        if self.mode == MODE_EDIT:
            self.name_edit.setText(urun["name"])
            self.price_edit.setText(kurus_to_tl_text(urun["sale_price"]))
        else:
            self.name_edit.setPlaceholderText(f"Örnek: {urun['name']}")

        if urun["brand_id"]:
            marka = self.services.db.query_one(
                "SELECT name FROM brands WHERE id = ?", (urun["brand_id"],)
            )
            if marka:
                self.brand_edit.setText(marka["name"])
        if urun["family_id"]:
            aile = self.services.db.query_one(
                "SELECT name FROM product_families WHERE id = ?", (urun["family_id"],)
            )
            if aile:
                self.family_edit.setText(aile["name"])

        index = self.category_combo.findData(urun["category_id"])
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
        self.unit_combo.setCurrentText(urun["unit_label"])
        self.vat_spin.setValue(urun["vat_rate"] or 0)
        self.min_spin.setValue(urun["min_stock"])
        self.critical_spin.setValue(urun["critical_stock"])

        if self.mode == MODE_EDIT:
            self._reload_barcodes()
            self._reload_locations()

    def _reload_barcodes(self) -> None:
        self.barcode_list.clear()
        for barkod in self.services.barcodes.barcodes_of(self.product_id):
            etiket = BARCODE_TYPE_LABELS.get(barkod["barcode_type"], "")
            carpan = (
                f" × {barkod['quantity_multiplier']}"
                if barkod["quantity_multiplier"] > 1 else ""
            )
            oge = QListWidgetItem(f"{barkod['barcode_norm']}   [{etiket}{carpan}]")
            oge.setData(32, barkod["id"])
            self.barcode_list.addItem(oge)

    def _reload_locations(self) -> None:
        self.location_list.clear()
        mevcut = {
            konum["id"] for konum in self.services.catalog.locations_of(self.product_id)
        }
        for konum in self.services.catalog.locations():
            oge = QListWidgetItem(konum["name"])
            oge.setFlags(oge.flags() | 16)          # Qt.ItemIsUserCheckable
            oge.setCheckState(2 if konum["id"] in mevcut else 0)
            oge.setData(32, konum["id"])
            self.location_list.addItem(oge)

    # ===================== Barkod işlemleri ==============================
    def _add_barcode(self) -> None:
        metin = self.new_barcode_edit.text().strip()
        if not metin:
            return
        try:
            self.services.barcodes.add_barcode(
                self.product_id, metin,
                self.barcode_type_combo.currentData(),
                self.multiplier_spin.value(),
            )
        except DomainError as hata:
            show_error(self, hata.message, hata.detail)
            return
        self.new_barcode_edit.clear()
        self.multiplier_spin.setValue(1)
        self._reload_barcodes()

    def _remove_barcode(self) -> None:
        oge = self.barcode_list.currentItem()
        if oge is None:
            return
        if not ask_confirm(
            self, "Bu barkod kullanımdan kaldırılsın mı?",
            "Barkod silinmez, geçmişte kalır. Kasada artık okunmaz.",
            accept_text="Evet",
        ):
            return
        self.services.barcodes.deactivate_barcode(oge.data(32))
        self._reload_barcodes()

    # ===================== Kaydetme ======================================
    def _save(self) -> None:
        ad = self.name_edit.text().strip()
        if not ad:
            show_error(self, "Ürün adı boş olamaz.")
            self.name_edit.setFocus()
            return

        fiyat = None
        if self.price_edit.text().strip():
            try:
                fiyat = tl_to_kurus(self.price_edit.text())
            except DomainError as hata:
                show_error(self, hata.message)
                self.price_edit.setFocus()
                return

        alanlar = {
            "brand_id": self.services.catalog.ensure_brand(self.brand_edit.text()),
            "family_id": self.services.catalog.ensure_family(self.family_edit.text()),
            "category_id": self.category_combo.currentData(),
            "unit_label": self.unit_combo.currentText(),
            "vat_rate": self.vat_spin.value(),
            "min_stock": self.min_spin.value(),
            "critical_stock": self.critical_spin.value(),
        }

        try:
            if self.mode == MODE_EDIT:
                self.services.products.update(self.product_id, name=ad, **alanlar)
                if fiyat is not None:
                    self.services.products.set_price(self.product_id, fiyat)
                self._save_locations()
            elif self.mode == MODE_CLONE:
                self.product_id = self.services.products.create_from_similar(
                    self.source_id, ad, sale_price=fiyat, **alanlar
                )
                self._save_new_extras()
            else:
                self.product_id = self.services.products.quick_create(
                    name=ad, sale_price=fiyat,
                    barcode=self.barcode_edit.text().strip() or None,
                    initial_stock=self._initial_stock(),
                    purchase_cost=self._purchase_cost(),
                    location_id=self.location_combo.currentData(),
                    **alanlar,
                )
        except DomainError as hata:
            show_error(self, hata.message, hata.detail)
            return
        except Exception as hata:
            log.exception("Ürün kaydedilemedi")
            show_error(self, "Ürün kaydedilemedi. Hiçbir bilgi değişmedi.", str(hata))
            return
        self.accept()

    def _save_new_extras(self) -> None:
        barkod = self.barcode_edit.text().strip()
        if barkod:
            try:
                self.services.barcodes.add_barcode(self.product_id, barkod)
            except DomainError as hata:
                show_error(self, hata.message)
        konum = self.location_combo.currentData()
        if konum:
            self.services.catalog.add_product_location(self.product_id, konum, True)
        adet = self._initial_stock()
        if adet is not None:
            self.services.inventory.set_initial_stock(
                self.product_id, adet, self._purchase_cost() or 0
            )

    def _save_locations(self) -> None:
        if not hasattr(self, "location_list"):
            return
        for index in range(self.location_list.count()):
            oge = self.location_list.item(index)
            konum_id = oge.data(32)
            secili = oge.checkState() == 2
            if secili:
                self.services.catalog.add_product_location(self.product_id, konum_id)
            else:
                self.services.catalog.remove_product_location(self.product_id, konum_id)

    def _initial_stock(self) -> int | None:
        """Boş = bilinmiyor ("Henüz Sayılmadı"); 0 = saydım, gerçekten sıfır."""
        if not hasattr(self, "stock_edit"):
            return None
        metin = self.stock_edit.text().strip()
        if not metin:
            return None
        try:
            from app.core.quantity import parse_quantity

            return max(0, parse_quantity(metin))
        except DomainError:
            return None

    def _purchase_cost(self) -> int | None:
        if not hasattr(self, "cost_edit") or not self.cost_edit.text().strip():
            return None
        try:
            return tl_to_kurus(self.cost_edit.text())
        except DomainError:
            return None

    # ===================== Kısayollar ====================================
    @staticmethod
    def create(services, parent=None) -> int | None:
        pencere = ProductEditDialog(services, None, MODE_CREATE, parent)
        return pencere.product_id if pencere.exec() else None

    @staticmethod
    def edit(services, product_id: int, parent=None) -> bool:
        pencere = ProductEditDialog(services, product_id, MODE_EDIT, parent)
        return bool(pencere.exec())

    @staticmethod
    def clone(services, product_id: int, parent=None) -> int | None:
        pencere = ProductEditDialog(services, product_id, MODE_CLONE, parent)
        return pencere.product_id if pencere.exec() else None
