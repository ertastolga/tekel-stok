"""📊 Analiz (YÖNETİM) — dönem seçmeli, sekmeli satış analizi (V1.2 M8b, §6.3).

* Her açılışta **Genel Bakış + Bugün** ile başlar.
* Dönem: Bugün, Dün, Son 7 Gün, Bu Hafta, Geçen Hafta, Bu Ay, Geçen Ay, Özel.
  Karşılaştırma dönemleri plan §6.3'e göre seçilir (366 günden uzunsa yok).
* Sekmeler: Genel Bakış · Eğilimler · Ürünler · Sepetler · Ödemeler ·
  Kâr ve Maliyet Kapsamı. Bir sekme ancak ilk GÖSTERİLDİĞİNDE doldurulur;
  sonuçlar servis tarafında ``(sorgu, dönem, data_version)`` ile önbelleklidir.

Çalışma kipi:
  **SALES_FIRST:** Genel Bakış KÂR GÖSTERMEZ (stoksuz satış serbest; maliyetler
  çoğu zaman tahminidir). Ödeme kırılımı, sepet, saatlik satış ve
  karşılaştırma görünür. Stok uyarılarının yeri Stok Durumu ekranıdır.
  **INVENTORY_TRACKED:** brüt kâr, stok değeri, Dikkat ve uzun süredir
  satılmayanlar (V1 davranışı).
"Kâr ve Maliyet Kapsamı" sekmesi her iki kipte de vardır ve önce kapsamı
söyler: kâr ancak güvenilir maliyetli satışlar cironun en az %95'i ise tek
rakam olarak yazılır.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.analytics import donemler as dn
from app.analytics import kar, sepetler
from app.core.models import STOCK_STATE_LABELS, StockState
from app.core.money import format_tl
from app.core.tr import fmt_decimal_trim, fmt_percent
from app.services.analytics_service import AYLIK, GUNLUK, HAFTALIK, HAFTANIN_GUNU, SAATLIK
from app.ui import metrics, theme
from app.ui.pages.base import Page
from app.ui.widgets.charts import ADET, TL, SimpleBarChart
from app.ui.widgets.common import (
    Badge,
    Card,
    EmptyState,
    PageHeader,
    StatCard,
    make_label,
    setup_table,
    stretch_column,
)

log = logging.getLogger(__name__)

GUN_KISA = ("Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz")
TARIH = "yyyy-MM-dd"
GENEL, EGILIM, URUNLER, SEPETLER, ODEMELER, KAR = range(6)
SEKME_ADLARI = ("Genel Bakış", "Eğilimler", "Ürünler", "Sepetler", "Ödemeler",
                "Kâr ve Maliyet Kapsamı")
DONEM_DUGMELERI = (dn.BUGUN, dn.DUN, dn.SON_7, dn.BU_HAFTA, dn.GECEN_HAFTA, dn.BU_AY,
                   dn.GECEN_AY, dn.OZEL)
EGILIM_ADLARI = {SAATLIK: "Saatlik", HAFTANIN_GUNU: "Haftanın günü", GUNLUK: "Günlük",
                 HAFTALIK: "Haftalık", AYLIK: "Aylık"}
URUN_GORUNUMLERI = {"ADET": "En çok satan (adet)", "CIRO": "En çok ciro",
                    "AZ": "Az satanlar", "KATEGORI": "Kategoriler", "MARKA": "Markalar",
                    "SATILMAYAN": "Uzun süredir satılmayanlar"}


def _sag(metin: str) -> QTableWidgetItem:
    hucre = QTableWidgetItem(metin)
    hucre.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return hucre


def _tablo(basliklar: list[str], esnek: str | None = None) -> QTableWidget:
    tablo = QTableWidget(0, len(basliklar))
    setup_table(tablo, basliklar)
    if esnek:
        stretch_column(tablo, esnek)
    return tablo


def _doldur(tablo: QTableWidget, satirlar: list[tuple]) -> None:
    tablo.setRowCount(len(satirlar))
    for i, satir in enumerate(satirlar):
        for j, deger in enumerate(satir):
            tablo.setItem(i, j, deger if isinstance(deger, QTableWidgetItem)
                          else (QTableWidgetItem(deger) if j == 0 else _sag(str(deger))))


def _degisim(simdi: int, once: int) -> str:
    yuzde = dn.degisim_yuzdesi(simdi, once)
    if yuzde is None:
        return "—"
    isaret = "▲" if yuzde > 0 else ("▼" if yuzde < 0 else "=")
    return f"{isaret} {fmt_percent(abs(yuzde))}"


class DashboardPage(Page):
    nav_title = "📊  Analiz"
    nav_key = "panel"
    nav_group = "yonetim"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self.period_type = dn.BUGUN
        self._donem: dn.Donem | None = None
        self._dolu: set[int] = set()

        self.header = PageHeader("📊 Analiz", "")
        self.root.addWidget(self.header)

        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(metrics.PAGE_MARGIN_H, 8, metrics.PAGE_MARGIN_H,
                                 metrics.PAGE_MARGIN_V)
        duzen.setSpacing(8)
        duzen.addLayout(self._build_period_bar())
        self.tabs = QTabWidget()
        for kurucu in (self._build_overview, self._build_trends, self._build_products,
                       self._build_baskets, self._build_payments, self._build_profit):
            sekme = kurucu()
            self.tabs.addTab(sekme, SEKME_ADLARI[self.tabs.count()])
        self.tabs.currentChanged.connect(lambda _i: self._sekmeyi_doldur())
        duzen.addWidget(self.tabs, 1)
        self.root.addWidget(govde, 1)

    # ===================== Dönem çubuğu ==================================
    def _build_period_bar(self) -> QHBoxLayout:
        satir = QHBoxLayout()
        satir.setSpacing(6)
        self.period_group = QButtonGroup(self)
        self.period_group.setExclusive(True)
        self.period_buttons: dict[str, QPushButton] = {}
        for tur in DONEM_DUGMELERI:
            dugme = QPushButton(dn.DONEM_ADLARI[tur])
            dugme.setCheckable(True)
            dugme.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            dugme.clicked.connect(lambda _=False, t=tur: self.set_period(t))
            self.period_group.addButton(dugme)
            self.period_buttons[tur] = dugme
            satir.addWidget(dugme)
        self.start_edit = QDateEdit()
        self.end_edit = QDateEdit()
        for kutu in (self.start_edit, self.end_edit):
            kutu.setCalendarPopup(True)
            kutu.setDisplayFormat("dd.MM.yyyy")
            kutu.setProperty("scannerExempt", True)
            kutu.dateChanged.connect(lambda _d: self._ozel_degisti())
            satir.addWidget(kutu)
        satir.addStretch(1)
        return satir

    def set_period(self, tur: str, baslangic: str | None = None,
                   bitis: str | None = None) -> None:
        self.period_type = tur
        self.period_buttons[tur].setChecked(True)
        ozel = tur == dn.OZEL
        self.start_edit.setVisible(ozel)
        self.end_edit.setVisible(ozel)
        if ozel and baslangic and bitis:
            for kutu, deger in ((self.start_edit, baslangic), (self.end_edit, bitis)):
                kutu.blockSignals(True)
                kutu.setDate(QDate.fromString(deger, TARIH))
                kutu.blockSignals(False)
        if ozel:
            self._donem = self.services.analytics.donem(
                dn.OZEL, self.start_edit.date().toString(TARIH),
                self.end_edit.date().toString(TARIH))
        else:
            self._donem = self.services.analytics.donem(tur)
        self.header.set_subtitle(
            f"{self._donem.ad or dn.DONEM_ADLARI[tur]} · {self._donem.baslangic}"
            + (f" – {self._donem.bitis}" if self._donem.gun_sayisi > 1 else ""))
        self._dolu.clear()
        self._sekmeyi_doldur()

    def _ozel_degisti(self) -> None:
        if self.period_type == dn.OZEL:
            self.set_period(dn.OZEL)

    @property
    def period(self) -> dn.Donem:
        return self._donem

    # ===================== Yaşam döngüsü =================================
    def on_activated(self) -> None:
        """Her açılış: Genel Bakış + Bugün."""
        bugun = QDate.fromString(self.services.analytics.is_gunu(), TARIH)
        for kutu in (self.start_edit, self.end_edit):
            kutu.blockSignals(True)
            kutu.setDate(bugun)
            kutu.blockSignals(False)
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(GENEL)
        self.tabs.blockSignals(False)
        self.set_period(dn.BUGUN)

    def refresh(self) -> None:
        if self._donem is None:
            self.on_activated()
            return
        self._dolu.clear()
        self._sekmeyi_doldur()

    def _sekmeyi_doldur(self) -> None:
        """Yalnızca GÖRÜNEN sekme ve yalnızca bir kez (dönem değişene kadar)."""
        index = self.tabs.currentIndex()
        if self._donem is None or index in self._dolu:
            return
        doldurucu = (self._fill_overview, self._fill_trends, self._fill_products,
                     self._fill_baskets, self._fill_payments, self._fill_profit)[index]
        try:
            doldurucu()
        except Exception:
            log.exception("Analiz sekmesi doldurulamadı: %s", SEKME_ADLARI[index])
            return
        self._dolu.add(index)

    def built_tabs(self) -> set[int]:
        return set(self._dolu)

    @staticmethod
    def _kaydirmali(icerik: QWidget) -> QScrollArea:
        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        kaydirma.setWidget(icerik)
        return kaydirma

    # ===================== 1. Genel Bakış ================================
    def _build_overview(self) -> QWidget:
        icerik = QWidget()
        duzen = QVBoxLayout(icerik)
        duzen.setContentsMargins(0, 8, 0, 0)
        duzen.setSpacing(metrics.PAGE_SPACING)

        ozet = QHBoxLayout()
        ozet.setSpacing(metrics.PAGE_SPACING)
        self.revenue_card = StatCard("CİRO", "-")
        self.customers_card = StatCard("MÜŞTERİ", "-", "Tamamlanan sepet")
        self.items_card = StatCard("SATILAN ÜRÜN", "-")
        self.avg_card = StatCard("ORTALAMA SEPET", "-")
        self.profit_card = StatCard("BRÜT KÂR", "-")
        self.stock_card = StatCard("STOK DEĞERİ", "-", "Eldeki malın maliyeti")
        for kart_ in (self.revenue_card, self.customers_card, self.items_card,
                      self.avg_card, self.profit_card, self.stock_card):
            ozet.addWidget(kart_)
        duzen.addLayout(ozet)

        self.payment_card = Card()
        self.payment_card.body.addWidget(make_label("Ödeme", "sectionTitle"))
        self.payment_grid = QGridLayout()
        self.payment_grid.setSpacing(8)
        self.payment_card.body.addLayout(self.payment_grid)
        self.payment_hint = make_label("", "cardHint", wrap=True)
        self.payment_card.body.addWidget(self.payment_hint)
        duzen.addWidget(self.payment_card)

        self.attention_card = Card()
        self.attention_card.body.addWidget(make_label("Dikkat", "sectionTitle"))
        self.attention_grid = QGridLayout()
        self.attention_grid.setSpacing(8)
        self.attention_card.body.addLayout(self.attention_grid)
        self.advisory_label = make_label("", "cardHint", wrap=True)
        self.attention_card.body.addWidget(self.advisory_label)
        duzen.addWidget(self.attention_card)

        self.compare_card = Card()
        self.compare_card.body.addWidget(make_label("Karşılaştırma", "sectionTitle"))
        self.compare_table = _tablo(["Dönem", "Ciro", "İşlem", "Satılan", "Ciro değişimi"],
                                    "Dönem")
        self.compare_table.setMaximumHeight(metrics.TABLE_ROW_HEIGHT * 5)
        self.compare_card.body.addWidget(self.compare_table)
        self.compare_hint = make_label("", "cardHint", wrap=True)
        self.compare_card.body.addWidget(self.compare_hint)
        duzen.addWidget(self.compare_card)

        self.hourly_card = Card()
        self.hourly_card.body.addWidget(make_label("Saatlik Satış", "sectionTitle"))
        self.hourly_chart = SimpleBarChart()
        self.hourly_card.body.addWidget(self.hourly_chart)
        duzen.addWidget(self.hourly_card)

        self.top_card = Card()
        self.top_title = make_label("En Çok Satanlar", "sectionTitle")
        self.top_card.body.addWidget(self.top_title)
        self.top_table = _tablo(["Ürün", "Adet", "Ciro", "Kâr"], "Ürün")
        self.top_table.setMaximumHeight(metrics.TABLE_ROW_HEIGHT * 7)
        self.top_card.body.addWidget(self.top_table)
        self.top_empty = EmptyState("Bu dönemde satış yok",
                                    "Satış ekranından ürün okutunca burada görünür.")
        self.top_card.body.addWidget(self.top_empty)
        duzen.addWidget(self.top_card)

        self.slow_card = Card()
        self.slow_card.body.addWidget(make_label("Uzun Süredir Satılmayanlar", "sectionTitle"))
        self.slow_hint = make_label("", "cardHint", wrap=True)
        self.slow_card.body.addWidget(self.slow_hint)
        self.slow_table = _tablo(["Ürün", "Stok", "Bağlı Para"], "Ürün")
        self.slow_table.setMaximumHeight(metrics.TABLE_ROW_HEIGHT * 7)
        self.slow_card.body.addWidget(self.slow_table)
        duzen.addWidget(self.slow_card)
        duzen.addStretch(1)
        return self._kaydirmali(icerik)

    def _set_mode_visibility(self, sales_first: bool) -> None:
        # SALES_FIRST'te kâr, stok değeri, dikkat ve ölü stok GÖSTERİLMEZ.
        self.profit_card.setVisible(not sales_first)
        self.stock_card.setVisible(not sales_first)
        self.attention_card.setVisible(not sales_first)
        self.slow_card.setVisible(not sales_first)
        self.customers_card.setVisible(sales_first)
        self.avg_card.setVisible(sales_first)
        self.payment_card.setVisible(sales_first)
        self.hourly_card.setVisible(sales_first and self._donem.gun_sayisi == 1)
        self.top_table.setColumnHidden(self.top_table.columnCount() - 1, sales_first)

    def _fill_overview(self) -> None:
        a = self.services.analytics
        satis_once = self.services.settings.is_sales_first()
        self._set_mode_visibility(satis_once)
        g = a.genel(self._donem)
        self.revenue_card.set_value(format_tl(g.ciro), f"{g.islem} işlem")
        self.customers_card.set_value(str(g.sepet_sayisi), "Kesin sepet (Sepetli Satış)")
        self.items_card.set_value(str(g.adet))
        self.avg_card.set_value(
            format_tl(g.ortalama_sepet),
            f"Sepet başına {fmt_decimal_trim(g.sepet_basina_urun)} ürün"
            if g.sepet_sayisi else "")
        if satis_once:
            self._fill_payment_badges(g.odemeler, g.iadeler)
            if self._donem.gun_sayisi == 1:
                self.hourly_chart.set_data(
                    [(n.etiket, n.ciro) for n in a.egilim(SAATLIK, self._donem)],
                    empty_text="Bu gün henüz satış yok")
        else:
            kapsam = a.maliyet_kapsami(self._donem)
            if kapsam.baslik_kari is not None or not kapsam.toplam_ciro:
                kar_ = g.ciro - g.maliyet
                self.profit_card.set_value(
                    format_tl(kar_), f"Marj {fmt_percent(kar_ * 100 / g.ciro)}"
                    if g.ciro else "")
            else:
                self.profit_card.set_value(
                    "kapsam düşük",
                    f"Güvenilir maliyet cironun %{kapsam.guvenilir_oran * 100:.0f}'i; "
                    "Kâr sekmesine bakın")
            self.stock_card.set_value(format_tl(a.stock_value()))
            self._fill_attention()
            self._fill_slow()
        self._fill_comparison(g)
        self._fill_top()

    def _fill_payment_badges(self, odemeler, iadeler) -> None:
        self._clear_grid(self.payment_grid)
        toplam = odemeler.toplam
        if not toplam:
            self.payment_grid.addWidget(
                make_label("Bu dönemde satış yok.", "cardHint"), 0, 0)
        renkler = {"NAKİT": theme.PRIMARY, "KART": theme.CART}
        sutun = 0
        for ad, tutar in (odemeler.satirlar() if toplam else []):
            if not tutar and ad == "KART" and not self.services.settings.show_card_button():
                continue
            rozet = Badge()
            rozet.set_state(f"{ad}  {format_tl(tutar)}  ({fmt_percent(tutar * 100 / toplam)})",
                            renkler.get(ad, theme.TEXT_MUTED), theme.SURFACE_ALT)
            self.payment_grid.addWidget(rozet, 0, sutun)
            sutun += 1
        ipuclari = []
        if odemeler.kaydedilmemis:
            ipuclari.append("\"Kaydedilmemiş\", ödeme yöntemi seçilmeden önce yapılmış "
                            "satışlardır; nakit ya da kart sayılmaz.")
        if iadeler.toplam:
            ipuclari.append("Bu dönemde yapılan iadeler: " + ", ".join(
                f"{ad} {format_tl(t)}" for ad, t in iadeler.satirlar() if t)
                + " (kasa sayımı için; satışlar orijinal günde netleşir).")
        self.payment_hint.setText(" ".join(ipuclari))
        self.payment_hint.setVisible(bool(ipuclari))

    def _fill_comparison(self, g) -> None:
        a = self.services.analytics
        kiyaslar = a.karsilastirmalar(self._donem)
        satirlar = [(f"{self._donem.ad or 'Seçili dönem'}", format_tl(g.ciro), g.islem, g.adet,
                     "")]
        for donem in kiyaslar:
            o = a.genel(donem)
            satirlar.append((f"{donem.ad} ({donem.baslangic}"
                             + (f" – {donem.bitis})" if donem.gun_sayisi > 1 else ")"),
                             format_tl(o.ciro), o.islem, o.adet, _degisim(g.ciro, o.ciro)))
        _doldur(self.compare_table, satirlar)
        self.compare_hint.setText("" if kiyaslar else dn.KARSILASTIRMA_YOK)
        self.compare_hint.setVisible(not kiyaslar)

    def _fill_top(self) -> None:
        urunler = self.services.analytics.en_cok_satanlar(self._donem, limit=5)
        self.top_title.setText(f"{self._donem.ad} En Çok Satanlar")
        self.top_table.setVisible(bool(urunler))
        self.top_empty.setVisible(not urunler)
        _doldur(self.top_table, [(u.ad, u.adet, format_tl(u.ciro), format_tl(u.kar))
                                 for u in urunler])

    def _fill_attention(self) -> None:
        self._clear_grid(self.attention_grid)
        dikkat = self.services.products.attention_counts()
        uyarilar = self.services.db.advisories()
        sutun = 0
        for anahtar, durum in (("kontrol_gerekli", StockState.NEEDS_CHECK),
                               ("kritik", StockState.CRITICAL), ("dusuk", StockState.LOW),
                               ("henuz_sayilmadi", StockState.NOT_COUNTED)):
            adet = dikkat.get(anahtar, 0)
            if not adet:
                continue
            on, arka = theme.level_colors(int(durum))
            rozet = Badge()
            rozet.set_state(f"{adet} ürün — {STOCK_STATE_LABELS[durum]}", on, arka)
            self.attention_grid.addWidget(rozet, 0, sutun)
            sutun += 1
        if sutun == 0:
            self.attention_grid.addWidget(
                make_label("Şu an dikkat gerektiren bir durum yok.", "cardHint"), 0, 0)
        self.advisory_label.setText(" ".join(uyarilar))
        self.advisory_label.setVisible(bool(uyarilar))

    def _fill_slow(self) -> None:
        gun = self.services.settings.slow_moving_days()
        yavaslar = self.services.analytics.slow_movers(limit=10)
        bagli = self.services.analytics.dead_capital()
        self.slow_hint.setText(
            f"Son {gun} gündür satılmayan ürünler · toplam bağlı para: {format_tl(bagli)}"
            if yavaslar else f"Son {gun} gündür satılmayan ürün yok.")
        self.slow_table.setVisible(bool(yavaslar))
        _doldur(self.slow_table, [(u["name"], u["current_stock"], format_tl(u["stock_value"]))
                                  for u in yavaslar])

    # ===================== 2. Eğilimler ==================================
    def _build_trends(self) -> QWidget:
        icerik = QWidget()
        duzen = QVBoxLayout(icerik)
        duzen.setContentsMargins(0, 8, 0, 0)
        ust = QHBoxLayout()
        ust.addWidget(make_label("Gösterim:", "cardHint"))
        self.trend_combo = QComboBox()
        for tur, ad in EGILIM_ADLARI.items():
            self.trend_combo.addItem(ad, tur)
        self.trend_combo.activated.connect(lambda _i: self._fill_trends(otomatik=False))
        ust.addWidget(self.trend_combo)
        self.trend_measure = QComboBox()
        self.trend_measure.addItem("Ciro", TL)
        self.trend_measure.addItem("İşlem sayısı", ADET)
        self.trend_measure.activated.connect(lambda _i: self._fill_trends(otomatik=False))
        ust.addWidget(self.trend_measure)
        ust.addStretch(1)
        duzen.addLayout(ust)
        self.trend_chart = SimpleBarChart()
        self.trend_chart.setMinimumHeight(220)
        duzen.addWidget(self.trend_chart)
        self.trend_table = _tablo(["Dönem", "Ciro", "İşlem", "Satılan", "Önceki dönem"],
                                  "Dönem")
        duzen.addWidget(self.trend_table, 1)
        return icerik

    def _varsayilan_egilim(self) -> str:
        gun = self._donem.gun_sayisi
        if gun == 1:
            return SAATLIK
        if gun <= 62:
            return GUNLUK
        if gun <= 200:
            return HAFTALIK
        return AYLIK

    def _fill_trends(self, otomatik: bool = True) -> None:
        a = self.services.analytics
        if otomatik:
            self.trend_combo.setCurrentIndex(
                self.trend_combo.findData(self._varsayilan_egilim()))
        tur = self.trend_combo.currentData()
        olcu = self.trend_measure.currentData()
        noktalar = a.egilim(tur, self._donem)
        kiyaslar = a.karsilastirmalar(self._donem)
        onceki = a.egilim(tur, kiyaslar[0]) if kiyaslar else []
        alan = (lambda n: n.ciro) if olcu == TL else (lambda n: n.islem)
        karsi = [alan(n) for n in onceki] if len(onceki) == len(noktalar) or \
            tur in (SAATLIK, HAFTANIN_GUNU) else []
        self.trend_chart.set_data(
            [(n.etiket, alan(n)) for n in noktalar], comparison=karsi, value_format=olcu,
            caption=f"{EGILIM_ADLARI[tur]} · {self._donem.ad or ''}"
            + (f" · gri: {kiyaslar[0].ad}" if karsi else ""),
            empty_text="Bu dönemde satış yok")
        satirlar = []
        for i, n in enumerate(noktalar):
            once = format_tl(onceki[i].ciro) if karsi and i < len(onceki) else ""
            satirlar.append((n.etiket, format_tl(n.ciro), n.islem, n.adet, once))
        _doldur(self.trend_table, satirlar)

    # ===================== 3. Ürünler ====================================
    def _build_products(self) -> QWidget:
        icerik = QWidget()
        duzen = QVBoxLayout(icerik)
        duzen.setContentsMargins(0, 8, 0, 0)
        ust = QHBoxLayout()
        self.product_view = QComboBox()
        for anahtar, ad in URUN_GORUNUMLERI.items():
            self.product_view.addItem(ad, anahtar)
        self.product_view.activated.connect(lambda _i: self._fill_products())
        ust.addWidget(self.product_view)
        ust.addStretch(1)
        duzen.addLayout(ust)
        self.product_hint = make_label("", "cardHint", wrap=True)
        duzen.addWidget(self.product_hint)
        self.product_table = _tablo(["Ad", "Adet", "Ciro", "Pay"], "Ad")
        self.product_table.itemSelectionChanged.connect(self._urun_egilimi)
        duzen.addWidget(self.product_table, 1)
        self.product_trend = SimpleBarChart()
        duzen.addWidget(self.product_trend)
        self._urun_kimlikleri: list = []
        return icerik

    def _fill_products(self) -> None:
        a = self.services.analytics
        gorunum = self.product_view.currentData()
        satirlar: list[tuple] = []
        self._urun_kimlikleri = []
        self.product_trend.setVisible(gorunum in ("ADET", "CIRO", "AZ"))
        if gorunum == "SATILMAYAN":
            gun = self.services.settings.slow_moving_days()
            urunler = a.slow_movers(limit=200)
            self.product_table.setHorizontalHeaderLabels(["Ürün", "Stok", "Bağlı para", ""])
            satirlar = [(u["name"], u["current_stock"], format_tl(u["stock_value"]), "")
                        for u in urunler]
            self.product_hint.setText(f"Son {gun} gündür satılmayan, stoğu olan ürünler "
                                      "(dönemden bağımsız).")
        else:
            if gorunum in ("ADET", "CIRO"):
                urunler = a.en_cok_satanlar(self._donem, ciroya_gore=gorunum == "CIRO",
                                            limit=50)
            elif gorunum == "AZ":
                urunler = a.az_satanlar(self._donem, limit=50)
            elif gorunum == "KATEGORI":
                urunler = a.kategori_kirilimi(self._donem)
            else:
                urunler = a.marka_kirilimi(self._donem)
            toplam = sum(u.ciro for u in urunler) or 1
            self.product_table.setHorizontalHeaderLabels(["Ad", "Adet", "Ciro", "Pay"])
            for u in urunler:
                satirlar.append((u.ad, u.adet, format_tl(u.ciro),
                                 fmt_percent(u.ciro * 100 / toplam)))
                self._urun_kimlikleri.append(u.product_id if gorunum in ("ADET", "CIRO", "AZ")
                                             else None)
                for alt in u.alt:
                    satirlar.append((f"    {alt.ad}", alt.adet, format_tl(alt.ciro),
                                     fmt_percent(alt.ciro * 100 / toplam)))
                    self._urun_kimlikleri.append(None)
            self.product_hint.setText(
                "Kategori ve marka ürünlerin BUGÜNKÜ sınıflandırmasına göredir; alt "
                "kategoriler üst kategoriye toplanır." if gorunum in ("KATEGORI", "MARKA")
                else ("" if satirlar else "Bu dönemde satış yok."))
        _doldur(self.product_table, satirlar)
        self.product_trend.set_data([], empty_text="Eğilimi görmek için bir ürün seçin")

    def _urun_egilimi(self) -> None:
        satir = self.product_table.currentRow()
        if not 0 <= satir < len(self._urun_kimlikleri) or self._urun_kimlikleri[satir] is None:
            return
        seri = self.services.analytics.urun_egilimi(self._urun_kimlikleri[satir],
                                                     self._donem)
        self.product_trend.set_data([(g[8:10] + "." + g[5:7], adet) for g, adet, _ in seri],
                                    value_format=ADET, caption="Günlük satılan adet",
                                    empty_text="Bu dönemde satış yok")

    # ===================== 4. Sepetler ===================================
    def _build_baskets(self) -> QWidget:
        icerik = QWidget()
        duzen = QVBoxLayout(icerik)
        duzen.setContentsMargins(0, 8, 0, 0)
        self.basket_summary = make_label("", "cardTitle", wrap=True)
        duzen.addWidget(self.basket_summary)
        duzen.addWidget(make_label(sepetler.ACIKLAMA + " Yalnızca Sepetli Satış sepetleri "
                                   "sayılır; Hızlı Satış'tan çıkarılan gruplar tahmindir ve "
                                   "buraya girmez.", "cardHint", wrap=True))
        ust = QHBoxLayout()
        ust.addWidget(make_label("En az birlikte geçen sepet:", "cardHint"))
        self.support_spin = QSpinBox()
        self.support_spin.setRange(1, 1000)
        self.support_spin.setValue(sepetler.VARSAYILAN_EN_AZ_DESTEK)
        self.support_spin.setProperty("scannerExempt", True)
        self.support_spin.valueChanged.connect(lambda _v: self._fill_baskets())
        ust.addWidget(self.support_spin)
        ust.addStretch(1)
        duzen.addLayout(ust)
        self.pairs_table = _tablo(["Birlikte alınanlar", "Birlikte", "Açıklama"], "Açıklama")
        duzen.addWidget(make_label("Ürün çiftleri", "sectionTitle"))
        duzen.addWidget(self.pairs_table, 1)
        duzen.addWidget(make_label("Kategori çiftleri", "sectionTitle"))
        self.category_pairs_table = _tablo(["Birlikte alınanlar", "Birlikte", "Açıklama"],
                                           "Açıklama")
        duzen.addWidget(self.category_pairs_table, 1)
        return icerik

    def _fill_baskets(self) -> None:
        a = self.services.analytics
        g = a.genel(self._donem)
        if g.sepet_sayisi:
            self.basket_summary.setText(
                f"{g.sepet_sayisi} kesin sepet · ortalama {format_tl(g.ortalama_sepet)} · "
                f"sepet başına {fmt_decimal_trim(g.sepet_basina_urun)} ürün")
        else:
            self.basket_summary.setText("Bu dönemde kesin sepet yok (Sepetli Satış).")
        destek = self.support_spin.value()
        for tablo, ciftler in ((self.pairs_table, a.urun_ciftleri(self._donem, destek)),
                               (self.category_pairs_table,
                                a.kategori_ciftleri(self._donem, destek))):
            _doldur(tablo, [(f"{c.a_ad} + {c.b_ad}", c.birlikte, c.cumle()) for c in ciftler])

    # ===================== 5. Ödemeler ===================================
    def _build_payments(self) -> QWidget:
        icerik = QWidget()
        duzen = QVBoxLayout(icerik)
        duzen.setContentsMargins(0, 8, 0, 0)
        duzen.addWidget(make_label("Satışlar (orijinal satış gününe göre)", "sectionTitle"))
        self.payment_table = _tablo(["Ödeme", "Tutar", "Pay"], "Ödeme")
        duzen.addWidget(self.payment_table)
        duzen.addWidget(make_label("Bu dönemde yapılan iadeler", "sectionTitle"))
        duzen.addWidget(make_label(
            "Geri alma gününe göre: dün yapılan kartlı satışın bugün geri alınması bugünün "
            "iadesidir (kasa sayımı için). Satış ölçüleri ise orijinal günde netleşir.",
            "cardHint", wrap=True))
        self.refund_table = _tablo(["Ödeme", "İade"], "Ödeme")
        duzen.addWidget(self.refund_table)
        duzen.addStretch(1)
        return icerik

    def _fill_payments(self) -> None:
        g = self.services.analytics.genel(self._donem)
        toplam = g.odemeler.toplam or 1
        _doldur(self.payment_table, [(ad, format_tl(t), fmt_percent(t * 100 / toplam))
                                     for ad, t in g.odemeler.satirlar()])
        iadeler = [(ad, format_tl(t)) for ad, t in g.iadeler.satirlar() if t]
        _doldur(self.refund_table, iadeler or [("Bu dönemde iade yok.", "")])

    # ===================== 6. Kâr ve Maliyet Kapsamı =====================
    def _build_profit(self) -> QWidget:
        icerik = QWidget()
        duzen = QVBoxLayout(icerik)
        duzen.setContentsMargins(0, 8, 0, 0)
        self.coverage_label = make_label("", "cardTitle", wrap=True)
        duzen.addWidget(self.coverage_label)
        self.profit_headline = make_label("", "cardValue", wrap=True)
        duzen.addWidget(self.profit_headline)
        self.tier_table = _tablo(["Maliyet bilgisi", "Ciro", "Ciro payı", "Maliyet",
                                  "Brüt kâr", "Satır"], "Maliyet bilgisi")
        duzen.addWidget(self.tier_table)
        duzen.addWidget(make_label(
            "Güvenilir maliyet: alış fiyatı bilinen mallardan satılmış. Tahmini maliyet: "
            "maliyeti bilinmeyen (ör. sayımla ya da alış fiyatsız gelen) mal aynı stoğa "
            "karışmış ya da satış stok yokken yapılmış. Maliyeti bilinmiyor: hiçbir alış "
            "bilgisi yok. Fiyatlar KDV dahil; kâr tahminidir.", "cardHint", wrap=True))
        duzen.addStretch(1)
        return icerik

    def _fill_profit(self) -> None:
        kapsam = self.services.analytics.maliyet_kapsami(self._donem)
        toplam = kapsam.toplam_ciro
        if not toplam:
            self.coverage_label.setText("Bu dönemde satış yok.")
            self.profit_headline.setText("")
        else:
            self.coverage_label.setText(
                f"Maliyet kapsamı: cironun %{kapsam.guvenilir_oran * 100:.0f}'inin alış "
                "fiyatı güvenilir.")
            if kapsam.baslik_kari is not None:
                self.profit_headline.setText(
                    f"Brüt kâr: {format_tl(kapsam.baslik_kari)} "
                    f"(marj {fmt_percent(kapsam.baslik_kari * 100 / toplam)})")
            else:
                g = kapsam.guvenilir
                self.profit_headline.setText(
                    f"Kâr yalnızca kapsanan kısım için: {format_tl(g.kar)} "
                    f"({format_tl(g.ciro)} ciro üzerinden). Tek bir toplam kâr rakamı "
                    f"verilmez: güvenilir pay %{kar.BASLIK_ESIGI * 100:.0f}'in altında.")
        satirlar = []
        for ad, katman in kapsam.katmanlar():
            satirlar.append((ad, format_tl(katman.ciro),
                             fmt_percent(katman.ciro * 100 / toplam) if toplam else "—",
                             format_tl(katman.maliyet) if katman.maliyet else "—",
                             format_tl(katman.kar) if katman.maliyet else "—", katman.satir))
        _doldur(self.tier_table, satirlar)

    # ===================== Ortak =========================================
    @staticmethod
    def _clear_grid(grid: QGridLayout) -> None:
        while grid.count():
            oge = grid.takeAt(0)
            if oge.widget() is not None:
                oge.widget().deleteLater()
