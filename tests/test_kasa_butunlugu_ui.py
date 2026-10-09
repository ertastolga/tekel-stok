"""Kasa bütünlüğü arayüzü (V1.2 M1d): D-01, D-02, D-03, D-14.

Korunan sözler:
  * fiyatı değişen sepette ödeme ALINMAZ; satır işaretlenir, ödeme düğmeleri
    kapanır, "Güncel fiyatları uygula" açıkça dokunulunca ekran / ödeme /
    kayıt aynı tutarı taşır,
  * ödeme onayından sonra satış yazılamazsa (iş kuralı hatası dahil) kritik
    iz bırakılır ve kullanıcı açıkça uyarılır,
  * sepet her değişiklikte (gecikmeli) ve kapanışta diske yazılır; boşalan
    sepet hayalet taslak bırakmaz; geri yükleme sonrası yeniden başlatmada
    eski sepet yazılmaz,
  * Ayarlar ekranı çalışma kipini ve varsayılan satış kipini DOĞRU gösterir
    ve bir seçeneği değiştirmek diğer ayarları ezmez,
  * modal iletiler açıkken okutma askıdadır.
"""
from __future__ import annotations

import logging
import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from app.core.errors import FiyatDegisti, IslemTamamlanamadi  # noqa: E402
from app.core.models import PaymentMethod  # noqa: E402
from app.core.tr import tr_lower  # noqa: E402
from app.payments.base import PaymentResult  # noqa: E402
from app.scanner.scan_event import ScanEvent  # noqa: E402
from app.ui import metrics  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

BIRA = "8690504001492"

from ui_support import *  # noqa: E402,F401,F403


class KaydedenOdeme:
    """Onaylanan tutarları kaydeden sahte ödeme adaptörü."""

    name = "kaydeden"
    supports_void = False

    def __init__(self) -> None:
        self.tutarlar: list[int] = []

    def authorize(self, request) -> PaymentResult:
        self.tutarlar.append(request.amount)
        return PaymentResult(approved=True, method=request.method, amount=request.amount)

    def void(self, reference):  # pragma: no cover
        raise RuntimeError("yok")


@pytest.fixture
def odeme(services):
    adaptor = KaydedenOdeme()
    services.payments.register(PaymentMethod.CASH, adaptor)
    services.payments.register(PaymentMethod.CARD, adaptor)
    return adaptor


# ===================== D-02: fiyat kayması =================================
def test_fiyat_degisince_odeme_ALINMAZ_satir_isaretlenir(
    sayfa, qapp, services, bira, odeme
):
    for _ in range(2):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    services.products.set_price(bira, 8500)        # örn. Ürünler ekranından

    assert sayfa.complete(PaymentMethod.CASH) is False
    qapp.processEvents()

    assert odeme.tutarlar == [], "ödeme cihazına HİÇ gidilmedi"
    assert services.db.scalar("SELECT COUNT(*) FROM sales") == 0
    satir = sayfa._rows[bira]
    assert satir.issue_text == "Fiyat değişti: 80 TL → 85 TL"
    assert "fiyat değişti" in tr_lower(satir.price_label.text())
    assert not sayfa.cash_button.isEnabled() and not sayfa.card_button.isEnabled()
    assert sayfa.apply_prices_button.isVisibleTo(sayfa)
    assert "ödeme alınmadı" in tr_lower(sayfa.banner.headline.text())


def test_guncel_fiyat_uygulaninca_gorunen_odenen_kaydedilen_ayni(
    sayfa, qapp, services, bira, odeme
):
    for _ in range(2):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    services.products.set_price(bira, 8500)
    sayfa.refresh()                                  # canlı doğrulama

    assert sayfa.apply_prices_button.isVisibleTo(sayfa)
    # M12d: üç düğme dar ekranda sığmıyordu; onay düğmesi ödemenin YERİNİ alır.
    assert not sayfa.cash_button.isVisibleTo(sayfa)
    assert not sayfa.card_button.isVisibleTo(sayfa)
    # Ödemenin yerini alan düğme ödeme düğmeleri kadar büyük (dokunma hedefi).
    assert sayfa.apply_prices_button.minimumSizeHint().height() >= metrics.TOUCH_TARGET_MIN
    assert (sayfa.apply_prices_button.minimumSizeHint().height()
            >= sayfa.cash_button.minimumSizeHint().height())
    sayfa.apply_prices_button.click()
    qapp.processEvents()

    assert sayfa.total_label.text() == "170 TL"
    assert sayfa._rows[bira].issue_text is None
    assert not sayfa.apply_prices_button.isVisibleTo(sayfa)
    assert sayfa.cash_button.isVisibleTo(sayfa) and sayfa.card_button.isVisibleTo(sayfa)
    assert sayfa.cash_button.isEnabled()

    sayfa.cash_button.click()
    qapp.processEvents()
    assert odeme.tutarlar == [17000], "ödenen = ekranda görünen"
    assert services.sales.last_sale()["total_amount"] == 17000, "kaydedilen = ödenen"


def test_isaretli_satir_cikarilinca_odeme_acilir(sayfa, qapp, services, bira, cips_urunu):
    sayfa.handle_scan(ScanEvent(code=BIRA))
    sayfa._add_product(cips_urunu, 1, None, 1)
    services.products.set_active(bira, False)
    sayfa.refresh()
    assert not sayfa.cash_button.isEnabled()
    assert not sayfa.apply_prices_button.isVisibleTo(sayfa), "pasif ürün fiyatla düzelmez"

    sayfa._on_remove_requested(bira)
    qapp.processEvents()
    assert sayfa.cash_button.isEnabled()
    assert sayfa.complete(PaymentMethod.CASH) is True
    assert services.sales.last_sale()["total_amount"] == 5000


def test_onaydan_sonra_is_kurali_hatasi_kritik_yoldan_gider(
    sayfa, qapp, services, bira, odeme, monkeypatch, caplog
):
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()

    def yarista_degisti(*a, **k):
        raise FiyatDegisti()

    monkeypatch.setattr(services.cart, "checkout", yarista_degisti)
    with caplog.at_level(logging.CRITICAL):
        assert sayfa.complete(PaymentMethod.CARD) is False
    qapp.processEvents()

    assert odeme.tutarlar == [8000]
    assert any(
        "Ödeme onaylandı ama satış yazılamadı" in r.getMessage()
        for r in caplog.records if r.levelno == logging.CRITICAL
    )
    assert "ödeme alındıysa" in tr_lower(sayfa.banner.detail.text())
    assert sayfa.cart.item_count == 1, "sepet olduğu gibi duruyor"


def test_odenen_tutar_her_zaman_kaydedilen_tutardir(sayfa, qapp, services, bira, odeme):
    """V1.1'de 2×80 TL sepet, fiyat 85'e çıkınca 160 TL ONAYLATIP 170 TL yazıyordu."""
    for _ in range(2):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    services.products.set_price(bira, 8500)

    sayfa.cash_button.click()
    qapp.processEvents()

    satis = services.sales.last_sale()
    kaydedilen = satis["total_amount"] if satis else 0
    assert sum(odeme.tutarlar) == kaydedilen, (odeme.tutarlar, kaydedilen)


def test_basarili_satista_complete_true_doner(sayfa, qapp, services, bira):
    sayfa.handle_scan(ScanEvent(code=BIRA))
    assert sayfa.complete() is True
    assert sayfa.complete() is False, "boş sepet"


# ===================== D-03: sepet taslağı =================================
def _acik_taslaklar(services):
    return services.cart.open_drafts()


def test_sepet_degisince_gecikmeli_diske_yazilir(sayfa, qapp, services, bira):
    sayfa.handle_scan(ScanEvent(code=BIRA))
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    assert sayfa._autosave_timer.isActive(), "kayıt zamanlandı (her okutmada DEĞİL)"
    assert _acik_taslaklar(services) == []

    sayfa._autosave_timer.timeout.emit()
    taslaklar = _acik_taslaklar(services)
    assert len(taslaklar) == 1
    assert services.db.scalar(
        "SELECT quantity FROM cart_draft_lines WHERE draft_id = ?", (taslaklar[0]["id"],)
    ) == 2


def test_kapanista_bekleyen_sepet_yazilir_ve_acilista_sorulur(
    qapp, services, bira, onay
):
    services.inventory.set_initial_stock(bira, 48, unit_cost=5000)
    win = MainWindow(services)
    win.show()
    win.go_to("sepetli_satis")
    sayfa = win.pages["sepetli_satis"]
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    assert _acik_taslaklar(services) == [], "henüz zamanlayıcı dolmadı"
    close_window(win, qapp)                         # elektrik değil, düzgün kapanış

    assert len(_acik_taslaklar(services)) == 1, "kapanışta yazıldı"

    onay.cevap = True
    yeni = MainWindow(services)
    try:
        yeni.show()
        yeni.go_to("sepetli_satis")
        qapp.processEvents()
        assert any("Tamamlanmamış bir sepet" in s for s in onay.sorular)
        assert yeni.pages["sepetli_satis"].cart.item_count == 1
    finally:
        close_window(yeni, qapp)


def test_acilista_kurtarma_sorusu_ana_pencere_gorununce_sorulur(
    qapp, services, bira, onay, monkeypatch
):
    """M12d (verify_build kuru çalıştırması): açık sepet varken soru pencere
    KURULURKEN, ana pencere görünmeden soruluyordu. Sahipsiz, görev çubuğunda
    düğmesi olmayan bir kutu dükkân sahibine "uygulama açılmadı" gibi görünür
    ve kutu başka pencerelerin arkasında kalabilir."""
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira, quantity=2)
    services.cart.autosave(sepet)
    assert len(_acik_taslaklar(services)) == 1

    gorunur_mu = []
    kayitli_exec = QMessageBox.exec

    def exec_(kutu):
        gorunur_mu.append(kutu.parentWidget().window().isVisible())
        return kayitli_exec(kutu)

    monkeypatch.setattr(QMessageBox, "exec", exec_)

    onay.cevap = True
    win = MainWindow(services)                      # açılış sayfası: Sepetli Satış
    try:
        assert win._current_key == "sepetli_satis"
        assert onay.sorular == [], "pencere görünmeden soru sorulmamalı"
        win.show()
        qapp.processEvents()
        assert [s for s in onay.sorular if "Tamamlanmamış bir sepet" in s] == [
            "Tamamlanmamış bir sepet bulundu."
        ], "pencere görününce bir kez sorulur"
        assert gorunur_mu == [True]
        assert win.pages["sepetli_satis"].cart.item_count == 2
        win.go_to("urunler")
        win.go_to("sepetli_satis")
        qapp.processEvents()
        assert len(onay.sorular) == 1, "kurtarılan sepet yeniden sorulmaz"
    finally:
        close_window(win, qapp)


def test_acilista_kurtarma_beklerken_baska_sayfaya_gecilirse_sorulmaz(
    qapp, services, bira, onay
):
    sepet = services.cart.new_cart()
    services.cart.add_product(sepet, bira)
    services.cart.autosave(sepet)
    win = MainWindow(services)
    try:
        win.go_to("urunler")                        # görünmeden önce sayfa değişti
        win.show()
        qapp.processEvents()
        assert onay.sorular == [], "soru yalnızca kasa ekranındayken sorulur"
        assert len(_acik_taslaklar(services)) == 1, "taslak kaybolmaz"
        win.go_to("sepetli_satis")
        qapp.processEvents()
        assert any("Tamamlanmamış bir sepet" in s for s in onay.sorular)
    finally:
        close_window(win, qapp)


def test_eksiyle_bosaltilan_sepet_hayalet_taslak_birakmaz(sayfa, qapp, services, bira):
    sayfa.handle_scan(ScanEvent(code=BIRA))
    sayfa._autosave_timer.timeout.emit()
    assert len(_acik_taslaklar(services)) == 1

    sayfa._on_quantity_changed(bira, 0)             # "−" 1'deyken
    sayfa._autosave_timer.timeout.emit()
    assert _acik_taslaklar(services) == []


def test_sayfalar_arasi_gezinmede_bosaltilan_sepet_hayalet_birakmaz(
    window, qapp, services, bira
):
    """V1.1: ekrandan çıkarken dolu sepet yazılıyor, boşaltılınca SİLİNMİYORDU."""
    window.go_to("sepetli_satis")
    sayfa = window.pages["sepetli_satis"]
    sayfa.handle_scan(ScanEvent(code=BIRA))
    window.go_to("urunler")                         # taslak yazılır
    assert len(_acik_taslaklar(services)) == 1
    window.go_to("sepetli_satis")
    sayfa._on_quantity_changed(bira, 0)
    window.go_to("urunler")
    assert _acik_taslaklar(services) == [], "boş sepetin taslağı kalmadı"


def test_yeniden_baslatmada_eski_sepet_yazilmaz(window, qapp, services, bira):
    window.go_to("sepetli_satis")
    sayfa = window.pages["sepetli_satis"]
    sayfa.handle_scan(ScanEvent(code=BIRA))
    window.request_restart()                        # geri yükleme sonrası
    sayfa._autosave_now()
    window.close()
    assert _acik_taslaklar(services) == []


def test_satis_sonrasi_bekleyen_kayit_taslak_birakmaz(sayfa, qapp, services, bira):
    sayfa.handle_scan(ScanEvent(code=BIRA))
    assert sayfa._autosave_timer.isActive()
    assert sayfa.complete() is True
    sayfa._autosave_timer.timeout.emit()
    assert _acik_taslaklar(services) == []


# ===================== D-01: Ayarlar kip kutuları ==========================
def test_ayarlar_kip_kutularini_dogru_gosterir_ve_ezmez(window, qapp, services):
    services.settings.set_many(
        {"operating_mode": "SALES_FIRST", "default_sale_mode": "SEPET"}
    )
    window.go_to("ayarlar")
    qapp.processEvents()
    sayfa = window.pages["ayarlar"]

    assert sayfa.mode_combo.currentData() == "SALES_FIRST"
    assert sayfa.sale_mode_combo.currentData() == "SEPET"

    sayfa.pack_check.setChecked(not sayfa.pack_check.isChecked())
    qapp.processEvents()
    assert services.settings.get("default_sale_mode") == "SEPET", "ezilmedi"
    assert services.settings.get("operating_mode") == "SALES_FIRST"


# ===================== D-14 ================================================
def test_modal_ileti_acikken_okutma_askidadir(window, qapp, monkeypatch):
    from app.ui.dialogs.common_dialogs import ask_confirm, show_error, show_info

    gorulen = []

    def exec_(kutu):
        gorulen.append(window.router.is_suspended)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    sayfa = window.pages["stok_girisi"]
    show_error(sayfa, "hata")
    show_info(sayfa, "bilgi", "ileti")
    ask_confirm(sayfa, "emin misiniz?")
    assert gorulen == [True, True, True]
    assert not window.router.is_suspended


def test_durum_iletisi_pencereye_bagli_tek_zamanlayici_kullanir(window, qapp):
    window.show_status("birinci", 4)
    zamanlayici = window._status_timer
    window.show_status("ikinci", 4)
    assert window._status_timer is zamanlayici, "zamanlayıcı birikmez"
    assert zamanlayici.parent() is window
    zamanlayici.timeout.emit()
    assert window.status_label.text() == ""


def test_hizli_satis_reddi_ayrintiyi_loga_yazar(window, qapp, services, bira, monkeypatch, caplog):
    window.go_to("hizli_satis")
    sayfa = window.pages["hizli_satis"]

    def reddet(*a, **k):
        raise IslemTamamlanamadi(detail="kilit: veritabani mesgul")

    monkeypatch.setattr(services.sales, "quick_sale", reddet)
    with caplog.at_level(logging.WARNING):
        sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    assert any("kilit: veritabani mesgul" in r.getMessage() for r in caplog.records)
    assert "kilit" not in sayfa.banner.detail.text(), "teknik ayrıntı gösterilmez"


def test_fiyat_onayindan_sonra_kart_ayari_korunur(sayfa, qapp, services, bira):
    """KART gizliyse fiyat onayından sonra da gizli kalır; NAKİT geri gelir."""
    services.settings.set("show_card_button", 0)
    sayfa.apply_settings()
    sayfa.handle_scan(ScanEvent(code=BIRA))
    qapp.processEvents()
    services.products.set_price(bira, 8500)
    sayfa.refresh()
    assert sayfa.apply_prices_button.isVisibleTo(sayfa)
    assert not sayfa.cash_button.isVisibleTo(sayfa)
    sayfa.apply_prices_button.click()
    qapp.processEvents()
    assert sayfa.cash_button.isVisibleTo(sayfa)
    assert not sayfa.card_button.isVisibleTo(sayfa), "KART ayarı korunur"
