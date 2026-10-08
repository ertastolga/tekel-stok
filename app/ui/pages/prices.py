"""Fiyat Yönetimi (YÖNETİM): fiyat listesi, toplu değişiklik, geri alma, geçmiş.

* Liste: ürün, kategori, marka, satış fiyatı, bilinen son alış, marj (yalnızca
  bilinen alışla), referans alış (katalog — ayrı ve etiketli), son fiyat
  değişimi, son alış tarihi.
* Toplu değişiklik DAİMA önce önizlenir; önizlemede yalnızca "Değişecek"
  satırlar seçili gelir (değişmeyen / ters yöndekiler işaretli ama seçili
  değil). Uygulama ve geri alma yönetici PIN'i ister (PIN varsa).
* Önizlemeden sonra fiyatı değişen ürün varsa hiçbir şey yazılmaz; kullanıcı
  yeniden önizler.
* Geri alma, yalnızca o toplu değişiklikten sonra el sürülmemiş ürünleri eski
  fiyatına döndürür; kaç ürüne dokunulmayacağı önceden söylenir.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core import pricing_math as pm
from app.core.errors import DomainError, FiyatlarDegisti
from app.core.money import format_tl, tl_to_kurus
from app.core.clock import utc_to_local
from app.core.tr import fmt_datetime
from app.services.pricing_service import (
    GRUP_ADLARI,
    FiyatDegisikligi,
    FiyatFiltresi,
)
from app.services.security_service import ProtectedAction
from app.ui import metrics
from app.ui.dialogs.common_dialogs import ask_confirm, scanning_suspended, show_error
from app.ui.pages.base import Page
from app.ui.widgets.common import Card, EmptyState, PageHeader, make_label, setup_table

log = logging.getLogger(__name__)

#: Listede bir kerede gösterilen en çok ürün.
LISTE_SINIRI = 500
KIMLIK_ROLU = int(Qt.ItemDataRole.UserRole)
LISTE_SUTUNLARI = [
    "Ürün", "Kategori", "Marka", "Satış", "Son alış", "Marj",
    "Referans alış (katalog)", "Son fiyat değişimi", "Son alış tarihi",
]
ONIZLEME_SUTUNLARI = ["Uygula", "Ürün", "Eski", "Yeni", "Değişim", "Yeni marj", "Durum"]


def _tl(kurus: int | None) -> str:
    return format_tl(kurus) if kurus is not None else "—"


def _yuzde(bp: int | None) -> str:
    return pm.bp_metni(bp) if bp is not None else "—"


def _tarih(utc: int | None) -> str:
    return fmt_datetime(utc_to_local(utc)) if utc else "—"


def _kart(baslik: str) -> Card:
    kart = Card()
    kart.body.addWidget(make_label(baslik, "cardTitle"))
    return kart


def _hucre(metin: str, sag: bool = False) -> QTableWidgetItem:
    hucre = QTableWidgetItem(metin)
    if sag:
        hucre.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return hucre


class PricesPage(Page):
    nav_title = "💲  Fiyat Yönetimi"
    nav_key = "fiyatlar"
    nav_group = "yonetim"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self._satirlar: list = []
        self._onizleme: list = []

        self.header = PageHeader(
            "💲 Fiyat Yönetimi",
            "Fiyatları tek tek ya da toplu değiştirin; her değişiklik önce önizlenir.",
        )
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
                                 metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V)
        duzen.setSpacing(metrics.PAGE_SPACING)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_list())
        self.stack.addWidget(self._build_preview())
        duzen.addWidget(self.stack, 1)
        self.root.addWidget(govde, 1)

    # ===================== Kurulum: liste ================================
    def _build_list(self) -> QWidget:
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        duzen.setContentsMargins(0, 0, 0, 0)
        duzen.setSpacing(metrics.PAGE_SPACING)

        suzgec = Card()
        satir = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Ürün adı ya da barkod ara…")
        self.search_edit.setProperty("scannerExempt", True)
        self.search_edit.textChanged.connect(lambda _m: self.refresh())
        satir.addWidget(self.search_edit, 2)
        self.category_combo = QComboBox()
        self.category_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        satir.addWidget(self.category_combo, 1)
        self.supplier_combo = QComboBox()
        self.supplier_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        satir.addWidget(self.supplier_combo, 1)
        self.no_cost_check = QCheckBox("Alış fiyatı bilinmeyenler")
        self.no_cost_check.toggled.connect(lambda _d: self.refresh())
        satir.addWidget(self.no_cost_check)
        self.no_price_check = QCheckBox("Fiyatı girilmemişler")
        self.no_price_check.toggled.connect(lambda _d: self.refresh())
        satir.addWidget(self.no_price_check)
        suzgec.body.addLayout(satir)
        duzen.addWidget(suzgec)

        orta = QHBoxLayout()
        orta.setSpacing(metrics.PAGE_SPACING)
        sol = QVBoxLayout()
        self.table = QTableWidget(0, len(LISTE_SUTUNLARI))
        setup_table(self.table, LISTE_SUTUNLARI)
        self.table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.table.itemSelectionChanged.connect(self._secim_degisti)
        sol.addWidget(self.table, 1)
        self.empty = EmptyState("Ürün bulunamadı", "Süzgeci değiştirip yeniden deneyin.")
        sol.addWidget(self.empty, 1)
        alt = QHBoxLayout()
        self.count_label = make_label("", "cardHint")
        alt.addWidget(self.count_label, 1)
        self.select_all_button = QPushButton("Tümünü seç")
        self.select_all_button.clicked.connect(self.table.selectAll)
        alt.addWidget(self.select_all_button)
        sol.addLayout(alt)
        orta.addLayout(sol, 3)
        orta.addWidget(self._build_side(), 2)
        duzen.addLayout(orta, 1)
        return sayfa

    def _build_side(self) -> QWidget:
        yan = QWidget()
        duzen = QVBoxLayout(yan)
        duzen.setContentsMargins(0, 0, 0, 0)
        duzen.setSpacing(metrics.PAGE_SPACING)

        toplu = _kart("Toplu değişiklik")
        self.operation_combo = QComboBox()
        for tur, ad in pm.ISLEM_ADLARI.items():
            self.operation_combo.addItem(ad, tur)
        self.operation_combo.currentIndexChanged.connect(lambda _i: self._islem_degisti())
        toplu.body.addWidget(self.operation_combo)
        self.value_edit = QLineEdit()
        self.value_edit.setProperty("scannerExempt", True)
        toplu.body.addWidget(self.value_edit)
        self.rounding_combo = QComboBox()
        for adim, ad in pm.YUVARLAMA_ADIMLARI.items():
            self.rounding_combo.addItem(f"Yuvarlama: {ad}", adim)
        toplu.body.addWidget(self.rounding_combo)
        self.rounding_hint = make_label(
            "Artışlar yukarı, düşüşler aşağı yuvarlanır.", "cardHint", wrap=True)
        toplu.body.addWidget(self.rounding_hint)
        self.preview_button = QPushButton("Önizle")
        self.preview_button.setObjectName("primary")
        self.preview_button.clicked.connect(self.preview_selected)
        toplu.body.addWidget(self.preview_button)
        duzen.addWidget(toplu)

        gecmis = _kart("Seçili ürünün fiyat geçmişi")
        self.timeline_list = QListWidget()
        gecmis.body.addWidget(self.timeline_list)
        duzen.addWidget(gecmis, 1)

        gruplar = _kart("Son toplu değişiklikler")
        self.batch_list = QListWidget()
        self.batch_list.currentRowChanged.connect(lambda _r: self._grup_secildi())
        gruplar.body.addWidget(self.batch_list)
        self.undo_button = QPushButton("Seçili değişikliği geri al")
        self.undo_button.clicked.connect(self.undo_selected_batch)
        gruplar.body.addWidget(self.undo_button)
        duzen.addWidget(gruplar, 1)
        self._islem_degisti()
        return yan

    # ===================== Kurulum: önizleme =============================
    def _build_preview(self) -> QWidget:
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        duzen.setContentsMargins(0, 0, 0, 0)
        duzen.setSpacing(metrics.PAGE_SPACING)
        self.preview_title = make_label("", "sectionTitle", wrap=True)
        duzen.addWidget(self.preview_title)
        self.preview_hint = make_label(
            "Yalnızca işaretli satırlar uygulanır. Değişmeyen ya da beklenenin tersi "
            "yönde değişen satırlar kendiliğinden işaretli gelmez.", "cardHint", wrap=True)
        duzen.addWidget(self.preview_hint)
        self.preview_table = QTableWidget(0, len(ONIZLEME_SUTUNLARI))
        setup_table(self.preview_table, ONIZLEME_SUTUNLARI)
        self.preview_table.itemChanged.connect(lambda _h: self._onizleme_sayaci())
        duzen.addWidget(self.preview_table, 1)
        alt = QHBoxLayout()
        self.preview_count = make_label("", "cardHint")
        alt.addWidget(self.preview_count, 1)
        geri = QPushButton("◀  Vazgeç")
        geri.clicked.connect(self.close_preview)
        alt.addWidget(geri)
        self.apply_button = QPushButton("Uygula")
        self.apply_button.setObjectName("primary")
        self.apply_button.clicked.connect(self.apply_preview)
        alt.addWidget(self.apply_button)
        duzen.addLayout(alt)
        return sayfa

    # ===================== Yaşam döngüsü =================================
    def on_activated(self) -> None:
        self._load_filters()
        self.rounding_combo.setCurrentIndex(
            self.rounding_combo.findData(self.services.settings.price_rounding()))
        self.refresh()

    def handle_back(self) -> bool:
        if self.stack.currentIndex() == 1:
            self.close_preview()
            return True
        return False

    def _load_filters(self) -> None:
        for kutu, ilk, kaynak in (
            (self.category_combo, "Tüm kategoriler", "kategori"),
            (self.supplier_combo, "Tüm tedarikçiler", "tedarikci"),
        ):
            secili = kutu.currentData()
            kutu.blockSignals(True)
            kutu.clear()
            kutu.addItem(ilk, None)
            if kaynak == "kategori":
                for ust, altlar in self.services.catalog.category_tree():
                    kutu.addItem(ust["name"], ust["id"])
                    for alt in altlar:
                        kutu.addItem(f"   {alt['name']}", alt["id"])
            else:
                for tedarikci in self.services.suppliers.all():
                    kutu.addItem(tedarikci["name"], tedarikci["id"])
            index = kutu.findData(secili)
            kutu.setCurrentIndex(index if index >= 0 else 0)
            kutu.blockSignals(False)

    def _filtre(self) -> FiyatFiltresi:
        return FiyatFiltresi(
            metin=self.search_edit.text(),
            kategori_id=self.category_combo.currentData(),
            tedarikci_id=self.supplier_combo.currentData(),
            yalniz_fiyatsiz=self.no_price_check.isChecked(),
            yalniz_maliyetsiz=self.no_cost_check.isChecked(),
        )

    def refresh(self) -> None:
        try:
            self._satirlar = self.services.pricing.listele(self._filtre(), limit=LISTE_SINIRI)
            gruplar = self.services.pricing.gruplar()
        except Exception:
            log.exception("Fiyat listesi okunamadı")
            return
        dolu = bool(self._satirlar)
        self.table.setVisible(dolu)
        self.empty.setVisible(not dolu)
        self.table.clearSelection()
        self.table.setRowCount(len(self._satirlar))
        for i, s in enumerate(self._satirlar):
            hucreler = (
                _hucre(s.ad), _hucre(s.kategori), _hucre(s.marka),
                _hucre(_tl(s.satis), True),
                _hucre(_tl(s.bilinen_maliyet) if s.bilinen_maliyet else "bilinmiyor", True),
                _hucre(_yuzde(s.marj_bp), True),
                _hucre(_tl(s.referans_maliyet), True),
                _hucre(_tarih(s.son_fiyat_degisimi_utc)),
                _hucre(_tarih(s.son_alis_utc)),
            )
            for sutun, hucre in enumerate(hucreler):
                self.table.setItem(i, sutun, hucre)
        self.count_label.setText(
            f"{len(self._satirlar)} ürün"
            + (f" (ilk {LISTE_SINIRI}; süzgeci daraltın)"
               if len(self._satirlar) == LISTE_SINIRI else "")
        )
        self.batch_list.clear()
        for g in gruplar:
            durum = " — geri alındı" if g["geri_alan"] else ""
            metin = (f"{_tarih(g['created_at_utc'])} · {GRUP_ADLARI[g['kind']]} · "
                     f"{g['product_count']} ürün{durum}")
            if g["description"]:
                metin += f"\n{g['description']}"
            oge = QListWidgetItem(metin)
            oge.setData(KIMLIK_ROLU, g["id"])
            self.batch_list.addItem(oge)
        self._secim_degisti()
        self._grup_secildi()

    # ===================== Seçim =========================================
    def selected_ids(self) -> list[int]:
        satirlar = sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        return [self._satirlar[s].product_id for s in satirlar if s < len(self._satirlar)]

    def _secim_degisti(self) -> None:
        secili = self.selected_ids()
        self.preview_button.setEnabled(bool(secili))
        self.preview_button.setText(f"Önizle ({len(secili)} ürün)" if secili else "Önizle")
        self.timeline_list.clear()
        if len(secili) != 1:
            self.timeline_list.addItem("Geçmişini görmek için tek bir ürün seçin.")
            return
        for olay in self.services.pricing.zaman_cizelgesi(secili[0]):
            if olay.zaman_utc is None:
                metin = f"{olay.kaynak}: {_tl(olay.yeni)}"
            else:
                metin = (f"{_tarih(olay.zaman_utc)} · {olay.kaynak}: "
                         f"{_tl(olay.eski)} → {_tl(olay.yeni)}")
            if olay.aciklama:
                metin += f" ({olay.aciklama})"
            self.timeline_list.addItem(metin)

    def _grup_secildi(self) -> None:
        oge = self.batch_list.currentItem()
        self.undo_button.setEnabled(oge is not None)

    def _islem_degisti(self) -> None:
        tur = self.operation_combo.currentData()
        self.value_edit.setPlaceholderText(
            "Yüzde, örnek: 5 ya da 7,5" if tur in pm.YUZDELI else "Tutar (TL), örnek: 2,50"
        )
        sabit = tur == pm.SABIT
        self.rounding_combo.setEnabled(not sabit)
        self.rounding_hint.setText(
            "Yazdığınız tutar aynen kullanılır (yuvarlanmaz)." if sabit else
            "Artışlar yukarı, düşüşler aşağı yuvarlanır." if tur != pm.MARJ else
            "Hedef marjı sağlayan fiyat, alış fiyatı BİLİNEN ürünlerde hesaplanır "
            "(referans alış kullanılmaz); yukarı yuvarlanır."
        )

    # ===================== Önizleme ======================================
    def islem(self) -> pm.FiyatIslemi:
        tur = self.operation_combo.currentData()
        metin = self.value_edit.text()
        deger = pm.yuzde_metninden_bp(metin) if tur in pm.YUZDELI else tl_to_kurus(metin)
        adim = 1 if tur == pm.SABIT else self.rounding_combo.currentData()
        return pm.FiyatIslemi(tur, deger, adim)

    def preview_selected(self) -> None:
        secili = self.selected_ids()
        if not secili:
            return
        try:
            islem = self.islem()
        except DomainError as hata:
            show_error(self, hata.message)
            return
        self._islem_son = islem
        self._onizleme = self.services.pricing.onizle(secili, islem)
        self.preview_table.blockSignals(True)
        self.preview_table.setRowCount(len(self._onizleme))
        for i, s in enumerate(self._onizleme):
            kutu = QTableWidgetItem()
            if s.yeni is not None and s.durum in (pm.DEGISIR, pm.TERS_YON):
                kutu.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                kutu.setCheckState(
                    Qt.CheckState.Checked if s.varsayilan_secili else Qt.CheckState.Unchecked)
            else:
                kutu.setFlags(Qt.ItemFlag.ItemIsEnabled)
            hucreler = (
                kutu, _hucre(s.ad), _hucre(_tl(s.eski), True), _hucre(_tl(s.yeni), True),
                _hucre(_yuzde(s.degisim_bp), True), _hucre(_yuzde(s.yeni_marj_bp), True),
                _hucre(pm.DURUM_ADLARI[s.durum]),
            )
            for sutun, hucre in enumerate(hucreler):
                self.preview_table.setItem(i, sutun, hucre)
        self.preview_table.blockSignals(False)
        self.preview_title.setText(
            f"Önizleme — {pm.ISLEM_ADLARI[islem.tur]} · {len(self._onizleme)} ürün")
        self._onizleme_sayaci()
        self.stack.setCurrentIndex(1)

    def preview_checked(self) -> list:
        return [
            s for i, s in enumerate(self._onizleme)
            if self.preview_table.item(i, 0).checkState() == Qt.CheckState.Checked
        ]

    def set_preview_checked(self, product_id: int, secili: bool) -> None:
        for i, s in enumerate(self._onizleme):
            if s.product_id == product_id:
                self.preview_table.item(i, 0).setCheckState(
                    Qt.CheckState.Checked if secili else Qt.CheckState.Unchecked)

    def _onizleme_sayaci(self) -> None:
        if self.stack.count() < 2 or not hasattr(self, "apply_button"):
            return
        adet = len(self.preview_checked()) if self._onizleme else 0
        isaretli_degil = len(self._onizleme) - adet
        self.preview_count.setText(
            f"{adet} ürünün fiyatı değişecek; {isaretli_degil} ürün değişmeyecek.")
        self.apply_button.setEnabled(adet > 0)
        self.apply_button.setText(f"Uygula ({adet})" if adet else "Uygula")

    def close_preview(self) -> None:
        self.stack.setCurrentIndex(0)
        self._onizleme = []

    def apply_preview(self) -> bool:
        secili = self.preview_checked()
        if not secili:
            return False
        if not self.guard_require(ProtectedAction.TOPLU_FIYAT):
            return False
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, f"{len(secili)} ürünün fiyatı değişsin mi?",
                "Değişiklik fiyat geçmişine yazılır ve 'Son toplu değişiklikler' "
                "listesinden geri alınabilir. Geçmiş satışlar değişmez.",
                accept_text="Uygula",
            )
        if not onay:
            return False
        try:
            self.services.pricing.uygula(
                [FiyatDegisikligi(s.product_id, s.eski, s.yeni) for s in secili],
                aciklama=f"{pm.ISLEM_ADLARI[self._islem_son.tur]}: "
                         f"{self.value_edit.text().strip()}",
            )
        except FiyatlarDegisti as hata:
            show_error(self, hata.message)
            self.close_preview()
            self.refresh()
            return False
        except DomainError as hata:
            show_error(self, hata.message)
            return False
        self.close_preview()
        self.refresh()
        self.data_changed()
        self.notify(f"{len(secili)} ürünün fiyatı değişti.")
        return True

    # ===================== Geri alma =====================================
    def undo_selected_batch(self) -> bool:
        oge = self.batch_list.currentItem()
        if oge is None:
            return False
        grup = oge.data(KIMLIK_ROLU)
        try:
            satirlar = self.services.pricing.geri_alma_onizle(grup)
        except DomainError as hata:
            show_error(self, hata.message)
            return False
        uygun = [s for s in satirlar if s.uygun]
        if not uygun:
            show_error(self, "Geri alınabilecek fiyat kalmadı: bu ürünlerin hepsi "
                             "sonradan yeniden değiştirilmiş.")
            return False
        if not self.guard_require(ProtectedAction.TOPLU_FIYAT):
            return False
        ayrinti = f"{len(uygun)} ürün eski fiyatına döner."
        dokunulmayan = len(satirlar) - len(uygun)
        if dokunulmayan:
            ayrinti += (f" {dokunulmayan} ürünün fiyatı sonradan değiştiği için "
                        "dokunulmayacak.")
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(self, "Toplu değişiklik geri alınsın mı?", ayrinti,
                               accept_text="Geri al", danger=True)
        if not onay:
            return False
        try:
            _grup, alinan, _kalan = self.services.pricing.geri_al(grup)
        except DomainError as hata:
            show_error(self, hata.message)
            return False
        self.refresh()
        self.data_changed()
        self.notify(f"{alinan} ürünün fiyatı geri alındı.")
        return True
