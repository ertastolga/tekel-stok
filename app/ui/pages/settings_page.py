"""Ayarlar: az sayıda, sade Türkçeyle anlatılmış tercih.

Teknik terim yoktur. Her ayarın altında ne işe yaradığı bir cümleyle yazar.
Yedekleme de buradadır çünkü kullanıcının aradığı yer burasıdır.
"""
from __future__ import annotations

import datetime
import logging

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.clock import shift_days
from app.core.errors import DomainError
from app.core.tr import fmt_datetime
from app.ui import metrics, sound, theme
from app.ui.dialogs.common_dialogs import ask_confirm, scanning_suspended, show_error, show_info
from app.ui.pages.base import Page
from app.ui.widgets.common import PageHeader, make_label

log = logging.getLogger(__name__)


class SettingsPage(Page):
    nav_title = "⚙️  Ayarlar"
    nav_key = "ayarlar"
    nav_group = "yonetim"

    def __init__(self, services, main_window) -> None:
        super().__init__(services, main_window)

        self.header = PageHeader("⚙️ Ayarlar", "Uygulamanın çalışma tercihleri.")
        self.root.addWidget(self.header)

        kaydirma = QScrollArea()
        kaydirma.setWidgetResizable(True)
        icerik = QWidget()
        duzen = QVBoxLayout(icerik)
        duzen.setContentsMargins(
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
            metrics.PAGE_MARGIN_H, metrics.PAGE_MARGIN_V,
        )
        duzen.setSpacing(metrics.PAGE_SPACING)

        duzen.addWidget(self._build_mode_group())
        duzen.addWidget(self._build_sales_group())
        duzen.addWidget(self._build_stock_group())
        duzen.addWidget(self._build_day_group())
        duzen.addWidget(self._build_backup_group())
        duzen.addStretch(1)

        kaydirma.setWidget(icerik)
        self.root.addWidget(kaydirma, 1)

    # ===================== Gruplar =======================================
    def _build_mode_group(self) -> QWidget:
        kutu = QGroupBox("Çalışma Kipi")
        duzen = QVBoxLayout(kutu)
        duzen.setSpacing(10)

        satir = QHBoxLayout()
        satir.addWidget(make_label("Uygulama nasıl çalışsın"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Satış Önceliği (dokunmatik kasa)", "SALES_FIRST")
        self.mode_combo.addItem("Stok Takibi (ayrıntılı envanter)", "INVENTORY_TRACKED")
        self.mode_combo.currentIndexChanged.connect(self._save_mode)
        satir.addWidget(self.mode_combo)
        satir.addStretch(1)
        duzen.addLayout(satir)

        duzen.addWidget(self._hint(
            "Satış Önceliği: uygulama doğrudan satış ekranına açılır. Stok "
            "bilgisi eksik ya da eksi olsa bile satış hiç durmaz ve kasada "
            "stok uyarısı çıkmaz. Stok ekranları Yönetim altında aynen durur."
        ))
        duzen.addWidget(self._hint(
            "Stok Takibi: uygulama ana ekrana açılır, satış sonrası stok "
            "uyarıları ve panelde kâr/stok bilgileri gösterilir."
        ))
        duzen.addWidget(self._hint(
            "Bu ayar yalnızca ekranları ve uyarıları değiştirir. "
            "Stok hareketleri, maliyetler ve geçmiş kayıtlar HER İKİ kipte de "
            "aynı şekilde tutulur."
        ))
        return kutu

    def _build_sales_group(self) -> QWidget:
        kutu = QGroupBox("Satış")
        duzen = QVBoxLayout(kutu)
        duzen.setSpacing(10)

        satir = QHBoxLayout()
        satir.addWidget(make_label("Stok Takibi kipinde gelen satış ekranı"))
        self.sale_mode_combo = QComboBox()
        self.sale_mode_combo.addItem("⚡ Hızlı Satış", "HIZLI")
        self.sale_mode_combo.addItem("🛒 Sepetli Satış", "SEPET")
        self.sale_mode_combo.currentIndexChanged.connect(self._save_sales)
        satir.addWidget(self.sale_mode_combo)
        satir.addStretch(1)
        duzen.addLayout(satir)

        self.pack_check = QCheckBox(
            "Koli barkodu okutulduğunda satıştan önce sor"
        )
        self.pack_check.stateChanged.connect(self._save_sales)
        duzen.addWidget(self.pack_check)
        duzen.addWidget(self._hint(
            "Kapatırsanız 1 koli okutmak doğrudan kolideki adet kadar satar. "
            "Yanlışlıkla okutmaya karşı açık kalması önerilir."
        ))

        self.group_check = QCheckBox(
            "Hızlı satışları olası müşteri gruplarına ayır"
        )
        self.group_check.stateChanged.connect(self._save_sales)
        duzen.addWidget(self.group_check)
        duzen.addWidget(self._hint(
            "Arka arkaya yapılan satışlar aynı müşteriye ait SAYILABİLİR. "
            "Bu bir tahmindir; kesin sepet bilgisi yalnızca Sepetli Satıştan gelir."
        ))

        self.sound_check = QCheckBox("Okutma seslerini çal")
        self.sound_check.stateChanged.connect(self._save_sales)
        duzen.addWidget(self.sound_check)

        satir2 = QHBoxLayout()
        satir2.addWidget(make_label("Aynı barkodun iki kez okunmasını engelle"))
        self.dup_spin = QSpinBox()
        self.dup_spin.setRange(0, 1000)
        self.dup_spin.setSingleStep(10)
        self.dup_spin.setSuffix(" ms")
        self.dup_spin.setProperty("scannerExempt", True)
        self.dup_spin.valueChanged.connect(self._save_sales)
        satir2.addWidget(self.dup_spin)
        satir2.addStretch(1)
        duzen.addLayout(satir2)
        duzen.addWidget(self._hint(
            "Bazı okuyucular tek okutmada barkodu iki kez gönderir. Bu süre "
            "içindeki ikinci okuma sayılmaz. Aynı ürünü arka arkaya satmanızı "
            "engellemeyecek kadar kısa tutulmalıdır (önerilen: 120 ms)."
        ))
        return kutu

    def _build_stock_group(self) -> QWidget:
        kutu = QGroupBox("Stok")
        duzen = QVBoxLayout(kutu)
        duzen.setSpacing(10)

        for etiket, alan, ipucu in (
            ("Yeni üründe az stok sınırı", "min", None),
            ("Yeni üründe kritik stok sınırı", "critical", None),
            ("Kaç gündür satılmayan ürün 'yavaş' sayılsın", "slow", None),
            ("Bu adetten büyük sayım farkında uyar", "diff",
             "Küçük farklar için soru sorulmaz; onay yorgunluğu yaratır."),
        ):
            satir = QHBoxLayout()
            satir.addWidget(make_label(etiket))
            kutucuk = QSpinBox()
            kutucuk.setRange(0, 100000)
            kutucuk.setProperty("scannerExempt", True)
            kutucuk.valueChanged.connect(self._save_stock)
            satir.addWidget(kutucuk)
            satir.addStretch(1)
            duzen.addLayout(satir)
            setattr(self, f"{alan}_spin", kutucuk)
            if ipucu:
                duzen.addWidget(self._hint(ipucu))
        duzen.addWidget(self._hint(
            "Bu sınırlar YENİ tanımlanan ürünler için varsayılandır; "
            "mevcut ürünlerin sınırları ürün ekranından değiştirilir."
        ))
        return kutu

    def _build_day_group(self) -> QWidget:
        kutu = QGroupBox("Gün Başlangıcı")
        duzen = QVBoxLayout(kutu)
        duzen.setSpacing(10)

        satir = QHBoxLayout()
        satir.addWidget(make_label("Yeni gün saat kaçta başlasın"))
        self.day_spin = QSpinBox()
        self.day_spin.setRange(0, 23)
        self.day_spin.setSuffix(":00")
        self.day_spin.setProperty("scannerExempt", True)
        satir.addWidget(self.day_spin)
        self.day_button = QPushButton("Uygula")
        self.day_button.clicked.connect(self._save_business_day)
        satir.addWidget(self.day_button)
        satir.addStretch(1)
        duzen.addLayout(satir)
        duzen.addWidget(self._hint(
            "Gece geç saate kadar açıksanız 04:00 seçebilirsiniz: gece yarısından "
            "sonraki satışlar bir önceki güne yazılır.\n"
            "Bu değişiklik YARINDAN itibaren geçerli olur ve GEÇMİŞ RAPORLARI "
            "DEĞİŞTİRMEZ."
        ))
        return kutu

    def _build_backup_group(self) -> QWidget:
        kutu = QGroupBox("Yedekleme")
        duzen = QVBoxLayout(kutu)
        duzen.setSpacing(10)

        self.backup_status = make_label("", "cardHint", wrap=True)
        duzen.addWidget(self.backup_status)

        satir = QHBoxLayout()
        satir.addWidget(make_label("Kaç dakikada bir otomatik yedek"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(5, 1440)
        self.interval_spin.setSuffix(" dakika")
        self.interval_spin.setProperty("scannerExempt", True)
        self.interval_spin.valueChanged.connect(self._save_backup)
        satir.addWidget(self.interval_spin)

        satir.addWidget(make_label("Kaç otomatik yedek saklansın"))
        self.retention_spin = QSpinBox()
        self.retention_spin.setRange(1, 100)
        self.retention_spin.setProperty("scannerExempt", True)
        self.retention_spin.valueChanged.connect(self._save_backup)
        satir.addWidget(self.retention_spin)
        satir.addStretch(1)
        duzen.addLayout(satir)
        duzen.addWidget(self._hint(
            "Elle aldığınız yedekler bu sayıdan etkilenmez; asla kendiliğinden silinmez."
        ))

        dugmeler = QHBoxLayout()
        self.backup_now_button = QPushButton("Şimdi Yedek Al")
        self.backup_now_button.setObjectName("primary")
        self.backup_now_button.clicked.connect(self._backup_now)
        dugmeler.addWidget(self.backup_now_button)

        self.restore_button = QPushButton("Yedekten Geri Yükle")
        self.restore_button.clicked.connect(self._restore)
        dugmeler.addWidget(self.restore_button)

        self.folder_button = QPushButton("Yedek Klasörünü Seç")
        self.folder_button.clicked.connect(self._choose_folder)
        dugmeler.addWidget(self.folder_button)
        dugmeler.addStretch(1)
        duzen.addLayout(dugmeler)

        duzen.addWidget(make_label("Mevcut yedekler", "sectionTitle"))
        self.backup_list = QListWidget()
        self.backup_list.setMaximumHeight(200)
        duzen.addWidget(self.backup_list)
        return kutu

    def _hint(self, text: str) -> QLabel:
        etiket = QLabel(text)
        etiket.setWordWrap(True)
        etiket.setStyleSheet(f"color: {theme.TEXT_MUTED};")
        return etiket

    # ===================== Yükleme / kaydetme ============================
    def refresh(self) -> None:
        ayarlar = self.services.settings
        self._loading = True
        try:
            index = self.mode_combo.findData(ayarlar.operating_mode())
            if index >= 0:
                self.mode_combo.setCurrentIndex(index)

            index = self.sale_mode_combo.findData(ayarlar.default_sale_mode())
            if index >= 0:
                self.sale_mode_combo.setCurrentIndex(index)
            self.pack_check.setChecked(ayarlar.pack_confirm_in_sale())
            self.group_check.setChecked(ayarlar.smart_grouping_enabled())
            self.sound_check.setChecked(ayarlar.sound_enabled())
            self.dup_spin.setValue(ayarlar.duplicate_scan_ms())

            az, kritik = ayarlar.default_thresholds()
            self.min_spin.setValue(az)
            self.critical_spin.setValue(kritik)
            self.slow_spin.setValue(ayarlar.slow_moving_days())
            self.diff_spin.setValue(ayarlar.large_count_diff_threshold())

            self.day_spin.setValue(ayarlar.current_business_day_start_hour())
            self.interval_spin.setValue(ayarlar.auto_backup_interval_minutes())
            self.retention_spin.setValue(ayarlar.auto_backup_retention())
            self._fill_backups()
        finally:
            self._loading = False

    def _save_mode(self) -> None:
        if getattr(self, "_loading", False):
            return
        self.services.settings.set("operating_mode", self.mode_combo.currentData())
        self.main_window.apply_settings()
        with scanning_suspended(self.main_window.router):
            show_info(
                self, "Çalışma kipi",
                "Kip değiştirildi. Ekranların tamamen güncellenmesi için "
                "uygulamayı kapatıp açabilirsiniz.",
            )

    def _save_sales(self) -> None:
        if getattr(self, "_loading", False):
            return
        self.services.settings.set_many({
            "default_sale_mode": self.sale_mode_combo.currentData(),
            "pack_confirm_in_sale": int(self.pack_check.isChecked()),
            "smart_grouping_enabled": int(self.group_check.isChecked()),
            "sound_enabled": int(self.sound_check.isChecked()),
            "duplicate_scan_ms": self.dup_spin.value(),
        })
        self.main_window.apply_settings()

    def _save_stock(self) -> None:
        if getattr(self, "_loading", False):
            return
        self.services.settings.set_many({
            "default_min_stock": self.min_spin.value(),
            "default_critical_stock": self.critical_spin.value(),
            "slow_moving_days": self.slow_spin.value(),
            "large_count_diff_threshold": self.diff_spin.value(),
        })

    def _save_business_day(self) -> None:
        """Kural GEÇERLİLİK TARİHLİDİR; geçmiş raporlar değişmez."""
        yarin = shift_days(self.services.settings.calendar().today(), 1)
        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self,
                f"Yeni gün {self.day_spin.value():02d}:00'da başlasın mı?",
                f"Bu kural {yarin} tarihinden itibaren geçerli olur.\n"
                "Geçmiş günlerin raporları DEĞİŞMEZ.",
                accept_text="Evet, uygula",
            )
        if not onay:
            return
        self.services.settings.set_business_day_start_hour(self.day_spin.value(), yarin)
        with scanning_suspended(self.main_window.router):
            show_info(self, "Gün başlangıcı", f"{yarin} tarihinden itibaren geçerli.")

    def _save_backup(self) -> None:
        if getattr(self, "_loading", False):
            return
        self.services.settings.set_many({
            "auto_backup_interval_minutes": self.interval_spin.value(),
            "auto_backup_retention": self.retention_spin.value(),
        })

    # ===================== Yedekleme =====================================
    def _fill_backups(self) -> None:
        self.backup_list.clear()
        try:
            durum = self.services.backup.status()
            yedekler = self.services.backup.list_backups()
        except Exception:
            log.exception("Yedekler listelenemedi")
            return

        son = durum["son_yedek_utc"]
        self.backup_status.setText(
            (f"Son yedek: {fmt_datetime(datetime.datetime.fromtimestamp(son))}"
             if son else "Henüz yedek alınmadı.")
            + f"\nOtomatik: {durum['otomatik_klasor']}"
            + f"\nElle: {durum['elle_klasor']}"
        )
        for yedek in yedekler[:50]:
            boyut = yedek.size_bytes / 1024 / 1024
            oge = QListWidgetItem(f"{yedek.display_name}  ·  {boyut:.1f} MB")
            oge.setData(32, str(yedek.path))
            self.backup_list.addItem(oge)

    def _backup_now(self) -> None:
        try:
            yol = self.services.backup.create_manual()
        except DomainError as hata:
            show_error(self, hata.message, hata.detail)
            return
        sound.success()
        with scanning_suspended(self.main_window.router):
            show_info(self, "Yedek alındı", f"Yedek kaydedildi:\n{yol}")
        self._fill_backups()

    def _restore(self) -> None:
        oge = self.backup_list.currentItem()
        yol = oge.data(32) if oge is not None else None
        if yol is None:
            with scanning_suspended(self.main_window.router):
                yol, _ = QFileDialog.getOpenFileName(
                    self, "Yedek seçin",
                    str(self.services.backup.manual_dir()),
                    "Yedek dosyaları (*.db)",
                )
            if not yol:
                return

        try:
            bilgi = self.services.backup.inspect(yol)
        except DomainError as hata:
            show_error(self, hata.message, hata.detail)
            return

        with scanning_suspended(self.main_window.router):
            onay = ask_confirm(
                self, "Bu yedek geri yüklensin mi?",
                f"{bilgi.display_name}\n"
                f"{bilgi.product_count} ürün · {bilgi.sale_count} satış\n\n"
                "Şu anki veriler bu yedekle DEĞİŞTİRİLİR. İşlemden önce mevcut "
                "verilerin bir güvenlik kopyası otomatik alınır.",
                accept_text="Evet, geri yükle", danger=True,
            )
        if not onay:
            return

        try:
            guvenlik = self.services.backup.restore(yol)
        except DomainError as hata:
            show_error(self, hata.message, hata.detail)
            return

        with scanning_suspended(self.main_window.router):
            show_info(
                self, "Geri yüklendi",
                "Yedek geri yüklendi.\n\n"
                f"Önceki verilerinizin kopyası:\n{guvenlik}\n\n"
                "Uygulama şimdi yeniden başlatılacak.",
            )
        self.main_window.request_restart()

    def _choose_folder(self) -> None:
        with scanning_suspended(self.main_window.router):
            klasor = QFileDialog.getExistingDirectory(
                self, "Yedek klasörü seçin", str(self.services.backup.manual_dir())
            )
        if not klasor:
            return
        self.services.settings.set("manual_backup_dir", klasor)
        self._fill_backups()
