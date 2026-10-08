"""Ürün tanımlama / düzenleme penceresi.

İlk kurulumda ZORUNLU alan azdır: ad ve fiyat yeter. Tedarikçi, aile, etiket,
asgari stok gibi alanlar SORULMAZ; eksik kalanlar "Eksik Bilgiler" listesinde
sonradan tamamlanır.

"Benzer Üründen Oluştur" marka, kategori, birim ve rafları kopyalar; barkod,
ad ve fiyat kopyalanmaz — onlar ürünü ayıran şeylerdir.

Düzenleme (V1.2, D-09): pencerede yapılan HER ŞEY (alanlar, fiyat, etiketler,
tedarikçi, barkod ekleme/kaldırma, yerler, referans alış fiyatı) yalnızca
"Kaydet"e basınca ve TEK işlemde yazılır; "Vazgeç" hiçbir şeyi değiştirmez.
Esas raf korunur. Ürünün kategorisi kaldırılmışsa listede "(kullanımdan
kaldırıldı)" olarak görünür ve kaydedince SİLİNMEZ.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
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

#: Liste öğesinde kimlik saklanan rol (Qt.ItemDataRole.UserRole).
VERI_ROLU = Qt.ItemDataRole.UserRole

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
        #: Kaydet'e kadar BEKLETİLEN barkod değişiklikleri (Vazgeç = hiçbiri).
        self.pending_barcode_adds: list[tuple[str, str, int]] = []
        self.pending_barcode_removals: set[int] = set()

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
        self.save_button = QPushButton("Kaydet")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        # Okuyucunun Enter'ı pencereyi KAYDETMEMELİ: varsayılan düğme yok.
        for dugme in (vazgec, self.save_button):
            dugme.setAutoDefault(False)
            dugme.setDefault(False)
        dugmeler.addWidget(vazgec)
        dugmeler.addWidget(self.save_button)
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

        self.supplier_combo = QComboBox()
        self.supplier_combo.addItem("Seçilmedi", None)
        for tedarikci in self.services.suppliers.all():
            self.supplier_combo.addItem(tedarikci["name"], tedarikci["id"])
        form.addRow("Tedarikçi", self.supplier_combo)

        self.tags_edit = self._text_field("virgülle ayırın: soğuk, kutu")
        form.addRow("Etiketler", self.tags_edit)

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

        if self.mode == MODE_EDIT:
            # Katalog / tedarikçi listesi fiyatı: stok değerine ve "son alış"a
            # GİRMEZ; yalnızca bilgi ve fiyat önerisi içindir.
            self.reference_edit = self._text_field("Bilmiyorsanız boş bırakın")
            form.addRow("Referans alış (katalog) (TL)", self.reference_edit)

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
        self.new_barcode_edit.returnPressed.connect(self._add_barcode)
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
        if index < 0 and urun["category_id"] is not None:
            # Kaldırılmış kategori: görünür kalır, kaydedince kaybolmaz.
            yol = self.services.categories.path(urun["category_id"])
            self.category_combo.addItem(f"{yol} (kullanımdan kaldırıldı)", urun["category_id"])
            index = self.category_combo.findData(urun["category_id"])
        if index >= 0:
            self.category_combo.setCurrentIndex(index)
        index = self.supplier_combo.findData(urun["default_supplier_id"])
        if index >= 0:
            self.supplier_combo.setCurrentIndex(index)
        kaynak_etiketler = self.services.catalog.tags_of(kaynak_id)
        self.tags_edit.setText(", ".join(t["name"] for t in kaynak_etiketler))
        if self.mode == MODE_EDIT and urun["reference_cost"] is not None:
            self.reference_edit.setText(kurus_to_tl_text(urun["reference_cost"]))
        self.unit_combo.setCurrentText(urun["unit_label"])
        self.vat_spin.setValue(urun["vat_rate"] or 0)
        self.min_spin.setValue(urun["min_stock"])
        self.critical_spin.setValue(urun["critical_stock"])

        if self.mode == MODE_EDIT:
            self._reload_barcodes()
            self._reload_locations()

    def _reload_barcodes(self) -> None:
        """Kayıtlı barkodlar (kaldırılacaklar hariç) + bekleyen eklemeler."""
        self.barcode_list.clear()
        for barkod in self.services.barcodes.barcodes_of(self.product_id):
            if barkod["id"] in self.pending_barcode_removals:
                continue
            etiket = BARCODE_TYPE_LABELS.get(barkod["barcode_type"], "")
            carpan = (
                f" × {barkod['quantity_multiplier']}"
                if barkod["quantity_multiplier"] > 1 else ""
            )
            oge = QListWidgetItem(f"{barkod['barcode_norm']}   [{etiket}{carpan}]")
            oge.setData(VERI_ROLU, barkod["id"])
            self.barcode_list.addItem(oge)
        for sira, (barkod, tur, carpan) in enumerate(self.pending_barcode_adds):
            etiket = BARCODE_TYPE_LABELS.get(tur, "")
            ek = f" × {carpan}" if carpan > 1 else ""
            oge = QListWidgetItem(f"{barkod}   [{etiket}{ek}]   (kaydedince eklenecek)")
            oge.setData(VERI_ROLU, -(sira + 1))
            self.barcode_list.addItem(oge)

    def _reload_locations(self) -> None:
        self.location_list.clear()
        mevcut = {
            konum["id"] for konum in self.services.catalog.locations_of(self.product_id)
        }
        for konum in self.services.catalog.locations():
            oge = QListWidgetItem(konum["name"])
            oge.setFlags(oge.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            oge.setCheckState(
                Qt.CheckState.Checked if konum["id"] in mevcut else Qt.CheckState.Unchecked
            )
            oge.setData(VERI_ROLU, konum["id"])
            self.location_list.addItem(oge)

    # ===================== Barkod işlemleri ==============================
    def _add_barcode(self) -> None:
        """Barkod Kaydet'e kadar BEKLETİLİR; çakışma hemen söylenir."""
        metin = self.new_barcode_edit.text().strip()
        if not metin:
            return
        sahip = self.services.barcodes.owner_of(metin)
        if sahip is not None and sahip["product_id"] != self.product_id:
            show_error(self, f"Bu barkod zaten {sahip['name']} ürününde kayıtlı.")
            return
        normal = self.services.barcodes.normalize(metin)
        if sahip is not None or any(
            self.services.barcodes.normalize(b) == normal for b, _, _ in self.pending_barcode_adds
        ):
            show_error(self, "Bu barkod bu üründe zaten kayıtlı.")
            return
        self.pending_barcode_adds.append(
            (metin, self.barcode_type_combo.currentData(), self.multiplier_spin.value())
        )
        self.new_barcode_edit.clear()
        self.multiplier_spin.setValue(1)
        self._reload_barcodes()

    def _remove_barcode(self) -> None:
        oge = self.barcode_list.currentItem()
        if oge is None:
            return
        kimlik = oge.data(VERI_ROLU)
        if kimlik < 0:                                    # henüz eklenmemiş
            del self.pending_barcode_adds[-kimlik - 1]
            self._reload_barcodes()
            return
        if not ask_confirm(
            self, "Bu barkod kullanımdan kaldırılsın mı?",
            "Kaydet'e basınca kaldırılır. Barkod silinmez, geçmişte kalır; kasada "
            "artık okunmaz.",
            accept_text="Evet",
        ):
            return
        self.pending_barcode_removals.add(kimlik)
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

        temel = {
            "category_id": self.category_combo.currentData(),
            "unit_label": self.unit_combo.currentText(),
            "vat_rate": self.vat_spin.value(),
            "min_stock": self.min_spin.value(),
            "critical_stock": self.critical_spin.value(),
            "default_supplier_id": self.supplier_combo.currentData(),
        }
        etiketler = [t.strip() for t in self.tags_edit.text().split(",") if t.strip()]

        try:
            if self.mode == MODE_EDIT:
                referans_metni = self.reference_edit.text().strip()
                referans = tl_to_kurus(referans_metni) if referans_metni else None
                # TEK işlem: marka/aile kaydı dahil hepsi ya olur ya hiçbiri.
                self.services.products.save_edit(
                    self.product_id,
                    {"name": ad, **temel},
                    sale_price=fiyat,
                    brand_name=self.brand_edit.text().strip(),
                    family_name=self.family_edit.text().strip(),
                    tags=etiketler,
                    location_ids=self._checked_locations(),
                    barcode_adds=list(self.pending_barcode_adds),
                    barcode_removals=sorted(self.pending_barcode_removals),
                    reference_cost=referans,
                )
                self.accept()
                return
            alanlar = {
                **temel,
                "brand_id": self.services.catalog.ensure_brand(self.brand_edit.text()),
                "family_id": self.services.catalog.ensure_family(self.family_edit.text()),
            }
            if self.mode == MODE_CLONE:
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
            if hata.detail:
                log.info("Ürün kaydedilemedi: %s | %s", hata.message, hata.detail)
            show_error(self, hata.message)
            return
        except Exception:
            log.exception("Ürün kaydedilemedi")
            show_error(self, "Ürün kaydedilemedi. Hiçbir bilgi değişmedi.")
            return
        if self.product_id is not None and (etiketler or self.mode == MODE_CLONE):
            self.services.catalog.set_tags(
                self.product_id,
                [self.services.catalog.ensure_tag(t) for t in etiketler],
            )
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
            # Boş maliyet = bilinmiyor (tahmini); 0 yazılmaz (D-06).
            self.services.inventory.set_initial_stock(
                self.product_id, adet, self._purchase_cost()
            )

    def _checked_locations(self) -> list[int] | None:
        if not hasattr(self, "location_list"):
            return None
        return [
            self.location_list.item(i).data(VERI_ROLU)
            for i in range(self.location_list.count())
            if self.location_list.item(i).checkState() == Qt.CheckState.Checked
        ]

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
