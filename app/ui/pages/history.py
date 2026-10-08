"""Geçmiş: satışlar, stok girişleri, sayımlar ve işlem günlüğü.

Normal kullanıcı günlük işinde buraya BAKMAZ. Bir şey ters gittiğinde ya da
"dün ne olmuştu?" diye merak edildiğinde açılır.

Satışlar (V1.2 M12a): dönem / kip / ödeme / durum süzgeçleri, ödeme sütunu,
doğru kalem sayısı (D-15: "+N kalem" artık satır sayısıdır, adet değil) ve
seçili satışın ayrıntısı (satırlar, geri alma zamanı ve günü). Önceki bir
güne ait satışı geri almak PIN ister (GECMIS_SATIS_GERI_AL).

Listeler DAİMA sayfalıdır: yılların geçmişi tek seferde belleğe alınmaz.
Satış sayfaları anahtar kümelidir (her sayfa aynı hızda gelir).
"""
from __future__ import annotations

import datetime
import logging

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.analytics import donemler as dn
from app.core.errors import DomainError
from app.core.models import PAYMENT_LABELS, PaymentMethod, SaleMode
from app.core.money import format_tl
from app.core.tr import fmt_date, fmt_datetime
from app.services.sale_service import (
    DURUM_GERI_ALINDI,
    DURUM_TAMAM,
    ODEME_KAYITSIZ,
    SatisFiltresi,
)
from app.ui import metrics, theme
from app.ui.dialogs.common_dialogs import ask_confirm, scanning_suspended, show_error, show_info
from app.ui.pages.base import Page
from app.ui.widgets.common import (
    Card,
    EmptyState,
    FlowLayout,
    PageHeader,
    labeled,
    make_label,
    setup_table,
    stretch_column,
)

log = logging.getLogger(__name__)

PAGE_SIZE = 100
#: Dönem seçeneği: tarih süzgeci yok (en yeni satışlar üstte).
TUMU = "TUMU"
DONEMLER = (TUMU, dn.BUGUN, dn.DUN, dn.SON_7, dn.BU_HAFTA, dn.GECEN_HAFTA,
            dn.BU_AY, dn.GECEN_AY, dn.OZEL)
TARIH = "yyyy-MM-dd"
KIP_ADLARI = {SaleMode.CART: "Sepetli", SaleMode.QUICK: "Hızlı"}


def _odeme_adi(yontem: str | None) -> str:
    return PAYMENT_LABELS.get(yontem, yontem or "")


class HistoryPage(Page):
    nav_title = "🕘  Geçmiş"
    nav_key = "gecmis"
    nav_group = "yonetim"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)
        self._sales: list = []
        #: Anahtar kümeli sayfalama: her sayfanın "bundan küçük kimlik" sınırı.
        self._sayfa_sinirlari: list[int | None] = [None]

        self.header = PageHeader("🕘 Geçmiş", "Yapılan işlemlerin kaydı.")
        self.root.addWidget(self.header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_sales_tab(), "Satışlar")
        self.tabs.addTab(self._build_receipts_tab(), "Stok Girişleri")
        self.tabs.addTab(self._build_counts_tab(), "Sayımlar")
        self.tabs.addTab(self._build_audit_tab(), "İşlem Günlüğü")
        self.tabs.currentChanged.connect(lambda _: self.refresh())
        self.root.addWidget(self.tabs, 1)

    # ===================== Sekmeler ======================================
    def _build_sales_tab(self) -> QWidget:
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        duzen.setContentsMargins(12, 12, 12, 12)
        duzen.setSpacing(10)
        duzen.addWidget(self._build_sales_filters())

        # Sol: liste (boşsa açıklama), sağ: seçili satışın ayrıntısı.
        self.sales_table = QTableWidget(0, 7)
        setup_table(
            self.sales_table,
            ["Zaman", "Kip", "Ödeme", "Ürün", "Adet", "Tutar", "Durum"],
        )
        stretch_column(self.sales_table, "Ürün")
        self.sales_table.itemSelectionChanged.connect(self._secim_degisti)
        self.sales_empty = EmptyState("Satış yok", "")
        self.sales_stack = QStackedWidget()
        self.sales_stack.addWidget(self.sales_table)
        self.sales_stack.addWidget(self.sales_empty)

        bolucu = QSplitter(Qt.Orientation.Horizontal)
        bolucu.setChildrenCollapsible(False)
        bolucu.addWidget(self.sales_stack)
        bolucu.addWidget(self._build_sale_detail())
        bolucu.setStretchFactor(0, 5)
        bolucu.setStretchFactor(1, 2)
        duzen.addWidget(bolucu, 1)

        alt = QHBoxLayout()
        self.sales_summary = make_label("", "cardHint")
        alt.addWidget(self.sales_summary, 1)
        self.prev_button = QPushButton("‹ Önceki")
        self.prev_button.clicked.connect(lambda: self._page_sales(-1))
        alt.addWidget(self.prev_button)
        self.page_label = make_label("", "cardHint")
        alt.addWidget(self.page_label)
        self.next_button = QPushButton("Sonraki ›")
        self.next_button.clicked.connect(lambda: self._page_sales(1))
        alt.addWidget(self.next_button)

        self.reverse_button = QPushButton("Seçili Satışı Geri Al")
        self.reverse_button.setObjectName("danger")
        self.reverse_button.clicked.connect(self._reverse_sale)
        alt.addSpacing(16)
        alt.addWidget(self.reverse_button)
        duzen.addLayout(alt)
        return sayfa

    def _build_sales_filters(self) -> QWidget:
        # Akış: dar pencerede süzgeçler alt satıra iner (M12b).
        kap = QWidget()
        satir = FlowLayout(kap, spacing=12)

        def secim(etiket: str, secenekler: list[tuple[str, object]]) -> QComboBox:
            kutu = QComboBox()
            for ad, deger in secenekler:
                kutu.addItem(ad, deger)
            kutu.currentIndexChanged.connect(lambda _i: self._suzgec_degisti())
            satir.addWidget(labeled(etiket, kutu))
            return kutu

        self.period_combo = secim("Dönem", [
            ("Tümü" if t == TUMU else dn.DONEM_ADLARI[t], t) for t in DONEMLER])
        self.start_edit = QDateEdit()
        self.end_edit = QDateEdit()
        bugun = QDate.fromString(self.services.settings.calendar().today(), TARIH)
        for kutu in (self.start_edit, self.end_edit):
            kutu.setCalendarPopup(True)
            kutu.setDisplayFormat("dd.MM.yyyy")
            kutu.setProperty("scannerExempt", True)
            kutu.setDate(bugun)
            kutu.setVisible(False)
            kutu.dateChanged.connect(lambda _d: self._suzgec_degisti())
            satir.addWidget(kutu)
        self.mode_combo = secim("Kip", [
            ("Tümü", None), (KIP_ADLARI[SaleMode.CART], SaleMode.CART),
            (KIP_ADLARI[SaleMode.QUICK], SaleMode.QUICK)])
        self.payment_combo = secim("Ödeme", [
            ("Tümü", None), (_odeme_adi(PaymentMethod.CASH), PaymentMethod.CASH),
            (_odeme_adi(PaymentMethod.CARD), PaymentMethod.CARD),
            (_odeme_adi(None), ODEME_KAYITSIZ)])
        self.status_combo = secim("Durum", [
            ("Tümü", None), ("Tamamlanan", DURUM_TAMAM), ("Geri alınan", DURUM_GERI_ALINDI)])
        return kap

    def _build_sale_detail(self) -> QWidget:
        kart = Card()
        kart.setMinimumWidth(260)
        kart.body.addWidget(make_label("Satış ayrıntısı", "cardTitle"))
        self.detail_stack = QStackedWidget()
        self.detail_empty = EmptyState(
            "Satış seçilmedi", "Ayrıntıyı görmek için listeden bir satış seçin.")
        icerik = QWidget()
        duzen = QVBoxLayout(icerik)
        duzen.setContentsMargins(0, 0, 0, 0)
        duzen.setSpacing(6)
        self.detail_info = make_label("", wrap=True)
        self.detail_status = make_label("", wrap=True)
        self.detail_lines = QTableWidget(0, 4)
        setup_table(self.detail_lines, ["Ürün", "Adet", "Birim", "Tutar"])
        stretch_column(self.detail_lines, "Ürün")
        duzen.addWidget(self.detail_info)
        duzen.addWidget(self.detail_status)
        duzen.addWidget(self.detail_lines, 1)
        self.detail_stack.addWidget(self.detail_empty)
        self.detail_stack.addWidget(icerik)
        kart.body.addWidget(self.detail_stack, 1)
        return kart

    def _build_receipts_tab(self) -> QWidget:
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        duzen.setContentsMargins(12, 12, 12, 12)
        duzen.setSpacing(10)

        self.receipts_table = QTableWidget(0, 5)
        setup_table(
            self.receipts_table,
            ["Tarih", "Tedarikçi", "İrsaliye", "Kalem", "Tutar"],
        )
        stretch_column(self.receipts_table, "Tedarikçi")
        duzen.addWidget(self.receipts_table, 1)

        alt = QHBoxLayout()
        alt.addStretch(1)
        self.reverse_receipt_button = QPushButton("Seçili Girişi Geri Al")
        self.reverse_receipt_button.clicked.connect(self._reverse_receipt)
        alt.addWidget(self.reverse_receipt_button)
        duzen.addLayout(alt)
        return sayfa

    def _build_counts_tab(self) -> QWidget:
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        duzen.setContentsMargins(12, 12, 12, 12)
        self.counts_table = QTableWidget(0, 5)
        setup_table(
            self.counts_table,
            ["Tarih", "Kapsam", "Durum", "Adet Farkı", "Değer Farkı"],
        )
        duzen.addWidget(self.counts_table, 1)
        return sayfa

    def _build_audit_tab(self) -> QWidget:
        sayfa = QWidget()
        duzen = QVBoxLayout(sayfa)
        duzen.setContentsMargins(12, 12, 12, 12)
        self.audit_table = QTableWidget(0, 2)
        setup_table(self.audit_table, ["Zaman", "İşlem"])
        stretch_column(self.audit_table, "İşlem")
        duzen.addWidget(self.audit_table, 1)
        return sayfa

    # ===================== Veri ==========================================
    def refresh(self) -> None:
        try:
            index = self.tabs.currentIndex()
            if index == 0:
                self._fill_sales()
            elif index == 1:
                self._fill_receipts()
            elif index == 2:
                self._fill_counts()
            else:
                self._fill_audit()
        except Exception:
            log.exception("Geçmiş okunamadı")

    # -- Satış süzgeci ve sayfalama --------------------------------------
    def sales_filter(self) -> SatisFiltresi:
        tur = self.period_combo.currentData()
        baslangic = bitis = None
        if tur == dn.OZEL:
            baslangic = self.start_edit.date().toString(TARIH)
            bitis = self.end_edit.date().toString(TARIH)
            if baslangic > bitis:
                baslangic, bitis = bitis, baslangic
        elif tur != TUMU:
            donem = dn.hazir(tur, self.services.settings.calendar().today())
            baslangic, bitis = donem.baslangic, donem.bitis
        return SatisFiltresi(
            baslangic=baslangic, bitis=bitis, kip=self.mode_combo.currentData(),
            odeme=self.payment_combo.currentData(), durum=self.status_combo.currentData())

    def _suzgec_degisti(self) -> None:
        ozel = self.period_combo.currentData() == dn.OZEL
        self.start_edit.setVisible(ozel)
        self.end_edit.setVisible(ozel)
        self._sayfa_sinirlari = [None]
        self._fill_sales()

    def _page_sales(self, direction: int) -> None:
        if direction > 0 and len(self._sales) >= PAGE_SIZE:
            self._sayfa_sinirlari.append(self._sales[-1]["id"])
        elif direction < 0 and len(self._sayfa_sinirlari) > 1:
            self._sayfa_sinirlari.pop()
        else:
            return
        self._fill_sales()

    def _fill_sales(self) -> None:
        filtre = self.sales_filter()
        satislar = self.services.sales.history(
            filtre, limit=PAGE_SIZE, once_id=self._sayfa_sinirlari[-1])
        self._sales = satislar
        self.sales_table.setRowCount(len(satislar))
        for satir, satis in enumerate(satislar):
            zaman = fmt_datetime(
                datetime.datetime.fromtimestamp(satis["created_at_utc"])
            )
            urun = satis["ilk_urun"] or "-"
            if satis["satir_sayisi"] > 1:                   # D-15: satır, adet değil
                urun += f"  (+{satis['satir_sayisi'] - 1} kalem)"
            durum = "Geri alındı" if satis["is_reversed"] else "Tamam"

            hucreler = (
                QTableWidgetItem(zaman),
                QTableWidgetItem(KIP_ADLARI.get(satis["sale_mode"], satis["sale_mode"])),
                QTableWidgetItem(_odeme_adi(satis["payment_method"])),
                QTableWidgetItem(urun),
                QTableWidgetItem(str(satis["item_count"])),
                QTableWidgetItem(format_tl(satis["total_amount"])),
                QTableWidgetItem(durum),
            )
            for hucre in hucreler[4:6]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            if satis["is_reversed"]:
                for hucre in hucreler:
                    hucre.setForeground(Qt.GlobalColor.gray)
            for sutun, hucre in enumerate(hucreler):
                self.sales_table.setItem(satir, sutun, hucre)

        self._bos_durum(filtre)
        sayfa = len(self._sayfa_sinirlari)
        self.prev_button.setEnabled(sayfa > 1)
        self.next_button.setEnabled(len(satislar) >= PAGE_SIZE)
        self.page_label.setText(f"Sayfa {sayfa}")
        ozet = self.services.sales.history_summary(filtre)
        self.sales_summary.setText(
            "En yeni satışlar üstte." if ozet is None else
            f"{ozet.satis_sayisi} satış · {ozet.geri_alinan} geri alındı · "
            f"net {format_tl(ozet.net_tutar)}")
        self._show_detail(None)

    def _bos_durum(self, filtre: SatisFiltresi) -> None:
        if self._sales:
            self.sales_stack.setCurrentWidget(self.sales_table)
            return
        if filtre == SatisFiltresi():
            self.sales_empty.set_text(
                "Henüz satış yok", "Satışlar yapıldıkça burada en yeni üstte listelenir.")
        else:
            self.sales_empty.set_text(
                "Bu süzgeçle satış yok", "Dönemi ya da süzgeçleri değiştirip yeniden bakın.")
        self.sales_stack.setCurrentWidget(self.sales_empty)

    # -- Ayrıntı -----------------------------------------------------------
    def _secili_satis(self):
        index = self.sales_table.currentRow()
        if 0 <= index < len(self._sales) and self.sales_table.selectionModel().hasSelection():
            return self._sales[index]
        return None

    def _secim_degisti(self) -> None:
        satis = self._secili_satis()
        self._show_detail(None if satis is None else satis["id"])

    def _show_detail(self, sale_id: int | None) -> None:
        ayrinti = None if sale_id is None else self.services.sales.detail(sale_id)
        self.reverse_button.setEnabled(
            ayrinti is not None and not ayrinti.satis["is_reversed"])
        if ayrinti is None:
            self.detail_stack.setCurrentWidget(self.detail_empty)
            return
        s = ayrinti.satis
        zaman = fmt_datetime(datetime.datetime.fromtimestamp(s["created_at_utc"]))
        self.detail_info.setText(
            f"{zaman} · iş günü {fmt_date(s['business_date'])}\n"
            f"{KIP_ADLARI.get(s['sale_mode'], s['sale_mode'])} · "
            f"{_odeme_adi(s['payment_method'])}\n"
            f"Toplam {format_tl(s['total_amount'])} · {s['item_count']} adet, "
            f"{ayrinti.satir_sayisi} kalem")
        if ayrinti.geri_alma is not None:
            g = ayrinti.geri_alma
            geri_zaman = fmt_datetime(datetime.datetime.fromtimestamp(g["created_at_utc"]))
            metin = f"Geri alındı: {geri_zaman}"
            if g["business_date"] != s["business_date"]:
                metin += (f" (iş günü {fmt_date(g['business_date'])}; iade o günün "
                          "iadelerinde görünür)")
            self.detail_status.setText(metin)
            self.detail_status.setStyleSheet(f"color: {theme.DANGER}; font-weight: 600;")
        else:
            self.detail_status.setText("Tamamlandı")
            self.detail_status.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        self.detail_lines.setRowCount(len(ayrinti.satirlar))
        for satir, kalem in enumerate(ayrinti.satirlar):
            hucreler = (
                QTableWidgetItem(kalem["product_name_snapshot"]),
                QTableWidgetItem(str(kalem["quantity"])),
                QTableWidgetItem(format_tl(kalem["unit_price"])),
                QTableWidgetItem(format_tl(kalem["line_total"])),
            )
            if kalem["barcode_used"]:
                hucreler[0].setToolTip(f"Barkod: {kalem['barcode_used']}")
            for hucre in hucreler[1:]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            for sutun, hucre in enumerate(hucreler):
                self.detail_lines.setItem(satir, sutun, hucre)
        self.detail_stack.setCurrentIndex(1)

    def _fill_receipts(self) -> None:
        fisler = self.services.purchases.history(limit=PAGE_SIZE)
        self._receipts = fisler
        self.receipts_table.setRowCount(len(fisler))
        for satir, fis in enumerate(fisler):
            geri_alindi = self.services.purchases.is_reversed(fis["id"])
            ad = fis["tedarikci"] or "-"
            if fis["reverses_receipt_id"]:
                ad += "  (geri alma kaydı)"
            elif geri_alindi:
                ad += "  (geri alındı)"
            hucreler = (
                QTableWidgetItem(fmt_date(fis["receipt_date"])),
                QTableWidgetItem(ad),
                QTableWidgetItem(fis["invoice_no"] or "-"),
                QTableWidgetItem(str(fis["line_count"])),
                QTableWidgetItem(format_tl(fis["total_cost"])),
            )
            for hucre in hucreler[3:]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(hucreler):
                self.receipts_table.setItem(satir, sutun, hucre)

    def _fill_counts(self) -> None:
        sayimlar = self.services.counts.history(limit=PAGE_SIZE)
        self.counts_table.setRowCount(len(sayimlar))
        for satir, sayim in enumerate(sayimlar):
            zaman = fmt_datetime(
                datetime.datetime.fromtimestamp(sayim["created_at_utc"])
            )
            durum = {
                "COMMITTED": "Tamamlandı",
                "CANCELLED": "İptal edildi",
                "DRAFT": "Sürüyor",
            }.get(sayim["status"], sayim["status"])
            hucreler = (
                QTableWidgetItem(zaman),
                QTableWidgetItem("Tüm Dükkân" if sayim["scope"] == "ALL" else "Bölüm"),
                QTableWidgetItem(durum),
                QTableWidgetItem(f"{sayim['total_diff_qty']:+d}"),
                QTableWidgetItem(format_tl(sayim["total_diff_value"])),
            )
            for hucre in hucreler[3:]:
                hucre.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
            for sutun, hucre in enumerate(hucreler):
                self.counts_table.setItem(satir, sutun, hucre)

    def _fill_audit(self) -> None:
        kayitlar = self.services.audit.recent(limit=PAGE_SIZE)
        self.audit_table.setRowCount(len(kayitlar))
        for satir, kayit in enumerate(kayitlar):
            zaman = fmt_datetime(
                datetime.datetime.fromtimestamp(kayit["created_at_utc"])
            )
            self.audit_table.setItem(satir, 0, QTableWidgetItem(zaman))
            self.audit_table.setItem(satir, 1, QTableWidgetItem(kayit["summary_tr"]))

    # ===================== Eylemler ======================================
    def _reverse_sale(self) -> None:
        index = self.sales_table.currentRow()
        if index < 0 or index >= len(self._sales):
            return
        satis = self._sales[index]
        if satis["is_reversed"]:
            show_error(self, "Bu satış daha önce geri alınmış.")
            return
        from app.services.security_service import ProtectedAction

        if not self.guard_require(ProtectedAction.GECMIS_SATIS_GERI_AL):
            return

        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self,
                f"{format_tl(satis['total_amount'])} tutarındaki satış geri alınsın mı?",
                self._geri_alma_aciklamasi(satis),
                accept_text="Evet, geri al",
            )
        if not onay:
            return
        try:
            self.services.sales.reverse_sale(satis["id"])
        except DomainError as hata:
            show_error(self, hata.message)
            return
        self.refresh()
        self.main_window.refresh_today()

    def _geri_alma_aciklamasi(self, satis) -> str:
        """Onay metni: kasada ne yapılacağını ve cironun nereye yazılacağını söyler."""
        satirlar = ["Ürünler stoğa geri eklenir. Kayıt silinmez, geri alındı olarak "
                    "işaretlenir."]
        if satis["business_date"] != self.services.settings.calendar().today():
            satirlar.append(
                f"Bu satış {fmt_date(satis['business_date'])} tarihli: ciro o günden "
                "düşülür, iade bugünün iadeleri arasında görünür.")
        if satis["payment_method"] == PaymentMethod.CARD:
            satirlar.append("Kartla ödenmiş: parayı banka POS cihazından ayrıca iade edin.")
        elif satis["payment_method"] == PaymentMethod.CASH:
            satirlar.append("Nakit ödenmiş: parayı kasadan iade edin.")
        return "\n\n".join(satirlar)

    def _reverse_receipt(self) -> None:
        index = self.receipts_table.currentRow()
        if index < 0 or index >= len(getattr(self, "_receipts", [])):
            return
        fis = self._receipts[index]
        from app.services.security_service import ProtectedAction

        if not self.guard_require(ProtectedAction.FIS_GERI_AL):
            return

        # Servis KARAR VERİR, pencere yalnızca çizer.
        onizleme = self.services.purchases.reversal_preview(fis["id"])
        if onizleme.reason:
            with scanning_suspended(self.main_window.router):
                show_info(self, "Bu giriş geri alınamıyor", onizleme.reason)
            return
        if not onizleme.allowed:
            adlar = ", ".join(onizleme.blocking_names[:5])
            with scanning_suspended(self.main_window.router):
                show_info(
                    self, "Bu giriş geri alınamıyor",
                    "Bu üründen sonra satış ya da yeni giriş yapılmış: "
                    f"{adlar}.\n\nStok değerinin bozulmaması için otomatik geri alma "
                    "yapılmaz. Bunun yerine Stok Durumu ekranından düzeltme "
                    "girişi yapabilirsiniz.",
                )
            return

        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, "Bu stok girişi geri alınsın mı?",
                f"{format_tl(fis['total_cost'])} tutarındaki giriş stoktan düşülür.",
                accept_text="Evet, geri al", danger=True,
            )
        if not onay:
            return
        try:
            self.services.purchases.reverse(fis["id"])
        except DomainError as hata:
            show_error(self, hata.message)
            return
        self.refresh()
