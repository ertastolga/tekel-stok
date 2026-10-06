"""Ana ekran: uygulamanın yüzü.

Dükkân sahibi burada beş şey görür ve hepsini tek bakışta anlar. En sık
kullanılan iş (Hızlı Satış) görsel olarak BASKINDIR.

Bu ekran bilerek SADEDİR: analiz, uyarı yığını ve teknik terim yoktur.
"""
from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QScrollArea, QVBoxLayout, QWidget

from app.core.money import format_tl
from app.ui import metrics
from app.ui.pages.base import Page
from app.ui.widgets.common import ActionCard, PageHeader, make_label


class HomePage(Page):
    nav_title = "🏠  Ana Ekran"
    nav_key = "ana_ekran"
    nav_group = ""            # menüde ayrıca en üstte gösterilir

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)

        self.header = PageHeader("Hoş geldiniz", "")
        self.root.addWidget(self.header)

        # Kaydirma alani: %125/%150 olceklemede ya da kucuk ekranda alt satir
        # KIRPILMASIN. Yasli kullanici icin gorunmeyen dugme, olmayan dugmedir.
        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        govde = QWidget()
        duzen = QVBoxLayout(govde)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
        )
        duzen.setSpacing(metrics.PAGE_SPACING)

        # --- Günlük işlemler ---
        duzen.addWidget(make_label("Günlük İşlemler", "sectionTitle"))
        gunluk = QGridLayout()
        gunluk.setSpacing(metrics.PAGE_SPACING)

        self.quick_card = ActionCard(
            "⚡", "Hızlı Satış",
            "Barkodu okutun, ürün hemen satılsın. (F1)",
            primary=True,
        )
        self.quick_card.clicked.connect(lambda: self.main_window.go_to("hizli_satis"))
        gunluk.addWidget(self.quick_card, 0, 0, 2, 1)

        self.cart_card = ActionCard(
            "🛒", "Sepetli Satış", "Önce sepete ekleyin, sonra tamamlayın. (F2)"
        )
        self.cart_card.clicked.connect(lambda: self.main_window.go_to("sepetli_satis"))
        gunluk.addWidget(self.cart_card, 0, 1)

        self.entry_card = ActionCard(
            "📦", "Stok Girişi", "Gelen malı okutup stoğa ekleyin. (F3)"
        )
        self.entry_card.clicked.connect(lambda: self.main_window.go_to("stok_girisi"))
        gunluk.addWidget(self.entry_card, 0, 2)

        self.count_card = ActionCard(
            "📋", "Stok Sayımı", "Raf raf sayın, farkı düzeltin. (F9)"
        )
        self.count_card.clicked.connect(lambda: self.main_window.go_to("stok_sayimi"))
        gunluk.addWidget(self.count_card, 1, 1)

        self.today_card = ActionCard(
            "📊", "Bugün", "Günün cirosu ve dikkat edilecekler. (F7)"
        )
        self.today_card.clicked.connect(lambda: self.main_window.go_to("panel"))
        gunluk.addWidget(self.today_card, 1, 2)

        gunluk.setColumnStretch(0, 3)
        gunluk.setColumnStretch(1, 2)
        gunluk.setColumnStretch(2, 2)
        duzen.addLayout(gunluk, 3)

        # --- Yönetim ---
        duzen.addWidget(make_label("Yönetim", "sectionTitle"))
        yonetim = QGridLayout()
        yonetim.setSpacing(10)
        for sutun, (ikon, baslik, anahtar) in enumerate(
            (
                ("🏷️", "Ürünler", "urunler"),
                ("📈", "Stok Durumu", "stok_durumu"),
                ("🚚", "Tedarikçiler", "tedarikciler"),
                ("🕘", "Geçmiş", "gecmis"),
                ("⚙️", "Ayarlar", "ayarlar"),
            )
        ):
            kart = ActionCard(ikon, baslik)
            kart.setMinimumHeight(0)
            kart.setMaximumHeight(90)
            kart.clicked.connect(lambda _=False, k=anahtar: self.main_window.go_to(k))
            yonetim.addWidget(kart, 0, sutun)
        duzen.addLayout(yonetim, 1)

        kaydirma.setWidget(govde)
        self.root.addWidget(kaydirma, 1)

    def refresh(self) -> None:
        """Başlıkta günün özeti; ekranın geri kalanı sabit ve sakin kalır."""
        try:
            ozet = self.services.analytics.today()
            dikkat = self.services.products.attention_counts()
        except Exception:
            self.header.set_subtitle("")
            return

        parcalar = [f"Bugün {format_tl(ozet.revenue)} ciro, {ozet.item_count} ürün"]
        # SALES_FIRST: stok uyarilari gunluk satis akisinda gosterilmez;
        # Yonetim > Stok Durumu ekraninda aynen durur.
        if self.services.settings.is_sales_first():
            self.header.set_subtitle(" · ".join(parcalar))
            self.main_window.refresh_today()
            return
        if dikkat.get("kritik"):
            parcalar.append(f"{dikkat['kritik']} üründe kritik stok")
        if dikkat.get("kontrol_gerekli"):
            parcalar.append(f"{dikkat['kontrol_gerekli']} üründe stok kontrolü gerekli")
        self.header.set_subtitle(" · ".join(parcalar))
        self.main_window.refresh_today()
