"""Tanınmayan barkod: "Ürün tanınmadı." akışı.

Kurallar (şartname §16):
  * Tanınmayan barkod ASLA sessizce yok sayılmaz,
  * adsız sahte ürün ASLA oluşturulmaz,
  * satış, ürün açıkça KAYDEDİLENE ve geçerli bir satış fiyatı OLANA kadar
    tamamlanmaz,
  * kaydedildikten sonra barkodu tekrar okutmaya gerek kalmaz.

Form bilerek MİNİMALDİR: ad, fiyat, kategori. Tedarikçi, etiket, aile, asgari
stok gibi alanlar burada SORULMAZ; müşteri beklerken doldurulacak şeyler değildir.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import DomainError
from app.core.money import tl_to_kurus
from app.ui import metrics, theme
from app.ui.dialogs.common_dialogs import BlockedScanNotice, show_error


class UnknownBarcodeDialog(QDialog):
    """Önce sorar: tanımlansın mı, vazgeçilsin mi?"""

    def __init__(self, barcode: str, services, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.services = services
        self.barcode = barcode
        self.product_id: int | None = None

        self.setWindowTitle("Ürün tanınmadı")
        self.setModal(True)
        self.setMinimumWidth(460)

        duzen = QVBoxLayout(self)
        duzen.setContentsMargins(24, 20, 24, 20)
        duzen.setSpacing(14)

        baslik = QLabel("Ürün tanınmadı.")
        baslik.setFont(theme.base_font(17, bold=True))
        duzen.addWidget(baslik)

        barkod_etiketi = QLabel(f"Okutulan barkod: {barcode}")
        barkod_etiketi.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        duzen.addWidget(barkod_etiketi)

        self.blocked_notice = BlockedScanNotice(self)
        duzen.addWidget(self.blocked_notice)

        # --- Kısa form ---
        self.form_widget = QWidget()
        form = QFormLayout(self.form_widget)
        form.setSpacing(10)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Örnek: Tuborg Gold 50 cl Kutu")
        # Elle yazılan alanlar okuyucu süzgecinden muaftır.
        self.name_edit.setProperty("scannerExempt", True)
        form.addRow("Ürün adı", self.name_edit)

        self.price_edit = QLineEdit()
        self.price_edit.setPlaceholderText("Örnek: 80")
        self.price_edit.setProperty("scannerExempt", True)
        form.addRow("Satış fiyatı (TL)", self.price_edit)

        self.category_combo = QComboBox()
        self.category_combo.addItem("Seçilmedi", None)
        for ust, altlar in services.catalog.category_tree():
            for alt in altlar:
                self.category_combo.addItem(f"{ust['name']} > {alt['name']}", alt["id"])
            if not altlar:
                self.category_combo.addItem(ust["name"], ust["id"])
        form.addRow("Kategori", self.category_combo)

        self.form_widget.setMaximumWidth(metrics.FORM_FIELD_MAX_WIDTH + 160)
        self.form_widget.setVisible(False)
        duzen.addWidget(self.form_widget)

        # --- Düğmeler ---
        self.buttons = QHBoxLayout()
        self.buttons.addStretch(1)

        self.cancel_button = QPushButton("Vazgeç")
        self.cancel_button.clicked.connect(self.reject)

        self.define_button = QPushButton("Ürün Tanımla")
        self.define_button.setObjectName("primary")
        self.define_button.setDefault(True)
        self.define_button.clicked.connect(self._show_form)

        self.save_button = QPushButton("Kaydet ve Sat")
        self.save_button.setObjectName("primary")
        self.save_button.setVisible(False)
        self.save_button.clicked.connect(self._save)

        self.buttons.addWidget(self.cancel_button)
        self.buttons.addWidget(self.define_button)
        self.buttons.addWidget(self.save_button)
        duzen.addLayout(self.buttons)

    def notify_blocked(self) -> None:
        """Pencere açıkken okutma yapıldı: anında görünür uyarı."""
        self.blocked_notice.show_blocked()

    def _show_form(self) -> None:
        self.form_widget.setVisible(True)
        self.define_button.setVisible(False)
        self.save_button.setVisible(True)
        self.name_edit.setFocus()
        self.adjustSize()

    def _save(self) -> None:
        ad = self.name_edit.text().strip()
        if not ad:
            show_error(self, "Ürün adı boş olamaz.")
            self.name_edit.setFocus()
            return
        try:
            fiyat = tl_to_kurus(self.price_edit.text())
        except DomainError as hata:
            show_error(self, hata.message)
            self.price_edit.setFocus()
            return
        if fiyat <= 0:
            show_error(self, "Satış fiyatı sıfırdan büyük olmalıdır.")
            self.price_edit.setFocus()
            return

        try:
            self.product_id = self.services.products.quick_create(
                name=ad,
                sale_price=fiyat,
                barcode=self.barcode,
                category_id=self.category_combo.currentData(),
                initial_stock=None,          # stok bilinmiyor: "henüz sayılmadı"
            )
        except DomainError as hata:
            show_error(self, hata.message, hata.detail)
            return
        self.accept()

    @staticmethod
    def run(barcode: str, services, parent: QWidget | None = None) -> int | None:
        """Ürün tanımlandıysa yeni ürünün kimliğini, aksi hâlde ``None`` döner."""
        pencere = UnknownBarcodeDialog(barcode, services, parent)
        if pencere.exec() == QDialog.DialogCode.Accepted:
            return pencere.product_id
        return None
