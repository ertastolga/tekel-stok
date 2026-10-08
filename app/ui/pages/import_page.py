"""📄 Ürün İçe Aktar (YÖNETİM): tedarikçi / katalog listesinden toplu ürün.

Adımlar: 1) Dosya  2) Sütunlar  3) Önizleme  4) Sonuç.

* Dosya: .xlsx ya da .csv. Örnek şablon kaydedilebilir.
* Sütunlar: başlıklar kendiliğinden eşlenir; kullanıcı düzeltir. Kategorisi
  olmayan yeni ürünler için varsayılan kategori ve çakışma politikası seçilir.
* Önizleme HİÇBİR ŞEY yazmaz: sayılar, durum süzgeci, satır satır değişiklik
  ve sorunlar. Güncellenecek alanlar tek tek seçilir (varsayılan: satış ve alış
  fiyatı). Baştaki sıfır önerisi yalnızca seçilen satırlarda kabul edilir.
  Yazılmayan satırlar CSV hata raporu olarak kaydedilebilir.
* "İçe Aktar" yönetici PIN'i ister (PIN varsa), önce güvenlik yedeği alır ve
  her şeyi tek işlemde yazar; fiyat değişiklikleri Fiyat Yönetimi'nden geri
  alınabilir.
"""
from __future__ import annotations

import csv
import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.errors import DomainError
from app.core.money import format_tl
from app.importers import alanlar as al
from app.importers.okuyucu import XLSX_KULLANILABILIR, Tablo, dosya_ozeti, oku
from app.services import import_service as ims
from app.services.security_service import ProtectedAction
from app.ui import metrics
from app.ui.dialogs.common_dialogs import ask_confirm, scanning_suspended, show_error
from app.ui.pages.base import Page
from app.ui.widgets.common import Card, PageHeader, make_label, setup_table, stretch_column

log = logging.getLogger(__name__)

DOSYA, SUTUNLAR, ONIZLEME, SONUC = range(4)
ONIZLEME_SUTUNLARI = ["Satır", "Durum", "Barkod", "Ürün adı", "Değişiklik / sorun"]
#: Önizlemede bir kerede gösterilen en çok satır (sayılar hepsini kapsar).
GOSTERIM_SINIRI = 2000
SABLON_SATIRLARI = [
    ["Barkod", "Ürün adı", "Satış fiyatı", "Kategori", "Marka", "Aile", "Tedarikçi",
     "Alış fiyatı", "KDV"],
    ["8690504001492", "Tuborg Gold 50 cl Kutu", "80", "Alkollü İçecekler > Bira",
     "Tuborg", "Tuborg Gold", "Anadolu Dağıtım", "52,50", "20"],
]


def _deger_metni(alan: str, deger) -> str:
    if deger is None or deger == "":
        return "—"
    if alan in (al.SATIS, al.ALIS):
        return format_tl(deger)
    if alan == al.KDV:
        return f"%{deger}"
    return str(deger)


class ImportPage(Page):
    nav_title = "📄  Ürün İçe Aktar"
    nav_key = "ice_aktar"
    nav_group = "yonetim"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.path: Path | None = None
        self.table_data: Tablo | None = None
        self.plan: ims.IceAktarmaPlani | None = None
        self.accepted_zero: set[int] = set()
        self.result: ims.IceAktarmaSonucu | None = None
        self._yazilacak = (0, 0)

        self.header = PageHeader(
            "📄 Ürün İçe Aktar",
            "Tedarikçi ya da katalog listesinden (.xlsx / .csv) ürün ekleyin veya "
            "fiyat güncelleyin. Önce önizlenir; onaylamadan hiçbir şey değişmez.",
        )
        self.root.addWidget(self.header)
        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
                                 metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V)
        duzen.setSpacing(metrics.PAGE_SPACING)
        self.step_label = make_label("", "cardHint")
        duzen.addWidget(self.step_label)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_file())
        self.stack.addWidget(self._build_mapping())
        self.stack.addWidget(self._build_preview())
        self.stack.addWidget(self._build_result())
        duzen.addWidget(self.stack, 1)
        self.root.addWidget(govde, 1)
        self.show_step(DOSYA)

    # ===================== Kurulum =======================================
    def _build_file(self) -> QWidget:
        kart = Card()
        kart.body.addWidget(make_label("1. Dosyayı seçin", "sectionTitle"))
        kart.body.addWidget(make_label(
            "İlk satır sütun başlıkları olmalıdır (Barkod, Ürün adı, Satış fiyatı…). "
            "Barkod sütununu Excel'de METİN olarak biçimlendirin; sayı olarak kaydedilen "
            "barkodlarda baştaki sıfırlar kaybolabilir.", "cardHint", wrap=True))
        if not XLSX_KULLANILABILIR:
            kart.body.addWidget(make_label(
                "Excel (.xlsx) okuma geçici olarak kullanılamıyor; dosyayı CSV olarak "
                "kaydedip seçin.", "cardHint", wrap=True))
        satir = QHBoxLayout()
        self.choose_button = QPushButton("Dosya Seç…")
        self.choose_button.setObjectName("primary")
        self.choose_button.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
        self.choose_button.clicked.connect(self._dosya_sec)
        satir.addWidget(self.choose_button)
        self.template_button = QPushButton("Örnek şablonu kaydet…")
        self.template_button.clicked.connect(self._sablon_kaydet)
        satir.addWidget(self.template_button)
        satir.addStretch(1)
        kart.body.addLayout(satir)
        self.file_info = make_label("", "cardHint", wrap=True)
        kart.body.addWidget(self.file_info)
        sayfa_satiri = QHBoxLayout()
        sayfa_satiri.addWidget(make_label("Sayfa:"))
        self.sheet_combo = QComboBox()
        self.sheet_combo.activated.connect(lambda _i: self._sayfa_degisti())
        sayfa_satiri.addWidget(self.sheet_combo)
        sayfa_satiri.addStretch(1)
        kart.body.addLayout(sayfa_satiri)
        kart.body.addStretch(1)
        alt = QHBoxLayout()
        alt.addStretch(1)
        self.to_mapping_button = QPushButton("Devam: Sütunlar ▶")
        self.to_mapping_button.setObjectName("primary")
        self.to_mapping_button.clicked.connect(lambda: self.show_step(SUTUNLAR))
        alt.addWidget(self.to_mapping_button)
        kart.body.addLayout(alt)
        return kart

    def _build_mapping(self) -> QWidget:
        kart = Card()
        kart.body.addWidget(make_label("2. Sütunları eşleyin", "sectionTitle"))
        kart.body.addWidget(make_label(
            "Her bilgi dosyanın hangi sütununda? Barkod zorunludur; yeni ürün için ad ve "
            "satış fiyatı da gerekir. 'Alış fiyatı' yalnızca katalog bilgisi olarak "
            "saklanır; stok değerini ve son alış fiyatını DEĞİŞTİRMEZ.", "cardHint", wrap=True))
        izgara = QGridLayout()
        self.mapping_combos: dict[str, QComboBox] = {}
        for sira, (alan, ad) in enumerate(al.ALAN_ADLARI.items()):
            izgara.addWidget(QLabel(ad + (" *" if alan in al.ZORUNLU else "")), sira // 3,
                             (sira % 3) * 2)
            kutu = QComboBox()
            self.mapping_combos[alan] = kutu
            izgara.addWidget(kutu, sira // 3, (sira % 3) * 2 + 1)
        kart.body.addLayout(izgara)

        secenek = QGridLayout()
        secenek.addWidget(QLabel("Kategorisi olmayan yeni ürünler:"), 0, 0)
        self.default_category_combo = QComboBox()
        secenek.addWidget(self.default_category_combo, 0, 1)
        secenek.addWidget(QLabel("Var olan ürünler:"), 1, 0)
        self.policy_combo = QComboBox()
        for kimlik, ad in ims.POLITIKA_ADLARI.items():
            self.policy_combo.addItem(ad, kimlik)
        self.policy_combo.setCurrentIndex(self.policy_combo.findData(ims.EKLE_VE_GUNCELLE))
        secenek.addWidget(self.policy_combo, 1, 1)
        kart.body.addLayout(secenek)
        kart.body.addStretch(1)
        alt = QHBoxLayout()
        geri = QPushButton("◀ Dosya")
        geri.clicked.connect(lambda: self.show_step(DOSYA))
        alt.addWidget(geri)
        alt.addStretch(1)
        self.preview_button = QPushButton("Önizle ▶")
        self.preview_button.setObjectName("primary")
        self.preview_button.clicked.connect(self.preview)
        alt.addWidget(self.preview_button)
        kart.body.addLayout(alt)
        return kart

    def _build_preview(self) -> QWidget:
        kart = Card()
        kart.body.addWidget(make_label("3. Önizleme — henüz hiçbir şey yazılmadı",
                                       "sectionTitle"))
        self.counts_label = make_label("", "cardHint", wrap=True)
        kart.body.addWidget(self.counts_label)
        ust = QHBoxLayout()
        ust.addWidget(QLabel("Göster:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("Tümü", None)
        for durum, ad in ims.DURUM_ADLARI.items():
            self.status_filter.addItem(ad, durum)
        self.status_filter.currentIndexChanged.connect(lambda _i: self._tabloyu_doldur())
        ust.addWidget(self.status_filter)
        ust.addStretch(1)
        self.accept_zero_button = QPushButton("Seçili satırlarda sıfır önerisini kabul et")
        self.accept_zero_button.clicked.connect(self._sifir_kabul_secili)
        ust.addWidget(self.accept_zero_button)
        self.report_button = QPushButton("Hata raporunu kaydet…")
        self.report_button.clicked.connect(self._rapor_kaydet)
        ust.addWidget(self.report_button)
        kart.body.addLayout(ust)

        self.preview_table = QTableWidget(0, len(ONIZLEME_SUTUNLARI))
        setup_table(self.preview_table, ONIZLEME_SUTUNLARI)
        self.preview_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        stretch_column(self.preview_table, "Değişiklik / sorun")
        kart.body.addWidget(self.preview_table, 1)

        alanlar = QHBoxLayout()
        alanlar.addWidget(QLabel("Var olan üründe güncellenecek bilgiler:"))
        self.field_checks: dict[str, QCheckBox] = {}
        for alan in ims.GUNCELLENEBILIR:
            kutu = QCheckBox(al.ALAN_ADLARI[alan])
            kutu.setChecked(alan in ims.VARSAYILAN_GUNCELLENECEK)
            kutu.toggled.connect(lambda _d: self._ozet_yaz())
            self.field_checks[alan] = kutu
            alanlar.addWidget(kutu)
        alanlar.addStretch(1)
        kart.body.addLayout(alanlar)

        alt = QHBoxLayout()
        geri = QPushButton("◀ Sütunlar")
        geri.clicked.connect(lambda: self.show_step(SUTUNLAR))
        alt.addWidget(geri)
        alt.addStretch(1)
        self.apply_button = QPushButton("İçe Aktar")
        self.apply_button.setObjectName("primary")
        self.apply_button.setMinimumHeight(metrics.TOUCH_TARGET_MIN)
        self.apply_button.clicked.connect(self.apply)
        alt.addWidget(self.apply_button)
        kart.body.addLayout(alt)
        return kart

    def _build_result(self) -> QWidget:
        kart = Card()
        kart.body.addWidget(make_label("4. Sonuç", "sectionTitle"))
        self.result_label = make_label("", "cardValue", wrap=True)
        kart.body.addWidget(self.result_label)
        self.result_hint = make_label("", "cardHint", wrap=True)
        kart.body.addWidget(self.result_hint)
        kart.body.addStretch(1)
        alt = QHBoxLayout()
        alt.addStretch(1)
        yeni = QPushButton("Yeni içe aktarma")
        yeni.clicked.connect(self.reset)
        alt.addWidget(yeni)
        kart.body.addLayout(alt)
        return kart

    # ===================== Gezinme =======================================
    def show_step(self, adim: int) -> None:
        if adim >= SUTUNLAR and self.table_data is None:
            adim = DOSYA
        if adim >= ONIZLEME and self.plan is None:
            adim = SUTUNLAR if self.table_data is not None else DOSYA
        self.stack.setCurrentIndex(adim)
        adlar = ("Dosya", "Sütunlar", "Önizleme", "Sonuç")
        self.step_label.setText("  ›  ".join(
            f"[{ad}]" if i == adim else ad for i, ad in enumerate(adlar)))
        self.to_mapping_button.setEnabled(self.table_data is not None)

    def handle_back(self) -> bool:
        adim = self.stack.currentIndex()
        if adim in (SUTUNLAR, ONIZLEME):
            self.show_step(adim - 1)
            return True
        return False

    def on_activated(self) -> None:
        self._kategorileri_yukle()

    def reset(self) -> None:
        self.path = None
        self.table_data = None
        self.plan = None
        self.result = None
        self.accepted_zero = set()
        self.file_info.setText("")
        self.sheet_combo.clear()
        self.show_step(DOSYA)

    # ===================== 1. Dosya ======================================
    def _dosya_sec(self) -> None:
        with scanning_suspended(self.main_window.router):
            yol, _ = QFileDialog.getOpenFileName(
                self, "Ürün listesi seçin", str(Path.home()),
                "Ürün listesi (*.xlsx *.csv);;Excel (*.xlsx);;CSV (*.csv)")
        if yol:
            self.load_file(yol)

    def load_file(self, yol: str | Path, sayfa: str | None = None) -> bool:
        try:
            tablo = oku(yol, sayfa)
        except DomainError as hata:
            show_error(self, hata.message)
            return False
        self.path = Path(yol)
        self.table_data = tablo
        self.plan = None
        self.accepted_zero = set()
        self.sheet_combo.clear()
        for ad in tablo.sayfalar:
            self.sheet_combo.addItem(ad)
        self.sheet_combo.setCurrentText(tablo.sayfa or "")
        self.sheet_combo.setEnabled(len(tablo.sayfalar) > 1)
        bicim = "Excel" if tablo.bicim == "XLSX" else f"CSV ({tablo.kodlama})"
        self.file_info.setText(
            f"{self.path.name} · {bicim} · {len(tablo.satirlar)} satır · "
            f"{len(tablo.basliklar)} sütun")
        self._eslemeyi_kur()
        self.show_step(SUTUNLAR)
        return True

    def _sayfa_degisti(self) -> None:
        if self.path is not None and self.sheet_combo.currentText():
            self.load_file(self.path, self.sheet_combo.currentText())

    def _sablon_kaydet(self) -> None:
        with scanning_suspended(self.main_window.router):
            yol, _ = QFileDialog.getSaveFileName(
                self, "Örnek şablonu kaydet", str(Path.home() / "urun_listesi_sablon.csv"),
                "CSV (*.csv)")
        if yol:
            self.save_template(yol)

    @staticmethod
    def save_template(yol: str | Path) -> None:
        with open(yol, "w", encoding="utf-8-sig", newline="") as dosya:
            csv.writer(dosya, delimiter=";").writerows(SABLON_SATIRLARI)

    # ===================== 2. Sütunlar ===================================
    def _kategorileri_yukle(self) -> None:
        secili = self.default_category_combo.currentData()
        self.default_category_combo.clear()
        self.default_category_combo.addItem("Seçilmedi — kategorisiz satırlar geçersiz", None)
        for ust, altlar in self.services.catalog.category_tree():
            self.default_category_combo.addItem(ust["name"], ust["id"])
            for alt in altlar:
                self.default_category_combo.addItem(f"   {alt['name']}", alt["id"])
        index = self.default_category_combo.findData(secili)
        self.default_category_combo.setCurrentIndex(max(0, index))

    def _eslemeyi_kur(self) -> None:
        esleme = al.otomatik_esle(self.table_data.basliklar)
        for alan, kutu in self.mapping_combos.items():
            kutu.clear()
            kutu.addItem("— yok —", None)
            for i, baslik in enumerate(self.table_data.basliklar):
                kutu.addItem(baslik or f"(sütun {i + 1})", i)
            kutu.setCurrentIndex(kutu.findData(esleme.get(alan)) if alan in esleme else 0)

    def mapping(self) -> dict[str, int]:
        return {alan: kutu.currentData() for alan, kutu in self.mapping_combos.items()
                if kutu.currentData() is not None}

    # ===================== 3. Önizleme ===================================
    def preview(self) -> bool:
        if self.table_data is None:
            return False
        esleme = self.mapping()
        kullanilan = list(esleme.values())
        if len(kullanilan) != len(set(kullanilan)):
            show_error(self, "Bir sütun birden çok bilgiye eşlenmiş. Lütfen düzeltin.")
            return False
        try:
            self.plan = self.services.imports.onizle(
                self.table_data, esleme, self.policy_combo.currentData(),
                self.default_category_combo.currentData(), frozenset(self.accepted_zero))
        except DomainError as hata:
            show_error(self, hata.message)
            return False
        self._tabloyu_doldur()
        self._ozet_yaz()
        self.show_step(ONIZLEME)
        return True

    def selected_fields(self) -> frozenset[str]:
        return frozenset(a for a, k in self.field_checks.items() if k.isChecked())

    def _ozet_yaz(self) -> None:
        if self.plan is None:
            return
        s = self.plan.sayilar()
        secili = self.selected_fields()
        guncellenecek = sum(1 for r in self.plan.satirlar if r.durum == ims.GUNCELLE
                            and any(a in secili for a in r.farklar))
        self.counts_label.setText(
            f"Toplam satır: {s['toplam']} · Geçerli yeni ürün: {s['yeni']} · Eşleşen "
            f"mevcut barkod: {s['eslesen']} · Güncellenebilecek: {s['guncellenecek']} "
            f"(seçili bilgilerle: {guncellenecek}) · Değişiklik yok: {s['ayni']} · "
            f"Çakışma: {s['cakisma']} · Geçersiz barkod: {s['gecersiz_barkod']} · Eksik "
            f"zorunlu alan: {s['eksik_zorunlu']} · Geçersiz fiyat: {s['gecersiz_fiyat']} · "
            f"Atlanan: {s['atlanan']}")
        self._yazilacak = (s["yeni"], guncellenecek)
        self.apply_button.setEnabled(bool(s["yeni"] or guncellenecek))
        self.apply_button.setText(
            f"İçe Aktar ({s['yeni']} yeni, {guncellenecek} güncelleme)")

    def visible_rows(self) -> list[ims.PlanSatiri]:
        if self.plan is None:
            return []
        durum = self.status_filter.currentData()
        return [s for s in self.plan.satirlar if durum is None or s.durum == durum]

    def _tabloyu_doldur(self) -> None:
        satirlar = self.visible_rows()[:GOSTERIM_SINIRI]
        self.preview_table.setRowCount(len(satirlar))
        for i, s in enumerate(satirlar):
            if s.farklar:
                ayrinti = "; ".join(
                    f"{al.ALAN_ADLARI[a]}: {_deger_metni(a, e)} → {_deger_metni(a, y)}"
                    for a, (e, y) in s.farklar.items())
            else:
                ayrinti = "; ".join(s.sorunlar)
            ekler = list(s.uyarilar)
            if s.sifir_onerisi:
                ekler.append(f"öneri: {s.sifir_onerisi}")
            if ekler:
                ayrinti = "; ".join(filter(None, [ayrinti, *ekler]))
            hucreler = (str(s.satir_no), ims.DURUM_ADLARI[s.durum], s.barkod or "",
                        s.ad or "", ayrinti)
            for sutun, metin in enumerate(hucreler):
                hucre = QTableWidgetItem(metin)
                hucre.setData(Qt.ItemDataRole.UserRole, s.satir_no)
                self.preview_table.setItem(i, sutun, hucre)

    def accept_zero_suggestions(self, satir_nolari: list[int]) -> None:
        self.accepted_zero.update(satir_nolari)
        self.preview()

    def _sifir_kabul_secili(self) -> None:
        secili = {self.preview_table.item(i.row(), 0).data(Qt.ItemDataRole.UserRole)
                  for i in self.preview_table.selectionModel().selectedRows()}
        if secili:
            self.accept_zero_suggestions(sorted(secili))

    def _rapor_kaydet(self) -> None:
        if self.plan is None:
            return
        with scanning_suspended(self.main_window.router):
            yol, _ = QFileDialog.getSaveFileName(
                self, "Hata raporunu kaydet", str(Path.home() / "ice_aktarma_hatalari.csv"),
                "CSV (*.csv)")
        if yol:
            self.save_error_report(yol)

    def save_error_report(self, yol: str | Path) -> int:
        satirlar = ims.hata_raporu_satirlari(self.plan)
        with open(yol, "w", encoding="utf-8-sig", newline="") as dosya:
            csv.writer(dosya, delimiter=";").writerows(satirlar)
        return len(satirlar) - 1

    # ===================== 4. Uygula =====================================
    def apply(self) -> bool:
        if self.plan is None or self.path is None:
            return False
        if not self.guard_require(ProtectedAction.ICE_AKTAR):
            return False
        s = self.plan.sayilar()
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, "Ürün listesi içe aktarılsın mı?",
                f"{self._yazilacak[0]} yeni ürün eklenecek, {self._yazilacak[1]} ürün "
                f"güncellenecek. Önce otomatik güvenlik yedeği alınır; "
                f"{s['gecersiz'] + s['cakisma']} sorunlu satır yazılmaz. Fiyat "
                "değişiklikleri Fiyat Yönetimi'nden geri alınabilir.",
                accept_text="İçe Aktar",
            )
        if not onay:
            return False
        try:
            sha, _ = dosya_ozeti(self.path)
            self.result = self.services.imports.uygula(
                self.plan, self.path.name, sha, self.selected_fields())
        except DomainError as hata:
            show_error(self, hata.message)
            return False
        except Exception:
            log.exception("İçe aktarma tamamlanamadı")
            show_error(self, "İçe aktarma tamamlanamadı. Hiçbir ürün değiştirilmedi.")
            return False
        r = self.result
        self.result_label.setText(
            f"✓ {r.yeni} yeni ürün eklendi, {r.guncellenen} ürün güncellendi.")
        self.result_hint.setText(
            f"{r.atlanan} satır yazılmadı. İçe aktarma öncesi yedek: {r.yedek_yolu}"
            + ("\nFiyat değişiklikleri Fiyat Yönetimi › Son toplu değişiklikler'den geri "
               "alınabilir." if r.fiyat_grubu else ""))
        self.show_step(SONUC)
        self.data_changed()
        return True
