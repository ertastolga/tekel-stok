"""Kategoriler (YÖNETİM): iki düzeyli ağaç, ürün sayıları ve güvenli düzenleme.

* Ağaç her kategorinin ürün sayısını gösterir; "Kategorisiz" ürün sayısı ayrıca
  yazar. Kaldırılan kategoriler istenirse görünür.
* Ekleme ve yeniden adlandırma benzer adları SORAR (uyarı), aynı yerde aynı adı
  ENGELLER (servis). Kaldırma ve birleştirme yönetici PIN'i ister.
* "Şablondan eksikleri ekle" önce ne yapılacağını listeler; isteğe bağlı
  adımlar (yeniden adlandırma, ürün taşıma) kendiliğinden seçili değildir.
* Ad girişi dokunmatik klavyeyle de yapılabilir (klavyesiz kasa).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import DomainError
from app.services.category_service import ISTEGE_BAGLI
from app.services.security_service import ProtectedAction
from app.ui import metrics
from app.ui.dialogs.common_dialogs import (
    ask_confirm,
    button_box,
    scanning_suspended,
    show_error,
    show_info,
)
from app.ui.pages.base import Page
from app.ui.widgets.common import PageHeader, make_label

log = logging.getLogger(__name__)

KIMLIK_ROLU = int(Qt.ItemDataRole.UserRole)


class CategoriesPage(Page):
    nav_title = "🗂  Kategoriler"
    nav_key = "kategoriler"
    nav_group = "yonetim"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.header = PageHeader("🗂 Kategoriler", "Ürünlerin gruplandığı iki düzeyli ağaç.")
        self.new_root_button = QPushButton("Yeni üst kategori")
        self.new_root_button.clicked.connect(lambda: self.add_category(alt=False))
        self.header.add_action(self.new_root_button)
        self.new_child_button = QPushButton("Yeni alt kategori")
        self.new_child_button.clicked.connect(lambda: self.add_category(alt=True))
        self.header.add_action(self.new_child_button)
        self.template_button = QPushButton("Şablondan eksikleri ekle")
        self.template_button.clicked.connect(self.apply_template)
        self.header.add_action(self.template_button)
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
                                 metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V)
        duzen.setSpacing(10)

        ust = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Kategori ara…")
        self.search_edit.setProperty("scannerExempt", True)
        self.search_edit.textChanged.connect(lambda _m: self._filtrele())
        ust.addWidget(self.search_edit, 1)
        self.inactive_check = QCheckBox("Kaldırılanları göster")
        self.inactive_check.stateChanged.connect(lambda _m: self.refresh())
        ust.addWidget(self.inactive_check)
        duzen.addLayout(ust)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Kategori", "Ürün", "Durum"])
        self.tree.setColumnWidth(0, 340)
        self.tree.itemSelectionChanged.connect(self._dugmeleri_guncelle)
        duzen.addWidget(self.tree, 1)

        self.uncategorized_label = make_label("", "cardHint")
        duzen.addWidget(self.uncategorized_label)

        dugmeler = QHBoxLayout()
        self.rename_button = QPushButton("Yeniden adlandır")
        self.rename_button.clicked.connect(self.rename_selected)
        self.move_button = QPushButton("Taşı")
        self.move_button.clicked.connect(self.move_selected)
        self.merge_button = QPushButton("Birleştir")
        self.merge_button.clicked.connect(self.merge_selected)
        self.deactivate_button = QPushButton("Kaldır")
        self.deactivate_button.setObjectName("danger")
        self.deactivate_button.clicked.connect(self.deactivate_selected)
        self.reactivate_button = QPushButton("Yeniden kullanıma al")
        self.reactivate_button.clicked.connect(self.reactivate_selected)
        for dugme in (self.rename_button, self.move_button, self.merge_button,
                      self.reactivate_button):
            dugmeler.addWidget(dugme)
        dugmeler.addStretch(1)
        dugmeler.addWidget(self.deactivate_button)
        duzen.addLayout(dugmeler)
        self.root.addWidget(govde, 1)
        self._dugmeleri_guncelle()

    # ===================== Çizim =========================================
    def refresh(self) -> None:
        secili = self.selected_id()
        self.tree.clear()
        for dugum in self.services.categories.tree(
            include_inactive=self.inactive_check.isChecked()
        ):
            ust = self._oge(dugum, dugum.toplam_urun)
            self.tree.addTopLevelItem(ust)
            for alt in dugum.altlar:
                ust.addChild(self._oge(alt, alt.urun_sayisi))
            ust.setExpanded(True)
        sayi = self.services.categories.uncategorized_count()
        self.uncategorized_label.setText(
            f"Kategorisiz ürün: {sayi}" if sayi else "Tüm ürünlerin kategorisi var."
        )
        if secili is not None:
            self.select_id(secili)
        self._filtrele()
        self._dugmeleri_guncelle()

    @staticmethod
    def _oge(dugum, sayi: int) -> QTreeWidgetItem:
        oge = QTreeWidgetItem([dugum.name, str(sayi), "" if dugum.active else "kaldırıldı"])
        oge.setData(0, KIMLIK_ROLU, dugum.id)
        oge.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if not dugum.active:
            for sutun in range(3):
                oge.setForeground(sutun, Qt.GlobalColor.gray)
        return oge

    def _filtrele(self) -> None:
        from app.core.tr import search_matches

        metin = self.search_edit.text()
        for i in range(self.tree.topLevelItemCount()):
            ust = self.tree.topLevelItem(i)
            gorunen_alt = False
            for j in range(ust.childCount()):
                alt = ust.child(j)
                uyar = search_matches(alt.text(0), metin)
                alt.setHidden(not uyar)
                gorunen_alt = gorunen_alt or uyar
            ust.setHidden(not (search_matches(ust.text(0), metin) or gorunen_alt))

    def selected_id(self) -> int | None:
        oge = self.tree.currentItem()
        return None if oge is None else int(oge.data(0, KIMLIK_ROLU))

    def select_id(self, kimlik: int) -> None:
        for oge in self._tum_ogeler():
            if int(oge.data(0, KIMLIK_ROLU)) == kimlik:
                self.tree.setCurrentItem(oge)
                return

    def _tum_ogeler(self):
        for i in range(self.tree.topLevelItemCount()):
            ust = self.tree.topLevelItem(i)
            yield ust
            for j in range(ust.childCount()):
                yield ust.child(j)

    def _dugmeleri_guncelle(self) -> None:
        kimlik = self.selected_id()
        satir = self.services.categories.get(kimlik) if kimlik is not None else None
        var = satir is not None
        aktif = var and bool(satir["active"])
        for dugme in (self.rename_button, self.move_button, self.merge_button,
                      self.deactivate_button):
            dugme.setEnabled(aktif)
        self.reactivate_button.setEnabled(var and not aktif)
        self.new_child_button.setEnabled(aktif)

    # ===================== Kullanıcı girdisi (testte yamalanır) ===========
    def _ad_iste(self, baslik: str, ilk: str = "") -> str | None:
        from app.ui.widgets.touch_input import TouchTextDialog

        pencere = TouchTextDialog(baslik, initial=ilk, parent=self)
        with scanning_suspended(self.main_window.router):
            sonuc = pencere.exec()
        return pencere.value().strip() if sonuc == QDialog.DialogCode.Accepted else None

    def _hedef_sec(self, baslik: str, secenekler: list[tuple[str, int | None]]):
        """Seçeneklerden birini döner (ad, kimlik); vazgeçilirse ``False``."""
        pencere = QDialog(self)
        pencere.setWindowTitle(baslik)
        dikey = QVBoxLayout(pencere)
        dikey.addWidget(QLabel(baslik))
        kutu = QComboBox()
        for ad, kimlik in secenekler:
            kutu.addItem(ad, kimlik)
        dikey.addWidget(kutu)
        dugmeler = button_box("Tamam", "Vazgeç")
        dugmeler.accepted.connect(pencere.accept)
        dugmeler.rejected.connect(pencere.reject)
        dikey.addWidget(dugmeler)
        with scanning_suspended(self.main_window.router):
            if pencere.exec() != QDialog.DialogCode.Accepted:
                return False
        return kutu.currentData()

    def _onayla(self, baslik: str, ayrinti: str, metin: str = "Evet",
                tehlike: bool = False) -> bool:
        with scanning_suspended(self.main_window.router):
            return ask_confirm(self, baslik, ayrinti, accept_text=metin, danger=tehlike)

    def _hata(self, hata: DomainError) -> None:
        with scanning_suspended(self.main_window.router):
            show_error(self, hata.message)

    # ===================== Eylemler ======================================
    def add_category(self, alt: bool) -> int | None:
        ust_id = None
        if alt:
            ust_id = self.selected_id()
            if ust_id is None:
                return None
            satir = self.services.categories.get(ust_id)
            if satir["parent_id"] is not None:
                ust_id = satir["parent_id"]           # alt seçiliyse kardeş eklenir
        ad = self._ad_iste("Yeni alt kategorinin adı" if alt else "Yeni üst kategorinin adı")
        if not ad:
            return None
        uyarilar = self.services.categories.similar_names(ad, ust_id)
        if uyarilar and not self._onayla(
            "Benzer bir kategori var. Yine de eklensin mi?", "\n".join(uyarilar),
            "Yine de ekle",
        ):
            return None
        try:
            kimlik = self.services.categories.create(ad, ust_id)
        except DomainError as hata:
            self._hata(hata)
            return None
        self.refresh()
        self.select_id(kimlik)
        return kimlik

    def rename_selected(self) -> None:
        kimlik = self.selected_id()
        if kimlik is None:
            return
        satir = self.services.categories.get(kimlik)
        ad = self._ad_iste("Yeni ad", satir["name"])
        if not ad or ad == satir["name"]:
            return
        uyarilar = self.services.categories.similar_names(ad, satir["parent_id"],
                                                          exclude_id=kimlik)
        if uyarilar and not self._onayla(
            "Benzer bir kategori var. Yine de bu ad verilsin mi?", "\n".join(uyarilar),
        ):
            return
        try:
            self.services.categories.rename(kimlik, ad)
        except DomainError as hata:
            self._hata(hata)
            return
        self.refresh()

    def move_selected(self) -> None:
        kimlik = self.selected_id()
        if kimlik is None:
            return
        secenekler = [("(Üst düzey kategori olsun)", None)] + [
            (d.name, d.id) for d in self.services.categories.tree() if d.id != kimlik
        ]
        hedef = self._hedef_sec("Nereye taşınsın?", secenekler)
        if hedef is False:
            return
        try:
            self.services.categories.move(kimlik, hedef)
        except DomainError as hata:
            self._hata(hata)
            return
        self.refresh()

    def deactivate_selected(self) -> None:
        kimlik = self.selected_id()
        if kimlik is None:
            return
        if not self.guard_require(ProtectedAction.KATEGORI_PASIF_BIRLESTIR):
            return
        satir = self.services.categories.get(kimlik)
        if not self._onayla(
            f"\"{satir['name']}\" kategorisi kaldırılsın mı?",
            "Ürünler kategorilerini korur; kategori listelerde görünmez. "
            "İstediğinizde yeniden kullanıma alabilirsiniz.",
            "Evet, kaldır", tehlike=True,
        ):
            return
        try:
            self.services.categories.deactivate(kimlik)
        except DomainError as hata:
            self._hata(hata)
            return
        self.refresh()

    def reactivate_selected(self) -> None:
        kimlik = self.selected_id()
        if kimlik is None:
            return
        try:
            self.services.categories.reactivate(kimlik)
        except DomainError as hata:
            self._hata(hata)
            return
        self.refresh()

    def merge_selected(self) -> None:
        kimlik = self.selected_id()
        if kimlik is None:
            return
        if not self.guard_require(ProtectedAction.KATEGORI_PASIF_BIRLESTIR):
            return
        secenekler = []
        for dugum in self.services.categories.tree():
            if dugum.id != kimlik:
                secenekler.append((dugum.name, dugum.id))
            for alt in dugum.altlar:
                if alt.id != kimlik:
                    secenekler.append((f"{dugum.name} > {alt.name}", alt.id))
        hedef = self._hedef_sec("Hangi kategoriyle birleştirilsin?", secenekler)
        if hedef is False or hedef is None:
            return
        satir = self.services.categories.get(kimlik)
        if not self._onayla(
            f"\"{satir['name']}\" kategorisi birleştirilsin mi?",
            f"Ürünleri \"{self.services.categories.path(hedef)}\" kategorisine taşınır ve "
            "bu kategori kaldırılır.", "Evet, birleştir", tehlike=True,
        ):
            return
        try:
            sayi = self.services.categories.merge(kimlik, hedef)
        except DomainError as hata:
            self._hata(hata)
            return
        self.notify(f"{sayi} ürün taşındı; kategori kaldırıldı.")
        self.refresh()

    # ===================== Şablon ========================================
    def _adimlari_sec(self, adimlar) -> list | None:
        """Önizleme penceresi: adımlar işaretlenebilir liste (testte yamalanır)."""
        pencere = QDialog(self)
        pencere.setWindowTitle("Şablondan eksikleri ekle")
        dikey = QVBoxLayout(pencere)
        dikey.addWidget(QLabel(
            "Aşağıdakiler yapılacak. İşaretsiz adımlar uygulanmaz; isteğe bağlı "
            "adımlar kendiliğinden seçili değildir."
        ))
        liste = QListWidget()
        for adim in adimlar:
            oge = QListWidgetItem(adim.aciklama)
            oge.setFlags(oge.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            oge.setCheckState(Qt.CheckState.Checked if adim.secili else Qt.CheckState.Unchecked)
            liste.addItem(oge)
        dikey.addWidget(liste)
        dugmeler = button_box("Uygula", "Vazgeç")
        dugmeler.accepted.connect(pencere.accept)
        dugmeler.rejected.connect(pencere.reject)
        dikey.addWidget(dugmeler)
        with scanning_suspended(self.main_window.router):
            if pencere.exec() != QDialog.DialogCode.Accepted:
                return None
        for i, adim in enumerate(adimlar):
            adim.secili = liste.item(i).checkState() == Qt.CheckState.Checked
        return adimlar

    def apply_template(self) -> int:
        adimlar = self.services.categories.template_preview()
        if not adimlar:
            with scanning_suspended(self.main_window.router):
                show_info(self, "Şablon", "Şablondaki tüm kategoriler zaten var.")
            return 0
        for adim in adimlar:
            if adim.tur in ISTEGE_BAGLI:
                adim.secili = False
        secilen = self._adimlari_sec(adimlar)
        if secilen is None:
            return 0
        try:
            sayi = self.services.categories.apply_template(secilen)
        except DomainError as hata:
            self._hata(hata)
            return 0
        self.notify(f"Şablondan {sayi} adım uygulandı.")
        self.refresh()
        return sayi
